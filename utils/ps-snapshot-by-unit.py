#!/usr/bin/env python3
"""ps-snapshot-by-unit.py

Build OUTPUT_BRANCH on --base that reaches --tip's tree through a *monotone*
history: every path in the net --base..--tip diff is written exactly once,
with its final content, by the logical unit that owns it.

This is the contract `linear-8.0.11` satisfies and that a delta-replaying
flatten (ps-flatten-first-parent.py) deliberately does not:

  * per-path source of truth -- a modified path gets the canonical final
    content from the unit that owns it, never an intermediate state and never
    a merge heuristic's guess;
  * untouched-path invariant -- a unit changes only the paths it owns;
  * no hidden catch-up -- no large "restore the input tree" commit at the end;
  * monotone non-drift -- summed per-commit diffstat equals the net diff, so a
    path is never written and then rewritten.

Logical units come from the same recursive first-parent walk a flatten uses:
walk --base..--tip on the first-parent chain; a non-merge node is one unit; a
merge node recurses into its second-parent train (when the train is at least
--recurse-min commits) and then contributes one "merge resolution" unit for
whatever the train did not scope. A train below the threshold collapses into a
single unit whose metadata comes from its earliest real content commit.

Ownership: each net-diff path is claimed by the LAST unit in emission order
whose source scope contains it. Paths no unit scoped (renames performed
outside any scoped delta, mostly) go to a sink unit at the tip.

Usage:
  ps-snapshot-by-unit.py OUTPUT_BRANCH --base mysql-8.0.11 --tip ps-8.0.11-init
  ps-snapshot-by-unit.py OUTPUT_BRANCH --base B --tip T --markers --keep-empty
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

NULL_OID = "0" * 40
PR_RE = re.compile(r"\bMerge pull request #(\d+)\b")

# Repo-plumbing commits: they are the first in-range toucher of files whose
# Percona content arrived later, so attributing a path to them buys a huge
# whole-file insertion under a subject that explains nothing.
DEFAULT_SKIP_DONORS = (
    r"^initial import\b",
    r"^initial revision\b",
    r"^import mysql-[0-9]",
    r"^remove \.bzrignore\b",
    r"^move Percona-Server to be the top level directory",
    r"^Merge from 5\.5 the move Percona-Server",
    r"^merge libperconaserverclient replacing libmysqlclient",
    r"^copy Docs/INFO_",
)


class SnapshotError(RuntimeError):
    pass


def git(repo, *args, input_text=None, env=None, check=True):
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=run_env,
    )
    if check and res.returncode != 0:
        raise SnapshotError(
            f"git {' '.join(args)} failed (rc={res.returncode})\n{res.stderr}")
    return res


def git_text(repo, *args, check=True):
    return git(repo, *args, check=check).stdout


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# units
# --------------------------------------------------------------------------- #

@dataclass
class Unit:
    donor: str | None               # commit supplying metadata + message
    scope: set[str] = field(default_factory=set)
    kind: str = "commit"            # commit | train | merge-resolution | sink
    marker: str | None = None       # "[#NNN]" from the enclosing PR merge
    owned: list[str] = field(default_factory=list)
    train: tuple[str, str] | None = None   # (side_base, side_tip) if collapsed
    merge_sha: str | None = None           # the merge itself, as donor fallback


def walk_nodes(repo, base, tip):
    """[(sha, parents, subject, changed_paths_vs_first_parent)] oldest first.

    Streamed: a `--name-only` pass over a big range can emit hundreds of MB,
    so read it line by line instead of buffering the whole output.
    """
    proc = subprocess.Popen(
        ["git", "-C", str(repo), "log", "--first-parent", "--reverse",
         "--name-only", "--format=@@%H\x01%P\x01%s", f"{base}..{tip}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    nodes, cur = [], None
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.startswith("@@"):
            sha, parents, subject = line[2:].split("\x01", 2)
            cur = (sha, parents.split(), subject, set())
            nodes.append(cur)
        elif line and cur is not None:
            cur[3].add(line)
    proc.stdout.close()
    if proc.wait() != 0:
        raise SnapshotError(f"git log {base}..{tip} failed:\n{proc.stderr.read()}")
    return nodes


def load_dag(repo, base, tip):
    """One pass: sha -> parents, sha -> subject, for every commit in the range."""
    out = git_text(repo, "log", "--format=%H\x01%P\x01%s", f"{base}..{tip}")
    parents, subjects = {}, {}
    for line in out.split("\n"):
        if not line:
            continue
        sha, par, subject = line.split("\x01", 2)
        parents[sha] = par.split()
        subjects[sha] = subject
    return parents, subjects


def collect_units(repo, dag, base, tip, net_set, recurse_min_paths, max_depth,
                  depth=0, marker=None, stats=None):
    parents_map, subjects = dag
    units: list[Unit] = []
    nodes = walk_nodes(repo, base, tip)
    stats["ranges"] += 1
    log(f"  {'  ' * depth}[d{depth}] {base[:9]}..{tip[:9]}: {len(nodes)} node(s)"
        f"  (ranges={stats['ranges']} units={stats['units']})")
    for sha, parents, subject, paths in nodes:
        node_marker = PR_RE.search(subject)
        child_marker = f"[#{node_marker.group(1)}]" if node_marker else marker

        if len(parents) < 2:
            units.append(Unit(donor=sha, scope=set(paths), kind="commit",
                              marker=marker))
            stats["units"] += 1
            continue

        side_base, side_tip = parents[0], parents[1]
        # Recurse when this merge's own delta claims a lot of the final tree --
        # that is what we must not let a single unit own. Sizing the train by
        # commit count needs a reachability query per merge (slow); the delta
        # is already in hand and targets the goal directly.
        weight = len(paths & net_set)
        stats["merges"] += 1
        deep = weight >= recurse_min_paths and (max_depth == 0
                                                or depth < max_depth)

        if deep:
            inner = collect_units(repo, dag, side_base, side_tip, net_set,
                                  recurse_min_paths, max_depth, depth + 1,
                                  child_marker, stats)
            scoped: set[str] = set()
            for u in inner:
                scoped |= u.scope
            units.extend(inner)
            residue = set(paths) - scoped
            units.append(Unit(donor=sha, scope=residue, kind="merge-resolution",
                              marker=marker))
            stats["units"] += 1
            stats["recursed"] += 1
        else:
            # Donor = earliest real content commit of the train. It cannot be
            # found by walking first-parents from side_tip: when side_tip is
            # itself a merge that walk leaves the train and drifts down the
            # shared mainline, handing every such PR the same stale commit.
            # It needs the range, so resolve it later and only for the units
            # that actually get emitted.
            units.append(Unit(donor=None, scope=set(paths), kind="train",
                              marker=child_marker,
                              train=(side_base, side_tip), merge_sha=sha))
            stats["units"] += 1
            stats["collapsed"] += 1
    return units


# --------------------------------------------------------------------------- #
# ownership + emission
# --------------------------------------------------------------------------- #

def commit_to_unit(parents_map, units):
    """Map every commit in the range to the unit that represents it.

    Units are visited in emission order and each claims, by BFS over parents,
    the commits no earlier unit took. A commit therefore belongs to exactly one
    unit -- the first one whose train pulls it in -- and the whole assignment
    costs one in-memory pass, no subprocesses.
    """
    owner: dict[str, int] = {}
    for idx, unit in enumerate(units):
        seeds = [unit.merge_sha or unit.donor]
        if unit.train:
            seeds.append(unit.train[1])
        stack = [c for c in seeds if c]
        while stack:
            cur = stack.pop()
            if cur is None or cur in owner or cur not in parents_map:
                continue
            owner[cur] = idx
            stack.extend(parents_map[cur])
    return owner


def path_toucher_lists(repo, base, tip, wanted, merges=False):
    """path -> [shas newest-first] for `wanted` paths only."""
    proc = subprocess.Popen(
        ["git", "-C", str(repo), "log", "--name-only",
         *(["--diff-merges=first-parent"] if merges else ["--no-merges"]),
         "--format=@@%H", f"{base}..{tip}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lists, cur = {}, None
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.startswith("@@"):
            cur = line[2:]
        elif line and line in wanted:
            lists.setdefault(line, []).append(cur)
    proc.stdout.close()
    if proc.wait() != 0:
        raise SnapshotError(f"git log --name-only failed:\n{proc.stderr.read()}")
    return lists


def path_touchers(repo, base, tip, merges=False):
    """(last_toucher, first_toucher) per path over the whole DAG."""
    proc = subprocess.Popen(
        ["git", "-C", str(repo), "log", "--name-only",
         *(["--diff-merges=first-parent"] if merges else ["--no-merges"]),
         "--format=@@%H", f"{base}..{tip}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    last, first, cur = {}, {}, None
    for line in proc.stdout:                      # newest first
        line = line.rstrip("\n")
        if line.startswith("@@"):
            cur = line[2:]
        elif line:
            if line not in last:
                last[line] = cur                  # first seen == newest touch
            first[line] = cur                     # overwritten down to oldest
    proc.stdout.close()
    if proc.wait() != 0:
        raise SnapshotError(f"git log --name-only failed:\n{proc.stderr.read()}")
    return last, first


def assign_by_toucher(repo, dag, units, paths, renames, base, tip, rule,
                      skip_res=()):
    """Own each path via the unit containing the commit `rule` picks for it.

    'introducer' (default): the OLDEST non-merge commit that touched the path,
    so a sweeping late change (a tree-wide warning fix, a clang-format pass, a
    version bump) cannot claim files it merely edited -- with final content
    those would arrive as whole-file insertions under a misleading subject.
    'toucher': the newest non-merge commit instead.
    Paths no non-merge commit touched fall through to merge deltas, then to
    the delta-scope rule.
    """
    parents_map, subjects = dag
    log("mapping commits to units")
    member = commit_to_unit(parents_map, units)
    log(f"  {len(member)} commit(s) mapped")
    log(f"finding {rule} per path")
    lists = path_toucher_lists(repo, base, tip, set(paths), merges=False)
    owner: dict[str, int] = {}
    skipped = 0
    for p in paths:
        seq = lists.get(p)
        if not seq:
            continue
        order = list(reversed(seq)) if rule == "introducer" else seq
        pick = None
        for cand in order:
            if skip_res and any(r.search(subjects.get(cand, "")) for r in skip_res):
                continue
            pick = cand
            break
        if pick is None:                  # every toucher is plumbing
            pick = order[0]
        elif pick is not order[0]:
            skipped += 1
        idx = member.get(pick)
        if idx is not None:
            owner[p] = idx
    if skipped:
        log(f"  {skipped} path(s) skipped a repo-plumbing donor")
    missing = [p for p in paths if p not in owner]
    if missing:
        last_m, first_m = path_touchers(repo, base, tip, merges=True)
        pick_m = first_m if rule == "introducer" else last_m
        n = 0
        for p in missing:
            idx = member.get(pick_m.get(p, ""))
            if idx is not None:
                owner[p] = idx
                n += 1
        log(f"  {n} path(s) attributed via a merge delta")
    # Paths no non-merge commit ever touched (deletions performed at merge
    # points, evil merges) fall back to the last unit whose delta scopes them.
    wanted = {p for p in paths if p not in owner}
    if wanted:
        for idx, unit in enumerate(units):
            for p in unit.scope & wanted:
                owner[p] = idx
        log(f"  {len(wanted)} merge-only path(s) fell back to delta scope")
    for src, dest in renames.items():
        if src not in owner and dest in owner:
            owner[src] = owner[dest]
    for p, idx in owner.items():
        units[idx].owned.append(p)
    return [p for p in paths if p not in owner]

def resolve_donors(repo, units, subjects=None, skip_res=()):
    """Fill in donors for collapsed trains: earliest non-merge in the train.

    Repo-plumbing commits are skipped here too. Skipping them only at
    attribution time is not enough: a path can legitimately land on a unit
    whose earliest commit is `initial import`, and then the commit is titled
    after the import even though it carries someone's feature work.
    """
    pending = [u for u in units if u.donor is None]
    for n, unit in enumerate(pending, 1):
        side_base, side_tip = unit.train
        out = git_text(repo, "rev-list", "--no-merges", "--reverse",
                       f"{side_base}..{side_tip}")
        candidates = [c for c in out.split("\n") if c.strip()]
        first = ""
        for cand in candidates:
            subj = (subjects or {}).get(cand, "")
            if skip_res and any(r.search(subj) for r in skip_res):
                continue
            first = cand
            break
        if not first and candidates:
            first = candidates[0]
        if first:
            unit.donor = first
        else:
            unit.donor = unit.merge_sha
            unit.kind = "merge-resolution"
            unit.marker = None
        if n % 100 == 0:
            log(f"  resolved {n}/{len(pending)} train donor(s)")
    return len(pending)

def net_paths(repo, base, tip):
    """(paths, rename_src -> rename_dest) for the net base..tip diff."""
    out = git_text(repo, "diff", "--name-status", "-z", base, tip)
    fields = [f for f in out.split("\0") if f]
    paths, renames, i = [], {}, 0
    while i < len(fields):
        status = fields[i]
        if status[0] == "R":             # rename: source must be removed too
            paths.append(fields[i + 1])
            paths.append(fields[i + 2])
            renames[fields[i + 1]] = fields[i + 2]
            i += 3
        elif status[0] == "C":           # copy: source survives, only dest is new
            paths.append(fields[i + 2])
            i += 3
        else:
            paths.append(fields[i + 1])
            i += 2
    return paths, renames


def assign(units, paths, renames):
    wanted = set(paths)
    owner: dict[str, int] = {}
    for idx, unit in enumerate(units):
        for p in unit.scope & wanted:
            owner[p] = idx
    # A rename's source disappears because its destination appeared: let it
    # follow the destination's unit so both halves land in one commit.
    for src, dest in renames.items():
        if src not in owner and dest in owner:
            owner[src] = owner[dest]
    for p, idx in owner.items():
        units[idx].owned.append(p)
    return [p for p in paths if p not in owner]


def tree_entries(repo, tree, paths, chunk=800):
    found = {}
    for start in range(0, len(paths), chunk):
        out = git_text(repo, "ls-tree", "-z", tree, "--",
                       *paths[start:start + chunk])
        for record in out.split("\0"):
            if not record:
                continue
            meta, path = record.split("\t", 1)
            mode, _kind, oid = meta.split()
            found[path] = (mode, oid)
    return found


def overlay(repo, base_tree, source_tree, paths):
    """base_tree with `paths` set to their source_tree state (absent = removed)."""
    if not paths:
        return base_tree
    wanted = sorted(set(paths))
    entries = tree_entries(repo, source_tree, wanted)
    lines = []
    for path in wanted:
        entry = entries.get(path)
        if entry is None:
            lines.append(f"0 {NULL_OID}\t{path}")
        else:
            mode, oid = entry
            lines.append(f"{mode} {oid}\t{path}")
    with tempfile.TemporaryDirectory(prefix="ps-snapshot-unit-index-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(repo, "read-tree", base_tree, env=env)
        git(repo, "update-index", "--index-info",
            input_text="\n".join(lines) + "\n", env=env)
        return git(repo, "write-tree", env=env).stdout.strip()


def commit_meta(repo, sha):
    out = git_text(repo, "show", "-s",
                   "--format=%an\x01%ae\x01%aI\x01%cn\x01%ce\x01%cI\x01%B", sha)
    an, ae, ad, cn, ce, cd, body = out.split("\x01", 6)
    return an, ae, ad, cn, ce, cd, body.rstrip("\n") + "\n"


def emit(repo, parent, tree, donor, marker, subject_override=None):
    an, ae, ad, cn, ce, cd, body = commit_meta(repo, donor)
    if subject_override:
        body = subject_override.rstrip("\n") + "\n"
    if marker:
        lines = body.split("\n")
        if not lines[0].startswith(f"{marker} "):
            lines[0] = f"{marker} {lines[0]}"
        body = "\n".join(lines)
    env = {
        "GIT_AUTHOR_NAME": an, "GIT_AUTHOR_EMAIL": ae, "GIT_AUTHOR_DATE": ad,
        "GIT_COMMITTER_NAME": cn, "GIT_COMMITTER_EMAIL": ce,
        "GIT_COMMITTER_DATE": cd,
    }
    return git(repo, "commit-tree", tree, "-p", parent,
               input_text=body, env=env).stdout.strip()


# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output_branch")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", required=True)
    ap.add_argument("--tip", required=True)
    ap.add_argument("--recurse-min-paths", type=int, default=40,
                    help="recurse into a merge's train when the merge's own "
                         "delta touches at least N paths of the net diff "
                         "(lighter merges collapse to one unit; default 40)")
    ap.add_argument("--max-depth", type=int, default=0,
                    help="recursion depth limit (0 = unlimited)")
    ap.add_argument("--markers", action="store_true",
                    help="prefix subjects with [#NNN] from the enclosing "
                         "'Merge pull request #NNN' node")
    ap.add_argument("--keep-empty", action="store_true",
                    help="emit units that own no path as empty commits")
    ap.add_argument("--sink-subject",
                    default="[snapshot] remaining paths with no owning unit",
                    help="subject for the final sink commit")
    ap.add_argument("--force-output", action="store_true")
    ap.add_argument("--ownership", choices=("introducer", "toucher", "delta"),
                    default="introducer",
                    help=(
                        "which commit gets credit for a path. "
                        "'introducer' (default): the OLDEST non-merge commit "
                        "that touched it, so a tree-wide sweep (warning fix, "
                        "clang-format, version bump) cannot claim files it "
                        "merely edited -- with final content those arrive as "
                        "whole-file insertions under a subject that explains "
                        "nothing. "
                        "'toucher': the NEWEST non-merge commit instead; "
                        "keeps a release merge from claiming files it carried, "
                        "but hands sweeps everything they grazed. "
                        "'delta': the last unit whose merge delta scopes the "
                        "path -- fewest, largest commits, and an upstream "
                        "release merge claims hundreds of carried files. "
                        "'introducer' and 'toucher' fall back to merge deltas, "
                        "then to 'delta', for paths no non-merge ever touched"),
                    )
    ap.add_argument("--skip-donor-subject", action="append", default=[],
                    metavar="REGEX",
                    help="additional subject patterns whose commits must not "
                         "own a path (attribution falls through to the next "
                         "toucher); adds to the built-in plumbing list")
    ap.add_argument("--no-skip-donors", action="store_true",
                    help="let repo-plumbing commits own paths after all")
    ap.add_argument("--dry-run", action="store_true",
                    help="report unit/ownership counts and stop before emitting")
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    base = git_text(repo, "rev-parse", f"{args.base}^{{commit}}").strip()
    tip = git_text(repo, "rev-parse", f"{args.tip}^{{commit}}").strip()
    tip_tree = git_text(repo, "rev-parse", f"{tip}^{{tree}}").strip()
    base_tree = git_text(repo, "rev-parse", f"{base}^{{tree}}").strip()

    if git(repo, "rev-parse", "-q", "--verify",
           f"refs/heads/{args.output_branch}", check=False).returncode == 0 \
            and not args.force_output:
        raise SnapshotError(
            f"{args.output_branch} exists; pass --force-output to replace it")

    stats = {"merges": 0, "recursed": 0, "collapsed": 0,
             "ranges": 0, "units": 0}
    paths, renames = net_paths(repo, base, tip)
    log(f"net diff paths: {len(paths)} ({len(renames)} rename(s))")
    log(f"loading dag {base[:12]}..{tip[:12]}")
    dag = load_dag(repo, base, tip)
    log(f"  {len(dag[0])} commit(s) in range")
    log("collecting units")
    units = collect_units(repo, dag, base, tip, set(paths),
                          args.recurse_min_paths, args.max_depth, stats=stats)
    log(f"  units={len(units)} merges={stats['merges']} "
        f"recursed={stats['recursed']} collapsed={stats['collapsed']}")

    pats = () if args.no_skip_donors else (
        tuple(DEFAULT_SKIP_DONORS) + tuple(args.skip_donor_subject))
    skip_res = tuple(re.compile(x, re.IGNORECASE) for x in pats)
    if args.ownership in ("introducer", "toucher"):
        unclaimed = assign_by_toucher(repo, dag, units, paths, renames,
                                      base, tip, args.ownership, skip_res)
    else:
        unclaimed = assign(units, paths, renames)
    owning = sum(1 for u in units if u.owned)
    log(f"  owned by {owning} unit(s); {len(units) - owning} unit(s) own nothing; "
        f"{len(unclaimed)} path(s) unclaimed")

    if args.dry_run:
        sizes = sorted((len(u.owned) for u in units if u.owned), reverse=True)
        log(f"dry-run: units={len(units)} owning={len(sizes)} "
            f"unclaimed={len(unclaimed)} largest={sizes[:5]}")
        print(f"recurse_min_paths={args.recurse_min_paths} units={len(units)} "
              f"owning={len(sizes)} unclaimed={len(unclaimed)} "
              f"max_owned={sizes[0] if sizes else 0}")
        return 0

    to_emit = [u for u in units if u.owned or args.keep_empty]
    n = resolve_donors(repo, to_emit, dag[1], skip_res)
    log(f"resolved {n} train donor(s) for {len(to_emit)} unit(s) to emit")

    parent, tree, emitted, rows = base, base_tree, 0, []
    for unit in to_emit:
        tree = overlay(repo, tree, tip_tree, unit.owned)
        marker = unit.marker if args.markers else None
        parent = emit(repo, parent, tree, unit.donor, marker)
        emitted += 1
        rows.append((parent, unit.donor, unit.kind, len(unit.owned)))
        if emitted % 100 == 0:
            log(f"  emitted {emitted} commit(s)")

    if unclaimed:
        tree = overlay(repo, tree, tip_tree, unclaimed)
        parent = emit(repo, parent, tree, tip, None,
                      subject_override=args.sink_subject)
        emitted += 1
        rows.append((parent, tip, "sink", len(unclaimed)))
        log(f"  sink commit: {len(unclaimed)} path(s)")

    if tree != tip_tree:
        raise SnapshotError(
            f"final tree {tree[:12]} != tip tree {tip_tree[:12]}\n"
            + git_text(repo, "diff", "--stat", tree, tip_tree))
    log(f"null-diff OK: output tree == {args.tip} tree")

    git(repo, "update-ref", f"refs/heads/{args.output_branch}", parent)
    log(f"done: {args.output_branch} = {parent[:12]} ({emitted} commits)")

    if args.report:
        with open(args.report, "w") as fh:
            fh.write(f"# ps-snapshot-by-unit: {args.output_branch}\n\n")
            fh.write(f"- base: `{args.base}` ({base[:12]})\n")
            fh.write(f"- tip:  `{args.tip}` ({tip[:12]})\n")
            fh.write(f"- units: {len(units)}, emitted: {emitted}, "
                     f"paths: {len(paths)}, unclaimed: {len(unclaimed)}\n\n")
            fh.write("| commit | donor | kind | paths |\n|---|---|---|---:|\n")
            for sha, donor, kind, n in rows:
                subj = git_text(repo, "show", "-s", "--format=%s", sha).strip()
                fh.write(f"| {sha[:12]} | {donor[:12]} | {kind} | {n} | "
                         f"{subj[:70]} |\n".replace("| \n", "|\n"))
        log(f"report: {args.report}")
    print(parent)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SnapshotError as exc:
        log(f"error: {exc}")
        sys.exit(1)

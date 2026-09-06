#!/usr/bin/env python3
"""
ps-reorder.py

Single-pass Percona Server branch reorder tool.

This is the simplified form of the two-pass tool (kept as ps-reorder-2pass.py).
It performs only what the old tool called "pass 1: emit g1-g4":

  g1  Squashes            one commit per squash category, holding the final
                          INPUT state of those paths
  g2  build-ps            per-source-commit split of build-ps/, packaging/ and
                          scripts/systemd/ paths
  g3  CI configs          per-source-commit split of CI config paths
  g4  MyRocks: storage    per-source-commit split of storage/rocksdb and
      and MTR             rocksdb MTR paths

Every other commit is kept intact, in its original first-parent order, with only
the g1-g4 paths removed from it. There is no group classification, no g11 queue,
no cherry-pick promotion probe and no .result squashing.

When the input already carries GROUP markers, commits found inside its g2, g3 and
g4 sections stay in their own section, in their original relative order. They keep
every path they own plus every path that belongs to a later group or to no group
at all, so nothing is ever pushed down to a later group or into the remaining
section. Paths owned by an *earlier* group are still squashed into g1 or split
into g2-g3 - a build-ps or doc/ path riding along in a g4 commit, for instance.
That direction is always safe because the receiving section is emitted first, so
the path's own section remains its last writer. Use --reclassify-groups to
classify every commit purely by path instead.

Existing MARKER commits in the input are dropped; markers in the output are
regenerated.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from collections import defaultdict


BATCH_SIZE = 400
OUTPUT_STAT_LINE_LEN = 104


MARKER_SUBJECTS = {
    1: "==================== MARKER: GROUP 1 — Squashes ====================",
    2: "==================== MARKER: GROUP 2 — build-ps ====================",
    3: "==================== MARKER: GROUP 3 — CI configs ====================",
    4: "==================== MARKER: GROUP 4 — MyRocks: storage and MTR ==========",
    5: "==================== MARKER: GROUP 5 — Remaining commits =================",
}

REST_GROUP = 5

# Commits already sitting in these input sections keep their place; only paths
# owned by an earlier group are extracted out of them.
KEEP_IN_PLACE_GROUPS = (2, 3, 4)

UNGROUPED = 0

DEFAULT_GROUP_LABELS = {
    UNGROUPED: "ungrouped",
    1: "Squashes",
    2: "build-ps",
    3: "CI configs",
    4: "MyRocks: storage and MTR",
    REST_GROUP: "Remaining commits",
}

# Matches the markers this tool emits and the 11-group markers emitted by the
# older two-pass tool, so a previously reordered branch can be fed back in.
MARKER_RE = re.compile(r"^={3,} MARKER: GROUP (\d+) — (.+?) ={3,}$")


G1_DOC = "doc"
G1_MAN = "man"
G1_INTERNAL = "internal"
G1_TOKUDB_BACKUP = "tokudb-backup-plugin"
G1_STORAGE_TOKUDB = "storage-tokudb"
G1_PS_TOKUDB_ADMIN = "ps-tokudb-admin"
G1_VERSION_UNIV = "version-univ"
G1_TOKUDB_TESTS = "tokudb-tests"
G1_TRAVIS = "travis"


G1_SUBJECTS = {
    G1_DOC: "Squash: doc/",
    G1_MAN: "Squash: man/",
    G1_INTERNAL: "Squash: internal/",
    G1_TOKUDB_BACKUP: "Squash: plugin/tokudb-backup-plugin/",
    G1_STORAGE_TOKUDB: "Squash: storage/tokudb/",
    G1_PS_TOKUDB_ADMIN: "Squash: scripts/ps_tokudb_admin.sh and scripts/fill_help_tables.sql",
    G1_VERSION_UNIV: "Squash: MYSQL_VERSION, VERSION and storage/innobase/include/univ.i",
    G1_TOKUDB_TESTS: "Squash: mysql-test/suite/tokudb* and MTR *toku* tests",
    G1_TRAVIS: "Squash: .travis.yml",
}


# Emitted at the head of g1: paths the input branch deletes outright relative to
# BASE that no g1-g4 section owns. Without it these deletions ride along in
# whichever g5 commit happened to carry them, so every g1-g4 commit still holds
# files the input branch does not have.
HEAD_DELETION_SUBJECT = "Remove files deleted by input branch"


class Style:
    def __init__(self):
        self.enabled = False

    def wrap(self, code, text):
        if not self.enabled or not text:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text):
        return self.wrap("1", text)

    def dim(self, text):
        return self.wrap("2", text)

    def red(self, text):
        return self.wrap("31", text)

    def green(self, text):
        return self.wrap("32", text)

    def yellow(self, text):
        return self.wrap("33", text)

    def blue(self, text):
        return self.wrap("34", text)

    def magenta(self, text):
        return self.wrap("35", text)

    def cyan(self, text):
        return self.wrap("36", text)


STYLE = Style()


def configure_color(mode):
    if mode == "always":
        STYLE.enabled = True
    elif mode == "never":
        STYLE.enabled = False
    elif os.environ.get("NO_COLOR") is not None:
        STYLE.enabled = False
    elif os.environ.get("FORCE_COLOR"):
        STYLE.enabled = True
    else:
        STYLE.enabled = sys.stderr.isatty()


def log(message):
    print(message, file=sys.stderr, flush=True)


def fmt_group(group):
    return STYLE.cyan(f"g{group}")


def fmt_sha(sha):
    return STYLE.yellow(sha[:12])


def truncate_text(text, max_len=OUTPUT_STAT_LINE_LEN):
    return text if len(text) <= max_len else text[:max_len]


def truncate_subject_for_prefix(prefix, subject):
    return truncate_text(subject, max(0, OUTPUT_STAT_LINE_LEN - len(prefix)))


def log_section(message):
    log(STYLE.bold(STYLE.blue(message)))


def log_marker(group, subject):
    log(f"{STYLE.cyan('marker')} {fmt_group(group)}: {STYLE.dim(subject)}")


def log_emit(group, source_hash, new_hash, subject):
    prefix = f"emit g{group} {source_hash[:12]} -> {new_hash[:12]} "
    subject = truncate_subject_for_prefix(prefix, subject)
    log(
        f"{STYLE.green('emit')} {fmt_group(group)} "
        f"{fmt_sha(source_hash)} -> {fmt_sha(new_hash)} {STYLE.bold(subject)}"
    )


def log_skip(group, source_hash, subject):
    prefix = f"skip g{group} {source_hash[:12]} "
    subject = truncate_subject_for_prefix(prefix, subject)
    log(f"{STYLE.yellow('skip')} {fmt_group(group)} {fmt_sha(source_hash)} {subject}")


def run_git(args, check=True, env=None, retry_on_lock=True):
    tries = 3 if retry_on_lock else 1
    last = None
    for attempt in range(tries):
        last = subprocess.run(
            ["git"] + list(args),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=env,
        )
        if last.returncode == 0:
            return last
        if retry_on_lock and "index.lock" in (last.stdout + last.stderr):
            time.sleep(0.3 * (attempt + 1))
            continue
        break

    if check and last.returncode != 0:
        cmd = "git " + " ".join(args)
        raise RuntimeError(
            f"{cmd} failed with rc={last.returncode}\n"
            f"STDOUT:\n{last.stdout}\nSTDERR:\n{last.stderr}"
        )
    return last


def git_rev_parse(rev):
    return run_git(["rev-parse", rev]).stdout.strip()


def branch_exists(ref):
    return run_git(["rev-parse", "--verify", "--quiet", ref],
                   check=False).returncode == 0


def current_branch():
    r = run_git(["symbolic-ref", "--short", "-q", "HEAD"], check=False)
    return r.stdout.strip() or None


def ensure_clean_worktree():
    r = run_git(["status", "--porcelain"], check=False)
    if r.stdout.strip():
        raise RuntimeError("working tree is not clean; commit or stash changes")


def get_commit_list(base, head):
    r = run_git(["log", "--first-parent", "--reverse", "--format=%H",
                 f"{base}..{head}"])
    return [line for line in r.stdout.splitlines() if line]


def get_commit_parents(commit):
    r = run_git(["rev-list", "--parents", "-n", "1", commit])
    parts = r.stdout.strip().split()
    return parts[1:]


def get_commit_files(commit):
    parents = get_commit_parents(commit)
    if not parents:
        r = run_git(["ls-tree", "-r", "--name-only", commit])
        return [line for line in r.stdout.splitlines() if line]
    r = run_git(["diff", "--name-only", "--no-renames", parents[0], commit])
    return [line for line in r.stdout.splitlines() if line]


def get_commit_info(commit):
    sep = "\x1f"
    fmt = sep.join(["%H", "%an", "%ae", "%aI", "%cn", "%ce", "%cI", "%s", "%B"])
    r = run_git(["show", "-s", f"--format={fmt}", commit])
    parts = r.stdout.rstrip("\n").split(sep, 8)
    if len(parts) != 9:
        raise RuntimeError(f"could not parse commit metadata for {commit}")
    full_message = parts[8].rstrip("\n")
    body = ""
    if "\n" in full_message:
        body = full_message.split("\n", 1)[1].lstrip("\n")
    return {
        "hash": parts[0],
        "author_name": parts[1],
        "author_email": parts[2],
        "author_date": parts[3],
        "committer_name": parts[4],
        "committer_email": parts[5],
        "committer_date": parts[6],
        "subject": parts[7],
        "body": body,
    }


def marker_group(subject):
    """Return (group number, group label) for a marker subject, else None."""
    m = MARKER_RE.match(subject)
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip()


def is_marker_subject(subject):
    return marker_group(subject) is not None


def parse_source_commits(commits):
    parsed = []
    removed = []
    labels = {}
    current = UNGROUPED

    for pos, commit in enumerate(commits):
        info = get_commit_info(commit)
        marker = marker_group(info["subject"])
        if marker is not None:
            current, label = marker
            labels[current] = label
            removed.append({
                "hash": commit,
                "subject": info["subject"],
                "reason": "source marker omitted; output markers are regenerated",
            })
            continue
        parsed.append({
            "hash": commit,
            "pos": pos,
            "info": info,
            "source_group": current,
            "files": get_commit_files(commit),
        })
    return parsed, removed, labels


def group_label(group, labels):
    return labels.get(group) or DEFAULT_GROUP_LABELS.get(group, "unknown")


def log_source_groups(parsed, labels, keep_in_place=True):
    """Report how many input commits were found in each group section."""
    counts = defaultdict(int)
    for src in parsed:
        counts[src["source_group"]] += 1

    log_section("input groups")
    if not labels:
        log(
            f"  {STYLE.dim('no markers found')}: "
            f"{STYLE.cyan(str(len(parsed)))} commit(s) treated as ungrouped"
        )
        return

    for group in sorted(counts):
        name = group_label(group, labels)
        note = (" (kept in place; g1-g3 paths extracted)"
                if keep_in_place and group in KEEP_IN_PLACE_GROUPS else "")
        label = "ungrouped" if group == UNGROUPED else f"g{group}"
        log(
            f"  {STYLE.cyan(f'{label:<9}')} {STYLE.green(f'{counts[group]:>5}')} "
            f"commit(s)  {STYLE.bold(name)}{STYLE.dim(note)}"
        )


def is_tokudb_mtr_test_path(path):
    base = os.path.basename(path)
    return (
        path.startswith("mysql-test/suite/tokudb") or
        (path.startswith("mysql-test/") and "toku" in base.lower())
    )


def is_ci_path(path):
    return (
        path == ".travis.yml" or
        path.startswith(".circleci/") or
        path == "azure-pipelines.yml" or
        path == ".cirrus.yml" or
        path == ".clang-tidy" or
        path.startswith(".github/workflows/")
    )


def is_g2_path(path):
    return (
        path.startswith("build-ps/") or
        path.startswith("packaging/") or
        path.startswith("scripts/systemd/")
    )


def is_g4_path(path):
    return (
        path == "storage/rocksdb" or
        path.startswith("storage/rocksdb/") or
        path == "mysql-test/suite/rocksdb" or
        path.startswith("mysql-test/suite/rocksdb") or
        path == "mysql-test/include/have_rocksdb.inc" or
        path == "mysql-test/include/have_rocksdb_as_default.inc"
    )


def classify_g1(path):
    if path.startswith("doc/"):
        return G1_DOC
    if path.startswith("man/"):
        return G1_MAN
    if path.startswith("internal/"):
        return G1_INTERNAL
    if path.startswith("plugin/tokudb-backup-plugin/"):
        return G1_TOKUDB_BACKUP
    if path.startswith("storage/tokudb/"):
        return G1_STORAGE_TOKUDB
    if path in {"scripts/ps_tokudb_admin.sh", "scripts/fill_help_tables.sql"}:
        return G1_PS_TOKUDB_ADMIN
    if path in {"MYSQL_VERSION", "VERSION", "storage/innobase/include/univ.i"}:
        return G1_VERSION_UNIV
    if is_tokudb_mtr_test_path(path):
        return G1_TOKUDB_TESTS
    if path == ".travis.yml":
        return G1_TRAVIS
    return None


def path_group(path):
    """Group that owns this path by the path rules, or None for the rest."""
    if classify_g1(path) is not None:
        return 1
    if is_g2_path(path):
        return 2
    if is_ci_path(path):
        return 3
    if is_g4_path(path):
        return 4
    return None


def split_paths(paths):
    """Partition one commit's paths into g1 categories, g2, g3, g4 and rest."""
    g1 = defaultdict(list)
    g2 = []
    g3 = []
    g4 = []
    rest = []

    for path in paths:
        g1_cat = classify_g1(path)
        if g1_cat is not None:
            g1[g1_cat].append(path)
        elif is_g2_path(path):
            g2.append(path)
        elif is_ci_path(path):
            g3.append(path)
        elif is_g4_path(path):
            g4.append(path)
        else:
            rest.append(path)
    return g1, g2, g3, g4, rest


def plan_head_deletions(base_hash, input_hash, parsed):
    """Paths present in BASE, absent from INPUT and owned by no g1-g4 section.

    Returns (paths, info) where info is the commit identity to reuse. Prefer an
    input commit that is itself a pure deletion of exactly these paths, so a
    branch that already carries such a commit keeps its author and date.
    """
    r = run_git(["diff", "--name-only", "--no-renames", "--diff-filter=D",
                 base_hash, input_hash], check=False)
    paths = sorted(
        line for line in r.stdout.splitlines()
        if line and path_group(line) is None
    )
    if not paths:
        return [], None

    wanted = set(paths)
    for src in parsed:
        files = src["files"]
        if files and set(files) <= wanted and commit_is_pure_deletion(src["hash"]):
            return paths, src["info"]
    return paths, parsed[0]["info"] if parsed else None


def commit_is_pure_deletion(commit):
    r = run_git(["show", "--no-renames", "--diff-filter=D", "--name-only",
                 "--format=", commit], check=False)
    deleted = {line for line in r.stdout.splitlines() if line}
    all_files = set(get_commit_files(commit))
    return bool(all_files) and deleted == all_files


def emit_head_deletions(paths, info, report):
    if not paths:
        return
    remove_paths(paths)
    body = (
        f"Deleted {len(paths)} path(s) that exist in the base tree but not in "
        "the input branch and that no g1-g4 section owns.\n\n"
        "Emitted at the head of group 1 so the rest of the history does not "
        "carry files the input branch has removed."
    )
    if commit_with_info(info, HEAD_DELETION_SUBJECT, body):
        new_hash = git_rev_parse("HEAD")
        report["emitted"].append({
            "hash": info["hash"],
            "subject": HEAD_DELETION_SUBJECT,
            "group": 1,
            "label": "head-deletions",
            "new_hash": new_hash,
        })
        log_emit(1, info["hash"], new_hash, HEAD_DELETION_SUBJECT)
    else:
        report["skipped"].append({
            "hash": info["hash"],
            "subject": HEAD_DELETION_SUBJECT,
            "group": 1,
            "label": "head-deletions",
            "reason": "no staged changes",
        })
        log_skip(1, info["hash"], HEAD_DELETION_SUBJECT)


def make_item(src, files, target_group, kind):
    info = src["info"]
    return {
        "source_hash": src["hash"],
        "source_pos": src["pos"],
        "info": info,
        "subject": info["subject"],
        "body": info["body"],
        "files": sorted(set(files)),
        "target_group": target_group,
        "kind": kind,
    }


def foreign_path_count(files, group):
    """Paths in files that do not classify to group by the path rules."""
    return sum(1 for path in files if path_group(path) != group)


def record_g1_paths(plan, src, g1_by_category):
    for cat, paths in g1_by_category.items():
        plan["g1_files"][cat].update(paths)
        if cat not in plan["g1_first_info"]:
            plan["g1_first_info"][cat] = src["info"]
            plan["g1_first_pos"][cat] = src["pos"]


def plan_kept_commit(plan, src, group):
    """Plan a commit found in the input g2-g4 sections.

    The commit stays where it is and keeps every path it owns, plus any path
    that belongs to a later group or to no group at all. Paths owned by an
    earlier group are squashed into g1 or split into g2-g3, which is always
    safe: extraction only ever moves a path to a section that is emitted
    before this one, so the path's own section stays the last writer.
    """
    g1, g2, g3, g4, rest = split_paths(src["files"])
    extracted = 0

    if g1:
        record_g1_paths(plan, src, g1)
        extracted += sum(len(paths) for paths in g1.values())

    stay = []
    for earlier, paths in ((2, g2), (3, g3)):
        if not paths:
            continue
        if earlier < group:
            plan["buckets"][earlier].append(
                make_item(src, paths, earlier, f"split-from-g{group}"))
            extracted += len(paths)
        else:
            stay.extend(paths)
    stay.extend(g4)
    stay.extend(rest)

    plan["extracted"][group] += extracted
    if not stay:
        plan["removed"].append({
            "hash": src["hash"],
            "subject": src["info"]["subject"],
            "reason": f"all g{group} paths extracted into earlier groups",
        })
        return

    plan["buckets"][group].append(make_item(src, stay, group, "kept-in-place"))
    plan["kept_in_place"][group] += 1
    plan["kept_foreign_paths"][group] += foreign_path_count(stay, group)


def plan_commits(parsed, removed_markers, base_hash, input_hash,
                 keep_in_place=True):
    head_deletion_paths, head_deletion_info = plan_head_deletions(
        base_hash, input_hash, parsed)
    plan = {
        "head_deletion_paths": head_deletion_paths,
        "head_deletion_info": head_deletion_info,
        "g1_files": defaultdict(set),
        "g1_first_info": {},
        "g1_first_pos": {},
        "buckets": {group: [] for group in (2, 3, 4, REST_GROUP)},
        "removed": list(removed_markers),
        "kept_in_place": {group: 0 for group in KEEP_IN_PLACE_GROUPS},
        "kept_foreign_paths": {group: 0 for group in KEEP_IN_PLACE_GROUPS},
        "extracted": {group: 0 for group in KEEP_IN_PLACE_GROUPS},
    }

    for src in parsed:
        group = src["source_group"]
        if keep_in_place and group in KEEP_IN_PLACE_GROUPS:
            if not src["files"]:
                plan["removed"].append({
                    "hash": src["hash"],
                    "subject": src["info"]["subject"],
                    "reason": f"g{group} source commit has no changed paths",
                })
                continue
            plan_kept_commit(plan, src, group)
            continue

        g1, g2, g3, g4, rest = split_paths(src["files"])

        record_g1_paths(plan, src, g1)

        if g2:
            plan["buckets"][2].append(make_item(src, g2, 2, "split"))
        if g3:
            plan["buckets"][3].append(make_item(src, g3, 3, "split"))
        if g4:
            plan["buckets"][4].append(make_item(src, g4, 4, "split"))

        if rest:
            plan["buckets"][REST_GROUP].append(
                make_item(src, rest, REST_GROUP, "kept"))
            continue

        if g1 or g2 or g3 or g4:
            plan["removed"].append({
                "hash": src["hash"],
                "subject": src["info"]["subject"],
                "reason": "all paths consumed by g1-g4 split/squash planning",
            })
        else:
            plan["removed"].append({
                "hash": src["hash"],
                "subject": src["info"]["subject"],
                "reason": "source commit has no changed paths",
            })

    for bucket in plan["buckets"].values():
        bucket.sort(key=lambda item: item["source_pos"])
    return plan


def batched(paths, size=BATCH_SIZE):
    for idx in range(0, len(paths), size):
        yield paths[idx:idx + size]


def split_present_absent(treeish, paths):
    if not paths:
        return [], []
    unique = sorted(set(paths))
    present = set()
    for batch in batched(unique):
        r = run_git(["ls-tree", treeish, "--"] + batch, check=False)
        for line in r.stdout.splitlines():
            if "\t" in line:
                present.add(line.split("\t", 1)[1])
    return (
        [path for path in paths if path in present],
        [path for path in paths if path not in present],
    )


def checkout_paths(treeish, paths):
    for batch in batched(paths):
        run_git(["checkout", treeish, "--"] + batch)


def remove_paths(paths):
    for batch in batched(paths):
        run_git(["rm", "-rf", "--quiet", "--ignore-unmatch", "--"] + batch,
                check=False)


def apply_file_states(treeish, paths):
    """Make the given paths match their state in treeish, staged for commit."""
    paths = sorted(set(paths))
    present, absent = split_present_absent(treeish, paths)
    checkout_paths(treeish, present)
    remove_paths(absent)


def build_message(subject, body):
    """Keep the source subject verbatim, however long it is."""
    return subject + ("\n\n" + body if body.strip() else "")


def commit_with_info(info, subject, body="", allow_empty=False):
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = info["author_name"]
    env["GIT_AUTHOR_EMAIL"] = info["author_email"]
    env["GIT_AUTHOR_DATE"] = info["author_date"]
    env["GIT_COMMITTER_NAME"] = info["committer_name"]
    env["GIT_COMMITTER_EMAIL"] = info["committer_email"]
    env["GIT_COMMITTER_DATE"] = info["committer_date"]

    cmd = ["commit", "-m", build_message(subject, body)]
    if allow_empty:
        cmd.append("--allow-empty")
    r = run_git(cmd, check=False, env=env)
    if r.returncode == 0:
        return True
    combined = (r.stdout + r.stderr).lower()
    if "nothing to commit" in combined or "no changes added" in combined:
        return False
    raise RuntimeError(
        f"git commit failed for {subject!r}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    )


def emit_marker(group):
    subject = MARKER_SUBJECTS[group]
    run_git(["commit", "--allow-empty", "-m", subject])
    log_marker(group, subject)


def emit_item(item, report, allow_empty=False):
    apply_file_states(item["source_hash"], item["files"])
    ok = commit_with_info(item["info"], item["subject"], item["body"],
                          allow_empty=allow_empty)
    entry = {
        "hash": item["source_hash"],
        "subject": item["subject"],
        "group": item["target_group"],
        "label": item["kind"],
    }
    if ok:
        new_head = git_rev_parse("HEAD")
        entry["new_hash"] = new_head
        report["emitted"].append(entry)
        log_emit(item["target_group"], item["source_hash"], new_head,
                 item["subject"])
        return True

    entry["reason"] = "planned item produced no staged changes"
    report["skipped"].append(entry)
    log_skip(item["target_group"], item["source_hash"], item["subject"])
    return False


def emit_squash(input_hash, cat, files, info, report):
    subject = G1_SUBJECTS[cat]
    apply_file_states(input_hash, sorted(files))
    body = (
        f"Squashed {len(files)} path(s) into group 1 category {cat}.\n\n"
        f"First source commit: {info['hash']}"
    )
    ok = commit_with_info(info, subject, body)
    entry = {
        "category": cat,
        "subject": subject,
        "paths": len(files),
        "first_source": info["hash"],
    }
    if ok:
        entry["new_hash"] = git_rev_parse("HEAD")
        report["squashed"].append(entry)
        log(
            f"{STYLE.magenta('squash')} {fmt_group(1)} {STYLE.bold(cat)}: "
            f"{STYLE.green(str(len(files)))} path(s)"
        )
    else:
        entry["reason"] = "squash produced no staged changes"
        report["skipped"].append(entry)
        log(f"{STYLE.yellow('skip')} {fmt_group(1)} {cat}: no staged changes")


def emit_group(plan, group, report, allow_empty=False):
    items = plan["buckets"][group]
    if not items:
        log(f"{fmt_group(group)}: {STYLE.dim('no items')}")
    for item in items:
        emit_item(item, report, allow_empty=allow_empty)


def emit_grouped_path_fixup(input_hash, report):
    """Repair g1-g4 paths left stale by a commit kept in place.

    Every g1-g4 path is owned by a section that is fully emitted before the kept
    commits start, so once g4 is done those paths must already match INPUT. A
    commit kept in place can still carry a path owned by a *later* group - a
    g2 commit touching a rocksdb path, say - and be its last writer even though
    that later section is emitted afterwards. Restore INPUT state for such paths
    here, so the kept commits start from the right tree and no snapshot commit
    has to land on the branch tip.
    """
    stale = [path for path in remaining_diff_paths(input_hash, "HEAD")
             if path_group(path) is not None]
    if not stale:
        log(f"{STYLE.dim('grouped-path fixup')}: none needed")
        return False

    log(
        f"{STYLE.yellow('grouped-path fixup')}: "
        f"{STYLE.yellow(str(len(stale)))} path(s) left stale by kept commits"
    )
    for path in stale[:20]:
        log(f"  {STYLE.dim(f'g{path_group(path)}')} {path}")
    if len(stale) > 20:
        log(f"  {STYLE.dim(f'... and {len(stale) - 20} more')}")

    apply_file_states(input_hash, stale)
    info = get_commit_info(input_hash)
    body = (
        f"Restored {len(stale)} g1-g4 path(s) to their INPUT_BRANCH state. Each "
        "one is owned by an already emitted group but was overwritten by a "
        "commit that was kept in place in another group section."
    )
    ok = commit_with_info(info, "Fixup: restore g1-g4 paths left stale by kept commits", body)
    report["fixup"] = {"paths": len(stale), "emitted": bool(ok)}
    return ok


def remaining_diff_paths(input_hash, output_ref):
    r = run_git(["diff", "--name-only", "--no-renames", output_ref, input_hash],
                check=False)
    return [line for line in r.stdout.splitlines() if line]


def reconcile_to_input(input_hash, output_ref, report):
    paths = remaining_diff_paths(input_hash, output_ref)
    if not paths:
        log(f"{STYLE.green('final tree matches input')}")
        return False

    log(
        f"{STYLE.yellow('final reconciliation')}: "
        f"{STYLE.yellow(str(len(paths)))} differing path(s)"
    )
    apply_file_states(input_hash, paths)
    info = get_commit_info(input_hash)
    body = (
        f"Applied file-state reconciliation for {len(paths)} path(s) so the "
        f"output tree matches {input_hash}."
    )
    ok = commit_with_info(info, "SNAP: reconcile remaining diff to INPUT_BRANCH", body)
    report["reconciliation"] = {
        "paths": len(paths),
        "emitted": bool(ok),
    }
    remaining = remaining_diff_paths(input_hash, output_ref)
    if remaining:
        raise RuntimeError(
            f"reconciliation did not converge; {len(remaining)} path(s) still differ"
        )
    return ok


def create_output_branch(output_branch, base_hash, force):
    if branch_exists(output_branch):
        if not force:
            raise RuntimeError(
                f"output branch {output_branch!r} already exists; pass --force-output"
            )
        if current_branch() == output_branch:
            run_git(["checkout", "--detach", "HEAD"])
        run_git(["branch", "-D", output_branch])
    run_git(["checkout", "-b", output_branch, base_hash])


def build_output(args, input_hash, base_hash, plan, report):
    create_output_branch(args.output_branch, base_hash, args.force_output)

    log_section("pass 1: emit g1-g4")
    emit_marker(1)
    emit_head_deletions(plan["head_deletion_paths"], plan["head_deletion_info"],
                        report)
    for cat in sorted(plan["g1_files"], key=lambda key: plan["g1_first_pos"][key]):
        emit_squash(input_hash, cat, plan["g1_files"][cat],
                    plan["g1_first_info"][cat], report)

    for group in (2, 3, 4):
        emit_marker(group)
        emit_group(plan, group, report)

    emit_grouped_path_fixup(input_hash, report)

    log_section("remaining commits kept in source order")
    if not args.no_rest_marker:
        emit_marker(REST_GROUP)
    emit_group(plan, REST_GROUP, report, allow_empty=args.keep_empty)

    diff_paths = remaining_diff_paths(input_hash, args.output_branch)
    if diff_paths and args.no_reconcile:
        raise RuntimeError(
            f"output tree differs from input by {len(diff_paths)} path(s); "
            "rerun without --no-reconcile to create a final reconciliation commit"
        )
    if diff_paths:
        reconcile_to_input(input_hash, args.output_branch, report)
    else:
        log(f"{STYLE.green('final tree matches input')}")


def log_entries(title, entries, formatter):
    if not entries:
        return
    log(STYLE.bold(title))
    for item in entries:
        log(f"  {formatter(item)}")


def print_final_report(args, base_hash, input_hash, parsed_count, plan, report):
    log_section("final report")
    log(f"{STYLE.bold('base')}: {fmt_sha(base_hash)}")
    log(f"{STYLE.bold('input')}: {fmt_sha(input_hash)}")
    log(f"{STYLE.bold('output branch')}: {STYLE.cyan(args.output_branch)}")
    log(f"{STYLE.bold('source commits parsed')}: {parsed_count}")
    log(f"{STYLE.bold('emitted commits')}: {STYLE.green(str(len(report['emitted'])))}")
    log(f"{STYLE.bold('g1 squashes')}: {STYLE.magenta(str(len(report['squashed'])))}")
    for group in (2, 3, 4):
        kept = plan["kept_in_place"][group]
        total = len(plan["buckets"][group])
        foreign = plan["kept_foreign_paths"][group]
        extracted = plan["extracted"][group]
        detail = (
            f" ({kept} kept in place carrying {foreign} foreign path(s), "
            f"{extracted} path(s) extracted to earlier groups, "
            f"{total - kept} split in from other sections)"
        ) if kept else ""
        log(
            f"{STYLE.bold(f'g{group} commits')}: "
            f"{STYLE.cyan(str(total))}{STYLE.dim(detail)}"
        )
    log(
        f"{STYLE.bold(f'g{REST_GROUP} commits kept in source order')}: "
        f"{STYLE.cyan(str(len(plan['buckets'][REST_GROUP])))}"
    )
    log(f"{STYLE.bold('skipped output items')}: {STYLE.yellow(str(len(report['skipped'])))}")
    log(f"{STYLE.bold('dropped source commits')}: {STYLE.yellow(str(len(plan['removed'])))}")

    fixup = report.get("fixup")
    if fixup:
        log(
            f"{STYLE.bold('grouped-path fixup')}: "
            f"{STYLE.yellow(str(fixup['paths']))} path(s), "
            f"commit emitted={str(fixup['emitted']).lower()}"
        )

    rec = report.get("reconciliation")
    if rec:
        log(
            f"{STYLE.bold('reconciliation')}: "
            f"{STYLE.yellow(str(rec['paths']))} path(s), "
            f"commit emitted={str(rec['emitted']).lower()}"
        )

    log_entries(
        "dropped source commits",
        plan["removed"],
        lambda item: (
            f"{fmt_sha(item['hash'])} "
            f"{truncate_text(item['subject'], 60)} - {item['reason']}"
        ),
    )
    log_entries(
        "skipped output items",
        report["skipped"],
        lambda item: (
            f"{fmt_sha(item.get('hash') or item.get('first_source', ''))} "
            f"{item.get('subject') or item.get('category', '')} - "
            f"{item.get('reason', 'skipped')}"
        ),
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Reorder a Percona Server branch: emit g1-g4 only, keep the "
                    "rest of the commits intact in source order."
    )
    parser.add_argument("--input-branch", required=True,
                        help="input branch or commit to reorder")
    parser.add_argument("--output-branch", required=True,
                        help="new output branch to create")
    parser.add_argument("--base-branch", required=True,
                        help="base branch or commit where output starts")
    parser.add_argument("--force-output", action="store_true",
                        help="delete and recreate output branch if it exists")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="allow starting from a dirty worktree")
    parser.add_argument("--no-reconcile", action="store_true",
                        help="fail instead of creating a final reconciliation commit")
    parser.add_argument("--no-rest-marker", action="store_true",
                        help="do not emit the marker before the kept commits")
    parser.add_argument("--reclassify-groups", action="store_true",
                        help="classify every commit by path, including commits "
                             "already found in the input g2-g4 sections "
                             "(default: keep those commits intact)")
    parser.add_argument("--keep-empty", action="store_true",
                        help="keep kept commits that became empty after the "
                             "g1-g4 paths were extracted")
    parser.add_argument("--color", choices=("auto", "always", "never"),
                        default="auto",
                        help="colorize progress output (default: auto)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    configure_color(args.color)
    if not args.allow_dirty:
        ensure_clean_worktree()

    base_hash = git_rev_parse(args.base_branch)
    input_hash = git_rev_parse(args.input_branch)
    commits = get_commit_list(base_hash, input_hash)
    parsed, removed_markers, labels = parse_source_commits(commits)

    log(
        f"{STYLE.bold('input commits')}: {len(commits)} total, "
        f"{len(parsed)} non-marker"
    )
    log_source_groups(parsed, labels,
                      keep_in_place=not args.reclassify_groups)
    if labels and not args.reclassify_groups:
        log(
            f"  {STYLE.dim('g2-g4 commits keep their place; only paths owned by an')} "
            f"{STYLE.dim('earlier group are extracted')}"
        )

    plan = plan_commits(parsed, removed_markers, base_hash, input_hash,
                        keep_in_place=not args.reclassify_groups)
    report = {
        "emitted": [],
        "skipped": [],
        "squashed": [],
    }

    build_output(args, input_hash, base_hash, plan, report)
    print_final_report(args, base_hash, input_hash, len(parsed), plan, report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"{STYLE.red('error')}: {exc}")
        raise SystemExit(1)

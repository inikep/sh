#!/usr/bin/env python3
"""Prune a replayed Percona Server branch by running Phase A, Phase B and
Phase C from the ps-make-clean skill.

Phase A — strip transient paths
  A path is transient iff it is touched somewhere in BASE..SRC AND it is absent
  from both BASE's tree and SRC's tree. Each source commit is re-emitted via
  tree-level plumbing (read-tree / update-index --remove / write-tree /
  commit-tree) with all transient paths force-removed. Commits whose stripped
  tree equals the running parent's tree are dropped.

Phase B — small-commit split and squash
  For each commit on the post-A branch, count diff lines = insertions+deletions
  (`git show --shortstat --format=`) and inspect touched paths
  (`git show --name-only --format=`). Classify:
    * Large (>8 lines): keep as-is.
    * Small with any C/C++ source (.h .c .cc .cxx .cpp .hh .hpp .hxx): keep.
    * Small without C/C++: squash candidate. Its prev-modifier is the most
      recent prior commit with same-path overlap; chains are resolved to the
      ultimate non-candidate root. If no prev-modifier exists, the candidate
      is kept as an orphan singleton.
  Application walks chronologically: roots that own absorbed members are
  cherry-picked --no-commit together with their members and committed with a
  combined message (root_msg + "\n\n-----\n\n" + member_msg ...); everything
  else is plain cherry-pick.

Phase C — deletion-only squash
  For each commit on the post-B branch, classify deletion-only commits
  (insertions == 0, deletions > 0). For each, the prev-modifier is the most
  recent prior commit that touched one of the same paths; chains are
  resolved to the ultimate non-candidate root. If no prev-modifier exists,
  the commit is kept as an orphan singleton. Application is identical to
  Phase B: combined message, single resulting commit per root.

All three phases must end with `git diff $OUTPUT $SRC` == 0.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


CPP_EXT = ('.h', '.c', '.cc', '.cxx', '.cpp', '.hh', '.hpp', '.hxx')

INS_RE = re.compile(r'(\d+) insertion')
DEL_RE = re.compile(r'(\d+) deletion')

# Marker commits are empty placeholders whose subject identifies a section in
# the linearized history, e.g.
#   ==================== MARKER: GROUP 3 — CI configs ====================
# They must survive all three phases even though their stripped tree is
# identical to their parent's.
MARKER_RE = re.compile(r'(^=+\s|MARKER:|=+$)')


def is_marker_subject(subj: str) -> bool:
    return bool(MARKER_RE.search(subj or ''))


def run(*cmd, check=True, capture=True, env=None, stdin=None):
    r = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        env=env,
        input=stdin,
    )
    if check and r.returncode != 0:
        sys.stderr.write(f"command failed: {' '.join(cmd)}\n")
        if r.stdout:
            sys.stderr.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
        raise SystemExit(r.returncode)
    return r


def git(*args, **kw):
    return run('git', *args, **kw)


def git_out(*args):
    return git(*args).stdout


def ensure_clean_worktree():
    if git_out('status', '--porcelain').strip():
        sys.exit("working tree is not clean. abort.")


def ensure_ancestor(base, src):
    r = run('git', 'merge-base', '--is-ancestor', base, src, check=False)
    if r.returncode != 0:
        sys.exit(f"{base} is not an ancestor of {src}. abort.")


def compute_transient(base, src, log_dir):
    touched = sorted({
        line for line in git_out(
            'log', '--pretty=format:', '--name-only', f'{base}..{src}'
        ).splitlines() if line.strip()
    })
    tip = set(git_out('ls-tree', '-r', '--name-only', src).splitlines())
    base_tree = set(git_out('ls-tree', '-r', '--name-only', base).splitlines())
    transient = [p for p in touched if p not in tip and p not in base_tree]

    (log_dir / 'touched.txt').write_text('\n'.join(touched) + '\n')
    (log_dir / 'tip.txt').write_text('\n'.join(sorted(tip)) + '\n')
    (log_dir / 'base.txt').write_text('\n'.join(sorted(base_tree)) + '\n')
    (log_dir / 'transient.txt').write_text('\n'.join(transient) + '\n')
    return transient


def phase_a(base, src, output, log_dir, transient):
    print(f"Transient paths: {len(transient)}")

    # Reset OUTPUT to BASE
    if git('rev-parse', '--verify', '--quiet', output, check=False).returncode == 0:
        git('checkout', '-q', output)
        git('reset', '--hard', '-q', base)
    else:
        git('checkout', '-q', '-b', output, base)

    source_shas = git_out('rev-list', '--reverse', f'{base}..{src}').split()
    total = len(source_shas)

    parent_commit = git_out('rev-parse', 'HEAD').strip()
    parent_tree = git_out('rev-parse', f'{parent_commit}^{{tree}}').strip()

    tmp_index = tempfile.NamedTemporaryFile(delete=False).name
    msg_file = tempfile.NamedTemporaryFile(delete=False).name
    transient_blob = '\n'.join(transient) + ('\n' if transient else '')

    sha_map = []
    skipped = []
    try:
        for i, sha in enumerate(source_shas, 1):
            meta = git_out('log', '-1',
                           '--format=%an%x1F%ae%x1F%aI%x1F%cn%x1F%ce%x1F%cI%x1F%s',
                           sha).rstrip('\n')
            an, ae, ad, cn, ce, cd, subj = meta.split('\x1f')

            env = os.environ.copy()
            env['GIT_INDEX_FILE'] = tmp_index
            run('git', 'read-tree', f'{sha}^{{tree}}', env=env)
            if transient:
                run('git', 'update-index', '--remove', '--force-remove',
                    '--stdin', env=env, stdin=transient_blob, check=False)
            new_tree = subprocess.run(
                ['git', 'write-tree'], capture_output=True, text=True, env=env
            ).stdout.strip()

            if new_tree == parent_tree and not is_marker_subject(subj):
                sha_map.append(f'{sha}\t-\tempty-after-strip')
                skipped.append(f'[{i}/{total}] SKIP: {sha} {subj}')
                continue

            Path(msg_file).write_text(git_out('log', '-1', '--format=%B', sha))

            ce_env = os.environ.copy()
            ce_env.update({
                'GIT_AUTHOR_NAME': an, 'GIT_AUTHOR_EMAIL': ae, 'GIT_AUTHOR_DATE': ad,
                'GIT_COMMITTER_NAME': cn, 'GIT_COMMITTER_EMAIL': ce, 'GIT_COMMITTER_DATE': cd,
            })
            new_commit = subprocess.run(
                ['git', 'commit-tree', new_tree, '-p', parent_commit, '-F', msg_file],
                capture_output=True, text=True, env=ce_env, check=True
            ).stdout.strip()

            parent_commit = new_commit
            parent_tree = new_tree
            sha_map.append(f'{sha}\t{new_commit}\tapplied')
    finally:
        for p in (tmp_index, msg_file):
            try:
                os.unlink(p)
            except OSError:
                pass

    git('update-ref', 'HEAD', parent_commit)
    git('reset', '--hard', '-q', 'HEAD')

    (log_dir / 'clean-sha-map.tsv').write_text('\n'.join(sha_map) + '\n')
    (log_dir / 'clean-skipped.txt').write_text('\n'.join(skipped) + '\n')

    applied = sum(1 for r in sha_map if r.endswith('\tapplied'))
    dropped = sum(1 for r in sha_map if '\t-\t' in r)
    print(f"Phase A done. Tip: {git_out('rev-parse', 'HEAD').strip()}")
    print(f"Applied: {applied}")
    print(f"Dropped (all-transient): {dropped}")
    verify_null_diff(output, src, phase='A')


def verify_null_diff(output, src, phase):
    diff = git_out('diff', output, src)
    n = 0 if not diff else len(diff.splitlines())
    print(f"Diff vs {src}: {n} lines (must be 0)")
    if n != 0:
        sys.exit(f"PHASE {phase} FAILED: non-zero diff vs {src}")


def phase_b_analyze(base, output, log_dir):
    chrono = git_out('rev-list', '--reverse', f'{base}..{output}').split()
    paths = {}
    diff_lines = {}
    for sha in chrono:
        ps = git_out('show', '--name-only', '--format=', sha).strip().splitlines()
        paths[sha] = set(p for p in ps if p)
        ss = git_out('show', '--shortstat', '--format=', sha).strip()
        ins = int(INS_RE.search(ss).group(1)) if INS_RE.search(ss) else 0
        dels = int(DEL_RE.search(ss).group(1)) if DEL_RE.search(ss) else 0
        diff_lines[sha] = ins + dels

    small_cpp = []
    small_nocpp = []
    large = []
    for sha in chrono:
        n = diff_lines[sha]
        has_cpp = any(p.endswith(CPP_EXT) for p in paths[sha])
        if n <= 8:
            (small_cpp if has_cpp else small_nocpp).append(sha)
        else:
            large.append(sha)

    prev_mod = {}
    chrono_pos = {s: i for i, s in enumerate(chrono)}
    for sha in small_nocpp:
        idx = chrono_pos[sha]
        target = None
        for j in range(idx - 1, -1, -1):
            if paths[chrono[j]] & paths[sha]:
                target = chrono[j]
                break
        prev_mod[sha] = target

    squash = {s: t for s, t in prev_mod.items() if t}
    orphan = [s for s, t in prev_mod.items() if not t]

    plan = {
        'chrono': chrono,
        'small_cpp_kept': small_cpp,
        'small_nocpp_squash': squash,
        'small_nocpp_keep_orphan': orphan,
        'paths': {s: sorted(p) for s, p in paths.items()},
        'diff_lines': diff_lines,
    }
    (log_dir / 'phase-b-plan.json').write_text(json.dumps(plan, indent=2))

    print(f"Total: {len(chrono)}")
    print(f"  large (>8 lines): {len(large)}")
    print(f"  small with C/C++ (kept): {len(small_cpp)}")
    print(f"  small no-C++ (candidates): {len(small_nocpp)}  "
          f"squashable: {len(squash)}  orphan: {len(orphan)}")
    for s, t in squash.items():
        s_subj = git_out('log', '-1', '--format=%s', s).strip()
        t_subj = git_out('log', '-1', '--format=%s', t).strip()
        print(f"  squash {s[:11]} {s_subj}")
        print(f"      -> {t[:11]} {t_subj}")
    return plan


def phase_c_analyze(base, output, log_dir):
    """Per-file split: for each deletion-only commit X with files
    [F1..Fn], each Fi is routed to the most recent prior NON-deletion-only
    commit that touched Fi. Different files in X may land in different
    roots. If every file of X has a target, X is fully absorbed and
    dropped; otherwise X is kept intact (no partial split).
    """
    chrono = git_out('rev-list', '--reverse', f'{base}..{output}').split()
    paths = {}
    ins_lines = {}
    del_lines = {}
    for sha in chrono:
        ps = git_out('show', '--name-only', '--format=', sha).strip().splitlines()
        paths[sha] = [p for p in ps if p]
        ss = git_out('show', '--shortstat', '--format=', sha).strip()
        ins_lines[sha] = int(INS_RE.search(ss).group(1)) if INS_RE.search(ss) else 0
        del_lines[sha] = int(DEL_RE.search(ss).group(1)) if DEL_RE.search(ss) else 0

    del_only = [s for s in chrono if ins_lines[s] == 0 and del_lines[s] > 0]
    del_only_set = set(del_only)
    chrono_pos = {s: i for i, s in enumerate(chrono)}

    # Per (source_sha, file) -> root_sha (most recent non-deletion-only
    # prior commit touching that file).
    per_file_target: dict[tuple[str, str], str] = {}
    fully_absorbed: list[str] = []
    partial_kept: list[str] = []
    for sha in del_only:
        idx = chrono_pos[sha]
        ok = True
        for f in paths[sha]:
            target = None
            for j in range(idx - 1, -1, -1):
                cand = chrono[j]
                if cand in del_only_set:
                    continue
                if f in paths[cand]:
                    target = cand
                    break
            if target is None:
                ok = False
                break
            per_file_target[(sha, f)] = target
        if ok:
            fully_absorbed.append(sha)
        else:
            # Roll back any per-file assignments for this source; we keep
            # the source intact rather than splitting it partially.
            for f in paths[sha]:
                per_file_target.pop((sha, f), None)
            partial_kept.append(sha)

    # root_sha -> ordered list of (source_sha, file) absorbed there.
    absorb_into: dict[str, list[tuple[str, str]]] = {}
    for (src, f), root in per_file_target.items():
        absorb_into.setdefault(root, []).append((src, f))
    for root in absorb_into:
        absorb_into[root].sort(key=lambda sf: (chrono_pos[sf[0]], sf[1]))

    plan = {
        'chrono': chrono,
        'fully_absorbed': fully_absorbed,
        'partial_kept': partial_kept,
        # JSON-friendly serialization of (src,file) tuples.
        'absorb_into': {
            root: [{'source': s, 'file': f} for s, f in items]
            for root, items in absorb_into.items()
        },
    }
    (log_dir / 'phase-c-plan.json').write_text(json.dumps(plan, indent=2))

    print(f"Total: {len(chrono)}")
    print(f"  deletion-only: {len(del_only)}  "
          f"fully-absorbed (drop): {len(fully_absorbed)}  "
          f"partial-kept: {len(partial_kept)}")
    return plan


def squash_apply(base, src, output, log_dir, chrono, squash, *, phase, work_suffix):
    """Generic apply: walk `chrono`, squashing absorbed commits into their
    ultimate root with a combined message. Used by Phase B and Phase C."""
    absorbed_set = set(squash.keys())

    def resolve(s, depth=0):
        if depth > 100 or s not in squash:
            return s
        return resolve(squash[s], depth + 1)

    ultimate = {a: resolve(a) for a in absorbed_set}
    chrono_pos = {s: i for i, s in enumerate(chrono)}
    absorb_into: dict[str, list[str]] = {}
    for a, root in ultimate.items():
        absorb_into.setdefault(root, []).append(a)
    for k in absorb_into:
        absorb_into[k].sort(key=lambda s: chrono_pos[s])

    work = f'{output}-{work_suffix}'
    run('git', 'branch', '-D', work, check=False)
    git('checkout', '-q', '-b', work, base)

    log_lines = []
    log_path = log_dir / f'phase-{phase.lower()}-apply.log'
    for i, sha in enumerate(chrono, 1):
        subj = git_out('log', '-1', '--format=%s', sha).strip()[:55]
        if sha in absorbed_set:
            log_lines.append(f"[{i}] DEFER {sha[:11]} -> root {ultimate[sha][:11]}")
            continue
        if sha in absorb_into:
            members = [sha] + absorb_into[sha]
            msgs = []
            for m in members:
                r = run('git', 'cherry-pick', '--allow-empty',
                        '--keep-redundant-commits', '--no-commit', m,
                        check=False)
                if r.returncode != 0:
                    log_lines.append(
                        f"[{i}] CONFLICT cherry-pick {m[:11]} under root {sha[:11]}"
                    )
                    run('git', 'cherry-pick', '--abort', check=False)
                    sys.stderr.write(r.stdout or '')
                    sys.stderr.write(r.stderr or '')
                    log_path.write_text('\n'.join(log_lines))
                    sys.exit(1)
                msgs.append(git_out('log', '-1', '--format=%B', m).rstrip())
            combined = "\n\n-----\n\n".join(msgs)
            env = os.environ.copy()
            for fmt, var in [('%an', 'GIT_AUTHOR_NAME'),
                             ('%ae', 'GIT_AUTHOR_EMAIL'),
                             ('%aI', 'GIT_AUTHOR_DATE'),
                             ('%cn', 'GIT_COMMITTER_NAME'),
                             ('%ce', 'GIT_COMMITTER_EMAIL'),
                             ('%cI', 'GIT_COMMITTER_DATE')]:
                env[var] = git_out('log', '-1', '--format=' + fmt, sha).strip()
            # Detect empty-after-squash: cherry-picks may net to zero
            # (e.g. an addition cancelled by a later deletion). In that
            # case there's nothing to commit; drop the merged commit
            # rather than fail.
            head_tree = git_out('rev-parse', 'HEAD^{tree}').strip()
            staged_tree = subprocess.run(
                ['git', 'write-tree'], capture_output=True, text=True, check=True
            ).stdout.strip()
            if staged_tree == head_tree:
                log_lines.append(
                    f"[{i}] DROP-EMPTY {sha[:11]} + {len(absorb_into[sha])} absorbed -> {subj}"
                )
                # Reset the (no-op) staged state cleanly.
                run('git', 'reset', '-q', '--hard', 'HEAD', check=False)
                continue
            fd, mp = tempfile.mkstemp()
            try:
                os.write(fd, combined.encode())
                os.close(fd)
                r = subprocess.run(
                    ['git', 'commit', '-q', '--no-verify', '--file', mp],
                    env=env, capture_output=True, text=True
                )
            finally:
                os.unlink(mp)
            if r.returncode:
                log_lines.append(f"COMMIT FAIL {sha[:11]}")
                log_path.write_text('\n'.join(log_lines))
                sys.stderr.write(r.stdout or '')
                sys.stderr.write(r.stderr or '')
                sys.exit(1)
            log_lines.append(
                f"[{i}] MERGE {sha[:11]} + {len(absorb_into[sha])} absorbed -> {subj}"
            )
        else:
            r = run('git', 'cherry-pick', '--allow-empty',
                    '--keep-redundant-commits', sha, check=False)
            if r.returncode:
                log_lines.append(f"[{i}] CONFLICT singleton {sha[:11]} {subj}")
                sys.stderr.write(r.stdout or '')
                sys.stderr.write(r.stderr or '')
                log_path.write_text('\n'.join(log_lines))
                sys.exit(1)
            log_lines.append(f"[{i}] PICK {sha[:11]} {subj}")

    log_path.write_text('\n'.join(log_lines) + '\n')

    git('branch', '-f', output, work)
    git('checkout', '-q', output)
    git('branch', '-D', work)

    print(f"Phase {phase} applied")
    verify_null_diff(output, src, phase=phase)


def phase_b_apply(base, src, output, log_dir, plan):
    squash_apply(
        base, src, output, log_dir,
        plan['chrono'], plan['small_nocpp_squash'],
        phase='B', work_suffix='phase-b',
    )


def phase_c_apply(base, src, output, log_dir, plan):
    """Walk chronologically. For each non-absorbed commit:
      * If absorb_into has entries for this commit, cherry-pick it, then
        for every (source, file) pair: replace the file's index entry
        with the source's blob for that file (deletion applied via
        tree-level swap). Commit once with combined message.
      * Otherwise plain cherry-pick.
    Fully-absorbed sources are dropped entirely (DEFER)."""
    chrono = plan['chrono']
    fully_absorbed_set = set(plan['fully_absorbed'])
    absorb_into = {
        root: [(e['source'], e['file']) for e in items]
        for root, items in plan['absorb_into'].items()
    }

    work = f'{output}-phase-c'
    run('git', 'branch', '-D', work, check=False)
    git('checkout', '-q', '-b', work, base)

    log_lines = []
    log_path = log_dir / 'phase-c-apply.log'

    for i, sha in enumerate(chrono, 1):
        subj = git_out('log', '-1', '--format=%s', sha).strip()[:55]
        if sha in fully_absorbed_set:
            log_lines.append(f"[{i}] DROP {sha[:11]} (fully absorbed per-file)")
            continue

        # Cherry-pick this commit (root or untouched non-deletion commit).
        r = run('git', 'cherry-pick', '--allow-empty',
                '--keep-redundant-commits', sha, check=False)
        if r.returncode:
            log_lines.append(f"[{i}] CONFLICT cherry-pick {sha[:11]} {subj}")
            sys.stderr.write(r.stdout or '')
            sys.stderr.write(r.stderr or '')
            log_path.write_text('\n'.join(log_lines))
            sys.exit(1)

        entries = absorb_into.get(sha)
        if not entries:
            log_lines.append(f"[{i}] PICK {sha[:11]} {subj}")
            continue

        # Apply per-file blob swaps for each (source, file) absorbed here.
        for source_sha, fpath in entries:
            ls = git_out('ls-tree', source_sha, '--', fpath).strip()
            if not ls:
                # Source deleted the file outright at this path. Remove
                # the path from our index.
                run('git', 'update-index', '--remove', '--force-remove',
                    '--', fpath, check=False)
                continue
            # ls-tree format: "<mode> <type> <sha>\t<path>"
            head, _ = ls.split('\t', 1)
            mode, _typ, blob = head.split()
            run('git', 'update-index', '--add', '--cacheinfo',
                f'{mode},{blob},{fpath}')

        # Amend the cherry-picked commit's tree to include the per-file
        # blob swaps, combining the messages of the root and each
        # contributing source.
        head_tree = git_out('rev-parse', 'HEAD^{tree}').strip()
        staged_tree = subprocess.run(
            ['git', 'write-tree'], capture_output=True, text=True, check=True
        ).stdout.strip()
        if staged_tree == head_tree:
            log_lines.append(
                f"[{i}] PICK {sha[:11]} (no-op absorbs) {subj}"
            )
            continue

        contributing = sorted({s for s, _ in entries},
                              key=lambda s: chrono.index(s))
        msgs = [git_out('log', '-1', '--format=%B', sha).rstrip()]
        for contrib in contributing:
            msgs.append(git_out('log', '-1', '--format=%B', contrib).rstrip())
        combined = "\n\n-----\n\n".join(msgs)

        env = os.environ.copy()
        for fmt, var in [('%an', 'GIT_AUTHOR_NAME'),
                         ('%ae', 'GIT_AUTHOR_EMAIL'),
                         ('%aI', 'GIT_AUTHOR_DATE'),
                         ('%cn', 'GIT_COMMITTER_NAME'),
                         ('%ce', 'GIT_COMMITTER_EMAIL'),
                         ('%cI', 'GIT_COMMITTER_DATE')]:
            env[var] = git_out('log', '-1', '--format=' + fmt, sha).strip()
        head_parent = git_out('rev-parse', 'HEAD^').strip()
        fd, mp = tempfile.mkstemp()
        try:
            os.write(fd, combined.encode())
            os.close(fd)
            new_commit = subprocess.run(
                ['git', 'commit-tree', staged_tree, '-p', head_parent,
                 '-F', mp],
                env=env, capture_output=True, text=True, check=True
            ).stdout.strip()
        finally:
            os.unlink(mp)
        run('git', 'reset', '-q', '--hard', new_commit)
        log_lines.append(
            f"[{i}] MERGE {sha[:11]} + {len(contributing)} source(s) "
            f"({len(entries)} file ops) -> {subj}"
        )

    log_path.write_text('\n'.join(log_lines) + '\n')

    git('branch', '-f', output, work)
    git('checkout', '-q', output)
    git('branch', '-D', work)

    print("Phase C applied")
    verify_null_diff(output, src, phase='C')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--src', required=True, help='source replayed branch (e.g. ups-5.6.5)')
    ap.add_argument('--base', required=True, help='destination base (e.g. mysql-5.6.5)')
    ap.add_argument('--output', required=True, help='output branch (e.g. ups-5.6.5-clean)')
    ap.add_argument('--log-dir', default=None,
                    help='scratch dir for logs (default: /tmp/ps-prune-${OUTPUT}-logs)')
    ap.add_argument('--skip-phase-a', action='store_true',
                    help='assume $OUTPUT already holds the Phase A result; run Phase B only')
    args = ap.parse_args()

    log_dir = Path(args.log_dir or f'/tmp/ps-prune-{args.output}-logs')
    log_dir.mkdir(parents=True, exist_ok=True)

    ensure_clean_worktree()
    ensure_ancestor(args.base, args.src)

    if not args.skip_phase_a:
        print("=== PHASE A: strip transient paths ===")
        transient = compute_transient(args.base, args.src, log_dir)
        phase_a(args.base, args.src, args.output, log_dir, transient)
    else:
        print("=== PHASE A: skipped (--skip-phase-a) ===")
        git('checkout', '-q', args.output)
        verify_null_diff(args.output, args.src, phase='A(skip)')

    print("=== PHASE B: small-commit split/squash ===")
    plan_b = phase_b_analyze(args.base, args.output, log_dir)
    phase_b_apply(args.base, args.src, args.output, log_dir, plan_b)

    print("=== PHASE C: deletion-only squash ===")
    plan_c = phase_c_analyze(args.base, args.output, log_dir)
    phase_c_apply(args.base, args.src, args.output, log_dir, plan_c)

    final = git_out('rev-list', '--count', f'{args.base}..{args.output}').strip()
    print("=== DONE ===")
    print(f"Final {args.output}: {final} commits")


if __name__ == '__main__':
    main()

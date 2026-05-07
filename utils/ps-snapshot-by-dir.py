#!/usr/bin/env python3
"""
ps-snapshot-by-dir.py

Create OUTPUT_BRANCH from BASE_BRANCH and apply the net BASE..SOURCE diff.
By default, split into one commit per top-level directory (plus one commit for
top-level files if any changed). Immediate subdirectories with more than 5
changed files are split into their own commits. With --single-commit, apply the
whole diff as one snapshot commit. With --split-mtr-only, keep non-MTR changes
in one snapshot commit and emit mysql-test/ changes as [MTR-only] commits.
Final tree == SOURCE_BRANCH tree (i.e. null diff to SOURCE_BRANCH).

Changed mysql-test/ files are classified by whether they already exist in
BASE_BRANCH. mysql-test/suite/ paths are emitted as [MTR-only] commits grouped
by suite subdirectory and classification; other mysql-test/ paths are grouped
by classification. Every mysql-test/ commit is marked [MTR-only]. The
mysql-test/ group is processed last, with all upstream commits before all
Percona commits.

Usage:
  ps-snapshot-by-dir.py --source-branch <branch|hash> \
                        --output-branch <new_branch> \
                        --base-branch <branch|hash> \
                        [--single-commit | --split-mtr-only] \
                        [--large-subdir-threshold <n>] \
                        [--report <path>] [--force-output] [--allow-dirty]
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections import OrderedDict


# Keep each git invocation's argv comfortably under the kernel's ARG_MAX.
BATCH_SIZE = 500
LARGE_SUBDIR_THRESHOLD = 5
SINGLE_COMMIT_KEY = '<single-commit>'
MYSQL_TEST_KEY = 'mysql-test'
MYSQL_TEST_PREFIX = MYSQL_TEST_KEY + '/'
MYSQL_TEST_SUITE_PREFIX = MYSQL_TEST_PREFIX + 'suite/'
MTR_ONLY_MARKER = '[MTR-only]'
UPSTREAM_CLASS = 'upstream'
NON_UPSTREAM_CLASS = 'non_upstream'
CLASS_DISPLAY = {
    UPSTREAM_CLASS: 'upstream',
    NON_UPSTREAM_CLASS: 'Percona',
}


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def run_git(args, check=True, env=None, retry_on_lock=True):
    retries = 3 if retry_on_lock else 1
    last = None
    for attempt in range(retries):
        result = subprocess.run(
            ['git'] + list(args),
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode == 0:
            return result
        # Transient index-lock contention: back off and retry.
        if retry_on_lock and 'index.lock' in (result.stdout + result.stderr):
            time.sleep(0.5 * (attempt + 1))
            last = result
            continue
        last = result
        break
    if check and last.returncode != 0:
        # Truncate argv in the error to keep the message readable when we pass
        # thousands of paths.
        argv = ['git'] + list(args)
        if len(argv) > 10:
            preview = ' '.join(argv[:6] + ['...', f'({len(argv)-6} more args)'])
        else:
            preview = ' '.join(argv)
        raise RuntimeError(
            f"{preview} failed (rc={last.returncode})\n"
            f"STDOUT:\n{last.stdout}\nSTDERR:\n{last.stderr}"
        )
    return last


def git_rev_parse(rev):
    return run_git(['rev-parse', rev]).stdout.strip()


def branch_exists(branch):
    return run_git(['rev-parse', '--verify', '--quiet', branch],
                   check=False).returncode == 0


def get_current_branch():
    r = run_git(['symbolic-ref', '--short', '-q', 'HEAD'], check=False)
    return r.stdout.strip() or None


def ensure_clean_worktree():
    if run_git(['status', '--porcelain'], check=False).stdout.strip():
        raise RuntimeError(
            "Working tree is not clean. Commit or stash changes first "
            "(or pass --allow-dirty).")


def batched(paths, size=BATCH_SIZE):
    for i in range(0, len(paths), size):
        yield paths[i:i + size]


def checkout_paths(source_hash, paths):
    """Batch-materialise `paths` in the index + working tree from source_hash."""
    if not paths:
        return
    for batch in batched(paths):
        run_git(['checkout', source_hash, '--'] + batch)
        # `git checkout <tree> -- <paths>` already stages them; explicit `add`
        # is redundant but defensive for edge cases (e.g. file-mode changes).


def remove_paths(paths):
    """Batch-remove `paths` from the index + working tree, tolerating absence."""
    if not paths:
        return
    for batch in batched(paths):
        run_git(['rm', '-rf', '--quiet', '--ignore-unmatch', '--'] + batch,
                check=False)
    # Also wipe anything still hanging around as untracked cruft.
    for p in paths:
        if os.path.lexists(p):
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.unlink(p)
            except OSError:
                pass


def top_level_key(path):
    """Return the grouping key for a path.
      - If path is under a top-level directory -> that directory name.
      - If path is a top-level file            -> the sentinel '<root>'.
    """
    if '/' in path:
        return path.split('/', 1)[0]
    return '<root>'


def immediate_subdir_key(path):
    """Return '<top>/<subdir>' for nested paths, otherwise None."""
    parts = path.split('/')
    if len(parts) < 3:
        return None
    return '/'.join(parts[:2])


def is_mysql_test_path(path):
    return path.startswith(MYSQL_TEST_PREFIX)


def is_mysql_test_suite_path(path):
    return path.startswith(MYSQL_TEST_SUITE_PREFIX)


def mysql_test_suite_group_key(path):
    """Return the immediate mysql-test/suite group for path."""
    if not is_mysql_test_suite_path(path):
        raise ValueError(f"not a mysql-test/suite path: {path}")
    rest = path[len(MYSQL_TEST_SUITE_PREFIX):]
    if '/' not in rest:
        return MYSQL_TEST_SUITE_PREFIX.rstrip('/')
    return MYSQL_TEST_SUITE_PREFIX + rest.split('/', 1)[0]


# ---------------------------------------------------------------------------
# File enumeration
# ---------------------------------------------------------------------------


def list_changed_paths_with_status(base_hash, source_hash):
    """Return (present_paths, absent_paths):
      present = paths that exist in source_hash (added / modified / type-changed)
      absent  = paths that were deleted between base and source
    Renames are disabled so both old and new names appear."""
    r = run_git(['diff', '--name-status', '--no-renames',
                 base_hash, source_hash])
    present, absent = [], []
    for line in r.stdout.split('\n'):
        if not line.strip():
            continue
        parts = line.split('\t', 1)
        if len(parts) != 2:
            continue
        status, path = parts[0][0], parts[1]
        if status == 'D':
            absent.append(path)
        else:  # A, M, T, C, R (renames disabled anyway)
            present.append(path)
    return present, absent


def list_tree_paths(commit_hash, pathspec):
    """Every file path under pathspec in the tree at commit_hash."""
    r = run_git(['ls-tree', '-r', '--name-only', commit_hash, '--', pathspec])
    return [f for f in r.stdout.split('\n') if f]


def group_by_top_level(paths):
    """Return OrderedDict: top-level key -> list of paths.
    Directory groups sorted alphabetically; '<root>' placed last."""
    buckets = {}
    for p in paths:
        buckets.setdefault(top_level_key(p), []).append(p)

    ordered = OrderedDict()
    for key in sorted(k for k in buckets if k != '<root>'):
        ordered[key] = sorted(buckets[key])
    if '<root>' in buckets:
        ordered['<root>'] = sorted(buckets['<root>'])
    return ordered


def split_large_subdir_groups(groups, threshold=LARGE_SUBDIR_THRESHOLD):
    """Split immediate subdirectories with more than threshold paths."""
    ordered = OrderedDict()
    for key, files in groups.items():
        if key == '<root>':
            ordered[key] = sorted(files)
            continue

        by_subdir = {}
        for path in files:
            subdir_key = immediate_subdir_key(path)
            if subdir_key:
                by_subdir.setdefault(subdir_key, []).append(path)

        large_subdirs = {
            subdir_key for subdir_key, subdir_files in by_subdir.items()
            if len(subdir_files) > threshold
        }
        remaining = [
            path for path in files
            if immediate_subdir_key(path) not in large_subdirs
        ]

        if remaining:
            ordered[key] = sorted(remaining)
        for subdir_key in sorted(large_subdirs):
            ordered[subdir_key] = sorted(by_subdir[subdir_key])
    return ordered


def classify_mysql_test_paths(paths, base_tree_paths):
    """Split changed mysql-test paths by whether they existed at BASE."""
    base_tree_path_set = set(base_tree_paths)
    changed_paths = sorted(p for p in paths if is_mysql_test_path(p))
    classification = OrderedDict()
    classification[UPSTREAM_CLASS] = [
        p for p in changed_paths if p in base_tree_path_set
    ]
    classification[NON_UPSTREAM_CLASS] = [
        p for p in changed_paths if p not in base_tree_path_set
    ]
    return classification


def plan_mysql_test_commits(files, classification):
    """Return ordered commit groups for the special mysql-test split."""
    file_set = set(files)
    commit_groups = []
    for kind in (UPSTREAM_CLASS, NON_UPSTREAM_CLASS):
        main_files = sorted(
            path for path in classification.get(kind, [])
            if path in file_set and not is_mysql_test_suite_path(path)
        )
        if main_files:
            commit_groups.append((kind, MYSQL_TEST_KEY, main_files, True))

        by_group = {}
        for path in classification.get(kind, []):
            if path in file_set and is_mysql_test_suite_path(path):
                by_group.setdefault(
                    mysql_test_suite_group_key(path), []).append(path)
        for group_key in sorted(by_group):
            commit_groups.append(
                (kind, group_key, sorted(by_group[group_key]), True))
    return commit_groups


# ---------------------------------------------------------------------------
# Commit construction
# ---------------------------------------------------------------------------


def do_commit(message, allow_empty=False):
    cmd = ['commit', '-m', message]
    if allow_empty:
        cmd.append('--allow-empty')
    r = run_git(cmd, check=False)
    if r.returncode != 0:
        combined = (r.stdout + r.stderr).lower()
        if ('nothing to commit' in combined or
                'nothing added to commit' in combined):
            return False
        raise RuntimeError(
            f"git commit failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    return True


def commit_subject(args, key, mtr_only=False, classification=None):
    title = args.title or f"Apply changes from {args.source_branch}"
    if key == SINGLE_COMMIT_KEY:
        subject = title
    elif key == '<root>':
        subject = f"{title}: top-level files"
    elif '/' in key:
        subject = f"{title}: {key}"
    else:
        subject = f"{title}: {key}/"

    if classification:
        subject = f"{subject} ({CLASS_DISPLAY[classification]})"

    if mtr_only:
        return f"{MTR_ONLY_MARKER} {subject}"
    return subject


def apply_and_commit_paths(args, source_hash, base_hash, key, files,
                           present_set, mtr_only=False, classification=None):
    p = [f for f in files if f in present_set]
    a = [f for f in files if f not in present_set]
    label = f" [{classification}]" if classification else ""
    marker = f" {MTR_ONLY_MARKER}" if mtr_only else ""
    print(f"  [g:{key}] +{len(p)} -{len(a)}{marker}{label}",
          file=sys.stderr, flush=True)

    checkout_paths(source_hash, p)
    remove_paths(a)

    subject = commit_subject(args, key, mtr_only=mtr_only,
                             classification=classification)
    body = (f"{subject}\n\n"
            f"{len(files)} file(s) differing vs "
            f"{args.base_branch} ({base_hash}).")
    if classification:
        body += f"\n\nmysql-test classification: {classification}."

    ok = do_commit(body)
    return {'files': len(files), 'committed': ok}


def make_output_branch(args, base_hash):
    """Create OUTPUT_BRANCH from base_hash."""
    if branch_exists(args.output_branch):
        if not args.force_output:
            raise RuntimeError(
                f"Output branch {args.output_branch!r} already exists; pass "
                f"--force-output to overwrite.")
        if get_current_branch() == args.output_branch:
            run_git(['checkout', '--detach', 'HEAD'])
        run_git(['branch', '-D', args.output_branch])

    run_git(['checkout', '-b', args.output_branch, base_hash])


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def do_diff_mode(args, source_hash, base_hash, report_path):
    present, absent = list_changed_paths_with_status(base_hash, source_hash)
    all_paths = present + absent
    top_level_groups = group_by_top_level(all_paths)
    present_set = set(present)
    mysql_test_classification = None
    if MYSQL_TEST_KEY in top_level_groups:
        mysql_test_base_paths = list_tree_paths(base_hash, MYSQL_TEST_KEY)
        mysql_test_classification = classify_mysql_test_paths(
            top_level_groups[MYSQL_TEST_KEY], mysql_test_base_paths)

    make_output_branch(args, base_hash)

    stats = OrderedDict()
    commit_groups = OrderedDict()
    non_mysql_groups = OrderedDict(
        (key, files) for key, files in top_level_groups.items()
        if key != MYSQL_TEST_KEY)
    split_groups = split_large_subdir_groups(
        non_mysql_groups, args.large_subdir_threshold)
    for key, files in split_groups.items():
        commit_groups[key] = files
        stats[key] = apply_and_commit_paths(
            args, source_hash, base_hash, key, files, present_set)

    if MYSQL_TEST_KEY in top_level_groups:
        upstream = mysql_test_classification[UPSTREAM_CLASS]
        non_upstream = mysql_test_classification[NON_UPSTREAM_CLASS]
        print(f"  [mysql-test] upstream-introduced: {len(upstream)}; "
              f"non-upstream: {len(non_upstream)}",
              file=sys.stderr, flush=True)
        mysql_test_groups = plan_mysql_test_commits(
            top_level_groups[MYSQL_TEST_KEY], mysql_test_classification)
        for classification, group_key, group_files, mtr_only in mysql_test_groups:
            commit_groups[f"{group_key} ({classification})"] = group_files
            stats[f"{group_key} ({classification})"] = apply_and_commit_paths(
                args, source_hash, base_hash, group_key, group_files,
                present_set, mtr_only=mtr_only, classification=classification)

    return stats, commit_groups, mysql_test_classification


def do_single_commit_mode(args, source_hash, base_hash, report_path):
    present, absent = list_changed_paths_with_status(base_hash, source_hash)
    all_paths = sorted(present + absent)
    present_set = set(present)

    make_output_branch(args, base_hash)

    stats = OrderedDict()
    groups = OrderedDict()
    groups[SINGLE_COMMIT_KEY] = all_paths
    stats[SINGLE_COMMIT_KEY] = apply_and_commit_paths(
        args, source_hash, base_hash, SINGLE_COMMIT_KEY, all_paths,
        present_set)
    return stats, groups, None


def do_split_mtr_only_mode(args, source_hash, base_hash, report_path):
    present, absent = list_changed_paths_with_status(base_hash, source_hash)
    all_paths = sorted(present + absent)
    present_set = set(present)
    non_mysql_paths = [p for p in all_paths if not is_mysql_test_path(p)]
    mysql_test_paths = [p for p in all_paths if is_mysql_test_path(p)]
    mysql_test_classification = None
    if mysql_test_paths:
        mysql_test_base_paths = list_tree_paths(base_hash, MYSQL_TEST_KEY)
        mysql_test_classification = classify_mysql_test_paths(
            mysql_test_paths, mysql_test_base_paths)

    make_output_branch(args, base_hash)

    stats = OrderedDict()
    groups = OrderedDict()
    if non_mysql_paths:
        groups[SINGLE_COMMIT_KEY] = non_mysql_paths
        stats[SINGLE_COMMIT_KEY] = apply_and_commit_paths(
            args, source_hash, base_hash, SINGLE_COMMIT_KEY, non_mysql_paths,
            present_set)

    if mysql_test_paths:
        upstream = mysql_test_classification[UPSTREAM_CLASS]
        non_upstream = mysql_test_classification[NON_UPSTREAM_CLASS]
        print(f"  [mysql-test] upstream-introduced: {len(upstream)}; "
              f"non-upstream: {len(non_upstream)}",
              file=sys.stderr, flush=True)
        mysql_test_groups = plan_mysql_test_commits(
            mysql_test_paths, mysql_test_classification)
        for classification, group_key, group_files, mtr_only in mysql_test_groups:
            groups[f"{group_key} ({classification})"] = group_files
            stats[f"{group_key} ({classification})"] = apply_and_commit_paths(
                args, source_hash, base_hash, group_key, group_files,
                present_set, mtr_only=mtr_only, classification=classification)

    return stats, groups, mysql_test_classification


def display_group_key(key):
    if key == '<root>':
        return '(top-level files)'
    if key == SINGLE_COMMIT_KEY:
        return '(single commit)'
    return key


def write_report(args, source_hash, base_hash, mode, stats, groups,
                 mysql_test_classification, report_path):
    log = run_git(['log', '--oneline', '--no-decorate', '--reverse',
                   args.output_branch]).stdout

    # Null diff verification: OUTPUT_BRANCH tree should equal SOURCE tree.
    diff = run_git(['diff', source_hash, args.output_branch],
                   check=False).stdout
    null_diff = not diff.strip()
    diff_stat = run_git(['diff', '--stat', source_hash, args.output_branch],
                        check=False).stdout.strip()

    lines = []
    lines.append("# ps-snapshot-by-dir report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Mode:          **{mode}**")
    lines.append(f"- SOURCE_BRANCH: `{args.source_branch}` ({source_hash})")
    if base_hash:
        lines.append(f"- BASE_BRANCH:   `{args.base_branch}`  ({base_hash})")
    lines.append(f"- OUTPUT_BRANCH: `{args.output_branch}`")
    lines.append(f"- Commit groups: {len(groups)}")
    lines.append(f"- Total paths:   {sum(len(v) for v in groups.values())}")
    lines.append("")

    lines.append("## Groups")
    lines.append("")
    lines.append("| Group | Files | Committed |")
    lines.append("|-------|------:|:---------:|")
    for key, g in stats.items():
        display = display_group_key(key)
        lines.append(f"| `{display}` | {g['files']} | "
                     f"{'yes' if g['committed'] else 'skipped (empty)'} |")
    lines.append("")

    if mysql_test_classification is not None:
        lines.append("## mysql-test upstream classification")
        lines.append("")
        lines.append("Files present in BASE_BRANCH are treated as "
                     "upstream-introduced.")
        lines.append("")
        report_mysql_test_classification(
            lines, "Upstream-introduced files",
            mysql_test_classification[UPSTREAM_CLASS])
        report_mysql_test_classification(
            lines, "Percona/non-upstream files",
            mysql_test_classification[NON_UPSTREAM_CLASS])

    lines.append("## Output branch structure")
    lines.append("")
    lines.append("```")
    lines.append(log.rstrip())
    lines.append("```")
    lines.append("")

    lines.append("## Null diff verification")
    lines.append("")
    lines.append(f"- OUTPUT tree equals SOURCE tree: "
                 f"**{'YES' if null_diff else 'NO'}**")
    if not null_diff:
        lines.append("")
        lines.append("### Remaining diff stat")
        lines.append("```")
        lines.append(diff_stat or "(empty)")
        lines.append("```")
        lines.append("")
        lines.append("### Remaining diff (truncated to 20000 chars)")
        lines.append("```diff")
        lines.append(diff[:20000])
        lines.append("```")
    lines.append("")

    with open(report_path, 'w') as fh:
        fh.write('\n'.join(lines))

    return null_diff


def report_mysql_test_classification(lines, title, paths):
    lines.append(f"### {title}")
    lines.append("")
    if paths:
        for path in paths:
            lines.append(f"- `{path}`")
    else:
        lines.append("(none)")
    lines.append("")


def main():
    parser = argparse.ArgumentParser(
        description='Apply BASE..SOURCE as snapshot commit(s).'
    )
    parser.add_argument('--source-branch', required=True,
                        help='Source branch or commit.')
    parser.add_argument('--output-branch', required=True,
                        help='New branch name to create.')
    parser.add_argument('--base-branch', required=True,
                        help='Base branch or commit. OUTPUT is built from BASE '
                             'and contains the BASE..SOURCE diff split by '
                             'top-level directory.')
    parser.add_argument('--title', default=None,
                        help='Subject prefix for each commit, e.g. '
                             '"Initial Percona Server 5.6.22 tree". '
                             'In split mode, the group name is appended as '
                             '"<title>: <group>" (or "<title>: top-level '
                             'files"). '
                             'Defaults to "Apply changes from <source>".')
    parser.add_argument('--single-commit', action='store_true',
                        help='Apply the whole BASE..SOURCE diff as one '
                             'snapshot commit instead of splitting by '
                             'directory.')
    parser.add_argument('--split-mtr-only', action='store_true',
                        help='Apply non-mysql-test changes as one snapshot '
                             'commit, then emit mysql-test changes as '
                             '[MTR-only] commits.')
    parser.add_argument('--large-subdir-threshold', type=int,
                        default=LARGE_SUBDIR_THRESHOLD,
                        help='In directory-split mode, split an immediate '
                             'subdirectory into its own commit when it has '
                             'more than this many changed files. Defaults to '
                             f'{LARGE_SUBDIR_THRESHOLD}.')
    parser.add_argument('--report', default='ps-snapshot-by-dir-report.md',
                        help='Path to the Markdown report.')
    parser.add_argument('--force-output', action='store_true',
                        help='Delete OUTPUT_BRANCH if it already exists.')
    parser.add_argument('--allow-dirty', action='store_true',
                        help='Skip the clean-worktree check.')
    args = parser.parse_args()
    if args.single_commit and args.split_mtr_only:
        parser.error('--single-commit and --split-mtr-only are mutually exclusive')
    if args.large_subdir_threshold < 0:
        parser.error('--large-subdir-threshold must be non-negative')

    if run_git(['rev-parse', '--show-toplevel'], check=False).returncode != 0:
        print("error: not inside a git repository", file=sys.stderr)
        return 1

    if not args.allow_dirty:
        ensure_clean_worktree()

    source_hash = git_rev_parse(args.source_branch)
    base_hash = git_rev_parse(args.base_branch)
    if base_hash == source_hash:
        raise RuntimeError("BASE_BRANCH and SOURCE_BRANCH point to the "
                           "same commit -- nothing to apply.")
    if run_git(['merge-base', '--is-ancestor', base_hash, source_hash],
               check=False).returncode != 0:
        print(f"warning: {args.base_branch!r} is not an ancestor of "
              f"{args.source_branch!r}; the diff split will still work but "
              f"the base may contain commits not on SOURCE.",
              file=sys.stderr)

    if args.split_mtr_only:
        mode = 'split-mtr-only'
    elif args.single_commit:
        mode = 'single-commit'
    else:
        mode = 'diff'

    print(f"Source: {args.source_branch} ({source_hash[:12]})", file=sys.stderr)
    print(f"Base:   {args.base_branch}  ({base_hash[:12]})", file=sys.stderr)
    print(f"Output: {args.output_branch}", file=sys.stderr)
    print(f"Mode:   {mode}", file=sys.stderr)

    if args.split_mtr_only:
        stats, groups, mysql_test_classification = do_split_mtr_only_mode(
            args, source_hash, base_hash, args.report)
    elif args.single_commit:
        stats, groups, mysql_test_classification = do_single_commit_mode(
            args, source_hash, base_hash, args.report)
    else:
        stats, groups, mysql_test_classification = do_diff_mode(
            args, source_hash, base_hash, args.report)

    print(f"Writing report to {args.report}...", file=sys.stderr)
    null_ok = write_report(args, source_hash, base_hash, mode, stats, groups,
                           mysql_test_classification, args.report)

    print(f"Done. Output tree matches SOURCE: "
          f"{'OK' if null_ok else 'MISMATCH (see report)'}", file=sys.stderr)
    return 0 if null_ok else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""
ps-reorder.py

Reorder a Percona Server branch into logical commit groups and produce a
new branch with a null diff to the original.

Groups (separated by MARKER commits):
  g1  Squashes        one squashed commit per category:
                        - doc/
                        - man/
                        - internal/
                        - plugin/tokudb-backup-plugin/
                        - storage/tokudb/
                        - MYSQL_VERSION + VERSION + storage/innobase/include/univ.i
                        - mysql-test/suite/tokudb* and MTR tests whose
                          filename contains "toku"
  g2  build-ps        build-ps/ portions split from source commits
  g3  CI configs      .travis.yml, .circleci/, azure-pipelines.yml,
                        .cirrus.yml, and .clang-tidy portions
  g4  RocksDB         storage/rocksdb and mysql-test/suite/rocksdb*
                        portions; unsafe source-g11 moves stay in Remaining
  g5  MTR tests       [MTR-only] commits, plus g11 mysql-test-only commits
                        that cherry-pick cleanly and do not overlap earlier
                        protected Remaining changes or later groups
  g6  Non-code changes
                      Remaining commits whose files contain no C/C++ or CMake
                        source (nothing ending in .h .c .cc .cxx .cpp .hh
                        .hpp .hxx .cmake, and no CMakeLists.txt / *.cmake.in).
  g7  Build/Compilation
                      commits whose subject starts with "[compilation]"
  g8  Upstream bug fixes
                      [upstream] commits, plus eligible g11 Remaining commits
                        that cherry-pick cleanly without protected overlaps
  g9  Initial Percona Server tree
                      commits whose subject starts with "[init]"
  g10  MyRocks changes in kernel
                      commits whose subject contains "MYR" or "rocks"
                        (case-insensitive), unless moving would conflict or
                        overlap protected Remaining changes; mixed RocksDB
                        commits contribute only their non-g4 portion here
  g11 Remaining       everything else, plus commits kept to preserve ordering

Rules implemented (letters match the task):
  A) OUTPUT_BRANCH has null diff to INPUT_BRANCH. If the grouped replay still
     leaves a residual diff, one final SNAP reconciliation commit applies the
     remaining file-state differences before verification/reporting.
  B) MARKER commits between groups 1-11
  C) Empty commits are removed except markers when commit creation reports
     "nothing to commit".
  D) Subjects > 91 chars are truncated; original subject is moved into body
  E) Files in g1 are extracted from their origin commits, including commits
     otherwise routed by subject-based whole-commit rules, and squashed into
     the corresponding g1 subcategory
  F) Commits containing g2/g3/g4 files are split; the g2/g3/g4 part goes to
     its bucket, the remainder to g11. For g4+g11 splits, titles get suffixes
     " [MyRocks part]" and " [non-MyRocks part]". When rerunning an already
     grouped branch, source group 11 files stay in g11 if moving them into an
     earlier dedicated bucket would be clobbered by a preserved later group.
  G) Squashes keep the position of their first source commit (ordering within
     g1 follows first-seen position)
  H) A Markdown report is written
  I) Deletion-heavy output commits (more deletions than insertions) have their
     subjects highlighted on the CLI. The reorder script no longer rewrites
     commits to absorb removals.
  J) Source commits whose subject starts with "[compilation]" are moved to the
     g7 build/compilation group after any g1 paths are extracted for squash.
  K) Source commits whose subject starts with "[MTR-only]" are moved to the g5
     MTR tests group after any g1 paths are extracted for squash and any g4
     RocksDB paths are extracted for the RocksDB bucket. When rerunning an
     already reordered branch, commits that already appear before source group
     11 stay in their source group and "[MTR-only]" commits that already appear
     in source group 11 stay in g11 so prior "marked but not moved" decisions
     do not create a non-null diff.
  L) Commits that touch only mysql-test/ files are eligible for the g5 MTR tests
     group, except for paths that belong to g1 tokudb-test squashes or g4
     RocksDB paths. Remaining-group mysql-test-only commits are probed with git
     cherry-pick after existing g5 commits are emitted. Commits that apply
     without conflict are emitted in g5; g11 commits moved to g5 keep their
     original subject, while g11 commits that stay in Remaining get an
     "[MTR-only]" subject prefix. Later g11 commits that overlap the same files
     do not block promotion because they still replay after the promoted commit,
     matching the source ordering.
  M) Source commits whose subject starts with "[upstream]" are moved to the g8
     upstream bug fixes group after any g1 paths are extracted for squash.
  N) Remaining-group commits are probed with git cherry-pick after existing g8
     commits are emitted. Commits that apply without conflict, do not start
     with "[MTR-only]" or "[result-only]", do not match the g10 MyRocks/kernel
     subject rules, and do not patch-overlap later groups are emitted in g8
     with their original subject; conflicted, MTR-only, result-only,
     g10-subject, or later-patch-overlapped commits stay in Remaining.
  O) Paths deleted by INPUT_BRANCH are handled outside the normal buckets.
     If the path exists in BASE_BRANCH, all normal references to it are
     skipped and one dedicated commit removes all such base files. If the path
     was introduced and deleted within INPUT_BRANCH, every reference to it is
     skipped so it never appears on OUTPUT_BRANCH.
  P) Source commits whose subject starts with "[init]" are moved to the g9
     initial Percona Server tree group after any g1 paths are extracted for
     squash.
  Q) Source commits whose subject contains "MYR" or "rocks"
     (case-insensitive) are moved intact to the g10 MyRocks changes in kernel
     group unless a git cherry-pick probe reports a conflict or a later g11
     commit touches the same patch. When such a commit also contains g2/g3/g4
     paths, those dedicated portions are split first and only the remaining
     non-dedicated portion is queued for g10. Conflicted or
     later-patch-overlapped commits stay in the remaining group. When rerunning
     an already reordered branch, commits that already appear in source group 10
     stay in g10.
  R) Commits whose remaining files all end in ".result" are squashed file by
     file into the previous in-range planned item that touched each file. If a
     file's previous occurrence is only in BASE_BRANCH, it remains in the
     current commit, and that commit is tagged with a "[result-only]" subject
     prefix. Tagged "[result-only]" commits are then candidates for promotion
     to g5 alongside other mysql-test-only commits (Rule L): they keep their
     "[result-only]" subject (no "[MTR-only]" is stacked on top) and are
     emitted in g5 when the cherry-pick probe is clean and they do not
     overlap a later protected group; otherwise they stay in Remaining.
  S) The report lists source commits that were removed or elided, with the
     source hash, subject, and reason.
  V) After g5 is emitted, Remaining commits whose modified files contain no
     C/C++ or CMake source files (extensions .h .c .cc .cxx .cpp .hh .hpp .hxx
     .cmake, plus CMakeLists.txt and *.cmake.in) are candidates for the new
     g6 Non-code changes group. Each candidate is probed by a cherry-pick at
     current HEAD: candidates that conflict are held back in g11, and
     candidates whose files would overlap a later protected group
     (g7/g8/g9/g10) or an earlier-source Remaining commit are also kept in
     g11, so promotion never drifts the tree from a reference replay.
     Promoted commits land in g6 in source order. Items with code files,
     locked subjects (Rule T), or any of the above conflicts stay in g11.
  T) Source commits whose subject contains "===" are locked from any
     reordering: they skip the g5/g7/g8/g9/g10 subject routings (and the
     MyRocks/kernel "MYR"/"rocks" match), are not split into g2/g3/g4
     dedicated commits, and are also skipped by the g11 to g5 and g11 to g8
     cherry-pick promotions. The whole commit lands in g11 (or in its
     preserved source bucket when rerunning a grouped branch) as a single
     item. Only g1 squash extraction still applies, since those paths must
     be folded into the squash for null diff.
  U) A later g2/g3/g4 path is kept in Remaining if an earlier Remaining commit
     touched the same path. Remaining commits materialise whole file states, so
     moving the later dedicated path before Remaining can otherwise clobber it.

Usage:
  ps-reorder-py --input-branch <branch|hash> \
                     --output-branch <new_branch> \
                     --base-branch  <base>
                     [--force-output]
                     [--color auto|always|never]
"""

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
import time
from collections import OrderedDict, defaultdict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TITLE_LEN = 91
LARGE_COMMIT_THRESHOLD = 10000
BATCH_SIZE = 500            # max paths per git invocation
PROGRESS_EVERY = 25         # print a progress line every N split commits
OUTPUT_STAT_LINE_LEN = 104
OUTPUT_STAT_FILES_WIDTH = 5
OUTPUT_STAT_COUNT_WIDTH = 5


class Style:
    """ANSI styling for terminal output; a no-op when disabled."""

    def __init__(self, enabled=False):
        self.enabled = enabled

    def _wrap(self, code, text):
        if not self.enabled or not text:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, t): return self._wrap("1", t)
    def dim(self, t): return self._wrap("2", t)
    def red(self, t): return self._wrap("31", t)
    def green(self, t): return self._wrap("32", t)
    def yellow(self, t): return self._wrap("33", t)
    def blue(self, t): return self._wrap("34", t)
    def magenta(self, t): return self._wrap("35", t)
    def cyan(self, t): return self._wrap("36", t)
    def default(self, t): return self._wrap("39", t)
    def bold_default(self, t): return self._wrap("1;39", t)
    def bold_red(self, t): return self._wrap("1;31", t)
    def bold_magenta(self, t): return self._wrap("1;35", t)


STYLE = Style(False)


def configure_style(mode):
    """Resolve --color {auto,always,never} into STYLE.enabled."""
    if mode == "always":
        STYLE.enabled = True
        return
    if mode == "never":
        STYLE.enabled = False
        return
    if os.environ.get("NO_COLOR") is not None:
        STYLE.enabled = False
        return
    if os.environ.get("FORCE_COLOR"):
        STYLE.enabled = True
        return
    STYLE.enabled = sys.stderr.isatty()


CONFLICT_LINE_RE = re.compile(r"^(CONFLICT \([^)]+\):.*)$", re.MULTILINE)
SECTION_LINE_RE = re.compile(r"^=== .+ ===$")
SHORT_HASH_RE = re.compile(r"\b[0-9a-f]{12,40}\b")
TAG_RE = re.compile(r"(^|\s)(\[[A-Za-z0-9_.:<>\-]+(?:->[A-Za-z0-9_.:<>\-]+)?\])")
SHORTSTAT_INSERTIONS_RE = re.compile(
    r"(^|[\s/])(\+\d+[KM]?|\d+[KM]?\+)(?=[\s/]|$)")
SHORTSTAT_DELETIONS_RE = re.compile(
    r"(^|[\s/])(-\d+[KM]?|\d+[KM]?-)(?=\s|$)")
RED_STATUS_RE = re.compile(r"\b(conflict(?:ed)?|failed|failure|MISMATCH)\b")
YELLOW_STATUS_RE = re.compile(r"\b(skipped|dropped|empty|none)\b")
GREEN_STATUS_RE = re.compile(r"\b(emitted|promoted|clean|ready|passed|OK)\b")


def colorize_conflicts(text):
    """Highlight `CONFLICT (...): ...` lines in red within multi-line output."""
    if not STYLE.enabled or not text:
        return text
    return CONFLICT_LINE_RE.sub(lambda m: STYLE.red(m.group(1)), text)


def colorize_log_message(msg):
    if not STYLE.enabled or not msg:
        return msg
    if SECTION_LINE_RE.match(msg):
        return STYLE.bold(STYLE.cyan(msg))
    msg = colorize_conflicts(msg)
    msg = SHORTSTAT_INSERTIONS_RE.sub(
        lambda m: m.group(1) + STYLE.green(m.group(2)), msg)
    msg = SHORTSTAT_DELETIONS_RE.sub(
        lambda m: m.group(1) + STYLE.red(m.group(2)), msg)
    msg = SHORT_HASH_RE.sub(lambda m: STYLE.yellow(m.group(0)), msg)
    msg = TAG_RE.sub(lambda m: m.group(1) + STYLE.cyan(m.group(2)), msg)
    msg = RED_STATUS_RE.sub(lambda m: STYLE.red(m.group(0)), msg)
    msg = YELLOW_STATUS_RE.sub(lambda m: STYLE.yellow(m.group(0)), msg)
    msg = GREEN_STATUS_RE.sub(lambda m: STYLE.green(m.group(0)), msg)
    return msg


def short_sha(sha):
    return STYLE.yellow(sha[:12])


def styled_path(path):
    return STYLE.magenta(path)


def log(msg):
    print(colorize_log_message(msg), file=sys.stderr, flush=True)


def log_error(msg):
    print(f"{STYLE.bold(STYLE.red('error:'))} {colorize_conflicts(msg)}",
          file=sys.stderr, flush=True)

G1_DOC = 'doc'
G1_MAN = 'man'
G1_INTERNAL = 'internal'
G1_TOKUDB_BACKUP = 'tokudb-backup-plugin'
G1_STORAGE_TOKUDB = 'storage-tokudb'
G1_VERSION_UNIV = 'version-univ'
G1_TOKUDB_TESTS = 'tokudb-tests'

G1_SUBJECTS = {
    G1_DOC:             'Squash: doc/',
    G1_MAN:             'Squash: man/',
    G1_INTERNAL:        'Squash: internal/',
    G1_TOKUDB_BACKUP:   'Squash: plugin/tokudb-backup-plugin/',
    G1_STORAGE_TOKUDB:  'Squash: storage/tokudb/',
    G1_VERSION_UNIV:    'Squash: MYSQL_VERSION, VERSION and storage/innobase/include/univ.i',
    G1_TOKUDB_TESTS:    'Squash: mysql-test/suite/tokudb* and MTR *toku* tests',
}

DEDICATED_GROUP_NUMBERS = {
    'g2': 2,
    'g3': 3,
    'g4': 4,
}

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def run_git(args, check=True, env=None, retry_on_lock=True):
    retries = 3 if retry_on_lock else 1
    last = None
    for attempt in range(retries):
        last = subprocess.run(
            ['git'] + list(args),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
        )
        if last.returncode == 0:
            return last
        if retry_on_lock and 'index.lock' in (last.stdout + last.stderr):
            time.sleep(0.5 * (attempt + 1))
            continue
        break
    if check and last.returncode != 0:
        argv = ['git'] + list(args)
        preview = ' '.join(argv[:6] + ['...', f'({len(argv)-6} more args)']) \
            if len(argv) > 10 else ' '.join(argv)
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


def ensure_clean_worktree():
    r = run_git(['status', '--porcelain'], check=False)
    if r.stdout.strip():
        raise RuntimeError(
            "Working tree is not clean. Commit or stash changes first "
            "(or pass --allow-dirty).")


def get_current_branch():
    r = run_git(['symbolic-ref', '--short', '-q', 'HEAD'], check=False)
    return r.stdout.strip() or None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


CODE_EXTENSIONS = ('.h', '.c', '.cc', '.cxx', '.cpp',
                   '.hh', '.hpp', '.hxx', '.cmake')


def is_code_file(path):
    if path.endswith(CODE_EXTENSIONS):
        return True
    base = os.path.basename(path)
    return base == 'CMakeLists.txt' or base.endswith('.cmake.in')


def commit_has_no_code_files(files):
    return bool(files) and not any(is_code_file(p) for p in files)


def classify_file(path):
    """Return a (group, subkey) tuple for a single file path."""
    # g1 — explicit subcategories
    if path.startswith('doc/'):
        return ('g1', G1_DOC)
    if path.startswith('man/'):
        return ('g1', G1_MAN)
    if path.startswith('internal/'):
        return ('g1', G1_INTERNAL)
    if path.startswith('plugin/tokudb-backup-plugin/'):
        return ('g1', G1_TOKUDB_BACKUP)
    if path.startswith('storage/tokudb/'):
        return ('g1', G1_STORAGE_TOKUDB)
    if (path == 'MYSQL_VERSION' or path == 'VERSION' or
            path == 'storage/innobase/include/univ.i'):
        return ('g1', G1_VERSION_UNIV)
    if is_tokudb_mtr_test_path(path):
        return ('g1', G1_TOKUDB_TESTS)

    # g2 — build-ps
    if path.startswith('build-ps/'):
        return ('g2', None)

    # g3 — CI configuration
    if (path == '.travis.yml' or
            path.startswith('.circleci/') or
            path == 'azure-pipelines.yml' or
            path == '.cirrus.yml' or
            path == '.clang-tidy'):
        return ('g3', None)

    # g4 — RocksDB
    if path.startswith('storage/rocksdb'):
        return ('g4', None)
    if path.startswith('mysql-test/suite/rocksdb'):
        return ('g4', None)

    # g11 — remaining
    return ('g11', None)


def is_tokudb_mtr_test_path(path):
    basename = os.path.basename(path)
    return (path.startswith('mysql-test/suite/tokudb') or
            (path.startswith('mysql-test/') and 'toku' in basename.lower()))


# ---------------------------------------------------------------------------
# Commit inspection
# ---------------------------------------------------------------------------


def get_commit_list(base, head):
    """Return commit hashes on head's first-parent line since base, oldest first."""
    r = run_git(['log', '--first-parent', '--reverse', '--format=%H',
                 f'{base}..{head}'])
    return [line for line in r.stdout.strip().split('\n') if line]


def get_commit_parents(ch):
    r = run_git(['rev-list', '--parents', '-n', '1', ch])
    parts = r.stdout.strip().split()
    return parts[1:] if len(parts) > 1 else []


def get_commit_files(ch):
    """Files modified by ch compared to its first parent (or the full tree for
    a root commit). Renames are not followed — both old and new path appear."""
    parents = get_commit_parents(ch)
    if not parents:
        r = run_git(['ls-tree', '-r', '--name-only', ch])
        return [f for f in r.stdout.strip().split('\n') if f]
    parent = parents[0]
    r = run_git(['diff', '--name-only', '--no-renames', parent, ch])
    return [f for f in r.stdout.strip().split('\n') if f]


def get_commit_deleted_paths(ch):
    """Return paths deleted by ch compared to its first parent."""
    parents = get_commit_parents(ch)
    if not parents:
        return []
    parent = parents[0]
    r = run_git(['diff', '--name-only', '--diff-filter=D', '--no-renames',
                 parent, ch])
    return [f for f in r.stdout.strip().split('\n') if f]


def get_commit_info(ch):
    sep = '\x1f'          # ASCII unit separator
    fmt = sep.join(['%H', '%an', '%ae', '%aI',
                    '%cn', '%ce', '%cI', '%s', '%B'])
    r = run_git(['show', '-s', f'--format={fmt}', ch])
    raw = r.stdout.rstrip('\n')
    parts = raw.split(sep, 8)
    full = parts[8].rstrip('\n') if len(parts) > 8 else parts[7]
    # Body (everything after the subject line)
    body_rest = ''
    if '\n' in full:
        body_rest = full.split('\n', 1)[1].lstrip('\n')
    return {
        'hash':             parts[0],
        'author_name':      parts[1],
        'author_email':     parts[2],
        'author_date':      parts[3],
        'committer_name':   parts[4],
        'committer_email':  parts[5],
        'committer_date':   parts[6],
        'subject':          parts[7],
        'body_rest':        body_rest,
    }


def get_commit_shortstat(ch):
    r = run_git(['show', '--format=', '--shortstat', ch])
    text = r.stdout.strip()
    ins = 0
    dele = 0
    m = re.search(r'(\d+) insertion', text)
    if m:
        ins = int(m.group(1))
    m = re.search(r'(\d+) deletion', text)
    if m:
        dele = int(m.group(1))
    return ins, dele


def get_commit_shortstat_text(ch):
    r = run_git(['show', '--format=', '--shortstat', '--no-renames', ch])
    text = ' '.join(r.stdout.split())
    return text if text else '0 files changed'


def get_commit_shortstat_details(ch):
    text = get_commit_shortstat_text(ch)
    files = 0
    ins = 0
    dele = 0
    m = re.search(r'(\d+) files? changed', text)
    if m:
        files = int(m.group(1))
    m = re.search(r'(\d+) insertion', text)
    if m:
        ins = int(m.group(1))
    m = re.search(r'(\d+) deletion', text)
    if m:
        dele = int(m.group(1))
    return files, ins, dele


def compact_count(n):
    if n >= 1000000:
        return f"{n // 1000000}M"
    if n >= 10000:
        return f"{n // 1000}K"
    return str(n)


def truncate_line(line, max_len=MAX_TITLE_LEN):
    return line[:max_len]


def format_output_commit_stats_line(files, ins, dele, ch, subject):
    files_field = f"{compact_count(files)}f".ljust(OUTPUT_STAT_FILES_WIDTH)
    ins_field = f"{compact_count(ins)}+".rjust(OUTPUT_STAT_COUNT_WIDTH)
    del_field = f"{compact_count(dele)}-".rjust(OUTPUT_STAT_COUNT_WIDTH)
    line = f"{files_field}{ins_field} {del_field} {ch[:12]} {subject}"
    return truncate_line(line, OUTPUT_STAT_LINE_LEN)


def subject_style(text, bold=False, red=False, blue=False, magenta=False):
    if magenta and bold:
        return STYLE.bold_magenta(text)
    if magenta:
        return STYLE.magenta(text)
    if blue:
        return STYLE.blue(text)
    if red and bold:
        return STYLE.bold_red(text)
    if red:
        return STYLE.red(text)
    return STYLE.bold_default(text) if bold else STYLE.default(text)


def colorize_output_commit_stats_line(line, bold_subject=False,
                                      red_subject=False, blue_subject=False,
                                      magenta_subject=False):
    if not STYLE.enabled:
        return line
    m = re.match(r"^(\S+)(\s+)(\S+)(\s+)(\S+)(\s+)"
                 r"([0-9a-f]{12})(\s?)(.*)$", line)
    if not m:
        return colorize_log_message(line)
    return (
        m.group(1) + m.group(2) +
        STYLE.green(m.group(3)) + m.group(4) +
        STYLE.red(m.group(5)) + m.group(6) +
        STYLE.yellow(m.group(7)) + m.group(8) +
        subject_style(m.group(9), bold_subject, red_subject, blue_subject,
                      magenta_subject))


def log_output_commit_stats(ch):
    files, ins, dele = get_commit_shortstat_details(ch)
    subject = get_commit_subject(ch)
    line = format_output_commit_stats_line(files, ins, dele, ch, subject)
    print(colorize_output_commit_stats_line(
        line, ins + dele <= 8, dele > ins,
        ins + dele > LARGE_COMMIT_THRESHOLD),
          file=sys.stderr, flush=True)


def get_commit_subject(ch):
    return run_git(['show', '-s', '--format=%s', ch]).stdout.rstrip('\n')


# ---------------------------------------------------------------------------
# File-state application
# ---------------------------------------------------------------------------


def batched(paths, size=BATCH_SIZE):
    for i in range(0, len(paths), size):
        yield paths[i:i + size]


def classify_existence(source_hash, paths):
    """Split `paths` into (present_at_source, absent_at_source) using one
    `ls-tree` call per batch — far cheaper than calling ls-tree per file."""
    if not paths:
        return [], []
    present = set()
    # Unique paths for probing (git ls-tree doesn't mind duplicates but we do).
    uniq = list({p for p in paths})
    for batch in batched(uniq):
        r = run_git(['ls-tree', source_hash, '--'] + batch, check=False)
        for line in r.stdout.split('\n'):
            if not line:
                continue
            # format: "<mode> <type> <sha>\t<path>"
            tab = line.find('\t')
            if tab >= 0:
                present.add(line[tab + 1:])
    present_list = [p for p in paths if p in present]
    absent_list = [p for p in paths if p not in present]
    return present_list, absent_list


class PathExistenceCache:
    """Cache path existence checks for a single tree-ish."""

    def __init__(self, source_hash):
        self.source_hash = source_hash
        self._present = {}

    def split(self, paths):
        unknown = [p for p in set(paths) if p not in self._present]
        if unknown:
            present, absent = classify_existence(self.source_hash, unknown)
            for p in present:
                self._present[p] = True
            for p in absent:
                self._present[p] = False
        return ([p for p in paths if self._present[p]],
                [p for p in paths if not self._present[p]])


def checkout_paths(source_hash, paths):
    """Batch-materialise `paths` in the index + working tree from source_hash."""
    if not paths:
        return
    for batch in batched(paths):
        run_git(['checkout', source_hash, '--'] + batch)


def remove_paths(paths):
    """Batch-remove `paths` from the index + working tree, tolerating absence."""
    if not paths:
        return
    for batch in batched(paths):
        run_git(['rm', '-rf', '--quiet', '--ignore-unmatch', '--'] + batch,
                check=False)
    for p in paths:
        if os.path.lexists(p):
            try:
                os.unlink(p)
            except OSError:
                pass


def apply_file_states(source_hash, paths):
    """Make each path in `paths` match its state at source_hash, in batches.
    A path present at source is checked out; a path absent from source is
    removed. Works efficiently for thousands of files."""
    present, absent = classify_existence(source_hash, paths)
    checkout_paths(source_hash, present)
    remove_paths(absent)


def apply_item_file_states(item):
    source_by_file = item.get('source_by_file') or {}
    if not source_by_file:
        apply_file_states(item['source_hash'], item['files'])
        return

    paths_by_source = defaultdict(list)
    for path in item['files']:
        paths_by_source[source_by_file.get(path, item['source_hash'])].append(path)
    for source_hash, paths in paths_by_source.items():
        apply_file_states(source_hash, paths)


# ---------------------------------------------------------------------------
# Commit building
# ---------------------------------------------------------------------------


def build_full_message(subject, body_rest, original_subject=None):
    """Apply Rule D: truncate subjects >91 chars, preserve original in body."""
    if len(subject) <= MAX_TITLE_LEN and not original_subject:
        return subject + ('\n\n' + body_rest if body_rest.strip() else '')
    truncated = subject[:MAX_TITLE_LEN]
    body = f"Original title:\n{original_subject or subject}"
    if body_rest.strip():
        body += '\n\n' + body_rest
    return truncated + '\n\n' + body


def truncate_with_suffix(subject, suffix):
    """Return subject + suffix, ensuring total length <= MAX_TITLE_LEN."""
    if len(subject) + len(suffix) <= MAX_TITLE_LEN:
        return subject + suffix
    return subject[:MAX_TITLE_LEN - len(suffix)] + suffix


def truncate_with_suffix_and_original(subject, suffix):
    full_subject = subject + suffix
    truncated = truncate_with_suffix(subject, suffix)
    original_subject = full_subject if truncated != full_subject else None
    return truncated, original_subject


SPLIT_SUBJECT_SUFFIXES = (' [MyRocks part]', ' [non-MyRocks part]')


def split_preserved_subject_suffix(subject):
    for suffix in SPLIT_SUBJECT_SUFFIXES:
        if subject.endswith(suffix):
            return subject[:-len(suffix)], suffix
    return subject, ''


def do_commit(info, subject, body_rest='', allow_empty=False,
              original_subject=None):
    """Commit the staged index with author/committer info. Returns True on
    success, False if there was nothing to commit."""
    message = build_full_message(subject, body_rest, original_subject)

    env = os.environ.copy()
    env['GIT_AUTHOR_NAME']     = info['author_name']
    env['GIT_AUTHOR_EMAIL']    = info['author_email']
    env['GIT_AUTHOR_DATE']     = info['author_date']
    env['GIT_COMMITTER_NAME']  = info['committer_name']
    env['GIT_COMMITTER_EMAIL'] = info['committer_email']
    env['GIT_COMMITTER_DATE']  = info['committer_date']

    cmd = ['commit', '-m', message]
    if allow_empty:
        cmd.append('--allow-empty')
    if not message.strip():
        # Source commit had an empty subject; preserve that by allowing it.
        cmd.append('--allow-empty-message')
    r = run_git(cmd, check=False, env=env)
    if r.returncode != 0:
        combined = (r.stdout + r.stderr).lower()
        if ('nothing to commit' in combined or
                'nothing added to commit' in combined or
                'no changes added' in combined):
            return False
        raise RuntimeError(
            f"git commit failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    log_output_commit_stats(git_rev_parse('HEAD'))
    return True


MARKER_AUTHOR = {
    'author_name':     'ps-reorder',
    'author_email':    'ps-reorder@local',
    'author_date':     '1970-01-01T00:00:00+00:00',
    'committer_name':  'ps-reorder',
    'committer_email': 'ps-reorder@local',
    'committer_date':  '1970-01-01T00:00:00+00:00',
}


def marker_commit(number, name, description=''):
    subject = (f"==================== MARKER: GROUP {number} — {name} "
               "====================")
    body = description
    # marker author/date is arbitrary; keep current HEAD date so the commit is
    # visible in log in insertion order.
    env = os.environ.copy()
    for k in ('GIT_AUTHOR_DATE', 'GIT_COMMITTER_DATE'):
        env.pop(k, None)
    r = run_git(['commit', '--allow-empty',
                 '-m', build_full_message(subject, body)], env=env)
    log_output_commit_stats(git_rev_parse('HEAD'))
    return r


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def is_compilation_group_subject(subject):
    return subject.startswith('[compilation]')


def is_mtr_only_group_subject(subject):
    return subject.startswith('[MTR-only]')


def is_result_only_group_subject(subject):
    return subject.startswith('[result-only]')


def is_upstream_bug_fix_group_subject(subject):
    return subject.startswith('[upstream]')


def is_init_group_subject(subject):
    return subject.startswith('[init]')


GROUP_NAME_TO_NUMBER = {
    'Squashes': 1,
    'build-ps': 2,
    'CI configs': 3,
    'RocksDB': 4,
    'MTR tests': 5,
    'Non-code changes': 6,
    'Build/Compilation': 7,
    'Upstream bug fixes': 8,
    'Initial Percona Server tree': 9,
    'MyRocks changes in kernel': 10,
    'Remaining': 11,
}

_MARKER_RE = re.compile(r'^={3,} MARKER: GROUP \d+ — (.+?) ={3,}$')


def marker_group_number(subject):
    """Resolve a marker subject to its new-scheme group number via name lookup,
    so re-running on a previously grouped branch with the old 1-10 numbering
    (Build/Compilation=6, ..., Remaining=10) still maps to the right buckets."""
    m = _MARKER_RE.match(subject)
    if not m:
        return None
    return GROUP_NAME_TO_NUMBER.get(m.group(1).strip())


def is_myrocks_kernel_group_subject(subject):
    sl = subject.lower()
    return 'myr' in sl or 'rocks' in sl


def is_locked_from_promotion(subject):
    """Subjects containing '===' opt out of subject-based moves and g11
    promotions; the commit stays in whichever bucket it would land in by
    file-content partitioning alone (Rule T)."""
    return '===' in subject


def is_mysql_test_only_commit(files):
    return touches_only_mysql_test(files)


def contains_g1_paths(files):
    return any(classify_file(path)[0] == 'g1' for path in files)


def add_g1_files_to_plan(plan, cat, files, info, idx):
    plan['g1_files'][cat].update(files)
    if cat not in plan['g1_first_info']:
        plan['g1_first_info'][cat] = info
        plan['g1_first_pos'][cat] = idx


def split_out_g1_files(files):
    g1_part = defaultdict(list)
    other_files = []
    for path in files:
        grp, sub = classify_file(path)
        if grp == 'g1':
            g1_part[sub].append(path)
        else:
            other_files.append(path)
    return g1_part, other_files


def split_out_group_files(files, group):
    group_files = []
    other_files = []
    for path in files:
        grp, _sub = classify_file(path)
        if grp == group:
            group_files.append(path)
        else:
            other_files.append(path)
    return group_files, other_files


def is_result_file(path):
    return path.endswith('.result')


def is_result_only_commit(files):
    return bool(files) and all(is_result_file(path) for path in files)


def is_result_only_item(item):
    return item.get('result_only') or is_result_only_group_subject(
        item['subject'])


def source_group_bucket_name(source_group):
    if source_group is None or source_group < 2 or source_group > 10:
        return None
    return f"g{source_group}_bucket"


def is_preserved_source_group_item(item):
    return source_group_bucket_name(item.get('source_group')) is not None


def item_source_cache_key(item):
    source_by_file = item.get('source_by_file') or {}
    source_history_by_file = item.get('source_history_by_file') or {}
    source_history_key = tuple(
        (path, tuple(sources))
        for path, sources in sorted(source_history_by_file.items()))
    return (item['source_hash'],
            tuple(sorted(item['files'])),
            tuple(sorted(source_by_file.items())),
            source_history_key)


def add_file_source_override(item, path, source_hash):
    if path not in item['files']:
        item['files'].append(path)
    source_history_by_file = item.setdefault('source_history_by_file', {})
    source_history_by_file.setdefault(path, [item['source_hash']]).append(
        source_hash)
    item.setdefault('source_by_file', {})[path] = source_hash


def register_result_file_occurrences(item, result_file_last_item):
    for path in item['files']:
        if is_result_file(path):
            result_file_last_item[path] = item


def append_plan_item(bucket, item, result_file_last_item):
    bucket.append(item)
    register_result_file_occurrences(item, result_file_last_item)


def record_removed_commit_entry(entries, source_hash, subject, reason):
    entries.append({
        'hash': source_hash,
        'subject': subject,
        'reason': reason,
    })


def record_removed_commit(plan, info, reason, source_hash=None, subject=None):
    record_removed_commit_entry(
        plan['removed_commits'],
        source_hash or info['hash'],
        subject if subject is not None else info['subject'],
        reason)


def record_removed_item(entries, item, reason):
    info = item['info']
    record_removed_commit_entry(
        entries,
        item.get('source_hash') or info['hash'],
        info['subject'],
        reason)


def squash_result_files_into_previous(files, source_hash, result_file_last_item):
    remaining = []
    squashed = 0
    for path in files:
        previous_item = result_file_last_item.get(path)
        if previous_item is None:
            remaining.append(path)
            continue
        add_file_source_override(previous_item, path, source_hash)
        squashed += 1
    return remaining, squashed


def final_removed_base_paths(base_hash, input_hash):
    """Paths present in BASE_BRANCH and absent from INPUT_BRANCH."""
    r = run_git(['diff', '--name-only', '--diff-filter=D', '--no-renames',
                 base_hash, input_hash])
    return set(f for f in r.stdout.strip().split('\n') if f)


def analyze_removed_paths(commits, base_hash, input_hash):
    """Classify deleted paths before planning normal output commits."""
    base_removed = final_removed_base_paths(base_hash, input_hash)
    deleted_in_range = set()
    first_base_removal_info = None

    for ch in commits:
        deleted = set(get_commit_deleted_paths(ch))
        if not deleted:
            continue
        deleted_in_range.update(deleted)
        if first_base_removal_info is None and deleted.intersection(base_removed):
            first_base_removal_info = get_commit_info(ch)

    transient_candidates = deleted_in_range.difference(base_removed)
    _base_present, absent_in_base = classify_existence(
        base_hash, transient_candidates)
    _input_present, absent_in_input = classify_existence(
        input_hash, absent_in_base)
    transient_removed = set(absent_in_input)

    if base_removed and first_base_removal_info is None:
        first_base_removal_info = get_commit_info(commits[-1]) \
            if commits else MARKER_AUTHOR

    return {
        'base_removed': base_removed,
        'transient_removed': transient_removed,
        'base_removal_info': first_base_removal_info,
    }


def collect_later_preserved_group_paths(commits, skipped_paths):
    """Paths touched by preserved source groups that emit after g2/g3/g4.

    On already grouped input branches, source group 11 commits are final
    corrections. Pulling their g2/g3/g4 paths before a preserved later group can
    let that later group's full file-state replay overwrite the correction.
    """
    later_paths = {group: set() for group in DEDICATED_GROUP_NUMBERS}
    source_group = None
    skipped_paths = set(skipped_paths)
    for ch in commits:
        info = get_commit_info(ch)
        marker_group = marker_group_number(info['subject'])
        if marker_group is not None:
            source_group = marker_group
            continue
        if source_group_bucket_name(source_group) is None:
            continue
        files = [f for f in get_commit_files(ch) if f not in skipped_paths]
        for group, group_number in DEDICATED_GROUP_NUMBERS.items():
            if source_group > group_number:
                later_paths[group].update(files)
    return later_paths


def keep_clobbered_dedicated_paths_in_remaining(files, clobber_paths):
    dedicated = []
    remaining = []
    for path in files:
        if path in clobber_paths:
            remaining.append(path)
        else:
            dedicated.append(path)
    return dedicated, remaining


def log_removed_paths(removed_paths):
    """Print every removed path, grouped by output handling."""
    base_removed = sorted(removed_paths['base_removed'])
    transient_removed = sorted(removed_paths['transient_removed'])

    log("Removed files present in BASE_BRANCH "
        "(will be removed in one commit):")
    if base_removed:
        for path in base_removed:
            log(f"  {styled_path(path)}")
    else:
        log("  (none)")

    log("Removed files introduced by INPUT_BRANCH "
        "(will be skipped entirely):")
    if transient_removed:
        for path in transient_removed:
            log(f"  {styled_path(path)}")
    else:
        log("  (none)")


def plan_commits(commits, base_hash, removed_paths):
    """Walk the commit list once and produce the plan for the output branch."""
    base_removed = set(removed_paths['base_removed'])
    transient_removed = set(removed_paths['transient_removed'])
    skipped_paths = base_removed.union(transient_removed)
    later_preserved_group_paths = collect_later_preserved_group_paths(
        commits, skipped_paths)
    plan = {
        'g1_files':       defaultdict(set),   # cat  -> set(files)
        'g1_first_info':  {},                 # cat  -> info
        'g1_first_pos':   {},                 # cat  -> int
        'g2_bucket':      [],
        'g3_bucket':      [],
        'g4_bucket':      [],
        'g5_bucket':      [],
        'g6_bucket':      [],
        'g7_bucket':      [],
        'g8_bucket':      [],
        'g9_bucket':      [],
        'g10_bucket':      [],
        'g11_bucket':     [],
        'n_source_commits': len(commits),
        'base_removed_files': sorted(base_removed),
        'transient_removed_files': sorted(transient_removed),
        'base_removal_info': removed_paths['base_removal_info'],
        'base_removed_refs_skipped': 0,
        'transient_removed_refs_skipped': 0,
        'result_only_files_squashed': 0,
        'result_only_commits_elided': 0,
        'result_only_base_files_kept': 0,
        'result_only_base_commits_kept': 0,
        'removed_commits': [],
    }

    total = len(commits)
    t0 = time.monotonic()
    source_group = None
    result_file_last_item = {}
    base_existence = PathExistenceCache(base_hash)
    prior_remaining_paths = set()

    def append_bucket_item(bucket_name, item):
        append_plan_item(plan[bucket_name], item, result_file_last_item)
        if bucket_name == 'g11_bucket':
            prior_remaining_paths.update(item['files'])

    for idx, ch in enumerate(commits):
        done = idx + 1
        if done % 200 == 0 or done == total:
            elapsed = time.monotonic() - t0
            rate = done / elapsed if elapsed > 0 else 0.0
            log(f"  planning {done}/{total} commits  ({rate:5.1f}/s)")
        info = get_commit_info(ch)
        marker_group = marker_group_number(info['subject'])
        if marker_group is not None:
            source_group = marker_group
            record_removed_commit(
                plan, info,
                f"source marker for group {marker_group} omitted; "
                "output markers are regenerated")
            continue
        files = get_commit_files(ch)
        if skipped_paths:
            base_refs = sum(1 for f in files if f in base_removed)
            transient_refs = sum(1 for f in files if f in transient_removed)
            plan['base_removed_refs_skipped'] += base_refs
            plan['transient_removed_refs_skipped'] += transient_refs
            files = [f for f in files if f not in skipped_paths]
        if not files:
            if skipped_paths and (base_refs or transient_refs):
                details = []
                if base_refs:
                    details.append(
                        f"{base_refs} base-removed file reference(s)")
                if transient_refs:
                    details.append(
                        f"{transient_refs} input-only removed file reference(s)")
                record_removed_commit(
                    plan, info,
                    "all modified paths were skipped because they are absent "
                    f"from INPUT_BRANCH ({', '.join(details)})")
            else:
                record_removed_commit(
                    plan, info,
                    "source commit has no file changes relative to its first "
                    "parent")
            continue

        source_group_bucket = source_group_bucket_name(source_group)
        if source_group_bucket is not None:
            # Split g1 paths into the G1 squash so its INPUT-final state is
            # not clobbered when this preserved group's whole-commit replay
            # emits later.
            g1_part, files = split_out_g1_files(files)
            for cat, fl in g1_part.items():
                add_g1_files_to_plan(plan, cat, fl, info, idx)

            # For preserved groups that emit AFTER a dedicated bucket (g5+
            # follows g2/g3/g4), peel off any g2/g3/g4 paths so the dedicated
            # bucket's source-ordered last writer remains correct.
            split_dedicated = []
            if source_group >= 5:
                for grp in ('g2', 'g3', 'g4'):
                    grp_part, files = split_out_group_files(files, grp)
                    if grp_part:
                        split_dedicated.append((grp, grp_part))

            preserved_subject = info['subject']
            preserved_original_subject = None
            if any(grp == 'g4' for grp, _ in split_dedicated) and files:
                preserved_subject, preserved_original_subject = (
                    truncate_with_suffix_and_original(
                        info['subject'], ' [non-MyRocks part]'))

            for grp, grp_part in split_dedicated:
                subj = info['subject']
                original_subject = None
                if grp == 'g4' and files:
                    subj, original_subject = (
                        truncate_with_suffix_and_original(
                            info['subject'], ' [MyRocks part]'))
                append_bucket_item(f'{grp}_bucket', {
                    'info': info,
                    'files': list(grp_part),
                    'subject': subj,
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_pos': idx,
                    'source_group': source_group,
                    'original_subject': original_subject,
                })

            if files:
                append_bucket_item(source_group_bucket, {
                    'info': info,
                    'files': list(files),
                    'subject': preserved_subject,
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_pos': idx,
                    'source_group': source_group,
                    'original_subject': preserved_original_subject,
                })
            elif g1_part or split_dedicated:
                record_removed_commit(
                    plan, info,
                    f"all paths from source group {source_group} routed to "
                    "g1 squashes and/or earlier dedicated buckets")
            continue

        g1_part, non_g1_files = split_out_g1_files(files)
        for cat, fl in g1_part.items():
            add_g1_files_to_plan(plan, cat, fl, info, idx)
        files = non_g1_files
        if g1_part and not files:
            cats = ', '.join(sorted(g1_part))
            record_removed_commit(
                plan, info,
                f"all remaining paths were folded into g1 squash(es): {cats}")
            continue

        if is_result_only_commit(files):
            result_files_before_squash = list(files)
            files, squashed = squash_result_files_into_previous(
                files, ch, result_file_last_item)
            plan['result_only_files_squashed'] += squashed
            if not files:
                plan['result_only_commits_elided'] += 1
                record_removed_commit(
                    plan, info,
                    f"all {len(result_files_before_squash)} .result path(s) "
                    "were squashed into previous in-range commit(s)")
                continue
            base_result_files, files = base_existence.split(files)
            if base_result_files:
                plan['result_only_base_files_kept'] += len(base_result_files)
                plan['result_only_base_commits_kept'] += 1
                result_subject, original_subject = add_subject_prefix_with_original(
                    info['subject'], '[result-only]', space_before_plain=True)
                append_bucket_item('g11_bucket', {
                    'info': info,
                    'files': list(base_result_files),
                    'subject': result_subject,
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_pos': idx,
                    'source_group': source_group,
                    'result_only': True,
                    'original_subject': original_subject,
                })
            if not files:
                continue

        locked_subject = is_locked_from_promotion(info['subject'])

        mtr_like_commit = (is_mtr_only_group_subject(info['subject']) or
                           is_mysql_test_only_commit(files))
        if mtr_like_commit and not locked_subject:
            g4_files, files = split_out_group_files(files, 'g4')
            if g4_files:
                append_bucket_item('g4_bucket', {
                    'info': info,
                    'files': list(g4_files),
                    'subject': info['subject'],
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_group': source_group,
                })
            if not files:
                continue

        if is_compilation_group_subject(info['subject']) and not locked_subject:
            if files:
                append_bucket_item('g7_bucket', {
                    'info': info,
                    'files': list(files),
                    'subject': info['subject'],
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_group': source_group,
                })
            continue
        if is_mtr_only_group_subject(info['subject']) and not locked_subject:
            if files:
                target_bucket = 'g11_bucket' if source_group == 11 else 'g5_bucket'
                append_bucket_item(target_bucket, {
                    'info': info,
                    'files': list(files),
                    'subject': info['subject'],
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_pos': idx,
                    'source_group': source_group,
                })
            continue
        if (is_mysql_test_only_commit(files) and not contains_g1_paths(files)
                and not locked_subject):
            append_bucket_item('g11_bucket', {
                'info': info,
                'files': list(files),
                'subject': info['subject'],
                'body_rest': info['body_rest'],
                'source_hash': ch,
                'source_pos': idx,
                'source_group': source_group,
                'mtr_only_candidate': True,
            })
            continue
        if is_upstream_bug_fix_group_subject(info['subject']) and not locked_subject:
            if files:
                append_bucket_item('g8_bucket', {
                    'info': info,
                    'files': list(files),
                    'subject': info['subject'],
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_group': source_group,
                })
            continue
        if is_init_group_subject(info['subject']) and not locked_subject:
            if files:
                append_bucket_item('g9_bucket', {
                    'info': info,
                    'files': list(files),
                    'subject': info['subject'],
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_group': source_group,
                })
            continue

        # Partition by group
        g2_part, g3_part, g4_part = [], [], []
        g11_part = []
        for f in files:
            grp, sub = classify_file(f)
            if grp == 'g2':
                g2_part.append(f)
            elif grp == 'g3':
                g3_part.append(f)
            elif grp == 'g4':
                g4_part.append(f)
            else:
                g11_part.append(f)

        myrocks_kernel_subject = (
            is_myrocks_kernel_group_subject(info['subject'])
            and not locked_subject)

        dedicated_forced_remaining = False
        g2_part, unsafe = keep_clobbered_dedicated_paths_in_remaining(
            g2_part, prior_remaining_paths)
        dedicated_forced_remaining = dedicated_forced_remaining or bool(unsafe)
        g11_part.extend(unsafe)
        g3_part, unsafe = keep_clobbered_dedicated_paths_in_remaining(
            g3_part, prior_remaining_paths)
        dedicated_forced_remaining = dedicated_forced_remaining or bool(unsafe)
        g11_part.extend(unsafe)
        g4_part, unsafe = keep_clobbered_dedicated_paths_in_remaining(
            g4_part, prior_remaining_paths)
        dedicated_forced_remaining = dedicated_forced_remaining or bool(unsafe)
        g11_part.extend(unsafe)

        if source_group == 11:
            g2_part, unsafe = keep_clobbered_dedicated_paths_in_remaining(
                g2_part, later_preserved_group_paths['g2'])
            dedicated_forced_remaining = dedicated_forced_remaining or bool(unsafe)
            g11_part.extend(unsafe)
            g3_part, unsafe = keep_clobbered_dedicated_paths_in_remaining(
                g3_part, later_preserved_group_paths['g3'])
            dedicated_forced_remaining = dedicated_forced_remaining or bool(unsafe)
            g11_part.extend(unsafe)
            g4_part, unsafe = keep_clobbered_dedicated_paths_in_remaining(
                g4_part, later_preserved_group_paths['g4'])
            dedicated_forced_remaining = dedicated_forced_remaining or bool(unsafe)
            g11_part.extend(unsafe)

        if locked_subject and (g2_part or g3_part or g4_part):
            # Rule T — locked commits stay intact, no g2/g3/g4 split.
            g11_part.extend(g2_part)
            g11_part.extend(g3_part)
            g11_part.extend(g4_part)
            g2_part, g3_part, g4_part = [], [], []

        has_g234 = bool(g2_part or g3_part or g4_part)

        if myrocks_kernel_subject and not has_g234 and not dedicated_forced_remaining:
            append_bucket_item('g10_bucket', {
                'info': info,
                'files': list(files),
                'subject': info['subject'],
                'body_rest': info['body_rest'],
                'source_hash': ch,
                'source_pos': idx,
                'source_group': source_group,
            })
            continue

        if has_g234:
            # Rule F — split g2/g3/g4 as dedicated commits; the remainder stays
            # in g11 except MYR/rocks subjects whose non-dedicated portion
            # belongs in g10.
            if g2_part:
                append_bucket_item('g2_bucket', {
                    'info': info,
                    'files': list(g2_part),
                    'subject': info['subject'],
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_group': source_group,
                })
            if g3_part:
                append_bucket_item('g3_bucket', {
                    'info': info,
                    'files': list(g3_part),
                    'subject': info['subject'],
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_group': source_group,
                })
            if g4_part:
                # "[MyRocks part]" suffix for the g4+g11 split per rule F.
                subj = info['subject']
                original_subject = None
                if g11_part:
                    subj, original_subject = truncate_with_suffix_and_original(
                        info['subject'], ' [MyRocks part]')
                append_bucket_item('g4_bucket', {
                    'info': info,
                    'files': list(g4_part),
                    'subject': subj,
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_group': source_group,
                    'original_subject': original_subject,
                })
            if g11_part:
                subj = info['subject']
                original_subject = None
                if g4_part:
                    subj, original_subject = truncate_with_suffix_and_original(
                        info['subject'], ' [non-MyRocks part]')
                target_bucket = 'g10_bucket' if myrocks_kernel_subject else 'g11_bucket'
                append_bucket_item(target_bucket, {
                    'info': info,
                    'files': list(g11_part),
                    'subject': subj,
                    'body_rest': info['body_rest'],
                    'source_hash': ch,
                    'source_pos': idx,
                    'source_group': source_group,
                    'original_subject': original_subject,
                })
        elif g11_part:
            # No g2/g3/g4; just emit g11.
            append_bucket_item('g11_bucket', {
                'info': info,
                'files': list(g11_part),
                'subject': info['subject'],
                'body_rest': info['body_rest'],
                'source_hash': ch,
                'source_pos': idx,
                'source_group': source_group,
            })

    return plan


# ---------------------------------------------------------------------------
# Output branch construction
# ---------------------------------------------------------------------------


def is_git_conflict_output(text):
    tl = text.lower()
    return any(token in tl for token in (
        'conflict',
        'would be overwritten',
        'unmerged',
        'needs merge',
    ))


def is_non_conflict_cherry_pick_failure(text):
    tl = text.lower()
    return ('is a merge but no -m option was given' in tl or
            'cherry-pick is now empty' in tl or
            'previous cherry-pick is now empty' in tl or
            'nothing to commit' in tl)


def can_move_without_git_conflict(source_hash):
    """Probe whether moving `source_hash` here would hit a git conflict."""
    original_head = git_rev_parse('HEAD')
    r = run_git(['cherry-pick', '--no-commit', source_hash], check=False)
    combined = r.stdout + r.stderr
    run_git(['cherry-pick', '--abort'], check=False)
    run_git(['reset', '--hard', original_head])

    if r.returncode == 0:
        return True
    if is_non_conflict_cherry_pick_failure(combined):
        return True
    if is_git_conflict_output(combined):
        return False
    raise RuntimeError(
        f"git cherry-pick probe failed for {source_hash}:\n"
        f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")


def add_subject_prefix_with_original(subject, prefix, space_before_plain=False,
                                     original_subject=None):
    if subject.startswith(prefix):
        return subject, original_subject
    separator = ' ' if space_before_plain and not subject.startswith('[') else ''
    body, suffix = split_preserved_subject_suffix(subject)
    max_body_len = MAX_TITLE_LEN - len(prefix) - len(separator) - len(suffix)
    prefixed = prefix + separator + body[:max_body_len] + suffix

    original_base = original_subject or subject
    original_separator = (
        ' ' if space_before_plain and not original_base.startswith('[') else '')
    full_subject = prefix + original_separator + original_base
    if prefixed != full_subject:
        return prefixed, full_subject
    return prefixed, None


def add_subject_prefix(subject, prefix, space_before_plain=False):
    prefixed, _original_subject = add_subject_prefix_with_original(
        subject, prefix, space_before_plain)
    return prefixed


_PATCH_HUNK_CACHE = {}
_PATCH_HUNK_MAP_CACHE = {}
_HUNK_RE = re.compile(
    r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def _range_with_min_width(start, count):
    count = max(count, 1)
    return start, start + count - 1


def item_patch_hunks(item):
    """Return zero-context diff hunks for an item's partial source commit."""
    key = item_source_cache_key(item)
    if key in _PATCH_HUNK_CACHE:
        return _PATCH_HUNK_CACHE[key]

    source_by_file = item.get('source_by_file') or {}
    if source_by_file:
        hunks = []
        paths_by_source = defaultdict(list)
        source_history_by_file = item.get('source_history_by_file') or {}
        for path in item['files']:
            source_history = source_history_by_file.get(path)
            if source_history:
                for source_hash in source_history:
                    paths_by_source[source_hash].append(path)
            else:
                paths_by_source[source_by_file.get(
                    path, item['source_hash'])].append(path)
        for source_hash, paths in paths_by_source.items():
            hunks.extend(item_patch_hunks({
                'source_hash': source_hash,
                'files': paths,
            }))
        _PATCH_HUNK_CACHE[key] = hunks
        return hunks

    parents = get_commit_parents(item['source_hash'])
    if parents:
        args = ['diff', '--unified=0', '--no-renames',
                parents[0], item['source_hash'], '--'] + list(item['files'])
    else:
        args = ['show', '--format=', '--unified=0', '--no-renames',
                item['source_hash'], '--'] + list(item['files'])
    r = run_git(args, check=False)

    hunks = []
    old_path = None
    new_path = None
    current_path = None
    for line in r.stdout.splitlines():
        if line.startswith('diff --git '):
            old_path = None
            new_path = None
            current_path = None
            continue
        if line.startswith('--- '):
            raw = line[4:]
            new_path = None
            old_path = None if raw == '/dev/null' else raw[2:] if raw.startswith('a/') else raw
            current_path = new_path or old_path
            continue
        if line.startswith('+++ '):
            raw = line[4:]
            new_path = None if raw == '/dev/null' else raw[2:] if raw.startswith('b/') else raw
            current_path = new_path or old_path
            continue

        m = _HUNK_RE.match(line)
        if not m or current_path is None:
            continue
        old_start = int(m.group(1))
        old_count = int(m.group(2) or '1')
        new_start = int(m.group(3))
        new_count = int(m.group(4) or '1')
        old_range = _range_with_min_width(old_start, old_count)
        new_range = _range_with_min_width(new_start, new_count)
        hunks.append((current_path, old_range, new_range))

    _PATCH_HUNK_CACHE[key] = hunks
    return hunks


def ranges_overlap(a, b):
    return max(a[0], b[0]) <= min(a[1], b[1])


def patch_hunks_overlap(left, right):
    return (left[0] == right[0] and
            (ranges_overlap(left[1], right[1]) or
             ranges_overlap(left[2], right[2])))


def patches_overlap(left_item, right_item):
    left_map = item_patch_hunk_map(left_item)
    right_map = item_patch_hunk_map(right_item)
    for path in set(left_map).intersection(right_map):
        if any(patch_hunks_overlap(lh, rh)
               for lh in left_map[path] for rh in right_map[path]):
            return True
    return False


def item_patch_hunk_map(item):
    key = item_source_cache_key(item)
    if key in _PATCH_HUNK_MAP_CACHE:
        return _PATCH_HUNK_MAP_CACHE[key]
    hunk_map = defaultdict(list)
    for hunk in item_patch_hunks(item):
        hunk_map[hunk[0]].append(hunk)
    _PATCH_HUNK_MAP_CACHE[key] = hunk_map
    return hunk_map


def patch_overlaps_any(item, protected_items):
    return any(patches_overlap(item, protected) for protected in protected_items)


def patch_overlap_keep_ids(candidates, protected_items):
    """Return candidate ids that must stay later due to patch overlap.

    The fixed-point loop means a candidate newly kept due to overlap becomes
    protected for the remaining candidates too.
    """
    keep_items = list(protected_items)
    keep_ids = set()
    changed = True
    while changed:
        changed = False
        for item in candidates:
            item_id = id(item)
            if item_id in keep_ids:
                continue
            if patch_overlaps_any(item, keep_items):
                keep_ids.add(item_id)
                keep_items.append(item)
                changed = True
    return keep_ids


def full_state_overlap_keep_ids(candidates, protected_items):
    """Return candidate ids clobbered by later full file-state replay.

    The overlap probe is patch-aware for patch-like moves, but most buckets are
    still emitted by materialising whole file states. For those later buckets,
    any shared file can erase an earlier non-overlapping patch.
    """
    keep_items = list(protected_items)
    keep_ids = set()
    changed = True
    while changed:
        changed = False
        protected_paths = set()
        for item in keep_items:
            protected_paths.update(item['files'])
        for item in candidates:
            item_id = id(item)
            if item_id in keep_ids:
                continue
            if protected_paths.intersection(item['files']):
                keep_ids.add(item_id)
                keep_items.append(item)
                changed = True
    return keep_ids


def unsafe_later_overlap_keep_ids(candidates, protected_items):
    return (patch_overlap_keep_ids(candidates, protected_items) |
            full_state_overlap_keep_ids(candidates, protected_items))


def item_source_pos(item):
    return item.get('source_pos', -1)


def item_full_state_overlaps_any(item, protected_items):
    item_paths = set(item['files'])
    return any(item_paths.intersection(protected['files'])
               for protected in protected_items)


def item_has_unsafe_overlap(item, protected_items):
    return (patch_overlaps_any(item, protected_items) or
            item_full_state_overlaps_any(item, protected_items))


def promotion_overlap_keep_ids(candidates, external_protected_items,
                               remaining_protected_items):
    """Return candidate ids unsafe to promote before Remaining.

    External protected items are emitted after g5 and before Remaining, so any
    overlap would be reordered. Remaining protected items only block a candidate
    when they originally came before it; later Remaining commits still replay
    after a promoted candidate, preserving the original dependency order.
    """
    keep_ids = set()
    remaining_protected = list(remaining_protected_items)
    for item in sorted(candidates, key=item_source_pos):
        pos = item_source_pos(item)
        earlier_remaining = [
            protected for protected in remaining_protected
            if item_source_pos(protected) < pos
        ]
        if item_has_unsafe_overlap(
                item, list(external_protected_items) + earlier_remaining):
            keep_ids.add(id(item))
            remaining_protected.append(item)
    return keep_ids


def touches_only_mysql_test(paths):
    return bool(paths) and all(p.startswith('mysql-test/') for p in paths)


def _with_subject_prefix(item, prefix, space_before_plain):
    """Return a shallow copy of `item` with `prefix` applied to its subject.
    Idempotent: returns the original item unchanged when no prefix is set,
    the subject already starts with it, or the subject already carries a
    different `[tag]` (so promotion-tag stacking like `[MTR-only][result-only]`
    is avoided)."""
    if prefix is None or item['subject'].startswith(prefix):
        return item
    if item['subject'].startswith('['):
        return item
    new_item = dict(item)
    subject, original_subject = add_subject_prefix_with_original(
        item['subject'], prefix, space_before_plain=space_before_plain,
        original_subject=item.get('original_subject'))
    new_item['subject'] = subject
    new_item['original_subject'] = original_subject
    return new_item


def filter_with_drift_guard(*,
                            source_bucket,
                            other_bucket,
                            source_tag,
                            other_tag,
                            unit_label,
                            direction,
                            candidate_filter=None,
                            skip_classifier=None,
                            preserve_filter=None,
                            external_protected_items=None,
                            overlap_strategy='per-candidate',
                            accept_subject_prefix=None,
                            reject_subject_prefix=None,
                            subject_prefix_space_before_plain=False,
                            sort_accepted_by_source_pos=True):
    """Shared probe-and-overlap classifier used by g5/g6/g8 (promote) and g10
    (keep-in-place). Items in `source_bucket` are split into an accepted set
    and a rejected set; `direction` controls which set ends up in which bucket:

      'promote'       — rejected items stay in `source_bucket`; accepted items
                        move to `other_bucket`. Log tag is "[other<-source]".
      'keep_in_place' — accepted items stay in `source_bucket`; rejected items
                        fall back to `other_bucket`. Log tag is "[source]".

    Per item:
      candidate_filter(item) is False           -> stays in source_bucket
                                                   (silent pass-through; no
                                                   subject prefix)
      preserve_filter(item) is True             -> accepted without probing
                                                   (also contributes to sibling
                                                   overlap protection)
      skip_classifier(item) -> (label, phrase)  -> rejected with logged reason
      can_move_without_git_conflict is False    -> rejected ("conflict")
      overlap_ids contains the item             -> rejected ("overlap")
      otherwise                                 -> accepted

    `overlap_strategy`:
      'per-candidate' — promotion_overlap_keep_ids; earlier-source remaining
                        items only (used by g5/g6).
      'global-unsafe' — unsafe_later_overlap_keep_ids; full protected set
                        regardless of source position (used by g8/g10).

    Returns: dict with `accepted`, `conflict_rejected`, `overlap_rejected`,
    `preserved`, and `skips` (label -> count)."""
    if direction == 'promote':
        log_tag = f"[{other_tag}<-{source_tag}]"
        reject_verb = 'keeping'
        reject_location = source_tag
    elif direction == 'keep_in_place':
        log_tag = f"[{source_tag}]"
        reject_verb = 'leaving'
        reject_location = other_tag
    else:
        raise ValueError(f"unknown direction: {direction!r}")

    if overlap_strategy == 'per-candidate':
        overlap_phrase = ("because moving it before Remaining would overlap "
                          "an earlier protected change")
    elif overlap_strategy == 'global-unsafe':
        overlap_phrase = "because a later patch overlaps"
    else:
        raise ValueError(f"unknown overlap_strategy: {overlap_strategy!r}")

    external_protected_items = list(external_protected_items or ())
    if candidate_filter is None:
        candidate_filter = lambda _item: True

    candidates = []
    preserve_ids = set()
    skip_lookup = {}
    for item in source_bucket:
        if not candidate_filter(item):
            continue
        if preserve_filter is not None and preserve_filter(item):
            preserve_ids.add(id(item))
            candidates.append(item)
            continue
        skip = skip_classifier(item) if skip_classifier is not None else None
        if skip is not None:
            skip_lookup[id(item)] = skip
        else:
            candidates.append(item)

    pre_skip_counts = defaultdict(int)
    for skip_label, _phrase in skip_lookup.values():
        pre_skip_counts[skip_label] += 1

    if not candidates and not skip_lookup:
        log(f"  {log_tag} no {unit_label} commits to probe")
        return {'accepted': 0, 'conflict_rejected': 0, 'overlap_rejected': 0,
                'preserved': 0, 'skips': {}}

    if skip_lookup:
        parts = ', '.join(f"{count} {label}"
                          for label, count in sorted(pre_skip_counts.items()))
        skip_summary = f" ({parts} pre-skipped)"
    else:
        skip_summary = ''
    log(f"  {log_tag} probing {len(candidates)} {unit_label} commit(s)"
        f"{skip_summary}")

    start = time.monotonic()
    clean_candidates = []
    conflict_ids = set()
    probed = 0
    for i, item in enumerate(candidates, 1):
        iid = id(item)
        if iid in preserve_ids:
            clean_candidates.append(item)
        else:
            probed += 1
            if can_move_without_git_conflict(item['source_hash']):
                clean_candidates.append(item)
            else:
                conflict_ids.add(iid)
        if probed and (i % PROGRESS_EVERY == 0 or i == len(candidates)):
            elapsed = time.monotonic() - start
            rate = i / elapsed if elapsed > 0 else 0.0
            log(f"  {log_tag} probed {i}/{len(candidates)} commits  "
                f"({len(clean_candidates)} clean, {len(conflict_ids)} "
                f"conflict)  {rate:5.1f} commits/s")

    candidate_ids = {id(item) for item in candidates}

    def _build_protected_source_items():
        return [item for item in source_bucket
                if id(item) not in candidate_ids or id(item) in conflict_ids]

    if overlap_strategy == 'per-candidate':
        overlap_ids = promotion_overlap_keep_ids(
            clean_candidates, external_protected_items,
            _build_protected_source_items())
    else:  # 'global-unsafe' (validated above)
        overlap_ids = unsafe_later_overlap_keep_ids(
            clean_candidates,
            external_protected_items + _build_protected_source_items())

    # Preserve items are forced-clean: they never get rejected on overlap.
    overlap_ids.difference_update(preserve_ids)

    accepted_items = []
    rejected_items = []
    pass_through_items = []
    accepted = 0
    conflict_rejected = 0
    overlap_rejected = 0
    preserved = 0
    skip_counts = defaultdict(int)

    for item in source_bucket:
        iid = id(item)
        if iid in skip_lookup:
            skip_label, log_phrase = skip_lookup[iid]
            log(f"  {log_tag} {reject_verb} {item['source_hash'][:12]} in "
                f"{reject_location} {log_phrase}")
            skip_counts[skip_label] += 1
            rejected_items.append(_with_subject_prefix(
                item, reject_subject_prefix,
                subject_prefix_space_before_plain))
            continue
        if iid not in candidate_ids:
            pass_through_items.append(item)
            continue
        if iid in conflict_ids:
            log(f"  {log_tag} {reject_verb} {item['source_hash'][:12]} in "
                f"{reject_location} because cherry-pick probe reported a "
                "conflict")
            conflict_rejected += 1
            rejected_items.append(_with_subject_prefix(
                item, reject_subject_prefix,
                subject_prefix_space_before_plain))
        elif iid in overlap_ids:
            log(f"  {log_tag} {reject_verb} {item['source_hash'][:12]} in "
                f"{reject_location} {overlap_phrase}")
            overlap_rejected += 1
            rejected_items.append(_with_subject_prefix(
                item, reject_subject_prefix,
                subject_prefix_space_before_plain))
        else:
            if iid in preserve_ids:
                preserved += 1
            else:
                accepted += 1
            accepted_items.append(_with_subject_prefix(
                item, accept_subject_prefix,
                subject_prefix_space_before_plain))

    if sort_accepted_by_source_pos:
        accepted_items.sort(key=lambda it: it.get('source_pos', -1))

    if direction == 'promote':
        # Non-candidates stay in source (alongside rejects); accepted moves out.
        other_bucket.extend(accepted_items)
        source_bucket[:] = pass_through_items + rejected_items
    else:  # 'keep_in_place'
        # Non-candidates stay in source (alongside accepted); rejects move out.
        source_bucket[:] = pass_through_items + accepted_items
        other_bucket.extend(rejected_items)

    parts = [f"{accepted + preserved} accepted",
             f"{conflict_rejected} conflict rejected",
             f"{overlap_rejected} overlap rejected"]
    if preserved:
        parts.append(f"{preserved} preserved")
    for label, count in sorted(skip_counts.items()):
        parts.append(f"{count} {label} rejected")
    total_eligible = len(candidates) + len(skip_lookup)
    log(f"  {log_tag} {total_eligible} eligible ({', '.join(parts)})")

    return {'accepted': accepted, 'conflict_rejected': conflict_rejected,
            'overlap_rejected': overlap_rejected, 'preserved': preserved,
            'skips': dict(skip_counts)}


def promote_with_drift_guard(*,
                             source_bucket,
                             dest_bucket,
                             source_tag,
                             dest_tag,
                             unit_label,
                             candidate_filter,
                             skip_classifier=None,
                             external_protected_items=None,
                             overlap_strategy='per-candidate',
                             promoted_subject_prefix=None,
                             kept_subject_prefix=None,
                             subject_prefix_space_before_plain=False,
                             sort_moved_by_source_pos=True):
    """Promote pattern wrapper around `filter_with_drift_guard` used by
    g5/g6/g8: clean candidates move from `source_bucket` to `dest_bucket`;
    conflicts/overlaps/skips stay in `source_bucket`."""
    result = filter_with_drift_guard(
        source_bucket=source_bucket,
        other_bucket=dest_bucket,
        source_tag=source_tag,
        other_tag=dest_tag,
        unit_label=unit_label,
        direction='promote',
        candidate_filter=candidate_filter,
        skip_classifier=skip_classifier,
        external_protected_items=external_protected_items,
        overlap_strategy=overlap_strategy,
        accept_subject_prefix=promoted_subject_prefix,
        reject_subject_prefix=kept_subject_prefix,
        subject_prefix_space_before_plain=subject_prefix_space_before_plain,
        sort_accepted_by_source_pos=sort_moved_by_source_pos,
    )
    return {'promoted': result['accepted'],
            'conflict_kept': result['conflict_rejected'],
            'overlap_kept': result['overlap_rejected'],
            'skips': result['skips']}


def keep_in_place_with_drift_guard(*,
                                   source_bucket,
                                   fallback_bucket,
                                   source_tag,
                                   fallback_tag,
                                   unit_label,
                                   candidate_filter=None,
                                   preserve_filter=None,
                                   skip_classifier=None,
                                   external_protected_items=None,
                                   overlap_strategy='global-unsafe'):
    """Keep-in-place wrapper around `filter_with_drift_guard` used by g10:
    clean candidates remain in `source_bucket`; conflicts/overlaps/skips fall
    back to `fallback_bucket`. `preserve_filter` items bypass the probe and
    are always accepted (they still contribute to overlap protection)."""
    return filter_with_drift_guard(
        source_bucket=source_bucket,
        other_bucket=fallback_bucket,
        source_tag=source_tag,
        other_tag=fallback_tag,
        unit_label=unit_label,
        direction='keep_in_place',
        candidate_filter=candidate_filter,
        preserve_filter=preserve_filter,
        skip_classifier=skip_classifier,
        external_protected_items=external_protected_items,
        overlap_strategy=overlap_strategy,
        sort_accepted_by_source_pos=False,
    )


def promote_mysql_test_only_to_mtr(source_bucket, g5_bucket, source_tag,
                                   protected_items=None):
    def is_candidate(item):
        return (touches_only_mysql_test(item['files']) and
                not contains_g1_paths(item['files']) and
                not is_preserved_source_group_item(item) and
                not is_locked_from_promotion(item['subject']))

    result = promote_with_drift_guard(
        source_bucket=source_bucket,
        dest_bucket=g5_bucket,
        source_tag=source_tag,
        dest_tag='g5',
        unit_label='mysql-test-only',
        candidate_filter=is_candidate,
        external_protected_items=protected_items,
        overlap_strategy='per-candidate',
        promoted_subject_prefix=(None if source_tag == 'g11'
                                 else '[MTR-only]'),
        kept_subject_prefix='[MTR-only]',
        subject_prefix_space_before_plain=True,
    )
    return result['promoted'], result['conflict_kept'], result['overlap_kept']


def drain_noncode_from_remaining(g11_bucket, g6_bucket, protected_items=None):
    """Move Remaining items whose files contain no C/C++ or CMake source into
    the Non-code group, but only when the move can be done without drifting
    the tree from a reference replay. Held back in g11 when (a) the
    cherry-pick probe at current HEAD reports a conflict, or (b) advancing
    the commit ahead of Remaining would overlap a later protected commit
    (g7/g8/g9/g10 or an earlier-source Remaining commit)."""
    def is_candidate(item):
        return (commit_has_no_code_files(item['files']) and
                not is_locked_from_promotion(item['subject']))

    result = promote_with_drift_guard(
        source_bucket=g11_bucket,
        dest_bucket=g6_bucket,
        source_tag='g11',
        dest_tag='g6',
        unit_label='non-code-only',
        candidate_filter=is_candidate,
        external_protected_items=protected_items,
        overlap_strategy='per-candidate',
    )
    return result['promoted'], result['conflict_kept'], result['overlap_kept']


def promote_remaining_to_upstream(g11_bucket, g8_bucket, protected_items=None):
    if not g11_bucket:
        log("  [g8<-g11] no remaining commits to probe")
        return 0, 0, 0, 0, 0, 0, 0

    def classify_skip(item):
        if is_locked_from_promotion(item['subject']):
            return ('=== locked',
                    "because subject contains '===' (locked from promotion)")
        if is_mtr_only_group_subject(item['subject']):
            return ('MTR', "because subject starts with [MTR-only]")
        if is_result_only_item(item):
            return ('result', "because subject starts with [result-only]")
        if is_myrocks_kernel_group_subject(item['subject']):
            return ('g10',
                    "because subject matches g10 MyRocks/kernel rules")
        return None

    result = promote_with_drift_guard(
        source_bucket=g11_bucket,
        dest_bucket=g8_bucket,
        source_tag='g11',
        dest_tag='g8',
        unit_label='remaining',
        candidate_filter=lambda _item: True,
        skip_classifier=classify_skip,
        external_protected_items=protected_items,
        overlap_strategy='global-unsafe',
    )
    skips = result['skips']
    return (result['promoted'], result['conflict_kept'],
            result['overlap_kept'],
            skips.get('MTR', 0), skips.get('result', 0),
            skips.get('g10', 0), skips.get('=== locked', 0))


def emit_split_bucket(bucket, tag, removed_commits=None):
    """Write individual commits of a split bucket (g2/g3/g4/g6/g7/g8/g9/g10/g11)."""
    emitted = 0
    skipped_empty = 0
    total = len(bucket)
    if total == 0:
        log(f"  [{tag}] (empty bucket)")
        return 0, 0
    total_files = sum(len(it['files']) for it in bucket)
    log(f"  [{tag}] {total} commits, {total_files} file-modifications")
    start = time.monotonic()
    for i, item in enumerate(bucket, 1):
        apply_item_file_states(item)
        if do_commit(item['info'], item['subject'], item['body_rest'],
                     original_subject=item.get('original_subject')):
            emitted += 1
        else:
            skipped_empty += 1
            if removed_commits is not None:
                record_removed_item(
                    removed_commits, item,
                    f"planned {tag} output commit produced no staged changes")
        if i % PROGRESS_EVERY == 0 or i == total:
            elapsed = time.monotonic() - start
            rate = i / elapsed if elapsed > 0 else 0.0
            log(f"  [{tag}] {i}/{total} commits  "
                f"({emitted} emitted, {skipped_empty} skipped)  "
                f"{rate:5.1f} commits/s")
    return emitted, skipped_empty


def emit_conflict_aware_split_bucket(bucket, tag, fallback_bucket,
                                     removed_commits=None):
    emitted = 0
    skipped_empty = 0
    conflict_fallback = 0
    total = len(bucket)
    if total == 0:
        log(f"  [{tag}] (empty bucket)")
        return 0, 0, 0
    total_files = sum(len(it['files']) for it in bucket)
    log(f"  [{tag}] {total} commits, {total_files} file-modifications")
    start = time.monotonic()
    for i, item in enumerate(bucket, 1):
        if not can_move_without_git_conflict(item['source_hash']):
            log(f"  [{tag}] leaving {item['source_hash'][:12]} in remaining "
                "because cherry-pick probe reported a conflict")
            fallback_bucket.append(item)
            conflict_fallback += 1
        else:
            apply_item_file_states(item)
            if do_commit(item['info'], item['subject'], item['body_rest'],
                         original_subject=item.get('original_subject')):
                emitted += 1
            else:
                skipped_empty += 1
                if removed_commits is not None:
                    record_removed_item(
                        removed_commits, item,
                        f"planned {tag} output commit produced no staged changes")
        if i % PROGRESS_EVERY == 0 or i == total:
            elapsed = time.monotonic() - start
            rate = i / elapsed if elapsed > 0 else 0.0
            log(f"  [{tag}] {i}/{total} commits  "
                f"({emitted} emitted, {skipped_empty} skipped, "
                f"{conflict_fallback} conflict fallback)  "
                f"{rate:5.1f} commits/s")
    return emitted, skipped_empty, conflict_fallback


def prepare_g10_bucket(g10_bucket, fallback_bucket, protected_items=None):
    if not g10_bucket:
        log("  [g10] (empty bucket)")
        return [], 0, 0
    working = list(g10_bucket)
    result = keep_in_place_with_drift_guard(
        source_bucket=working,
        fallback_bucket=fallback_bucket,
        source_tag='g10',
        fallback_tag='remaining',
        unit_label='MyRocks/kernel',
        preserve_filter=lambda item: item.get('source_group') == 9,
        external_protected_items=protected_items,
        overlap_strategy='global-unsafe',
    )
    return working, result['conflict_rejected'], result['overlap_rejected']


def emit_squash(input_hash, files_set, info, subject, tag):
    """Write one squashed commit using final file state from input_hash."""
    files = sorted(files_set)
    log(f"  [{tag}] squashing {len(files)} file(s) "
        f"(first source: {info['hash'][:12]})")
    apply_file_states(input_hash, files)
    body = (f"Squashed changes covering {len(files_set)} path(s). "
            f"First source commit: {info['hash']}.")
    return do_commit(info, subject, body)


def emit_base_removed_files(plan):
    files = plan['base_removed_files']
    if not files:
        log("  [removed-base-files] (none)")
        return False
    info = plan['base_removal_info']
    log(f"  [removed-base-files] removing {len(files)} file(s)")
    remove_paths(files)
    subject = "Remove files deleted by input branch"
    body = (f"Removed {len(files)} path(s) that existed in BASE_BRANCH and "
            "are absent from INPUT_BRANCH.")
    return do_commit(info, subject, body)


def remaining_diff_paths(input_hash, output_branch):
    r = run_git(['diff', '--name-only', '--no-renames', input_hash, output_branch],
                check=False)
    return [p for p in r.stdout.strip().split('\n') if p]


def emit_snap_reconciliation_commit(input_hash, output_branch):
    paths = remaining_diff_paths(input_hash, output_branch)
    if not paths:
        log("=== SNAP RECONCILIATION ===")
        log("  [snap] no remaining diff to reconcile")
        return False, 0, '', []

    log("=== SNAP RECONCILIATION ===")
    log(f"  [snap] reconciling {len(paths)} differing path(s) to INPUT_BRANCH")
    diff_stat = run_git(['diff', '--stat', output_branch, input_hash],
                        check=False).stdout.strip()
    apply_file_states(input_hash, paths)
    info = get_commit_info(input_hash)
    subject = "SNAP: reconcile remaining diff to INPUT_BRANCH"
    body = (f"Applied final file-state reconciliation for {len(paths)} path(s) "
            f"so {output_branch} matches INPUT_BRANCH exactly.")
    return do_commit(info, subject, body), len(paths), diff_stat, paths


def build_output_branch(args, input_hash, base_hash, plan):
    # Create / reset the output branch at the base
    if branch_exists(args.output_branch):
        if not args.force_output:
            raise RuntimeError(
                f"Output branch {args.output_branch!r} already exists; pass "
                f"--force-output to overwrite.")
        # Switch away if currently checked out
        if get_current_branch() == args.output_branch:
            run_git(['checkout', '--detach', 'HEAD'])
        run_git(['branch', '-D', args.output_branch])

    run_git(['checkout', '-b', args.output_branch, base_hash])

    stats = {
        'g1_emitted': 0, 'g1_skipped': 0,
        'g2_emitted': 0, 'g2_skipped': 0,
        'g3_emitted': 0, 'g3_skipped': 0,
        'g4_emitted': 0, 'g4_skipped': 0,
        'g5_emitted': 0, 'g5_skipped': 0,
        'g5_promoted_from_upstream': 0,
        'g5_upstream_conflict_kept': 0,
        'g5_upstream_overlap_kept': 0,
        'g5_promoted_from_remaining': 0,
        'g5_remaining_conflict_kept': 0,
        'g5_remaining_overlap_kept': 0,
        'g6_emitted': 0, 'g6_skipped': 0,
        'g6_promoted_from_remaining': 0,
        'g6_remaining_conflict_kept': 0,
        'g6_remaining_overlap_kept': 0,
        'g7_emitted': 0, 'g7_skipped': 0,
        'g8_emitted': 0, 'g8_skipped': 0,
        'g8_promoted_from_remaining': 0,
        'g8_remaining_conflict_kept': 0,
        'g8_remaining_overlap_kept': 0,
        'g8_remaining_mtr_kept': 0,
        'g8_remaining_result_kept': 0,
        'g8_remaining_myr_kept': 0,
        'g8_remaining_locked_kept': 0,
        'g9_emitted': 0, 'g9_skipped': 0,
        'g10_emitted': 0, 'g10_skipped': 0,
        'g10_conflict_fallback': 0,
        'g10_overlap_fallback': 0,
        'g11_emitted': 0, 'g11_skipped': 0,
        'snap_emitted': 0, 'snap_skipped': 0, 'snap_paths': 0,
        'snap_diff_stat': '', 'snap_diff_paths': [],
        'removed_base_emitted': 0, 'removed_base_skipped': 0,
    }

    log("=== REMOVED BASE FILES ===")
    if emit_base_removed_files(plan):
        stats['removed_base_emitted'] = 1
    elif plan['base_removed_files']:
        stats['removed_base_skipped'] = 1

    # -- Group 1 ------------------------------------------------------------
    log("=== GROUP 1: Squashes ===")
    marker_commit(
        1, 'Squashes',
        'doc/, internal/, plugin/tokudb-backup-plugin/, storage/tokudb/, '
        'MYSQL_VERSION + VERSION + storage/innobase/include/univ.i, '
        'tokudb MTR tests')
    g1_cats = sorted(plan['g1_files'].keys(),
                     key=lambda c: plan['g1_first_pos'][c])
    for cat in g1_cats:
        ok = emit_squash(input_hash, plan['g1_files'][cat],
                         plan['g1_first_info'][cat], G1_SUBJECTS[cat],
                         f'g1:{cat}')
        if ok:
            stats['g1_emitted'] += 1
        else:
            stats['g1_skipped'] += 1

    # -- Group 2 ------------------------------------------------------------
    log("=== GROUP 2: build-ps ===")
    marker_commit(2, 'build-ps',
                  'Commits touching only build-ps/.')
    e, s = emit_split_bucket(plan['g2_bucket'], 'g2',
                             plan['removed_commits'])
    stats['g2_emitted'], stats['g2_skipped'] = e, s

    # -- Group 3 ------------------------------------------------------------
    log("=== GROUP 3: CI configs ===")
    marker_commit(3, 'CI configs',
                  '.travis.yml, .circleci/, azure-pipelines.yml, .cirrus.yml, '
                  '.clang-tidy')
    e, s = emit_split_bucket(plan['g3_bucket'], 'g3',
                             plan['removed_commits'])
    stats['g3_emitted'], stats['g3_skipped'] = e, s

    # -- Group 4 ------------------------------------------------------------
    log("=== GROUP 4: RocksDB ===")
    marker_commit(4, 'RocksDB',
                  'storage/rocksdb and mysql-test/suite/rocksdb*')
    e, s = emit_split_bucket(plan['g4_bucket'], 'g4',
                             plan['removed_commits'])
    stats['g4_emitted'], stats['g4_skipped'] = e, s

    # -- Group 5 ------------------------------------------------------------
    log("=== GROUP 5: MTR tests ===")
    marker_commit(5, 'MTR tests',
                  'Whole commits whose subject starts with "[MTR-only]", plus '
                  'mysql-test-only Remaining commits that cherry-pick cleanly '
                  'after existing g5 commits without patch-overlapping later '
                  'groups; g11 promotions keep their original subjects.')
    e, s = emit_split_bucket(plan['g5_bucket'], 'g5',
                             plan['removed_commits'])
    stats['g5_emitted'], stats['g5_skipped'] = e, s
    promoted_g5_bucket = []
    promoted, conflict_kept, overlap_kept = promote_mysql_test_only_to_mtr(
        plan['g11_bucket'], promoted_g5_bucket, 'g11',
        plan['g7_bucket'] + plan['g8_bucket'] + plan['g9_bucket'] +
        plan['g10_bucket'])
    stats['g5_promoted_from_remaining'] = promoted
    stats['g5_remaining_conflict_kept'] = conflict_kept
    stats['g5_remaining_overlap_kept'] = overlap_kept
    e, s = emit_split_bucket(promoted_g5_bucket, 'g5:promoted',
                             plan['removed_commits'])
    stats['g5_emitted'] += e
    stats['g5_skipped'] += s

    # -- Group 6 ------------------------------------------------------------
    log("=== GROUP 6: Non-code changes ===")
    marker_commit(6, 'Non-code changes',
                  'Remaining commits whose files contain no C/C++ or CMake '
                  'source (i.e. nothing ending in .h .c .cc .cxx .cpp .hh .hpp '
                  '.hxx .cmake, and no CMakeLists.txt / *.cmake.in).')
    promoted, conflict_kept, overlap_kept = drain_noncode_from_remaining(
        plan['g11_bucket'], plan['g6_bucket'],
        plan['g7_bucket'] + plan['g8_bucket'] + plan['g9_bucket'] +
        plan['g10_bucket'])
    stats['g6_promoted_from_remaining'] = promoted
    stats['g6_remaining_conflict_kept'] = conflict_kept
    stats['g6_remaining_overlap_kept'] = overlap_kept
    e, s = emit_split_bucket(plan['g6_bucket'], 'g6',
                             plan['removed_commits'])
    stats['g6_emitted'], stats['g6_skipped'] = e, s

    # -- Group 7 ------------------------------------------------------------
    log("=== GROUP 7: Build/Compilation ===")
    marker_commit(7, 'Build/Compilation',
                  'Whole commits whose subject starts with "[compilation]".')
    e, s = emit_split_bucket(plan['g7_bucket'], 'g7',
                             plan['removed_commits'])
    stats['g7_emitted'], stats['g7_skipped'] = e, s

    # -- Group 8 ------------------------------------------------------------
    log("=== GROUP 8: Upstream bug fixes ===")
    marker_commit(8, 'Upstream bug fixes',
                  'Whole commits whose subject starts with "[upstream]", plus '
                  'Remaining commits that cherry-pick cleanly after existing '
                  'g8 commits without patch-overlapping later groups or '
                  'matching g10 MyRocks/kernel subject rules; g11 promotions '
                  'keep their original subjects.')
    e, s = emit_split_bucket(plan['g8_bucket'], 'g8',
                             plan['removed_commits'])
    stats['g8_emitted'], stats['g8_skipped'] = e, s
    if getattr(args, 'no_g8_promotion', False):
        log("  [g8<-g11] skipped (--no-g8-promotion)")
        stats['g8_promoted_from_remaining'] = 0
        stats['g8_remaining_conflict_kept'] = 0
        stats['g8_remaining_overlap_kept'] = 0
        stats['g8_remaining_mtr_kept'] = 0
        stats['g8_remaining_result_kept'] = 0
        stats['g8_remaining_myr_kept'] = 0
        stats['g8_remaining_locked_kept'] = 0
    else:
        promoted_g8_bucket = []
        (promoted, conflict_kept, overlap_kept, mtr_kept, result_kept, myr_kept,
         locked_kept) = promote_remaining_to_upstream(
            plan['g11_bucket'], promoted_g8_bucket,
            plan['g9_bucket'] + plan['g10_bucket'])
        stats['g8_promoted_from_remaining'] = promoted
        stats['g8_remaining_conflict_kept'] = conflict_kept
        stats['g8_remaining_overlap_kept'] = overlap_kept
        stats['g8_remaining_mtr_kept'] = mtr_kept
        stats['g8_remaining_result_kept'] = result_kept
        stats['g8_remaining_myr_kept'] = myr_kept
        stats['g8_remaining_locked_kept'] = locked_kept
        e, s = emit_split_bucket(promoted_g8_bucket, 'g8:promoted',
                                 plan['removed_commits'])
        stats['g8_emitted'] += e
        stats['g8_skipped'] += s

    # -- Group 9 ------------------------------------------------------------
    log("=== GROUP 9: Initial Percona Server tree ===")
    marker_commit(9, 'Initial Percona Server tree',
                  'Whole commits whose subject starts with "[init]".')
    e, s = emit_split_bucket(plan['g9_bucket'], 'g9',
                             plan['removed_commits'])
    stats['g9_emitted'], stats['g9_skipped'] = e, s

    # -- Group 10 ------------------------------------------------------------
    log("=== GROUP 10: MyRocks changes in kernel ===")
    marker_commit(10, 'MyRocks changes in kernel',
                  'Whole commits whose subject contains "MYR" or "rocks" '
                  '(case-insensitive), unless moving would cause a git '
                  'conflict or a later Remaining commit would overwrite the '
                  'same patch; mixed g4 commits contribute only their non-g4 '
                  'portion here.')
    prepared_g10_bucket, conflict_fallback, overlap_fallback = prepare_g10_bucket(
        plan['g10_bucket'], plan['g11_bucket'], plan['g11_bucket'])
    e, s = emit_split_bucket(prepared_g10_bucket, 'g10',
                             plan['removed_commits'])
    stats['g10_emitted'], stats['g10_skipped'] = e, s
    stats['g10_conflict_fallback'] = conflict_fallback
    stats['g10_overlap_fallback'] = overlap_fallback

    # -- Group 11 -----------------------------------------------------------
    log("=== GROUP 11: Remaining ===")
    marker_commit(11, 'Remaining',
                  'Everything not classified into groups 1-9.')
    plan['g11_bucket'].sort(key=lambda item: item.get('source_pos', -1))
    e, s = emit_split_bucket(plan['g11_bucket'], 'g11',
                             plan['removed_commits'])
    stats['g11_emitted'], stats['g11_skipped'] = e, s

    snap_ok, snap_paths, snap_diff_stat, snap_diff_paths = emit_snap_reconciliation_commit(
        input_hash, args.output_branch)
    stats['snap_paths'] = snap_paths
    stats['snap_diff_stat'] = snap_diff_stat
    stats['snap_diff_paths'] = snap_diff_paths
    if snap_ok:
        stats['snap_emitted'] = 1
    elif snap_paths:
        stats['snap_skipped'] = 1

    return stats


def emit_final_summary_marker(in_count, out_count, out_ins, out_del):
    """Append an empty marker commit summarising the input/output sizes."""
    subject = (f"=== {in_count} => {out_count} commits; "
               f"total +{out_ins}/-{out_del} ===")
    env = os.environ.copy()
    for k in ('GIT_AUTHOR_DATE', 'GIT_COMMITTER_DATE'):
        env.pop(k, None)
    run_git(['commit', '--allow-empty', '-m', subject], env=env)
    log_output_commit_stats(git_rev_parse('HEAD'))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


_INS_RE = re.compile(r'(\d+)\s+insertion')
_DEL_RE = re.compile(r'(\d+)\s+deletion')


def _shortstat_one(ch):
    """Run shortstat for one commit; returns (hash, ins, del). Rename
    detection is disabled (matches branch_range_stats.py) for speed."""
    r = subprocess.run(
        ['git', '-c', 'diff.renames=false', 'show',
         '--no-patch', '--format=', '--shortstat', ch],
        capture_output=True, text=True, encoding='utf-8',
        errors='replace', check=False,
    )
    text = r.stdout
    ins = int(_INS_RE.search(text).group(1)) if _INS_RE.search(text) else 0
    dele = int(_DEL_RE.search(text).group(1)) if _DEL_RE.search(text) else 0
    return ch, ins, dele


def scan_commits(start, end, label=None, jobs=32):
    """Walk every first-parent commit in `start..end` in parallel, summing
    per-commit insertions/deletions.

    Returns (total_ins, total_del). Uses a thread pool (default 32 workers) to
    parallelise `git show --shortstat`.
    """
    r = run_git(['log', '--first-parent', '--reverse', '--format=%H',
                 f'{start}..{end}'])
    hashes = [x for x in r.stdout.strip().split('\n') if x]
    total = len(hashes)
    if label:
        log(f"Scanning {label} for per-commit stats across {total} commits "
            f"(parallel, {jobs} workers)...")
    if not hashes:
        return 0, 0

    total_ins = 0
    total_del = 0
    t0 = time.monotonic()
    done = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for ch, ins, dele in ex.map(_shortstat_one, hashes, chunksize=32):
            total_ins += ins
            total_del += dele
            done += 1
            if label and (done % 500 == 0 or done == total):
                elapsed = time.monotonic() - t0
                rate = done / elapsed if elapsed > 0 else 0.0
                log(f"  {label}: scanned {done}/{total}  "
                    f"({rate:5.1f}/s)")

    return total_ins, total_del


def grouped_removed_commits(entries):
    grouped = OrderedDict()
    for entry in entries:
        source_hash = entry.get('hash', '')
        subject = entry.get('subject', '')
        reason = entry.get('reason', '').strip() or "(no reason recorded)"
        key = (source_hash, subject)
        grouped.setdefault(key, [])
        if reason not in grouped[key]:
            grouped[key].append(reason)
    return [(source_hash, subject, reasons)
            for (source_hash, subject), reasons in grouped.items()]


def is_source_marker_removed_reason(reason):
    return (reason.startswith("source marker for group ") and
            reason.endswith(" omitted; output markers are regenerated"))


def removed_reason_group_header(reason):
    absent_prefix = (
        "all modified paths were skipped because they are absent from "
        "INPUT_BRANCH")
    if reason.startswith(absent_prefix):
        return "All modified paths were skipped because they are absent from INPUT_BRANCH"
    if re.match(r"^all \d+ \.result path\(s\) were squashed into "
                r"previous in-range commit\(s\)$", reason):
        return "All .result path(s) were squashed into previous in-range commit(s)"
    if reason.startswith("all modified paths"):
        return "All" + reason[len("all"):]
    if reason.startswith("all "):
        return "All" + reason[len("all"):]
    return reason


def removed_commits_by_reason(entries):
    grouped = OrderedDict()
    seen = defaultdict(set)
    for source_hash, subject, reasons in grouped_removed_commits(entries):
        for reason in reasons:
            if is_source_marker_removed_reason(reason):
                continue
            reason = removed_reason_group_header(reason)
            key = (source_hash, subject)
            if key in seen[reason]:
                continue
            grouped.setdefault(reason, []).append(key)
            seen[reason].add(key)
    return grouped


def print_removed_commit_line(source_hash, subject):
    files, ins, dele = get_commit_shortstat_details(source_hash)
    line = format_output_commit_stats_line(files, ins, dele, source_hash,
                                           subject)
    print(colorize_output_commit_stats_line(
        line, ins + dele <= 8, dele > ins,
        ins + dele > LARGE_COMMIT_THRESHOLD, True),
        file=sys.stderr, flush=True)


def log_removed_commits_by_reason(plan):
    grouped = removed_commits_by_reason(plan.get('removed_commits', []))
    log("=== REMOVED COMMITS ===")
    if not grouped:
        log("  (none)")
        return
    unique_commits = OrderedDict()
    for commits in grouped.values():
        for source_hash, subject in commits:
            unique_commits[(source_hash, subject)] = True
    total = len(unique_commits)
    log(f"  {total} source commit(s) removed or elided")
    for reason, commits in grouped.items():
        log("")
        log(f"{reason} ({len(commits)} commit(s))")
        for source_hash, subject in commits:
            print_removed_commit_line(source_hash, subject)


def log_terminal_summary(args, input_hash, base_hash, plan, stats):
    in_count = int(run_git(['rev-list', '--first-parent', '--count',
                            f'{base_hash}..{input_hash}']).stdout.strip())
    out_count = int(run_git(['rev-list', '--first-parent', '--count',
                             f'{base_hash}..{args.output_branch}']).stdout.strip())

    in_ins, in_del = scan_commits(base_hash, input_hash,
                                  label='INPUT_BRANCH')
    out_ins, out_del = scan_commits(base_hash, args.output_branch,
                                    label='OUTPUT_BRANCH')

    emit_final_summary_marker(in_count, out_count, out_ins, out_del)

    diff_stat = run_git(['diff', '--stat', input_hash, args.output_branch],
                        check=False).stdout.strip()
    diff_content = run_git(['diff', input_hash, args.output_branch],
                           check=False).stdout
    null_diff = not diff_content.strip()

    visible_removed = OrderedDict()
    for commits in removed_commits_by_reason(
            plan.get('removed_commits', [])).values():
        for source_hash, subject in commits:
            visible_removed[(source_hash, subject)] = True

    log("=== FINAL SUMMARY ===")
    log(f"Input:  {args.input_branch}  ({input_hash[:12]})")
    log(f"Base:   {args.base_branch}   ({base_hash[:12]})")
    log(f"Output: {args.output_branch}")
    log(f"Source commits considered: {plan['n_source_commits']}")
    log(f"Source commits removed or elided: {len(visible_removed)}")
    log(f"Commits on INPUT_BRANCH (first-parent):  {in_count}")
    log(f"Commits on OUTPUT_BRANCH (first-parent): {out_count}")
    log(f"Per-commit totals on INPUT_BRANCH:  "
        f"+{in_ins}/-{in_del}  (total {in_ins + in_del})")
    log(f"Per-commit totals on OUTPUT_BRANCH: "
        f"+{out_ins}/-{out_del}  (total {out_ins + out_del})")
    log(f"Base-branch removed files: {len(plan['base_removed_files'])}")
    log(f"Input-only removed files skipped: "
        f"{len(plan['transient_removed_files'])}")
    log(f"Removed-file references skipped while planning: "
        f"{plan['base_removed_refs_skipped']} base-file, "
        f"{plan['transient_removed_refs_skipped']} input-only")
    log(f".result file changes squashed into previous in-range occurrences: "
        f"{plan.get('result_only_files_squashed', 0)}")
    log(f".result-only commits fully elided by that squash: "
        f"{plan.get('result_only_commits_elided', 0)}")
    log(f".result files kept as [result-only] because their previous "
        f"occurrence is in BASE_BRANCH: "
        f"{plan.get('result_only_base_files_kept', 0)}")
    log(f"[result-only] commits kept separate: "
        f"{plan.get('result_only_base_commits_kept', 0)}")

    log("")
    log("Group totals:")
    log("  Group              Emitted  Skipped")
    for g in ('g1', 'g2', 'g3', 'g4', 'g5', 'g6',
              'g7', 'g8', 'g9', 'g10', 'g11'):
        log(f"  {g:<18} {stats[f'{g}_emitted']:>7}  "
            f"{stats[f'{g}_skipped']:>7}")
    log(f"  {'removed-base-files':<18} "
        f"{stats['removed_base_emitted']:>7}  "
        f"{stats['removed_base_skipped']:>7}")
    log(f"  {'snap-reconcile':<18} {stats.get('snap_emitted', 0):>7}  "
        f"{stats.get('snap_skipped', 0):>7}")

    log("")
    log("Promotion and fallback stats:")
    log(f"g11 mysql-test-only commits promoted to g5 without adding "
        f"[MTR-only]: {stats.get('g5_promoted_from_remaining', 0)}")
    log(f"g11 mysql-test-only commits kept for g5 cherry-pick conflicts: "
        f"{stats.get('g5_remaining_conflict_kept', 0)}")
    log(f"g11 mysql-test-only commits kept out of g5 for later patch "
        f"overlaps: {stats.get('g5_remaining_overlap_kept', 0)}")
    log(f"g11 non-code-only commits promoted to g6: "
        f"{stats.get('g6_promoted_from_remaining', 0)}")
    log(f"g11 non-code-only commits kept for g6 cherry-pick conflicts: "
        f"{stats.get('g6_remaining_conflict_kept', 0)}")
    log(f"g11 non-code-only commits kept out of g6 for later patch "
        f"overlaps: {stats.get('g6_remaining_overlap_kept', 0)}")
    log(f"g10 conflict fallbacks emitted in Remaining: "
        f"{stats.get('g10_conflict_fallback', 0)}")
    log(f"g10 later patch-overlap fallbacks emitted in Remaining: "
        f"{stats.get('g10_overlap_fallback', 0)}")
    log(f"Final SNAP reconciliation paths applied: "
        f"{stats.get('snap_paths', 0)}")
    log(f"g11 commits promoted to g8 without adding [upstream]: "
        f"{stats.get('g8_promoted_from_remaining', 0)}")
    log(f"g11 commits kept for g8 cherry-pick conflicts: "
        f"{stats.get('g8_remaining_conflict_kept', 0)}")
    log(f"g11 commits kept to avoid later patch overlap: "
        f"{stats.get('g8_remaining_overlap_kept', 0)}")
    log(f"g11 [MTR-only] commits kept out of g8: "
        f"{stats.get('g8_remaining_mtr_kept', 0)}")
    log(f"g11 [result-only] commits kept out of g8: "
        f"{stats.get('g8_remaining_result_kept', 0)}")
    log(f"g11 MyRocks/kernel-subject commits kept out of g8: "
        f"{stats.get('g8_remaining_myr_kept', 0)}")
    log(f"g11 commits kept out of g8 because subject contains '===': "
        f"{stats.get('g8_remaining_locked_kept', 0)}")

    log("")
    log(f"Null diff vs INPUT_BRANCH: {'YES' if null_diff else 'NO'}")
    if not null_diff:
        log("Remaining diff stat:")
        for line in (diff_stat or "(no stat available)").splitlines():
            log(f"  {line}")
        log("Remaining diff (truncated to 20000 chars):")
        for line in diff_content[:20000].splitlines():
            log(line)

    if stats.get('snap_paths', 0):
        log("")
        log("Final SNAP reconciliation:")
        log("The grouped replay left a residual diff, so a final "
            "`SNAP: reconcile remaining diff to INPUT_BRANCH` commit was "
            "added before null-diff verification.")
        log(f"Paths reconciled: {stats.get('snap_paths', 0)}")
        log("SNAP diff stat:")
        for line in (stats.get('snap_diff_stat') or
                     "(no stat available)").splitlines():
            log(f"  {line}")
        log("SNAP paths:")
        for path in stats.get('snap_diff_paths') or []:
            log(f"  {styled_path(path)}")

    return null_diff


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description='Reorder a Percona Server branch into logical commit groups.'
    )
    parser.add_argument('--input-branch',  required=True,
                        help='Branch name or commit hash to reorder.')
    parser.add_argument('--output-branch', required=True,
                        help='New branch name to create.')
    parser.add_argument('--base-branch',   required=True,
                        help='Base branch of INPUT_BRANCH and OUTPUT_BRANCH.')
    parser.add_argument('--report',        help=argparse.SUPPRESS)
    parser.add_argument('--force-output',  action='store_true',
                        help='Delete OUTPUT_BRANCH if it already exists.')
    parser.add_argument('--allow-dirty',   action='store_true',
                        help='Skip the clean-worktree check.')
    parser.add_argument('--no-g8-promotion', action='store_true',
                        help='Disable promotion of Remaining (g11) commits '
                             'into Group 8 (Upstream bug fixes); only commits '
                             'whose subject already starts with "[upstream]" '
                             'land in g8.')
    parser.add_argument(
        '--color',
        choices=('auto', 'always', 'never'),
        default='auto',
        help='Colorize stderr output (default: auto; respects NO_COLOR / FORCE_COLOR).')
    args = parser.parse_args()
    configure_style(args.color)

    # Inside a git repo?
    if run_git(['rev-parse', '--show-toplevel'], check=False).returncode != 0:
        log_error("not inside a git repository")
        return 1

    if not args.allow_dirty:
        ensure_clean_worktree()

    input_hash = git_rev_parse(args.input_branch)
    base_hash  = git_rev_parse(args.base_branch)

    if run_git(['merge-base', '--is-ancestor', base_hash, input_hash],
               check=False).returncode != 0:
        raise RuntimeError(
            f"{args.base_branch!r} ({base_hash[:12]}) is not an ancestor "
            f"of {args.input_branch!r} ({input_hash[:12]}).")

    if input_hash == base_hash:
        raise RuntimeError("INPUT_BRANCH and BASE_BRANCH point to the same "
                           "commit — nothing to reorder.")

    if branch_exists(args.output_branch) and not args.force_output:
        raise RuntimeError(
            f"Output branch {args.output_branch!r} already exists; pass "
            f"--force-output to overwrite.")

    log(f"{STYLE.bold('Input:')}  {args.input_branch}  ({short_sha(input_hash)})")
    log(f"{STYLE.bold('Base:')}   {args.base_branch}   ({short_sha(base_hash)})")
    log(f"{STYLE.bold('Output:')} {args.output_branch}")

    commits = get_commit_list(base_hash, input_hash)
    log(f"{STYLE.bold('Analyzing removed paths')} across "
        f"{len(commits)} source commits...")
    removed_paths = analyze_removed_paths(commits, base_hash, input_hash)
    log(f"  base-branch removed files: {len(removed_paths['base_removed'])}")
    log(f"  input-only removed files to skip: "
        f"{len(removed_paths['transient_removed'])}")
    log_removed_paths(removed_paths)
    log(f"{STYLE.bold('Planning')} {len(commits)} source commits...")
    plan = plan_commits(commits, base_hash, removed_paths)

    log(f"{STYLE.bold('Building')} output branch...")
    stats = build_output_branch(args, input_hash, base_hash, plan)
    log_removed_commits_by_reason(plan)

    null_ok = log_terminal_summary(args, input_hash, base_hash, plan, stats)

    status = STYLE.green('OK') if null_ok else STYLE.red('MISMATCH')
    log(f"{STYLE.bold('Done.')} Null diff to INPUT_BRANCH: {status}")
    return 0 if null_ok else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except RuntimeError as e:
        log_error(str(e))
        sys.exit(1)

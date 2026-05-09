#!/usr/bin/env python3
"""
ps-log.py

Print git commits in the color-formatted single-line layout used by
ps-reorder.py:

    <files>f  <insertions>+  <deletions>- <short-sha> <subject>

Files / insertions / deletions are computed via `git show --shortstat`
fanned out across a thread pool (--jobs, default 32) — git itself is
single-threaded per process, so parallelizing is what makes this fast
on large ranges. Short-sha is 12 characters, and the subject is
truncated to keep each line within OUTPUT_STAT_LINE_LEN columns.
Output is newest-first by default, matching `git log`. Use `--reverse`
to flip the order.

Usage:
  ps-log.py [--color auto|always|never] [--reverse] [-n N]
            [--path PATHSPEC]... [--section PATHSPEC]... [--all-section]
            [--sort none|desc|asc] [--top N] [-j JOBS]
            [<git log args>...]

Examples:
  ps-log.py -n 20
  ps-log.py master..feature
  ps-log.py --reverse v8.0.32..HEAD -- storage/innobase
  ps-log.py --path 'sql/*' --sort desc -n 50
  ps-log.py --path 'sql_*.cc' --path 'sql_*.h' --sort desc
  ps-log.py mysql-8.0.12..feature --sort desc --top 10 \
      --section 'storage/innobase/*' --section 'sql/*' --all-section
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys


MAX_TITLE_LEN = 91
LARGE_COMMIT_THRESHOLD = 10000
OUTPUT_STAT_LINE_LEN = 104
OUTPUT_STAT_FILES_WIDTH = 5
OUTPUT_STAT_COUNT_WIDTH = 5


class Style:
    """ANSI styling for terminal output; a no-op when disabled."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled or not text:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, t): return self._wrap("1", t)
    def red(self, t): return self._wrap("31", t)
    def green(self, t): return self._wrap("32", t)
    def yellow(self, t): return self._wrap("33", t)
    def magenta(self, t): return self._wrap("35", t)
    def cyan(self, t): return self._wrap("36", t)
    def default(self, t): return self._wrap("39", t)
    def bold_default(self, t): return self._wrap("1;39", t)
    def bold_red(self, t): return self._wrap("1;31", t)
    def bold_magenta(self, t): return self._wrap("1;35", t)


STYLE = Style(False)


def configure_style(mode: str) -> None:
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
    STYLE.enabled = sys.stdout.isatty()


def run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True, text=True, check=True,
    )


FILES_RE = re.compile(r"(\d+) files? changed")
INS_RE = re.compile(r"(\d+) insertion")
DEL_RE = re.compile(r"(\d+) deletion")


def list_commits_with_subjects(log_args: list[str], reverse: bool,
                               limit: int | None,
                               paths: list[str] | None
                               ) -> list[tuple[str, str]]:
    """One cheap `git log` call returning (sha, subject) pairs."""
    cmd = ["log", "--no-merges", "--format=%H%x09%s"]
    if limit is not None:
        cmd.append(f"-n{limit}")
    if reverse:
        cmd.append("--reverse")
    cmd.extend(log_args)
    if paths:
        if "--" not in log_args:
            cmd.append("--")
        cmd.extend(paths)
    r = run_git(cmd)
    items: list[tuple[str, str]] = []
    for line in r.stdout.splitlines():
        if "\t" not in line:
            continue
        h, s = line.split("\t", 1)
        items.append((h, s))
    return items


def shortstat_for(sha: str,
                  paths: list[str] | None) -> tuple[int, int, int]:
    cmd = ["git", "-c", "diff.renames=false", "show", "--no-patch",
           "--format=", "--shortstat", sha]
    if paths:
        cmd.append("--")
        cmd.extend(paths)
    text = subprocess.run(cmd, capture_output=True, text=True,
                          check=True).stdout
    files = ins = dele = 0
    m = FILES_RE.search(text)
    if m:
        files = int(m.group(1))
    m = INS_RE.search(text)
    if m:
        ins = int(m.group(1))
    m = DEL_RE.search(text)
    if m:
        dele = int(m.group(1))
    return files, ins, dele


def fetch_rows(log_args: list[str], reverse: bool, limit: int | None,
               paths: list[str] | None, jobs: int
               ) -> list[tuple[str, str, int, int, int]]:
    items = list_commits_with_subjects(log_args, reverse, limit, paths)
    if not items:
        return []
    paths_t = tuple(paths) if paths else None

    def one(item: tuple[str, str]) -> tuple[str, str, int, int, int]:
        h, s = item
        files, ins, dele = shortstat_for(
            h, list(paths_t) if paths_t else None)
        return (h, s, files, ins, dele)

    if jobs <= 1 or len(items) == 1:
        return [one(it) for it in items]
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, jobs)) as ex:
        return list(ex.map(one, items, chunksize=8))


def compact_count(n: int) -> str:
    if n >= 1000000:
        return f"{n // 1000000}M"
    if n >= 10000:
        return f"{n // 1000}K"
    return str(n)


def format_stats_line(files: int, ins: int, dele: int,
                      ch: str, subject: str) -> str:
    files_field = f"{compact_count(files)}f".ljust(OUTPUT_STAT_FILES_WIDTH)
    ins_field = f"{compact_count(ins)}+".rjust(OUTPUT_STAT_COUNT_WIDTH)
    del_field = f"{compact_count(dele)}-".rjust(OUTPUT_STAT_COUNT_WIDTH)
    line = f"{files_field}{ins_field} {del_field} {ch[:12]} {subject}"
    return line[:OUTPUT_STAT_LINE_LEN]


def subject_style(text: str, bold: bool, red: bool) -> str:
    if red and bold:
        return STYLE.bold_red(text)
    if red:
        return STYLE.red(text)
    return STYLE.bold_default(text) if bold else STYLE.default(text)


def colorize_stats_line(line: str, bold_subject: bool,
                        red_subject: bool) -> str:
    if not STYLE.enabled:
        return line
    m = re.match(r"^(\S+)(\s+)(\S+)(\s+)(\S+)(\s+)"
                 r"(\S{12})(\s?)(.*)$", line)
    if not m:
        return line
    return (
        m.group(1) + m.group(2) +
        STYLE.green(m.group(3)) + m.group(4) +
        STYLE.red(m.group(5)) + m.group(6) +
        STYLE.yellow(m.group(7)) + m.group(8) +
        subject_style(m.group(9), bold_subject, red_subject))


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Print git commits as colored <files>f <ins>+ <del>- "
                    "<sha> <subject> lines.",
        usage="%(prog)s [options] [<git log args>...]",
    )
    parser.add_argument("--color", choices=("auto", "always", "never"),
                        default="auto")
    parser.add_argument("--reverse", action="store_true",
                        help="Print oldest commits first (git log order)")
    parser.add_argument("-n", "--max-count", type=int, default=None,
                        help="Limit number of commits")
    parser.add_argument("--path", action="append", default=[],
                        metavar="PATHSPEC",
                        help="Restrict commits and stats to the given "
                             "pathspec (e.g. 'sql/*', 'sql_*.cc'). May be "
                             "passed multiple times; all entries are combined "
                             "into a single filter. Commits with no changes "
                             "in the pathspec are dropped.")
    parser.add_argument("--section", action="append", default=[],
                        metavar="PATHSPEC",
                        help="Render an additional section restricted to "
                             "PATHSPEC. May be passed multiple times. "
                             "Each section gets its own '=== PATHSPEC ===' "
                             "header and TOTAL line. Mutually exclusive "
                             "with --path.")
    parser.add_argument("--all-section", action="store_true",
                        help="Add an unrestricted '=== ALL paths ===' "
                             "section. Useful together with --section to "
                             "show the overall top commits alongside "
                             "per-path breakdowns.")
    parser.add_argument("--sort", choices=("none", "desc", "asc"),
                        default="none",
                        help="Sort commits by total lines changed "
                             "(insertions + deletions). Default: none "
                             "(git log order).")
    parser.add_argument("--top", type=int, default=None, metavar="N",
                        help="After sorting and pathspec filtering, print "
                             "at most N rows. Differs from -n, which limits "
                             "commits before they are sorted.")
    parser.add_argument("-j", "--jobs", type=int, default=32, metavar="N",
                        help="Parallel workers for shortstat (default: 32). "
                             "Lower this to reduce concurrency.")
    return parser.parse_known_args(argv)


def render_section(label: str | None, log_args: list[str],
                   reverse: bool, max_count: int | None,
                   paths: list[str] | None, sort: str, top: int | None,
                   jobs: int) -> None:
    if label is not None:
        header = f"=== {label} ==="
        if STYLE.enabled:
            header = STYLE.bold(STYLE.cyan(header))
        print(header, flush=True)

    rows = fetch_rows(log_args, reverse, max_count, paths, jobs)
    if paths:
        rows = [r for r in rows if (r[2] + r[3] + r[4]) > 0]
    range_count = len(rows)

    if sort != "none":
        rows.sort(key=lambda r: r[3] + r[4], reverse=(sort == "desc"))

    if top is not None:
        rows = rows[:max(top, 0)]

    total_files = total_ins = total_dele = 0
    for ch, subject, files, ins, dele in rows:
        line = format_stats_line(files, ins, dele, ch, subject)
        bold = (ins + dele) <= 8
        red = dele > ins
        print(colorize_stats_line(line, bold, red), flush=True)
        total_files += files
        total_ins += ins
        total_dele += dele

    if rows:
        if len(rows) == range_count:
            total_subject = f"TOTAL ({len(rows)} commits)"
        else:
            total_subject = (
                f"TOTAL ({len(rows)} of {range_count} commits)")
        line = format_stats_line(total_files, total_ins, total_dele,
                                 "-" * 12, total_subject)
        print(colorize_stats_line(line, bold_subject=True,
                                  red_subject=total_dele > total_ins),
              flush=True)


def main(argv: list[str]) -> int:
    args, log_args = parse_args(argv)
    configure_style(args.color)

    if args.section and args.path:
        sys.stderr.write(
            "error: --section and --path are mutually exclusive\n")
        return 2

    sections: list[tuple[str | None, list[str] | None]] = []
    if args.section or args.all_section:
        for ps in args.section:
            sections.append((ps, [ps]))
        if args.all_section:
            sections.append(("ALL paths", None))
    else:
        sections.append((None, args.path or None))

    try:
        for i, (label, paths) in enumerate(sections):
            if i > 0:
                print()
            render_section(label, log_args, args.reverse, args.max_count,
                           paths, args.sort, args.top, args.jobs)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.stderr or f"git failed ({e.returncode})\n")
        return e.returncode or 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

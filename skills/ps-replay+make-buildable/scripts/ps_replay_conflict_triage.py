#!/usr/bin/env python3
"""Triage the current cherry-pick conflict state against a reference branch.

For each unmerged path, classify as:
  * auto-match     - no conflict markers, worktree byte-identical to reference
  * auto-mismatch  - no conflict markers but content differs from reference
                     (likely rerere resolved to a non-reference state; review)
  * unresolved     - one or more conflict markers still present

Optionally `--auto-stage` will `git add` the auto-match files only, leaving
the rest for manual hunk-level work.

This is the script you want first after every batch stop on a conflict, to
decide what (if anything) you can stage immediately and what needs a real
hunk-level decision.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


CONFLICT_MARKER_RE = (
    "^<<<<<<<",
    "^>>>>>>>",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Classify current cherry-pick conflicts as auto-match / "
            "auto-mismatch / unresolved against a reference branch."
        )
    )
    parser.add_argument(
        "--reference",
        required=True,
        help="Reference branch or commit to compare against",
    )
    parser.add_argument(
        "--worktree",
        type=Path,
        default=Path.cwd(),
        help="Git worktree (default: current directory)",
    )
    parser.add_argument(
        "--auto-stage",
        action="store_true",
        help=(
            "Stage (`git add`) every auto-match file. Files in other "
            "categories are never touched."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the per-file table; print only the summary counts",
    )
    return parser.parse_args()


def git(args: List[str], cwd: Path, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )
    return result.stdout


def unmerged_paths(cwd: Path) -> List[str]:
    """Return paths that are currently in conflict (any unmerged stage)."""
    out = git(["ls-files", "-u", "-z"], cwd)
    if not out:
        return []
    paths: List[str] = []
    seen: set = set()
    for entry in out.split("\0"):
        if not entry:
            continue
        # Format: "<mode> <sha> <stage>\t<path>"
        try:
            _, path = entry.split("\t", 1)
        except ValueError:
            continue
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def count_conflict_markers(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        text = path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return 0
    count = 0
    for line in text.splitlines():
        if line.startswith("<<<<<<<") or line.startswith(">>>>>>>"):
            count += 1
    return count


def diff_lines_vs_reference(reference: str, path: str, cwd: Path) -> int:
    """Return the line count of `git diff <reference> -- <path>`.

    Zero means worktree matches reference exactly for this path.
    """
    out = git(["diff", reference, "--", path], cwd, check=False)
    if not out:
        return 0
    return out.count("\n")


def classify(
    paths: List[str], reference: str, cwd: Path
) -> List[Tuple[str, str, int, int]]:
    rows: List[Tuple[str, str, int, int]] = []
    for path in paths:
        full = cwd / path
        markers = count_conflict_markers(full)
        diff_lines = diff_lines_vs_reference(reference, path, cwd)
        if markers > 0:
            status = "unresolved"
        elif diff_lines == 0:
            status = "auto-match"
        else:
            status = "auto-mismatch"
        rows.append((status, path, markers, diff_lines))
    # Sort by status (auto-match first so they're cheap-and-obvious),
    # then by file path.
    order = {"auto-match": 0, "auto-mismatch": 1, "unresolved": 2}
    rows.sort(key=lambda r: (order.get(r[0], 99), r[1]))
    return rows


def main() -> int:
    args = parse_args()
    cwd = args.worktree

    paths = unmerged_paths(cwd)
    if not paths:
        print("no conflicted paths in worktree")
        return 0

    rows = classify(paths, args.reference, cwd)

    counts = {"auto-match": 0, "auto-mismatch": 0, "unresolved": 0}
    for status, *_ in rows:
        counts[status] += 1

    if not args.quiet:
        print(f"{'STATUS':<14}{'MARKERS':>8}{'DIFFLINES':>11}  PATH")
        for status, path, markers, diff_lines in rows:
            print(f"{status:<14}{markers:>8}{diff_lines:>11}  {path}")
        print()

    print(
        f"summary: auto-match={counts['auto-match']} "
        f"auto-mismatch={counts['auto-mismatch']} "
        f"unresolved={counts['unresolved']}"
    )

    if args.auto_stage and counts["auto-match"]:
        to_stage = [p for s, p, _m, _d in rows if s == "auto-match"]
        git(["add", "--", *to_stage], cwd)
        print(f"staged {len(to_stage)} auto-match file(s)")
        if counts["auto-mismatch"] == 0 and counts["unresolved"] == 0:
            print(
                "all conflicts resolved by reference auto-match; "
                "you can `git cherry-pick --continue` now"
            )

    if counts["unresolved"] or counts["auto-mismatch"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

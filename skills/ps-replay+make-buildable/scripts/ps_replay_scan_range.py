#!/usr/bin/env python3
"""Scan the source/reference range for special commits before replay.

Surfaces things that change the strategy:

  * gcc-9 build-fix commits ("Fix gcc-9 compilation issues")
  * snap commits ("Snap to ...")
  * empty-marker commits ("=== MARKER:")
  * squash commits ("Squash:")
  * merge commits

It also compares `$BASE..$TIP` against `$BASE..$REFERENCE` (when those
differ) and lists commits present in the reference range but missing
from the tip range. That last case is the one we hit in practice: the
reference branch had a post-snap gcc-9 fix that wasn't part of the
saved tip-range source list.

Run this BEFORE generating the source list and starting the replay.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("gcc-9-fix", re.compile(r"Fix gcc-9 compilation", re.IGNORECASE)),
    ("snap", re.compile(r"^Snap to\b", re.IGNORECASE)),
    ("marker", re.compile(r"=== MARKER:", re.IGNORECASE)),
    ("squash", re.compile(r"^Squash:", re.IGNORECASE)),
]


@dataclass
class Commit:
    sha: str
    subject: str

    def classify(self) -> List[str]:
        kinds = [name for name, pat in PATTERNS if pat.search(self.subject)]
        return kinds or ["normal"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a Percona replay source range for special commits and "
            "highlight reference-only commits that the tip range misses."
        )
    )
    parser.add_argument("--base", required=True, help="Base branch / commit")
    parser.add_argument("--tip", required=True, help="Tip branch / commit")
    parser.add_argument(
        "--reference",
        required=True,
        help=(
            "Reference branch / commit. May equal --tip; if it differs, "
            "commits in reference-only are flagged."
        ),
    )
    parser.add_argument(
        "--worktree",
        type=Path,
        default=Path.cwd(),
        help="Git worktree (default: current directory)",
    )
    return parser.parse_args()


def git_lines(args: List[str], cwd: Path) -> List[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def list_range(base: str, tip: str, cwd: Path) -> List[Commit]:
    raw = git_lines(
        ["log", "--reverse", "--pretty=%H%x09%s", f"{base}..{tip}"],
        cwd,
    )
    out: List[Commit] = []
    for line in raw:
        sha, _, subject = line.partition("\t")
        out.append(Commit(sha=sha, subject=subject))
    return out


def render_buckets(commits: List[Commit]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for c in commits:
        for kind in c.classify():
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def main() -> int:
    args = parse_args()

    tip_commits = list_range(args.base, args.tip, args.worktree)
    print(f"=== {args.base}..{args.tip} ({len(tip_commits)} commits)")
    counts = render_buckets(tip_commits)
    for kind in ("gcc-9-fix", "snap", "marker", "squash", "normal"):
        if kind in counts:
            print(f"  {kind:<11} {counts[kind]}")

    print()
    print("special commits in tip range:")
    for idx, commit in enumerate(tip_commits, start=1):
        kinds = [k for k in commit.classify() if k != "normal"]
        if kinds:
            kind_str = ",".join(kinds)
            print(f"  [{idx:>3}] {commit.sha[:12]} [{kind_str}] {commit.subject}")

    if args.reference != args.tip:
        print()
        ref_commits = list_range(args.base, args.reference, args.worktree)
        tip_shas = {c.sha for c in tip_commits}
        ref_only = [c for c in ref_commits if c.sha not in tip_shas]
        print(
            f"=== {args.base}..{args.reference} "
            f"({len(ref_commits)} commits; "
            f"{len(ref_only)} reference-only)"
        )
        if ref_only:
            print("commits in reference but not in tip:")
            for c in ref_only:
                kinds = ",".join(c.classify())
                print(f"  {c.sha[:12]} [{kinds}] {c.subject}")
            print()
            print(
                "WARNING: reference range differs from tip range. "
                "Verify whether reference-only commits should be applied "
                "as out-of-range fixes (e.g. a post-snap gcc-9 fix)."
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

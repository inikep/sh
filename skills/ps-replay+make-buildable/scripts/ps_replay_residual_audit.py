#!/usr/bin/env python3
"""Audit the residual diff between OUTPUT_BRANCH and REFERENCE_BRANCH.

Use after the source range has been replayed, when `git diff $OUTPUT
$REFERENCE` is non-empty and you want to know whether the residual is
trivial (whitespace, single-line edits) or substantive (real content
deltas) before deciding on reconciliation commits.

Each hunk is classified as one of:
  whitespace   - all added/removed lines are blank or whitespace-only
  trivial      - <= --trivial-lines net non-whitespace change (default 1)
  substantive  - more than --trivial-lines change

Output is grouped per file, with a global summary at the end.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
FILE_HEADER_RE = re.compile(r"^\+\+\+ b/(.*)$")


@dataclass
class Hunk:
    file: str
    new_start: int
    added: List[str]
    removed: List[str]

    @property
    def added_nonblank(self) -> List[str]:
        return [line for line in self.added if line.strip()]

    @property
    def removed_nonblank(self) -> List[str]:
        return [line for line in self.removed if line.strip()]

    def classify(self, trivial_lines: int) -> str:
        net = len(self.added_nonblank) + len(self.removed_nonblank)
        if net == 0:
            return "whitespace"
        if net <= trivial_lines:
            return "trivial"
        return "substantive"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Classify hunks in `git diff <output> <reference>` as "
            "whitespace / trivial / substantive."
        )
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output branch / commit (left side of diff)",
    )
    parser.add_argument(
        "--reference",
        required=True,
        help="Reference branch / commit (right side of diff)",
    )
    parser.add_argument(
        "--worktree",
        type=Path,
        default=Path.cwd(),
        help="Git worktree (default: current directory)",
    )
    parser.add_argument(
        "--trivial-lines",
        type=int,
        default=1,
        help=(
            "Maximum non-whitespace +/- lines per hunk to count as "
            "'trivial' (default: 1)"
        ),
    )
    parser.add_argument(
        "--show-substantive",
        action="store_true",
        help="Print the body of each substantive hunk",
    )
    return parser.parse_args()


def run_diff(output: str, reference: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--no-color", output, reference],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def parse_hunks(diff_text: str) -> List[Hunk]:
    hunks: List[Hunk] = []
    current_file: str = ""
    current: Hunk | None = None
    for line in diff_text.splitlines():
        m_file = FILE_HEADER_RE.match(line)
        if m_file:
            current_file = m_file.group(1)
            continue
        m_hunk = HUNK_HEADER_RE.match(line)
        if m_hunk:
            if current is not None:
                hunks.append(current)
            current = Hunk(
                file=current_file,
                new_start=int(m_hunk.group(2)),
                added=[],
                removed=[],
            )
            continue
        if current is None:
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            current.added.append(line[1:])
        elif line.startswith("-"):
            current.removed.append(line[1:])
    if current is not None:
        hunks.append(current)
    return hunks


def render(
    hunks: Iterable[Hunk],
    trivial_lines: int,
    show_substantive: bool,
) -> int:
    counts = {"whitespace": 0, "trivial": 0, "substantive": 0}
    by_file: dict[str, List[tuple[str, Hunk]]] = {}
    for hunk in hunks:
        kind = hunk.classify(trivial_lines)
        counts[kind] += 1
        by_file.setdefault(hunk.file, []).append((kind, hunk))

    for path, entries in sorted(by_file.items()):
        kinds = [k for k, _ in entries]
        worst = (
            "substantive"
            if "substantive" in kinds
            else ("trivial" if "trivial" in kinds else "whitespace")
        )
        print(
            f"{worst:<12} {len(entries):>2} hunk(s)  {path}  "
            f"(ws={kinds.count('whitespace')} "
            f"triv={kinds.count('trivial')} "
            f"subst={kinds.count('substantive')})"
        )
        if show_substantive:
            for kind, hunk in entries:
                if kind != "substantive":
                    continue
                print(f"  @@ +{hunk.new_start} @@")
                for line in hunk.removed:
                    print(f"  - {line}")
                for line in hunk.added:
                    print(f"  + {line}")
                print()

    print()
    print(
        f"summary: whitespace={counts['whitespace']} "
        f"trivial={counts['trivial']} "
        f"substantive={counts['substantive']}"
    )
    return counts["substantive"]


def main() -> int:
    args = parse_args()
    diff_text = run_diff(args.output, args.reference, args.worktree)
    if not diff_text.strip():
        print("no residual diff; trees are identical")
        return 0
    hunks = parse_hunks(diff_text)
    if not hunks:
        print("no hunks parsed (diff is non-empty but contains no changes)")
        return 0
    substantive = render(hunks, args.trivial_lines, args.show_substantive)
    return 1 if substantive else 0


if __name__ == "__main__":
    sys.exit(main())

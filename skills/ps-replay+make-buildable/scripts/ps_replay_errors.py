#!/usr/bin/env python3
"""Extract actionable build diagnostics from a Percona replay build log."""

from __future__ import annotations

import argparse
import re
from collections import deque
from pathlib import Path


PATTERNS = [
    r"\berror:",
    r"\bfatal error:",
    r"undefined reference",
    r"multiple definition",
    r"collect2: error",
    r"ld returned",
    r"CMake Error",
    r"Configuring incomplete",
    r"No such file or directory",
    r"was not declared in this scope",
    r"has no member named",
    r"conflicting declaration",
    r"ABI check",
    r"Error [0-9]+",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print likely root-cause errors from a large build log."
    )
    parser.add_argument("log", type=Path, help="Build log to inspect")
    parser.add_argument(
        "--context",
        type=int,
        default=2,
        help="Lines of context before and after each match (default: 2)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Maximum matches to print (default: 40)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    needle = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.IGNORECASE)

    if not args.log.exists():
        raise SystemExit(f"log does not exist: {args.log}")

    previous: deque[tuple[int, str]] = deque(maxlen=args.context)
    pending_after = 0
    printed = 0
    last_printed_line = 0

    with args.log.open(errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            is_match = bool(needle.search(line))
            if is_match and printed >= args.limit:
                continue

            if is_match:
                if line_no > last_printed_line + 1:
                    print("--")
                for prev_no, prev_line in previous:
                    if prev_no > last_printed_line:
                        print(f"{prev_no}: {prev_line.rstrip()}")
                        last_printed_line = prev_no
                print(f"{line_no}: {line.rstrip()}")
                last_printed_line = line_no
                printed += 1
                pending_after = args.context
            elif pending_after > 0:
                print(f"{line_no}: {line.rstrip()}")
                last_printed_line = line_no
                pending_after -= 1

            previous.append((line_no, line))

    if printed == 0:
        print(f"No likely build errors found in {args.log}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

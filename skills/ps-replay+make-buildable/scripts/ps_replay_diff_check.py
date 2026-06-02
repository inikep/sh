#!/usr/bin/env python3
"""Run git diff --check while preserving reference-matching whitespace."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


CHECK_RE = re.compile(r"^(.+):(\d+): (.+)$")


@dataclass
class DiffCheckWarning:
    path: str
    line: int
    message: str
    added_line: str | None = None


@dataclass
class ClassifiedWarning:
    warning: DiffCheckWarning
    reference_matching: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run git diff --check and allow whitespace warnings whose exact "
            "warned line already exists in the reference tree."
        )
    )
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--reference", required=True)
    parser.add_argument("--cached", action="store_true", help="Check the staged diff.")
    parser.add_argument("paths", nargs="*", help="Optional pathspecs.")
    return parser.parse_args()


def git(worktree: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def git_text(worktree: Path, args: list[str], check: bool = True) -> str:
    return git(worktree, args, check=check).stdout.decode("utf-8", errors="replace")


def parse_diff_check_output(text: str) -> list[DiffCheckWarning]:
    warnings: list[DiffCheckWarning] = []
    current: DiffCheckWarning | None = None
    for line in text.splitlines():
        match = CHECK_RE.match(line)
        if match:
            current = DiffCheckWarning(
                path=match.group(1),
                line=int(match.group(2)),
                message=match.group(3),
            )
            warnings.append(current)
            continue
        if current is not None and line.startswith("+"):
            current.added_line = line[1:]
        current = None
    return warnings


def reference_lines(worktree: Path, reference: str, path: str) -> list[str]:
    proc = git(worktree, ["show", f"{reference}:{path}"], check=False)
    if proc.returncode != 0:
        return []
    return proc.stdout.decode("utf-8", errors="replace").splitlines()


def warning_matches_reference(
    warning: DiffCheckWarning,
    get_reference_lines: Callable[[str], Iterable[str]],
) -> bool:
    ref_lines = list(get_reference_lines(warning.path))
    if warning.message == "new blank line at EOF.":
        return (warning.added_line in (None, "")) and bool(ref_lines) and ref_lines[-1] == ""
    if warning.added_line is None:
        return False
    if "whitespace" not in warning.message and "space before tab" not in warning.message:
        return False
    return warning.added_line in ref_lines


def classify_warnings(
    warnings: Iterable[DiffCheckWarning],
    get_reference_lines: Callable[[str], Iterable[str]],
) -> list[ClassifiedWarning]:
    return [
        ClassifiedWarning(warning, warning_matches_reference(warning, get_reference_lines))
        for warning in warnings
    ]


def run_diff_check(worktree: Path, cached: bool, paths: list[str]) -> subprocess.CompletedProcess[bytes]:
    cmd = ["diff", "--check"]
    if cached:
        cmd.insert(1, "--cached")
    if paths:
        cmd.extend(["--", *paths])
    return git(worktree, cmd, check=False)


def main() -> int:
    args = parse_args()
    worktree = args.worktree.resolve()
    proc = run_diff_check(worktree, args.cached, args.paths)
    output = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode == 0:
        print("diff-check PASS")
        return 0

    warnings = parse_diff_check_output(output)
    if not warnings:
        print(output, end="")
        return proc.returncode

    classified = classify_warnings(
        warnings,
        lambda path: reference_lines(worktree, args.reference, path),
    )
    for item in classified:
        status = "REFERENCE-MATCH" if item.reference_matching else "NEW-WARNING"
        warning = item.warning
        print(f"{status}\t{warning.path}:{warning.line}\t{warning.message}")
        if warning.added_line is not None:
            print(f"  line={warning.added_line!r}")

    if all(item.reference_matching for item in classified):
        print("diff-check warnings are reference-matching; preserve them")
        return 0
    print("diff-check found warnings absent from reference")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

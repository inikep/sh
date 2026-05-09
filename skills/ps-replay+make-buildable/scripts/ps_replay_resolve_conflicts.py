#!/usr/bin/env python3
"""Inspect cherry-pick conflicts and print hunk-level reference guidance.

This helper intentionally does not modify the worktree. The skill forbids
snap-to-REFERENCE, so this script reports conflicted files, conflict blocks,
and nearby reference snippets for manual hunk-level resolution.
"""

from __future__ import annotations

import argparse
import difflib
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConflictBlock:
    start_line: int
    end_line: int
    ours: list[str]
    theirs: list[str]
    before: list[str]
    after: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect current conflicts and print hunk-level reference guidance."
    )
    parser.add_argument("--reference", required=True, help="Reference branch or commit")
    parser.add_argument(
        "--worktree",
        type=Path,
        default=Path.cwd(),
        help="Git worktree (default: current directory)",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=6,
        help="Context lines to show around reference candidates (default: 6)",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        help="Optional markdown file to append a conflict summary to",
    )
    return parser.parse_args()


def git(worktree: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def git_output(worktree: Path, args: list[str]) -> str:
    return git(worktree, args).stdout.strip()


def conflicted_paths(worktree: Path) -> list[Path]:
    names = set(git_output(worktree, ["diff", "--name-only", "--diff-filter=U"]).splitlines())
    for line in git_output(worktree, ["status", "--porcelain"]).splitlines():
        if line[:2] in {"UU", "UD", "DU", "AA", "DD", "AU", "UA"}:
            names.add(line[3:])
    return [Path(name) for name in sorted(name for name in names if name)]


def reference_lines(worktree: Path, reference: str, path: Path) -> list[str] | None:
    proc = subprocess.run(
        ["git", "show", f"{reference}:{path.as_posix()}"],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.splitlines()


def parse_conflicts(path: Path, context: int) -> list[ConflictBlock]:
    if not path.exists() or not path.is_file():
        return []

    lines = path.read_text(errors="replace").splitlines()
    blocks: list[ConflictBlock] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("<<<<<<< "):
            i += 1
            continue

        start = i
        i += 1
        ours: list[str] = []
        while i < len(lines) and lines[i] != "=======":
            ours.append(lines[i])
            i += 1

        if i >= len(lines):
            break
        i += 1
        theirs: list[str] = []
        while i < len(lines) and not lines[i].startswith(">>>>>>> "):
            theirs.append(lines[i])
            i += 1

        if i >= len(lines):
            break
        end = i
        before = lines[max(0, start - context) : start]
        after = lines[end + 1 : min(len(lines), end + 1 + context)]
        blocks.append(
            ConflictBlock(
                start_line=start + 1,
                end_line=end + 1,
                ours=ours,
                theirs=theirs,
                before=before,
                after=after,
            )
        )
        i += 1

    return blocks


def find_reference_window(ref: list[str], block: ConflictBlock, context: int) -> tuple[int, int] | None:
    anchors = [line for line in reversed(block.before) if line.strip()]
    anchors.extend(line for line in block.after if line.strip())
    anchors.extend(line for line in block.ours if line.strip())
    anchors.extend(line for line in block.theirs if line.strip())

    for anchor in anchors:
        for idx, line in enumerate(ref):
            if line == anchor:
                return max(0, idx - context), min(len(ref), idx + context + 1)

    choices = [line for line in ref if line.strip()]
    probes = [line for line in block.before + block.after + block.ours + block.theirs if line.strip()]
    if not choices or not probes:
        return None
    matches = difflib.get_close_matches(probes[0], choices, n=1, cutoff=0.75)
    if not matches:
        return None
    idx = ref.index(matches[0])
    return max(0, idx - context), min(len(ref), idx + context + 1)


def append_report(report: Path | None, line: str) -> None:
    if report is None:
        return
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("a") as fh:
        fh.write(line + "\n")


def print_block(path: Path, block_no: int, block: ConflictBlock, ref: list[str] | None, context: int) -> None:
    print(f"\n## {path} conflict {block_no} lines {block.start_line}-{block.end_line}")
    print("\n### Ours")
    for line in block.ours[:80]:
        print(line)
    if len(block.ours) > 80:
        print(f"... {len(block.ours) - 80} more ours lines")

    print("\n### Theirs")
    for line in block.theirs[:80]:
        print(line)
    if len(block.theirs) > 80:
        print(f"... {len(block.theirs) - 80} more theirs lines")

    if ref is None:
        print("\n### Reference")
        print("Path is absent from reference; resolve only the conflicting add/delete hunk manually.")
        return

    window = find_reference_window(ref, block, context)
    print("\n### Reference Candidate")
    if window is None:
        print("No nearby reference window found automatically; inspect the reference file manually.")
        return

    start, end = window
    for idx in range(start, end):
        print(f"{idx + 1}: {ref[idx]}")


def main() -> int:
    args = parse_args()
    worktree = args.worktree.resolve()
    paths = conflicted_paths(worktree)
    if not paths:
        print("no conflicted paths")
        return 0

    append_report(args.report_file, f"- Conflict inspection against `{args.reference}`:")
    for path in paths:
        full_path = worktree / path
        blocks = parse_conflicts(full_path, args.context)
        ref = reference_lines(worktree, args.reference, path)
        status = "missing from reference" if ref is None else "reference present"
        print(f"\n# {path}: {len(blocks)} conflict block(s), {status}")
        append_report(
            args.report_file,
            f"  - `{path}`: {len(blocks)} conflict block(s), {status}; hunk-level manual resolution required.",
        )
        if not blocks:
            print("No conflict markers found. Inspect index stages manually; no file was modified.")
        for block_no, block in enumerate(blocks, 1):
            print_block(path, block_no, block, ref, args.context)

    print("\nNo files were modified. Resolve hunks manually, then run git add and git cherry-pick --continue.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

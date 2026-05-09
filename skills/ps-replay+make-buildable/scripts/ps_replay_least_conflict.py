#!/usr/bin/env python3
"""Rank mysql-5.6.26 initial-tree replay candidates by trial conflict count.

This helper is intentionally limited to the branch-specific rule for
BASE_BRANCH=mysql-5.6.26. It creates a temporary worktree at the current
OUTPUT_BRANCH HEAD, trial-applies each remaining "Initial Percona Server 5.6.22
tree" candidate, counts conflicted files, removes the temporary worktree, and
prints the lowest-conflict candidate first. It never applies the selected
candidate to the real worktree.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


REQUIRED_BASE_BRANCH = "mysql-5.6.26"
INITIAL_TREE_PREFIX = "Initial Percona Server 5.6.22 tree"


@dataclass(frozen=True)
class Candidate:
    index: int
    sha: str
    subject: str


@dataclass(frozen=True)
class TrialResult:
    candidate: Candidate
    conflicts: int
    status: str
    detail: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rank remaining mysql-5.6.26 Initial Percona Server 5.6.22 tree "
            "candidates by least conflicted files against the current HEAD."
        )
    )
    parser.add_argument("--base-branch", required=True)
    parser.add_argument("--source-list", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument(
        "--remaining-indices",
        help="Comma-separated 1-based indices or ranges, for example 10,12-18,21.",
    )
    parser.add_argument("--start", type=int, help="1-based first candidate index")
    parser.add_argument("--end", type=int, help="1-based last candidate index")
    parser.add_argument(
        "--subject-prefix",
        default=INITIAL_TREE_PREFIX,
        help="Only subjects starting with this prefix are considered.",
    )
    parser.add_argument(
        "--porcelain",
        action="store_true",
        help="Print only TSV rows: index, sha, conflicts, status, subject.",
    )
    return parser.parse_args()


def run_git(
    worktree: Path,
    git_args: list[str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *git_args],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def git_output(worktree: Path, git_args: list[str]) -> str:
    return run_git(worktree, git_args).stdout.strip()


def parse_index_set(value: str) -> set[int]:
    indices: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError(f"invalid descending range: {part}")
            indices.update(range(start, end + 1))
        else:
            indices.add(int(part))
    return indices


def selected_indices(args: argparse.Namespace, commit_count: int) -> set[int]:
    if args.remaining_indices and (args.start is not None or args.end is not None):
        raise SystemExit("use either --remaining-indices or --start/--end, not both")
    if args.remaining_indices:
        indices = parse_index_set(args.remaining_indices)
    elif args.start is not None or args.end is not None:
        if args.start is None or args.end is None:
            raise SystemExit("--start and --end must be provided together")
        if args.start > args.end:
            raise SystemExit(f"invalid descending range: {args.start}-{args.end}")
        indices = set(range(args.start, args.end + 1))
    else:
        indices = set(range(1, commit_count + 1))

    invalid = [idx for idx in sorted(indices) if idx < 1 or idx > commit_count]
    if invalid:
        raise SystemExit(f"indices outside source list: {invalid}")
    return indices


def load_candidates(args: argparse.Namespace) -> list[Candidate]:
    commits = [line.strip() for line in args.source_list.read_text().splitlines() if line.strip()]
    indices = selected_indices(args, len(commits))
    candidates: list[Candidate] = []
    for idx in sorted(indices):
        sha = commits[idx - 1]
        subject = git_output(args.worktree, ["show", "-s", "--format=%s", sha])
        if subject.startswith(args.subject_prefix):
            candidates.append(Candidate(idx, sha, subject))
    return candidates


def unmerged_paths(worktree: Path) -> list[str]:
    output = git_output(worktree, ["ls-files", "-u", "-z"])
    paths: list[str] = []
    seen: set[str] = set()
    for entry in output.split("\0"):
        if not entry:
            continue
        try:
            _metadata, path = entry.split("\t", 1)
        except ValueError:
            continue
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return sorted(paths)


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def trial_candidate(main_worktree: Path, base_head: str, candidate: Candidate) -> TrialResult:
    with tempfile.TemporaryDirectory(prefix="ps-replay-least-conflict-") as tmp:
        trial = Path(tmp) / "trial"
        run_git(main_worktree, ["worktree", "add", "--detach", "-q", str(trial), base_head])
        try:
            proc = run_git(trial, ["cherry-pick", "--no-commit", candidate.sha], check=False)
            if proc.returncode == 0:
                return TrialResult(candidate, 0, "clean", "")

            conflicts = unmerged_paths(trial)
            if conflicts:
                return TrialResult(candidate, len(conflicts), "conflict", ",".join(conflicts))

            detail = first_line(proc.stdout) or f"git cherry-pick exited {proc.returncode}"
            return TrialResult(candidate, 1_000_000, "error", detail)
        finally:
            run_git(main_worktree, ["worktree", "remove", "--force", str(trial)], check=False)


def main() -> int:
    args = parse_args()
    args.worktree = args.worktree.resolve()

    if args.base_branch != REQUIRED_BASE_BRANCH:
        raise SystemExit(
            f"refusing least-conflict initial-tree ordering for BASE_BRANCH={args.base_branch}; "
            f"required {REQUIRED_BASE_BRANCH}"
        )

    status = git_output(args.worktree, ["status", "--porcelain"])
    if status:
        raise SystemExit(f"refusing to trial from dirty worktree:\n{status}")

    candidates = load_candidates(args)
    if not candidates:
        raise SystemExit("no remaining Initial Percona Server 5.6.22 tree candidates found")

    base_head = git_output(args.worktree, ["rev-parse", "HEAD"])
    results = [trial_candidate(args.worktree, base_head, candidate) for candidate in candidates]
    results.sort(key=lambda result: (result.conflicts, result.candidate.index))

    if not args.porcelain:
        print(f"{'INDEX':>5}  {'CONFLICTS':>9}  {'STATUS':<8}  {'SHA':<12}  SUBJECT")
    for result in results:
        candidate = result.candidate
        if args.porcelain:
            print(
                f"{candidate.index}\t{candidate.sha}\t{result.conflicts}\t"
                f"{result.status}\t{candidate.subject}"
            )
        else:
            print(
                f"{candidate.index:>5}  {result.conflicts:>9}  {result.status:<8}  "
                f"{candidate.sha[:12]:<12}  {candidate.subject}"
            )
            if result.detail and result.status != "clean":
                print(f"       detail: {result.detail}")

    selected = results[0]
    if not args.porcelain:
        print(
            "\nselected: "
            f"{selected.candidate.index} {selected.candidate.sha} "
            f"conflicts={selected.conflicts} {selected.candidate.subject}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

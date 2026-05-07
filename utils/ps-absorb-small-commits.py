#!/usr/bin/env python3
"""Absorb small commits from a first-parent branch range.

For each non-merge commit in BASE_BRANCH..INPUT_BRANCH whose insertions plus
deletions are at or below --threshold, print the commit patch and try to absorb
its hunks using ps-absorb-hunks.py. The output branch is created from the input
branch first, then rewritten in place after each successful absorb.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_REPO = "/data/percona-server-linear"
DEFAULT_THRESHOLD = 8
IGNORED_TITLE_PREFIXES = ("=== MARKER: GROUP",)
IGNORED_TITLE_SUBSTRINGS = ("myr", "rocks")


@dataclass(frozen=True)
class SmallCommit:
    sha: str
    title: str
    changes: int
    shortstat: str
    key: str


def load_absorb_module():
    script = Path(__file__).with_name("ps-absorb-hunks.py")
    spec = importlib.util.spec_from_file_location("ps_absorb_hunks", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_shortstat(text: str) -> tuple[int, int, str]:
    compact = " ".join(text.split())
    insertions = 0
    deletions = 0
    match = re.search(r"(\d+) insertion", compact)
    if match:
        insertions = int(match.group(1))
    match = re.search(r"(\d+) deletion", compact)
    if match:
        deletions = int(match.group(1))
    return insertions, deletions, compact or "0 files changed"


def commit_shortstat(absorb, repo: Path, commit: str) -> tuple[int, int, str] | None:
    meta = absorb.load_commit(repo, commit)
    if len(meta.parents) != 1:
        return None
    out = absorb.git_text(
        repo,
        "diff",
        "--shortstat",
        "--no-renames",
        meta.parents[0],
        commit,
    )
    return parse_shortstat(out)


def commit_key(absorb, repo: Path, commit: str) -> str:
    patch = absorb.git_text(repo, "show", "--format=", "--no-renames", commit)
    if not patch.strip():
        return f"empty:{commit}"
    result = absorb.git(repo, "patch-id", "--stable", input_text=patch)
    line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    return line.split()[0] if line else f"patch:{commit}"


def should_ignore_title(title: str) -> bool:
    title_lower = title.lower()
    return title.startswith(IGNORED_TITLE_PREFIXES) or any(
        substring in title_lower for substring in IGNORED_TITLE_SUBSTRINGS
    )


def base_index(absorb, repo: Path, chain: list[str], base_branch: str) -> int:
    base_tip = absorb.rev_parse(repo, base_branch)
    try:
        return {sha: idx for idx, sha in enumerate(chain)}[base_tip]
    except KeyError as exc:
        raise absorb.AbsorbError("--base-branch tip is not on the output branch first-parent chain") from exc


def next_small_commit(
    absorb,
    repo: Path,
    output_branch: str,
    base_branch: str,
    threshold: int,
    ignored_keys: set[str],
) -> SmallCommit | None:
    tip = absorb.branch_tip(repo, output_branch)
    chain = absorb.first_parent_chain(repo, tip)
    start = base_index(absorb, repo, chain, base_branch) + 1

    for sha in chain[start:]:
        meta = absorb.load_commit(repo, sha)
        if should_ignore_title(meta.title):
            continue
        stats = commit_shortstat(absorb, repo, sha)
        if stats is None:
            continue
        insertions, deletions, shortstat = stats
        changes = insertions + deletions
        if changes > threshold:
            continue
        key = commit_key(absorb, repo, sha)
        if key in ignored_keys:
            continue
        return SmallCommit(sha=sha, title=meta.title, changes=changes, shortstat=shortstat, key=key)
    return None


def print_commit_content(absorb, repo: Path, candidate: SmallCommit) -> None:
    print(
        f"\n=== SMALL COMMIT {candidate.sha[:12]} "
        f"({candidate.changes} change(s); {candidate.shortstat}) ===",
        flush=True,
    )
    print(absorb.git_text(repo, "show", "--stat", "--patch", "--no-renames", candidate.sha), end="")
    print(f"=== END SMALL COMMIT {candidate.sha[:12]} {candidate.title} ===", flush=True)


def print_unabsorbed_commits(absorb, commits: list[SmallCommit]) -> None:
    if not commits:
        absorb.log("Commits not fully absorbed: none")
        return

    absorb.log("Commits not fully absorbed:")
    for commit in commits:
        absorb.log(f"- {commit.sha[:12]} {commit.title} ({commit.shortstat})")


def reset_output_branch(absorb, repo: Path, input_branch: str, output_branch: str, force: bool) -> None:
    input_tip = absorb.branch_tip(repo, input_branch)
    if absorb.branch_exists(repo, output_branch):
        if not force:
            raise absorb.AbsorbError(f"output branch already exists: {output_branch}; pass --force to replace it")
        expected_tip = absorb.branch_tip(repo, output_branch)
    else:
        expected_tip = None
    absorb.update_branch_ref(repo, output_branch, input_tip, expected_tip)


def absorb_small_commits(args: argparse.Namespace) -> int:
    absorb = load_absorb_module()
    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        raise absorb.AbsorbError(f"not a git repository: {repo}")
    absorb.ensure_clean_worktree(repo)

    input_tip = absorb.branch_tip(repo, args.input_branch)
    chain = absorb.first_parent_chain(repo, input_tip)
    base_index(absorb, repo, chain, args.base_branch)
    reset_output_branch(absorb, repo, args.input_branch, args.output_branch, args.force)

    ignored_keys: set[str] = set()
    unabsorbed_commits: list[SmallCommit] = []
    absorbed = 0
    skipped = 0

    while True:
        candidate = next_small_commit(
            absorb,
            repo,
            args.output_branch,
            args.base_branch,
            args.threshold,
            ignored_keys,
        )
        if candidate is None:
            break

        print_commit_content(absorb, repo, candidate)
        before = absorb.branch_tip(repo, args.output_branch)
        rewrite_args = argparse.Namespace(
            repo=str(repo),
            input_branch=args.output_branch,
            output_branch=None,
            base_branch=args.base_branch,
            context=args.context,
            force=False,
            commit=candidate.sha,
        )
        absorb.rewrite_branch(rewrite_args)
        after = absorb.branch_tip(repo, args.output_branch)
        if after == before:
            ignored_keys.add(candidate.key)
            unabsorbed_commits.append(candidate)
            skipped += 1
            absorb.log(f"Small commit not absorbed; continuing: {candidate.sha[:12]}")
        else:
            absorbed += 1
            absorb.log(f"Absorbed small commit: {candidate.sha[:12]}")

    print_unabsorbed_commits(absorb, unabsorbed_commits)
    absorb.log(f"Absorbed {absorbed} small commit(s); skipped {skipped}.")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print and absorb small commits from BASE_BRANCH..INPUT_BRANCH.",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"Git repository (default: {DEFAULT_REPO}).")
    parser.add_argument("--base-branch", required=True, help="Lower bound; do not absorb into this branch history.")
    parser.add_argument("--input-branch", required=True, help="Input branch to scan.")
    parser.add_argument("--output-branch", required=True, help="Output branch to create and rewrite.")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help="Maximum insertions+deletions.")
    parser.add_argument("--context", type=int, default=3, help="Unified diff context for hunk absorbing.")
    parser.add_argument("--force", action="store_true", help="Replace an existing output branch.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return absorb_small_commits(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

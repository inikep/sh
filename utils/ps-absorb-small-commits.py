#!/usr/bin/env python3
"""Absorb small commits from a first-parent branch range.

Walks BASE_BRANCH..INPUT_BRANCH and, for each non-merge commit whose
insertions+deletions are at or below --threshold, delegates to
ps-absorb-hunks.py to fold the commit's hunks into earlier commits on the
same first-parent chain (above the --base-branch boundary). After every
successful absorption the output branch is rewritten in place and the
remaining chain is rescanned for the next candidate; the loop ends when no
eligible candidate remains.

Commits whose absorption attempt leaves the branch tip unchanged are
remembered by `git patch-id` so the same content isn't retried in later
iterations. Marker commits (titles starting with `=== MARKER: GROUP`) and
commits whose titles match `myr`/`rocks` but touch non-RocksDB paths are
filtered out before any absorption attempt. Submodule (gitlink) updates are
absorbed normally via ps-absorb-hunks.py's path-touch fallback.

ps-absorb-hunks.py prints the source commit, its shortstat, every hunk with
colored diff content, and the per-commit rewrite progress; this script does
not re-emit that content. It only prints the per-iteration verdict, a
separator between commits, and a final summary listing absorbed and
unabsorbed commits. Output color is controlled by --color {auto,always,never}
and respects the NO_COLOR / FORCE_COLOR environment variables.
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
ROCKSDB_ONLY_PATH_PREFIXES = ("storage/rocksdb/", "mysql-test/suite/rocksdb")
ROCKSDB_ONLY_EXACT_PATHS = ("storage/rocksdb",)
COMMIT_SEPARATOR = "=" * 80


@dataclass(frozen=True)
class SmallCommit:
    sha: str
    title: str
    changes: int
    shortstat: str
    key: str


@dataclass(frozen=True)
class AbsorbingCommit:
    sha: str
    title: str
    hunk_count: int


@dataclass(frozen=True)
class AbsorbedCommit:
    commit: SmallCommit
    absorbing_commits: list[AbsorbingCommit]


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


def modified_paths(absorb, repo: Path, commit: str, parent: str) -> list[str]:
    out = absorb.git_text(repo, "diff", "--name-only", "--no-renames", parent, commit)
    return [line for line in out.splitlines() if line]


def modifies_only_rocksdb_paths(paths: list[str]) -> bool:
    return bool(paths) and all(
        path in ROCKSDB_ONLY_EXACT_PATHS or path.startswith(ROCKSDB_ONLY_PATH_PREFIXES)
        for path in paths
    )


def should_ignore_commit(absorb, repo: Path, commit: str, title: str, parents: list[str]) -> bool:
    title_lower = title.lower()
    if title.startswith(IGNORED_TITLE_PREFIXES):
        return True
    if not any(substring in title_lower for substring in IGNORED_TITLE_SUBSTRINGS):
        return False
    if len(parents) != 1:
        return True
    return not modifies_only_rocksdb_paths(modified_paths(absorb, repo, commit, parents[0]))


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
        if should_ignore_commit(absorb, repo, sha, meta.title, meta.parents):
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


def pluralize(count: int, singular: str) -> str:
    return f"{count} {singular if count == 1 else singular + 's'}"


def planned_absorbing_commits(
    absorb,
    repo: Path,
    output_branch: str,
    base_branch: str,
    commit: str,
    context: int,
) -> list[AbsorbingCommit]:
    tip = absorb.branch_tip(repo, output_branch)
    source = absorb.rev_parse(repo, commit)
    source_meta = absorb.load_commit(repo, source)
    if len(source_meta.parents) != 1:
        return []

    chain = absorb.first_parent_chain(repo, tip)
    chain_index = {sha: idx for idx, sha in enumerate(chain)}
    min_target_index = base_index(absorb, repo, chain, base_branch) + 1
    dispositions = absorb.build_hunk_dispositions(
        repo,
        source,
        source_meta.parents[0],
        chain,
        context,
        min_target_index,
    )
    groups = absorb.dispositions_by_target(dispositions)
    absorbing_commits = []
    for target in sorted(groups, key=chain_index.__getitem__):
        target_meta = absorb.load_commit(repo, target)
        absorbing_commits.append(
            AbsorbingCommit(
                sha=target,
                title=target_meta.title,
                hunk_count=len(groups[target]),
            )
        )
    return absorbing_commits


def print_absorbed_commits(absorb, commits: list[AbsorbedCommit]) -> None:
    header = absorb.STYLE.bold("Absorbed commits:")
    if not commits:
        absorb.log(f"{header} none")
        return

    absorb.log(header)
    for absorbed_commit in commits:
        commit = absorbed_commit.commit
        absorb.log(
            f"- {absorb.short_sha(commit.sha)} {commit.title} "
            f"({commit.shortstat})"
        )
        for absorbing_commit in absorbed_commit.absorbing_commits:
            absorb.log(
                f"  - {absorb.short_sha(absorbing_commit.sha)} "
                f"{absorbing_commit.title} "
                f"({pluralize(absorbing_commit.hunk_count, 'hunk')})"
            )


def print_unabsorbed_commits(
    absorb, repo: Path, commits: list[SmallCommit]
) -> None:
    header = absorb.STYLE.bold("Commits not fully absorbed:")
    absorb.log("")
    if not commits:
        absorb.log(f"{header} none")
        return

    absorb.log(header)
    for commit in commits:
        absorb.log(
            f"- {absorb.short_sha(commit.sha)} {commit.title} "
            f"({commit.shortstat})"
        )
        meta = absorb.load_commit(repo, commit.sha)
        if len(meta.parents) != 1:
            continue
        for path in modified_paths(absorb, repo, commit.sha, meta.parents[0]):
            absorb.log(f"    {absorb.styled_path(path)}")


def reset_output_branch(absorb, repo: Path, input_branch: str, output_branch: str, force: bool) -> None:
    input_tip = absorb.branch_tip(repo, input_branch)
    if absorb.branch_exists(repo, output_branch):
        if not force:
            raise absorb.AbsorbError(f"output branch already exists: {output_branch}; pass --force to replace it")
        expected_tip = absorb.branch_tip(repo, output_branch)
    else:
        expected_tip = None
    absorb.update_branch_ref(repo, output_branch, input_tip, expected_tip)


def absorb_small_commits(absorb, args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        raise absorb.AbsorbError(f"not a git repository: {repo}")
    absorb.ensure_clean_worktree(repo)

    input_tip = absorb.branch_tip(repo, args.input_branch)
    chain = absorb.first_parent_chain(repo, input_tip)
    base_index(absorb, repo, chain, args.base_branch)
    reset_output_branch(absorb, repo, args.input_branch, args.output_branch, args.force)

    ignored_keys: set[str] = set()
    absorbed_commits: list[AbsorbedCommit] = []
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

        before = absorb.branch_tip(repo, args.output_branch)
        absorbing_commits = planned_absorbing_commits(
            absorb,
            repo,
            args.output_branch,
            args.base_branch,
            candidate.sha,
            args.context,
        )
        rewrite_args = argparse.Namespace(
            repo=str(repo),
            input_branch=args.output_branch,
            output_branch=None,
            base_branch=args.base_branch,
            context=args.context,
            force=False,
            commit=candidate.sha,
            color=args.color,
        )
        absorb.rewrite_branch(rewrite_args)
        after = absorb.branch_tip(repo, args.output_branch)
        if after == before:
            ignored_keys.add(candidate.key)
            unabsorbed_commits.append(candidate)
            skipped += 1
            absorb.log(
                f"{absorb.STYLE.yellow('Small commit not absorbed; continuing:')} "
                f"{absorb.short_sha(candidate.sha)} {candidate.title}"
            )
        else:
            absorbed_commits.append(AbsorbedCommit(candidate, absorbing_commits))
            absorbed += 1
            absorb.log(
                f"{absorb.STYLE.green('Absorbed small commit:')} "
                f"{absorb.short_sha(candidate.sha)} {candidate.title}"
            )
        absorb.log("")
        absorb.log(absorb.STYLE.dim(COMMIT_SEPARATOR))
        absorb.log("")

    print_absorbed_commits(absorb, absorbed_commits)
    print_unabsorbed_commits(absorb, repo, unabsorbed_commits)
    absorb.log(
        f"{absorb.STYLE.bold('Absorbed')} "
        f"{absorb.STYLE.bold(pluralize(absorbed, 'small commit'))}; "
        f"skipped {pluralize(skipped, 'small commit')}."
    )
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
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Colorize stderr output (default: auto; respects NO_COLOR / FORCE_COLOR).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    absorb = load_absorb_module()
    absorb.configure_style(args.color)
    try:
        return absorb_small_commits(absorb, args)
    except Exception as exc:
        text = absorb.colorize_conflicts(str(exc))
        print(f"{absorb.STYLE.bold(absorb.STYLE.red('ERROR:'))} {text}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

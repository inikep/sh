#!/usr/bin/env python3
"""Flatten a merge-heavy branch by walking first-parent history.

Rules:
  * commits whose tree equals their first parent's tree are skipped;
  * main-chain non-merge commits are re-emitted with the same
    tree/message/metadata and a rewritten parent;
  * --onto can set a separate output parent while --base..--tip remains the
    source range; by default, source tree parity is preserved by aligning the
    output back to --base before replay and to each expanded merge's tree after
    replaying its side branch;
  * non-null merges are replaced by walking their second-parent side's
    first-parent chain;
  * commits emitted under a "Merge pull request #NNN" parent or side-merge
    subject get a "[#NNN]" subject marker;
  * side-branch merge commits are squashed by replaying their net delta, but use
    message, author, and date metadata from the first real non-merge commit
    found through nested second-parent propagation.
  * one-parent side commits with merge-like subjects can use metadata from a
    matching real bug-fix commit when the original branch merge was already
    linearized before this script sees it.
  * side-branch deltas are replayed onto the current emitted parent rather than
    preserving full side-branch trees.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


PR_NUMBER_RE = re.compile(r"\bMerge pull request #(\d+)\b")
MERGE_BRANCH_SUBJECT_RE = re.compile(
    r"\bMerge (?:remote-tracking )?branch ['\"]?([^'\"]+)['\"]? into ['\"]?([^'\"]+)['\"]?",
    re.IGNORECASE,
)
BUG_ID_RE = re.compile(r"\bbug[-_/ ]*#?(\d{4,})\b", re.IGNORECASE)


class FlattenError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommitMeta:
    sha: str
    tree: str
    parents: list[str]
    author_name: str
    author_email: str
    author_date: str
    committer_name: str
    committer_email: str
    committer_date: str
    message: str

    @property
    def subject(self) -> str:
        return self.message.splitlines()[0] if self.message else ""

    @property
    def is_merge(self) -> bool:
        return len(self.parents) >= 2


@dataclass
class Stats:
    walked: int = 0
    emitted: int = 0
    skipped_null: int = 0
    expanded_merges: int = 0
    squashed_merges: int = 0
    linearized_merge_metadata: int = 0
    base_alignments: int = 0
    merge_alignments: int = 0


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def git(
    repo: str | Path,
    *args: str,
    check: bool = True,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=run_env,
    )
    if check and result.returncode != 0:
        raise FlattenError(
            f"git {' '.join(args)} failed (rc={result.returncode})\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def git_text(repo: str | Path, *args: str, check: bool = True) -> str:
    return git(repo, *args, check=check).stdout


def rev_parse(repo: str | Path, rev: str) -> str:
    return git_text(repo, "rev-parse", "--verify", f"{rev}^{{commit}}").strip()


def tree_of(repo: str | Path, rev: str) -> str:
    return git_text(repo, "rev-parse", f"{rev}^{{tree}}").strip()


def branch_exists(repo: str | Path, branch: str) -> bool:
    return (
        git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode
        == 0
    )


def validate_branch_name(repo: str | Path, branch: str) -> None:
    result = git(repo, "check-ref-format", "--branch", branch, check=False)
    if result.returncode != 0:
        raise FlattenError(f"invalid output branch name: {branch!r}")


def load_commit(repo: str | Path, sha: str) -> CommitMeta:
    fmt = "%H%n%T%n%P%n%an%n%ae%n%aI%n%cn%n%ce%n%cI%n%B"
    out = git_text(repo, "log", "-1", f"--format={fmt}", sha)
    parts = out.split("\n", 9)
    if len(parts) < 10:
        raise FlattenError(f"bad commit metadata for {sha}")
    return CommitMeta(
        sha=parts[0],
        tree=parts[1],
        parents=parts[2].split(),
        author_name=parts[3],
        author_email=parts[4],
        author_date=parts[5],
        committer_name=parts[6],
        committer_email=parts[7],
        committer_date=parts[8],
        message=parts[9].rstrip("\n"),
    )


def sanitize_ident(name: str, email: str) -> tuple[str, str]:
    name = name.strip() if name else ""
    email = email.strip() if email else ""
    if not name:
        name = email.split("@", 1)[0] if "@" in email else (email or "unknown")
    if not email:
        email = "unknown@local"
    return name, email


def commit_tree(
    repo: str | Path,
    tree: str,
    parent: str | None,
    meta: CommitMeta,
    message: str | None = None,
) -> str:
    author_name, author_email = sanitize_ident(meta.author_name, meta.author_email)
    committer_name, committer_email = sanitize_ident(meta.committer_name, meta.committer_email)
    env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_AUTHOR_DATE": meta.author_date,
        "GIT_COMMITTER_NAME": committer_name,
        "GIT_COMMITTER_EMAIL": committer_email,
        "GIT_COMMITTER_DATE": meta.committer_date,
    }
    args = ["commit-tree", tree]
    if parent:
        args.extend(["-p", parent])
    args.extend(["-F", "-"])
    commit_message = meta.message if message is None else message
    if not commit_message.endswith("\n"):
        commit_message += "\n"
    return git(repo, *args, input_text=commit_message, env=env).stdout.strip()


def first_parent_chain(repo: str | Path, base: str, tip: str) -> list[str]:
    out = git_text(repo, "rev-list", "--first-parent", "--reverse", f"{base}..{tip}")
    return [line for line in out.splitlines() if line]


def is_null_against_first_parent(repo: str | Path, meta: CommitMeta) -> bool:
    return bool(meta.parents) and meta.tree == tree_of(repo, meta.parents[0])


def marker_from_subject(subject: str) -> str | None:
    match = PR_NUMBER_RE.search(subject)
    return f"[#{match.group(1)}]" if match else None


def bug_id_from_subject(subject: str) -> str | None:
    match = BUG_ID_RE.search(subject)
    return match.group(1) if match else None


def is_merge_branch_subject(subject: str) -> bool:
    return MERGE_BRANCH_SUBJECT_RE.search(subject) is not None


def prefix_message_subject(message: str, marker: str | None) -> str:
    if not marker:
        return message
    if not message:
        return marker
    lines = message.splitlines()
    if not lines:
        return marker
    if lines[0].startswith(f"{marker} "):
        return message
    lines[0] = f"{marker} {lines[0]}"
    return "\n".join(lines)


def linearized_pr_body_message(message: str) -> str | None:
    lines = message.splitlines()
    if not lines or marker_from_subject(lines[0]) is None:
        return None
    body = lines[1:]
    while body and not body[0].strip():
        body.pop(0)
    if not body:
        return None
    return "\n".join(body)


def find_first_real_non_merge(repo: str | Path, meta: CommitMeta, seen: set[str] | None = None) -> CommitMeta:
    if seen is None:
        seen = set()
    if meta.sha in seen:
        raise FlattenError(f"cycle while following nested merges at {meta.sha}")
    seen.add(meta.sha)
    if not meta.is_merge:
        return meta

    first_parent, second_parent = meta.parents[0], meta.parents[1]
    for sha in first_parent_chain(repo, first_parent, second_parent):
        candidate = load_commit(repo, sha)
        if is_null_against_first_parent(repo, candidate):
            continue
        if candidate.is_merge:
            return find_first_real_non_merge(repo, candidate, seen)
        return candidate

    second_meta = load_commit(repo, second_parent)
    if second_meta.is_merge:
        return find_first_real_non_merge(repo, second_meta, seen)
    return second_meta


def changed_paths(repo: str | Path, sha: str) -> set[str]:
    out = git_text(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha)
    return {line for line in out.splitlines() if line}


def find_linearized_merge_metadata(repo: str | Path, meta: CommitMeta) -> CommitMeta | None:
    if meta.is_merge or not meta.parents or not is_merge_branch_subject(meta.subject):
        return None

    bug_id = bug_id_from_subject(meta.subject)
    if bug_id is None:
        return None

    source_paths = changed_paths(repo, meta.sha)
    if not source_paths:
        return None

    candidates: list[tuple[tuple[int, int, int, str], CommitMeta]] = []
    out = git_text(repo, "log", "--all", f"--grep={bug_id}", "--format=%H")
    for sha in out.splitlines():
        if not sha or sha == meta.sha:
            continue
        candidate = load_commit(repo, sha)
        if (
            candidate.is_merge
            or is_merge_branch_subject(candidate.subject)
            or candidate.subject.startswith("[")
            or bug_id_from_subject(candidate.subject) != bug_id
        ):
            continue

        candidate_paths = changed_paths(repo, candidate.sha)
        overlap = source_paths & candidate_paths
        if not overlap:
            continue

        exact_paths = int(candidate_paths == source_paths)
        symmetric_difference = len(source_paths ^ candidate_paths)
        score = (exact_paths, len(overlap), -symmetric_difference, candidate.author_date)
        candidates.append((score, candidate))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def emit_preserved(
    repo: str | Path,
    meta: CommitMeta,
    parent: str,
    stats: Stats,
    marker: str | None = None,
) -> str:
    effective_marker = marker or marker_from_subject(meta.subject)
    source_message = linearized_pr_body_message(meta.message) or meta.message
    message = prefix_message_subject(source_message, effective_marker)
    new_sha = commit_tree(repo, meta.tree, parent, meta, message)
    stats.emitted += 1
    log(f"emit {new_sha[:12]} from {meta.sha[:12]} {message.splitlines()[0] if message else ''}")
    return new_sha


def emit_squashed_merge(
    repo: str | Path,
    meta: CommitMeta,
    parent: str,
    stats: Stats,
    marker: str | None,
) -> str:
    original = find_first_real_non_merge(repo, meta)
    message = prefix_message_subject(original.message, marker)
    new_sha = commit_tree(repo, meta.tree, parent, original, message)
    stats.emitted += 1
    stats.squashed_merges += 1
    log(
        f"squash {new_sha[:12]} from {meta.sha[:12]} "
        f"using {original.sha[:12]} {message.splitlines()[0] if message else ''}"
    )
    return new_sha


def tree_entry(repo: str | Path, tree: str, path: str) -> tuple[str, str] | None:
    out = git_text(repo, "ls-tree", tree, "--", path)
    if not out.strip():
        return None
    meta, _ = out.rstrip("\n").split("\t", 1)
    mode, _kind, oid = meta.split()
    return mode, oid


def resolve_merge_tree_conflicts(
    repo: str | Path,
    result_tree: str,
    output_lines: list[str],
    expected_tree: str | None,
) -> str:
    stages: dict[str, dict[str, tuple[str, str]]] = {}
    for line in output_lines[1:]:
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        fields = meta.split()
        if len(fields) != 3 or fields[2] not in {"1", "2", "3"}:
            continue
        mode, oid, stage = fields
        stages.setdefault(path, {})[stage] = (mode, oid)

    if not stages:
        raise FlattenError("merge-tree reported conflicts but no conflicted paths were parsed")

    with tempfile.TemporaryDirectory(prefix="ps-flatten-conflict-index-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(repo, "read-tree", result_tree, env=env)
        for path, path_stages in sorted(stages.items()):
            source = tree_entry(repo, expected_tree, path) if expected_tree is not None else path_stages.get("3")
            if source is None:
                git(repo, "update-index", "--force-remove", "--", path, env=env)
                continue
            mode, oid = source
            git(repo, "update-index", "--cacheinfo", mode, oid, path, env=env)
        tree = git(repo, "write-tree", env=env).stdout.strip()
    source_label = "expected merge tree" if expected_tree is not None else "source side"
    log(f"  resolved {len(stages)} merge-tree conflict path(s) with {source_label}")
    return tree


def replay_delta_tree(
    repo: str | Path,
    delta_parent: str,
    delta_commit: str,
    emitted_parent: str,
    expected_tree: str | None = None,
) -> str | None:
    if tree_of(repo, delta_parent) == tree_of(repo, delta_commit):
        return None

    result = git(
        repo,
        "merge-tree",
        "--write-tree",
        f"--merge-base={delta_parent}",
        emitted_parent,
        delta_commit,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise FlattenError(
            f"git merge-tree failed (rc={result.returncode})\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise FlattenError(f"merge-tree produced no tree for {delta_commit}")
    result_tree = lines[0].strip()
    if result.returncode == 0:
        return result_tree
    return resolve_merge_tree_conflicts(repo, result_tree, lines, expected_tree)


def emit_replayed_delta(
    repo: str | Path,
    delta_meta: CommitMeta,
    emitted_parent: str,
    stats: Stats,
    marker: str | None,
    metadata_meta: CommitMeta | None = None,
    expected_tree: str | None = None,
) -> str:
    if not delta_meta.parents:
        raise FlattenError(f"cannot replay root commit as side delta: {delta_meta.sha}")
    metadata = metadata_meta or delta_meta
    message = prefix_message_subject(metadata.message, marker)
    tree = replay_delta_tree(repo, delta_meta.parents[0], delta_meta.sha, emitted_parent, expected_tree)
    if tree is None or tree == tree_of(repo, emitted_parent):
        stats.skipped_null += 1
        log(f"skip empty replay {delta_meta.sha[:12]} {message.splitlines()[0] if message else ''}")
        return emitted_parent
    new_sha = commit_tree(repo, tree, emitted_parent, metadata, message)
    stats.emitted += 1
    log(f"replay {new_sha[:12]} from {delta_meta.sha[:12]} {message.splitlines()[0] if message else ''}")
    return new_sha


def emit_replayed_squash(
    repo: str | Path,
    meta: CommitMeta,
    parent: str,
    stats: Stats,
    marker: str | None,
    expected_tree: str | None,
) -> str:
    original = find_first_real_non_merge(repo, meta)
    new_sha = emit_replayed_delta(repo, meta, parent, stats, marker, original, expected_tree)
    if new_sha != parent:
        stats.squashed_merges += 1
        log(f"  squash metadata from {original.sha[:12]}")
    return new_sha


def emit_tree_alignment(
    repo: str | Path,
    expected_tree: str,
    emitted_parent: str,
    meta: CommitMeta,
    stats: Stats,
    subject: str,
    body: str,
    alignment_kind: str,
) -> str:
    if expected_tree == tree_of(repo, emitted_parent):
        return emitted_parent

    message = f"{subject}\n\n{body}"
    new_sha = commit_tree(repo, expected_tree, emitted_parent, meta, message)
    stats.emitted += 1
    if alignment_kind == "base":
        stats.base_alignments += 1
    elif alignment_kind == "merge":
        stats.merge_alignments += 1
    log(f"align {new_sha[:12]} to {alignment_kind} tree {meta.sha[:12]}")
    return new_sha


def emit_base_alignment(
    repo: str | Path,
    base: str,
    emitted_parent: str,
    stats: Stats,
) -> str:
    base_meta = load_commit(repo, base)
    return emit_tree_alignment(
        repo,
        base_meta.tree,
        emitted_parent,
        base_meta,
        stats,
        f"Align output tree with source base {base_meta.sha[:12]}",
        "Synthetic commit created by ps-flatten-first-parent.py before replaying "
        "the source range onto a different parent.",
        "base",
    )


def emit_merge_alignment(
    repo: str | Path,
    merge_meta: CommitMeta,
    emitted_parent: str,
    stats: Stats,
) -> str:
    return emit_tree_alignment(
        repo,
        merge_meta.tree,
        emitted_parent,
        merge_meta,
        stats,
        f"Align output tree with merge {merge_meta.sha[:12]}",
        "Synthetic commit created by ps-flatten-first-parent.py after expanding "
        "a merge so cleanly-surviving destination-only hunks do not drift past "
        "the source merge boundary.",
        "merge",
    )


def flatten_side(
    repo: str | Path,
    first_parent: str,
    second_parent: str,
    emitted_parent: str,
    stats: Stats,
    marker: str | None,
    expected_tree: str | None,
) -> str:
    side_chain = first_parent_chain(repo, first_parent, second_parent)
    log(f"  side {first_parent[:12]}..{second_parent[:12]}: {len(side_chain)} first-parent commits")
    for sha in side_chain:
        meta = load_commit(repo, sha)
        stats.walked += 1
        if is_null_against_first_parent(repo, meta):
            stats.skipped_null += 1
            log(f"skip null {sha[:12]} {meta.subject}")
            continue
        if meta.is_merge:
            side_marker = marker_from_subject(meta.subject) or marker
            emitted_parent = emit_replayed_squash(repo, meta, emitted_parent, stats, side_marker, expected_tree)
        else:
            metadata_meta = find_linearized_merge_metadata(repo, meta)
            if metadata_meta is not None:
                stats.linearized_merge_metadata += 1
                log(
                    f"  linearized merge metadata from {metadata_meta.sha[:12]} "
                    f"for {meta.sha[:12]}"
                )
            emitted_parent = emit_replayed_delta(
                repo,
                meta,
                emitted_parent,
                stats,
                marker,
                metadata_meta=metadata_meta,
                expected_tree=expected_tree,
            )
    return emitted_parent


def flatten_range(
    repo: str | Path,
    base: str,
    tip: str,
    onto: str | None = None,
    align_source_trees: bool = True,
) -> tuple[str, Stats]:
    stats = Stats()
    emitted_parent = onto if onto is not None else base
    chain = first_parent_chain(repo, base, tip)
    log(f"main {base[:12]}..{tip[:12]}: {len(chain)} first-parent commits")
    if onto is not None and onto != base:
        log(f"onto {onto[:12]}")
        if align_source_trees:
            emitted_parent = emit_base_alignment(repo, base, emitted_parent, stats)
    for sha in chain:
        meta = load_commit(repo, sha)
        stats.walked += 1
        if is_null_against_first_parent(repo, meta):
            stats.skipped_null += 1
            log(f"skip null {sha[:12]} {meta.subject}")
            continue
        if meta.is_merge:
            stats.expanded_merges += 1
            marker = marker_from_subject(meta.subject)
            emitted_parent = flatten_side(
                repo,
                meta.parents[0],
                meta.parents[1],
                emitted_parent,
                stats,
                marker,
                meta.tree,
            )
            if align_source_trees:
                emitted_parent = emit_merge_alignment(repo, meta, emitted_parent, stats)
        else:
            emitted_parent = emit_preserved(repo, meta, emitted_parent, stats)
    return emitted_parent, stats


def update_output_branch(repo: str | Path, branch: str, new_tip: str) -> None:
    git(repo, "update-ref", f"refs/heads/{branch}", new_tip)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Flatten a merge-heavy branch by walking first-parent history.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("output_branch", help="branch to create/update with flattened history")
    parser.add_argument("--repo", default=".", help="repository path (default: current directory)")
    parser.add_argument("--base", required=True, help="base commit/ref excluded from the rewrite range")
    parser.add_argument("--tip", default="HEAD", help="tip commit/ref included in the rewrite range")
    parser.add_argument(
        "--onto",
        help="parent for the first emitted commit (default: --base); the walked range remains --base..--tip",
    )
    parser.add_argument("--force-output", action="store_true", help="allow updating an existing output branch")
    parser.add_argument(
        "--no-final-tree-check",
        action="store_true",
        help="do not require the output tip tree to match the input tip tree",
    )
    parser.add_argument(
        "--preserve-onto-tree",
        action="store_true",
        help=(
            "legacy --onto behavior: replay source deltas directly onto the --onto tree "
            "instead of aligning emitted trees back to the source"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        validate_branch_name(repo, args.output_branch)
        if args.preserve_onto_tree and not args.onto:
            raise FlattenError("--preserve-onto-tree requires --onto")
        if branch_exists(repo, args.output_branch) and not args.force_output:
            raise FlattenError(
                f"output branch already exists: {args.output_branch}; pass --force-output to update it"
            )

        base = rev_parse(repo, args.base)
        tip = rev_parse(repo, args.tip)
        onto = rev_parse(repo, args.onto) if args.onto else None
        new_tip, stats = flatten_range(repo, base, tip, onto, not args.preserve_onto_tree)

        if not args.no_final_tree_check and tree_of(repo, new_tip) != tree_of(repo, tip):
            raise FlattenError(
                "final output tree does not match input tip tree; "
                "rerun with --no-final-tree-check only if this drift is expected"
            )

        update_output_branch(repo, args.output_branch, new_tip)
        print(new_tip)
        log(
            "done: "
            f"walked={stats.walked} emitted={stats.emitted} skipped_null={stats.skipped_null} "
            f"expanded_merges={stats.expanded_merges} squashed_merges={stats.squashed_merges} "
            f"linearized_merge_metadata={stats.linearized_merge_metadata} "
            f"base_alignments={stats.base_alignments} merge_alignments={stats.merge_alignments} "
            f"output={args.output_branch}"
        )
        return 0
    except FlattenError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

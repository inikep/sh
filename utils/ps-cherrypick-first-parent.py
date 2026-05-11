#!/usr/bin/env python3
"""Flatten a range by chunked topo-order cherry-pick between first-parent neighbors.

Algorithm:
  1. Split BASE..TIP into chunks delimited by the first-parent commits:
         (BASE, A1], (A1, A2], (A2, A3], ..., (An-1, TIP].
  2. If E is a merge commit that advances the highest reachable upstream
     `mysql-X.Y.Z` tag, emit E as a merge commit whose first parent is the
     current output tip and whose remaining parents are E's non-first parents.
     This preserves large upstream histories instead of flattening them into
     the Percona first-parent replay.
  3. For each other chunk (P, E], walk every commit in topo order reverse and
     replay its delta against parent #1 (the `cherry-pick -m1` semantics).
  4. Conflicted paths during any commit in the chunk are resolved by taking
     the tree entry from E (the chunk's upper first-parent endpoint) — i.e.
     the equivalent of `git checkout E -- <conflicted_file>`.
  5. At each chunk boundary, residual path drift is reconciled to E by
     folding the endpoint path state into the latest emitted commit in the
     chunk that touched the path, considering all parents for merge commits.
  6. Commits emitted under a "Merge pull request #NNN" parent or side-merge
     subject get a "[#NNN]" subject marker.
  7. With --depth N, merge commits at side-depth N are squashed as a single
     net delta instead of descending into their nested side branches. Squashed
     commits use message, author, and date metadata from the first real
     non-merge commit found through nested second-parent propagation.
  8. Commits whose replay yields no tree change are silently skipped.

This mirrors, in-process, the shell idiom:

    fps=( $(git log --pretty='%H' --first-parent --reverse $BASE..$TIP) )
    prev=$BASE
    for endpoint in "${fps[@]}"; do
        git log --pretty='%H' --topo-order --reverse $prev..$endpoint \
            | xargs git cherry-pick -m1
        # on conflict: git checkout $endpoint -- <conflicted_file>
        prev=$endpoint
    done
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


SHORT_HASH_RE = re.compile(r"\b[0-9a-f]{12,40}\b")
ACTION_RE = re.compile(r"^(done:|range|onto|snap|=|merge|reconcile|upstream|drift)(?=\s|\b)")
PR_NUMBER_RE = re.compile(r"\bMerge pull request #(\d+)\b")
UPSTREAM_MYSQL_TAG_NAME_RE = re.compile(r"(?i)^mysql-(\d+)\.(\d+)\.(\d+)$")

LOG_LINE_WIDTH = 104


class FlattenError(RuntimeError):
    pass


class Style:
    """ANSI styling for terminal output; a no-op when disabled."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled or not text:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def blue(self, text: str) -> str:
        return self._wrap("34", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)


STYLE = Style(False)


def configure_style(mode: str) -> None:
    if mode == "always":
        STYLE.enabled = True
        return
    if mode == "never":
        STYLE.enabled = False
        return
    if os.environ.get("NO_COLOR") is not None:
        STYLE.enabled = False
        return
    if os.environ.get("FORCE_COLOR"):
        STYLE.enabled = True
        return
    STYLE.enabled = sys.stderr.isatty()


def colorize_log_message(message: str) -> str:
    if not STYLE.enabled or not message:
        return message
    stripped = message.lstrip()
    if stripped.startswith("ERROR:"):
        return STYLE.red(message)
    if stripped.startswith("upstream "):
        return STYLE.red(message)
    if stripped.startswith("drift "):
        return STYLE.blue(message)
    if stripped.startswith("skip "):
        return STYLE.dim(message)
    message = SHORT_HASH_RE.sub(lambda match: STYLE.yellow(match.group(0)), message)
    message = ACTION_RE.sub(lambda match: STYLE.cyan(match.group(0)), message)
    return message


def format_commit_line(marker: str, sha: str, subject: str) -> str:
    body = f"{marker}{sha[:12]} {subject}".rstrip()
    if len(body) > LOG_LINE_WIDTH:
        return body[: LOG_LINE_WIDTH - 1] + "…"
    return body


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
    skipped_empty_replay: int = 0
    replayed_merges: int = 0
    squashed_merges: int = 0
    upstream_import_merges: int = 0
    drift_files: int = 0
    drift_insertions: int = 0
    drift_deletions: int = 0
    drift_binary_files: int = 0
    reconciled_paths: int = 0
    snapped: int = 0


@dataclass
class EmittedCommit:
    meta: CommitMeta
    sha: str
    tree: str
    source_sha: str | None = None
    message: str | None = None


def log(message: str) -> None:
    print(colorize_log_message(message), file=sys.stderr, flush=True)


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
    parent: str | list[str] | None,
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
    parents = [parent] if isinstance(parent, str) else (parent or [])
    for item in parents:
        args.extend(["-p", item])
    args.extend(["-F", "-"])
    commit_message = meta.message if message is None else message
    if not commit_message.endswith("\n"):
        commit_message += "\n"
    return git(repo, *args, input_text=commit_message, env=env).stdout.strip()


def dedupe_parents(parents: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for parent in parents:
        if parent in seen:
            continue
        seen.add(parent)
        result.append(parent)
    return result


def first_parent_chain(repo: str | Path, base: str, tip: str) -> list[str]:
    out = git_text(repo, "rev-list", "--first-parent", "--reverse", f"{base}..{tip}")
    return [line for line in out.splitlines() if line]


def topo_chunk(repo: str | Path, prev: str, endpoint: str) -> list[str]:
    out = git_text(repo, "log", "--pretty=%H", "--topo-order", "--reverse", f"{prev}..{endpoint}")
    return [line for line in out.splitlines() if line]


def marker_from_subject(subject: str) -> str | None:
    match = PR_NUMBER_RE.search(subject)
    return f"[#{match.group(1)}]" if match else None


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


def is_null_against_first_parent(repo: str | Path, meta: CommitMeta) -> bool:
    return bool(meta.parents) and meta.tree == tree_of(repo, meta.parents[0])


def find_first_real_non_merge(
    repo: str | Path,
    meta: CommitMeta,
    seen: set[str] | None = None,
) -> CommitMeta:
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


def collect_chunk_depths(
    repo: str | Path,
    prev: str,
    endpoint: str,
    depth: int,
    squash_merge_depth: int | None,
    depths: dict[str, int],
    seen_ranges: set[tuple[str, str]],
) -> None:
    range_key = (prev, endpoint)
    if range_key in seen_ranges:
        return
    seen_ranges.add(range_key)

    chain = first_parent_chain(repo, prev, endpoint)
    for sha in chain:
        existing = depths.get(sha)
        if existing is None or depth < existing:
            depths[sha] = depth

    if squash_merge_depth is not None and depth >= squash_merge_depth:
        return

    for sha in chain:
        meta = load_commit(repo, sha)
        if not meta.is_merge:
            continue
        for side_parent in meta.parents[1:]:
            collect_chunk_depths(
                repo,
                meta.parents[0],
                side_parent,
                depth + 1,
                squash_merge_depth,
                depths,
                seen_ranges,
            )


def collect_chunk_markers(
    repo: str | Path,
    prev: str,
    endpoint: str,
    depth: int,
    squash_merge_depth: int | None,
    inherited_marker: str | None,
    markers: dict[str, str],
    seen_ranges: set[tuple[str, str]],
) -> None:
    range_key = (prev, endpoint)
    if range_key in seen_ranges:
        return
    seen_ranges.add(range_key)

    chain = first_parent_chain(repo, prev, endpoint)
    metas = [load_commit(repo, sha) for sha in chain]
    for meta in metas:
        commit_marker = inherited_marker
        if depth > 0:
            commit_marker = marker_from_subject(meta.subject) or inherited_marker
        if commit_marker:
            markers[meta.sha] = commit_marker

    if squash_merge_depth is not None and depth >= squash_merge_depth:
        return

    for meta in metas:
        if not meta.is_merge:
            continue
        side_marker = marker_from_subject(meta.subject) or inherited_marker
        for side_parent in meta.parents[1:]:
            collect_chunk_markers(
                repo,
                meta.parents[0],
                side_parent,
                depth + 1,
                squash_merge_depth,
                side_marker,
                markers,
                seen_ranges,
            )


def load_upstream_mysql_tags(repo: str | Path) -> list[tuple[tuple[int, int, int], str]]:
    out = git_text(repo, "tag", "--list", "mysql-*")
    tags: list[tuple[tuple[int, int, int], str]] = []
    for tag in out.splitlines():
        match = UPSTREAM_MYSQL_TAG_NAME_RE.match(tag)
        if not match:
            continue
        tags.append((tuple(int(part) for part in match.groups()), tag))
    tags.sort()
    return tags


def highest_reachable_upstream_tag(
    repo: str | Path,
    rev: str,
    upstream_tags: list[tuple[tuple[int, int, int], str]],
    cache: dict[str, tuple[tuple[int, int, int], str] | None],
) -> tuple[tuple[int, int, int], str] | None:
    if rev in cache:
        return cache[rev]
    merged = set(git_text(repo, "tag", "--merged", rev, "--list", "mysql-*").splitlines())
    best = None
    for version, tag in upstream_tags:
        if tag in merged:
            best = (version, tag)
    cache[rev] = best
    return best


def advanced_upstream_tag(
    repo: str | Path,
    prev: str,
    endpoint: str,
    upstream_tags: list[tuple[tuple[int, int, int], str]],
    cache: dict[str, tuple[tuple[int, int, int], str] | None],
) -> tuple[tuple[int, int, int], str] | None:
    if not upstream_tags:
        return None
    before = highest_reachable_upstream_tag(repo, prev, upstream_tags, cache)
    after = highest_reachable_upstream_tag(repo, endpoint, upstream_tags, cache)
    if after is None or after == before:
        return None
    if before is None:
        return after
    return after if after[0] > before[0] else None


def tree_entry(repo: str | Path, tree: str, path: str) -> tuple[str, str] | None:
    out = git_text(repo, "ls-tree", tree, "--", path)
    if not out.strip():
        return None
    meta, _ = out.rstrip("\n").split("\t", 1)
    mode, _kind, oid = meta.split()
    return mode, oid


def diff_paths(repo: str | Path, left_tree: str, right_tree: str) -> list[str]:
    out = git_text(repo, "diff", "--name-only", "--no-renames", left_tree, right_tree)
    return [line for line in out.splitlines() if line]


def diff_numstat(repo: str | Path, left_tree: str, right_tree: str) -> tuple[int, int, int, int]:
    out = git_text(repo, "diff", "--numstat", "--no-renames", left_tree, right_tree)
    files = insertions = deletions = binary_files = 0
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        files += 1
        if parts[0] == "-" or parts[1] == "-":
            binary_files += 1
            continue
        insertions += int(parts[0])
        deletions += int(parts[1])
    return files, insertions, deletions, binary_files


def touched_paths(repo: str | Path, meta: CommitMeta) -> set[str]:
    paths: set[str] = set()
    for parent in meta.parents:
        out = git_text(repo, "diff", "--name-only", "--no-renames", parent, meta.sha)
        paths.update(line for line in out.splitlines() if line)
    return paths


def overlay_tree_paths(
    repo: str | Path,
    base_tree: str,
    source_tree: str,
    paths: list[str],
) -> str:
    if not paths:
        return base_tree
    with tempfile.TemporaryDirectory(prefix="ps-flatten-topo-overlay-index-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(repo, "read-tree", base_tree, env=env)
        for path in sorted(set(paths)):
            source = tree_entry(repo, source_tree, path)
            if source is None:
                git(repo, "update-index", "--force-remove", "--", path, env=env)
                continue
            mode, oid = source
            git(repo, "update-index", "--cacheinfo", mode, oid, path, env=env)
        return git(repo, "write-tree", env=env).stdout.strip()


def resolve_merge_tree_conflicts(
    repo: str | Path,
    result_tree: str,
    output_lines: list[str],
    expected_tree: str,
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

    with tempfile.TemporaryDirectory(prefix="ps-flatten-topo-conflict-index-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(repo, "read-tree", result_tree, env=env)
        for path, _path_stages in sorted(stages.items()):
            source = tree_entry(repo, expected_tree, path)
            if source is None:
                git(repo, "update-index", "--force-remove", "--", path, env=env)
                continue
            mode, oid = source
            git(repo, "update-index", "--cacheinfo", mode, oid, path, env=env)
        tree = git(repo, "write-tree", env=env).stdout.strip()
    log(f"  resolved {len(stages)} conflict path(s) using chunk endpoint's tree")
    return tree


def replay_delta_tree(
    repo: str | Path,
    delta_parent: str,
    delta_commit: str,
    emitted_parent: str,
    expected_tree: str,
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
    meta: CommitMeta,
    emitted_parent: str,
    stats: Stats,
    expected_tree: str,
    metadata_meta: CommitMeta | None = None,
    marker: str | None = None,
) -> str:
    if not meta.parents:
        raise FlattenError(f"cannot replay root commit: {meta.sha}")
    metadata = metadata_meta or meta
    message = prefix_message_subject(metadata.message, marker)
    tree = replay_delta_tree(repo, meta.parents[0], meta.sha, emitted_parent, expected_tree)
    if tree is None or tree == tree_of(repo, emitted_parent):
        stats.skipped_empty_replay += 1
        return emitted_parent
    new_sha = commit_tree(repo, tree, emitted_parent, metadata, message)
    stats.emitted += 1
    if meta.is_merge:
        stats.replayed_merges += 1
    subject = message.splitlines()[0] if message else ""
    log(format_commit_line("= ", new_sha, subject))
    return new_sha


def upstream_import_tag(
    repo: str | Path,
    prev: str,
    meta: CommitMeta,
    upstream_tags: list[tuple[tuple[int, int, int], str]],
    upstream_tag_cache: dict[str, tuple[tuple[int, int, int], str] | None],
) -> tuple[tuple[int, int, int], str] | None:
    if not meta.is_merge:
        return None
    return advanced_upstream_tag(repo, prev, meta.sha, upstream_tags, upstream_tag_cache)


def emit_upstream_import_merge(
    repo: str | Path,
    meta: CommitMeta,
    emitted_parent: str,
    upstream_tag: str,
    stats: Stats,
) -> str:
    upstream_parent = rev_parse(repo, upstream_tag)
    parents = dedupe_parents([emitted_parent, upstream_parent])
    new_sha = commit_tree(repo, meta.tree, parents, meta, meta.message)
    stats.emitted += 1
    stats.replayed_merges += 1
    stats.upstream_import_merges += 1
    log(format_commit_line("upstream ", new_sha, f"{upstream_tag} {meta.subject}"))
    return new_sha


def last_toucher_by_path(
    repo: str | Path,
    chunk_metas: list[CommitMeta],
    paths: list[str],
) -> dict[str, str | None]:
    remaining = set(paths)
    result: dict[str, str | None] = {path: None for path in paths}
    touched_cache: dict[str, set[str]] = {}
    for meta in reversed(chunk_metas):
        touched = touched_cache.setdefault(meta.sha, touched_paths(repo, meta))
        matched = remaining & touched
        for path in matched:
            result[path] = meta.sha
        remaining -= matched
        if not remaining:
            break
    return result


def rebuild_chunk_suffix(
    repo: str | Path,
    chunk_base_parent: str,
    chunk_emitted: list[EmittedCommit],
    adjusted_trees: list[str],
    first_index: int,
) -> str:
    parent = chunk_base_parent if first_index == 0 else chunk_emitted[first_index - 1].sha
    for index in range(first_index, len(chunk_emitted)):
        emitted = chunk_emitted[index]
        tree = adjusted_trees[index]
        subject = emitted.message.splitlines()[0] if emitted.message else emitted.meta.subject
        if tree == tree_of(repo, parent):
            log(format_commit_line("skip ", emitted.sha, f"{subject} (empty after reconcile)"))
            continue
        new_sha = commit_tree(repo, tree, parent, emitted.meta, emitted.message)
        chunk_emitted[index] = EmittedCommit(
            emitted.meta,
            new_sha,
            tree,
            source_sha=emitted.source_sha,
            message=emitted.message,
        )
        parent = new_sha
        log(format_commit_line("= ", new_sha, f"{subject} [reconciled]"))
    return parent


def reconcile_chunk(
    repo: str | Path,
    chunk_base_parent: str,
    emitted_parent: str,
    endpoint_meta: CommitMeta,
    chunk_metas: list[CommitMeta],
    chunk_emitted: list[EmittedCommit],
    source_to_emitted_index: dict[str, int],
    stats: Stats,
) -> str:
    emitted_tree = tree_of(repo, emitted_parent)
    residual_paths = diff_paths(repo, emitted_tree, endpoint_meta.tree)
    if not residual_paths:
        return emitted_parent

    files, insertions, deletions, binary_files = diff_numstat(repo, emitted_tree, endpoint_meta.tree)
    stats.drift_files += files
    stats.drift_insertions += insertions
    stats.drift_deletions += deletions
    stats.drift_binary_files += binary_files
    binary_suffix = f", binary_files={binary_files}" if binary_files else ""
    log(
        f"drift files={files} lines={insertions + deletions} "
        f"(+{insertions}/-{deletions}{binary_suffix}) to {endpoint_meta.sha[:12]}"
    )
    last_toucher = last_toucher_by_path(repo, chunk_metas, residual_paths)
    paths_by_index: dict[int, list[str]] = {}
    fallback_paths: list[str] = []
    for path in residual_paths:
        source_sha = last_toucher[path]
        index = source_to_emitted_index.get(source_sha or "")
        if index is None:
            fallback_paths.append(path)
            continue
        paths_by_index.setdefault(index, []).append(path)

    if paths_by_index:
        adjusted_trees = [emitted.tree for emitted in chunk_emitted]
        for index, paths in sorted(paths_by_index.items()):
            for tree_index in range(index, len(adjusted_trees)):
                adjusted_trees[tree_index] = overlay_tree_paths(
                    repo, adjusted_trees[tree_index], endpoint_meta.tree, paths
                )
            stats.reconciled_paths += len(paths)
            log(
                f"    folded {len(paths)} path(s) into "
                f"{(chunk_emitted[index].source_sha or chunk_emitted[index].meta.sha)[:12]}"
            )
        emitted_parent = rebuild_chunk_suffix(
            repo, chunk_base_parent, chunk_emitted, adjusted_trees, min(paths_by_index)
        )

    if fallback_paths:
        current_tree = tree_of(repo, emitted_parent)
        tree = overlay_tree_paths(repo, current_tree, endpoint_meta.tree, fallback_paths)
        if tree != current_tree:
            message = (
                f"Reconcile chunk to {endpoint_meta.sha[:12]}\n\n"
                "Synthetic commit added by ps-cherrypick-first-parent.py because\n"
                "some residual paths could not be folded into an emitted commit.\n"
            )
            emitted_parent = commit_tree(repo, tree, emitted_parent, endpoint_meta, message)
            stats.emitted += 1
            stats.reconciled_paths += len(fallback_paths)
            log(format_commit_line("= ", emitted_parent, f"reconcile {endpoint_meta.sha[:12]}"))

    remaining = diff_paths(repo, tree_of(repo, emitted_parent), endpoint_meta.tree)
    if remaining:
        sample = "\n".join(f"  {path}" for path in remaining[:20])
        raise FlattenError(
            f"chunk reconciliation failed for {endpoint_meta.sha[:12]} "
            f"({len(remaining)} path(s) still differ)\n{sample}"
        )
    return emitted_parent


def emit_snap_commit(
    repo: str | Path,
    tip_meta: CommitMeta,
    emitted_parent: str,
    stats: Stats,
) -> str:
    if tip_meta.tree == tree_of(repo, emitted_parent):
        return emitted_parent
    message = (
        f"Snap output tree to {tip_meta.sha[:12]}\n\n"
        "Synthetic commit added by ps-cherrypick-first-parent.py so the output\n"
        "branch's tip tree exactly matches the input --tip's tree.\n"
    )
    new_sha = commit_tree(repo, tip_meta.tree, emitted_parent, tip_meta, message)
    stats.emitted += 1
    stats.snapped += 1
    log(format_commit_line("snap ", new_sha, f"tree matches {tip_meta.sha[:12]}"))
    return new_sha


def flatten_first_parent_range(
    repo: str | Path,
    base: str,
    tip: str,
    onto: str | None = None,
    snap_to_tip: bool = True,
    preserve_upstream_imports: bool = True,
    squash_merge_depth: int | None = None,
) -> tuple[str, Stats]:
    stats = Stats()
    emitted_parent = onto if onto is not None else base
    upstream_tags = load_upstream_mysql_tags(repo)
    upstream_tag_cache: dict[str, tuple[tuple[int, int, int], str] | None] = {}
    fp_chain = first_parent_chain(repo, base, tip)
    log(f"range {base[:12]}..{tip[:12]}: {len(fp_chain)} first-parent chunks")
    if onto is not None and onto != base:
        log(f"onto {onto[:12]}")
    prev = base
    for endpoint in fp_chain:
        endpoint_meta = load_commit(repo, endpoint)
        advanced_tag = upstream_import_tag(repo, prev, endpoint_meta, upstream_tags, upstream_tag_cache)
        if preserve_upstream_imports and advanced_tag is not None:
            stats.walked += 1
            emitted_parent = emit_upstream_import_merge(
                repo, endpoint_meta, emitted_parent, advanced_tag[1], stats
            )
            prev = endpoint
            continue

        chunk_base_parent = emitted_parent
        chunk_emitted: list[EmittedCommit] = []
        chunk_metas: list[CommitMeta] = []
        source_to_emitted_index: dict[str, int] = {}
        chunk = topo_chunk(repo, prev, endpoint)
        chunk_depths: dict[str, int] | None = None
        if squash_merge_depth is not None:
            chunk_depths = {}
            collect_chunk_depths(
                repo,
                prev,
                endpoint,
                0,
                squash_merge_depth,
                chunk_depths,
                set(),
            )
        chunk_markers: dict[str, str] = {}
        collect_chunk_markers(
            repo,
            prev,
            endpoint,
            0,
            squash_merge_depth,
            None,
            chunk_markers,
            set(),
        )
        if len(chunk) > 1:
            log(f"  chunk {prev[:12]}..{endpoint[:12]}: {len(chunk)} commits")
        for sha in chunk:
            commit_depth = chunk_depths.get(sha) if chunk_depths is not None else None
            if chunk_depths is not None and commit_depth is None:
                continue
            meta = load_commit(repo, sha)
            chunk_metas.append(meta)
            stats.walked += 1
            log(format_commit_line("", meta.sha, meta.subject))
            if not meta.parents:
                stats.skipped_null += 1
                continue
            if is_null_against_first_parent(repo, meta):
                stats.skipped_null += 1
                continue
            metadata_meta = None
            if (
                squash_merge_depth is not None
                and commit_depth is not None
                and commit_depth >= squash_merge_depth
                and meta.is_merge
            ):
                metadata_meta = find_first_real_non_merge(repo, meta)
                log(f"  squash metadata from {metadata_meta.sha[:12]}")
            marker = chunk_markers.get(meta.sha)
            message = prefix_message_subject((metadata_meta or meta).message, marker)
            before = emitted_parent
            emitted_parent = emit_replayed_delta(
                repo,
                meta,
                emitted_parent,
                stats,
                endpoint_meta.tree,
                metadata_meta=metadata_meta,
                marker=marker,
            )
            if emitted_parent != before:
                if metadata_meta is not None:
                    stats.squashed_merges += 1
                source_to_emitted_index[meta.sha] = len(chunk_emitted)
                chunk_emitted.append(
                    EmittedCommit(
                        metadata_meta or meta,
                        emitted_parent,
                        tree_of(repo, emitted_parent),
                        source_sha=meta.sha,
                        message=message,
                    )
                )
        emitted_parent = reconcile_chunk(
            repo,
            chunk_base_parent,
            emitted_parent,
            endpoint_meta,
            chunk_metas,
            chunk_emitted,
            source_to_emitted_index,
            stats,
        )
        prev = endpoint
    if snap_to_tip:
        tip_meta = load_commit(repo, tip)
        emitted_parent = emit_snap_commit(repo, tip_meta, emitted_parent, stats)
    return emitted_parent, stats


def update_output_branch(repo: str | Path, branch: str, new_tip: str) -> None:
    git(repo, "update-ref", f"refs/heads/{branch}", new_tip)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Flatten a range by cherry-picking every first-parent commit (cherry-pick -m1 semantics).",
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
        "--no-snap",
        action="store_true",
        help="do not emit a synthetic snap commit when the output tree drifts from --tip",
    )
    parser.add_argument(
        "--no-preserve-upstream-imports",
        action="store_true",
        help=(
            "flatten merge commits that advance the reachable mysql-X.Y.Z "
            "upstream tag instead of preserving them as merge commits"
        ),
    )
    parser.add_argument(
        "--depth",
        type=int,
        help=(
            "squash merge commits at this side-branch depth instead of "
            "descending into their nested side branches; default expands all depths"
        ),
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colorize stderr output (default: auto; respects NO_COLOR / FORCE_COLOR)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_style(args.color)
    repo = Path(args.repo).resolve()
    try:
        validate_branch_name(repo, args.output_branch)
        if branch_exists(repo, args.output_branch) and not args.force_output:
            raise FlattenError(
                f"output branch already exists: {args.output_branch}; pass --force-output to update it"
            )

        base = rev_parse(repo, args.base)
        tip = rev_parse(repo, args.tip)
        onto = rev_parse(repo, args.onto) if args.onto else None
        if args.depth is not None and args.depth < 0:
            raise FlattenError("--depth must be non-negative")
        new_tip, stats = flatten_first_parent_range(
            repo,
            base,
            tip,
            onto,
            snap_to_tip=not args.no_snap,
            preserve_upstream_imports=not args.no_preserve_upstream_imports,
            squash_merge_depth=args.depth,
        )

        update_output_branch(repo, args.output_branch, new_tip)
        print(new_tip)
        log(
            "done: "
            f"walked={stats.walked} emitted={stats.emitted} skipped_null={stats.skipped_null} "
            f"skipped_empty_replay={stats.skipped_empty_replay} replayed_merges={stats.replayed_merges} "
            f"squashed_merges={stats.squashed_merges} "
            f"upstream_import_merges={stats.upstream_import_merges} "
            f"drift_files={stats.drift_files} "
            f"drift_lines={stats.drift_insertions + stats.drift_deletions} "
            f"drift_insertions={stats.drift_insertions} drift_deletions={stats.drift_deletions} "
            f"drift_binary_files={stats.drift_binary_files} "
            f"reconciled_paths={stats.reconciled_paths} snapped={stats.snapped} output={args.output_branch}"
        )
        return 0
    except FlattenError as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

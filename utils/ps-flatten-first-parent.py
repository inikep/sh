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
    first-parent chain; mysql-X.Y.Z imports are preserved only at the direct
    import point, either the merge whose second parent is the tag or a
    side-branch reconciliation commit immediately after the tagged upstream
    commit;
  * commits emitted under a "Merge pull request #NNN" parent or side-merge
    subject get a "[#NNN]" subject marker;
  * side-branch merge commits are squashed by replaying their net delta; when a
    nested merge imports a single real change, that change supplies metadata once,
    while later broad merge squashes keep their own merge metadata.
  * one-parent side commits with merge-like subjects can use metadata from a
    matching real bug-fix commit when the original branch merge was already
    linearized before this script sees it.
  * side-branch deltas are replayed onto the current emitted parent rather than
    preserving full side-branch trees.
  * residual drift after replaying a side branch is folded into the latest
    emitted commit inside that side branch that touched the path; unowned
    residual paths fall back to an explicit merge alignment commit.
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
MERGE_51_TO_55_SUBJECT_RE = re.compile(r"\b5\.1\b", re.IGNORECASE)
SHORT_HASH_RE = re.compile(r"\b[0-9a-f]{12,40}\b")
ACTION_RE = re.compile(r"^(emit|squash|replay|skip null|skip empty replay|done:|main|onto|upstream|=)(?=\s|\b)")
UPSTREAM_MYSQL_TAG_NAME_RE = re.compile(r"(?i)^mysql-(\d+)\.(\d+)\.(\d+)$")
FILES_RE = re.compile(r"(\d+) files? changed")
INS_RE = re.compile(r"(\d+) insertion")
DEL_RE = re.compile(r"(\d+) deletion")

LOG_LINE_WIDTH = 104
OUTPUT_STAT_FILES_WIDTH = 5
OUTPUT_STAT_COUNT_WIDTH = 5


def format_commit_line(marker: str, sha: str, subject: str, depth: int = 0) -> str:
    indent = "  " * depth
    body = f"{indent}{marker}{sha[:12]} {subject}".rstrip()
    if len(body) > LOG_LINE_WIDTH:
        return body[: LOG_LINE_WIDTH - 1] + "…"
    return body


def compact_count(n: int) -> str:
    if n >= 1000000:
        return f"{n // 1000000}M"
    if n >= 10000:
        return f"{n // 1000}K"
    return str(n)


def depth_marker(depth: int) -> str:
    return "  " * max(depth, 0)


def format_stats_commit_line(
    files: int,
    insertions: int,
    deletions: int,
    marker: str,
    sha: str,
    subject: str,
    depth: int = 0,
) -> str:
    files_field = f"{compact_count(files)}f".ljust(OUTPUT_STAT_FILES_WIDTH)
    ins_field = f"{compact_count(insertions)}+".rjust(OUTPUT_STAT_COUNT_WIDTH)
    del_field = f"{compact_count(deletions)}-".rjust(OUTPUT_STAT_COUNT_WIDTH)
    indent = depth_marker(depth)
    body = f"{indent}{files_field}{ins_field} {del_field} {marker}{sha[:12]} {subject}".rstrip()
    return body[:LOG_LINE_WIDTH]


def format_squash_metadata_line(meta: "CommitMeta") -> str:
    line = f"  squash metadata from {meta.sha[:12]} {meta.subject}"
    return line[:LOG_LINE_WIDTH]


def format_side_drift_line(path_count: int, merge_meta: "CommitMeta") -> str:
    line = (
        f"  align side drift {path_count} path(s) "
        f"to merge tree {merge_meta.sha[:12]} {merge_meta.subject}"
    )
    return line[:LOG_LINE_WIDTH]


def format_folded_paths_line(path_count: int, sha: str, subject: str) -> str:
    line = f"  folded {path_count} path(s) into {sha[:12]} {subject}"
    return line[:LOG_LINE_WIDTH]


def format_fallback_paths_line(path_count: int) -> str:
    line = (
        f"  {path_count} path(s) have no emitted owner in current side; "
        "falling back to merge alignment"
    )
    return line[:LOG_LINE_WIDTH]


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

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def blue(self, text: str) -> str:
        return self._wrap("34", text)

    def violet(self, text: str) -> str:
        return self._wrap("35", text)

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
    if stripped.startswith("align side drift "):
        return STYLE.green(message)
    if stripped.startswith("align "):
        return STYLE.red(message)
    if stripped.startswith("ERROR:"):
        return STYLE.red(message)
    if stripped.startswith("skip "):
        return STYLE.dim(message)
    message = SHORT_HASH_RE.sub(lambda match: STYLE.yellow(match.group(0)), message)
    message = ACTION_RE.sub(lambda match: STYLE.cyan(match.group(0)), message)
    return message


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
    merge_reconciled_paths: int = 0
    upstream_import_merges: int = 0


@dataclass
class EmittedSideCommit:
    source_meta: CommitMeta
    emit_meta: CommitMeta
    sha: str
    tree: str
    message: str


def log(message: str) -> None:
    print(colorize_log_message(message), file=sys.stderr, flush=True)


def is_51_to_55_merge(meta: CommitMeta) -> bool:
    return meta.is_merge and MERGE_51_TO_55_SUBJECT_RE.search(meta.subject) is not None


def style_stats_commit_line(line: str, subject_color: str | None = None) -> str:
    if not STYLE.enabled:
        return line
    match = re.match(
        r"^(\s*)(\[[^\]]+\]\s+)?(\S+)(\s+)(\S+)(\s+)(\S+)(\s+)(.*?)([0-9a-f]{12})(\s?)(.*)$",
        line,
    )
    if not match:
        return line
    subject = match.group(12)
    commit_hash = match.group(10)
    if subject_color == "violet":
        subject = STYLE.violet(subject)
    elif subject_color == "blue":
        subject = STYLE.blue(subject)
    elif subject_color == "blue_hash_subject":
        subject = STYLE.blue(subject)
        commit_hash = STYLE.blue(commit_hash)
    elif subject_color == "green":
        subject = STYLE.green(subject)
        commit_hash = STYLE.green(commit_hash)
    elif subject_color == "red":
        subject = STYLE.red(subject)
        commit_hash = STYLE.red(commit_hash)
    else:
        commit_hash = STYLE.yellow(commit_hash)
    return (
        match.group(1)
        + (match.group(2) or "")
        + match.group(3)
        + match.group(4)
        + STYLE.green(match.group(5))
        + match.group(6)
        + STYLE.red(match.group(7))
        + match.group(8)
        + STYLE.cyan(match.group(9))
        + commit_hash
        + match.group(11)
        + subject
    )


def shortstat_for_commit(repo: str | Path, sha: str) -> tuple[int, int, int]:
    text = git_text(
        repo,
        "-c",
        "diff.renames=false",
        "show",
        "-m",
        "--first-parent",
        "--no-patch",
        "--format=",
        "--shortstat",
        sha,
    )
    files = insertions = deletions = 0
    match = FILES_RE.search(text)
    if match:
        files = int(match.group(1))
    match = INS_RE.search(text)
    if match:
        insertions = int(match.group(1))
    match = DEL_RE.search(text)
    if match:
        deletions = int(match.group(1))
    return files, insertions, deletions


def format_rewrite_commit_line(
    files: int,
    insertions: int,
    deletions: int,
    marker: str,
    sha: str,
    subject: str,
) -> str:
    stats_line = format_stats_commit_line(
        files, insertions, deletions, marker, sha, subject
    )
    return f"  [rewrite] {stats_line}"[:LOG_LINE_WIDTH]


def format_align_commit_line(
    files: int,
    insertions: int,
    deletions: int,
    marker: str,
    sha: str,
    subject: str,
    align_sha: str,
) -> str:
    stats_line = format_stats_commit_line(
        files, insertions, deletions, marker, sha, subject
    )
    return f"  [align to {align_sha[:12]}] {stats_line}"[:LOG_LINE_WIDTH]


def output_subject_color(
    marker: str,
    insertions: int,
    deletions: int,
    default: str | None = None,
) -> str | None:
    if marker == "=> " and insertions + deletions > 10000:
        return "red"
    return default


def log_commit_line(
    repo: str | Path,
    marker: str,
    sha: str,
    subject: str,
    depth: int = 0,
    subject_color: str | None = None,
) -> None:
    files, insertions, deletions = shortstat_for_commit(repo, sha)
    line = format_stats_commit_line(files, insertions, deletions, marker, sha, subject, depth)
    color = output_subject_color(marker, insertions, deletions, subject_color)
    print(style_stats_commit_line(line, color), file=sys.stderr, flush=True)


def log_align_commit_line(
    repo: str | Path,
    marker: str,
    sha: str,
    subject: str,
    align_sha: str,
) -> None:
    files, insertions, deletions = shortstat_for_commit(repo, sha)
    line = format_align_commit_line(
        files, insertions, deletions, marker, sha, subject, align_sha
    )
    subject_color = output_subject_color(marker, insertions, deletions, "green")
    print(style_stats_commit_line(line, subject_color=subject_color), file=sys.stderr, flush=True)


def log_rewrite_commit_line(
    repo: str | Path,
    marker: str,
    sha: str,
    subject: str,
) -> None:
    files, insertions, deletions = shortstat_for_commit(repo, sha)
    line = format_rewrite_commit_line(
        files, insertions, deletions, marker, sha, subject
    )
    color = output_subject_color(marker, insertions, deletions)
    print(style_stats_commit_line(line, color), file=sys.stderr, flush=True)


def log_first_parent_commit(repo: str | Path, meta: CommitMeta, upstream_tag: str | None) -> None:
    subject_color = None
    if STYLE.enabled:
        if is_51_to_55_merge(meta):
            subject_color = "violet"
        elif upstream_tag:
            subject_color = "blue"
    log_commit_line(repo, "", meta.sha, meta.subject, subject_color=subject_color)


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


def direct_upstream_import_tag(
    repo: str | Path,
    meta: CommitMeta,
    advanced_tag: tuple[tuple[int, int, int], str] | None,
) -> tuple[tuple[int, int, int], str] | None:
    """Return the advanced mysql tag only for a merge that directly imports it."""
    if advanced_tag is None or not meta.is_merge or len(meta.parents) < 2:
        return None
    upstream_parent = rev_parse(repo, advanced_tag[1])
    if meta.parents[1] == upstream_parent:
        return advanced_tag
    return None


def emit_upstream_import_merge(
    repo: str | Path,
    meta: CommitMeta,
    emitted_parent: str,
    upstream_tag: str,
    stats: Stats,
) -> str:
    upstream_parent = rev_parse(repo, upstream_tag)
    parents = dedupe_parents([emitted_parent, upstream_parent])
    message = prefix_upstream_tag_subject(meta.message, upstream_tag)
    new_sha = commit_tree(repo, meta.tree, parents, meta, message)
    stats.emitted += 1
    stats.upstream_import_merges += 1
    subject = message.splitlines()[0] if message else ""
    log_commit_line(repo, "=> ", new_sha, subject, subject_color="blue_hash_subject")
    return new_sha


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


def prefix_upstream_tag_subject(message: str, upstream_tag: str | None) -> str:
    if not upstream_tag:
        return message
    return prefix_message_subject(message, f"({upstream_tag})")


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
    upstream_tag: str | None = None,
) -> str:
    effective_marker = marker or marker_from_subject(meta.subject)
    source_message = linearized_pr_body_message(meta.message) or meta.message
    message = prefix_message_subject(source_message, effective_marker)
    message = prefix_upstream_tag_subject(message, upstream_tag)
    new_sha = commit_tree(repo, meta.tree, parent, meta, message)
    stats.emitted += 1
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


def diff_paths(repo: str | Path, left_tree: str, right_tree: str) -> list[str]:
    out = git_text(repo, "diff", "--name-only", "--no-renames", left_tree, right_tree)
    return [line for line in out.splitlines() if line]


def touched_paths(repo: str | Path, meta: CommitMeta) -> set[str]:
    if not meta.parents:
        return set()
    out = git_text(repo, "diff", "--name-only", "--no-renames", meta.parents[0], meta.sha)
    return {line for line in out.splitlines() if line}


def overlay_tree_paths(
    repo: str | Path,
    base_tree: str,
    source_tree: str,
    paths: list[str],
) -> str:
    if not paths:
        return base_tree
    with tempfile.TemporaryDirectory(prefix="ps-flatten-side-overlay-index-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(repo, "read-tree", base_tree, env=env)
        for path in sorted(set(paths)):
            source = tree_entry(repo, source_tree, path)
            if source is None:
                git(repo, "update-index", "--force-remove", "--", path, env=env)
                continue
            mode, oid = source
            git(repo, "update-index", "--add", "--cacheinfo", mode, oid, path, env=env)
        return git(repo, "write-tree", env=env).stdout.strip()


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
            git(repo, "update-index", "--add", "--cacheinfo", mode, oid, path, env=env)
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
    depth: int = 0,
    pre_emit_log: str | None = None,
) -> str:
    if not delta_meta.parents:
        raise FlattenError(f"cannot replay root commit as side delta: {delta_meta.sha}")
    metadata = metadata_meta or delta_meta
    message = prefix_message_subject(metadata.message, marker)
    tree = replay_delta_tree(repo, delta_meta.parents[0], delta_meta.sha, emitted_parent, expected_tree)
    if tree is None or tree == tree_of(repo, emitted_parent):
        stats.skipped_null += 1
        log("  skip empty replay")
        return emitted_parent
    new_sha = commit_tree(repo, tree, emitted_parent, metadata, message)
    stats.emitted += 1
    subject = message.splitlines()[0] if message else ""
    if pre_emit_log is not None:
        log(pre_emit_log)
    log_commit_line(repo, "=> ", new_sha, subject, depth=depth)
    return new_sha


def emit_replayed_squash(
    repo: str | Path,
    meta: CommitMeta,
    parent: str,
    stats: Stats,
    marker: str | None,
    expected_tree: str | None,
    used_metadata_shas: set[str] | None = None,
    depth: int = 0,
) -> str:
    original = find_first_real_non_merge(repo, meta)
    metadata = meta if used_metadata_shas is not None and original.sha in used_metadata_shas else original
    new_sha = emit_replayed_delta(
        repo,
        meta,
        parent,
        stats,
        marker,
        metadata,
        expected_tree,
        depth=depth,
        pre_emit_log=format_squash_metadata_line(original) if metadata.sha == original.sha else None,
    )
    if new_sha != parent:
        stats.squashed_merges += 1
        if used_metadata_shas is not None:
            used_metadata_shas.add(metadata.sha)
    return new_sha


def emit_tree_alignment(
    repo: str | Path,
    expected_tree: str,
    emitted_parent: str,
    meta: CommitMeta,
    stats: Stats,
    alignment_kind: str,
) -> str:
    if expected_tree == tree_of(repo, emitted_parent):
        return emitted_parent

    new_sha = commit_tree(repo, expected_tree, emitted_parent, meta, meta.message)
    stats.emitted += 1
    if alignment_kind == "base":
        stats.base_alignments += 1
    elif alignment_kind == "merge":
        stats.merge_alignments += 1
    if alignment_kind == "merge":
        log_align_commit_line(repo, "=> ", new_sha, meta.subject, meta.sha)
    else:
        subject = f"align to {alignment_kind} tree {meta.sha[:12]}: {meta.subject}"
        log_commit_line(repo, "=> ", new_sha, subject)
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
        "merge",
    )


def last_side_toucher_by_path(
    repo: str | Path,
    side_emitted: list[EmittedSideCommit],
    paths: list[str],
) -> dict[str, int | None]:
    remaining = set(paths)
    result: dict[str, int | None] = {path: None for path in paths}
    touched_cache: dict[str, set[str]] = {}
    for index in range(len(side_emitted) - 1, -1, -1):
        source_meta = side_emitted[index].source_meta
        touched = touched_cache.setdefault(source_meta.sha, touched_paths(repo, source_meta))
        matched = remaining & touched
        for path in matched:
            result[path] = index
        remaining -= matched
        if not remaining:
            break
    return result


def rebuild_side_suffix(
    repo: str | Path,
    side_base_parent: str,
    side_emitted: list[EmittedSideCommit],
    adjusted_trees: list[str],
    first_index: int,
    folded_paths_by_index: dict[int, int] | None = None,
) -> str:
    parent = side_base_parent if first_index == 0 else side_emitted[first_index - 1].sha
    folded_paths_by_index = folded_paths_by_index or {}
    for index in range(first_index, len(side_emitted)):
        emitted = side_emitted[index]
        tree = adjusted_trees[index]
        subject = emitted.message.splitlines()[0] if emitted.message else emitted.emit_meta.subject
        if tree == tree_of(repo, parent):
            log(format_commit_line("skip empty replay ", emitted.sha, f"{subject} after reconcile", depth=1))
            continue
        new_sha = commit_tree(repo, tree, parent, emitted.emit_meta, emitted.message)
        side_emitted[index] = EmittedSideCommit(
            emitted.source_meta,
            emitted.emit_meta,
            new_sha,
            tree,
            emitted.message,
        )
        parent = new_sha
        folded_count = folded_paths_by_index.get(index)
        if folded_count is not None:
            log(format_folded_paths_line(folded_count, new_sha, subject))
        log_rewrite_commit_line(repo, "=> ", new_sha, subject)
    return parent


def reconcile_side_to_merge_tree(
    repo: str | Path,
    side_base_parent: str,
    emitted_parent: str,
    merge_meta: CommitMeta,
    side_emitted: list[EmittedSideCommit],
    stats: Stats,
) -> str:
    residual_paths = diff_paths(repo, tree_of(repo, emitted_parent), merge_meta.tree)
    if not residual_paths:
        return emitted_parent

    log(format_side_drift_line(len(residual_paths), merge_meta))
    last_toucher = last_side_toucher_by_path(repo, side_emitted, residual_paths)
    paths_by_index: dict[int, list[str]] = {}
    fallback_paths: list[str] = []
    for path in residual_paths:
        index = last_toucher[path]
        if index is None:
            fallback_paths.append(path)
            continue
        paths_by_index.setdefault(index, []).append(path)

    if paths_by_index:
        adjusted_trees = [emitted.tree for emitted in side_emitted]
        folded_paths_by_index: dict[int, int] = {}
        for index, paths in sorted(paths_by_index.items()):
            for tree_index in range(index, len(adjusted_trees)):
                adjusted_trees[tree_index] = overlay_tree_paths(
                    repo,
                    adjusted_trees[tree_index],
                    merge_meta.tree,
                    paths,
                )
            stats.merge_reconciled_paths += len(paths)
            folded_paths_by_index[index] = len(paths)
        emitted_parent = rebuild_side_suffix(
            repo,
            side_base_parent,
            side_emitted,
            adjusted_trees,
            min(paths_by_index),
            folded_paths_by_index,
        )

    if fallback_paths:
        log(format_fallback_paths_line(len(fallback_paths)))
        return emit_merge_alignment(repo, merge_meta, emitted_parent, stats)

    remaining = diff_paths(repo, tree_of(repo, emitted_parent), merge_meta.tree)
    if remaining:
        sample = "\n".join(f"  {path}" for path in remaining[:20])
        raise FlattenError(
            f"side reconciliation failed for {merge_meta.sha[:12]} "
            f"({len(remaining)} path(s) still differ)\n{sample}"
        )
    return emitted_parent


def flatten_side(
    repo: str | Path,
    first_parent: str,
    second_parent: str,
    emitted_parent: str,
    stats: Stats,
    marker: str | None,
    expected_tree: str | None,
    merge_meta: CommitMeta | None = None,
    align_source_tree: bool = True,
    preserve_upstream_imports: bool = True,
    upstream_tags: list[tuple[tuple[int, int, int], str]] | None = None,
    upstream_tag_cache: dict[str, tuple[tuple[int, int, int], str] | None] | None = None,
    used_metadata_shas: set[str] | None = None,
) -> str:
    upstream_tags = upstream_tags or []
    if upstream_tag_cache is None:
        upstream_tag_cache = {}
    if used_metadata_shas is None:
        used_metadata_shas = set()
    side_chain = first_parent_chain(repo, first_parent, second_parent)
    side_metas = [load_commit(repo, sha) for sha in side_chain]
    log(f"  side {first_parent[:12]}..{second_parent[:12]}: {len(side_chain)} first-parent commits")
    side_base_parent = emitted_parent
    side_emitted: list[EmittedSideCommit] = []
    start_index = 0
    prev_endpoint = first_parent
    forced_upstream_imports: dict[str, str] = {}
    if preserve_upstream_imports and upstream_tags:
        scan_prev_endpoint = first_parent
        for index, meta in enumerate(side_metas):
            advanced_tag = advanced_upstream_tag(
                repo,
                scan_prev_endpoint,
                meta.sha,
                upstream_tags,
                upstream_tag_cache,
            )
            direct_upstream_tag = direct_upstream_import_tag(repo, meta, advanced_tag)
            if direct_upstream_tag is not None:
                if index:
                    stats.walked += index
                    log(
                        f"  skip upstream prefix before {direct_upstream_tag[1]} import: "
                        f"{index} first-parent commits"
                    )
                start_index = index
                prev_endpoint = first_parent if index == 0 else side_metas[index - 1].sha
                break
            if advanced_tag is not None:
                upstream_parent = rev_parse(repo, advanced_tag[1])
                if meta.sha == upstream_parent:
                    import_index = index
                    if index + 1 < len(side_metas) and side_metas[index + 1].tree == meta.tree:
                        import_index = index + 1
                    if import_index:
                        stats.walked += import_index
                        log(
                            f"  skip upstream prefix before {advanced_tag[1]} import: "
                            f"{import_index} first-parent commits"
                        )
                    start_index = import_index
                    prev_endpoint = first_parent if import_index == 0 else side_metas[import_index - 1].sha
                    forced_upstream_imports[side_metas[import_index].sha] = advanced_tag[1]
                    break
            scan_prev_endpoint = meta.sha
    depth = 1
    diag_indent = "  " * (depth + 1)
    for meta in side_metas[start_index:]:
        stats.walked += 1
        advanced_tag = (
            advanced_upstream_tag(repo, prev_endpoint, meta.sha, upstream_tags, upstream_tag_cache)
            if preserve_upstream_imports
            else None
        )
        direct_upstream_tag = direct_upstream_import_tag(repo, meta, advanced_tag)
        upstream_import_tag_name = forced_upstream_imports.get(meta.sha) or (
            direct_upstream_tag[1] if direct_upstream_tag is not None else None
        )
        log_commit_line(
            repo,
            "",
            meta.sha,
            meta.subject,
            depth=depth,
            subject_color="blue" if upstream_import_tag_name is not None else None,
        )
        if upstream_import_tag_name is not None:
            emitted_parent = emit_upstream_import_merge(
                repo,
                meta,
                emitted_parent,
                upstream_import_tag_name,
                stats,
            )
            used_metadata_shas.add(meta.sha)
            prev_endpoint = meta.sha
            continue
        if is_null_against_first_parent(repo, meta):
            stats.skipped_null += 1
            log(f"{diag_indent}skip null")
            prev_endpoint = meta.sha
            continue
        if meta.is_merge:
            side_marker = marker_from_subject(meta.subject) or marker
            original = find_first_real_non_merge(repo, meta)
            metadata_meta = meta if original.sha in used_metadata_shas else original
            message = prefix_message_subject(metadata_meta.message, side_marker)
            prev_emitted = emitted_parent
            emitted_parent = emit_replayed_delta(
                repo,
                meta,
                emitted_parent,
                stats,
                side_marker,
                metadata_meta,
                expected_tree,
                depth=depth,
                pre_emit_log=(
                    format_squash_metadata_line(original)
                    if metadata_meta.sha == original.sha
                    else None
                ),
            )
            if emitted_parent != prev_emitted:
                stats.squashed_merges += 1
                used_metadata_shas.add(metadata_meta.sha)
                side_emitted.append(
                    EmittedSideCommit(
                        meta,
                        metadata_meta,
                        emitted_parent,
                        tree_of(repo, emitted_parent),
                        message,
                    )
                )
        else:
            metadata_meta = find_linearized_merge_metadata(repo, meta)
            if metadata_meta is not None:
                stats.linearized_merge_metadata += 1
                log(
                    f"{diag_indent}linearized merge metadata from {metadata_meta.sha[:12]} "
                    f"for {meta.sha[:12]}"
                )
            message = prefix_message_subject((metadata_meta or meta).message, marker)
            prev_emitted = emitted_parent
            emitted_parent = emit_replayed_delta(
                repo,
                meta,
                emitted_parent,
                stats,
                marker,
                metadata_meta=metadata_meta,
                expected_tree=expected_tree,
                depth=depth,
            )
            if emitted_parent != prev_emitted:
                used_metadata_shas.add((metadata_meta or meta).sha)
                side_emitted.append(
                    EmittedSideCommit(
                        meta,
                        metadata_meta or meta,
                        emitted_parent,
                        tree_of(repo, emitted_parent),
                        message,
                    )
                )
        prev_endpoint = meta.sha
    if align_source_tree and merge_meta is not None:
        emitted_parent = reconcile_side_to_merge_tree(
            repo,
            side_base_parent,
            emitted_parent,
            merge_meta,
            side_emitted,
            stats,
        )
    return emitted_parent


def flatten_range(
    repo: str | Path,
    base: str,
    tip: str,
    onto: str | None = None,
    align_source_trees: bool = True,
    preserve_upstream_imports: bool = True,
) -> tuple[str, Stats]:
    stats = Stats()
    emitted_parent = onto if onto is not None else base
    chain = first_parent_chain(repo, base, tip)
    log(f"main {base[:12]}..{tip[:12]}: {len(chain)} first-parent commits")
    if onto is not None and onto != base:
        log(f"onto {onto[:12]}")
        if align_source_trees:
            emitted_parent = emit_base_alignment(repo, base, emitted_parent, stats)
    upstream_tags = load_upstream_mysql_tags(repo) if preserve_upstream_imports else []
    upstream_tag_cache: dict[str, tuple[tuple[int, int, int], str] | None] = {}
    used_metadata_shas: set[str] = set()
    prev_endpoint = base
    for sha in chain:
        meta = load_commit(repo, sha)
        stats.walked += 1
        advanced_tag = (
            advanced_upstream_tag(repo, prev_endpoint, meta.sha, upstream_tags, upstream_tag_cache)
            if preserve_upstream_imports
            else None
        )
        first_parent_upstream_tag = advanced_tag[1] if advanced_tag is not None else None
        direct_upstream_tag = direct_upstream_import_tag(repo, meta, advanced_tag)
        if meta.is_merge and direct_upstream_tag is None:
            first_parent_upstream_tag = None
        log_first_parent_commit(repo, meta, first_parent_upstream_tag)
        if is_null_against_first_parent(repo, meta):
            stats.skipped_null += 1
            log("  skip null")
            prev_endpoint = sha
            continue
        if meta.is_merge:
            if direct_upstream_tag is not None:
                emitted_parent = emit_upstream_import_merge(
                    repo, meta, emitted_parent, direct_upstream_tag[1], stats
                )
                used_metadata_shas.add(meta.sha)
                prev_endpoint = sha
                continue
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
                merge_meta=meta,
                align_source_tree=align_source_trees,
                preserve_upstream_imports=preserve_upstream_imports,
                upstream_tags=upstream_tags,
                upstream_tag_cache=upstream_tag_cache,
                used_metadata_shas=used_metadata_shas,
            )
        else:
            prev_emitted = emitted_parent
            emitted_parent = emit_preserved(
                repo,
                meta,
                emitted_parent,
                stats,
                upstream_tag=first_parent_upstream_tag,
            )
            if emitted_parent != prev_emitted:
                used_metadata_shas.add(meta.sha)
                emitted_meta = load_commit(repo, emitted_parent)
                log_commit_line(repo, "=> ", emitted_parent, emitted_meta.subject)
        prev_endpoint = sha
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
    parser.add_argument(
        "--no-preserve-upstream-imports",
        action="store_true",
        help=(
            "flatten merge commits that advance the reachable mysql-X.Y.Z "
            "upstream tag instead of preserving them as merge commits"
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
        if args.preserve_onto_tree and not args.onto:
            raise FlattenError("--preserve-onto-tree requires --onto")
        if branch_exists(repo, args.output_branch) and not args.force_output:
            raise FlattenError(
                f"output branch already exists: {args.output_branch}; pass --force-output to update it"
            )

        base = rev_parse(repo, args.base)
        tip = rev_parse(repo, args.tip)
        onto = rev_parse(repo, args.onto) if args.onto else None
        new_tip, stats = flatten_range(
            repo,
            base,
            tip,
            onto,
            align_source_trees=not args.preserve_onto_tree,
            preserve_upstream_imports=not args.no_preserve_upstream_imports,
        )

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
            f"merge_reconciled_paths={stats.merge_reconciled_paths} "
            f"upstream_import_merges={stats.upstream_import_merges} "
            f"output={args.output_branch}"
        )
        return 0
    except FlattenError as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

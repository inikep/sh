#!/usr/bin/env python3
"""Absorb hunks from one commit into prior first-parent commits.

For each textual hunk in COMMIT, pick a target commit on the input branch's
first-parent chain (strictly between the --base-branch tip and COMMIT) and
fold the hunk into it. The base is auto-detected as the highest-versioned
`mysql-M.m.p` ref (e.g. `mysql-5.6.22`, `mysql-5.7.9`, `mysql-8.0.13`) on
the chain when --base-branch is omitted; pass --base-branch to override.

  1. Blame the hunk's old-side context and deleted lines at COMMIT^ and
     pick the newest blamed commit that lies in the eligible range.
  2. For pure-addition hunks (no old-side lines to blame), fall back to the
     newest in-range commit that touched the same file.
  3. If the only blamed commits are at or before --base-branch, fall back
     to the newest in-range commit that touched the same file.

Hunks with no eligible target are reported as skipped and left in COMMIT.

The chain from the earliest target through the branch tip is then rebuilt:
each commit is replayed onto the new parent via `git merge-tree` (with a
patch-based fallback for replayable modify/delete and rename/delete
conflicts), absorbed hunks are applied to the matching target's tree, and
COMMIT itself is dropped if it becomes empty after absorption.

The input branch is updated in place only after the rewritten tip has a
null diff against the original tip. Pass --output-branch to write the
rewritten history to a separate branch instead.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


DEFAULT_REPO = "/data/percona-server-linear"
GIT_TEXT_ENCODING = "utf-8"
GIT_TEXT_ERRORS = "surrogateescape"


def configure_standard_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors=GIT_TEXT_ERRORS)


configure_standard_streams()


class Style:
    """ANSI styling for terminal output; a no-op when disabled."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled or not text:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, t: str) -> str: return self._wrap("1", t)
    def dim(self, t: str) -> str: return self._wrap("2", t)
    def red(self, t: str) -> str: return self._wrap("31", t)
    def green(self, t: str) -> str: return self._wrap("32", t)
    def yellow(self, t: str) -> str: return self._wrap("33", t)
    def blue(self, t: str) -> str: return self._wrap("34", t)
    def magenta(self, t: str) -> str: return self._wrap("35", t)
    def cyan(self, t: str) -> str: return self._wrap("36", t)


STYLE = Style(False)


def configure_style(mode: str) -> None:
    """Resolve --color {auto,always,never} into STYLE.enabled."""
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


CONFLICT_LINE_RE = re.compile(r"^(CONFLICT \([^)]+\):.*)$", re.MULTILINE)


def colorize_conflicts(text: str) -> str:
    """Highlight `CONFLICT (...): ...` lines in red within multi-line output."""
    if not STYLE.enabled or not text:
        return text
    return CONFLICT_LINE_RE.sub(lambda m: STYLE.red(m.group(1)), text)


class AbsorbError(RuntimeError):
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
    def title(self) -> str:
        return self.message.splitlines()[0] if self.message else "(no subject)"


@dataclass(frozen=True)
class Hunk:
    old_path: str | None
    new_path: str | None
    file_header: tuple[str, ...]
    hunk_header: str
    hunk_lines: tuple[str, ...]
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    old_side_lines: list[int]

    @property
    def is_added_only(self) -> bool:
        return not self.old_side_lines

    def patch_text(self) -> str:
        text = "".join((*self.file_header, self.hunk_header, *self.hunk_lines))
        return text if text.endswith("\n") else text + "\n"


@dataclass(frozen=True)
class BinaryHunk:
    """Represents a binary-file change in a parsed diff.

    Used by `patch_cherry_pick_tree` to copy the target commit's blob into
    the rewritten tree without trying to apply a textual patch. Other
    callers of `parse_unified_diff` opt out of binary emission and continue
    to receive `AbsorbError` when binary content is encountered.
    """

    old_path: str | None
    new_path: str | None
    new_blob: str | None  # None when the file is being deleted.
    new_mode: str | None  # None when the file is being deleted.


@dataclass(frozen=True)
class HunkDecision:
    hunk: Hunk
    target: str | None
    reason: str


@dataclass(frozen=True)
class HunkDisposition:
    number: int
    hunk: Hunk
    target: str | None
    skip_reason: str | None


HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)
CONFLICT_RE = re.compile(r"^CONFLICT \((?P<type>[^)]+)\):")
REPLAYABLE_DELETE_CONFLICTS = {"modify/delete", "rename/delete"}
INDEX_LINE_RE = re.compile(
    r"^index (?P<old>[0-9a-f]+)\.\.(?P<new>[0-9a-f]+)(?: (?P<mode>\d{6}))?$"
)
NEW_FILE_MODE_RE = re.compile(r"^new file mode (?P<mode>\d{6})$")
DELETED_FILE_MODE_RE = re.compile(r"^deleted file mode (?P<mode>\d{6})$")
NEW_MODE_RE = re.compile(r"^new mode (?P<mode>\d{6})$")
DIFF_GIT_PATHS_RE = re.compile(r'^diff --git "?a/(?P<a>.+?)"? "?b/(?P<b>.+?)"?\n?$')


def _is_zero_sha(sha: str | None) -> bool:
    return bool(sha) and set(sha) == {"0"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


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
    input_bytes = (
        input_text.encode(GIT_TEXT_ENCODING, GIT_TEXT_ERRORS)
        if input_text is not None
        else None
    )
    raw_result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=run_env,
    )
    result = subprocess.CompletedProcess(
        raw_result.args,
        raw_result.returncode,
        raw_result.stdout.decode(GIT_TEXT_ENCODING, GIT_TEXT_ERRORS),
        raw_result.stderr.decode(GIT_TEXT_ENCODING, GIT_TEXT_ERRORS),
    )
    if check and result.returncode != 0:
        raise AbsorbError(
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


def short_sha(sha: str) -> str:
    return STYLE.yellow(sha[:12])


def commit_label(meta: CommitMeta) -> str:
    return f"{short_sha(meta.sha)} {meta.title}"


def hunk_path(hunk: Hunk) -> str:
    return hunk.new_path or hunk.old_path or "<unknown>"


def hunk_header_text(hunk: Hunk) -> str:
    return hunk.hunk_header.rstrip()


def styled_path(path: str) -> str:
    return STYLE.magenta(path)


def styled_hunk_header(hunk: Hunk) -> str:
    return STYLE.cyan(hunk_header_text(hunk))


def styled_diff_line(line: str) -> str:
    """Color a single hunk-body line by its diff prefix."""
    body = line.rstrip("\n").rstrip("\r")
    if not body:
        return body
    prefix = body[0]
    if prefix == "+":
        return STYLE.green(body)
    if prefix == "-":
        return STYLE.red(body)
    if prefix == "\\":
        return STYLE.dim(body)
    return body


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


SHORTSTAT_INSERTIONS_RE = re.compile(r"\d+ insertions?\(\+\)")
SHORTSTAT_DELETIONS_RE = re.compile(r"\d+ deletions?\(-\)")


def commit_shortstat(repo: str | Path, source_meta: CommitMeta) -> str:
    """Return a single-line `git diff --shortstat` for `source_meta` vs its parent.

    Returns an empty string for merge or root commits, where a single-parent
    diff isn't well-defined.
    """
    if len(source_meta.parents) != 1:
        return ""
    out = git_text(
        repo,
        "diff",
        "--shortstat",
        "--no-renames",
        source_meta.parents[0],
        source_meta.sha,
    )
    return " ".join(out.split())


def styled_shortstat(text: str) -> str:
    """Colorize the insertion/deletion segments of a `git diff --shortstat` line."""
    if not text:
        return text
    text = SHORTSTAT_INSERTIONS_RE.sub(lambda m: STYLE.green(m.group(0)), text)
    text = SHORTSTAT_DELETIONS_RE.sub(lambda m: STYLE.red(m.group(0)), text)
    return text


def log_numbered_hunks(
    repo: str | Path,
    dispositions: list[HunkDisposition],
    source_meta: CommitMeta,
) -> None:
    """Print every hunk with diff colors, numbered, plus its disposition."""
    shortstat = commit_shortstat(repo, source_meta)
    header = (
        f"{STYLE.bold('Hunks from')} {commit_label(source_meta)} "
        f"({STYLE.bold(pluralize(len(dispositions), 'hunk'))} total"
    )
    if shortstat:
        header += f"; {styled_shortstat(shortstat)}"
    header += "):"
    log(header)
    log("")
    for d in dispositions:
        number_tag = STYLE.bold(f"[{d.number}]")
        log(
            f"{number_tag} {styled_path(hunk_path(d.hunk))} "
            f"{styled_hunk_header(d.hunk)}"
        )
        for line in d.hunk.hunk_lines:
            log(styled_diff_line(line))
        if d.target:
            target_meta = load_commit(repo, d.target)
            log(
                f"{STYLE.green('-> absorbed into')} "
                f"{commit_label(target_meta)}"
            )
        else:
            log(
                f"{STYLE.yellow('-> skipped:')} "
                f"{STYLE.yellow(d.skip_reason or 'no target')}"
            )
        log("")


def current_branch(repo: str | Path) -> str:
    branch = git_text(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip()
    if not branch:
        raise AbsorbError("cannot infer branch: HEAD is detached; pass --input-branch")
    return branch


def ensure_clean_worktree(repo: str | Path) -> None:
    status = git_text(repo, "status", "--porcelain")
    if status.strip():
        raise AbsorbError("worktree is dirty; commit/stash changes before rewriting a branch")


def branch_tip(repo: str | Path, branch: str) -> str:
    return rev_parse(repo, f"refs/heads/{branch}")


def branch_exists(repo: str | Path, branch: str) -> bool:
    return (
        git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode
        == 0
    )


def update_branch_ref(
    repo: str | Path,
    branch: str,
    new_tip: str,
    expected_tip: str | None,
) -> None:
    args = ["update-ref", f"refs/heads/{branch}", new_tip]
    if expected_tip is not None:
        args.append(expected_tip)
    else:
        args.append("")
    git(repo, *args)


def load_commit(repo: str | Path, sha: str) -> CommitMeta:
    fmt = "%H%n%T%n%P%n%an%n%ae%n%aI%n%cn%n%ce%n%cI%n%B"
    out = git_text(repo, "log", "-1", f"--format={fmt}", sha)
    parts = out.split("\n", 9)
    if len(parts) < 10:
        raise AbsorbError(f"bad commit metadata for {sha}")
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


def commit_tree(repo: str | Path, tree: str, parent: str | None, meta: CommitMeta) -> str:
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
    message = meta.message if meta.message.endswith("\n") else meta.message + "\n"
    return git(repo, *args, input_text=message, env=env).stdout.strip()


def parse_patch_path(raw: str) -> str | None:
    raw = raw.strip()
    if raw == "/dev/null":
        return None
    if raw.startswith("a/") or raw.startswith("b/"):
        return raw[2:]
    return raw


def parse_count(value: str | None) -> int:
    return 1 if value is None else int(value)


def split_lf_keepends(text: str) -> list[str]:
    """Split Git text on LF only; binary-ish data may contain other line separators."""
    if not text:
        return []
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def parse_unified_diff(
    patch: str, *, emit_binary: bool = False
) -> list[Hunk | BinaryHunk]:
    """Parse a unified diff into hunks.

    By default, raises `AbsorbError` when a binary file diff is encountered
    (the historic behavior, used by callers that need textual hunks for
    blame). With `emit_binary=True`, binary file diffs are emitted as
    `BinaryHunk` records instead, so the caller can apply them by copying
    the target blob into the index.
    """
    lines = split_lf_keepends(patch)
    hunks: list[Hunk | BinaryHunk] = []
    i = 0
    file_header: list[str] = []
    old_path: str | None = None
    new_path: str | None = None
    diff_path_a: str | None = None
    diff_path_b: str | None = None
    index_new_sha: str | None = None
    index_mode: str | None = None
    new_file_mode: str | None = None
    deleted_file_mode: str | None = None
    new_mode: str | None = None

    def reset_file_state() -> None:
        nonlocal old_path, new_path, diff_path_a, diff_path_b
        nonlocal index_new_sha, index_mode, new_file_mode, deleted_file_mode, new_mode
        old_path = None
        new_path = None
        diff_path_a = None
        diff_path_b = None
        index_new_sha = None
        index_mode = None
        new_file_mode = None
        deleted_file_mode = None
        new_mode = None

    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            file_header = [line]
            reset_file_state()
            match = DIFF_GIT_PATHS_RE.match(line)
            if match:
                diff_path_a = match.group("a")
                diff_path_b = match.group("b")
            i += 1
            continue

        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            if not emit_binary:
                raise AbsorbError("binary change encountered in target commit")
            is_deletion = (
                deleted_file_mode is not None
                or _is_zero_sha(index_new_sha)
            )
            mode = new_file_mode or new_mode or index_mode
            blob = None if is_deletion else index_new_sha
            if not is_deletion and (blob is None or mode is None):
                raise AbsorbError(
                    "cannot extract binary blob/mode for "
                    f"{diff_path_b or diff_path_a or '<unknown>'}; "
                    "diff lacks `index` line with full SHA "
                    "(use --full-index)"
                )
            hunks.append(
                BinaryHunk(
                    old_path=diff_path_a,
                    new_path=None if is_deletion else (diff_path_b or diff_path_a),
                    new_blob=blob,
                    new_mode=mode,
                )
            )
            # Skip remaining lines belonging to this file's diff section
            # until the next `diff --git` line (or EOF).
            i += 1
            while i < len(lines) and not lines[i].startswith("diff --git "):
                i += 1
            continue

        if line.startswith("@@ "):
            match = HUNK_RE.match(line)
            if not match:
                raise AbsorbError(f"cannot parse hunk header: {line.rstrip()}")
            old_start = int(match.group("old_start"))
            old_count = parse_count(match.group("old_count"))
            new_start = int(match.group("new_start"))
            new_count = parse_count(match.group("new_count"))
            hunk_header = line
            i += 1
            body: list[str] = []
            old_side_lines: list[int] = []
            old_line = old_start

            while i < len(lines):
                body_line = lines[i]
                if body_line.startswith("diff --git ") or body_line.startswith("@@ "):
                    break
                if body_line.startswith((" ", "-")):
                    old_side_lines.append(old_line)
                    old_line += 1
                elif body_line.startswith("+"):
                    pass
                elif body_line.startswith("\\"):
                    pass
                elif body_line.startswith("Binary files ") or body_line.startswith("GIT binary patch"):
                    raise AbsorbError("binary change encountered in target commit")
                body.append(body_line)
                i += 1

            hunks.append(
                Hunk(
                    old_path=old_path,
                    new_path=new_path,
                    file_header=tuple(file_header),
                    hunk_header=hunk_header,
                    hunk_lines=tuple(body),
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    old_side_lines=old_side_lines,
                )
            )
            continue

        if file_header:
            file_header.append(line)
            if line.startswith("--- "):
                old_path = parse_patch_path(line[4:].strip().split("\t", 1)[0])
            elif line.startswith("+++ "):
                new_path = parse_patch_path(line[4:].strip().split("\t", 1)[0])
            else:
                stripped = line.rstrip("\n").rstrip("\r")
                if stripped.startswith("index "):
                    match = INDEX_LINE_RE.match(stripped)
                    if match:
                        index_new_sha = match.group("new")
                        index_mode = match.group("mode") or index_mode
                elif stripped.startswith("new file mode "):
                    match = NEW_FILE_MODE_RE.match(stripped)
                    if match:
                        new_file_mode = match.group("mode")
                elif stripped.startswith("deleted file mode "):
                    match = DELETED_FILE_MODE_RE.match(stripped)
                    if match:
                        deleted_file_mode = match.group("mode")
                elif stripped.startswith("new mode "):
                    match = NEW_MODE_RE.match(stripped)
                    if match:
                        new_mode = match.group("mode")
        i += 1

    return hunks


def blame_line(repo: str | Path, rev: str, path: str, line_no: int) -> str | None:
    result = git(
        repo,
        "blame",
        "--first-parent",
        "--line-porcelain",
        "-L",
        f"{line_no},{line_no}",
        rev,
        "--",
        path,
        check=False,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if re.match(r"^[0-9a-f]{40} ", line):
            return line.split(" ", 1)[0]
    return None


def commit_touches_path(repo: str | Path, commit: str, path: str) -> bool:
    parent_line = git_text(repo, "rev-list", "--parents", "-n", "1", commit).strip()
    parents = parent_line.split()[1:]
    if parents:
        out = git_text(repo, "diff", "--name-only", "--no-renames", parents[0], commit, "--", path)
    else:
        out = git_text(repo, "ls-tree", "-r", "--name-only", commit, "--", path)
    return any(line == path for line in out.splitlines())


def newest_path_touch_on_chain(
    repo: str | Path,
    chain: list[str],
    path: str,
    source_index: int,
) -> str | None:
    """Newest first-parent ancestor of `chain[source_index]` (exclusive) that touched `path`.

    Backed by a single `git log --first-parent -1 -- <path>` invocation
    instead of iterating the chain and running `git diff --name-only` per
    commit, which is O(chain) git calls and very slow on long histories.

    Returns the SHA, or None if no first-parent ancestor ever touched the
    path. The returned SHA is always on `chain` because we walk from
    `chain[source_index - 1]` along first parents, which by construction is
    a prefix of `chain`.
    """
    if source_index <= 0:
        return None
    out = git_text(
        repo,
        "log",
        "--first-parent",
        "--pretty=%H",
        "-1",
        chain[source_index - 1],
        "--",
        path,
    )
    sha = out.strip()
    return sha or None


def newest_path_touch_target(
    repo: str | Path,
    chain: list[str],
    path: str,
    source_index: int,
    min_target_index: int,
) -> str | None:
    sha = newest_path_touch_on_chain(repo, chain, path, source_index)
    if sha is None:
        return None
    chain_index = {s: i for i, s in enumerate(chain)}
    idx = chain_index.get(sha)
    if idx is None or idx < min_target_index or idx >= source_index:
        return None
    return sha


def newest_path_touch_decision(
    repo: str | Path,
    chain: list[str],
    hunk: Hunk,
    source_index: int,
    min_target_index: int,
    target_reason: str,
) -> HunkDecision:
    path = hunk.old_path or hunk.new_path
    if not path:
        return HunkDecision(hunk, None, "path-touch fallback requires a non-null file path")

    sha = newest_path_touch_on_chain(repo, chain, path, source_index)
    if sha is None:
        return HunkDecision(hunk, None, "no prior commit touched the same path")
    chain_index = {s: i for i, s in enumerate(chain)}
    idx = chain_index.get(sha)
    if idx is None:
        # Defensive: --first-parent should keep us on `chain`, but if a
        # caller passed a non-matching chain we shouldn't claim a target.
        return HunkDecision(
            hunk,
            None,
            f"newest path touch {sha[:12]} is not on the input first-parent chain",
        )
    if idx < min_target_index:
        return HunkDecision(
            hunk,
            None,
            f"latest path touch is at or before base boundary: {sha[:12]}",
        )
    return HunkDecision(hunk, sha, target_reason)


def choose_hunk_target(
    repo: str | Path,
    parent_rev: str,
    hunk: Hunk,
    chain_index: dict[str, int],
    source_index: int,
    min_target_index: int = 0,
) -> str | None:
    return choose_hunk_target_decision(
        repo,
        parent_rev,
        hunk,
        chain_index,
        source_index,
        min_target_index,
    ).target


def choose_hunk_target_decision(
    repo: str | Path,
    parent_rev: str,
    hunk: Hunk,
    chain_index: dict[str, int],
    source_index: int,
    min_target_index: int = 0,
) -> HunkDecision:
    if hunk.is_added_only or not hunk.old_path:
        return HunkDecision(hunk, None, "added-only hunk has no old-side blame target")

    candidates: set[str] = set()
    base_blocked: set[str] = set()
    out_of_range: set[str] = set()
    untracked: set[str] = set()
    for line_no in hunk.old_side_lines:
        blamed = blame_line(repo, parent_rev, hunk.old_path, line_no)
        if blamed is None:
            continue
        idx = chain_index.get(blamed)
        if idx is not None and min_target_index <= idx < source_index:
            candidates.add(blamed)
        elif idx is not None and idx < min_target_index:
            base_blocked.add(blamed)
        elif idx is not None:
            out_of_range.add(blamed)
        else:
            untracked.add(blamed)

    if not candidates:
        if base_blocked:
            blocked = ", ".join(sorted(sha[:12] for sha in base_blocked))
            return HunkDecision(hunk, None, f"only blamed commit(s) are at or before base boundary: {blocked}")
        if out_of_range:
            blocked = ", ".join(sorted(sha[:12] for sha in out_of_range))
            return HunkDecision(hunk, None, f"only blamed commit(s) are outside the absorb range: {blocked}")
        if untracked:
            blocked = ", ".join(sorted(sha[:12] for sha in untracked))
            return HunkDecision(hunk, None, f"blamed commit(s) are not on the input first-parent chain: {blocked}")
        return HunkDecision(hunk, None, "no blamed commit found on old-side hunk lines")
    target = max(candidates, key=lambda sha: chain_index[sha])
    return HunkDecision(hunk, target, "newest eligible blamed commit")


def first_parent_chain(repo: str | Path, tip: str) -> list[str]:
    return [
        line
        for line in git_text(repo, "rev-list", "--first-parent", "--reverse", tip).splitlines()
        if line
    ]


MYSQL_UPSTREAM_REF_RE = re.compile(r"^mysql-(\d+)\.(\d+)\.(\d+)$")


def detect_latest_mysql_base_branch(
    repo: str | Path, input_tip: str
) -> tuple[str, str] | None:
    """Find the highest-version `mysql-M.m.p` ref in the input branch's ancestry.
    Returns (ref_short, peeled_sha) or None.

    Looks at both `refs/tags/mysql-*` and `refs/heads/mysql-*`. Picks the latest by
    `(major, minor, patch)` tuple whose tip commit is an ancestor of `input_tip`
    (general ancestry, not strict first-parent). Branch rewrites can move the
    upstream-base tag off the first-parent chain even though it still merges
    into the history; ancestry catches that case.
    """
    out = git_text(
        repo,
        "for-each-ref",
        "--format=%(refname:short)\t%(objectname)\t%(*objectname)",
        "refs/tags/mysql-*",
        "refs/heads/mysql-*",
    )
    candidates: list[tuple[tuple[int, int, int], str, str]] = []
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        ref_short = parts[0]
        m = MYSQL_UPSTREAM_REF_RE.match(ref_short)
        if not m:
            continue
        peeled = parts[2] if len(parts) > 2 and parts[2] else (parts[1] if len(parts) > 1 else "")
        if not peeled:
            continue
        version = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        candidates.append((version, ref_short, peeled))
    candidates.sort(key=lambda x: x[0], reverse=True)
    for _version, ref_short, sha in candidates:
        rc = git(
            repo, "merge-base", "--is-ancestor", sha, input_tip, check=False
        ).returncode
        if rc == 0:
            return ref_short, sha
    return None


def first_parent_index_after_base(
    repo: str | Path, chain: list[str], base_sha: str
) -> int | None:
    """Translate `base_sha` (an ancestor of the input branch) into the smallest
    chain index `i` such that `chain[i]` is `base_sha` itself or a descendant of
    it. Subsequent chain entries are eligible absorption targets; earlier entries
    forked off before `base_sha` joined and are not.
    """
    chain_index = {sha: idx for idx, sha in enumerate(chain)}
    if base_sha in chain_index:
        return chain_index[base_sha] + 1
    # base_sha is reachable via a merge somewhere on the chain. Find the earliest
    # chain entry that descends from base_sha.
    for i, sha in enumerate(chain):
        rc = git(
            repo, "merge-base", "--is-ancestor", base_sha, sha, check=False
        ).returncode
        if rc == 0:
            return i + 1
    return None


def cherry_pick_tree(repo: str | Path, base: str | None, ours: str | None, theirs: str) -> str:
    if base is None or ours is None:
        return tree_of(repo, theirs)
    result = git(
        repo,
        "merge-tree",
        "--write-tree",
        f"--merge-base={base}",
        ours,
        theirs,
        check=False,
    )
    if result.returncode != 0:
        tree = merge_tree_output_tree(result.stdout)
        if tree and is_replayable_delete_conflict(result.stdout):
            conflict_summary = ", ".join(sorted(set(merge_tree_conflict_types(result.stdout))))
            log(
                f"  {STYLE.yellow('accepting')} {STYLE.red(conflict_summary)} "
                f"replay result for {short_sha(theirs)} onto {short_sha(ours)}"
            )
            return tree
        try:
            log(
                f"  {STYLE.yellow('replaying')} {short_sha(theirs)} onto "
                f"{short_sha(ours)} with patch fallback"
            )
            return patch_cherry_pick_tree(repo, base, ours, theirs)
        except AbsorbError as fallback_exc:
            raise AbsorbError(
                f"could not replay {theirs[:12]} onto {ours[:12]}\n"
                f"STDOUT:\n{colorize_conflicts(result.stdout)}\n"
                f"STDERR:\n{result.stderr}\n"
                f"FALLBACK:\n{fallback_exc}"
            ) from fallback_exc
    tree = merge_tree_output_tree(result.stdout)
    if not tree:
        raise AbsorbError(f"merge-tree did not return a tree for {theirs[:12]}")
    return tree


def patch_cherry_pick_tree(repo: str | Path, base: str, ours: str, theirs: str) -> str:
    patch = git_text(
        repo,
        "diff",
        "--full-index",
        "--no-ext-diff",
        "--no-renames",
        base,
        theirs,
    )
    hunks = parse_unified_diff(patch, emit_binary=True)
    if not hunks:
        return tree_of(repo, ours)
    return apply_hunks_to_tree(repo, tree_of(repo, ours), hunks)


def apply_binary_hunk_to_index(
    repo: str | Path,
    env: dict[str, str],
    hunk: BinaryHunk,
) -> None:
    if hunk.new_blob is None:
        # Deletion.
        path = hunk.old_path or hunk.new_path
        if path is None:
            raise AbsorbError("binary deletion has no path")
        git(repo, "update-index", "--remove", "--", path, env=env)
        return
    path = hunk.new_path or hunk.old_path
    if path is None:
        raise AbsorbError("binary change has no path")
    mode = hunk.new_mode or "100644"
    git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"{mode},{hunk.new_blob},{path}",
        env=env,
    )


def apply_hunks_to_tree(
    repo: str | Path, tree: str, hunks: list[Hunk | BinaryHunk]
) -> str:
    fd, index_path = tempfile.mkstemp(prefix="ps-absorb-hunks-index-")
    os.close(fd)
    os.unlink(index_path)
    try:
        env = {"GIT_INDEX_FILE": index_path}
        current_tree = tree
        for hunk in hunks:
            git(repo, "read-tree", "--reset", current_tree, env=env)
            if isinstance(hunk, BinaryHunk):
                apply_binary_hunk_to_index(repo, env, hunk)
                current_tree = git(repo, "write-tree", env=env).stdout.strip()
                continue
            if is_submodule_hunk(hunk):
                apply_submodule_hunk_to_index(repo, env, hunk)
                current_tree = git(repo, "write-tree", env=env).stdout.strip()
                continue
            result = git(
                repo,
                "apply",
                "--cached",
                "--3way",
                "--whitespace=nowarn",
                "-",
                check=False,
                input_text=hunk.patch_text(),
                env=env,
            )
            if result.returncode != 0:
                path = hunk.new_path or hunk.old_path or "<unknown>"
                git(repo, "read-tree", "--reset", current_tree, env=env)
                try:
                    apply_hunk_to_index_with_fallback(repo, env, hunk)
                    log(
                        f"  {STYLE.yellow('fallback-applied')} hunk for "
                        f"{styled_path(path)}"
                    )
                except AbsorbError as fallback_exc:
                    raise AbsorbError(
                        f"could not apply hunk for {path} at {hunk.hunk_header.rstrip()}\n"
                        f"STDOUT:\n{colorize_conflicts(result.stdout)}\n"
                        f"STDERR:\n{result.stderr}\n"
                        f"FALLBACK:\n{fallback_exc}"
                    ) from fallback_exc
            current_tree = git(repo, "write-tree", env=env).stdout.strip()
        return current_tree
    finally:
        try:
            os.unlink(index_path)
        except OSError:
            pass


def merge_tree_output_tree(output: str) -> str | None:
    for line in output.splitlines():
        line = line.strip()
        if re.match(r"^[0-9a-f]{40}$", line):
            return line
    return None


def merge_tree_conflict_types(output: str) -> list[str]:
    conflict_types: list[str] = []
    for line in output.splitlines():
        match = CONFLICT_RE.match(line)
        if match:
            conflict_types.append(match.group("type"))
    return conflict_types


def is_replayable_delete_conflict(output: str) -> bool:
    conflict_types = merge_tree_conflict_types(output)
    return bool(conflict_types) and all(
        conflict_type in REPLAYABLE_DELETE_CONFLICTS for conflict_type in conflict_types
    )


def hunk_has_deletions(hunk: Hunk) -> bool:
    return any(line.startswith("-") for line in hunk.hunk_lines)


def hunk_has_additions(hunk: Hunk) -> bool:
    return any(line.startswith("+") for line in hunk.hunk_lines)


def is_submodule_hunk(hunk: Hunk) -> bool:
    """Detect a submodule (gitlink) update hunk.

    Git renders submodule changes as a synthetic single-line diff like:

        @@ -1 +1 @@
        -Subproject commit <old-sha>
        +Subproject commit <new-sha>

    These cannot be absorbed into a prior commit because the path is a
    gitlink rather than a text file, so `git blame` has nothing to attribute.
    """
    for line in hunk.hunk_lines:
        if line.startswith(("-Subproject commit ", "+Subproject commit ")):
            return True
    return False


def hunk_line_text(line: str) -> str:
    return line[1:]


def is_no_newline_marker(line: str) -> bool:
    return line.startswith("\\ No newline at end of file")


def find_sequence(lines: list[str], sequence: list[str], start: int = 0) -> list[int]:
    if not sequence:
        return []
    end = len(lines) - len(sequence) + 1
    return [idx for idx in range(start, end) if lines[idx : idx + len(sequence)] == sequence]


def find_subsequence_positions(
    lines: list[str],
    sequence: list[str],
    path: str,
    header: str,
) -> list[int]:
    max_gap = 50
    candidates: list[list[int]] = []

    for first in find_sequence(lines, [sequence[0]]):
        positions = [first]
        cursor = first + 1
        for item in sequence[1:]:
            next_pos = None
            for idx in range(cursor, min(len(lines), cursor + max_gap + 1)):
                if lines[idx] == item:
                    next_pos = idx
                    break
            if next_pos is None:
                break
            positions.append(next_pos)
            cursor = next_pos + 1
        if len(positions) == len(sequence):
            candidates.append(positions)

    if not candidates:
        raise AbsorbError(f"could not locate fallback context for {path} at {header.rstrip()}")

    candidates.sort(key=lambda item: (item[-1] - item[0], item[0]))
    if len(candidates) > 1:
        best_span = candidates[0][-1] - candidates[0][0]
        if candidates[1][-1] - candidates[1][0] == best_span:
            raise AbsorbError(
                f"could not locate a unique fallback context for {path} "
                f"at {header.rstrip()}"
            )
    return candidates[0]


def fallback_apply_hunk(lines: list[str], hunk: Hunk, path: str) -> list[str]:
    if not hunk_has_additions(hunk) and not hunk_has_deletions(hunk):
        raise AbsorbError("fallback requires a changing hunk")
    unsupported_metadata = [
        line.rstrip("\n")
        for line in hunk.hunk_lines
        if line.startswith("\\") and not is_no_newline_marker(line)
    ]
    if unsupported_metadata:
        raise AbsorbError(f"fallback does not support hunk metadata: {unsupported_metadata[0]}")

    old_side = [
        hunk_line_text(line)
        for line in hunk.hunk_lines
        if line.startswith((" ", "-"))
    ]
    if not old_side:
        if hunk_has_deletions(hunk):
            raise AbsorbError("fallback requires old-side context")
        insert_at = hunk.old_start
        if insert_at < 0 or insert_at > len(lines):
            raise AbsorbError(
                f"fallback insertion point {insert_at} is outside {path} "
                f"with {len(lines)} line(s)"
            )
        added = [
            hunk_line_text(line)
            for line in hunk.hunk_lines
            if line.startswith("+")
        ]
        return [*lines[:insert_at], *added, *lines[insert_at:]]

    # Git reports conflicts when the rewritten side has nearby absorbed lines.
    # Match the old-side hunk as an ordered subsequence so those extra lines
    # survive while the hunk's explicit additions/deletions are still applied.
    positions = find_subsequence_positions(lines, old_side, path, hunk.hunk_header)
    position_iter = iter(positions)
    current = 0
    updated: list[str] = []

    for line in hunk.hunk_lines:
        if is_no_newline_marker(line):
            continue
        if line.startswith("+"):
            updated.append(hunk_line_text(line))
            continue
        if not line.startswith((" ", "-")):
            continue

        pos = next(position_iter)
        if line.startswith(" "):
            updated.extend(lines[current : pos + 1])
        else:
            updated.extend(lines[current:pos])
        current = pos + 1

    updated.extend(lines[current:])
    return updated


def index_file_entry(repo: str | Path, env: dict[str, str], path: str) -> tuple[str, str]:
    out = git(repo, "ls-files", "--stage", "--", path, env=env).stdout
    entries = [line for line in out.splitlines() if line.endswith(f"\t{path}")]
    if len(entries) != 1:
        raise AbsorbError(f"expected one index entry for {path}, found {len(entries)}")
    meta, _ = entries[0].split("\t", 1)
    mode, blob, stage = meta.split()
    if stage != "0":
        raise AbsorbError(f"fallback requires a resolved stage-0 index entry for {path}")
    return mode, blob


SUBPROJECT_PLUS = "+Subproject commit "
SUBPROJECT_MINUS = "-Subproject commit "
GITLINK_MODE = "160000"


def submodule_hunk_new_sha(hunk: Hunk) -> str | None:
    """Extract the post-image gitlink SHA from a submodule hunk, or None."""
    for line in hunk.hunk_lines:
        body = line.rstrip("\n").rstrip("\r")
        if body.startswith(SUBPROJECT_PLUS):
            return body[len(SUBPROJECT_PLUS):].strip()
    return None


def apply_submodule_hunk_to_index(
    repo: str | Path,
    env: dict[str, str],
    hunk: Hunk,
) -> None:
    """Apply a gitlink (submodule) hunk by directly updating the index entry.

    `git apply --cached` is unreliable on gitlinks because the index entry
    holds the submodule's commit SHA rather than a blob, so the standard
    3-way machinery in `apply_hunks_to_tree` doesn't have the right inputs.
    Instead we read the new gitlink SHA out of the `+Subproject commit ...`
    line and update (or remove) the cacheinfo for the path directly.
    """
    path = hunk.new_path or hunk.old_path
    if not path:
        raise AbsorbError("submodule hunk has no path")
    new_sha = submodule_hunk_new_sha(hunk)
    if new_sha is not None:
        git(
            repo,
            "update-index",
            "--add",
            "--cacheinfo",
            GITLINK_MODE,
            new_sha,
            path,
            env=env,
        )
        return
    if any(
        line.startswith(SUBPROJECT_MINUS) for line in hunk.hunk_lines
    ):
        git(repo, "update-index", "--remove", "--", path, env=env)
        return
    raise AbsorbError(
        f"submodule hunk for {path} has neither + nor - Subproject line"
    )


def apply_hunk_to_index_with_fallback(repo: str | Path, env: dict[str, str], hunk: Hunk) -> None:
    path = hunk.new_path or hunk.old_path
    if not path:
        raise AbsorbError("fallback requires a non-null file path")

    mode, blob = index_file_entry(repo, env, path)
    content = git(repo, "cat-file", "-p", blob).stdout
    updated_lines = fallback_apply_hunk(split_lf_keepends(content), hunk, path)
    updated = "".join(updated_lines)
    new_blob = git(repo, "hash-object", "-w", "--stdin", input_text=updated).stdout.strip()
    git(repo, "update-index", "--cacheinfo", mode, new_blob, path, env=env)


def build_hunk_dispositions(
    repo: str | Path,
    source: str,
    source_parent: str,
    chain: list[str],
    context: int,
    min_target_index: int = 0,
) -> list[HunkDisposition]:
    """Parse COMMIT's diff and decide a target (or skip reason) for every hunk."""
    patch = git_text(
        repo,
        "diff",
        "--full-index",
        "--no-ext-diff",
        "--no-renames",
        f"-U{context}",
        source_parent,
        source,
    )
    hunks = parse_unified_diff(patch)
    chain_index = {sha: idx for idx, sha in enumerate(chain)}
    source_index = chain_index[source]
    dispositions: list[HunkDisposition] = []

    for number, hunk in enumerate(hunks, start=1):
        decision = choose_hunk_target_decision(
            repo,
            source_parent,
            hunk,
            chain_index,
            source_index,
            min_target_index,
        )
        hunk_file = hunk.old_path or hunk.new_path
        # Submodule (gitlink) hunks have old-side lines but `git blame` cannot
        # attribute them, so blame always fails. Treat them like added-only
        # hunks and fall back to the newest commit that touched the same
        # gitlink path. The same applies to genuinely added-only hunks.
        if decision.target is None and (hunk.is_added_only or is_submodule_hunk(hunk)):
            decision = newest_path_touch_decision(
                repo,
                chain,
                hunk,
                source_index,
                min_target_index,
                "newest eligible commit that touched the same path",
            )
        if (
            decision.target is None
            and hunk_file
            and decision.reason.startswith("only blamed commit(s) are at or before base boundary")
        ):
            fallback_target = newest_path_touch_target(
                repo,
                chain,
                hunk_file,
                source_index,
                min_target_index,
            )
            if fallback_target:
                decision = HunkDecision(
                    hunk,
                    fallback_target,
                    "newest eligible commit that touched the same path after base boundary",
                )
        dispositions.append(
            HunkDisposition(
                number=number,
                hunk=hunk,
                target=decision.target,
                skip_reason=None if decision.target else decision.reason,
            )
        )

    return dispositions


def dispositions_by_target(
    dispositions: list[HunkDisposition],
) -> dict[str, list[HunkDisposition]]:
    grouped: dict[str, list[HunkDisposition]] = defaultdict(list)
    for d in dispositions:
        if d.target:
            grouped[d.target].append(d)
    return grouped


def rewrite_branch(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        raise AbsorbError(f"not a git repository: {repo}")

    ensure_clean_worktree(repo)
    if not args.input_branch:
        raise AbsorbError("--input-branch is required; refusing to infer the input branch")
    input_branch = args.input_branch
    output_branch = args.output_branch or input_branch
    if args.output_branch == input_branch:
        raise AbsorbError("--output-branch must differ from --input-branch; omit it for in-place rewrite")

    original_tip = branch_tip(repo, input_branch)
    output_expected_tip: str | None
    if args.output_branch:
        if branch_exists(repo, output_branch):
            if not args.force:
                raise AbsorbError(f"output branch already exists: {output_branch}; pass --force to replace it")
            output_expected_tip = branch_tip(repo, output_branch)
        else:
            output_expected_tip = None
    else:
        output_expected_tip = original_tip

    source = rev_parse(repo, args.commit)
    source_meta = load_commit(repo, source)
    if len(source_meta.parents) != 1:
        raise AbsorbError("target commit must be a non-merge commit")
    source_parent = source_meta.parents[0]

    chain = first_parent_chain(repo, original_tip)
    chain_index = {sha: idx for idx, sha in enumerate(chain)}
    if source not in chain_index:
        raise AbsorbError("target commit is not on the branch first-parent chain")
    min_target_index = 0
    if args.base_branch:
        base_tip = rev_parse(repo, args.base_branch)
        idx = first_parent_index_after_base(repo, chain, base_tip)
        if idx is None:
            raise AbsorbError("--base-branch tip is not in the input branch ancestry")
        min_target_index = idx
    else:
        detected = detect_latest_mysql_base_branch(repo, original_tip)
        if detected is not None:
            ref_short, sha = detected
            idx = first_parent_index_after_base(repo, chain, sha)
            if idx is not None:
                min_target_index = idx
                log(
                    f"Auto-detected base: {STYLE.bold(ref_short)} ({short_sha(sha)}); "
                    f"hunks will not be absorbed at or before this tip. "
                    f"Override with --base-branch."
                )

    dispositions = build_hunk_dispositions(
        repo, source, source_parent, chain, args.context, min_target_index
    )
    log_numbered_hunks(repo, dispositions, source_meta)

    groups = dispositions_by_target(dispositions)
    if not groups:
        log("No movable hunks found; branch left unchanged.")
        if args.output_branch:
            update_branch_ref(repo, output_branch, original_tip, output_expected_tip)
            log(f"Created {output_branch} at unchanged tip {original_tip}")
        return 0

    earliest = min(chain_index[target] for target in groups)
    if earliest == 0:
        raise AbsorbError("cannot absorb into the root commit")

    log(
        f"{STYLE.bold('Rewriting')} "
        f"{STYLE.bold(pluralize(len(chain) - earliest, 'commit'))}..."
    )
    new_parent = chain[earliest - 1]
    rewritten: dict[str, str] = {}

    for idx in range(earliest, len(chain)):
        original = chain[idx]
        meta = load_commit(repo, original)
        original_parent = meta.parents[0] if meta.parents else None
        new_tree = cherry_pick_tree(repo, original_parent, new_parent, original)
        absorbed = groups.get(original, [])
        if absorbed:
            new_tree = apply_hunks_to_tree(
                repo, new_tree, [d.hunk for d in absorbed]
            )
        if original == source and new_tree == tree_of(repo, new_parent):
            log(
                f"  {commit_label(meta)}  "
                f"{STYLE.yellow('-> dropped (empty after absorption)')}"
            )
            rewritten[original] = new_parent
            continue
        if absorbed:
            numbers = ", ".join(f"#{d.number}" for d in absorbed)
            absorbed_tag = STYLE.green(
                f"-> absorbed {pluralize(len(absorbed), 'hunk')} ({numbers})"
            )
            log(f"  {commit_label(meta)}  {absorbed_tag}")
        new_commit = commit_tree(repo, new_tree, new_parent, meta)
        rewritten[original] = new_commit
        new_parent = new_commit

    candidate_tip = new_parent
    if tree_of(repo, original_tip) != tree_of(repo, candidate_tip):
        raise AbsorbError(
            f"null-diff tree check failed: {original_tip[:12]} and {candidate_tip[:12]} differ"
        )
    diff_check = git(repo, "diff", "--quiet", original_tip, candidate_tip, check=False)
    if diff_check.returncode != 0:
        raise AbsorbError(
            f"git diff --quiet failed for {original_tip[:12]}..{candidate_tip[:12]}"
        )

    update_branch_ref(repo, output_branch, candidate_tip, output_expected_tip)

    moved = sum(len(v) for v in groups.values())
    not_absorbed = sum(1 for d in dispositions if d.target is None)
    log("")
    summary = f"{STYLE.bold('Moved')} {STYLE.bold(pluralize(moved, 'hunk'))}."
    if not_absorbed:
        summary += (
            f" {STYLE.bold(pluralize(not_absorbed, 'hunk'))} not absorbed."
        )
    log(summary)
    if args.output_branch:
        log(
            f"{STYLE.bold('Created')} {output_branch} from {input_branch}: "
            f"{short_sha(original_tip)} -> {short_sha(candidate_tip)}"
        )
    else:
        log(
            f"{STYLE.bold('Updated')} {input_branch}: "
            f"{short_sha(original_tip)} -> {short_sha(candidate_tip)}"
        )
    log(STYLE.green("Null diff check passed."))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("commit", help="Non-merge commit whose hunks should be absorbed.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"Git repository (default: {DEFAULT_REPO}).")
    parser.add_argument("--input-branch", default=None, help="Input branch to rewrite, updated in place by default.")
    parser.add_argument(
        "--base-branch",
        default=None,
        help=(
            "Do not absorb hunks into commits at or before this branch tip. "
            "If omitted, the script auto-detects the latest mysql-M.m.p ref "
            "(tags or heads) that lies on the input branch first-parent chain."
        ),
    )
    parser.add_argument("--output-branch", default=None, help="Create/update this branch with the rewritten history.")
    parser.add_argument("--force", action="store_true", help="Replace an existing --output-branch.")
    parser.add_argument("--context", type=int, default=3, help="Unified diff context for hunk parsing.")
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
    configure_style(args.color)
    try:
        return rewrite_branch(args)
    except AbsorbError as exc:
        text = colorize_conflicts(str(exc))
        print(f"{STYLE.bold(STYLE.red('ERROR:'))} {text}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

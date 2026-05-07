#!/usr/bin/env python3
"""Absorb hunks from one commit into prior first-parent commits.

For each textual hunk in COMMIT, blame the hunk's old-side context and
deleted lines at COMMIT^, pick the newest blamed commit on the selected
branch's first-parent chain, and fold the whole hunk into that commit.

The explicitly selected branch is updated in place only after the rewritten
candidate tip has a null diff against the original branch tip. Pass
--output-branch to create a separate rewritten branch instead.
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
class HunkDecision:
    hunk: Hunk
    target: str | None
    reason: str


HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)
CONFLICT_RE = re.compile(r"^CONFLICT \((?P<type>[^)]+)\):")
REPLAYABLE_DELETE_CONFLICTS = {"modify/delete", "rename/delete"}


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


def commit_label(meta: CommitMeta) -> str:
    return f"{meta.sha[:12]} {meta.title}"


def hunk_label(hunk: Hunk) -> str:
    path = hunk.new_path or hunk.old_path or "<unknown>"
    return f"{path} {hunk.hunk_header.rstrip()}"


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


def parse_unified_diff(patch: str) -> list[Hunk]:
    lines = split_lf_keepends(patch)
    hunks: list[Hunk] = []
    i = 0
    file_header: list[str] = []
    old_path: str | None = None
    new_path: str | None = None

    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            file_header = [line]
            old_path = None
            new_path = None
            i += 1
            continue

        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            raise AbsorbError("binary change encountered in target commit")

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


def newest_path_touch_target(
    repo: str | Path,
    chain: list[str],
    path: str,
    source_index: int,
    min_target_index: int,
) -> str | None:
    for idx in range(source_index - 1, min_target_index - 1, -1):
        if commit_touches_path(repo, chain[idx], path):
            return chain[idx]
    return None


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
                f"  accepting {conflict_summary} replay result for "
                f"{theirs[:12]} onto {ours[:12]}"
            )
            return tree
        try:
            log(f"  replaying {theirs[:12]} onto {ours[:12]} with patch fallback")
            return patch_cherry_pick_tree(repo, base, ours, theirs)
        except AbsorbError as fallback_exc:
            raise AbsorbError(
                f"could not replay {theirs[:12]} onto {ours[:12]}\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n"
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
    hunks = parse_unified_diff(patch)
    if not hunks:
        return tree_of(repo, ours)
    return apply_hunks_to_tree(repo, tree_of(repo, ours), hunks)


def apply_hunks_to_tree(repo: str | Path, tree: str, hunks: list[Hunk]) -> str:
    fd, index_path = tempfile.mkstemp(prefix="ps-absorb-hunks-index-")
    os.close(fd)
    os.unlink(index_path)
    try:
        env = {"GIT_INDEX_FILE": index_path}
        current_tree = tree
        for hunk in hunks:
            git(repo, "read-tree", "--reset", current_tree, env=env)
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
                    log(f"  fallback-applied hunk for {path}")
                except AbsorbError as fallback_exc:
                    raise AbsorbError(
                        f"could not apply hunk for {path} at {hunk.hunk_header.rstrip()}\n"
                        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n"
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
        raise AbsorbError("fallback requires old-side context")

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


def build_hunk_groups(
    repo: str | Path,
    source: str,
    source_parent: str,
    chain: list[str],
    context: int,
    min_target_index: int = 0,
) -> tuple[dict[str, list[Hunk]], list[HunkDecision]]:
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
    groups: dict[str, list[Hunk]] = defaultdict(list)
    skipped: list[HunkDecision] = []

    for hunk in hunks:
        decision = choose_hunk_target_decision(
            repo,
            source_parent,
            hunk,
            chain_index,
            source_index,
            min_target_index,
        )
        hunk_path = hunk.old_path or hunk.new_path
        if (
            decision.target is None
            and hunk_path
            and decision.reason.startswith("only blamed commit(s) are at or before base boundary")
        ):
            fallback_target = newest_path_touch_target(
                repo,
                chain,
                hunk_path,
                source_index,
                min_target_index,
            )
            if fallback_target:
                decision = HunkDecision(
                    hunk,
                    fallback_target,
                    "newest eligible commit that touched the same path after base boundary",
                )
        if decision.target:
            groups[decision.target].append(hunk)
        else:
            skipped.append(decision)

    return groups, skipped


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
        base_index = chain_index.get(base_tip)
        if base_index is None:
            raise AbsorbError("--base-branch tip is not on the input branch first-parent chain")
        min_target_index = base_index + 1

    groups, skipped_hunks = build_hunk_groups(repo, source, source_parent, chain, args.context, min_target_index)
    if not groups:
        log("No movable hunks found; branch left unchanged.")
        for decision in skipped_hunks:
            log(f"  skipped {hunk_label(decision.hunk)}: {decision.reason}")
        if args.output_branch:
            update_branch_ref(repo, output_branch, original_tip, output_expected_tip)
            log(f"Created {output_branch} at unchanged tip {original_tip}")
        return 0

    earliest = min(chain_index[target] for target in groups)
    if earliest == 0:
        raise AbsorbError("cannot absorb into the root commit")

    first_meta = load_commit(repo, chain[earliest])
    log(f"Rebuilding {len(chain) - earliest} commit(s) from {commit_label(first_meta)}...")
    for target in sorted(groups, key=chain_index.__getitem__):
        target_meta = load_commit(repo, target)
        log(f"  target {len(groups[target])} hunk(s): {commit_label(target_meta)}")
        for hunk in groups[target]:
            log(f"    {hunk_label(hunk)}")
    if skipped_hunks:
        log(f"  skipped {len(skipped_hunks)} hunk(s):")
        for decision in skipped_hunks:
            log(f"    {hunk_label(decision.hunk)}: {decision.reason}")
    new_parent = chain[earliest - 1]
    rewritten: dict[str, str] = {}

    for idx in range(earliest, len(chain)):
        original = chain[idx]
        meta = load_commit(repo, original)
        original_parent = meta.parents[0] if meta.parents else None
        new_tree = cherry_pick_tree(repo, original_parent, new_parent, original)
        if original in groups:
            log(f"  absorbing {len(groups[original])} hunk(s) into {commit_label(meta)}")
            for hunk in groups[original]:
                log(f"    absorbed {hunk_label(hunk)}")
            new_tree = apply_hunks_to_tree(repo, new_tree, groups[original])
        if original == source and new_tree == tree_of(repo, new_parent):
            log(f"  dropping empty absorbed commit {commit_label(meta)}")
            rewritten[original] = new_parent
            continue
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
    log(f"Moved {moved} hunk(s).")
    if args.output_branch:
        log(f"Created {output_branch} from {input_branch}: {original_tip} -> {candidate_tip}")
    else:
        log(f"Updated {input_branch}: {original_tip} -> {candidate_tip}")
    log("Null diff check passed.")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Absorb hunks from one commit into prior first-parent commits.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("commit", help="Non-merge commit whose hunks should be absorbed.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"Git repository (default: {DEFAULT_REPO}).")
    parser.add_argument("--input-branch", default=None, help="Input branch to rewrite, updated in place by default.")
    parser.add_argument("--base-branch", default=None, help="Do not absorb hunks into commits at or before this branch tip.")
    parser.add_argument("--output-branch", default=None, help="Create/update this branch with the rewritten history.")
    parser.add_argument("--force", action="store_true", help="Replace an existing --output-branch.")
    parser.add_argument("--context", type=int, default=3, help="Unified diff context for hunk parsing.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return rewrite_branch(args)
    except AbsorbError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

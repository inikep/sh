#!/usr/bin/env python3
"""Audit a replay diff for common post-conflict porting artifacts."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".ic"}

OBSOLETE_PATTERNS: list[tuple[str, str]] = [
    ("fil_system->name_hash", "old 5.7 fil_system hash member"),
    ("fil_system->space_list", "old 5.7 fil_system space list member"),
    ("fil_system->max_assigned_id", "old 5.7 fil_system max id member"),
    ("fil_system->mutex", "old 5.7 fil_system mutex member"),
    ("fil_node_complete_io", "old 5.7 fil I/O completion helper"),
    ("buf_pool_mutex_enter", "old buffer-pool mutex helper"),
    ("buf_pool_mutex_exit", "old buffer-pool mutex helper"),
    ("DB_TABLESPACE_TRUNCATED", "old/foreign tablespace status in this port"),
    ("OS_AIO_NORMAL", "old AIO mode enum"),
    ("Tablespace::is_undo_tablespace", "newer API not present in older 8.0 bases"),
    ("srv_is_tablespace_truncated", "newer API not present in older 8.0 bases"),
]

SUSPECT_LABELS = {"exit_loop", "crash", "page_not_corrupt"}
STRUCT_RE = re.compile(r"^\s*(?:struct|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b.*\{")
FIELD_RE = re.compile(
    r"^\s*(?:bool|ibool|ulint|uint32_t|page_no_t|lsn_t|size_t|int|unsigned|"
    r"UT_LIST_NODE_T\([^)]*\)|UT_LIST_BASE_NODE_T\([^)]*\)|hash_node_t)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\b"
)
LABEL_RE = re.compile(r"^\+([A-Za-z_][A-Za-z0-9_]*):")


@dataclass
class Finding:
    severity: str
    path: str
    line: int | None
    message: str

    def render(self) -> str:
        loc = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{self.severity}\t{loc}\t{self.message}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan staged or working-tree replay diffs for common conflict-helper "
            "artifacts before spending a full build attempt."
        )
    )
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--cached", action="store_true", help="Audit staged diff")
    parser.add_argument(
        "--base",
        default="HEAD^",
        help="Base for working-tree audits when --cached is not used (default: HEAD^)",
    )
    parser.add_argument(
        "--max-added-block",
        type=int,
        default=80,
        help="Warn on contiguous added source blocks larger than this many lines",
    )
    return parser.parse_args()


def git_text(worktree: Path, args: list[str], check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )
    return proc.stdout.decode("utf-8", errors="replace")


def changed_paths(worktree: Path, cached: bool, base: str) -> list[str]:
    if cached:
        args = ["diff", "--cached", "--name-only"]
    else:
        args = ["diff", "--name-only", base]
    return [
        p
        for p in git_text(worktree, args).splitlines()
        if Path(p).suffix in SOURCE_EXTS
    ]


def file_lines(worktree: Path, path: str, cached: bool) -> list[str]:
    if cached:
        proc = subprocess.run(
            ["git", "show", f":{path}"],
            cwd=worktree,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", errors="replace").splitlines()
    file_path = worktree / path
    if not file_path.exists():
        return []
    return file_path.read_text(encoding="utf-8", errors="replace").splitlines()


def diff_text(worktree: Path, path: str, cached: bool, base: str) -> str:
    if cached:
        args = ["diff", "--cached", "--", path]
    else:
        args = ["diff", base, "--", path]
    return git_text(worktree, args, check=False)


def added_lines_with_numbers(text: str) -> list[tuple[int, str]]:
    added: list[tuple[int, str]] = []
    new_line = 0
    for line in text.splitlines():
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            new_line = int(match.group(1)) - 1 if match else 0
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            new_line += 1
            added.append((new_line, line[1:]))
        elif line.startswith("-"):
            continue
        elif line.startswith(" "):
            new_line += 1
    return added


def audit_obsolete_patterns(path: str, lines: list[tuple[int, str]]) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in lines:
        for pattern, description in OBSOLETE_PATTERNS:
            if pattern in line:
                findings.append(
                    Finding("WARN", path, lineno, f"{description}: {pattern}")
                )
    return findings


def audit_duplicate_structs(path: str, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    struct_lines: dict[str, list[int]] = {}
    for lineno, line in enumerate(lines, 1):
        match = STRUCT_RE.match(line)
        if match:
            struct_lines.setdefault(match.group(1), []).append(lineno)
    for name in ("fil_space_t", "fil_node_t", "buf_page_t", "buf_block_t"):
        if len(struct_lines.get(name, [])) > 1:
            findings.append(
                Finding(
                    "WARN",
                    path,
                    struct_lines[name][1],
                    f"multiple definitions of {name}; possible old struct chunk inserted",
                )
            )
    return findings


def audit_duplicate_fields(path: str, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    stack: list[tuple[str, int, int, dict[str, int]]] = []
    brace_depth = 0
    for lineno, line in enumerate(lines, 1):
        match = STRUCT_RE.match(line)
        if match:
            stack.append((match.group(1), lineno, brace_depth + line.count("{"), {}))
        if stack:
            struct_name, _start, struct_depth, fields = stack[-1]
            field = FIELD_RE.match(line)
            if field and struct_depth <= brace_depth + line.count("{"):
                field_name = field.group(1)
                if "(" in line.split(field_name, 1)[-1]:
                    continue
                if field_name in fields:
                    findings.append(
                        Finding(
                            "WARN",
                            path,
                            lineno,
                            f"duplicate field {struct_name}::{field_name}; possible duplicate conflict block",
                        )
                    )
                else:
                    fields[field_name] = lineno
        brace_depth += line.count("{") - line.count("}")
        while stack and brace_depth < stack[-1][2]:
            stack.pop()
    return findings


def audit_diff_shape(path: str, text: str, max_added_block: int) -> list[Finding]:
    findings: list[Finding] = []
    new_line = 0
    added_run = 0
    added_run_start = 0
    for line in text.splitlines():
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            new_line = int(match.group(1)) - 1 if match else 0
            added_run = 0
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            new_line += 1
            added_run += 1
            if added_run == 1:
                added_run_start = new_line
            label = LABEL_RE.match(line)
            if label and label.group(1) in SUSPECT_LABELS:
                findings.append(
                    Finding(
                        "WARN",
                        path,
                        new_line,
                        f"added label {label.group(1)!r}; verify it is inside the intended function",
                    )
                )
            if added_run == max_added_block + 1:
                findings.append(
                    Finding(
                        "WARN",
                        path,
                        added_run_start,
                        f"large contiguous added block > {max_added_block} lines; inspect for whole old function/struct insertion",
                    )
                )
            continue
        if line.startswith("-"):
            continue
        added_run = 0
        if line.startswith(" "):
            new_line += 1
    return findings


def main() -> int:
    args = parse_args()
    worktree = args.worktree.resolve()
    paths = changed_paths(worktree, args.cached, args.base)
    findings: list[Finding] = []
    for path in paths:
        lines = file_lines(worktree, path, args.cached)
        path_diff = diff_text(worktree, path, args.cached, args.base)
        findings.extend(audit_obsolete_patterns(path, added_lines_with_numbers(path_diff)))
        findings.extend(audit_duplicate_structs(path, lines))
        findings.extend(audit_duplicate_fields(path, lines))
        findings.extend(audit_diff_shape(path, path_diff, args.max_added_block))

    if not findings:
        print(f"post-conflict-audit PASS ({len(paths)} source files checked)")
        return 0

    for finding in findings:
        print(finding.render())
    print(f"post-conflict-audit found {len(findings)} finding(s)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Capture reference feature-presence evidence for one source commit.

The script does not decide whether to apply or skip a commit. It extracts
concrete identifiers from the source commit, searches the reference tree, and
writes an auditable JSON record that the replay operator can cite in the
ledger.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b")
NOISY_WORDS = {
    "const", "static", "return", "include", "define", "ifdef", "ifndef",
    "endif", "class", "struct", "virtual", "public", "private", "false",
    "true", "NULL", "nullptr", "mysql", "test", "result", "source",
}
INTERESTING_PREFIXES = (
    "COM_",
    "ER_",
    "HA_",
    "MYSQL_",
    "OPT_",
    "PFS_",
    "PSI_",
    "SQLCOM_",
    "TOKUDB_",
    "innodb_",
    "log_slow_",
    "rpl_",
    "srv_",
    "tokudb_",
)


@dataclass
class GrepHit:
    identifier: str
    hits: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract source feature identifiers and search a reference tree."
    )
    parser.add_argument("--commit", required=True, help="Source commit SHA")
    parser.add_argument("--reference", required=True, help="Reference branch/commit")
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, help="JSON evidence output path")
    parser.add_argument("--max-identifiers", type=int, default=80)
    parser.add_argument("--max-hits", type=int, default=5)
    return parser.parse_args()


def git(cwd: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def git_text(cwd: Path, args: list[str], check: bool = True) -> str:
    return git(cwd, args, check=check).stdout.decode("utf-8", errors="replace")


def changed_paths(worktree: Path, commit: str) -> list[str]:
    text = git_text(worktree, ["diff-tree", "--no-commit-id", "--name-only", "-r", commit])
    return [line for line in text.splitlines() if line]


def added_paths(worktree: Path, commit: str) -> list[str]:
    text = git_text(worktree, ["diff-tree", "--no-commit-id", "--name-status", "-r", commit])
    paths: list[str] = []
    for line in text.splitlines():
        fields = line.split("\t")
        if fields and fields[0] == "A" and len(fields) >= 2:
            paths.append(fields[1])
    return paths


def source_diff(worktree: Path, commit: str) -> str:
    return git_text(worktree, ["diff", "--no-color", f"{commit}^", commit])


def source_subject(worktree: Path, commit: str) -> str:
    return git_text(worktree, ["show", "-s", "--format=%s", commit]).strip()


def source_body(worktree: Path, commit: str) -> str:
    return git_text(worktree, ["show", "-s", "--format=%B", commit]).strip()


def interesting_identifier(token: str) -> bool:
    if token in NOISY_WORDS:
        return False
    if token.startswith(INTERESTING_PREFIXES):
        return True
    if token.isupper() and "_" in token:
        return True
    if "_" in token and len(token) >= 7:
        return True
    return False


def extract_identifiers(diff_text: str, message: str, added: Iterable[str], limit: int) -> list[str]:
    candidates: list[str] = []
    candidates.extend(Path(path).stem for path in added)
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        candidates.extend(IDENT_RE.findall(line))
    candidates.extend(IDENT_RE.findall(message))

    seen: set[str] = set()
    identifiers: list[str] = []
    for token in candidates:
        if token in seen or not interesting_identifier(token):
            continue
        seen.add(token)
        identifiers.append(token)
        if len(identifiers) >= limit:
            break
    return identifiers


def path_exists(worktree: Path, reference: str, path: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{reference}:{path}"],
        cwd=worktree,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def grep_identifier(worktree: Path, reference: str, identifier: str, max_hits: int) -> list[str]:
    proc = git(
        worktree,
        ["grep", "-n", "-F", "--", identifier, reference],
        check=False,
    )
    if proc.returncode not in (0, 1):
        return [proc.stdout.decode("utf-8", errors="replace").strip()]
    text = proc.stdout.decode("utf-8", errors="replace")
    return [line for line in text.splitlines()[:max_hits] if line]


def main() -> int:
    args = parse_args()
    worktree = args.worktree.resolve()
    subject = source_subject(worktree, args.commit)
    body = source_body(worktree, args.commit)
    paths = changed_paths(worktree, args.commit)
    added = added_paths(worktree, args.commit)
    identifiers = extract_identifiers(
        source_diff(worktree, args.commit),
        f"{subject}\n{body}",
        added,
        args.max_identifiers,
    )

    path_evidence = [
        {"path": path, "present_in_reference": path_exists(worktree, args.reference, path)}
        for path in added
    ]
    grep_hits = [
        GrepHit(identifier=identifier, hits=grep_identifier(worktree, args.reference, identifier, args.max_hits))
        for identifier in identifiers
    ]
    present_identifiers = [hit.identifier for hit in grep_hits if hit.hits]
    absent_identifiers = [hit.identifier for hit in grep_hits if not hit.hits]

    evidence = {
        "commit": args.commit,
        "subject": subject,
        "reference": args.reference,
        "changed_paths": paths,
        "added_paths": path_evidence,
        "identifiers_searched": identifiers,
        "present_identifiers": present_identifiers,
        "absent_identifiers": absent_identifiers,
        "grep_hits": [asdict(hit) for hit in grep_hits],
        "summary": {
            "changed_path_count": len(paths),
            "added_path_count": len(added),
            "identifier_count": len(identifiers),
            "present_identifier_count": len(present_identifiers),
            "absent_identifier_count": len(absent_identifiers),
        },
    }

    text = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

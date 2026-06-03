#!/usr/bin/env python3
"""Range-level feature presence audit for Percona replay commits.

This helper compares the selected source commits against the target reference
range once, so replay does not run a slow full-reference grep before every
post-Group-8 commit. It is evidence, not an automatic skip/apply decision.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import ps_replay_feature_gate as commit_gate


MARKER_RE = re.compile(r"^\s*=+\sMARKER:")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare source-range feature identifiers to a reference range."
    )
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-list", type=Path, help="Ordered source commit list")
    source.add_argument("--source-range", nargs=2, metavar=("BASE", "TIP"))
    parser.add_argument(
        "--source-exclude",
        action="append",
        default=[],
        help="Revision excluded from --source-range. May be passed more than once.",
    )
    parser.add_argument("--start", type=int, default=1, help="1-based source-list start")
    parser.add_argument("--end", type=int, help="1-based source-list end")
    parser.add_argument("--first-parent", action="store_true")
    parser.add_argument("--reference-base", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-identifiers-per-commit", type=int, default=80)
    parser.add_argument("--include-markers", action="store_true")
    return parser.parse_args()


def git_bytes(cwd: Path, args: list[str], check: bool = True) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    ).stdout


def git_text(cwd: Path, args: list[str], check: bool = True) -> str:
    return git_bytes(cwd, args, check=check).decode("utf-8", errors="replace")


def rev_list(worktree: Path, base: str, tip: str, excludes: list[str], first_parent: bool) -> list[str]:
    args = ["rev-list", "--reverse"]
    if first_parent:
        args.append("--first-parent")
    args.append(f"{base}..{tip}")
    args.extend(f"^{exclude}" for exclude in excludes)
    text = git_text(worktree, args)
    return [line for line in text.splitlines() if line]


def source_commits(args: argparse.Namespace, worktree: Path) -> list[tuple[int, str]]:
    if args.source_list:
        commits = [line.strip() for line in args.source_list.read_text().splitlines() if line.strip()]
    else:
        base, tip = args.source_range
        commits = rev_list(worktree, base, tip, args.source_exclude, args.first_parent)

    end = args.end or len(commits)
    if args.start < 1 or end > len(commits) or args.start > end:
        raise SystemExit(f"invalid source slice {args.start}-{end} for {len(commits)} commits")
    return [(idx, commits[idx - 1]) for idx in range(args.start, end + 1)]


def added_paths_in_range(worktree: Path, base: str, tip: str) -> set[str]:
    text = git_text(worktree, ["diff", "--name-status", "--find-renames", base, tip])
    paths: set[str] = set()
    for line in text.splitlines():
        fields = line.split("\t")
        if not fields:
            continue
        status = fields[0]
        if status.startswith("A") and len(fields) >= 2:
            paths.add(fields[1])
        elif status.startswith("R") and len(fields) >= 3:
            paths.add(fields[2])
    return paths


def changed_paths_in_range(worktree: Path, base: str, tip: str) -> set[str]:
    text = git_text(worktree, ["diff", "--name-only", "--find-renames", base, tip])
    return {line for line in text.splitlines() if line}


def reference_identifiers(worktree: Path, base: str, tip: str) -> set[str]:
    identifiers: set[str] = set()
    proc = subprocess.Popen(
        ["git", "diff", "--no-color", base, tip],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if line.startswith("+") and not line.startswith("+++"):
            for token in commit_gate.IDENT_RE.findall(line):
                if commit_gate.interesting_identifier(token):
                    identifiers.add(token)
    _, stderr = proc.communicate()
    if proc.returncode != 0:
        raise SystemExit(stderr)

    for path in added_paths_in_range(worktree, base, tip):
        token = Path(path).stem
        if commit_gate.interesting_identifier(token):
            identifiers.add(token)
    return identifiers


def classify_match(
    diff_ids: list[str],
    message_ids: list[str],
    matched_diff: list[str],
    unmatched_diff: list[str],
    unmatched_message: list[str],
    matched_paths: list[str],
    matched_added_paths: list[str],
) -> str:
    if not diff_ids:
        return "no-diff-identifiers"
    if unmatched_diff and not matched_diff and not matched_paths and not matched_added_paths:
        return "needs-review"
    if unmatched_diff:
        return "partial-match-review"
    if unmatched_message:
        return "message-only-review"
    return "reference-present"


def source_record_from_parts_for_test(
    diff_identifiers: list[str],
    message_identifiers: list[str],
    changed_paths: list[str],
    added_paths: list[str],
    reference_identifiers: set[str],
    reference_changed_paths: set[str],
    reference_added_paths: set[str],
) -> str:
    matched_diff = [identifier for identifier in diff_identifiers if identifier in reference_identifiers]
    unmatched_diff = [identifier for identifier in diff_identifiers if identifier not in reference_identifiers]
    unmatched_message = [
        identifier for identifier in message_identifiers if identifier not in reference_identifiers
    ]
    matched_paths = [path for path in changed_paths if path in reference_changed_paths]
    matched_added_paths = [path for path in added_paths if path in reference_added_paths]
    return classify_match(
        diff_identifiers,
        message_identifiers,
        matched_diff,
        unmatched_diff,
        unmatched_message,
        matched_paths,
        matched_added_paths,
    )


def source_record(
    worktree: Path,
    idx: int,
    commit: str,
    reference_ids: set[str],
    reference_changed_paths: set[str],
    reference_added_paths: set[str],
    max_identifiers: int,
) -> dict:
    subject = commit_gate.source_subject(worktree, commit)
    paths = commit_gate.changed_paths(worktree, commit)
    added = commit_gate.added_paths(worktree, commit)
    records = commit_gate.extract_identifier_records(
        commit_gate.source_diff(worktree, commit),
        subject,
        commit_gate.source_body(worktree, commit),
        added,
        max_identifiers,
    )

    diff_ids = [record.identifier for record in records if commit_gate.has_diff_origin(record)]
    message_ids = [record.identifier for record in records if not commit_gate.has_diff_origin(record)]
    matched_diff = [identifier for identifier in diff_ids if identifier in reference_ids]
    unmatched_diff = [identifier for identifier in diff_ids if identifier not in reference_ids]
    matched_message = [identifier for identifier in message_ids if identifier in reference_ids]
    unmatched_message = [identifier for identifier in message_ids if identifier not in reference_ids]
    matched_paths = [path for path in paths if path in reference_changed_paths]
    matched_added_paths = [path for path in added if path in reference_added_paths]

    decision_hint = classify_match(
        diff_ids,
        message_ids,
        matched_diff,
        unmatched_diff,
        unmatched_message,
        matched_paths,
        matched_added_paths,
    )

    return {
        "index": idx,
        "commit": commit,
        "subject": subject,
        "changed_paths": paths,
        "added_paths": added,
        "identifier_origins": {record.identifier: record.origins for record in records},
        "diff_identifiers": diff_ids,
        "message_only_identifiers": message_ids,
        "matched_diff_identifiers": matched_diff,
        "unmatched_diff_identifiers": unmatched_diff,
        "matched_message_only_identifiers": matched_message,
        "unmatched_message_only_identifiers": unmatched_message,
        "matched_changed_paths": matched_paths,
        "matched_added_paths": matched_added_paths,
        "decision_hint": decision_hint,
    }


def main() -> int:
    args = parse_args()
    worktree = args.worktree.resolve()
    selected = source_commits(args, worktree)
    ref_commits = rev_list(worktree, args.reference_base, args.reference, [], True)
    ref_changed_paths = changed_paths_in_range(worktree, args.reference_base, args.reference)
    ref_added_paths = added_paths_in_range(worktree, args.reference_base, args.reference)
    ref_ids = reference_identifiers(worktree, args.reference_base, args.reference)

    records = []
    for idx, commit in selected:
        subject = commit_gate.source_subject(worktree, commit)
        if MARKER_RE.match(subject) and not args.include_markers:
            continue
        records.append(
            source_record(
                worktree,
                idx,
                commit,
                ref_ids,
                ref_changed_paths,
                ref_added_paths,
                args.max_identifiers_per_commit,
            )
        )

    summary = {
        "source_commit_count": len(selected),
        "audited_commit_count": len(records),
        "reference_commit_count": len(ref_commits),
        "reference_identifier_count": len(ref_ids),
        "reference_changed_path_count": len(ref_changed_paths),
        "reference_added_path_count": len(ref_added_paths),
        "decision_hint_counts": {},
    }
    for record in records:
        hint = record["decision_hint"]
        summary["decision_hint_counts"][hint] = summary["decision_hint_counts"].get(hint, 0) + 1

    evidence = {
        "inputs": {
            "source_list": str(args.source_list) if args.source_list else None,
            "source_range": args.source_range,
            "source_exclude": args.source_exclude,
            "source_start": args.start,
            "source_end": args.end,
            "first_parent": args.first_parent,
            "reference_base": args.reference_base,
            "reference": args.reference,
        },
        "summary": summary,
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

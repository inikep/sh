#!/usr/bin/env python3
"""Hunk-level conflict resolver: pick HEAD or theirs per conflict region by
overlap with REFERENCE.

For each `<<<<<<< / ||||||| / ======= / >>>>>>>` region in a file, the script
parses the HEAD side and the THEIRS side and picks whichever side's distinct
non-trivial lines have the highest overlap with the corresponding file on
REFERENCE. The chosen side replaces ONLY the conflict block; merged context
outside the markers is left untouched.

This is hunk-level transcription, not whole-file replacement. Per skill rule
HP-1, do not extend this script to copy whole files from REFERENCE.

Usage:
  ps_replay_resolve_hunks.py <reference-ref> <path> [<path>...]
  ps_replay_resolve_hunks.py <reference-ref> --all   # all files with markers

Exit codes:
  0  every conflict region was resolved
  1  one or more conflict regions remained unresolved (neither side overlaps
     reference enough to choose); those regions are left intact for manual
     review
  2  invocation error

Stop conditions (the caller must handle):
  * Files with `unresolved` regions still need manual hunk-level work using
    REFERENCE for inspection only (`git show $REF:<path>`, then a manual
    edit). Do not rerun this script with a different heuristic to "force" a
    resolution; that path slides toward whole-file replacement.
  * If the script's choice produces a build error later in the
    Build-Driven Fixes loop, treat the failure normally (Fold/Defer/Align/
    Remove) — the resolver's heuristic is best-effort, not authoritative.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def get_reference_text(reference: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{reference}:{path}"],
        text=True, capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def split_into_segments(text: str):
    """Split into [(kind, content)] where kind is 'merged' or 'conflict'."""
    lines = text.split("\n")
    segments = []
    i = 0
    cur: list[str] = []
    while i < len(lines):
        if lines[i].startswith("<<<<<<<"):
            if cur:
                segments.append(("merged", "\n".join(cur)))
                cur = []
            block = [lines[i]]
            i += 1
            while i < len(lines) and not lines[i].startswith(">>>>>>>"):
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])
                i += 1
            segments.append(("conflict", "\n".join(block)))
        else:
            cur.append(lines[i])
            i += 1
    if cur:
        segments.append(("merged", "\n".join(cur)))
    return segments


def parse_conflict_block(block: str):
    """Return (head_lines, parent_lines_or_None, theirs_lines).

    Supports both classic (no `|||||||`) and diff3-style conflict blocks.
    """
    lines = block.split("\n")
    body = lines[1:-1]
    head: list[str] = []
    parent: list[str] | None = None
    theirs: list[str] = []
    state = "head"
    for ln in body:
        if ln.startswith("|||||||"):
            parent = []
            state = "parent"
            continue
        if ln.startswith("======="):
            state = "theirs"
            continue
        if state == "head":
            head.append(ln)
        elif state == "parent":
            assert parent is not None
            parent.append(ln)
        else:
            theirs.append(ln)
    return head, parent, theirs


def overlap_score(side_lines, ref_lines_set):
    """Distinct non-trivial lines in `side_lines` that exist in
    `ref_lines_set`. Trivial lines (length < 4 after strip, blank) are not
    counted; duplicates within a side are deduped before scoring."""
    seen: set[str] = set()
    score = 0
    for ln in side_lines:
        s = ln.strip()
        if len(s) < 4:
            continue
        if s in seen:
            continue
        seen.add(s)
        if s in ref_lines_set:
            score += 1
    return score


def resolve_file(reference: str, path: str) -> tuple[int, int, int]:
    """Returns (segment_count, conflict_count, unresolved_count)."""
    p = Path(path)
    text = p.read_text()
    if "<<<<<<<" not in text:
        return (0, 0, 0)
    ref_text = get_reference_text(reference, path)
    if ref_text is None:
        ref_set: set[str] = set()
    else:
        ref_set = {ln.strip() for ln in ref_text.split("\n") if ln.strip()}

    segments = split_into_segments(text)
    n_conf = 0
    n_unresolved = 0
    out: list[str] = []
    for kind, content in segments:
        if kind == "merged":
            out.append(content)
            continue
        n_conf += 1
        head, _parent, theirs = parse_conflict_block(content)
        h_score = overlap_score(head, ref_set)
        t_score = overlap_score(theirs, ref_set)
        if h_score == 0 and t_score == 0:
            # Neither side overlaps reference. Leave the conflict block in
            # place for manual review; the caller must resolve hunk-level.
            out.append(content)
            n_unresolved += 1
        elif h_score >= t_score:
            # Tie-break: prefer HEAD on equal scores. HEAD already represents
            # the chosen-base content, so when both sides match reference
            # equally, we prefer to keep the existing tree intact.
            out.append("\n".join(head))
        else:
            out.append("\n".join(theirs))

    new_text = "\n".join(out)
    p.write_text(new_text)
    return (len(segments), n_conf, n_unresolved)


def files_with_markers(cwd: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "grep", "-l", "^<<<<<<<"],
        cwd=cwd, capture_output=True, text=True,
    )
    if proc.returncode not in (0, 1):
        return []
    return [ln for ln in proc.stdout.splitlines() if ln]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Auto-resolve cherry-pick conflict regions hunk-by-hunk by "
            "picking HEAD or theirs based on overlap with REFERENCE. "
            "Hunk-level only — never replaces whole files."
        )
    )
    parser.add_argument("reference", help="Reference branch or commit")
    parser.add_argument("paths", nargs="*", help="Files to resolve")
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Resolve every file in the current worktree that contains "
            "`<<<<<<<` markers."
        ),
    )
    args = parser.parse_args()

    if args.all and args.paths:
        print("--all is exclusive with explicit paths", file=sys.stderr)
        return 2
    if args.all:
        paths = files_with_markers(Path.cwd())
        if not paths:
            print("no files with conflict markers")
            return 0
    else:
        paths = args.paths

    if not paths:
        print("usage: ps_replay_resolve_hunks.py <reference> <path>... | --all",
              file=sys.stderr)
        return 2

    rc = 0
    for path in paths:
        try:
            _, n_conf, n_un = resolve_file(args.reference, path)
            print(f"{path}: {n_conf} conflict region(s), "
                  f"{n_un} left unresolved")
            if n_un:
                rc = 1
        except subprocess.CalledProcessError as e:
            print(f"{path}: ERROR {e}", file=sys.stderr)
            rc = 2
        except Exception as e:
            print(f"{path}: ERROR {e!r}", file=sys.stderr)
            rc = 2
    return rc


if __name__ == "__main__":
    sys.exit(main())

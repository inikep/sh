#!/usr/bin/env python3
"""Classify commits in a range as FOLLOWUP, NORMAL, or NORMAL_no_overlap.

A FOLLOWUP requires BOTH:
  (1) subject or body matches a follow-up keyword
  (2) the commit shares at least 3 paths with some chronologically prior commit
      in the range
The target carrier is the most recent prior commit that shares >=3 paths with
this commit (per the SKILL.md C(b) gate, which requires "at least 3 paths the
follow-up shares with the carrier").

Usage: follow-up-detect.py <git-range>
Output (TSV to stdout): <sha>\\t<status>\\t<target_or_->\\t<matched_keyword_or_->
"""
import re, subprocess, sys

if len(sys.argv) < 2:
    print("usage: follow-up-detect.py <git-range>", file=sys.stderr); sys.exit(2)

rng = sys.argv[1]
shas = subprocess.check_output(['git', 'rev-list', '--reverse', rng]).decode().split()

follow_up_kw = re.compile(
    r'\b('
    r'follow-?up|addendum|amend(?:ment|s)?|refresh|'
    r'fix(?:es)?\s+(?:test|the|for|up|main|the\s)|'
    r'fix(?:up)?\s+test|'
    r'tests?\s+for|'
    r'more\s+test\s+(?:suite\s+)?fixup|'
    r'test\s+suite\s+fixup|'
    r'porting\s+(?:to|fix|for)|'
    r'port\s+(?:fix|to)|'
    r'manually\s+merge|'
    r'(?:reverse-)?manual(?:ly)?\s+merge|'
    r'automerge|'
    r'merge\s+(?:fix|removal|subunit|build)|'
    r'rev(?:erse)?\s+manual'
    r')\b',
    re.I,
)

# Map sha -> set of paths
sha_paths = {}
for sha in shas:
    paths = subprocess.check_output(
        ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', sha]
    ).decode().split()
    sha_paths[sha] = set(paths)

for i, sha in enumerate(shas):
    msg = subprocess.check_output(['git', 'log', '-1', '--format=%s%n%b', sha]).decode()
    m = follow_up_kw.search(msg)
    if not m:
        print(f"{sha}\tNORMAL\t-\t-")
        continue
    paths = sha_paths[sha]
    target = None
    for j in range(i - 1, -1, -1):
        prev = shas[j]
        if len(sha_paths[prev] & paths) >= 3:
            target = prev
            break
    if target:
        print(f"{sha}\tFOLLOWUP\t{target}\t{m.group(1)}")
    else:
        print(f"{sha}\tNORMAL_no_overlap\t-\t{m.group(1)}")

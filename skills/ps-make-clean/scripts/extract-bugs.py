#!/usr/bin/env python3
"""Extract normalized "bug:N" tokens from each commit's subject+body.

Usage: extract-bugs.py <git-range>
Output (TSV to stdout): <sha>\\t<comma-sep tokens>
"""
import re, subprocess, sys

if len(sys.argv) < 2:
    print("usage: extract-bugs.py <git-range>", file=sys.stderr); sys.exit(2)

rng = sys.argv[1]
shas = subprocess.check_output(['git', 'rev-list', '--reverse', rng]).decode().split()

# Bug-number patterns. Numbers are 4-7 digits to filter out version strings.
bug_pat = re.compile(
    r'(?:'
    r'bugs?\.mysql\.com/bug\.php\?id=(\d{4,7})'
    r'|'
    r'(?:^|[^A-Za-z])[Bb]ug[s]?\s*#?\s*(\d{4,7})(?![0-9])'
    r'|'
    r'(?:^|[^A-Za-z])bug(\d{4,7})(?![0-9])'              # filename-style: bug933969.patch
    r'|'
    r'(?:^|[^A-Za-z])LP\s+bug\s+#?(\d{4,7})(?![0-9])'    # Launchpad
    r')'
)
multi_bug_pat = re.compile(r'(?:^|[^A-Za-z])[Bb]ugs?\s+(\d{4,7})\s+and\s+(\d{4,7})(?![0-9])')

for sha in shas:
    msg = subprocess.check_output(['git', 'log', '-1', '--format=%s%n%b', sha]).decode()
    tokens = set()
    for m in bug_pat.finditer(msg):
        for g in m.groups():
            if g: tokens.add(f"bug:{g}")
    for m in multi_bug_pat.finditer(msg):
        tokens.add(f"bug:{m.group(1)}")
        tokens.add(f"bug:{m.group(2)}")
    print(f"{sha}\t{','.join(sorted(tokens))}")

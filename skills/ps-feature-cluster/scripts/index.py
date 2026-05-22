#!/usr/bin/env python3
"""Phase 1 — index commits in $BASE_BRANCH..$TIP_BRANCH and extract per-file hunk ranges.

Output: $WORK_DIR/commits.json — list of:
  { idx, sha, short, subj, body, files: { path: { pre: [[a,b],..], post: [[c,d],..],
                                                  binary: bool, new: bool, deleted: bool } } }
"""
import json, re, sys
from _common import BASE, TIP, WORK, sh, strip_subject_markers

HUNK_RE = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
DIFF_RE = re.compile(r'^diff --git a/(.*?) b/(.*?)$')

chrono = sh('rev-list', '--reverse', f'{BASE}..{TIP}').stdout.split()
print(f"commits: {len(chrono)}", file=sys.stderr)

commits = []
for i, sha in enumerate(chrono, 1):
    raw_subj = sh('log', '-1', '--format=%s', sha).stdout.strip()
    subj = strip_subject_markers(raw_subj)
    body = sh('log', '-1', '--format=%B', sha).stdout
    body = body[len(raw_subj):].lstrip('\n') if body.startswith(raw_subj) else body
    raw = sh('show', '--no-renames', '--format=', '-U0', sha).stdout
    files = {}
    cur = None
    for line in raw.splitlines():
        m = DIFF_RE.match(line)
        if m:
            cur = m.group(1)
            files[cur] = {'pre': [], 'post': [], 'binary': False, 'new': False, 'deleted': False}
            continue
        if cur is None:
            continue
        if line.startswith('Binary files'):
            files[cur]['binary'] = True
            continue
        if line.startswith('new file mode'):
            files[cur]['new'] = True
            continue
        if line.startswith('deleted file mode'):
            files[cur]['deleted'] = True
            continue
        m = HUNK_RE.match(line)
        if m:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) is not None else 1
            c = int(m.group(3))
            d = int(m.group(4)) if m.group(4) is not None else 1
            files[cur]['pre'].append([a, a + b])
            files[cur]['post'].append([c, c + d])
    commits.append({
        'idx': i,
        'sha': sha,
        'short': sha[:11],
        'raw_subj': raw_subj,
        'subj': subj,
        'body': body,
        'files': files,
    })

json.dump(commits, open(f'{WORK}/commits.json', 'w'), indent=1)
print(f"wrote {WORK}/commits.json", file=sys.stderr)

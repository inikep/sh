#!/usr/bin/env python3
"""Phase 5.5 — inverse-diff replacement/revert candidates + DAG movability.

This is a read-only companion signal for feature clustering.  It finds pairs
where a later commit deletes lines added by an earlier commit, or re-adds lines
deleted by an earlier commit.  That pattern is common for "feature imported,
then corrected/replaced/reverted in follow-up" histories.

Outputs:
  $WORK_DIR/replacements.json
  $WORK_DIR/replacements.tsv
  $WORK_DIR/replacement-candidates.md
"""
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from _common import WORK, commit_subject

MIN_SCORE = int(os.environ.get('REPLACEMENT_MIN_SCORE', '3'))
MAX_REPORT = int(os.environ.get('REPLACEMENT_MAX_REPORT', '50'))

commits = json.load(open(f'{WORK}/commits.json'))
idx2c = {c['idx']: c for c in commits}

NOISE_LINES = {
    '{', '}', '};', ');', '(', ')', 'break;', 'return;', 'return false;',
    'return true;', 'return(FALSE);', 'return(TRUE);'
}
SKIP_PREFIXES = (
    'index ', 'new file ', 'deleted file ', 'similarity ', 'rename ',
    '--- ', '+++ ', '@@ ', 'Binary files ',
)

def norm_line(s):
    s = s.strip()
    # Collapse whitespace but preserve token order.  Exact line matching after
    # normalization is intentionally conservative: it avoids fuzzy false
    # positives while catching most mechanical replacement/revert edits.
    s = re.sub(r'\s+', ' ', s)
    if len(s) < 8 or s in NOISE_LINES:
        return ''
    if s.startswith(('/*', '*', '//')) and len(s) < 24:
        return ''
    return s

def patch_lines(sha):
    out = subprocess.run(
        ['git', 'show', '--format=', '--no-ext-diff', '--no-renames', '-U0', sha],
        text=True, capture_output=True, errors='replace', check=True
    ).stdout
    path = None
    adds = defaultdict(list)
    dels = defaultdict(list)
    for line in out.splitlines():
        if line.startswith('diff --git '):
            m = re.match(r'diff --git a/(.*?) b/(.*)$', line)
            path = m.group(2) if m else None
            continue
        if path is None or line.startswith(SKIP_PREFIXES):
            continue
        if line.startswith('+') and not line.startswith('+++'):
            s = norm_line(line[1:])
            if s:
                adds[path].append(s)
        elif line.startswith('-') and not line.startswith('---'):
            s = norm_line(line[1:])
            if s:
                dels[path].append(s)
    return adds, dels

parsed = {}
for c in commits:
    parsed[c['idx']] = patch_lines(c['sha'])

graph_path = f'{WORK}/dep-graph.json'
graph = json.load(open(graph_path)) if os.path.exists(graph_path) else {'adj': {}, 'radj': {}}
adj = {int(k): set(v) for k, v in graph.get('adj', {}).items()}
radj = {int(k): set(v) for k, v in graph.get('radj', {}).items()}

def ancestors_between(n, lower):
    seen = set()
    stack = list(radj.get(n, ()))
    while stack:
        x = stack.pop()
        if x in seen or x <= lower:
            continue
        seen.add(x)
        stack.extend(radj.get(x, ()))
    return sorted(seen)

def descendants_between(n, upper):
    seen = set()
    stack = list(adj.get(n, ()))
    while stack:
        x = stack.pop()
        if x in seen or x >= upper:
            continue
        seen.add(x)
        stack.extend(adj.get(x, ()))
    return sorted(seen)

def movability(a, b):
    if b == a + 1:
        return 'adjacent', [], []
    blockers_up = ancestors_between(b, a)
    blockers_down = descendants_between(a, b)
    if not blockers_up:
        return 'move-member-up', [], blockers_down
    if not blockers_down:
        return 'move-carrier-down', blockers_up, []
    return 'blocked', blockers_up, blockers_down

rows = []
for ia, a in enumerate(commits):
    a_idx = a['idx']
    a_add, a_del = parsed[a_idx]
    for b in commits[ia + 1:]:
        b_idx = b['idx']
        b_add, b_del = parsed[b_idx]
        details = []
        score = 0
        delete_added_total = 0
        readd_deleted_total = 0
        for path in sorted(set(a_add) | set(a_del) | set(b_add) | set(b_del)):
            delete_added = sum((Counter(a_add.get(path, [])) & Counter(b_del.get(path, []))).values())
            readd_deleted = sum((Counter(a_del.get(path, [])) & Counter(b_add.get(path, []))).values())
            if not delete_added and not readd_deleted:
                continue
            score += delete_added + readd_deleted
            delete_added_total += delete_added
            readd_deleted_total += readd_deleted
            details.append({
                'path': path,
                'deletes_earlier_adds': delete_added,
                'readds_earlier_deletes': readd_deleted,
            })
        if score < MIN_SCORE:
            continue
        strategy, blockers_up, blockers_down = movability(a_idx, b_idx)
        rows.append({
            'score': score,
            'carrier': a_idx,
            'member': b_idx,
            'carrier_sha': a['sha'],
            'member_sha': b['sha'],
            'carrier_short': a['short'],
            'member_short': b['short'],
            'carrier_subject': commit_subject(a),
            'member_subject': commit_subject(b),
            'deletes_earlier_adds': delete_added_total,
            'readds_earlier_deletes': readd_deleted_total,
            'strategy': strategy,
            'blockers_up': blockers_up,
            'blockers_down': blockers_down,
            'paths': details,
        })

rows.sort(key=lambda r: (-r['score'], r['carrier'], r['member']))
json.dump(rows, open(f'{WORK}/replacements.json', 'w'), indent=1)

with open(f'{WORK}/replacements.tsv', 'w') as f:
    f.write('score\tcarrier\tmember\tstrategy\tdeletes_earlier_adds\treadds_earlier_deletes\tpaths\tcarrier_subject\tmember_subject\n')
    for r in rows:
        paths = ','.join(d['path'] for d in r['paths'][:8])
        f.write(
            f"{r['score']}\t{r['carrier']}\t{r['member']}\t{r['strategy']}\t"
            f"{r['deletes_earlier_adds']}\t{r['readds_earlier_deletes']}\t{paths}\t"
            f"{r['carrier_subject']}\t{r['member_subject']}\n")

with open(f'{WORK}/replacement-candidates.md', 'w') as f:
    f.write("# Inverse-diff replacement/revert candidates\n\n")
    f.write(f"Minimum score: `{MIN_SCORE}`. Score is exact normalized line matches where a later commit deletes an earlier addition or re-adds an earlier deletion.\n\n")
    f.write("| rank | score | pair | movability | inverse signal | subjects |\n")
    f.write("| --- | ---: | --- | --- | --- | --- |\n")
    for rank, r in enumerate(rows[:MAX_REPORT], 1):
        inv = f"-added:{r['deletes_earlier_adds']} +deleted:{r['readds_earlier_deletes']}"
        pair = f"{r['carrier']}→{r['member']} `{r['carrier_short']}`→`{r['member_short']}`"
        subj = (r['carrier_subject'][:55] + " / " + r['member_subject'][:55]).replace('|', '\\|')
        f.write(f"| {rank} | {r['score']} | {pair} | {r['strategy']} | {inv} | {subj} |\n")

print(f"wrote {WORK}/replacements.json ({len(rows)} candidates)", file=os.sys.stderr)
print(f"wrote {WORK}/replacements.tsv and replacement-candidates.md", file=os.sys.stderr)

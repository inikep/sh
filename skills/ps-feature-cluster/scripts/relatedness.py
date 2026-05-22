#!/usr/bin/env python3
"""Phase 5 — combine four signals into per-pair edge weights.

Signals (per pair (A, B)):
  hunk_w   = sum of overlap line-counts from dep-edges.tsv
  file_w   = TF-IDF-weighted shared-file count
  tok_w    = shared bug/lp/mdev/cve/patch/bp tokens from subj+body
  sym_w    = weight column from symbol-edges.tsv

Combined: w = log1p(hunk_w)*3 + file_w*1.5 + tok_w*8 + sym_w*0.5

Output: $WORK_DIR/relatedness-edges.tsv with columns
  a_idx  b_idx  w  hunk_w  file_w  tok_w  sym_w  shared_tokens  shared_paths_sample
"""
import json, math, re, sys
from collections import defaultdict, Counter
from _common import WORK, commit_subject

commits = json.load(open(f'{WORK}/commits.json'))
N = len(commits)
idx2c = {c['idx']: c for c in commits}

# --- hunk overlap ---
def span_len(s):
    if '-' not in s:
        return 1
    a, b = s.split('-')
    try:
        return max(1, int(b) - int(a) + 1)
    except ValueError:
        return 1

hunk_w = defaultdict(int)
hunk_paths = defaultdict(set)
with open(f'{WORK}/dep-edges.tsv') as fh:
    next(fh)
    for line in fh:
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 5:
            continue
        a, b, path, a_post, b_pre = parts[:5]
        a, b = int(a), int(b)
        key = (min(a, b), max(a, b))
        hunk_w[key] += min(span_len(a_post), span_len(b_pre))
        hunk_paths[key].add(path)

# --- TF-IDF shared files ---
files_of = {c['idx']: set(c.get('files', {}).keys()) for c in commits}
file_freq = Counter()
for fa in files_of.values():
    for p in fa:
        file_freq[p] += 1
def file_idf(p):
    return math.log(N / file_freq[p]) if file_freq[p] > 0 else 0.0

file_w = {}
shared_paths = {}
for a in range(1, N + 1):
    fa = files_of.get(a, set())
    if not fa:
        continue
    for b in range(a + 1, N + 1):
        fb = files_of.get(b, set())
        if not fb:
            continue
        common = fa & fb
        if not common:
            continue
        w = sum(file_idf(p) for p in common)
        if w > 0:
            file_w[(a, b)] = w
            shared_paths[(a, b)] = sorted(common)

# --- tokens ---
TOK_RES = [
    (re.compile(r'\bbug[\s#:]*(\d{3,7})\b', re.I), 'bug'),
    (re.compile(r'\blp[:\s]*(\d{3,8})\b', re.I), 'lp'),
    (re.compile(r'\bmdev[\s-]*(\d{2,6})\b', re.I), 'mdev'),
    (re.compile(r'\bcve-(\d{4}-\d{3,5})\b', re.I), 'cve'),
    (re.compile(r'Import\s+([a-zA-Z0-9_]+)\.patch', re.I), 'patch'),
    (re.compile(r'([a-zA-Z0-9_]+)\.patch', re.I), 'patch'),
    (re.compile(r'\+spec/([a-z0-9-]+)', re.I), 'bp'),
]
def tokens_of(c):
    text = (commit_subject(c) + '\n' + c.get('body', ''))
    toks = set()
    for rx, ns in TOK_RES:
        for m in rx.finditer(text):
            toks.add(f"{ns}:{m.group(1).lower()}")
    return toks
c_tokens = {c['idx']: tokens_of(c) for c in commits}

tok_w = {}
shared_tokens = {}
for a in range(1, N + 1):
    ta = c_tokens.get(a, set())
    if not ta:
        continue
    for b in range(a + 1, N + 1):
        tb = c_tokens.get(b, set())
        common = ta & tb
        if common:
            tok_w[(a, b)] = len(common)
            shared_tokens[(a, b)] = sorted(common)

# --- symbol edges ---
sym_w_all = {}
with open(f'{WORK}/symbol-edges.tsv') as fh:
    next(fh)
    for line in fh:
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 9:
            continue
        a, b = int(parts[0]), int(parts[1])
        w = int(parts[7])
        sym_w_all[(min(a, b), max(a, b))] = w

# --- combine ---
with open(f'{WORK}/relatedness-edges.tsv', 'w') as out:
    out.write("a_idx\tb_idx\tw\thunk_w\tfile_w\ttok_w\tsym_w\tshared_tokens\tshared_paths_sample\n")
    for a in range(1, N + 1):
        for b in range(a + 1, N + 1):
            key = (a, b)
            h = hunk_w.get(key, 0)
            f = file_w.get(key, 0.0)
            t = tok_w.get(key, 0)
            s = sym_w_all.get(key, 0)
            if h == 0 and f == 0 and t == 0 and s == 0:
                continue
            w = math.log1p(h) * 3 + f * 1.5 + t * 8 + s * 0.5
            sp = ','.join(sorted(shared_paths.get(key, []))[:3])
            st = ','.join(shared_tokens.get(key, []))
            out.write(f"{a}\t{b}\t{w:.3f}\t{h}\t{f:.2f}\t{t}\t{s}\t{st}\t{sp}\n")
print(f"wrote {WORK}/relatedness-edges.tsv", file=sys.stderr)

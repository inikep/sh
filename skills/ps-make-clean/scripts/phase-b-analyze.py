#!/usr/bin/env python3
"""Phase B analysis: classify commits as large / small-with-C++ (kept-printed) /
small-without-C++ (squash candidate). Compute prev-modifier (most recent prior
commit with same-path overlap) for each squash candidate.

NOTE: use `git show --shortstat --format=` and `git show --name-only --format=`
SEPARATELY. The combined form `--shortstat --name-only --format=` suppresses
the shortstat line.

Inputs (env): LOG_DIR, BASE_BRANCH, OUTPUT_BRANCH (post-Phase-B branch).
Writes $LOG_DIR/phase-b-plan.json.
"""
import os, re, json, subprocess

CPP_EXT = ('.h', '.c', '.cc', '.cxx', '.cpp', '.hh', '.hpp', '.hxx')

LOG  = os.environ['LOG_DIR']
BASE = os.environ['BASE_BRANCH']
OUT  = os.environ['OUTPUT_BRANCH']

chrono = subprocess.check_output(['git','rev-list','--reverse', f'{BASE}..{OUT}']).decode().split()

paths = {}; diff_lines = {}
for sha in chrono:
    ps = subprocess.check_output(['git','show','--name-only','--format=', sha]).decode().strip().splitlines()
    paths[sha] = set(p for p in ps if p)
    ss = subprocess.check_output(['git','show','--shortstat','--format=', sha]).decode().strip()
    ins = dels = 0
    m = re.search(r'(\d+) insertion', ss); ins  = int(m.group(1)) if m else 0
    m = re.search(r'(\d+) deletion',  ss); dels = int(m.group(1)) if m else 0
    diff_lines[sha] = ins + dels

small_cpp = []; small_nocpp = []; large = []
for sha in chrono:
    n = diff_lines[sha]
    has_cpp = any(p.endswith(CPP_EXT) for p in paths[sha])
    if n <= 8:
        (small_cpp if has_cpp else small_nocpp).append(sha)
    else:
        large.append(sha)

# prev_modifier for each small_nocpp
prev_mod = {}
for sha in small_nocpp:
    idx = chrono.index(sha)
    tgt = None
    for j in range(idx - 1, -1, -1):
        if paths[chrono[j]] & paths[sha]:
            tgt = chrono[j]; break
    prev_mod[sha] = tgt

squash = {s: t for s, t in prev_mod.items() if t}
orphan = [s for s, t in prev_mod.items() if not t]

with open(os.path.join(LOG, 'phase-b-plan.json'), 'w') as f:
    json.dump({
        'chrono': chrono,
        'small_cpp_kept': small_cpp,
        'small_nocpp_squash': squash,
        'small_nocpp_keep_orphan': orphan,
        'paths': {s: list(p) for s,p in paths.items()},
        'diff_lines': diff_lines,
    }, f, indent=2)

print(f"Total: {len(chrono)}")
print(f"  large (>8 lines): {len(large)}")
print(f"  small with C/C++ (kept-printed): {len(small_cpp)}")
print(f"  small no-C++ (candidates): {len(small_nocpp)}  squashable: {len(squash)}  orphan: {len(orphan)}")

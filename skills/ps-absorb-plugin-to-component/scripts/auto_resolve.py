#!/usr/bin/env python3
"""Region-level resolver for backchain.py conflicts (diff3 output: component | plugin-after | plugin-before).

For each conflict region the toucher's reverse change is base(plugin-after) -> theirs(plugin-before).
It is replayed on ours(component) when every line it needs can be located unambiguously:
  * replace/delete: the base lines of the edit must occur in ours exactly once, verbatim or after
    the conversion substitutions S (--subs module with  subs(line) -> line);
  * insert: the insertion is placed after the (substituted) base line preceding it, or before the
    following one, when that anchor line occurs exactly once in ours.
Inserted/replacement lines are passed through S as well.
A file is written to OUT only if every region resolved; otherwise it is listed as manual.

usage: auto_resolve.py --conflicts DIR/<sha> --out RES/<sha> [--subs subs.py] [--report FILE]
"""
import argparse, difflib, importlib.util, os, sys

ap = argparse.ArgumentParser()
ap.add_argument('--conflicts', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--subs')
ap.add_argument('--report')
a = ap.parse_args()
S = lambda l: l
if a.subs:
    sp = importlib.util.spec_from_file_location('subs', a.subs); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); S = m.subs

def find_unique(hay, needle):
    hits = [i for i in range(len(hay) - len(needle) + 1) if hay[i:i + len(needle)] == needle]
    return hits[0] if len(hits) == 1 else None

def locate(ours, lines):
    if not lines:
        return None
    for cand in (lines, [S(l) for l in lines]):
        i = find_unique(ours, cand)
        if i is not None:
            return i, len(cand)
    return None

def resolve_region(o, b, t):
    ours = list(o)
    sm = difflib.SequenceMatcher(a=b, b=t, autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != 'equal']
    # apply from the end so earlier indexes stay valid
    for tag, i1, i2, j1, j2 in reversed(ops):
        new = [S(l) for l in t[j1:j2]]
        if tag in ('replace', 'delete'):
            loc = locate(ours, b[i1:i2])
            if loc is None:
                return None
            k, n = loc
            ours[k:k + n] = new
        else:  # insert
            placed = False
            if i1 > 0:
                loc = locate(ours, [b[i1 - 1]])
                if loc is not None:
                    k = loc[0] + 1; ours[k:k] = new; placed = True
            if not placed and i1 < len(b):
                loc = locate(ours, [b[i1]])
                if loc is not None:
                    k = loc[0]; ours[k:k] = new; placed = True
            if not placed and not b:           # region had no base lines at all
                ours = ours + new; placed = True
            if not placed:
                return None
    return ours

manual = []; done = 0
for root, _, files in os.walk(a.conflicts):
    for fn in files:
        src = os.path.join(root, fn); rel = os.path.relpath(src, a.conflicts)
        L = open(src, encoding='utf-8', errors='surrogateescape').read().split('\n')
        out = []; i = 0; ok = True
        while i < len(L):
            if L[i].startswith('<<<<<<< '):
                o = []; b = []; t = []; cur = o; i += 1
                while not L[i].startswith('>>>>>>> '):
                    if L[i].startswith('||||||| '): cur = b
                    elif L[i] == '=======': cur = t
                    else: cur.append(L[i])
                    i += 1
                r = resolve_region(o, b, t)
                if r is None:
                    ok = False; break
                out += r; i += 1; continue
            out.append(L[i]); i += 1
        if ok:
            dst = os.path.join(a.out, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'w', encoding='utf-8', errors='surrogateescape').write('\n'.join(out)); done += 1
        else:
            manual.append(rel)
if a.report:
    open(a.report, 'w').write('\n'.join(sorted(manual)) + ('\n' if manual else ''))
print(f'auto-resolved {done}, manual {len(manual)}')

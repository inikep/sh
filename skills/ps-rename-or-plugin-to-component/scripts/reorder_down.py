#!/usr/bin/env python3
"""Move commit A to right after commit K (A < K) in a linear range, by plumbing.

For each commit c in (A, K]: new tree = tree(c) with A's change reverted
(git merge-tree --merge-base=A c A^). A' = A's change applied on top of K'
(merge-tree --merge-base=A^ K' A); tree(A') must equal tree(K). Later commits
keep their trees. Raw commit objects are rewritten (messages, author, committer kept).
usage: reorder_down.py BASE HEAD A K   -> prints new tip and the new SHA of A
"""
import subprocess, sys

def git(*a, inp=None, ok=(0,)):
    r = subprocess.run(['git', *a], input=inp, capture_output=True)
    if r.returncode not in ok:
        sys.exit(f"git {' '.join(a)} failed: {r.stderr.decode()}{r.stdout.decode()[:2000]}")
    return r.stdout

rev = lambda x: git('rev-parse', x).decode().strip()
base, head, A, K = (rev(x) for x in sys.argv[1:5])
commits = git('rev-list', '--reverse', f'{base}..{head}').decode().split()
ia, ik = commits.index(A), commits.index(K)
assert ia < ik

def parse(c):
    h, _, msg = git('cat-file', 'commit', c).partition(b'\n\n')
    return h.split(b'\n'), msg

def mk(c, tree, parent):
    hl, msg = parse(c)
    nh = [(b'tree ' + tree.encode()) if l.startswith(b'tree ') else
          (b'parent ' + parent.encode()) if l.startswith(b'parent ') else l for l in hl]
    return git('hash-object', '-t', 'commit', '-w', '--stdin', inp=b'\n'.join(nh) + b'\n\n' + msg).decode().strip()

def mtree(mb, x, y):
    out = git('merge-tree', '--write-tree', '--merge-base=' + mb, x, y, ok=(0, 1))
    first = out.decode().split('\n')[0]
    if out.decode().count('\n') > 1 and 'CONFLICT' in out.decode():
        sys.exit(f'conflict merging {x[:12]} {y[:12]} base {mb[:12]}:\n{out.decode()[:3000]}')
    return first

tip = commits[ia - 1]
for c in commits[ia + 1:ik + 1]:
    t = mtree(A, c, A + '^')
    tip = mk(c, t, tip)
ta = mtree(A + '^', tip, A)
if ta != rev(K + '^{tree}'):
    sys.exit('A applied on K\' does not reproduce tree(K)')
tip = newA = mk(A, ta, tip)
for c in commits[ik + 1:]:
    tip = mk(c, rev(c + '^{tree}'), tip)
print(tip)
print('A ->', newA)

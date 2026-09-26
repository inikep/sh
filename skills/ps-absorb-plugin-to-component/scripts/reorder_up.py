#!/usr/bin/env python3
"""Move commit P to right before commit Q (Q < P) in a linear range, by plumbing.
P' = P's change applied on Q^ (merge-tree --merge-base=P^ Q^ P). For each c in [Q, P):
tree(c') = merge-tree --merge-base=P^ c P  (c with P's change). tree(last c') must equal tree(P).
Commits after P keep their trees. Aborts on any conflict.
usage: reorder_up.py BASE HEAD Q P   -> prints new tip and new SHA of P
"""
import subprocess, sys
def git(*a, inp=None, ok=(0,)):
    r = subprocess.run(['git', *a], input=inp, capture_output=True)
    if r.returncode not in ok:
        sys.exit(f"git {' '.join(a)} failed: {r.stderr.decode()}{r.stdout.decode()[:3000]}")
    return r.stdout
rev = lambda x: git('rev-parse', x).decode().strip()
base, head, Q, P = (rev(x) for x in sys.argv[1:5])
commits = git('rev-list', '--reverse', f'{base}..{head}').decode().split()
iq, ip = commits.index(Q), commits.index(P)
assert iq < ip
def mk(c, tree, parent):
    h, _, msg = git('cat-file', 'commit', c).partition(b'\n\n')
    nh = [(b'tree ' + tree.encode()) if l.startswith(b'tree ') else
          (b'parent ' + parent.encode()) if l.startswith(b'parent ') else l for l in h.split(b'\n')]
    return git('hash-object', '-t', 'commit', '-w', '--stdin', inp=b'\n'.join(nh) + b'\n\n' + msg).decode().strip()
def mtree(mb, x, y, what):
    r = subprocess.run(['git', 'merge-tree', '--write-tree', '--no-messages', '--merge-base=' + mb, x, y], capture_output=True)
    if r.returncode != 0:
        sys.exit(f'conflict at {what}:\n{r.stdout.decode()[:3000]}')
    return r.stdout.decode().split('\n')[0]
tip = newP = mk(P, mtree(P + '^', Q + '^', P, 'P onto Q^'), commits[iq - 1])
for c in commits[iq:ip]:
    tip = mk(c, mtree(P + '^', c, P, c[:12]), tip)
if rev(tip + '^{tree}') != rev(P + '^{tree}'):
    sys.exit('moved range does not end at tree(P)')
for c in commits[ip + 1:]:
    tip = mk(c, rev(c + '^{tree}'), tip)
print(tip); print('P ->', newP)

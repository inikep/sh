#!/usr/bin/env python3
"""fold_line.py BASE HEAD FROM UNTIL PATH ANCHOR LINE
For commits in [FROM, UNTIL): insert LINE after ANCHOR in PATH if absent. UNTIL's tree must be
unchanged (it already has the line). Later commits keep trees; raw objects rewritten. Prints new tip."""
import subprocess, sys, os, tempfile
def git(*a, inp=None, env=None):
    r = subprocess.run(['git', *a], input=inp, capture_output=True, env=env)
    if r.returncode: sys.exit(f"git {' '.join(a)} failed: {r.stderr.decode()}")
    return r.stdout
rev = lambda x: git('rev-parse', x).decode().strip()
base, head, frm, until, path, anchor, line = sys.argv[1:8]
anchor += '\n'; line += '\n'
commits = git('rev-list', '--reverse', f'{base}..{head}').decode().split()
i0, i1 = commits.index(rev(frm)), commits.index(rev(until))
env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tempfile.mkdtemp(), 'index'))
newmap = {}; tip = commits[i0 - 1]
for i, c in enumerate(commits[i0:], i0):
    h, _, msg = git('cat-file', 'commit', c).partition(b'\n\n'); hl = h.split(b'\n')
    tree = rev(c + '^{tree}')
    if i < i1:
        git('read-tree', tree, env=env)
        mode, blob = git('ls-files', '-s', '--', path, env=env).decode().split()[:2]
        s = git('cat-file', 'blob', blob).decode('utf-8', 'surrogateescape')
        if line not in s:
            if s.count(anchor) != 1: sys.exit(f'anchor count {s.count(anchor)} at {c[:12]}')
            s = s.replace(anchor, anchor + line)
            nb = git('hash-object', '-w', '--stdin', inp=s.encode('utf-8', 'surrogateescape')).decode().strip()
            git('update-index', '--cacheinfo', f'{mode},{nb},{path}', env=env)
            tree = git('write-tree', env=env).decode().strip()
    nh = [(b'tree ' + tree.encode()) if l.startswith(b'tree ') else (b'parent ' + tip.encode()) if l.startswith(b'parent ') else l for l in hl]
    tip = git('hash-object', '-t', 'commit', '-w', '--stdin', inp=b'\n'.join(nh) + b'\n\n' + msg).decode().strip()
    if i == i1: assert tree == rev(c + '^{tree}')
print(tip)

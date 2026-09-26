#!/usr/bin/env python3
"""fold_edits.py BASE HEAD FROM UNTIL PATH EDITS.py [NOTE]
Fold hunks that a later commit UNTIL introduces back into FROM: for every commit in [FROM, UNTIL),
apply EDITS (a python file defining EDITS = [(old, new), ...]) to PATH. An edit is skipped where
`new` is already present, otherwise `old` must occur exactly once. UNTIL's tree must come out
unchanged (it already has the hunks), so later trees are untouched and UNTIL just stops adding
them. Raw commit objects are rewritten; NOTE, if given, is appended to FROM's message as a new
paragraph. Prints the new tip. (fold_line.py is the one-line special case.)"""
import importlib.util, os, subprocess, sys, tempfile
def git(*a, inp=None, env=None):
    r = subprocess.run(['git', *a], input=inp, capture_output=True, env=env)
    if r.returncode: sys.exit(f"git {' '.join(a)} failed: {r.stderr.decode()}")
    return r.stdout
rev = lambda x: git('rev-parse', x).decode().strip()
base, head, frm, until, path, edits_file = sys.argv[1:7]
note = sys.argv[7] if len(sys.argv) > 7 else None
sp = importlib.util.spec_from_file_location('edits', edits_file); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
commits = git('rev-list', '--reverse', f'{base}..{head}').decode().split()
i0, i1 = commits.index(rev(frm)), commits.index(rev(until))
env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tempfile.mkdtemp(), 'index'))
cache = {}
tip = commits[i0 - 1]
for i, c in enumerate(commits[i0:], i0):
    h, _, msg = git('cat-file', 'commit', c).partition(b'\n\n'); hl = h.split(b'\n')
    tree = rev(c + '^{tree}')
    if i < i1:
        git('read-tree', tree, env=env)
        mode, blob = git('ls-files', '-s', '--', path, env=env).decode().split()[:2]
        if blob not in cache:
            s = git('cat-file', 'blob', blob).decode('utf-8', 'surrogateescape')
            for old, new in m.EDITS:
                if new in s:
                    continue
                if s.count(old) != 1:
                    sys.exit(f'{c[:12]}: expected 1 x {old[:70]!r}, found {s.count(old)}')
                s = s.replace(old, new)
            cache[blob] = git('hash-object', '-w', '--stdin', inp=s.encode('utf-8', 'surrogateescape')).decode().strip()
        git('update-index', '--cacheinfo', f'{mode},{cache[blob]},{path}', env=env)
        tree = git('write-tree', env=env).decode().strip()
    if i == i1 and tree != rev(c + '^{tree}'):
        sys.exit('UNTIL tree changed')
    if note and i == i0:
        msg = msg.rstrip(b'\n') + b'\n\n' + note.encode() + b'\n'
    nh = [(b'tree ' + tree.encode()) if l.startswith(b'tree ') else (b'parent ' + tip.encode()) if l.startswith(b'parent ') else l for l in hl]
    tip = git('hash-object', '-t', 'commit', '-w', '--stdin', inp=b'\n'.join(nh) + b'\n\n' + msg).decode().strip()
print(tip)

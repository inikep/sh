#!/usr/bin/env python3
"""Plumbing history rewrite for absorbing a conversion commit into earlier commits.

Walks BASE..HEAD (must be linear). For every commit from --start (inclusive) up to
--drop (exclusive) it:
  * moves paths (--move OLD=NEW, same blob and mode), and
  * rewrites file contents with transform programs (--transform PATH=PROG [ARGS...]):
    PROG reads the blob on stdin and writes the new blob on stdout; env COMMIT is the
    original commit SHA. Transforms run on the NEW path (after moves).
  * adds files (--add PATH=REV:PATH or PATH=BLOB): created if absent; if already present
    it must hold exactly that blob (otherwise the rewrite aborts).
Any --move/--transform/--add value may end with @REV to start that operation at REV
instead of --start (REV must lie in [--start, --drop)).
The --drop commit must become a no-op on its rewritten parent (asserted) and is removed.
Commits after --drop keep their trees; only parent lines change. Commit objects are
rewritten raw: messages, author, committer and all other headers stay byte-identical.
--append-msg-to SHA appends the dropped commit's message to that commit after a
'==========================================' line.

Trees are rebuilt by splicing only the touched directories (treeedit.py), so the cost
scales with the number of edited paths, not with the size of the tree.

Prints the new tip SHA and a map of selected commits. Does not move any ref.
"""
import argparse, os, shlex, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from treeedit import ls_paths, edit_tree

def git(*a, inp=None, env=None):
    r = subprocess.run(['git', *a], input=inp, capture_output=True, env=env)
    if r.returncode:
        sys.exit(f"git {' '.join(a)} failed: {r.stderr.decode()}")
    return r.stdout

def rev(x):
    return git('rev-parse', x).decode().strip()

ap = argparse.ArgumentParser()
ap.add_argument('--base', required=True)
ap.add_argument('--head', default='HEAD')
ap.add_argument('--start', required=True, help='first commit to rewrite (introduction)')
ap.add_argument('--drop', required=True, help='conversion commit to remove')
ap.add_argument('--move', action='append', default=[], help='OLD=NEW')
ap.add_argument('--transform', action='append', default=[], help="PATH=PROG [ARGS][@REV]")
ap.add_argument('--add', action='append', default=[], help='PATH=REV:PATH|BLOB[@REV]')
ap.add_argument('--append-msg-to')
ap.add_argument('--show', action='append', default=[], help='print new SHA for these commits')
a = ap.parse_args()

commits = git('rev-list', '--reverse', f'{a.base}..{a.head}').decode().split()
if git('rev-list', '--merges', f'{a.base}..{a.head}').strip():
    sys.exit('range contains merge commits; this tool handles linear history only')
start, drop = rev(a.start), rev(a.drop)
si, di = commits.index(start), commits.index(drop)
assert si < di
def split_at(v):
    # optional trailing @REV selects this operation's first commit
    if '@' in v:
        body, r = v.rsplit('@', 1)
        idx = commits.index(rev(r))
        assert si <= idx < di, f'@{r} outside [start, drop)'
        return body, idx
    return v, si
moves, transforms, adds = [], [], []
for m in a.move:
    body, i0 = split_at(m); old, new = body.split('=', 1); moves.append((old, new, i0))
for t in a.transform:
    body, i0 = split_at(t); p, prog = body.split('=', 1); transforms.append((p, shlex.split(prog), i0))
for ad in a.add:
    body, i0 = split_at(ad); p, src = body.split('=', 1)
    blob = rev(src) if ':' in src else src
    assert git('cat-file', '-t', blob).decode().strip() == 'blob', src
    adds.append((p, blob, i0))
append_to = rev(a.append_msg_to) if a.append_msg_to else None

cache = {}

def transform(path, prog, blob, commit):
    key = (path, tuple(prog), blob)
    if key not in cache:
        data = git('cat-file', 'blob', blob)
        r = subprocess.run(prog, input=data, capture_output=True, env=dict(os.environ, COMMIT=commit))
        if r.returncode:
            sys.exit(f"transform {prog} failed on {path}@{commit[:12]}: {r.stderr.decode()}")
        cache[key] = git('hash-object', '-w', '--stdin', inp=r.stdout).decode().strip()
    return cache[key]

def rewrite_tree(tree, i, c):
    """Apply the moves, adds and transforms that are active at commit index i, in the
    same order and with the same checks as an index-based rewrite, but by splicing only
    the touched directories (treeedit.edit_tree)."""
    paths = set()
    for old, new, i0 in moves:
        if i >= i0: paths.update((old, new))
    for path, blob, i0 in adds:
        if i >= i0: paths.add(path)
    for path, prog, i0 in transforms:
        if i >= i0: paths.add(path)
    if not paths:
        return tree
    before = ls_paths(tree, paths)
    for p_, (_, typ, _) in before.items():
        if typ == 'tree':
            sys.exit(f'{p_} is a directory at {c[:12]}; list its files instead')
    cur = {p_: (m, s_) for p_, (m, _, s_) in before.items()}
    for old, new, i0 in moves:
        if i < i0 or old not in cur:
            continue
        if new in cur:
            sys.exit(f'{new} already exists at {c[:12]}')
        cur[new] = cur.pop(old)
    for path, blob, i0 in adds:
        if i < i0:
            continue
        if path in cur:
            if cur[path][1] != blob:
                sys.exit(f'--add {path}: present at {c[:12]} with a different blob {cur[path][1][:12]}')
            continue
        cur[path] = ('100644', blob)
    for path, prog, i0 in transforms:
        if i < i0 or path not in cur:
            continue
        cur[path] = (cur[path][0], transform(path, prog, cur[path][1], c))
    init = {p_: (m, s_) for p_, (m, _, s_) in before.items()}
    edits = {p_: cur.get(p_) for p_ in set(init) | set(cur) if init.get(p_) != cur.get(p_)}
    return edit_tree(tree, edits) if edits else tree

drop_msg = git('cat-file', 'commit', drop).partition(b'\n\n')[2]
newmap = {}
for i, c in enumerate(commits):
    if i < si:
        newmap[c] = c
        continue
    head, _, msg = git('cat-file', 'commit', c).partition(b'\n\n')
    hl = head.split(b'\n')
    parents = [l[7:].decode() for l in hl if l.startswith(b'parent ')]
    assert len(parents) == 1, c
    op = parents[0]
    tree = [l for l in hl if l.startswith(b'tree ')][0][5:].decode()
    if i == di:
        if rev(newmap.get(op, op) + '^{tree}') != tree:
            sys.exit('drop commit is not a no-op after the rewrite; absorption incomplete '
                     '(compare its tree with the rewritten parent)')
        newmap[c] = newmap.get(op, op)
        continue
    if i < di:
        tree = rewrite_tree(tree, i, c)
    if c == append_to:
        msg = msg.rstrip(b'\n') + b'\n\n==========================================\n\n' + drop_msg
    nh = [(b'tree ' + tree.encode()) if l.startswith(b'tree ') else
          (b'parent ' + newmap.get(op, op).encode()) if l.startswith(b'parent ') else l for l in hl]
    newmap[c] = git('hash-object', '-t', 'commit', '-w', '--stdin',
                    inp=b'\n'.join(nh) + b'\n\n' + msg).decode().strip()

print(newmap[commits[-1]])
for s in a.show:
    print(s, '->', newmap[rev(s)][:12])

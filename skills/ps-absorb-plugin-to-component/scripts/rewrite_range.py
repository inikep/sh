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

Prints the new tip SHA and a map of selected commits. Does not move any ref.
"""
import argparse, os, shlex, subprocess, sys, tempfile

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

tmpdir = tempfile.mkdtemp(prefix='rewrite_range.')
env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmpdir, 'index'))
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
        if rev(newmap[op] + '^{tree}') != tree:
            sys.exit('drop commit is not a no-op after the rewrite; absorption incomplete '
                     '(compare its tree with the rewritten parent)')
        newmap[c] = newmap[op]
        continue
    if i < di:
        git('read-tree', tree, env=env)
        for old, new, i0 in moves:
            if i < i0:
                continue
            ent = git('ls-files', '-s', '--', old, env=env).decode().split()
            if not ent:
                continue
            if git('ls-files', '-s', '--', new, env=env).strip():
                sys.exit(f'{new} already exists at {c[:12]}')
            git('update-index', '--force-remove', '--', old, env=env)
            git('update-index', '--add', '--cacheinfo', f'{ent[0]},{ent[1]},{new}', env=env)
        for path, blob, i0 in adds:
            if i < i0:
                continue
            ent = git('ls-files', '-s', '--', path, env=env).decode().split()
            if ent:
                if ent[1] != blob:
                    sys.exit(f'--add {path}: present at {c[:12]} with a different blob {ent[1][:12]}')
                continue
            git('update-index', '--add', '--cacheinfo', f'100644,{blob},{path}', env=env)
        for path, prog, i0 in transforms:
            if i < i0:
                continue
            ent = git('ls-files', '-s', '--', path, env=env).decode().split()
            if not ent:
                continue
            nb = transform(path, prog, ent[1], c)
            git('update-index', '--cacheinfo', f'{ent[0]},{nb},{path}', env=env)
        tree = git('write-tree', env=env).decode().strip()
    if c == append_to:
        msg = msg.rstrip(b'\n') + b'\n\n==========================================\n\n' + drop_msg
    nh = [(b'tree ' + tree.encode()) if l.startswith(b'tree ') else
          (b'parent ' + newmap[op].encode()) if l.startswith(b'parent ') else l for l in hl]
    newmap[c] = git('hash-object', '-t', 'commit', '-w', '--stdin',
                    inp=b'\n'.join(nh) + b'\n\n' + msg).decode().strip()

print(newmap[commits[-1]])
for s in a.show:
    print(s, '->', newmap[rev(s)][:12])

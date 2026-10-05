#!/usr/bin/env python3
"""Plumbing history rewrite driven by a backchain.py state chain.

For every commit from --start (A) up to --drop (X, exclusive) the new-root subtrees are
replaced by the chain state of the latest toucher at or before that commit
(DIR/NNN-<sha12>.tsv = state AFTER toucher NNN), the old root is removed, and the optional
--transform / --add operations of rewrite_range.py are applied (same syntax, incl. @REV).
X must become a no-op on its rewritten parent (asserted) and is removed. Commits after X
keep their trees. Commit objects are rewritten raw (messages, author, committer kept);
--append-msg-to SHA appends X's message after a '==========================================' line.

usage: rewrite_chain.py --base B --head H --start A --drop X --chain DIR --touchers FILE
         --old-root plugin/<name>/ --new-root components/<name>/ [--new-root ...]
         [--transform PATH=PROG[@REV[..END]]] [--add PATH=REV:PATH[@REV]] [--remove PATH[@REV]]
         [--append-msg-to A]
--old-root may be repeated (e.g. the plugin dir and its unittest dir); --remove deletes a path
that X deletes but that is outside the old roots (e.g. a plugin-only mysql-test include).
--transform ...@REV..END applies to commits in [REV, END) only (hoisting a hunk that a later
commit removes again).
Prints the new tip SHA; does not move any ref.
"""
import argparse, glob, os, shlex, subprocess, sys, tempfile

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
ap.add_argument('--start', required=True)
ap.add_argument('--drop', required=True)
ap.add_argument('--chain', required=True)
ap.add_argument('--touchers', required=True)
ap.add_argument('--old-root', action='append', required=True)
ap.add_argument('--new-root', action='append', required=True)
ap.add_argument('--transform', action='append', default=[])
ap.add_argument('--add', action='append', default=[])
ap.add_argument('--remove', action='append', default=[])
ap.add_argument('--append-msg-to')
ap.add_argument('--show', action='append', default=[])
a = ap.parse_args()

commits = git('rev-list', '--reverse', f'{a.base}..{a.head}').decode().split()
if git('rev-list', '--merges', f'{a.base}..{a.head}').strip():
    sys.exit('range contains merge commits; linear history only')
start, drop = rev(a.start), rev(a.drop)
si, di = commits.index(start), commits.index(drop)
pos = {c: i for i, c in enumerate(commits)}
touchers = [rev(l.split()[0]) for l in open(a.touchers) if l.strip() and not l.startswith('#')]
states = {}
for f in glob.glob(os.path.join(a.chain, '[0-9][0-9][0-9]-*.tsv')):
    n = int(os.path.basename(f)[:3])
    states[n] = f
assert sorted(states) == list(range(len(touchers))), 'chain does not match touchers'
for n, t in enumerate(touchers):
    assert os.path.basename(states[n])[4:16] == t[:12], (n, t)
    assert si <= pos[t] < di, f'toucher {t[:12]} outside [start, drop)'
assert touchers[0] == start, 'first toucher must be the start commit'
assert [pos[t] for t in touchers] == sorted(pos[t] for t in touchers), 'touchers not in history order'

def load(f):
    out = []
    for l in open(f):
        p, m, b = l.rstrip('\n').split('\t')
        out.append((p, m, b))
    return out
state_rows = {n: load(f) for n, f in states.items()}

def split_at(v, allow_end=False):
    if '@' in v:
        body, r = v.rsplit('@', 1)
        end = di
        if allow_end and '..' in r:
            r, e = r.split('..', 1)
            end = pos[rev(e)]
        idx = pos[rev(r)]
        assert si <= idx < di and idx < end <= di
        return (body, idx, end) if allow_end else (body, idx)
    return (v, si, di) if allow_end else (v, si)
transforms, adds, removes = [], [], []
for t in a.transform:
    body, i0, i1 = split_at(t, True); p, prog = body.split('=', 1); transforms.append((p, shlex.split(prog), i0, i1))
for ad in a.add:
    body, i0 = split_at(ad); p, src = body.split('=', 1)
    adds.append((p, rev(src) if ':' in src else src, i0))
for rm_ in a.remove:
    removes.append(split_at(rm_))

tmpdir = tempfile.mkdtemp(prefix='rewrite_chain.')
env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmpdir, 'index'))
cache = {}
def transform(path, prog, blob, commit):
    key = (path, tuple(prog), blob)
    if key not in cache:
        r = subprocess.run(prog, input=git('cat-file', 'blob', blob), capture_output=True,
                           env=dict(os.environ, COMMIT=commit))
        if r.returncode:
            sys.exit(f'transform {prog} failed on {path}@{commit[:12]}: {r.stderr.decode()}')
        cache[key] = git('hash-object', '-w', '--stdin', inp=r.stdout).decode().strip()
    return cache[key]

roots = a.old_root + a.new_root
drop_msg = git('cat-file', 'commit', drop).partition(b'\n\n')[2]
append_to = rev(a.append_msg_to) if a.append_msg_to else None
newmap = {}
tn = -1
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
            d = git('diff-tree', '-r', '--name-status', newmap[op] + '^{tree}', tree).decode()
            sys.exit(f'drop commit is not a no-op after the rewrite; rewritten parent {newmap[op]} differs:\n{d[:3000]}')
        newmap[c] = newmap[op]
        continue
    if i < di:
        while tn + 1 < len(touchers) and pos[touchers[tn + 1]] <= i:
            tn += 1
        git('read-tree', tree, env=env)
        rm = git('ls-files', '-z', '--', *roots, env=env).split(b'\0')
        info = b''.join(b'0 ' + b'0' * 40 + b'\t' + p + b'\n' for p in rm if p)
        info += ''.join(f'{m} {b}\t{p}\n' for p, m, b in state_rows[tn]).encode()
        git('update-index', '--index-info', inp=info, env=env)
        for path, i0 in removes:
            if i >= i0:
                git('update-index', '--force-remove', '--', path, env=env)
        for path, blob, i0 in adds:
            if i < i0:
                continue
            ent = git('ls-files', '-s', '--', path, env=env).decode().split()
            if ent:
                if ent[1] != blob:
                    sys.exit(f'--add {path}: present at {c[:12]} with a different blob')
                continue
            git('update-index', '--add', '--cacheinfo', f'100644,{blob},{path}', env=env)
        for path, prog, i0, i1 in transforms:
            if i < i0 or i >= i1:
                continue
            ent = git('ls-files', '-s', '--', path, env=env).decode().split()
            if not ent:
                continue
            git('update-index', '--cacheinfo', f'{ent[0]},{transform(path, prog, ent[1], c)},{path}', env=env)
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

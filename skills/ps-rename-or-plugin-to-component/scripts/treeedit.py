"""Edit git trees without an index: read only the touched paths, rebuild only the
directories on their way to the root with `git mktree`, and memoize per directory.

A per-entry `git update-index` on a full index rewrites the whole index (tens of
thousands of entries) on every call; for N path operations over M commits that is
N*M index rewrites. Splicing touches only the changed directories, so the cost is
proportional to the paths edited, not to the size of the tree.
"""
import subprocess, sys

def _git(*a, inp=None, env=None):
    r = subprocess.run(['git', *a], input=inp, capture_output=True, env=env)
    if r.returncode:
        sys.exit(f"git {' '.join(a[:3])} ... failed: {r.stderr.decode()}")
    return r.stdout

def ls_paths(tree, paths):
    """Return {path: (mode, type, sha)} for the given file paths that exist in tree.
    A path that names a directory is reported with type 'tree' so callers can refuse it."""
    if not paths:
        return {}
    out = {}
    # -r lists files; directories named in paths show up as their files, detect below
    data = _git('ls-tree', '-r', '-t', '-z', '--full-tree', tree, '--', *sorted(set(paths)))
    want = set(paths)
    for rec in data.split(b'\0'):
        if not rec:
            continue
        meta, name = rec.split(b'\t', 1)
        mode, typ, sha = meta.decode().split()
        name = name.decode()
        if name in want:
            out[name] = (mode, typ, sha)
    return out

_ls_cache, _mk_cache = {}, {}

def _ls(tree):
    if tree not in _ls_cache:
        ents = {}
        for rec in _git('ls-tree', '-z', tree).split(b'\0'):
            if rec:
                meta, name = rec.split(b'\t', 1)
                mode, typ, sha = meta.decode().split()
                ents[name.decode()] = (mode, typ, sha)
        _ls_cache[tree] = ents
    return _ls_cache[tree]

def _mktree(ents):
    key = tuple(sorted(ents.items()))
    if key not in _mk_cache:
        data = b''.join(f'{m} {t} {s}\t{n}'.encode() + b'\0' for n, (m, t, s) in ents.items())
        _mk_cache[key] = _git('mktree', '-z', inp=data).decode().strip()
    return _mk_cache[key]

_edit_cache = {}

def edit_tree(tree, edits):
    """Apply edits {path: (mode, blob_sha) or None (delete)} to tree; return the new
    tree sha, or None when the result is empty. tree may be None (new directory)."""
    key = (tree, tuple(sorted(edits.items(), key=lambda kv: kv[0])))
    if key in _edit_cache:
        return _edit_cache[key]
    ents = dict(_ls(tree)) if tree else {}
    sub = {}
    for path, val in edits.items():
        head, sep, rest = path.partition('/')
        if sep:
            sub.setdefault(head, {})[rest] = val
        elif val is None:
            ents.pop(head, None)
        else:
            if head in ents and ents[head][1] == 'tree':
                sys.exit(f'edit_tree: {path} is a directory')
            ents[head] = (val[0], 'commit' if val[0] == '160000' else 'blob', val[1])
    for head, sedits in sub.items():
        cur = ents.get(head)
        if cur and cur[1] != 'tree':
            sys.exit(f'edit_tree: {head} is a file, cannot descend')
        nt = edit_tree(cur[2] if cur else None, sedits)
        if nt is None:
            ents.pop(head, None)
        else:
            ents[head] = ('040000', 'tree', nt)
    res = _mktree(ents) if ents else None
    _edit_cache[key] = res
    return res

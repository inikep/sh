#!/usr/bin/env python3
"""Carry a conversion commit X backwards through the commits that touched the old tree.

For semantic conversions (no deterministic transform), the component-form state at each
toucher T is derived from the state after the next toucher by reverse-applying T's own
change with a per-file 3-way merge:
    before(T)[new] = merge(ours=after(T)[new], base=T:<old>, theirs=T^:<old>)
Start: after(T_last) = X's content for the new paths.

Usage:
  backchain.py --x X --map map.py --touchers FILE --out DIR [--resolutions DIR] [--special FILE]

  map.py defines  to_new(old_path) -> new_path|None  and  NEW_ROOTS (list of new dirs).
  touchers: one commit per line, oldest first (all commits in A..X^ touching old paths).
  Output: DIR/<n>-<sha>.tsv = state AFTER toucher n (new_path<TAB>mode<TAB>blob), plus
          DIR/conflicts.txt listing (toucher, new_path) that need a manual resolution.
  Resolutions (preferred): DIR/<sha12>/<new_path>.res.py = edit script with resolve(r) that is
  re-applied to a fresh merge on every run (see reslib.py); it returns the text of new_path in
  the state BEFORE <sha> or None to drop it. Legacy: DIR/<sha12>/<new_path> = full resolved
  content (goes stale when a later step changes), or "@@DELETE@@\n" to drop the file.
  --special FILE: python with  adjust(sha, state, git) -> None  to apply semantic edits when
  stepping back over <sha> (e.g. drop a feature the conversion re-implemented).

State is carried for paths under NEW_ROOTS only. Paths created by X that never existed in the
old tree stay unless a resolution/special removes them.
"""
import argparse, importlib.util, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reslib

def git(*a, inp=None):
    r = subprocess.run(['git', *a], input=inp, capture_output=True)
    if r.returncode:
        sys.exit(f"git {' '.join(a)} failed: {r.stderr.decode()}")
    return r.stdout

def blob_of(rev, path):
    r = subprocess.run(['git', 'rev-parse', '-q', '--verify', f'{rev}:{path}'], capture_output=True)
    return r.stdout.decode().strip() if r.returncode == 0 else None

def mode_of(rev, path):
    out = git('ls-tree', rev, '--', path).decode().split()
    return out[0] if out else '100644'

ap = argparse.ArgumentParser()
ap.add_argument('--x', required=True)
ap.add_argument('--map', required=True)
ap.add_argument('--touchers', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--resolutions')
ap.add_argument('--special')
ap.add_argument('--normalize', help="command applied to base and theirs before merging; '{new}' = new path; blob on stdin")
ap.add_argument('--transform-files', help='new paths (one per line) derived by --transform-prog instead of merging')
ap.add_argument('--transform-prog', help="command; '{new}' is replaced by the new path; plugin blob on stdin")
a = ap.parse_args()

spec = importlib.util.spec_from_file_location('pathmap', a.map); pm = importlib.util.module_from_spec(spec); spec.loader.exec_module(pm)
adjust = None
if a.special:
    s2 = importlib.util.spec_from_file_location('special', a.special); sp = importlib.util.module_from_spec(s2); s2.loader.exec_module(sp)
    adjust = sp.adjust
X = git('rev-parse', a.x).decode().strip()
touchers = [git('rev-parse', l.split()[0]).decode().strip() for l in open(a.touchers) if l.strip() and not l.startswith('#')]
os.makedirs(a.out, exist_ok=True)
tfiles = set(l.strip() for l in open(a.transform_files)) if a.transform_files else set()
import shlex
def run_transform(newp, blob):
    cmd = shlex.split(a.transform_prog.replace('{new}', newp))
    r = subprocess.run(cmd, input=git('cat-file', 'blob', blob), capture_output=True)
    if r.returncode:
        sys.exit(f'transform failed for {newp}: {r.stderr.decode()}')
    return git('hash-object', '-w', '--stdin', inp=r.stdout).decode().strip()

# initial state = X's new paths
state = {}
for root in pm.NEW_ROOTS:
    for line in git('ls-tree', '-r', X, '--', root).decode().splitlines():
        meta, path = line.split('\t', 1)
        mode, _, blob = meta.split()
        state[path] = (mode, blob)

tmp = tempfile.mkdtemp(prefix='backchain.')
conflicts = []

def write_state(n, sha):
    with open(os.path.join(a.out, f'{n:03d}-{sha[:12]}.tsv'), 'w') as f:
        for p in sorted(state):
            f.write(f'{p}\t{state[p][0]}\t{state[p][1]}\n')

def resolution(sha, newp):
    """('script', path) for an edit script, ('file', path) for a legacy full file, or None"""
    if not a.resolutions:
        return None
    f = os.path.join(a.resolutions, sha[:12], newp)
    if os.path.exists(f + '.res.py'):
        return ('script', f + '.res.py')
    return ('file', f) if os.path.exists(f) else None

def blob_text(b):
    return None if b is None else git('cat-file', 'blob', b).decode('utf-8', 'surrogateescape')

def normalized(newp, b):
    if b is None:
        return None
    data = git('cat-file', 'blob', b)
    if a.normalize:
        r0 = subprocess.run(shlex.split(a.normalize.replace('{new}', newp)), input=data, capture_output=True)
        if r0.returncode:
            sys.exit(f'normalize failed for {newp}: {r0.stderr.decode()}')
        data = r0.stdout
    return data.decode('utf-8', 'surrogateescape')

def merge3(ours, base, theirs):
    files = []
    for tag, text in (('ours', ours), ('base', base), ('theirs', theirs)):
        p = os.path.join(tmp, tag); open(p, 'w', encoding='utf-8', errors='surrogateescape').write(text); files.append(p)
    r = subprocess.run(['git', 'merge-file', '-p', '--diff3', '-L', 'component', '-L', 'plugin-after', '-L', 'plugin-before', *files], capture_output=True)
    return r.stdout.decode('utf-8', 'surrogateescape'), r.returncode

def run_script(path, T, newp, st, oldp):
    spec = importlib.util.spec_from_file_location('res_' + T[:12], path); mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ours = blob_text(state.get(newp, (None, None))[1])
    base = normalized(newp, blob_of(T, oldp)); theirs = normalized(newp, blob_of(f'{T}^', oldp))
    merged, nconf = (merge3(ours, base, theirs) if None not in (ours, base, theirs) else (None, 0))
    r = reslib.Resolution(T, newp, st, ours, base, theirs, merged, nconf,
                          lambda p: blob_text(state.get(p, (None, None))[1]))
    try:
        return mod.resolve(r)
    except SystemExit as e:
        sys.exit(f'resolution {path}: {e}')

for n in range(len(touchers) - 1, -1, -1):
    T = touchers[n]
    write_state(n, T)                          # state AFTER T
    changed = git('diff-tree', '--no-commit-id', '-r', '--no-renames', '--name-status', f'{T}^', T).decode().splitlines()
    for line in changed:
        st, oldp = line.split('\t', 1)
        newp = pm.to_new(oldp)
        if newp is None:
            continue
        res = resolution(T, newp)
        if res and res[0] == 'script':
            text = run_script(res[1], T, newp, st, oldp)
            if text is None:
                state.pop(newp, None)
            else:
                state[newp] = (state.get(newp, (mode_of(f'{T}^', oldp),))[0],
                               git('hash-object', '-w', '--stdin', inp=text.encode('utf-8', 'surrogateescape')).decode().strip())
            continue
        if res:
            res = res[1]
            data = open(res, 'rb').read()
            if data == b'@@DELETE@@\n':
                state.pop(newp, None)
            else:
                state[newp] = (state.get(newp, (mode_of(f'{T}^', oldp),))[0], git('hash-object', '-w', '--stdin', inp=data).decode().strip())
            continue
        base = blob_of(T, oldp); theirs = blob_of(f'{T}^', oldp); ours = state.get(newp, (None, None))[1]
        if newp in tfiles:
            if theirs is None:
                state.pop(newp, None)
            else:
                state[newp] = (mode_of(f'{T}^', oldp), run_transform(newp, theirs))
            continue
        if st == 'A':                          # T added it: file did not exist before T
            if ours is not None and base is not None and ours != base:
                # conversion changed it; still did not exist before T -> drop
                pass
            state.pop(newp, None)
            continue
        if st == 'D':
            conflicts.append((T, newp, 'T deleted the file; needs a component version of the pre-T file'))
            continue
        if ours is None:
            conflicts.append((T, newp, 'modified by T but absent from the component state'))
            continue
        files = []
        for tag, b in (('ours', ours), ('base', base), ('theirs', theirs)):
            data = git('cat-file', 'blob', b)
            if a.normalize and tag != 'ours':
                # merge in normalized (converted) space: mechanical conversion differences cancel out
                r0 = subprocess.run(shlex.split(a.normalize.replace('{new}', newp)), input=data, capture_output=True)
                if r0.returncode:
                    sys.exit(f'normalize failed for {newp}: {r0.stderr.decode()}')
                data = r0.stdout
            p = os.path.join(tmp, tag); open(p, 'wb').write(data); files.append(p)
        r = subprocess.run(['git', 'merge-file', '-p', '--diff3', '-L', 'component', '-L', 'plugin-after', '-L', 'plugin-before', *files], capture_output=True)
        if r.returncode != 0:
            conflicts.append((T, newp, f'{r.returncode} conflict region(s)'))
            d = os.path.join(a.out, 'conflicts', T[:12], os.path.dirname(newp)); os.makedirs(d, exist_ok=True)
            open(os.path.join(a.out, 'conflicts', T[:12], newp), 'wb').write(r.stdout)
            continue
        state[newp] = (state[newp][0], git('hash-object', '-w', '--stdin', inp=r.stdout).decode().strip())
    if adjust:
        adjust(T, state, git)
write_state(-1, 'before-first')                 # state before the first toucher (should be empty-ish)
with open(os.path.join(a.out, 'conflicts.txt'), 'w') as f:
    for T, p, why in conflicts:
        f.write(f'{T[:12]}\t{p}\t{why}\n')
print(f'touchers: {len(touchers)}  conflicts: {len(conflicts)}  remaining paths before first toucher: {len(state)}')

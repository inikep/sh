#!/usr/bin/env python3
"""Find defects that already exist in the input branch, before rewriting anything.

usage: scan_input.py --start A --end X^ --old-root plugin/<name>/ [--window 60] [--min-files 2]
1. Missing sources: at every commit in [A, X^] that touches the old root, each source named in
   <old-root>CMakeLists.txt and each quoted "<old-root>..." #include must exist in that tree
   (a lost file makes the original commit unbuildable; restore it rather than "fixing" CMake).
2. Round trips: a commit C changes files that a later commit D (within --window commits) puts
   back to exactly C^'s blobs. Genuine revert pairs show up too; the suspicious ones are
   unrelated subjects restoring several files (e.g. a "Revert" commit that also reverted
   unrelated upstream files, leaving the commits in between unbuildable).
Configure/build the original touchers separately (build_commit.sh) to confirm.
"""
import argparse, collections, re, subprocess

ap = argparse.ArgumentParser()
ap.add_argument('--start', required=True)
ap.add_argument('--end', required=True)
ap.add_argument('--old-root', required=True)
ap.add_argument('--window', type=int, default=60)
ap.add_argument('--min-files', type=int, default=2)
a = ap.parse_args()
root = a.old_root.rstrip('/') + '/'

def git(*args, check=True):
    r = subprocess.run(['git', *args], capture_output=True)
    if check and r.returncode:
        raise SystemExit(r.stderr.decode())
    return r.stdout.decode('utf-8', 'surrogateescape')
def exists(rev, path):
    return subprocess.run(['git', 'cat-file', '-e', f'{rev}:{path}'], capture_output=True).returncode == 0
subj = lambda c: git('log', '-1', '--format=%h %s', c).strip()[:90]

commits = git('rev-list', '--reverse', f'{a.start}^..{a.end}').split()

print('== missing sources / includes')
problems = 0
for c in git('rev-list', '--reverse', f'{a.start}^..{a.end}', '--', root).split():
    missing = set()
    cm = git('show', f'{c}:{root}CMakeLists.txt', check=False)
    for src in re.findall(r'(?<![\w/$.{])([\w/.-]+\.(?:cc|cpp|c))\b', cm):
        if not exists(c, root + src):
            missing.add(root + src)
    for f in git('ls-tree', '-r', '--name-only', c, '--', root).split():
        if re.search(r'\.(cc|h|cpp|hpp|c)$', f):
            for inc in re.findall(r'#include\s+"(%s[^"]+)"' % re.escape(root), git('show', f'{c}:{f}')):
                if not exists(c, inc):
                    missing.add(inc)
    if missing:
        problems += 1
        print(f'{subj(c)}\n    missing: ' + ', '.join(sorted(missing)))
print(f'{problems} commit(s) with missing files')

print('== round trips (C changes files that D later restores exactly)')
pos = {c: i for i, c in enumerate(commits)}
changes = collections.defaultdict(list)     # path -> [(index, old_blob, new_blob)]
for c in commits:
    for line in git('diff-tree', '-r', '--no-commit-id', '--no-renames', '--raw', f'{c}^', c).splitlines():
        meta, path = line.split('\t', 1)
        _, _, old, new, _ = meta.split(' ')
        changes[path].append((pos[c], old, new))
pairs = collections.defaultdict(list)
for path, seq in changes.items():
    for k, (i, old, new) in enumerate(seq):
        for j, _, new2 in seq[k + 1:]:
            if j - i > a.window:
                break
            if new2 == old:
                pairs[(i, j)].append(path)
                break
for (i, j), paths in sorted(pairs.items()):
    if len(paths) >= a.min_files:
        print(f'{subj(commits[i])}\n  restored by {subj(commits[j])} ({j - i} commits later): '
              + ', '.join(sorted(paths)[:8]) + (' ...' if len(paths) > 8 else ''))

print('== near restores (a large change mostly undone by the next change of the same file)')
def nlines(b1, b2):
    out = git('diff', '--numstat', b1, b2).split()
    return int(out[0]) + int(out[1]) if len(out) >= 2 and out[0].isdigit() else 0
near = collections.defaultdict(list)
for path, seq in changes.items():
    for k in range(len(seq) - 1):
        i, old, new = seq[k]
        j, _, new2 = seq[k + 1]
        if j - i > a.window or '0' * 40 in (old, new, new2) or new2 == old:
            continue
        size = nlines(old, new)
        if size >= 40:
            rest = nlines(old, new2)
            if rest <= size // 4:
                near[(i, j)].append(f'{path} ({size} -> {rest} lines)')
for (i, j), paths in sorted(near.items()):
    print(f'{subj(commits[i])}\n  mostly undone by {subj(commits[j])} ({j - i} commits later): ' + '; '.join(paths[:6]))

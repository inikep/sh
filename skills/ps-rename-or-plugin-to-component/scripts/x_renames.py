#!/usr/bin/env python3
"""Turn a rename-style conversion commit X into rewrite_range.py arguments.

usage: x_renames.py X [--base BASE] [--old-paths]

--old-paths: print only the rename sources (one per line), for verify_rewrite.sh.

Prints one argument per line (feed with `mapfile -t ARGS < file`):
  --move OLD=NEW                 for every 100% rename in X
  --add NEW=X:NEW@START          for every file X adds
and, on stderr, what still needs a decision:
  * renames below 100% similarity (content changed: needs a --transform or the
    backward chain, not a plain --move);
  * any other change (modify/delete) in X;
  * START: the first commit in BASE..X^ that touches an old path (the introduction);
  * for each added file, whether it is a verbatim copy of a file that no commit in
    BASE..X changes. Only then is adding X's blob at START tree-neutral; otherwise
    choose the @REV yourself.
Exit status 1 when X is not a pure rename (+ verbatim adds) commit.
"""
import argparse, subprocess, sys

def git(*a):
    return subprocess.run(['git', *a], capture_output=True, text=True, check=True).stdout

ap = argparse.ArgumentParser()
ap.add_argument('x')
ap.add_argument('--base', default=None, help='range base; needed for START and the copy checks')
ap.add_argument('--old-paths', action='store_true', help='print rename sources only')
a = ap.parse_args()
x = git('rev-parse', a.x).strip()

moves, adds, other = [], [], []
for line in git('show', '-M', '--name-status', '--format=', x).splitlines():
    f = line.split('\t')
    if f[0] == 'R100':
        moves.append((f[1], f[2]))
    elif f[0] == 'A':
        adds.append(f[1])
    else:
        other.append(line)

if a.old_paths:
    print('\n'.join(o for o, _ in moves))
    sys.exit(0)

ok = not other
for l in other:
    print(f'needs a --transform (gate it, see SKILL.md): {l}', file=sys.stderr)

start = None
if a.base and moves:
    olds = [o for o, _ in moves]
    revs = git('rev-list', '--reverse', f'{a.base}..{x}^', '--', *olds).split()
    if revs:
        start = revs[0]
        print(f'START (first toucher of old paths): {start[:12]} '
              f'{git("log", "-1", "--format=%s", start).strip()}', file=sys.stderr)
        print(f'touchers of old paths in range: {len(revs)}', file=sys.stderr)
    newtouch = git('rev-list', f'{a.base}..{x}^', '--', *[n for _, n in moves], *adds).split()
    if newtouch:
        ok = False
        print(f'new paths already touched before X by {len(newtouch)} commit(s), e.g. {newtouch[0][:12]}',
              file=sys.stderr)

for o, n in moves:
    print(f'--move\n{o}={n}')
for p in adds:
    blob = git('rev-parse', f'{x}:{p}').strip()
    src = [l.split()[3] + ' ' + l.split('\t')[1] for l in
           git('ls-tree', '-r', f'{x}^').splitlines() if l.split()[2] == blob]
    note = 'no identical file in X^'
    if src:
        path = src[0].split(' ', 1)[1]
        changed = git('rev-list', f'{a.base}..{x}', '--', path).split() if a.base else ['?']
        note = (f'copy of {path}, unchanged in range' if not changed else
                f'copy of {path}, but {path} changes in range ({len(changed)} commit(s)): pick @REV')
        if changed:
            ok = False
    else:
        ok = False
    print(f'add {p}: {note}', file=sys.stderr)
    print(f'--add\n{p}={a.x}:{p}' + (f'@{start}' if start else ''))
sys.exit(0 if ok else 1)

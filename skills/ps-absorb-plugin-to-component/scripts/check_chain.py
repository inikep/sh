#!/usr/bin/env python3
"""Invariant checks for a backchain.py state chain (run after every step).

usage: check_chain.py --chain DIR --touchers FILE --map map.py --old-root plugin/<name>/
                      [--allow FILE] [--min-len 8] [--strict-last]
1. Anachronisms: identifiers that the plugin first gets in toucher T (present in T's plugin
   code, absent from T^'s) must not appear in the component state BEFORE T. Catches stale
   resolutions and special rules that keep later features alive (e.g. a helper function or a
   registry API that only arrives in a later commit). --allow lists identifiers that are
   component infrastructure on purpose (one per line, '#' comments); 'path:<glob>' entries allow identifiers found only in
   matching files (e.g. files restored into history on purpose).
2. Containment: the state before T and the state after T may differ only in paths T changes
   (mapped). Other paths are listed; they are legitimate only for deliberate special rules.
   For the LAST toucher any extra path means special rules rewrote X's own content: error.
The .so undefined-symbol check is part of the build (build_commit.sh / ccheck).
Exit status 1 if any anachronism or a last-toucher containment error is found.
"""
import argparse, glob, importlib.util, os, re, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument('--chain', required=True)
ap.add_argument('--touchers', required=True)
ap.add_argument('--map', required=True)
ap.add_argument('--old-root', required=True)
ap.add_argument('--allow')
ap.add_argument('--min-len', type=int, default=8)
a = ap.parse_args()

def git(*args):
    return subprocess.run(['git', *args], capture_output=True, check=True).stdout
spec = importlib.util.spec_from_file_location('pathmap', a.map); pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)
touchers = [git('rev-parse', l.split()[0]).decode().strip() for l in open(a.touchers) if l.strip() and not l.startswith('#')]
states = {}
for f in glob.glob(os.path.join(a.chain, '[0-9][0-9][0-9]-*.tsv')):
    states[int(os.path.basename(f)[:3])] = {l.split('\t')[0]: l.split('\t')[2].strip() for l in open(f)}
allow, allow_paths = set(), []
if a.allow:
    for l in open(a.allow):
        l = l.split('#')[0].strip()
        if l.startswith('path:'):
            allow_paths.append(l[5:])
        elif l:
            allow.add(l)
import fnmatch
def path_allowed(paths):
    return all(any(fnmatch.fnmatch(p, g) for g in allow_paths) for p in paths)

CODE = re.compile(r'\.(cc|h|hpp|cpp|c)$')
IDENT = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]{%d,}\b' % (a.min_len - 1))
KEYWORDS = {'decltype', 'static_cast', 'reinterpret_cast', 'const_cast', 'dynamic_cast', 'constexpr',
            'namespace', 'noexcept', 'nullptr', 'override', 'template', 'typename', 'unsigned', 'nodiscard',
            'maybe_unused', 'explicit', 'operator', 'volatile', 'register', 'continue', 'protected'}
cache = {}
def idents_of_blob(b):
    if b not in cache:
        text = git('cat-file', 'blob', b).decode('utf-8', 'surrogateescape')
        text = re.sub(r'//[^\n]*|/\*.*?\*/', ' ', text, flags=re.S)       # ignore comments
        text = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)                    # and string literals
        text = re.sub(r'^\s*#[^\n]*', ' ', text, flags=re.M)               # and preprocessor lines
        cache[b] = set(IDENT.findall(text)) - KEYWORDS
    return cache[b]
def plugin_idents(rev):
    out = set()
    for line in git('ls-tree', '-r', rev, '--', a.old_root).decode().splitlines():
        meta, path = line.split('\t', 1)
        if CODE.search(path) and '/tests/' not in path:
            out |= idents_of_blob(meta.split()[2])
    return out
def state_idents(st):
    out = {}
    for p, b in st.items():
        if CODE.search(p):
            for i in idents_of_blob(b):
                out.setdefault(i, set()).add(p)
    return out

bad = 0
for n in range(1, len(touchers)):
    T = touchers[n]
    before, after = states[n - 1], states[n]
    intro = plugin_idents(T) - plugin_idents(T + '^')
    found = state_idents(before)
    hits = sorted((i, ', '.join(sorted(found[i]))) for i in intro
                  if i in found and i not in allow and not path_allowed(found[i]))
    changed = set()
    for line in git('diff-tree', '-r', '--no-commit-id', '--name-only', '--no-renames', T + '^', T).decode().splitlines():
        np = pm.to_new(line)
        if np:
            changed.add(np)
    extra = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p) and p not in changed)
    tag = T[:12]
    if hits:
        bad += 1
        print(f'{tag} ANACHRONISM: {len(hits)} identifier(s) introduced by this commit exist before it:')
        for i, p in hits[:12]:
            print(f'    {i}  ({p})')
    if extra:
        last = n == len(touchers) - 1
        if last:
            bad += 1
        print(f'{tag} {"ERROR" if last else "note"}: state changes outside the paths it touches: '
              + ', '.join(extra[:8]) + (' ...' if len(extra) > 8 else ''))
print(f'checked {len(touchers) - 1} steps: {"FAIL" if bad else "ok"}')
sys.exit(1 if bad else 0)

#!/usr/bin/env python3
"""Reverse gate for conversion rules: applied to X's OWN (already converted) files they must
change nothing. The forward gate (X^ -> X) cannot see rules that over-apply, e.g. a sysvar rename
that also renames an identically named UDF ('audit_log_filter_flush') or an option VALUE
(--x.file='audit_log_filter_file'); such rules corrupt merged lines in older states.

usage: check_rules_noop.py --x X --prog "python3 normalize.py {new}" ROOT [ROOT...]
  PROG reads a file on stdin and writes the converted file ({new} = its path in X).
Prints every changed line (X line -> rule output); exit 1 if any file changes.
Fix the rule, or document the line as protected (special rules must skip lines present in X).
"""
import argparse, difflib, shlex, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument('--x', required=True)
ap.add_argument('--prog', required=True)
ap.add_argument('roots', nargs='+')
a = ap.parse_args()
files = subprocess.run(['git', 'ls-tree', '-r', '--name-only', a.x, '--', *a.roots],
                       capture_output=True, text=True, check=True).stdout.split()
changed = 0
for p in files:
    data = subprocess.run(['git', 'show', f'{a.x}:{p}'], capture_output=True, check=True).stdout
    r = subprocess.run(shlex.split(a.prog.replace('{new}', p)), input=data, capture_output=True)
    if r.returncode:
        print(f'{p}: rule program failed: {r.stderr.decode()[:200]}'); changed += 1; continue
    if r.stdout != data:
        changed += 1
        old = data.decode('utf-8', 'surrogateescape').split('\n'); new = r.stdout.decode('utf-8', 'surrogateescape').split('\n')
        print(f'== {p}')
        for d in difflib.unified_diff(old, new, lineterm='', n=0):
            if not d.startswith(('---', '+++', '@@')):
                print('   ', d[:160])
print(f'{len(files)} files, {changed} changed by the rules')
sys.exit(1 if changed else 0)

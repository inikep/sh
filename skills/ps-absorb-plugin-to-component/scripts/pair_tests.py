#!/usr/bin/env python3
"""Give converted MTR tests the per-test setup a component needs.

A plugin suite often loads the plugin for the whole suite (suite.opt plugin-load) and may rely on
MTR bootstrap for its tables; a component is installed by each test. For a test that does not
install the component (directly or via a local .inc), insert the setup includes after the
have-include line and append the teardown includes; for a test that creates tables but never
drops them (older DELETE-style cleanup), append the teardown. X's own tests must come out
unchanged (check that first: every test in X must be a no-op).

Library: pair(text, read, cfg) with read(inc_name) -> text of a suite-local include or None.
CLI (apply to a directory in place, e.g. a materialized suite):
  pair_tests.py DIR [--head L] [--install L] [--uninstall L] [--tables-init L] [--tables-cleanup L]
"""
import argparse, glob, os, re

DEFAULT = dict(
    head='--source include/have_component_audit_log.inc',
    install='--source ../inc/audit_comp_install.inc',
    uninstall='--source ../inc/audit_comp_uninstall.inc',
    tables_init='--source ../inc/audit_tables_init.inc',
    tables_cleanup='--source ../inc/audit_tables_cleanup.inc')


def _has(text, line, read, depth=0):
    if line in text:
        return True
    if depth > 3:
        return False
    for inc in re.findall(r'^--source\s+(\S+\.inc)\s*$', text, re.M):
        if not inc.startswith('include/'):
            t = read(inc)
            if t is not None and _has(t, line, read, depth + 1):
                return True
    return False


def pair(text, read, cfg=DEFAULT):
    c = dict(DEFAULT, **cfg)
    if not _has(text, c['install'], read):
        head = c['head'] + '\n'
        if not text.startswith(head):
            raise SystemExit(f'test does not start with {c["head"]!r}')
        add = ([] if not c['tables_init'] or _has(text, c['tables_init'], read) else [c['tables_init']]) + [c['install']]
        text = head + '\n'.join(add) + '\n' + text[len(head):]
        tail = ([] if _has(text, c['uninstall'], read) else [c['uninstall']])
        if c['tables_cleanup'] and not _has(text, c['tables_cleanup'], read):
            tail.append(c['tables_cleanup'])
        if tail:
            text = text.rstrip('\n') + '\n\n' + '\n'.join(tail) + '\n'
    elif c['tables_init'] and _has(text, c['tables_init'], read) and not _has(text, c['tables_cleanup'], read):
        tail = ([] if _has(text, c['uninstall'], read) else [c['uninstall']]) + [c['tables_cleanup']]
        text = text.rstrip('\n') + '\n\n' + '\n'.join(tail) + '\n'
    return text


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('dir')
    for k in DEFAULT:
        ap.add_argument('--' + k.replace('_', '-'), default=DEFAULT[k])
    a = ap.parse_args()
    cfg = {k: getattr(a, k) for k in DEFAULT}
    read = lambda inc: open(os.path.join(a.dir, inc)).read() if os.path.exists(os.path.join(a.dir, inc)) else None
    n = 0
    for f in sorted(glob.glob(os.path.join(a.dir, '*.test'))):
        t = open(f).read(); t2 = pair(t, read, cfg)
        if t2 != t:
            open(f, 'w').write(t2); n += 1; print('paired', os.path.basename(f))
    print(n, 'test(s) changed')

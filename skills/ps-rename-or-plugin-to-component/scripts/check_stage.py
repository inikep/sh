#!/usr/bin/env python3
"""Sanity check for a transformed file at one commit (the byte-for-byte gate only proves X^).
usage: check_stage.py cc|test|result|any <old_so_name> < transformed_file
cc: known_udfs entries must equal DECLARE_*_UDF declarations; all kinds: no plugin leftovers."""
import re, sys
kind, old_so = sys.argv[1], sys.argv[2]
s = sys.stdin.read(); bad = []
if kind == 'cc':
    decl = re.findall(r'^DECLARE_(?:STRING|INT|REAL)_UDF(?:_AUTO)?\(\s*(?:\w+,\s*)?(\w+)\s*\)', s, re.M)
    info = re.findall(r'DECLARE_UDF_INFO(?:_AUTO)?\(\s*(\w+)', s)
    if sorted(decl) != sorted(info): bad.append(f'known_udfs {info} != declared {decl}')
    for tok in ('mysql_declare_plugin', 'mysql_plugin_registry_acquire', '#include <mysql/plugin.h>'):
        if tok in s: bad.append(f'leftover: {tok}')
if kind in ('test', 'result'):
    for tok in ('INSTALL PLUGIN', 'UNINSTALL PLUGIN', 'SONAME'):
        if tok in s: bad.append(f'leftover: {tok}')
if re.search(r'(?<![\w_])' + re.escape(old_so) + r'\.so', s): bad.append(f'leftover: {old_so}.so')
print('OK' if not bad else 'FAIL: ' + '; '.join(bad)); sys.exit(1 if bad else 0)

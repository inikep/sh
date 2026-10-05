#!/usr/bin/env python3
# plugin/audit_log_filter/CMakeLists.txt (stdin) -> components/audit_log_filter/CMakeLists.txt (stdout)
import re, subprocess, sys
s = sys.stdin.read()
tmpl = subprocess.run(['git', '-C', '/data/percona-server-linear', 'show', '4c08e7b0005a:components/audit_log_filter/CMakeLists.txt'],
                      capture_output=True, text=True, check=True).stdout
srcs = [l.strip() for l in s.split('\n') if re.fullmatch(r'\s*[\w/]+\.cc', l)]
if len(sys.argv) > 1:  # REV: drop sources missing from REV's plugin tree (broken lists in history)
    have = set(subprocess.run(['git', '-C', '/data/percona-server-linear', 'ls-tree', '-r', '--name-only', sys.argv[1], 'plugin/audit_log_filter/'], capture_output=True, text=True, check=True).stdout.split())
    srcs = [x for x in srcs if 'plugin/audit_log_filter/' + x in have]
assert srcs, 'no sources found'
L = tmpl.split('\n')
i = L.index('  SET(AUDIT_LOG_FILTER_SOURCES'); j = L.index('  )', i)
L[i + 1:j] = ['      ' + x for x in srcs]
out = '\n'.join(L)
m = re.search(r'VERSION_LESS ([\d.]+)\)\s*\n\s*TARGET_LINK_LIBRARIES\(audit_log_filter stdc\+\+fs\)', s)
fs_block = '  IF(CMAKE_CXX_COMPILER_ID MATCHES "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS 9.1)\n    TARGET_LINK_LIBRARIES(component_audit_log_filter stdc++fs)\n  ENDIF()\n\n'
assert fs_block in out
out = out.replace(fs_block, fs_block.replace('9.1', m.group(1)) if m else '')
inst = out[out.index('  IF(UNIX)\n    IF(INSTALL_MYSQLSHAREDIR)'):out.index('ENDIF()\n', out.index('  IF(UNIX)\n    IF(INSTALL_MYSQLSHAREDIR)')) + 0]
if 'audit_log_filter_linux_install.sql' not in s:
    k = out.index('  IF(UNIX)\n    IF(INSTALL_MYSQLSHAREDIR)'); e = out.index('  ENDIF()\n', out.index('    ENDIF()\n', k)) + len('  ENDIF()\n')
    out = out[:k].rstrip('\n') + '\n' + out[e:]
sys.stdout.write(out)

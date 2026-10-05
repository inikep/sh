#!/usr/bin/env python3
# percona-udf plugin -> component_percona_udf in packaging files (d9cb6086e414 rules).
# usage: pkg_transform.py install|spec|postinst|defs < file > file
import sys
kind = sys.argv[1]; s = sys.stdin.read()
def rep(old, new):
    global s
    assert s.count(old) == 1, (kind, old[:60], s.count(old))
    s = s.replace(old, new)
if kind == 'install':
    libs = ''.join(f'usr/lib/mysql/plugin/{d}lib{n}_udf.so\n' for n in ('fnv1a', 'fnv', 'murmur') for d in ('', 'debug/'))
    rep(libs, '')
    rep('\n\n# support files\n', 'usr/lib/mysql/plugin/component_percona_udf.so\n'
        'usr/lib/mysql/plugin/debug/component_percona_udf.so\n\n\n# support files\n')
elif kind == 'spec':
    libs = ''.join(f'%attr(755, root, root) %{{_libdir}}/mysql/plugin/{d}lib{n}_udf.*\n' for n in ('fnv1a', 'fnv', 'murmur') for d in ('', 'debug/'))
    rep(libs, '')
    rep('echo "Run the following commands to create these functions:"\n'
        'echo "mysql -e \\"CREATE FUNCTION fnv1a_64 RETURNS INTEGER SONAME \'libfnv1a_udf.so\'\\""\n'
        'echo "mysql -e \\"CREATE FUNCTION fnv_64 RETURNS INTEGER SONAME \'libfnv_udf.so\'\\""\n'
        'echo "mysql -e \\"CREATE FUNCTION murmur_hash RETURNS INTEGER SONAME \'libmurmur_udf.so\'\\""\n',
        'echo "Run the following command to install these functions (fnv_64, fnv1a_64, murmur_hash):"\n'
        'echo "mysql -e \\"INSTALL COMPONENT \'file://component_percona_udf\'\\""\n')
    rep('#\n#%attr(644, root, root) %{_datadir}/percona-server/fill_help_tables.sql\n',
        '%attr(755, root, root) %{_libdir}/mysql/plugin/component_percona_udf.so\n'
        '%attr(755, root, root) %{_libdir}/mysql/plugin/debug/component_percona_udf.so\n'
        '#\n#%attr(644, root, root) %{_datadir}/percona-server/fill_help_tables.sql\n')
elif kind == 'postinst':
    rep('echo -e " * Run the following commands to create these functions:\\n"\n'
        'echo -e "\\tmysql -e \\"CREATE FUNCTION fnv1a_64 RETURNS INTEGER SONAME \'libfnv1a_udf.so\'\\""\n'
        'echo -e "\\tmysql -e \\"CREATE FUNCTION fnv_64 RETURNS INTEGER SONAME \'libfnv_udf.so\'\\""\n'
        'echo -e "\\tmysql -e \\"CREATE FUNCTION murmur_hash RETURNS INTEGER SONAME \'libmurmur_udf.so\'\\""\n',
        'echo -e " * Run the following command to install these functions (fnv_64, fnv1a_64, murmur_hash):\\n"\n'
        'echo -e "\\tmysql -e \\"INSTALL COMPONENT \'file://component_percona_udf\'\\""\n')
elif kind == 'defs':
    assert 'component_percona_udf' not in s and s.endswith('\n')
    s += 'component_percona_udf               plugin_output_directory  no  PERCONA_UDF_COMPONENT\n'
sys.stdout.write(s)

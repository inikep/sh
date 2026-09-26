#!/usr/bin/env python3
# plugin-form binlog_utils_udf.cc (stdin) -> component-form (stdout), mirroring f2394dfb4e31
import sys, re, subprocess, tempfile, os
s=sys.stdin.read()
HEADER='''/* Copyright (c) 2023 Percona LLC and/or its affiliates. All rights reserved.

   This program is free software; you can redistribute it and/or
   modify it under the terms of the GNU General Public License
   as published by the Free Software Foundation; version 2 of
   the License.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA */

'''
assert not s.startswith('/*')
s=HEADER+s
def rep(old,new,count=1):
    global s
    assert s.count(old)==count, (old, s.count(old))
    s=s.replace(old,new)
rep('#include <type_traits>\n','')
if '#include <boost/algorithm/find_backward.hpp>\n' in s:
    rep('#include <boost/algorithm/find_backward.hpp>\n\n#include <mysql/plugin.h>\n',
        '#include <boost/algorithm/find_backward.hpp>\n#include <boost/preprocessor/stringize.hpp>\n')
else:
    rep('#include <mysql/plugin.h>\n','#include <boost/preprocessor/stringize.hpp>\n')
rep('#include <mysql/components/services/component_sys_var_service.h>\n',
    '#include <mysql/components/services/component_sys_var_service.h>\n#include <mysql/components/services/mysql_runtime_error_service.h>\n')
rep('#include <mysqlpp/udf_wrappers.hpp>\n','#include <mysqlpp/udf_registration.hpp>\n#include <mysqlpp/udf_wrappers.hpp>\n')
MACROS='''// defined as a macro because needed both raw and stringized
#define CURRENT_COMPONENT_NAME binlog_utils_udf
#define CURRENT_COMPONENT_NAME_STR BOOST_PP_STRINGIZE(CURRENT_COMPONENT_NAME)

REQUIRES_SERVICE_PLACEHOLDER(udf_registration);
REQUIRES_SERVICE_PLACEHOLDER(component_sys_variable_register);
'''
m=re.search(r'namespace \{\n\nbool binlog_utils_udf_initialized\{false\};\n.*?\} mysql_declare_plugin_end;\n', s, re.S)
if m:
    s=s[:m.start()]+MACROS+s[m.end():]
else:
    m=re.search(r'static bool binlog_utils_udf_initialized\{false\};\n.*?\} mysql_declare_plugin_end;\n', s, re.S)
    assert m
    s=s[:m.start()]+MACROS+s[m.end():]
chk=re.compile(r'\n    if \(!binlog_utils_udf_initialized\)\n      throw std::invalid_argument\(\n          "This function requires binlog_utils_udf plugin which is not "\n          "installed."\);\n')
s,n=chk.subn('',s); assert n>0
assert 'binlog_utils_udf_initialized' not in s
s=s.replace('sys_var_srv->get_variable(','mysql_service_component_sys_variable_register->get_variable(')
assert 'sys_var_srv' not in s and 'my_error' not in s.split('mysqlpp::udf_error_reporter')[0][-0:] or True
# known UDFs in declaration order
udfs=[]
for mm in re.finditer(r'^DECLARE_(STRING|INT|REAL)_UDF(?:_AUTO)?\(\s*(?:[A-Za-z0-9_]+,\s*)?([A-Za-z0-9_]+)\s*\)$', s, re.M):
    udfs.append((mm.group(2), mm.group(1)+'_RESULT'))
assert udfs
entries=',\n'.join(f'    DECLARE_UDF_INFO({n}, {t})' for n,t in udfs)
TAIL='''
static const std::array known_udfs{
'''+entries+'''};

#undef DECLARE_UDF_INFO

static void binlog_utils_my_error(int error_id, myf flags, ...) {
  va_list args;
  va_start(args, flags);
  mysql_service_mysql_runtime_error->emit(error_id, flags, args);
  va_end(args);
}

using udf_bitset_type =
    std::bitset<std::tuple_size<decltype(known_udfs)>::value>;
static udf_bitset_type registered_udfs;

static mysql_service_status_t component_init() {
  // here we use a custom error reporting function
  // 'binlog_utils_my_error()' based on the
  // 'mysql_service_mysql_runtime_error' service instead of the standard
  // 'my_error()' from 'mysys' to get rid of the 'mysys' dependency for this
  // component
  mysqlpp::udf_error_reporter::instance() = &binlog_utils_my_error;

  mysqlpp::register_udfs(mysql_service_udf_registration, known_udfs,
                         registered_udfs);
  return registered_udfs.all() ? 0 : 1;
}

static mysql_service_status_t component_deinit() {
  mysqlpp::unregister_udfs(mysql_service_udf_registration, known_udfs,
                           registered_udfs);
  return registered_udfs.none() ? 0 : 1;
}

// clang-format off
BEGIN_COMPONENT_PROVIDES(CURRENT_COMPONENT_NAME)
END_COMPONENT_PROVIDES();

BEGIN_COMPONENT_REQUIRES(CURRENT_COMPONENT_NAME)
  REQUIRES_SERVICE(udf_registration),
  REQUIRES_SERVICE(component_sys_variable_register),
END_COMPONENT_REQUIRES();

BEGIN_COMPONENT_METADATA(CURRENT_COMPONENT_NAME)
  METADATA("mysql.author", "Percona Corporation"),
  METADATA("mysql.license", "GPL"),
END_COMPONENT_METADATA();

DECLARE_COMPONENT(CURRENT_COMPONENT_NAME, CURRENT_COMPONENT_NAME_STR)
  component_init,
  component_deinit,
END_DECLARE_COMPONENT();
// clang-format on

DECLARE_LIBRARY_COMPONENTS &COMPONENT_REF(CURRENT_COMPONENT_NAME)
    END_DECLARE_LIBRARY_COMPONENTS
'''
s=s.rstrip('\n')+'\n'+TAIL
# re-wrap the lines touched by the sys_var rename with clang-format (only those lines)
lines=s.split('\n')
touched=[i+1 for i,l in enumerate(lines) if 'mysql_service_component_sys_variable_register->get_variable(' in l]
if touched:
    with tempfile.NamedTemporaryFile('w',suffix='.cc',dir=os.getcwd(),delete=False) as t: t.write(s); tn=t.name
    args=['clang-format','--style=file','-i']
    for ln in touched: args.append(f'--lines={ln}:{ln+2}')
    subprocess.run(args+[tn],check=True)
    s=open(tn).read(); os.unlink(tn)
sys.stdout.write(s)

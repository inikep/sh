#!/usr/bin/env python3
# plugin CMakeLists.txt (stdin) -> component CMakeLists.txt (stdout), binlog_utils_udf case.
# The plugin's build-flag style at that commit is kept: directory-level ADD_DEFINITIONS/
# INCLUDE_DIRECTORIES stay directory-level; target_* calls move to the component target.
import sys
s = sys.stdin.read()
assert 'MYSQL_ADD_PLUGIN(binlog_utils_udf' in s, 'expected plugin form'
HEAD = '''# Copyright (c) 2023 Percona LLC and/or its affiliates. All rights reserved.

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2 of
# the License.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

option(WITH_BINLOG_UTILS_UDF "Build Binlog Utils component" ON)

if(WITH_BINLOG_UTILS_UDF)
  message(STATUS "Building Binlog Utils UDF component")
else()
  message(STATUS "Not building Binlog Utils UDF component")
  return()
endif()

# We are not interesting in profiling tests.
DISABLE_MISSING_PROFILE_WARNING()

MYSQL_ADD_COMPONENT(binlog_utils_udf
  binlog_utils_udf.cc
  LINK_LIBRARIES extra::rapidjson
  MODULE_ONLY
)

'''
TAIL = '''
IF(APPLE)
  SET_TARGET_PROPERTIES(component_binlog_utils_udf PROPERTIES LINK_FLAGS "-undefined dynamic_lookup")
ENDIF()
'''
if 'target_compile_definitions(binlog_utils_udf' in s:
    body = ('target_compile_definitions(component_binlog_utils_udf PRIVATE MYSQL_SERVER)\n'
            'target_include_directories(component_binlog_utils_udf SYSTEM PRIVATE ${BOOST_PATCHES_DIR} ${BOOST_INCLUDE_DIR})\n')
else:
    assert 'ADD_DEFINITIONS(-DMYSQL_SERVER)' in s
    body = ('ADD_DEFINITIONS(-DMYSQL_SERVER)\n\n'
            'INCLUDE_DIRECTORIES(SYSTEM ${BOOST_PATCHES_DIR} ${BOOST_INCLUDE_DIR})\n')
sys.stdout.write(HEAD + body + TAIL)

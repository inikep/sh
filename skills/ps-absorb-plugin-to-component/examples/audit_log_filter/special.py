import importlib.util
_sp = importlib.util.spec_from_file_location('subs', '/data/ps-replay-vps-8.1.0-build/alf/subs.py')
_m = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(_m)
TFILES = set(l.strip() for l in open('/data/ps-replay-vps-8.1.0-build/alf/test_ok.txt'))

import subprocess as _sp
_XL = {}
def _x_lines(p):
    # lines X itself has in this file are canonical: never rewrite them
    if p not in _XL:
        r = _sp.run(['git', '-C', '/data/percona-server-linear', 'show', f'4c08e7b0005a:{p}'], capture_output=True)
        _XL[p] = set(r.stdout.decode('utf-8', 'surrogateescape').split('\n')) if r.returncode == 0 else set()
    return _XL[p]

def adjust(sha, state, git):
    # canonicalise every component-side file after each backward step: clean merges copy
    # plugin-before lines verbatim (plugin include paths, LogPluginErr*, old sysvar names)
    for p, (mode, blob) in list(state.items()):
        if p in TFILES:
            continue
        data = git('cat-file', 'blob', blob)
        text = data.decode('utf-8', 'surrogateescape')
        keep = _x_lines(p)
        new = '\n'.join(l if l in keep else _m.subs(l) for l in text.split('\n'))
        if new != text:
            state[p] = (mode, git('hash-object', '-w', '--stdin', inp=new.encode('utf-8', 'surrogateescape')).decode().strip())

# PS-8789 (de4bbcf29c53) introduced SysVars::acquire/release_comp_registry_srv(); before it the
# registry was a lazily created static behind SysVars::get_comp_registry_srv().
_REG_OLD = {l.split()[0] for l in open('/data/ps-replay-vps-8.1.0-build/alf/touchers.txt') if l.strip()}
_TOUCHERS = [l.split()[0] for l in open('/data/ps-replay-vps-8.1.0-build/alf/touchers.txt') if l.strip()]
_REG_FROM = _TOUCHERS.index('de4bbcf29c536f58e132d8dd61b569de32db7c58')
_H_NEW = '''  /**
   * @brief Acquire component registry service.
   *
   * @return component registry service instance
   */
  static comp_registry_srv_t *acquire_comp_registry_srv() noexcept;

  /**
   * @brief Release component registry service.
   */
  static void release_comp_registry_srv() noexcept;

  /**
   * @brief Get component registry service instance.
   *
   * @return component registry service instance
   */
  static comp_registry_srv_t *get_comp_registry_srv() noexcept;
'''
_H_OLD = '''  /**
   * @brief Get component registry service instance.
   *
   * @return component registry service instance
   */
  static decltype(get_component_registry_service().get())
  get_comp_registry_srv() noexcept;
'''

def _edit(state, git, p, fn):
    if p not in state:
        return
    mode, blob = state[p]
    text = git('cat-file', 'blob', blob).decode('utf-8', 'surrogateescape')
    new = fn(text)
    if new != text:
        state[p] = (mode, git('hash-object', '-w', '--stdin', inp=new.encode('utf-8', 'surrogateescape')).decode().strip())

def _alf(text):
    text = text.replace('SysVars::acquire_comp_registry_srv()', 'SysVars::get_comp_registry_srv()')
    text = text.replace('      SysVars::release_comp_registry_srv();\n', '')
    text = text.replace('  SysVars::release_comp_registry_srv();\n\n', '')
    text = text.replace('  SysVars::release_comp_registry_srv();\n', '')
    return text

_adjust_subs = adjust
def adjust(sha, state, git):
    _adjust_subs(sha, state, git)
    if _TOUCHERS.index(sha) <= _REG_FROM:
        _edit(state, git, 'components/audit_log_filter/sys_vars.h', lambda t: t.replace(_H_NEW, _H_OLD))
        _edit(state, git, 'components/audit_log_filter/audit_log_filter.cc', _alf)

# PS-8042 (0f065017a900) moved the registry into SysVars; the component needs SysVars-level
# registry access before that too (SysVars::init/deinit, UDF registration), so keep the
# static accessor as component infrastructure in every earlier state.
_REG_SRV_FROM = _TOUCHERS.index('0f065017a9001658269e975460ca77b164381a27')
_H_INC = '#include "components/audit_log_filter/component_registry_service.h"\n'
_CC_DEF = '''decltype(get_component_registry_service().get())
SysVars::get_comp_registry_srv() noexcept {
  static auto comp_registry_srv = get_component_registry_service();
  return comp_registry_srv.get();
}
'''
def _h_reg(t):
    if 'get_comp_registry_srv() noexcept;' not in t:
        k = t.rindex('};\n\n}  // namespace audit_log_filter')
        cls = t.rindex('class SysVars {', 0, k)
        if ' private:\n' in t[cls:k]:   # instance-style class: keep the accessor public
            k = t.index(' public:\n', cls) + len(' public:\n')
            t = t[:k] + _H_OLD + '\n' + t[k:]
        else:
            t = t[:k] + '\n' + _H_OLD + t[k:]
    if _H_INC not in t:
        t = t.replace('#include "components/audit_log_filter/log_record_formatter/base.h"\n',
                      _H_INC + '#include "components/audit_log_filter/log_record_formatter/base.h"\n', 1)
    return t
def _cc_reg(t):
    if 'SysVars::get_comp_registry_srv() noexcept {' not in t:
        k = t.rindex('}  // namespace audit_log_filter')
        t = t[:k] + _CC_DEF + '\n' + t[k:]
    return t

_adjust_reg = adjust
def adjust(sha, state, git):
    _adjust_reg(sha, state, git)
    if _TOUCHERS.index(sha) <= _REG_SRV_FROM:
        _edit(state, git, 'components/audit_log_filter/sys_vars.h', _h_reg)
        _edit(state, git, 'components/audit_log_filter/sys_vars.cc', _cc_reg)

# audit_log_json_handler.{h,cc} were lost in vps-8.1.0-build3 (present in vps-8.1.0-build2 at
# 66aa48f1146a, removed by 3c50770bc12b): commits 4df9a792ae36..8b3a73b05cea list and include
# them. Restore them for that range; 0f065017a900 replaces them with json_reader/.
_JH = {'components/audit_log_filter/audit_log_json_handler.h': '66aa48f1146a:plugin/audit_log_filter/audit_log_json_handler.h',
       'components/audit_log_filter/audit_log_json_handler.cc': '66aa48f1146a:plugin/audit_log_filter/audit_log_json_handler.cc'}
_JH_ADD = '0f065017a9001658269e975460ca77b164381a27'   # stepping back over it: files exist before it
_JH_DEL = '4df9a792ae3628a660efb53ef86f1efcbfaf7732'   # stepping back over it: files did not exist before
_adjust_jh = adjust
def adjust(sha, state, git):
    _adjust_jh(sha, state, git)
    if sha == _JH_ADD:
        for p, src in _JH.items():
            text = git('cat-file', 'blob', src).decode('utf-8', 'surrogateescape')
            new = '\n'.join(_m.subs(l) for l in text.split('\n'))
            state[p] = ('100644', git('hash-object', '-w', '--stdin', inp=new.encode('utf-8', 'surrogateescape')).decode().strip())
    elif sha == _JH_DEL:
        for p in _JH:
            state.pop(p, None)

# audit_udf.cc: the component's has_audit_admin_privilege() needs security_context.h directly
# (the plugin got it transitively through headers that older states do not have).
_SC_INC = '#include <mysql/components/services/security_context.h>\n'
def _udf_inc(t):
    if ('has_audit_admin_privilege' in t or 'Security_context_handle' in t) and _SC_INC not in t:
        anchor = '#include <mysql/components/services/mysql_current_thread_reader.h>\n'
        assert anchor in t
        t = t.replace(anchor, anchor + _SC_INC, 1)
    return t
_adjust_sc = adjust
def adjust(sha, state, git):
    _adjust_sc(sha, state, git)
    _edit(state, git, 'components/audit_log_filter/audit_udf.cc', _udf_inc)

# Before 9b1a65295bae the plugin tests cleaned up with DELETE FROM statements instead of
# audit_tables_cleanup.inc (the plugin stayed loaded for the whole suite). Component tests
# must uninstall what they installed, so pair every audit_comp_install.inc with an uninstall.
_UNINST_FROM = _TOUCHERS.index('9b1a65295bae55d7caafb24fec73ccf76e28ae29')
def _pair_uninstall(t):
    if '--source ../inc/audit_comp_install.inc' in t and '--source ../inc/audit_comp_uninstall.inc' not in t:
        t = t.rstrip('\n') + '\n\n--source ../inc/audit_comp_uninstall.inc\n'
    return t
_adjust_un = adjust
def adjust(sha, state, git):
    _adjust_un(sha, state, git)
    if _TOUCHERS.index(sha) <= _UNINST_FROM:
        for p in list(state):
            if p.startswith('mysql-test/suite/component_audit_log_filter/t/') and p.endswith('.test'):
                _edit(state, git, p, _pair_uninstall)

# Standard headers the plugin got transitively (mysql/plugin_audit.h, sql/ headers) but the
# component has to include directly.
import re as _re
_STD_NEEDS = [('std::stringstream', '<sstream>'), ('std::ostringstream', '<sstream>'),
              ('strlen(', '<cstring>'), ('std::strlen(', '<cstring>')]
def _ensure_std(t):
    for sym, hdr in _STD_NEEDS:
        if sym not in t or f'#include {hdr}' in t:
            continue
        if hdr == '<cstring>' and '#include <string.h>' in t:
            continue
        lines = t.split('\n')
        std = [i for i, l in enumerate(lines) if _re.fullmatch(r'#include <[a-z_]+>', l)]
        inc = f'#include {hdr}'
        if std:
            pos = next((i for i in std if lines[i] > inc), std[-1] + 1)
            lines.insert(pos, inc)
        else:
            last = max(i for i, l in enumerate(lines) if l.startswith('#include '))
            lines[last + 1:last + 1] = ['', inc]
        t = '\n'.join(lines)
    return t
_STD_FILES = {'components/audit_log_filter/audit_rule.cc': ['<sstream>'],
              'components/audit_log_filter/log_record_formatter/base.cc': ['<cstring>']}
_adjust_std = adjust
def adjust(sha, state, git):
    _adjust_std(sha, state, git)
    for p, hdrs in _STD_FILES.items():
        global _STD_NEEDS
        saved = _STD_NEEDS
        _STD_NEEDS = [(s_, h_) for s_, h_ in saved if h_ in hdrs]
        _edit(state, git, p, _ensure_std)
        _STD_NEEDS = saved

# 80ffe4128040 added the session filter id (plugin: filter_id THDVAR). The component replaces
# the variable with the audit_log_session_filter_id() UDF (X-created code and tests), which
# therefore must not exist before that commit.
_SFID = '80ffe412804012100ddeabec44f2c151dd74d257'
def _udf_h_sfid(t):
    i = t.index('  /**\n   * @brief Init function for audit_log_session_filter_id UDF.')
    j = t.index('  static void audit_log_session_filter_id_udf_deinit(UDF_INIT *initid);\n\n', i)
    return t[:i] + t[j + len('  static void audit_log_session_filter_id_udf_deinit(UDF_INIT *initid);\n\n'):]
def _udf_cc_sfid(t):
    i = t.index('bool AuditUdf::audit_log_session_filter_id_udf_init(')
    end = 'void AuditUdf::audit_log_session_filter_id_udf_deinit(UDF_INIT *) {}\n'
    j = t.index(end, i) + len(end)
    if t[j:j + 1] == '\n':
        j += 1
    elif t[i - 1:i] == '\n' and t[i - 2:i - 1] == '\n':
        i -= 1
    return t[:i] + t[j:]
_adjust_sfid = adjust
def adjust(sha, state, git):
    _adjust_sfid(sha, state, git)
    if sha == _SFID:
        _edit(state, git, 'components/audit_log_filter/audit_udf.h', _udf_h_sfid)
        _edit(state, git, 'components/audit_log_filter/audit_udf.cc', _udf_cc_sfid)
        for p in ('mysql-test/suite/component_audit_log_filter/t/udf_audit_log_session_filter_id.test',
                  'mysql-test/suite/component_audit_log_filter/r/udf_audit_log_session_filter_id.result'):
            state.pop(p, None)

# 8492b62f91a6 introduced has_audit_admin_privilege() (AUDIT_ADMIN check for the filtering
# UDFs) and the user/host wildcard check; before it only audit_log_rotate() checked AUDIT_ADMIN,
# inline. Older full-file resolutions were written while the helper was still in the chain.
_ADMIN_FROM = _TOUCHERS.index('8492b62f91a6c8194a116099816e6c30f88eb0b4')
_ROTATE_INLINE = '''  my_service<SERVICE_TYPE(mysql_current_thread_reader)> thd_reader_srv(
      "mysql_current_thread_reader", SysVars::get_comp_registry_srv());
  my_service<SERVICE_TYPE(mysql_thd_security_context)> security_context_service(
      "mysql_thd_security_context", SysVars::get_comp_registry_srv());
  my_service<SERVICE_TYPE(global_grants_check)> grants_check_service(
      "global_grants_check", SysVars::get_comp_registry_srv());

  MYSQL_THD thd;
  Security_context_handle ctx;

  if (!security_context_service.is_valid() ||
      !grants_check_service.is_valid() || thd_reader_srv->get(&thd) ||
      security_context_service->get(thd, &ctx)) {
    std::snprintf(message, MYSQL_ERRMSG_SIZE, "ERROR: Internal error");
    return true;
  }

  if (!grants_check_service->has_global_grant(ctx,
                                              STRING_WITH_LEN("AUDIT_ADMIN"))) {
    my_error(ER_SPECIFIC_ACCESS_DENIED_ERROR, MYF(0), "AUDIT_ADMIN");
    return true;
  }
'''
_CALL = '  if (!has_audit_admin_privilege(message)) {\n    return true;\n  }\n'
def _pre_admin(t):
    if 'bool has_audit_admin_privilege(char *message) {' in t:
        i = t.index('bool has_audit_admin_privilege(char *message) {')
        j = t.index('\n}\n\n', i) + 4
        t = t[:i] + t[j:]
    r = t.find('bool AuditUdf::audit_log_rotate_udf_init(')
    if r >= 0 and t.find(_CALL, r) >= 0 and t.find(_CALL, r) < t.find('\n}\n', r):
        k = t.find(_CALL, r)
        t = t[:k] + _ROTATE_INLINE + t[k + len(_CALL):]
    t = t.replace(_CALL + '\n', '').replace(_CALL, '')
    t = t.replace('  const std::regex deprecated_symbols_regex("[\\\\*|\\\\%]");\n', '')
    for what in ('user', 'host'):
        blk = ('      if (std::regex_search(user_%s_match.str(), deprecated_symbols_regex)) {\n'
               '        std::snprintf(message, MYSQL_ERRMSG_SIZE,\n'
               '                      "Wrong argument: bad %s name format");\n'
               '        return nullptr;\n      }\n\n') % ('name' if what == 'user' else 'host', what)
        t = t.replace(blk, '')
    if 'Security_context_handle' not in t:
        t = t.replace(_SC_INC, '')
    return t
_adjust_admin = adjust
def adjust(sha, state, git):
    _adjust_admin(sha, state, git)
    if _TOUCHERS.index(sha) <= _ADMIN_FROM:
        _edit(state, git, 'components/audit_log_filter/audit_udf.cc', _pre_admin)

# The component init keeps its scope guard in every state; <scope_guard.h> must follow it.
def _scope_inc(t):
    if 'create_scope_guard(' in t and '#include <scope_guard.h>' not in t:
        assert '\n#include <array>\n' in t
        t = t.replace('\n#include <array>\n', '\n#include <scope_guard.h>\n#include <array>\n', 1)
    elif 'create_scope_guard(' not in t:
        t = t.replace('#include <scope_guard.h>\n', '')
    return t
_adjust_scope = adjust
def adjust(sha, state, git):
    _adjust_scope(sha, state, git)
    _edit(state, git, 'components/audit_log_filter/audit_log_filter.cc', _scope_inc)

# Component tests must set up / tear down what the plugin suite got globally (see pair_install.py).
import sys as _sys
_sys.path.insert(0, '/data/ps-replay-vps-8.1.0-build/alf')
import pair_install as _pi
_TDIR = 'mysql-test/suite/component_audit_log_filter/t/'
_adjust_pair = adjust
def adjust(sha, state, git):
    _adjust_pair(sha, state, git)
    def read(inc):
        p = _TDIR + inc
        return git('cat-file', 'blob', state[p][1]).decode('utf-8', 'surrogateescape') if p in state else None
    for p in list(state):
        if p.startswith(_TDIR) and p.endswith('.test'):
            _edit(state, git, p, lambda t: _pi.pair(t, read))

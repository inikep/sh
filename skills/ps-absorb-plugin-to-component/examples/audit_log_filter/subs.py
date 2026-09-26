import re
VARS = ['buffer_size','flush','syslog_ident','compression','database','disable','encryption','file','format','format_unix_timestamp','handler',
        'key_derivation_iterations_count_mean','syslog_priority','syslog_tag','max_size','password_history_keep_days',
        'prune_seconds','rotate_on_size','strategy','syslog_facility','read_buffer_size']
V = '|'.join(sorted(VARS, key=len, reverse=True))
def subs(l):
    l = l.replace('get_comp_regystry_srv', 'get_comp_registry_srv')
    l = l.replace('LogPluginErrMsg(', 'LogComponentErr(').replace('LogPluginErr(', 'LogComponentErr(')
    l = l.replace('"plugin/audit_log_filter/', '"components/audit_log_filter/')
    # option files: --audit_log_filter_X=... -> --loose-audit_log_filter.X=...
    l = re.sub(r'^--audit_log_filter_(%s)=' % V, r'--loose-audit_log_filter.\1=', l)
    l = re.sub(r'@@session\.audit_log_filter_read_buffer_size\b', '@@global.audit_log_filter.read_buffer_size', l)
    l = re.sub(r'(@@global\.|@@session\.|@@)audit_log_filter_(%s)\b' % V, r'\1audit_log_filter.\2', l)
    l = re.sub(r'\b(SET\s+(?:GLOBAL|SESSION|PERSIST|PERSIST_ONLY)?\s*)audit_log_filter_(%s)\b' % V, r'\1audit_log_filter.\2', l, flags=re.I)
    if l.strip() == '--source audit_tables_init.inc': l = l.replace('audit_tables_init.inc', '../inc/audit_tables_init.inc')
    if l.strip() == '--source audit_tables_cleanup.inc': l = l.replace('audit_tables_cleanup.inc', '../inc/audit_tables_cleanup.inc')
    l = re.sub(r"(?<!=)'audit_log_filter_(%s)'" % V, r"'audit_log_filter.\1'", l)
    l = re.sub(r'(?<!^)--audit_log_filter_(%s)=' % V, r'--audit_log_filter.\1=', l)
    l = l.replace("Plugin audit_log_filter reported:", "Component audit_log_filter reported:")
    l = re.sub(r'^audit_log_filter_(%s)=' % V, r'loose-audit_log_filter.\1=', l)
    l = re.sub(r'Truncated incorrect audit_log_filter_(%s) value' % V, r'Truncated incorrect audit_log_filter.\1 value', l)
    l = re.sub(r'\bSET SESSION audit_log_filter\.read_buffer_size\b', 'SET GLOBAL audit_log_filter.read_buffer_size', l)
    l = l.replace('@@session.audit_log_filter_filter_id', 'audit_log_session_filter_id()')
    l = re.sub(r'\[Bad audit_log_filter_(%s) value\]' % V, r'[Bad audit_log_filter.\1 value]', l)
    l = re.sub(r'Both audit_log_filter_max_size and audit_log_filter_prune_seconds', 'Both audit_log_filter.max_size and audit_log_filter.prune_seconds', l)
    l = re.sub(r'^--audit-log-filter\.(%s)=' % '|'.join(v.replace('_','-') for v in VARS), lambda m: '--loose-audit_log_filter.' + m.group(1).replace('-','_') + '=', l)
    return l

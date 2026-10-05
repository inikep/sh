import re
def includes(text):
    return re.findall(r'^--source\s+(\S+\.inc)\s*$', text, re.M)
def has(text, what, read, depth=0):
    if what in text:
        return True
    if depth > 3:
        return False
    for inc in includes(text):
        if inc.startswith('include/'):
            continue
        t = read(inc)
        if t is not None and has(t, what, read, depth + 1):
            return True
    return False
TINIT = '--source ../inc/audit_tables_init.inc'
TCLEAN = '--source ../inc/audit_tables_cleanup.inc'
INST = '--source ../inc/audit_comp_install.inc'
UNINST = '--source ../inc/audit_comp_uninstall.inc'
HEAD = '--source include/have_component_audit_log.inc\n'
def pair(text, read):
    """Component tests set up and tear down what the plugin suite got globally (plugin loaded by
    suite.opt, audit tables created by MTR bootstrap before 9b1a65295bae)."""
    if not has(text, INST, read):
        assert text.startswith(HEAD), text[:80]
        add = ([] if has(text, TINIT, read) else [TINIT]) + [INST]
        text = HEAD + '\n'.join(add) + '\n' + text[len(HEAD):]
        tail = ([] if has(text, UNINST, read) else [UNINST]) + ([] if has(text, TCLEAN, read) else [TCLEAN])
        if tail:
            text = text.rstrip('\n') + '\n\n' + '\n'.join(tail) + '\n'
    elif has(text, TINIT, read) and not has(text, TCLEAN, read):
        tail = ([] if has(text, UNINST, read) else [UNINST]) + [TCLEAN]
        text = text.rstrip('\n') + '\n\n' + '\n'.join(tail) + '\n'
    return text

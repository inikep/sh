#!/usr/bin/env python3
"""Phase 4 — catalogue per-commit introduced features.

For each commit, mine `+` lines for:
  * new files (new in this commit) bucketed by area
  * file-structure tags from changed paths (MTR suites, plugin dirs, sql/,
    storage/innobase/ modules)
  * plugin sysvars       MYSQL_(SYSVAR|THDVAR)_*
  * server sysvars       static Sys_var_* Sys_…("name", …)
  * long options         { "name", OPT_*, …, GET_… }
  * SQL commands         SQLCOM_<NAME>
  * yacc tokens          %token NAME (.yy / .y files)
  * InnoDB globals       srv_* / innobase_* / log_online_* externs
  * notable macros       UPPER_SNAKE ≥ 6 chars from symbols.json added_defs
  * notable types        PascalCase ≥ 8 chars from symbols.json added_defs

Output:
  $WORK_DIR/features-report.md   — per-commit detail + flat catalog
  $WORK_DIR/features.json        — same data in machine-readable form
"""
import json, re, subprocess, sys
from collections import defaultdict, OrderedDict
from _common import WORK, commit_subject

commits = json.load(open(f'{WORK}/commits.json'))
symbols = json.load(open(f'{WORK}/symbols.json'))

RE_PLUGIN_SYSVAR = re.compile(r'\bMYSQL_(?:SYSVAR|THDVAR)_[A-Z]+\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,', re.M)
RE_SERVER_SYSVAR = re.compile(r'static\s+Sys_var_[A-Za-z_]+\s+Sys_[A-Za-z0-9_]+\s*\(\s*"([A-Za-z0-9_]+)"')
RE_LONGOPT       = re.compile(r'\{\s*"([a-zA-Z0-9][-a-zA-Z0-9_]*)"\s*,\s*OPT_[A-Z0-9_]+\s*,')
RE_SQLCOM        = re.compile(r'\bSQLCOM_([A-Z][A-Z0-9_]+)\b')
RE_YACC_TOKEN    = re.compile(r'^\s*%token\s+(?:<\w+>\s+)?([A-Z][A-Z0-9_]*)', re.M)
RE_INNOBASE_GBL  = re.compile(r'^\s*(?:UNIV_INTERN\s+|extern\s+)?[A-Za-z_][\w\s\*]*\s+(srv_[a-z_]+|innobase_[a-z_]+|log_online_[a-z_]+)\s*[\(=;]', re.M)

NOISE = {'NULL', 'TRUE', 'FALSE', 'YES', 'NO', 'TYPE', 'STATUS'}
GENERIC_TEST_PREFIXES = (
    'percona_', 'innodb_', 'mysql_', 'rpl_', 'sys_vars_', 'bug_', 'ps_'
)
GENERIC_TAG_WORDS = {
    'basic', 'func', 'test', 'tests', 'result', 'master', 'slave', 'include',
    'main', 'misc', 'common', 'helper', 'helpers', 'debug', 'embedded',
    'mysql', 'mysqld', 'server', 'client', 'sql', 'handler', 'item', 'field',
    'table', 'filesort', 'protocol', 'log', 'trx', 'srv', 'buf', 'dict',
}
GENERIC_PATH_TAGS = {
    'mysql_test', 'sql_yacc', 'sql_parse', 'sql_class', 'mysqld', 'handler',
    'sql_base', 'sql_cmd', 'sql_show', 'sql_lex', 'sql_select', 'sql_insert',
    'sql_update', 'sql_delete', 'sql_table', 'sql_reload', 'sql_priv',
    'ha_innodb', 'trx0trx', 'trx0sys', 'srv0srv', 'buf0buf', 'dict0dict',
    'row0mysql', 'row0sel', 'row0ins', 'row0upd', 'btr0cur', 'btr0sea',
    'lock0lock', 'log0log', 'log0recv', 'fil0fil', 'os0file',
}
GENERIC_SQLCOMS = {
    'SELECT', 'INSERT', 'INSERT_SELECT', 'UPDATE', 'DELETE', 'DELETE_MULTI',
    'REPLACE', 'REPLACE_SELECT', 'CREATE_TABLE', 'ALTER_TABLE', 'DROP_TABLE',
    'SHOW_TABLES', 'SHOW_FIELDS', 'SHOW_KEYS', 'SHOW_VARIABLES',
}

def norm_tag(s):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_').lower()
    s = re.sub(r'_+', '_', s)
    return s

def strip_test_prefixes(stem):
    out = stem
    out = re.sub(r'_(basic|func|master|slave|debug|embedded)$', '', out)
    changed = True
    while changed:
        changed = False
        for prefix in GENERIC_TEST_PREFIXES:
            if out.startswith(prefix) and len(out) > len(prefix) + 3:
                out = out[len(prefix):]
                changed = True
        out2 = re.sub(r'_(basic|func|master|slave|debug|embedded)$', '', out)
        if out2 != out:
            out = out2
            changed = True
    return out

def useful_tag(tag):
    if not tag or len(tag) < 4:
        return False
    parts = [p for p in tag.split('_') if p]
    if not parts or all(p in GENERIC_TAG_WORDS for p in parts):
        return False
    if re.fullmatch(r'(bug|lp|mdev)?_?\d+', tag):
        return False
    return True

def add_tag(candidates, tag, source, weight):
    tag = norm_tag(tag)
    if useful_tag(tag):
        candidates[tag].append((source, weight))

def file_stem(path):
    base = path.rsplit('/', 1)[-1]
    stem = base.rsplit('.', 1)[0]
    stem = re.sub(r'-(master|slave|debug|embedded)$', '', stem)
    return norm_tag(stem)

def mtr_stems(paths):
    stems = []
    for p in paths:
        if not p.startswith('mysql-test/'):
            continue
        base = strip_test_prefixes(file_stem(p))
        if useful_tag(base):
            stems.append((base, p))
    return stems

def path_tags(paths, new_files):
    tags = []
    new_set = set(new_files)
    for p in paths:
        parts = p.split('/')
        is_new = p in new_set
        weight = 5 if is_new else 2
        source_kind = 'new file path' if is_new else 'changed path'

        if p.startswith('plugin/') and len(parts) >= 2:
            tags.append((norm_tag(parts[1]), f'{source_kind} `{p}`', weight + 2))
            if len(parts) >= 3:
                stem = file_stem(p)
                if stem not in GENERIC_PATH_TAGS:
                    tags.append((stem, f'{source_kind} `{p}`', weight))

        elif p.startswith('mysql-test/'):
            if is_new:
                # New MTR files are already scored by mtr_stems(new_files).
                # Changed MTR paths still carry useful file-structure evidence.
                continue
            for stem, path in mtr_stems([p]):
                tags.append((stem, f'{source_kind} `{path}`', weight + 2))

        elif p.startswith('sql/') and p.endswith(('.cc', '.h')):
            stem = file_stem(p)
            if stem not in GENERIC_PATH_TAGS:
                tags.append((stem, f'{source_kind} `{p}`', weight))

        elif p.startswith('storage/innobase/') and p.endswith(('.cc', '.c', '.h', '.ic')):
            if len(parts) >= 3:
                module = norm_tag(f'innodb_{parts[2]}')
                if module not in GENERIC_PATH_TAGS:
                    tags.append((module, f'{source_kind} `{p}`', max(1, weight - 1)))
            stem = file_stem(p)
            if stem not in GENERIC_PATH_TAGS:
                tags.append((stem, f'{source_kind} `{p}`', weight))

        elif p.startswith(('scripts/', 'client/', 'include/', 'mysys/')) and p.endswith(('.c', '.cc', '.h', '.sh', '.pl')):
            stem = file_stem(p)
            if stem not in GENERIC_PATH_TAGS:
                tags.append((stem, f'{source_kind} `{p}`', max(1, weight - 1)))

    return tags

def derive_feature_tags(info, paths):
    candidates = defaultdict(list)

    for s in info.get('plugin_sysvars', []):
        add_tag(candidates, s, f'plugin sysvar `{s}`', 8)
    for s in info.get('server_sysvars', []):
        add_tag(candidates, s, f'server sysvar `{s}`', 8)
    for s in info.get('longopts', []):
        add_tag(candidates, s, f'long option `{s}`', 5)
    for s in info.get('innodb_globals', []):
        tag = re.sub(r'^(srv|innobase|log_online)_', '', s)
        add_tag(candidates, tag, f'InnoDB global `{s}`', 4)

    for stem, path in mtr_stems(info.get('new_files', [])):
        add_tag(candidates, stem, f'MTR test `{path}`', 7)
    for tag, source, weight in path_tags(paths, info.get('new_files', [])):
        add_tag(candidates, tag, source, weight)

    for m in info.get('notable_macros', []):
        tag = re.sub(r'^(MYSQL|MYSQLD|INNODB|SRV|SQL|THD)_', '', m, flags=re.I)
        add_tag(candidates, tag, f'macro `{m}`', 2)
    for t in info.get('notable_types', []):
        add_tag(candidates, t, f'type `{t}`', 2)

    # SQLCOM_* names are often generic operation names. Use them only as a
    # last-resort tag source; tests/sysvars/options usually carry the feature.
    for s in info.get('sql_commands', []):
        if s in GENERIC_SQLCOMS:
            continue
        add_tag(candidates, f"sqlcom_{s.lower()}", f'SQL command `SQLCOM_{s}`', 3)
    for s in info.get('yacc_tokens', []):
        add_tag(candidates, s, f'yacc token `{s}`', 2)

    scored = []
    for tag, hits in candidates.items():
        score = sum(w for _, w in hits)
        sources = []
        seen = set()
        for source, _ in sorted(hits, key=lambda x: -x[1]):
            if source not in seen:
                sources.append(source)
                seen.add(source)
        scored.append((score, tag, sources[:4]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [
        {'tag': tag, 'score': score, 'sources': sources}
        for score, tag, sources in scored[:8]
    ]

def added_lines(sha, paths):
    r = subprocess.run(
        ['git', 'show', '--format=', '--no-renames', '-U0', sha],
        text=True, capture_output=True, errors='replace'
    )
    cur, keep = None, False
    for line in r.stdout.splitlines():
        if line.startswith('diff --git'):
            m = re.match(r'diff --git a/(.*?) b/', line)
            cur = m.group(1) if m else None
            keep = (cur in paths) if paths is not None else True
            continue
        if not keep:
            continue
        if line.startswith('+') and not line.startswith('+++'):
            yield cur, line[1:]

def extract(c):
    out = OrderedDict()
    files = c.get('files', {})
    new_files = [p for p, info in files.items() if info.get('new')]
    out['new_files'] = new_files
    paths = set(files.keys())

    psv, ssv, opts, sqlcoms, yacc_t, innogbl = set(), set(), set(), set(), set(), set()
    yacc_files = {p for p in paths if p.endswith(('.yy', '.y'))}
    per_path_buf = defaultdict(list)
    for p, ln in added_lines(c['sha'], paths):
        per_path_buf[p].append(ln)

    for p, buf in per_path_buf.items():
        body = '\n'.join(buf)
        if 'ha_innodb' in p or 'plugin' in p or p.endswith(('.cc', '.c')):
            for m in RE_PLUGIN_SYSVAR.finditer(body):
                psv.add(m.group(1))
        if p.endswith('sys_vars.cc') or p.endswith('mysqld.cc'):
            for m in RE_SERVER_SYSVAR.finditer(body):
                ssv.add(m.group(1))
        if p.endswith(('mysqld.cc', 'mysqld.h')) or 'sys_vars' in p or 'mysqld_safe' in p:
            for m in RE_LONGOPT.finditer(body):
                opts.add(m.group(1))
        for m in RE_SQLCOM.finditer(body):
            sqlcoms.add(m.group(1))
        if p in yacc_files:
            for m in RE_YACC_TOKEN.finditer(body):
                yacc_t.add(m.group(1))
        if 'innobase' in p or p.endswith(('.cc', '.c', '.h', '.ic')):
            for m in RE_INNOBASE_GBL.finditer(body):
                innogbl.add(m.group(1))

    out['plugin_sysvars'] = sorted(psv)
    out['server_sysvars'] = sorted(ssv)
    out['longopts']       = sorted(opts)
    out['sql_commands']   = sorted(sqlcoms)
    out['yacc_tokens']    = sorted(yacc_t)
    out['innodb_globals'] = sorted(innogbl)

    syms = set(symbols.get(str(c['idx']), {}).get('added', [])) - NOISE
    macros = sorted(s for s in syms if s.isupper() and len(s) >= 6)
    types  = sorted(s for s in syms if s[0].isupper() and not s.isupper() and len(s) >= 8)
    out['notable_macros'] = macros[:25]
    out['notable_types']  = types[:15]
    out['feature_tags'] = derive_feature_tags(out, paths)
    return out

per_commit_features = {}
flat = {
    'plugin_sysvars': defaultdict(list),
    'server_sysvars': defaultdict(list),
    'longopts':       defaultdict(list),
    'sql_commands':   defaultdict(list),
    'yacc_tokens':    defaultdict(list),
}

# write markdown report
with open(f'{WORK}/features-report.md', 'w') as f:
    f.write("# Features introduced per commit\n\n")
    f.write(f"Range: {len(commits)} commits\n\n")
    for c in commits:
        info = extract(c)
        per_commit_features[c['idx']] = info
        if not any(info[k] for k in info):
            continue
        subj = commit_subject(c)[:100]
        f.write(f"## idx {c['idx']:2d}  {c['short']}  — {subj}\n")
        if info['new_files']:
            buckets = defaultdict(list)
            for p in info['new_files']:
                if p.startswith('mysql-test/'):
                    buckets['MTR test'].append(p)
                elif p.startswith('include/') or p.endswith('.h'):
                    buckets['header'].append(p)
                elif p.startswith('storage/innobase/'):
                    buckets['InnoDB'].append(p)
                elif p.startswith('sql/'):
                    buckets['sql/'].append(p)
                elif p.startswith('plugin/'):
                    buckets['plugin'].append(p)
                elif p.startswith('scripts/'):
                    buckets['scripts'].append(p)
                else:
                    buckets['other'].append(p)
            for cat, lst in buckets.items():
                if cat == 'MTR test':
                    stems = sorted(set(re.sub(r'^mysql-test/.*?/', '', p).rsplit('.', 1)[0] for p in lst))
                    f.write(f"  - new MTR ({len(lst)} files): {', '.join(stems[:6])}{'…' if len(stems)>6 else ''}\n")
                else:
                    head = lst[:5]
                    more = f" (+{len(lst)-5} more)" if len(lst) > 5 else ""
                    f.write(f"  - new {cat} files: {', '.join(head)}{more}\n")
        if info['plugin_sysvars']:
            f.write(f"  - new plugin sysvars: `{'`, `'.join(info['plugin_sysvars'])}`\n")
            for s in info['plugin_sysvars']:
                flat['plugin_sysvars'][s].append(c['idx'])
        if info['server_sysvars']:
            f.write(f"  - new server sysvars: `{'`, `'.join(info['server_sysvars'])}`\n")
            for s in info['server_sysvars']:
                flat['server_sysvars'][s].append(c['idx'])
        if info['longopts']:
            new_opts = [o for o in info['longopts'] if o not in info['plugin_sysvars'] and o not in info['server_sysvars']]
            if new_opts:
                f.write(f"  - new long-options: `{'`, `'.join(new_opts[:12])}`{'…' if len(new_opts)>12 else ''}\n")
                for s in new_opts:
                    flat['longopts'][s].append(c['idx'])
        if info['sql_commands']:
            f.write(f"  - new SQL commands: `SQLCOM_{'`, `SQLCOM_'.join(info['sql_commands'])}`\n")
            for s in info['sql_commands']:
                flat['sql_commands'][s].append(c['idx'])
        if info['yacc_tokens']:
            f.write(f"  - new yacc tokens: `{'`, `'.join(info['yacc_tokens'][:10])}`{'…' if len(info['yacc_tokens'])>10 else ''}\n")
            for s in info['yacc_tokens']:
                flat['yacc_tokens'][s].append(c['idx'])
        if info['innodb_globals']:
            keep = [s for s in info['innodb_globals'] if len(s) >= 6][:10]
            if keep:
                f.write(f"  - InnoDB globals: `{'`, `'.join(keep)}`{'…' if len(info['innodb_globals'])>10 else ''}\n")
        if info['notable_macros']:
            f.write(f"  - new macros: `{'`, `'.join(info['notable_macros'][:12])}`{'…' if len(info['notable_macros'])>12 else ''}\n")
        if info['notable_types']:
            f.write(f"  - new types: `{'`, `'.join(info['notable_types'][:8])}`{'…' if len(info['notable_types'])>8 else ''}\n")
        if info['feature_tags']:
            tags = [f"`{x['tag']}`" for x in info['feature_tags'][:5]]
            f.write(f"  - content feature tags: {', '.join(tags)}\n")
        f.write("\n")

    f.write("\n# Flat catalog\n\n")
    for label, key in (
        ("Plugin sysvars (`innodb_*`, etc.)", 'plugin_sysvars'),
        ("Server sysvars (sql/sys_vars.cc)", 'server_sysvars'),
        ("Long options (mysqld / mysqld_safe)", 'longopts'),
        ("SQL commands (SQLCOM_*)", 'sql_commands'),
        ("Yacc tokens", 'yacc_tokens'),
    ):
        d = flat[key]
        if not d:
            continue
        f.write(f"## {label}  ({len(d)} entries)\n\n")
        for name in sorted(d.keys()):
            f.write(f"  - `{name}` — idx {d[name]}\n")
        f.write("\n")

json.dump(per_commit_features, open(f'{WORK}/features.json', 'w'), indent=1)
print(f"wrote {WORK}/features-report.md and features.json", file=sys.stderr)

#!/usr/bin/env python3
"""Phase 3 — extract per-commit C/C++ symbol sets and per-pair symbol edges.

Output:
  $WORK_DIR/symbols.json        — per-commit { added, removed, refs, contexts }
  $WORK_DIR/symbol-edges.tsv    — per-pair edge contributions
"""
import json, re, subprocess, sys
from _common import WORK

commits = json.load(open(f'{WORK}/commits.json'))

CXX_EXTS = re.compile(r'\.(?:h|c|cc|cxx|cpp|hh|hpp|hxx|i|ic)$', re.I)
def is_cxx_path(p):
    if not CXX_EXTS.search(p):
        return False
    if p.startswith('mysql-test/'):
        return False
    if p.endswith('.h.pp'):
        return False
    return True

RE_DEFINE         = re.compile(r'#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)')
RE_TYPEDEF_SIMPLE = re.compile(r'\btypedef\b[^;]*?\b([A-Za-z_][A-Za-z0-9_]*)\s*[;\[]')
RE_STRUCT         = re.compile(r'\b(?:struct|union|class|enum)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[{:;]')
RE_FUNC           = re.compile(
    r'^\s*(?:static\s+|inline\s+|extern\s+|virtual\s+)*'
    r'(?:[A-Za-z_][A-Za-z0-9_:*<>\s,&]*?\s+\**)'
    r'([A-Za-z_][A-Za-z0-9_]*)'
    r'\s*\([^;]*\)'
    r'\s*(?:const\s*)?(?:throw\s*\([^)]*\)\s*)?(?:noexcept\s*)?'
    r'(?:\{|$)')
RE_IDENT          = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]{3,})\b')

KEYWORDS = set("""
auto break case char const continue default do double else enum extern float for goto
if inline int long register return short signed sizeof static struct switch typedef
union unsigned void volatile while bool true false class friend new delete operator
private protected public template this throw try catch using namespace virtual
explicit mutable typename
NULL TRUE FALSE FILE size_t ssize_t int8_t int16_t int32_t int64_t
uint8_t uint16_t uint32_t uint64_t intptr_t uintptr_t ptrdiff_t off_t time_t
__attribute__ __FILE__ __LINE__ __func__ __FUNCTION__ __cplusplus
""".split())

NOISE = set("""
DBUG_ENTER DBUG_RETURN DBUG_VOID_RETURN DBUG_PRINT DBUG_ASSERT DBUG_ABORT
LINT_INIT ut_ad ut_a ut_error ut_print_timestamp my_error
THD::THD thd_proc_info my_printf_error sql_print_error sql_print_warning
sql_print_information mysql_mutex_lock mysql_mutex_unlock pthread_mutex_lock
pthread_mutex_unlock mutex_enter mutex_exit ut_uint64 IB_UINT64
""".split())

def is_keyword(t):
    return t in KEYWORDS or t in NOISE

def extract_for(sha):
    r = subprocess.run(
        ['git', 'show', '--format=', '-U0', '--no-renames', sha],
        text=True, capture_output=True, errors='replace'
    )
    added, removed, refs, contexts = set(), set(), set(), set()
    cur_path = None
    cur_is_cxx = False
    for line in r.stdout.splitlines():
        if line.startswith('diff --git'):
            m = re.match(r'diff --git a/(.*?) b/', line)
            cur_path = m.group(1) if m else None
            cur_is_cxx = is_cxx_path(cur_path) if cur_path else False
            continue
        if not cur_is_cxx:
            continue
        if line.startswith('@@'):
            m = re.match(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@\s*(.*)$', line)
            if m:
                ctx = m.group(1).strip()
                if ctx:
                    fn = re.search(r'([A-Za-z_][A-Za-z0-9_]{2,})\s*\(', ctx)
                    if fn:
                        contexts.add((cur_path, fn.group(1)))
                    else:
                        contexts.add((cur_path, ctx[:60]))
            continue
        if not (line.startswith('+') or line.startswith('-')):
            continue
        if line.startswith('+++') or line.startswith('---'):
            continue
        sign, body = line[0], line[1:]
        defs = set()
        for rx in (RE_DEFINE, RE_TYPEDEF_SIMPLE, RE_STRUCT):
            for m in rx.finditer(body):
                defs.add(m.group(1))
        m = RE_FUNC.match(body)
        if m:
            defs.add(m.group(1))
        defs = {d for d in defs if not is_keyword(d) and len(d) >= 3}
        if sign == '+':
            added |= defs
            for m in RE_IDENT.finditer(body):
                t = m.group(1)
                if not is_keyword(t):
                    refs.add(t)
        else:
            removed |= defs
    refs -= added
    return added, removed, refs, contexts

per_commit = {}
for c in commits:
    a, rm, f, ctx = extract_for(c['sha'])
    per_commit[c['idx']] = {
        'added':    sorted(a),
        'removed':  sorted(rm),
        'refs':     sorted(f),
        'contexts': sorted([f"{p}::{n}" for p, n in ctx]),
    }
    print(f"idx {c['idx']:2d}  {c['short']}  +defs={len(a):4d}  -defs={len(rm):4d}  refs={len(f):4d}  ctx={len(ctx):3d}", file=sys.stderr)

json.dump(per_commit, open(f'{WORK}/symbols.json', 'w'), indent=1)

# pairwise edges
sets = {i: {k: set(v) for k, v in d.items()} for i, d in per_commit.items()}
N = len(commits)
with open(f'{WORK}/symbol-edges.tsv', 'w') as out:
    out.write("a_idx\tb_idx\tco_def\tdef_use_ab\tdef_use_ba\tco_remove\tshared_ctx\tweight\texamples\n")
    for a in range(1, N + 1):
        sa = sets.get(a, {})
        if not sa:
            continue
        Aadd, Arem, Aref, Actx = sa.get('added', set()), sa.get('removed', set()), sa.get('refs', set()), sa.get('contexts', set())
        for b in range(a + 1, N + 1):
            sb = sets.get(b, {})
            if not sb:
                continue
            Badd, Brem, Bref, Bctx = sb.get('added', set()), sb.get('removed', set()), sb.get('refs', set()), sb.get('contexts', set())
            co_def, du_ab, du_ba, co_rem, sctx = Aadd & Badd, Aadd & Bref, Badd & Aref, Arem & Brem, Actx & Bctx
            w = len(co_def) * 10 + len(du_ab) * 2 + len(du_ba) * 2 + len(co_rem) * 4 + len(sctx) * 3
            if w == 0:
                continue
            ex = list(co_def)[:3] or list(du_ab)[:3] or list(du_ba)[:3] or list(sctx)[:3]
            out.write(f"{a}\t{b}\t{len(co_def)}\t{len(du_ab)}\t{len(du_ba)}\t{len(co_rem)}\t{len(sctx)}\t{w}\t{','.join(str(e) for e in ex)}\n")
print(f"wrote {WORK}/symbols.json and {WORK}/symbol-edges.tsv", file=sys.stderr)

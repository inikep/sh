#!/usr/bin/env python3
"""Phase 6 — auto-detect seed candidates from the features catalogue.

Emits $WORK_DIR/seeds.tsv (`feature_name<TAB>idx_1,idx_2,...`) and
$WORK_DIR/seed-suggestions.md for engineer review. If $SEEDS_FILE already
exists, this phase is skipped (the engineer's edits win).

Heuristics for becoming a seed:
  * Introduces ≥ 5 new sysvars (plugin + server combined), OR
  * Introduces ≥ 3 new SQLCOM_*, OR
  * Introduces ≥ 3 new yacc tokens, OR
  * Creates ≥ 20 new files (a new subsystem), OR
  * Creates a plugin subtree (≥ 3 new files under plugin/), OR
  * Has a feature-anchor subject (Implement/Implementation/Port/Blueprint/Add
    support) with enough code/test footprint, OR
  * Subject matches `Import <patch_name>.patch` AND <patch_name> is referenced
    by ≥ 2 other commits in the range (a feature-import anchor)
"""
import json, os, re, sys
from collections import defaultdict
from _common import WORK, SEEDS_FILE, commit_subject

if os.path.exists(SEEDS_FILE):
    sys.stderr.write(f"{SEEDS_FILE} already exists; skipping auto-detection.\n")
    sys.exit(0)

commits = json.load(open(f'{WORK}/commits.json'))
features = json.load(open(f'{WORK}/features.json'))
idx2c = {c['idx']: c for c in commits}

CODE_EXT = ('.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx', '.ic', '.i')
TEST_PREFIXES = ('mysql-test/', 'mysql-test-extra/')
FEATURE_SUBJECT_RE = re.compile(
    r'^\s*(?:'
    r'implement(?:ation)?\b|'
    r'this is implementation\b|'
    r'port\b|'
    r'blueprint:|'
    r'add(?:ed)?\b.*\b(?:support|tests?|plugin|sysvar|option|feature)\b|'
    r'tune\b.*\b(?:thread|cleaner|flush|heuristic|algorithm)\b'
    r')',
    re.I)
NON_SEED_SUBJECT_RE = re.compile(
    r'^\s*(?:'
    r'\[reconciliation\]|'
    r'reconcile mysql|'
    r'merge mysql|'
    r'manual merge|'
    r'null merge|'
    r'fix(?:es)?\b|'
    r'bug\b|'
    r'cherry-picked fix\b'
    r')',
    re.I)
BP_RE = re.compile(r'\+spec/([a-z0-9-]+)', re.I)
GENERIC_SEED_TAGS = {
    'innodb_include', 'innodb_handler', 'innodb_buf', 'innodb_log',
    'innodb_row', 'innodb_srv', 'innodb_btr', 'xtradb_i_s',
    'mysqld_help_win', 'mysqld_help_notwin',
}

def norm_tag(s):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_').lower()
    s = re.sub(r'_+', '_', s)
    if len(s) > 48:
        s = s[:48].rstrip('_')
    return s

def content_feature_tag(info):
    tags = info.get('feature_tags') or []
    for item in tags:
        tag = norm_tag(item.get('tag', ''))
        if tag:
            return tag, item.get('sources', [])

    # Backward-compatible fallback for older features.json files generated
    # before Phase 4 learned feature_tags.
    for key in ('plugin_sysvars', 'server_sysvars', 'longopts'):
        vals = info.get(key, [])
        if vals:
            return norm_tag(vals[0]), [key]
    new_files = info.get('new_files', [])
    for p in new_files:
        if p.startswith('mysql-test/'):
            stem = p.rsplit('/', 1)[-1].rsplit('.', 1)[0]
            stem = re.sub(r'^(percona|innodb|mysql|rpl)_', '', norm_tag(stem))
            if stem:
                return stem, ['MTR test']
    for s in info.get('innodb_globals', []):
        return norm_tag(re.sub(r'^(srv|innobase|log_online)_', '', s)), ['InnoDB global']
    return None, []

def code_files(c):
    return [p for p in c.get('files', {}) if p.endswith(CODE_EXT)
            and not p.startswith(TEST_PREFIXES)]

def test_files(c):
    return [p for p in c.get('files', {}) if p.startswith(TEST_PREFIXES)]

def is_feature_subject(subj):
    return bool(FEATURE_SUBJECT_RE.search(subj)) and not NON_SEED_SUBJECT_RE.search(subj)

def subject_tokens(text):
    # Replayed subjects are sometimes truncated in the middle of a blueprint
    # slug, while the full "Original title:" is still present in the body.
    # Prefer the longest matching slug so names are stable and meaningful.
    return sorted(
        {m.group(1).lower() for m in BP_RE.finditer(text)},
        key=lambda s: (-len(s), s))

# Index patch tokens across the range
patch_token_count = defaultdict(int)
RE_PATCH = re.compile(r'([a-zA-Z0-9_]+)\.patch', re.I)
for c in commits:
    text = commit_subject(c) + '\n' + c.get('body', '')
    for m in RE_PATCH.finditer(text):
        patch_token_count[m.group(1).lower()] += 1

candidates = []   # (idx, suggested_name, rationale)
for c in commits:
    i = c['idx']
    info = features.get(str(i), {})
    if not info:
        continue
    new_files = info.get('new_files', [])
    ssv = info.get('server_sysvars', [])
    psv = info.get('plugin_sysvars', [])
    sqlcoms = info.get('sql_commands', [])
    yacc_t = info.get('yacc_tokens', [])
    subj = commit_subject(c)
    body = c.get('body', '')
    paths = set(c.get('files', {}).keys())
    code_n = len(code_files(c))
    test_n = len(test_files(c))
    file_n = len(paths)
    plugin_new = [p for p in new_files if p.startswith('plugin/')]
    bp_tokens = subject_tokens(subj + '\n' + body)
    content_tag, content_sources = content_feature_tag(info)

    rationale = []
    if len(ssv) + len(psv) >= 5:
        rationale.append(f"{len(ssv)+len(psv)} new sysvars")
    if len(sqlcoms) >= 3:
        rationale.append(f"{len(sqlcoms)} new SQLCOM")
    if len(yacc_t) >= 3:
        rationale.append(f"{len(yacc_t)} new yacc tokens")
    if len(new_files) >= 20:
        rationale.append(f"{len(new_files)} new files")
    if len(plugin_new) >= 3:
        rationale.append(f"{len(plugin_new)} new plugin files")
    m = re.match(r'^\s*Import\s+([a-zA-Z0-9_]+)\.patch\s*$', subj)
    if m and patch_token_count.get(m.group(1).lower(), 0) >= 2:
        rationale.append(f"patch-token shared ({m.group(1)})")
    if bp_tokens and is_feature_subject(subj):
        rationale.append(f"blueprint/spec token ({', '.join(bp_tokens[:2])})")
    if is_feature_subject(subj):
        feature_weight = code_n * 2 + test_n + len(new_files)
        if file_n >= 5 or code_n >= 3 or test_n >= 3 or feature_weight >= 8:
            rationale.append(
                f"feature-anchor subject; footprint {file_n} files/{code_n} code/{test_n} tests")
    if not rationale:
        continue

    # Prefer content-derived feature tags.  Subject-derived names are fallback
    # only: bug-fix subjects often describe a symptom, not the feature being
    # introduced or updated.
    short = subj
    bp_short = bp_tokens[0] if bp_tokens else None
    short = re.sub(r'^\s*(\[upstream\]\s*)?Import\s+', '', short)
    short = re.sub(r'\.patch\s*$', '', short)
    short = re.sub(r'^\s*Bug[ #:]+\d+[\s.:]+', '', short, flags=re.I)
    short = re.sub(r'^\s*BP\s+\S+\s+', '', short)
    short = re.sub(r'https?://\S+', '', short)
    short = re.sub(r'\bblueprint:\s*', '', short, flags=re.I)
    if content_tag and content_tag not in GENERIC_SEED_TAGS:
        short = content_tag
        if content_sources:
            rationale.append("content tag from " + ', '.join(content_sources[:2]))
    elif bp_short:
        short = bp_short
    short = re.sub(r'[^a-zA-Z0-9_]+', '_', short).strip('_').lower()
    if len(short) > 40:
        short = short[:40].rstrip('_')
    if not short:
        short = f"feat_idx{i}"
    candidates.append((i, short, '; '.join(rationale)))

name_counts = defaultdict(int)
deduped = []
for i, name, why in candidates:
    name_counts[name] += 1
    if name_counts[name] > 1:
        name = f"{name}_idx{i}"
    deduped.append((i, name, why))
candidates = deduped

# Write suggestions markdown
with open(f'{WORK}/seed-suggestions.md', 'w') as f:
    f.write("# Seed suggestions\n\n")
    f.write("Each row is a candidate seed (commit that anchors a feature). Edit `seeds.tsv` to:\n\n")
    f.write("- Merge multiple seeds into one feature (one row, comma-separated indices)\n")
    f.write("- Rename to a human-readable feature name\n")
    f.write("- Remove false-positive seeds (e.g. version bumps, packaging commits)\n\n")
    f.write("After editing, run `cluster.py` to produce the final cluster summary.\n\n")
    f.write("| idx | suggested name | rationale | subject |\n")
    f.write("| --- | --- | --- | --- |\n")
    for i, name, why in sorted(candidates):
        subj = commit_subject(idx2c[i])[:70].replace('|', '\\|')
        f.write(f"| {i} | `{name}` | {why} | {subj} |\n")

# Write the seeds.tsv (one seed per feature by default)
with open(SEEDS_FILE, 'w') as f:
    f.write("# feature_name<TAB>idx_1,idx_2,...\n")
    f.write("# Auto-generated by seeds.py — edit before running cluster.py.\n")
    f.write("# Merge seeds that are really one feature; rename to be human-readable.\n")
    for i, name, why in sorted(candidates):
        f.write(f"{name}\t{i}\n")

print(f"wrote {SEEDS_FILE} ({len(candidates)} candidate seeds)", file=sys.stderr)
print(f"wrote {WORK}/seed-suggestions.md", file=sys.stderr)

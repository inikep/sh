#!/usr/bin/env python3
"""Phase 7 — seeded cluster expansion + cluster-summary.md.

Reads $SEEDS_FILE, $WORK_DIR/relatedness-edges.tsv, and optionally
$WORK_DIR/replacements.json. Builds a combined affinity graph from all signals:
hunk overlap, TF-IDF shared files, shared tokens, symbol edges, and inverse-diff
replacement/revert evidence. For each non-seed commit, computes affinity = max
combined edge weight to any of the feature's seed members. Assigns to the
winning feature provided:
  - winner ≥ $MIN_AFFINITY, and
  - winner exceeds runner-up by ≥ $MARGIN.

Then performs a transitive pass: unassigned commits may join via the best
already-assigned member of any cluster (still subject to threshold/margin).

Classifies satellites as:
  - Strong: affinity ≥ $STRONG_AFFINITY
  - Weak:   $MIN_AFFINITY ≤ affinity < $STRONG_AFFINITY

Writes:
  $WORK_DIR/cluster-summary.md
  $WORK_DIR/combined-edges.tsv
  $WORK_DIR/seed-feature-merges.json
  $WORK_DIR/commit-feature-impact.json
"""
import json, os, sys
import math
from collections import defaultdict
from _common import WORK, SEEDS_FILE, MIN_AFFINITY, STRONG_AFFINITY, MARGIN, commit_subject, sh

REPLACEMENT_AFFINITY_SCALE = float(os.environ.get('REPLACEMENT_AFFINITY_SCALE', '4.0'))
REPLACEMENT_AFFINITY_CAP = float(os.environ.get('REPLACEMENT_AFFINITY_CAP', '24.0'))
SEED_MERGE_AFFINITY = float(os.environ.get('SEED_MERGE_AFFINITY', '20.0'))
SEED_MERGE_REPLACEMENT_MIN_SCORE = int(os.environ.get('SEED_MERGE_REPLACEMENT_MIN_SCORE', '5'))
SEED_MERGE_REQUIRE_MOVABLE = os.environ.get('SEED_MERGE_REQUIRE_MOVABLE', '1') != '0'

commits = json.load(open(f'{WORK}/commits.json'))
N = len(commits)
idx2c = {c['idx']: c for c in commits}
commit_shortstats = {}
for c in commits:
    shortstat = sh('show', '--no-renames', '--format=', '--shortstat', c['sha']).stdout.strip()
    commit_shortstats[c['idx']] = shortstat or '0 files changed'
features_catalog_path = f'{WORK}/features.json'
features_catalog = json.load(open(features_catalog_path)) if os.path.exists(features_catalog_path) else {}
replacements_path = f'{WORK}/replacements.json'
replacement_candidates = json.load(open(replacements_path)) if os.path.exists(replacements_path) else []

# --- load edges ---
edge_w = {}
edge_info = {}
with open(f'{WORK}/relatedness-edges.tsv') as fh:
    next(fh)
    for line in fh:
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 9:
            continue
        a, b = int(parts[0]), int(parts[1])
        w = float(parts[2])
        hunk_w, file_w, tok_w, sym_w = int(parts[3]), float(parts[4]), int(parts[5]), int(parts[6])
        shared_tokens = parts[7]
        shared_paths  = parts[8]
        key = (min(a, b), max(a, b))
        edge_w[key] = w
        edge_info[key] = {
            'hunk_w': hunk_w, 'file_w': file_w, 'tok_w': tok_w, 'sym_w': sym_w,
            'tokens': shared_tokens, 'paths': shared_paths,
        }

combined_edge_w = dict(edge_w)
replacement_edge_info = {}
for r in replacement_candidates:
    key = (min(r['carrier'], r['member']), max(r['carrier'], r['member']))
    repl_w = min(math.log1p(r['score']) * REPLACEMENT_AFFINITY_SCALE, REPLACEMENT_AFFINITY_CAP)
    combined_edge_w[key] = combined_edge_w.get(key, 0.0) + repl_w
    replacement_edge_info[key] = {
        'score': r['score'],
        'weight': repl_w,
        'strategy': r['strategy'],
        'deletes_earlier_adds': r['deletes_earlier_adds'],
        'readds_earlier_deletes': r['readds_earlier_deletes'],
    }

with open(f'{WORK}/combined-edges.tsv', 'w') as f:
    f.write('a_idx\tb_idx\tcombined_w\tbase_w\treplacement_w\treplacement_score\treplacement_strategy\n')
    for key in sorted(combined_edge_w):
        repl = replacement_edge_info.get(key, {})
        f.write(
            f"{key[0]}\t{key[1]}\t{combined_edge_w[key]:.3f}\t"
            f"{edge_w.get(key, 0.0):.3f}\t{repl.get('weight', 0.0):.3f}\t"
            f"{repl.get('score', 0)}\t{repl.get('strategy', '')}\n")

def w(a, b):
    if a == b:
        return 0.0
    return combined_edge_w.get((min(a, b), max(a, b)), 0.0)

# --- load seeds.tsv ---
if not os.path.exists(SEEDS_FILE):
    sys.stderr.write(f"FATAL: {SEEDS_FILE} not found. Run seeds.py first.\n")
    sys.exit(1)

features = []   # list of (name, [seed_idxs])
seed_set = set()
with open(SEEDS_FILE) as fh:
    for line in fh:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        name = parts[0]
        seeds = sorted({int(x) for x in parts[1].split(',') if x.strip()})
        features.append((name, seeds))
        seed_set |= set(seeds)

def merge_seed_features(features):
    parent = list(range(len(features)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    merges = []
    for ia, (name_a, seeds_a) in enumerate(features):
        for ib in range(ia + 1, len(features)):
            name_b, seeds_b = features[ib]
            best = None
            for a in seeds_a:
                for b in seeds_b:
                    key = (min(a, b), max(a, b))
                    repl = replacement_edge_info.get(key)
                    if not repl:
                        continue
                    if repl['score'] < SEED_MERGE_REPLACEMENT_MIN_SCORE:
                        continue
                    if SEED_MERGE_REQUIRE_MOVABLE and repl['strategy'] == 'blocked':
                        continue
                    aff = combined_edge_w.get(key, 0.0)
                    if aff < SEED_MERGE_AFFINITY:
                        continue
                    candidate = (aff, a, b, repl)
                    if best is None or candidate[0] > best[0]:
                        best = candidate
            if best:
                union(ia, ib)
                aff, a, b, repl = best
                merges.append({
                    'from': name_a,
                    'into': name_b,
                    'seed_pair': [a, b],
                    'combined_affinity': aff,
                    'replacement_score': repl['score'],
                    'replacement_strategy': repl['strategy'],
                })

    groups = defaultdict(list)
    for i, feat in enumerate(features):
        groups[find(i)].append(feat)

    merged = []
    for members in groups.values():
        if len(members) == 1:
            merged.append(members[0])
            continue
        names = []
        seen_names = set()
        for name, _ in members:
            if name not in seen_names:
                names.append(name)
                seen_names.add(name)
        seeds = sorted({s for _, seed_idxs in members for s in seed_idxs})
        merged.append((' + '.join(names), seeds))
    merged.sort(key=lambda item: item[1][0] if item[1] else 0)
    return merged, merges

original_feature_count = len(features)
features, seed_merges = merge_seed_features(features)
seed_set = {s for _, seeds in features for s in seeds}
json.dump(seed_merges, open(f'{WORK}/seed-feature-merges.json', 'w'), indent=1)

print(
    f"loaded {original_feature_count} seed features, merged to {len(features)} features, "
    f"{len(seed_set)} seed commits",
    file=sys.stderr)

# --- pass 1: max-link assignment ---
assignments = defaultdict(list)
ambiguous = []
unassigned = []

for c in commits:
    i = c['idx']
    if i in seed_set:
        continue
    scores = []
    for name, seeds in features:
        aff = max((w(i, s) for s in seeds), default=0.0)
        anchor = max(seeds, key=lambda s: w(i, s)) if seeds else 0
        scores.append((aff, name, anchor))
    scores.sort(reverse=True)
    top_aff, top_name, top_anchor = (scores[0] if scores else (0.0, None, 0))
    runner = scores[1][0] if len(scores) > 1 else 0.0
    if top_aff < MIN_AFFINITY:
        unassigned.append((i, top_aff, top_name))
    elif (top_aff - runner) < MARGIN:
        ambiguous.append((i, top_aff, top_name, scores[1][1], runner, top_anchor))
    else:
        assignments[top_name].append((i, top_aff, top_anchor))

# --- pass 2: transitive expansion via any assigned member ---
extras = defaultdict(list)
still_unassigned = []
for i, aff, _ in unassigned:
    scores = []
    for name, seeds in features:
        members = list(seeds) + [m for m, _, _ in assignments.get(name, [])]
        best = max((w(i, m) for m in members), default=0.0)
        best_anchor = max(members, key=lambda m: w(i, m)) if members else 0
        scores.append((best, name, best_anchor))
    scores.sort(reverse=True)
    top_aff, top_name, top_anchor = (scores[0] if scores else (0.0, None, 0))
    runner = scores[1][0] if len(scores) > 1 else 0.0
    if top_aff >= MIN_AFFINITY and (top_aff - runner) >= MARGIN:
        extras[top_name].append((i, top_aff, top_anchor))
    else:
        still_unassigned.append((i, top_aff, top_name))

# --- per-commit feature impact index ---
def esc_md(s):
    return str(s).replace('|', '\\|')

def short_list(items, limit=4, prefix=''):
    vals = [f"{prefix}{x}" for x in items if x]
    if not vals:
        return []
    tail = f"+{len(vals) - limit} more" if len(vals) > limit else None
    out = vals[:limit]
    if tail:
        out.append(tail)
    return out

def catalog_summary(idx):
    info = features_catalog.get(str(idx), features_catalog.get(idx, {}))
    bits = []
    bits.extend(short_list([x.get('tag') for x in info.get('feature_tags', [])], 3, 'tag '))
    bits.extend(short_list(info.get('plugin_sysvars', []), 4, 'plugin sysvar '))
    bits.extend(short_list(info.get('server_sysvars', []), 4, 'server sysvar '))
    bits.extend(short_list(info.get('longopts', []), 4, 'option '))
    bits.extend(short_list([f"SQLCOM_{x}" for x in info.get('sql_commands', [])], 4))
    bits.extend(short_list(info.get('yacc_tokens', []), 4, 'token '))
    bits.extend(short_list(info.get('innodb_globals', []), 4, 'InnoDB global '))
    new_files = info.get('new_files', [])
    if new_files:
        bits.append(f"{len(new_files)} new files")
    bits.extend(short_list(info.get('notable_macros', []), 3, 'macro '))
    bits.extend(short_list(info.get('notable_types', []), 3, 'type '))
    return bits

commit_impact = {
    c['idx']: {
        'introduced': [],
        'updated': [],
        'removes_or_replaces': [],
        'replaced_by': [],
    }
    for c in commits
}
feature_by_idx = defaultdict(list)

for name, seeds in features:
    for s in seeds:
        commit_impact[s]['introduced'].append({
            'feature': name,
            'kind': 'seed',
        })
        feature_by_idx[s].append(name)
    for i, aff, anchor in sorted(assignments.get(name, []) + extras.get(name, []), key=lambda x: x[0]):
        tier = 'strong' if aff >= STRONG_AFFINITY else 'weak'
        commit_impact[i]['updated'].append({
            'feature': name,
            'tier': tier,
            'affinity': aff,
            'anchor': anchor,
        })
        feature_by_idx[i].append(name)

for c in commits:
    idx = c['idx']
    for bit in catalog_summary(idx):
        commit_impact[idx]['introduced'].append({
            'feature': bit,
            'kind': 'catalog',
        })

def feature_label(idx):
    names = feature_by_idx.get(idx)
    if names:
        return ', '.join(sorted(set(names)))
    bits = catalog_summary(idx)
    if bits:
        return '; '.join(bits[:3])
    return f"idx{idx}"

for r in replacement_candidates:
    carrier = r['carrier']
    member = r['member']
    feature = feature_label(carrier)
    item = {
        'feature': feature,
        'score': r['score'],
        'strategy': r['strategy'],
        'deletes_earlier_adds': r['deletes_earlier_adds'],
        'readds_earlier_deletes': r['readds_earlier_deletes'],
    }
    member_item = dict(item)
    member_item['carrier'] = carrier
    member_item['carrier_short'] = r['carrier_short']
    commit_impact[member]['removes_or_replaces'].append(member_item)

    carrier_item = dict(item)
    carrier_item['member'] = member
    carrier_item['member_short'] = r['member_short']
    commit_impact[carrier]['replaced_by'].append(carrier_item)

json.dump(commit_impact, open(f'{WORK}/commit-feature-impact.json', 'w'), indent=1)

# --- describe dominant signal between two commits ---
def signal_phrase(a, b):
    key = (min(a, b), max(a, b))
    info = edge_info.get(key, {})
    repl = replacement_edge_info.get(key, {})
    bits = []
    if repl:
        bits.append(
            f"inverse-diff score={repl['score']} repl_w={repl['weight']:.1f} "
            f"({repl['strategy']}, -added:{repl['deletes_earlier_adds']} "
            f"+deleted:{repl['readds_earlier_deletes']})")
    if info.get('tok_w'):
        bits.append(f"shared tokens: {info['tokens']}")
    if info.get('sym_w'):
        bits.append(f"symbol w={info['sym_w']}")
    if info.get('hunk_w'):
        bits.append(f"hunk={info['hunk_w']}L")
    if info.get('file_w'):
        bits.append(f"file-IDF={info['file_w']:.1f} ({info.get('paths','')})")
    return ' | '.join(bits) if bits else 'minimal signal'

def render_impact(idx, key, limit=3):
    vals = commit_impact[idx][key]
    if not vals:
        return '—'
    rendered = []
    for v in vals[:limit]:
        if key == 'introduced':
            rendered.append(v['feature'])
        elif key == 'updated':
            rendered.append(
                f"{v['feature']} ({v['tier']}, aff={v['affinity']:.1f}, idx{v['anchor']})")
        elif key == 'removes_or_replaces':
            inv = f"-added:{v['deletes_earlier_adds']} +deleted:{v['readds_earlier_deletes']}"
            rendered.append(
                f"{v['feature']} from idx{v['carrier']} (score={v['score']}, {v['strategy']}, {inv})")
        elif key == 'replaced_by':
            inv = f"-added:{v['deletes_earlier_adds']} +deleted:{v['readds_earlier_deletes']}"
            rendered.append(
                f"{v['feature']} by idx{v['member']} (score={v['score']}, {v['strategy']}, {inv})")
    if len(vals) > limit:
        rendered.append(f"+{len(vals) - limit} more")
    return '<br>'.join(esc_md(x) for x in rendered)

# --- write cluster-summary.md ---
report_path = f'{WORK}/cluster-summary.md'
with open(report_path, 'w') as f:
    f.write(f"# Feature cluster summary\n\n")
    f.write(f"Range: {len(commits)} commits.\n\n")
    f.write("Seeded clustering with combined multi-signal affinity:\n\n")
    f.write("- `hunk_w` — line-overlap counts from the hunk-level dep graph (×3, log-compressed)\n")
    f.write("- `file_w` — TF-IDF-weighted shared-file count (×1.5)\n")
    f.write("- `tok_w`  — shared bug/lp/mdev/cve/patch/bp tokens (×8)\n")
    f.write("- `sym_w`  — co-defined macros/types, def-use, shared `(file, function)` contexts (×0.5)\n")
    f.write(f"- `replacement_w` — inverse-diff replacement/revert score, `min(log1p(score) × {REPLACEMENT_AFFINITY_SCALE:g}, {REPLACEMENT_AFFINITY_CAP:g})`\n\n")
    f.write(f"**Strong** = affinity ≥ {STRONG_AFFINITY}. **Weak** = {MIN_AFFINITY} ≤ affinity < {STRONG_AFFINITY}.\n\n")
    if replacement_candidates:
        f.write("The inverse-diff replacement/revert signal participates in cluster assignment and is also shown separately for review. There, score means exact normalized line matches where a later commit deletes an earlier addition or re-adds an earlier deletion; movability is computed from the hunk DAG.\n\n")
    if seed_merges:
        f.write(f"Seed feature merge pass combined {original_feature_count} auto/manual seed features into {len(features)} clusters. Seed features merge when a seed-to-seed pair has combined affinity ≥ {SEED_MERGE_AFFINITY:g}, inverse-diff score ≥ {SEED_MERGE_REPLACEMENT_MIN_SCORE}, and replacement movability is not blocked.\n\n")

    # cluster summary table
    f.write("## Cluster summary\n\n")
    f.write("| Feature | Seeds | Strong satellites | Weak satellites | Total |\n")
    f.write("| --- | --- | --- | --- | --- |\n")
    for name, seeds in features:
        members = sorted(assignments.get(name, []) + extras.get(name, []), key=lambda x: -x[1])
        strong = [str(m[0]) for m in members if m[1] >= STRONG_AFFINITY]
        weak   = [str(m[0]) for m in members if m[1] <  STRONG_AFFINITY]
        seed_str = ', '.join(str(s) for s in seeds)
        strong_str = ', '.join(strong) if strong else '—'
        weak_str   = ', '.join(weak)   if weak   else '—'
        total = len(seeds) + len(members)
        f.write(f"| **{name}** | {seed_str} | {strong_str} | {weak_str} | {total} |\n")
    f.write("\n")

    if seed_merges:
        f.write(f"## Merged Seed Features — {len(seed_merges)}\n\n")
        f.write("| feature A | feature B | seed pair | combined affinity | replacement signal |\n")
        f.write("| --- | --- | --- | ---: | --- |\n")
        for m in seed_merges:
            repl = f"score={m['replacement_score']}, {m['replacement_strategy']}"
            pair = f"idx{m['seed_pair'][0]}→idx{m['seed_pair'][1]}"
            f.write(
                f"| {esc_md(m['from'])} | {esc_md(m['into'])} | {pair} | "
                f"{m['combined_affinity']:.1f} | {repl} |\n")
        f.write("\n")

    # per-cluster detail
    f.write("## Per-cluster detail\n\n")
    for name, seeds in features:
        members = sorted(assignments.get(name, []) + extras.get(name, []), key=lambda x: -x[1])
        total = len(seeds) + len(members)
        f.write(f"### {name} — {total}\n\n")
        for s in seeds:
            c = idx2c[s]
            f.write(f"- ★ **{s}** {c['short']}  {commit_subject(c)[:90]}\n")
            f.write(f"    └─ shortstat: {commit_shortstats.get(s, '0 files changed')}\n")
        for i, aff, anchor in members:
            tier = 'strong' if aff >= STRONG_AFFINITY else 'weak'
            c = idx2c[i]
            phrase = signal_phrase(i, anchor)
            f.write(f"- {tier} **{i}** aff={aff:.1f} → idx{anchor}  {c['short']}  {commit_subject(c)[:75]}\n")
            f.write(f"    ├─ shortstat: {commit_shortstats.get(i, '0 files changed')}\n")
            f.write(f"    └─ {phrase}\n")
        f.write("\n")

    if replacement_candidates:
        f.write(f"## Inverse-diff replacement/revert candidates — {len(replacement_candidates)}\n\n")
        f.write("These are not automatic squash approvals. They highlight feature follow-ups, replacements, or partial reverts that token-only pairing can miss.\n\n")
        f.write("| rank | score | pair | movability | inverse signal | subjects |\n")
        f.write("| --- | ---: | --- | --- | --- | --- |\n")
        for rank, r in enumerate(replacement_candidates[:30], 1):
            inv = f"-added:{r['deletes_earlier_adds']} +deleted:{r['readds_earlier_deletes']}"
            pair = f"{r['carrier']}→{r['member']} `{r['carrier_short']}`→`{r['member_short']}`"
            subj = (r['carrier_subject'][:48] + " / " + r['member_subject'][:48]).replace('|', '\\|')
            blockers = ''
            if r['strategy'] == 'blocked':
                blockers = f" (up={r['blockers_up'][:6]}, down={r['blockers_down'][:6]})"
            f.write(f"| {rank} | {r['score']} | {pair} | {r['strategy']}{blockers} | {inv} | {subj} |\n")
        f.write("\n")

    f.write("## Per-commit feature impact\n\n")
    f.write("This table answers, for each commit, which feature it introduces, updates as a satellite, or removes/replaces through inverse-diff evidence. `replaced by` is the reverse view for the earlier commit whose added lines are later removed or whose deleted lines are later re-added.\n\n")
    f.write("| idx | commit | introduced | updated | removes/replaces | replaced by |\n")
    f.write("| ---: | --- | --- | --- | --- | --- |\n")
    for c in commits:
        idx = c['idx']
        commit = f"`{c['short']}` {esc_md(commit_subject(c)[:52])}"
        f.write(
            f"| {idx} | {commit} | "
            f"{render_impact(idx, 'introduced')} | "
            f"{render_impact(idx, 'updated')} | "
            f"{render_impact(idx, 'removes_or_replaces')} | "
            f"{render_impact(idx, 'replaced_by')} |\n")
    f.write("\n")

    # ambiguous
    if ambiguous:
        f.write(f"## Ambiguous — {len(ambiguous)}\n\n")
        f.write("Winner did not beat runner-up by margin.\n\n")
        f.write("| idx | best | aff | runner-up | runner aff | subject |\n")
        f.write("| --- | --- | --- | --- | --- | --- |\n")
        for i, aff, name, name2, aff2, anchor in ambiguous:
            subj = commit_subject(idx2c[i])[:60].replace('|', '\\|')
            f.write(f"| {i} | {name} | {aff:.1f} | {name2} | {aff2:.1f} | {subj} |\n")
        f.write("\n")

    # unassigned
    if still_unassigned:
        f.write(f"## Unassigned — {len(still_unassigned)}\n\n")
        f.write("No strong link to any seeded feature (after transitive expansion).\n\n")
        f.write("| idx | closest | aff | subject |\n")
        f.write("| --- | --- | --- | --- |\n")
        for i, aff, name in still_unassigned:
            subj = commit_subject(idx2c[i])[:70].replace('|', '\\|')
            cname = name if name else '—'
            f.write(f"| {i} | {cname} | {aff:.1f} | {subj} |\n")
        f.write("\n")

print(f"wrote {report_path}", file=sys.stderr)
n_strong = sum(1 for name, _ in features for m in (assignments.get(name, []) + extras.get(name, [])) if m[1] >= STRONG_AFFINITY)
n_weak   = sum(1 for name, _ in features for m in (assignments.get(name, []) + extras.get(name, [])) if m[1] <  STRONG_AFFINITY)
print(f"  features: {len(features)}", file=sys.stderr)
print(f"  seeds: {len(seed_set)}  strong satellites: {n_strong}  weak: {n_weak}  ambiguous: {len(ambiguous)}  unassigned: {len(still_unassigned)}", file=sys.stderr)

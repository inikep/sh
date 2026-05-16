#!/usr/bin/env python3
"""Build the Phase C squash plan from bug groups and follow-up detections.

Inputs (env):
  LOG_DIR         scratch dir with bugs.tsv and followups.tsv already produced
  BASE_BRANCH     for the range mysql-X..OUTPUT
  OUTPUT_BRANCH   the post-Phase-A branch

Writes $LOG_DIR/phase-c-plan.json with:
  chrono                    list of SHAs in chronological order
  contiguous_groups         carrier -> contiguous-prefix members (size >=2)
  non_contiguous_residuals  carrier -> members deferred for reorder-attempt
  carrier_of                effective carrier per absorbed SHA (only those squashed)
"""
import os, json, subprocess

LOG_DIR = os.environ['LOG_DIR']
BASE = os.environ['BASE_BRANCH']
OUT = os.environ['OUTPUT_BRANCH']

chrono = subprocess.check_output(['git','rev-list','--reverse', f'{BASE}..{OUT}']).decode().split()
chrono_pos = {s:i for i,s in enumerate(chrono)}

# Direct squash map from B(a) and B(b)
direct = {}

# B(a)
with open(os.path.join(LOG_DIR, 'bugs.tsv')) as f:
    sha_bugs = {}
    for l in f:
        parts = l.rstrip('\n').split('\t')
        if len(parts) >= 2 and parts[1]:
            sha_bugs[parts[0]] = set(parts[1].split(','))
bug_groups = {}
for sha, bugs in sha_bugs.items():
    for b in bugs:
        bug_groups.setdefault(b, []).append(sha)
for b, shas in bug_groups.items():
    if len(shas) > 1:
        shas_sorted = sorted(shas, key=lambda s: chrono_pos[s])
        for s in shas_sorted[1:]:
            if s not in direct: direct[s] = shas_sorted[0]

# B(b)
with open(os.path.join(LOG_DIR, 'followups.tsv')) as f:
    for l in f:
        parts = l.rstrip('\n').split('\t')
        if len(parts) >= 4 and parts[1] == 'FOLLOWUP':
            sha, _, target, _ = parts
            if sha not in direct: direct[sha] = target

def resolve(sha, depth=0):
    if depth > 100: return sha
    if sha not in direct: return sha
    return resolve(direct[sha], depth+1)

carrier_of = {s: resolve(s) for s in chrono}
groups = {}
for s in chrono:
    groups.setdefault(carrier_of[s], []).append(s)

# Split each group into contiguous prefix + non-contiguous remainder
contiguous = {}
non_contig = {}
for c, members in groups.items():
    if len(members) == 1:
        continue
    positions = [chrono_pos[m] for m in members]
    prefix = [members[0]]; last = positions[0]
    for m,p in zip(members[1:], positions[1:]):
        if p == last + 1:
            prefix.append(m); last = p
        else:
            break
    if len(prefix) > 1:
        contiguous[c] = prefix
    rest = [m for m in members if m not in prefix]
    if rest:
        non_contig[c] = rest

eff_carrier = {}
for c, m in contiguous.items():
    for s in m:
        eff_carrier[s] = c

out = {
    'chrono': chrono,
    'contiguous_groups': contiguous,
    'non_contiguous_residuals': non_contig,
    'carrier_of': eff_carrier,
}
with open(os.path.join(LOG_DIR, 'phase-c-plan.json'), 'w') as f:
    json.dump(out, f, indent=2)

print(f"Total commits: {len(chrono)}")
print(f"Contiguous groups (>=2 members): {len(contiguous)}")
print(f"Non-contiguous residuals (will attempt reorder): {sum(len(v) for v in non_contig.values())}")
print(f"Absorbed via contiguous: {sum(len(m)-1 for m in contiguous.values())}")

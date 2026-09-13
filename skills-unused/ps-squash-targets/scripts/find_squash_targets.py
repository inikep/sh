#!/usr/bin/env python3
"""Find squash candidates in a commit range and score squash targets for each.

Usage:
  find_squash_targets.py --repo /path/to/repo \
      --candidate-range A..B --target-range C..D \
      [--max-lines 64] [--alts 3] [--out /tmp/squash-targets]

Candidate filter: total changed lines <= max-lines OR deletions > additions.
Scoring signals (additive, advisory only — semantic vetting is the caller's job):
  +60  exact [feature_tag] subject-prefix match (non-#, must recur in range)
  +50  shared bug/ticket token (bug N / lp:N / PS-N / DB-N / MYR-N / BLD-N / MDEV-N / #NNNN)
  <=40 rarity-weighted file overlap: 25*coverage + 15*sum(1/df) capped at 40,
       where df = number of in-range commits touching the file (hot files ~0)
Output: <out>/pairs.json + <out>/pairs.md (ranked, with alternatives and df
per shared file so the caller can spot hot-file-only matches).
"""
import argparse, json, os, re, subprocess, sys
from collections import Counter

TAG_RE = re.compile(r'^(?:\[g\d+\])?\[([^\]]+)\]')
BUG_RE = re.compile(
    r'(?:bug\s*#?\s*(\d{5,8})|lp[:\-\s]?(\d{6,8})|(PS|DB|MYR|BLD|MDEV|WL)-(\d+)|#(\d{4,5})\b)',
    re.I)


def git(repo, *args):
    return subprocess.run(['git', '-C', repo] + list(args),
                          capture_output=True, text=True, check=True).stdout


def parse_range(repo, rangespec):
    out = git(repo, 'log', '--reverse', '--format=C|%H|%s', '--numstat', rangespec)
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith('C|'):
            _, h, s = line.split('|', 2)
            cur = {'sha': h, 'subj': s, 'files': {}, 'add': 0, 'rem': 0}
            commits.append(cur)
        elif line.strip() and cur is not None:
            parts = line.split('\t')
            if len(parts) == 3:
                a, r, f = parts
                a = 0 if a == '-' else int(a)
                r = 0 if r == '-' else int(r)
                cur['files'][f] = (a, r)
                cur['add'] += a
                cur['rem'] += r
    return [c for c in commits if 'MARKER' not in c['subj']]


def tag(c):
    m = TAG_RE.match(c['subj'])
    t = m.group(1) if m else None
    return None if (t is None or t.startswith('#')) else t


def bugs(c):
    toks = set()
    for m in BUG_RE.finditer(c['subj']):
        g = m.groups()
        if g[2] and g[3]:
            toks.add(f'{g[2].upper()}-{g[3]}')
        else:
            toks.add(next(x for x in (g[0], g[1], g[4]) if x))
    return toks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True)
    ap.add_argument('--candidate-range', required=True)
    ap.add_argument('--target-range', required=True)
    ap.add_argument('--max-lines', type=int, default=64)
    ap.add_argument('--alts', type=int, default=3)
    ap.add_argument('--out', default='/tmp/squash-targets')
    args = ap.parse_args()

    targets = parse_range(args.repo, args.target_range)
    cands_all = parse_range(args.repo, args.candidate_range)
    target_shas = {c['sha'] for c in targets}
    order = {c['sha']: i for i, c in enumerate(targets)}

    cands = [c for c in cands_all
             if (c['add'] + c['rem']) <= args.max_lines or c['rem'] > c['add']]

    df = Counter()
    for c in targets:
        for f in c['files']:
            df[f] += 1
    tag_count = Counter(t for c in targets if (t := tag(c)))

    results, unmatched = [], []
    for c in cands:
        ct, cb, cf = tag(c), bugs(c), set(c['files'])
        scored = []
        for t in targets:
            if t['sha'] == c['sha']:
                continue
            score, why = 0.0, []
            tt = tag(t)
            if ct and tt == ct and tag_count[ct] > 1:
                score += 60
                why.append(f'same feature tag [{ct}]')
            shared_bugs = cb & bugs(t)
            if shared_bugs:
                score += 50
                why.append('same bug token ' + ','.join(sorted(shared_bugs)))
            sf = cf & set(t['files'])
            if sf:
                w = sum(1.0 / df[f] for f in sf)
                score += min(40, 25 * len(sf) / len(cf) + 15 * w)
                why.append(f'{len(sf)}/{len(cf)} files overlap')
            if score > 5:
                scored.append((score, t, why, sorted(sf)))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            unmatched.append(c)
            continue
        entry = {'cand': {'sha': c['sha'][:12], 'subj': c['subj'],
                          'files': len(c['files']), 'add': c['add'], 'rem': c['rem']},
                 'matches': []}
        for score, t, why, sf in scored[:args.alts]:
            pos = ('earlier' if c['sha'] in order and order[t['sha']] < order[c['sha']]
                   else 'later')
            entry['matches'].append({
                'score': round(score, 1),
                'sha': t['sha'][:12], 'subj': t['subj'],
                'files': len(t['files']), 'add': t['add'], 'rem': t['rem'],
                'pos': pos, 'why': why,
                'shared_files': [{'file': f, 'df': df[f]} for f in sf]})
        results.append(entry)

    results.sort(key=lambda e: -e['matches'][0]['score'])
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'pairs.json'), 'w') as fh:
        json.dump({'pairs': results,
                   'unmatched': [{'sha': c['sha'][:12], 'subj': c['subj']}
                                 for c in unmatched],
                   'counts': {'candidates_in_range': len(cands_all),
                              'selected': len(cands),
                              'target_pool': len(targets)}}, fh, indent=1)

    with open(os.path.join(args.out, 'pairs.md'), 'w') as fh:
        fh.write(f'# Squash pairs (raw scores — vet before reporting)\n\n'
                 f'{len(cands)} candidates selected of {len(cands_all)} '
                 f'in candidate range; {len(targets)} targets.\n\n')
        for e in results:
            c, m = e['cand'], e['matches'][0]
            fh.write(f"## score {m['score']} — {c['sha']}\n"
                     f"- CAND ({c['files']} files, +{c['add']}/-{c['rem']}): {c['subj']}\n"
                     f"- TGT  {m['sha']} ({m['files']} files, +{m['add']}/-{m['rem']}, "
                     f"{m['pos']}): {m['subj']}\n"
                     f"- why: {'; '.join(m['why'])}\n"
                     f"- shared: "
                     + ', '.join(f"{s['file']} (df={s['df']})" for s in m['shared_files'])
                     + '\n')
            for alt in e['matches'][1:]:
                fh.write(f"- alt ({alt['score']}): {alt['sha']} {alt['subj'][:80]}\n")
            fh.write('\n')
        if unmatched:
            fh.write('## No target found\n')
            for c in unmatched:
                fh.write(f"- {c['sha']} {c['subj']}\n")
    print(f"{len(results)} matched, {len(unmatched)} unmatched, "
          f"{len(cands)} candidates -> {args.out}/pairs.md")


if __name__ == '__main__':
    main()

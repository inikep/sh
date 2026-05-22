#!/usr/bin/env python3
"""Phase 2 — hunk-level dependency graph via blame frontier.

For each path, maintain a sorted list of [start, end, origin_idx] segments
representing line ownership in the cumulative tree. For each commit's hunk on
a path: emit an edge from each overlapping segment's origin to this commit;
then splice the frontier to install this commit's post-range as a new segment
and shift downstream segments by (post_len - pre_len).

Output: $WORK_DIR/dep-edges.tsv with columns
  a_idx  b_idx  path  a_post(start-end)  b_pre(start-end)
"""
import json, sys
from _common import WORK

commits = json.load(open(f'{WORK}/commits.json'))

# path -> sorted list of [start, end, origin_idx]
frontier = {}
edges = []  # (a_idx, b_idx, path, a_range, b_range)

for c in commits:
    b_idx = c['idx']
    for path, info in c['files'].items():
        pre = info.get('pre', [])
        post = info.get('post', [])
        if info.get('binary') or info.get('new') or info.get('deleted'):
            # coarse file-level edge
            segs = frontier.get(path, [])
            if segs:
                last = segs[-1]
                edges.append((last[2], b_idx, path, f"{last[0]}-{last[1]}", "file"))
            frontier[path] = [[1, 1 + sum(p[1] - p[0] for p in post), b_idx]]
            continue
        segs = frontier.setdefault(path, [])
        for (a, ae), (c_, ce) in zip(pre, post):
            # find overlapping segments with [a, ae)
            new_segs = []
            for s, e, oi in segs:
                if e <= a or s >= ae:
                    new_segs.append([s, e, oi])
                else:
                    # overlap
                    edges.append((oi, b_idx, path, f"{s}-{e}", f"{a}-{ae}"))
                    if s < a:
                        new_segs.append([s, a, oi])
                    if e > ae:
                        new_segs.append([ae, e, oi])
            # insert this commit's post segment
            new_segs.append([c_, ce, b_idx])
            new_segs.sort()
            # shift segments after the pre-range by delta
            delta = (ce - c_) - (ae - a)
            shifted = []
            for s, e, oi in new_segs:
                if s >= ae and oi != b_idx:
                    shifted.append([s + delta, e + delta, oi])
                else:
                    shifted.append([s, e, oi])
            segs = shifted
        frontier[path] = segs

with open(f'{WORK}/dep-edges.tsv', 'w') as f:
    f.write("a_idx\tb_idx\tpath\ta_post\tb_pre\n")
    for a, b, p, ar, br in edges:
        f.write(f"{a}\t{b}\t{p}\t{ar}\t{br}\n")

# also dump as a JSON graph for easy in-memory loads downstream
adj = {}
radj = {}
for a, b, p, ar, br in edges:
    adj.setdefault(a, set()).add(b)
    radj.setdefault(b, set()).add(a)
json.dump(
    {'adj': {k: sorted(v) for k, v in adj.items()},
     'radj': {k: sorted(v) for k, v in radj.items()}},
    open(f'{WORK}/dep-graph.json', 'w'),
)
print(f"edges: {len(edges)}", file=sys.stderr)
print(f"wrote {WORK}/dep-edges.tsv and dep-graph.json", file=sys.stderr)

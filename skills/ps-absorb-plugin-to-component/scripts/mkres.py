#!/usr/bin/env python3
"""Write an edit-script resolution for backchain.py and dry-run it on the current conflict.

usage: mkres.py CHAIN RES SHA12 NEWPATH < lambdas
  stdin: one region lambda per line, (o, b, t) -> list of lines (o = component after T,
  b = plugin after T, t = plugin before T), in conflict-region order. Helpers from reslib
  (keep_ours, keep_theirs, drop_all, without(...)) may be used.
Writes RES/SHA12/NEWPATH.res.py with resolve(r) = r.regions(...). Add post-edits (rep1, drop,
drop_function, drop_decl_blocks from reslib) to the script by hand when a region choice is not
enough; the script is re-applied to a fresh merge on every backchain run, so never paste
whole-file content into it.
The dry run applies the lambdas to CHAIN/conflicts/SHA12/NEWPATH and fails on a count mismatch.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reslib import *  # noqa: F401,F403  (lambdas may use the helpers)
import reslib

chain, res, sha, path = sys.argv[1:5]
lams = [l.strip() for l in sys.stdin.read().split('\n') if l.strip()]
fns = [eval(l) for l in lams]
conf = os.path.join(chain, 'conflicts', sha, path)
if os.path.exists(conf):
    reslib.apply_regions(open(conf, encoding='utf-8', errors='surrogateescape').read(), fns, path)
else:
    print(f'note: no conflict file {conf}; written without dry run')
dst = os.path.join(res, sha, path + '.res.py')
os.makedirs(os.path.dirname(dst), exist_ok=True)
body = ',\n        '.join(lams)
open(dst, 'w').write(f'''from reslib import *


def resolve(r):
    return r.regions(
        {body})
''')
print('wrote', dst)

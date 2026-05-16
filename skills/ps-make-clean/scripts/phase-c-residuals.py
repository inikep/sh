#!/usr/bin/env python3
"""Attempt to squash non-contiguous Phase C residuals via reorder.

For each non-contiguous residual member, we walk back from its current position
on the work branch and try to reorder it adjacent to its carrier's squashed
commit via interactive-rebase semantics. If the move-and-squash succeeds without
conflict, the member is absorbed. If a conflict arises, we abort that attempt,
leave the member as a singleton, and continue with the next residual.

Records outcomes in $LOG_DIR/phase-c-residual-outcomes.log.

Inputs (env): LOG_DIR, BASE_BRANCH, OUTPUT_BRANCH (current work branch HEAD).
"""
import os, json, subprocess, sys, tempfile

LOG = os.environ['LOG_DIR']
BASE = os.environ['BASE_BRANCH']

with open(os.path.join(LOG, 'phase-c-plan.json')) as f:
    plan = json.load(f)

nc = plan['non_contiguous_residuals']  # carrier_orig_sha -> [residual_orig_shas]
if not nc:
    print("No non-contiguous residuals to process.")
    open(os.path.join(LOG, 'phase-c-residual-outcomes.log'), 'w').close()
    sys.exit(0)

# Map original SHAs to current work branch positions by subject + author+date.
# (Squashed carriers have new SHAs; non-absorbed singletons keep their content.)
def find_in_work(orig_sha):
    """Return current SHA on work branch that corresponds to orig_sha (by subject and authored date), or None."""
    subj = subprocess.check_output(['git','log','-1','--format=%s', orig_sha]).decode().strip()
    aut = subprocess.check_output(['git','log','-1','--format=%aI', orig_sha]).decode().strip()
    out = subprocess.check_output(['git','log','--format=%H%x09%aI%x09%s','HEAD']).decode().splitlines()
    for line in out:
        h, a, s = line.split('\t', 2)
        if s == subj and a == aut:
            return h
    return None

outcomes = []
for carrier, residuals in nc.items():
    # carrier_now is re-resolved inside the inner loop because each successful
    # rebase rewrites the carrier commit (its SHA changes once squashed).
    for res in residuals:
        carrier_now = find_in_work(carrier)
        if carrier_now is None:
            outcomes.append(f"SKIP carrier {carrier[:11]} not found in work branch")
            break
        res_now = find_in_work(res)
        if res_now is None:
            outcomes.append(f"SKIP residual {res[:11]} not found in work branch (likely already part of another squash)")
            continue

        # Reorder strategy: rebase onto carrier_now^ with todo
        #     pick   <carrier_now>
        #     squash <res_now>
        #     pick   <intermediate_1>
        #     ...
        # This squashes res_now into carrier_now without leaving `squash` as the
        # first todo line (git rejects that with "cannot 'squash' without a
        # previous commit").
        head = subprocess.check_output(['git','rev-parse','HEAD']).decode().strip()
        carrier_parent = subprocess.check_output(['git','rev-parse', f'{carrier_now}^']).decode().strip()

        commits = subprocess.check_output(
            ['git','rev-list','--reverse', f'{carrier_parent}..HEAD']
        ).decode().split()
        # commits[0] == carrier_now; remaining are post-carrier in chrono order.
        post_carrier = [c for c in commits[1:] if c != res_now]

        todo_path = tempfile.mkstemp()[1]
        with open(todo_path, 'w') as f:
            f.write(f"pick {carrier_now}\n")
            f.write(f"squash {res_now}\n")
            for c in post_carrier:
                f.write(f"pick {c}\n")

        env = os.environ.copy()
        env['GIT_SEQUENCE_EDITOR'] = f"cp {todo_path}"
        env['GIT_EDITOR'] = 'true'  # accept default combined commit message
        r = subprocess.run(['git','rebase','-i', carrier_parent], env=env, capture_output=True, text=True)
        os.unlink(todo_path)
        if r.returncode == 0:
            outcomes.append(f"ABSORBED non-contig {res[:11]} -> carrier {carrier[:11]}")
        else:
            subprocess.run(['git','rebase','--abort'], capture_output=True)
            subprocess.run(['git','reset','--hard', head], capture_output=True)
            outcomes.append(f"SKIP non-contig {res[:11]} -> carrier {carrier[:11]} (conflict on rebase)")

with open(os.path.join(LOG, 'phase-c-residual-outcomes.log'), 'w') as f:
    f.write("\n".join(outcomes))
for o in outcomes: print(o)

#!/bin/bash
# Phase B applier: small no-C/C++ commits are squashed into chain-resolved roots.
#
# Inputs (env): BASE_BRANCH, SRC_BRANCH, OUTPUT_BRANCH, LOG_DIR
set -e
: "${BASE_BRANCH:?}" "${SRC_BRANCH:?}" "${OUTPUT_BRANCH:?}" "${LOG_DIR:?}"

SCRIPT_DIR="$(dirname "$0")"
LOG_DIR="$LOG_DIR" BASE_BRANCH="$BASE_BRANCH" OUTPUT_BRANCH="$OUTPUT_BRANCH" \
  python3 "$SCRIPT_DIR/phase-b-analyze.py"

WORK="${OUTPUT_BRANCH}-phase-b"
git branch -D "$WORK" 2>/dev/null || true
git checkout -q -b "$WORK" "$BASE_BRANCH"

python3 - <<'PY'
import os, json, subprocess, sys, tempfile

LOG = os.environ['LOG_DIR']
with open(os.path.join(LOG, 'phase-b-plan.json')) as f:
    plan = json.load(f)

chrono   = plan['chrono']
squash   = plan['small_nocpp_squash']
absorbed_set = set(squash.keys())

def resolve(s, depth=0):
    if depth > 100: return s
    if s not in squash: return s
    return resolve(squash[s], depth+1)

ultimate = {a: resolve(a) for a in absorbed_set}
absorb_into = {}
chrono_pos = {s:i for i,s in enumerate(chrono)}
for a, root in ultimate.items():
    absorb_into.setdefault(root, []).append(a)
for k in absorb_into:
    absorb_into[k].sort(key=lambda s: chrono_pos[s])

def run(*a, **kw): return subprocess.run(a, capture_output=True, text=True, **kw)

log = []
for i, sha in enumerate(chrono):
    subj = subprocess.check_output(['git','log','-1','--format=%s', sha]).decode().strip()[:55]
    if sha in absorbed_set:
        log.append(f"[{i+1}] DEFER {sha[:11]} -> root {ultimate[sha][:11]}")
        continue
    if sha in absorb_into:
        members = [sha] + absorb_into[sha]
        msgs = []
        for m in members:
            r = run('git','cherry-pick','--no-commit', m)
            if r.returncode:
                log.append(f"[{i+1}] CONFLICT cherry-pick {m[:11]} under root {sha[:11]}")
                # Abort the cherry-pick and skip this member; root + remaining absorbed will still be picked
                subprocess.run(['git','cherry-pick','--abort'], capture_output=True)
                # Re-pick what we have so far as singletons
                # (For simplicity in this version: if any conflict occurs, abort whole group.)
                print(r.stdout, file=sys.stderr); print(r.stderr, file=sys.stderr); sys.exit(1)
            msgs.append(subprocess.check_output(['git','log','-1','--format=%B', m]).decode().rstrip())
        combined = "\n\n-----\n\n".join(msgs)
        env = os.environ.copy()
        for fmt,var in [('%an','GIT_AUTHOR_NAME'),('%ae','GIT_AUTHOR_EMAIL'),
                        ('%aI','GIT_AUTHOR_DATE'),('%cn','GIT_COMMITTER_NAME'),
                        ('%ce','GIT_COMMITTER_EMAIL'),('%cI','GIT_COMMITTER_DATE')]:
            env[var] = subprocess.check_output(['git','log','-1','--format='+fmt, sha]).decode().strip()
        fd, mp = tempfile.mkstemp(); os.write(fd, combined.encode()); os.close(fd)
        r = subprocess.run(['git','commit','-q','--no-verify','--file', mp], env=env)
        os.unlink(mp)
        if r.returncode: log.append(f"COMMIT FAIL {sha[:11]}"); sys.exit(1)
        log.append(f"[{i+1}] MERGE {sha[:11]} + {len(absorb_into[sha])} absorbed -> {subj}")
    else:
        r = run('git','cherry-pick', sha)
        if r.returncode:
            log.append(f"[{i+1}] CONFLICT singleton {sha[:11]} {subj}")
            print(r.stdout, file=sys.stderr); print(r.stderr, file=sys.stderr); sys.exit(1)
        log.append(f"[{i+1}] PICK {sha[:11]} {subj}")

with open(os.path.join(LOG, 'phase-b-apply.log'), 'w') as f:
    f.write("\n".join(log))
print("Phase B applied")
PY

# Promote
git branch -f "$OUTPUT_BRANCH" "$WORK"
git checkout -q "$OUTPUT_BRANCH"
git branch -D "$WORK"

# Verify null diff
diff_lines=$(git diff "$OUTPUT_BRANCH" "$SRC_BRANCH" | wc -l)
echo "Phase B done. Diff vs $SRC_BRANCH: $diff_lines lines (must be 0)"
[ "$diff_lines" -eq 0 ] || { echo "PHASE C FAILED" >&2; exit 1; }

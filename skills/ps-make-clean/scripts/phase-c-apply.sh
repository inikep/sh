#!/bin/bash
# Phase C applier: contiguous-prefix squashes first, then attempt reorder for non-contiguous.
#
# Inputs (env): BASE_BRANCH, SRC_BRANCH, OUTPUT_BRANCH, LOG_DIR
set -e
: "${BASE_BRANCH:?}" "${SRC_BRANCH:?}" "${OUTPUT_BRANCH:?}" "${LOG_DIR:?}"

# Run bug extraction + follow-up detection
SCRIPT_DIR="$(dirname "$0")"
python3 "$SCRIPT_DIR/extract-bugs.py"      "$BASE_BRANCH..$OUTPUT_BRANCH" > "$LOG_DIR/bugs.tsv"
python3 "$SCRIPT_DIR/follow-up-detect.py"  "$BASE_BRANCH..$OUTPUT_BRANCH" > "$LOG_DIR/followups.tsv"
LOG_DIR="$LOG_DIR" BASE_BRANCH="$BASE_BRANCH" OUTPUT_BRANCH="$OUTPUT_BRANCH" \
  python3 "$SCRIPT_DIR/phase-c-plan.py"

# Build squashed branch from BASE_BRANCH
WORK="${OUTPUT_BRANCH}-phase-c"
git branch -D "$WORK" 2>/dev/null || true
git checkout -q -b "$WORK" "$BASE_BRANCH"

python3 - <<'PY'
import os, json, subprocess, sys, tempfile

LOG = os.environ['LOG_DIR']
with open(os.path.join(LOG, 'phase-c-plan.json')) as f:
    plan = json.load(f)

chrono   = plan['chrono']
groups   = plan['contiguous_groups']      # carrier -> contiguous members
nc       = plan['non_contiguous_residuals']  # carrier -> non-contig members
absorbed = set()
for m_list in groups.values():
    for m in m_list[1:]:
        absorbed.add(m)

def run(*a, **kw): return subprocess.run(a, capture_output=True, text=True, **kw)

log = []
for i, sha in enumerate(chrono):
    subj = subprocess.check_output(['git','log','-1','--format=%s', sha]).decode().strip()[:60]
    if sha in absorbed:
        log.append(f"[{i+1}] DEFER {sha[:11]} (absorbed)")
        continue
    if sha in groups:
        members = groups[sha]
        msgs = []
        for m in members:
            r = run('git','cherry-pick','--no-commit', m)
            if r.returncode:
                log.append(f"[{i+1}] CONFLICT in group {sha[:11]} on member {m[:11]}")
                print(r.stdout, file=sys.stderr); print(r.stderr, file=sys.stderr); sys.exit(1)
            msgs.append(subprocess.check_output(['git','log','-1','--format=%B', m]).decode().rstrip())
        env = os.environ.copy()
        for fmt,var in [('%an','GIT_AUTHOR_NAME'),('%ae','GIT_AUTHOR_EMAIL'),
                        ('%aI','GIT_AUTHOR_DATE'),('%cn','GIT_COMMITTER_NAME'),
                        ('%ce','GIT_COMMITTER_EMAIL'),('%cI','GIT_COMMITTER_DATE')]:
            env[var] = subprocess.check_output(['git','log','-1','--format='+fmt, sha]).decode().strip()
        fd,mp = tempfile.mkstemp(); os.write(fd, ("\n\n-----\n\n".join(msgs)).encode()); os.close(fd)
        r = subprocess.run(['git','commit','-q','--no-verify','--file', mp], env=env)
        os.unlink(mp)
        if r.returncode: log.append(f"COMMIT FAIL {sha[:11]}"); sys.exit(1)
        log.append(f"[{i+1}] GROUP {sha[:11]} squashed {len(members)} members")
    else:
        r = run('git','cherry-pick', sha)
        if r.returncode:
            log.append(f"[{i+1}] CONFLICT singleton {sha[:11]} {subj}")
            print(r.stdout, file=sys.stderr); print(r.stderr, file=sys.stderr); sys.exit(1)
        log.append(f"[{i+1}] PICK {sha[:11]} {subj}")

with open(os.path.join(LOG, 'phase-c-apply.log'),'w') as f:
    f.write("\n".join(log))
print("Phase C (contiguous only) done")
PY

# Attempt non-contiguous reorders: for each carrier with non-contig residuals,
# rebase the work branch with a todo that puts each residual member right after
# the carrier's squashed commit. If conflict can't be auto-resolved, skip that
# specific member and continue.
#
# (See SKILL.md for the engineer-approved aggressive-reorder policy. The skipped
# residuals remain as singletons; this script records which non-contiguous
# members were absorbed and which were left as singletons in
# $LOG_DIR/phase-c-residual-outcomes.log.)
SCRIPT_DIR="$(dirname "$0")"
python3 "$SCRIPT_DIR/phase-c-residuals.py" || true

# Promote the worktree to OUTPUT_BRANCH
git branch -f "$OUTPUT_BRANCH" "$WORK"
git checkout -q "$OUTPUT_BRANCH"
git branch -D "$WORK"

# Verify null diff
diff_lines=$(git diff "$OUTPUT_BRANCH" "$SRC_BRANCH" | wc -l)
echo "Phase C done. Diff vs $SRC_BRANCH: $diff_lines lines (must be 0)"
[ "$diff_lines" -eq 0 ] || { echo "PHASE B FAILED" >&2; exit 1; }

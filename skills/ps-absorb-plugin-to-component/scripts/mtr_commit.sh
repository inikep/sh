#!/bin/bash
# usage: mtr_commit.sh WORKTREE BUILDDIR TIP SUITE [MTR_ARGS...]
# Runs SUITE for the commit checked out in WORKTREE (built in BUILDDIR, e.g. by
# build_commit.sh). Old commits often have a broken mysql-test-run.pl, so the TIP's
# mysql-test-run.pl and mysql-test/lib are overlaid in the (scratch) worktree; include/plugin.defs
# is overlaid only if the tip harness rejects the commit's format (check that commit's line by eye).
# The warnings check is off (old servers under a new harness produce noise); a test passes when
# its body completes without a result mismatch. main.1st runs separately as the control
# (naming a test together with --suite would restrict the run to that test).
# Parallel workers: $MTR_PARALLEL (default 16).
set -u
WT=$1 BLD=$2 TIP=$3 SUITE=$4; shift 4
cd "$WT" || exit 2
git show "$TIP:mysql-test/mysql-test-run.pl" > mysql-test/mysql-test-run.pl
rm -rf mysql-test/lib && git archive "$TIP" mysql-test/lib | tar -x -C "$WT"
V=$BLD/mtr-var; LOG=$BLD/mtr-logs; mkdir -p "$LOG"
run() { (cd "$BLD/mysql-test" && perl mysql-test-run.pl --vardir="$V-$1" --force --nowarnings \
         --mysqld=--lc-messages-dir="$BLD/share" "${@:2}") > "$LOG/$1.log" 2>&1; }
run ctl --parallel=1 --suite=main main.1st
if grep -q 'Lines in include/plugin.defs must have' "$LOG/ctl.log"; then
  echo "overlaying tip plugin.defs (commit line: $(grep -i "$SUITE" mysql-test/include/plugin.defs | head -1))"
  git show "$TIP:mysql-test/include/plugin.defs" > mysql-test/include/plugin.defs
  run ctl --parallel=1 --suite=main main.1st
fi
echo "control: $(grep -a '^Completed' "$LOG/ctl.log")"
run suite --parallel=${MTR_PARALLEL:-16} --max-test-fail=0 --suite="$SUITE" "$@"
echo "suite:   $(grep -a '^Completed' "$LOG/suite.log")"
grep -aE '\[ fail \]' "$LOG/suite.log" | sed -E 's/^\[[^]]*\] *//' | cut -c1-100
echo "logs: $LOG"

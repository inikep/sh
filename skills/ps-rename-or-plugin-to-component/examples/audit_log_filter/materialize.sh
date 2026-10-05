#!/bin/bash
# materialize.sh STATE_TSV COMMIT : scratch worktree $WT at COMMIT with the component state applied
W=/data/ps-replay-vps-8.1.0-build/alf; TSV=$1; C=$2; WT=${WT:-$W/wt}
[ -s "$TSV" ] || { echo "no state file $TSV"; exit 2; }
cd /data/percona-server-linear
if [ ! -d $WT ]; then git worktree add -q --detach $WT $C 2>/dev/null; else git -C $WT checkout -q --detach -f $C 2>/dev/null; git -C $WT clean -qfd components/audit_log_filter mysql-test/suite/component_audit_log_filter plugin/audit_log_filter 2>/dev/null; fi
cd $WT
git rm -rq --cached plugin/audit_log_filter 2>/dev/null; rm -rf plugin/audit_log_filter components/audit_log_filter mysql-test/suite/component_audit_log_filter
while IFS=$'\t' read p m b; do mkdir -p "$(dirname "$p")"; git cat-file blob $b > "$p"; [ "$m" = 100755 ] && chmod +x "$p"; done < $TSV
git show 4c08e7b0005a:mysql-test/include/have_component_audit_log.inc > mysql-test/include/have_component_audit_log.inc
for kp in "errlog share/messages_to_error_log.txt" "defs mysql-test/include/plugin.defs" "mtr mysql-test/mysql-test-run.pl"; do set -- $kp; [ -f $2 ] && { python3 $W/misc_transform.py $1 < $2 > $2.new && mv $2.new $2 || echo "misc transform $1 FAILED"; }; done
echo "materialized $(wc -l < $TSV) files at $(git log -1 --format='%h %s' | cut -c1-70)"

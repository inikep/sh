#!/bin/bash
set -o pipefail

SCRIPT_DIR=/data/pstress/pstress/scripts
AUDIT_DIR=$SCRIPT_DIR/audit_log
DATA_DIR=/mnt/black/pstress-run/workdir-8044/audit_log_filter

BASEDIR=/data/mysql-server/percona-8.4-deb-gcc14-rocks
#BASEDIR=/data/mysql-server/percona-8.4-rel-gcc14-rocks-847-PS-10324

$SCRIPT_DIR/mysql_option_tester.py \
   --basedir $BASEDIR \
   --datadir $DATA_DIR/data_alf \
   --sql $AUDIT_DIR/test_audit_log_filter_84_component.sql \
   --sql $AUDIT_DIR/test_common_filters.sql \
   --sql $AUDIT_DIR/test_common_lang_cp1250.sql \
   --charset "cp1250" \
   --opt-file $AUDIT_DIR/audit_log.opt
#   --socket

#   --sh $SCRIPT_DIR/run_mysqlslap.sh \

#   --sql $AUDIT_DIR/test_common.sql \
#   --sql $AUDIT_DIR/udf_audit_log_format.sql \
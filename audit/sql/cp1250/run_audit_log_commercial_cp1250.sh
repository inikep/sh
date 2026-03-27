#!/bin/bash
set -o pipefail

SCRIPT_DIR=/data/pstress/pstress/scripts
AUDIT_DIR=$SCRIPT_DIR/audit_log
DATA_DIR=/mnt/black/pstress-run/workdir-8044/audit_log_filter

$SCRIPT_DIR/mysql_option_tester.py \
   --basedir /data/mysql-server/mysql-8.4.7-commercial \
   --datadir $DATA_DIR/data_alf \
   --sql $AUDIT_DIR/test_audit_log_commercial.sql \
   --sql $AUDIT_DIR/test_common_filters.sql \
   --sql $AUDIT_DIR/test_common_lang_cp1250.sql \
   --charset "cp1250" \
   --opt-file $AUDIT_DIR/audit_log.opt

#   --sql $AUDIT_DIR/test_common.sql \
#   --sql $AUDIT_DIR/udf_audit_log_format.sql \

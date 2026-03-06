#!/bin/bash
set -o pipefail

usage() {
    cat <<EOF
Usage: $0 <mode> [sql_file]

  sql_file defaults to table_access_field_filters.sql

Modes:
  80old        (a) Old audit_log plugin           – Percona Server 8.0
  80plugin     (b) audit_log_filter plugin        – Percona Server 8.0
  84component  (c) audit_log_filter component     – Percona Server 8.4 / 9.7
  84enterprise (d) audit_log commercial plugin    – MySQL 8.4 Enterprise
EOF
    exit 1
}

MODE="${1:-}"
[[ -z "$MODE" ]] && usage

SCRIPT_DIR=/data/sh/deployer
AUDIT_DIR=/data/sh/deployer/audit
LOGS_DIR=/data/sh/deployer/audit/logs_audit

SQL_FILE="${2:-table_access_field_filters.sql}"
CNF_FILE=$SCRIPT_DIR/cnf/innodb-84-audit.cnf

case "$MODE" in
    80o*)
        TAG=alf80old
        BASEDIR=/data/mysql-server/percona-8.0-deb-gcc14-rocks
        MYSQLD_PARAMS="--loose-audit_log_file=$LOGS_DIR/${TAG}.json_"
        INSTALL_FILE=install/audit_log_setup.sql
        ;;
    80p*)
        TAG=alf80plugin
        BASEDIR=/data/mysql-server/percona-8.0-deb-gcc14-rocks
        MYSQLD_PARAMS="--loose-audit_log_filter_file=$LOGS_DIR/${TAG}.json_"
        INSTALL_FILE=install/audit_log_filter_80_plugin_install.sql
        ;;
    84c*)
        TAG=alf84component
        BASEDIR=/data/mysql-server/percona-8.4-deb-gcc15-rocks
        #BASEDIR=/data/mysql-server/ai-deb-gcc15-rocks
        MYSQLD_PARAMS="--loose-audit_log_filter.file=$LOGS_DIR/${TAG}.json_"
        INSTALL_FILE=install/audit_log_filter_84_component_install.sql
        ;;
    84e*)
        TAG=alf84enterprise
        BASEDIR=/data/mysql-server/mysql-8.4.7-commercial
        MYSQLD_PARAMS="--loose-audit_log_file=$LOGS_DIR/${TAG}.json_"
        INSTALL_FILE=install/audit_log_commercial_install.sql
        ;;
    *)
        echo "ERROR: unknown mode '$MODE'"
        usage
        ;;
esac

DATA_DIR=/data/sh/deployer/work/datadir_${TAG}

echo "[INFO] Mode: $MODE"
echo "[INFO] BASEDIR:  $BASEDIR"
echo "[INFO] DATA_DIR: $DATA_DIR"
echo "[INFO] INSTALL:  $INSTALL_FILE"
echo "[INFO] SQL:      $SQL_FILE"

$SCRIPT_DIR/mysql_deployer.py \
   --basedir $BASEDIR \
   --datadir $DATA_DIR \
   --cnf $CNF_FILE \
   --params="$MYSQLD_PARAMS" \
   --sql $AUDIT_DIR/$INSTALL_FILE  \
   --sql $AUDIT_DIR/$SQL_FILE

#  --sql $AUDIT_DIR/$COMMON_SQL \
#  --socket
#  --sh $SCRIPT_DIR/run_mysqlslap.sh \

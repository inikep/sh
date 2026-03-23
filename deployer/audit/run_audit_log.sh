#!/bin/bash
set -o pipefail

usage() {
    cat <<EOF
Usage: $0 <mode> [sql_file] [format]

  sql_file defaults to table_access_field_filters.sql
  format   defaults to JSON; use NEW for the NEW (XML-based) audit format
           (pass sql_file before format, e.g. ... table_access_field_filters.sql NEW)

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

COMMON_SQL=common_filters.sql
SQL_FILE="${2:-table_access_field_filters.sql}"
AUDIT_FORMAT_RAW="${3:-JSON}"
# Bash 4+: uppercase for comparison; strip accidental whitespace
AUDIT_FORMAT="${AUDIT_FORMAT_RAW^^}"
AUDIT_FORMAT="${AUDIT_FORMAT//[[:space:]]/}"

case "$AUDIT_FORMAT" in
    JSON|NEW) ;;
    *)
        echo "ERROR: unknown format '$AUDIT_FORMAT_RAW' (use JSON or NEW)"
        usage
        ;;
esac

CNF_FILE=$SCRIPT_DIR/cnf/innodb-84-audit.cnf

case "$MODE" in
    80o*)
        TAG=alf80old
        BASEDIR=/data/mysql-server/percona-8.0-deb-gcc14-rocks
        FILTER_FORMAT_KEY="--loose-audit_log_format="
        INSTALL_FILE=install/audit_log_setup.sql
        ;;
    80p*)
        TAG=alf80plugin
        BASEDIR=/data/mysql-server/percona-8.0-deb-gcc14-rocks
        FILTER_FORMAT_KEY="--loose-audit_log_filter_format="
        INSTALL_FILE=install/audit_log_filter_80_plugin_install.sql
        ;;
    84entc*)
        TAG=alf84ent_component
        BASEDIR=/data/mysql-server/mysql-8.4.7-commercial
        #BASEDIR=/data/mysql-server/ai-deb-gcc15-rocks
        FILTER_FORMAT_KEY="--loose-audit_log_filter.format="
        INSTALL_FILE=install/audit_log_filter_84_component_install.sql
        ;;
    84c*)
        TAG=alf84component
        #BASEDIR=/data/mysql-server/percona-8.4-deb-gcc15-rocks
        BASEDIR=/data/mysql-server/ai-deb-gcc15-rocks
        FILTER_FORMAT_KEY="--loose-audit_log_filter.format="
        INSTALL_FILE=install/audit_log_filter_84_component_install.sql
        ;;
    84e*)
        TAG=alf84enterprise
        BASEDIR=/data/mysql-server/mysql-8.4.7-commercial
        FILTER_FORMAT_KEY="--loose-audit_log_format="
        INSTALL_FILE=install/audit_log_commercial_install.sql
        ;;
    *)
        echo "ERROR: unknown mode '$MODE'"
        usage
        ;;
esac

if [[ "$AUDIT_FORMAT" == "NEW" ]]; then
    TAG="${TAG}_new"
fi

case "$MODE" in
    80o*|84e*)
        LOG_BASENAME_EXT=$([[ "$AUDIT_FORMAT" == JSON ]] && echo json || echo new)
        MYSQLD_PARAMS="--loose-audit_log_file=$LOGS_DIR/${TAG}.${LOG_BASENAME_EXT}_"
        ;;
    80p*)
        LOG_BASENAME_EXT=$([[ "$AUDIT_FORMAT" == JSON ]] && echo json || echo new)
        MYSQLD_PARAMS="--loose-audit_log_filter_file=$LOGS_DIR/${TAG}.${LOG_BASENAME_EXT}_"
        ;;
    84entc*|84c*)
        LOG_BASENAME_EXT=$([[ "$AUDIT_FORMAT" == JSON ]] && echo json || echo new)
        MYSQLD_PARAMS="--loose-audit_log_filter.file=$LOGS_DIR/${TAG}.${LOG_BASENAME_EXT}_"
        ;;
esac

FILTER_FORMAT="${FILTER_FORMAT_KEY}${AUDIT_FORMAT}"

DATA_DIR=/data/sh/deployer/work/datadir_${TAG}

echo "[INFO] Mode:   $MODE"
echo "[INFO] Format: $AUDIT_FORMAT"
echo "[INFO] BASEDIR:  $BASEDIR"
echo "[INFO] DATA_DIR: $DATA_DIR"
echo "[INFO] INSTALL:  $INSTALL_FILE"
echo "[INFO] SQL:      $SQL_FILE"

$SCRIPT_DIR/mysql_deployer.py \
   --basedir $BASEDIR \
   --datadir $DATA_DIR \
   --cnf $CNF_FILE \
   --params="$MYSQLD_PARAMS $FILTER_FORMAT" \
   --sql $AUDIT_DIR/$INSTALL_FILE  \
   --sql $AUDIT_DIR/$COMMON_SQL  \
   --sql $AUDIT_DIR/$SQL_FILE

#  --sql $AUDIT_DIR/$COMMON_SQL \
#  --socket
#  --sh $SCRIPT_DIR/run_mysqlslap.sh \

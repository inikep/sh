#!/bin/bash
set -o pipefail

usage() {
    cat <<EOF
Usage: $0 <mode> <format> [sql_file1] [sql_file2] .. [sql_fileX]

  format    JSON or NEW (XML-based audit format).
  sql_files default to table_access_field_filters.sql when none are given.

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
shift

DEPLOYER_DIR=/data/sh/deployer
AUDIT_DIR=/data/sh/audit
CNF_FILE=$AUDIT_DIR/cnf/innodb-84-audit.cnf

#COMMON_SQL=sql/filters_simple.sql

DEFAULT_SQL=( "table_access_field_filters.sql" )
[[ $# -lt 1 ]] && usage

AUDIT_FORMAT_RAW="${1}"
AUDIT_FORMAT="${AUDIT_FORMAT_RAW^^}"
AUDIT_FORMAT="${AUDIT_FORMAT//[[:space:]]/}"
shift

case "$AUDIT_FORMAT" in
    JSON|NEW) ;;
    *)
        echo "ERROR: unknown format '$AUDIT_FORMAT_RAW' (use JSON or NEW)"
        usage
        ;;
esac

if (($# == 0)); then
    SQL_FILES=( "${DEFAULT_SQL[@]}" )
else
    SQL_FILES=( "$@" )
fi

_log_label_parts=()
for _sf in "${SQL_FILES[@]}"; do
    _log_label_parts+=( "$(basename "${_sf}" .sql)" )
done
LOG_LABEL=$(IFS=+; echo "${_log_label_parts[*]}")
LOGS_DIR=$AUDIT_DIR/logs/${LOG_LABEL}_${AUDIT_FORMAT}
mkdir -p $LOGS_DIR

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
        BASEDIR=/data/mysql-server/percona-8.4-deb-gcc15-rocks
        #BASEDIR=/data/mysql-server/ai-deb-gcc15-rocks
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

DATA_DIR=/data/sh/audit/work/datadir_${TAG}

echo "[INFO] Mode:   $MODE"
echo "[INFO] Format: $AUDIT_FORMAT"
echo "[INFO] BASEDIR:  $BASEDIR"
echo "[INFO] DATA_DIR: $DATA_DIR"
echo "[INFO] INSTALL:  $INSTALL_FILE"
echo "[INFO] SQL:      ${SQL_FILES[*]}"
echo "[INFO] LOGS_DIR: $LOGS_DIR"

SQL_DEPLOY_ARGS=( )
for _sf in "${SQL_FILES[@]}"; do
    SQL_DEPLOY_ARGS+=( --sql "$AUDIT_DIR/$_sf" )
done

$DEPLOYER_DIR/mysql_deployer.py \
   --basedir $BASEDIR \
   --datadir $DATA_DIR \
   --cnf $CNF_FILE \
   --params="$MYSQLD_PARAMS $FILTER_FORMAT --loose-audit_log_filter.event_mode=FULL" \
   --sql "$AUDIT_DIR/$INSTALL_FILE" \
   "${SQL_DEPLOY_ARGS[@]}"

#  --sql "$AUDIT_DIR/$COMMON_SQL"
#  --socket
#  --sh $DEPLOYER_DIR/run_mysqlslap.sh \

# Deployer can return before the audit component finishes renaming TAG.<ext>_ to
# TAG.<timestamp>.<ext>_ (async strategy / shutdown ordering). Wait until the
# active basename disappears or timeout, so the picker sees the final rotation.
AUDIT_ACTIVE_LOG="$LOGS_DIR/${TAG}.${LOG_BASENAME_EXT}_"
_audit_wait_until=$((SECONDS + 30))
while [[ -e "$AUDIT_ACTIVE_LOG" ]] && (( SECONDS < _audit_wait_until )); do
  sleep 0.2
done
if [[ -e "$AUDIT_ACTIVE_LOG" ]]; then
  echo "[WARN] Active audit log still present after 30s wait: $AUDIT_ACTIVE_LOG"
fi

# Glob TAG.<timestamp>.<ext>_ (not *<ext>_2); newest by mtime. With the active-log
# wait above this is usually correct; if not, pick by timestamp in the basename instead.
AUDIT_LOG_PATH=""
shopt -s nullglob
ROTATED=( "$LOGS_DIR/${TAG}."*".${LOG_BASENAME_EXT}_" )
shopt -u nullglob
if ((${#ROTATED[@]} > 0)); then
  AUDIT_LOG_PATH="$(ls -t "${ROTATED[@]}" | head -n1)"
else
  AUDIT_LOG_PATH="$LOGS_DIR/${TAG}.${LOG_BASENAME_EXT}_"
fi

if [[ ! -s "$AUDIT_LOG_PATH" ]]; then
  echo "[WARN] No audit log to post-process (expected rotated file under $LOGS_DIR or $AUDIT_LOG_PATH)"
else
  OUT_PATH="${AUDIT_LOG_PATH%.${LOG_BASENAME_EXT}_}.filter.${LOG_BASENAME_EXT}_"
  if [[ "$AUDIT_FORMAT" == "NEW" ]]; then
    echo "[INFO] sort_xml_sibling_tags.py input: $AUDIT_LOG_PATH"
    /data/sh/utils/sort_xml_sibling_tags.py "$AUDIT_LOG_PATH" -o "$OUT_PATH"
  else
    echo "[INFO] unfold_json.py input: $AUDIT_LOG_PATH"
    /data/sh/utils/unfold_json.py "$AUDIT_LOG_PATH" "$OUT_PATH"
    python3 - "$OUT_PATH" <<'PY'
import json, sys

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)

pairs = set()
if isinstance(data, list):
    for item in data:
        if isinstance(item, dict):
            c, e = item.get("class"), item.get("event")
            if c is not None and e is not None:
                pairs.add((str(c), str(e)))
elif isinstance(data, dict):
    c, e = data.get("class"), data.get("event")
    if c is not None and e is not None:
        pairs.add((str(c), str(e)))

print(f"[INFO] unique class/event pairs: {len(pairs)}")
for c, e in sorted(pairs):
    print(f"--- {c}/{e} ---")
PY
  fi
fi

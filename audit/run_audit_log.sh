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

DEPLOYER_DIR=/data/sh/deployer
AUDIT_DIR=/data/sh/audit
CNF_FILE=$AUDIT_DIR/cnf/innodb-84-audit.cnf

COMMON_SQL=filter_all.sql
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

LOGS_DIR=$AUDIT_DIR/logs_audit_${AUDIT_FORMAT}
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
echo "[INFO] SQL:      $SQL_FILE"
echo "[INFO] LOGS_DIR: $LOGS_DIR"

# Bound this run's audit output: the newest path in LOGS_DIR may be from another
# mysqld that shares the same directory, not from mysql_deployer.py below.
AUDIT_RUN_MARKER="$LOGS_DIR/.audit_run_marker.$$.$RANDOM"
touch "$AUDIT_RUN_MARKER"
trap 'rm -f -- "$AUDIT_RUN_MARKER" 2>/dev/null' EXIT

$DEPLOYER_DIR/mysql_deployer.py \
   --basedir $BASEDIR \
   --datadir $DATA_DIR \
   --cnf $CNF_FILE \
   --params="$MYSQLD_PARAMS $FILTER_FORMAT" \
   --sql $AUDIT_DIR/$INSTALL_FILE  \
   --sql $AUDIT_DIR/$COMMON_SQL  \
   --sql $AUDIT_DIR/$SQL_FILE

#  --sql $AUDIT_DIR/$COMMON_SQL \
#  --socket
#  --sh $DEPLOYER_DIR/run_mysqlslap.sh \

# Server rotates the active log on shutdown to TAG.<timestamp>.<ext>_ (rename).
# On Linux, rename updates ctime but not mtime, so mtime can stay *before* the
# pre-run marker while ctime reflects this shutdown — use max(mtime, ctime).
# Then max embedded time (YYYYMMDDTHHMMSS[-N]). AUDIT_LOG_DEBUG=1 for stderr trace.
AUDIT_LOG_PATH="$(
  LOGS_DIR="$LOGS_DIR" TAG="$TAG" LOG_BASENAME_EXT="$LOG_BASENAME_EXT" \
  AUDIT_RUN_MARKER="$AUDIT_RUN_MARKER" \
  AUDIT_LOG_DEBUG="${AUDIT_LOG_DEBUG:-}" \
  python3 - <<'PY'
import glob, os, re, sys

log_dir = os.environ["LOGS_DIR"]
tag = os.environ["TAG"]
ext = os.environ["LOG_BASENAME_EXT"]
marker_path = os.environ.get("AUDIT_RUN_MARKER", "")
debug = os.environ.get("AUDIT_LOG_DEBUG", "").lower() in ("1", "yes", "true")

def dbg(*a):
    if debug:
        print(*a, file=sys.stderr)

suffix = "." + ext + "_"
paths = glob.glob(os.path.join(log_dir, f"{tag}.*{suffix}"))
paths = [p for p in paths if p.endswith(suffix) and not p.endswith(suffix + "2")]
rx = re.compile(r"\.(\d{8}T\d{6})(?:-(\d+))?" + re.escape(suffix) + r"$")

def sort_key(path):
    m = rx.search(os.path.basename(path))
    if not m:
        return ("", -1)
    return (m.group(1), int(m.group(2) or 0))

dbg("audit log pick:", "LOGS_DIR=", log_dir, "TAG=", tag, "EXT=", ext)
dbg("marker=", marker_path, "exists=", os.path.exists(marker_path) if marker_path else False)
dbg("glob count=", len(paths), "names=", [os.path.basename(p) for p in sorted(paths)])

if not paths:
    sys.exit(0)

marker_t0 = None
if marker_path and os.path.exists(marker_path):
    marker_t0 = os.stat(marker_path).st_mtime


def activity_time(path):
    st = os.stat(path)
    return max(st.st_mtime, st.st_ctime)


scoped = paths
if marker_t0 is not None:
    scoped = [p for p in paths if activity_time(p) >= marker_t0]
    dbg(
        "after max(mtime,ctime)>=marker:",
        len(scoped),
        [os.path.basename(p) for p in sorted(scoped)],
    )
    if debug and paths:
        for p in sorted(paths)[-3:]:
            st = os.stat(p)
            dbg(
                "  ",
                os.path.basename(p),
                "mtime",
                st.st_mtime,
                "ctime",
                st.st_ctime,
                "marker",
                marker_t0,
            )

if not scoped:
    print(
        "[WARN] run_audit_log.sh: no rotated audit file changed since the run marker "
        "(max(mtime,ctime)); using newest name in LOGS_DIR (AUDIT_LOG_DEBUG=1 for details).",
        file=sys.stderr,
    )
    dbg("activity filter empty; falling back to all glob matches")
    scoped = paths

parsed = [p for p in scoped if rx.search(os.path.basename(p))]
if parsed:
    chosen = max(parsed, key=sort_key)
else:
    chosen = max(scoped)
dbg("chosen=", os.path.basename(chosen), "key=", sort_key(chosen))
print(chosen)
PY
)"
if [[ -z "$AUDIT_LOG_PATH" ]]; then
  AUDIT_LOG_PATH="$LOGS_DIR/${TAG}.${LOG_BASENAME_EXT}_"
fi

if [[ ! -s "$AUDIT_LOG_PATH" ]]; then
  echo "[WARN] No audit log to post-process (expected rotated file under $LOGS_DIR or $AUDIT_LOG_PATH)"
else
  OUT_PATH="${AUDIT_LOG_PATH}2"
  if [[ "$AUDIT_FORMAT" == "NEW" ]]; then
    echo "[INFO] sort_xml_sibling_tags.py input: $AUDIT_LOG_PATH"
    /data/sh/utils/sort_xml_sibling_tags.py "$AUDIT_LOG_PATH" -o "$OUT_PATH"
  else
    echo "[INFO] unfold_json.py input: $AUDIT_LOG_PATH"
    /data/sh/utils/unfold_json.py "$AUDIT_LOG_PATH" "$OUT_PATH"
  fi
fi

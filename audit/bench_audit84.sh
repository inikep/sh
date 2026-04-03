#set -x
#export ENGINE=rocksdb
export ENGINE=innodb
export ENGINE_CACHE=32G
export NUM_TABLES=16
export DATASIZE=100K
export START_DATE=$(date +"%Y-%m-%d_%H:%M:%S")

export WARMUP_TIME_SECONDS=0
export WRITES_TIME_SECONDS=60
export READS_TIME_SECONDS=60
#export MYEXTRA="--innodb_status_output=ON --innodb_status_output_locks=ON --innodb_monitor_enable='all'"
#export RESULTS_EMAIL=przemyslaw.skibinski@percona.com
export SMART_DEVICE=/dev/nvme0
export SCALING_GOVERNOR=performance

HOME_DIR=/data
BENCH_DIR=$HOME_DIR/db-bench
export WORKSPACE=$HOME_DIR/db-res

export SYSBENCH_LUA=/data/benchmark/sysbench_inikep/src/lua
export SYSBENCH_BIN=/data/benchmark/sysbench_inikep/src/sysbench
#export SYSBENCH_EXTRA="--report-interval=1 --events=4000 --debug=on --mysql-debug=on"

export THREADS_LIST="8" # 16"
#export WORKLOAD_NAMES="POINT_SELECT"
export WORKLOAD_NAMES="SIMPLE_RANGES"
#export WORKLOAD_NAMES="READ_ONLY,READ_WRITE,WRITE_ONLY"
NICE_DATE=$(date +"%Y-%m-%d_%H:%M")
export BENCH_NAME=9554_8-4-8_${NICE_DATE}

#export TASKSET_MYSQLD="gdb -ex run --args"
export FLAMEGRAPH_PATH=/data/benchmark/FlameGraph
#export PROFILER=1

# Audit log filter setup
AUDIT_MODE=${AUDIT_MODE:-alf84component}
STRATEGY=${STRATEGY:-ASYNCHRONOUS}
FORMAT=${FORMAT:-json}
EVENT_MODE=${EVENT_MODE:-REDUCED}
DIRECT_IO=${DIRECT_IO:-OFF}
AUDIT_DIR=/data/sh/audit
export CONFIG_FILES="$AUDIT_DIR/cnf/innodb-84-audit.cnf"
export SETUP_SQL_PATH=$AUDIT_DIR/sql/filters_simple.sql

# filter_all, filter_tab_anyField, filter_gen_manyFields, filter_gen, filter_tab
FILTER_NAME=${FILTER_NAME:-filter_all}
export RUN_SQL_COMMANDS="SELECT audit_log_filter_set_user('%', '${FILTER_NAME}')"
LOGS_DIR=/mnt/black/logs/audit_log_${FILTER_NAME}
#LOGS_DIR=$AUDIT_DIR/logs/db-bench

# Pick backend: alf84enterprise | old84plugin | alf84component
mkdir -p $LOGS_DIR
case "$AUDIT_MODE" in
    alf84enterprise)
        TAG=alf84enterprise
        export BUILD_PATH=/data/mysql-server/mysql-8.4.7-commercial
        export INSTALL_SQL_PATH=$AUDIT_DIR/install/audit_log_commercial_install.sql
        # export INSTALL_SQL_PATH=$AUDIT_DIR/audit_log_commercial_legacy_install.sql
        export MYEXTRA="--loose-audit_log_format=${FORMAT} --loose-audit_log_strategy=$STRATEGY --loose-audit_log_file=$LOGS_DIR/${TAG}_${STRATEGY}.${FORMAT}_ "
        ;;
    old84plugin)
        TAG=old84plugin
        export BUILD_PATH=/data/mysql-server/percona-8.4-rel-gcc15-rocks
        export INSTALL_SQL_PATH=$AUDIT_DIR/install/audit_log_setup.sql
        unset MYEXTRA
        ;;
    alf84component)
        TAG=alf84component
        export BUILD_PATH=/data/mysql-server/percona-8.4-rel-gcc15-rocks
        export INSTALL_SQL_PATH=$AUDIT_DIR/install/audit_log_filter_84_component_install.sql
        export MYEXTRA="--loose-audit_log_filter.direct_io=${DIRECT_IO} --loose-audit_log_filter.format=${FORMAT} --loose-audit_log_filter.strategy=$STRATEGY --loose-audit_log_filter.file=$LOGS_DIR/${TAG}_${STRATEGY}.${FORMAT}_  --loose-audit_log_filter.event_mode=$EVENT_MODE"
        ;;
    *)
        echo "ERROR: unknown AUDIT_MODE='$AUDIT_MODE' (alf84enterprise, old84plugin, alf84component)" >&2
        exit 1
        ;;
esac

$HOME_DIR/db-bench/db-bench.sh

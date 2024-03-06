#!/bin/echo This script should be sourced in a shell, not executed directly
#set -x

function usage() {
  echo $1
  echo "Usage: BUILD_PATH=<BUILD_PATH> CONFIG_FILE=<MYSQL_CONFIG_FILE> ; $0"
  echo "where:"
  echo "<BUILD_PATH> - full path to MySQL or Percona Server binaries"
  echo "<MYSQL_CONFIG_FILE> - full path to Percona Server's configuration file"
  return 1
}

function init_datadir() {
  if [ $# -lt 2 ]; then echo "Usage: init_datadir <DATADIR> <LOG_INIT>"; return 1; fi
  local DATADIR=$1
  local LOG_INIT=$2
  local BASEDIR=$BUILD_PATH
  rm -rf $DATADIR
  mkdir $DATADIR
  $MYSQLD_BIN --no-defaults --initialize-insecure --basedir=$BASEDIR --datadir=$DATADIR --log-error-verbosity=3 >$LOG_INIT 2>&1
}

function start_mysqld() {
  if [ $# -lt 4 ]; then echo "Usage: start_mysqld <DATADIR> <SOCKET> <PORT> <LOG_ERROR> [MORE_PARAMS]"; return 1; fi
  local DATADIR=$1
  local SOCKET=$2
  local PORT=$3
  local LOG_ERROR=$4
  local MORE_PARAMS=$5
  local BASEDIR=$BUILD_PATH
  local DEFAULTS_FILE=$CONFIG_FILE
  local START_TIMEOUT=300
  # --default-authentication-plugin=mysql_native_password --gtid_mode=ON --enforce_gtid_consistency=ON
  local MYSQLD_PARAMS="--defaults-file=$DEFAULTS_FILE --basedir=$BASEDIR --datadir=$DATADIR --socket=$SOCKET --port=$PORT $MORE_PARAMS --log-error=$LOG_ERROR"
  echo "- Starting Percona Server with options $MYSQLD_PARAMS" | tee -a $LOG_ERROR
  $MYSQLD_BIN $MYSQLD_PARAMS >>$LOG_ERROR 2>&1 &

  for X in $(seq 0 ${START_TIMEOUT}); do
    sleep 1
    if ${BUILD_PATH}/bin/mysqladmin -u$MYSQL_USER -S$SOCKET ping > /dev/null 2>&1; then
      echo "- Server started: Socket=$SOCKET Port=$PORT"
      break
    fi
  done
  ${BUILD_PATH}/bin/mysqladmin -u$MYSQL_USER -S$SOCKET ping > /dev/null 2>&1 || { echo “Couldn\'t connect $SOCKET && return 0; }
}

function shutdown_mysqld() {
  if [ $# -lt 2 ]; then echo "Usage: shutdown_mysqld <HOST> <PORT>"; return 1; fi
  local HOST=$1
  local PORT=$2
  echo "- Shutting mysqld down"
  ${BUILD_PATH}/bin/mysqladmin -u$MYSQL_USER --host=$HOST --port=$PORT shutdown # >/dev/null 2>&1
  echo "- Shutting mysqld down - done"
}

function mysql_client() {
  if [ $# -lt 3 ]; then echo "Usage: mysql_client <HOST> <PORT> <COMMAND>"; return 1; fi
  local HOST=$1
  local PORT=$2
  local COMMAND=$3
  echo "- Send command $COMMAND"
  ${BUILD_PATH}/bin/mysql -u$MYSQL_USER --host=$HOST --port=$PORT -e "$COMMAND"
}

function mysql_client_master() {
  mysql_client $MASTER_HOST $MASTER_PORT "$1"
}

function mysql_client_slave() {
  mysql_client $SLAVE_HOST $SLAVE_PORT "$1"
}

function sync_slave_sql() {
  local MASTER_FILE=$(mysql_client_master "SHOW MASTER STATUS\G" | grep "File:" | awk '{print $2}')
  local MASTER_POS=$(mysql_client_master "SHOW MASTER STATUS\G" | grep "Position:" | awk '{print $2}')
  while true; do
    local SLAVE_FILE=$(mysql_client_slave "SHOW REPLICA STATUS\G" | grep "Source_Log_File:" | head -1 | awk '{print $2}')
    local SLAVE_POS=$(mysql_client_slave "SHOW REPLICA STATUS\G" | grep "Read_Source_Log_Pos:" | awk '{print $2}')
    echo "MASTER_POS=$MASTER_FILE/$MASTER_POS SLAVE_POS=$SLAVE_FILE/$SLAVE_POS"
    if [[ "$MASTER_FILE" == "$SLAVE_FILE" ]] && [ "$SLAVE_POS" -ge "$MASTER_POS" ]; then break; fi
    sleep 1
  done
}

function sync_relay_log() {
  echo -n "SECS_BEHIND_SOURCE="
  while true; do
    local SECS_BEHIND_SOURCE=$(mysql_client_slave "SHOW REPLICA STATUS\G" | grep "Seconds_Behind_Source:" | awk '{print $2}')
    echo -n "$SECS_BEHIND_SOURCE "
    if [[ "$SECS_BEHIND_SOURCE" == "0" ]]; then echo; break; fi
    sleep 1
  done
}

function run_sysbench_prepare() {
  if [ $# -lt 3 ]; then echo "Usage: run_sysbench <DATABASE> <NUM_TABLES> <NUM_ROWS> <NUM_THREADS> <SOCKET> <LOG_SYSBENCH> <MORE_PARAMS>"; return 1; fi
  local DATABASE=$1
  local NUM_TABLES=$2
  local NUM_ROWS=$3
  local NUM_THREADS=$4
  local SOCKET=$5
  local LOG_SYSBENCH=$6
  local MORE_PARAMS=$7
  local SYSBENCH_DIR=${SYSBENCH_DIR:-/usr/local/share}
  # --time=$SYSBENCH_RUN_TIME
  local SYSBENCH_PARAMS="--table-size=$NUM_ROWS --tables=$NUM_TABLES --threads=$NUM_THREADS --mysql-db=$DATABASE --mysql-user=$MYSQL_USER --mysql-socket=$SOCKET --report-interval=10 --db-ps-mode=disable --percentile=99 $MORE_PARAMS"
  echo "- Starting sysbench with options $SYSBENCH_PARAMS" | tee $LOG_SYSBENCH
  time sysbench $SYSBENCH_DIR/sysbench/oltp_write_only.lua $SYSBENCH_PARAMS prepare 2>&1 | tee -a $LOG_SYSBENCH
}

function start_master() {
  local MORE_PARAMS=$1
  start_mysqld $MASTER_DD $MASTER_SOCKET $MASTER_PORT $LOG_PATH/log_master.err "--log-bin=master-bin --server_id=1 $MORE_PARAMS"
}

function stop_master() {
  shutdown_mysqld $MASTER_HOST $MASTER_PORT
  kill -9 $(pgrep -f $MASTER_DD)
}

function check_master() {
  mysql_client_master "select count(*) from $DATABASE.sbtest1"
  mysql_client_master "select @@innodb_flush_method"
}

function populate_master() {
  local MORE_PARAMS=$1
  init_datadir $MASTER_DD $LOG_PATH/init_master.err
  start_master "$MORE_PARAMS"
  mysql_client_master "CREATE USER 'repl'@'localhost' IDENTIFIED WITH mysql_native_password BY 'slavepass'"
  mysql_client_master "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'localhost'"
  mysql_client_master "CREATE USER 'repl'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY 'slavepass'"
  mysql_client_master "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'127.0.0.1'"
  mysql_client_master "FLUSH PRIVILEGES"
  mysql_client_master "RESET MASTER"
  mysql_client_master "DROP DATABASE IF EXISTS $DATABASE; CREATE DATABASE $DATABASE;"
  run_sysbench_prepare $DATABASE $NTHREADS $NROWS $NTHREADS $MASTER_SOCKET $LOG_PATH/sysbench_prepare.log

  stop_master
}

function start_slave() {
  if [ $# -lt 1 ]; then echo "Usage: start_slave <MORE_PARAMS>"; return 1; fi
  local MORE_PARAMS=$1
  init_datadir $SLAVE_DD $LOG_PATH/init_slave.err
  start_mysqld $SLAVE_DD $SLAVE_SOCKET $SLAVE_PORT $LOG_PATH/log_slave.err "--log-bin=slave-bin --server_id=2 --skip_slave_start $MORE_PARAMS"
  mysql_client_slave "CHANGE MASTER TO MASTER_HOST='localhost', MASTER_PORT=$MASTER_PORT, MASTER_USER='repl', MASTER_PASSWORD='slavepass', MASTER_LOG_FILE='master-bin.000001', MASTER_LOG_POS=0"
}

function stop_slave() {
  shutdown_mysqld $SLAVE_HOST $SLAVE_PORT
  kill -9 $(pgrep -f $SLAVE_DD)
}

function check_slave() {
  mysql_client_slave "select count(*) from $DATABASE.sbtest1"
  mysql_client_slave "select @@innodb_flush_method"
}

function bench_slave() {
  if [ $# -lt 1 ]; then echo "Usage: bench_slave <MORE_PARAMS>"; return 1; fi
  local LOG_BENCH=$LOG_PATH/bench.log
  local SLAVE_DATABASE=sb_slave
  start_slave "$1" 2>&1 | tee -a $LOG_BENCH
  mysql_client_slave "DROP DATABASE IF EXISTS $SLAVE_DATABASE; CREATE DATABASE $SLAVE_DATABASE;"
  mysql_client_slave "START SLAVE";
  run_sysbench_prepare $SLAVE_DATABASE 4 $NROWS $NTHREADS $SLAVE_SOCKET $LOG_PATH/slave_prepare.log &
  (time ( sync_slave_sql; sync_relay_log ) 2>&1) | tee -a $LOG_BENCH
  mysql_client_slave "select count(*) from $SLAVE_DATABASE.sbtest1" | tee -a $LOG_BENCH
  stop_slave 2>&1 | tee -a $LOG_BENCH
}

MYSQLD_BIN=$BUILD_PATH/bin/mysqld
if [ ! -x $MYSQLD_BIN ]; then
    MYSQLD_BIN=$BUILD_PATH/bin/mysqld-debug
    if [ ! -x $MYSQLD_BIN ]; then
        usage "ERROR: Executable $MYSQLD_BIN not found."; return 1;
    fi
    echo "WARNING: using Debug executable"
fi
if [ ! -f $CONFIG_FILE ]; then usage "ERROR: Config file $CONFIG_FILE not found."; return 1; fi

WORKSPACE=${WORKSPACE:-$PWD}
LOG_PATH=$WORKSPACE
DATABASE=sb
MYSQL_USER=root
NROWS=${NROWS:-1000000}
NTHREADS=${NTHREADS:-16}

MASTER_HOST=${MASTER_HOST:-127.0.0.1}
MASTER_PORT=${MASTER_PORT:-3333}
MASTER_SOCKET=${MASTER_SOCKET:-/tmp/mysql_master.sock}
MASTER_DD=${MASTER_DD:-${WORKSPACE}/dd_master}

SLAVE_HOST=${SLAVE_HOST:-127.0.0.1}
SLAVE_PORT=${SLAVE_PORT:-4444}
SLAVE_SOCKET=${SLAVE_SOCKET:-/tmp/mysql_slave.sock}
SLAVE_DD=${SLAVE_DD:-${WORKSPACE}/dd_slave}


echo "Using WORKSPACE=$WORKSPACE NROWS=$NROWS NTHREADS=$NTHREADS BUILD_PATH=$BUILD_PATH CONFIG_FILE=$CONFIG_FILE"
echo "Available functions:"
echo "  populate_master - init datadir and populate tables"
echo "  start_master"
echo "  stop_master"
echo "  check_master"
echo ""
echo "  start_slave --slave_parallel_workers=2"
echo "  stop_slave"
echo "  check_slave"
echo ""
echo "  bench_slave --slave_parallel_workers=2 (starts server, benchmark, stops server)"

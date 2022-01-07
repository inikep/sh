#!/bin/bash
shopt -s extglob

SERVER_BUILD=${1##*/}
CONFIG_FILE=$2
CFG_FILE=${CONFIG_FILE##*/}
FILE_SYSTEM=$3
COMMANDS=$4

BUILDDIR=${BUILDDIR:-~}/$SERVER_BUILD
BENCH_PATH=${BENCH_PATH:-~/bench}
ROOTDIR=$BENCH_PATH/$SERVER_BUILD
MYSQLDIR=$ROOTDIR/mysqld
DATADIR=${DATADIR:-${ROOTDIR}/master}
SYSBENCH_DIR=${SYSBENCH_DIR:-/usr/local}
ZENFS_DEV=${ZENFS_DEV:-nvme1n2}
DISKNAME=${DISKNAME:-nvme0n1}
WORKLOAD_SCRIPT=${WORKLOAD_SCRIPT:=all_percona.sh}

if [ "$FILE_SYSTEM" == "zenfs" ]; then
  ENGINE=rocksdb
else
  ENGINE=$FILE_SYSTEM
  [ ! -d "$DATADIR" ] && mkdir -p $DATADIR
  DATADIR_TYPE=`stat -f -c %T $DATADIR`
  if [ ! -z "$DATADIR_TYPE" ]; then FILE_SYSTEM=${DATADIR_TYPE##*/}; fi
fi

# params for benchmarking
NTABS=${NTABS:-16}
NROWS=${NROWS:-10M}; NROWS=$(numfmt --from=si $NROWS); NROWS_SI=$(numfmt --to=si $NROWS)
SECS="${SECS:-300}"
MEMORY=${MEMORY:-"16"} # "4,8,16"
CT_MEMORY=${MEMORY##*,} # get the last number
NTHREADS=${NTHREADS:-16} # "8,16,32"
RANGE_SIZE=${RANGE_SIZE:-100}
if ([ "$ENGINE" == "innodb" ]); then
  BULK_LOAD=${BULK_LOAD:-0}
else
  BULK_LOAD=${BULK_LOAD:-1}
fi
BULK_SYNC_SIZE=${BULK_SYNC_SIZE:-0}; BULK_SYNC_SIZE=$(numfmt --from=si $BULK_SYNC_SIZE)
TABLE_OPTIONS=none
USE_PK=${USE_PK:-1}
dbAndCreds=mysql,root,pw,127.0.0.1,test,$ENGINE # dbAndCreds=mysql,user,password,host,db,engine

CLIENT_OPT_NOPASS="-hlocalhost -uroot"
CLIENT_OPT="$CLIENT_OPT_NOPASS -ppw"
ZENFS_TOOL=$MYSQLDIR/bin/zenfs
MYSQLD_TOOL=$MYSQLDIR/bin/mysqld

# HOST="--mysql-socket=/tmp/mysql.sock"
# HOST="--mysql-host=127.0.0.1"
# SYSBENCH="$SYSBENCH_DIR/bin/sysbench --rand-type=uniform --db-driver=mysql --mysql-user=root --mysql-password=pw $HOST --mysql-db=test --mysql-storage-engine=$ENGINE "
# SYSBENCH+="--table-size=$NROWS --tables=$NTABS --events=0 --report-interval=10 --create_secondary=off --mysql-ignore-errors=1062,1213"

print_usage() {
  printf "\nusage: ${0##*/} [SERVER_BUILD] [CONFIG_FILE] [ENGINE] [COMMANDS]\n"
  echo "where:"
  echo "[SERVER_BUILD] - directory name of server build/binaries (please set also \$BUILDDIR)"
  echo "[CONFIG_FILE] - full path to Percona Server's configuration file"
  echo "[ENGINE] - 'innodb' or 'rocksdb' or 'zenfs'"
  echo "[COMMANDS]:"
  echo "  init    - copy binaries from \$BUILDDIR to \$ROOTDIR if required, initialize mysqld database and tables"
  echo "  prepare - populate \$NTABS tables with \$NROWS using \$NTHREADS"
  echo "  verify  - check mysqld database"
  echo "  run     - run sysbench using \$WORKLOAD_SCRIPT for \$SECS for each workload"
  echo "variables:"
  echo "  NTABS - number of tables (default = $NTABS)"
  echo "  NROWS - number of rows per table (default = $NROWS), accepts e.g. 10M, 2G"
  echo "  NTHREADS - number of sysbench threads (default = $NTHREADS), accepts e.g. \"14,24\""
  echo "  SECS - number of seconds per each sysbench job (default = $SECS)"
  echo "  MEMORY - memory in GB (default = $MEMORY), sets 'innodb_buffer_pool_size' or 'rocksdb_block_cache_size'"
  echo "  BUILDDIR - path to server build/binaries without \$SERVER_BUILD (default = $BUILDDIR)"
  echo "  BENCH_PATH - path where to copy server binaries and keep output results (default = $BENCH_PATH)"
  echo "  DATADIR - path to Percona Server's data directory (default = $DATADIR)"
  echo "  WORKLOAD_SCRIPT - use a given script from 'sysbench.lua' directory (default = $WORKLOAD_SCRIPT)"
  echo "example:"
  echo "  NTABS=8 NROWS=10M SECS=60 BENCH_PATH=/data/bench BUILDDIR=/data/mysql-server run_sysbench.sh wdc-8.0-rel-clang12 ~/cnf/vadim-rocksdb.cnf rocksdb init,prepare,verify,run"
}

if [ $# -lt 4 ]; then echo "error: too few parameters"; print_usage; exit; fi
if [ ! -f "$CONFIG_FILE" ]; then echo "error: config file $CONFIG_FILE doesn't exist"; print_usage; exit; fi
if [ "$ENGINE" != "innodb" ] && [ "$ENGINE" != "rocksdb" ]; then echo "error: unknown $ENGINE storage engine"; exit; fi

for COMMAND_NAME in $(echo "$COMMANDS" | tr "," "\n")
do
if [ "$COMMAND_NAME" != "verify" ] && [ "$COMMAND_NAME" != "init" ] && [ "$COMMAND_NAME" != "run" ] && [ "$COMMAND_NAME" != "prepare" ]; then
  echo "error: unknown $COMMAND_NAME command";
  print_usage;
  exit
fi
done # for COMMAND_NAME

if [ ! -d "$ROOTDIR" ]; then mkdir $ROOTDIR; fi
cp $CONFIG_FILE $ROOTDIR/$CFG_FILE
if [ ! -f $MYSQLD_TOOL ]; then
   echo "- Copy server from $BUILDDIR to $MYSQLDIR"
   if [ ! -f $BUILDDIR/bin/mysqld ]; then echo "error: can't find $BUILDDIR/bin/mysqld; check \$BUILDDIR parameter"; print_usage; exit; fi
   STARTPATH=$PWD
   cd $BUILDDIR
   make install DESTDIR="$MYSQLDIR" || exit
   mv $MYSQLDIR/usr/local/mysql/* $MYSQLDIR || exit
   cd $STARTPATH
fi

printf "\nSERVER_BUILD=$SERVER_BUILD CFG_FILE=$CFG_FILE ENGINE=$ENGINE FILE_SYSTEM=$FILE_SYSTEM SECS=$SECS NTABS=$NTABS NROWS=$NROWS NTHREADS=$NTHREADS MEMORY=$MEMORY DISKNAME=$DISKNAME DATADIR=$DATADIR BUILDDIR=$BUILDDIR\n"


kill_all() {
  sudo sh -c 'echo - root privilleges acquired'
  sudo killall -9 mysqld && sleep 3
  sudo killall -9 vmstat
  sudo rm -rf /tmp/mysql*
}

# startmysql $CFG_FILE $MEMORY $ADDITIONAL_OPTIONS
startmysql(){
  MEM="${2:-8}"
  ADDITIONAL_PARAMS="--defaults-file=$1"
  if [ "$ENGINE" == "rocksdb" ]; then
      ADDITIONAL_PARAMS+=" --rocksdb_block_cache_size=${MEM}G $3"
  else 
      ADDITIONAL_PARAMS+=" --innodb_buffer_pool_size=${MEM}G $3"
  fi
  if [ "$FILE_SYSTEM" == "zenfs" ]; then
     ADDITIONAL_PARAMS+=" --rocksdb_fs_uri=zenfs://dev:$ZENFS_DEV"
  fi

  echo "- Starting mysqld with $ADDITIONAL_PARAMS"
  sync
  sudo sh -c 'sysctl -q -w vm.drop_caches=3'
  sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
  ulimit -n 1000000
  cd $ROOTDIR
  $MYSQLD_TOOL $ADDITIONAL_PARAMS --user=root --port=3306 --log-error=$ROOTDIR/log.err --basedir=$MYSQLDIR --datadir=$DATADIR 2>&1 &
}

waitmysql(){
  echo "- Waiting for start of mysqld"
  sleep 5
  while true;
  do
          $MYSQLDIR/bin/mysql $1 -Bse "SELECT 1" mysql
          if [ "$?" -eq 0 ]; then break; fi
          sleep 5
          echo -n "."
  done
}

# shutdownmysql [output_file] [print_files]
shutdownmysql(){
  local RESULTS_FILE=$1
  local PRINT_FILES=$2
  print_database_size $RESULTS_FILE $PRINT_FILES
  echo "- Shutting mysqld down at $(date '+%H:%M:%S')"
  echo "- Shutting mysqld down at $(date '+%H:%M:%S')" >>$RESULTS_FILE
  $MYSQLDIR/bin/mysqladmin shutdown $CLIENT_OPT
  echo "- Shutdown finished at $(date '+%H:%M:%S')"
  echo "- Shutdown finished at $(date '+%H:%M:%S')" >>$RESULTS_FILE
  print_database_size $RESULTS_FILE $PRINT_FILES
  if [ "$ENGINE" == "rocksdb" ]; then
    cp $DATADIR/.rocksdb/LOG $RESULTS_DIR/$(generate_name _log_ $CT_MEMORY)
  fi
  cat $ROOTDIR/log.err >>$RESULTS_FILE # copy log err
  grep -i "ERROR" $ROOTDIR/log.err
  rm $ROOTDIR/log.err
}

# print_database_size [output_file] [print_files]
print_database_size(){
  local RESULTS_FILE=$1
  local PRINT_FILES=$2
  if [ "$FILE_SYSTEM" == "zenfs" ]; then
    EMPTY_ZONES=`zbd report /dev/$ZENFS_DEV | grep em | wc -l`
    DATA_SIZE=`$ZENFS_TOOL list --zbd=$ZENFS_DEV --path=./.rocksdb | awk '{sum+=$1;} END {printf "%d\n", sum/1024/1024;}'`
    FILE_COUNT=`$ZENFS_TOOL list --zbd=$ZENFS_DEV --path=./.rocksdb | wc -l`
    if [ "$PRINT_FILES" == "1" ]; then $ZENFS_TOOL list --zbd=$ZENFS_DEV --path=./.rocksdb >>$RESULTS_FILE; fi
    echo "- Number of empty zones is $EMPTY_ZONES"
    echo "- Number of empty zones is $EMPTY_ZONES" >>$RESULTS_FILE
    $ZENFS_TOOL df --zbd=$ZENFS_DEV
    $ZENFS_TOOL df --zbd=$ZENFS_DEV >>$RESULTS_FILE
  else
    DATA_SIZE=`du -s $DATADIR | awk '{sum+=$1;} END {printf "%d\n", sum/1024;}'`
    if [ "$PRINT_FILES" == "1" ]; then ls -alR $DATADIR >>$RESULTS_FILE; fi
    FILE_COUNT=`ls -aR $DATADIR | wc -l`
  fi
  echo "- Size of RocksDB database is $DATA_SIZE MB in $FILE_COUNT files"
  echo "- Size of RocksDB database is $DATA_SIZE MB in $FILE_COUNT files" >>$RESULTS_FILE
}

# generate_name [prefix] [memory]
generate_name(){
  echo "${1}${FILE_SYSTEM}_${NTABS}x${NROWS_SI}_${2}GB_${SECS}s_`date +%F_%H-%M`"
}

init_db(){
  local RES_INIT=$(generate_name _init_ $CT_MEMORY)
  echo >>$RESULTS_DIR/$RES_INIT SERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE FILE_SYSTEM=$FILE_SYSTEM CFG_FILE=$CFG_FILE SECS=$SECS NTABS=$NTABS NROWS=$NROWS MEM=$MEM NTHREADS=$NTHREADS DISKNAME=$DISKNAME DATADIR=$DATADIR

  echo "- Initialize mysqld at $(date '+%H:%M:%S')"
  rm -rf $DATADIR
  if [ "$FILE_SYSTEM" == "zenfs" ]; then
    export ZENFS_DEV
    sudo -E bash -c 'echo mq-deadline > /sys/block/$ZENFS_DEV/queue/scheduler'
    sudo chmod o+rw /dev/$ZENFS_DEV
    sudo zbd reset /dev/$ZENFS_DEV
    $ZENFS_TOOL mkfs --zbd=$ZENFS_DEV --aux_path=$DATADIR --finish_threshold=0 --force || exit
  else
    mkdir -p $DATADIR
  fi
#  cp ${MYSQLD_TOOL}-debug $MYSQLD_TOOL
  $MYSQLD_TOOL --initialize-insecure --basedir=$MYSQLDIR --datadir=$DATADIR --log-error-verbosity=2 --log-error=$ROOTDIR/log.err

  startmysql $CFG_FILE $CT_MEMORY
  waitmysql "$CLIENT_OPT_NOPASS"
  echo "- Create 'test' database at $(date '+%H:%M:%S')"
  $MYSQLDIR/bin/mysql $CLIENT_OPT_NOPASS -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'pw'"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "CREATE DATABASE test"
  shutdownmysql $RESULTS_DIR/$RES_INIT
}

prepare_db(){
  local RES_PREPARE=$(generate_name _prepare_ $CT_MEMORY)

  ADDITIONAL_PARAMS="--disable-log-bin"
  if [ "$ENGINE" == "rocksdb" ] && [ "$BULK_LOAD" == "1" ]; then
    ADDITIONAL_PARAMS+=" --rocksdb_bulk_load=1"
    if [ "$USE_PK" == "0" ]; then ADDITIONAL_PARAMS+=" --rocksdb_bulk_load_allow_sk=1"; fi
  fi
  startmysql $CFG_FILE $CT_MEMORY "$ADDITIONAL_PARAMS"
  waitmysql "$CLIENT_OPT"

  free -m  >>$RESULTS_DIR/$RES_PREPARE
  THREADS=${NTHREADS##*,} # get the last number
  echo "- Populate database with sysbench with ${NTABS}x$NROWS rows and $THREADS threads at $(date '+%H:%M:%S')"
  echo "- Populate database with sysbench with ${NTABS}x$NROWS rows and $THREADS threads at $(date '+%H:%M:%S')" >>$RESULTS_DIR/$RES_PREPARE
#  (time $SYSBENCH --threads=$THREADS /usr/local/share/sysbench/oltp_read_write.lua prepare --rand-type=uniform --range-size=$RANGE_SIZE >>$RESULTS_DIR/$RES_PREPARE) 2>>$RESULTS_DIR/$RES_PREPARE
  cd $RESULTS_DIR
  time { (time bash run.sh $NTABS $NROWS 0 $dbAndCreds 1 0 setup 100 $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $DATADIR $DISKNAME $USE_PK 0 $BULK_SYNC_SIZE $THREADS) 2>>$RESULTS_DIR/$RES_PREPARE; }
  STATUS=$?
  cat sb.prepare.o.setup.range100.pk* >>$RESULTS_DIR/$RES_PREPARE
  free -m >>$RESULTS_DIR/$RES_PREPARE

  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; show table status" >>$RESULTS_DIR/$RES_PREPARE

  time { (time shutdownmysql $RESULTS_DIR/$RES_PREPARE 1) 2>>$RESULTS_DIR/$RES_PREPARE; }
  free -m  >>$RESULTS_DIR/$RES_PREPARE
  if [[ $STATUS != 0 ]]; then echo run_sysbench failed; exit -1; fi
}

verify_db(){
  local RES_VERIFY=$(generate_name _verify_ $CT_MEMORY)
  startmysql $CFG_FILE $CT_MEMORY
  waitmysql "$CLIENT_OPT"
  $MYSQLDIR/bin/mysqlcheck $CLIENT_OPT --analyze --databases test >$RESULTS_DIR/$RES_VERIFY
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; SHOW CREATE TABLE sbtest1; SHOW ENGINE $ENGINE STATUS\G; show table status" >>$RESULTS_DIR/$RES_VERIFY
  shutdownmysql $RESULTS_DIR/$RES_VERIFY
}

# run_sysbench [output_file]
run_sysbench(){
  cd $RESULTS_DIR
  local RESULTS_FILE=$1

  READSECS=$SECS
  WRITESECS=$SECS
  INSERTSECS=$SECS
  CLEANUP=0
  THREADS=$(echo "$NTHREADS" | tr "," "\n")

  for SCRIPT in $(echo "$WORKLOAD_SCRIPT" | tr "," "\n")
  do
    echo - Run $SCRIPT for THREADS=$THREADS
    bash $SCRIPT $NTABS $NROWS $READSECS $WRITESECS $INSERTSECS $dbAndCreds 0 $CLEANUP $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $DATADIR $DISKNAME $USE_PK $BULK_SYNC_SIZE $THREADS
  done

  echo >>$RESULTS_FILE SERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE FILE_SYSTEM=$FILE_SYSTEM CFG_FILE=$CFG_FILE SECS=$SECS NTABS=$NTABS NROWS=$NROWS MEM=$MEM NTHREADS=$NTHREADS DISKNAME=$DISKNAME DATADIR=$DATADIR
  printf "\n- Results in queries per second (QPS)\n" >>$RESULTS_FILE
  cat sb.r.qps.!(*.pre.*) | sort -k3 >>$RESULTS_FILE
  printf "\n- Results in transactions per second (TPS)\n" >>$RESULTS_FILE
  cat sb.r.trx.!(*.pre.*) | sort -k3  >>$RESULTS_FILE
  printf "\n- Latency max (ms)\n" >>$RESULTS_FILE
  cat sb.r.rtmax.!(*.pre.*) | sort -k3  >>$RESULTS_FILE
  printf "\n- Latency avg (ms)\n" >>$RESULTS_FILE
  cat sb.r.rtavg.!(*.pre.*) | sort -k3  >>$RESULTS_FILE
  printf "\n- Latency 95th percentile (ms)\n" >>$RESULTS_FILE
  cat sb.r.rt95.!(*.pre.*) | sort -k3  >>$RESULTS_FILE
  printf "\n- $DISKNAME disk usage\n" >>$RESULTS_FILE
  cat sb.df.!(*.pre.*) | sort -k3  >>$RESULTS_FILE
  cat $RESULTS_FILE
}


# preparations before main loop
kill_all
# trap "trap - SIGTERM && kill -- -$$" SIGINT SIGTERM EXIT
rm -f $ROOTDIR/log.err
RESULTS_DIR=${ROOTDIR}/${CFG_FILE%.*}$(generate_name / $CT_MEMORY)
mkdir -p $RESULTS_DIR
cp $CONFIG_FILE $RESULTS_DIR/$CFG_FILE
echo "- Script started at $(date '+%H:%M:%S'). Results are written to $RESULTS_DIR"

# main loop
for COMMAND_NAME in $(echo "$COMMANDS" | tr "," "\n")
do

echo "- Execute COMMAND_NAME=$COMMAND_NAME at $(date '+%H:%M:%S')"

if [ "${COMMAND_NAME}" == "init" ]; then init_db; continue; fi
if [ "${COMMAND_NAME}" == "prepare" ]; then prepare_db; continue; fi
if [ "${COMMAND_NAME}" == "verify" ]; then verify_db; continue; fi

for MEM in $(echo "$MEMORY" | tr "," "\n")
do
echo --MEM=$MEM
free -m

startmysql $CFG_FILE $MEM
waitmysql "$CLIENT_OPT"
RES_RUN=$(generate_name _run_ $MEM)

if [ 1 == 0 ]; then
  for THREADS in $(echo "$NTHREADS" | tr "," "\n")
  do
  echo --THREADS=$THREADS
  $SYSBENCH --threads=$THREADS --time=$SECS --range-size=$RANGE_SIZE /usr/local/share/sysbench/oltp_read_write.lua run
  $SYSBENCH --threads=$THREADS --time=$SECS --range-size=$RANGE_SIZE /usr/local/share/sysbench/oltp_write_only.lua run
  $SYSBENCH --threads=$THREADS --time=$SECS --range-size=$RANGE_SIZE /usr/local/share/sysbench/oltp_insert.lua run
  done # for THREADS
else
  time { (time run_sysbench $RES_RUN) 2>>$RESULTS_DIR/$RES_RUN; }
fi

shutdownmysql $RESULTS_DIR/$RES_RUN
verify_db

sleep 30

done # for MEM

done # for COMMAND_NAME

echo "- Script finished at $(date '+%H:%M:%S'). Results are written to $RESULTS_DIR"

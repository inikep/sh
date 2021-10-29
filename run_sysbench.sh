#!/bin/bash 

SERVER_BUILD=$1
BENCH_PATH=${BENCH_PATH:-~/bench}
BUILDDIR=${BUILDDIR:-~}/$SERVER_BUILD
ROOTDIR=$BENCH_PATH/$SERVER_BUILD
CONFIG_FILE=$2
CFG_FILE=${CONFIG_FILE##*/}
ENGINE=$3
COMMANDS=$4

if [ "$ENGINE" == "zenfs" ]; then SUBENGINE=rocksdb; else SUBENGINE=$ENGINE; fi


for COMMAND_NAME in $(echo "$COMMANDS" | tr "," "\n")
do
if ([ "$COMMAND_NAME" != "verify" ] && [ "$COMMAND_NAME" != "init" ]) && [ "$COMMAND_NAME" != "run" ] || ([ "$SUBENGINE" != "innodb" ] && [ "$SUBENGINE" != "rocksdb" ]) || [ $# -lt 3 ]; then
  echo "usage: $0 [server_build] [my.cnf] [innodb/rocksdb/zenfs] [init/run/verify]"
  echo "  init   - copy binaries from $BUILDDIR to $ROOTDIR if required, initialize mysqld database"
  echo "  verify - check mysqld database"
  echo "  run  - run sysbench"
  echo "  NTABS - number of tables"
  echo "  NROWS - number of rows per table"
  echo "  NTHREADS - number of sysbench threads"
  echo "  SECS - number of seconds per each sysbench job"
  echo "example: time NTABS=8 SECS=60 run_sysbench.sh init,verify,run wdc-8.0-rel-clang12-rocks-toku-add rocksdb ~/sh/cnf/vadim-rocksdb.cnf"
  exit
fi     
done # for COMMAND_NAME

if [ ! -f "$CONFIG_FILE" ]; then
  echo "error: config file $CONFIG_FILE doesn't exist"
  exit
fi

kill_all() {
  sudo sh -c 'echo - root privilleges acquired'
  sudo killall -9 mysqld && sleep 3
  sudo killall -9 vmstat
  sudo rm -rf /tmp/mysql*
}

kill_all

# params for benchmarking
NTABS=${NTABS:-16}
ORIG_NROWS=$NROWS
if [ ! -z "$NROWS" ]; then NROWS=$(numfmt --from=si $NROWS); fi
NROWS=${NROWS:-10000000}
ORIG_NROWS=${ORIG_NROWS:=$NROWS}
SECS="${SECS:-300}"
MEMORY=${MEMORY:-"16"} # "4,8,16"
CT_MEMORY=${MEMORY##*,} # get the last number
NTHREADS=${NTHREADS:-16} # "8,16,32"
RANGE_SIZE=${RANGE_SIZE:-100}
TABLE_OPTIONS=none
USE_PK=${USE_PK:-0}
ZENFS_DEV=${ZENFS_DEV:-nvme1n2}
DISKNAME=$ZENFS_DEV
dbAndCreds=mysql,root,pw,127.0.0.1,test,$SUBENGINE # dbAndCreds=mysql,user,password,host,db,engine

SYSBENCH_DIR=${SYSBENCH_DIR:-/usr/local}
SYSBENCH="$SYSBENCH_DIR/bin/sysbench --rand-type=uniform --db-driver=mysql --mysql-user=root --mysql-password=pw --mysql-host=127.0.0.1 --mysql-db=test --mysql-storage-engine=$SUBENGINE "
SYSBENCH+="--table-size=$NROWS --tables=$NTABS --events=0 --report-interval=10 --create_secondary=off --mysql-ignore-errors=1062,1213"

printf "\nSERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE CFG_FILE=$CFG_FILE SECS=$SECS NTABS=$NTABS NROWS=$NROWS NTHREADS=$NTHREADS MEMORY=$MEMORY\n"

#HOST="--mysql-socket=/tmp/mysql.sock"
HOST="--mysql-host=127.0.0.1"
CLIENT_OPT_NOPASS="-hlocalhost -uroot"
CLIENT_OPT="$CLIENT_OPT_NOPASS -ppw"
MYSQLDIR=$ROOTDIR/mysqld
DATADIR=${DATADIR:-${ROOTDIR}/master}
ZENFS_TOOL=$MYSQLDIR/bin/zenfs


if [ ! -d "$ROOTDIR" ]; then mkdir $ROOTDIR; fi
cp $CONFIG_FILE $ROOTDIR/$CFG_FILE
if [ ! -d "$MYSQLDIR" ]; then
   STARTPATH=$PWD
   cd $BUILDDIR
   make install DESTDIR="$MYSQLDIR"          
   mv $MYSQLDIR/usr/local/mysql/* $MYSQLDIR || exit
   cd $STARTPATH
fi    

# trap "trap - SIGTERM && kill -- -$$" SIGINT SIGTERM EXIT

# startmysql $CFG_FILE $MEMORY $ADDITIONAL_OPTIONS
startmysql(){
  MEM="${2:-8}"
  ADDITIONAL_PARAMS=""
  if [ "$SUBENGINE" == "rocksdb" ]; then
      ADDITIONAL_PARAMS="--rocksdb_block_cache_size=${MEM}G --rocksdb_merge_buf_size=1G $3"
  else 
      ADDITIONAL_PARAMS="--innodb_buffer_pool_size=${MEM}G"
  fi
  if [ "$ENGINE" == "zenfs" ]; then
     ADDITIONAL_PARAMS+=" --rocksdb_fs_uri=zenfs://dev:$ZENFS_DEV"
  fi

  if [ "$1" == "no-defaults-file" ]; then
      ADDITIONAL_PARAMS="--no-defaults-file"
  else
      ADDITIONAL_PARAMS="--defaults-file=$1 $ADDITIONAL_PARAMS"  
  fi
  echo "- Starting mysqld with $ADDITIONAL_PARAMS"
  sync
  sudo sh -c 'sysctl -q -w vm.drop_caches=3'
  sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
  ulimit -n 1000000
  cd $ROOTDIR
  $MYSQLDIR/bin/mysqld $ADDITIONAL_PARAMS --user=root --port=3306 --log-error=$ROOTDIR/log.err --basedir=$MYSQLDIR --datadir=$DATADIR 2>&1 &
}

shutdownmysql(){
  echo "- Shutting mysqld down"
  $MYSQLDIR/bin/mysqladmin shutdown $CLIENT_OPT
}

print_database_size(){
  if [ "$ENGINE" == "zenfs" ]; then
    EMPTY_ZONES=`zbd report /dev/$ZENFS_DEV | grep em | wc -l`
    DATA_SIZE=`$ZENFS_TOOL list --zbd=$ZENFS_DEV --path=./.rocksdb | awk '{sum+=$1;} END {printf "%d\n", sum/1024/1024;}'`
    $ZENFS_TOOL list --zbd=$ZENFS_DEV --path=./.rocksdb
    echo "Number of empty zones is $EMPTY_ZONES"
  else
    DATA_SIZE=`du -s $DATADIR | awk '{sum+=$1;} END {printf "%d\n", sum/1024;}'`
    ls -l $DATADIR/.rocksdb
  fi
  echo "Size of RocksDB database is $DATA_SIZE MB"
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

# generate_name [prefix] [memory]
generate_name(){
  echo "${1}${ENGINE}_${NTABS}x${ORIG_NROWS}_${2}GB_${SECS}s_`date +%F_%H-%M`"
}

copy_log_err() {
  cat $ROOTDIR/log.err >>$1
  grep -i "ERROR" $ROOTDIR/log.err
  rm $ROOTDIR/log.err
}

verify_db(){
  RES_VERIFY=$(generate_name _verify_ $CT_MEMORY)
  startmysql $CFG_FILE $CT_MEMORY
  waitmysql "$CLIENT_OPT"
  $MYSQLDIR/bin/mysqlcheck $CLIENT_OPT --analyze --databases test
  $MYSQLDIR/bin/mysqlcheck $CLIENT_OPT --analyze --databases test >$RESULTS_DIR/$RES_VERIFY
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; SHOW CREATE TABLE sbtest1; SHOW ENGINE ROCKSDB STATUS\G; show table status" >>$RESULTS_DIR/$RES_VERIFY
  shutdownmysql
  copy_log_err $RESULTS_DIR/$RES_VERIFY
}

run_sysbench(){
  cd $RESULTS_DIR
  RESULTS_FILE=$1

  READSECS=$SECS
  WRITESECS=$SECS
  INSERTSECS=$SECS
  CLEANUP=0
  THREADS=$(echo "$NTHREADS" | tr "," "\n")
  echo --THREADS=$THREADS

  bash all_small.sh $NTABS $NROWS $READSECS $WRITESECS $INSERTSECS $dbAndCreds 0 $CLEANUP $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $PWD $DISKNAME $USE_PK $THREADS
  echo >>$RESULTS_FILE SERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE CFG_FILE=$CFG_FILE SECS=$SECS NTABS=$NTABS NROWS=$NROWS MEM=$MEM NTHREADS=$NTHREADS
  cat sb.r.qps.* >>$RESULTS_FILE
  cat sb.r.qps.*
  copy_log_err $RESULTS_DIR/$RESULTS_FILE
}

CREATE_RESULTS_DIR=1

for COMMAND_NAME in $(echo "$COMMANDS" | tr "," "\n")
do

if [ "${CREATE_RESULTS_DIR}" == "1" ]; then
  RESULTS_DIR=${ROOTDIR}/${CFG_FILE%.*}$(generate_name / $CT_MEMORY)
  mkdir -p $RESULTS_DIR
  CREATE_RESULTS_DIR=0
fi

echo "- Execute COMMAND_NAME=$COMMAND_NAME"

if [ "${COMMAND_NAME}" == "verify" ]; then
  verify_db
  continue
fi

if [ "${COMMAND_NAME}" == "init" ]; then
  RES_INIT=$(generate_name _init_ $CT_MEMORY)
  echo >>$RESULTS_DIR/$RES_INIT SERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE CFG_FILE=$CFG_FILE SECS=$SECS NTABS=$NTABS NROWS=$NROWS MEM=$MEM NTHREADS=$NTHREADS

  echo "- Initialize mysqld"
  rm -rf $DATADIR
  if [ "$ENGINE" == "zenfs" ]; then
    export ZENFS_DEV
    sudo -E bash -c 'echo mq-deadline > /sys/block/$ZENFS_DEV/queue/scheduler'
    sudo chmod o+rw /dev/$ZENFS_DEV
    $ZENFS_TOOL mkfs --zbd=$ZENFS_DEV --aux_path=$DATADIR --finish_threshold=0 --force || exit
  else
    mkdir $DATADIR
  fi
#  cp $MYSQLDIR/bin/mysqld-debug $MYSQLDIR/bin/mysqld
  $MYSQLDIR/bin/mysqld --initialize-insecure --basedir=$MYSQLDIR --datadir=$DATADIR --log-error-verbosity=2

  if [ "$USE_PK" == "0" ]; then
    startmysql $CFG_FILE $CT_MEMORY "--disable-log-bin --rocksdb_bulk_load_allow_sk=1 --rocksdb_bulk_load=1"
  else
    startmysql $CFG_FILE $CT_MEMORY "--disable-log-bin --rocksdb_bulk_load=1"
  fi
  waitmysql "$CLIENT_OPT_NOPASS"
  echo "- Create 'test' database" 
  $MYSQLDIR/bin/mysql $CLIENT_OPT_NOPASS -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'pw'"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "CREATE DATABASE test"

  free -m  >>$RESULTS_DIR/$RES_INIT
  THREADS=${NTHREADS##*,} # get the last number
  echo "- Populate database with sysbench with ${NTABS}x$NROWS rows and $THREADS threads"
  echo "- Populate database with sysbench with ${NTABS}x$NROWS rows and $THREADS threads" >>$RESULTS_DIR/$RES_INIT
#  (time $SYSBENCH --threads=$THREADS /usr/local/share/sysbench/oltp_read_write.lua prepare --rand-type=uniform --range-size=$RANGE_SIZE >>$RESULTS_DIR/$RES_INIT) 2>>$RESULTS_DIR/$RES_INIT
  cd $RESULTS_DIR
  (time bash all_small_setup_only.sh $NTABS $NROWS 0 0 0 $dbAndCreds 1 0 $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $PWD $DISKNAME $USE_PK $THREADS) 2>>$RESULTS_DIR/$RES_INIT
  STATUS=$?
  cat sb.prepare.o.point-query.warm.range100.pk* >>$RESULTS_DIR/$RES_INIT
  free -m >>$RESULTS_DIR/$RES_INIT

  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "SET global rocksdb_bulk_load=0;"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; show table status" >>$RESULTS_DIR/$RES_INIT

  print_database_size >>$RESULTS_DIR/$RES_INIT
  echo "- Shutdown mysqld" >>$RESULTS_DIR/$RES_INIT
  (time shutdownmysql) 2>>$RESULTS_DIR/$RES_INIT
  free -m  >>$RESULTS_DIR/$RES_INIT
  print_database_size >>$RESULTS_DIR/$RES_INIT
#  kill_all
  copy_log_err $RESULTS_DIR/$RES_INIT
  if [[ $STATUS != 0 ]]; then echo run_sysbench failed; exit -1; fi
  continue
fi


for MEM in $(echo "$MEMORY" | tr "," "\n")
do
echo --MEM=$MEM
free -m

startmysql $CFG_FILE $MEM
waitmysql "$CLIENT_OPT"

if [ 1 == 0 ]; then
  for THREADS in $(echo "$NTHREADS" | tr "," "\n")
  do
  echo --THREADS=$THREADS
  $SYSBENCH --threads=$THREADS --time=$SECS --range-size=$RANGE_SIZE /usr/local/share/sysbench/oltp_read_write.lua run
  $SYSBENCH --threads=$THREADS --time=$SECS --range-size=$RANGE_SIZE /usr/local/share/sysbench/oltp_write_only.lua run
  $SYSBENCH --threads=$THREADS --time=$SECS --range-size=$RANGE_SIZE /usr/local/share/sysbench/oltp_insert.lua run
  done # for THREADS
else
  RES_RUN=$(generate_name _run_ $MEM)
  (time run_sysbench $RES_RUN) 2>>$RESULTS_DIR/$RES_RUN
  verify_db
  CREATE_RESULTS_DIR=1
fi

shutdownmysql
sleep 30

done # for MEM

done # for COMMAND_NAME

echo "- Script finished"

#!/bin/bash
shopt -s extglob

SERVER_BUILD=$1
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

if [ "$FILE_SYSTEM" == "zenfs" ]; then
  ENGINE=rocksdb
else
  ENGINE=$FILE_SYSTEM
  [ ! -d "$DATADIR" ] && mkdir -p $DATADIR
  DATADIR_TYPE=`stat -f -c %T $DATADIR`
  if [ ! -z "$DATADIR_TYPE" ]; then FILE_SYSTEM=${DATADIR_TYPE##*/}; fi
fi

for COMMAND_NAME in $(echo "$COMMANDS" | tr "," "\n")
do
if ([ "$COMMAND_NAME" != "verify" ] && [ "$COMMAND_NAME" != "init" ]) && [ "$COMMAND_NAME" != "run" ] ||
    ([ "$ENGINE" != "innodb" ] && [ "$ENGINE" != "rocksdb" ]) ||
    [ $# -lt 3 ]; then
  echo "usage: $0 [server_build] [my.cnf] [innodb/rocksdb/zenfs] [init/run/verify]"
  echo "  init   - copy binaries from \$BUILDDIR to \$ROOTDIR if required, initialize mysqld database"
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
BULK_LOAD=${BULK_LOAD:-1}
BULK_SYNC_SIZE=${BULK_SYNC_SIZE:-0}
TABLE_OPTIONS=none
USE_PK=${USE_PK:-0}
DISKNAME=$ZENFS_DEV
dbAndCreds=mysql,root,pw,127.0.0.1,test,$ENGINE # dbAndCreds=mysql,user,password,host,db,engine

# SYSBENCH="$SYSBENCH_DIR/bin/sysbench --rand-type=uniform --db-driver=mysql --mysql-user=root --mysql-password=pw --mysql-host=127.0.0.1 --mysql-db=test --mysql-storage-engine=$ENGINE "
# SYSBENCH+="--table-size=$NROWS --tables=$NTABS --events=0 --report-interval=10 --create_secondary=off --mysql-ignore-errors=1062,1213"

#HOST="--mysql-socket=/tmp/mysql.sock"
HOST="--mysql-host=127.0.0.1"
CLIENT_OPT_NOPASS="-hlocalhost -uroot"
CLIENT_OPT="$CLIENT_OPT_NOPASS -ppw"
ZENFS_TOOL=$MYSQLDIR/bin/zenfs

printf "\nSERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE FILE_SYSTEM=$FILE_SYSTEM CFG_FILE=$CFG_FILE SECS=$SECS NTABS=$NTABS NROWS=$NROWS NTHREADS=$NTHREADS MEMORY=$MEMORY DATADIR=$DATADIR\n"

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
  if [ "$ENGINE" == "rocksdb" ]; then
      ADDITIONAL_PARAMS="--rocksdb_block_cache_size=${MEM}G --rocksdb_merge_buf_size=1G $3"
  else 
      ADDITIONAL_PARAMS="--innodb_buffer_pool_size=${MEM}G"
  fi
  if [ "$FILE_SYSTEM" == "zenfs" ]; then
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

# startmysql [output_file] [print_files]
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
  else
    DATA_SIZE=`du -s $DATADIR | awk '{sum+=$1;} END {printf "%d\n", sum/1024;}'`
    if [ "$PRINT_FILES" == "1" ]; then ls -l $DATADIR/.rocksdb >>$RESULTS_FILE; fi
    FILE_COUNT=`ls $DATADIR/.rocksdb | wc -l`
  fi
  echo "- Size of RocksDB database is $DATA_SIZE MB in $FILE_COUNT files"
  echo "- Size of RocksDB database is $DATA_SIZE MB in $FILE_COUNT files" >>$RESULTS_FILE
}

# generate_name [prefix] [memory]
generate_name(){
  echo "${1}${FILE_SYSTEM}_${NTABS}x${ORIG_NROWS}_${2}GB_${SECS}s_`date +%F_%H-%M`"
}

verify_db(){
  RES_VERIFY=$(generate_name _verify_ $CT_MEMORY)
  startmysql $CFG_FILE $CT_MEMORY
  waitmysql "$CLIENT_OPT"
  $MYSQLDIR/bin/mysqlcheck $CLIENT_OPT --analyze --databases test >$RESULTS_DIR/$RES_VERIFY
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; SHOW CREATE TABLE sbtest1; SHOW ENGINE ROCKSDB STATUS\G; show table status" >>$RESULTS_DIR/$RES_VERIFY
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
  echo --THREADS=$THREADS

  bash all_wdc.sh $NTABS $NROWS $READSECS $WRITESECS $INSERTSECS $dbAndCreds 0 $CLEANUP $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $PWD $DISKNAME $USE_PK $BULK_SYNC_SIZE $THREADS

  echo >>$RESULTS_FILE SERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE FILE_SYSTEM=$FILE_SYSTEM CFG_FILE=$CFG_FILE SECS=$SECS NTABS=$NTABS NROWS=$NROWS MEM=$MEM NTHREADS=$NTHREADS DATADIR=$DATADIR
  printf "\n- Results in queries per second (QPS)\n" >>$RESULTS_FILE
  cat sb.r.qps.!(*.pre.*) | sort -k2 >>$RESULTS_FILE
  printf "\n- Results in transactions per second (TPS)\n" >>$RESULTS_FILE
  cat sb.r.trx.!(*.pre.*) | sort -k2  >>$RESULTS_FILE
  printf "\n- Latency max (ms)\n" >>$RESULTS_FILE
  cat sb.r.rtmax.!(*.pre.*) | sort -k2  >>$RESULTS_FILE
  printf "\n- Latency avg (ms)\n" >>$RESULTS_FILE
  cat sb.r.rtavg.!(*.pre.*) | sort -k2  >>$RESULTS_FILE
  printf "\n- Latency 95th percentile (ms)\n" >>$RESULTS_FILE
  cat sb.r.rt95.!(*.pre.*) | sort -k2  >>$RESULTS_FILE
  cat $RESULTS_FILE
}


# preparations before main loop
rm -f $ROOTDIR/log.err
RESULTS_DIR=${ROOTDIR}/${CFG_FILE%.*}$(generate_name / $CT_MEMORY)
mkdir -p $RESULTS_DIR
cp $CONFIG_FILE $RESULTS_DIR/$CFG_FILE


# main loop
for COMMAND_NAME in $(echo "$COMMANDS" | tr "," "\n")
do

echo "- Execute COMMAND_NAME=$COMMAND_NAME at $(date '+%H:%M:%S')"

if [ "${COMMAND_NAME}" == "verify" ]; then
  verify_db
  continue
fi

if [ "${COMMAND_NAME}" == "init" ]; then
  RES_INIT=$(generate_name _init_ $CT_MEMORY)
  echo >>$RESULTS_DIR/$RES_INIT SERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE FILE_SYSTEM=$FILE_SYSTEM CFG_FILE=$CFG_FILE SECS=$SECS NTABS=$NTABS NROWS=$NROWS MEM=$MEM NTHREADS=$NTHREADS DATADIR=$DATADIR

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
#  cp $MYSQLDIR/bin/mysqld-debug $MYSQLDIR/bin/mysqld
  $MYSQLDIR/bin/mysqld --initialize-insecure --basedir=$MYSQLDIR --datadir=$DATADIR --log-error-verbosity=2 --log-error=$ROOTDIR/log.err

  ADDITIONAL_PARAMS="--disable-log-bin"
  if [ "$BULK_LOAD" == "1" ]; then
    ADDITIONAL_PARAMS+=" --rocksdb_bulk_load=1"
    if [ "$USE_PK" == "0" ]; then ADDITIONAL_PARAMS+=" --rocksdb_bulk_load_allow_sk=1"; fi
  fi
  startmysql $CFG_FILE $CT_MEMORY "$ADDITIONAL_PARAMS"

  waitmysql "$CLIENT_OPT_NOPASS"
  echo "- Create 'test' database at $(date '+%H:%M:%S')"
  $MYSQLDIR/bin/mysql $CLIENT_OPT_NOPASS -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'pw'"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "CREATE DATABASE test"

  free -m  >>$RESULTS_DIR/$RES_INIT
  THREADS=${NTHREADS##*,} # get the last number
  echo "- Populate database with sysbench with ${NTABS}x$NROWS rows and $THREADS threads at $(date '+%H:%M:%S')"
  echo "- Populate database with sysbench with ${NTABS}x$NROWS rows and $THREADS threads at $(date '+%H:%M:%S')" >>$RESULTS_DIR/$RES_INIT
#  (time $SYSBENCH --threads=$THREADS /usr/local/share/sysbench/oltp_read_write.lua prepare --rand-type=uniform --range-size=$RANGE_SIZE >>$RESULTS_DIR/$RES_INIT) 2>>$RESULTS_DIR/$RES_INIT
  cd $RESULTS_DIR
  time { (time bash all_small_setup_only.sh $NTABS $NROWS 0 0 0 $dbAndCreds 1 0 $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $PWD $DISKNAME $USE_PK $BULK_SYNC_SIZE $THREADS) 2>>$RESULTS_DIR/$RES_INIT; }
  STATUS=$?
  cat sb.prepare.o.point-query.warm.range100.pk* >>$RESULTS_DIR/$RES_INIT
  free -m >>$RESULTS_DIR/$RES_INIT

  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "SET global rocksdb_bulk_load=0;"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; show table status" >>$RESULTS_DIR/$RES_INIT

  time { (time shutdownmysql $RESULTS_DIR/$RES_INIT 1) 2>>$RESULTS_DIR/$RES_INIT; }
  free -m  >>$RESULTS_DIR/$RES_INIT
  if [[ $STATUS != 0 ]]; then echo run_sysbench failed; exit -1; fi
  continue
fi


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

echo "- Script finished at $(date '+%H:%M:%S')"

#!/bin/bash 

SERVER_BUILD=$1
BENCH_PATH=${BENCH_PATH:-/data/bench}
BUILDDIR=${BUILDDIR:-/data/mysql-server}/$SERVER_BUILD
ROOTDIR=$BENCH_PATH/$SERVER_BUILD
CONFIG_FILE=$2
CFG_FILE=${CONFIG_FILE##*/}
ENGINE=$3
COMMAND_TYPE=$4

if [ "$ENGINE" == "zenfs" ]; then SUBENGINE=rocksdb; else SUBENGINE=$ENGINE; fi

if ([ "$COMMAND_TYPE" != "verify" ] && [ "$COMMAND_TYPE" != "init" ]) && [ "$COMMAND_TYPE" != "start" ] || ([ "$SUBENGINE" != "innodb" ] && [ "$SUBENGINE" != "rocksdb" ]) || [ $# -lt 3 ]; then
  echo "usage: $0 [server_build] [my.cnf] [innodb/rocksdb/zenfs] [init/start/verify]"
  echo "  init   - copy binaries from $BUILDDIR to $ROOTDIR if required, initialize mysqld database"
  echo "  verify - check mysqld database"
  echo "  start  - start sysbench"
  echo "  NTABS - number of tables"
  echo "  NROWS - number of rows per table"
  echo "  NTHREADS - number of sysbench threads"
  echo "  SECS - number of seconds per each sysbench job"
  echo "example: time NTABS=8 SECS=60 run_sysbench.sh verify wdc-8.0-rel-clang12-rocks-toku-add rocksdb /data/sh/cnf/vadim-rocksdb.cnf"
  exit
fi     

if [ ! -f "$CONFIG_FILE" ]; then
  echo "error: config file $CONFIG_FILE doesn't exist"
  exit
fi

sudo sh -c 'echo - root privilleges acquired'
sudo killall -9 mysqld && sleep 3
sudo killall -9 vmstat
sudo rm -rf /tmp/mysqlx.sock.lock

ZENFS_DEV=${ZENFS_DEV:-nvme1n2}
if [ "$ENGINE" == "zenfs" ] && [ "$COMMAND_TYPE" == "init" ]; then
  ZENFS_PATH=$BENCH_PATH/zenfs_sysbench_$ZENFS_DEV
  rm -rf $ZENFS_PATH
  zenfs mkfs --zbd=$ZENFS_DEV --aux_path=$ZENFS_PATH --finish_threshold=0 --force || exit
fi


# params for creating tables
NTABS=${NTABS:-16}
NROWS=${NROWS:-2000000}
CT_MEMORY=${CT_MEMORY:-8}

# params for benchmarking
SECS="${SECS:-300}"
MEMORY=${MEMORY:-"16"} # "4 8 16"
NTHREADS=${NTHREADS:-16} # "8 16 32"
RANGE_SIZE=${RANGE_SIZE:-10000}
DISKNAME=$ZENFS_DEV
TABLE_OPTIONS=none
USE_PK=${USE_PK:-1}

SYSBENCH_DIR=${SYSBENCH_DIR:-/usr/local}
SYSBENCH="$SYSBENCH_DIR/bin/sysbench --db-driver=mysql --mysql-user=root --mysql-password=pw --mysql-host=127.0.0.1 --mysql-db=test --mysql-storage-engine=$SUBENGINE "
SYSBENCH+="--table-size=$NROWS --tables=$NTABS --events=0 --report-interval=10 --create_secondary=off --mysql-ignore-errors=1062"

printf "\nSERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE CFG_FILE=$CFG_FILE SECS=$SECS NTABS=$NTABS NROWS=$NROWS NTHREADS=$NTHREADS MEMORY=$MEMORY\n"

#HOST="--mysql-socket=/tmp/mysql.sock"
HOST="--mysql-host=127.0.0.1"
CLIENT_OPT_NOPASS="-hlocalhost -uroot"
CLIENT_OPT="$CLIENT_OPT_NOPASS -ppw"
MYSQLDIR=$ROOTDIR/mysqld
DATADIR=$ROOTDIR/master


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
    DATA_SIZE=`zenfs list --zbd=$ZENFS_DEV --path=./.rocksdb | awk '{sum+=$1;} END {print sum/1024/1024;}'`
    echo "Size of RocksDB database is $DATA_SIZE MB"
  else
    du -ch $DATADIR
  fi
}

waitmysql(){
  set +e

  echo "- Waiting for start of mysqld"
  sleep 5
  while true;
  do
          $MYSQLDIR/bin/mysql $1 -Bse "SELECT 1" mysql
          if [ "$?" -eq 0 ]; then break; fi
          sleep 5
          echo -n "."
  done
  set -e
}

run_sysbench(){
  RESULTS_DIR=results-${CFG_FILE%.*}-$ENGINE-${MEM}GB-${SECS}s-`date +%F-%H-%M`
  rm -rf $ROOTDIR/$RESULTS_DIR
  mkdir $ROOTDIR/$RESULTS_DIR
  cd $ROOTDIR/$RESULTS_DIR

  READSECS=$SECS
  WRITESECS=$SECS
  INSERTSECS=$(( $SECS / 2 ))
  CLEANUP=0

  bash all_concurrency.sh $NTABS $NROWS $READSECS $WRITESECS $INSERTSECS $SUBENGINE 0 $CLEANUP $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $PWD $DISKNAME $USE_PK $NTHREADS
  echo >_res SERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE CFG_FILE=$CFG_FILE SECS=$SECS
  cat sb.r.qps.* >>_res
  cat sb.r.qps.*
}

if [ "${COMMAND_TYPE}" == "verify" ]; then
  startmysql $CFG_FILE $CT_MEMORY
  waitmysql "$CLIENT_OPT"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; SHOW CREATE TABLE sbtest1; SHOW ENGINE ROCKSDB STATUS\G; show table status"
  shutdownmysql
  exit
fi

if [ "${COMMAND_TYPE}" == "init" ]; then
  echo "- Initialize mysqld"
  rm -rf $DATADIR
  mkdir $DATADIR
  cp $MYSQLDIR/bin/mysqld-debug $MYSQLDIR/bin/mysqld
  $MYSQLDIR/bin/mysqld --initialize-insecure --basedir=$MYSQLDIR --datadir=$DATADIR --log-error-verbosity=2

  startmysql $CFG_FILE $CT_MEMORY "--disable-log-bin --rocksdb_bulk_load=1"
  waitmysql "$CLIENT_OPT_NOPASS"
  echo "- Create 'test' database" 
  $MYSQLDIR/bin/mysql $CLIENT_OPT_NOPASS -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'pw'"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "CREATE DATABASE test"

  NTHR=${NTHREADS%% *} # get the first number
  free -m
  echo "- Start sysbench using $NTHR threads"
  time $SYSBENCH --threads=$NTHR /usr/local/share/sysbench/oltp_read_write.lua prepare --rand-type=uniform --range-size=$RANGE_SIZE
  free -m

  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; show table status"

  print_database_size
  shutdownmysql
  print_database_size

  exit
fi


for MEM in $MEMORY
do

free -m

startmysql $CFG_FILE $MEM
waitmysql "$CLIENT_OPT"

for NTHR in $NTHREADS
do
#run_sysbench
echo "- Start sysbench using $NTHR threads"
$SYSBENCH --threads=$NTHR /usr/local/share/sysbench/oltp_read_write.lua run --time=$SECS --range-size=$RANGE_SIZE
$SYSBENCH --threads=$NTHR /usr/local/share/sysbench/oltp_write_only.lua run --time=$SECS --range-size=$RANGE_SIZE
$SYSBENCH --threads=$NTHR /usr/local/share/sysbench/oltp_insert.lua run --time=$SECS --range-size=$RANGE_SIZE
done


shutdownmysql
sleep 30

done

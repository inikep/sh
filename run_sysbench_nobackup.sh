#!/bin/bash

# init   - copy binaries from $BUILDDIR to $ROOTDIR if required, initialize mysqld database
# start  - start sysbench

killall -9 mysqld && sleep 3
killall -9 vmstat

COMMAND_TYPE=$1
SERVER_BUILD=$2
ENGINE=$3
if [ "$ENGINE" == "zenfs" ]; then
  SUBENGINE=rocksdb
  DEV=nvme1n2
  ZENFS_PATH=/data/zenfs_sysbench_$DEV
  rm -rf $ZENFS_PATH
  # zbd reset /dev/nvme1n2
  /data/sh/zenfs mkfs --zbd=$DEV --aux_path=$ZENFS_PATH --finish_threshold=0 --force || exit
else
  SUBENGINE=$ENGINE
fi
CONFIG_FILE=$4
CFG_FILE=${CONFIG_FILE##*/}
STARTPATH=$PWD


# params for creating tables
NTABS=16
NROWS=200000000
CT_MEMORY=4

# sysbench
NTHREADS=16
RANGE_SIZE=10000

SYSBENCH="/usr/local/bin/sysbench --db-driver=mysql --mysql-user=root --mysql-password=pw --mysql-host=127.0.0.1 --mysql-db=test --mysql-storage-engine=$SUBENGINE "
SYSBENCH+="--table-size=$NROWS --tables=$NTABS --threads=$NTHREADS --events=0 --report-interval=5 --create_secondary=off"


# params for benchmarking
#CONCURRENCY="3 6 12"
CONCURRENCY="8 16 32"
#MEMORY="4 8 16"
MEMORY="16"
SECS="${5:-300}"
printf "\nSERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE CFG_FILE=$CFG_FILE SECS=$SECS\n"

DISKNAME=nvme1n1
TABLE_OPTIONS=none
USE_PK=1
SYSBENCH_DIR=/usr/local

#HOST="--mysql-socket=/tmp/mysql.sock"
HOST="--mysql-host=127.0.0.1"
CLIENT_OPT="-hlocalhost -uroot"
BUILDDIR=/data/mysql-server/$SERVER_BUILD
ROOTDIR=/data/bench/$SERVER_BUILD
MYSQLDIR=$ROOTDIR/mysqld
DATADIR=$ROOTDIR/master


if ([ "$COMMAND_TYPE" != "verify" ] && [ "$COMMAND_TYPE" != "init" ]) && [ "$COMMAND_TYPE" != "start" ] || ([ "$SUBENGINE" != "innodb" ] && [ "$SUBENGINE" != "rocksdb" ]) || [ $# -lt 4 ]; then
  echo "usage: $0 [init/start/verify] [server_build] [innodb/rocksdb] [my.cnf] <seconds>"
  exit
fi     

if [ ! -f "$CONFIG_FILE" ]; then
  echo "error: $CONFIG_FILE doesn't exist"
  exit
fi

sudo sh -c 'echo - root privilleges acquired'
if [ ! -d "$ROOTDIR" ]; then mkdir $ROOTDIR; fi
cp $CONFIG_FILE $ROOTDIR/$CFG_FILE
if [ ! -d "$MYSQLDIR" ]; then
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
     ADDITIONAL_PARAMS+=" --rocksdb_fs_uri=zenfs://dev:nvme1n2"
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
  sudo $MYSQLDIR/bin/mysqld $ADDITIONAL_PARAMS --user=root --port=3306 --log-error=$ROOTDIR/log.err --basedir=$MYSQLDIR --datadir=$DATADIR 2>&1 &
}

shutdownmysql(){
  echo "- Shutting mysqld down"
  $MYSQLDIR/bin/mysqladmin shutdown $CLIENT_OPT
}

waitmysql(){
  set +e

  echo "- Waiting for start of mysqld"
  sleep 5
  while true;
  do
          $MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "SELECT 1" mysql
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

  bash all_concurrency.sh $NTABS $NROWS $READSECS $WRITESECS $INSERTSECS $SUBENGINE 0 $CLEANUP $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $PWD $DISKNAME $USE_PK $CONCURRENCY
  echo >_res SERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE CFG_FILE=$CFG_FILE SECS=$SECS
  cat sb.r.qps.* >>_res
  cat sb.r.qps.*
}

if [ "${COMMAND_TYPE}" == "verify" ]; then
  startmysql $CFG_FILE $CT_MEMORY
  CLIENT_OPT="$CLIENT_OPT -ppw"
  waitmysql
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; SELECT COUNT(*) FROM sbtest1; SHOW CREATE TABLE sbtest1; SHOW ENGINE ROCKSDB STATUS\G;SELECT COUNT(*) FROM sbtest1;"
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
  waitmysql
  echo "- Create 'test' database" 
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'pw'"
  CLIENT_OPT="$CLIENT_OPT -ppw"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "CREATE DATABASE test"

free -m
$SYSBENCH /usr/local/share/sysbench/oltp_read_only.lua prepare --rand-type=uniform --range-size=$RANGE_SIZE
#$MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "SELECT COUNT(*) FROM test.sbtest1" mysql
free -m

shutdownmysql
exit
  free -m
  echo "- Load data from file"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "CREATE TABLE test.sbtest1 (id int NOT NULL AUTO_INCREMENT, k int NOT NULL DEFAULT '0', c char(120) COLLATE latin1_bin NOT NULL DEFAULT '', pad char(60) COLLATE latin1_bin NOT NULL DEFAULT '', PRIMARY KEY (id)) ENGINE=RocksDB AUTO_INCREMENT=1 DEFAULT CHARSET=latin1 COLLATE=latin1_bin" mysql
  $MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "LOAD DATA INFILE '/data/txt/sql/sysbench_8Mb.txt' INTO TABLE test.sbtest1" mysql
  $MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "SELECT * FROM test.sbtest1 LIMIT 10; SELECT COUNT(*) FROM test.sbtest1" mysql
  shutdownmysql
  sleep 5
fi


for MEM in $MEMORY
do

free -m

startmysql $CFG_FILE $MEM
CLIENT_OPT="$CLIENT_OPT -ppw"
waitmysql
#run_sysbench
$SYSBENCH /usr/local/share/sysbench/oltp_read_write.lua run --time=$SECS --range-size=$RANGE_SIZE
$SYSBENCH /usr/local/share/sysbench/oltp_write_only.lua run --time=$SECS --range-size=$RANGE_SIZE
$SYSBENCH /usr/local/share/sysbench/oltp_insert.lua run --time=$SECS --range-size=$RANGE_SIZE
shutdownmysql
sleep 30

done

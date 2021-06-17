# init   - copy binaries from $BUILDDIR to $ROOTDIR if required, initialize mysqld database
# start  - start sysbench

COMMAND_TYPE=$1
SERVER_BUILD=$2
ENGINE=$3
CONFIG_FILE=$4
CFG_FILE=${CONFIG_FILE##*/}
STARTPATH=$PWD

if [[ "$SERVER_BUILD" == *"percona"* ]] || [[ "$SERVER_BUILD" == *"wdc"* ]]; then
  IS_PERCONA_SERVER=1
fi

# params for creating tables
NTABS=1
NROWS=8000000
#NTHREADS=$NTABS
NTHREADS=1
CT_MEMORY=4


# params for benchmarking
CONCURRENCY="1"
CONCURRENCY="8 16 32"
#MEMORY="4 8 16"
MEMORY="8"
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
BACKUP_FILE=$DATADIR-$ENGINE.tar.zst


if ([ "$COMMAND_TYPE" != "verify" ] && [ "$COMMAND_TYPE" != "init" ]) && [ "$COMMAND_TYPE" != "start" ] || ([ "$ENGINE" != "innodb" ] && [ "$ENGINE" != "rocksdb" ] && [ "$ENGINE" != "rocksdb-zenfs" ] ) || [ $# -lt 4 ]; then
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

# startmysql $CFG_FILE $MEMORY
startmysql(){
  MEM="${2:-8}"
  ADDITIONAL_PARAMS=""
  if [ "$ENGINE" == "rocksdb" ]; then
      ADDITIONAL_PARAMS="--rocksdb_block_cache_size=${MEM}G --rocksdb_merge_buf_size=1G"
  else 
      ADDITIONAL_PARAMS="--innodb_buffer_pool_size=${MEM}G"
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
#  sudo $MYSQLDIR/bin/mysqld $ADDITIONAL_PARAMS --user=root --port=3306 --log-error=$ROOTDIR/log.err --basedir=$MYSQLDIR --datadir=$DATADIR 2>&1 &
  $MYSQLDIR/bin/mysqld $ADDITIONAL_PARAMS --port=3306 --log-error=$ROOTDIR/log.err --basedir=$MYSQLDIR --datadir=$DATADIR 2>&1 &
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

create_tables(){
  RESULTS_DIR=results-${CFG_FILE%.*}-$ENGINE-init
  rm -rf $ROOTDIR/$RESULTS_DIR
  mkdir $ROOTDIR/$RESULTS_DIR
  cd $ROOTDIR/$RESULTS_DIR

  echo - Creating $NTABS $ENGINE tables with $NROWS rows using $NTHREADS threads
# bash run.sh $ntabs $nrows $readsecs $ENGINE $setup 0 point-query.pre 100 $client $tableoptions $sysbdir $ddir $dname $usepk $nthreads
  bash run.sh $NTABS $NROWS 1 $ENGINE 1 0 point-query.pre 10000 $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $PWD $DISKNAME $USE_PK $NTHREADS
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

  bash all_concurrency.sh $NTABS $NROWS $READSECS $WRITESECS $INSERTSECS $ENGINE 0 $CLEANUP $MYSQLDIR/bin/mysql $TABLE_OPTIONS $SYSBENCH_DIR $PWD $DISKNAME $USE_PK $CONCURRENCY
  echo >_res SERVER_BUILD=$SERVER_BUILD ENGINE=$ENGINE CFG_FILE=$CFG_FILE SECS=$SECS
  cat sb.r.qps.* >>_res
  cat sb.r.qps.*
}

if [ "${COMMAND_TYPE}" == "verify" ]; then
  startmysql $CFG_FILE $CT_MEMORY
  CLIENT_OPT="$CLIENT_OPT -ppw"
  waitmysql
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; SELECT COUNT(*) FROM sbtest1; SHOW CREATE TABLE sbtest1; SHOW ENGINE ROCKSDB STATUS\G"
  #$MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; SET FOREIGN_KEY_CHECKS=0; alter table sbtest1 modify column id int not null"
  #$MYSQLDIR/bin/mysql $CLIENT_OPT -e "USE test; SELECT COUNT(*) FROM sbtest1; SHOW CREATE TABLE sbtest1;"
  shutdownmysql
  exit
fi

if [ "${COMMAND_TYPE}" == "init" ]; then
  echo "- Initialize mysqld"
  sudo rm -rf $DATADIR
  mkdir $DATADIR
  # 5.6 $MYSQLDIR/scripts/mysql_install_db --user=root --basedir=$MYSQLDIR --datadir=$DATADIR
  cp $MYSQLDIR/bin/mysqld-debug $MYSQLDIR/bin/mysqld
  $MYSQLDIR/bin/mysqld --initialize-insecure --basedir=$MYSQLDIR --datadir=$DATADIR --log-error-verbosity=2

  if [[ "$IS_PERCONA_SERVER" == "1" ]]; then
    startmysql no-defaults-file $CT_MEMORY
    waitmysql
    $MYSQLDIR/bin/ps-admin --enable-rocksdb $CLIENT_OPT
    shutdownmysql
    sleep 3
  fi

  free -m
  startmysql $CFG_FILE $CT_MEMORY
  waitmysql
  echo "- Create 'test' database" 
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'pw'"
  CLIENT_OPT="$CLIENT_OPT -ppw"
  $MYSQLDIR/bin/mysql $CLIENT_OPT -e "CREATE DATABASE test"
  # 5.6 $MYSQLDIR/bin/mysql $CLIENT_OPT -e "SET PASSWORD=PASSWORD('pw')"
  free -m
  create_tables

#  killall -9 mysqld
#  startmysql $CFG_FILE $CT_MEMORY
#  waitmysql
#  shutdownmysql
#  exit

#  $MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "SELECT * FROM test.sbtest1 INTO OUTFILE '/data/txt/sql/sysbench_8M.txt'" mysql
  $MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "SHOW CREATE TABLE test.sbtest1\GSELECT COUNT(*) FROM test.sbtest1" mysql
  free -m
#  echo "- Create 'k_1' index" 
#  $MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "ALTER TABLE test.sbtest1 DROP INDEX k_1; CREATE INDEX k_1 ON test.sbtest1(k);" mysql
#  $MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "ALTER TABLE test.sbtest1 DROP INDEX k_1; ALTER TABLE test.sbtest1 ADD INDEX k_1 (k);" mysql

  free -m

  shutdownmysql
  free -m
#exit
  rm -f $BACKUP_FILE
  echo "- Create a backup" 
  tar --zstd -cf $BACKUP_FILE -C $DATADIR .
  free -m
  exit
fi

CLIENT_OPT="$CLIENT_OPT -ppw"


for MEM in $MEMORY
do

free -m

echo "- Restoring backup"
rm -rf $DATADIR
mkdir $DATADIR
tar -I zstd -xf $BACKUP_FILE -C $DATADIR

free -m

startmysql $CFG_FILE $MEM
waitmysql
$MYSQLDIR/bin/mysql $CLIENT_OPT -Bse "SELECT * FROM test.sbtest1 INTO OUTFILE '/data/txt/sql/sysbench_8Mb.txt'" mysql
run_sysbench
shutdownmysql
sleep 30

done

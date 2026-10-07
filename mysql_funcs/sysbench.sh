# init   - copy binaries to $BENCHPATH, initialize mysqld database, start mysqld
# start  - start sysbench
# deinit - stop mysqld

PARAM1=$1
DIRNAME=${PWD##*/}
STARTPATH=$PWD
BENCHPATH=/data/bench/$DIRNAME
MY_CNF=$2

if [ "$PARAM1" != "init" ] && [ "$PARAM1" != "start" ] && [ "$PARAM1" != "deinit" ]; then
  echo usage: $0 [init/start/deinit] [my.cnf]
  exit
fi

if [ "$PARAM1" == "deinit" ]; then
  killall -9 mysqld
  exit
fi

if [ "$PARAM1" == "start" ]; then
  $BENCHPATH/bin/bin/mysql -uroot -ppw -e "DROP DATABASE test; CREATE DATABASE test"

  SYSBENCH_CREDS="--mysql-user=root --mysql-password=pw --mysql-host=127.0.0.1 --mysql-db=test"
  SYSBENCH_PARAMS="$SYSBENCH_CREDS --db-driver=mysql --rand-type=uniform"
  sysbench /usr/share/sysbench/oltp_read_only.lua prepare --range_size=100  --table_size=10000 --tables=1 --threads=1 --events=0 $SYSBENCH_PARAMS
  sysbench /usr/share/sysbench/oltp_write_only.lua run --range_size=6000 --table_size=10000 --tables=1 --threads=4 --events=0 --time=60 --report-interval=1 $SYSBENCH_PARAMS
  exit
fi

set -x

if [ ! -d "$BENCHPATH/bin" ]; then
   make install DESTDIR="$BENCHPATH/bin"          

   mv $BENCHPATH/bin/usr/local/mysql/* $BENCHPATH/bin/
fi

killall -9 mysqld

cd $BENCHPATH
cp bin/bin/mysqld-debug bin/bin/mysqld

MASTERWD=master
MASTER_PARAMS=""
#rm -rf $MASTERWD/
mkdir $MASTERWD cnf
cp $MY_CNF cnf/${MY_CNF##*/}
echo $PWD
# bin/bin/mysqld --defaults-file=cnf/${MY_CNF##*/} --initialize-insecure --basedir=$PWD/bin --datadir=$PWD/$MASTERWD --log-error-verbosity=3
bin/bin/mysqld --defaults-file=cnf/${MY_CNF##*/} --basedir=$PWD/bin --datadir=$PWD/$MASTERWD  --core-file --port=3306 --log-error=$PWD/$MASTERWD/log.err $MASTER_PARAMS 2>&1 &
sleep 3
bin/bin/mysql -hlocalhost -uroot -e "ALTER USER 'root'@'localhost' IDENTIFIED BY 'pw'"
bin/bin/mysql -hlocalhost -uroot -ppw -e "CREATE DATABASE test"

cd $STARTPATH

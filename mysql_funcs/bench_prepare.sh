MASTERWD=master_th32_tb4_ts1m_LOGICAL_COMMIT_ORDER
#MASTERWD=master_th32_tb4_ts1m_LOGICAL_WRITESET
SYSBENCH_PARAMS="--tables=4 --threads=32 --table_size=1000000 --events=0"
#MASTER_PARAMS="--binlog_group_commit_sync_delay=1000000"
MASTER_PARAMS="--slave_parallel_type=LOGICAL_CLOCK --binlog_transaction_dependency_tracking=COMMIT_ORDER --binlog_transaction_dependency_history_size=1000000"

if [ "$MASTERWD" == "" ] || [ "$MASTERWD" == "" ] || [ "$MASTERWD" == "" ]; then
   echo Unknown MASTERWD=$MASTERWD or SYSBENCH_PARAMS=$SYSBENCH_PARAMS or MASTER_PARAMS=$MASTER_PARAMS;
   exit 1;
fi

set -x

SRC_DIR=$PWD
BENCH_DIR=/data/bench

if [ ! -d "$BENCH_DIR/bin" ]; then
   make install DESTDIR="$BENCH_DIR/bin"
   mv $BENCH_DIR/bin/usr/local/mysql/* $BENCH_DIR/bin/
   cp $BENCH_DIR/bin/bin/mysqld-debug $BENCH_DIR/bin/bin/mysqld
fi;

cd $BENCH_DIR/bin/bin/
./mysql -uroot -S /tmp/mysql_master.sock -e "shutdown" && sleep 2

rm -rf $BENCH_DIR/$MASTERWD/
mkdir $BENCH_DIR/$MASTERWD

./mysqld --initialize-insecure --basedir=$SRC_DIR --datadir=$BENCH_DIR/$MASTERWD --log-error-verbosity=3
./mysqld --no-defaults $MASTER_PARAMS --basedir=$SRC_DIR --datadir=$BENCH_DIR/$MASTERWD --core-file --socket=/tmp/mysql_master.sock --port=3333 --log-error=$BENCH_DIR/$MASTERWD/log.err --log-bin=master-bin --server_id=1 --default_authentication_plugin=mysql_native_password 2>&1 &

sleep 2
./mysql -uroot -S /tmp/mysql_master.sock -e "CREATE DATABASE test"
./mysql -uroot -S /tmp/mysql_master.sock test -e "CREATE USER 'repl'@'localhost' IDENTIFIED BY 'slavepass'"
./mysql -uroot -S /tmp/mysql_master.sock test -e "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'localhost'"
./mysql -uroot -S /tmp/mysql_master.sock test -e "CREATE USER 'repl'@'127.0.0.1' IDENTIFIED BY 'slavepass'"
./mysql -uroot -S /tmp/mysql_master.sock test -e "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'127.0.0.1'"
./mysql -uroot -S /tmp/mysql_master.sock test -e "FLUSH PRIVILEGES"

SYSBENCH_OPTIONS="--db-driver=mysql --mysql-user=root --mysql-socket=/tmp/mysql_master.sock --mysql-db=test --rand-type=uniform --create_secondary=off"
sysbench /usr/share/sysbench/oltp_read_write.lua prepare $SYSBENCH_PARAMS $SYSBENCH_OPTIONS
# sysbench /usr/share/sysbench/oltp_write_only.lua run     $SYSBENCH_PARAMS $SYSBENCH_OPTIONS --time=60 --report-interval=1

./mysql -uroot -S /tmp/mysql_master.sock test -e "FLUSH LOGS; show master logs"

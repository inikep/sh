set -x
SRC_DIR=$PWD
BENCH_DIR=/data/bench

SLAVEWD=slave
SLAVE_PARAMS="--skip_slave_start --log_slave_updates --binlog-format=row --slave_use_idempotent_for_recovery=yes --slave_tx_isolation=READ-COMMITTED"

rm -rf $BENCH_DIR/$SLAVEWD/
mkdir $BENCH_DIR/$SLAVEWD

cd $BENCH_DIR/bin/bin/
./mysql -uroot -S /tmp/mysql_slave.sock -e "shutdown" && sleep 2
./mysqld --initialize-insecure --basedir=$SRC_DIR --datadir=$BENCH_DIR/$SLAVEWD --log-error-verbosity=2
./mysqld --no-defaults $MY_PARAMS $SLAVE_PARAMS --basedir=$SRC_DIR --datadir=$BENCH_DIR/$SLAVEWD --core-file --socket=/tmp/mysql_slave.sock --port=6666 --log-error=$BENCH_DIR/$SLAVEWD/log.err --log-bin=slave-bin --server_id=2 2>&1 &

sleep 5
./mysql -uroot -S /tmp/mysql_slave.sock -e "CHANGE MASTER TO MASTER_HOST='localhost', MASTER_PORT=3333, MASTER_USER='repl', MASTER_PASSWORD='slavepass', MASTER_LOG_FILE='master-bin.000001', MASTER_LOG_POS=0"
time ./mysql -uroot -S /tmp/mysql_slave.sock -e "start slave; SELECT MASTER_POS_WAIT('master-bin.000002', 155, 300); show slave status\G; select @@global.slave_parallel_workers, @@global.slave_parallel_type, @@global.slave_preserve_commit_order, @@global.mts_dependency_replication\G; shutdown;"

exit

/data/bench/bin/bin/mysql -uroot -S /tmp/mysql_slave.sock -e "shutdown"

MY_PARAMS="--slave_preserve_commit_order=1 --slave_parallel_workers=8 --slave_parallel_type=LOGICAL_CLOCK --mts_dependency_replication=TBL" bench_start.sh

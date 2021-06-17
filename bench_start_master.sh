set -x
SRC_DIR=$PWD
BENCH_DIR=/data/bench


MASTERWD=master_th8_tb8_ts500k_LOGICAL_COMMIT_ORDER
cd $BENCH_DIR/bin/bin/
./mysql -uroot -S /tmp/mysql_master.sock -e "shutdown" && sleep 2
./mysqld --no-defaults --basedir=$SRC_DIR --datadir=$BENCH_DIR/$MASTERWD --core-file --socket=/tmp/mysql_master.sock --port=3333 --log-error=$BENCH_DIR/$MASTERWD/log.err --log-bin=master-bin --server_id=1 $MASTER_PARAMS 2>&1 &

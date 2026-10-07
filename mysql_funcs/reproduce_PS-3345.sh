set -x

if [ ! -d "/bin" ]; then
   make install DESTDIR="$PWD/bin"
   mv $PWD/bin/usr/local/mysql/* $PWD/bin/
fi;

killall -9 mysqld

cd bin
cp ../sql/mysqld-debug bin/mysqld

MASTERWD=master_ps3345
MASTER_PARAMS="--binlog_group_commit_sync_delay=1000000"
rm -rf $MASTERWD/
mkdir $MASTERWD
bin/mysqld --initialize-insecure --basedir=$PWD --datadir=$PWD/$MASTERWD --log-error-verbosity=3
bin/mysqld --no-defaults --basedir=$PWD --datadir=$PWD/$MASTERWD --core-file --socket=/tmp/mysql_master.sock --port=3333 --log-error=$PWD/$MASTERWD/log.err --log-bin=master-bin --server_id=1 $MASTER_PARAMS 2>&1 &

SLAVEWD=slave_ps3345
SLAVE_PARAMS="--skip_slave_start --log_slave_updates --slave_preserve_commit_order=1 --slave_parallel_workers=2 --slave_parallel_type=LOGICAL_CLOCK"
rm -rf $SLAVEWD/
mkdir $SLAVEWD
bin/mysqld --initialize-insecure --basedir=$PWD --datadir=$PWD/$SLAVEWD --log-error-verbosity=3
bin/mysqld --no-defaults --basedir=$PWD --datadir=$PWD/$SLAVEWD --core-file --socket=/tmp/mysql_slave.sock --port=6666 --log-error=$PWD/$SLAVEWD/log.err --log-bin=slave-bin --server_id=2 $SLAVE_PARAMS 2>&1 &

bin/mysql -uroot -S /tmp/mysql_master.sock -e "CREATE DATABASE test"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "CREATE USER 'repl'@'localhost' IDENTIFIED BY 'slavepass'"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'localhost'"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "CREATE USER 'repl'@'127.0.0.1' IDENTIFIED BY 'slavepass'"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'127.0.0.1'"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "FLUSH PRIVILEGES"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "show master logs"

bin/mysql -uroot -S /tmp/mysql_slave.sock -e "CHANGE MASTER TO MASTER_HOST='localhost', MASTER_PORT=3333, MASTER_USER='repl', MASTER_PASSWORD='slavepass', MASTER_LOG_FILE='master-bin.000001', MASTER_LOG_POS=0"
bin/mysql -uroot -S /tmp/mysql_slave.sock -e "start slave"
bin/mysql -uroot -S /tmp/mysql_slave.sock -e "show slave status\G"

SYSBENCH_PARAMS="--db-driver=mysql --mysql-user=root --mysql-socket=/tmp/mysql_master.sock --mysql-db=test --rand-type=uniform"
sysbench /usr/share/sysbench/oltp_read_only.lua prepare --range_size=100  --table_size=10000 --tables=1 --threads=1 --events=0 $SYSBENCH_PARAMS
sysbench /usr/share/sysbench/oltp_write_only.lua run --range_size=6000 --table_size=10000 --tables=1 --threads=4 --events=0 --time=60 --report-interval=1 $SYSBENCH_PARAMS

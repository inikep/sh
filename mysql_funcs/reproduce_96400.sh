set -x
# make install DESTDIR="$PWD/bin"
# mv $PWD/bin/usr/local/mysql/* $PWD/bin/
# cd bin
# cp bin/mysqld-debug bin/mysqld

MASTERWD=master_96400
rm -rf $MASTERWD/
mkdir $MASTERWD
bin/mysqld --initialize-insecure --basedir=$PWD --datadir=$PWD/$MASTERWD --log-error-verbosity=3
# bin/mysql_install_db --user=mysql --basedir=$PWD --datadir=$PWD/$MASTERWD
bin/mysqld --no-defaults --basedir=$PWD --datadir=$PWD/$MASTERWD --core-file --socket=/tmp/mysql_master.sock --port=3333 --log-error=$PWD/$MASTERWD/log.err --log-bin=master-bin --server_id=1 2>&1 &

SLAVEWD=slave_96400
rm -rf $SLAVEWD/
mkdir $SLAVEWD
bin/mysqld --initialize-insecure --basedir=$PWD --datadir=$PWD/$SLAVEWD --log-error-verbosity=3
# bin/mysql_install_db --user=mysql --basedir=$PWD --datadir=$PWD/$SLAVEWD
bin/mysqld --no-defaults --basedir=$PWD --datadir=$PWD/$SLAVEWD --core-file --socket=/tmp/mysql_slave.sock --port=6666 --log-error=$PWD/$SLAVEWD/log.err --log-bin=slave-bin --server_id=2 --skip_slave_start --slave_parallel_workers=2 --slave_parallel_type=LOGICAL_CLOCK 2>&1 &

bin/mysql -uroot -S /tmp/mysql_master.sock -e "CREATE DATABASE test"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "CREATE USER 'repl'@'localhost' IDENTIFIED BY 'slavepass'"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'localhost'"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "CREATE USER 'repl'@'127.0.0.1' IDENTIFIED BY 'slavepass'"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "GRANT REPLICATION SLAVE ON *.* TO 'repl'@'127.0.0.1'"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "FLUSH PRIVILEGES"
bin/mysql -uroot -S /tmp/mysql_master.sock test -e "show master logs"

sysbench /usr/share/sysbench/oltp_read_write.lua --mysql_storage_engine=innodb  --table-size=100000 --mysql-db=test --db-driver=mysql --mysql-user=root --mysql-socket=/tmp/mysql_master.sock prepare

bin/mysql -uroot -S /tmp/mysql_slave.sock -e "CHANGE MASTER TO MASTER_HOST='localhost', MASTER_PORT=3333, MASTER_USER='repl', MASTER_PASSWORD='slavepass', MASTER_LOG_FILE='master-bin.000001', MASTER_LOG_POS=0"
bin/mysql -uroot -S /tmp/mysql_slave.sock -e "start slave"
bin/mysql -uroot -S /tmp/mysql_slave.sock -e "show slave status\G"

bin/mysql -uroot -S /tmp/mysql_master.sock test -e "drop table if exists sbtest10; create table sbtest10 like sbtest1; insert into sbtest10 select * from sbtest1"
kill -9 $(pgrep -f $MASTERWD)

bin/mysql -uroot -S /tmp/mysql_slave.sock -e "show slave status\G"
bin/mysql -uroot -S /tmp/mysql_slave.sock -e "SELECT NOW(); stop slave; SELECT NOW();"

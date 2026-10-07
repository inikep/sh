set -x

cd bin

bin/mysql -uroot -S /tmp/mysql_slave.sock -e "show processlist"
while true
do
bin/mysql -uroot -S /tmp/mysql_slave.sock -e "lock binlog for backup; unlock binlog;"
done

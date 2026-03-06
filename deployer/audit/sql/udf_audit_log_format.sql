SELECT audit_log_filter_set_user('%', 'filter_all');

CREATE DATABASE IF NOT EXISTS test;
USE test;
CREATE TABLE t1 (c1 INT);

# Generate three rotated logs with some events and add some events into currently active log
SET @file1_start_bookmark := audit_log_read_bookmark();
INSERT INTO t1 VALUES (1);
INSERT INTO t1 VALUES (2);
INSERT INTO t1 VALUES (3);
INSERT INTO t1 VALUES (4);
SELECT audit_log_filter_flush();
SELECT audit_log_rotate();

SET @file1_start_with_limit_bookmark := JSON_SET(@file1_start_bookmark, '$.max_array_length', 2);
SELECT @file1_start_bookmark;
SELECT @file1_start_with_limit_bookmark;

SELECT audit_log_read(@file1_start_bookmark);
SELECT audit_log_read(@file1_start_with_limit_bookmark);
SELECT audit_log_read('{"max_array_length": 2}');
SELECT audit_log_read();

DROP TABLE t1;

# {"timestamp":"2025-12-02 12:46:35","id":0,"class":"audit","event":"startup","connection_id":9,"account":{"user":"root","host":"localhost"},"login":{"user":"root","os":"","ip":"127.0.0.1","proxy":""},"startup_data":{"server_id":1,"os_version":"x86_64-Linux","mysql_version":"8.4.7-commercial","args":["/data/mysql-server/mysql-8.4.7-commercial/bin/mysqld","--defaults-file=/data/db-bench/cnf/innodb-80-noACID-audit.cnf","--datadir=./data_alf_temp","--basedir=/data/mysql-server/mysql-8.4.7-commercial","--port=3307","--skip-networking=0","--socket=/mnt/black/pstress-run/workdir-8044/audit_log_filter/data_alf.socket","--log-error-verbosity=3","--log-error=/mnt/black/pstress-run/workdir-8044/audit_log_filter/data_alf.log"]}},
# {"timestamp":"2025-12-02 12:46:35","id":1,"class":"connection","event":"connect","connection_id":20,"account":{"user":"root","host":"localhost"},"login":{"user":"root","os":"","ip":"127.0.0.1","proxy":""},"connection_data":{"connection_type":"tcp/ip","status":0,"db":""}}

# {"timestamp":"2025-12-02 12:46:35","id":2,"class":"general","event":"status","connection_id":20,"account":{"user":"root","host":"localhost"},"login":{"user":"root","os":"","ip":"127.0.0.1","proxy":""},"general_data":{"command":"Query","sql_command":"set_option","query":"SET NAMES \'utf8mb4\' COLLATE \'utf8mb4_general_ci\'","status":0}}, 
# {"timestamp":"2025-12-02 12:46:35","id":3,"class":"general","event":"status","connection_id":20,"account":{"user":"root","host":"localhost"},"login":{"user":"root","os":"","ip":"127.0.0.1","proxy":""},"general_data":{"command":"Query","sql_command":"set_option","query":"SET @@session.autocommit = OFF","status":0}} 

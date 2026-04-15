# Common MTR Test Patterns

## Basic Structure

```sql
# suite/t/ps_1234.test
--source include/have_innodb.inc

--echo #
--echo # PS-1234: Brief description of the bug
--echo #

--echo # Setup
CREATE TABLE t1 (id INT PRIMARY KEY, val VARCHAR(100)) ENGINE=InnoDB;
INSERT INTO t1 VALUES (1, 'test'), (2, 'data');

--echo # Reproduce
# The SQL that triggers the bug
SELECT * FROM t1 WHERE id = 1;

--echo # Cleanup
DROP TABLE t1;
```

## Pattern: Expected Error

```sql
--error ER_LOCK_DEADLOCK
UPDATE t1 SET val = 'x' WHERE id = 1;

# Or by error number:
--error 1213
UPDATE t1 SET val = 'x' WHERE id = 1;
```

## Pattern: Server Crash / Assertion

```sql
# Enable core dump catching
--source include/have_debug.inc

# The crash-triggering statement
--exec_in_background $MYSQLD ...

# Or for assertions — run normally, mysqld will abort with assertion message
# MTR will catch the crash and mark test as FAIL unless:
--source include/expect_crash.inc
# ... trigger crash ...
--source include/start_mysqld.inc   # restart and continue
```

## Pattern: Debug Sync (Race Conditions)

```sql
--source include/have_debug_sync.inc

SET GLOBAL debug_sync = 'RESET';

# Thread 1: pause at sync point
SET DEBUG_SYNC = 'after_lock_table SIGNAL t1_locked WAIT_FOR go';
--send UPDATE t1 SET val='a' WHERE id=1;

# Thread 2 (via connect): wait for thread 1, then do conflicting op
connect(con2, localhost, root,,);
SET DEBUG_SYNC = 'now WAIT_FOR t1_locked';
--error ER_LOCK_DEADLOCK
UPDATE t1 SET val='b' WHERE id=1;
SET DEBUG_SYNC = 'now SIGNAL go';

connection default;
--reap

SET GLOBAL debug_sync = 'RESET';
disconnect con2;
```

## Pattern: Multiple Connections

```sql
connect(con1, localhost, root,,);
connect(con2, localhost, root,,);

connection con1;
BEGIN;
SELECT * FROM t1 FOR UPDATE;

connection con2;
--send SELECT * FROM t1 FOR UPDATE;  # will block

connection con1;
COMMIT;

connection con2;
--reap

connection default;
disconnect con1;
disconnect con2;
```

## Pattern: Replication

```sql
--source include/master-slave.inc

connection master;
CREATE TABLE t1 (id INT) ENGINE=InnoDB;
INSERT INTO t1 VALUES (1);

--source include/sync_slave_sql_with_master.inc

connection slave;
SELECT * FROM t1;   # verify replication

connection master;
DROP TABLE t1;
--source include/rpl_end.inc
```

## Pattern: Wrong Query Result (assert value)

```sql
CREATE TABLE t1 (a INT);
INSERT INTO t1 VALUES (1),(2),(3);

# Use --let + --echo to assert specific values
SELECT COUNT(*) INTO @cnt FROM t1;
--let $expected = 3
if (`SELECT @cnt != $expected`) {
  --echo FAIL: expected $expected rows but got @cnt
  --die Wrong row count
}

DROP TABLE t1;
```

## Pattern: Performance Schema / INFORMATION_SCHEMA

```sql
--source include/have_performance_schema.inc

SELECT COUNT(*) FROM performance_schema.events_statements_history
WHERE SQL_TEXT LIKE '%problematic_query%';
```

## Pattern: System Variables & Config

```sql
# Save and restore global variable
SET @old_val = @@GLOBAL.innodb_buffer_pool_size;
SET GLOBAL innodb_buffer_pool_size = 128*1024*1024;

# ... test ...

SET GLOBAL innodb_buffer_pool_size = @old_val;
```

## Pattern: File Operations (for import/export bugs)

```sql
--let $datadir = `SELECT @@datadir`
--copy_file $MYSQL_TEST_DIR/std_data/input.ibd $datadir/test/input.ibd

FLUSH TABLES t1 FOR EXPORT;
--copy_file $datadir/test/t1.ibd /tmp/t1_backup.ibd
UNLOCK TABLES;
```

## Pattern: Stored Procedure / Trigger bugs

```sql
DELIMITER //
CREATE PROCEDURE reproduce_bug()
BEGIN
  DECLARE v INT DEFAULT 0;
  WHILE v < 1000 DO
    INSERT INTO t1 VALUES (v);
    SET v = v + 1;
  END WHILE;
END//
DELIMITER ;

CALL reproduce_bug();
DROP PROCEDURE reproduce_bug;
```

## Pattern: Slow Query / Optimizer

```sql
--source include/have_optimizer_trace.inc

SET optimizer_trace = 'enabled=on';
SELECT * FROM t1 WHERE ...;
SELECT * FROM information_schema.OPTIMIZER_TRACE\G
SET optimizer_trace = 'enabled=off';
```

## Pattern: InnoDB-Specific

```sql
--source include/have_innodb.inc

# Check InnoDB status
SHOW ENGINE INNODB STATUS\G

# Force a checkpoint
SET GLOBAL innodb_fast_shutdown = 0;

# Corrupt detection
--source include/have_innodb_zip.inc
CREATE TABLE t1 (a INT) ENGINE=InnoDB ROW_FORMAT=COMPRESSED;
```

## Common Include Files

| Include | Purpose |
|---------|---------|
| `have_innodb.inc` | Require InnoDB |
| `have_debug.inc` | Require debug build |
| `have_debug_sync.inc` | Require DEBUG_SYNC |
| `have_binlog_format_row.inc` | Require ROW binlog |
| `master-slave.inc` | Set up replication |
| `have_performance_schema.inc` | Require P_S |
| `have_ssl.inc` | Require SSL |
| `not_valgrind.inc` | Skip under Valgrind |
| `not_asan.inc` | Skip under ASan |

## Running MTR

```bash
# Single test
perl mysql-test-run.pl --suite=innodb --do-test=ps_1234 --force --retry=0

# Record result file (first run)
perl mysql-test-run.pl --suite=innodb --do-test=ps_1234 --record

# With specific mysqld options
perl mysql-test-run.pl --suite=innodb --do-test=ps_1234 \
  --mysqld=--innodb-buffer-pool-size=256M \
  --mysqld=--log-bin=mysql-bin \
  --force --retry=0

# With Valgrind
perl mysql-test-run.pl --suite=innodb --do-test=ps_1234 --valgrind --force

# Debug output
perl mysql-test-run.pl --suite=innodb --do-test=ps_1234 --verbose --force

# Full suite regression check
perl mysql-test-run.pl --suite=innodb --force --retry=0 --max-test-fail=0
```

## Reading MTR Output

```
# PASS
mysqltest: [pass]  innodb.ps_1234

# FAIL — shows diff between expected and actual
mysqltest: [fail]  innodb.ps_1234
--- r/ps_1234.result
+++ /path/to/r/ps_1234.reject
@@ -3,7 +3,7 @@
-Expected line
+Actual line

# CRASH — signals core dump
mysqltest: [ERROR] mysqltest failed (signal 11)
```

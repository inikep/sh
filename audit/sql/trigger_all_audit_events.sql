--
-- Trigger all audit event classes and subclasses that the audit_log_filter
-- component can observe.  Run with a connection that has sufficient
-- privileges (SUPER / SYSTEM_VARIABLES_ADMIN / etc.).
--
-- Events that cannot be triggered from plain SQL are noted in comments.
--

CREATE DATABASE IF NOT EXISTS test;
USE test;

-- =====================================================================
-- 1. General  (general_log, general_error, general_result, general_status)
--    Every SQL statement produces general events.
-- =====================================================================
SELECT 1;

-- Force a general_error subclass by executing invalid SQL.
-- (Uncomment if you want an error in the log; the client will report it.)
-- DO syntax_error_here;

-- =====================================================================
-- 2. Command  (command_start, command_end)
--    Every client command (Query, Quit, Ping, etc.) fires these.
--    Each SQL statement below is itself a "Query" command.
-- =====================================================================
SELECT 'command event';

-- =====================================================================
-- 3. Parse  (parse_preparse, parse_postparse)
--    Fired for every statement the server parses.
-- =====================================================================
SELECT 'parse event';

-- =====================================================================
-- 4. Query  (query_start, query_status_end)
--    Every top-level query fires these.
-- =====================================================================
SELECT 'query event - top level';

-- =====================================================================
-- 5. Query – nested  (query_nested_start, query_nested_status_end)
--    Triggered by queries executed inside stored programs / triggers.
-- =====================================================================
CREATE TABLE IF NOT EXISTS trigger_test (id INT PRIMARY KEY, val INT);

DELIMITER //
CREATE PROCEDURE trigger_nested_query()
BEGIN
  DO (SELECT 'nested query from stored procedure');
END//
DELIMITER ;

CALL trigger_nested_query();
DROP PROCEDURE trigger_nested_query;

CREATE TRIGGER trg_before_ins BEFORE INSERT ON trigger_test
  FOR EACH ROW SET NEW.val = NEW.val + 100;
INSERT INTO trigger_test VALUES (1, 1);
DROP TRIGGER trg_before_ins;

-- =====================================================================
-- 6. Table Access  (read, insert, update, delete)
-- =====================================================================
CREATE TABLE IF NOT EXISTS t_access (id INT PRIMARY KEY, data VARCHAR(50));

INSERT INTO t_access VALUES (1, 'inserted');
INSERT INTO t_access VALUES (2, 'to_update');
INSERT INTO t_access VALUES (3, 'to_delete');
SELECT * FROM t_access;
UPDATE t_access SET data = 'updated' WHERE id = 2;
DELETE FROM t_access WHERE id = 3;

DROP TABLE t_access;
DROP TABLE trigger_test;

-- =====================================================================
-- 7. Global Variable  (global_variable_get, global_variable_set)
-- =====================================================================
SELECT @@global.sort_buffer_size;
SET @saved_sort_buf = @@global.sort_buffer_size;
SET GLOBAL sort_buffer_size = 1048576;
SET GLOBAL sort_buffer_size = @saved_sort_buf;

-- =====================================================================
-- 8. Stored Program  (stored_program_execute)
-- =====================================================================
DELIMITER //
CREATE PROCEDURE sp_audit_test()
BEGIN
  DO (SELECT 'stored program executed');
END//
DELIMITER ;

CALL sp_audit_test();
DROP PROCEDURE sp_audit_test;

CREATE FUNCTION fn_audit_test() RETURNS INT DETERMINISTIC
  RETURN 42;
SELECT fn_audit_test();
DROP FUNCTION fn_audit_test;

-- =====================================================================
-- 9. Authentication subclass events
--    authid_create, credential_change, authid_rename, authid_drop, flush
-- =====================================================================
CREATE USER 'audit_tmp_user'@'localhost' IDENTIFIED BY 'Passw0rd!';
ALTER USER 'audit_tmp_user'@'localhost' IDENTIFIED BY 'NewPassw0rd!';
RENAME USER 'audit_tmp_user'@'localhost' TO 'audit_renamed'@'localhost';
DROP USER 'audit_renamed'@'localhost';
FLUSH PRIVILEGES;

-- =====================================================================
-- 10. Connection  (connect, disconnect, change_user, pre_authenticate)
--
--     Plain SQL cannot open/close connections or issue COM_CHANGE_USER.
--     Use one of the approaches below:
--
--     a) From the mysql CLI, reconnect:
--          \connect audit_user@localhost
--          \quit
--
--     b) From a second client session:
--          mysql -u audit_user -p -e "SELECT 'connection event'"
--
--     c) In MTR (.test file):
--          connect (con1,localhost,audit_user,password,test);
--          disconnect con1;
--          connection default;
--
--     d) COM_CHANGE_USER via the C API or mysqltest:
--          --change_user audit_user,password,test
-- =====================================================================
-- (cannot be done from within a single SQL script)

-- =====================================================================
-- 11. Message  (message_user)
--     Requires the audit_api_message_emit component.
-- =====================================================================
INSTALL COMPONENT 'file://component_audit_api_message_emit';

SELECT audit_api_message_emit_udf(
  'test_component',
  'test_producer',
  'trigger all events test',
  'key1', 'value1',
  'key2', 123
) AS message_result;

UNINSTALL COMPONENT 'file://component_audit_api_message_emit';

-- =====================================================================
-- 12. Server Startup  (startup)
--     Only generated when mysqld starts. Cannot be triggered from SQL.
--     In MTR: --source include/restart_mysqld.inc
-- =====================================================================
-- (requires server restart)

-- =====================================================================
-- 13. Server Shutdown  (shutdown)
--     Generated when mysqld shuts down.
--     The SHUTDOWN statement will stop the server.
-- =====================================================================
-- Uncomment to actually shut down the server:
-- SHUTDOWN;

-- =====================================================================
-- Summary of events NOT triggerable from plain SQL:
--   - connection (connect / disconnect / change_user / pre_authenticate)
--   - server_startup
--   - server_shutdown  (SHUTDOWN works but terminates the server)
--   - message_internal (only emitted by server components, not the UDF)
--   - Percona-internal audit/noaudit events
-- =====================================================================

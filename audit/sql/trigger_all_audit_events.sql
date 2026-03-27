--
-- Trigger all audit event classes and subclasses that the audit_log_filter
-- component can observe.  Run with a connection that has sufficient
-- privileges (SUPER / SYSTEM_VARIABLES_ADMIN / etc.).
--
-- Events that cannot be triggered from plain SQL are noted in comments.
--

-- =====================================================================
-- Initialization (schema, routines, user, saved globals, components)
-- =====================================================================

CREATE DATABASE IF NOT EXISTS test;
USE test;

CREATE TABLE IF NOT EXISTS trigger_test (id INT PRIMARY KEY, val INT);
CREATE TABLE IF NOT EXISTS t_access (id INT PRIMARY KEY, data VARCHAR(50));

DELIMITER //
CREATE PROCEDURE trigger_nested_query()
BEGIN
  DO (SELECT 'nested query from stored procedure');
END//
CREATE PROCEDURE sp_audit_test()
BEGIN
  DO (SELECT 'stored program executed');
END//
DELIMITER ;

CREATE TRIGGER trg_before_ins BEFORE INSERT ON trigger_test
  FOR EACH ROW SET NEW.val = NEW.val + 100;

CREATE FUNCTION fn_audit_test() RETURNS INT DETERMINISTIC
  RETURN 42;

CREATE USER 'audit_tmp_user'@'localhost' IDENTIFIED BY 'Passw0rd!';

SET @saved_sort_buf = @@global.sort_buffer_size;

INSTALL COMPONENT 'file://component_test_audit_api_message';

-- =====================================================================
-- 1. General  (general_log, general_error, general_result, general_status)
-- 2. Command  (command_start, command_end)
-- 3. Parse  (parse_preparse, parse_postparse)
-- 4. Query  (query_start, query_status_end)
--    Every SQL statement produces general events.
-- =====================================================================
SELECT 1;

-- general/error
SELECT * FROM missing_table_for_audit;

-- =====================================================================
-- 5. Query – nested  (query_nested_start, query_nested_status_end)
--    Triggered by queries executed inside stored programs / triggers.
-- =====================================================================
CALL trigger_nested_query();
INSERT INTO trigger_test VALUES (1, 1);

-- =====================================================================
-- 6. Table Access  (read, insert, update, delete)
-- =====================================================================
INSERT INTO t_access VALUES (1, 'inserted');
INSERT INTO t_access VALUES (2, 'to_update');
INSERT INTO t_access VALUES (3, 'to_delete');
SELECT * FROM t_access;
UPDATE t_access SET data = 'updated' WHERE id = 2;
DELETE FROM t_access WHERE id = 3;

-- =====================================================================
-- 7. Global Variable  (global_variable_get, global_variable_set)
-- =====================================================================
SELECT @@global.sort_buffer_size;
SET GLOBAL sort_buffer_size = 1048576;

-- =====================================================================
-- 8. Stored Program  (stored_program_execute)
-- =====================================================================
CALL sp_audit_test();
SELECT fn_audit_test();

-- =====================================================================
-- 9. Authentication subclass events
--    authid_create, credential_change, authid_rename, authid_drop, flush
-- =====================================================================
ALTER USER 'audit_tmp_user'@'localhost' IDENTIFIED BY 'NewPassw0rd!';
RENAME USER 'audit_tmp_user'@'localhost' TO 'audit_renamed'@'localhost';

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
-- 11. Message  (message_internal, message_user)
--     UDFs test_audit_api_message_* are registered by the test component
--     component_test_audit_api_message (components/test/test_audit_api_message).
--     For production-style emits use component_audit_api_message_emit and
--     audit_api_message_emit_udf(...) instead.
-- =====================================================================
SELECT test_audit_api_message_internal();
SELECT test_audit_api_message_user();

-- =====================================================================
-- Deinitialization (restore globals, drop objects, uninstall components)
-- =====================================================================

SET GLOBAL sort_buffer_size = @saved_sort_buf;

DROP TRIGGER trg_before_ins;
DROP PROCEDURE trigger_nested_query;
DROP PROCEDURE sp_audit_test;
DROP FUNCTION fn_audit_test;
DROP TABLE t_access;
DROP TABLE trigger_test;

DROP USER 'audit_renamed'@'localhost';
FLUSH PRIVILEGES;

UNINSTALL COMPONENT 'file://component_test_audit_api_message';

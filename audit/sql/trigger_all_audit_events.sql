--
-- Trigger all 30 audit event class/event pairs that the audit_log_filter
-- component can observe.  Run with a connection that has sufficient
-- privileges (SUPER / SYSTEM_VARIABLES_ADMIN / etc.).
--
-- Run order: trigger_all_audit_events-init.sql, this file,
--            trigger_all_audit_events-deinit.sql
--
-- Observed class/event pairs (30):
--
--   audit/startup, audit/shutdown              – implicit (server lifecycle)
--   connection/connect, connection/disconnect,
--     connection/pre_authenticate              – implicit (session lifecycle)
--   command/command_start, command/command_end  – every SQL statement
--   parse/preparse, parse/postparse            – every SQL statement
--   query/query_start, query/query_status_end  – every SQL statement
--   general/log, general/result,
--     general/status                           – every SQL statement
--   general/error                              – §2
--   query/query_nested_start,
--     query/query_nested_status_end            – §3
--   stored_program/execute                     – §3
--   table_access/insert, table_access/read,
--     table_access/update, table_access/delete – §4
--   message/internal, message/user             – §5
--   global_variable/variable_get,
--     global_variable/variable_set             – §6
--   authentication/auth_credential_change,
--     authentication/auth_authid_rename,
--     authentication/auth_authid_drop,
--     authentication/auth_flush                – §7
--

USE test;

-- =====================================================================
-- §1  general/log, general/result, general/status
--     command/command_start, command/command_end
--     parse/preparse, parse/postparse
--     query/query_start, query/query_status_end
--     Every SQL statement produces these events.
-- =====================================================================
-- SELECT 1;

-- =====================================================================
-- §2  general/error
-- =====================================================================
SELECT * FROM missing_table_for_audit;

-- =====================================================================
-- §3  query/query_nested_start, query/query_nested_status_end,
--     stored_program/execute
--     Triggered by queries inside stored programs / triggers.
-- =====================================================================
CALL trigger_nested_query();

-- =====================================================================
-- §4  table_access/insert, table_access/read,
--     table_access/update, table_access/delete
-- =====================================================================
INSERT INTO t_access VALUES (1, 'inserted');
SELECT * FROM t_access;
UPDATE t_access SET data = 'updated' WHERE id = 1;
DELETE FROM t_access WHERE id = 1;

-- =====================================================================
-- §5  message/internal, message/user
--     UDFs registered by component_test_audit_api_message.  For
--     production use component_audit_api_message_emit instead.
-- =====================================================================
SELECT test_audit_api_message_internal();
SELECT test_audit_api_message_user();

-- =====================================================================
-- §6  global_variable/variable_get, global_variable/variable_set
-- =====================================================================
SELECT @@global.sort_buffer_size;
SET GLOBAL sort_buffer_size = 1048576;

-- =====================================================================
-- §7  authentication/auth_credential_change,
--     authentication/auth_authid_rename,
--     authentication/auth_authid_drop, authentication/auth_flush
--     (auth_authid_create is fired in -init.sql)
-- =====================================================================
ALTER USER 'audit_tmp_user'@'localhost' IDENTIFIED BY 'NewPassw0rd!';
RENAME USER 'audit_tmp_user'@'localhost' TO 'audit_renamed'@'localhost';
DROP USER 'audit_renamed'@'localhost';
FLUSH PRIVILEGES;

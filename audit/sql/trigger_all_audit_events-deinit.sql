--
-- Deinitialization for trigger_all_audit_events.sql (run after the main script).
-- Requires trigger_all_audit_events-init.sql to have been run first.
--

SET GLOBAL sort_buffer_size = @saved_sort_buf;

DROP PROCEDURE trigger_nested_query;
DROP TABLE t_access;

UNINSTALL COMPONENT 'file://component_test_audit_api_message';

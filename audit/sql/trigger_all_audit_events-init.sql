--
-- Initialization for trigger_all_audit_events.sql (run first).
-- See trigger_all_audit_events-deinit.sql for teardown.
--

CREATE DATABASE IF NOT EXISTS test;
USE test;

CREATE TABLE IF NOT EXISTS t_access (id INT PRIMARY KEY, data VARCHAR(50));

DELIMITER //
CREATE PROCEDURE trigger_nested_query()
BEGIN
  DO (SELECT 'nested query from stored procedure');
END//
DELIMITER ;

CREATE USER 'audit_tmp_user'@'localhost' IDENTIFIED BY 'Passw0rd!';

SET @saved_sort_buf = @@global.sort_buffer_size;

INSTALL COMPONENT 'file://component_test_audit_api_message';

SELECT audit_log_filter_set_filter('filter_all', '{
  "filter": { "log": true } 
}');
SELECT audit_log_filter_set_user('%', 'filter_all');

USE mysql;

SELECT audit_log_filter_set_filter('filter_all', '{"filter": {"log": true}}');
SELECT audit_log_filter_set_filter('filter_empty', '{"filter": {} }');
SELECT audit_log_filter_set_filter('filter_con', '{"filter": { "class": [ { "name": "connection" } ] } }');

# SELECT audit_log_filter_set_user('%', 'filter_all');

SELECT 
    u.username, 
    u.userhost, 
    f.name AS filter_name, 
    f.filter AS filter_definition
FROM mysql.audit_log_user u
JOIN mysql.audit_log_filter f ON u.filtername = f.name;

SHOW CREATE TABLE mysql.audit_log_filter;
# SELECT * FROM mysql.audit_log_filter;
SHOW CREATE TABLE mysql.audit_log_user;
# SELECT * FROM mysql.audit_log_user;

# from mysql_system_tables_fix.sql
ALTER TABLE mysql.audit_log_user DROP FOREIGN KEY audit_log_user_ibfk_1;
ALTER TABLE mysql.audit_log_user MODIFY COLUMN HOST VARCHAR(255) BINARY NOT NULL;
ALTER TABLE mysql.audit_log_filter ENGINE=InnoDB;
ALTER TABLE mysql.audit_log_filter CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_ci;
ALTER TABLE mysql.audit_log_user ENGINE=InnoDB;
ALTER TABLE mysql.audit_log_user CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_ci;
ALTER TABLE mysql.audit_log_user MODIFY COLUMN USER VARCHAR(32);
ALTER TABLE mysql.audit_log_user ADD FOREIGN KEY (FILTERNAME) REFERENCES mysql.audit_log_filter(NAME);

SHOW CREATE TABLE mysql.audit_log_filter;
SHOW CREATE TABLE mysql.audit_log_user;

SELECT * FROM mysql.audit_log_filter;
SELECT audit_log_filter_remove_filter('filter_empty');
SELECT SLEEP(5);
SELECT * FROM mysql.audit_log_filter;

ALTER TABLE audit_log_user RENAME INDEX filtername TO filter_name;
SELECT audit_log_filter_remove_filter('filter_all');
SELECT * FROM mysql.audit_log_filter;

#SET @had_audit_log_user =
#  (SELECT COUNT(table_name) FROM information_schema.tables
#     WHERE table_schema = 'mysql' AND table_name = 'audit_log_user' AND
#           table_type = 'BASE TABLE');
#SELECT @had_audit_log_user;

USE mysql;

CREATE TABLE IF NOT EXISTS audit_log_filter(NAME VARCHAR(64) BINARY NOT NULL PRIMARY KEY, FILTER JSON NOT NULL) engine= InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_ci;
CREATE TABLE IF NOT EXISTS audit_log_user(USER VARCHAR(32) BINARY NOT NULL, HOST VARCHAR(255) CHARACTER SET ASCII NOT NULL, FILTERNAME VARCHAR(64) BINARY NOT NULL, PRIMARY KEY (USER, HOST), FOREIGN KEY (FILTERNAME) REFERENCES audit_log_filter(NAME)) engine= InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_ci;

INSTALL PLUGIN audit_log SONAME 'audit_log.so';

CREATE FUNCTION audit_log_filter_set_filter RETURNS STRING SONAME 'audit_log.so';
CREATE FUNCTION audit_log_filter_remove_filter RETURNS STRING SONAME 'audit_log.so';
CREATE FUNCTION audit_log_filter_set_user RETURNS STRING SONAME 'audit_log.so';
CREATE FUNCTION audit_log_filter_remove_user RETURNS STRING SONAME 'audit_log.so';
CREATE FUNCTION audit_log_filter_flush RETURNS STRING SONAME 'audit_log.so';
CREATE FUNCTION audit_log_read_bookmark RETURNS STRING SONAME 'audit_log.so';
CREATE FUNCTION audit_log_read RETURNS STRING SONAME 'audit_log.so';
CREATE FUNCTION audit_log_encryption_password_set RETURNS INTEGER SONAME 'audit_log.so';
CREATE FUNCTION audit_log_encryption_password_get RETURNS STRING SONAME 'audit_log.so';
CREATE FUNCTION audit_log_rotate RETURNS STRING SONAME 'audit_log.so';

SELECT audit_log_filter_flush() AS 'Result';

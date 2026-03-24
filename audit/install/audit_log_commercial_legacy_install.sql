USE mysql;

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

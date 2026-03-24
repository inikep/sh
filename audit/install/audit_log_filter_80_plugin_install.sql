USE mysql;

SELECT @sys_var_database := variable_value FROM performance_schema.global_variables WHERE variable_name = 'audit_log_filter_database';
SET @db_name = IFNULL(IFNULL(@sys_var_database, DATABASE()), 'mysql');

SET @create_filter = CONCAT(
  'CREATE TABLE IF NOT EXISTS ', @db_name, '.audit_log_filter (',
    'filter_id INT UNSIGNED NOT NULL AUTO_INCREMENT,',
    'name VARCHAR(255) NOT NULL,',
    'filter JSON NOT NULL,',
    'PRIMARY KEY (`filter_id`),',
    'UNIQUE KEY `filter_name` (`name`)',
  ') Engine = InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_ci'
);

SET @create_user = CONCAT(
  'CREATE TABLE IF NOT EXISTS ', @db_name, '.audit_log_user(',
    'username VARCHAR(32) NOT NULL,',
    'userhost VARCHAR(255) NOT NULL,',
    'filtername VARCHAR(255) NOT NULL,',
    'PRIMARY KEY (username, userhost), FOREIGN KEY `filter_name` (filtername) REFERENCES ', @db_name, '.audit_log_filter(name)'
  ') Engine = InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_ci'
);

PREPARE stmt from @create_filter;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

PREPARE stmt from @create_user;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSTALL PLUGIN audit_log_filter SONAME 'audit_log_filter.so';

SELECT audit_log_filter_set_filter('filter_all', '{
  "filter": { "log": true } 
}');

SELECT audit_log_filter_set_filter('filter_none', '{
  "filter": { "log": false } 
}');

SELECT audit_log_filter_set_filter('filter_empty', '{
  "filter": { } 
}');

SELECT audit_log_filter_set_filter('filter_con', '{"filter": { "class": [
  { "name": "connection" }
] } }');

SELECT audit_log_filter_set_filter('filter_tab', '{"filter": { "class": [
  { "name": "table_access" }
] } }');

SELECT audit_log_filter_set_filter('filter_gen', '{"filter": { "class": [
  { "name": "general" }
] } }');


SELECT audit_log_filter_set_filter('filter_con_gen_tab', '{"filter": { "class": [
  { "name": "connection" },
  { "name": "general" },
  { "name": "table_access" }
] } }');

SELECT audit_log_filter_set_filter('filter_tab_anyField', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "or": [
            { "field": { "name": "connection_id", "value": 1 } },
            { "field": { "name": "sql_command_id", "value": 0 } },
            { "field": { "name": "query.str", "value": "SELECT * FROM t1" } },
            { "field": { "name": "query.length", "value": 16 } },
            { "field": { "name": "table_database.str", "value": "test" } },
            { "field": { "name": "table_database.length", "value": 4 } },
            { "field": { "name": "table_name.str", "value": "t1" } },
            { "field": { "name": "table_name.length", "value": 2 } }
          ]
        }
      }
  }
] } }');

SELECT audit_log_filter_set_filter('filter_gen_manyFields', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "and": [
            { "field": { "name": "general_error_code", "value": 0 } },
            { "field": { "name": "general_command.str", "value": "Query" } },
            { "field": { "name": "general_command.length", "value": 5 } },
            { "field": { "name": "general_host.str", "value": "localhost" } },
            { "field": { "name": "general_host.length", "value": 9 } },
            { "field": { "name": "general_sql_command.str", "value": "select" } },
            { "field": { "name": "general_sql_command.length", "value": 6 } },
            { "field": { "name": "general_external_user.str", "value": "" } },
            { "field": { "name": "general_external_user.length", "value": 0 } }
          ]
        }
      }
  }
] } }');

CREATE DATABASE IF NOT EXISTS test;
USE test;
CREATE TABLE IF NOT EXISTS t_access (id INT PRIMARY KEY, data VARCHAR(50));
INSERT INTO t_access VALUES (1, 'inserted');

SELECT PLUGIN_NAME, PLUGIN_STATUS FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME LIKE 'audit%';
SHOW GLOBAL VARIABLES LIKE 'audit%';

#SELECT audit_log_filter_set_user('%', 'filter_all');
#SELECT audit_log_filter_set_user('%', 'filter_tab_anyField');
#SELECT audit_log_filter_set_user('%', 'filter_gen_manyFields');
#SELECT audit_log_filter_set_user('%', 'filter_gen');
#SELECT audit_log_filter_set_user('%', 'filter_tab');

SELECT audit_log_filter_set_filter('filter_all', '{
  "filter": { "log": true } 
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

# MySQL 8.4.7 Enterprise
# ERROR: Class name not supported. [$.filter.class[1].name
SELECT audit_log_filter_set_filter('filter_gen_que', '{"filter": { "class": [
  { "name": "general" },
  { "name": "query" }
] } }');

SELECT audit_log_filter_set_filter('filter_con_gen_tab', '{"filter": { "class": [
  { "name": "connection" },
  { "name": "general" },
  { "name": "table_access" }
] } }');

SELECT audit_log_filter_set_filter('filter_con_tab_genQuery', '{"filter": { "class": [
  { "name": "connection" },
  { "name": "table_access" },
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_command.str", "value": "Query" }
        }
      }
  }
] } }');

# works with MySQL 8.4.7 Enterprise
SELECT audit_log_filter_set_filter('filter_genQuery', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_command.str", "value": "Query" }
        }
      }
  }
] } }');

# works with MySQL 8.4.7 Enterprise
SELECT audit_log_filter_set_filter('filter_genSelect', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_sql_command.str", "value": "select" }
        }
      }
  }
] } }');

# works with MySQL 8.4.7 Enterprise
# sql_command_id = 0 (select); 5 (insert)
SELECT audit_log_filter_set_filter('filter_tabSelect', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": "read",
        "log": {
          "field": { "name": "sql_command_id", "value": 0 }
        }
      }
  }
] } }');

# works with PS 8.4.7-7
# sql_command_id = 0 (select); 5 (insert)
SELECT audit_log_filter_set_filter('filter_tabSelectPS', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": "read",
        "log": {
          "field": { "name": "sql_command_id", "value": "0" }
        }
      }
  }
] } }');



# simulates MySQL 8.4.7 Enterprise
SELECT audit_log_filter_set_filter('filter_genSelect_tabSelect', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_sql_command.str", "value": "select" }
        }
      }
  },
  { "name": "table_access",
      "event": {
        "name": "read",
        "log": {
          "field": { "name": "sql_command_id", "value": 0 }
        }
      }
  }
] } }');

# simulates MySQL 8.4.7 Enterprise
SELECT audit_log_filter_set_filter('filter_genSelect_tabSelectPS', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_sql_command.str", "value": "select" }
        }
      }
  },
  { "name": "table_access",
      "event": {
        "name": "read",
        "log": {
          "field": { "name": "sql_command_id", "value": "0" }
        }
      }
  }
] } }');



# MySQL 8.4.7 Enterprise
# ERROR: Unknown event name [$.filter.class[0].event].  
SELECT audit_log_filter_set_filter('log_old', '{"filter": { "class": [
  { "name": "general",
      "event": {"name": "log"},
      "general_data": { "sql_command": "select" }
  }
] } }');

SELECT audit_log_filter_set_filter('filter4', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_host.str", "value": "localhost" }
        }
      }
  },
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "host.str", "value": "localhost" }
        }
      }
  },
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "table_database.str", "value": "test" }
        }
      }
  }
] } }');

SELECT audit_log_filter_set_filter('filter5int', '{"filter": { "class": [
  { "name": "table_access", 
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "sql_command_id", "value": 5 }
        }
      }
  }
] } }');

# MySQL 8.4.7 Enterprise
# ERROR: Invalid element type [$.filter.class[0].event.log.field.value]. 
SELECT audit_log_filter_set_filter('filter5str', '{"filter": { "class": [
  { "name": "table_access", 
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "sql_command_id", "value": "5" }
        }
      }
  }
] } }');

SELECT audit_log_filter_set_filter('filter6int', '{"filter": { "class": [
  { "name": "connection", 
      "event": {
        "name": [ "connect" ],
        "log": {
          "field": { "name": "connection_id", "value": 31 }
        }
      }
  }
] } }');

# MySQL 8.4.7 Enterprise
# ERROR: Invalid element type [$.filter.class[0].event.log.field.value]. 
SELECT audit_log_filter_set_filter('filter6str', '{"filter": { "class": [
  { "name": "connection", 
      "event": {
        "name": [ "connect" ],
        "log": {
          "field": { "name": "connection_id", "value": "31" }
        }
      }
  }
] } }');

# MySQL 8.4.7 Enterprise
# ERROR: Invalid element type [$.filter.class[0].event.log.field.value]. 
SELECT audit_log_filter_set_filter('filter_bad1', '{"filter": { "class": [
  { "name": "table_access", 
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "WRONG.str", "value": "test" }
        }
      }
  }
] } }');


SELECT audit_log_filter_set_filter('filter_gen_AND', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "and": [
            { "field": { "name": "general_command.str", "value": "Query" } },
            { "field": { "name": "general_sql_command.str", "value": "select" } }
          ]
        }
      }
  }
] } }');   

SELECT audit_log_filter_set_filter('filter_gen_OR', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "or": [
            { "field": { "name": "general_sql_command.str", "value": "create_table" } },
            { "field": { "name": "general_sql_command.str", "value": "select" } }
          ]
        }
      }
  }
] } }');

SELECT audit_log_filter_set_filter('filter_broken_queryLen_str', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "query.length", "value": "aa8" }
        }
      }
  }
] } }');

SELECT audit_log_filter_set_filter('filter_con_connType', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "aa8"}
        }
      }
  }
] } }');


SELECT PLUGIN_NAME, PLUGIN_STATUS FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME LIKE 'audit%';
SHOW GLOBAL VARIABLES LIKE 'audit%';

-- OK SELECT audit_log_filter_set_user('%', 'filter3');
-- BAD SELECT audit_log_filter_set_user('root%', 'filter3');
-- BAD SELECT audit_log_filter_set_user('root@%', 'filter3');
-- OK SELECT audit_log_filter_set_user('root@localhost', 'filter3');
-- BAD SELECT audit_log_filter_set_user('root@127.0.0.1', 'filter3');

# SELECT audit_log_filter_set_user('%', 'filter_con_tab_genQuery');
# SELECT audit_log_filter_set_user('%', 'filter_all'); # 8 records/query 
# SELECT audit_log_filter_set_user('%', 'filter_gen_que'); # 5 records/query 
# SELECT audit_log_filter_set_user('%', 'filter_gen'); # 3 records/query 
# SELECT audit_log_filter_set_user('%', 'filter_genQuery'); # 1 records/query

#SELECT audit_log_filter_set_user('%', 'filter_gen_OR');
SELECT audit_log_filter_set_user('%', 'filter_all');

# ---------------------------------------------------------------
# Filters validating individual table_access field support
# ---------------------------------------------------------------

# connection_id: unsigned integer (uint64_t)
SELECT audit_log_filter_set_filter('filter_tab_connId', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "connection_id", "value": 1 }
        }
      }
  }
] } }');

# sql_command_id: integer (int64_t)
# 0 = select, 5 = insert
SELECT audit_log_filter_set_filter('filter_tab_sqlCmdId', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "sql_command_id", "value": 0 }
        }
      }
  }
] } }');

# query.str: string
SELECT audit_log_filter_set_filter('filter_tab_queryStr', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "query.str", "value": "SELECT 1" }
        }
      }
  }
] } }');

# query.length: unsigned integer (uint64_t)
SELECT audit_log_filter_set_filter('filter_tab_queryLen', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "query.length", "value": 8 }
        }
      }
  }
] } }');

# table_database.str: string
SELECT audit_log_filter_set_filter('filter_tab_dbStr', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "table_database.str", "value": "test" }
        }
      }
  }
] } }');

# table_database.length: unsigned integer (uint64_t)
SELECT audit_log_filter_set_filter('filter_tab_dbLen', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "table_database.length", "value": 4 }
        }
      }
  }
] } }');

# table_name.str: string
SELECT audit_log_filter_set_filter('filter_tab_tblStr', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "table_name.str", "value": "t1" }
        }
      }
  }
] } }');

# table_name.length: unsigned integer (uint64_t)
SELECT audit_log_filter_set_filter('filter_tab_tblLen', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "field": { "name": "table_name.length", "value": 2 }
        }
      }
  }
] } }');

# ---------------------------------------------------------------
# Combined filter: all fields in a single filter using "and"
# Matches: SELECT on table "t1" in database "test"
# ---------------------------------------------------------------

SELECT audit_log_filter_set_filter('filter_tab_allFields', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "insert", "update", "delete", "read" ],
        "log": {
          "and": [
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

# ---------------------------------------------------------------
# Combined filter: all fields using "or" (log if ANY field matches)
# ---------------------------------------------------------------

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

# ---------------------------------------------------------------
# Broken filters: expected to fail at set_filter time or behave
# incorrectly — useful for negative/validation testing
# ---------------------------------------------------------------

# BROKEN: wrong type — string value for unsigned integer field connection_id
# MySQL Enterprise rejects this: "Invalid element type [$.filter...value]"
SELECT audit_log_filter_set_filter('filter_broken_connId_str', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "connection_id", "value": "1" }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for integer field sql_command_id
SELECT audit_log_filter_set_filter('filter_broken_sqlCmdId_str', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "sql_command_id", "value": "0" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field query.str
SELECT audit_log_filter_set_filter('filter_broken_queryStr_int', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "query.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field query.length
SELECT audit_log_filter_set_filter('filter_broken_queryLen_str', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "query.length", "value": "8" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field table_database.str
SELECT audit_log_filter_set_filter('filter_broken_dbStr_int', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "table_database.str", "value": 99 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field table_database.length
SELECT audit_log_filter_set_filter('filter_broken_dbLen_str', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "table_database.length", "value": "4" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field table_name.str
SELECT audit_log_filter_set_filter('filter_broken_tblStr_int', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "table_name.str", "value": 77 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field table_name.length
SELECT audit_log_filter_set_filter('filter_broken_tblLen_str', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "table_name.length", "value": "2" }
        }
      }
  }
] } }');

# BROKEN: nonexistent field name
SELECT audit_log_filter_set_filter('filter_broken_badField', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "NONEXISTENT.str", "value": "x" }
        }
      }
  }
] } }');

# BROKEN: field from wrong class (general_command.str belongs to "general", not "table_access")
SELECT audit_log_filter_set_filter('filter_broken_wrongClass', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "general_command.str", "value": "Query" }
        }
      }
  }
] } }');

# BROKEN: missing "value" key in field object
SELECT audit_log_filter_set_filter('filter_broken_noValue', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "table_name.str" }
        }
      }
  }
] } }');

# BROKEN: missing "name" key in field object
SELECT audit_log_filter_set_filter('filter_broken_noName', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "value": "t1" }
        }
      }
  }
] } }');

# BROKEN: null value
SELECT audit_log_filter_set_filter('filter_broken_nullValue', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "table_name.str", "value": null }
        }
      }
  }
] } }');

# BROKEN: boolean value
SELECT audit_log_filter_set_filter('filter_broken_boolValue', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "connection_id", "value": true }
        }
      }
  }
] } }');

# BROKEN: negative value for unsigned integer field connection_id
SELECT audit_log_filter_set_filter('filter_broken_connId_neg', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "connection_id", "value": -1 }
        }
      }
  }
] } }');

# BROKEN: float value for integer field sql_command_id
SELECT audit_log_filter_set_filter('filter_broken_sqlCmdId_float', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "sql_command_id", "value": 1.5 }
        }
      }
  }
] } }');

# BROKEN: array value for field
SELECT audit_log_filter_set_filter('filter_broken_arrayValue', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { "name": "table_name.str", "value": ["t1", "t2"] }
        }
      }
  }
] } }');

# BROKEN: empty field object
SELECT audit_log_filter_set_filter('filter_broken_emptyField', '{"filter": { "class": [
  { "name": "table_access",
      "event": {
        "name": [ "read" ],
        "log": {
          "field": { }
        }
      }
  }
] } }');

# ---------------------------------------------------------------
# Filters validating individual general event field support
# Values match documented field types as-is.
# ---------------------------------------------------------------

# general_error_code: integer — event status (0 = OK)
SELECT audit_log_filter_set_filter('filter_gen_errorCode', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_error_code", "value": 0 }
        }
      }
  }
] } }');

# general_thread_id: unsigned integer — connection/thread ID
SELECT audit_log_filter_set_filter('filter_gen_threadId', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_thread_id", "value": 1 }
        }
      }
  }
] } }');

# general_user.str: string
SELECT audit_log_filter_set_filter('filter_gen_userStr', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_user.str", "value": "root[root] @ localhost [127.0.0.1]" }
        }
      }
  }
] } }');

# general_user.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_gen_userLen', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_user.length", "value": 33 }
        }
      }
  }
] } }');

# general_command.str: string
SELECT audit_log_filter_set_filter('filter_gen_cmdStr', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_command.str", "value": "Query" }
        }
      }
  }
] } }');

# general_command.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_gen_cmdLen', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_command.length", "value": 5 }
        }
      }
  }
] } }');

# general_query.str: string
SELECT audit_log_filter_set_filter('filter_gen_queryStr', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_query.str", "value": "SELECT 1" }
        }
      }
  }
] } }');

# general_query.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_gen_queryLen', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_query.length", "value": 8 }
        }
      }
  }
] } }');

# general_host.str: string
SELECT audit_log_filter_set_filter('filter_gen_hostStr', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_host.str", "value": "localhost" }
        }
      }
  }
] } }');

# general_host.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_gen_hostLen', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_host.length", "value": 9 }
        }
      }
  }
] } }');

# general_sql_command.str: string
SELECT audit_log_filter_set_filter('filter_gen_sqlCmdStr', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_sql_command.str", "value": "select" }
        }
      }
  }
] } }');

# general_sql_command.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_gen_sqlCmdLen', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_sql_command.length", "value": 6 }
        }
      }
  }
] } }');

# general_external_user.str: string
SELECT audit_log_filter_set_filter('filter_gen_extUserStr', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_external_user.str", "value": "" }
        }
      }
  }
] } }');

# general_external_user.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_gen_extUserLen', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_external_user.length", "value": 0 }
        }
      }
  }
] } }');

# general_ip.str: string
SELECT audit_log_filter_set_filter('filter_gen_ipStr', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_ip.str", "value": "127.0.0.1" }
        }
      }
  }
] } }');

# general_ip.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_gen_ipLen', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_ip.length", "value": 9 }
        }
      }
  }
] } }');

# ---------------------------------------------------------------
# Combined filter: all general fields using "and"
# ---------------------------------------------------------------

SELECT audit_log_filter_set_filter('filter_gen_allFields', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "and": [
            { "field": { "name": "general_error_code", "value": 0 } },
            { "field": { "name": "general_thread_id", "value": 1 } },
            { "field": { "name": "general_user.str", "value": "root[root] @ localhost [127.0.0.1]" } },
            { "field": { "name": "general_user.length", "value": 33 } },
            { "field": { "name": "general_command.str", "value": "Query" } },
            { "field": { "name": "general_command.length", "value": 5 } },
            { "field": { "name": "general_query.str", "value": "SELECT 1" } },
            { "field": { "name": "general_query.length", "value": 8 } },
            { "field": { "name": "general_host.str", "value": "localhost" } },
            { "field": { "name": "general_host.length", "value": 9 } },
            { "field": { "name": "general_sql_command.str", "value": "select" } },
            { "field": { "name": "general_sql_command.length", "value": 6 } },
            { "field": { "name": "general_external_user.str", "value": "" } },
            { "field": { "name": "general_external_user.length", "value": 0 } },
            { "field": { "name": "general_ip.str", "value": "127.0.0.1" } },
            { "field": { "name": "general_ip.length", "value": 9 } }
          ]
        }
      }
  }
] } }');

# ---------------------------------------------------------------
# Combined filter: all general fields using "or"
# ---------------------------------------------------------------

SELECT audit_log_filter_set_filter('filter_gen_anyField', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "or": [
            { "field": { "name": "general_error_code", "value": 0 } },
            { "field": { "name": "general_thread_id", "value": 1 } },
            { "field": { "name": "general_user.str", "value": "root[root] @ localhost [127.0.0.1]" } },
            { "field": { "name": "general_user.length", "value": 33 } },
            { "field": { "name": "general_command.str", "value": "Query" } },
            { "field": { "name": "general_command.length", "value": 5 } },
            { "field": { "name": "general_query.str", "value": "SELECT 1" } },
            { "field": { "name": "general_query.length", "value": 8 } },
            { "field": { "name": "general_host.str", "value": "localhost" } },
            { "field": { "name": "general_host.length", "value": 9 } },
            { "field": { "name": "general_sql_command.str", "value": "select" } },
            { "field": { "name": "general_sql_command.length", "value": 6 } },
            { "field": { "name": "general_external_user.str", "value": "" } },
            { "field": { "name": "general_external_user.length", "value": 0 } },
            { "field": { "name": "general_ip.str", "value": "127.0.0.1" } },
            { "field": { "name": "general_ip.length", "value": 9 } }
          ]
        }
      }
  }
] } }');

# ---------------------------------------------------------------
# Broken filters: expected to fail at set_filter time or behave
# incorrectly — useful for negative/validation testing
# ---------------------------------------------------------------

# BROKEN: wrong type — string value for integer field general_error_code
SELECT audit_log_filter_set_filter('filter_broken_gen_errorCode_str', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_error_code", "value": "0" }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field general_thread_id
SELECT audit_log_filter_set_filter('filter_broken_gen_threadId_str', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_thread_id", "value": "1" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field general_user.str
SELECT audit_log_filter_set_filter('filter_broken_gen_userStr_int', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_user.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field general_user.length
SELECT audit_log_filter_set_filter('filter_broken_gen_userLen_str', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_user.length", "value": "33" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field general_command.str
SELECT audit_log_filter_set_filter('filter_broken_gen_cmdStr_int', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_command.str", "value": 99 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field general_command.length
SELECT audit_log_filter_set_filter('filter_broken_gen_cmdLen_str', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_command.length", "value": "5" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field general_query.str
SELECT audit_log_filter_set_filter('filter_broken_gen_queryStr_int', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_query.str", "value": 77 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field general_query.length
SELECT audit_log_filter_set_filter('filter_broken_gen_queryLen_str', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_query.length", "value": "8" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field general_host.str
SELECT audit_log_filter_set_filter('filter_broken_gen_hostStr_int', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_host.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field general_host.length
SELECT audit_log_filter_set_filter('filter_broken_gen_hostLen_str', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_host.length", "value": "9" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field general_sql_command.str
SELECT audit_log_filter_set_filter('filter_broken_gen_sqlCmdStr_int', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_sql_command.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field general_sql_command.length
SELECT audit_log_filter_set_filter('filter_broken_gen_sqlCmdLen_str', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_sql_command.length", "value": "6" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field general_external_user.str
SELECT audit_log_filter_set_filter('filter_broken_gen_extUserStr_int', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_external_user.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field general_external_user.length
SELECT audit_log_filter_set_filter('filter_broken_gen_extUserLen_str', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_external_user.length", "value": "0" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field general_ip.str
SELECT audit_log_filter_set_filter('filter_broken_gen_ipStr_int', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_ip.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field general_ip.length
SELECT audit_log_filter_set_filter('filter_broken_gen_ipLen_str', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_ip.length", "value": "9" }
        }
      }
  }
] } }');

# BROKEN: nonexistent field name
SELECT audit_log_filter_set_filter('filter_broken_gen_badField', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "NONEXISTENT.str", "value": "x" }
        }
      }
  }
] } }');

# BROKEN: field from wrong class (connection_type belongs to "connection", not "general")
SELECT audit_log_filter_set_filter('filter_broken_gen_wrongClass', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "connection_type", "value": 1 }
        }
      }
  }
] } }');

# BROKEN: missing "value" key in field object
SELECT audit_log_filter_set_filter('filter_broken_gen_noValue', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_command.str" }
        }
      }
  }
] } }');

# BROKEN: missing "name" key in field object
SELECT audit_log_filter_set_filter('filter_broken_gen_noName', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "value": "Query" }
        }
      }
  }
] } }');

# BROKEN: null value
SELECT audit_log_filter_set_filter('filter_broken_gen_nullValue', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_command.str", "value": null }
        }
      }
  }
] } }');

# BROKEN: boolean value
SELECT audit_log_filter_set_filter('filter_broken_gen_boolValue', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_thread_id", "value": true }
        }
      }
  }
] } }');

# BROKEN: negative value for unsigned integer field general_thread_id
SELECT audit_log_filter_set_filter('filter_broken_gen_threadId_neg', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_thread_id", "value": -1 }
        }
      }
  }
] } }');

# BROKEN: float value for integer field general_error_code
SELECT audit_log_filter_set_filter('filter_broken_gen_errorCode_float', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_error_code", "value": 1.5 }
        }
      }
  }
] } }');

# BROKEN: array value for field
SELECT audit_log_filter_set_filter('filter_broken_gen_arrayValue', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { "name": "general_command.str", "value": ["Query", "Execute"] }
        }
      }
  }
] } }');

# BROKEN: empty field object
SELECT audit_log_filter_set_filter('filter_broken_gen_emptyField', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "field": { }
        }
      }
  }
] } }');

# ---------------------------------------------------------------
# Broken multi-field filters: first field valid, second broken
# ---------------------------------------------------------------

# BROKEN: nonexistent field name after valid field
SELECT audit_log_filter_set_filter('filter_broken_gen_and_badField', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "and": [
            { "field": { "name": "general_error_code", "value": 0 } },
            { "field": { "name": "NONEXISTENT.str", "value": "x" } }
          ]
        }
      }
  }
] } }');

# BROKEN: field from wrong class after valid field (connection_type belongs to "connection")
SELECT audit_log_filter_set_filter('filter_broken_gen_and_wrongClass', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "and": [
            { "field": { "name": "general_error_code", "value": 0 } },
            { "field": { "name": "connection_type", "value": 1 } }
          ]
        }
      }
  }
] } }');

# BROKEN: integer value for string field after valid field
SELECT audit_log_filter_set_filter('filter_broken_gen_and_strAsInt', '{"filter": { "class": [
  { "name": "general",
      "event": {
        "name": "status",
        "log": {
          "and": [
            { "field": { "name": "general_error_code", "value": 0 } },
            { "field": { "name": "general_command.str", "value": 42 } }
          ]
        }
      }
  }
] } }');

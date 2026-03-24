# ---------------------------------------------------------------
# Filters validating individual connection event field support
# Values match documented field types as-is.
# ---------------------------------------------------------------

# status: integer — event status (0 = OK)
SELECT audit_log_filter_set_filter('filter_con_status', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "status", "value": 0 }
        }
      }
  }
] } }');

# connection_id: unsigned integer
SELECT audit_log_filter_set_filter('filter_con_connId', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_id", "value": 1 }
        }
      }
  }
] } }');

# user.str: string
SELECT audit_log_filter_set_filter('filter_con_userStr', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "user.str", "value": "root" }
        }
      }
  }
] } }');

# user.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_con_userLen', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "user.length", "value": 4 }
        }
      }
  }
] } }');

# priv_user.str: string
SELECT audit_log_filter_set_filter('filter_con_privUserStr', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "priv_user.str", "value": "root" }
        }
      }
  }
] } }');

# priv_user.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_con_privUserLen', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "priv_user.length", "value": 4 }
        }
      }
  }
] } }');

# external_user.str: string
SELECT audit_log_filter_set_filter('filter_con_extUserStr', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "external_user.str", "value": "" }
        }
      }
  }
] } }');

# external_user.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_con_extUserLen', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "external_user.length", "value": 0 }
        }
      }
  }
] } }');

# proxy_user.str: string
SELECT audit_log_filter_set_filter('filter_con_proxyUserStr', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "proxy_user.str", "value": "" }
        }
      }
  }
] } }');

# proxy_user.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_con_proxyUserLen', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "proxy_user.length", "value": 0 }
        }
      }
  }
] } }');

# host.str: string
SELECT audit_log_filter_set_filter('filter_con_hostStr', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "host.str", "value": "localhost" }
        }
      }
  }
] } }');

# host.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_con_hostLen', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "host.length", "value": 9 }
        }
      }
  }
] } }');

# ip.str: string
SELECT audit_log_filter_set_filter('filter_con_ipStr', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "ip.str", "value": "127.0.0.1" }
        }
      }
  }
] } }');

# ip.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_con_ipLen', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "ip.length", "value": 9 }
        }
      }
  }
] } }');

# database.str: string
SELECT audit_log_filter_set_filter('filter_con_dbStr', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "database.str", "value": "test" }
        }
      }
  }
] } }');

# database.length: unsigned integer
SELECT audit_log_filter_set_filter('filter_con_dbLen', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "database.length", "value": 4 }
        }
      }
  }
] } }');

# connection_type: integer
# 0=undefined, 1=tcp/ip, 2=socket, 3=named_pipe, 4=ssl, 5=shared_memory
SELECT audit_log_filter_set_filter('filter_con_connType', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": 1 }
        }
      }
  }
] } }');

# connection_type: "::undefined" (string alias for 0)
SELECT audit_log_filter_set_filter('filter_con_connType_undefined', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::undefined" }
        }
      }
  }
] } }');

# connection_type: "::tcp/ip" (string alias for 1)
SELECT audit_log_filter_set_filter('filter_con_connType_tcpip', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::tcp/ip" }
        }
      }
  }
] } }');

# connection_type: "::socket" (string alias for 2)
SELECT audit_log_filter_set_filter('filter_con_connType_socket', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::socket" }
        }
      }
  }
] } }');

# connection_type: "::named_pipe" (string alias for 3)
SELECT audit_log_filter_set_filter('filter_con_connType_namedPipe', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::named_pipe" }
        }
      }
  }
] } }');

# connection_type: "::ssl" (string alias for 4)
SELECT audit_log_filter_set_filter('filter_con_connType_ssl', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::ssl" }
        }
      }
  }
] } }');

# connection_type: "::shared_memory" (string alias for 5)
SELECT audit_log_filter_set_filter('filter_con_connType_sharedMem', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::shared_memory" }
        }
      }
  }
] } }');

# ---------------------------------------------------------------
# Combined filter: all connection fields using "and"
# ---------------------------------------------------------------

SELECT audit_log_filter_set_filter('filter_con_allFields', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "and": [
            { "field": { "name": "status", "value": 0 } },
            { "field": { "name": "connection_id", "value": 1 } },
            { "field": { "name": "user.str", "value": "root" } },
            { "field": { "name": "user.length", "value": 4 } },
            { "field": { "name": "priv_user.str", "value": "root" } },
            { "field": { "name": "priv_user.length", "value": 4 } },
            { "field": { "name": "external_user.str", "value": "" } },
            { "field": { "name": "external_user.length", "value": 0 } },
            { "field": { "name": "proxy_user.str", "value": "" } },
            { "field": { "name": "proxy_user.length", "value": 0 } },
            { "field": { "name": "host.str", "value": "localhost" } },
            { "field": { "name": "host.length", "value": 9 } },
            { "field": { "name": "ip.str", "value": "127.0.0.1" } },
            { "field": { "name": "ip.length", "value": 9 } },
            { "field": { "name": "database.str", "value": "test" } },
            { "field": { "name": "database.length", "value": 4 } },
            { "field": { "name": "connection_type", "value": 1 } }
          ]
        }
      }
  }
] } }');

# ---------------------------------------------------------------
# Combined filter: all connection fields using "or"
# ---------------------------------------------------------------

SELECT audit_log_filter_set_filter('filter_con_anyField', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "or": [
            { "field": { "name": "status", "value": 0 } },
            { "field": { "name": "connection_id", "value": 1 } },
            { "field": { "name": "user.str", "value": "root" } },
            { "field": { "name": "user.length", "value": 4 } },
            { "field": { "name": "priv_user.str", "value": "root" } },
            { "field": { "name": "priv_user.length", "value": 4 } },
            { "field": { "name": "external_user.str", "value": "" } },
            { "field": { "name": "external_user.length", "value": 0 } },
            { "field": { "name": "proxy_user.str", "value": "" } },
            { "field": { "name": "proxy_user.length", "value": 0 } },
            { "field": { "name": "host.str", "value": "localhost" } },
            { "field": { "name": "host.length", "value": 9 } },
            { "field": { "name": "ip.str", "value": "127.0.0.1" } },
            { "field": { "name": "ip.length", "value": 9 } },
            { "field": { "name": "database.str", "value": "test" } },
            { "field": { "name": "database.length", "value": 4 } },
            { "field": { "name": "connection_type", "value": 1 } }
          ]
        }
      }
  }
] } }');

# ---------------------------------------------------------------
# Broken filters: expected to fail at set_filter time or behave
# incorrectly — useful for negative/validation testing
# ---------------------------------------------------------------

# BROKEN: wrong type — string value for integer field status
SELECT audit_log_filter_set_filter('filter_broken_con_status_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "status", "value": "0" }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field connection_id
SELECT audit_log_filter_set_filter('filter_broken_con_connId_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_id", "value": "1" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field user.str
SELECT audit_log_filter_set_filter('filter_broken_con_userStr_int', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "user.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field user.length
SELECT audit_log_filter_set_filter('filter_broken_con_userLen_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "user.length", "value": "4" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field priv_user.str
SELECT audit_log_filter_set_filter('filter_broken_con_privUserStr_int', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "priv_user.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field priv_user.length
SELECT audit_log_filter_set_filter('filter_broken_con_privUserLen_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "priv_user.length", "value": "4" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field external_user.str
SELECT audit_log_filter_set_filter('filter_broken_con_extUserStr_int', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "external_user.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field external_user.length
SELECT audit_log_filter_set_filter('filter_broken_con_extUserLen_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "external_user.length", "value": "0" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field proxy_user.str
SELECT audit_log_filter_set_filter('filter_broken_con_proxyUserStr_int', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "proxy_user.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field proxy_user.length
SELECT audit_log_filter_set_filter('filter_broken_con_proxyUserLen_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "proxy_user.length", "value": "0" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field host.str
SELECT audit_log_filter_set_filter('filter_broken_con_hostStr_int', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "host.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field host.length
SELECT audit_log_filter_set_filter('filter_broken_con_hostLen_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "host.length", "value": "9" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field ip.str
SELECT audit_log_filter_set_filter('filter_broken_con_ipStr_int', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "ip.str", "value": 42 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field ip.length
SELECT audit_log_filter_set_filter('filter_broken_con_ipLen_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "ip.length", "value": "9" }
        }
      }
  }
] } }');

# BROKEN: wrong type — integer value for string field database.str
SELECT audit_log_filter_set_filter('filter_broken_con_dbStr_int', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "database.str", "value": 99 }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for unsigned integer field database.length
SELECT audit_log_filter_set_filter('filter_broken_con_dbLen_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "database.length", "value": "4" }
        }
      }
  }
] } }');

# BROKEN: wrong type — string value for integer field connection_type
SELECT audit_log_filter_set_filter('filter_broken_con_connType_str', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "1" }
        }
      }
  }
] } }');

# BROKEN: connection_type invalid "::"-prefixed alias
SELECT audit_log_filter_set_filter('filter_broken_con_connType_invalidAlias', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::invalid" }
        }
      }
  }
] } }');

# BROKEN: connection_type "::TCP/IP" — wrong case
SELECT audit_log_filter_set_filter('filter_broken_con_connType_wrongCase', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::TCP/IP" }
        }
      }
  }
] } }');

# BROKEN: connection_type "::tcpip" — missing slash
SELECT audit_log_filter_set_filter('filter_broken_con_connType_noSlash', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::tcpip" }
        }
      }
  }
] } }');

# BROKEN: connection_type "::named pipe" — space instead of underscore
SELECT audit_log_filter_set_filter('filter_broken_con_connType_space', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::named pipe" }
        }
      }
  }
] } }');

# BROKEN: connection_type "::shared" — truncated alias
SELECT audit_log_filter_set_filter('filter_broken_con_connType_truncated', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "::shared" }
        }
      }
  }
] } }');

# BROKEN: connection_type "socket" — missing "::" prefix
SELECT audit_log_filter_set_filter('filter_broken_con_connType_noPrefix', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": "socket" }
        }
      }
  }
] } }');

# BROKEN: connection_type out-of-range integer (6, max valid is 5)
SELECT audit_log_filter_set_filter('filter_broken_con_connType_outOfRange', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": 6 }
        }
      }
  }
] } }');

# BROKEN: connection_type negative integer
SELECT audit_log_filter_set_filter('filter_broken_con_connType_neg', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": -1 }
        }
      }
  }
] } }');

# BROKEN: connection_type float value
SELECT audit_log_filter_set_filter('filter_broken_con_connType_float', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": 1.5 }
        }
      }
  }
] } }');

# BROKEN: connection_type boolean value
SELECT audit_log_filter_set_filter('filter_broken_con_connType_bool', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": true }
        }
      }
  }
] } }');

# BROKEN: connection_type null value
SELECT audit_log_filter_set_filter('filter_broken_con_connType_null', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": null }
        }
      }
  }
] } }');

# BROKEN: connection_type array value
SELECT audit_log_filter_set_filter('filter_broken_con_connType_array', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_type", "value": [0, 1] }
        }
      }
  }
] } }');

# BROKEN: nonexistent field name
SELECT audit_log_filter_set_filter('filter_broken_con_badField', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "NONEXISTENT.str", "value": "x" }
        }
      }
  }
] } }');

# BROKEN: field from wrong class (general_command.str belongs to "general", not "connection")
SELECT audit_log_filter_set_filter('filter_broken_con_wrongClass', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "general_command.str", "value": "Query" }
        }
      }
  }
] } }');

# BROKEN: missing "value" key in field object
SELECT audit_log_filter_set_filter('filter_broken_con_noValue', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "user.str" }
        }
      }
  }
] } }');

# BROKEN: missing "name" key in field object
SELECT audit_log_filter_set_filter('filter_broken_con_noName', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "value": "root" }
        }
      }
  }
] } }');

# BROKEN: null value
SELECT audit_log_filter_set_filter('filter_broken_con_nullValue', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "user.str", "value": null }
        }
      }
  }
] } }');

# BROKEN: boolean value
SELECT audit_log_filter_set_filter('filter_broken_con_boolValue', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_id", "value": true }
        }
      }
  }
] } }');

# BROKEN: negative value for unsigned integer field connection_id
SELECT audit_log_filter_set_filter('filter_broken_con_connId_neg', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "connection_id", "value": -1 }
        }
      }
  }
] } }');

# BROKEN: float value for integer field status
SELECT audit_log_filter_set_filter('filter_broken_con_status_float', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "status", "value": 1.5 }
        }
      }
  }
] } }');

# BROKEN: array value for field
SELECT audit_log_filter_set_filter('filter_broken_con_arrayValue', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "field": { "name": "user.str", "value": ["root", "admin"] }
        }
      }
  }
] } }');

# BROKEN: empty field object
SELECT audit_log_filter_set_filter('filter_broken_con_emptyField', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
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
SELECT audit_log_filter_set_filter('filter_broken_con_and_badField', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "and": [
            { "field": { "name": "status", "value": 0 } },
            { "field": { "name": "NONEXISTENT.str", "value": "x" } }
          ]
        }
      }
  }
] } }');

# BROKEN: field from wrong class after valid field (general_command.str belongs to "general")
SELECT audit_log_filter_set_filter('filter_broken_con_and_wrongClass', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "and": [
            { "field": { "name": "status", "value": 0 } },
            { "field": { "name": "general_command.str", "value": "Query" } }
          ]
        }
      }
  }
] } }');

# BROKEN: integer value for string field after valid field
SELECT audit_log_filter_set_filter('filter_broken_con_and_strAsInt', '{"filter": { "class": [
  { "name": "connection",
      "event": {
        "name": [ "connect", "change_user", "disconnect" ],
        "log": {
          "and": [
            { "field": { "name": "status", "value": 0 } },
            { "field": { "name": "user.str", "value": 42 } }
          ]
        }
      }
  }
] } }');

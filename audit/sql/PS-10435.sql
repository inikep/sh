SELECT audit_log_filter_set_filter('log_query_digest1', '
{
  "filter": {
    "class": {
      "name": "general",
      "event": {
        "name": "status",
        "print": {
          "field": {
            "name": "general_query.str",
            "print": false,
            "replace": {
              "function": {
                "name": "query_digest"
              }
            }
          }
        }
      }
    }
  }
}');

SELECT audit_log_filter_set_filter('log_query_digest2', '
{
  "filter": {
    "class": {
      "name": "general",
      "event": {
        "name": "status",
        "print": {
          "field": {
            "name": "general_query.str",
            "print": {
              "not": {
                "function": {
                  "name": "query_digest",
                  "args": "SELECT ?"
                }
              }
            },
            "replace": {
              "function": {
                "name": "query_digest"
              }
            }
          }
        }
      }
    }
  }
}');

SELECT audit_log_filter_set_filter('log_query_digest3', '
{
  "filter": {
    "class": {
      "name": "general",
      "event": {
        "name": "status",
        "print": {
          "field": {
            "name": "general_query.str",
            "print": {
              "function": {
                "name": "query_digest",
                "args": "SELECT ?"
                }
            },
            "replace": {
              "function": {
                "name": "query_digest"
              }
            }
          }
        }
      }
    }
  }
}');


SELECT audit_log_filter_set_filter('log_query_digest3_array', '
{
  "filter": {
    "class": {
      "name": "general",
      "event": {
        "name": "status",
        "print": {
          "field": {
            "name": "general_query.str",
            "print": {
              "function": {
                "name": "query_digest",
                "args": [{"string": {"string": "SELECT ?"}}]
                }
            },
            "replace": {
              "function": {
                "name": "query_digest"
              }
            }
          }
        }
      }
    }
  }
}');

SELECT audit_log_filter_set_user('%', 'log_query_digest2');

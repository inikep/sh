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
#SELECT audit_log_filter_set_user('%', 'filter_none');

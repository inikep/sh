percona-udf (d9cb6086e414): three standalone UDF libraries -> one component_percona_udf.
- Sources and tests had a single pre-conversion version: replace_if.py per file, moves at their own introduction (@sources commit, @tests commit).
- percona_udf.cc/.h added at the sources' introduction with --add; include/mysqlpp/udf_registration.hpp added there too (it first appeared 10 commits later).
- pkg_transform.py: packaging/postinst/plugin.defs rules, anchored on list end markers.

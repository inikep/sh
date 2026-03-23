CREATE DATABASE test;
USE test;
CREATE TABLE tt_4 (c0 CHAR(17), c1 CHAR(24), i2 INT AUTO_INCREMENT, INDEX tt_4i0(i2, c0)  );
INSERT INTO tt_4 (c0, c1, i2) VALUES("U7w45sTTdfPpCM7U", 'YcRhRexsJsO', NULL), ('', 'G', NULL), ('', 'xZhQojs1qw', NULL), ('3rrO5flgjyXoSbYf', 'T8EldiljdnLKdXPQ', NULL), ('nMWe', 'k1hPHZc', NULL);
SELECT * FROM tt_4;
DROP TABLE tt_4;
-- SELECT audit_log_filter_remove_filter('filter3');

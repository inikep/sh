USE test;

-- Table with a single CHAR column
CREATE TABLE tt_multilang (
  text_value CHAR(30) CHARACTER SET utf8mb4
);

-- Insert words in different languages
INSERT INTO tt_multilang (text_value) VALUES
('zażółć gęślą'),   -- Polish
('привет'),          -- Russian
('你好'),             -- Chinese
('こんにちは'),       -- Japanese
('안녕하세요'),       -- Korean
('hello');           -- English

-- Check results
SELECT * FROM tt_multilang;

-- Cleanup
DROP TABLE tt_multilang;

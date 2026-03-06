USE test;

set names cp1250;
create table t1 (a varchar(64) collate cp1250_czech_cs NOT NULL, primary key(a));
insert into t1 values("cp1250-ááèè¿æ¹œó³ñ");

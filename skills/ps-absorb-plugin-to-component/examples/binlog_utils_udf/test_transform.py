#!/usr/bin/env python3
import sys,re
kind=sys.argv[1]; s=sys.stdin.read()
RR='--replace_result $BINLOG_UTILS_UDF_LIB BINLOG_UTILS_UDF_LIB\n'
if kind=='test':
    old=('--echo *** checking if UDF works without loading the plugin\n'+RR+
         'eval CREATE FUNCTION get_last_gtid_from_binlog RETURNS STRING SONAME "$BINLOG_UTILS_UDF_LIB";\n'
         '--replace_result $binlog_file_name <binlog_file_name>\n--error ER_CANT_INITIALIZE_UDF\n'
         "eval SELECT get_last_gtid_from_binlog('$binlog_file_name');\nDROP FUNCTION get_last_gtid_from_binlog;\n")
    new=('--echo *** checking if UDF works without loading the plugin\n'
         '--replace_result $binlog_file_name <binlog_file_name>\n--error ER_SP_DOES_NOT_EXIST\n'
         "eval SELECT get_last_gtid_from_binlog('$binlog_file_name');\n\nINSTALL COMPONENT 'file://component_binlog_utils_udf';\n")
    assert s.count(old)==1; s=s.replace(old,new)
    s,n=re.subn(re.escape(RR)+r"eval INSTALL PLUGIN binlog_utils_udf SONAME '\$BINLOG_UTILS_UDF_LIB';\n",'',s); assert n==1
    s,n=re.subn(re.escape(RR)+r'eval CREATE FUNCTION [a-z_]+ RETURNS [A-Z]+ SONAME "\$BINLOG_UTILS_UDF_LIB";\n','',s); assert n>=1
    L=s.split('\n'); out=[]
    for i,l in enumerate(L):
        if re.fullmatch(r'DROP FUNCTION [a-z_]+;',l):
            if out and out[-1]=='}' and i+2<len(L) and L[i+1]=='' and L[i+2]=='--echo': out.append('')
            continue
        out.append(l)
    s='\n'.join(out)
    s,n=re.subn(r'(?:'+re.escape(RR)+r')?UNINSTALL PLUGIN binlog_utils_udf;\n',"UNINSTALL COMPONENT 'file://component_binlog_utils_udf';\n",s); assert n==1
else:
    old=('*** checking if UDF works without loading the plugin\n'
         'CREATE FUNCTION get_last_gtid_from_binlog RETURNS STRING SONAME "BINLOG_UTILS_UDF_LIB";\n'
         "SELECT get_last_gtid_from_binlog('<binlog_file_name>');\n"
         "ERROR HY000: Can't initialize function 'get_last_gtid_from_binlog'; This function requires binlog_utils_udf plugin which is not installed.\n"
         'DROP FUNCTION get_last_gtid_from_binlog;\n')
    new=('*** checking if UDF works without loading the plugin\n'
         "SELECT get_last_gtid_from_binlog('<binlog_file_name>');\n"
         'ERROR 42000: FUNCTION test.get_last_gtid_from_binlog does not exist\n'
         "INSTALL COMPONENT 'file://component_binlog_utils_udf';\n")
    assert s.count(old)==1; s=s.replace(old,new)
    s,n=re.subn(r"INSTALL PLUGIN binlog_utils_udf SONAME 'BINLOG_UTILS_UDF_LIB';\n",'',s); assert n==1
    s,n=re.subn(r'CREATE FUNCTION [a-z_]+ RETURNS [A-Z]+ SONAME "BINLOG_UTILS_UDF_LIB";\n','',s); assert n>=1
    s,n=re.subn(r'DROP FUNCTION [a-z_]+;\n','',s); assert n>=1
    s,n=re.subn(r'UNINSTALL PLUGIN binlog_utils_udf;\n',"UNINSTALL COMPONENT 'file://component_binlog_utils_udf';\n",s); assert n==1
sys.stdout.write(s)

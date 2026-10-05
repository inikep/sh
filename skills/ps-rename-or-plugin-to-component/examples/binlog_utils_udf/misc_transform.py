#!/usr/bin/env python3
import sys,re
kind=sys.argv[1]; s=sys.stdin.read()
if kind=='defs':
    L=s.split('\n'); out=[]; pos=None; hasno=None
    for l in L:
        if re.match(r'^binlog_utils_udf +plugin_output_directory ',l):
            assert l.endswith('BINLOG_UTILS_UDF_LIB'); hasno=' no ' in l; pos=len(out); continue
        out.append(l)
    assert pos is not None
    new='component_binlog_utils_udf          plugin_output_directory  '+('no  ' if hasno else '')+'BINLOG_UTILS_UDF_LIB'
    pi=[i for i,l in enumerate(out) if l.startswith('procfs ')]
    if pi: out.insert(pi[0]+1,new)
    else: out.insert(pos,new)
    s='\n'.join(out)
elif kind=='pkg':
    n0=s.count('binlog_utils_udf.so')
    s=re.sub(r'(plugin/(?:debug/)?)binlog_utils_udf\.so',r'\1component_binlog_utils_udf.so',s)
    assert n0==2 and s.count('component_binlog_utils_udf.so')==2
sys.stdout.write(s)

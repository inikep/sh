#!/bin/bash
# ccheck.sh LABEL : configure (if needed) and build only the component in $W/bld from $W/wt;
# also fail on undefined audit_log_filter symbols (a MODULE link does not report them)
W=/data/ps-replay-vps-8.1.0-build/alf; L=$W/logs/ccheck-$1.log; WT=${WT:-$W/wt}; BLD=${BLD:-$W/bld}; mkdir -p $W/logs $BLD
FLAGS=$(python3 -c "import sys; sys.path.insert(0,'/home/przemek/.agents/skills/ps-replay+make-buildable/scripts'); import ps_replay_build as b; print(' '.join(b.DEFAULT_CMAKE_FLAGS))")
cd $BLD
{ CC=gcc-9 CXX=g++-9 cmake $WT -GNinja $FLAGS -UWITH_EDITLINE > /dev/null 2>&1 || { echo CMAKE_FAIL; exit 3; }
  JOBS=$(( $(nproc) * 3 / 4 )); [ $JOBS -gt 80 ] && JOBS=80; ninja -j$JOBS component_audit_log_filter; } > $L 2>&1
rc=$?
if [ $rc = 0 ]; then
  U=$(nm -uC plugin_output_directory/component_audit_log_filter.so | grep 'audit_log_filter::')
  [ -n "$U" ] && { echo "UNDEFINED:"; echo "$U"; } | tee -a $L && rc=4
fi
echo "ccheck $1 rc=$rc log=$L"; exit $rc

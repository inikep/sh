#!/bin/bash
# usage: build_commit.sh WORKTREE BUILDDIR COMMIT [TARGET] [SO_NAMESPACE]
# Checks COMMIT out in WORKTREE (created if missing, submodules initialised), configures
# BUILDDIR and builds TARGET (default: everything). With SO_NAMESPACE (e.g. audit_log_filter)
# the built component .so must not have undefined symbols in that namespace (a MODULE link
# does not report them). Jobs: 3/4 of the cores, at most 80; export JOBS=N to override
# (split the budget when several builds run at once). Extra cmake flags: $CMAKE_FLAGS.
set -u
WT=$1 BLD=$2 C=$3 TARGET=${4:-} NS=${5:-}
if [ -z "${JOBS:-}" ]; then JOBS=$(( $(nproc) * 3 / 4 )); [ $JOBS -gt 80 ] && JOBS=80; fi
[ -d "$WT" ] || git worktree add -q --detach "$WT" "$C" || exit 2
git -C "$WT" checkout -q --detach -f "$C" && git -C "$WT" clean -qfdx -- components plugin mysql-test/suite || exit 2
# only gitlinks present in this commit's tree (.gitmodules may list more); rocksdb is not built
SUBS=$(git -C "$WT" ls-tree -r HEAD | awk '$1 == "160000" && $4 !~ /rocksdb/ {print $4}')
[ -z "$SUBS" ] || git -C "$WT" submodule update --init -q -- $SUBS || exit 2
mkdir -p "$BLD" && cd "$BLD" || exit 2
# -UWITH_EDITLINE: a cache configured at another commit may hold a conflicting setting
cmake "$WT" -GNinja ${CMAKE_FLAGS:-} -UWITH_EDITLINE > cmake.log 2>&1 || { echo "CMAKE_FAIL (see $BLD/cmake.log)"; exit 3; }
ninja -j$JOBS $TARGET > ninja.log 2>&1 || { grep -m5 -A3 'error:\|FAILED:' ninja.log; exit 1; }
if [ -n "$NS" ]; then
  so=$(find plugin_output_directory -name "component_$NS.so" | head -1)
  [ -n "$so" ] || { echo "component_$NS.so not built"; exit 4; }
  U=$(nm -uC "$so" | grep "$NS::")
  [ -n "$U" ] && { echo "UNDEFINED in $so:"; echo "$U"; exit 4; }
fi
echo "build ok: $(git -C "$WT" log -1 --format='%h %s' | cut -c1-80) (-j$JOBS)"

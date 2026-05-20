#!/bin/bash
# probe.sh - Tentative cherry-pick + build. Always rolls back. Prints TSV:
#   <sha>\t<n_conflicts>\t<n_build_error>\t<subject>
#
# Use to fingerprint each commit in remaining_commits without changing $OUTPUT_NAME.
# Required env: cd into the worktree root before running.
# Required vars: BUILD_DIR (default ./build).

set -u
SHA="$1"
BUILD_DIR="${BUILD_DIR:-./build}"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

PRE=$(git rev-parse HEAD)
subj=$(git log -1 --format='%s' "$SHA" | head -c 65)
n_conflicts=0
n_build_error=0

out=$(git cherry-pick --allow-empty --keep-redundant-commits "$SHA" 2>&1)
rc=$?
if [ $rc -ne 0 ]; then
  n_conflicts=$(git diff --name-only --diff-filter=U 2>/dev/null | wc -l)
  git cherry-pick --abort 2>/dev/null
  printf "%s\t%d\t%d\t%s\n" "$SHA" "$n_conflicts" 0 "$subj"
  exit
fi

# Clean apply
if [ "$(git rev-parse HEAD)" != "$PRE" ]; then
  if git diff --quiet "$PRE" HEAD; then
    git reset --hard "$PRE" >/dev/null 2>&1
    printf "%s\t%d\t%d\t%s [empty]\n" "$SHA" 0 0 "$subj"
    exit
  fi
  cd "$BUILD_DIR"
  build_out=$(make -j$(( $(nproc) * 3 / 4 )) 2>&1)
  build_rc=$?
  n_build_error=$(printf "%s\n" "$build_out" | "$SCRIPT_DIR/count_build_errors.sh")
  cd - >/dev/null
  git reset --hard "$PRE" >/dev/null 2>&1
fi
printf "%s\t%d\t%d\t%s\n" "$SHA" "$n_conflicts" "$n_build_error" "$subj"

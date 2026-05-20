#!/bin/bash
# try_apply.sh - Cherry-pick + build. Lands on success; on conflict leaves the
# cherry-pick in progress for caller to resolve via CDF; on build failure rolls
# back. Always prints: n_conflicts, n_build_error, n_symbol_pull (caller
# computes), and LANDED/CONFLICT/BUILD-FAIL.
#
# Usage: try_apply.sh <SHA> [BUILD_DIR]
# Exit codes: 0=LANDED  1=CONFLICT (left in cherry-pick state for CDF)
#             2=BUILD-FAIL (rolled back, needs BDF)

set -u
SHA="$1"
BUILD_DIR="${2:-./build}"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PRE=$(git rev-parse HEAD)
subj=$(git log -1 --format='%s' "$SHA" | head -c 65)

out=$(git cherry-pick --allow-empty --keep-redundant-commits "$SHA" 2>&1)
rc=$?

if [ $rc -ne 0 ]; then
  n_conflicts=$(git diff --name-only --diff-filter=U 2>/dev/null | wc -l)
  if [ "$n_conflicts" -eq 0 ] && git diff --quiet && git diff --cached --quiet; then
    git cherry-pick --abort >/dev/null 2>&1 || true
    git commit --allow-empty -C "$SHA" >/dev/null
    printf "[%s] %s\n" "$SHA" "$subj"
    printf "  n_conflicts=0 n_build_error=0 n_symbol_pull=0 -> LANDED (empty) (%s)\n" "$(git rev-parse HEAD)"
    exit 0
  fi
  printf "[%s] %s\n" "$SHA" "$subj"
  printf "  n_conflicts=%d n_build_error=- n_symbol_pull=- -> CONFLICT (cherry-pick in progress)\n" "$n_conflicts"
  echo "Files:"; git diff --name-only --diff-filter=U | sed 's/^/  /'
  exit 1
fi

# Clean cherry-pick — may be empty
if [ "$(git rev-parse HEAD)" = "$PRE" ]; then
  git commit --allow-empty -C "$SHA" >/dev/null
  printf "[%s] %s\n" "$SHA" "$subj"
  printf "  n_conflicts=0 n_build_error=0 n_symbol_pull=0 -> LANDED (empty) (%s)\n" "$(git rev-parse HEAD)"
  exit 0
fi
if git diff --quiet "$PRE" HEAD; then
  printf "[%s] %s\n" "$SHA" "$subj"
  printf "  n_conflicts=0 n_build_error=0 n_symbol_pull=0 -> LANDED (empty) (%s)\n" "$(git rev-parse HEAD)"
  exit 0
fi

# Build
cd "$BUILD_DIR"
build_out=$(make -j$(( $(nproc) * 3 / 4 )) 2>&1)
build_rc=$?
n_build_error=$(printf "%s\n" "$build_out" | "$SCRIPT_DIR/count_build_errors.sh")
cd - >/dev/null

if [ $build_rc -eq 0 ]; then
  printf "[%s] %s\n" "$SHA" "$subj"
  printf "  n_conflicts=0 n_build_error=0 n_symbol_pull=0 -> LANDED (%s)\n" "$(git rev-parse HEAD)"
  exit 0
else
  printf "[%s] %s\n" "$SHA" "$subj"
  printf "  n_conflicts=0 n_build_error=%d n_symbol_pull=- -> BUILD-FAIL (rolling back)\n" "$n_build_error"
  echo "Errors:"
  echo "$build_out" | grep -E "^[^:]*:[0-9]+:[0-9]+: (fatal )?error:|^CMake Error|fatal error:" | sort -u | head -5 | sed 's/^/  /'
  git reset --hard "$PRE" >/dev/null 2>&1
  exit 2
fi

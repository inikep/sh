#!/bin/bash
# Top-level driver. Reads inputs from env or args.
# Usage: SRC_BRANCH=ups-X.Y.Z BASE_BRANCH=mysql-X.Y.Z OUTPUT_BRANCH=ups-X.Y.Z-clean LOG_DIR=/tmp/... ./run.sh
set -e

: "${SRC_BRANCH:?SRC_BRANCH required}"
: "${BASE_BRANCH:?BASE_BRANCH required}"
: "${OUTPUT_BRANCH:?OUTPUT_BRANCH required}"
: "${LOG_DIR:=/tmp/ps-make-clean-${OUTPUT_BRANCH}-logs}"
: "${REPORT_FILE:=/data/sh/utils/reports/ps-make-clean_${OUTPUT_BRANCH}.md}"

mkdir -p "$LOG_DIR" "$(dirname "$REPORT_FILE")"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Sanity
[ -z "$(git status --porcelain)" ] || { echo "Working tree not clean. Abort." >&2; exit 1; }
git merge-base --is-ancestor "$BASE_BRANCH" "$SRC_BRANCH" || {
  echo "$BASE_BRANCH is not an ancestor of $SRC_BRANCH. Abort." >&2; exit 1; }

echo "=== PHASE A: strip transient paths ==="
BASE_BRANCH="$BASE_BRANCH" SRC_BRANCH="$SRC_BRANCH" OUTPUT_BRANCH="$OUTPUT_BRANCH" LOG_DIR="$LOG_DIR" \
  bash "$SCRIPT_DIR/phase-a-strip.sh"

echo "=== PHASE B: small-commit split/squash ==="
BASE_BRANCH="$BASE_BRANCH" SRC_BRANCH="$SRC_BRANCH" OUTPUT_BRANCH="$OUTPUT_BRANCH" LOG_DIR="$LOG_DIR" \
  bash "$SCRIPT_DIR/phase-b-apply.sh"

echo "=== PHASE C: squash related commits ==="
BASE_BRANCH="$BASE_BRANCH" SRC_BRANCH="$SRC_BRANCH" OUTPUT_BRANCH="$OUTPUT_BRANCH" LOG_DIR="$LOG_DIR" \
  bash "$SCRIPT_DIR/phase-c-apply.sh"

# Final null-diff check
diff_lines=$(git diff "$OUTPUT_BRANCH" "$SRC_BRANCH" | wc -l)
final=$(git rev-list --count "$BASE_BRANCH..$OUTPUT_BRANCH")
echo "=== DONE ==="
echo "Final $OUTPUT_BRANCH: $final commits"
echo "Diff vs $SRC_BRANCH: $diff_lines lines"
[ "$diff_lines" -eq 0 ] || { echo "FAIL: non-zero diff vs $SRC_BRANCH" >&2; exit 1; }

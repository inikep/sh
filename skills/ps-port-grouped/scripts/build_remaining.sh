#!/bin/bash
# build_remaining.sh - Compute remaining_commits = input-range commits not yet
# landed in $OUTPUT_NAME. Uses subject-match (not SHA) since cherry-pick changes
# SHAs.
#
# Usage:
#   build_remaining.sh <OUTPUT_BASE> <INPUT_BASE> <INPUT_TIP> [BUILD_CHANGING_TSV]
# Writes SHAs (one per line) to stdout. If BUILD_CHANGING_TSV is given,
# only includes commits with build_changing=1.

set -u
if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  echo "Usage: $0 <OUTPUT_BASE> <INPUT_BASE> <INPUT_TIP> [BUILD_CHANGING_TSV]" >&2
  exit 64
fi

OUTPUT_BASE="$1"
INPUT_BASE="$2"
INPUT_TIP="$3"
BC_TSV="${4:-}"

LANDED_SUBJECTS=$(git log "$OUTPUT_BASE"..HEAD --format='%s')
LANDED_TMP=$(mktemp)
printf '%s\n' "$LANDED_SUBJECTS" > "$LANDED_TMP"

if [ -n "$BC_TSV" ]; then
  BC_TMP=$(mktemp)
  awk -F'\t' '$2==1 {print $1}' "$BC_TSV" > "$BC_TMP"
else
  BC_TMP=""
fi

git rev-list --reverse "$INPUT_BASE".."$INPUT_TIP" | while IFS= read -r sha; do
  subj=$(git log -1 --format='%s' "$sha")
  if grep -qFx "$subj" "$LANDED_TMP"; then
    awk -v s="$subj" 'BEGIN {removed=0} $0 == s && !removed {removed=1; next} {print}' "$LANDED_TMP" > "$LANDED_TMP.next"
    mv "$LANDED_TMP.next" "$LANDED_TMP"
    continue
  fi
  if [ -z "$BC_TMP" ] || grep -qFx "$sha" "$BC_TMP"; then
    echo "$sha"
  fi
done

rm -f "$LANDED_TMP" "${BC_TMP:-}"

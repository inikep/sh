#!/bin/bash
# report_remaining.sh - Print the mandatory pass-end remaining_commits report.
#
# Usage:
#   report_remaining.sh <PASS_LABEL> <REMAINING_SHAS> <COUNTER_STATE_TSV>
#
# REMAINING_SHAS is a file containing one input-range SHA per line, in the
# current pass order. Missing ledger rows are reported as UNTRIED with zero
# counters.

set -eu

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <PASS_LABEL> <REMAINING_SHAS> <COUNTER_STATE_TSV>" >&2
  exit 64
fi

PASS_LABEL="$1"
REMAINING_SHAS="$2"
STATE="$3"

if [ ! -f "$REMAINING_SHAS" ]; then
  echo "remaining SHAs file not found: $REMAINING_SHAS" >&2
  exit 66
fi

count=$(grep -cve '^[[:space:]]*$' "$REMAINING_SHAS" || true)

printf "%s remaining_commits report\n" "$PASS_LABEL"
printf "remaining_commits=%s\n" "$count"
printf "sha\tn_conflicts\tn_build_error\tn_symbol_pull\tstatus\tsubject\n"

while IFS= read -r sha; do
  [ -n "$sha" ] || continue
  if [ -f "$STATE" ]; then
    row=$(awk -F'\t' -v sha="$sha" '$1 == sha { found=$0 } END { if (found) print found }' "$STATE")
  else
    row=""
  fi

  if [ -n "$row" ]; then
    printf "%s\n" "$row"
  else
    subject=$(git log -1 --format='%s' "$sha")
    printf "%s\t0\t0\t0\tUNTRIED\t%s\n" "$sha" "$subject"
  fi
done < "$REMAINING_SHAS"

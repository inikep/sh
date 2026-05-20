#!/bin/bash
# record_attempt.sh - Upsert one real-attempt counter row.
#
# Usage:
#   record_attempt.sh <COUNTER_STATE_TSV> <SHA> <n_conflicts> <n_build_error> <n_symbol_pull> <status>
#
# TSV columns:
#   sha n_conflicts n_build_error n_symbol_pull status subject

set -eu

if [ "$#" -ne 6 ]; then
  echo "Usage: $0 <COUNTER_STATE_TSV> <SHA> <n_conflicts> <n_build_error> <n_symbol_pull> <status>" >&2
  exit 64
fi

STATE="$1"
SHA="$2"
N_CONFLICTS="$3"
N_BUILD_ERROR="$4"
N_SYMBOL_PULL="$5"
STATUS="$6"

mkdir -p "$(dirname "$STATE")"
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

if [ -f "$STATE" ]; then
  awk -F'\t' -v sha="$SHA" '$1 != sha { print }' "$STATE" > "$tmp"
fi

subject=$(git log -1 --format='%s' "$SHA")
printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
  "$SHA" "$N_CONFLICTS" "$N_BUILD_ERROR" "$N_SYMBOL_PULL" "$STATUS" "$subject" >> "$tmp"

mv "$tmp" "$STATE"
trap - EXIT

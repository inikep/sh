#!/bin/bash
# refresh_remaining.sh - Rebuild a remaining_commits SHA file safely.
#
# Usage:
#   refresh_remaining.sh <OUTPUT_BASE> <INPUT_BASE> <INPUT_TIP> <OUT_FILE> [BUILD_CHANGING_TSV] [REMOVED_SHAS_FILE]
#
# Always exits 0 after writing OUT_FILE, even when no commits remain.

set -eu

if [ "$#" -lt 4 ] || [ "$#" -gt 6 ]; then
  echo "Usage: $0 <OUTPUT_BASE> <INPUT_BASE> <INPUT_TIP> <OUT_FILE> [BUILD_CHANGING_TSV] [REMOVED_SHAS_FILE]" >&2
  exit 64
fi

OUTPUT_BASE="$1"
INPUT_BASE="$2"
INPUT_TIP="$3"
OUT_FILE="$4"
BC_TSV="${5:-}"
REMOVED="${6:-}"

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

if [ -n "$BC_TSV" ]; then
  "$(dirname "$0")/build_remaining.sh" "$OUTPUT_BASE" "$INPUT_BASE" "$INPUT_TIP" "$BC_TSV" > "$tmp"
else
  "$(dirname "$0")/build_remaining.sh" "$OUTPUT_BASE" "$INPUT_BASE" "$INPUT_TIP" > "$tmp"
fi

if [ -n "$REMOVED" ] && [ -s "$REMOVED" ]; then
  grep -vxFf "$REMOVED" "$tmp" > "$OUT_FILE" || true
else
  cp "$tmp" "$OUT_FILE"
fi

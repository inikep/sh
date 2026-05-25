#!/bin/bash
# final_snap_report.sh - Summarize the residual diff before final reference snap.
#
# Usage:
#   final_snap_report.sh <REFERENCE> [BASE_COMMIT]
#
# BASE_COMMIT defaults to HEAD. The report separates whitespace-only files from
# semantic residual files and counts diff-check whitespace issues that would be
# introduced by matching REFERENCE.

set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Usage: $0 <REFERENCE> [BASE_COMMIT]" >&2
  exit 64
fi

REFERENCE="$1"
BASE="${2:-HEAD}"

git rev-parse --verify "$REFERENCE^{commit}" >/dev/null
git rev-parse --verify "$BASE^{commit}" >/dev/null

files_tmp=$(mktemp)
numstat_tmp=$(mktemp)
ws_only_tmp=$(mktemp)
check_tmp=$(mktemp)
trap 'rm -f "$files_tmp" "$numstat_tmp" "$ws_only_tmp" "$check_tmp"' EXIT

git diff --name-only "$BASE" "$REFERENCE" > "$files_tmp"
git diff --numstat "$BASE" "$REFERENCE" > "$numstat_tmp"

while IFS= read -r path; do
  [ -n "$path" ] || continue
  if git diff -w --quiet "$BASE" "$REFERENCE" -- "$path"; then
    echo "$path" >> "$ws_only_tmp"
  fi
done < "$files_tmp"

git diff --check "$BASE" "$REFERENCE" > "$check_tmp" || true

total_files=$(grep -cve '^[[:space:]]*$' "$files_tmp" || true)
ws_only_files=$(grep -cve '^[[:space:]]*$' "$ws_only_tmp" || true)
semantic_files=$(( total_files - ws_only_files ))
check_issues=$(grep -Ec ':( trailing whitespace| new blank line at EOF| space before tab)' "$check_tmp" || true)

read -r add del <<EOF
$(awk '
  $1 ~ /^[0-9]+$/ { add += $1 }
  $2 ~ /^[0-9]+$/ { del += $2 }
  END { printf "%d %d", add, del }
' "$numstat_tmp")
EOF

read -r ws_add ws_del <<EOF
$(while IFS= read -r path; do
    [ -n "$path" ] || continue
    awk -v p="$path" -F'\t' '$3 == p && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ { add += $1; del += $2 } END { printf "%d %d\n", add, del }' "$numstat_tmp"
  done < "$ws_only_tmp" |
  awk '{ add += $1; del += $2 } END { printf "%d %d", add, del }')
EOF

printf "final_snap_report base=%s reference=%s\n" "$BASE" "$REFERENCE"
printf "files=%s add=%s del=%s\n" "$total_files" "$add" "$del"
printf "semantic_files=%s whitespace_only_files=%s whitespace_only_add=%s whitespace_only_del=%s\n" \
  "$semantic_files" "$ws_only_files" "$ws_add" "$ws_del"
printf "diff_check_whitespace_issues=%s\n" "$check_issues"

if [ "$ws_only_files" -gt 0 ]; then
  printf "whitespace_only_file_list:\n"
  sed 's/^/  /' "$ws_only_tmp"
fi

if [ "$check_issues" -gt 0 ]; then
  printf "first_diff_check_issues:\n"
  head -n 20 "$check_tmp" | sed 's/^/  /'
fi

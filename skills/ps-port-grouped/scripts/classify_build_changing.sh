#!/bin/bash
# classify_build_changing.sh - For each commit in $INPUT_BASE..$INPUT_TIP,
# decide build_changing=0/1 by examining changed paths.
#
# Usage: classify_build_changing.sh <INPUT_BASE> <INPUT_TIP>
# Output TSV: <sha>\t<bc>\t<n_files>\t<subject>

set -u
BASE="$1"
TIP="$2"

git rev-list --reverse "$BASE".."$TIP" | while IFS= read -r sha; do
  files=$(git diff-tree --no-commit-id --name-only -r "$sha")
  bc=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    base="${f##*/}"
    ext="${f##*.}"
    case "$base" in
      CMakeLists.txt) bc=1; break;;
    esac
    case ".$ext" in
      .h|.c|.cc|.cxx|.cpp|.hh|.hpp|.hxx|.cmake|.i|.ic) bc=1; break;;
    esac
  done <<< "$files"
  subj=$(git log -1 --format='%s' "$sha")
  n_files=$(printf '%s\n' "$files" | grep -c . || true)
  printf '%s\t%d\t%d\t%s\n' "$sha" "$bc" "$n_files" "$subj"
done

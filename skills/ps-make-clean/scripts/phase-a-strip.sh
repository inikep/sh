#!/bin/bash
# Phase A: strip transient paths from every commit in $BASE..$SRC, emit clean branch on $OUTPUT.
# Uses tree-level plumbing (read-tree, update-index --remove, write-tree, commit-tree)
# so binary files and gitlinks are handled correctly. Never invokes diff/apply.
#
# Inputs (env):
#   BASE_BRANCH, SRC_BRANCH, OUTPUT_BRANCH, LOG_DIR
set -e

: "${BASE_BRANCH:?}" "${SRC_BRANCH:?}" "${OUTPUT_BRANCH:?}" "${LOG_DIR:?}"
mkdir -p "$LOG_DIR"

# Compute transient paths
git log --pretty=format: --name-only "$BASE_BRANCH..$SRC_BRANCH" | sort -u | sed '/^$/d' > "$LOG_DIR/touched.txt"
git ls-tree -r --name-only "$SRC_BRANCH"  | sort > "$LOG_DIR/tip.txt"
git ls-tree -r --name-only "$BASE_BRANCH" | sort > "$LOG_DIR/base.txt"
comm -23 "$LOG_DIR/touched.txt" "$LOG_DIR/tip.txt"  > "$LOG_DIR/touched-not-tip.txt"
comm -23 "$LOG_DIR/touched-not-tip.txt" "$LOG_DIR/base.txt" > "$LOG_DIR/transient.txt"

echo "Transient paths: $(wc -l < "$LOG_DIR/transient.txt")"

# Reset OUTPUT_BRANCH to BASE
git checkout -q "$OUTPUT_BRANCH" 2>/dev/null || git checkout -q -b "$OUTPUT_BRANCH" "$BASE_BRANCH"
git reset --hard -q "$BASE_BRANCH"

> "$LOG_DIR/clean-sha-map.tsv"
> "$LOG_DIR/clean-skipped.txt"

SOURCE_SHAS=$(git rev-list --reverse "$BASE_BRANCH..$SRC_BRANCH")
TOTAL=$(echo "$SOURCE_SHAS" | wc -l)

parent_commit=$(git rev-parse HEAD)
parent_tree=$(git rev-parse "$parent_commit^{tree}")
TMP_INDEX=$(mktemp)
MSG=$(mktemp)
trap 'rm -f "$TMP_INDEX" "$MSG"' EXIT

i=0
for sha in $SOURCE_SHAS; do
  i=$((i+1))

  # One git log call for all six identity fields + subject (\x1F = unit sep).
  META=$(git log -1 --format='%an%x1F%ae%x1F%aI%x1F%cn%x1F%ce%x1F%cI%x1F%s' "$sha")
  IFS=$'\x1F' read -r AN AE AD CN CE CD subj <<< "$META"

  # Read $sha's tree into a temp index, batch-remove all transient paths via
  # a single update-index --stdin invocation, write tree.
  GIT_INDEX_FILE="$TMP_INDEX" git read-tree "$sha^{tree}"
  GIT_INDEX_FILE="$TMP_INDEX" git update-index --remove --force-remove --stdin \
    < "$LOG_DIR/transient.txt" 2>/dev/null || true
  new_tree=$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)

  if [ "$new_tree" = "$parent_tree" ]; then
    echo -e "$sha\t-\tempty-after-strip" >> "$LOG_DIR/clean-sha-map.tsv"
    echo "[$i/$TOTAL] SKIP: $sha $subj" >> "$LOG_DIR/clean-skipped.txt"
    continue
  fi

  git log -1 --format=%B "$sha" > "$MSG"

  new_commit=$(GIT_AUTHOR_NAME="$AN" GIT_AUTHOR_EMAIL="$AE" GIT_AUTHOR_DATE="$AD" \
               GIT_COMMITTER_NAME="$CN" GIT_COMMITTER_EMAIL="$CE" GIT_COMMITTER_DATE="$CD" \
               git commit-tree "$new_tree" -p "$parent_commit" -F "$MSG")

  parent_commit="$new_commit"
  parent_tree="$new_tree"
  echo -e "$sha\t$new_commit\tapplied" >> "$LOG_DIR/clean-sha-map.tsv"
done

git update-ref HEAD "$parent_commit"

# Sync worktree with new HEAD. `reset --hard` compares the old index (still at
# $BASE_BRANCH from line 24) against the new HEAD tree and deletes files present
# in BASE but absent at HEAD — which `checkout-index -a -f` would leave as
# untracked and trip up subsequent branch switches in phase B.
git reset --hard -q HEAD

echo "Phase A done. Tip: $(git rev-parse HEAD)"
echo "Applied: $(grep -c $'\tapplied$' "$LOG_DIR/clean-sha-map.tsv")"
echo "Dropped (all-transient): $(grep -c $'\t-\t' "$LOG_DIR/clean-sha-map.tsv")"

# Sanity: null diff with SRC
diff_lines=$(git diff "$OUTPUT_BRANCH" "$SRC_BRANCH" | wc -l)
echo "Diff vs $SRC_BRANCH: $diff_lines lines (must be 0)"
[ "$diff_lines" -eq 0 ] || { echo "PHASE A FAILED: non-zero diff vs $SRC_BRANCH" >&2; exit 1; }

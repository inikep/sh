#!/bin/bash
# usage: verify_rewrite.sh BASE OLD_TIP NEW_TIP DROP_SHA [OLD_PATH...]
# Checks: tip trees equal, count one fewer, DROP not an ancestor, messages/metadata
# identical except the listed differences, no OLD_PATH anywhere in NEW history.
BASE=$1 OLD=$2 NEW=$3 DROP=$(git rev-parse $4); shift 4
echo "tip tree equal: $([ "$(git rev-parse $NEW^{tree})" = "$(git rev-parse $OLD^{tree})" ] && echo yes || echo NO)"
echo "commits: old=$(git rev-list --count $BASE..$OLD) new=$(git rev-list --count $BASE..$NEW)"
git merge-base --is-ancestor $DROP $NEW && echo "DROP STILL ANCESTOR" || echo "drop commit removed: yes"
paste -d' ' <(git rev-list --reverse $BASE..$NEW) <(git rev-list --reverse $BASE..$OLD | grep -v "^$DROP") |
while read n o; do
  cmp -s <(git cat-file commit $n | sed '1,/^$/d') <(git cat-file commit $o | sed '1,/^$/d') || echo "message differs: $(git log -1 --format='%h %s' $n)"
  [ "$(git log -1 --format='%an|%ae|%ad|%cn|%ce|%cd' $n)" = "$(git log -1 --format='%an|%ae|%ad|%cn|%ce|%cd' $o)" ] || echo "metadata differs: $n"
done
for p in "$@"; do n=$(git log --format=%h $BASE..$NEW -- "$p" | wc -l); echo "commits touching old path $p: $n"; done

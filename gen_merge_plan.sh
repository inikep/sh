#!/bin/bash

if [ $# -lt 4 ]; then
  echo usage: $0 [fb-prod1] [fb-prod2] [PS-XXXX] [out-dir]
  exit
fi

FBPROD1=$1
FBPROD2=$2
PS_JIRA=$3
OUTNAME=$4/$2-merge-plan

rm -f $OUTNAME;
rm -f $OUTNAME-markdown;

printf >>$OUTNAME "https://github.com/facebook/mysql-5.6/compare/$FBPROD1...$FBPROD2\n\n"
printf >>$OUTNAME -- "------------------------------------------------------\n"
printf >>$OUTNAME "\nCherry-pick the following commits from \`$FBPROD2\`:\n"

printf >>$OUTNAME-markdown "1. Update rocksdb submodule to [8.5.1](https://github.com/facebook/rocksdb/commit/XXXXXXXXX)\n\n"
printf >>$OUTNAME-markdown "2. Add new MyRocks variables \`aaa\` and \`bbb\`.\n\n"
printf >>$OUTNAME-markdown "3. Cherry-pick the following commits from \`$FBPROD2\`:\n"

i=1
for COMMIT in $(git rev-list --first-parent --topo-order --reverse --abbrev-commit $FBPROD2 ^$FBPROD1)
do
  TITLE=$(git show -s --format=%s $COMMIT)
  TITLE=${TITLE//]/)}
  TITLE=${TITLE//[/(}
  ROCKS_FILES=`git diff --name-only $COMMIT~..$COMMIT | grep rocksdb`
  if [[ "$ROCKS_FILES" != "" ]]; then
     MTR_FILES=$(git diff --name-only $COMMIT~..$COMMIT | grep -P ."\.(result|test)" | cut -f 1 -d '.' | rev | cut -f 1 -d '/' | rev | sort | uniq | tr '\n' ' ')
     if [[ "$MTR_FILES" != "" ]]; then MTR_FILES=${MTR_FILES::-1}; fi
     ROCKS_FILES=`git diff --name-only $COMMIT~..$COMMIT`
     printf >>$OUTNAME "\nCOMMIT $i: $COMMIT $TITLE\n"
     printf >>$OUTNAME -- "------------------------------------------------------\n"
     printf >>$OUTNAME "Upstream commit ID: https://github.com/facebook/mysql-5.6/commit/$COMMIT\n"
     printf >>$OUTNAME "$PS_JIRA: Merge $FBPROD2 (https://jira.percona.com/browse/$PS_JIRA)\n\n"
     printf >>$OUTNAME "Modified MTR files: $MTR_FILES\n\n"
     echo >>$OUTNAME "$ROCKS_FILES"
     echo >>$OUTNAME-markdown "- [$COMMIT $TITLE](https://github.com/facebook/mysql-5.6/commit/$COMMIT)"
     ((i=i+1))
  fi
done

printf >>$OUTNAME "\nSkipped MyRocks commits:\n"
printf >>$OUTNAME-markdown "\n4. Skipped MyRocks commits:\n\n"

printf >>$OUTNAME "\nSkipped upstream commits:\n"
printf >>$OUTNAME-markdown "\n5. Skipped upstream commits:\n"
i=1
for COMMIT in $(git rev-list --first-parent --topo-order --reverse --abbrev-commit $FBPROD2 ^$FBPROD1)
do
  TITLE=$(git show -s --format=%s $COMMIT)
  TITLE=${TITLE//]/)}
  TITLE=${TITLE//[/(}
  ROCKS_FILES=`git diff --name-only $COMMIT~..$COMMIT | grep rocksdb`
  if [[ "$ROCKS_FILES" == "" ]]; then
     #echo >>$OUTNAME "COMMIT $i: $COMMIT $TITLE"
     echo >>$OUTNAME-markdown "- [$COMMIT $TITLE](https://github.com/facebook/mysql-5.6/commit/$COMMIT)"
     ((i=i+1))
  fi
done

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
rm -f $OUTNAME-jira;

printf >>$OUTNAME "https://github.com/facebook/mysql-5.6/compare/$FBPROD1...$FBPROD2\n\n"
printf >>$OUTNAME "fb_prod_skip_commits.sh $FBPROD1 $FBPROD2 $PS_JIRA\n\n"
printf >>$OUTNAME "fb_skip_commit.sh $FBPROD2 $PS_JIRA [commit]\n\n"
printf >>$OUTNAME -- "------------------------------------------------------\n"
printf >>$OUTNAME "Upstream commit ID : fb-mysql-5.6.35/XXXX\n"
printf >>$OUTNAME "$PS_JIRA : Merge $FBPROD2\n"
printf >>$OUTNAME "\n"
printf >>$OUTNAME "This is a NULL cherry-pick to Percona Server 5.7 to create the commit placeholder for the corresponding upstream commit.\n"
printf >>$OUTNAME "Reason: Patch not taken into Percona Server\n"
printf >>$OUTNAME "Reason: Change already applied to source tree through another patch.\n"
printf >>$OUTNAME "\n"
printf >>$OUTNAME "git cherry-pick\n"
printf >>$OUTNAME "git checkout HEAD . ; git status\n"
printf >>$OUTNAME "git rm -f\n"
printf >>$OUTNAME "git cherry-pick --continue\n"
printf >>$OUTNAME "git commit --allow-empty\n"
printf >>$OUTNAME -- "------------------------------------------------------\n"
printf >>$OUTNAME "\nCherry-pick the following commits from \`$FBPROD2\`:\n"

printf >>$OUTNAME-jira "1. Update rocksdb submodule to [XXXXXXXXX Fix build |https://github.com/facebook/rocksdb/commit/XXXXXXXXX] (v5.8-YYYYYYYYY)\n\n"
printf >>$OUTNAME-jira "2. Add new MyRocks variables \`aaa\` and \`bbb\`.\n\n"
printf >>$OUTNAME-jira "3. Cherry-pick the following commits from \`$FBPROD2\`:\n"

i=1
for COMMIT in $(git rev-list --first-parent --topo-order --reverse $FBPROD2 ^$FBPROD1)
do
  TITLE=$(git show -s --format=%s $COMMIT)
  ROCKS_FILES=`git diff --name-only $COMMIT~..$COMMIT | grep rocksdb`
  if [[ "$ROCKS_FILES" != "" ]]; then
     ROCKS_FILES=`git diff --name-only $COMMIT~..$COMMIT`
     printf >>$OUTNAME "\nCOMMIT $i: $COMMIT $TITLE\n"
     printf >>$OUTNAME -- "------------------------------------------------------\n"
     printf >>$OUTNAME "Upstream commit ID : fb-mysql-5.6.35/$COMMIT\n"
     printf >>$OUTNAME "$PS_JIRA : Merge $FBPROD2\n\n"
     echo >>$OUTNAME "$ROCKS_FILES";
     echo >>$OUTNAME-jira "- [$COMMIT $TITLE|https://github.com/facebook/mysql-5.6/commit/$COMMIT]"
     ((i=i+1))
  fi
done

printf >>$OUTNAME "\nNull cherry-picked upstream commits:\n"
printf >>$OUTNAME-jira "\n4. Null cherry-picked upstream commits:\n"
i=1
for COMMIT in $(git rev-list --first-parent --topo-order --reverse $FBPROD2 ^$FBPROD1)
do
  TITLE=$(git show -s --format=%s $COMMIT)
  ROCKS_FILES=`git diff --name-only $COMMIT~..$COMMIT | grep rocksdb`
  if [[ "$ROCKS_FILES" == "" ]]; then
     echo >>$OUTNAME "COMMIT $i: $COMMIT $TITLE"
     echo >>$OUTNAME-jira "- [$COMMIT $TITLE|https://github.com/facebook/mysql-5.6/commit/$COMMIT]"
     ((i=i+1))
  fi
done

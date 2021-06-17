#!/bin/bash

if [ $# -lt 3 ]; then
  echo usage: $0 [COMMIT1] [COMMIT2] [out-dir]
  exit
fi

COMMIT1=$1
COMMIT2=$2
OUTCSV=$3/$(basename $2)_rocks.csv

function git-check-files() {
  FILES=`git diff --name-only $COMMIT~..$COMMIT | grep $1`
  if [[ "$FILES" != "" ]]; then TAGS+="$2,"; fi
}

i=1
echo >$OUTCSV "Date;Author;fbshipit-source-id;Commit title;Commit;Link;Differential Revision;Squash with;FB Tag;Modified MTR files"

for COMMIT in $(git rev-list --first-parent --topo-order --reverse $COMMIT2 ^$COMMIT1)
do
  TAGS=""
  git-check-files rocks rocks

  if [[ "$TAGS" != "" ]]; then
    MTR_FILES=$(git diff --name-only $COMMIT~..$COMMIT | grep -P ."\.(result|test)" | cut -f 1 -d '.' | rev | cut -f 1 -d '/' | rev | sort | uniq | tr '\n' ',')
    if [[ "$MTR_FILES" != "" ]]; then MTR_FILES=${MTR_FILES::-1}; fi

    PARAMS=$(git show -s $COMMIT --pretty="format:%cd;%an" --date=short)
    COMMIT_SHORT=$(git show -s $COMMIT --pretty="format:%h")
    TITLE=$(git show -s --format=%s $COMMIT | tr -d ';')
    DIFF_REV=$(git show -s $COMMIT --format=%B | grep -zioP 'Differential revision[: \n]*(https://reviews.facebook.net/|https://phabricator.intern.facebook.com/|)\K[[:alnum:] ,]*' | tr '\0' ',' | head --bytes -1)
    SQUASH=$(git show -s $COMMIT --format=%B | grep -zioP 'Squash with[: \n]*(https://reviews.facebook.net/|https://phabricator.intern.facebook.com/|)\K[[:alnum:] ,]*' | tr '\0' ',' | head --bytes -1)
    SOURCE_ID=$(git show -s $COMMIT --format=%B | grep -zioP 'fbshipit-source-id[: \n]*\K[[:alnum:] ,]*' | tr '\0' ',' | head --bytes -1)
    GIT_TAG=$(git tag --contains $COMMIT | head -1)

    echo >>$OUTCSV "$PARAMS;$SOURCE_ID;$TITLE;$COMMIT_SHORT;;$DIFF_REV;$SQUASH;$GIT_TAG;$MTR_FILES"
  fi

  ((i=i+1))
done

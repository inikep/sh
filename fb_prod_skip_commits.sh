#!/bin/bash

if [ $# -lt 3 ]; then
  echo usage: $0 [fb-prod1] [fb-prod2] [PS-number]
  exit
fi

OUTNAME=./commit_msg

FBPROD1=$1
FBPROD2=$2
PSNUM=$3

for COMMIT in $(git rev-list --reverse $FBPROD2 ^$FBPROD1)
do
  ROCKS_FILES=`git diff --name-only $COMMIT~..$COMMIT | grep rocksdb`
  SQL_FILES=`git diff --name-only $COMMIT~..$COMMIT | grep "sql/"`
  if [[ "$ROCKS_FILES" == "" ]] || [[ "$SQL_FILES" != "" ]]; then
    fb_skip_commit.sh $FBPROD2 $PSNUM $COMMIT
  fi
done

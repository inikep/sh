#!/bin/bash

if [ $# -lt 3 ]; then
  echo usage: $0 [COMMIT1/BRANCH1] [COMMIT2/BRANCH2] [out-dir]
  exit
fi

COMMIT1=$1
COMMIT2=$2
OUTCSV=$3/${2##*/}.csv

function git-check-files() {
  FILES=`git diff --name-only $COMMIT~..$COMMIT | grep $1`
  if [[ "$FILES" != "" ]]; then TAGS+="$2,"; fi
}

i=1
echo >$OUTCSV "Date;Author;fbshipit-source-id;Commit title;FB Tag;Commit;Link;Differential Revision;Modifications;Tags;Status;Additional Info;Failing MTR files;Modified MTR files"

for COMMIT in $(git rev-list --topo-order --reverse $COMMIT2 ^$COMMIT1)
do
  TAGS=""
  git-check-files "mysqld_safe\.sh" mysqld_safe
  git-check-files "mysql-test-run\.pl" mysql-test-run
  git-check-files "\.gitignore" gitignore
  git-check-files "\.pem" cert
  git-check-files "\.cmake" cmake
  git-check-files "CMakeLists\.txt" cmake
  git-check-files rocks rocks
  git-check-files innobase innobase
  git-check-files valgrind valgrind
  git-check-files jemalloc jemalloc
  git-check-files clang clang
  git-check-files raft raft
  git-check-files "client/" client
  git-check-files "components/" components
  git-check-files "libmysql/" libmysql
  git-check-files "mysys/" mysys
  git-check-files "plugin/" plugin
  git-check-files "sql/" sql
  git-check-files "sql-common/" sql-common
  git-check-files "mysql-test/" mtr
  git-check-files "vio/" vio
  git-check-files "unittest/" unittest
  if [[ "$TAGS" != "" ]]; then TAGS=${TAGS::-1}; fi

  MTR_FILES=$(git diff --name-only $COMMIT~..$COMMIT | grep -P ."\.(result|test)" | cut -f 1 -d '.' | rev | cut -f 1 -d '/' | rev | sort | uniq | tr '\n' ',')
  if [[ "$MTR_FILES" != "" ]]; then MTR_FILES=${MTR_FILES::-1}; fi

  PARAMS=$(git show -s $COMMIT --pretty="format:%cd;%an" --date=short)
  COMMIT_SHORT=$(git show -s $COMMIT --pretty="format:%h")
  TITLE=$(git show -s --format=%s $COMMIT | tr -d ';')
  STATSLINE=$(git show --stat $COMMIT | tail -1)
  STATS=( $STATSLINE )
  MODIFICATIONS="${STATS[0]} files ${STATS[3]}+ ${STATS[5]:-0}-"
  DIFF_REV=$(git show -s $COMMIT --format=%B | grep -zioP 'Differential revision[: \n]*(https://reviews.facebook.net/|https://phabricator.intern.facebook.com/|)\K[[:alnum:] ,]*' | tr '\0' ',' | head --bytes -1)
  SQUASH=$(git show -s $COMMIT --format=%B | grep -zioP 'Squash with[: \n]*(https://reviews.facebook.net/|https://phabricator.intern.facebook.com/|)\K.*' | tr '\0' ',' | head --bytes -1)
  SOURCE_ID=$(git show -s $COMMIT --format=%B | grep -zioP 'fbshipit-source-id[: \n]*\K[[:alnum:] ,]*' | tr '\0' ',' | head --bytes -1)
  UPSTREAM_BUG=$(git show -s $COMMIT --format=%B | grep -zioP 'https://bugs\.mysql\.com/(bug\.php\?id=|)[0-9]*' | tr '\0' ',' | head --bytes -1)
  GIT_TAG=$(git tag --contains $COMMIT | head -1)
  if [[ "$SQUASH" != "" ]]; then SQUASH="Squash with $SQUASH"; fi;
  echo >>$OUTCSV "$PARAMS;$SOURCE_ID;$TITLE;$GIT_TAG;$COMMIT_SHORT;;$DIFF_REV;$MODIFICATIONS;$TAGS;should port;$SQUASH;$UPSTREAM_BUG;$MTR_FILES"
  ((i=i+1))
done

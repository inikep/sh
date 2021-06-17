#!/bin/bash

if [ $# -lt 3 ]; then
  echo usage: $0 [fb-prodXXXX] [PS-XXXX] [commit]
  exit
fi

OUTNAME=./commit_msg

COMMIT=$3
PSNUM=$2
FBPROD2=$1

TITLE=$(git show -s --format=%s $COMMIT)
while [[ ${TITLE::1} == "-" ]] || [[ ${TITLE::1} == " " ]]
do
TITLE="${TITLE:1}"
done
printf >>$OUTNAME "$TITLE\n\n"
printf >>$OUTNAME "Upstream commit ID : fb-mysql-5.6.35/$COMMIT\n"
printf >>$OUTNAME "$PSNUM : Merge $FBPROD2\n\n"
printf >>$OUTNAME "This is a NULL cherry-pick to Percona Server to create the commit placeholder for the corresponding upstream commit.\n"
printf >>$OUTNAME "Reason: Patch not taken into Percona Server\n"
git commit --allow-empty -F $OUTNAME
rm -f $OUTNAME

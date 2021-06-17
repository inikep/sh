#!/bin/bash
for f in $(find server-work/ -type f -iname "*.h" -or -iname "*.c" -or -iname "*.cc")
do
  echo "Processing $f file..."
  # take action on each file. $f store current file name
  echo $f
  clang-format -style=file $f | diff $f -
  # cat $f
done

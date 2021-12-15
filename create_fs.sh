#!/bin/bash

DEVICE=$1
MOUNT_POINT=$2
FILE_SYSTEM=$3
MKFS_OPTIONS=$4

if [ $# -lt 3 ]; then
  echo "usage: $0 [DEVICE] [MOUNT_POINT] [FILE_SYSTEM] <MKFS_OPTIONS>"
  exit
fi

df -T | grep $DEVICE
umount $MOUNT_POINT
if [ "$FILE_SYSTEM" == "xfs" ]; then
    mkfs.$FILE_SYSTEM -f $MKFS_OPTIONS $DEVICE
else
    mkfs.$FILE_SYSTEM -F $MKFS_OPTIONS $DEVICE
fi
mkdir -p $MOUNT_POINT
mount $DEVICE $MOUNT_POINT
chmod a+rwx $MOUNT_POINT
df -T | grep $DEVICE

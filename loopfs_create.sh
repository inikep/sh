#!/bin/sh

LOOP_PATH=/home/przemek/Downloads/loop
DATA_FILE=$LOOP_PATH/loopfs_file.img
MOUNT_DIR=$LOOP_PATH/loopfs

set -x
dd if=/dev/zero of=$DATA_FILE bs=1M count=256
chmod 644 $DATA_FILE
du -sh $DATA_FILE
sudo losetup -fP $DATA_FILE
sudo /sbin/mkfs.fat $DATA_FILE

mkdir $MOUNT_DIR
sudo mount -o loop,uid='id -u przemek',gid='id -g przemek' $DATA_FILE $MOUNT_DIR
df -hP $MOUNT_DIR
mount | grep loopfs

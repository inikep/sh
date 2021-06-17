#!/bin/sh

LOOP_PATH=/home/przemek/Downloads/loop
DATA_FILE=$LOOP_PATH/loopfs_file.img
MOUNT_DIR=$LOOP_PATH/loopfs

set -x
sudo umount $MOUNT_DIR
rmdir $MOUNT_DIR
sudo losetup -d $DATA_FILE
rm $DATA_FILE

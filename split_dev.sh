#!/bin/bash

if [ $# != 3 ]; then
    echo "Usage: $0 <device> <splitted device 1> <splitted device 2>"
    exit 1
fi

DEV=$1
ZONE_SIZE=$(cat /sys/class/block/$DEV/queue/chunk_sectors)
NR_ZONES=$(cat /sys/class/block/$DEV/queue/nr_zones)
SPLIT_ZONES=$(($NR_ZONES / 2))
SPLIT_SZ=$(($SPLIT_ZONES * $ZONE_SIZE))

echo "0 $SPLIT_SZ linear /dev/$DEV 0" | dmsetup create "$2"
echo "0 $SPLIT_SZ linear /dev/$DEV $SPLIT_SZ" | dmsetup create "$3"

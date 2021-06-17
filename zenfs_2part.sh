if [ $# != 1 ]; then
    echo "Usage: $0 <on/off>"
    exit 1
fi

MODE=$1
MAX_OPEN=$((16 / 2))

DEV=nvme1n2
DEV_part1=nvme1n2_part1
DEV_part2=nvme1n2_part2

dmsetup remove $DEV_part1
dmsetup remove $DEV_part2
zbd reset /dev/$DEV

rm -rf /data/zenfs_$DEV_part1
rm -rf /data/zenfs_$DEV_part2

if [ $MODE == "on" ]; then
  split_dev.sh $DEV $DEV_part1 $DEV_part2
  zenfs_exp mkfs --aux-path=/data/zenfs_$DEV_part1 --force --zbd=mapper/$DEV_part1 --finish_threshold=100 --max_active_zones=$MAX_OPEN --max_open_zones=$MAX_OPEN
  zenfs_exp mkfs --aux-path=/data/zenfs_$DEV_part2 --force --zbd=mapper/$DEV_part2 --finish_threshold=100 --max_active_zones=$MAX_OPEN --max_open_zones=$MAX_OPEN
fi

#!/bin/sh -ex

DEV=nvme1n2
FUZZ=5
ZONE_SZ_SECS=$(cat /sys/class/block/$DEV/queue/chunk_sectors)
ZONE_CAP=$((ZONE_SZ_SECS * 512))
BASE_FZ=$(($ZONE_CAP  * (100 - $FUZZ) / 100))
WB_SIZE=$(($BASE_FZ * 2))

TARGET_FZ_BASE=$WB_SIZE
TARGET_FILE_SIZE_MULTIPLIER=2
MAX_BYTES_FOR_LEVEL_BASE=$((2 * $TARGET_FZ_BASE))

rm -rf /tmp/zenfs_$DEV
/data/sh/zenfs mkfs --zbd=$DEV --aux_path=/tmp/zenfs_$DEV --finish_threshold=0 --force

VALUE_SIZE=800
NUM_KEYS=1000000
# fillsync
BENCHMARKS=fillrandom,overwrite,readrandom,readwhilewriting,readwhilescanning,randomtransaction
BENCHMARKS=fillrandom,readrandom,readwhilewriting
BENCHMARKS=fillseq,fillrandom,overwrite,readrandom,newiterator,newiteratorwhilewriting,seekrandom,seekrandomwhilewriting,readseq,readreverse,compact,readrandom,multireadrandom,readseq,readtocache,readreverse,readwhilewriting,readrandomwriterandom,updaterandom,randomwithverify,fill100K,crc32c,xxhash,compress,uncompress,acquireload,fillseekseq,randomtransaction,randomreplacekeys,timeseries,fillbatch,deleteseq,filluniquerandom,readwhilescanning,appendrandom,deleterandom

echo WD DC ZN540 2 TB, PCIe 3.1 x4 / dual-port NVMe 1.3c
if [ 1 == 0 ];
then
for WB_SIZE in 4080218930 # 1073741824 134217728
# for VALUE_SIZE in 800 400 200 100
do
  echo NUM_KEYS=$NUM_KEYS VALUE_SIZE=$VALUE_SIZE WB_SIZE=$WB_SIZE
  /data/sh/db_bench --fs_uri=zenfs://dev:$DEV --value_size=$VALUE_SIZE --write_buffer_size=$WB_SIZE --benchmarks=$BENCHMARKS  \
   --num=$NUM_KEYS --use_direct_io_for_flush_and_compaction --compression_type=lz4
done
fi

echo Samsung 980 PRO 2TB, PCIe 4.0 x4 / NVMe 1.3c
for WB_SIZE in 4080218930 # 1073741824 134217728
# for VALUE_SIZE in 800 400 200 100
do
  echo NUM_KEYS=$NUM_KEYS VALUE_SIZE=$VALUE_SIZE WB_SIZE=$WB_SIZE
  /data/sh/db_bench --value_size=$VALUE_SIZE --write_buffer_size=$WB_SIZE --benchmarks=$BENCHMARKS  \
   --num=$NUM_KEYS --use_direct_io_for_flush_and_compaction --compression_type=lz4
done

# --use_direct_io_for_flush_and_compaction
# --max_bytes_for_level_multiplier=4
# --max_bytes_for_level_base=$MAX_BYTES_FOR_LEVEL_BASE
# --target_file_size_base=$TARGET_FZ_BASE
# --key_size=16
# --max_background_jobs=$MAX_BACKGROUND_JOBS
# --max_background_compactions=$MAX_BACKGROUND_COMPACTIONS
# --open_files=$OPEN_FILES

# Any subsequent(*) commands which fail will cause the shell script to exit immediately
set -e

ntabs=$1
nrows=$2
readsecs=$3
writesecs=$4
insertsecs=$5
dbAndCreds=$6
setup=$7
cleanup=$8
client=$9
tableoptions=${10}
sysbdir=${11}
ddir=${12}
dname=${13}
usepk=${14}
sync_size=${15}
shift 15
threads=$@  # The remaining args are the number of concurrent users per test run, for example "1 2 4"
pwr=0       # value for "postwrite" option for most tests

# run_workload [testType] [range] [secs]
run_workload() {
  local testType=$1
  local range=$2
  local secs=$3
  bash run.sh $ntabs $nrows $secs $dbAndCreds 0 0 $testType $range $client $tableoptions $sysbdir $ddir $dname $usepk $pwr $sync_size $threads
}

# prepare
preparesecs=$((readsecs / 4))
RANGE_SIZE=100

run_workload point-query.pre  $RANGE_SIZE $preparesecs

for range in 10 100 10000 ; do
run_workload read-only.pre $range $preparesecs
done


# main tests
run_workload update-index     $RANGE_SIZE $writesecs
run_workload update-nonindex  $RANGE_SIZE $writesecs
run_workload update-one       $RANGE_SIZE $writesecs
run_workload update-zipf      $RANGE_SIZE $writesecs
run_workload write-only       $RANGE_SIZE $writesecs

for range in 10 100 ; do
run_workload read-write    $range $writesecs
done

for range in 10 100 10000 ; do
run_workload read-only     $range $readsecs
done

run_workload point-query      $RANGE_SIZE $readsecs
run_workload delete           $RANGE_SIZE $writesecs
run_workload insert           $RANGE_SIZE $insertsecs

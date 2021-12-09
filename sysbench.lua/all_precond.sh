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

# value for "postwrite" option for most tests
pwr=0

# The remaining args are the number of concurrent users per test run, for example "1 2 4"
shift 15

# Drop tables
echo drop $ntabs tables
bash run.sh $ntabs $nrows $readsecs  $dbAndCreds 0      1        cleanup               100 $client $tableoptions $sysbdir $ddir $dname $usepk 0    $sync_size $@

# Create and populate tables
echo populate $ntabs tables with $nrows rows
bash run.sh $ntabs $nrows $readsecs  $dbAndCreds 1      0        setup                 100 $client $tableoptions $sysbdir $ddir $dname $usepk 0    $sync_size $@

# Main tests
echo write-only, run 1
bash run.sh $ntabs $nrows $writesecs $dbAndCreds 0      0        write-only.run-1      100 $client $tableoptions $sysbdir $ddir $dname $usepk $pwr $sync_size $@

echo write-only, run 2
bash run.sh $ntabs $nrows $writesecs $dbAndCreds 0      0        write-only.run-2      100 $client $tableoptions $sysbdir $ddir $dname $usepk $pwr $sync_size $@

echo write-only, run 3
bash run.sh $ntabs $nrows $writesecs $dbAndCreds 0      0        write-only.run-3      100 $client $tableoptions $sysbdir $ddir $dname $usepk $pwr $sync_size $@

echo write-only, run 4
bash run.sh $ntabs $nrows $writesecs $dbAndCreds 0      0        write-only.run-4      100 $client $tableoptions $sysbdir $ddir $dname $usepk $pwr $sync_size $@

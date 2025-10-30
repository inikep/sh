alias vpn-import="sudo openvpn3 config-import --config /home/przemek/.ssh/ovpn/profile-902.ovpn"
alias vpn-start="sudo openvpn3 session-start --config /home/przemek/.ssh/ovpn/profile-902.ovpn"
alias ssh14="ssh przemyslaw.skibinski@10.30.3.14 -i /home/przemek/.ssh/inikep.priv"
alias ssh117="ssh przemyslaw.skibinski@10.30.7.117 -i /home/przemek/.ssh/inikep.priv"
alias ssh134="ssh przemyslaw.skibinski@10.30.7.134 -i /home/przemek/.ssh/inikep.priv"
function sshini() { ssh przemyslaw.skibinski@$1 -i /home/przemek/.ssh/inikep-rsa4096.priv $2 $3; }

alias cf_on="git config --local include.path /data/mysql-server/percona-8.0/.gitconfig"
alias cf_off="git config --local --unset include.path"
alias git-clang-format="cf_off; git clang-format $@; cf_on"
alias git-log="git log --oneline -10 $@"
alias git-logfp="git log --first-parent --topo-order --oneline -10 $@"
alias git-last="git log --format=%B -1"
alias git-pick="git cherry-pick"
alias git-picknc="git cherry-pick --no-commit"
alias git-amend="git cherry-pick --amend"
alias zenfs-rocks-size="zenfs list --zbd=nvme1n2 --path=./.rocksdb | awk '{sum+=\$1;} END {printf \"%d\n\", sum/1024/1024;}'"
alias zenfs-free-zones="zbd report /dev/nvme1n2 | grep em | wc -l"
alias hibernate="systemctl hibernate"

MTR_BASE="./mysql-test/mtr --debug-server --retry-failure=0 --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libeatmydata.so --mysqld=--replica-parallel-workers=4"
MTR_PARALLEL="$MTR_BASE --parallel=auto --force --max-test-fail=0"
MTR_SANITIZE="$MTR_PARALLEL --sanitize"
alias     mtr-single="$MTR_BASE"
alias      mtr-zenfs="sudo $MTR_BASE --mysqld=--rocksdb_fs_uri=zenfs://dev:nvme1n2"
alias   mtr-jemalloc="$MTR_BASE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so:/usr/lib/x86_64-linux-gnu/libeatmydata.so"
alias   mtr-valgrind="$MTR_PARALLEL --shutdown-timeout=150 --valgrind --valgrind-clients --valgrind-option=--num-callers=32 --valgrind-option=--show-leak-kinds=all --valgrind-option=--leak-check=full"
alias     mtr-massif="$MTR_BASE --shutdown-timeout=150 --valgrind --valgrind-clients --valgrind-option=--tool=massif"
function mtr-parallel-aio() { t $MTR_PARALLEL --mysqld=--innodb_use_native_aio=0 $@; }
function mtr-parallel() { t $MTR_PARALLEL $@; }
function      mtr-rec() { t $MTR_PARALLEL --record $@; }
function      mtr-big() { t $MTR_PARALLEL --big-test $@; }
alias       mtr-fb56="$MTR_PARALLEL --mysqld=--default-storage-engine=rocksdb --mysqld=--rocksdb=1 --mysqld=--skip-innodb --mysqld=--default-tmp-storage-engine=MyISAM"
alias       mtr-fb80="$MTR_PARALLEL --mysqld=--default-storage-engine=rocksdb --charset-for-testdb=latin1"
alias   mtr-sanitize="$MTR_SANITIZE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libasan.so"
alias  mtr-sanitize5="$MTR_SANITIZE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libasan.so.5:/usr/lib/x86_64-linux-gnu/libeatmydata.so"
alias  mtr-sanitize6="$MTR_SANITIZE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libasan.so.6:/usr/lib/x86_64-linux-gnu/libeatmydata.so"
alias  mtr-sanitize8="$MTR_SANITIZE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libasan.so.8:/usr/lib/x86_64-linux-gnu/libeatmydata.so"

function t() {
  export PARAMS="$@"
  echo $PARAMS
  /usr/bin/time --quiet -f "%e" -o ~/time.log $PARAMS
  CMD_TIME=$(cat ~/time.log)
  TIME_ROOT=${TIME_ROOT:-/data}
  echo $CMD_TIME $@ | tee -a $TIME_ROOT/cmd_time.log
}

function get-gca() {
  if [ $# -lt 2 ]; then
    echo "usage: $0 <lower_branch> <higher_branch>"
  else
    gca_rev="$(git rev-list "$1" ^"$2" --first-parent --topo-order | tail -1)^"
    gca_num="$(git rev-list "$1" ^"$2" --first-parent --topo-order | wc -l)"
    echo "The number of commits from '$1' missing in '$2' = $gca_num"
    echo "GCA of '$1' and '$2' = $gca_rev"
    git log --oneline -1 $gca_rev
  fi
}

function mtr-result-files() {
  if [ $# -lt 1 ]; then
    echo "usage: $0 [commit1] <commit2>"
  else
    if [ "$2" = "" ]; then PREV=$1~; else PREV=$2; fi
    echo "commits $PREV..$1"
    printf "mtr-rec " && git diff $PREV..$1 --name-only | grep -Po "[[:alnum:]_-]*(?=(\.result|\.test|-master\.opt))" | sort | uniq | tr '\n' ' '; echo;
  fi
}

# INST_LIST="c5.4xlarge c6i.8xlarge" REGION=us-west-2 aws-prices
function aws-prices() {
  for inst in ${INST_LIST};
  do
    echo $inst;
    sudo docker run --rm ghcr.io/alexei-led/spotinfo --type="$inst" --region="${REGION}" --os=linux --output=text --sort=interruption;
    aws ec2 --region="${REGION}" describe-spot-price-history --instance-types "$inst" --product-description "Linux/UNIX (Amazon VPC)" --start-time $(date +%s) --query SpotPriceHistory[].[InstanceType,AvailabilityZone,SpotPrice] --output text;
  done
}

function drop-caches() {
  sync
  sudo sh -c 'sysctl -q -w vm.drop_caches=3'
  sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
}

function count-lines() { cat $1 | rev | cut -f 1,2 -d '.' | rev | sort | uniq -c | sort -nr > $1_sorted; }
function git-worktree() { git worktree add -b $1 ../$1 $2 $3 $4; cd ../$1; }
function git-mergetool() { git checkout --conflict=merge $1; git mergetool $1; }
function git-commitfile() { git add $1; git commit -m"$1"; }
function git-diff-files() { git diff $1~..$1 $2 $3 $4; }
function git-squash() {
  if [ $# -lt 1 ]; then
    echo usage: $0 [num_of_commits]
  else
    git reset --soft HEAD~$1 && git commit --edit -m"$(git log --format=%B --reverse HEAD..HEAD@{1})"
    git commit
  fi
}
function git-split() {
  if [ $# -lt 1 ]; then
    echo usage: $0 [file_names]
  else
    git reset HEAD^ -- $@
    git commit --amend
    git add $@
    git commit --reuse-message=HEAD@{1}
    git commit --amend
  fi
}

function git-unmerge() {
  if [ $# -lt 2 ]; then
    echo usage: $0 [start_commit] [end_commit]
  else
    git log --pretty='%H' --topo-order $1..$2 --reverse | xargs git cherry-pick -m1
  fi
}

function git-unmerge-plan() {
  if [ $# -lt 2 ]; then
    echo usage: $0 [start_commit] [end_commit]
  else
    git log --oneline --topo-order $1..$2 --reverse
  fi
}

function fb-worktree() { git fetch facebook && cd ../fb-8.0.13 && git checkout fb-8.0.13 && git pull && git worktree add -b $@ ../$@ facebook/fb-mysql-8.0.13; cd ../$@; }
function fb-update() { MYPWD=`pwd`; git fetch facebook && cd ../fb-8.0.13 && git checkout fb-8.0.13 && git pull; cd $MYPWD; }


function disable_address_randomization(){
    PREVIOUS_ASLR=`cat /proc/sys/kernel/randomize_va_space`
    sudo sh -c "echo 0 > /proc/sys/kernel/randomize_va_space"
    echo "Changing /proc/sys/kernel/randomize_va_space from $PREVIOUS_ASLR to `cat /proc/sys/kernel/randomize_va_space`"
}

function restore_address_randomization(){
    local CURRENT_ASLR=`cat /proc/sys/kernel/randomize_va_space`
    sudo sh -c "echo $PREVIOUS_ASLR > /proc/sys/kernel/randomize_va_space"
    echo "Resoring /proc/sys/kernel/randomize_va_space from $CURRENT_ASLR to `cat /proc/sys/kernel/randomize_va_space`"
}

function disable_turbo_boost(){
  SCALING_DRIVER=`cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver`
  echo "Using $SCALING_DRIVER scaling driver"

  if [[ ${SCALING_DRIVER} == "intel_pstate" || ${SCALING_DRIVER} == "intel_cpufreq" ]]; then
    PREVIOUS_TURBO=`cat /sys/devices/system/cpu/intel_pstate/no_turbo`
    sudo sh -c "echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo"
    echo "Changing /sys/devices/system/cpu/intel_pstate/no_turbo from $PREVIOUS_TURBO to `cat /sys/devices/system/cpu/intel_pstate/no_turbo`"
  else
    PREVIOUS_TURBO=`cat /sys/devices/system/cpu/cpufreq/boost`
    sudo sh -c "echo 0 > /sys/devices/system/cpu/cpufreq/boost"
    echo "Changing /sys/devices/system/cpu/cpufreq/boost from $PREVIOUS_TURBO to `cat /sys/devices/system/cpu/cpufreq/boost`"
  fi
}

function restore_turbo_boost(){
  echo "Restore turbo boost with $SCALING_DRIVER scaling driver"

  if [[ ${SCALING_DRIVER} == "intel_pstate" || ${SCALING_DRIVER} == "intel_cpufreq" ]]; then
    CURRENT_TURBO=`cat /sys/devices/system/cpu/intel_pstate/no_turbo`
    sudo sh -c "echo $PREVIOUS_TURBO > /sys/devices/system/cpu/intel_pstate/no_turbo"
    echo "Resoring /sys/devices/system/cpu/intel_pstate/no_turbo from $CURRENT_TURBO to $PREVIOUS_TURBO"
  else
    CURRENT_TURBO=`cat /sys/devices/system/cpu/cpufreq/boost`
    sudo sh -c "echo $PREVIOUS_TURBO > /sys/devices/system/cpu/cpufreq/boost"
    echo "Resoring /sys/devices/system/cpu/cpufreq/boost from $CURRENT_TURBO to $PREVIOUS_TURBO"
  fi
}

function change_scaling_governor(){
  PREVIOUS_GOVERNOR=`cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
  sudo cpupower frequency-set -g $1
  echo "Changing scaling governor from $PREVIOUS_GOVERNOR to `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`"
  sudo cpupower frequency-info
}

function restore_scaling_governor(){
  local CURRENT_GOVERNOR=`cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
  sudo cpupower frequency-set -g $PREVIOUS_GOVERNOR
  echo "Restoring scaling governor from $CURRENT_GOVERNOR to `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`"
  sudo cpupower frequency-info
}

function set_performance(){
  disable_address_randomization
  disable_turbo_boost
  change_scaling_governor performance
}

function restore_from_performance(){
  restore_address_randomization
  restore_turbo_boost
  restore_scaling_governor
}

function check_errors() {
    local target_dir="$1"
    # save the current directory
    local orig_dir="$PWD"

    # go to target directory
    cd "$target_dir" || { echo "Cannot cd into $target_dir"; return 1; }

    # loop through subdirectories
    for dir in $(ls -d */ | sort -V); do
        echo "${dir%/}"
        grep -iE "sanit|terribly wrong|ERROR|seqno|Assertion|loose" "$dir/log/master.err"
    done

    # return to original directory
    cd "$orig_dir" || { echo "Cannot return to $orig_dir"; return 1; }
}

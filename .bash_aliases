alias vpn="sudo openvpn --config /home/przemek/.ssh/client.ovpn --auth-retry interact --mute-replay-warnings"
alias ssh13="ssh przemyslaw.skibinski@10.30.3.13 -i /home/przemek/.ssh/inikep.priv"
alias ssh14="ssh przemyslaw.skibinski@10.30.3.14 -i /home/przemek/.ssh/inikep.priv"
alias ssh117="ssh przemyslaw.skibinski@10.30.7.117 -i /home/przemek/.ssh/inikep.priv"
alias ssh134="ssh przemyslaw.skibinski@10.30.7.134 -i /home/przemek/.ssh/inikep.priv"
function sshini() { ssh przemyslaw.skibinski@$1 -i /home/przemek/.ssh/inikep.priv; }
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
MTR_BASE_OLD="./mysql-test/mtr --debug-server --retry-failure=0 --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libeatmydata.so --mysqld=--slave-parallel-workers=4"
MTR_PARALLEL_OLD="$MTR_BASE_OLD --parallel=auto --force --max-test-fail=0"
MTR_PARALLEL="$MTR_BASE --parallel=auto --force --max-test-fail=0"
MTR_SANITIZE="$MTR_PARALLEL --sanitize"
MTR_SANITIZE_OLD="$MTR_PARALLEL_OLD --sanitize --big-test"
alias   mtr-sanitize-old="$MTR_SANITIZE_OLD"
alias   mtr-parallel-old="$MTR_PARALLEL_OLD"
alias     mtr-single-old="$MTR_BASE_OLD"
alias     mtr-single="$MTR_BASE"
alias      mtr-zenfs="sudo $MTR_BASE --mysqld=--rocksdb_fs_uri=zenfs://dev:nvme1n2"
alias   mtr-jemalloc="$MTR_BASE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so:/usr/lib/x86_64-linux-gnu/libeatmydata.so"
alias   mtr-valgrind="$MTR_PARALLEL --shutdown-timeout=150 --valgrind --valgrind-clients --valgrind-option=--num-callers=32 --valgrind-option=--show-leak-kinds=all --valgrind-option=--leak-check=full"
alias     mtr-massif="$MTR_BASE --shutdown-timeout=150 --valgrind --valgrind-clients --valgrind-option=--tool=massif"
alias   mtr-parallel="$MTR_PARALLEL"
alias        mtr-big="$MTR_PARALLEL --big-test"
alias       mtr-fb56="$MTR_PARALLEL --mysqld=--default-storage-engine=rocksdb --mysqld=--rocksdb=1 --mysqld=--skip-innodb --mysqld=--default-tmp-storage-engine=MyISAM"
alias       mtr-fb80="$MTR_PARALLEL --mysqld=--default-storage-engine=rocksdb --charset-for-testdb=latin1"
alias   mtr-sanitize="$MTR_SANITIZE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libasan.so"
alias  mtr-sanitize5="$MTR_SANITIZE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libasan.so.5:/usr/lib/x86_64-linux-gnu/libeatmydata.so"
alias  mtr-sanitize6="$MTR_SANITIZE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libasan.so.6:/usr/lib/x86_64-linux-gnu/libeatmydata.so"
alias  mtr-sanitize8="$MTR_SANITIZE --mysqld-env=LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libasan.so.8:/usr/lib/x86_64-linux-gnu/libeatmydata.so"

function mtr-result-files() {
  if [ $# -lt 1 ]; then
    echo "usage: $0 [commit1] <commit2>"
  else
    if [ "$2" = "" ]; then PREV=$1~; else PREV=$2; fi
    echo "commits $PREV..$1"
    printf "mtr-parallel " && git diff $PREV..$1 --name-only | grep -Po "[[:alnum:]_-]*(?=(\.result|\.test|-master\.opt))" | sort | uniq | tr '\n' ' '; echo;
  fi
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


function fb-worktree() { git fetch facebook && cd ../fb-8.0.13 && git checkout fb-8.0.13 && git pull && git worktree add -b $@ ../$@ facebook/fb-mysql-8.0.13; cd ../$@; }
function fb-update() { MYPWD=`pwd`; git fetch facebook && cd ../fb-8.0.13 && git checkout fb-8.0.13 && git pull; cd $MYPWD; }

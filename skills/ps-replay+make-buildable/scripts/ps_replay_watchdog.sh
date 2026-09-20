#!/bin/bash
# Progress / hang-up watchdog for a ps-replay run.
#
# Completion is detected promptly: the rc files are polled every POLL seconds
# (default 1), so the caller is handed back within ~1s of the driver or build
# finishing. INTERVAL is only the *heartbeat* cadence -- how often a status line
# is printed and how stall detection is clocked. It is never the thing that
# decides when we notice the work is done.
#
# usage: ps_replay_watchdog.sh RUN_DIR [INTERVAL_SECONDS] [STALL_TICKS] [POLL_SECONDS]
#
# Exit codes:
#   0  the watched work finished  (driver.rc or build.rc appeared)
#   2  STALLED: no log output and no new commit for STALL_TICKS consecutive ticks
#
# Status line fields:
#   t=<elapsed>  rc=<driver.rc|build.rc|->  head=<short sha>  n=<commits on branch>
#   idx=<last index seen in the newest driver log>  log=<seconds since newest log write>
set -u
RUN_DIR=${1:?usage: ps_replay_watchdog.sh RUN_DIR [INTERVAL] [STALL_TICKS] [POLL]}
INTERVAL=${2:-300}
STALL_TICKS=${3:-6}
POLL=${4:-1}
WORKTREE=${WORKTREE:-/data/percona-server-linear}
BASE=${BASE:-mysql-8.0.28}

started=$(date +%s)
stalled=0
prev_sig=""
next_tick=$started          # print a status line immediately, then every INTERVAL

# Only an rc file written after the watchdog started counts as "this work
# finished"; a leftover driver.rc/build.rc from an earlier step must not be
# mistaken for a completion.
fresh_rc() {  # fresh_rc <file> -> echoes value, returns 0 when fresh
  [ -f "$1" ] || return 1
  [ "$(stat -c %Y "$1")" -ge "$started" ] || return 1
  cat "$1"
}

status_line() {  # status_line <rc> -> prints one heartbeat line
  printf 't=%02d:%02d:%02d  rc=%s  head=%s  n=%s  idx=%s  log_age=%ss\n' \
    $((t/3600)) $((t%3600/60)) $((t%60)) "$1" "$head" "$n" "${idx:--}" "$age"
}

collect() {  # refresh head/n/idx/age for the status line and stall signature
  head=$(git -C "$WORKTREE" rev-parse --short HEAD 2>/dev/null)
  n=$(git -C "$WORKTREE" rev-list --count "$BASE"..HEAD 2>/dev/null)
  newest=$(ls -t "$RUN_DIR"/logs/*.log 2>/dev/null | head -1)
  if [ -n "$newest" ]; then
    age=$(( now - $(stat -c %Y "$newest") ))
    idx=$(grep -o '^\[[0-9]\+/[0-9]\+\]' "$newest" 2>/dev/null | tail -1 | tr -d '[]')
  else
    age=-1; idx="-"; newest=""
  fi
}

while :; do
  now=$(date +%s); t=$(( now - started ))

  # --- completion check, every POLL seconds ---------------------------------
  rc=""
  if v=$(fresh_rc "$RUN_DIR/driver.rc"); then rc="driver:$v"; fi
  if v=$(fresh_rc "$RUN_DIR/build.rc");  then rc="${rc:+$rc }build:$v"; fi
  if [ -n "$rc" ]; then
    collect
    status_line "$rc"
    echo "FINISHED  rc=$rc  head=$head"
    exit 0
  fi

  # --- heartbeat + stall detection, every INTERVAL seconds -------------------
  if [ "$now" -ge "$next_tick" ]; then
    collect
    status_line "-"
    sig="$head|$idx|$(stat -c %Y "$newest" 2>/dev/null)"
    if [ "$sig" = "$prev_sig" ]; then stalled=$(( stalled + 1 )); else stalled=0; fi
    prev_sig="$sig"
    if [ "$stalled" -ge "$STALL_TICKS" ]; then
      echo "STALLED  no progress for $(( stalled * INTERVAL ))s  head=$head idx=${idx:--} log=$newest"
      exit 2
    fi
    next_tick=$(( next_tick + INTERVAL ))
    # If we fell behind (long git call), resync so ticks stay on cadence.
    while [ "$next_tick" -le "$now" ]; do next_tick=$(( next_tick + INTERVAL )); done
  fi

  sleep "$POLL"
done

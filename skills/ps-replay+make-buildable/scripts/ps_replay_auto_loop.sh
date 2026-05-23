#!/bin/bash
# Compatibility wrapper for ps_replay_batch.py.
#
# The current skill rules require Group 8 checkpoint handling, post-Group-8
# HP-8 staged-path checks, and no upfront effort-budget prompt. Keep those
# mechanics in the Python batch driver; this wrapper only maps the historical
# environment-variable interface onto that driver.

set -u

START=${1:?usage: $0 START END}
END=${2:?usage: $0 START END}

SRC_LIST=${PS_REPLAY_SRC_LIST:?PS_REPLAY_SRC_LIST not set}
LOG_DIR=${PS_REPLAY_LOG_DIR:?PS_REPLAY_LOG_DIR not set}
BUILD_DIR=${PS_REPLAY_BUILD_DIR:?PS_REPLAY_BUILD_DIR not set}
WORKTREE=${PS_REPLAY_WORKTREE:-$(pwd)}
REFERENCE=${PS_REPLAY_REFERENCE:?PS_REPLAY_REFERENCE not set}
SCRIPTS=${PS_REPLAY_SCRIPTS:-$(dirname "$0")}
REPORT_ARGS=()
GROUP8_ARGS=()

if [ -n "${PS_REPLAY_REPORT_FILE:-}" ]; then
    REPORT_ARGS=(--report-file "$PS_REPLAY_REPORT_FILE")
fi

if [ -n "${PS_REPLAY_GROUP8_MARKER:-}" ]; then
    GROUP8_ARGS=(--group8-marker "$PS_REPLAY_GROUP8_MARKER")
fi

exec python3 "$SCRIPTS/ps_replay_batch.py" \
    --source-list "$SRC_LIST" \
    --start "$START" \
    --end "$END" \
    --reference "$REFERENCE" \
    --worktree "$WORKTREE" \
    --build-dir "$BUILD_DIR" \
    --log-dir "$LOG_DIR" \
    --build-policy bucketed \
    "${REPORT_ARGS[@]}" \
    "${GROUP8_ARGS[@]}"

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
CMAKE_ARGS=()
GATE_ARGS=()
AUTO_ARGS=()

if [ -n "${PS_REPLAY_REPORT_FILE:-}" ]; then
    REPORT_ARGS=(--report-file "$PS_REPLAY_REPORT_FILE")
fi

if [ -n "${PS_REPLAY_GROUP8_MARKER:-}" ]; then
    GROUP8_ARGS=(--group8-marker "$PS_REPLAY_GROUP8_MARKER")
fi

if [ -n "${PS_REPLAY_FEATURE_GATES:-}" ]; then
    # Whitespace-separated range-gate evidence JSON paths
    # (pre-group9-gate.json and/or range-gate.json).
    read -r -a _PS_REPLAY_FEATURE_GATES <<< "$PS_REPLAY_FEATURE_GATES"
    for gate in "${_PS_REPLAY_FEATURE_GATES[@]}"; do
        GATE_ARGS+=(--feature-gate "$gate")
    done
fi

if [ -n "${PS_REPLAY_GATE_DECIDED_APPLY:-}" ]; then
    # Whitespace-separated 1-based source indexes already inspected and
    # decided to apply.
    read -r -a _PS_REPLAY_GATE_DECIDED <<< "$PS_REPLAY_GATE_DECIDED_APPLY"
    for idx in "${_PS_REPLAY_GATE_DECIDED[@]}"; do
        GATE_ARGS+=(--gate-decided-apply "$idx")
    done
fi

if [ -n "${PS_REPLAY_GATE_DECIDED_APPLY_FILE:-}" ]; then
    GATE_ARGS+=(--gate-decided-apply-file "$PS_REPLAY_GATE_DECIDED_APPLY_FILE")
fi

if [ -n "${PS_REPLAY_GATE_AUTO_APPLY_PATH_GLOBS:-}" ]; then
    # Whitespace-separated path globs. Quote the env assignment in the caller
    # so shell expansion does not happen before this wrapper receives them.
    read -r -a _PS_REPLAY_GATE_AUTO_GLOBS <<< "$PS_REPLAY_GATE_AUTO_APPLY_PATH_GLOBS"
    for glob in "${_PS_REPLAY_GATE_AUTO_GLOBS[@]}"; do
        AUTO_ARGS+=(--gate-auto-apply-path-glob "$glob")
    done
fi

if [ -n "${PS_REPLAY_GATE_AUTO_APPLY_UNMATCHED_IDENTIFIERS:-}" ]; then
    read -r -a _PS_REPLAY_GATE_AUTO_IDS <<< "$PS_REPLAY_GATE_AUTO_APPLY_UNMATCHED_IDENTIFIERS"
    for ident in "${_PS_REPLAY_GATE_AUTO_IDS[@]}"; do
        AUTO_ARGS+=(--gate-auto-apply-unmatched-identifier "$ident")
    done
fi

if [ -n "${PS_REPLAY_AUTO_DROP_CONFLICT_GLOBS:-}" ]; then
    # Whitespace-separated path globs for reference-absent conflict drops.
    read -r -a _PS_REPLAY_AUTO_DROP_GLOBS <<< "$PS_REPLAY_AUTO_DROP_CONFLICT_GLOBS"
    for glob in "${_PS_REPLAY_AUTO_DROP_GLOBS[@]}"; do
        AUTO_ARGS+=(--auto-drop-reference-absent-conflict-glob "$glob")
    done
fi

if [ -n "${PS_REPLAY_LEDGER_FILE:-}" ]; then
    AUTO_ARGS+=(--ledger-file "$PS_REPLAY_LEDGER_FILE")
fi

if [ -n "${PS_REPLAY_CMAKE_FLAGS:-}" ]; then
    # Whitespace-separated compatibility hook for simple flags such as
    # -DCMAKE_CXX_FLAGS=-fpermissive.
    read -r -a _PS_REPLAY_CMAKE_FLAGS <<< "$PS_REPLAY_CMAKE_FLAGS"
    for flag in "${_PS_REPLAY_CMAKE_FLAGS[@]}"; do
        CMAKE_ARGS+=(--cmake-flag "$flag")
    done
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
    "${GROUP8_ARGS[@]}" \
    "${GATE_ARGS[@]}" \
    "${AUTO_ARGS[@]}" \
    "${CMAKE_ARGS[@]}"

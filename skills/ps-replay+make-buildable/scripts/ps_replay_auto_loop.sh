#!/bin/bash
# Driver loop for replaying a 1-based source-list range with build-driven
# resolution and per-commit builds.
#
# For each idx in [START, END]:
#   1. Read sha and subject from $SRC_LIST.
#   2. Bucket the commit:
#        empty-marker      subject begins with "=== MARKER:"
#        no-build          all changed paths match no-build prefixes
#                          (mysql-test/, doc/, build-ps/, packaging/, *.spec,
#                          scripts/*.{sh,pl,cmake})
#        plugin            every changed path is under plugin/
#        source            anything else (ambiguous defaults to source)
#   3. Cherry-pick:
#        empty-marker      git cherry-pick --allow-empty
#        otherwise         git cherry-pick
#   4. On conflict: resolve DU files absent on REFERENCE by `git rm`, then
#      run ps_replay_resolve_hunks.py against REFERENCE for any files with
#      markers, stage the cleaned files, and continue. Stop if any markers
#      remain.
#   5. If the result is empty after resolution: `git cherry-pick --skip`.
#   6. For source / plugin commits: run ps_replay_build.py incrementally and
#      stop on build failure.
#
# This script is a Build-Driven Fixes scaffold; it does NOT auto-fix build
# failures (those require Fold/Defer/Align/Remove judgment per skill rule
# 6). It stops on the first build failure with the log path so the caller
# can inspect and fix manually.
#
# Per skill HP-1, this script never copies whole files from REFERENCE. The
# only reference-touching action is the hunk-level resolver in
# ps_replay_resolve_hunks.py.
#
# Usage:
#   ps_replay_auto_loop.sh START END
#
# Required environment variables:
#   PS_REPLAY_SRC_LIST    file with one source SHA per line
#   PS_REPLAY_LOG_DIR     directory for per-commit build logs
#   PS_REPLAY_BUILD_DIR   out-of-tree build directory under /tmp
#   PS_REPLAY_WORKTREE    path to the worktree (default: current directory)
#   PS_REPLAY_REFERENCE   reference branch (default: ps-5.7.9-gca-start)
#   PS_REPLAY_SCRIPTS     skill scripts directory (default: dirname of this
#                         script)
#
# Exit codes:
#   0  range completed successfully
#   3  cherry-pick conflict could not be auto-resolved
#   4  build failure
#   5  unmerged files remain after attempted resolution
#   6  cherry-pick continue failed
#   7  marker preservation failed

set -u

START=${1:?usage: $0 START END}
END=${2:?usage: $0 START END}

SRC_LIST=${PS_REPLAY_SRC_LIST:?PS_REPLAY_SRC_LIST not set}
LOG_DIR=${PS_REPLAY_LOG_DIR:?PS_REPLAY_LOG_DIR not set}
BUILD_DIR=${PS_REPLAY_BUILD_DIR:?PS_REPLAY_BUILD_DIR not set}
WORKTREE=${PS_REPLAY_WORKTREE:-$(pwd)}
REFERENCE=${PS_REPLAY_REFERENCE:-ps-5.7.9-gca-start}
SCRIPTS=${PS_REPLAY_SCRIPTS:-$(dirname "$0")}

RESOLVE="$SCRIPTS/ps_replay_resolve_hunks.py"
BUILD="$SCRIPTS/ps_replay_build.py"

cd "$WORKTREE"

is_marker() {
    local subj=$1
    case "$subj" in
        '=== MARKER:'*) return 0 ;;
        *) return 1 ;;
    esac
}

classify_paths() {
    # Stdin: one path per line. Stdout: bucket name.
    local has_plugin=0 has_source=0 has_anything=0 nb=1
    while IFS= read -r p; do
        [ -z "$p" ] && continue
        has_anything=1
        case "$p" in
            mysql-test/*|doc/*|build-ps/*|packaging/*|man/*|Docs/*) ;;
            *.spec|*.spec.*|*.md|*.rst|.bzrignore|.gitignore) ;;
            scripts/*.sh|scripts/*.pl|scripts/CMakeLists.txt|scripts/*.cmake) ;;
            plugin/*) has_plugin=1; nb=0 ;;
            *) has_source=1; nb=0 ;;
        esac
    done
    if [ "$has_anything" = "0" ]; then
        echo empty
        return
    fi
    if [ "$nb" = "1" ]; then
        echo no-build
        return
    fi
    if [ "$has_source" = "0" ] && [ "$has_plugin" = "1" ]; then
        echo plugin
        return
    fi
    echo source
}

for ((idx=START; idx<=END; idx++)); do
    sha=$(sed -n "${idx}p" "$SRC_LIST")
    if [ -z "$sha" ]; then
        echo "[$idx] empty source-list line; stopping" >&2
        exit 2
    fi
    subj=$(git log -1 --format=%s "$sha")

    if is_marker "$subj"; then
        echo "[$idx/$END] MARKER preserve: $subj"
        if ! git cherry-pick --allow-empty "$sha" >/dev/null 2>&1; then
            commit=$(git commit --allow-empty -C "$sha" 2>&1)
            if [ $? -ne 0 ]; then
                echo "[$idx] FAILED to preserve empty marker: $commit" >&2
                exit 7
            fi
        fi
        continue
    fi

    paths=$(git diff-tree --no-commit-id --name-only -r "$sha")
    bucket=$(echo "$paths" | classify_paths)

    echo "[$idx/$END] CHERRY-PICK ${sha:0:12} [$bucket] $subj"

    if ! git cherry-pick "$sha" >/tmp/ps-replay-cp-$$.out 2>&1; then
        # DU files: cherry-pick wants to modify a file that is missing on
        # our side. If the file is also absent on REFERENCE, `git rm` it.
        du_files=$(git status --porcelain | awk '$1=="DU"||$1=="UD" {print $2}')
        for f in $du_files; do
            if ! git cat-file -e "$REFERENCE:$f" 2>/dev/null; then
                git rm --quiet "$f" || true
            fi
        done

        # Files with markers: try the hunk-level resolver.
        markers=$(git grep -l '^<<<<<<<' 2>/dev/null || true)
        if [ -n "$markers" ]; then
            echo "[$idx] auto-resolving markers ..."
            python3 "$RESOLVE" "$REFERENCE" $markers || true
            for f in $markers; do
                if ! grep -q '^<<<<<<<' "$f" 2>/dev/null; then
                    git add "$f" || true
                fi
            done
        fi

        # Bail if any markers remain.
        remaining=$(git grep -l '^<<<<<<<' 2>/dev/null || true)
        if [ -n "$remaining" ]; then
            echo "[$idx] STOP: markers remain in:" >&2
            echo "$remaining" >&2
            echo "  resolve manually using \`git show $REFERENCE:<path>\` for inspection," >&2
            echo "  then \`git add <path>\` and re-run from idx $idx." >&2
            exit 3
        fi

        # Bail if any unmerged files remain.
        unmerged=$(git diff --name-only --diff-filter=U)
        if [ -n "$unmerged" ]; then
            echo "[$idx] STOP: unmerged files remain:" >&2
            echo "$unmerged" >&2
            exit 5
        fi

        # If nothing changed after resolution, the cherry-pick is empty —
        # skip it per skill rule 15.
        if git diff --cached --quiet && git diff --quiet; then
            echo "[$idx] EMPTY after resolution; skipping (rule 15)"
            git cherry-pick --skip >/dev/null 2>&1 || git reset --hard HEAD >/dev/null 2>&1
            continue
        fi

        if ! git cherry-pick --continue --no-edit >/tmp/ps-replay-cp-$$.out 2>&1; then
            echo "[$idx] FAILED to continue cherry-pick:" >&2
            cat /tmp/ps-replay-cp-$$.out >&2
            exit 6
        fi
    fi

    new_sha=$(git rev-parse HEAD)
    echo "[$idx] -> ${new_sha:0:12}"

    # Per-commit build for source/plugin (skill rule 10).
    if [ "$bucket" = "source" ] || [ "$bucket" = "plugin" ]; then
        log="$LOG_DIR/build-${idx}-${new_sha:0:12}.log"
        echo "[$idx] BUILD $log"
        if ! python3 "$BUILD" \
            --worktree "$WORKTREE" \
            --build-dir "$BUILD_DIR" \
            --log "$log" \
            --incremental >/dev/null 2>&1; then
            echo "[$idx] BUILD FAILED. Log: $log" >&2
            echo "  apply Fold/Defer/Align/Remove from skill rule 6," >&2
            echo "  amend the current commit, rebuild, and re-run from idx $((idx+1))." >&2
            exit 4
        fi
        echo "[$idx] BUILD PASS"
    fi
done

echo "DONE [$START-$END]"

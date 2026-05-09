---
name: ps-replay+make-buildable
description: Use to replay Percona Server commits from a mysql-5.6.x BASE_BRANCH..TIP_BRANCH range onto a mysql-5.7.x destination base, resolving conflicts from a known-buildable REFERENCE_BRANCH, preserving buildability after every commit, and producing a final branch with null diff to the reference. Use when porting or rebasing a Percona Server commit range with per-commit build verification.
---

# Percona Server Replay And Make Buildable

## Purpose

Use this skill to port a Percona Server commit range while maintaining a buildable history and converging exactly to a known-good reference branch.

The task is complete only when:

1. `$OUTPUT_BRANCH` is rooted at the destination MySQL base, for example `mysql-5.7.9`.
2. The first non-base commit is the `$REFERENCE_BRANCH` gcc-9 build-fix commit when that fix is not in `$BASE_BRANCH..$TIP_BRANCH` but is required for final parity.
3. Every commit from `$BASE_BRANCH..$TIP_BRANCH` has been cherry-picked one at a time onto that destination base.
4. Empty cherry-picks are skipped, not preserved as empty commits.
5. Every commit on `$OUTPUT_BRANCH` builds successfully, except the destination base commit.
6. `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty.
7. `$REPORT_FILE` records the commits, skipped empty commits, conflicts, build fixes, reordering, and final parity result.

## Inputs

- `$BASE_BRANCH`: source-base branch whose tip is the lower bound of the source range, for example `mysql-5.6.26`.
- `$TIP_BRANCH`: branch containing commits to port.
- `$DESTINATION_BASE_BRANCH`: destination MySQL base for `$OUTPUT_BRANCH`, for example `mysql-5.7.9`.
- `$REFERENCE_BRANCH`: known-buildable branch used as the source of truth for conflict resolution and final tree parity.
- `$OUTPUT_BRANCH`: branch to create from `$DESTINATION_BASE_BRANCH`.
- `$LLM_MODEL`: identifier including model and reasoning level, for example `opus-4.7-high`.
- `$REPORT_FILE`: markdown report to produce. Default to `/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}.md`.
- `$BUILD_DIR`: out-of-tree build directory under `/tmp`, for example `/tmp/ps-replay-${OUTPUT_BRANCH}`.

## Mandatory Rules

1. Cherry-pick commits from `$BASE_BRANCH..$TIP_BRANCH` one by one.
2. Reordering is allowed when it reduces conflicts or simplifies resolution. Record every reordered commit and the reason in `$REPORT_FILE`.
3. Root `$OUTPUT_BRANCH` at `$DESTINATION_BASE_BRANCH`, not at `$BASE_BRANCH`. The source range may be mysql-5.6.x-based while the output branch is mysql-5.7.x-based.
4. If `$REFERENCE_BRANCH` contains a top-level gcc-9 build-fix commit that is not in `$BASE_BRANCH..$TIP_BRANCH`, apply it as the first non-base commit on `$OUTPUT_BRANCH`.
5. For commits in the `"Initial Percona Server 5.6.22 tree"` group, choose the next commit dynamically by least conflicts against the current `$OUTPUT_BRANCH` state. This is intentionally slower and is required.
6. Resolve conflicts using `$REFERENCE_BRANCH` as the ground truth.
7. When a commit does not build in isolation, first fold in the minimum necessary fixes or partial changes from later commits on `$REFERENCE_BRANCH`.
8. If those changes become cascading and very large, remove only the hunks that cause dependency-cascade conflicts and defer them to the later commit that introduces the required dependency.
9. Build after every completed commit, including the first gcc-9 fix commit and every cherry-picked source commit. Only the destination base commit is exempt.
10. Do not create empty commits. If a cherry-pick becomes empty because its changes are already present or were intentionally deferred/applied elsewhere, skip it and document it.
11. The final tree must have a null diff to `$REFERENCE_BRANCH`.
12. If residual differences remain after all cherry-picks, add a final reconciliation commit that brings the tree to `$REFERENCE_BRANCH` and document it.
13. Do not use scripts from `/data/sh/utils`. Writing `$REPORT_FILE` under `/data/sh/utils/reports/` is allowed.
14. Do not use the `percona_gca_sync_tdd` or `percona_conflict_resolution_tdd` skills.

## Build Configuration

Use an out-of-tree build directory under `/tmp`, and configure with these options unless the task explicitly overrides them:

```sh
CC=gcc-9 CXX=g++-9 cmake .. \
  -DCMAKE_BUILD_TYPE=Debug \
  -DMYSQL_MAINTAINER_MODE=OFF \
  -DDOWNLOAD_BOOST=1 \
  -DWITH_BOOST=/tmp/boost \
  -DWITHOUT_TOKUDB=1 \
  -DENABLE_DOWNLOADS=1 \
  -DWITH_READLINE=system
make -j$(( $(nproc) * 3 / 4 ))
```

A successful build means both CMake configuration and the build step complete without errors.

Do not use MySQL helper-script directories such as `BUILD` or `BUILD-CMAKE` as build output directories.

## Workflow

### 1. Prepare

1. Confirm all required inputs are set: `$BASE_BRANCH`, `$TIP_BRANCH`, `$DESTINATION_BASE_BRANCH`, `$REFERENCE_BRANCH`, `$OUTPUT_BRANCH`, `$LLM_MODEL`, and `$REPORT_FILE`.
2. Confirm the working tree is clean before starting.
3. If `$REPORT_FILE` is not specified, set it to `/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}.md`.
4. Set `$BUILD_DIR` to a directory under `/tmp` if not specified.
5. Create `$OUTPUT_BRANCH` from `$DESTINATION_BASE_BRANCH`.
6. Generate the ordered source list:

```sh
git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH
```

7. Identify the gcc-9 build-fix commit at the top of `$REFERENCE_BRANCH` when present and not included in `$BASE_BRANCH..$TIP_BRANCH`.
8. Identify commits whose subjects belong to the `"Initial Percona Server 5.6.22 tree"` group so they can be handled with least-conflict ordering.
9. Start a deferred-hunks ledger for cascade-causing changes that must be applied later with their dependent commit.

### 2. Apply The First gcc-9 Fix

When `$REFERENCE_BRANCH` has a final `Fix gcc-9 compilation issues` commit that is not in `$BASE_BRANCH..$TIP_BRANCH`, cherry-pick that commit first onto `$OUTPUT_BRANCH`.

Build-verify this first commit before applying source-range commits. Record it in `$REPORT_FILE` as an out-of-range build-fix commit applied first. If it is empty against `$DESTINATION_BASE_BRANCH`, skip it and record it as skipped.

### 3. Choose Commit Order

Default to the chronological order from `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH`.

For the `"Initial Percona Server 5.6.22 tree"` group:

1. Trial-apply each remaining candidate against the current `$OUTPUT_BRANCH` state.
2. Count conflicted files.
3. Select the candidate with the fewest conflicts.
4. Abort/reset the trial state.
5. Apply the selected commit for real.
6. Repeat until the group is exhausted.

Keep non-group commits in chronological order unless reordering clearly reduces conflicts or simplifies resolution. Record all order changes in `$REPORT_FILE`.

### 4. Cherry-Pick One Commit

For each selected commit:

```sh
git cherry-pick <sha>
```

If it applies cleanly, proceed directly to build verification.

If it conflicts:

1. Identify every conflicted file.
2. In each conflicted file, replace only the `<<<<<<<` / `=======` / `>>>>>>>` conflict regions with the corresponding content from `$REFERENCE_BRANCH`.
3. Leave non-conflicted regions untouched.
4. Stage the resolved files.
5. Continue the cherry-pick.

```sh
git add <resolved-files>
git cherry-pick --continue
```

Use `git show $REFERENCE_BRANCH:<path>` as the source of truth for the reference-side content. If a direct hunk replacement is ambiguous, inspect the matching region in `$REFERENCE_BRANCH` and resolve the conflict to that logic while keeping unrelated local context intact.

### 5. Drop Empty Cherry-Picks

Do not use `--allow-empty` and do not preserve marker commits that produce no tree change.

Skip the commit when:

1. `git cherry-pick <sha>` reports that the previous cherry-pick is empty.
2. Conflict resolution, hunk deferral, or reference-based fixes leave no staged or working-tree changes relative to `HEAD`.
3. The commit's changes are already present because an earlier commit, deferred hunk application, or build-fix fold introduced them.

Use the appropriate Git operation for the current state:

```sh
git cherry-pick --skip
```

or abort/reset the in-progress pick if no cherry-pick state remains. Record the skipped commit's original SHA, subject, and reason in `$REPORT_FILE`. There is no new SHA and no build step for a skipped empty commit because the tree did not change.

### 6. Defer Dependency-Cascade Hunks

The Percona 5.6.22 initial-tree commits are tightly coupled. Some changes are structurally correct only after another subdirectory lands. For example, a `vio/` change can alter `vio_shutdown(vio, type)` semantics and cascade into `sql/protocol_classic.cc`, `sql/sql_class.cc`, `sql/sql_class.h`, `handler.cc`, and related dependencies.

First try to keep the commit buildable by folding in the minimum necessary fixes or partial changes from later commits on `$REFERENCE_BRANCH`. Defer hunks only when those reference-derived fixes become cascading and very large.

When deferral is needed:

1. Keep the non-cascading parts of the commit.
2. Remove only the hunks that create cascading conflicts or compile failures.
3. Record each removed hunk in the deferred-hunks ledger with source commit, file, short reason, and target later commit or directory.
4. Apply the deferred hunk later with the dependent commit, such as a later `sql/` or `storage/` commit, where the required declarations, members, or APIs land together.
5. Build the current commit after the deferral and do not proceed until it passes.

Prefer small `$REFERENCE_BRANCH` fixes over targeted deferral. Prefer targeted deferral over broad snap-to-reference, over a non-buildable intermediate commit, and over creating a supercommit.

### 7. Restore Buildability

After each completed cherry-pick, run a clean build with the configured CMake options and make command.

If the build fails:

1. Diagnose the smallest set of files or changes responsible for the failure.
2. Port the minimum necessary fixes from `$REFERENCE_BRANCH`, including fixes that originate from later commits.
3. Keep those fixes in the current cherry-pick when they are required to make that commit build.
4. If those fixes become cascading and very large, defer only the offending hunks to the later commit that makes them coherent.
5. Rebuild until the commit passes.
6. Document every deferred hunk and every extra build-fix change in `$REPORT_FILE`.

Do not proceed to the next commit until the current commit builds, unless the current commit is the base commit of `$OUTPUT_BRANCH`.

### 8. Execution And Progress

Run the replay in the foreground unless the engineer explicitly asks to background it. Use a TaskList or todo tracker for the long workflow and summarize progress every 10-20 commits, including the current commit count, current phase, latest build result, and notable conflicts.

Long build commands may run for a while, but keep the agent session active by reporting progress when each build or batch completes.

### 9. Final Parity

After the final source commit is applied and build-verified:

```sh
git diff $OUTPUT_BRANCH $REFERENCE_BRANCH
```

If the diff is empty, record the null-diff confirmation in `$REPORT_FILE`.

If differences remain:

1. Add a final reconciliation commit that brings `$OUTPUT_BRANCH` to parity with `$REFERENCE_BRANCH`.
2. Re-run the build at the tip.
3. Confirm `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty.
4. Document the reconciliation commit and the residual differences it resolved.

## Report Requirements

Write `$REPORT_FILE` in markdown. It must include:

- The input branches and report path.
- `$LLM_MODEL`, `$BUILD_DIR`, and the build command used.
- The complete list of ported commits in the order applied, plus skipped empty source commits.
- The first gcc-9 build-fix commit, if applied before the source range.
- For each applied commit:
  - Original SHA from `$TIP_BRANCH`, or from `$REFERENCE_BRANCH` for the out-of-range gcc-9 build-fix commit.
  - New SHA on `$OUTPUT_BRANCH`.
  - One-line subject.
  - Whether it applied cleanly or required conflict resolution.
  - Build result for that commit.
- For each skipped empty commit:
  - Original SHA and one-line subject.
  - Reason it was empty.
  - Confirmation that no new SHA was created.
- For conflicted commits:
  - Conflicted files.
  - Short description of each conflict.
  - How each conflict was resolved, including the `$REFERENCE_BRANCH` hunk or logic used.
- A deferred-hunks section listing every cascade-causing hunk removed from an earlier commit, why it was deferred, and which later `sql/` or `storage/` commit applied it.
- Any reordering relative to `$BASE_BRANCH..$TIP_BRANCH`, with reasons.
- Any fixes or partial changes ported from later commits on `$REFERENCE_BRANCH` to preserve buildability.
- Final confirmation that `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty.
- The reconciliation commit SHA and explanation, if one was required.

## Stop Conditions

Stop and ask the engineer how to proceed if:

- `$REFERENCE_BRANCH` does not contain enough information to resolve a conflict.
- A dependency cascade cannot be isolated into targeted hunks for later `sql/` or `storage/` application.
- A commit cannot be made buildable without changes that are larger than the minimum needed for the current failure.
- The required toolchain or build dependencies are unavailable.
- The final tree cannot be reconciled to `$REFERENCE_BRANCH` without contradicting the requested commit history.

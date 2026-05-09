---
name: ps-replay+make-buildable
description: Use to replay Percona Server commits from a mysql-5.6.x BASE_BRANCH..TIP_BRANCH range onto a mysql-5.7.x destination base, resolving conflicts with hunk-level guidance from a known-buildable REFERENCE_BRANCH, preserving buildability through bucketing, incremental builds, and targeted fold/defer build fixes, and producing a final branch with null diff to the reference. Use when porting or rebasing a Percona Server commit range with per-commit build verification.
---

# Percona Server Replay And Make Buildable

## Purpose

Use this skill to port a Percona Server commit range while maintaining a buildable history and converging exactly to a known-good reference branch without snapping whole files or trees to that reference.

The task is complete only when:

1. `$OUTPUT_BRANCH` is rooted at the destination MySQL base, for example `mysql-5.7.9`.
2. The first non-base commit is the `$REFERENCE_BRANCH` gcc-9 build-fix commit when that fix is not in `$BASE_BRANCH..$TIP_BRANCH` but is required for final parity.
3. Every commit from `$BASE_BRANCH..$TIP_BRANCH` has been cherry-picked one at a time onto that destination base.
4. Empty cherry-picks are skipped, not preserved as empty commits.
5. Every source-touching commit on `$OUTPUT_BRANCH` builds successfully, except the destination base commit; no-build batches are verified at their batch boundary and documented.
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
5. Resolve conflicts using `$REFERENCE_BRANCH` as hunk-level or logic-level guidance, not as an automatic file replacement source. If `rerere` proposes a resolution, accept it only after verifying there are no conflict markers and the resolved content matches the intended reference logic.
6. Snap-to-REFERENCE is forbidden unless the engineer explicitly approves a named exception. Do not use `git checkout $REFERENCE_BRANCH -- <path>`, `git restore --source=$REFERENCE_BRANCH <path>`, `git show $REFERENCE_BRANCH:<path> > <path>`, `git read-tree $REFERENCE_BRANCH`, whole-file replacement, or final tree snapping as a routine conflict strategy.
7. When a commit does not build in isolation, classify the failure before editing: missing dependency to fold into the current commit, premature hunk to defer, incoherent source-only addition to remove, or unresolved design issue requiring engineer guidance.
8. First fold in the minimum necessary fixes or partial changes from later commits on `$REFERENCE_BRANCH`. If those changes become cascading and very large, remove only the hunks that cause dependency-cascade conflicts and defer them to the later commit that introduces the required dependency.
9. Use commit bucketing and incremental builds to improve throughput, but never carry a known source-touching build failure forward.
10. Build-verify after every completed source-touching commit, including the first gcc-9 fix commit and every cherry-picked source commit. No-build buckets may be applied in small batches and verified with one incremental build at the batch boundary. Only the destination base commit is exempt.
11. Never carry a non-buildable commit forward. If the current commit cannot be made buildable, stop at the last known buildable commit and ask the engineer for guidance.
12. Do not rely on a later merge, final source commit, or reconciliation commit to make earlier unbuildable commits coherent.
13. Do not create empty commits. If a cherry-pick becomes empty because its changes are already present or were intentionally deferred/applied elsewhere, skip it and document it.
14. The final tree must have a null diff to `$REFERENCE_BRANCH`.
15. If residual differences remain after all cherry-picks, add explicit reconciliation commits with path-level explanations; do not use tree snapping.
16. Do not use scripts from `/data/sh/utils`. Do not read files from `/data/sh/utils/reports/`. Writing `$REPORT_FILE` under `/data/sh/utils/reports/` is allowed.
17. Do not use the `percona_gca_sync_tdd` or `percona_conflict_resolution_tdd` skills.

## Build Configuration

Use an out-of-tree build directory under `/tmp`, and configure with these options unless the task explicitly overrides them:

```sh
CC=gcc-9 CXX=g++-9 cmake .. \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache \
  -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DMYSQL_MAINTAINER_MODE=OFF \
  -DDOWNLOAD_BOOST=1 \
  -DWITH_BOOST=/tmp/boost \
  -DWITHOUT_TOKUDB=1 \
  -DENABLE_DOWNLOADS=1 \
  -DWITH_READLINE=system
make -j$(( $(nproc) * 3 / 4 ))
```

A successful build means both CMake configuration and the build step complete without errors. Capture each build in a per-commit or per-batch log named with the source commit index and SHA. Prefer incremental builds in a stable `$BUILD_DIR` to preserve ccache and CMake state. Reconfigure or clean only when forced by CMake/cache breakage or a deep generated-header/build-system change. If a parallel build exits with truncated diagnostics, rerun `make` in the same build directory, optionally with `-j1`, only to expose the first actionable compiler or linker error; after fixing, rerun the normal configured build.

Use `ccache` through CMake compiler launchers, not by replacing `CC` or `CXX`; the underlying compilers remain `gcc-9` and `g++-9`. Do not use MySQL helper-script directories such as `BUILD` or `BUILD-CMAKE` as build output directories.

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
8. Start a deferred-hunks ledger for cascade-causing changes that must be applied later with their dependent commit.

### 2. Apply The First gcc-9 Fix

When `$REFERENCE_BRANCH` has a final `Fix gcc-9 compilation issues` commit that is not in `$BASE_BRANCH..$TIP_BRANCH`, cherry-pick that commit first onto `$OUTPUT_BRANCH`.

Build-verify this first commit before applying source-range commits. Record it in `$REPORT_FILE` as an out-of-range build-fix commit applied first. If it is empty against `$DESTINATION_BASE_BRANCH`, skip it and record it as skipped.

### 3. Choose Commit Order

Default to the chronological order from `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH`.

Keep commits in chronological order unless reordering clearly reduces conflicts or simplifies resolution. Record all order changes in `$REPORT_FILE`.

Before applying commits, bucket each source commit by changed paths with `git diff-tree --no-commit-id --name-only -r <sha>`:

- **No-build bucket**: docs, `build-ps/`, `man/`, `mysql-test/`, pure test result changes, packaging metadata, and scripts that do not affect compiled outputs. Apply in small chronological batches, then run one incremental build at the batch boundary.
- **Plugin-only bucket**: isolated `plugin/<name>/` changes. Apply singly or in very small batches; run an incremental build before proceeding past the bucket.
- **Source bucket**: `sql/`, `include/`, `storage/`, `vio/`, `mysys/`, `client/`, `libmysql/`, `cmake/`, generated headers, or build-system files. Apply singly and build immediately.
- **Empty-marker bucket**: marker commits or commits that become empty after hunk-level resolution. Skip and document; do not create empty commits.

If a supposedly no-build batch fails, stop, identify the source commit that caused the failure, document the mis-bucket, and resume with source-bucket rules.

### 4. Cherry-Pick One Commit

For each selected commit:

```sh
git cherry-pick <sha>
```

If it applies cleanly, proceed directly to build verification.

If it conflicts:

1. Identify every conflicted file.
2. Check whether `rerere` already resolved the file. If so, verify no `<<<<<<<` / `=======` / `>>>>>>>` markers remain and compare the result with `$REFERENCE_BRANCH` or the intended reference logic before staging it.
3. By default, replace only the conflict regions with the corresponding content from `$REFERENCE_BRANCH` and leave unrelated local context untouched.
4. Do not resolve by copying the whole file from `$REFERENCE_BRANCH`, even for test fixtures, generated/preprocessed headers, version files, or coherent API families. Use hunk-level edits. If whole-file replacement seems necessary, stop and ask for explicit approval for the named file and reason.
5. If the file does not exist on `$REFERENCE_BRANCH`, remove only the conflicting addition/deletion hunk when that is the hunk-level reference logic. Do not delete the whole file unless the entire file is the conflicting change and the engineer-approved resolution is removal.
6. Stage the resolved files.
7. Continue the cherry-pick.

```sh
git add <resolved-files>
git cherry-pick --continue
```

Use `git show $REFERENCE_BRANCH:<path>` only for inspection or for copying the specific conflict-region text. Do not redirect it over the worktree file. If a direct hunk replacement is ambiguous, inspect the matching region in `$REFERENCE_BRANCH` and resolve the conflict to that logic while keeping unrelated local context intact. If safe hunk-level resolution is not possible, stop and ask the engineer.

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

First try to keep the commit buildable by folding in the minimum necessary fixes or partial changes from later commits on `$REFERENCE_BRANCH`. Defer hunks only when those reference-derived fixes become cascading and very large.

When deferral is needed:

1. Keep the non-cascading parts of the commit.
2. Remove only the hunks that create cascading conflicts or compile failures.
3. Record each removed hunk in the deferred-hunks ledger with source commit, file, short reason, and target later commit or directory.
4. Apply the deferred hunk later with the dependent commit, such as a later commit, where the required declarations, members, or APIs land together.
5. Build the current commit after the deferral and do not proceed until it passes.

Prefer small `$REFERENCE_BRANCH` fixes over targeted deferral. Prefer targeted deferral over a non-buildable intermediate commit and over creating a supercommit. Do not use broad snap-to-reference.

Common deferral candidates:

- Header/API hunks that introduce fields, enum values, declarations, or function signatures before the implementation or all call sites arrive.
- Generated or preprocessed plugin headers that must stay ABI-consistent with their canonical headers.
- SQL command enum additions that require matching status arrays, parser use sites, or instrumentation tables.
- Storage-engine struct changes that require matching storage implementation files from a later commit.

When the dependent commit arrives, apply the deferred hunk there and record that the earlier deferral has been reconciled.

### 7. Build-Driven Fixes

Use the build log as the authority for intermediate fixes. Do not guess from the final reference tree alone.

For each build failure:

1. Identify the first real error, not just the final `Error 2`.
2. Map the error to the smallest inconsistent surface: declaration/type mismatch, enum/table mismatch, missing member, missing source file, incoherent CMake entry, unresolved symbol, or ABI check mismatch.
3. Compare the current commit, `HEAD^`, the source commit, and `$REFERENCE_BRANCH` for the affected files.
4. Choose one of these actions:
   - **Fold**: add the smallest required reference or source-required declaration/member/enum entry to the current commit.
   - **Defer**: remove a premature hunk from the current commit and apply it later with its dependent implementation.
   - **Align hunks**: edit the smallest coherent set of hunks to match the reference API family while preserving unrelated current-commit content.
   - **Remove**: delete source-only files or CMake entries that are not present in the reference branch and cannot build coherently in this intermediate commit.
   - **Stop**: ask the engineer when the required fix is larger than the current failure justifies.
5. Rewrite only the current replayed commit after the fix. Do not alter already build-verified earlier commits unless the engineer explicitly approves.
6. Rebuild and repeat until the current commit passes.

Examples of valid build-driven fixes:

- Defer a header struct/API hunk until the later commit that introduces the matching implementation.
- Fold a missing plugin declaration or PSI member when current source files already require it.
- Temporarily add source-required enum entries when parser/use sites exist in the current commit, then let final parity remove them later if absent from `$REFERENCE_BRANCH`.
- Align the specific InnoDB log header and implementation hunks needed for a coherent reference API family.
- Remove a source-only implementation file and its CMake entry when the reference branch has no coherent matching API.

### 8. Restore Buildability

After each completed source-touching cherry-pick, run an incremental build in the configured `$BUILD_DIR`. After each no-build batch, run one incremental build. Use a clean build only for the first verification, after CMake/cache breakage, after build-system/generated-header changes that invalidate incremental trust, or for final confidence when time permits.

Before starting each cherry-pick, record `LAST_GOOD=HEAD`. `$OUTPUT_BRANCH` must never be left pointing at a commit that has not passed its build.

If the build fails:

1. Follow the Build-Driven Fixes decision loop.
2. Keep folded fixes in the current cherry-pick only when required to make that commit build.
3. Defer only the offending hunks to the later commit that makes them coherent.
4. Rebuild until the commit passes.
5. Document every deferred hunk, folded fix, aligned hunk set, removed source-only file, and rewritten commit SHA in `$REPORT_FILE`.

If the commit still cannot be made buildable:

1. Capture the failing commit SHA if one was created, the source commit SHA, the failing build summary, and the attempted fixes in `$REPORT_FILE`.
2. Return `$OUTPUT_BRANCH` to `LAST_GOOD` before asking for guidance. If a cherry-pick is still in progress, abort it; if a failing commit was already created, move the branch back to `LAST_GOOD` after preserving diagnostics.
3. Ask the engineer whether to split the source commit, defer a specific named hunk, reorder a small set of commits, or apply a larger approved reference-derived fix.

Do not proceed to the next commit until the current commit builds, unless the current commit is the base commit of `$OUTPUT_BRANCH`. Do not create a "mid-chain build failures carried into final commit" or "fat-tail" block where a later merge/final commit repairs earlier unbuildable commits.

### 9. Execution And Progress

Run the replay in the foreground unless the engineer explicitly asks to background it. Use a TaskList or todo tracker for the long workflow and summarize progress every 10-20 commits, including the current commit count, current phase, latest build result, and notable conflicts.

Long build commands may run for a while, but keep the agent session active by reporting progress when each build or batch completes.

### 10. Utility Scripts

Use only helper scripts whose behavior matches the mandatory rules above. The mandatory rules override all scripts.

- `scripts/ps_replay_batch.py`: replay a bounded 1-based commit range from a source-list file, build non-empty commits with ccache compiler launchers, and stop on the first build failure. Do not use it on conflicted ranges until its conflict handling is changed to hunk-only behavior.
- `scripts/ps_replay_resolve_conflicts.py`: historical snap-capable helper for current cherry-pick conflicts. Do not use until changed to hunk-only behavior or explicitly approved for named files.
- `scripts/ps_replay_build.py`: run a clean or incremental build with the standard gcc-9/g++-9 and ccache launcher configuration, writing a per-run log.
- `scripts/ps_replay_errors.py`: extract likely root-cause compiler, linker, CMake, and ABI diagnostics from large build logs when the terminal output is truncated.

Example build-failure diagnosis:

```sh
python3 scripts/ps_replay_errors.py /tmp/ps-replay-${OUTPUT_BRANCH}-logs/build-58-812714fe16da-ccache.log
python3 scripts/ps_replay_build.py --worktree "$WORKTREE" --build-dir "$BUILD_DIR" --log /tmp/rebuild.log --incremental
```

Do not use helper modes that perform whole-file or whole-tree reference replacement. The current `ps_replay_batch.py`, `ps_replay_resolve_conflicts.py`, `snap_tip.sh`, and `snap_range.sh` are snap-capable historical helpers unless they are first changed to hunk-only behavior. The older shell scripts in `scripts/` are historical helpers. Do not use them when they conflict with this skill's current rules, especially the no-empty-commit, hunk-only conflict resolution, and source-touching build requirements.

### 11. Final Parity

After the final source commit is applied and build-verified:

```sh
git diff $OUTPUT_BRANCH $REFERENCE_BRANCH
```

If the diff is empty, record the null-diff confirmation in `$REPORT_FILE`.

If differences remain:

1. Add one or more explicit reconciliation commits that bring `$OUTPUT_BRANCH` to parity with `$REFERENCE_BRANCH` through reviewed path/hunk-level edits.
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
- A deferred-hunks section listing every cascade-causing hunk removed from an earlier commit, why it was deferred, and which later commit applied it.
- A build-driven fixes section listing every folded declaration/member/enum, reference-aligned hunk set, removed source-only file or CMake entry, and the build error it fixed.
- Any reordering relative to `$BASE_BRANCH..$TIP_BRANCH`, with reasons.
- Commit bucket classification, batching decisions, and any mis-bucket corrections.
- Any fixes or partial changes ported from later commits on `$REFERENCE_BRANCH` to preserve buildability.
- Any commit rewrite caused by build fixes, including failed SHA, final SHA, and build log path.
- Confirmation that no non-buildable commits remain on `$OUTPUT_BRANCH`; if the run stopped, identify the last known buildable commit and the blocked source commit.
- Final confirmation that `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty.
- The reconciliation commit SHA and explanation, if one was required.

## Stop Conditions

Stop and ask the engineer how to proceed if:

- `$REFERENCE_BRANCH` does not contain enough information to resolve a conflict.
- A dependency cascade cannot be isolated into targeted hunks for later application.
- A conflict appears to require whole-file or whole-tree reference replacement and the engineer has not explicitly approved that named exception.
- A commit cannot be made buildable without changes that are larger than the minimum needed for the current failure.
- A commit remains non-buildable after minimal `$REFERENCE_BRANCH` fixes and targeted hunk deferral. Stop at the last known buildable commit; do not carry the failure forward.
- The required toolchain or build dependencies are unavailable.
- The final tree cannot be reconciled to `$REFERENCE_BRANCH` without contradicting the requested commit history.

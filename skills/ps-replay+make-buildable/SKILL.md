---
name: ps-replay+make-buildable
description: Use to replay Percona Server commits from a mysql-5.6.x BASE_BRANCH..TIP_BRANCH range onto a mysql-5.7.x destination base, resolving conflicts with hunk-level guidance from a known-buildable REFERENCE_BRANCH, preserving buildability through bucketing, incremental builds, and targeted fold/defer build fixes, and producing a final branch with null diff to the reference. Use when porting or rebasing a Percona Server commit range with Group 7 marker checkpoint build verification.
---

# Percona Server Replay And Make Buildable

## Purpose

Use this skill to port a Percona Server commit range while maintaining a buildable history and converging exactly to a known-good reference branch without snapping whole files or trees to that reference.

The task is complete only when:

1. `$OUTPUT_BRANCH` is rooted at the destination MySQL base, for example `mysql-5.7.9`.
2. Every commit from `$BASE_BRANCH..$TIP_BRANCH` has been cherry-picked one at a time onto that destination base.
3. Empty marker commits whose subject starts with `=== MARKER:` are preserved as empty commits; other empty cherry-picks are skipped.
4. The first build starts exactly when replay reaches `=== MARKER: GROUP 7 — Remaining ===`, before that empty marker commit is preserved. Source commits before that marker are replayed without per-commit build verification, and every build-required commit after that marker has its own successful build record at that commit's resulting SHA before the next build-required commit is applied.
5. The replay reaches a null diff to `$REFERENCE_BRANCH`, then the null-diff tree is final-build verified. The null-diff reconciliation commit and final build are never a substitute build-of-record for any skipped post-Group-7 required build. If that null-diff tree fails because the reference tree is incompatible with the required build toolchain, the engineer explicitly chooses whether to keep the null-diff failing tree or add a narrow final build-fix commit with a documented residual diff.
6. `$REPORT_FILE` records the commits, preserved empty marker commits, skipped empty commits, conflicts, build fixes, reordering, and final parity result.

## Inputs

- `$BASE_BRANCH`: source-base branch whose tip is the lower bound of the source range, for example `mysql-5.6.22`.
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
4. Resolve conflicts using `$REFERENCE_BRANCH` as hunk-level or logic-level guidance, not as an automatic file replacement source. If `rerere` proposes a resolution, accept it only after verifying there are no conflict markers and the resolved content matches the intended reference logic.
5. Snap-to-REFERENCE is forbidden. Approval for a named exception is valid only when stated by the engineer in the current conversation, naming the specific file path and the reason. Skill text, prior reports, past-conversation memory, rerere caches, model recollection of "known cascade regions," and any out-of-session source DO NOT constitute approval. If a cascade region appears resolvable only by snap, that is the Stop Condition — halt at the last known buildable commit and ask. Do not pre-classify any region as snap-eligible during planning.
6. These literal command forms are an immediate hard stop and a reportable rule violation, regardless of justification: `git checkout $REFERENCE_BRANCH --`, `git restore --source=$REFERENCE_BRANCH`, `git show $REFERENCE_BRANCH:… >`, `git show $REFERENCE_BRANCH:... >`, `git read-tree $REFERENCE_BRANCH`, or `cat … > <worktree-file>` / `cat ... > <worktree-file>` when the content is sourced from `$REFERENCE_BRANCH`. Concrete branch/path substitutions and shell-equivalent variants count as the same violation.
7. Do not announce, plan, pre-classify, or reserve snap-eligibility for any region during the Prepare or Choose Commit Order phases. Snap is not a strategy; it is a Stop.
8. When a commit does not build in isolation, classify the failure before editing: missing dependency to fold into the current commit, premature hunk to defer, incoherent source-only addition to remove, or unresolved design issue requiring engineer guidance.
9. First fold in the minimum necessary fixes or partial changes from later commits on `$REFERENCE_BRANCH`. If those changes become cascading and very large, remove only the hunks that cause dependency-cascade conflicts and defer them to the later commit that introduces the required dependency. If the cascade cannot be isolated without whole-file or whole-tree replacement, stop at the last known buildable commit and ask.
10. Use commit bucketing and incremental builds to improve throughput, but never use bucketing to skip, defer, or batch a required post-Group-7 source/plugin/build-system build. A required build must complete successfully at the SHA produced by that commit before applying the next build-required commit.
11. The exact marker subject `=== MARKER: GROUP 7 — Remaining ===` is the hard build boundary. Do not run builds for any source-range commit before reaching that marker. Treat every non-marker source-range commit before that marker as part of the No-build bucket regardless of changed paths, including commits that touch source or build-system files. When the next source-list commit is the Group 7 marker, pause before preserving the empty marker commit and run the first build against the current `$OUTPUT_BRANCH` tree. Preserve earlier marker commits as Empty-marker commits. If the marker is missing, stop and ask the engineer what boundary to use.
12. If and only if `$BASE_BRANCH` is exactly `mysql-5.6.22`, apply the branch-specific initial-tree ordering rules in [mysql-5.6.22-initial-tree-ordering.md](mysql-5.6.22-initial-tree-ordering.md). For other base branches, do not use those rules unless the engineer explicitly requests them in the current conversation.
13. For source-range commits before the Group 7 marker, do not run per-commit builds. The first build must start exactly at the Group 7 marker checkpoint, before the marker commit itself is created. For source-range commits after the Group 7 marker, build-verify every completed source/plugin/build-system commit and any other commit selected by the active build policy at that commit's resulting SHA before applying the next build-required commit. Only the destination base commit, pre-Group-7 source-range commits, and empty marker commits are exempt from their otherwise-required build record.
14. If the first build run at the Group 7 marker checkpoint fails with compilation issues, apply the minimal fixes in one or more new commits before preserving the `=== MARKER: GROUP 7 — Remaining ===` marker itself. Each fix commit subject must start with `[compilation]` exactly, then rebuild before preserving the marker and proceeding.
15. Never carry a known non-buildable build-required commit forward. If the current build-required commit cannot be made buildable, stop at the last known buildable commit and ask the engineer for guidance.
16. Do not rely on a later merge, final source commit, reconciliation commit, or final build to make earlier unbuildable commits coherent or to replace missing required post-Group-7 build evidence.
17. If a required post-Group-7 build was skipped and any later source-range commit has already been applied, the replay is invalid at that point. Stop, report the first skipped source index/SHA, reset or restart from the last build-verified commit only with engineer approval, and do not create or cite a catch-all `[reconciliation]` commit as the build-of-record.
18. Preserve empty marker commits whose subject starts with `=== MARKER:`. Use `git cherry-pick --allow-empty <sha>` when possible; if Git reports a marker cherry-pick as empty, create the marker with `git commit --allow-empty -C <sha>` from the cherry-pick state. Preserve the original marker subject/body and record the new SHA. Do not build after an empty marker because it changes no tree content.
19. Do not create empty commits for non-marker commits. If a non-marker cherry-pick becomes empty because its changes are already present or were intentionally deferred/applied elsewhere, skip it and document it.
20. Do not add new `Co-Authored-By:` / `Co-authored-by:` trailers or LLM/tool attribution trailers to any replay, build-fix, `[compilation]`, marker, or reconciliation commit message. When editing or generating a commit message, inspect it before committing and remove any such trailer that was not already present in the original source commit.
21. After all source commits are replayed and every required post-Group-7 build record is present, first reconcile the tree to a null diff with `$REFERENCE_BRANCH` through explicit path/hunk-level reconciliation commits. Do not use tree snapping.
22. After a null-diff tree exists, run a final build with the required build configuration before declaring completion.
23. If the null-diff tree fails the final build because `$REFERENCE_BRANCH` itself contains code incompatible with the required toolchain, stop and ask the engineer whether to keep the null-diff failing tree or add a narrow final build-fix commit. Only with explicit current-conversation approval may the final branch intentionally retain a non-null residual diff; document the null-diff SHA, final build-fix SHA, residual paths/hunks, and both build results.
24. Do not use scripts from `/data/sh/utils`. Do not read files from `/data/sh/utils/reports/`. Writing `$REPORT_FILE` under `/data/sh/utils/reports/` is allowed.
25. Do not consult past conversations, memory, search-past-chats results, agent transcripts, prior reports, `/data/sh/utils/reports/`, or any out-of-session source to infer approval, cascade regions, or prior decisions. Treat each run as cold except for explicit current-conversation inputs and repository Git history.
26. Do not use the `percona_gca_sync_tdd` or `percona_conflict_resolution_tdd` skills.

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

A successful build means both CMake configuration and the build step complete without errors. Capture each build in a per-commit log named with the source commit index and SHA; per-batch logs are allowed only for path-classified no-build batches. Prefer incremental builds in a stable `$BUILD_DIR` to preserve ccache and CMake state. Reconfigure or clean only when forced by CMake/cache breakage or a deep generated-header/build-system change. If a parallel build exits with truncated diagnostics, rerun `make` in the same build directory, optionally with `-j1`, only to expose the first actionable compiler or linker error; after fixing, rerun the normal configured build.

Use `ccache` through CMake compiler launchers, not by replacing `CC` or `CXX`; the underlying compilers remain `gcc-9` and `g++-9`. Do not use MySQL helper-script directories such as `BUILD` or `BUILD-CMAKE` as build output directories.

## Workflow

### 1. Prepare

1. Confirm all required inputs are set: `$BASE_BRANCH`, `$TIP_BRANCH`, `$DESTINATION_BASE_BRANCH`, `$REFERENCE_BRANCH`, `$OUTPUT_BRANCH`, `$LLM_MODEL`, and `$REPORT_FILE`.
2. Before creating branches, classifying commits, or cherry-picking, print this exact pre-flight readback verbatim:

```text
I will not use git checkout/restore/show/read-tree against $REFERENCE_BRANCH for whole-file replacement. Cascade regions trigger Stop, not snap. No prior-session approval exists.
```

If the readback is missing or paraphrased, abort the run.

3. Confirm the working tree is clean before starting.
4. If `$REPORT_FILE` is not specified, set it to `/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}.md`.
5. Set `$BUILD_DIR` to a directory under `/tmp` if not specified.
6. Generate the ordered source list:

```sh
git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH
```

7. Inspect the ordered source list subjects and verify the exact marker `=== MARKER: GROUP 7 — Remaining ===` exists. Record its 1-based source index as the Group 7 boundary. If it is missing, stop and ask the engineer what to do; do not infer a fallback boundary.
8. If `$BASE_BRANCH` is exactly `mysql-5.6.22`, read [mysql-5.6.22-initial-tree-ordering.md](mysql-5.6.22-initial-tree-ordering.md) and identify source-list commits whose subjects start with `Initial Percona Server 5.6.22 tree`. If `$BASE_BRANCH` is not exactly `mysql-5.6.22`, do not apply those branch-specific ordering rules.
9. Create `$OUTPUT_BRANCH` from `$DESTINATION_BASE_BRANCH`.
10. Start a deferred-hunks ledger for cascade-causing changes that must be applied later with their dependent commit.

### 2. Choose Commit Order

Default to the chronological order from `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH`.

Keep commits in chronological order unless reordering clearly reduces conflicts or simplifies resolution. Record all order changes in `$REPORT_FILE`.

Exception: when `$BASE_BRANCH` is exactly `mysql-5.6.22`, use [mysql-5.6.22-initial-tree-ordering.md](mysql-5.6.22-initial-tree-ordering.md) for commits whose subjects start with `Initial Percona Server 5.6.22 tree`. Select the next commit in that group dynamically by least conflicted files against the current `$OUTPUT_BRANCH` state, then apply the selected commit for real. This exception does not apply to any other `$BASE_BRANCH`.

Before applying commits, first bucket by the Group 7 boundary and then by changed paths:

1. For each non-marker source commit whose 1-based index is less than the `=== MARKER: GROUP 7 — Remaining ===` index, force the bucket to **No-build bucket** regardless of changed paths. This includes commits that touch `sql/`, `include/`, `storage/`, `cmake/`, generated headers, or any other source/build-system path.
2. The exact Group 7 marker is a **Boundary-build checkpoint**: run the first build before preserving the marker commit, create any required `[compilation]` fix commits before the marker itself, then preserve the marker as an empty commit after the boundary build passes.
3. For non-marker commits after the Group 7 marker, bucket by changed paths with `git diff-tree --no-commit-id --name-only -r <sha>`. Source/plugin/build-system buckets are build-required and must not be merged into a later catch-up build.
4. Other marker commits always use **Empty-marker bucket**, including marker commits that appear before Group 7.

- **Forced pre-Group-7 no-build bucket**: apply commits before Group 7 in chronological batches without running builds.
- **Boundary-build checkpoint**: at the exact `=== MARKER: GROUP 7 — Remaining ===` source-list position, run the first build against the current tree before creating the marker commit. If compilation fixes are needed, commit them as `[compilation]` commits before the marker, rebuild until the boundary passes, then preserve the marker as an empty commit.
- **Path-classified no-build bucket**: after Group 7, this bucket covers docs, `build-ps/`, `man/`, `mysql-test/`, pure test result changes, packaging metadata, and scripts that do not affect compiled outputs; apply those in small chronological batches, then run one incremental build at the batch boundary. Do not place any source/plugin/build-system change in this bucket.
- **Plugin-only bucket**: isolated `plugin/<name>/` changes. Apply singly and build immediately at the resulting SHA before applying the next build-required commit.
- **Source bucket**: `sql/`, `include/`, `storage/`, `vio/`, `mysys/`, `client/`, `libmysql/`, `cmake/`, generated headers, or build-system files. Apply singly and build immediately at the resulting SHA before applying the next build-required commit.
- **Empty-marker bucket**: commits whose subject starts with `=== MARKER:`. Preserve them as empty commits with `--allow-empty`, record the new SHA, and do not build because they change no tree content.

Do not run build-failure diagnosis for pre-Group-7 no-build batches because no build is run there. The first build-failure diagnosis may happen only at the Group 7 marker checkpoint. If a path-classified no-build batch after Group 7 fails, stop, identify the source commit that caused the failure, document the mis-bucket, and resume with source-bucket rules. If a source/plugin/build-system commit after Group 7 was applied without its required immediate build, stop and treat the run as invalid from the first skipped build; do not continue to final reconciliation.

### 3. Cherry-Pick One Commit

For each selected commit:

```sh
git cherry-pick <sha>
```

If it applies cleanly, proceed directly to the next build required by the active build policy.

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

Use `git show $REFERENCE_BRANCH:<path>` only for inspection or for copying the specific conflict-region text into a manual hunk edit. Do not redirect, pipe, or copy the whole reference blob over the worktree file. If a direct hunk replacement is ambiguous, inspect the matching region in `$REFERENCE_BRANCH` and resolve the conflict to that logic while keeping unrelated local context intact. If safe hunk-level resolution is not possible, stop and ask the engineer.

### 4. Preserve Marker Commits And Drop Other Empty Cherry-Picks

Preserve empty marker commits whose subject starts with `=== MARKER:`. These commits are intentional history separators such as `=== MARKER: GROUP 2 — build-ps ===`, and they must remain present on `$OUTPUT_BRANCH` even when they produce no tree change.

For marker commits:

1. Prefer `git cherry-pick --allow-empty <sha>`.
2. If Git reports that the marker cherry-pick is empty, use `git commit --allow-empty -C <sha>` from the cherry-pick state to preserve the original subject/body and authorship.
3. Do not add `Co-Authored-By:` or other LLM/tool attribution trailers.
4. Record the original SHA, new SHA, subject, and confirmation that no build was run because the tree did not change.

For non-marker commits, do not use `--allow-empty`.

Skip the commit when:

1. `git cherry-pick <sha>` reports that the previous non-marker cherry-pick is empty.
2. Conflict resolution, hunk deferral, or reference-based fixes leave no staged or working-tree changes relative to `HEAD`.
3. The commit's changes are already present because an earlier commit, deferred hunk application, or build-fix fold introduced them.

Use the appropriate Git operation for the current state:

```sh
git cherry-pick --skip
```

or abort/reset the in-progress pick if no cherry-pick state remains. Record the skipped commit's original SHA, subject, and reason in `$REPORT_FILE`. There is no new SHA and no build step for a skipped empty non-marker commit because the tree did not change.

### 5. Defer Dependency-Cascade Hunks

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

### 6. Build-Driven Fixes

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
5. Rewrite only the current replayed commit after the fix. Exception: for the first Group 7 marker checkpoint build, compilation fixes must be committed as new `[compilation]` commit(s) immediately before preserving the `=== MARKER: GROUP 7 — Remaining ===` marker itself. Do not alter already build-verified earlier commits unless the engineer explicitly approves.
6. Rebuild and repeat until the current commit passes.

Examples of valid build-driven fixes:

- Defer a header struct/API hunk until the later commit that introduces the matching implementation.
- Fold a missing plugin declaration or PSI member when current source files already require it.
- Temporarily add source-required enum entries when parser/use sites exist in the current commit, then let final parity remove them later if absent from `$REFERENCE_BRANCH`.
- Align the specific InnoDB log header and implementation hunks needed for a coherent reference API family.
- Remove a source-only implementation file and its CMake entry when the reference branch has no coherent matching API.

### 7. Restore Buildability

When replay reaches the exact `=== MARKER: GROUP 7 — Remaining ===` source-list commit, run the first build in the configured `$BUILD_DIR` before preserving that marker as an empty commit. After each completed source/plugin/build-system cherry-pick after Group 7, run an incremental build at that commit's resulting SHA before applying the next build-required commit. After each path-classified no-build batch after Group 7, run one incremental build. Do not build for any source-range commit before the Group 7 marker checkpoint. Use a clean build only for the first verification, after CMake/cache breakage, after build-system/generated-header changes that invalidate incremental trust, or for final confidence when time permits.

Before starting the Group 7 marker checkpoint build or any later build-verified cherry-pick, record `LAST_GOOD=HEAD`. `$OUTPUT_BRANCH` must never be left pointing at a boundary-fix commit or post-Group-7 build-required commit that has not passed its required build. Missing required build evidence is a stop condition, not a reportable deferral.

If the build fails:

1. Follow the Build-Driven Fixes decision loop.
2. If this is the first build run at the Group 7 marker checkpoint and the failure is a compilation issue, keep the pending marker uncommitted, apply the minimal fixes in the working tree, and create one or more new commits whose subjects start with `[compilation]`. These fix commits must be committed before the `=== MARKER: GROUP 7 — Remaining ===` marker itself.
3. For later build failures, keep folded fixes in the current cherry-pick only when required to make that commit build.
4. Defer only the offending hunks to the later commit that makes them coherent.
5. Rebuild until the commit passes.
6. Document every deferred hunk, folded fix, aligned hunk set, removed source-only file, rewritten commit SHA, and `[compilation]` fix commit SHA in `$REPORT_FILE`.

If the commit still cannot be made buildable:

1. Capture the failing commit SHA if one was created, the source commit SHA, the failing build summary, and the attempted fixes in `$REPORT_FILE`.
2. Return `$OUTPUT_BRANCH` to `LAST_GOOD` before asking for guidance. If a cherry-pick is still in progress, abort it; if a failing commit was already created, move the branch back to `LAST_GOOD` after preserving diagnostics.
3. Ask the engineer whether to split the source commit, defer a specific named hunk, reorder a small set of commits, or apply a larger approved reference-derived fix.

Do not preserve the Group 7 marker or proceed to the next post-Group-7 build-required commit until the current checkpoint or commit builds, unless the current commit is the base commit of `$OUTPUT_BRANCH`. Do not create a "mid-chain build failures carried into final commit", "fat-tail", or "deferred builds covered by reconciliation" block where a later merge/final/reconciliation commit repairs or substitutes for earlier build-required commits.

### 8. Execution And Progress

Run the replay in the foreground unless the engineer explicitly asks to background it. Use a TaskList or todo tracker for the long workflow and summarize progress every 10-20 commits, including the current commit count, current phase, latest build result, and notable conflicts.

Long build commands may run for a while, but keep the agent session active by reporting progress when each build or batch completes.

### 9. Direct Execution And Optional Utility Scripts

Direct Git and build commands are the default, portable implementation of this skill. Do not require repository-local replay helper scripts to exist before starting.

Helper scripts are bundled with this skill at:

```sh
/home/przemek/.agents/skills/ps-replay+make-buildable/scripts
```

Before falling back to direct execution, check that bundled directory first. If it is unavailable, check repo-local `scripts/`. If neither location contains the needed helper, continue by driving `git cherry-pick`, conflict inspection, hunk-level edits, and the configured CMake/make build commands directly.

When helper scripts are present, use only scripts whose behavior matches the mandatory rules above. The mandatory rules override all scripts. Missing helper scripts are not a blocker and should not be treated as a failure; mention their absence only briefly in progress/reporting if it affects how the run was driven.

Do not switch to a helper solely because it exists if that helper would violate the selected bucket strategy. Use `ps_replay_batch.py --build-policy bucketed` when replaying a classified mixed range only if it build-verifies each post-Group-7 source/plugin/build-system commit at that commit's resulting SHA before applying the next build-required commit: it cherry-picks one commit at a time, preserves empty marker commits, skips empty non-marker commits, stops on conflicts, forces every non-marker commit before `=== MARKER: GROUP 7 — Remaining ===` into the no-build bucket without running builds, runs the first build at the Group 7 marker checkpoint before preserving that marker, and applies the configured build policy after Group 7. Use `--classify-only` first when you want to inspect its bucket decisions before replay. A small auditable driver script under `/tmp` is still acceptable if a run needs behavior that the bundled helper does not support. Prefer `ps_replay_build.py` for the actual build command and `ps_replay_errors.py` for diagnostics even when the cherry-pick driver is custom.

Always preserve these direct-execution invariants, whether using scripts or hand-written shell loops:

1. Generate the source list with `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH`.
2. Locate the exact `=== MARKER: GROUP 7 — Remaining ===` subject in the source list before classification. Stop if it is missing.
3. Force every non-marker commit before the Group 7 marker into the no-build bucket before considering changed paths.
4. Treat the exact Group 7 marker as the first-build checkpoint: run the first build before preserving the marker as an empty commit, and create any required `[compilation]` fix commits before the marker itself.
5. Classify non-marker commits after Group 7 by touched paths before batching, using `git diff-tree --no-commit-id --name-only -r <sha>`.
6. Apply pre-Group-7 no-build batches only in small chronological groups and do not build them.
7. Apply post-Group-7 no-build batches in small chronological groups and run an incremental build at each batch boundary.
8. Apply source/plugin/build-system commits after Group 7 singly and build immediately at the resulting SHA before applying the next build-required commit.
9. Stop on the first conflict, build failure, or missing required build record; do not let an automation loop auto-resolve conflicts, defer required builds, or carry failures forward.
10. If the first Group 7 marker checkpoint build fails with compilation issues, create the required `[compilation]` fix commit(s) before preserving the marker and before replaying the next source commit.
11. Log each source index, original SHA, new SHA if any, subject, bucket, whether the no-build bucket was forced by the pre-Group-7 rule, apply status, and build result or no-build exemption. For every post-Group-7 source/plugin/build-system commit, the log must include that commit's own build log path and PASS result; `deferred`, `covered by reconciliation`, `final build-of-record`, or similar wording is a failure.

- `ps_replay_batch.py`: replay a bounded 1-based commit range from a source-list file, stop without modifying files on the first conflict, preserve empty marker commits, skip empty non-marker commits, and stop on the first build failure or missing required build record. It requires the exact Group 7 marker by default, forces every non-marker commit before that marker into the no-build bucket without running builds, and treats the marker as the first-build checkpoint before preserving it as an empty commit. Default `--build-policy always` now applies after Group 7. `--build-policy bucketed` classifies post-Group-7 commits by changed paths, builds source/plugin/build-system commits immediately at each commit's resulting SHA, builds no-build runs at `--nobuild-fence-size` or before crossing into source/plugin/build-system work, and delegates build execution to `ps_replay_build.py` when available. Use `--classify-only` first to print TSV bucket decisions without modifying the worktree.
- `ps_replay_resolve_conflicts.py`: inspect current cherry-pick conflicts and print conflict blocks plus nearby `$REFERENCE_BRANCH` snippets for manual hunk-level resolution. It does not modify or stage files.
- `ps_replay_build.py`: run a clean or incremental build with the standard gcc-9/g++-9 and ccache launcher configuration, writing a per-run log.
- `ps_replay_errors.py`: extract likely root-cause compiler, linker, CMake, and ABI diagnostics from large build logs when the terminal output is truncated.
- `ps_replay_scan_range.py`: scan `$BASE..$REFERENCE` (and `$BASE..$TIP` when they differ) for special commits — snap commits, markers, squashes — and surface commits in reference but not in tip. Run this in the Prepare phase before generating the source list so reference-only commits cannot be silently missed.
- `ps_replay_conflict_triage.py`: after a batch stop, classify every conflicted file as `auto-match` (rerere matches reference; safe to stage), `auto-mismatch` (rerere resolved but content differs from reference; review needed), or `unresolved` (markers still present). Use `--auto-stage` to `git add` the auto-match files only; the rest are left for manual hunk-level work. Run this before doing any per-file inspection.
- `ps_replay_residual_audit.py`: classify hunks in `git diff $OUTPUT $REFERENCE` as whitespace / trivial / substantive. Use it during Final Parity to decide what (if anything) needs a reconciliation commit and to confirm there are no substantive deltas remaining.
- `ps_replay_least_conflict.py`: only for `$BASE_BRANCH=mysql-5.6.22`, rank remaining `Initial Percona Server 5.6.22 tree` candidates by trial-applying each candidate in a temporary worktree and counting conflicted files. It does not apply the selected commit for real; use it to choose the next candidate, then cherry-pick manually under the main rules.

Example build-failure diagnosis:

```sh
SKILL_SCRIPT_DIR=/home/przemek/.agents/skills/ps-replay+make-buildable/scripts
python3 "$SKILL_SCRIPT_DIR/ps_replay_errors.py" /tmp/ps-replay-${OUTPUT_BRANCH}-logs/build-58-812714fe16da-ccache.log
python3 "$SKILL_SCRIPT_DIR/ps_replay_build.py" --worktree "$WORKTREE" --build-dir "$BUILD_DIR" --log /tmp/rebuild.log --incremental
```

Do not use helper modes that perform whole-file or whole-tree reference replacement. If historical `snap_*` helpers are present, treat them as disabled unless the engineer explicitly approves a named exception in the current conversation with the specific file path and reason. The mandatory preserve-empty-marker, skip-empty-non-marker, no-added-coauthor-trailer, hunk-only conflict resolution, post-Group-7 source/plugin/build-system build, and no-prior-session-approval requirements override all helper behavior.

### 10. Final Parity

After the final source commit is applied and build-verified, first audit that every required post-Group-7 build record exists. Do not start Final Parity if any post-Group-7 source/plugin/build-system commit is missing its own successful build log; stop at the first missing source index/SHA and ask the engineer whether to restart from the last build-verified commit.

Then check parity:

```sh
git diff $OUTPUT_BRANCH $REFERENCE_BRANCH
```

If the diff is empty, record the null-diff confirmation and the null-diff SHA in `$REPORT_FILE`, then run the final build at that exact SHA.

If differences remain:

1. Add one or more explicit reconciliation commits that bring `$OUTPUT_BRANCH` to parity with `$REFERENCE_BRANCH` through reviewed path/hunk-level edits.
2. Confirm `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty and record the null-diff SHA.
3. Re-run the build at the null-diff tip.
4. Document the reconciliation commit and the residual differences it resolved.

If the null-diff final build passes, the task can complete with both parity and buildability.

If the null-diff final build fails:

1. Extract the first actionable error and verify whether the failure is caused by the null-diff reconciliation itself or by matching `$REFERENCE_BRANCH` code that does not build under the required toolchain.
2. If the failure can be fixed while preserving null diff, fix the reconciliation hunk and repeat the null-diff build.
3. If preserving null diff and passing the required build conflict, stop and ask the engineer which final state to keep:
   - keep the null-diff tree with the final build failure documented; or
   - add a narrow final build-fix commit, accepting a documented residual diff to `$REFERENCE_BRANCH`.
4. Do not choose buildability over null diff, or null diff over buildability, without explicit current-conversation approval.
5. If the engineer approves a final build-fix residual diff, apply only the smallest build-required hunks, commit them after the null-diff reconciliation commit, run the final build again, and document the residual `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH`.

## Report Requirements

Write `$REPORT_FILE` in markdown. It must include:

- The input branches and report path.
- `$LLM_MODEL`, `$BUILD_DIR`, and the build command used.
- The complete list of ported commits in the order applied, plus preserved empty marker commits and skipped empty source commits.
- For each applied commit:
  - Original SHA from `$TIP_BRANCH`.
  - New SHA on `$OUTPUT_BRANCH`.
  - One-line subject.
  - Whether it applied cleanly or required conflict resolution.
  - Build result for that commit, or the no-build exemption when it is before Group 7 or an approved post-Group-7 no-build bucket.
  - For every post-Group-7 source/plugin/build-system commit, that commit's own build log path and PASS result at the resulting SHA. `Deferred`, `covered by final build`, `covered by reconciliation`, or `build-of-record is final` is not an acceptable build result.
- For each preserved empty marker commit:
  - Original SHA and new SHA.
  - One-line marker subject.
  - Confirmation that the commit was preserved with no tree changes and no build step.
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
- For `$BASE_BRANCH=mysql-5.6.22`, every `Initial Percona Server 5.6.22 tree` least-conflict selection, including candidate index, SHA, conflicted-file count, and selected order.
- Commit bucket classification, batching decisions, and any mis-bucket corrections.
- The first Group 7 marker checkpoint `[compilation]` fix commit SHA(s), subject(s), changed paths, build error summary, rebuild result, and confirmation that each fix commit was created before the `=== MARKER: GROUP 7 — Remaining ===` marker itself, if any were required.
- Any fixes or partial changes ported from later commits on `$REFERENCE_BRANCH` to preserve buildability.
- Any commit rewrite caused by build fixes, including failed SHA, final SHA, and build log path.
- Confirmation that no non-buildable build-required commits remain on `$OUTPUT_BRANCH`; if the run stopped, identify the last known buildable commit and the blocked source commit.
- Confirmation that no required post-Group-7 build was skipped. If any required build was skipped, the report must mark the replay invalid from the first skipped source index/SHA and must not present a reconciliation commit as successful completion.
- Final confirmation that `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty at the null-diff SHA, plus the final build result at that SHA.
- The reconciliation commit SHA and explanation, if one was required.
- If the engineer approved a final build-fix residual diff, include the approval decision, final build-fix SHA, final build log, residual diff paths/hunks, and the reason the null-diff tree could not also be buildable under the required toolchain.

## Stop Conditions

Stop and ask the engineer how to proceed if:

- `$REFERENCE_BRANCH` does not contain enough information to resolve a conflict.
- A dependency cascade cannot be isolated into targeted hunks for later application.
- A conflict or cascade appears to require whole-file or whole-tree reference replacement. Prior reports, memory, rerere, or model recollection do not count as approval; stop unless the engineer has explicitly approved the exact file path and reason in the current conversation.
- A commit cannot be made buildable without changes that are larger than the minimum needed for the current failure.
- A commit remains non-buildable after minimal `$REFERENCE_BRANCH` fixes and targeted hunk deferral. Stop at the last known buildable commit; do not carry the failure forward.
- The required toolchain or build dependencies are unavailable.
- The final tree cannot be reconciled to `$REFERENCE_BRANCH` without contradicting the requested commit history.
- The null-diff final tree fails the required build and no engineer decision has been made about whether parity or a narrow build-fix residual diff should be the final state.

---
name: ps-replay-make-buildable
description: Use when replaying Percona Server commits from one MySQL base to another while preserving post-Group-8 per-commit buildability and converging to a known reference branch.
---

# Percona Server Replay And Make Buildable

## Goal

Replay `$BASE_BRANCH..$TIP_BRANCH` onto `$DESTINATION_BASE_BRANCH` as `$OUTPUT_BRANCH`, keep the required history buildable, and finish with a null diff to `$REFERENCE_BRANCH`.

Success requires all of:

- `$OUTPUT_BRANCH` is rooted at `$DESTINATION_BASE_BRANCH`.
- The selected source commits are processed in order, one at a time.
- Empty marker commits are preserved; other empty cherry-picks are skipped.
- The Group 8 end checkpoint (immediately before the Group 9 marker) and every later build-required commit has its own PASS build record.
- Final tree diff to `$REFERENCE_BRANCH` is empty and the null-diff tip builds.
- `$REPORT_FILE` records inputs, replay decisions, build logs, final parity, and `violations encountered: none` or the violations found.

## Inputs

Required:

- `$BASE_BRANCH`
- `$TIP_BRANCH`
- `$DESTINATION_BASE_BRANCH`
- `$REFERENCE_BRANCH`
- `$OUTPUT_BRANCH`

Default:

- `$RUN_DIR=/tmp/ps-replay-${OUTPUT_BRANCH}`
- `$BUILD_DIR=$RUN_DIR/build`
- `$REPORT_FILE=/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}.md`

The source list may include task-specified filters, for example `--first-parent` or `^mysql-5.7.44`. Record the exact command.

## Hard Rules

- **HR-1:** Use plain `git cherry-pick <sha>` only. No `-X ours`, `-X theirs`, `git checkout --ours/--theirs`, merge-strategy shortcuts, or bulk conflict resolution. A ledgered `rewrite-replacement` may plain-cherry-pick one matching 8.0 rewrite commit instead of the current 5.7 source commit when all Rewrite-Replacement Bounds hold.
- **HR-2:** Never snap to `$REFERENCE_BRANCH`: no checkout/restore/read-tree/copy/redirect of whole files or directories from reference. `git show $REFERENCE_BRANCH:<path>` is inspection-only, except for manually copying small conflict-region text.
- **HR-3:** Do not consult prior chats, memory, old reports, rerere decisions, or out-of-session notes. Allowed sources are the current conversation, Git history, the worktree, run logs, and reference-tree inspection.
- **HR-4:** Do not add LLM/tool attribution trailers to commits.
- **HR-5:** Do not use helper modes that perform whole-file/tree reference replacement.
- **HR-6:** Do not invoke forbidden conflict-resolution skills.
- **HR-7:** Do not branch behavior on commit subjects, except marker detection.
- **HR-8:** Bucketing is locked from the source commit's path list, never from the resolved output diff.
- **HR-9:** Do not strip source/plugin/build-system hunks to avoid a required build.
- **HR-10:** Build-driven fixes update the side that lags `$REFERENCE_BRANCH`; do not revert a region that already matches reference.
- **HR-11:** If a rule violation happens, the run is invalid from that point. Stop and report it; do not repair it by later null diff or final build.
- **HR-12:** Feature gating is upfront and range-only: run `ps_replay_range_feature_gate.py` exactly twice — once for the pre-Group-9 range before replay starts, once for the post-Group-8 range before post-Group-8 replay — then consult those results. Do not run per-commit feature-gate helpers.

## Prepare

1. Confirm inputs, clean worktree, run directories, report path, and build command.
2. Generate and store the ordered source list:

   ```sh
   git rev-list --reverse <task filters> $BASE_BRANCH..$TIP_BRANCH > $RUN_DIR/source-list.txt
   ```

3. Run an upfront reference-shape audit before creating `$OUTPUT_BRANCH`:

   ```sh
   git merge-base $DESTINATION_BASE_BRANCH $REFERENCE_BRANCH
   git rev-list --count --first-parent $DESTINATION_BASE_BRANCH..$REFERENCE_BRANCH
   git log --first-parent --oneline --reverse $DESTINATION_BASE_BRANCH..$REFERENCE_BRANCH
   git log --first-parent --merges --oneline $DESTINATION_BASE_BRANCH..$REFERENCE_BRANCH
   git cherry -v $TIP_BRANCH $REFERENCE_BRANCH
   git diff --name-status $DESTINATION_BASE_BRANCH $REFERENCE_BRANCH
   git diff --shortstat $DESTINATION_BASE_BRANCH $REFERENCE_BRANCH
   ```

   Record whether reference has source-list-missing commits, merge-up resolutions, delete-only areas, rename-only areas, missing reference files, MTR fixture drift, support/build/client/plugin drift, SQL drift, or storage drift. This is diagnostic only; it does not authorize pre-dropping hunks or snapping.

4. Locate the exact marker subjects:

   ```text
   ==================== MARKER: GROUP 8 — Build/Compilation ====================
   ==================== MARKER: GROUP 9 — Upstream bug fixes ====================
   ```

   Record their 1-based source indexes. Stop if either is absent. Set `GROUP9_INDEX` to the Group 9 marker's index. The build checkpoint is at the end of Group 8: Group 8's own commits are no-build, and per-commit builds start only after the last Group 8 commit, immediately before the Group 9 marker is preserved. Throughout this skill, "post-Group-8" means from the Group 9 marker onward.

5. Create `$OUTPUT_BRANCH` from `$DESTINATION_BASE_BRANCH`.
6. Start `$RUN_DIR/ledger.tsv`. Record only non-routine events: conflict resolutions, empty skips, feature-absent skips and hunk drops, deferred hunks, forward-folds, squashes, build fixes, waivers, reconciliation commits, final parity, and final build. Routine clean cherry-picks need not be ledgered.
7. Before starting replay, run the feature gate once for the pre-checkpoint range (every commit before the Group 9 marker, including all Group 8 commits):

   ```sh
   scripts/ps_replay_range_feature_gate.py \
     --worktree . \
     --source-list $RUN_DIR/source-list.txt \
     --start 1 \
     --end $((GROUP9_INDEX - 1)) \
     --first-parent \
     --reference-base $DESTINATION_BASE_BRANCH \
     --reference $REFERENCE_BRANCH \
     --output $RUN_DIR/feature-evidence/pre-group9-gate.json
   ```

   Record the command and summary counts. Pre-checkpoint commits owe no builds, but they are gated: consult this file before each pre-checkpoint non-marker cherry-pick to decide plain apply, whole-commit `reference-feature-absent-skip`, or partial `reference-feature-absent-hunk-drop`.
8. Before post-Group-8 replay, run the feature gate exactly once: build one range-level feature evidence file for the selected source commits against the target reference range:

   ```sh
   scripts/ps_replay_range_feature_gate.py \
     --worktree . \
     --source-list $RUN_DIR/source-list.txt \
     --start $((GROUP9_INDEX + 1)) \
     --first-parent \
     --reference-base $DESTINATION_BASE_BRANCH \
     --reference $REFERENCE_BRANCH \
     --output $RUN_DIR/feature-evidence/range-gate.json
   ```

   This compares `$BASE_BRANCH..$TIP_BRANCH` after task filters (for example `^mysql-5.7.44`) to `$DESTINATION_BASE_BRANCH..$REFERENCE_BRANCH`, not every commit to the whole reference tree. Record the command and summary counts. These two range gates (pre-Group-9 and post-Group-8) are the only feature-gate runs for the replay.

## Build Setup

Use an out-of-tree build. Default configuration:

```sh
CC=gcc-9 CXX=g++-9 cmake .. \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache \
  -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DMYSQL_MAINTAINER_MODE=OFF \
  -DDOWNLOAD_BOOST=1 \
  -DWITH_BOOST=/tmp/boost \
  -DWITHOUT_TOKUDB=1 \
  -DWITH_ROCKSDB=OFF \
  -DENABLE_DOWNLOADS=1 \
  -DWITH_READLINE=system \
  $EXTRA_CMAKE_FLAGS
make -j$(( $(nproc) * 3 / 4 ))
```

Pass task-requested build flags through `$EXTRA_CMAKE_FLAGS` or equivalent CMake variables, and record them. Store each build log under `$RUN_DIR/logs/` with source index, source SHA, output SHA, and attempt number.

## Bucket Rules

Before the checkpoint (every commit up to the end of Group 8, i.e., before the Group 9 marker):

- Non-marker commits are no-build. This includes all of Group 8's own commits.
- Marker commits are preserved empty, including the Group 8 marker, with no build.

At the Group 8 end checkpoint (immediately before the Group 9 marker):

- Run the first build after the last Group 8 commit, before preserving the Group 9 marker.
- If it fails, commit minimal `[compilation]` fixes before the marker, rebuild, then preserve the Group 9 marker empty.

After Group 8 (from the Group 9 marker onward):

- Classify each non-marker source commit from `git diff-tree --no-commit-id --name-only -r <source-sha>`.
- Source bucket if any path is source/build-system-like: `sql/`, `storage/`, `client/`, `mysys/`, `mysys_ssl/`, `vio/`, `include/`, `extra/`, `sql-common/`, `plugin/`, `cmake/`, `scripts/`, `CMakeLists.txt`, `configure.cmake`, `config.h.cmake`, or extensions `.c .cc .cpp .cxx .h .hh .hpp .hxx .cmake`.
- Source/plugin/build-system bucket commits are applied singly and must build at their resulting SHA before the next build-required commit.
- No-build commits may be batched in small chronological batches; run a boundary build after each post-Group-8 no-build batch.

## Replay Loop

### Pre-checkpoint (fast path) — through the end of Group 8

Before the Group 8 end checkpoint (every commit before the Group 9 marker, including all Group 8 commits), no build is owed for any commit. Use the minimum loop:

1. If marker: `git commit --allow-empty -m "$subject"`. Continue.
2. Consult `$RUN_DIR/feature-evidence/pre-group9-gate.json` for the commit:
   - `reference-present`, `message-only-review`, or `no-diff-identifiers` entries proceed to plain cherry-pick.
   - For `needs-review` or `partial-match-review` entries, inspect the source patch, `diff_identifiers`, `unmatched_diff_identifiers`, path matches, and nearby `$REFERENCE_BRANCH` code with targeted `git grep`/`git ls-tree`/`git cat-file`, the same way as in the post-Group-8 rules. The same absence criteria apply: absence means the reference lacks the feature behavior represented by the actual patch hunks, not a moved file, changed API shape, or message-only identifiers.
   - If the whole feature represented by the patch hunks is absent from `$REFERENCE_BRANCH`: do not cherry-pick the commit. Ledger `reference-feature-absent-skip` with the identifiers searched, reference evidence, source index/SHA/subject, and the no-output exception.
   - If only part of the commit is reference-absent: cherry-pick, then rewrite the commit before finalizing it — drop only the reference-absent hunks/paths (unstage and revert whole-file drops; edit absent hunks out of mixed files) and keep the rest under the original commit message. Ledger one `reference-feature-absent-hunk-drop` row per dropped path/hunk group with the evidence. If dropping the absent parts leaves nothing, treat the commit as a whole-commit `reference-feature-absent-skip` instead.
3. Otherwise `git cherry-pick <sha>`.
4. If the cherry-pick is empty: `git cherry-pick --skip`. Ledger one `empty-skip-equivalent` row. Continue.
5. If there are conflicts: resolve hunk by hunk using the rules below, `git add`, `git cherry-pick --continue --no-edit`. Ledger one row per resolved file (or one summary row per commit). Continue.
6. If the cherry-pick succeeded cleanly with no conflicts: no ledger row needed.

Do not run any per-commit feature-gate helper; the upfront pre-Group-9 range gate plus targeted manual inspection is the only gating input. Do not write a ledger row for every clean apply.

#### Optional Fast Path For Repeated Reference-Absent Packaging

Use only after targeted inspection in the current run has established a recurring path-shape decision, for example old `build-ps/ubuntu/**`, `build-ps/debian/*-5.7*`, or `build-ps/debian/*.notokudb` paths that are absent from the reference while equivalent packaging lives in reference-present paths.

- Configure the driver with explicit globs. Do not rely on built-in defaults; there are none.
- Gate auto-apply is allowed only when every gate-unmatched path matches the configured globs and every unmatched diff identifier is explicitly allowed or absent.
- Conflict auto-drop is allowed only when every conflicted path matches the configured globs and `git cat-file -e $REFERENCE_BRANCH:<path>` proves the path is absent from the reference.
- The helper may `git rm` only those proven reference-absent conflict paths, then either continue the plain cherry-pick with remaining staged reference-present paths or skip if the cherry-pick becomes empty.
- Pass `--ledger-file $RUN_DIR/ledger.tsv` so automated `reference-feature-absent-skip` and `reference-feature-absent-hunk-drop` decisions are recorded.
- Do not use this fast path for source/plugin/build-system semantic hunks, SQL/storage behavior, moved APIs, or any path that exists in the reference.

#### Batch-Reviewed Gate Decisions

For repeated `partial-match-review` stops that are not eligible for automatic
path-shape acceleration, inspect a contiguous block in one pass and record the
source indexes that are decided to apply in a reviewed decision file:

```text
# one reviewed decision per line; notes after the index are allowed
58 reference has the MyRocks checksum/direct-IO behavior; unmatched ids are test/sysvar drift
59 reference has ROCKSDB_COMPACTION_STATS; unmatched ids are naming/API drift
```

Then restart the driver with `--gate-decided-apply-file <file>` instead of
passing many `--gate-decided-apply <idx>` flags. This is not an auto-apply
mechanism: every listed index must already have current-run targeted
inspection evidence, and skips or hunk drops must still be handled manually
and ledgered before advancing past that source index.

### Post-Group-8 (full path) — from the Group 9 marker onward

For each source commit from the Group 9 marker onward:

1. Record source index, SHA, subject, path list, and locked bucket.
2. Before cherry-picking a non-marker commit, consult `$RUN_DIR/feature-evidence/range-gate.json`:

   - `reference-present`, `message-only-review`, `partial-match-review`, or `no-diff-identifiers` entries may proceed to plain cherry-pick unless the patch itself looks semantically absent. Ledger only entries whose mapping affects conflict resolution, skip decisions, or staged-path explanations.
   - `needs-review` entries are not automatic skips. Inspect the source patch, `diff_identifiers`, `unmatched_diff_identifiers`, path matches, and nearby `$REFERENCE_BRANCH` code. Search targeted identifiers/files with `git grep`, `git ls-tree`, or `git cat-file` as needed.
   - Do not run `ps_replay_feature_gate.py` or any other per-commit feature-gate helper. For apply/skip decisions, cite the upfront range-gate record plus any targeted manual inspection commands. Prefer evidence fields that distinguish identifier origin: `diff_identifiers`, `message_only_identifiers`, `matched_diff_identifiers`, `unmatched_diff_identifiers`, `absent_diff_identifiers`, and `absent_message_only_identifiers`.
   - If the feature is present, moved, renamed, split, or implemented by a reference-equivalent mechanism, continue to the plain cherry-pick and ledger the mapping when it affects hunks or paths.
   - If the feature itself is absent from `$REFERENCE_BRANCH`, do not cherry-pick the commit. Ledger `reference-feature-absent-skip` with the diff/new-path identifiers searched, reference evidence, source index/SHA/subject, and the no-output exception. No build is owed for this skipped non-marker commit, even if its locked bucket is source/build-system.
   - Do not classify a feature as absent merely because a file moved, an API shape changed, or the commit message mentions absent side features. Absence means the reference lacks the feature behavior, user-visible variable/command/plugin, or equivalent implementation represented by the actual patch hunks.
   - If the current diff hunks are present in the reference but subject/body identifiers are absent, apply the commit or let it become an `empty-skip-equivalent`; do not use `reference-feature-absent-skip` for the whole commit. Ledger this as `applied-equivalent` or `message-only-absent-apply` when it affects the decision.
   - If targeted inspection shows the same feature was rewritten as one separate 8.0 port commit on the reference/percona 8.0 side, try `rewrite-replacement` before spending time manually porting obsolete 5.7 hunks. This is especially applicable when the 5.7 cherry-pick conflicts because the destination API shape changed, but the 8.0 commit has the same feature/bug identifiers and implements the same behavior directly against the 8.0 API. If a source cherry-pick is already in conflict, abort that cherry-pick first; then plain cherry-pick the rewrite commit and resolve any remaining conflicts hunk by hunk.

3. If marker: `git commit --allow-empty` with the original marker subject; no build, except the Group 9 marker, where the Group 8 end checkpoint build runs first and the marker is preserved after it passes.
4. Otherwise run plain `git cherry-pick <sha>`.
5. Resolve conflicts hunk by hunk. Use `$REFERENCE_BRANCH` only for local inspection and semantic guidance. Prefer the destination/reference-shaped 5.7 API when the 5.6 hunk is obsolete, moved, split, or reference-absent; ledger the mapping.
   If `git diff --check` or `git diff --cached --check` reports trailing whitespace, space-before-tab, or similar whitespace warnings, compare the exact warned line to `$REFERENCE_BRANCH` before editing it. If the same whitespace is present in the reference, keep it and ledger/report it as reference-matching whitespace; do not clean it just to satisfy `diff --check`. Only remove whitespace that is absent from the reference or that you introduced while resolving a conflict.
   If cherry-pick pseudo-files are lost while the index/worktree still contain the interrupted pick, recover them with:

   ```sh
   scripts/ps_replay_recover_cherry_pick.py --worktree . --commit <source-sha>
   ```

   Do not hand-create a replacement commit until this recovery helper has failed or proven inapplicable. The helper restores `CHERRY_PICK_HEAD` and `MERGE_MSG` only; it does not resolve files.
6. Before `git cherry-pick --continue` for every post-Group-8 source/plugin/build-system commit, compare source paths to staged paths:

   ```sh
   git diff-tree --no-commit-id --name-only -r <source-sha>
   git diff --cached --name-only
   ```

   Any absent source/plugin/build-system path must have a ledger row: deferred-hunk, forward-fold, squash, reference-absent nonsemantic, or destination/reference-equivalent semantic.

7. If the cherry-pick becomes empty:
   - preserve only marker commits;
   - skip non-markers and ledger `empty-skip-equivalent`;
   - no build is owed for an empty skip.
8. Commit or continue, record the output SHA. For build-required commits, this output commit remains the container for any later build fixes for the same source commit.
9. If build-required, build immediately. Do not apply the next build-required commit until the current one passes.

## Build Failures

Default cap: 4 attempts per build-required commit. Ask for a current-conversation waiver before exceeding it.

Commit-shape rule:

- `[compilation]` commits are allowed only for the Group 8 end checkpoint first build before the Group 9 marker, where no build-required source commit exists yet to amend.
- For every post-Group-8 source/plugin/build-system commit, do not create a separate `[compilation]` commit for an independent build failure.
- If the failing source commit has already been committed, apply the build fix and `git commit --amend` the current output commit, preserving the source commit message unless a ledgered squash/cluster message format applies.
- If the failing source commit has not yet been committed, include the build fix before `git cherry-pick --continue`.
- After each amend, update the recorded output SHA and ledger the failed log, fix paths, reason, old output SHA, amended output SHA, and PASS log.

For each failure:

- Extract the first actionable compiler/linker/CMake error.
- Compare both sides of mismatched APIs against `$REFERENCE_BRANCH`.
- Edit only the lagging side; do not undo reference-matching code.
- Prefer targeted forward-fold from a named later source commit when known; otherwise use the smallest reference-shaped fix needed for the current commit.
- Ledger build-fix paths, reason, failed log, amended/final output SHA, and PASS log.

If a commit cannot be made buildable within the cap, reset to the last known buildable SHA, report the blocker, and ask.

## Residual Diff Audit

After the source list is exhausted and before any reconciliation or snap decision, run the residual audit helper:

```sh
scripts/ps_replay_residual_audit.py \
  --worktree . \
  --output HEAD \
  --reference $REFERENCE_BRANCH \
  --trivial-lines 1 > $RUN_DIR/residual-audit.txt
```

The helper is binary-safe and decodes non-UTF-8 diff bytes with replacement characters. Record the shortstat, residual audit summary, and any reference-only first-parent commits in `$REPORT_FILE`. If the residual includes substantive diffs or reference-only merge commits, stop and choose an explicit reconciliation policy; do not silently snap unless the user requests or the run inputs allow it.

## Allowed Content Movement

Use only when needed for conflict, buildability, or reference-feature absence, and ledger every row:

- `deferred-hunk`: remove a hunk now and apply it at a named later source commit.
- `defer-commit`: postpone the entire current commit to one specific later source-list position.
- `forward-fold`: apply a minimal hunk from one named later source commit into the current build fix.
- `squash`: combine exactly two adjacent source commits when most of the later commit is needed now.
- `squash-cluster`: only with current-conversation engineer approval naming the members.
- `applied-equivalent`: old source hunk is already present, moved/split/renamed, obsolete, or intentionally absent in the 5.7 reference.
- `message-only-absent-apply`: apply a commit whose actual diff/new-path hunks are reference-present even though absent identifiers appear only in the subject/body.
- `reference-feature-absent-skip`: skip a non-marker before cherry-pick when the applicable range gate (pre-Group-9 or post-Group-8) plus targeted inspection proves the feature behavior represented by the actual diff/new-path hunks is absent from the reference.
- `reference-feature-absent-hunk-drop`: while applying a commit, drop only the hunks/paths whose feature is reference-absent and commit the rest under the original message. Requires range-gate plus targeted inspection evidence per dropped hunk group. Never use it to avoid a conflict, a required build, or an HP-8 explanation.
- `rewrite-replacement`: replace the current 5.7 source commit with one separate 8.0 rewrite/port commit for the same feature. The replacement commit must be plain-cherry-picked, not copied from a tree, and every path/build obligation from both commits remains auditable.

Never use these mechanisms for convenience, batching, or hiding missing builds.

### Rewrite-Replacement Bounds

Use `rewrite-replacement` when a 5.7 feature commit has an independently authored 8.0 port/rewrite commit that is a better semantic unit than manual conflict resolution.

Every bound must hold:

- Find exactly one rewrite commit that represents the current source commit's feature, using commit message tokens, bug/PS IDs, diff identifiers, and changed paths. A merge commit alone is not enough; identify the concrete non-merge commit when the rewrite arrived through a PR merge.
- The rewrite must implement the same feature behavior as the 5.7 source commit. It may adapt storage, parser, DD, tests, or API wiring to 8.0, but it must not bundle unrelated features that would have required separate source-list positions.
- Prefer local evidence first: `$REFERENCE_BRANCH`, an available `percona/8.0` or `8.0` branch, and targeted `git log -S/-G/--grep` searches. Do not treat a later maintenance fix for the feature as the rewrite unless it is the only commit needed for the current source feature.
- If the source cherry-pick is already in progress, abort only that current cherry-pick and preserve all prior output commits. Then run plain `git cherry-pick <rewrite-sha>`.
- Resolve rewrite conflicts hunk by hunk under the normal conflict rules. The rewrite does not authorize whole-file reference replacement or a final snap.
- The output commit message may be the rewrite commit's original message. Ledger the current source index/SHA/subject, rewrite SHA/subject, evidence that it is the same feature, output SHA, and any conflict/build resolution.
- The locked bucket is the union of the source commit and rewrite commit path lists. If either side is source/plugin/build-system, the replacement output commit is build-required and needs a PASS build at its resulting SHA.
- The HP-8 staged-path check uses the union of source and rewrite path lists. Every absent source/plugin/build-system path still needs a ledgered explanation such as destination/reference-equivalent semantic, obsolete 5.7 API, or rewrite-covered path.
- Do not use `rewrite-replacement` when the 8.0 feature is split across multiple commits. In that case use normal hunk resolution, forward-fold, defer-commit, squash, or squash-cluster bounds as applicable.

### Defer-commit Bounds

Use `defer-commit` only when the current commit is mostly premature and the alternative would require pulling content from multiple later commits into the current build point.

Every bound must hold:

- Name one landing commit by source index and SHA. "Somewhere later" is not valid.
- Do not transitively defer other commits. If deferring this commit requires deferring another, stop and ask.
- Intervening commits must remain buildable without the deferred commit. If one fails because the deferred content is missing, the deferral was wrong; stop and ask.
- The deferred commit keeps its original locked bucket. At the landing position it still gets normal conflict handling, HP-8 staged-path checks, and its own PASS build if build-required.
- A source commit may be defer-committed at most once.
- Ledger original index/SHA/subject, landing index/SHA, motivating failure, dependency supplied by the landing commit, final output SHA, and PASS log.
- Every deferred commit must be applied and closed before final parity.

### Squash Bounds

Use `squash` only when most of one later commit is needed for the current commit to build and leaving the remainder as a separate commit would be artificial.

Every bound must hold:

- Combine exactly two source commits. Do not chain squashes or absorb multiple later commits into one squash.
- Record a concrete justification for "most": majority of needed hunks, or a clear continuation/fix-up relationship shown by the build failure.
- Resolve both commits hunk by hunk. Do not use `-X ours/theirs`, whole-file replacement, or alignment passes.
- The combined commit's bucket is the union of both source commits' buckets. If either component is Source/Plugin/build-system, the combined commit is build-required and needs one PASS build at the combined SHA.
- The combined commit's HP-8 check uses the union of both source commits' path lists; every absent path needs a ledgered explanation.
- The absorbed commit gets no separate output SHA and no separate later build; the combined SHA/build is where its content lives.
- A source commit may participate in at most one squash.
- Ledger both original SHAs/subjects, combined output SHA, build log, motivating failure, and justification.

Combined commit message format:

```text
<subject of N>; squashed with: <subject of N+1>

Squashed commits:
  - <original sha of N>
  - <original sha of N+1>
```

### Squash-cluster Bounds

Use `squash-cluster` only after current-run build failures show a named multi-commit dependency cluster that cannot be handled by a single forward-fold, hunk defer, defer-commit, or pairwise squash.

Every bound must hold:

- Record concrete dependency evidence for every member: source index, SHA, subject, and what dependency it provides.
- Get current-conversation engineer approval after presenting the full member list. Approval must name or directly acknowledge all members; vague approval such as "squash as needed" is not enough.
- Squash all approved members or none. Do not leave a residual member of the approved cluster outside the cluster squash.
- Land the combined commit at the earliest member's source-list position; remove all other members from the source-list cursor.
- Resolve every member hunk by hunk using normal replay rules.
- The cluster bucket is the union of all member buckets. If any member is Source/Plugin/build-system, the combined cluster commit is build-required and needs one PASS build at the combined SHA.
- Run the HP-8 check against the union of all member path lists; unledgered missing paths are violations.
- Do not nest clusters. A cluster cannot be a member of another cluster; if a larger cluster is needed, stop and ask with the expanded member list.
- Ledger cluster name, full member list, dependency evidence, approval quote, combined output SHA, PASS log, and HP-8 result.

Cluster commit message format:

```text
Squashed cluster: <cluster_name>

Cluster members:
  - idx <N> <sha> <original subject>
  - idx <M> <sha> <original subject>
```

## Helper Scripts

Direct Git and build commands are the default. Helper scripts are optional and must obey HR-1 through HR-11. Prefer scripts in `/home/przemek/.agents/skills/ps-replay+make-buildable/scripts`; if absent, check this skill's `scripts/` directory.

Allowed helpers:

- `ps_replay_scan_range.py`: preflight scan of source/reference ranges for markers, squash/snap-like commits, and reference-only commits. Use during the reference-shape audit.
- `ps_replay_range_feature_gate.py`: range-level feature audit comparing selected source commits against `$DESTINATION_BASE_BRANCH..$REFERENCE_BRANCH`. Use exactly twice: once before replay starts for the pre-Group-9 range (`--start 1 --end $((GROUP9_INDEX - 1))`) and once before post-Group-8 replay for the rest; consult `decision_hint` before each non-marker commit in the corresponding range. This is the only allowed feature-gate helper in this skill.
- `ps_replay_batch.py`: bounded replay driver. It must use plain `git cherry-pick <sha>` for every non-marker commit, preserve marker commits with `git commit --allow-empty`, stop on conflicts/build failures/missing build records, and HP-8 check post-Group-8 source/plugin commits. For clean plain cherry-picks it checks the resulting output commit's changed paths; for conflicts, do the staged-path HP-8 check manually before `git cherry-pick --continue` unless the optional fast path above resolved only configured reference-absent conflicts. Use `--classify-only` before trusting bucket decisions. Pass the range-gate evidence files with `--feature-gate` (repeatable: pre-Group-9 and post-Group-8 files); the driver then stops before cherry-picking any commit whose decision hint requires manual review (pre-Group-9: `needs-review` and `partial-match-review`; post-Group-8: `needs-review`) unless explicitly accelerated with `--gate-auto-apply-path-glob` and `--gate-auto-apply-unmatched-identifier`, or already reviewed with `--gate-decided-apply <idx>` / `--gate-decided-apply-file <file>`. After inspecting a stopped commit, restart with a decided-apply option to apply it, or handle the skip/hunk-drop manually and restart after that index. For repeated audited absent packaging paths, pass `--auto-drop-reference-absent-conflict-glob <glob>` and `--ledger-file $RUN_DIR/ledger.tsv`; the driver may auto-`git rm` only conflicted paths that match the globs and are absent from `$REFERENCE_BRANCH`.
- `ps_replay_auto_loop.sh`: compatibility wrapper around `ps_replay_batch.py`; it must inherit the same stop/build/cross-check behavior. Set `PS_REPLAY_CMAKE_FLAGS='-DCMAKE_CXX_FLAGS=-fpermissive'` or pass `--cmake-flag` to the Python helper for task-specific build flags. Set `PS_REPLAY_FEATURE_GATES` (whitespace-separated gate JSON paths), `PS_REPLAY_GATE_DECIDED_APPLY` (whitespace-separated indexes), and/or `PS_REPLAY_GATE_DECIDED_APPLY_FILE` to forward the feature-gate options. Optional acceleration env vars: `PS_REPLAY_GATE_AUTO_APPLY_PATH_GLOBS`, `PS_REPLAY_GATE_AUTO_APPLY_UNMATCHED_IDENTIFIERS`, `PS_REPLAY_AUTO_DROP_CONFLICT_GLOBS`, and `PS_REPLAY_LEDGER_FILE`.
- `ps_replay_build.py`: standard CMake/build runner that writes logs.
- `ps_replay_errors.py`: extracts likely root-cause diagnostics from large build logs.
- `ps_replay_conflict_triage.py`: prints conflict status and may stage only files whose conflict regions already match safely; remaining files require manual hunk review.
- `ps_replay_diff_check.py`: runs `git diff --check` or `git diff --cached --check`, compares warning lines to `$REFERENCE_BRANCH`, and exits success when every warning is reference-matching whitespace that should be preserved.
- `ps_replay_resolve_conflicts.py`: inspection-only conflict display with nearby reference context.
- `ps_replay_resolve_hunks.py`: best-effort conflict-block resolver; it may replace only conflict blocks, never whole files. Review its output before continuing.
- `ps_replay_residual_audit.py`: classifies final residual diff hunks before reconciliation.

Disabled helper behavior:

- whole-file or whole-tree reference replacement;
- automatic `ours`/`theirs` conflict resolution;
- post-resolution source-path alignment to reference;
- rebucketing Source/Plugin commits as no-build;
- mass-folding later reference state into Group 8 or another single build fix;
- continuing past a conflict, failed build, missing build record, or unledgered HP-8 path absence.

## Final Parity

Before final parity:

- Audit every post-Group-8 build-required source commit: each must have its own PASS build log at its resulting SHA, unless it was an empty skip, closed defer-commit entry, ledgered squash component, or approved squash-cluster member.
- Audit the ledger: every deferred-hunk, defer-commit, forward-fold, squash, squash-cluster, rewrite-replacement, and applied-equivalent row must point to a landing/target/combined/replacement SHA or explicit no-output exception.

Then:

```sh
git diff $OUTPUT_BRANCH $REFERENCE_BRANCH
```

If non-empty, add explicit reconciliation commits by reviewed path/hunk groups. Recommended order:

1. delete reference-absent files;
2. move rename-only paths with `git mv`;
3. add reference merge-resolution files through narrow patches;
4. reconcile MTR/test fixtures;
5. reconcile support/build/client/plugin paths;
6. reconcile `sql/`;
7. reconcile `storage/`.

Do not use whole-tree or whole-file reference replacement. After reconciliation, confirm null diff and run the final build at the null-diff SHA. If null diff and buildability conflict, stop and ask.

## Report

Write `$REPORT_FILE` incrementally. Required sections:

- Inputs, exact source-list command, build flags, run directories.
- Pre-flight/readback summary and `violations encountered: none` or violations.
- Reference-shape audit and final-reconciliation forecast.
- Both range feature-gate commands (pre-Group-9 and post-Group-8), summary counts, and every `needs-review` entry that led to targeted inspection, apply-equivalent, `reference-feature-absent-skip`, or `reference-feature-absent-hunk-drop`.
- Group 8 end boundary (Group 9 marker index), checkpoint build, `[compilation]` fixes, and marker preservation.
- Per source commit: index, source SHA, output SHA or skip, bucket, path list, conflicts, HP-8 staged-path result, build result or no-build reason.
- Ledger summary: feature-absent skips and hunk drops, deferred hunks, defer-commits, forward-folds, squashes, squash-clusters, rewrite-replacements, applied-equivalents, waivers.
- Build-driven fixes (BDF): failed log, error, fix paths, PASS log.
- Final parity reconciliation commits.
- Final null-diff SHA and final build log.

## Stop Conditions

Stop and ask when:

- HR-1 through HR-11 would be violated.
- The Group 8 or Group 9 marker is missing.
- A required build was skipped and later commits were applied.
- HP-8 staged-path cross-check has an unledgered missing source/plugin/build-system path.
- A build-required commit exceeds the attempt cap without waiver.
- A conflict requires whole-file/directory reference replacement to proceed.
- A defer-commit would need transitive deferral, lacks a named landing commit, or has already been deferred once.
- A squash would absorb more than one later commit, chain with another squash, or lacks concrete "most of later commit is needed" justification.
- A squash-cluster lacks current-conversation approval for the full member list, lacks concrete dependency evidence, would leave approved members outside the cluster, or would nest clusters.
- The ledger is unclosed before final parity.
- Null diff and final build cannot both be satisfied.

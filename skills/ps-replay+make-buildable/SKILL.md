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
- The Group 8 end checkpoint (immediately before the Group 9 marker) and every later build-required commit has its own PASS build record. A PASS means the build succeeded **and** the MTR smoke test `main.1st` passed on that build.
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

## Runtime And Token Efficiency

Default to the low-token replay mode unless the user asks for detailed narration:

- Before restarting the driver after a feature-gate stop, scan the next contiguous gate-stopped block from the existing range-gate JSON and review the whole block in one pass. Write the apply decisions to one `--gate-decided-apply-file` and handle true skips or hunk drops manually before advancing past their source indexes.
- Keep evidence in durable artifacts: `$RUN_DIR/ledger.tsv`, `$REPORT_FILE`, gate decision files, and build logs. Chat/status output should normally be limited to source index, stop reason, decision type, output SHA, and build result.
- Do not paste large diffs, full gate records, or build logs into chat. Inspect them locally, record the command/evidence summary in the report or ledger, and quote only the minimal line needed to identify a blocker.
- Maintain a current-run path/API mapping note in the report when the same 8.0 move recurs across conflicts. Reuse that note for later hunk decisions, but still ledger any source/plugin/build-system source path that is absent from the staged output.
- Prefer an allowed `rewrite-replacement` as soon as exactly one matching 8.0 rewrite commit is proven, especially when the 5.7 patch conflicts only because the destination API shape changed.
- After conflict helpers or broad rewrite replacements, run the post-conflict audit before the first build. This catches duplicate old structs/functions, stale labels, and obsolete 5.7 APIs cheaply.
- For InnoDB/storage-heavy source commits, run changed-object compilation before the full build when an existing build tree is available. Full builds still remain the only PASS record.
- Do not weaken HR-1 through HR-12 for speed. Faster replay comes from batching review, compact reporting, cached current-run evidence, and fewer driver restarts, not from strategy shortcuts or whole-file reference replacement.

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

## Driver Monitoring

`ps_replay_batch.py` is not interactive and never blocks: it runs until the range is finished or it
stops on a conflict, a build failure, a feature-gate review, or an HP-8 violation, then exits with a
non-zero status. A driver that looks stuck is almost always a monitoring bug, not a hung driver.

Launch it detached and have it record its own exit status, then wait on that file:

```sh
# launcher: run-driver.sh START [END]
rm -f $RUN_DIR/driver.rc
python3 $SCRIPTS/ps_replay_batch.py --source-list $RUN_DIR/source-list.txt \
  --start $START --end ${END:-<last index>} ... > $RUN_DIR/logs/driver-$START.log 2>&1
echo $? > $RUN_DIR/driver.rc
```

```sh
# waiter: blocks until the driver finished, then prints its status and log tail
for i in $(seq 1 $((TIMEOUT/5))); do [ -f $RUN_DIR/driver.rc ] && break; sleep 5; done
[ -f $RUN_DIR/driver.rc ] && echo "EXITED rc=$(cat $RUN_DIR/driver.rc)" || echo "STILL-RUNNING"
tail -8 $RUN_DIR/logs/driver-$START.log
```

Do **not** poll with `pgrep -f ps_replay_batch.py` (or any `pgrep -f` on a string that appears in the
waiter's own command line). The polling shell's `-c '... pgrep -f ps_replay_batch.py ...'` command
line contains the pattern, so `pgrep` matches the waiter itself and the loop reports `STILL-RUNNING`
forever after the driver has already exited. The same trap hits `pkill -f`, which will kill the
waiting shell. If a PID-based check is needed, capture the driver's own PID at launch and test it
with `kill -0 "$PID"`.

Exit statuses worth recognizing:

| rc | meaning | next step |
|---|---|---|
| 0 | range finished | move to the next range, the checkpoint build, or final parity |
| 3 | conflict or unresolved cherry-pick result | resolve hunks manually, HP-8 check, `git cherry-pick --continue`, restart after that index |
| 4 | build failure | read the log under `$RUN_DIR/logs/`, apply a build-driven fix, amend, rebuild |
| 5 | build passed, `main.1st` smoke test failed | read `build-<idx>-<sha>-ccache-mtr-1st.log`; fix the harness or server defect at the commit that introduced it (not by overlaying a newer `mysql-test-run.pl`), amend, rebuild |
| 6 | feature-gate stop | inspect, then restart with `--gate-decided-apply-file`, or handle the skip/hunk-drop manually |

Confirm the real state from Git, not from the process table: `git status --short | grep '^UU\|^AA\|^DU\|^UD'`
and `git log --oneline -1` say whether a cherry-pick is actually open and where the branch stands.

### Progress Heartbeat And Completion Detection

A long post-Group-8 range is mostly waiting. The dominant failure mode of that
wait is **not** a hung driver — it is the driver or build finishing while
nothing looks at the result, so the run idles. Treat a silent run as
unverified, never as busy.

Wait on the run with the watchdog, which does two separate jobs at two
different cadences:

```sh
$SCRIPTS/ps_replay_watchdog.sh $RUN_DIR             # 1s completion poll, 300s heartbeat
$SCRIPTS/ps_replay_watchdog.sh $RUN_DIR 300 6 1     # same, spelled out
#                                       ^   ^ ^
#                                       |   | poll seconds  (completion detection)
#                                       |   stall ticks
#                                       heartbeat seconds   (status line cadence)
```

- **Completion is detected within ~1 second.** `driver.rc` / `build.rc` are
  polled every `POLL` seconds and the watchdog exits 0 immediately when one
  appears. The heartbeat interval must never gate this — a build that finishes
  in 25 s hands control back in 25 s even with the default 300 s heartbeat.
- **The heartbeat interval is only the status-line cadence and the stall
  clock.** It exists so a genuinely hung run is noticed, not so completions are
  noticed. Do not shrink it to make completion detection faster; that is what
  `POLL` is for, and it is already fast.

```
t=00:00:00  rc=-  head=5be41b8bd8bf  n=938  idx=939/1237  log_age=0s
t=00:00:25  rc=build:0  head=5be41b8bd8bf  n=938  idx=194/194  log_age=1s
FINISHED  rc=build:0  head=5be41b8bd8bf
```

Fields: elapsed, recorded exit status, branch head, commits on the output
branch, the last `[idx/total]` the driver logged, and the age of the newest log
write. A rising `log_age` with an unchanged `idx` and `head` is the stall
signature.

The watchdog exits **2 — STALLED** when `head`, `idx` and the newest log's
mtime are all unchanged for `STALL_TICKS` consecutive *heartbeat* ticks
(default 6 × 300 s, i.e. 30 minutes). That is a genuine hang-up: investigate before restarting anything.
Note that a single large InnoDB translation unit, or the Debug `mysqld` link,
can legitimately hold one tick or two without touching the log, so a stall is
only declared after the full run of quiet ticks.

Rules for the wait:

- Never end a turn describing work as "running" without having polled it in
  that turn. The cost of a missed completion is measured in hours of idle time,
  not seconds.
- A background-task notification is a hint, not the source of truth. Poll
  `driver.rc` / `build.rc` directly; a waiter whose last command is a `grep`
  that matched nothing exits non-zero and will be reported as a failure even
  though the build passed.
- When the watchdog exits 0, act on it immediately: read the rc, resolve or
  amend, and restart the driver at `IDX + 1`.
- Record any stall longer than one tick in `$REPORT_FILE`, with the elapsed
  time and what the run was waiting on, so the timing summary stays honest.

Two more launch details that cost a restart each if missed:

- Options whose value starts with `-` must be passed as `--cmake-flag=-DCMAKE_CXX_FLAGS=-fpermissive`.
  With a space, `argparse` reads the value as the next option and fails.
- `--group8-marker` defaults to the full-width Group 9 marker subject. Real branches often carry a
  truncated marker (fewer trailing `=`), so read the exact subject out of Git and pass it:
  `M9=$(git log -1 --format=%s <group9-marker-sha>)` then `--group8-marker "$M9"`. Verify with
  `git log -1 --format=%s <sha> | cat -A` when a "required marker not found" error appears. The
  marker must also fall inside `--start`..`--end` for the boundary to be detected, so keep `--end`
  at the last source index and move only `--start` when restarting; once `--start` is past the
  marker, `--allow-missing-group8-marker` is required and the driver's automatic HP-8 check for
  clean picks no longer runs, so audit those output commits' paths against their source commits
  separately.

### Restart Protocol After A Manual Stop

The driver has no resume state: it always starts at `--start` and re-picks that index. After a stop
you own the current index, and the restart index is always the next one.

1. Resolve the conflict hunk by hunk, run the HP-8 staged-path check, `git cherry-pick --continue`.
2. **If the commit is build-required, build it now**, at its own resulting SHA, before the driver
   touches the next commit — a small `build-now.sh IDX SRCSHA` wrapper around
   `ps_replay_build.py --incremental` (same `--cmake-flag`s as the driver) keeps this one command.
   It runs the `main.1st` smoke test too; exit 0 is the only PASS, exit 5 is a smoke failure.
   **Pass `--reconfigure` only when a CMake input actually changed**, exactly as the driver decides
   it: compare `<build-dir>/.ps_replay_cmake_stamp` to `HEAD` and look for `CMakeLists.txt`,
   `*.cmake`, `configure.cmake` or `config.h.cmake` in the delta (and in the unstaged worktree).
   A forced reconfigure of this tree costs about 4.5 minutes; a 20-object incremental build costs
   about 25 seconds, so reconfiguring unconditionally makes every manual build an order of
   magnitude slower than the driver's own.
3. Only then restart the driver at `IDX + 1`.

Both ways of getting this wrong are silent:

- Restarting at `IDX` re-cherry-picks a commit that is already applied. It reopens the same conflict
  on top of the committed result, leaving a stray `CHERRY_PICK_HEAD`; `git cherry-pick --abort`
  recovers it and leaves `HEAD` untouched.
- Restarting at `IDX + 1` *without* building leaves that commit with no PASS record, and the driver
  will happily apply and build later commits over it. Recovering means `git reset --hard` back to
  that output SHA, building it, and replaying what came after — so it is worth the one extra
  command up front.

### Auditing A Clean Cherry-pick That Landed Wrong

A cherry-pick that reports no conflict is not automatically correct. When an upstream release has
re-indented or restructured a function, git can apply the source's context-matched hunks into the
wrong nesting level and still exit 0. The symptom at build time is a burst of
`a function-definition is not allowed here before '{' token` / `qualified-id in declaration before
'(' token` errors well past the edited region, plus an undeclared variable that exists in a sibling
block — brace imbalance, not a missing API.

Do not chase those errors line by line. Instead:

1. Reduce the source commit to its **net semantic change** for that file, ignoring pure
   re-indentation and comment rewrapping (diff the added and removed lines as multisets: what is
   left after cancelling equal stripped lines is the real change).
2. Restore the file from your own previous output commit (`git show HEAD~1:<path>`) — this is your
   replay state, not `$REFERENCE_BRANCH`, so it is not a snap.
3. Re-apply only that net change, in the destination's shape.
4. Amend the output commit and rebuild.

`ps_replay_post_conflict_audit.py --cached` catches the same class of damage before the build; run it
whenever a commit reindents a large block.

## Build Setup

Use an out-of-tree build. Default configuration:

```sh
CC=gcc-9 CXX=g++-9 cmake -GNinja .. \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache \
  -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DMYSQL_MAINTAINER_MODE=OFF \
  -DDOWNLOAD_BOOST=1 \
  -DWITH_BOOST=/work/mysql-server/_deps \
  -DWITHOUT_TOKUDB=1 \
  -DWITH_ROCKSDB=OFF \
  -DWITH_PAM=ON \
  -DENABLE_DOWNLOADS=1 \
  -DWITH_READLINE=system \
  -DWITH_CURL=system \
  -DCMAKE_CXX_FLAGS=-fpermissive \
  -DCMAKE_EXE_LINKER_FLAGS=-fuse-ld=gold \
  -DCMAKE_SHARED_LINKER_FLAGS=-fuse-ld=gold \
  -DCMAKE_MODULE_LINKER_FLAGS=-fuse-ld=gold \
  $EXTRA_CMAKE_FLAGS
ninja -j80
```

Cap build parallelism at 80 jobs: always pass `-j80` (or lower) to `ninja` or `make`. Never use
`-j$(nproc)`, a bare `-j`, or a higher value, even on hosts with more cores. The `ps_replay_*`
build helpers enforce the same cap: `--jobs` defaults to 3/4 of the CPUs and is clamped to 80.

Build with the Ninja generator and the GNU gold linker. Post-checkpoint commits typically compile
one or two translation units but relink every dependent target, including the multi-hundred-MB Debug
`mysqld`; with Make plus the default BFD linker that link step dominates and costs tens of minutes
per commit. Ninja plus gold cuts it several-fold without changing the compiler, the sources, or the
set of targets built, so a PASS still means the same thing.

Re-run `cmake` whenever a CMake input changed, not only when the build tree is missing. MySQL globs
`plugin/*/CMakeLists.txt` (and similar directory lists) at configure time, so a commit that adds a
new plugin or storage-engine directory is invisible to an existing `build.ninja`: `ninja` then
succeeds after compiling nothing from that commit, which looks like a PASS but verifies nothing. The
symptom is a build log with only a handful of trivial targets for a commit that added many source
files - check the target count against the commit's file list before accepting such a PASS, and
confirm the new component appears in `build.ninja`.

`ps_replay_batch.py` configures when `CMakeCache.txt` is absent, and otherwise when any
`CMakeLists.txt` or `*.cmake` path changed since the last configure. It tracks that with
`<build-dir>/.ps_replay_cmake_stamp`, which `ps_replay_build.py` writes with the worktree HEAD after
every successful `cmake` run; a missing or unreadable stamp forces a reconfigure. Because the stamp
is a commit, not a single build, deferred no-build batches still trigger one reconfigure at the next
build they are folded into. `ps_replay_build.py --incremental --reconfigure` does the same thing by
hand: `cmake` plus `ninja` in the existing build tree, without the clean-build wipe. Reach for
`--reconfigure` only when a CMake input changed — plain `--incremental` reuses the existing
`build.ninja` and is several minutes faster per build.

`-DWITH_CURL=system` is required, not optional. Upstream sets `WITH_CURL_DEFAULT` to `system` only
under `IF(WITH_INTERNAL AND UNIX)`, so a normal replay build resolves it to `none`, leaves `CURL_FOUND`
unset, and `plugin/keyring_vault/CMakeLists.txt` then aborts configure with
`CHECK_IF_LIB_FOUND(CURL "keyring_vault" FATAL_ERROR)` as soon as the keyring_vault commit lands. That
is a build-environment gap, not a replay defect: do not re-add source hunks to `cmake/curl.cmake` to
work around it when the reference keeps the file at its upstream form. The system curl development
headers must be installed; on Debian/Ubuntu they live at the multiarch path
`/usr/include/<triplet>/curl/curl.h`, so check with `dpkg -L libcurl4-openssl-dev` or
`FIND_PACKAGE(CURL)` output rather than testing `/usr/include/curl/curl.h`.

If `$BUILD_DIR` was already configured without it, the cached `WITH_CURL:STRING=none` wins over the new
default; re-run `cmake -DWITH_CURL=system .` inside the build tree to override the cache in place
instead of deleting the tree.

The generator cannot be switched inside an existing build tree. If `$BUILD_DIR` was configured with
another generator, delete and reconfigure it; ccache absorbs most of the one-time recompile. Record
the switch and the source index it happened at in `$REPORT_FILE`.

Pass task-requested build flags through `$EXTRA_CMAKE_FLAGS` or equivalent CMake variables, and record them. Store each build log under `$RUN_DIR/logs/` with source index, source SHA, output SHA, and attempt number.

For build-required commits with changed `.c/.cc/.cpp/.cxx` files and an existing build tree, run a changed-object preflight before the full build:

```sh
scripts/ps_replay_changed_object_build.py \
  --worktree . \
  --build-dir $BUILD_DIR \
  --log $RUN_DIR/logs/objects-<idx>-<sha>-attempt<N>.log \
  --base HEAD^ \
  --allow-missing
```

Use this to find compile errors faster; it is not a substitute for the required full build PASS.

### MTR smoke test after every build

`ps_replay_build.py` runs `main.1st` with the build tree's own `mysql-test-run.pl` after every
successful ninja build (`--suite=main 1st`, `--parallel=1`, vardir `<build-dir>/mtr-smoke-var`,
15-minute timeout). The log is written next to the build log as `<build-log-stem>-mtr-1st.log`.
It passes only on `Completed: All N tests were successful`, which also covers the `shutdown_report`
pseudo test. Exit status 5 means the build passed but the smoke test failed; `ps_replay_batch.py`
stops with rc 5 and records both logs in `$REPORT_FILE`. It costs about 30-40 seconds per build.

A compile-only PASS doesn't catch the defects that stop MTR altogether: a `mysql-test-run.pl` that
no longer compiles (e.g. `Global symbol "$x" requires explicit package name` because a commit took
the uses of a variable but not its declaration), a harness whose worker and master sides disagree
("N+1 of N test(s) completed"), or a `mysqld --initialize` that crashes in InnoDB. Each of these
hid for more than 100 commits in an earlier replay. Treat a smoke failure like a build failure: find
the commit that introduced it, fix it there (fold the missing hunk into it or defer the part that
depends on something later), amend, rebuild. `--no-smoke-test` (on both scripts) exists for
diagnostic rebuilds only; a build without the smoke test is not a PASS record.

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

When the driver stops on `needs-review` or `partial-match-review`, do not immediately restart for a single index unless the next source commit is already known to be unsafe. Inspect the next contiguous pre-checkpoint review block from the same gate JSON, create one reviewed decision file for all indexes proven to apply, and restart once with `--gate-decided-apply-file <file>`. This is the preferred fast path for pre-checkpoint feature-gate churn.

#### Optional Fast Path For Repeated Reference-Absent Packaging

Use only after targeted inspection in the current run has established a recurring path-shape decision, for example old `build-ps/ubuntu/**`, `build-ps/debian/*-5.7*`, or `build-ps/debian/*.notokudb` paths that are absent from the reference while equivalent packaging lives in reference-present paths.

- Configure the driver with explicit globs. Do not rely on built-in defaults; there are none.
- Gate auto-apply is allowed only when every gate-unmatched path matches the configured globs and every unmatched diff identifier is explicitly allowed or absent.
- Conflict auto-drop is allowed only when every conflicted path matches the configured globs and `git cat-file -e $REFERENCE_BRANCH:<path>` proves the path is absent from the reference.
- The helper may `git rm` only those proven reference-absent conflict paths, then either continue the plain cherry-pick with remaining staged reference-present paths or skip if the cherry-pick becomes empty.
- Pass `--ledger-file $RUN_DIR/ledger.tsv` so automated `reference-feature-absent-skip` and `reference-feature-absent-hunk-drop` decisions are recorded.
- Do not use this fast path for source/plugin/build-system semantic hunks, SQL/storage behavior, moved APIs, or any path that exists in the reference.

#### Batch-Reviewed Gate Decisions

For repeated `needs-review` or `partial-match-review` stops that are not
eligible for automatic path-shape acceleration, inspect a contiguous block in
one pass and record the source indexes that are decided to apply in a reviewed
decision file:

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

Keep the review file compact. Put detailed commands and evidence in the report
only when the decision is non-obvious or affects a later conflict. For routine
apply-equivalent decisions, one line naming the feature/API mapping is enough.

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
   After any hunk helper, broad rewrite-replacement conflict, or large storage/SQL conflict, run:

   ```sh
   scripts/ps_replay_post_conflict_audit.py --worktree . --cached
   ```

   Treat findings as review blockers, not automatic failures: inspect and fix duplicate old structs/functions, stale labels such as `exit_loop:` outside their function, obsolete 5.7 APIs, or large added old-code blocks before continuing or building. Record material findings/fixes in the ledger/report.
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
- If the first errors are parse cascades or many unrelated missing symbols after a conflict helper/rewrite, rerun `ps_replay_post_conflict_audit.py` and inspect the reported regions before another full build.
- If only changed C/C++ sources are involved and the build tree exists, run `ps_replay_changed_object_build.py` after the fix and before spending the next full build attempt. Ledger object preflight failures only when they change the fix decision.
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
- If the only candidate rewrite is outside `$REFERENCE_BRANCH` ancestry or conflicts in many source files, classify it as high-risk: inspect the staged diff with `ps_replay_post_conflict_audit.py --cached` before committing, and reject the rewrite if it imported broad unrelated later-state APIs or old whole-function/struct chunks.
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

The `scripts/…` paths below are written relative to that directory. Commands run from the worktree (`--worktree .`), so invoke each helper by its absolute path — set `SCRIPTS=<that directory>` once and call `$SCRIPTS/ps_replay_*.py`. Every helper is executable and carries a `python3` shebang; `python3 $SCRIPTS/<helper>` works equally well. All of them run on the standard library alone — no virtualenv, no install step.

Allowed helpers:

- `ps_replay_scan_range.py`: preflight scan of source/reference ranges for markers, squash/snap-like commits, and reference-only commits. Use during the reference-shape audit.
- `ps_replay_range_feature_gate.py`: range-level feature audit comparing selected source commits against `$DESTINATION_BASE_BRANCH..$REFERENCE_BRANCH`. Use exactly twice: once before replay starts for the pre-Group-9 range (`--start 1 --end $((GROUP9_INDEX - 1))`) and once before post-Group-8 replay for the rest; consult `decision_hint` before each non-marker commit in the corresponding range. This is the only allowed feature-gate helper in this skill.
- `ps_replay_batch.py`: bounded replay driver. It must use plain `git cherry-pick <sha>` for every non-marker commit, preserve marker commits with `git commit --allow-empty`, stop on conflicts/build failures/missing build records, and HP-8 check post-Group-8 source/plugin commits. For clean plain cherry-picks it checks the resulting output commit's changed paths; for conflicts, do the staged-path HP-8 check manually before `git cherry-pick --continue` unless the optional fast path above resolved only configured reference-absent conflicts. Use `--classify-only` before trusting bucket decisions. Pass the range-gate evidence files with `--feature-gate` (repeatable: pre-Group-9 and post-Group-8 files); the driver then stops before cherry-picking any commit whose decision hint requires manual review (pre-Group-9: `needs-review` and `partial-match-review`; post-Group-8: `needs-review`) unless explicitly accelerated with `--gate-auto-apply-path-glob` and `--gate-auto-apply-unmatched-identifier`, or already reviewed with `--gate-decided-apply <idx>` / `--gate-decided-apply-file <file>`. After inspecting a stopped commit, restart with a decided-apply option to apply it, or handle the skip/hunk-drop manually and restart after that index. For repeated audited absent packaging paths, pass `--auto-drop-reference-absent-conflict-glob <glob>` and `--ledger-file $RUN_DIR/ledger.tsv`; the driver may auto-`git rm` only conflicted paths that match the globs and are absent from `$REFERENCE_BRANCH`.
- `ps_replay_auto_loop.sh`: compatibility wrapper around `ps_replay_batch.py`; it must inherit the same stop/build/cross-check behavior (including the Ninja generator and gold linker defaults). Set `PS_REPLAY_CMAKE_FLAGS='-DCMAKE_CXX_FLAGS=-fpermissive'` or pass `--cmake-flag` to the Python helper for task-specific build flags. Set `PS_REPLAY_FEATURE_GATES` (whitespace-separated gate JSON paths), `PS_REPLAY_GATE_DECIDED_APPLY` (whitespace-separated indexes), and/or `PS_REPLAY_GATE_DECIDED_APPLY_FILE` to forward the feature-gate options. Optional acceleration env vars: `PS_REPLAY_GATE_AUTO_APPLY_PATH_GLOBS`, `PS_REPLAY_GATE_AUTO_APPLY_UNMATCHED_IDENTIFIERS`, `PS_REPLAY_AUTO_DROP_CONFLICT_GLOBS`, and `PS_REPLAY_LEDGER_FILE`. It takes exactly two positional arguments, `START END`, and passes nothing else through; every other option must arrive as one of these env vars, or call `ps_replay_batch.py` directly.
- `ps_replay_build.py`: standard CMake/Ninja build runner that writes logs. It configures with `-GNinja` and the gold linker flags and builds with `ninja -j<N>`, where `--jobs` is clamped to 80.
- `ps_replay_build.py`: configure (when needed) and build with the skill defaults, then run the `main.1st` smoke test; exit 5 = build ok, smoke failed.
- `ps_replay_changed_object_build.py`: cheap preflight that finds CMake object targets for changed C/C++ files and runs `ninja` on those objects. Use before full builds to shorten compile-error loops; full build PASS is still required.
- `ps_replay_errors.py`: extracts likely root-cause diagnostics from large build logs.
- `ps_replay_recover_cherry_pick.py`: restores `CHERRY_PICK_HEAD` and `MERGE_MSG` when the cherry-pick pseudo-files are lost while the index/worktree still hold the interrupted pick. It recovers cherry-pick state only; it never resolves files. Use it before hand-creating a replacement commit.
- `ps_replay_conflict_triage.py`: prints conflict status and may stage only files whose conflict regions already match safely; remaining files require manual hunk review. Requires `--reference`.
- `ps_replay_diff_check.py`: runs `git diff --check` or `git diff --cached --check`, compares warning lines to `$REFERENCE_BRANCH`, and exits success when every warning is reference-matching whitespace that should be preserved.
- `ps_replay_post_conflict_audit.py`: scans staged or working-tree source diffs for common conflict artifacts: duplicate old structs/fields, obsolete 5.7 APIs, stale labels, and large added blocks. Use after hunk helpers/rewrite conflicts and before build attempts.
- `ps_replay_resolve_conflicts.py`: inspection-only conflict display with nearby reference context.
- `ps_replay_resolve_hunks.py`: best-effort conflict-block resolver; it may replace only conflict blocks, never whole files. Review its output before continuing. Unlike the other helpers it takes the reference as a positional argument and has no `--worktree`, so run it from inside the worktree: `ps_replay_resolve_hunks.py $REFERENCE_BRANCH <path>...` or `--all`. Exit 1 means some regions were left intact for manual work, not that the run failed.
- `ps_replay_residual_audit.py`: classifies final residual diff hunks before reconciliation.
- `ps_replay_watchdog.sh`: progress / hang-up heartbeat for a running driver or build. Polls
  `driver.rc` / `build.rc` every `POLL` seconds (default 1) and exits 0 within ~1s of either
  appearing; prints one status line per heartbeat tick (default 300s); exits 2 when head, source
  index and log mtime are all unchanged for `STALL_TICKS` ticks. Use it for every wait; see
  Progress Heartbeat And Completion Detection.

Library modules, never invoked directly:

- `ps_replay_feature_gate.py`: per-commit feature-gate implementation. Do not run it as a command (see the Replay Loop rule against per-commit gating), but do not delete it either: `ps_replay_range_feature_gate.py` imports it as a module for identifier extraction, subject/body/diff access, and changed/added path lookup. It must stay next to the range gate on `sys.path`.

Tests:

- `scripts/test_*.py` are plain `unittest` files with no third-party dependencies. Run the suite with `python3 -m unittest discover -s scripts -p 'test_*.py'`, or a single file with `python3 scripts/test_<name>.py`, from a checkout where the scripts sit on `sys.path`. They cover HP-8 path bucketing and marker handling in the batch driver, the feature-gate decision table and its stop/proceed hints, reference-matching whitespace in `ps_replay_diff_check.py`, and hunk selection in `ps_replay_resolve_hunks.py`. Keep them passing when changing a helper; a failure there means a replay rule changed behavior, not that a test is stale.

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

For long runs, the report is the primary detail sink. User-facing progress can
stay compact: `idx`, source SHA, decision (`applied`, `skip`, `hunk-drop`,
`rewrite-replacement`, `conflict`, `build-pass`, `build-fail`), output SHA or
no-output exception, and log path.

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

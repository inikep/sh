---
name: ps-port-grouped
description: Use when porting a Percona Server commit range onto an output branch, grouping non-build-changing commits before build-changing commits, preserving per-commit buildability, resolving conflicts hunk-by-hunk, and requiring the final tree to match a reference branch.
---

# Percona Server Grouped Port

## Definitions

- `$INPUT_RANGE` — source commit range to port, equal to `$INPUT_BASE..$INPUT_TIP` and enumerated with `git rev-list --reverse`.
- `$OUTPUT_BASE` — destination base where the output history starts.
- `$OUTPUT_NAME` — output branch created by the skill.
- `$REFERENCE` — known-good target tree; the final `$OUTPUT_NAME` tip must have a null diff against it.
- `build_changing` — path-derived flag for commits that touch build-relevant inputs. Set it to 1 when any changed path has one of these extensions: `.h`, `.c`, `.cc`, `.cxx`, `.cpp`, `.hh`, `.hpp`, `.hxx`, `.cmake`, `.i`, `.ic`; or when the basename is exactly `CMakeLists.txt`. Exact file-name matching matters: `scripts/CMakefile.txt` is ignored because `CMakefile.txt` is not in the build-changing file-name set.
- `n_conflicts` — per-commit field: number of conflicted files in the latest real cherry-pick attempt. Counters are **latest-attempt values**, not max-seen history; keep older counters only when no new real attempt has been made for that commit.
- `n_build_error` — per-commit field: number of distinct root-cause build error groups from the latest real failing build attempt, not the raw diagnostic-line count. Count repeated diagnostics for the same missing symbol, missing struct/class member, missing source file, undefined reference, or identical compiler/CMake message as one error. Count unrelated root causes separately. When the build exit code is 0, record `n_build_error=0` even if the log contains non-fatal text matching `error:`.
- `n_symbol_pull` — per-commit field: number of forward symbols BDF must pull to make the current commit build in the latest attempt. This is latest-attempt scope, not cumulative across abandoned attempts.
- `remaining_commits` — working set of `build_changing=1` commits that still need to be ported. Each entry stores the commit id, deferral history, assigned `deferred_changes`, and the latest `n_conflicts`, `n_build_error`, and `n_symbol_pull` values measured for that commit.
- `deferred_changes` — active list of code intentionally deferred during BDF. For each entry, record the skipped hunk or symbol, why it was deferred, and the commit in `remaining_commits` that must reintroduce it. When processing that assigned commit, apply its `deferred_changes` entries before deciding whether the commit landed successfully.
- `CDF` / `Conflict-Driven Fix` — hunk-by-hunk conflict resolution using later commits or `$REFERENCE`. Do not use whole-file snaps from `$REFERENCE` unless explicitly authorized.
- `COUNTER_STATE_TSV` — durable attempt ledger for `remaining_commits`. Store it outside the source tree, usually `/tmp/$JOB_NAME.counter-state.tsv`. Each real attempt must upsert one row with `sha`, `n_conflicts`, `n_build_error`, `n_symbol_pull`, `status`, and `subject`.

## BDF Methods

- `BDF` / `Build-Driven Fix` — minimal build repair for the current commit. Pull only the smallest later-range or `$REFERENCE` *symbols, macros, enum values, declarations, or includes* needed to make the commit build — never a whole later commit, because its tail of unrelated additions (new sysvars, tests, headers) cascades into fresh undefined-symbol errors. BDF may defer incoming code, or code already committed in `$OUTPUT_NAME`, when deferral reduces the size or risk of the current fix. Every deferral must be recorded in `deferred_changes`. Do not pull unrelated future changes forward.
- When `$REFERENCE` changes an API signature and the current cherry-pick leaves old declarations behind, keep the `$REFERENCE` API shape and pull the minimal matching declarations, vtable members, implementations, and call-site arguments. Do not repair the build by reverting call sites back to the old API if `$REFERENCE` has already moved forward.
- For the VIO SSL shutdown case, if `$REFERENCE` uses `vio_ssl_shutdown(vio, SHUT_RDWR);`, preserve the two-argument shutdown API: `vio_shutdown(Vio*, int)`, `vio_ssl_shutdown(Vio*, int)`, all `vioshutdown` function pointers, pipe/shared-memory implementations, and direct `vio_shutdown(..., SHUT_RDWR)` call sites must be updated together as one symbol pull.
- For global mutex/status symbols, pull the whole minimal lifecycle as one symbol group: extern declaration, storage definition, PSI key declaration and `all_server_mutexes` entry when applicable, init call, destroy call, and any direct status variable definition. Do not pull neighboring globals or registry rows that are not required by the current undefined symbol.
- Before accepting broad surrounding context in a conflict or pulling BDF symbols from `$REFERENCE`, inspect the current source commit's own diff for the affected file (`git show --stat --name-only --no-ext-diff "$SHA"` and targeted `git show --unified=<N> "$SHA" -- <file>`). If the candidate context contains feature blocks, schema tables, parser tokens, status variables, typedefs, globals, or init/free hooks that are not introduced by the current source commit and are owned by a later `remaining_commits` entry, do not pull them forward. Remove or defer those blocks and record them in `deferred_changes` for the owning later commit.
- In shared registry files (`sql/sql_yacc.yy`, `sql/sql_cmd.h`, `sql/sql_show.cc`, `sql/mysqld.cc`, `sql/handler.h`, and similar enum/table/list files), treat each token, enum value, status row, field array, schema table row, sysvar row, typedef, global, and init/free hook as a separate symbol. Pull only the entries required by the current commit. Same-file proximity is not evidence of relatedness.

## Hard Prohibitions

- **HP1** Do not replay the range chronologically by default.
- **HP2** Do not cherry-pick from memory or from raw `git rev-list` order once the waiting set exists.
- **HP3** Do not keep pushing through a commit that exceeds the current pass budget.
- **HP4** Do not finish a commit attempt without printing `n_conflicts`, `n_build_error`, `n_symbol_pull`, and whether the commit landed or stayed in `remaining_commits`.
- **HP5** Do not leave a known-bad build on `$OUTPUT_NAME`.
- **HP6** Do not use whole-file snaps from `$REFERENCE` unless explicitly authorized.
- **HP7** Do not use bulk ours/theirs strategies.
- **HP8** Do not use auto-take-incoming sweepers.
- **HP9** Do not silently choose empty HEAD when `$REFERENCE` still contains the incoming content.
- **HP10** Do not pull unrelated future changes during BDF.
- **HP11** Do not cherry-pick the introducing commit as a BDF shortcut; cherry-picking drags unrelated additions that cascade. Pull only the specific symbols/macros/declarations needed, or defer the feature flag that gates the broken sites.
- **HP12** Do not expand BDF indefinitely when the fix exceeds the symbol budget, cascades into more missing dependencies, or reveals an internal patch bug.
- **HP13** Do not accept unrelated later feature scaffolding just because it appears near the current conflict, in `$REFERENCE`, or in a shared registry file. If a block is not in the current source commit's own diff, it must either be required by a concrete current build error or deferred to its owning later commit.
- **HP14** Do not silently slide from pass execution into final convergence with an unexplained deferred set.
- **HP15** Do not accept a null-diff branch that builds only at the tip.
- **HP16** Do not end a pass without a `remaining_commits` report generated from `COUNTER_STATE_TSV`; a prose summary or partial list is not sufficient.

## Initial Pass

- Parse commits in `$INPUT_RANGE` and compute `build_changing` for each commit.
- Apply all `build_changing=0` commits to `$OUTPUT_NAME` first.
- Initialize `remaining_commits` with the `build_changing=1` commits that still need to be ported. For each entry, initialize `n_conflicts=0`, `n_build_error=0`, `n_symbol_pull=0`, and an empty deferral history.
- Initialize `COUNTER_STATE_TSV` before the first main pass. Use `scripts/record_attempt.sh` for every real commit attempt so pass-end reports do not depend on memory or chat history.
- If the boundary build fails after the Initial Pass, use BDF to make `$OUTPUT_NAME` buildable before starting the main passes. Before editing any source, **triage errors by enclosing `#ifdef`/feature flag**: if >=3 errors share one flag, the first BDF move is to remove the `#define FLAG` line from its defining header (typically a one-line edit). Do not add source comments for the deferral. Record the deferral in the run notes/output as `deferred_changes: feature-flag FLAG - re-enabled by <introducing-commit>` (or, when no input-range commit re-enables it, by the final REFERENCE snap). Then build; only fall back to per-site surgical BDF for errors that remain.

## Main Passes

- After each commit attempt, update that commit's `remaining_commits` entry with the measured latest-attempt `n_conflicts`, grouped `n_build_error`, and `n_symbol_pull`, then print those values and whether the commit landed or stayed in `remaining_commits`. Immediately persist the same counters with `scripts/record_attempt.sh "$COUNTER_STATE_TSV" "$SHA" "$n_conflicts" "$n_build_error" "$n_symbol_pull" "$status"`.
- During conflict resolution, run a feature-leak check before the first build: compare staged additions against the current source commit's own changed symbols. If staged additions include unrelated later feature names in shared registry files, remove or defer them before building. This check is mandatory when the current commit touches `sql/sql_yacc.yy`, `sql/sql_show.cc`, `sql/mysqld.cc`, `sql/sql_cmd.h`, or `sql/structs.h`.
- After each pass, regenerate the remaining SHA file with `scripts/refresh_remaining.sh "$OUTPUT_BASE" "$INPUT_BASE" "$INPUT_TIP" "$REMAINING_SHAS" "${BC_TSV:-}" "${REMOVED_SHAS:-}"` and print the mandatory pass report with `scripts/report_remaining.sh "Pass N" "$REMAINING_SHAS" "$COUNTER_STATE_TSV"`. The report must list every current `remaining_commits` entry, in current pass order, with columns `sha`, `n_conflicts`, `n_build_error`, `n_symbol_pull`, `status`, and `subject`. If a commit has not yet been attempted, its counters must print as `0 0 0` and status as `UNTRIED`. Empty `remaining_commits` is valid and must still produce a report; do not use raw `grep -vxFf ...` pipelines that fail when the result is empty.
- For each pass, iterate through the commits in the current `remaining_commits` order. Remove a commit from `remaining_commits` only after its counters are updated, it lands successfully, and the resulting output commit builds.
- **Pass 1** — cherry-pick each commit and update `n_conflicts` from the real conflicted-file count. Resolve conflicts with CDF while `n_conflicts <= 4`, then build and update grouped `n_build_error` from the real build output. Repair with BDF while `n_build_error <= 4` and `n_symbol_pull <= 1`, updating `n_symbol_pull` as BDF pulls symbols. If any limit is exceeded, abort or roll back the attempt and keep the commit in `remaining_commits` with its latest counter values.
- **Pass 2** — repeat the Pass 1 procedure for commits still in `remaining_commits`, but use wider limits: `n_conflicts <= 8`, `n_build_error <= 8`, and `n_symbol_pull <= 2`.
- **Pass 3** — repeat the Pass 2 procedure for commits still in `remaining_commits`, but use wider limits: `n_conflicts <= 16`, `n_build_error <= 16`, and `n_symbol_pull <= 4`.
- **Pass 4** — repeat the Pass 3 procedure for commits still in `remaining_commits`, but allow at most one Pass 3 limit to be exceeded: `n_conflicts > 16`, `n_build_error > 16`, or `n_symbol_pull > 4`. The attempt must still remain BDF-eligible. Keep a history of why each unlanded commit stayed in `remaining_commits`.
- **Pass 5** — handle the commits that remain after Pass 4 with no conflict, build-error, or symbol-pull limits. Continue resolving conflicts with CDF and build failures with BDF until each attempted commit either lands with a passing build or is explicitly deferred for a concrete blocker. Show the user the conflicts for each commit still in `remaining_commits` and include the deferral history from earlier passes before applying resolutions.
- After `remaining_commits` is empty, run `scripts/final_snap_report.sh "$REFERENCE" HEAD` before creating the final snap. If the report shows unexpected `whitespace_only_files` or many `diff_check_whitespace_issues`, decide whether those residuals should have been ported earlier before staging the snap.
- Create the final whole-tree snap with `scripts/apply_reference_snap.sh "$REFERENCE"` instead of raw `git diff "$REFERENCE" | git apply`; the wrapper prints the residual-diff report, stages the reference tree, and verifies the staged tree has a null diff to `$REFERENCE`.
- After the final snap commit, verify both `git diff HEAD "$REFERENCE"` is empty and a committed-tree build exits with code 0.
- The run is complete only when every output commit builds, the final diff is null, and the final committed-tree build passes.


## Helper Scripts

The `scripts/` directory holds small shell helpers that codify recurring mechanics. Use them; don't reinvent.

- `scripts/classify_build_changing.sh <BASE> <TIP>` — emits a TSV (`sha\tbc\tn_files\tsubject`) for every commit in the range, with `bc=1` iff any changed path is build-relevant per the `build_changing` definition. Run once at Initial Pass to drive the bucketing.
- `scripts/build_remaining.sh <OUTPUT_BASE> <INPUT_BASE> <INPUT_TIP> [BC_TSV]` — emits the subject-matched, not-yet-landed SHAs (one per line). Use to refresh `remaining_commits` after each landing; subject match handles cherry-pick SHA changes while keeping the input range and output branch base separate.
- `scripts/refresh_remaining.sh <OUTPUT_BASE> <INPUT_BASE> <INPUT_TIP> <OUT_FILE> [BC_TSV] [REMOVED_SHAS_FILE]` — safely writes the current remaining SHA file, optionally removing manually excluded SHAs, and exits 0 even when the resulting list is empty. Prefer this over hand-written `build_remaining.sh | grep ...` pipelines.
- `scripts/final_snap_report.sh <REFERENCE> [BASE_COMMIT]` — reports final snap size, whitespace-only files, semantic files, and diff-check whitespace issues before the reference convergence snap.
- `scripts/apply_reference_snap.sh <REFERENCE>` — requires a clean worktree, runs `final_snap_report.sh`, stages the final reference snap with whitespace warnings suppressed at apply time, and verifies the staged tree is null-diff to `$REFERENCE`.
- `scripts/probe.sh <SHA>` — tentative cherry-pick + build that **always rolls back**. Prints TSV `sha\tn_conflicts\tn_build_error\tsubject`. Use to fingerprint each commit in `remaining_commits` before deciding pass order; never use it to make progress.
- `scripts/try_apply.sh <SHA> [BUILD_DIR]` — the real per-commit attempt. Cherry-picks with `--allow-empty --keep-redundant-commits`; on conflict, **leaves the cherry-pick in progress** so the caller can do hunk-level CDF; on build failure rolls back. Exit code: `0`=LANDED, `1`=CONFLICT (CDF needed), `2`=BUILD-FAIL (BDF or defer). Always prints the three counters plus status.
- `scripts/count_build_errors.sh [--build-rc RC]` — normalizes build output into grouped root-cause errors. Use its count for `n_build_error`; do not substitute raw `grep -c` diagnostic counts. Pass the real build exit code with `--build-rc "$rc"` so successful builds always count as 0 even when logs contain non-fatal diagnostics.
- `scripts/record_attempt.sh <COUNTER_STATE_TSV> <SHA> <n_conflicts> <n_build_error> <n_symbol_pull> <status>` — upserts one real-attempt row in the durable counter ledger. Run it after every landed, deferred, conflict, build-fail, aborted, or rolled-back attempt.
- `scripts/report_remaining.sh <PASS_LABEL> <REMAINING_SHAS> <COUNTER_STATE_TSV>` — prints the mandatory full pass-end `remaining_commits` report. Run it before saying a pass is complete.

Both `probe.sh` and `try_apply.sh` use `--allow-empty --keep-redundant-commits` so that commits whose tree-effect is already in HEAD (squashed earlier in the rebase) land as empty commits instead of getting stuck in a cherry-pick state.

## Build Configuration

Use an out-of-tree build directory under `/tmp`. Define `JOB_NAME` from the output branch when the task does not specify one:

```sh
SOURCE_DIR=$(git rev-parse --show-toplevel)
JOB_NAME=${JOB_NAME:-${OUTPUT_NAME//[^A-Za-z0-9_.-]/_}}
BUILD_DIR=${BUILD_DIR:-/tmp/$JOB_NAME}
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"
```

Default build configuration — override via task instructions if the user specifies:

```sh
CC=gcc-9 CXX=g++-9 cmake "$SOURCE_DIR" \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_CXX_FLAGS="-fpermissive" \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache \
  -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DMYSQL_MAINTAINER_MODE=OFF \
  -DDOWNLOAD_BOOST=1 \
  -DWITH_BOOST=/tmp/boost \
  -DWITHOUT_TOKUDB=1 \
  -DWITH_ROCKSDB=OFF \
  -DENABLE_DOWNLOADS=1 \
  -DWITH_READLINE=system
make -j$(( $(nproc) * 3 / 4 ))
```

For pass attempts, capture the build return code and pass it to the grouped counter:

```sh
SKILL_DIR=/data/sh/skills/ps-port-grouped
make -j$(( $(nproc) * 3 / 4 )) > "$BUILD_LOG" 2>&1
rc=$?
echo "BUILD_RC=$rc"
"$SKILL_DIR/scripts/count_build_errors.sh" --build-rc "$rc" < "$BUILD_LOG"
exit "$rc"
```

## Definitions

- `$INPUT_RANGE` — source commit range to port, equal to `$INPUT_BASE..$INPUT_TIP` and enumerated with `git rev-list --reverse`.
- `$OUTPUT_BASE` — destination base where the output history starts.
- `$OUTPUT_NAME` — output branch created by the skill.
- `$REFERENCE` — known-good target tree; the final `$OUTPUT_NAME` tip must have a null diff against it.
- `build_changing` — path-derived flag for commits that touch build-relevant inputs. Set it to 1 when any changed path has one of these extensions: `.h`, `.c`, `.cc`, `.cxx`, `.cpp`, `.hh`, `.hpp`, `.hxx`, `.cmake`, `.i`, `.ic`; or when the basename is exactly `CMakeLists.txt`. Exact file-name matching matters: `scripts/CMakefile.txt` is ignored because `CMakefile.txt` is not in the build-changing file-name set.
- `n_conflicts` — per-commit field: number of conflicted files in the latest real cherry-pick attempt.
- `n_build_error` — per-commit field: number of build errors from the latest real build attempt.
- `n_symbol_pull` — per-commit field: number of forward symbols BDF must pull to make the current commit build in the latest attempt.
- `remaining_commits` — working set of `build_changing=1` commits that still need to be ported. Each entry stores the commit id, deferral history, assigned `deferred_changes`, and the latest `n_conflicts`, `n_build_error`, and `n_symbol_pull` values measured for that commit.
- `BDF` / `Build-Driven Fix` — minimal build repair for the current commit. Pull only the smallest later-range or `$REFERENCE` *symbols, macros, enum values, declarations, or includes* needed to make the commit build — never a whole later commit, because its tail of unrelated additions (new sysvars, tests, headers) cascades into fresh undefined-symbol errors. BDF may defer incoming code, or code already committed in `$OUTPUT_NAME`, when deferral reduces the size or risk of the current fix. Every deferral must be recorded in `deferred_changes`. Do not pull unrelated future changes forward.
- `deferred_changes` — active list of code intentionally deferred during BDF. For each entry, record the skipped hunk or symbol, why it was deferred, and the commit in `remaining_commits` that must reintroduce it. When processing that assigned commit, apply its `deferred_changes` entries before deciding whether the commit landed successfully.
- `CDF` / `Conflict-Driven Fix` — hunk-by-hunk conflict resolution using later commits or `$REFERENCE`. Do not use whole-file snaps from `$REFERENCE` unless explicitly authorized.

## Prohibitions

- Do not replay the range chronologically by default.
- Do not cherry-pick from memory or from raw `git rev-list` order once the waiting set exists.
- Do not keep pushing through a commit that exceeds the current pass budget.
- Do not finish a commit attempt without printing `n_conflicts`, `n_build_error`, `n_symbol_pull`, and whether the commit landed or stayed in `remaining_commits`.
- Do not leave a known-bad build on `$OUTPUT_NAME`.
- Do not use whole-file snaps from `$REFERENCE` unless explicitly authorized.
- Do not use bulk ours/theirs strategies.
- Do not use auto-take-incoming sweepers.
- Do not silently choose empty HEAD when `$REFERENCE` still contains the incoming content.
- Do not pull unrelated future changes during BDF.
- Do not cherry-pick the introducing commit as a BDF shortcut; cherry-picking drags unrelated additions that cascade. Pull only the specific symbols/macros/declarations needed, or defer the feature flag that gates the broken sites.
- Do not expand BDF indefinitely when the fix exceeds the symbol budget, cascades into more missing dependencies, or reveals an internal patch bug.
- Do not silently slide from pass execution into final convergence with an unexplained deferred set.
- Do not accept a null-diff branch that builds only at the tip.

## Initial Pass

- Parse commits in `$INPUT_RANGE` and compute `build_changing` for each commit.
- Apply all `build_changing=0` commits to `$OUTPUT_NAME` first.
- Initialize `remaining_commits` with the `build_changing=1` commits that still need to be ported. For each entry, initialize `n_conflicts=0`, `n_build_error=0`, `n_symbol_pull=0`, and an empty deferral history.
- If the boundary build fails after the Initial Pass, use BDF to make `$OUTPUT_NAME` buildable before starting the main passes. Before editing any source, **triage errors by enclosing `#ifdef`/feature flag**: if ≥3 errors share one flag, the first BDF move is to comment out the `#define FLAG` line in its defining header (typically a one-line edit). Record the deferral as `deferred_changes: feature-flag FLAG — re-enabled by <introducing-commit>` (or, when no input-range commit re-enables it, by the final REFERENCE snap). Then build; only fall back to per-site surgical BDF for errors that remain.

## Main Passes

- After each commit attempt, update that commit's `remaining_commits` entry with the measured `n_conflicts`, `n_build_error`, and `n_symbol_pull`, then print those values and whether the commit landed or stayed in `remaining_commits`.
- For each pass, iterate through the commits still in `remaining_commits`. Remove a commit from `remaining_commits` only after its counters are updated, it lands successfully, and the resulting output commit builds.
- **Pass 1** — cherry-pick each commit and update `n_conflicts` from the real conflicted-file count. Resolve conflicts with CDF while `n_conflicts <= 4`, then build and update `n_build_error` from the real build output. Repair with BDF while `n_build_error <= 4` and `n_symbol_pull <= 1`, updating `n_symbol_pull` as BDF pulls symbols. If any limit is exceeded, abort or roll back the attempt and keep the commit in `remaining_commits` with its latest counter values.
- **Pass 2** — repeat the Pass 1 procedure for commits still in `remaining_commits`, but use wider limits: `n_conflicts <= 8`, `n_build_error <= 8`, and `n_symbol_pull <= 2`.
- **Pass 3** — repeat the Pass 2 procedure for commits still in `remaining_commits`, but use wider limits: `n_conflicts <= 16`, `n_build_error <= 16`, and `n_symbol_pull <= 4`.
- **Pass 4** — repeat the Pass 3 procedure for commits still in `remaining_commits`, but allow at most one Pass 3 limit to be exceeded: `n_conflicts > 16`, `n_build_error > 16`, or `n_symbol_pull > 4`. The attempt must still remain BDF-eligible. Keep a history of why each unlanded commit stayed in `remaining_commits`.
- **Pass 5** — handle the commits that remain after Pass 4. Show the user the conflicts for each commit still in `remaining_commits`, include the deferral history from earlier passes, and ask how each conflict should be resolved.
- After `remaining_commits` is empty, create the final whole-tree snap to `$REFERENCE`.
- The run is complete only when every output commit builds, the final diff is null, and the final build passes.


## Build Configuration

Use `/tmp` for builds.
Default — override via task instructions if the user specifies:

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
  -DWITH_READLINE=system
make -j$(( $(nproc) * 3 / 4 ))
```

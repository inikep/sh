---
name: ps-replay+make-buildable
description: "Use to replay a chain of Percona Server commits onto a different mysql base (e.g. mysql-5.6.x → mysql-5.7.x), using a known-buildable reference branch as the conflict-resolution oracle, with per-commit buildability and a final null diff to the reference. Reorder structural commits by least-conflict greedy when allowed; back-port files/commits from later in the chain to keep intermediate commits buildable."
metadata:
  short-description: Reference-guided cross-base cherry-pick replay with per-commit full-build verification.
---

## Sources / lineage

Consolidated execution guide for what the operator sometimes calls "porting and rebase" or "cherry-pick and reconcile". Supersedes the per-run task definitions:

- `ps-cherry-pick-and-make-buildable-orig.txt` — original concise rule set (algorithm + CMake options).
- `ps-porting_task_definition-gemini.md` — formalised "Mandatory Rules" framing.
- `ps-cherry-pick-task-opus.md` — explicit Inputs/Goal/Rules + report-field specification.

When all three disagree (typically on per-commit build cadence, whole-file vs hunk-only conflict resolution, or where to root `$OUTPUT_BRANCH`), this skill follows the strictest reading: **per-commit full build, snap-to-reference whenever needed, root at the destination mysql tag (not at `$BASE_BRANCH`)**. Reasons are recorded inline.

## Working agreement

Use this skill when the engineer asks to materialise a Percona patch chain on top of a different mysql base than the one it was authored against — the canonical case is replaying `mysql-5.6.x..ps-replay-5.6.x-…` onto `mysql-5.7.x` so the resulting branch is identical to a hand-prepared "merged" reference branch (e.g. `ps-gpt-5.7.9`) but built one cherry-pick at a time.

### Inputs

| Variable | Meaning |
|---|---|
| `BASE_BRANCH` | Branch whose tip is the lower bound of `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH` (e.g. `mysql-5.6.26`). Note: `$OUTPUT_BRANCH` is *not* rooted here — see goal #1. |
| `TIP_BRANCH` | Tip of the source chain (e.g. `ps-replay-5.6.26-no-rebase-ref5.6.26-snap-reo`). |
| `REFERENCE_BRANCH` | Pre-existing buildable branch whose final tree is the truth (e.g. `ps-gpt-5.7.9`). Conflict oracle. |
| `OUTPUT_BRANCH` | Branch you produce (e.g. `ps-opus-5.7.9-buildable`). Rooted at a different mysql base (e.g. `mysql-5.7.9`) — *not* at `$BASE_BRANCH`. |
| `LLM_MODEL` | Identifier including reasoning level (e.g. `opus-4.7-high`). |
| `REPORT_FILE` | `/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}.md` |

The `$BASE_BRANCH` is used only to define the rev-range; do not root `$OUTPUT_BRANCH` there. Root `$OUTPUT_BRANCH` at the mysql tag the engineer specifies for the destination side (the "based on top of …" phrase in the prompt). The two opus/gemini task definitions diverge on this point — opus says "rooted at `$BASE_BRANCH`", which is wrong for the cross-base case; the runbook root is the destination mysql tag.

### Goal

Produce `$OUTPUT_BRANCH` such that:

1. It is rooted at the destination mysql tag (e.g. `mysql-5.7.9`), *not* at `$BASE_BRANCH`.
2. It contains every commit from `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH`, cherry-picked one at a time (`--allow-empty` permitted).
3. Every commit on `$OUTPUT_BRANCH` builds successfully under the engineer's CMake configuration, **except** the base commit (the destination mysql tag) which is exempt by spec.
4. `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty (null diff at the tip).
5. `$REPORT_FILE` documents apply-order, conflicts, resolutions, and per-commit build verification.

A "successful build" means **`cmake` configuration and the `make` step both complete without errors**, and the default target produces (at minimum) `sql/mysqld`.

## Mandatory rules (non-negotiables)

1. **Cherry-pick one by one.** Iterate `git cherry-pick --allow-empty <sha>` for every commit in the rev-range. Empty cherry-picks (markers, post-snap redundancies) are kept with `--allow-empty`. Do not use a single `git merge` or a wholesale `git read-tree` to short-circuit the entire chain.
2. **Conflicts resolved against `$REFERENCE_BRANCH` and only `$REFERENCE_BRANCH`.** The original spec says *"replace ONLY the `<<<<<<<` / `=======` / `>>>>>>>` regions with the corresponding region from `$REFERENCE_BRANCH`"*. In practice that hunk-only operation is unworkable when the reference branch has diverged structurally (file moved, file deleted, file rewritten). Practical adaptation:
   - **If F exists in `$REFERENCE_BRANCH`** and the file structure aligns: hunk-only (replace each conflict block with the corresponding region in `git show $REFERENCE_BRANCH:F`) — produces a smaller, more reviewable per-commit diff. Prefer this when the file context lines up cleanly.
   - **If F exists but has diverged structurally**: whole-file fetch — `git show $REFERENCE_BRANCH:F > F && git add F`. This supersets the hunk operation and is the only viable resolution when hunk-only would not converge.
   - **If F does not exist in `$REFERENCE_BRANCH`**: `git rm -f F` (file deleted upstream).
   - Never hand-merge, never invent content, never search the network for the resolution.
3. **Per-commit buildability except the base.** Every commit on `$OUTPUT_BRANCH` must build cleanly under the engineer-specified CMake config. The base commit (= the destination mysql tag) is the only exception. Buildability uses the engineer's exact CMake flags and `make -j<N>` value.
4. **Full `make`, not `make mysqld`.** "Buildable" means the full default `make -j<N>` target succeeds (which on this codebase includes `mysqld`, `mysql_client_test_embedded`, `udf_example`, `pfs_connect_attr-t`, `my_safe_process`, etc.). `make -j<N> mysqld` alone gives false positives — `testclients/` link against `perconaserverclient` while `libmysql/CMakeLists.txt` still produces `mysqlclient` in many intermediate hybrid trees, and that mismatch is invisible to the `mysqld` target. **Always verify the default target.**
5. **Back-port from later commits is allowed and expected.** When a cherry-picked commit produces a hybrid tree that does not build (5.7.x base + partial 5.6.x patch overlay), back-port from `$REFERENCE_BRANCH` (which is the union of all later commits + the merge with mysql-5.7.x) until the commit builds. Two granularities, prefer the smallest:
   - **File-level back-port**: `git checkout $REFERENCE_BRANCH -- <path>` for the specific files the build error names. Smallest, most auditable. Always try this first when the build error names a small set of files.
   - **Tree-level snap (maximal back-port)**: rewrite the commit with `git commit-tree $REF_TREE -p $PARENT -m "$ORIG_MSG"` (preserves author, committer, dates, message — only tree changes). Use when file-level back-port would require chasing a transitive closure of dependencies.
6. **Reordering inside the "Initial Percona Server <X.Y.Z> tree: \<subdir\>/" structural group is greedy-least-conflict.** Within that group only — bug-fix `[#NN]` and upstream-MTR squashes stay in their original chain order. For each greedy step: trial-cherry-pick every remaining candidate (counting `git diff --name-only --diff-filter=U` plus unmerged `git status -s` entries), pick the candidate with the fewest conflicts, apply it, repeat. Do not reorder the rest of the chain unless the engineer explicitly asks.
7. **Final null diff.** `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` must be empty. If it is not, **prefer adding an explicit final reconciliation commit** (auditable; the report explains it) over silently amending the tip. The reconciliation commit's body must enumerate the residual diff (file names + brief reason: "submodule pointer", "files deleted upstream by mysql-5.7.x merge", "scripts mode bits 644→755", etc.).
8. **Tooling restrictions.**
   - Do **not** run scripts from `/data/sh/utils`.
   - Do **not** invoke the `percona_conflict_resolution_tdd` or `percona_gca_sync_tdd` skills. Those target different problems and will steer off-spec.
9. **No partial-then-full `make` in the same build dir.** Only run the full `make -j<N>` per build state. `make -j<N> mysqld` first then `make -j<N>` afterwards in the same build dir reliably produces spurious dependency-graph race failures (`cannot find -lperconaserverclient`, `mysqld_error.h: No such file or directory`). When you need to verify, do `rm -rf $BUILD_DIR/* && cmake … && make -j<N>` once per state.

## Bundled scripts

The skill ships executable helpers in `~/.claude/skills/ps-replay+make-buildable/scripts/`. Use them rather than re-implementing inline:

| Script | Purpose |
|---|---|
| `cherrypick_one.sh <sha>` | One cherry-pick + reference-guided conflict resolution. Requires `REFERENCE_BRANCH` env. |
| `greedy_pick.sh <sha-list-file>` | Greedy least-conflict-first reorder for the structural block. Calls `cherrypick_one.sh`. |
| `snap_range.sh <last-good-sha> <range-shas-file>` | Rewrite a contiguous commit range so each commit has `tree == $REFERENCE_BRANCH^{tree}`, preserving author/committer/dates/message. Requires `REFERENCE_BRANCH` and `OUTPUT_BRANCH` env. |
| `verify_buildable.sh <sha-list-file>` | Walk SHAs, full `make -j<N>`, cache-wipe-on-stale + retry. Requires `BUILD_DIR`, `REPO`, `MAKE_JOBS`, `CMAKE_FLAGS` env. Writes `/tmp/verify_failed.txt`. |
| `snap_tip.sh` | Add an explicit reconciliation commit if `git diff HEAD $REFERENCE_BRANCH` is non-empty; commit body enumerates the residual diff. |

Examples — see Phase 1, 1.5, 2, 3, 4 below.

## Required tooling

| Tool | Purpose |
|---|---|
| `git`, `git rev-list`, `git cherry-pick`, `git read-tree`, `git checkout-index`, `git commit-tree`, `git update-ref` | The replay engine. |
| `cmake`, `make -j<N>` | Build verification. Use the engineer's specified `<N>` (typical: `80`); do not default to `$(nproc)` if the box has more cores than the engineer's value. |
| `gcc-9`, `g++-9` | Default compiler unless the engineer specifies otherwise. The codebase is calibrated for gcc-9 — the leading `Fix gcc-9 compilation issues` commit at the bottom of the chain is exactly that calibration. gcc-13+ fails on `std::byte` ↔ InnoDB `#define byte unsigned char` collision (`storage/innobase/include/univ.i:438`); that failure is *inherent to the reference* — do not "fix" it. |
| Stale-cache reset | `rm -rf $BUILD_DIR/* && cmake …` whenever `make` reports `cmake_check_build_system Error 1`, `Configuring incomplete`, or `Cannot configure WITH_READLINE and WITH_EDITLINE!`. The CMakeLists files churn between commits; preserved caches are unreliable. |

## Build configuration

The default configuration the operator uses (override only if the engineer specifies different flags):

```sh
CC=gcc-9 CXX=g++-9 cmake $REPO \
  -DCMAKE_BUILD_TYPE=Debug \
  -DMYSQL_MAINTAINER_MODE=OFF \
  -DDOWNLOAD_BOOST=1 \
  -DWITH_BOOST=/tmp/boost \
  -DWITHOUT_TOKUDB=1 \
  -DENABLE_DOWNLOADS=1 \
  -DWITH_READLINE=system
make -j80
```

Build dir: out-of-tree, typically `/tmp/build-test-<id>`. `WITH_READLINE=system` is silently ignored at the reference's HEAD CMakeLists (only `WITH_EDITLINE` is honoured); leave the flag in the configure line because the engineer specifies it.

## Workflow

The workflow is **prepare → replay → snap-on-failure → verify per-commit → align tip → report**. Do not skip steps; the order matters.

### Phase 0 — Prepare

1. Cd to the working repo. Confirm `git status` is clean.
2. Resolve `$LLM_MODEL`, `$REPORT_FILE`, all branch variables. Confirm the engineer's CMake configuration. Note the `-j<N>` value (default `-j80`).
3. Confirm `$REFERENCE_BRANCH` itself builds with the engineer's flags. If it does not, stop and report — the spec is malformed.
4. Build the source chain list: `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH > /tmp/cherry_list.txt`. Record `wc -l`. The chain length is typically 100–200.
5. Identify the gcc-fix commit at the *top* of `$REFERENCE_BRANCH` (e.g. `Fix gcc-9 compilation issues`). It is *not* part of `$BASE_BRANCH..$TIP_BRANCH` — it lives only on `$REFERENCE_BRANCH`. Apply it as the very first commit on `$OUTPUT_BRANCH` so the base toolchain is clean.
6. Identify the structural "Initial Percona Server <X.Y.Z> tree: \<subdir\>/" group. There are typically ~22 commits, one per top-level subdir (`build-ps`, `client`, `cmake`, `extra`, `include`, `libmysql`, `libmysqld`, `man`, `mysql-test`, `mysys`, `mysys_ssl`, `plugin`, `regex`, `scripts`, `sql`, `sql-common`, `storage`, `strings`, `support-files`, `unittest`, `vio`, `top-level files`). Note: `build-ps/` is typically applied early in the chain (next to the build-ps fix-up `[#NN]` commits that depend on it) — leave that one in original order. The remaining ~21 are the "structural block" you greedy-reorder.
7. Set up the build dir once: `BUILD=/tmp/build-test-<id>; mkdir -p $BUILD; cd $BUILD; cmake $REPO <flags>; make -j<N>` to confirm baseline at the destination mysql tag (after gcc-fix). Then preserve the dir for incremental verifies.

### Phase 1 — Replay

```sh
git checkout -B $OUTPUT_BRANCH <destination-mysql-tag>
git cherry-pick <gcc-fix-sha>
```

Then iterate the rev-range:

- **Original-order block** (positions 1 .. start-of-structural-block): apply with conflict-resolution against `$REFERENCE_BRANCH`. Build between commits is optional in this region — they are mostly markers/squashes/build-ps additions and rarely break anything.
- **Structural block**: greedy-least-conflict reorder (Phase 1.5 below).
- **Original-order tail** (after structural block): apply with conflict-resolution. Building per-commit during apply is wasteful here — defer to Phase 4. The hybrid trees in this region typically need a tail-snap.

A working cherry-pick helper:

```bash
cherrypick_one() {
  SHA=$1
  REF=$REFERENCE_BRANCH
  git cherry-pick --allow-empty "$SHA" >/dev/null 2>&1 || true
  if [ -f .git/CHERRY_PICK_HEAD ]; then
    CONF=$(git diff --name-only --diff-filter=U; git status -s | awk '/^(UU|UD|DU|AA|DD|AU|UA)/ {print $2}')
    for f in $(echo "$CONF" | sort -u | grep -v '^$'); do
      if git cat-file -e "$REF":"$f" 2>/dev/null; then
        mkdir -p "$(dirname "$f")" 2>/dev/null
        git show "$REF":"$f" > "$f"
        git add "$f"
      else
        git rm -f "$f" 2>/dev/null || rm -f "$f"
      fi
    done
    GIT_EDITOR=true git cherry-pick --continue --no-edit >/dev/null 2>&1
    [ -f .git/CHERRY_PICK_HEAD ] && git commit --allow-empty --no-edit -C "$SHA" >/dev/null
  fi
}
```

### Phase 1.5 — Greedy reorder for the structural block

```bash
REMAINING=$(cat /tmp/structural_block.txt)
while [ -n "$REMAINING" ]; do
  BEST=""
  BEST_COUNT=999999
  for sha in $REMAINING; do
    git cherry-pick --no-commit "$sha" >/dev/null 2>&1
    COUNT=$(( $(git diff --name-only --diff-filter=U | wc -l) + $(git status -s | awk '/^(UU|UD|DU|AA|DD|AU|UA)/' | wc -l) ))
    git reset --hard HEAD --quiet
    git cherry-pick --abort 2>/dev/null
    if [ $COUNT -lt $BEST_COUNT ]; then BEST_COUNT=$COUNT; BEST=$sha; fi
  done
  cherrypick_one "$BEST"
  REMAINING=$(echo "$REMAINING" | grep -v "^$BEST$")
done
```

Record the order picked + conflict counts — they go into the report.

### Phase 2 — Snap on build failure (back-port from later commits)

After the chain is fully replayed, do not assume it is buildable. Two failure modes are typical:

- **Library-rename mismatch.** The structural block leaves a 5.7.x/5.6.x hybrid in which `testclients/CMakeLists.txt` (already percona-flavoured by the early "Squash: miscellaneous legacy paths" commit) references `perconaserverclient`, but `libmysql/CMakeLists.txt` still produces `mysqlclient` because `Initial Percona Server <X.Y.Z> tree: libmysql/` has not landed yet. Build dies with `cannot find -lperconaserverclient` and/or `mysqld_error.h: No such file or directory`. **`make mysqld` does *not* hit this — only the full `make` does.**
- **Original-order-tail drift.** Bug-fix commits drift the tree away from `$REFERENCE_BRANCH`'s merge result on small things (a backed-out fix that 5.7.x already incorporated, a renamed file, a submodule pointer). The drift can break compile.

The cure is **snap to `$REFERENCE_BRANCH`'s tree, preserving original author/message** for each affected commit. Either snap individual commits via `git commit --amend` after `git read-tree $REFERENCE_BRANCH`, or — to snap a contiguous range with metadata preservation — rewrite the range with `git commit-tree`:

```bash
REF_TREE=$(git rev-parse $REFERENCE_BRANCH^{tree})
NEW_PARENT=<sha-of-last-known-good-commit>
while read sha; do
  AN=$(git log -1 --format=%an $sha); AE=$(git log -1 --format=%ae $sha); AD=$(git log -1 --format=%ai $sha)
  CN=$(git log -1 --format=%cn $sha); CE=$(git log -1 --format=%ce $sha); CD=$(git log -1 --format=%ci $sha)
  MSG=$(git log -1 --format=%B $sha)
  NEW_PARENT=$(GIT_AUTHOR_NAME="$AN" GIT_AUTHOR_EMAIL="$AE" GIT_AUTHOR_DATE="$AD" \
               GIT_COMMITTER_NAME="$CN" GIT_COMMITTER_EMAIL="$CE" GIT_COMMITTER_DATE="$CD" \
               git commit-tree $REF_TREE -p $NEW_PARENT -m "$MSG")
done < /tmp/snap_range.txt
git update-ref refs/heads/$OUTPUT_BRANCH $NEW_PARENT
```

Run this for the structural block (every commit ends up with `tree == $REF_TREE`), and again for the original-order tail if Phase 4 finds tail commits that fail the full build. The first commit in each rewritten range carries the entire delta from the previous tree to `$REF_TREE`; subsequent commits are tree-identical (their content is "no change vs predecessor" — kept for audit/history of the cherry-pick chain).

When a single file is enough to repair the build (and you can identify it quickly from the build error), prefer the file-level back-port:

```sh
git checkout $REFERENCE_BRANCH -- <path>
git add <path>
git commit --amend --no-edit
```

Record every back-port in the report (file names + reason + source commit/branch).

### Phase 3 — Tip alignment

```sh
git diff HEAD $REFERENCE_BRANCH --stat
```

If empty, you are done with this phase. If not, *prefer* an explicit reconciliation commit (auditable; future reviewers see exactly what the residual diff was):

```sh
git read-tree $REFERENCE_BRANCH
git checkout-index -a -f
git clean -fdq
git add -A
git commit -m "Reconcile to $REFERENCE_BRANCH: <one-line summary of residual diff>

<bulleted list of file groups + brief reason for each>"
```

The reconciliation commit's body lists the residual diff categories (submodule pointers, files deleted upstream, mode bits, etc.). This is the **audit-friendly alternative to silent `--amend`**. Both produce the same tree; the explicit commit is preferred per opus's spec, and is what reviewers will look at first. Use silent `--amend` only when the residual diff is genuinely zero-information (e.g. CRLF normalisation) and would just clutter history.

### Phase 4 — Per-commit build verification

Walk every commit on `$OUTPUT_BRANCH` from oldest to newest (excluding the destination mysql base commit), in a preserved build dir, with the engineer's exact CMake flags and `make -j<N>`. Use a wipe-on-stale-cache guard. Always verify the **full default target**, not `mysqld`.

```bash
BUILD=/tmp/build-test-<id>
git log --format=%H HEAD ^<destination-mysql-tag> --reverse > /tmp/walk.txt
while read SHA; do
  git checkout -q $SHA
  ( cd $BUILD && timeout 600 make -j<N> >/tmp/build.log 2>&1 )
  if grep -q "Built target mysqld$" /tmp/build.log && ! grep -qE "Error [0-9]" /tmp/build.log; then
    echo "$SHA OK"
  else
    if grep -qE "Cannot configure WITH_READLINE|cmake_check_build_system|Configuring incomplete" /tmp/build.log; then
      ( cd $BUILD && rm -rf * && CC=gcc-9 CXX=g++-9 cmake $REPO <engineer-flags> >/dev/null 2>&1 && timeout 600 make -j<N> >/tmp/build.log 2>&1 )
      grep -q "Built target mysqld$" /tmp/build.log && ! grep -qE "Error [0-9]" /tmp/build.log && { echo "$SHA OK (cache wipe)"; continue; }
    fi
    echo "$SHA FAILED"
    # Snap range from $SHA to current tip and rerun verify (Phase 2).
  fi
done < /tmp/walk.txt
```

If any commit fails, identify a contiguous range `[first_failure..tip]`, rewrite that range with `commit-tree $REF_TREE` (Phase 2), and re-run Phase 4 over the rewritten range.

### Phase 5 — Final clean build

Wipe build dir, fresh `cmake`, fresh `make -j<N>` at HEAD. This is the only build the engineer typically inspects directly. Confirm `[100%] Built target mysql_client_test_embedded` (or equivalent end-target) appears at the end and `sql/mysqld` is produced. Capture the last ~5 lines of `make` output and the `sql/mysqld` size for the report.

### Phase 6 — Report

Write `$REPORT_FILE` in markdown. The report must contain:

- **Header.** `$LLM_MODEL`, date, all branch variables, total commit count (`gcc-fix + N percona cherry-picks`).
- **Summary.** One paragraph: what was replayed, on what base, with what reorder, and the verification headline (null diff confirmed, per-commit build verified, final full build succeeds).
- **Conflict-resolution algorithm.** State exactly what you did (whole-file fetch vs hunk-only) and the modify/delete handling.
- **Greedy reorder table for the structural block.** One row per subdir: `subdir, conflict count at pick time`. Covers the "least-conflict-first" picks.
- **Per-commit table.** One row per cherry-picked commit, in apply order, with these columns:
  - `#` (apply position)
  - `Original SHA` (from `$TIP_BRANCH`)
  - `New SHA` (on `$OUTPUT_BRANCH`)
  - `Subject` (one-line)
  - `Resolution` — one of: `clean` / `conflict (N files, REF whole-file)` / `conflict (N files, REF hunk)` / `back-port files: <list>` / `tree-snap to REF` / `empty (allow-empty)` / `reconciliation`
  - `Build` — `OK` / `OK (cache wipe)` / `OK (after snap)` / `not-built (covered by snap range)`. Net failures must be 0.
- **Per-commit detail entries** for every conflicted, back-ported, or tree-snapped commit:
  - List of conflicted files with one-line reason ("`mysys/waiting_threads.c` deleted upstream", "`sql/sql_class.cc` heavy refactor in 5.7", etc.).
  - Resolution method (REF whole-file / REF hunk / back-port from later commit `<sha>` / tree-snap).
  - Any extra build-fix changes folded in to preserve the buildability invariant.
- **Tip alignment section.** Either "null diff to `$REFERENCE_BRANCH` after final cherry-pick" or "reconciliation commit `<sha>` added with body describing residual diff: <categories>".
- **Build verification.** Per-commit pass/fail counts; final full-build `make -j<N>` output tail; `sql/mysqld` size.
- **Final confirmation.** `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` empty.

Also write a separate task-definition file at `/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}_task_definition.md` capturing: the rules verbatim, the engineer-specified CMake config, every operator clarification applied during the run, and the outcome. This is the artefact future runs will read to repeat the procedure exactly.

## Lessons learned (record these in the report; reapply them on the next run)

- **Stale CMake cache after cross-commit checkout.** As you walk the chain, `CMakeLists.txt` and friends churn (e.g. `WITH_EDITLINE` appears or disappears). The cache from the previous commit's configure can produce false errors like `Cannot configure WITH_READLINE and WITH_EDITLINE!`. The fix is *not* a code change; it is `rm -rf $BUILD_DIR/* && cmake …`. Build the wipe-on-stale-cache guard into your verify loop.
- **Partial-then-full `make` produces spurious link errors.** If you `make -j<N> mysqld` first then `make -j<N>` afterwards, you get `cannot find -lperconaserverclient` and `mysqld_error.h: No such file or directory` from `testclients/`. These look real but they are an artefact of dependency-graph races between artefacts left by the partial build and the full build's recompile order. The fix is procedural: only run full `make -j<N>` per build-dir state; for incremental verifies, also use full `make`, not `make <target>`.
- **Hybrid 5.7.x + partial 5.6.x trees are fundamentally inconsistent.** The structural block's intermediate states (one subdir converted to 5.6.22, the rest still 5.7.9) cannot be made buildable by per-commit conflict resolution alone — vio/mysys/sql APIs disagree across subdirs. Snap-to-reference is the only mechanism. Greedy reordering reduces the *count* of conflicts but does not fix the *coherence* of intermediate states.
- **`make -j$(nproc)` is not always the right knob.** On a 128-thread box, parallel link of 800-MB Debug objects can wedge the system or trigger OOM; `make -j80` avoids this. Use the engineer's specified `<N>` even if `nproc` is larger.
- **`git commit-tree` is the right primitive for tree-snap-with-history.** `git commit --amend` mutates only the tip. To snap a range with metadata preservation, walk the range with `commit-tree $REF_TREE -p $PARENT -m "$ORIG_MSG"` and `git update-ref refs/heads/$OUTPUT_BRANCH $NEW_TIP`.
- **The leading gcc-fix commit on `$REFERENCE_BRANCH` is sourced *out of band*.** It is not in `$BASE_BRANCH..$TIP_BRANCH`. You apply it as the very first commit on `$OUTPUT_BRANCH` so the base toolchain compiles. The other ~147 cherry-picks come from the rev-range as specified.
- **`make -j<N> mysqld` is not a valid buildability check.** It misses the `testclients/perconaserverclient` mismatch class of failure, which only the default target catches. Always verify full `make`.
- **Reconciliation commit > silent amend.** When the tip needs to be aligned to `$REFERENCE_BRANCH`, an explicit "Reconcile to `$REFERENCE_BRANCH`" commit (with a body that enumerates the residual diff) is far easier to review than a silent `--amend`. Both produce the same tree; the explicit commit preserves the audit trail and matches opus's spec.
- **Root `$OUTPUT_BRANCH` at the destination mysql tag, not at `$BASE_BRANCH`.** Opus's task definition gets this wrong for the cross-base case. The runbook root is the destination mysql tag (e.g. `mysql-5.7.9`); `$BASE_BRANCH` (e.g. `mysql-5.6.26`) only defines the lower bound of the rev-range.

## Anti-patterns to avoid

- Resolving conflicts by hand-editing the `<<<<<<< ======= >>>>>>>` markers when `$REFERENCE_BRANCH` already has the file.
- Using `git rebase -i` with `merge` strategy options ("ours"/"theirs") instead of explicit reference-pull. The merge strategies do not match what `$REFERENCE_BRANCH` decided.
- Verifying buildability with `make -j<N> mysqld` only — passes for trees that fail the full build because of percona-vs-mysql library rename mismatches in `testclients/`.
- Doing the final `make` *without* a clean configure when the prior build was a partial target. Use `rm -rf $BUILD_DIR/* && cmake … && make -j<N>` for the final verification.
- Reordering commits outside the structural block. The bug-fix `[#NN]` order is meaningful for git-blame and changelog continuity.
- "Reconcile commits" piled on top of the chain *instead of* snapping the offending range. A trailing reconcile masks per-commit unbuildability and hides what was actually rewritten. Use both: snap the broken range (Phase 2) *and* an explicit reconcile commit at the tip if Phase 3 still has residual diff.
- Rooting `$OUTPUT_BRANCH` at `$BASE_BRANCH` (opus's task definition gets this wrong for the cross-base case). Root at the destination mysql tag.

## When to bail out

- If `$REFERENCE_BRANCH` itself does not build under the engineer's CMake config — stop and report. The reference is the truth; if it cannot build, no replay onto a different base will either, and the spec is malformed.
- If the engineer asks for "every commit buildable" but also "no rewrites at all" — these constraints are mutually exclusive on cross-base replays. Surface the conflict and ask which to relax.
- If the rev-range contains commits whose authorship/message contains data you cannot represent (binary message, PGP-only). Stop and ask.
- If `gcc-9` is not available on the host. The codebase will not build cleanly under newer toolchains; the engineer must install gcc-9 or specify a different reference branch.

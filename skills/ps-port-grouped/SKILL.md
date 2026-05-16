---
name: ps-port-grouped
description: Use when porting a Percona Server commit range from one MySQL base to a newer one (e.g. mysql-5.6.x → mysql-5.7.x) and a known-good REFERENCE branch exists, by categorizing commits, scheduling easy-first in five groups, building after every commit, and converging the output to a null diff against REFERENCE. Alternative to ps-replay+make-buildable when chronological order with a single build boundary is the wrong shape.
---

# Percona Server Grouped Port

## Purpose

Port a Percona Server commit range from `$INPUT_BASE..$INPUT_TIP` onto a newer base `$OUTPUT_BASE`, producing `$OUTPUT_NAME` that:

1. Is rooted at `$OUTPUT_BASE`.
2. Builds at **every** commit.
3. Has a null tree diff to `$REFERENCE` at the tip.

The strategy is **easier-first by group**, not chronological. Easy commits land first and establish a buildable foundation; harder source-code conflicts land last when the surrounding patches are already in place.

**Hard ordering rule:** the workflow is `§1 Prepare → §2 Scan → §2.5 Dep graph → §3 Assign Groups (tentative+lock, batched but completed for the entire range) → §3.5 Workflow Gate → §4 Execute Groups 1→5 → §5 Converge`. You may not begin §4 cherry-picks while §3 is still partial. Processing commits in `git rev-list` order with on-the-fly grouping is the failure mode this skill is built to prevent — see §3.6 for the red-flag list.

This skill is a sibling of `ps-replay+make-buildable`. Choose this one when:

- A `$REFERENCE` branch already exists with the desired final tree.
- You want a buildable-at-every-commit history.
- The source range has no `=== MARKER:` boundary, or the boundary's position is wrong for your run.
- Chronological order would land hard source-code conflicts before the easy fixes that make them tractable.

## Inputs

- `$INPUT_RANGE` — any `git rev-list` spec. Common shapes:
  - Plain range: `mysql-5.6.26..ps-5.6.26`
  - First-parent only (drop merged-in side-branches): `--first-parent mysql-5.6.26..ps-5.6.26`
  - With exclusion (drop commits reachable from another ref, e.g. an even-newer upstream): `mysql-5.6.26..ps-5.6.26 ^mysql-5.7.44`
  Derive `$INPUT_BASE` (the `..` left side) and `$INPUT_TIP` (the right side) for reporting; pass the full spec to `git rev-list --reverse` to generate the candidate list.
- `$OUTPUT_RANGE` — formatted as `$OUTPUT_BASE..$OUTPUT_NAME` (e.g. `mysql-5.7.9..ps-5.7.9`). `$OUTPUT_NAME` is the branch this skill creates.
- `$REFERENCE` — branch or commit. Final `$OUTPUT_NAME` must null-diff to it. Used both as the convergence target and as the source of truth for conflict resolution.
- `$REPORT_FILE` — markdown report path (default `/tmp/ps-port-grouped-$OUTPUT_NAME.md`).
- `$BUILD_DIR` — out-of-tree build directory under `/tmp` (default `/tmp/build-$OUTPUT_NAME`).

## Build Configuration

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

Use `$BUILD_DIR` incrementally. Per-commit log: `$BUILD_DIR/../logs/build-<grp>-<idx>-<sha12>.log`.

## Workflow

### 1. Prepare

```sh
git checkout -B "$OUTPUT_NAME" "$OUTPUT_BASE"
git rerere clear     # drop any stale resolutions from prior runs
```

Build at `$OUTPUT_BASE` **before any cherry-pick**. If `$OUTPUT_BASE` itself doesn't build with the configured toolchain, **stop and ask** — the run cannot start.

Record `$OUTPUT_BASE`'s build PASS in `$REPORT_FILE`.

**rerere hygiene during the run:** if `rerere` is enabled, treat every reuse as untrusted. Before staging a rerere-resolved file, verify each resolved hunk against `$REFERENCE` per Rule C/D below. A stale rerere resolution from a prior run is one of the easiest ways to silently drop content from the output.

### 2. Scan and Categorize

Generate the candidate commit list:

```sh
git rev-list --reverse "$INPUT_RANGE"
```

For each commit, derive two attributes:

**Category** (lower-case, single token preferred):

- `feature` — new functionality, plugin, variable, syntax
- `bugfix` — Percona-side bug fix
- `upstream-bugfix` — re-applies an upstream MySQL bug fix from a later MySQL version
- `build` — build system, packaging, CMake, RPM/DEB spec, scripts
- `docs` — documentation, man pages, comments
- `test` — `mysql-test/` only, no source paths
- `reconciliation` — porter-side resync/snap/merge prep
- `other` — anything that doesn't fit

Categorize by inspecting the commit's **subject + changed paths**. Do not branch behavior on category for cherry-pick semantics — category is metadata for grouping and reporting.

**BUILD_CHANGING flag** — true if `git diff-tree --no-commit-id --name-only -r <sha>` includes any path matching:

```
(?i)\.(h|c|cc|cxx|cpp|hh|hpp|hxx|cmake)$
```

(case-insensitive). Plain `.txt`, `.result`, `.test`, `.md`, `.spec` etc. do **not** trigger BUILD_CHANGING. A single matching path forces the flag true.

Record per commit in `$REPORT_FILE`: original SHA, subject, category, BUILD_CHANGING, changed-paths summary.

### 2.5 Build the Hunk-Level Dependency Graph

Before group assignment, build a **hunk-level dependency graph** of the input range. The graph is the single most important artifact for identifying pair candidates that the build chronology will trip over later. Skipping this step and discovering structure commit-by-commit through build failures is the #1 cause of long, frustrating runs.

**What the graph contains.** For each commit, parse `git show -U0 --format=` and extract every hunk as a tuple `(file, new_start, new_end, old_start, old_end)`. Then for every pair `(A, B)` with `A` earlier than `B`:

- **Hunk overlap edge** `A→B` if `B` modifies a line range on a file that `A` previously added or modified, with overlap measured on raw line numbers. Record the total overlap-line count as edge weight.
- **Subject-pair edge** `A↔B` if `git log --format=%s A` equals `git log --format=%s B`. High-confidence signal: the same patch imported (or re-imported) twice.
- **Author+timestamp edge** `A↔B` if `git log --format='%an %aI' A` equals the same on `B`. Catches split commits where the engineer or import tool wrote the same metadata to two commits intentionally (split for size, split for tooling).
- **Tag-pair edge** `A↔B` if both subjects contain the same `[#NNN]`, `bug#NNN`, `lp:NNN`, or `BUG#NNN` token. High-confidence: tracked work item.

A minimal Python implementation that scales to 500+ commits in under 10 minutes is sufficient. The graph drops to two TSVs:

```
hunks.tsv      idx, sha, file, new_start, new_end, old_start, old_end
overlaps.tsv   idx_A, idx_B, file, A_new_range, B_old_range, overlap_lines
```

Subject/author/tag-pair edges can live in a third TSV or be re-computed cheaply from the per-commit `git log` metadata.

**Caveat — line drift.** Raw line-number overlap is exact only for adjacent commits. Once intervening commits modify the same file, line numbers shift; `B`'s `old_start..old_end` is in `B`'s pre-image coordinate system, not `A`'s post-image coordinate system. So hunk-overlap is a **noisy** signal mid-range. Treat it as suggestive, not definitive. The subject/author/tag-pair edges have no drift problem and should dominate when they agree.

**How to use the graph.** Three concrete consumers:

1. **Pair detection for Rule-3 squash candidates** — any (A, B) with a subject-edge AND author+timestamp-edge is a near-certain split-pair. Pre-list these *before* execution starts so the run loop can plan squashes instead of stumbling into them as build failures.
2. **Fix-candidate ranking on build failure** — when commit N fails to build at execution time, query: forward neighbors `M > N` ranked by `(subject-edge, author-edge, tag-edge, hunk-overlap-weight)`. The top candidate is almost always the right squash partner. Don't guess; query.

Record the pair-detection output prominently in `$REPORT_FILE` (a dedicated "Pre-detected pairs" section). Each entry: `(idx_A, idx_B, subject, signals)` where `signals` is the set of edge types that fired. This makes the post-run report self-explanatory.

### 3. Assign Groups

Each commit lands in exactly one group. Groups are processed in numeric order; within a group, prefer commits the user cares about (features first) unless the user specified otherwise. Chronological order does **not** control ordering.

| Group | Definition |
|-------|------------|
| 1 | Applies cleanly OR with only trivial conflicts (whitespace, copyright, version strings, single-line context shifts). |
| 2 | Small conflicts AND small/easily-portable build dependencies. May be BUILD_CHANGING. |
| 3 | Larger conflicts BUT **not** BUILD_CHANGING (tests, docs, packaging, result files). Should never break the build. |
| 4 | BUILD_CHANGING with source-code conflicts. Hardest group. |
| 5 | Anything not applicable above — deferred / problem cases. |

**Assignment is a two-pass process.** You cannot fully grade conflict size by reading the commit; you have to try. So:

1. **Tentative pass** — assign every commit a tentative group from its category + BUILD_CHANGING flag + a quick `git cherry-pick --no-commit` trial **on a throwaway worktree** (or in-place with `--abort` on every result). The trial is to gauge conflict shape, not to land anything.
2. **Lock pass** — record the locked group for each commit before starting Group 1 execution. Re-grading mid-run is allowed only to demote (e.g. Group 1 → Group 4) when reality refutes the tentative grade; never promote (Group 4 → Group 1) just because resolution turned out cleaner than expected.

**Batch the tentative pass — required, not optional.** A full upfront trial of every commit is expensive (500+ throwaway picks is a real cost). Trial in **~50-commit chunks**, grade each chunk, then trial the next chunk. The tentative pass must cover the **entire** `$INPUT_RANGE` before Group 1 execution starts. The only permitted shortcut: skip the trial-pick for low-risk categories (docs-only, test-only, packaging-only) and grade those by category + BUILD_CHANGING alone after the first ~3 chunks have established the conflict pattern. Source-bucket, build, reconciliation, and any BUILD_CHANGING commit always get the trial.

**Do not interleave trial chunks with Group 1 execution.** "Trial chunk 1 → land Group 1 from chunk 1 → trial chunk 2" is forbidden. It produces post-hoc grouping (you grade commits in the order they appear, then land them in roughly that order) and silently degenerates into chronological processing. Complete the tentative pass for the entire range, write the locked dataset, *then* begin §4.

The tentative pass produces a working dataset; throwaway operations must not pollute `$OUTPUT_NAME`.

### 3.5 Workflow Gate — Preconditions for §4

Before executing the first real cherry-pick (§4), confirm **all** of the following are true. If any answer is "no", you are not ready for §4 — return to the corresponding earlier step.

- [ ] `$OUTPUT_BASE` built clean (§1) and the PASS is recorded in `$REPORT_FILE`.
- [ ] Every commit in `$INPUT_RANGE` has a row in the §3 scan table with Category, BUILD_CHANGING, and a **locked** Group (1–5).
- [ ] The hunk-level dep graph (§2.5) has been built and the "Pre-detected pairs" section of `$REPORT_FILE` is populated (even if the list is empty — record "no pairs detected").
- [ ] The locked dataset is written to `$REPORT_FILE` *before* the first `git cherry-pick` on `$OUTPUT_NAME`.
- [ ] The next commit you intend to apply is the lowest-numbered Group still containing unlanded commits (i.e. Group 1 commits come before any Group 2 commit, regardless of chronology).

If the dataset is locked but you find yourself reaching for the next commit in input-list order rather than the next commit in Group order, **stop**. That is the rationalization the skill exists to prevent. Re-read §3 and the Red Flags below.

### 3.6 Red Flags — STOP and re-plan

You are about to (or already) violating the easier-first invariant if any of these are true:

- You started cherry-picking onto `$OUTPUT_NAME` before every input-range commit had a locked Group.
- You are processing commits in the order `git rev-list --reverse $INPUT_RANGE` produced them.
- Your "Group 1" execution log includes commits you later re-graded as Group 4 *after* they failed to apply or build — i.e. the group was assigned post-hoc, after attempting the pick.
- You are on commit N and the next commit you plan to attempt is N+1, without checking whether commits N+2…end contain easier (lower-group) work that should land first.
- You're stuck on a hard commit (Group 4/5 shape) and your plan is "push through this one" rather than "skip past it, land the easier groups, return to it last."
- You skipped §2.5 (the dep graph) because "the range is short" or "I'll discover pairs as I go."

If any of these fire: revert `$OUTPUT_NAME` to the last group-boundary buildable SHA, redo the tentative + lock passes for all unlanded commits, and resume from Group 1 of the re-planned dataset. The discarded work is the cost of skipping §3; the alternative (continuing chronologically and re-grading on the fly) compounds the cost commit by commit.

### 4. Execute Groups 1 → 5

**Precondition:** the §3.5 Workflow Gate has been satisfied. If you cannot tick every box in §3.5, do not run a single cherry-pick from this section.

**Ordering invariant:** the iteration is `for g in 1..5: for commit in group[g]:`. It is **not** `for commit in input_list: cherry_pick(commit)`. If you find yourself reaching for the next commit by input-list index instead of by `(group, intra-group order)`, you have fallen back to chronological processing — stop and re-read §3.6.

For each group, in order:

```
for each commit in group:
    if commit has >1 parent (merge commit): git cherry-pick -m 1 <sha>
    else:                                   git cherry-pick <sha>
    resolve conflicts (rules below)
    if cherry-pick is empty after resolution: git cherry-pick --skip; continue
    git cherry-pick --continue (or commit naturally on clean apply)
    BUILD the project
    if build fails: apply build-conflict rules (below)
    record outcome in $REPORT_FILE
```

**Merge commits in the input range:** `git cherry-pick` requires `-m <parent-number>` for merges. With `--first-parent` in `$INPUT_RANGE` this rarely matters (merges normally get traversed via their first-parent edge, not picked as merges themselves). With a plain range, merges *will* appear in the list. Default to `-m 1` (apply the diff against parent 1, the mainline). If parent 1 isn't the right mainline for a particular merge, that's a stop-and-ask condition.

After every group boundary, snapshot the SHA and confirm `$OUTPUT_NAME` is buildable at the boundary.

### 5. Final Convergence

After Group 5:

```sh
git diff "$OUTPUT_NAME" "$REFERENCE"
```

If empty, run a final build at the tip, record both, done.

If non-empty, the remaining diff is residual. Add one or more **explicit hunk-level reconciliation commits** to converge to null diff. Whole-tree snap from `$REFERENCE` is forbidden unless the engineer explicitly authorizes it in the current conversation, naming the file paths or accepting the whole-tree scope. Each reconciliation commit must build.

When null-diff is reached, run the final build at that SHA and record the PASS.

## Cherry-Pick Conflict Rules

These are **mandatory**.

### Rule A — Hunks only, no whole-file snaps

Replace only the conflict regions. Edit the conflicted file by hand to transcribe the chosen content into the conflict region. Forbidden:

- `git checkout $REFERENCE -- <path>` (whole-file replacement)
- `git checkout --ours <path>` / `git checkout --theirs <path>` on a conflicted file
- `git cherry-pick -X ours` / `-X theirs` / `--strategy-option=ours|theirs` (bulk merge-strategy resolution)
- `git restore --source=$REFERENCE <path>`
- Any helper that copies a whole file's contents from `$REFERENCE` into the worktree

`git show $REFERENCE:<path>` for **inspection** is fine — it's how you decide what to write into the conflict region. Just don't redirect it into the worktree.

### Rule B — Check REFERENCE for category removal

Before resolving, look at `$REFERENCE` and ask: **did this commit's category survive?**

```sh
# Check whether the files this commit modifies still exist in REFERENCE
for p in $(git diff-tree --no-commit-id --name-only -r <sha>); do
  git cat-file -e "$REFERENCE:$p" 2>/dev/null && echo "kept: $p" || echo "removed: $p"
done
```

- If every changed file is **absent in REFERENCE** → the feature was removed (likely replaced by an upstream solution). Skip the commit. Document the skip with the original SHA, subject, and the file list.
- If some files are kept and some are removed → resolve hunks normally for kept files; drop hunks targeting removed files. New files the commit adds that are absent in REFERENCE → delete them (`git rm`).
- If everything is kept → resolve hunks normally.

### Rule C — Find where REFERENCE resolved the same upstream change

When conflict-region content is in REFERENCE but the conflict markers' lines disagree, the resolution often **moved** to a different file or different position. Don't blindly take a side.

Workflow when stuck on a non-trivial hunk:

1. Identify the **upstream change** that's causing the conflict — usually a 5.7 refactor (e.g. `IORequest` typing, `page_id_t` introduction, connection-handler split, MVCC reshuffle).
2. Search REFERENCE for the same symbol(s) or the same intent:

   ```sh
   git grep -n '<symbol or fragment>' "$REFERENCE" -- '<related dir>/'
   ```

3. Read REFERENCE's surrounding code to learn the new shape (different function signature, different field access pattern, different file).
4. Transcribe REFERENCE's form into the conflict region. If REFERENCE moved the resolution to a different file, apply the change at the new location and drop the corresponding hunk at the old location.

The conflict region is just where Git noticed disagreement. The right fix is wherever REFERENCE actually expresses the change.

### Rule D — Per-region side selection (the HEAD-empty trap)

Once you're at the right conflict region (Rule C), pick which side to keep using this algorithm. **Do not** default to HEAD just because HEAD is empty.

For each unresolved conflict region:

1. Read each candidate side's **distinct, non-trivial content** — strip whitespace, copyright, and noise; what does each side actually contribute?
2. Check what `$REFERENCE` has at the same path around the same logical position. Use `git show $REFERENCE:<path>` and a token-overlap or substring check against each candidate's distinct content.
3. Decide:
   - REFERENCE contains content from exactly one side → **pick that side**.
   - REFERENCE contains a **third form** distinct from both sides → **transcribe REFERENCE's exact lines** into the conflict region by hand (hunk-level edit; Rule A still applies — no whole-file replacement).
   - REFERENCE contains content from both sides at different positions → split: keep each side at the position REFERENCE keeps it.
   - REFERENCE has **nothing** at that region — neither side's content survives → only then take the HEAD-empty side. Document the drop in the report (path + region + brief reason).

**Why this rule exists:** the naive "take HEAD when HEAD is empty" heuristic is wrong most of the time when `$REFERENCE` is the desired final tree. By definition, every patch in the input range has *some* representation in REFERENCE — that's what REFERENCE is. So "HEAD-empty + REFERENCE has content" almost always means the patch's contribution is real and survived in REFERENCE, just at a different place or in a different form. Silently taking HEAD-empty drops live content from the output and produces an invisible residual diff at the end.

**Maximum-danger configuration: `$REFERENCE` = `$INPUT_TIP`.** When REFERENCE is the input branch's own tip (e.g. you're porting `ps-5.6` onto `mysql-5.7.9` and using `ps-5.7.9` as REFERENCE), *every* input commit's surviving contribution is in REFERENCE by construction — that's how REFERENCE was produced. In this configuration the HEAD-empty trap is at maximum risk: virtually every "HEAD-empty + incoming has content" region must **not** pick HEAD. When grading conflict severity during the trial pass, assume `$REFERENCE` = `$INPUT_TIP` runs will need hunk-level decisions on essentially every non-clean cherry-pick; budget time accordingly.

**Automated-resolver guardrail.** A hunk resolver that auto-tiebreaks to HEAD when both sides score zero overlap with `$REFERENCE` is **worse than stopping**. It produces silent, invisible drops at every region neither side resembles. Any helper used during this skill must, when both candidate sides have zero overlap with REFERENCE:

- Read REFERENCE's content at the same path and look for a **third form**.
- If a third form is found, surface the region as `unresolved, REFERENCE has third form at lines X–Y` with the excerpt and stop for manual transcription.
- If no third form exists, surface the region as `unresolved, REFERENCE empty at this region — engineer must confirm HEAD-empty drop` and stop.

Never tiebreak to HEAD silently. Stopping is recoverable; silent drops are not (they only surface at final-convergence time, mixed with all other residual, with no record of which commit caused which drop).

**Red flags that signal you're about to fall into the HEAD-empty trap:**

- The conflict region is between an empty HEAD side and an incoming side that adds new lines.
- You're tempted to "just take HEAD because the upstream removed this" without grepping REFERENCE for the affected symbol.
- A hunk-level resolver script picked a side automatically and you didn't read the REFERENCE excerpt at that path.
- The run is in maximum-danger configuration (`$REFERENCE` = `$INPUT_TIP`) and you're treating any HEAD-empty conflict as a routine auto-pick.

In all four cases: stop, run `git show $REFERENCE:<path>` and the symbol search, and apply the decision rule above.

## Build Conflict Rules

After every commit lands, build. If the build fails:

### Rule 1 — Minimal fix, scoped to current commit's intent

Add the smallest set of edits that restore buildability. Sources of the fix:

- A **later commit in the input range** that introduces the missing dependency. Inspect that commit's diff for just the bits you need.
- `$REFERENCE` directly, if the later commit's shape doesn't fit cleanly.

Squash the fix into the failing commit (`git commit --amend` or `git commit --fixup` + interactive rebase, depending on how many commits back the failure was). Do not leave a known-bad commit on `$OUTPUT_NAME`.

### Rule 2 — Defer cascading code

If the minimal fix in Rule 1 pulls in code that itself fails to build (cascading missing symbols), don't expand the fix indefinitely. Instead **defer** the cascading portion:

- Comment it out or `#if 0` it with a `// TODO laurynas-style` marker referencing the originating commit's SHA and the deferred symbol.
- Record the deferral in the report's "Deferred code" section.
- When the dependency-introducing commit later lands, restore the deferred code in the same commit (or in an immediate follow-up fix commit) and confirm it builds.

Deferrals must converge — every deferral entry needs a recorded "restored at SHA <X>" by the time the run completes.

### Rule 3 — Squash related commits when build-coupled

If commit A introduces a header change and commit B immediately uses it, A may not build in isolation. When A's build failure can only be fixed by pulling in most of B, squash B into A. Record the squash in the report.

A squash is justified only when **most** of commit B is needed to make A build. If only a small slice of B is needed, prefer Rule 1 (minimal fix folded into A, B continues to apply later with the slice already in place — adjust B's cherry-pick accordingly).

## Stop Conditions

Stop and ask the engineer when:

- `$OUTPUT_BASE` does not build with the configured toolchain.
- A commit's conflict resolution requires whole-file replacement from `$REFERENCE`.
- The minimal build fix would require pulling more than ~30 lines from a later commit (cascading fix territory — Rule 2 may not isolate cleanly).
- A deferral can't be restored at the input commit you predicted, and no obvious successor commit will restore it.
- The Group 5 residual after all input-range commits land still contains commits the engineer expected to apply.
- Final convergence after Group 5 still has a residual to `$REFERENCE` that no targeted reconciliation commit can close without whole-tree snap.

When stopping, return `$OUTPUT_NAME` to the last known-buildable SHA, document the blocker, and propose 2–3 concrete options for the engineer.

## Report Requirements

Write `$REPORT_FILE` (markdown). Sections:

### Header

- `$INPUT_RANGE`, `$OUTPUT_RANGE`, `$REFERENCE`
- Build command used, `$BUILD_DIR`
- Run start timestamp

### Scan output

Table of every commit in `$INPUT_RANGE`:

| Idx | SHA | Subject | Category | BUILD_CHANGING | Group | Paths summary |
|-----|-----|---------|----------|----------------|-------|---------------|

### Group execution

For each group 1..5:

- Total commits, applied / skipped-empty / category-removed / deferred-to-later-group
- For each applied commit: original SHA → new SHA, conflict files (if any) and the REFERENCE region cited, build log path, PASS/FAIL
- For each skipped commit: original SHA, subject, reason (empty after resolution / category removed from REFERENCE / explicit engineer skip)
- Group-boundary buildable SHA

### Deferred code

Every Rule-2 deferral: originating SHA, symbol/region deferred, predicted restore SHA, actual restore SHA, restore-build log.

### Squashes

Every Rule-3 squash: SHAs squashed together, resulting SHA, justification.

### Dep graph & pair detection

Path to `hunks.tsv` and `overlaps.tsv`. List of pre-detected pairs with their edge-type signals (subject / author+timestamp / tag / hunk-overlap).

### Final convergence

- `git diff $OUTPUT_NAME $REFERENCE` size before reconciliation
- Each reconciliation commit's SHA and the paths/hunks it touched
- Final diff confirmation (null) and final build log

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Treating chronological order as the default | Groups override chronology. Scan and assign before cherry-picking the first commit. |
| Processing commits in `git rev-list --reverse` order and grouping post-hoc | This is chronological with cosmetic grouping. The tentative + lock passes (§3) must finish for the **entire** range before any real cherry-pick. Symptom: you get stuck on a Group 4/5 commit at a mid-range index instead of skipping past it to easier work. |
| Interleaving tentative-pass chunks with Group 1 execution | The "trial 50 → land Group 1 from those 50 → trial next 50" pattern degenerates into chronological order. Complete the tentative pass for the whole range first. |
| Pushing through a hard commit because you've already started it | If a commit's actual conflict shape reveals it's Group 4/5 when tentative-graded Group 1/2, demote it, `cherry-pick --abort`, and continue with the next Group-1 commit. Sunk cost is not a reason to land a hard commit early. |
| Skipping the `$OUTPUT_BASE` build | If the base doesn't build, no later state on `$OUTPUT_NAME` builds either. Always verify first. |
| Promoting a commit between groups based on hope | Demotion (easier → harder) is fine. Promotion (harder → easier) requires re-running the tentative pass. |
| Cherry-picking before group assignment is locked | The trial pass uses throwaway worktree state. The real pass uses the locked dataset only. |
| Letting a build failure stay on `$OUTPUT_NAME` | Every commit must build. Amend or squash the fix into the failing commit before moving on. |
| Whole-file `git checkout REFERENCE -- path` to "fix the diff" at the end | Forbidden. Use targeted hunk-level reconciliation commits, or ask the engineer for explicit authorization. |
| Squashing two commits because they share a category | Squashes are justified by build coupling, not category. Don't merge related-feature commits unless one literally cannot build without the other. |
| Deferring code with no restore plan | Every deferral must name the commit that will restore it. Track restoration in the report. |
| Skipping the dep graph and discovering pairs through build failures | The graph (§2.5) costs <10 min and surfaces every split-pair before execution. Discovering them via build failures wastes hours per pair. |

## Quick Reference

| Step | Command |
|------|---------|
| List source range | `git rev-list --reverse $INPUT_RANGE` |
| Source-SHA paths | `git diff-tree --no-commit-id --name-only -r <sha>` |
| BUILD_CHANGING test | grep paths against `(?i)\.(h\|c\|cc\|cxx\|cpp\|hh\|hpp\|hxx\|cmake)$` |
| Category-removed test | `git cat-file -e $REFERENCE:<path>` per path |
| Inspect REFERENCE region | `git show $REFERENCE:<path>` (inspection only) |
| Search REFERENCE | `git grep -n '<symbol>' $REFERENCE -- '<dir>/'` |
| Throwaway trial pick | `git cherry-pick --no-commit <sha>; git diff --name-only --diff-filter=U; git cherry-pick --abort` |
| Final null-diff check | `git diff $OUTPUT_NAME $REFERENCE` |

## When NOT to Use This Skill

- The commit range has a meaningful `=== MARKER: GROUP 7 — Upstream bug fixes ===` boundary and chronological order is the desired shape — use `ps-replay+make-buildable` instead.
- You don't have a `$REFERENCE` branch with the desired final tree. This skill is convergence-driven; without REFERENCE, conflict resolution loses its anchor.
- You want a single squashed result rather than per-commit history — use `ps-squash-dag` after porting, or do the port chronologically and squash at the end.

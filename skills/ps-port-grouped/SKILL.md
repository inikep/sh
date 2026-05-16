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

## Workflow Phase Discipline

The skill enforces phases. Each phase has a precondition (what must exist on disk before entering) and an output (what's produced). You may not begin a later phase while an earlier phase's output is absent.

| Phase | Precondition | Output |
|-------|--------------|--------|
| §1 Prepare | nothing | `$OUTPUT_NAME` at `$OUTPUT_BASE`, base build PASS recorded in `$REPORT_FILE` |
| §2 Scan | §1 output | per-commit table in `$REPORT_FILE` |
| §2.5 Dep graph | §2 output | `hunks.tsv`, `overlaps.tsv`, pre-detected pairs list in `$REPORT_FILE` |
| §3 Assign Groups | §2.5 output | **`$LOCKED_PLAN_FILE` written**, one row per commit, sorted by (group, intra-group order) |
| §3.5 Gate | `$LOCKED_PLAN_FILE` complete | all checkboxes ticked in `$REPORT_FILE` |
| §4 Execute | §3.5 passed | one cherry-pick per row of `$LOCKED_PLAN_FILE`, **iterated in file order** |
| §5 Converge | §4 output | null diff to `$REFERENCE`, final build PASS |

**The single failure mode this skill exists to prevent.** An LLM reads the skill, internalizes "easier-first by group," and then drifts into "process commits in `git rev-list --reverse` order, grade each as I pick, land what works, struggle on what doesn't." This *feels* like compliance — there are groups in the report, there is a trial pass — but it is chronological execution with cosmetic grouping. Recognize the fingerprints:

- A single commit consuming disproportionate time. You are stuck because the next commit *by chronological index* was a Group 4/5 commit, not because no easier work remained in the range.
- Cherry-picks landed on `$OUTPUT_NAME` before `$LOCKED_PLAN_FILE` existed on disk. (Check: `stat $LOCKED_PLAN_FILE` vs `git log --format=%aI $OUTPUT_BASE..$OUTPUT_NAME | tail -1`. If the file is missing or younger than the oldest pick, you drifted.)
- The landed-SHA order on `$OUTPUT_NAME` corresponds to `git rev-list --reverse $INPUT_RANGE` order rather than (group, intra-group) order.
- You did per-commit "trial pick → grade → land" in a single loop instead of completing the trial pass for the entire range up front.

If any of those describe the current run, do not push through the stuck commit. Jump to §3.7 Recovery.

**Why the on-disk plan file is non-negotiable.** Text guardrails ("batch the trial pass," "do not interleave") are easy for an LLM to agree with and then locally optimize away. A file is not. §4's loop is literally `for row in $LOCKED_PLAN_FILE`. If the file doesn't exist, §4 cannot start. If the file is sorted by group, the execution order is by group. Phase discipline is enforced by what exists on disk, not by what you remember the skill said.

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
- `$LOCKED_PLAN_FILE` — TSV path (default `/tmp/ps-port-grouped-$OUTPUT_NAME-plan.tsv`). Written by §3, consumed by §4. Its existence and completeness is the §3.5 gate's primary check. §4 iterates this file in row order; if it does not exist, §4 cannot start.
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
| 1 | **BC=0 only.** Any outcome (clean apply, empty, or conflict) — by construction these touch no `.h/.c/.cc/.cxx/.cpp/.hh/.hpp/.hxx/.cmake` paths and therefore cannot break the build. Land first; build verification not required mid-group, only at the group boundary. |
| 2 | BC=1 (BUILD_CHANGING) commits whose trial outcome was **clean or empty**. They may still fail at build time (uses-before-defines from later commits), but the cherry-pick itself is conflict-free. |
| 3 | BC=1 with **small conflict** in the trial pass (n_conflicts ≤ 3). |
| 4 | BC=1 with **larger conflict** (n_conflicts > 3). Hardest group. |
| 5 | Anything not applicable above — deferred / problem cases (other-fail trial outcomes, etc.). |

**Why Group 1 is BC=0-only.** A previous version of this rubric admitted BC=1 commits into Group 1 whenever the cherry-pick trial happened to be clean. In practice, BC=1 "clean trial" commits routinely fail at build time because they use symbols a later commit defines (e.g. `expand_fast_index_creation`, `OPT_INNODB_OPTIMIZE_KEYS`, `page_hash_latch`). That forced a Rule-1 or Rule-2 build fix on every BC=1 commit in what was supposed to be the easiest group, inflating Group 1 wall-clock time disproportionately and undermining the "easier-first" framing. Restricting Group 1 to BC=0 means it lands fast (no per-commit builds needed; one build at the group boundary is enough), establishing a known-buildable foundation **before** any BC=1 commit is picked.

**Assignment is a two-pass process.** You cannot fully grade conflict size by reading the commit; you have to try. So:

1. **Tentative pass** — assign every commit a tentative group from its category + BUILD_CHANGING flag + a quick `git cherry-pick --no-commit` trial **on a throwaway worktree** (or in-place with `--abort` on every result). The trial is to gauge conflict shape, not to land anything.
2. **Lock pass** — record the locked group for each commit before starting Group 1 execution. Re-grading mid-run is allowed only to demote (e.g. Group 1 → Group 4) when reality refutes the tentative grade; never promote (Group 4 → Group 1) just because resolution turned out cleaner than expected.

**Batch the tentative pass — required, not optional.** A full upfront trial of every commit is expensive (500+ throwaway picks is a real cost). Trial in **~50-commit chunks**, grade each chunk, then trial the next chunk. The tentative pass must cover the **entire** `$INPUT_RANGE` before Group 1 execution starts. The only permitted shortcut: skip the trial-pick for low-risk categories (docs-only, test-only, packaging-only) and grade those by category + BUILD_CHANGING alone after the first ~3 chunks have established the conflict pattern. Source-bucket, build, reconciliation, and any BUILD_CHANGING commit always get the trial.

**Do not interleave trial chunks with Group 1 execution.** "Trial chunk 1 → land Group 1 from chunk 1 → trial chunk 2" is forbidden. It produces post-hoc grouping (you grade commits in the order they appear, then land them in roughly that order) and silently degenerates into chronological processing. Complete the tentative pass for the entire range, write `$LOCKED_PLAN_FILE`, *then* begin §4.

The tentative pass produces a working dataset; throwaway operations must not pollute `$OUTPUT_NAME`.

#### Writing `$LOCKED_PLAN_FILE`

At the end of §3, **write the locked dataset to `$LOCKED_PLAN_FILE`** in this exact TSV format (tab-separated, header row included):

```
plan_pos	group	intra_group_order	orig_sha	rev_list_pos	category	build_changing	subject
1	1	1	abc123def456	7	bugfix	false	Fix typo in error message
2	1	2	...
...
N	5	K	...
```

Field semantics:

- `plan_pos` — 1..N. This is the **execution order**. §4 iterates by this column. It is **not** the chronological index.
- `group` — 1..5, the locked group from §3.
- `intra_group_order` — 1..M within the group. Within a group, prefer commits the user cares about (features first) unless the user specified otherwise.
- `orig_sha` — the source commit's full SHA.
- `rev_list_pos` — the commit's index in `git rev-list --reverse $INPUT_RANGE`. **Reference only.** This is what `idx` meant in past conversations about this skill; surfaced here so you can detect chronological drift (if `rev_list_pos` is monotonically increasing along `plan_pos`, you have not actually grouped — you've sorted chronologically and labeled it).
- `category`, `build_changing`, `subject` — as scanned in §2.

Sort the file by `(group ASC, intra_group_order ASC)`. The file's row order **is** the execution order.

Sanity checks before declaring §3 complete:

```sh
# Row count matches input-range commit count.
test "$(tail -n +2 "$LOCKED_PLAN_FILE" | wc -l)" -eq "$(git rev-list --count $INPUT_RANGE)" || echo "PLAN INCOMPLETE"

# plan_pos column is 1..N contiguous.
awk -F'\t' 'NR>1 {print $1}' "$LOCKED_PLAN_FILE" | awk 'NR!=$1 {print "GAP at "NR; exit 1}'

# rev_list_pos is NOT monotonically increasing along plan_pos (if it is, you didn't actually re-order by group — flag for manual review unless the range was genuinely already easier-first).
awk -F'\t' 'NR>1 {if (prev!="" && $5<prev) mono=0; else if (prev!="" && $5>prev) inc++; prev=$5; tot++} END {if (inc==tot-1) print "WARNING: rev_list_pos monotonically increasing — verify groups are real, not cosmetic"}' "$LOCKED_PLAN_FILE"
```

If the warning fires, do not proceed to §4 — re-check that the trial pass actually graded conflict shape, not just category.

### 3.5 Workflow Gate — Preconditions for §4

Before executing the first real cherry-pick (§4), confirm **all** of the following are true. Each is independently verifiable on disk — do not "remember" them, run the check. If any answer is "no", you are not ready for §4 — return to the corresponding earlier step.

- [ ] `$OUTPUT_BASE` built clean (§1) and the PASS is recorded in `$REPORT_FILE`.
- [ ] **`$LOCKED_PLAN_FILE` exists** (`test -f "$LOCKED_PLAN_FILE"`).
- [ ] **`$LOCKED_PLAN_FILE` row count equals `git rev-list --count $INPUT_RANGE`** (see §3 sanity checks). A partial plan is not a plan.
- [ ] **`$LOCKED_PLAN_FILE` rows are sorted by (group, intra_group_order).** Verify: `awk -F'\t' 'NR>1 {key=$2"."sprintf("%06d",$3); if (key<prev) {print "OUT OF ORDER at line "NR; exit 1} prev=key}' "$LOCKED_PLAN_FILE"`.
- [ ] Every commit in `$INPUT_RANGE` has a row in the §3 scan table with Category, BUILD_CHANGING, and a locked Group (1–5).
- [ ] The hunk-level dep graph (§2.5) has been built and the "Pre-detected pairs" section of `$REPORT_FILE` is populated (even if the list is empty — record "no pairs detected").
- [ ] **`$OUTPUT_NAME` is at `$OUTPUT_BASE`.** Verify: `git rev-parse "$OUTPUT_NAME"` equals `git rev-parse "$OUTPUT_BASE"`. No commits have been cherry-picked yet. If commits exist, you either drifted (jump to §3.7) or you're resuming mid-run (different recovery — see §3.7).
- [ ] The next commit you intend to apply is **row 1 of `$LOCKED_PLAN_FILE`**, not "the next commit by chronological index" or "the next commit I happen to remember."

If the dataset is locked but you find yourself reaching for the next commit in input-list order rather than the next row of `$LOCKED_PLAN_FILE`, **stop**. That is the rationalization the skill exists to prevent. Re-read §3 and the Red Flags below.

### 3.6 Red Flags — STOP and re-plan

You are about to (or already) violating the easier-first invariant if any of these are true:

- You started cherry-picking onto `$OUTPUT_NAME` before every input-range commit had a locked Group.
- You are processing commits in the order `git rev-list --reverse $INPUT_RANGE` produced them.
- Your "Group 1" execution log includes commits you later re-graded as Group 4 *after* they failed to apply or build — i.e. the group was assigned post-hoc, after attempting the pick.
- You are on commit N and the next commit you plan to attempt is N+1, without checking whether commits N+2…end contain easier (lower-group) work that should land first.
- You're stuck on a hard commit (Group 4/5 shape) and your plan is "push through this one" rather than "skip past it, land the easier groups, return to it last."
- You skipped §2.5 (the dep graph) because "the range is short" or "I'll discover pairs as I go."

If any of these fire: revert `$OUTPUT_NAME` to the last group-boundary buildable SHA, redo the tentative + lock passes for all unlanded commits, and resume from Group 1 of the re-planned dataset. The discarded work is the cost of skipping §3; the alternative (continuing chronologically and re-grading on the fly) compounds the cost commit by commit.

### 3.7 Recovery — How to pivot when chronological drift is detected

You are here because the Workflow Phase Discipline section, §3.5, or §3.6 fired and you've established that `$OUTPUT_NAME` has commits landed without `$LOCKED_PLAN_FILE` driving them. Do not push through the stuck commit. Pivot:

1. **Inventory what's on `$OUTPUT_NAME` already.** Capture `git log --reverse --format='%H %s' $OUTPUT_BASE..$OUTPUT_NAME > /tmp/landed-so-far.txt`. These SHAs are the commits you already invested resolution work in — you don't want to throw that away unless necessary.

2. **Find the last group-boundary buildable SHA.** Walk `$REPORT_FILE`'s "Group execution" section for the most recent recorded `Group-boundary buildable SHA`. If none exists (you never finished a group cleanly), use `$OUTPUT_BASE`.

3. **Reset.** `git checkout "$OUTPUT_NAME" && git reset --hard <buildable-SHA>`. This is the irreversible step; confirm the SHA before running it.

4. **Complete §2.5 and §3 for the unlanded commits.** Build the dep graph if you skipped it. Run the trial pass for all commits in `$INPUT_RANGE` that are not already reachable from the new `$OUTPUT_NAME` tip. Grade conflict shape — actually run the trial picks on a throwaway worktree, do not grade by category alone.

5. **Write `$LOCKED_PLAN_FILE`.** The plan covers only commits not already landed. Run the §3 sanity checks. If the "rev_list_pos monotonically increasing" warning fires, your trial pass didn't grade conflict shape — re-do it.

6. **Run the §3.5 gate.** Every checkbox.

7. **Resume §4 from row 1 of the new `$LOCKED_PLAN_FILE`.** The cherry-picks you previously did that fall into Group 1 of the new plan can often be re-applied cleanly; the ones in Groups 2–5 may have been the wrong order anyway. Either way, the next pick comes from the plan file.

8. **Record the pivot in `$REPORT_FILE`** under a dedicated "Pivots" section: the SHA you reset to, why (which red flag fired, which `plan_pos` or `rev_list_pos` you were stuck on), how many commits were re-planned. This is for the engineer reviewing the run, not for you — but writing it forces honest acknowledgement of what happened.

**Sunk-cost trap.** "I've already done conflict resolution for commits 1–33, surely I can finish 34 and recover from there." No. The reason 34 is hard is that easier commits in the same range haven't landed yet to provide context. Pushing through 34 in isolation does not produce a better tree than 34 with the easier surrounding work applied first. Reset.

**When `$REFERENCE` = `$INPUT_TIP` (maximum-danger config).** Chronological drift in this configuration risks silent HEAD-empty drops at the same time. After reset, re-examine every Rule-D decision made on the discarded commits when you re-do them. Do not assume past resolutions were correct.

### 4. Execute Groups 1 → 5

**Precondition:** the §3.5 Workflow Gate has been satisfied. If you cannot tick every box in §3.5, do not run a single cherry-pick from this section.

**Ordering invariant — the iteration is over `$LOCKED_PLAN_FILE` rows, not over `git rev-list` output.** The next commit to pick is *always* the lowest-numbered `plan_pos` not yet landed. If you find yourself reaching for a commit by `rev_list_pos` (i.e. chronological index), or by SHA-from-memory, you have fallen back to chronological processing — stop and re-read §3.6/§3.7.

The execution loop is, literally:

```sh
tail -n +2 "$LOCKED_PLAN_FILE" | while IFS=$'\t' read -r plan_pos group intra_order orig_sha rev_list_pos category build_changing subject; do
    echo "=== plan_pos=$plan_pos group=$group orig_sha=$orig_sha (rev_list_pos=$rev_list_pos) ==="

    # 1. Cherry-pick (use -m 1 if merge commit).
    if [ "$(git cat-file -p "$orig_sha" | grep -c '^parent ')" -gt 1 ]; then
        git cherry-pick -m 1 "$orig_sha" || true
    else
        git cherry-pick "$orig_sha" || true
    fi

    # 2. Resolve conflicts per Rules A–D (manual step; the loop pauses here).
    # 3. If empty after resolution: git cherry-pick --skip; continue.
    # 4. Otherwise: git cherry-pick --continue.
    # 5. Build. If fail, apply build-conflict rules.
    # 6. Record outcome in $REPORT_FILE (which plan_pos, new SHA, conflicts, build log).
done
```

This loop is the contract. Every cherry-pick `$OUTPUT_NAME` receives must come from a `$LOCKED_PLAN_FILE` row, processed in `plan_pos` order. There is no other way to pick a commit. If you find yourself running `git cherry-pick <sha>` where `<sha>` did not come from reading the next unlanded row, you are violating §4.

**Demotion mid-run.** If commit at `plan_pos = P` reveals itself to be Group 4/5 when tentative-graded Group 1/2 (the conflict shape was worse than the trial predicted), `git cherry-pick --abort`, edit `$LOCKED_PLAN_FILE` to move the row to its true group (re-numbering `plan_pos` accordingly), record the demotion in `$REPORT_FILE`, and proceed to the new `plan_pos = P`. Demotion is fine. Promotion (Group 4 → Group 1 because resolution turned out clean) is forbidden without re-running the trial pass for affected commits — clean resolution might depend on later commits not yet landed, which a re-trial would reveal.

**Merge commits in the input range:** `git cherry-pick` requires `-m <parent-number>` for merges. With `--first-parent` in `$INPUT_RANGE` this rarely matters (merges normally get traversed via their first-parent edge, not picked as merges themselves). With a plain range, merges *will* appear in the list. Default to `-m 1` (apply the diff against parent 1, the mainline). If parent 1 isn't the right mainline for a particular merge, that's a stop-and-ask condition.

After every group boundary (last row of group G processed and built), snapshot the SHA and confirm `$OUTPUT_NAME` is buildable at the boundary. Record the boundary SHA in `$REPORT_FILE` — this is the recovery point if §3.7 fires later.

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

Reference: `$LOCKED_PLAN_FILE` is the source of truth for what was supposed to happen. This section records what actually happened against it.

For each group 1..5:

- Total commits (from plan), applied / skipped-empty / category-removed / deferred-to-later-group / demoted-out
- For each applied commit: `plan_pos`, original SHA → new SHA, conflict files (if any) and the REFERENCE region cited, build log path, PASS/FAIL
- For each skipped commit: `plan_pos`, original SHA, subject, reason (empty after resolution / category removed from REFERENCE / explicit engineer skip)
- For each demoted commit: `plan_pos` before/after, group before/after, what the trial pass missed
- Group-boundary buildable SHA (record this — it's the recovery point for §3.7 if drift is detected later)

### Pivots (if §3.7 fired)

For each pivot: which §3.6 red flag fired, `plan_pos` where the run was when detected, SHA reset to, count of commits re-planned, brief note on what changed about the locked plan after re-planning. If no pivots occurred, record "no pivots".

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
| Cherry-picking before `$LOCKED_PLAN_FILE` exists on disk | The plan is the execution contract. No `git cherry-pick` on `$OUTPUT_NAME` before §3 writes the file and §3.5 verifies it. If you have already drifted into this state, pivot per §3.7 rather than continuing. |
| Plan file exists but `rev_list_pos` is monotonically increasing along `plan_pos` | You grouped on paper but ordered chronologically. The trial pass didn't actually grade conflict shape. Re-do §3 with real `git cherry-pick --no-commit` trials on a throwaway worktree. |
| Picking the next commit "from memory" or by chronological index instead of by reading `$LOCKED_PLAN_FILE` row | The plan file is the source of truth for what comes next. Read it, pick the lowest unlanded `plan_pos`. |
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
| Plan file row count check | `test "$(tail -n +2 "$LOCKED_PLAN_FILE" \| wc -l)" -eq "$(git rev-list --count $INPUT_RANGE)"` |
| Plan file sort check | `awk -F'\t' 'NR>1 {k=$2"."sprintf("%06d",$3); if (k<p) {print "OOO "NR; exit 1} p=k}' "$LOCKED_PLAN_FILE"` |
| Drift detector | `git log --reverse --format=%H $OUTPUT_BASE..$OUTPUT_NAME` — landed SHAs should match `$LOCKED_PLAN_FILE`'s `orig_sha` column in `plan_pos` order |
| Next commit to pick | `tail -n +2 "$LOCKED_PLAN_FILE" \| awk -v n=<next_plan_pos> -F'\t' '$1==n'` |
| Final null-diff check | `git diff $OUTPUT_NAME $REFERENCE` |


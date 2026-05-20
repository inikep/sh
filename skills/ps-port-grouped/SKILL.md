---

## name: ps-port-grouped
description: Use when porting a Percona Server commit range from one MySQL base to a newer one (e.g. mysql-5.6.x → mysql-5.7.x) and a known-good REFERENCE branch exists, by categorizing commits, scheduling easy-first across reducing passes (each pass strictly shrinks the waiting set), building after every commit, and converging the output to a null diff against REFERENCE. Alternative to ps-replay+make-buildable when chronological order with a single build boundary is the wrong shape.

# Percona Server Grouped Port

## Purpose

Port a Percona Server commit range from `$INPUT_BASE..$INPUT_TIP` onto a newer base `$OUTPUT_BASE`, producing `$OUTPUT_NAME` that:

1. Is rooted at `$OUTPUT_BASE`.
2. Builds at **every** commit. **Hard requirement — not a goal, not a "nice to have".** Tip-only buildable is a failed run. If you cannot achieve per-commit buildability for some segment of the range, **stop and ask** (see Stop Conditions) — do not silently downgrade the deliverable.
3. Has a null tree diff to `$REFERENCE` at the tip.

The strategy is **easier-first across reducing passes**, not chronological. Each pass is an eligibility band chosen from a fresh trial sweep against the current `$OUTPUT_NAME` tip. The next pass lands only the easiest currently eligible band, then rewrites the waiting set. The waiting set strictly shrinks every pass. Easy commits land first and establish a buildable foundation; harder source-code conflicts land later as their prerequisite siblings drop their conflict and build cost on subsequent re-trials.

### Per-commit buildability is non-negotiable

The single most attractive failure mode for this skill is: cherry-pick all N commits chronologically because they apply cleanly under progressive replay, build only at the tip, declare victory because the tip builds and the diff to `$REFERENCE` is null. **This is not a successful run.** The deliverable the skill exists to produce is a history that is buildable at every commit. A null-diff-but-only-tip-builds branch is functionally equivalent to what `ps-replay+make-buildable` produces at its single build boundary, and the wrong tool was chosen.

Telltale signs you are about to (or already did) deliver tip-only buildable as a fallback:

- `$OUTPUT_BASE` does not build, and your plan is "land all commits chronologically and verify only at tip" because the tip commit happens to be a comprehensive end-fix (e.g., `Make part-1 prefix buildable`).
- The first trial sweep showed 0 conflicts across the range, so you concluded "no work needed" and skipped per-commit builds.
- You discovered tip-fix's hunks have cross-commit dependencies (later-introduced symbols, files added by later commits) and concluded "per-commit redistribution is structurally hard, deliver chronological instead."
- The exec log records `clean` for every commit but only one `build PASS` entry exists.

If any of these describe the run, **the deliverable is not acceptable**. Either invest the per-commit BDF work, or stop and surface the structural blocker to the engineer with concrete options (see Stop Conditions). Do not deliver tip-only as a quiet downgrade.

### When `$OUTPUT_BASE` doesn't build AND `$REFERENCE` tip contains a comprehensive end-fix

This is the maximum-difficulty configuration. The pattern: the input range ends with a single commit (e.g., `Make part-1 prefix buildable`) that supplies the buildability fixes the rest of the range needs. Naively the end-fix lands only in the last pass and only the tip builds.

Per-commit buildability in this configuration **requires** redistributing the end-fix's hunks earlier — folding each hunk into the ancestor where its context is established and its strip-targets exist. This is concrete, bounded work, not "structurally impossible":

- Split the end-fix into per-file patches up front (§1 / §2.5).
- For each per-file patch, identify the earliest ancestor commit where the patch applies cleanly AND no later commit re-introduces the patch's strip target. That ancestor is the fold target.
- For "strip-call-site" hunks where the target call is introduced by multiple commits, fold the strip into **each** introducing commit so the call is never added.
- Build at every fold to verify.

In the pass model this means: many of the end-fix's hunks land during Base-BDF (§1.5) and during early passes via fold; the end-fix commit itself lands in a later pass with a reduced (or empty) diff. The waiting-set TSV still shows it remaining until its actual cherry-pick lands.

The work is hours of focused BDF, not days. If the engineer authorized the run knowing the configuration, the work is in scope. Do not retroactively decide "this is structurally impossible" partway through. If the run scale genuinely exceeds the session budget, stop and ask the engineer to split the range or accept a partial-coverage delivery with explicit per-commit-build attestation for the covered subset — not a silent chronological downgrade.

**Companion technique:** `BDF.md` documents Build-Driven Fix — the per-commit re-attempt subroutine for the deferred set (called from §4.5 strategy (a)). Read it before re-attempting deferred commits.

## Workflow Phase Discipline

The skill enforces phases. Each phase has a precondition (what must exist on disk before entering) and an output (what's produced). You may not begin a later phase while an earlier phase's output is absent.


| Phase                                                  | Precondition                                       | Output                                                                                                       |
| ------------------------------------------------------ | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| §1 Prepare                                             | nothing                                            | `$OUTPUT_NAME` at `$OUTPUT_BASE`, base build PASS recorded in `$REPORT_FILE`                                 |
| §1.5 Base-BDF (only if §1 base build FAIL)             | §1 FAIL                                            | `$OUTPUT_NAME` at Base-BDF SHA, Base-BDF build PASS recorded                                                 |
| §2 Scan                                                | §1 output                                          | per-commit table in `$REPORT_FILE`                                                                           |
| §2.5 Dep graph                                         | §2 output                                          | `hunks.tsv`, `overlaps.tsv`, pre-detected pairs list, SCC report in `$REPORT_FILE`                           |
| §3 Plan First Pass                                     | §2.5 output                                        | `**$WAITING_FILE` written**, one row per still-unported commit, sorted by (landing_pass, intra_pass_order) for the first §4 pass |
| §3.5 Gate                                              | `$WAITING_FILE` complete                           | all checkboxes ticked in `$REPORT_FILE`                                                                      |
| §4 Execute Iterative Passes                            | §3.5 passed                                        | loop {trial-sweep waiting set → land the lowest eligible pass band → rewrite `$WAITING_FILE`} until waiting set empty or pass adds 0 |
| §4.5 Deferred-set management                           | §4 pass with 0 landings, or waiting set non-empty  | strategy choice recorded; deferred set handled per (a)/(b)/(c)/(d)                                           |
| §5 Converge                                            | §4.5 output (or §4 finished with empty waiting set) | null diff to `$REFERENCE`, final build PASS                                                                  |


**Pass invariant.** Each entry into the pass loop trial-sweeps every commit still in `$WAITING_FILE` against the current `$OUTPUT_NAME` tip, assigns a `landing_pass` (1–5) based on **right-now** conflict + build difficulty, then executes only the lowest eligible pass band present in the file. At the end of every pass, `$WAITING_FILE` has strictly fewer rows than at the start (or the pass terminates the loop by adding 0 commits → §4.5). `landing_pass` is therefore current-state eligibility, not a one-time locked grade — a commit assigned to landing pass 4 in an earlier round may be assigned to landing pass 2 later once its prerequisites have landed. This is **expected**; every value comes from a fresh trial against the live tip.

**The single failure mode this skill exists to prevent.** An LLM reads the skill, internalizes "easier-first by pass," and then drifts into "process commits in `git rev-list --reverse` order, grade each as I pick, land what works, struggle on what doesn't." This *feels* like compliance — there are pass assignments in the report, there is a trial sweep — but it is chronological execution with cosmetic scheduling. Recognize the fingerprints:

- A single commit consuming disproportionate time. You are stuck because the next commit *by chronological index* belonged to landing pass 4/5, not because no easier work remained in the waiting set.
- Cherry-picks landed on `$OUTPUT_NAME` before `$WAITING_FILE` existed on disk. (Check: `stat $WAITING_FILE` vs `git log --format=%aI $OUTPUT_BASE..$OUTPUT_NAME | tail -1`. If the file is missing or younger than the oldest pick, you drifted.)
- The landed-SHA order on `$OUTPUT_NAME` corresponds to `git rev-list --reverse $INPUT_RANGE` order rather than `(execution pass, intra_pass_order)` order.
- You did per-commit "trial pick → assign pass → land" in a single loop instead of completing one **trial sweep** of the entire waiting set, writing `$WAITING_FILE`, then executing the lowest eligible pass band.
- `$WAITING_FILE` was written once at the start of §4 and never rewritten — that's the locked-plan anti-pattern. The file must be rewritten at the start of every pass with fresh trial-sweep numbers.

If any of those describe the current run, do not push through the stuck commit. Jump to §3.7 Recovery.

**Why the on-disk waiting file is non-negotiable.** Text guardrails ("batch the trial sweep," "do not interleave") are easy for an LLM to agree with and then locally optimize away. A file is not. Each pass's landing loop is literally `for row in $WAITING_FILE`. If the file doesn't exist, the pass cannot start. If the file is sorted by `landing_pass` ascending, the landing order is pass-ascending. Phase discipline is enforced by what exists on disk, not by what you remember the skill said. **Snapshot `$WAITING_FILE` to `$WAITING_FILE.passN` at the start of every pass** so the audit trail records what each pass attempted.

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
- `$WAITING_FILE` — TSV path (default `/tmp/ps-port-grouped-$OUTPUT_NAME-waiting.tsv`). Written first by §3 for the first §4 pass, then **rewritten at the start of every subsequent pass** in §4 to reflect the current waiting set with fresh trial-sweep pass assignments. Its existence and completeness is the §3.5 gate's primary check. Each pass iterates this file in row order for the lowest `landing_pass` present; if it does not exist or is empty, the pass cannot start (empty waiting set means §5 is next, not "skip the pass").
- A snapshot `$WAITING_FILE.passN` is written at the start of pass N for audit. Never delete these snapshots until the run completes.
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

Build at `$OUTPUT_BASE` **before any cherry-pick**. Three outcomes:

1. **PASS** — record `$OUTPUT_BASE`'s build PASS in `$REPORT_FILE` and proceed to §2.
2. **FAIL, BDF-fixable** — apply Build-Driven Fix to make the base buildable (see §1.5 below). Then proceed to §2.
3. **FAIL, BDF-futile** — stop and ask (see Stop Conditions).

**rerere hygiene during the run:** if `rerere` is enabled, treat every reuse as untrusted. Before staging a rerere-resolved file, verify each resolved hunk against `$REFERENCE` per Rule C/D below. A stale rerere resolution from a prior run is one of the easiest ways to silently drop content from the output.

### 1.5 Base-BDF — make `$OUTPUT_BASE` buildable when it doesn't build

A non-building `$OUTPUT_BASE` is no longer a hard stop. Per-commit buildability requires every commit on `$OUTPUT_NAME` to build, **including the base** (commit 0 of the new history). If the base doesn't build, the very first cherry-pick has nowhere buildable to land on. Apply Build-Driven Fix to the base itself, **before §2 starts**, to establish a buildable foundation commit on `$OUTPUT_NAME`.

**Procedure.** Treat the base as a "commit 0" that BDF must repair:

1. **Inventory base errors.** Build at `$OUTPUT_BASE`, capture every unique compile error. Classify each per `BDF.md`'s external-missing-symbol vs internal-patch-bug taxonomy.
2. **Source the fix material.** Two authoritative sources, in priority order:
  - `**$REFERENCE` (or `$INPUT_TIP`) tip-fix commit**, if the input range contains an end-of-range "make buildable" commit (subject like `Make … buildable`, `Build/Compilation fix`, etc.). Split it into per-file patches up front; the patches whose target files are at base context apply cleanly here and supply most of the base-fix material. **This is the common case** for ranges where prior tooling already collected the buildability fixes.
  - **Cherry-pick of relevant later-range commits**, when the fix lives in a later input-range commit (Rule-1 prereq pull pattern from BDF.md). Pull only the symbol/decl/macro needed; don't drag the whole later commit forward.
3. **Apply as a single Base-BDF commit on `$OUTPUT_NAME`.** Call it `Base-BDF: make $OUTPUT_BASE buildable`. Its diff is the minimum set of hunks needed to flip the base's build from FAIL to PASS. Record its SHA in `$REPORT_FILE`.
4. **Build and confirm PASS.** This commit becomes the new "buildable foundation" — landing pass 1 starts on top of it.
5. **Reconcile with the tip-fix commit (if §1.5 sourced from it).** When the tip-fix commit's own cherry-pick eventually lands in §4 (in whichever pass its trial sweep first grades it landable), the hunks already folded into Base-BDF will be no-ops; the remaining hunks (those that needed later-commit context) will apply normally. The tip-fix commit ends up with a smaller diff than it started with, but `$OUTPUT_NAME`'s final tree still null-diffs to `$REFERENCE` because the same hunks are present, just landed earlier.

**Bounding.** Base-BDF is subject to the same Bounded Rule-1 thresholds from BDF.md: if the prereq set grows past ~5 distinct symbols per file region, or any error is internal-patch-bug class, or a fix cascades into 3+ further undeclared symbols, **stop applying Rule-1 and surface the blocker** rather than continue chasing. Base-BDF is "small, bounded fix to flip base build", not "rewrite the base wholesale." If it cannot be bounded, that's a Stop Condition — see "BDF-futile" below.

**Record in `$REPORT_FILE`.** Add a dedicated "§1.5 Base-BDF" section:

- Base error inventory (count, families, classification).
- Fix source (tip-fix per-file patches applied / later-commit prereq pulls / both).
- Base-BDF commit SHA and its file/hunk count.
- Post-Base-BDF build: PASS or FAIL.
- For each tip-fix hunk folded into Base-BDF: which input-range commit will see it as a no-op when that commit cherry-picks later.

**Drift detector.** After Base-BDF, `$OUTPUT_NAME` has 1 commit and is not at `$OUTPUT_BASE` anymore. The §3.5 gate's `$OUTPUT_NAME == $OUTPUT_BASE` check is replaced by `$OUTPUT_NAME == Base-BDF SHA AND Base-BDF builds clean`. Update the gate checklist accordingly.

**BDF-futile.** Base-BDF is futile and you must stop if:

- Base errors come from a strongly-connected dependency cluster of 30+ symbols spanning many later commits.
- No tip-fix commit exists in the input range AND no later commit supplies a minimal prereq.
- Bounded Rule-1 thresholds keep firing (3+ symbol cascades per attempted fix, internal-patch-bug class errors at base).

When futile, return `$OUTPUT_NAME` to `$OUTPUT_BASE`, document the analysis in `$REPORT_FILE`, and surface options per Stop Conditions.

### 2. Scan and Categorize

Generate the candidate commit list:

```sh
git rev-list --reverse "$INPUT_RANGE"
```

For each commit, derive three attributes:

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
(?i)\.(h|c|cc|cxx|cpp|hh|hpp|hxx|cmake|i|ic)$
```

(case-insensitive). Plain `.txt`, `.result`, `.test`, `.md`, `.spec` etc. do **not** trigger BUILD_CHANGING. A single matching path forces the flag true. (`.i` and `.ic` are InnoDB inline-include headers — same treatment as `.h`.)

**CMAKE_ONLY flag** — true if **all** changed paths basename-match `CMakeLists.txt` (any directory) AND BUILD_CHANGING is false. CMakeLists.txt by itself doesn't match the BC regex (`.txt` extension), but its content drives `cmake ..` reconfigure — flag it explicitly so landing pass 1 can include it without conflating with BC=0 docs/test commits.

```sh
# Pseudo-shell for the flag
paths=$(git diff-tree --no-commit-id --name-only -r "$sha")
cmake_only=1
for p in $paths; do
  case "$(basename "$p")" in
    CMakeLists.txt) ;;
    *) cmake_only=0; break ;;
  esac
done
```

Record per commit in `$REPORT_FILE`: original SHA, subject, category, BUILD_CHANGING, CMAKE_ONLY, changed-paths summary.

### 2.5 Build the Hunk-Level Dependency Graph

Before pass planning, build a **hunk-level dependency graph** of the input range. The graph is the single most important artifact for identifying pair candidates that the build chronology will trip over later. Skipping this step and discovering structure commit-by-commit through build failures is the #1 cause of long, frustrating runs.

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

#### Cycle detection (predict BDF futility up-front)

After the trial pass (§3) classifies each commit, compute **strongly-connected components of the conflict-pending subgraph**:

- Nodes: commits whose trial outcome is `conflict` or whose later state will be `deferred-build-fail` (in practice, BC=1 with trial=conflict and any BC=1 likely to build-fail).
- Edges: from `hunks.tsv` / `overlaps.tsv` — `A→B` where `B` modifies code `A` previously touched. Restrict to edges where both endpoints are in the pending set.
- Treat the graph as undirected for SCC; report largest connected component sizes.

If the largest component has size `>~50`, the pending set is structurally indivisible — **per-commit BDF (§4 pass loop and the §4.5 re-attempt strategy) will not converge.** Surface this in `$REPORT_FILE` and the §3.5 gate output BEFORE pass 1 execution. Two consequences:

- **Operator decision early, not late.** Rather than discovering futility commit-by-commit through 10 attempted blockers, present the SCC size and offer the §4.5 alternatives up front (cluster-as-one cherry-pick / per-family reconciliation / explicit reconciliation commits).
- **Prereq budgeting.** If the SCC is large, treat each blocker's prereq set as a leading indicator: blockers whose Rule-1 fix exceeds the bounded threshold (~5 symbols, see Rule 1) are inside the SCC and should be deferred, not chased.

A minimal SCC computation in Python (Tarjan or simple union-find over `overlaps.tsv`) takes seconds for 500 commits.

### 2.6 Build the Patch-ID Coverage Map

`git patch-id --stable` produces an identifier for a commit's diff that is independent of context line numbers, surrounding offsets, and small reformattings. Two commits whose tree changes are equivalent (the same patch applied in two places — e.g. an upstream cherry-pick already merged into `$OUTPUT_BASE`, an `Import foo.patch` re-import, or content folded into Base-BDF that originally lived in a later input-range commit) share the same patch-id even when their commit SHAs differ.

Build the coverage map **once** at this point in the workflow, then maintain it incrementally in §4 as commits land. Pre-computing empties is strictly cheaper than discovering them via the §3 trial sweep cherry-pick or the §4 `cherry-pick --skip` path. Crucially, it also removes those commits from the pass-assignment accounting so they do not consume landing-pass budget for work that will be skipped — and it surfaces, before the first pass starts, the count of commits whose content is already covered.

**Two patch-id sets, computed up front:**

```sh
mkdir -p .ps-port-grouped

# Input-range patch-ids (immutable after §2.6).
: > .ps-port-grouped/input-patch-ids.tsv
git rev-list --reverse "$INPUT_RANGE" | while read sha; do
    pid=$(git show "$sha" | git patch-id --stable | awk '{print $1}')
    [ -n "$pid" ] && printf '%s\t%s\n' "$pid" "$sha" >> .ps-port-grouped/input-patch-ids.tsv
done

# HEAD coverage patch-ids: commits already on $OUTPUT_NAME at or above $OUTPUT_BASE,
# PLUS a generous window of $OUTPUT_BASE's recent ancestry (catches already-merged
# equivalents when porting onto a base that absorbed earlier upstream cherry-picks).
: > .ps-port-grouped/head-patch-ids.tsv
{
    git rev-list "$OUTPUT_BASE..$OUTPUT_NAME"
    git log --format=%H -n 5000 "$OUTPUT_BASE"
} | sort -u | while read sha; do
    pid=$(git show "$sha" | git patch-id --stable | awk '{print $1}')
    [ -n "$pid" ] && printf '%s\t%s\n' "$pid" "$sha" >> .ps-port-grouped/head-patch-ids.tsv
done
```

Use `git patch-id --stable` (not the default `unstable` mode) — it produces a deterministic id across git versions and is independent of small context formatting.

**Intersect to predict empties:**

```sh
# Source commits whose patch-id is already present in HEAD coverage:
join -t$'\t' -1 1 -2 1 \
    <(sort -u .ps-port-grouped/input-patch-ids.tsv) \
    <(sort -u .ps-port-grouped/head-patch-ids.tsv) \
    | awk -F'\t' '{print $2"\t"$1"\t"$3}' \
    > .ps-port-grouped/predicted-empty.tsv
# Columns: source_sha, patch_id, head_sha
```

Every row in `predicted-empty.tsv` is an input-range commit whose tree-change is already in HEAD. The intent of the input commit is already satisfied; cherry-picking it would produce no diff and the §4 landing loop would `cherry-pick --skip` it anyway.

**§3 trial-sweep integration.** Before invoking `git cherry-pick --no-commit` for any commit, look it up in `predicted-empty.tsv`. If present:

- **Do not run the trial cherry-pick.** The commit is excluded from this pass's `$WAITING_FILE`.
- **Log once** in `$REPORT_FILE` under a "Predicted-empty (patch-id coverage)" section: `source_sha`, subject, the `head_sha` that already carries the same patch-id, and the pass at which the prediction fired.
- **No landing pass is assigned.** Predicted-empty commits never enter `$WAITING_FILE` and never count against pass landing budgets.

This trims the waiting set before §3's lock sweep runs. For runs onto a destination base that already absorbed many upstream cherry-picks (common in PS port runs), this can remove 10–30 % of the nominal input range up front, with zero cost beyond the patch-id computation.

**§4 landing-loop integration.** After every successful landing on `$OUTPUT_NAME`, append the new commit's patch-id to `head-patch-ids.tsv`:

```sh
# Run immediately after `git cherry-pick --continue` (or after the build PASS for the row).
new_sha=$(git rev-parse HEAD)
new_pid=$(git show "$new_sha" | git patch-id --stable | awk '{print $1}')
[ -n "$new_pid" ] && printf '%s\t%s\n' "$new_pid" "$new_sha" >> .ps-port-grouped/head-patch-ids.tsv
```

Then, when the next pass's §3 trial sweep runs, **re-intersect** input-patch-ids with the extended head-patch-ids before assigning the new waiting set. This catches commits whose net diff collapsed to empty because some of their hunks landed via fold operations into an earlier commit during this pass — the dependent commit's patch-id may now match one of HEAD's commits. Without re-intersection, those commits would consume a full trial-sweep slot (and possibly an early-pass landing slot) only to skip-empty in §4 step 3.

**Bounds and caveats.**

- **Renames.** `git patch-id` is computed on the diff text. File renames change the diff header (`a/old`, `b/new`) and produce a different patch-id even when the content change is identical. If your input range contains renames whose content also lands in `$OUTPUT_BASE` (under either old or new name), the intersection will miss them and they'll discover-empty at cherry-pick time. Do not invent a rename-tolerant patch-id without engineer approval — the standard `--stable` form is the contract.

- **Whitespace and trivial reformat.** `--stable` is robust to most context drift but not to deliberate whitespace-only changes interleaved with content. A commit that reformats and then re-adds the same content has a different patch-id from the reformat-free original. Treat patch-id misses as "could not predict" — never "definitely not present".

- **Tree-identical without patch-id match.** A commit that resolves to a no-op for other reasons (e.g. its hunks were folded into Base-BDF as different-but-equivalent edits, or REFERENCE-based reconciliation removed the target lines) will not be caught by patch-id intersection. The §4 landing loop's existing `git diff --cached --quiet && git diff --quiet` check still runs as the final guard; patch-id prediction is an upstream optimization, not a replacement for the runtime empty check.

- **`$REFERENCE` patch-id set is optional.** Computing patch-ids for `$REFERENCE`'s ancestry lets you spot input commits whose content lives in REFERENCE under a different SHA — useful Rule-D context (a HEAD-empty conflict region whose REFERENCE counterpart exists under a different commit). Build the REFERENCE set only if the run hits Rule-D ambiguity at scale; otherwise it costs without paying for itself.

- **HP-1 / Rule-A compliance.** The patch-id coverage map is read-only computation. It does not perform any worktree write, conflict resolution, or whole-file replacement. Predicting an empty cherry-pick is information, not action — the §4 landing loop still applies its skip-empty rule when a predicted-empty source SHA is encountered (or when post-cherry-pick checks confirm an unpredicted empty).

**Where the coverage map lives.** Under a `.ps-port-grouped/` directory in the worktree root. Files:

- `input-patch-ids.tsv` — `patch_id<TAB>source_sha` (immutable after §2.6, sorted unique by patch_id for the `join`).
- `head-patch-ids.tsv` — `patch_id<TAB>head_sha` (append-only during §4; re-sort before each pass's re-intersection).
- `predicted-empty.tsv` — `source_sha<TAB>patch_id<TAB>head_sha` (recomputed each pass via the `join` above).

**Performance.** For 500 commits, computing patch-ids is ~30–60 s (single-pass `git show | git patch-id`). The `join`-based intersection is sub-second. Per-pass append-and-reintersect is sub-second after the first pass. This is dwarfed by the per-pass trial-build cost — the coverage map is essentially free relative to §3's trial sweep.

**§3.5 gate addition.** Add these checks to the workflow gate:

- `.ps-port-grouped/input-patch-ids.tsv` exists and has row count equal to `git rev-list --count $INPUT_RANGE` (modulo commits that produced no patch-id — record any such in the report).
- `.ps-port-grouped/head-patch-ids.tsv` exists and includes at minimum every SHA in `$OUTPUT_BASE..$OUTPUT_NAME`.
- `.ps-port-grouped/predicted-empty.tsv` was recomputed for this pass.
- `$WAITING_FILE` row count equals `(input count − predicted-empty count − already-landed count)`, not `(input count − already-landed count)`. The predicted-empty subset is excluded from the waiting set.

A missing coverage map is a §3.5 gate stop in its own right: continue and you'll re-discover the empties one cherry-pick at a time, inflating pass cost.

**Why this matters at the rubric level.** Without the coverage map, an input commit whose content is already in HEAD goes through the trial cherry-pick (returns clean/empty, n_conflicts=0), gets assigned to landing pass 1 or 2, lands at its `land_pos`, runs the empty-skip path, contributes one row to the audit trail and produces no tree change. With the coverage map, the same commit is identified before any trial cherry-pick runs; it is logged once in `predicted-empty.tsv` and the report, and is excluded from `$WAITING_FILE` entirely. For large input ranges with significant input/HEAD overlap (common when the destination base already absorbed upstream cherry-picks, or when the input range re-imports patches the base already contains), this removes dozens to hundreds of empty-skip cycles per run with no risk to correctness — the §4 runtime empty check is preserved as the final guard for the un-predicted cases.

### 3. Plan First Pass

The skill iterates **passes** in §4. Each pass strictly reduces the waiting set. §3 builds the data for the first pass: a trial sweep of every commit in `$INPUT_RANGE` against `$OUTPUT_BASE` (or post-Base-BDF tip), assigned to a `landing_pass`, and written to `$WAITING_FILE`. §4 will rewrite `$WAITING_FILE` for every subsequent pass using the same procedure against the then-current `$OUTPUT_NAME` tip.

A commit's `landing_pass` is its eligibility-to-land right now. It is assigned from the pass definitions in §4, not from chronological order. Within the selected pass, prefer commits the user cares about (features first) unless the user specified otherwise, optionally re-sorted by descending `fwd-weight` for large pass bands (see §4 intra-pass ordering).

`**build_conflicts` metric.** During the trial sweep, for every BC=1 commit:

1. Cherry-pick `--no-commit` against the trial base (current `$OUTPUT_NAME` tip for the pass being planned).
2. If the cherry-pick produced conflicts, also run `make -j$N` against the conflicted-but-staged tree. If it didn't conflict, run `make` directly.
3. Parse `build.log` for `error:` lines, extract the source file path, count **distinct files**. That count is the commit's `build_conflicts` for this pass.
4. `git cherry-pick --abort` (if pending) and `git reset --hard $TRIAL_BASE`; `git clean -fdq`.

This adds a build step per BC=1 commit during the trial sweep. With warm ccache, each trial build is typically 30–120 s. For 300 BC=1 commits that's ~2–10 hours of trial cost per pass — front-loaded so the pass assignments reflect real build difficulty against the **current** tip, not just cherry-pick conflict shape and not the previous pass's stale numbers. If the cost is prohibitive for the run scale, skip the trial-build for any commit whose `n_conflicts` already exceeds 16 (it will land no earlier than pass 4 regardless) and skip for commits whose touched paths are exclusively `mysql-test/` (no build impact).

Record both `n_conflicts` and `build_conflicts` columns in the trial output TSV; the lock sweep uses both to assign the next landing pass.

**Planning a pass is a two-sweep process.** You cannot fully grade conflict size by reading the commit; you have to try against the live tip. So at the start of every pass (including pass 1, which §3 plans):

0. **Patch-ID empty filter (§2.6).** Before the trial sweep, re-intersect `input-patch-ids.tsv` with the current `head-patch-ids.tsv` (regenerated by appending each landed commit's patch-id during §4) and rewrite `predicted-empty.tsv`. Exclude every commit whose source SHA appears in `predicted-empty.tsv` from this pass's waiting set — they do not get trialed, assigned a landing pass, or written to `$WAITING_FILE`. Log them in the "Predicted-empty" section of `$REPORT_FILE` with the head SHA that already carries their patch-id. The lock sweep operates on the post-filter set.
1. **Trial sweep** — for every commit in the current (post-filter) waiting set, run a quick `git cherry-pick --no-commit` trial **on a throwaway worktree** (or in-place with `--abort` on every result), plus the BC=1 trial build above. Compute `(n_conflicts, build_conflicts)` against the live tip.
2. **Lock sweep** — assign each waiting commit a `landing_pass` from the pass definitions in §4 and write `$WAITING_FILE` for this pass. If reality later refutes the trial, defer the row to the next pass rather than moving it in place. The **next** pass's trial sweep is where re-assignment happens cleanly — by construction it produces fresh values against the new tip.

**Batch the trial sweep — required, not optional.** A full sweep of every waiting commit is expensive (500+ throwaway picks is a real cost in pass 1; smaller in later passes). Trial in **~50-commit chunks**, assign each chunk, then trial the next chunk. The trial sweep must cover the **entire** waiting set before any cherry-pick lands in this pass. The only permitted shortcut: skip the trial-pick for low-risk categories (docs-only, test-only, packaging-only) and assign those by category + BUILD_CHANGING alone after the first ~3 chunks have established the conflict pattern. Source-bucket, build, reconciliation, and any BUILD_CHANGING commit always get the trial.

**Do not interleave trial chunks with pass-1 landings inside a pass.** "Trial chunk 1 → land pass 1 from chunk 1 → trial chunk 2" is forbidden inside a single pass. It produces post-hoc scheduling (you assign commits in the order they appear, then land them in roughly that order) and silently degenerates into chronological processing. Complete the trial sweep for the entire waiting set, write `$WAITING_FILE` for this pass, *then* begin landings. (Across **passes** this looks similar — pass 2's trial sweep happens after pass 1's landings — but that's *the design*: re-trialing against a different live tip yields different pass assignments. Inside one pass, do not interleave.)

The trial sweep produces a working dataset; throwaway operations must not pollute `$OUTPUT_NAME`.

#### Writing `$WAITING_FILE`

At the end of §3 (and at the start of every subsequent pass in §4), **write the current waiting set to `$WAITING_FILE`** in this exact TSV format (tab-separated, header row included):

```
land_pos	landing_pass	intra_pass_order	orig_sha	rev_list_pos	category	build_changing	cmake_only	n_conflicts	build_conflicts	attempt_round	subject
1	1	1	abc123def456	7	bugfix	0	0	0	0	1	Fix typo in error message
2	1	2	...
...
M	5	K	...
```

The file holds **M rows for M still-unlanded commits**. M shrinks every pass. A row is removed once its commit successfully lands; a row stays (with refreshed `landing_pass`/`n_conflicts`/`build_conflicts` and incremented `attempt_round`) when its commit is not yet attempted or attempted and rolled back.

Field semantics:

- `land_pos` — 1..M within this pass. The **landing order for this pass**. Re-numbered every pass. Not stable across passes.
- `landing_pass` — 1..5, current-pass eligibility band from the trial sweep and §4 pass definitions.
- `intra_pass_order` — 1..K within the `landing_pass` for this pass.
- `orig_sha` — the source commit's full SHA. Stable across passes.
- `rev_list_pos` — the commit's index in `git rev-list --reverse $INPUT_RANGE`. **Reference only.** Surfaced here so you can detect chronological drift: if `rev_list_pos` is monotonically increasing along `land_pos`, you have not actually scheduled by pass — you've sorted chronologically and labeled it.
- `category`, `build_changing`, `subject` — as scanned in §2. Stable across passes.
- `cmake_only` — 1 if the commit's changed paths are **exclusively** `CMakeLists.txt` files (any directory); 0 otherwise. Used together with `build_changing=0` for landing pass 1 admittance.
- `n_conflicts` — count of files reported unmerged after `git cherry-pick --no-commit` in this pass's trial sweep. 0 for clean/empty trial outcomes. **Refreshed every pass.**
- `build_conflicts` — count of distinct source files emitting `error:` lines during this pass's trial build. **Refreshed every pass.** May drop dramatically once a prereq sibling lands in an earlier pass.
- `attempt_round` — how many times this commit has been present during a §4 re-plan (1, 2, 3, …). Lets you see how long each commit has been waiting without overloading `landing_pass`.

A commit's `(landing_pass, n_conflicts, build_conflicts)` changing across passes is the **point** of the pass model — it shows the waiting set is being de-risked by the landings, not just shuffled.

#### Landing-pass assignment pseudocode (for the lock sweep)

```python
def landing_pass_for(t):
    bc = (t['build_changing'] == '1')
    cmake_only = (t['cmake_only'] == '1')
    nc = int(t['n_conflicts'])
    bf = int(t['build_conflicts'])

    # Pass 1: BC=0 OR cmake_only
    if (not bc) or cmake_only:
        return 1

    # BC=1 from here on. Both metrics must satisfy the threshold (AND).
    if nc <= 4 and bf <= 4:
        return 2
    if nc <= 16 and bf <= 16:
        return 3
    # Anything else BC=1
    return 4
```

`other-fail` trial outcomes (cherry-pick exit code != 0 with no conflicts and no clean status) -> landing pass 5.

Sort the file by `(landing_pass ASC, intra_pass_order ASC)`. The file's row order **is** the candidate landing order for this pass; §4 will execute only the lowest `landing_pass` present before re-planning.

Sanity checks before declaring the pass plan complete (run at the end of §3 for pass 1; run at the top of each pass in §4 for pass 2+):

```sh
# Row count matches expected waiting set (input-range commit count minus already-landed).
expected_M=$(( $(git rev-list --count $INPUT_RANGE) - $(git rev-list --count $OUTPUT_BASE..$OUTPUT_NAME) ))
test "$(tail -n +2 "$WAITING_FILE" | wc -l)" -eq "$expected_M" || echo "WAITING FILE WRONG SIZE"

# land_pos column is 1..M contiguous.
awk -F'\t' 'NR>1 {print $1}' "$WAITING_FILE" | awk 'NR!=$1 {print "GAP at "NR; exit 1}'

# rev_list_pos is NOT monotonically increasing along land_pos (if it is, you didn't actually schedule by pass — flag for manual review unless the waiting set is genuinely already easier-first).
awk -F'\t' 'NR>1 {if (prev!="" && $5<prev) mono=0; else if (prev!="" && $5>prev) inc++; prev=$5; tot++} END {if (inc==tot-1) print "WARNING: rev_list_pos monotonically increasing — verify pass assignments are real, not cosmetic"}' "$WAITING_FILE"

# Pass thresholds: verify pass 2 rows have n_conflicts ≤ 4 AND build_conflicts ≤ 4;
# pass 3 rows have ≤16 on both; pass 4 rows exceed 16 on at least one.
# (Field positions per the documented TSV: n_conflicts=col 9, build_conflicts=col 10.)
awk -F'\t' 'NR>1 {
  g=$2; nc=$9+0; bf=$10+0;
  if (g==2 && (nc>4 || bf>4)) print "Pass 2 row violates thresholds at line "NR": nc="nc" bf="bf;
  if (g==3 && (nc>16 || bf>16)) print "Pass 3 row violates thresholds at line "NR": nc="nc" bf="bf;
  if (g==4 && nc<=16 && bf<=16) print "Pass 4 row should have been in pass 3 at line "NR": nc="nc" bf="bf;
}' "$WAITING_FILE"

# Pass 1 admittance: BC=0 OR cmake_only=1. (build_changing=col 7, cmake_only=col 8.)
awk -F'\t' 'NR>1 && $2==1 {
  bc=$7+0; co=$8+0;
  if (bc==1 && co==0) print "Pass 1 row at line "NR" is BC=1 and not cmake_only — admittance violated";
}' "$WAITING_FILE"

# Snapshot for audit before the pass begins landing.
cp "$WAITING_FILE" "$WAITING_FILE.pass${PASS_NUM}"
```

If any of these warnings fire, do not proceed to the landing loop — re-check that the trial sweep actually graded conflict shape (and ran the trial build for `build_conflicts`) against the current tip, not just category or stale numbers from the previous pass.

### 3.5 Workflow Gate — Preconditions for §4

Before executing the first real cherry-pick of pass 1 (§4), confirm **all** of the following are true. Each is independently verifiable on disk — do not "remember" them, run the check. If any answer is "no", you are not ready for §4 — return to the corresponding earlier step.

- `$OUTPUT_BASE` (or the Base-BDF SHA from §1.5) built clean (§1/§1.5) and the PASS is recorded in `$REPORT_FILE`.
- `**$WAITING_FILE` exists** (`test -f "$WAITING_FILE"`).
- `**$WAITING_FILE` row count equals the unlanded-and-not-predicted-empty commit count** — for pass 1 this is `git rev-list --count $INPUT_RANGE` minus the row count of `.ps-port-grouped/predicted-empty.tsv`. (Pass 2+: `(input count − landed count − predicted-empty count)`.) A partial waiting set is not a waiting set.
- `**Patch-ID coverage map exists** (`test -s .ps-port-grouped/input-patch-ids.tsv` and `test -s .ps-port-grouped/head-patch-ids.tsv`) **and was re-intersected for this pass** (`predicted-empty.tsv` mtime is newer than the most recent landing on `$OUTPUT_NAME`). A missing or stale coverage map means §3.0 was skipped — return to §2.6 and §3 step 0 before proceeding.
- `**$WAITING_FILE` rows are sorted by (landing_pass, intra_pass_order).** Verify: `awk -F'\t' 'NR>1 {key=$2"."sprintf("%06d",$3); if (key<prev) {print "OUT OF ORDER at line "NR; exit 1} prev=key}' "$WAITING_FILE"`.
- A `$WAITING_FILE.pass1` snapshot exists.
- Every commit in `$INPUT_RANGE` has a row in the §3 scan table with Category, BUILD_CHANGING, and a first-pass `landing_pass` (1–5).
- The hunk-level dep graph (§2.5) has been built and the "Pre-detected pairs" section of `$REPORT_FILE` is populated (even if the list is empty — record "no pairs detected").
- `**$OUTPUT_NAME` is at `$OUTPUT_BASE` (or Base-BDF SHA).** Verify: `git rev-parse "$OUTPUT_NAME"` equals the expected SHA. No commits have been cherry-picked yet for pass 1. If commits exist, you either drifted (jump to §3.7) or you're resuming mid-run (different recovery — see §3.7).
- The next commit you intend to apply is **row 1 of `$WAITING_FILE`** (the lowest-landing-pass, intra-pass-first row), not "the next commit by chronological index" or "the next commit I happen to remember."

If the waiting set is written but you find yourself reaching for the next commit in input-list order rather than the next row of `$WAITING_FILE`, **stop**. That is the rationalization the skill exists to prevent. Re-read §3 and the Red Flags below.

### 3.6 Red Flags — STOP and re-plan

You are about to (or already) violating the easier-first invariant if any of these are true:

- You started cherry-picking onto `$OUTPUT_NAME` before every commit in the waiting set had a current-pass `landing_pass`.
- You are processing commits in the order `git rev-list --reverse $INPUT_RANGE` produced them.
- Your "pass 1 of execution pass N" landings include commits you later reassigned to pass 4 *after* they failed to apply or build — i.e. the pass was assigned post-hoc, after attempting the pick.
- You are on commit N and the next commit you plan to attempt is N+1 (by `rev_list_pos`), without checking whether commits later in this pass's `$WAITING_FILE` contain easier (lower-pass) work that should land first.
- You're stuck on a hard commit (landing pass 4/5 shape) inside a pass and your plan is "push through this one" rather than "skip past it, land the easier passes, let the next pass's trial sweep re-assign it once its siblings have landed."
- `$WAITING_FILE` is the same on disk as when you started the pass — i.e. you never rewrote it after pass N's landings. The next pass cannot start until pass N+1's trial sweep produces fresh pass assignments.
- You skipped §2.5 (the dep graph) because "the range is short" or "I'll discover pairs as I go."

If any of these fire: revert `$OUTPUT_NAME` to the last pass-boundary buildable SHA, redo the trial + lock sweeps for the unlanded waiting set, and resume from row 1 of the re-planned pass. The discarded work is the cost of skipping the pass discipline; the alternative (continuing chronologically and re-assigning on the fly) compounds the cost commit by commit.

### 3.7 Recovery — How to pivot when chronological drift is detected

You are here because the Workflow Phase Discipline section, §3.5, or §3.6 fired and you've established that `$OUTPUT_NAME` has commits landed without `$WAITING_FILE` driving them. Do not push through the stuck commit. Pivot:

1. **Inventory what's on `$OUTPUT_NAME` already.** Capture `git log --reverse --format='%H %s' $OUTPUT_BASE..$OUTPUT_NAME > /tmp/landed-so-far.txt`. These SHAs are the commits you already invested resolution work in — you don't want to throw that away unless necessary.
2. **Find the last pass-boundary buildable SHA.** Walk `$REPORT_FILE`'s "Pass execution" section for the most recent recorded `Pass-N end buildable SHA`. If none exists (you never finished a pass cleanly), use `$OUTPUT_BASE` (or Base-BDF SHA).
3. **Reset.** `git checkout "$OUTPUT_NAME" && git reset --hard <buildable-SHA>`. This is the irreversible step; confirm the SHA before running it.
4. **Re-do the trial sweep for the unlanded commits** against the new tip. Run the trial picks on a throwaway worktree, do not grade by category alone. This is functionally a fresh pass plan (§3 procedure, but with a smaller waiting set).
5. **Rewrite `$WAITING_FILE`.** The waiting set covers only commits not already landed. Run the sanity checks. If the "rev_list_pos monotonically increasing" warning fires, your trial sweep didn't grade conflict shape — re-do it.
6. **Snapshot to `$WAITING_FILE.pass<N>-recovered`** so the audit shows the pivot.
7. **Run the §3.5 gate.** Every checkbox.
8. **Resume §4 from row 1 of the rewritten `$WAITING_FILE`.** The cherry-picks you previously did that fall into landing pass 1 of the new plan can often be re-applied cleanly; the ones in later passes may have been the wrong order anyway. Either way, the next pick comes from the file.
9. **Record the pivot in `$REPORT_FILE`** under a dedicated "Pivots" section: the SHA you reset to, why (which red flag fired, which `land_pos` or `rev_list_pos` you were stuck on, what pass you were in), how many commits were re-planned. This is for the engineer reviewing the run, not for you — but writing it forces honest acknowledgement of what happened.

**Sunk-cost trap.** "I've already done conflict resolution for commits 1–33 this pass, surely I can finish 34 and recover from there." No. The reason 34 is hard is that easier commits in the same waiting set haven't landed yet to provide context — and the next pass's re-trial would have surfaced that 34 should be deferred. Pushing through 34 in isolation does not produce a better tree than 34 with the easier surrounding work applied first. Reset.

**When `$REFERENCE` = `$INPUT_TIP` (maximum-danger config).** Chronological drift in this configuration risks silent HEAD-empty drops at the same time. After reset, re-examine every Rule-D decision made on the discarded commits when you re-do them. Do not assume past resolutions were correct.

### 4. Execute Iterative Passes

**Precondition:** the §3.5 Workflow Gate has been satisfied for the first pass. If you cannot tick every box in §3.5, do not run a single cherry-pick from this section.

§4 is the pass loop. The former scheduling buckets are the passes: pass 1 is the easiest work that can land now, pass 4 is the hardest still-BDF-eligible work, and pass 5 is the deferred/problem set. **Each pass executes only the lowest `landing_pass` present in `$WAITING_FILE`, then rewrites `$WAITING_FILE` from a fresh trial sweep before choosing the next pass.** Each pass strictly reduces `$WAITING_FILE`'s row count, or it terminates the loop by adding 0 commits → §4.5. The loop runs until the waiting set is empty (success → §5) or a whole pass yields 0 landings (escalate → §4.5).

#### Pass Definitions

| Landing pass | Definition |
| ------------ | ---------- |
| 1 | **BC=0 commits + CMakeLists.txt-only commits.** Any trial outcome (clean apply, empty, or conflict). Two admittance shapes: (a) commits whose changed paths match no `.h/.c/.cc/.cxx/.cpp/.hh/.hpp/.hxx/.cmake/.i/.ic` extension (per the BC regex); (b) commits whose changed paths are **exclusively** `CMakeLists.txt` (any directory). Land first; build verification is required at the pass boundary, not after every row by default. |
| 2 | BC=1 with **trial n_conflicts <= 4 AND trial-build error-file count <= 4** against the current tip. Lightest BC=1 pass. Includes BC=1 commits whose trial outcome was clean/empty (n_conflicts = 0) as long as their trial build produces <= 4 error-files. |
| 3 | BC=1 with **trial n_conflicts <= 16 AND trial-build error-file count <= 16**, AND not already in pass 2. Medium pass. |
| 4 | BC=1 with **n_conflicts > 16 OR trial-build error-file count > 16**. All remaining BC=1 that is still BDF-eligible. |
| 5 | Anything not applicable above: deferred/problem cases such as `other-fail` trial outcomes (cherry-pick rc != 0 with no conflicts and no clean status). Pass-5 rows are not attempted while earlier passes exist; they roll forward to the next trial sweep, where their assignment may change as the tip evolves. |

Both pass-2 and pass-3 admission requires **both thresholds** to hold (AND, not OR). A commit with n_conflicts=2 but 30 trial-build errors -> pass 4. A commit with n_conflicts=8 but 2 trial-build errors -> pass 3 (8 <= 16 AND 2 <= 16). The two metrics are independent signals: cherry-pick conflict density and build-time symbol-dependency density.

**Why pass 1 admits CMakeLists.txt-only.** CMake files affect `cmake ..` configure-time orchestration (which sources are listed in `INNOBASE_SOURCES`, which plugins are built) but contain no C++ that gets compiled. Broken CMake content surfaces as `cmake` errors at the next reconfigure, not as `error:` messages during `make`. Putting CMakeLists.txt-only commits in pass 1 lets them land alongside docs/tests/MTR commits without forcing build verification at every row. A commit that touches both CMakeLists.txt AND `.cc` source is BC=1 (the `.cc` triggers the BC regex) and lands in pass 2/3/4 by its trial metrics.

**Why pass 1 is BC=0-only otherwise.** A previous version of this rubric admitted BC=1 commits into the earliest bucket whenever the cherry-pick trial happened to be clean. In practice, BC=1 "clean trial" commits routinely fail at build time because they use symbols a later commit defines (e.g. `expand_fast_index_creation`, `OPT_INNODB_OPTIMIZE_KEYS`, `page_hash_latch`). That forced a Rule-1 or Rule-2 build fix on every BC=1 commit in what was supposed to be the easiest pass, inflating pass-1 wall-clock time disproportionately and undermining the "easier-first" framing. Restricting pass 1 to BC=0 (plus CMakeLists.txt-only as a known-safe extension) means it lands fast, establishing a known-buildable foundation **before** any BC=1 commit is picked.

**Why the `(n_conflicts, build_conflicts)` two-axis assignment for passes 2–4.** Trial cherry-pick conflicts measure code that overlaps with the live tip's edits in the same file regions. Trial-build error count measures symbol-dependency on commits that haven't landed yet — a completely different failure mode. A commit can be cherry-pick-clean but build-fail on 30 files (uses-before-defines); another can have 8-file cherry-pick conflicts but build-clean once those are resolved. The dual threshold separates these.

```text
pass = 1
while $WAITING_FILE has rows:
    # (a) Plan this pass — §3 procedure applied to the current waiting set.
    if pass > 1:
        run §3 trial sweep against the current $OUTPUT_NAME tip for every row
        rewrite $WAITING_FILE with fresh landing_pass / n_conflicts / build_conflicts / attempt_round columns
        run the §3 sanity checks; if they fail, fix before proceeding
    current_landing_pass = lowest landing_pass value present in $WAITING_FILE
    if current_landing_pass == 5:
        invoke §4.5 deferred-set management; break
    cp $WAITING_FILE $WAITING_FILE.pass${pass}    # audit snapshot

    landed_this_pass = 0
    skipped_this_pass = 0

    # (b) Landing loop — iterate only rows for current_landing_pass, in row order.
    tail -n +2 "$WAITING_FILE" | rows where row.landing_pass == current_landing_pass | while read row; do
        attempt cherry-pick of row.orig_sha
        if applied + built clean:
            landed_this_pass += 1
            remove row from $WAITING_FILE in-memory
        else:
            git cherry-pick --abort (or roll back the local commit)
            leave row in $WAITING_FILE (next pass will re-trial it)
            skipped_this_pass += 1
        record outcome in $REPORT_FILE under "Pass ${pass} (landing_pass=${current_landing_pass})"
    done

    # (c) End-of-pass bookkeeping.
    write the surviving rows back to $WAITING_FILE
    record pass-end buildable SHA in $REPORT_FILE
    if landed_this_pass == 0:
        invoke §4.5 deferred-set management; break

    pass += 1
```

**Ordering invariant — within a pass, the iteration is over `$WAITING_FILE` rows for the selected `landing_pass`, not over `git rev-list` output.** The next commit to pick is *always* the lowest-numbered `land_pos` in the current `landing_pass` not yet attempted in this pass. If you find yourself reaching for a commit by `rev_list_pos` (i.e. chronological index), or by SHA-from-memory, you have fallen back to chronological processing — stop and re-read §3.6/§3.7.

The intra-pass landing loop, in shell-style:

```sh
current_landing_pass=$(awk -F'\t' 'NR>1 {if (min=="" || $2<min) min=$2} END {print min}' "$WAITING_FILE")
tail -n +2 "$WAITING_FILE" | awk -F'\t' -v p="$current_landing_pass" '$2 == p' | while IFS=$'\t' read -r land_pos landing_pass intra_order orig_sha rev_list_pos category build_changing cmake_only n_conflicts build_conflicts attempt_round subject; do
    echo "=== pass=$pass landing_pass=$landing_pass land_pos=$land_pos orig_sha=$orig_sha (rev_list_pos=$rev_list_pos) ==="

    # 0. Patch-ID guard (§2.6). The §3.0 filter already excluded predicted-empty
    #    commits from $WAITING_FILE, so this row should not be predicted-empty.
    #    Re-check defensively in case the coverage map was extended mid-pass:
    if grep -q "^${orig_sha}\b" .ps-port-grouped/predicted-empty.tsv; then
        echo "predicted-empty mid-pass — skipping without cherry-pick"
        # Record the late discovery in $REPORT_FILE; do not run any git command.
        continue
    fi

    # 1. Cherry-pick (use -m 1 if merge commit).
    if [ "$(git cat-file -p "$orig_sha" | grep -c '^parent ')" -gt 1 ]; then
        git cherry-pick -m 1 "$orig_sha" || true
    else
        git cherry-pick "$orig_sha" || true
    fi

    # 2. Resolve conflicts per Rules A–D (manual step; the loop pauses here).
    # 3. If empty after resolution: git cherry-pick --skip; remove the row from $WAITING_FILE; continue.
    #    (This catches the un-predicted-empty cases — renames, whitespace, fold-equivalents
    #    that the §2.6 patch-id map could not match. It is the final guard, not the primary
    #    detection path.)
    # 4. Otherwise: git cherry-pick --continue.
    # 5. Build. If fail: apply Bounded Rule 1; if that's blown, git reset --hard HEAD~ and leave the row in $WAITING_FILE for the next pass.
    # 6. On success:
    #    - remove the row from $WAITING_FILE;
    #    - append the new commit's patch-id to .ps-port-grouped/head-patch-ids.tsv:
    #        new_sha=$(git rev-parse HEAD)
    #        new_pid=$(git show "$new_sha" | git patch-id --stable | awk '{print $1}')
    #        [ -n "$new_pid" ] && printf '%s\t%s\n' "$new_pid" "$new_sha" \
    #            >> .ps-port-grouped/head-patch-ids.tsv
    #    - record outcome in $REPORT_FILE.
done
```

This loop is the per-pass contract. Every cherry-pick `$OUTPUT_NAME` receives must come from a `$WAITING_FILE` row in the selected `landing_pass`, processed in `land_pos` order, on a snapshot that already reflects this pass's trial sweep. There is no other way to pick a commit. If you find yourself running `git cherry-pick <sha>` where `<sha>` did not come from reading the next un-attempted row, you are violating §4.

**Reassignment waits for the next pass.** If commit at `land_pos = P` reveals itself to require a later landing pass than the trial assigned (for example, pass 1/2 work that actually has pass 4/5 shape), `git cherry-pick --abort`, leave the row in `$WAITING_FILE`, record the mismatch in `$REPORT_FILE`, and continue with the next row in the current pass. Do not edit the row into a different pass and keep going inside the same pass. The next pass's trial sweep is the only place pass reassignment happens; fresh numbers against the new tip are the point of the model.

**Merge commits in the input range:** `git cherry-pick` requires `-m <parent-number>` for merges. With `--first-parent` in `$INPUT_RANGE` this rarely matters (merges normally get traversed via their first-parent edge, not picked as merges themselves). With a plain range, merges *will* appear in the list. Default to `-m 1` (apply the diff against parent 1, the mainline). If parent 1 isn't the right mainline for a particular merge, that's a stop-and-ask condition.

After every **pass boundary** (`landed_this_pass > 0` and waiting set non-empty), snapshot the SHA, confirm `$OUTPUT_NAME` is buildable, and record the pass-end buildable SHA in `$REPORT_FILE` — these are the recovery points if §3.7 fires later.

**Termination conditions for the pass loop:**

- **Success** — `$WAITING_FILE` empty. Go to §5.
- **Stall** — a whole pass with `landed_this_pass == 0`. Go to §4.5. This is the canonical signal that per-commit BDF won't progress without a strategy choice; do not start another pass with the same waiting set hoping for a different result.
- **Hard budget exhausted** — engineer-set wall-clock or pass-count budget. Stop and ask; do not silently switch to "land everything chronologically and verify only at tip."

#### Intra-pass ordering: topological by dep-graph forward weight

`$WAITING_FILE` is sorted by `(landing_pass, intra_pass_order)`, but the *intra-pass* default sort is `rev_list_pos` (maintainer order). For pass bands large enough to matter (typically landing pass 3 and landing pass 4), the dep graph offers a better intra-pass sort: **descending `fwd-weight`** — i.e. land first the commits that unblock the most others.

The `fwd-weight` is the sum of overlap weights on outgoing edges from `commit A → other-pending`. Landing a high-`fwd-weight` commit means its declarations/struct-field additions are in HEAD before the dependents try to land — converting conflict commits into clean picks, often moving them into an earlier landing pass in the **next** pass's trial sweep.

When to use topological order instead of `rev_list_pos`:

- Landing pass 3 / landing pass 4 large (>=30 commits each) in this pass's waiting set.
- Trial showed many `BC=1 conflict` commits whose conflicts are on the same shared headers (univ.i, buf0buf.h, sql_class.h, etc.).
- A `depq.py hot` (or equivalent) query lists 5+ commits with `fwd-weight > 50`.

How to use: in the pass's lock sweep, secondary-sort within each `landing_pass` by `fwd-weight DESC` after the first-pass `rev_list_pos`. Keep the original `rev_list_pos` in the row for traceability. Record the choice in `$REPORT_FILE` so a re-runner knows whether to expect maintainer-chronological vs topological order.

Caveat: topological order only makes sense for commits inside the trial-graded *conflict* set (landing passes 3 and 4). Pass 1 (BC=0) and pass 2 (BC=1 clean/empty/light) have no incoming-graph reason to deviate from maintainer order.

### 4.5 Deferred-set Management — invoked when a pass yields 0 landings

Most non-trivial runs reach a state where one entire pass through `$WAITING_FILE` lands zero commits. That is the §4 stall condition — the deferred set is what's left in `$WAITING_FILE` at that point:

- Built but failed (per-commit build) and were rolled back;
- Hit conflict at cherry-pick time and were skipped via `cherry-pick --abort`;
- Sat in landing pass 5 (other-fail) across multiple passes without ever becoming landable.

§5 ("Final Convergence to null diff") assumes you're handling residual file content. §4.5 sits between §4 and §5 and explicitly decides **how** to deal with the deferred set before measuring residual.

**Precondition:** a §4 pass completed with `landed_this_pass == 0` (or the engineer authorized an early §4.5 invocation); branch is buildable at HEAD.

**Step 1 — Inventory.** Count outcomes by family from `$EXEC`:


| outcome                                  | meaning                                 | typical handling                                        |
| ---------------------------------------- | --------------------------------------- | ------------------------------------------------------- |
| `deferred-build-fail`                    | Cherry-pick clean, build broken         | BDF re-attempt candidate                                |
| `deferred-conflict`                      | Cherry-pick fails, conflicts unresolved | BDF re-attempt candidate (state may have evolved)       |
| `deferred-bdf-internal`                  | Commit's own code is buggy              | Wait for sibling commit, then re-attempt                |
| `skip-rule-b`                            | Patch's intent dead in REFERENCE        | Leave skipped; §5 residual will be zero for these paths |
| `skip-empty` / `skip-empty-after-remove` | Content already present or removed      | Leave skipped                                           |


**Step 2 — Cycle check.** Run the §2.5 SCC computation against just the deferred set. If the largest component has size `> ~50`, per-commit BDF will not converge — escalate to a §4.5 alternative (below) rather than wasting iterations.

**Step 3 — Choose a strategy.** Surface options to the engineer and let them pick (do not silently progress):


| Strategy                                | When appropriate                                                                                                          | Workflow                                                                                                                                                                                                                                                                                                                              |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **(a) Iterative BDF re-attempt**        | Small deferred set (≤30), no SCC, mostly `deferred-build-fail` from isolated symbols                                      | Run BDF (see `BDF.md`) over the deferred set repeatedly until a whole pass yields 0 new landings. Bounded Rule-1 still applies — defer at the same thresholds.                                                                                                                                                                        |
| **(b) Per-family reconciliation**       | Deferred set has a clear feature-family structure (xtradb-log-archive, threadpool, userstat, ...) and the engineer agrees | For each family, write a single reconciliation commit that lands all related deferred work together — by cherry-picking the cluster as one operation and resolving conflicts in the combined state. Each family-commit builds. Engineer authorization required if any commit in the family requires file-path-scoped REFERENCE pulls. |
| **(c) Cluster-as-one**                  | Deferred set is one SCC of 50–200 commits; per-commit BDF demonstrably futile                                             | Single multi-commit cherry-pick of the SCC; resolve all conflicts in the combined state; apply BDF to the resulting tip (which now has everyone's symbols present). One big commit, audit trail preserved via the cherry-pick range.                                                                                                  |
| **(d) Explicit reconciliation commits** | Deferred set is small but heterogeneous; null-diff is the only goal, traceability isn't                                   | Add one or more named-file reconciliation commits at §5 directly. Engineer-authorized snap-to-reference is the typical mechanism here.                                                                                                                                                                                                |


**Step 4 — Record the choice.** Add a dedicated "Deferred-set management" section to `$REPORT_FILE` documenting:

- Inventory (counts by outcome).
- Cycle-check result (largest SCC size in deferred set).
- Chosen strategy and rationale.
- Per-strategy outcome: for (a), how many BDF re-attempts landed; for (b)/(c)/(d), which family/cluster/commit produced which residual reduction.

Do not silently slide into §5 with 100+ deferred commits unaccounted for. §5's "explicit hunk-level reconciliation commits" assumption breaks down quickly under that load — §4.5 makes the strategy choice explicit and reviewable.

### 5. Final Convergence

Entered when (a) the §4 pass loop drained `$WAITING_FILE` to empty, or (b) §4.5 handled the deferred set and `$WAITING_FILE` is now empty (or the engineer accepted explicit reconciliation commits in lieu of further per-commit landings).

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

**Never use snap-to-reference (whole-file `git checkout REFERENCE -- <path>`, or pulling a file wholesale from REFERENCE during Rule-1 fixes) unless the engineer explicitly approves it in the current conversation, naming the file or accepting the scope.** Snapping a file from REFERENCE pulls in EVERYTHING that file has — including symbols, fields, and call signatures introduced by *later* commits beyond the one you're trying to land. Those then-undefined symbols cascade into new "X was not declared" errors, often across multiple files; the Rule-1 fix is no longer minimal, and the cascade can grow without bound. Observed repeatedly: pulling `log0online.cc` from REFERENCE to satisfy a missing-symbol error introduced 4+ further undeclared symbols (`os_file_set_eof_at`, `innodb_file_bmp_key`, `SYNC_LOG_ONLINE`, `os_file_close_no_error_handling`) — each from a different deferred commit. Per-symbol Rule-1 (one decl, one enum value, one function body) is bounded; per-file snap is not.

#### No auto-take-incoming sweepers

Never write a script that walks the deferred set (or any multi-commit conflict batch) and silently applies "take the incoming side" across every conflict region in a file without per-region verification against `$REFERENCE`. This is forbidden even when "incoming" happens to match REFERENCE in most regions, because:

- Rule D requires *per-region* verification — REFERENCE may agree with incoming in 90% of regions and disagree in 10%. Auto-take-incoming silently flips the 10% to wrong content.
- A multi-file auto-resolver is functionally a multi-file snap with extra steps; it loses the per-hunk audit trail the skill demands.
- Operator preference recorded across runs: do not automate Rule D.

If you find yourself writing a loop that opens conflicted files and strips `<<<<<<< HEAD ... =======` blocks programmatically, **stop**. Resolve commits one at a time, verifying each region against REFERENCE by hand.

**Exception — test-data AA conflicts:** when both branches "added" the same file at `mysql-test/{r,t,suite,include}/*.{result,test,opt,inc,require}` and the conflict is a single region spanning the whole file, taking the incoming side is acceptable as a one-hunk choice (the file is pure test data, not code). Record as `clean,resolved-DU` or similar in `$EXEC`. This exception does NOT extend to source files or to multi-region conflicts.

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

#### Classify each build error BEFORE applying Rule 1

When the build fails after a cherry-pick, every reported error falls into one of two classes — and only the first is a Rule-1 candidate:

- **External missing symbol** — the failing commit references a decl/def/macro/struct-field/include that lives *elsewhere* in the codebase. Error shapes: `X was not declared in this scope`, `X.h: No such file or directory`, `struct X has no member named Y`, `no matching function for call to X(...)` where a different overload exists, `extern X` referenced but not defined. **Rule-1 candidate** — pull the minimal decl/def from a later in-range commit or from REFERENCE.
- **Internal patch bug** — the failing commit's *own* code is incoherent: it redefines its own function with a mismatched signature, calls `buf->append()` on a `char* buf` parameter it declared, defines a macro then uses it inconsistently, adds duplicate function definitions, references a local variable name that doesn't exist in its own scope. These are commit-authored bugs. **Rule-1 cannot fix them** — only a sibling follow-up commit (the patch's intended successor) can. **Defer immediately**; the commit will land cleanly once its sibling lands too. Don't waste cycles pulling symbols hoping the cascade stops.

Patch-internal macros that REFERENCE removed/replaced (e.g. `QUOTED_IDENTIFIER` defined and used at multiple sites by a single commit, where REFERENCE rewrote each site to use a different idiom) are a hybrid: the macro IS defined by the commit, but its definition didn't survive in REFERENCE. Treat as internal — defer.

#### Bounded Rule-1: hard threshold

Rule 1's "minimal" is a hard cap, not a vibe:

- If the external prereq set grows past **~5 distinct symbols**, the commit is signaling it's inside a strongly-connected dependency cluster. Stop applying Rule-1 and **defer** rather than continue chasing.
- If any error is **internal** (per the classification above), defer at the first internal error, not after.
- If a Rule-1 pull itself cascades into 3+ further undeclared symbols, stop and defer (this is the Rule-2 cascade gate — see below).

Observed thresholds in practice: a commit landable by Rule-1 typically needs 1–3 external prereqs. Commits needing 6+ are inside an SCC and won't land alone. Don't burn the conversation chasing them.

#### Prereq commit pattern (when ≥2 distinct symbols)

When applying Rule-1 fixes, write the prereq pulls as a **separate, traceable commit** before the failing commit, not as an `--amend` of the failing commit. Example sequence:

```
[BDF prereq] Add BTR_SEARCH_TREE enum + innobase_get_slow_log()
Import innodb_fake_changes.patch                             <- now picks/builds clean on top
```

Benefits over `--amend`:

- **Traceable**: prereq commit's diff shows exactly which decls/defs were pulled.
- **Revertable**: stands on its own if the deferred commit later fails for other reasons.
- **Audit-clean**: the failing commit's own diff stays unchanged.
- **Squash-later**: if the eventual sibling never lands, you can squash the prereq into the deferred commit; the inverse is much harder.

**Rule of thumb:** 1-symbol fix → `--amend` is fine; ≥2 distinct external symbols → separate prereq commit.

### Rule 2 — Defer cascading code

If the minimal fix in Rule 1 pulls in code that itself fails to build (cascading missing symbols), don't expand the fix indefinitely. Instead **defer** the cascading portion.

**Preferred form: delete the function/code block AND every caller.** When a function's body would have to be stubbed because all its dependencies are deferred, just remove the function definition entirely and remove every call site too — let the later commit that introduces the real dependency *also* re-introduce the function and its calls. The diff against REFERENCE stays smaller and there are no `#if 0` blocks or "no-op stub" comments cluttering the tree. Record the originating commit's SHA in the report's "Deferred code" section so the eventual restore is tracked.

**Avoid (anti-pattern):**

```c
init_log_online(void)
{
    /* TODO laurynas-style: body deferred — uses srv_track_changed_pages,
       log_online_read_init, srv_redo_log_follow_thread (changed-page-tracking
       subsystem; lands ~idx=147). Stubbed as no-op until then. */
}
```

**Prefer:** delete `init_log_online` entirely; delete `init_log_online();` from each caller too. The later changed-page-tracking commit will add the function definition *and* the calls in one self-contained landing.

**Stub-with-`#if 0` is only acceptable when** the function or call cannot be removed (e.g. it's referenced by a function-pointer table, a virtual override, or a platform macro expansion) and the calling structure must stay present. In that case:

- Replace the function body with `#if 0 … #endif` around the original lines plus a one-line `// TODO laurynas-style: restore at SHA <predicted-restore-SHA>` marker — keep the comment terse, no multi-paragraph explanation.
- Record the deferral in the report's "Deferred code" section.
- When the dependency-introducing commit later lands, restore the deferred code in the same commit (or in an immediate follow-up fix commit) and confirm it builds.

Deferrals must converge — every deferral entry needs a recorded "restored at SHA " by the time the run completes.

### Rule 3 — Squash related commits when build-coupled

If commit A introduces a header change and commit B immediately uses it, A may not build in isolation. When A's build failure can only be fixed by pulling in most of B, squash B into A. Record the squash in the report.

A squash is justified only when **most** of commit B is needed to make A build. If only a small slice of B is needed, prefer Rule 1 (minimal fix folded into A, B continues to apply later with the slice already in place — adjust B's cherry-pick accordingly).

### Known build-fail patterns

These shapes appear repeatedly and have known minimal fixes — recognize on sight, don't burn cycles re-deriving:

- `**abi_check` CMake error after a `plugin.h` change.** MySQL's `include/mysql/plugin_audit.h.pp` / `plugin_auth.h.pp` / `plugin_ftparser.h.pp` are the frozen-ABI fixtures that the build asserts against. When a Percona patch adds prototypes to `plugin.h`, the three `.pp` files must be regenerated. Symptom: `CMake Error at cmake/do_abi_check.cmake:NN (MESSAGE): ABI check found difference between .../plugin_audit.h.pp and .../abi_check.out`. Fix: after the build first fails, `cat $BUILD_DIR/abi_check.out` is what the build expects in each `.pp` file. Each `.pp` is generated from preprocessing its own `plugin_*.h` and they SHARE common content with one another — but the build only generates `abi_check.out` for one at a time. The simplest workflow: copy the appropriate diff lines from `abi_check.out` into each `.pp`'s end-of-file location matching the new content's anchor. If unsure, re-run the build between each `.pp` update — abi_check fails one file at a time so you can iterate.
- `**compile_time_assert` failure on `SQLCOM_END + N` when adding SQLCOM values.** The assert balances `com_status_vars` entries against the SQLCOM enum count; the `+N` constant tracks intentional-imbalance entries. Adding SQLCOM values without matching `com_status_vars` entries grows the imbalance — adjust `+N` accordingly (subtract the count of new SQLCOMs that did NOT get a com_status_vars entry).
- `**narrowing conversion of '-1'` in `MYSQL_SYSVAR_ULONG` / `MYSQL_SYSVAR_ULONGLONG`.** A sysvar registered with `def=-1` (signed `-1`) where the type is unsigned long fails in C++11 narrowing. Either change `-1` to `0` or `ULONG_MAX`, or check the patch's intent — sometimes the patch uses `~0L` which IS allowed.
- **Header in `.i` / `.ic` file ignored by BC regex.** The default BC detection regex covers `.h/.c/.cc/.cxx/.cpp/.hh/.hpp/.hxx/.cmake`. InnoDB uses `.i` and `.ic` as inline-include headers — these DO affect builds. Ensure the BC detection includes `.i` and `.ic` in the regex; otherwise a "BC=0" commit can silently break the build via header-only changes (e.g. enabling `UNIV_LOG_ARCHIVE`).

## Stop Conditions

Stop and ask the engineer when:

- `$OUTPUT_BASE` does not build with the configured toolchain **AND §1.5 Base-BDF is futile** (per the BDF-futile criteria in §1.5). A failing base build by itself is no longer a stop condition — try Base-BDF first.
- A commit's conflict resolution requires whole-file replacement from `$REFERENCE`.
- The minimal build fix would require pulling more than ~30 lines from a later commit (cascading fix territory — Rule 2 may not isolate cleanly).
- A deferral can't be restored at the input commit you predicted, and no obvious successor commit will restore it.
- The landing-pass-5 residual after the §4 pass loop terminates still contains commits the engineer expected to apply.
- Final convergence after the pass loop / §4.5 still has a residual to `$REFERENCE` that no targeted reconciliation commit can close without whole-tree snap.
- **You realize per-commit buildability is structurally hard** for some portion of the range (e.g., end-fix-style tip-fix with many cross-commit hunk dependencies, large pending-set SCC, or the run scale exceeds the session budget). **Stop and surface options** — do NOT silently fall back to chronological-with-tip-only-build. Acceptable options to propose: (a) extend the session and commit to the per-commit BDF work; (b) split the input range so the difficult segment is handled separately; (c) deliver a partial-coverage branch with explicit per-commit-build attestation for the covered subset and an explicitly-marked unbuildable tail. Tip-only buildable as the deliverable for the whole range is **never** acceptable.

When stopping, return `$OUTPUT_NAME` to the last known-buildable SHA, document the blocker, and propose 2–3 concrete options for the engineer.

## Report Requirements

Write `$REPORT_FILE` (markdown). Sections:

### Header

- `$INPUT_RANGE`, `$OUTPUT_RANGE`, `$REFERENCE`
- Build command used, `$BUILD_DIR`
- Run start timestamp

### Scan output

Table of every commit in `$INPUT_RANGE`:


| Idx | SHA | Subject | Category | BUILD_CHANGING | First landing pass | Paths summary |
| --- | --- | ------- | -------- | -------------- | ----------- | ------------- |


### Pass execution

Reference: `$WAITING_FILE.passN` snapshots are the source of truth for what each pass attempted. This section records what actually happened against each one.

For each pass 1..K (until success or §4.5 stall):

- Waiting set size at pass start, at pass end. Delta = landings this pass (must be > 0 except on the stall pass).
- Per-landing-pass breakdown for this pass: applied / skipped-empty / category-removed / rolled-back-build / left-for-next-pass
- For each applied commit: `pass`, `landing_pass`, `land_pos`, original SHA → new SHA, conflict files (if any) and the REFERENCE region cited, build log path, PASS/FAIL
- For each skipped commit (within this pass): `pass`, `land_pos`, original SHA, subject, reason (empty after resolution / category removed from REFERENCE / explicit engineer skip)
- For each commit rolled back to the waiting set: `pass`, `land_pos`, original SHA, why it failed (cherry-pick conflict unresolvable now / build failed past Bounded Rule-1), expected pass for retry
- For each commit whose actual shape did not match its assigned pass: `land_pos`, `landing_pass`, what this pass's trial sweep missed, and that it was left for the next pass
- The **pass-end buildable SHA** (record this — it is the recovery point for §3.7 if drift is detected later)

### Pivots (if §3.7 fired)

For each pivot: which §3.6 red flag fired, `pass` and `land_pos` where the run was when detected, SHA reset to, count of commits re-planned, brief note on what changed about the waiting set after re-planning. If no pivots occurred, record "no pivots".

### Deferred code

Every Rule-2 deferral: originating SHA, symbol/region deferred, predicted restore SHA, actual restore SHA, restore-build log.

### Squashes

Every Rule-3 squash: SHAs squashed together, resulting SHA, justification.

### Dep graph & pair detection

Path to `hunks.tsv` and `overlaps.tsv`. List of pre-detected pairs with their edge-type signals (subject / author+timestamp / tag / hunk-overlap).

### Patch-ID coverage (§2.6)

- Paths: `.ps-port-grouped/input-patch-ids.tsv`, `.ps-port-grouped/head-patch-ids.tsv`, `.ps-port-grouped/predicted-empty.tsv`.
- Pass-1 input-range row count vs predicted-empty row count → percentage of input range removed up front by patch-id intersection.
- For each predicted-empty source SHA: subject, the head SHA already carrying the same patch-id, and the pass at which the prediction first fired (pass 1 from `$OUTPUT_BASE` ancestry; later passes when a sibling landing extended HEAD).
- Re-intersection counts per pass: number of additional source SHAs that became predicted-empty after pass `N` landings extended `head-patch-ids.tsv`.
- Any unpredicted empties discovered at §4 runtime: source SHA, pass, the post-resolution diff state that revealed the empty (typically rename, whitespace-only reformat, or fold-equivalent — listed as the patch-id intersection's known blind spots in §2.6).

### Final convergence

- `git diff $OUTPUT_NAME $REFERENCE` size before reconciliation
- Each reconciliation commit's SHA and the paths/hunks it touched
- Final diff confirmation (null) and final build log

## Common Mistakes


| Mistake                                                                                                                  | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Treating chronological order as the default                                                                              | Pass-ascending landing overrides chronology. Run the trial sweep and write `$WAITING_FILE` before cherry-picking the first commit of each pass.                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Processing commits in `git rev-list --reverse` order and assigning passes post-hoc                                       | This is chronological with cosmetic scheduling. The trial + lock sweeps (§3 / start of each pass) must finish for the **entire** waiting set before any real cherry-pick. Symptom: you get stuck on a landing-pass-4/5 commit at a mid-pass index instead of skipping past it and letting the next pass re-trial it.                                                                                                                                                                                                                                                           |
| Cherry-picking before `$WAITING_FILE` exists on disk                                                                     | The waiting file is the per-pass execution contract. No `git cherry-pick` on `$OUTPUT_NAME` before the trial sweep writes the file and §3.5 (pass 1) or the pass-start sanity checks (pass 2+) verify it. If you have already drifted into this state, pivot per §3.7 rather than continuing.                                                                                                                                                                                                                                                                                |
| Reusing a stale `$WAITING_FILE` across passes without re-trialing                                                        | `landing_pass` values are pass-specific. Pass 2's trial sweep against the new tip will produce different numbers; reusing pass 1's file is functionally identical to a locked plan and re-introduces the failure mode this rewrite was designed to remove. Rewrite `$WAITING_FILE` at every pass start.                                                                                                                                                                                                                                                                         |
| Waiting file exists but `rev_list_pos` is monotonically increasing along `land_pos`                                      | You assigned passes on paper but ordered chronologically. The trial sweep didn't actually grade conflict shape. Re-do the sweep with real `git cherry-pick --no-commit` trials on a throwaway worktree against the current tip.                                                                                                                                                                                                                                                                                                                                               |
| Picking the next commit "from memory" or by chronological index instead of by reading the next `$WAITING_FILE` row       | The waiting file is the source of truth for what comes next in this pass. Read it, pick the lowest un-attempted `land_pos`.                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Interleaving trial-sweep chunks with pass-1 landings inside one pass                                                     | The "trial 50 → land pass 1 from those 50 → trial next 50" pattern degenerates into chronological order. Complete the trial sweep for the whole pass's waiting set first.                                                                                                                                                                                                                                                                                                                                                                                                     |
| Running another pass after one yielded 0 landings                                                                        | A 0-landing pass is the stall signal — go to §4.5, do not start another pass with the same waiting set hoping for a different result.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Pushing through a hard commit because you've already started it                                                          | If a commit's actual conflict shape reveals it belongs to landing pass 4/5 when this pass's sweep assigned it to pass 1/2, abort it, leave it in `$WAITING_FILE`, and continue with the next pass-1 row. The next pass's trial sweep will re-assign it cleanly. Sunk cost is not a reason to land a hard commit early.                                                                                                                                                                                                                                                        |
| Skipping the `$OUTPUT_BASE` build                                                                                        | If the base doesn't build, no later state on `$OUTPUT_NAME` builds either. Always verify first; if it fails, run §1.5 Base-BDF.                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Reassigning a commit inside a single pass based on hope                                                                  | Do not move rows between pass bands while executing a pass. Leave failed/mismatched rows in `$WAITING_FILE`; the next pass's fresh trial sweep produces the new `landing_pass`.                                                                                                                                                                                                                                                                                                                                                                                                |
| Letting a build failure stay on `$OUTPUT_NAME`                                                                           | Every commit must build. Amend or squash the fix into the failing commit before moving on, or roll the commit back into `$WAITING_FILE` for the next pass.                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **Delivering tip-only-buildable as a fallback when per-commit BDF is hard**                                              | Per-commit buildability is a hard requirement, not a goal. If the work is structurally difficult (end-fix style tip-fix, many cross-commit hunk dependencies, large pending SCC), **stop and surface options to the engineer** (extend session / split range / partial-coverage with explicit attestation). A null-diff-but-only-tip-builds branch is a failed run — it is functionally `ps-replay+make-buildable` output, and the wrong tool was chosen. The exec log recording `clean` for every commit but only one `build PASS` entry is the fingerprint of this mistake. |
| Skipping per-commit builds because the trial sweep had 0 conflicts                                                       | "Clean cherry-pick" ≠ "buildable commit". A commit can apply cleanly and still fail to build because it uses symbols later commits define, or because the cumulative state has pre-existing errors the commit doesn't fix. Per-commit builds verify what the trial sweep cannot. The only build a clean trial-sweep authorizes you to skip is the per-commit-build for BC=0 commits in pass 1 (and even those need a pass-1 boundary build).                                                                                                                                  |
| Whole-file `git checkout REFERENCE -- path` to "fix the diff" at the end                                                 | Forbidden. Use targeted hunk-level reconciliation commits, or ask the engineer for explicit authorization.                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Squashing two commits because they share a category                                                                      | Squashes are justified by build coupling, not category. Don't merge related-feature commits unless one literally cannot build without the other.                                                                                                                                                                                                                                                                                                                                                                                                                              |
| Deferring code with no restore plan                                                                                      | Every deferral must name the commit that will restore it. Track restoration in the report.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Skipping the dep graph and discovering pairs through build failures                                                      | The graph (§2.5) costs <10 min and surfaces every split-pair before execution. Discovering them via build failures wastes hours per pair.                                                                                                                                                                                                                                                                                                                                                                                                                                     |


## Quick Reference


| Step                      | Command                                                                                                                                           |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| List source range         | `git rev-list --reverse $INPUT_RANGE`                                                                                                             |
| Source-SHA paths          | `git diff-tree --no-commit-id --name-only -r <sha>`                                                                                               |
| BUILD_CHANGING test       | grep paths against `(?i)\.(h|c|cc|cxx|cpp|hh|hpp|hxx|cmake)$`                                                                                     |
| Category-removed test     | `git cat-file -e $REFERENCE:<path>` per path                                                                                                      |
| Inspect REFERENCE region  | `git show $REFERENCE:<path>` (inspection only)                                                                                                    |
| Search REFERENCE          | `git grep -n '<symbol>' $REFERENCE -- '<dir>/'`                                                                                                   |
| Throwaway trial pick          | `git cherry-pick --no-commit <sha>; git diff --name-only --diff-filter=U; git cherry-pick --abort`                                                                                                                                |
| Waiting file row count check  | `expected=$(( $(git rev-list --count $INPUT_RANGE) - $(git rev-list --count $OUTPUT_BASE..$OUTPUT_NAME) )); test "$(tail -n +2 "$WAITING_FILE" | wc -l)" -eq "$expected"`                                                          |
| Waiting file sort check       | `awk -F'\t' 'NR>1 {k=$2"."sprintf("%06d",$3); if (k<p) {print "OOO "NR; exit 1} p=k}' "$WAITING_FILE"`                                                                                                                            |
| Pass snapshot                 | `cp "$WAITING_FILE" "$WAITING_FILE.pass${PASS_NUM}"` at start of every pass                                                                                                                                                       |
| Drift detector                | `git log --reverse --format=%H $OUTPUT_BASE..$OUTPUT_NAME` — landed SHAs should match the union of `orig_sha` columns across `$WAITING_FILE.pass*` snapshots, in pass-then-landing-pass order                                      |
| Next commit to pick this pass | `tail -n +2 "$WAITING_FILE" | awk -v n=<next_land_pos> -F'\t' '$1==n'`                                                                                                                                                            |
| Final null-diff check         | `git diff $OUTPUT_NAME $REFERENCE`                                                                                                                                                                                                |



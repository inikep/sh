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

This skill is a sibling of `ps-replay+make-buildable`. Choose this one when:

- A `$REFERENCE` branch already exists with the desired final tree.
- You want a buildable-at-every-commit history.
- The source range has no `=== MARKER:` boundary, or the boundary's position is wrong for your run.
- Chronological order would land hard source-code conflicts before the easy fixes that make them tractable.

## Inputs

- `$INPUT_RANGE` — formatted as `$INPUT_BASE..$INPUT_TIP` (e.g. `mysql-5.6.26..ps-5.6.26`). Derive both endpoints from this.
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
```

Build at `$OUTPUT_BASE` **before any cherry-pick**. If `$OUTPUT_BASE` itself doesn't build with the configured toolchain, **stop and ask** — the run cannot start.

Record `$OUTPUT_BASE`'s build PASS in `$REPORT_FILE`.

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

The tentative pass produces a working dataset; throwaway operations must not pollute `$OUTPUT_NAME`.

### 4. Execute Groups 1 → 5

For each group, in order:

```
for each commit in group:
    git cherry-pick <sha>
    resolve conflicts (rules below)
    if cherry-pick is empty after resolution: git cherry-pick --skip; continue
    git cherry-pick --continue (or commit naturally on clean apply)
    BUILD the project
    if build fails: apply build-conflict rules (below)
    record outcome in $REPORT_FILE
```

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

**Red flags that signal you're about to fall into the HEAD-empty trap:**

- The conflict region is between an empty HEAD side and an incoming side that adds new lines.
- You're tempted to "just take HEAD because the upstream removed this" without grepping REFERENCE for the affected symbol.
- A hunk-level resolver script picked a side automatically and you didn't read the REFERENCE excerpt at that path.

In all three cases: stop, run `git show $REFERENCE:<path>` and the symbol search, and apply the decision rule above.

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

### Final convergence

- `git diff $OUTPUT_NAME $REFERENCE` size before reconciliation
- Each reconciliation commit's SHA and the paths/hunks it touched
- Final diff confirmation (null) and final build log

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Treating chronological order as the default | Groups override chronology. Scan and assign before cherry-picking the first commit. |
| Skipping the `$OUTPUT_BASE` build | If the base doesn't build, no later state on `$OUTPUT_NAME` builds either. Always verify first. |
| Promoting a commit between groups based on hope | Demotion (easier → harder) is fine. Promotion (harder → easier) requires re-running the tentative pass. |
| Cherry-picking before group assignment is locked | The trial pass uses throwaway worktree state. The real pass uses the locked dataset only. |
| Letting a build failure stay on `$OUTPUT_NAME` | Every commit must build. Amend or squash the fix into the failing commit before moving on. |
| Whole-file `git checkout REFERENCE -- path` to "fix the diff" at the end | Forbidden. Use targeted hunk-level reconciliation commits, or ask the engineer for explicit authorization. |
| Squashing two commits because they share a category | Squashes are justified by build coupling, not category. Don't merge related-feature commits unless one literally cannot build without the other. |
| Deferring code with no restore plan | Every deferral must name the commit that will restore it. Track restoration in the report. |

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

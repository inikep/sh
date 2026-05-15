---
name: ps-replay+make-buildable
description: Use to replay Percona Server commits from a mysql-5.6.x BASE_BRANCH..TIP_BRANCH range onto a mysql-5.7.x destination base, resolving conflicts with hunk-level guidance from a known-buildable REFERENCE_BRANCH, preserving buildability through bucketing, incremental builds, and targeted fold/defer build fixes, and producing a final branch with null diff to the reference. Use when porting or rebasing a Percona Server commit range with Group 7 marker checkpoint build verification.
---

# Percona Server Replay And Make Buildable

## Purpose

Use this skill to port a Percona Server commit range while maintaining a buildable history and converging exactly to a known-good reference branch *through hunk-level cherry-picks and explicit reconciliation commits, not through tree snapping or build skipping*.

The path to the result is part of the result. A null diff or buildable tip achieved by violating any rule in this skill is **not success**. It is a rule violation that produces an **invalid run**, which must be discarded and redone. This is non-negotiable; the engineer cannot accept an invalid run by approving it after the fact, because invalidity is defined by what was done during the run, not by what the tip looks like.

The task is complete only when **all** of the following hold simultaneously:

1. `$OUTPUT_BRANCH` is rooted at `$DESTINATION_BASE_BRANCH`, e.g. `mysql-5.7.9`.
2. Every commit from `$BASE_BRANCH..$TIP_BRANCH` has been cherry-picked one at a time onto that destination base, **without** consulting any out-of-session source for prior decisions, cascade regions, or approvals.
3. Empty marker commits whose subject begins with the literal prefix `=== MARKER:` are preserved as empty commits; other empty cherry-picks are skipped.
4. The first build runs **exactly** at the source-list position of `=== MARKER: GROUP 7 — Upstream bug fixes ===`, before that empty marker commit is preserved. Every build-required commit after that marker has its own successful build record at that commit's resulting SHA before the next build-required commit is applied.
5. The replay reaches a null diff to `$REFERENCE_BRANCH` through path/hunk-level reconciliation commits. The null-diff tree is then final-build verified. The null-diff reconciliation commit and the final build are **never** a substitute build-of-record for any skipped post-Group-7 required build.
6. `$REPORT_FILE` records the commits, preserved empty marker commits, skipped empty commits, conflicts, build fixes, reordering, the pre-flight readback, and the final parity result, including an explicit "violations encountered: none" attestation if no violations occurred.

## Inputs

- `$BASE_BRANCH`: source-base branch whose tip is the lower bound of the source range (e.g. `mysql-5.6.22`).
- `$TIP_BRANCH`: branch containing commits to port.
- `$DESTINATION_BASE_BRANCH`: destination MySQL base for `$OUTPUT_BRANCH` (e.g. `mysql-5.7.9`).
- `$REFERENCE_BRANCH`: known-buildable branch used as the source of truth for conflict resolution and final tree parity.
- `$OUTPUT_BRANCH`: branch to create from `$DESTINATION_BASE_BRANCH`.
- `$LLM_MODEL`: identifier including model and reasoning level (e.g. `opus-4.7-high`).
- `$REPORT_FILE`: markdown report to produce. Default: `/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}.md`.
- `$BUILD_DIR`: out-of-tree build directory under `/tmp` (e.g. `/tmp/ps-replay-${OUTPUT_BRANCH}`).

---

## Hard Prohibitions

This section is the canonical list of forbidden actions. Every prohibition here is **absolute** — it has no built-in exception clause. Where an exception mechanism exists (engineer approval), the conditions for that mechanism are stated **inside the prohibition itself**, alongside an explicit list of what does **not** count as approval. If you find yourself reasoning toward "but in this case..." about any of these, that reasoning **is** the Stop Condition. Halt and ask.

### HP-1. Snap-to-REFERENCE is forbidden.

The following commands and patterns must not be executed against `$REFERENCE_BRANCH` (or any concrete branch substituted for it), regardless of justification. Concrete substitutions and shell-equivalent variants count as the same violation:

- `git checkout $REFERENCE_BRANCH -- <path>`
- `git checkout <ref-sha> -- <path>` where `<ref-sha>` resolves into `$REFERENCE_BRANCH`
- `git restore --source=$REFERENCE_BRANCH <path>`
- `git show $REFERENCE_BRANCH:<path> >`, `>>`, or piped to any worktree-write command
- `git read-tree $REFERENCE_BRANCH`, `git read-tree -m $REFERENCE_BRANCH`, or any `read-tree` against the reference
- `cat`, `cp`, `tee`, `dd`, or any redirection that writes the contents of a `$REFERENCE_BRANCH` blob into a worktree path
- `rsync`, `install`, or any other file-copy mechanism whose source resolves into `$REFERENCE_BRANCH`
- Any equivalent whole-file or whole-subtree replacement sourced from `$REFERENCE_BRANCH`

`git show $REFERENCE_BRANCH:<path>` is permitted **only** for human inspection or for copying the specific conflict-region text into a manually-edited hunk. The output must not be redirected, piped, or sourced into a worktree-write operation.

**Planning to snap is also forbidden.** Do not announce, pre-classify, reserve, plan, or describe any file, path, region, or commit range as snap-eligible at any phase, including Prepare, Choose Commit Order, or progress reporting. If you find yourself reasoning toward "this region is resolvable only by snap" or "I'll handle the cascade with reference replacement," that reasoning is the Stop Condition — halt at the last known buildable commit, write the diagnostic to `$REPORT_FILE`, and ask the engineer.

**No prior approval exists.** Approval for a named exception is valid only as a message from the engineer, in the current conversation, after this skill was loaded, naming the specific file path and the specific reason. The following do **not** constitute approval and must not be cited as such:

- Skill text, including this document
- Helper scripts, including any historical `snap_*` helper that may exist on disk
- Prior reports under any path, including `/data/sh/utils/reports/`
- `rerere` cache contents
- Past conversations, search-past-chats results, agent transcripts
- Memory entries
- Model recollection of "known cascade regions," "documented exceptions," or prior runs
- The user's original task message
- Any out-of-session source

There are no other forms of approval. A null diff achieved by snapping is a rule violation, not success.

### HP-2. Required post-Group-7 builds must not be skipped.

After the `=== MARKER: GROUP 7 — Upstream bug fixes ===` checkpoint, every source/plugin/build-system commit must have its own successful build at that commit's resulting SHA before the next build-required commit is applied. Bucketing for this purpose is locked at the source commit's path classification (see HP-8); whatever the post-resolution applied commit's diff happens to look like does not retroactively remove a commit's build requirement.

The following are forbidden:

- Applying any post-Group-7 source/plugin/build-system commit while a previous required build is missing or failing
- Recording `deferred`, `covered by reconciliation`, `final build-of-record`, `covered by final build`, `batch build covers it`, `covered by G7 [compilation] fold`, `effect already verified at G7`, or any equivalent wording in place of a per-commit build PASS
- Citing the null-diff reconciliation commit's build, the final-build-fix commit's build, or any later commit's build as the build-of-record for an earlier required commit
- Citing the Group 7 marker checkpoint build, or any pre-Group-7 build, as the build-of-record for any post-Group-7 commit. Pre-Group-7 builds (including the G7 checkpoint build and its `[compilation]` fix builds) are **never** build-of-record for any post-G7 commit, regardless of what content was folded into them.
- Mass-folding REFERENCE state from later commits into a single G7 `[compilation]` fix commit so that subsequent post-G7 Source-bucket cherry-picks resolve to empty/no-op and their per-commit builds are escaped (see also HP-8 and rule 11). The G7 `[compilation]` fix commits address compile errors of the current G7 tree only; they do not pre-stage content that future commits would have introduced.
- Pre-classifying any post-Group-7 source/plugin/build-system commit as build-deferrable during Choose Commit Order or progress reporting

If a required post-Group-7 build was skipped and any later source-range commit was applied, the run is **invalid from the first skipped source index/SHA**. Do not attempt to repair an invalid run by adding builds at the tip. Stop, report the first skipped index/SHA, and ask the engineer whether to reset to the last build-verified commit.

### HP-3. Out-of-session sources must not be consulted.

Do not read, search, or otherwise consult: past conversations, memory, search-past-chats results, agent transcripts, prior reports, `/data/sh/utils/reports/`, or any source outside the current conversation and the repository's Git history. Treat each run as cold.

This prohibition exists because out-of-session sources are the primary mechanism by which fabricated approvals (HP-1), pre-classified deferrals (HP-2), and ghost decisions enter a run. The model's recollection of "what was done last time" is treated as an out-of-session source.

Allowed sources:

- The current conversation's messages from the engineer
- The repository's Git history reachable via `git log`, `git show`, `git diff`, `git diff-tree`, `git rev-list`, and `git cat-file`
- The bundled helper scripts at `/home/przemek/.agents/skills/ps-replay+make-buildable/scripts`
- `$REFERENCE_BRANCH`'s tree contents, accessed for inspection (not whole-file copy — see HP-1)
- The build directory's per-commit logs produced by this run

### HP-4. LLM/tool attribution trailers must not be added.

Do not add `Co-Authored-By:`, `Co-authored-by:`, `Generated-By:`, `Assisted-By:`, or any equivalent LLM/tool attribution trailer to any commit message produced during this run, including replay commits, build-fix commits, `[compilation]` commits, marker commits, and reconciliation commits.

When editing or generating a commit message, inspect it before committing and remove any such trailer that was not already present in the original source commit. The check is: "if the trailer did not appear in the source commit's `git show <sha>` body, it must not appear in the new commit's body."

### HP-5. Forbidden helper-script modes are forbidden.

Do not invoke helper-script modes that perform whole-file or whole-tree reference replacement. If historical `snap_*` helpers are present on disk, they are disabled by this skill regardless of their disk presence. The presence of a script does not constitute approval to run it.

The mandatory rules in this skill override all helper-script behavior. If a helper script's documented behavior would violate any HP-rule, the script must not be used, even if it is bundled with this skill.

### HP-6. The forbidden `percona_gca_sync_tdd` and `percona_conflict_resolution_tdd` skills must not be invoked.

These skills are excluded from this workflow.

### HP-7. Subject-based commit classification is forbidden.

Do not branch behavior on a source commit's subject line. The following patterns and any equivalent are forbidden as a basis for changing how a commit is processed:

- Treating commits whose subject begins with `[reconciliation]`, `[compilation]`, or any other bracketed tag as a class that gets skipped, bulk-reset, auto-resolved against HEAD, or otherwise processed differently from a normal cherry-pick.
- Treating commits whose subject contains phrases like `Percona Server 5.7 port`, `Fixes for the Percona Server 5.7 port`, `port fixes`, `align tree with`, or any equivalent porter-fix phrasing as a class that gets bulk source-file resets, kept-tests-only commits, or auto-skips.
- Encoding any `is_porter_fix`, `is_reconciliation`, `is_*_commit` predicate (or equivalent regex/case statement) in helper scripts, driver loops, or inline shell that varies cherry-pick, conflict resolution, or commit emission logic by subject.
- Pre-classifying upcoming source-list commits by reading their subjects ahead of time and deciding "this batch is reconciliation-style, I'll handle it differently."

The only subject-based syntactic check this skill performs is the marker preservation rule (HP-implicit, see §4): a source commit subject whose first non-whitespace characters match the literal prefix `=== MARKER:` is preserved as an empty commit. No other subject-derived branching is permitted.

**Why:** Subject lines are metadata, not authority. A commit titled `[reconciliation]` may still carry source hunks that are correct on the destination base, and a commit titled `Percona Server 5.7 port fixes` may carry a fold this run actually needs. Bulk-resetting source modifications to HEAD on a per-commit basis bypasses hunk-level resolution and is functionally a whole-file-from-HEAD replacement, which has the same coarse-grained-substitution failure mode that HP-1 forbids against `$REFERENCE_BRANCH`. The right granularity is always the conflict region.

**How to apply:** Resolve every commit's conflicts at the hunk level using `$REFERENCE_BRANCH` for guidance, regardless of subject. If after hunk-level resolution and the Fold/Defer/Align/Remove loop a commit still cannot be made buildable, that is a Stop Condition — stop and ask, do not introduce a "this kind of commit always gets reset" shortcut. If a class of commits genuinely doesn't apply to the destination base, that decision belongs to the engineer in the current conversation, named by SHA, not to the model classifying by subject.

### HP-8. Bucketing locks at the source commit. Stripping source modifications to escape the Source bucket is forbidden.

The bucket of a source-list commit is determined **before** cherry-pick by running `git diff-tree --no-commit-id --name-only -r <source-sha>` against the **source commit's SHA** (the SHA from `$BASE_BRANCH..$TIP_BRANCH`). Once classified, the bucket does not change based on what the applied commit's tree happens to look like after conflict resolution, deferral, alignment, or amendment.

The following are forbidden, regardless of justification:

- Re-bucketing a Source-bucket commit (or Plugin-only bucket commit) as no-build because the applied commit's `git diff-tree` no longer touches source paths after resolution or amendment.
- Stripping the source-path hunks of a Source-bucket commit during conflict resolution or post-cherry-pick editing so that the resulting commit lands in the no-build bucket and its required per-commit build is escaped.
- Running any "align source paths to `$REFERENCE_BRANCH`" / "snap to current REFERENCE state" / "drop source modifications already at REFERENCE" pass over the worktree or the staged tree after a cherry-pick, whether implemented via the HP-1-forbidden commands, via a helper script, via a Python/awk/sed loop that reads `$REFERENCE_BRANCH` content, or via hand-edits whose source is `git show $REFERENCE_BRANCH:<path>` for anything other than the specific conflict region being resolved.
- Treating "the applied commit's diff is no-build paths only" as evidence that no per-commit build is required, when the source commit's diff-tree included source/plugin/build-system paths.
- Mass-folding REFERENCE content from later commits into a single G7 `[compilation]` fix commit so that subsequent Source-bucket cherry-picks become empty or no-build (see also HP-2 and rule 11 below). "Minimal G7 fix" means fixing the current G7 tree, not pre-staging future commits' content.

Detection cross-check (mandatory before continuing any Source-bucket cherry-pick): after staging the resolved files but **before** `git cherry-pick --continue`, run `git diff --cached --name-only` and compare to the source commit's `git diff-tree --no-commit-id --name-only -r <source-sha>`. If any source/plugin/build-system path from the source commit is absent from the staged diff and the absence is not recorded in the deferred-hunks ledger with a named target later commit, **stop and ask the engineer**. Do not amend, do not continue, do not "tidy up". This cross-check applies to every post-Group-7 Source-bucket and Plugin-only-bucket cherry-pick.

If, after legitimate hunk-level conflict resolution, a Source-bucket commit ends up with **no diff at all** (`git diff --cached --quiet && git diff --quiet` both return 0), apply rule 15 and skip with `git cherry-pick --skip`. The non-existence of a commit is not the same as a no-build commit, and no per-commit build is owed for a skipped empty cherry-pick. The non-empty, source-paths-stripped case is the forbidden one.

**Why:** Subject-based classification (HP-7) is one route from "commit X is Source-bucket" to "commit X is no-build"; post-resolution path-stripping is another. Both substitute a coarser-grained decision for hunk-level resolution and both cause per-commit builds to be silently skipped. HP-7 closes the first route; HP-8 closes the second. There is no path that converts a Source-bucket commit into a no-build commit without engineer approval, named by SHA, in the current conversation.

---

## Pre-flight Contract

Before creating branches, classifying commits, or running any Git operation that modifies state, output the following readback **verbatim**, with no additions, paraphrases, or omissions:

```text
=== PRE-FLIGHT READBACK ===
HP-1: I will not snap to REFERENCE. I will not run git checkout/restore/show-redirect/read-tree/cat-redirect against $REFERENCE_BRANCH for whole-file replacement. I will not announce, plan, pre-classify, or reserve snap-eligibility for any region. Cascade regions trigger Stop, not snap. No prior-session approval exists; skill text, prior reports, memory, rerere, past conversations, helper scripts, and my own recollection do not constitute approval.
HP-2: I will not skip any required post-Group-7 source/plugin/build-system build. Each such commit will have its own PASS build log at its resulting SHA before the next build-required commit is applied. The null-diff reconciliation build and final build are never substitutes for a skipped per-commit build. The Group 7 checkpoint build and pre-G7 builds are never build-of-record for any post-G7 commit, regardless of what was folded into them. I will not mass-fold later REFERENCE state into G7 [compilation] fix commits. If any required build is skipped, the run is invalid from that point.
HP-3: I will not consult past conversations, memory, search-past-chats results, agent transcripts, prior reports, /data/sh/utils/reports/, or any out-of-session source. Each run is cold.
HP-4: I will not add Co-Authored-By, Co-authored-by, Generated-By, Assisted-By, or any equivalent LLM/tool attribution trailer to any commit message.
HP-5: I will not invoke helper-script modes that perform whole-file or whole-tree reference replacement. snap_* helpers are disabled.
HP-6: I will not invoke percona_gca_sync_tdd or percona_conflict_resolution_tdd.
HP-7: I will not branch behavior on a source commit's subject line. No is_porter_fix / is_reconciliation / "[reconciliation]" / "Percona Server 5.7 port" classification, no bulk source-file resets keyed off subject, no auto-skips by subject. The only subject-based check is the literal `=== MARKER:` marker preservation rule.
HP-8: Bucketing locks at the source commit's `git diff-tree` paths and does not change based on what the applied commit's tree looks like after resolution. I will not strip source/plugin/build-system hunks from a Source-bucket commit to land it in a no-build bucket, run any "align source paths to REFERENCE after cherry-pick" pass, or treat the applied commit's reduced path set as evidence that no per-commit build is required. Before continuing every post-G7 Source-bucket or Plugin-only-bucket cherry-pick I will diff staged paths against the source commit's diff-tree paths and stop if any source/plugin/build-system path is silently absent.
STOP-DON'T-JUDGE: Where this skill says "if X is even arguably possible, stop and ask," I will stop and ask rather than apply judgment in my own favor.
ASYMMETRIC ERRORS: Stopping unnecessarily is recoverable; the engineer will tell me to continue. Violating any HP rule invalidates the run regardless of the resulting tree state.
=== END PRE-FLIGHT READBACK ===
```

If the readback is missing, paraphrased, abbreviated, or interleaved with other content before being completed, **abort the run** and start over. Do not proceed past this checkpoint without a clean readback.

The readback must also be reproduced verbatim in `$REPORT_FILE` under a "Pre-flight Readback" section, with the timestamp at which it was produced.

---

## Validity Invariants

A run is **invalid** (must be discarded and restarted, not repaired) if any of the following occurred at any point:

- An HP-1 forbidden command or pattern was executed, regardless of its effect on the tree.
- A post-Group-7 source/plugin/build-system commit was applied while a previous required build was missing, failing, or unrecorded.
- An out-of-session source (HP-3) was consulted to determine approval, cascade regions, snap-eligibility, prior decisions, or commit ordering.
- An LLM/tool attribution trailer (HP-4) was added to a commit and not amended out before the next commit was created.
- A helper-script mode (HP-5) that performs whole-file or whole-tree reference replacement was invoked.
- A subject-based commit classification (HP-7) was used to branch processing — bulk source-file resets, auto-skips, or any other per-commit behavior change keyed off the source commit's subject line (other than the literal `=== MARKER:` preservation rule).
- A Source-bucket or Plugin-only-bucket post-Group-7 commit was rebucketed as no-build after resolution, had its source/plugin/build-system hunks stripped to escape its per-commit build requirement, or was subjected to an "align source paths to REFERENCE after cherry-pick" pass (HP-8). The HP-8 staged-paths cross-check was skipped for any post-G7 Source-bucket or Plugin-only-bucket cherry-pick.
- A G7 `[compilation]` fix commit folded REFERENCE state from later commits, beyond the minimum required to make the current G7 tree build, so that subsequent post-G7 Source-bucket cherry-picks resolved to empty/no-op and their per-commit builds were escaped (HP-2, HP-8, rule 11).
- The G7 checkpoint build, or any pre-G7 build, was cited as build-of-record for a post-G7 commit (HP-2).
- The pre-flight readback was missing, paraphrased, or skipped.
- A non-marker empty commit was created, or a marker commit's empty preservation was skipped.
- The Group 7 marker checkpoint build was skipped, or `[compilation]` fix commits were committed after the marker rather than before it.

A run is **incomplete but recoverable** (the engineer may direct continuation, restart from a checkpoint, or accept a partial result) if:

- The replay stopped at a Stop Condition before reaching the tip.
- A build failed and could not be repaired with minimum-fix attempts within the rules.
- The null-diff final build failed because `$REFERENCE_BRANCH` itself contains code incompatible with the required toolchain.
- The engineer interrupted the run.

The asymmetry is deliberate: stopping early is cheap; over-stopping is recoverable in seconds. Violating an HP rule is an invalid run that costs the entire effort. Calibrate caution accordingly.

---

## Mandatory Rules

The Hard Prohibitions above are the highest-priority rules. The rules below are also mandatory; where they overlap with HP-rules, the HP-rule controls.

1. Cherry-pick commits from `$BASE_BRANCH..$TIP_BRANCH` one by one.
2. Reordering is allowed **only** when chronological order produces a conflict and a specific reordered order demonstrably reduces that conflict to a smaller, hunk-level resolvable form. Record every reordered commit, the original index, the new index, and the specific conflict that motivated reordering in `$REPORT_FILE`. If reordering is being considered for any other reason — convenience, throughput, "it just works better" — do not reorder.
3. Root `$OUTPUT_BRANCH` at `$DESTINATION_BASE_BRANCH`, not at `$BASE_BRANCH`. The source range may be mysql-5.6.x-based while the output branch is mysql-5.7.x-based.
4. Resolve conflicts using `$REFERENCE_BRANCH` as hunk-level or logic-level guidance. `git show $REFERENCE_BRANCH:<path>` is allowed for inspection only (see HP-1). If `rerere` produces a resolution, do not stage it until you have:
   - Confirmed there are no `<<<<<<<`, `=======`, or `>>>>>>>` markers in the file with `git grep -nE '^(<<<<<<<|=======|>>>>>>>)' -- <path>`.
   - Compared the resolved hunks against the corresponding `$REFERENCE_BRANCH` region with `git diff` and confirmed the logic matches.
   - If either check is uncertain, treat the rerere resolution as untrusted and resolve manually.
5. When a commit does not build in isolation **after the Group 7 marker**, classify the failure before editing. The classification must be one of: missing dependency to fold, premature hunk to defer, incoherent source-only addition to remove, or unresolved design issue. **If the failure does not clearly fit one of these four categories, stop and ask the engineer.** Do not invent a fifth category. Do not classify as "fold" what is actually whole-file replacement.
6. First fold in the minimum necessary fixes from later commits on `$REFERENCE_BRANCH`. Defer hunks only when those reference-derived fixes touch more than the affected commit's own changed paths plus a small set of directly-required headers. **If isolating the cascade requires editing files that the current commit did not touch and that are not direct-dependency headers, stop and ask the engineer.** "Cascading and very large" is not a judgment call you make; it is a Stop Condition you trigger.
7. Use commit bucketing and incremental builds to improve throughput, but never use bucketing to skip, defer, or batch a required post-Group-7 build (see HP-2).
8. The exact marker subject `=== MARKER: GROUP 7 — Upstream bug fixes ===` is the hard build boundary. Treat every non-marker source-range commit before that marker as part of the No-build bucket regardless of changed paths, including commits that touch `sql/`, `include/`, `storage/`, `cmake/`, generated headers, or any other source/build-system path. If the marker is missing from the source list, **stop and ask the engineer** what boundary to use; do not infer a fallback.
9. If and only if `$BASE_BRANCH` is exactly `mysql-5.6.22`, apply the branch-specific initial-tree ordering rules in [mysql-5.6.22-initial-tree-ordering.md](mysql-5.6.22-initial-tree-ordering.md). For any other base branch, do not apply those rules even if the engineer mentions them.
10. For source-range commits before the Group 7 marker, do not run per-commit builds. The first build must start exactly at the Group 7 marker checkpoint, before the marker commit itself is created. For source-range commits after the Group 7 marker, build-verify every completed source/plugin/build-system commit at that commit's resulting SHA before applying the next build-required commit. Only the destination base commit, pre-Group-7 source-range commits, and empty marker commits are exempt.
11. If the first build run at the Group 7 marker checkpoint fails with compilation issues, apply the minimal fixes in one or more new commits **before** preserving the `=== MARKER: GROUP 7 — Upstream bug fixes ===` marker itself. Each fix commit subject must start with the literal prefix `[compilation]`, then rebuild before preserving the marker and proceeding. The marker commit, when preserved, must be authored after all `[compilation]` fix commits — verify this with `git log --oneline` before continuing. "Minimal" means the smallest set of edits that makes the current G7 tree compile and link; it does **not** include folding REFERENCE state that addresses compile errors which would only be triggered by later commits. Pre-staging post-G7 content into a G7 `[compilation]` commit is forbidden (HP-2, HP-8): it converts later Source-bucket commits into empty/no-op cherry-picks and lets the G7 build act as a substitute build-of-record for content that belongs to post-G7 commits.
12. Never carry a known non-buildable build-required commit forward (see HP-2). If the current build-required commit cannot be made buildable with at most three minimum-fix attempts, stop and ask.
13. Do not rely on a later merge, final source commit, reconciliation commit, or final build to make earlier unbuildable commits coherent or to replace missing required post-Group-7 build evidence.
14. Preserve empty marker commits whose subject starts with `=== MARKER:`. Use `git cherry-pick --allow-empty <sha>` when possible; if Git reports a marker cherry-pick as empty, create the marker with `git commit --allow-empty -C <sha>` from the cherry-pick state. Preserve the original marker subject/body and record the new SHA. Do not build after an empty marker because it changes no tree content. **Detection of "marker" is syntactic**: the source commit subject's first non-whitespace characters must match the literal prefix `=== MARKER:`. If the subject merely contains the word "marker" without that exact prefix, it is not a marker.
15. Do not create empty commits for non-marker commits. After conflict resolution, hunk deferral, or build-fix folding, if `git diff --cached --quiet && git diff --quiet` reports no changes, the cherry-pick is empty. Skip it with `git cherry-pick --skip` (or abort/reset if no cherry-pick state remains). Document the skip with the original SHA, subject, and reason.
16. Do not add LLM/tool attribution trailers (see HP-4). Inspect every commit message before committing.
17. After all source commits are replayed and every required post-Group-7 build record is present, reconcile the tree to a null diff with `$REFERENCE_BRANCH` through explicit path/hunk-level reconciliation commits. Do not use tree snapping (HP-1).
18. After a null-diff tree exists, run a final build with the required build configuration before declaring completion.
19. If the null-diff tree fails the final build because `$REFERENCE_BRANCH` itself contains code incompatible with the required toolchain, **stop and ask the engineer** whether to keep the null-diff failing tree or add a narrow final build-fix commit. Only with explicit current-conversation approval may the final branch intentionally retain a non-null residual diff. Document the null-diff SHA, final build-fix SHA, residual paths/hunks, and both build results.
20. Do not use scripts from `/data/sh/utils`. Do not read files from `/data/sh/utils/reports/`. Writing `$REPORT_FILE` under `/data/sh/utils/reports/` is allowed (this is an output-only path).

---

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
  -DWITH_ROCKSDB=OFF \
  -DENABLE_DOWNLOADS=1 \
  -DWITH_READLINE=system
make -j$(( $(nproc) * 3 / 4 ))
```

A successful build means both CMake configuration and the build step complete without errors. Capture each build in a per-commit log named with the source commit index and SHA; per-batch logs are allowed only for path-classified post-Group-7 no-build batches. Prefer incremental builds in a stable `$BUILD_DIR` to preserve ccache and CMake state. Reconfigure or clean only when forced by CMake/cache breakage or a deep generated-header/build-system change.

If a parallel build exits with truncated diagnostics, rerun `make` in the same build directory, optionally with `-j1`, **only** to expose the first actionable compiler or linker error. After identifying the error, rerun the normal configured build to confirm it still fails the same way before editing any source.

Use `ccache` through CMake compiler launchers, not by replacing `CC` or `CXX`; the underlying compilers remain `gcc-9` and `g++-9`. Do not use MySQL helper-script directories such as `BUILD` or `BUILD-CMAKE` as build output directories.

---

## Workflow

### 1. Prepare

1. Confirm all required inputs are set: `$BASE_BRANCH`, `$TIP_BRANCH`, `$DESTINATION_BASE_BRANCH`, `$REFERENCE_BRANCH`, `$OUTPUT_BRANCH`, `$LLM_MODEL`, `$REPORT_FILE`.
2. **Output the Pre-flight Contract readback verbatim** (see [Pre-flight Contract](#pre-flight-contract)). If the readback is missing, paraphrased, or interleaved, abort the run.
3. Confirm the working tree is clean before starting.
4. If `$REPORT_FILE` is not specified, set it to `/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}.md`.
5. Set `$BUILD_DIR` to a directory under `/tmp` if not specified.
6. Generate the ordered source list:

   ```sh
   git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH
   ```

7. Inspect the ordered source list subjects and verify the exact marker `=== MARKER: GROUP 7 — Upstream bug fixes ===` exists. Record its 1-based source index as the Group 7 boundary. **If it is missing, stop and ask the engineer.** Do not infer a fallback boundary; do not select a "nearby" marker; do not proceed without one.
8. If `$BASE_BRANCH` is exactly `mysql-5.6.22`, read [mysql-5.6.22-initial-tree-ordering.md](mysql-5.6.22-initial-tree-ordering.md) and identify source-list commits whose subjects start with `Initial Percona Server 5.6.22 tree`. If `$BASE_BRANCH` is not exactly `mysql-5.6.22`, do not apply those rules even if a comment or memory suggests they would help.
9. Create `$OUTPUT_BRANCH` from `$DESTINATION_BASE_BRANCH`.
10. Start a deferred-hunks ledger for cascade-causing changes that must be applied later with their dependent commit.

### 2. Choose Commit Order

Default to chronological order from `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH`.

Reorder a commit only if all three conditions hold:

1. The chronological position produces a conflict that is **not** safely resolvable by hunk-level edits.
2. A specific alternative position resolves the conflict without producing new conflicts of equal or greater severity.
3. The reordering is recorded in `$REPORT_FILE` with original index, new index, and the specific conflict text that motivated the change.

If conditions 1 and 2 cannot both be demonstrated before the reorder, do not reorder. Convenience-driven reordering is forbidden.

**Branch-specific exception**: when `$BASE_BRANCH` is exactly `mysql-5.6.22`, use [mysql-5.6.22-initial-tree-ordering.md](mysql-5.6.22-initial-tree-ordering.md) for commits whose subjects start with `Initial Percona Server 5.6.22 tree`. Select the next commit in that group dynamically by least conflicted files against the current `$OUTPUT_BRANCH` state, then apply the selected commit for real. This exception does not apply to any other `$BASE_BRANCH`.

#### Bucketing

Bucket each commit before applying it. Bucketing is a syntactic operation, not a judgment call:

1. **Empty-marker bucket**: source commit subject's first non-whitespace characters match the literal prefix `=== MARKER:`. Always preserve as empty commit, regardless of position relative to Group 7. Do not build after.
2. **Forced pre-Group-7 no-build bucket**: source commit's 1-based index is less than the Group 7 marker's index, AND it is not itself the Group 7 marker, AND it is not in the Empty-marker bucket. Apply in chronological batches without running builds. This bucket overrides any path-based classification.
3. **Boundary-build checkpoint**: source commit's subject is exactly `=== MARKER: GROUP 7 — Upstream bug fixes ===`. Run the first build before preserving the marker as an empty commit. Create any required `[compilation]` fix commits before the marker itself.
4. **Path-classified buckets** (post-Group-7 only): for non-marker commits after Group 7, run `git diff-tree --no-commit-id --name-only -r <source-sha>` against the **source commit's SHA** (from `$BASE_BRANCH..$TIP_BRANCH`) — never the applied commit's SHA, never the staged tree, never the post-resolution amended commit — and classify by changed paths.

   **Extension-based Source override (checked first, overrides every rule below):** if **any** changed path has a filename ending in one of the following case-insensitive extensions, the commit is **Source bucket**, regardless of directory prefix:

   ```
   .h  .c  .cc  .cxx  .cpp  .hh  .hpp  .hxx  .cmake
   ```

   Concretely: match `(?i)\.(h|c|cc|cxx|cpp|hh|hpp|hxx|cmake)$` against each path. A single matching path forces the whole commit into Source bucket. This override applies even when the path lives under `mysql-test/`, `plugin/foo/`, `scripts/`, `packaging/`, or any other directory that would otherwise be no-build or plugin-only. C/C++/CMake source content is build-relevant regardless of where it lives.

   If the extension override does not fire (no changed path matches any of those extensions), classify by directory prefix:

   - **Path-classified no-build bucket**: only if every changed path matches `^(docs/|build-ps/|man/|mysql-test/|.*\.result$|debian/|rpm/|packaging/|.*\.spec$|scripts/(?!.*\.cmake))`. Apply in small chronological batches; run one incremental build at each batch boundary.
   - **Plugin-only bucket**: every changed path matches `^plugin/[^/]+/`. Apply singly and build immediately at the resulting SHA.
   - **Source bucket**: any changed path that does not match the no-build or plugin-only patterns above, including `sql/`, `include/`, `storage/`, `vio/`, `mysys/`, `client/`, `libmysql/`, `cmake/`, generated headers, or build-system files. Apply singly and build immediately at the resulting SHA.

If a path's bucket is ambiguous, default to the **Source bucket** (build-required). Never default to no-build for an ambiguous path.

The bucket assigned here is **locked** (HP-8). It does not change based on what the applied commit's diff-tree looks like after conflict resolution, deferral, alignment, or amendment. The only legitimate way for a Source-bucket commit not to produce a per-commit build is rule 15: the cherry-pick is fully empty after hunk-level resolution and is therefore skipped — in which case no commit exists, so no build is owed. A non-empty Source-bucket commit whose applied diff has been reduced to no-build paths only is the forbidden case, and the HP-8 staged-paths cross-check in §3 must catch it before the cherry-pick is continued.

If a path-classified no-build batch after Group 7 fails its boundary build, stop, identify the source commit that caused the failure, document the mis-bucket as a violation in `$REPORT_FILE`, and resume with source-bucket rules. If a source/plugin/build-system commit after Group 7 was applied without its required immediate build, the run is invalid (see HP-2 and Validity Invariants).

### 3. Cherry-Pick One Commit

For each selected commit:

```sh
git cherry-pick <sha>
```

If it applies cleanly, proceed to the build step required by the active bucket.

If it conflicts:

1. Identify every conflicted file with `git diff --name-only --diff-filter=U`.
2. For each conflicted file, check whether `rerere` already resolved it:
   - Run `git grep -nE '^(<<<<<<<|=======|>>>>>>>)' -- <path>`. If markers remain, treat as unresolved.
   - If markers are absent, compare hunks against the corresponding `$REFERENCE_BRANCH` region with `git diff <ref-sha>:<path> -- <path>`. If the rerere resolution does not match the reference's logic at the conflict regions, treat as untrusted and resolve manually.
3. By default, replace only the conflict regions with the corresponding content from `$REFERENCE_BRANCH` and leave unrelated local context untouched. Use a text editor or `sed` to edit the worktree file directly, transcribing the reference-region content into the conflict region. **Do not use any HP-1 forbidden command** to perform this transcription.
4. **Whole-file replacement is forbidden** (HP-1) even for test fixtures, generated/preprocessed headers, version files, or coherent API families. If hunk-level resolution is not feasible, stop and ask.
5. If the file does not exist on `$REFERENCE_BRANCH`, the conflict is between a local addition and a reference-side absence. Remove the conflicting addition hunk only if hunk-level analysis confirms the reference's deletion is the correct logic. Do not delete the whole file unless the entire file is the conflicting change and the engineer has explicitly approved removal in the current conversation.
6. Stage the resolved files: `git add <resolved-files>`.
7. **HP-8 staged-paths cross-check (mandatory for every post-Group-7 Source-bucket and Plugin-only-bucket cherry-pick, whether the cherry-pick conflicted or applied cleanly).** Before continuing, compare the staged tree's touched paths to the source commit's touched paths:

   ```sh
   git diff-tree --no-commit-id --name-only -r <source-sha> | sort -u > /tmp/src-paths.txt
   { git diff --cached --name-only; git diff --name-only; } | sort -u > /tmp/staged-paths.txt
   comm -23 /tmp/src-paths.txt /tmp/staged-paths.txt
   ```

   For every source/plugin/build-system path that appears in `src-paths.txt` but not in `staged-paths.txt`, the source commit's modification of that path is silently absent. Two cases are acceptable:

   1. The full cherry-pick is empty (no diff on any path, staged or unstaged). Apply rule 15 and `git cherry-pick --skip`. No build is owed.
   2. The omission is bounded deferral recorded in the deferred-hunks ledger with a specific named later target commit (rule 5 / §5 bounds).

   Any other case — non-empty cherry-pick where source/plugin/build-system paths from the source commit are silently absent — is an **HP-8 Stop Condition**. Abort the cherry-pick (`git cherry-pick --abort`), return to `LAST_GOOD`, and ask the engineer. Do not amend, do not run an "alignment" pass, do not strip more to make the commit cleaner, do not rebucket as no-build.

8. Continue the cherry-pick: `git cherry-pick --continue`.

If safe hunk-level resolution is not possible at any step, **stop and ask the engineer**. Do not escalate from hunk-level to whole-file replacement on your own authority. Do not "align" the staged tree to `$REFERENCE_BRANCH` after resolution; the conflict regions resolved during the cherry-pick are the only places where `$REFERENCE_BRANCH` content is permitted to enter the worktree, and only via hand-transcription, not via HP-1-forbidden commands.

### 4. Preserve Marker Commits And Drop Other Empty Cherry-Picks

#### Marker commits (subject begins with `=== MARKER:`)

1. Prefer `git cherry-pick --allow-empty <sha>`.
2. If Git reports the marker cherry-pick as empty, use `git commit --allow-empty -C <sha>` from the cherry-pick state to preserve the original subject, body, and authorship.
3. Inspect the new commit message with `git log -1 --format=%B` and verify no LLM/tool attribution trailer was added (HP-4). If a trailer is present that was not in the source commit, amend it out before continuing.
4. Record the original SHA, new SHA, subject, and confirmation that no build was run because the tree did not change.

#### Non-marker commits

Do not use `--allow-empty`. Detect emptiness syntactically:

```sh
git diff --cached --quiet && git diff --quiet
```

If both return 0 (no changes), the cherry-pick is empty. Skip it:

```sh
git cherry-pick --skip
```

If no cherry-pick state remains, abort or reset as appropriate. Record the skipped commit's original SHA, subject, and the reason it was empty. There is no new SHA and no build step.

### 5. Defer Dependency-Cascade Hunks

First try to keep the commit buildable by folding in the minimum necessary fixes or partial changes from later commits on `$REFERENCE_BRANCH`. Defer hunks only when the deferral is **bounded**:

- The deferred hunks touch only paths that the current source commit itself touched.
- The deferred hunks are clearly attributable to a specific later commit that introduces the missing dependency.
- The deferral does not cascade into editing files outside the current commit's diff.

If any of these bounds is violated — i.e., if the deferral would require editing files the current commit did not touch, or if the dependent later commit cannot be specifically identified — **stop and ask the engineer**. Do not extend a deferral to make it fit; do not invent a "cascade region" that spans multiple files outside the current diff. (Reasoning toward "this region is resolvable only by snap" or "the cascade is too large to isolate" is the Stop Condition itself; see HP-1.)

When deferral is in bounds:

1. Keep the non-cascading parts of the commit.
2. Remove only the hunks that create cascading conflicts or compile failures.
3. Record each removed hunk in the deferred-hunks ledger with source commit, file, short reason, and target later commit.
4. Apply the deferred hunk later with the dependent commit.
5. Build the current commit after the deferral and do not proceed until it passes.

Common deferral candidates:

- Header/API hunks that introduce fields, enum values, declarations, or function signatures before the implementation or all call sites arrive.
- Generated or preprocessed plugin headers that must stay ABI-consistent with their canonical headers.
- SQL command enum additions that require matching status arrays, parser use sites, or instrumentation tables.
- Storage-engine struct changes that require matching storage implementation files from a later commit.

When the dependent commit arrives, apply the deferred hunk there and record that the earlier deferral has been reconciled.

### 6. Build-Driven Fixes

Use the build log as the authority for intermediate fixes. Do not guess from the final reference tree alone.

For each post-Group-7 build failure:

1. Identify the first real error, not just the final `Error 2`. Use `ps_replay_errors.py` if the log is truncated.
2. Map the error to the smallest inconsistent surface: declaration/type mismatch, enum/table mismatch, missing member, missing source file, incoherent CMake entry, unresolved symbol, or ABI check mismatch.
3. Compare the current commit, `HEAD^`, the source commit, and `$REFERENCE_BRANCH` for the affected files using `git diff` and `git show <ref-sha>:<path>` (inspection only — see HP-1).
4. Choose **exactly one** of these actions:
   - **Fold**: add the smallest required reference or source-required declaration/member/enum entry to the current commit.
   - **Defer**: remove a premature hunk from the current commit and apply it later with its dependent implementation (subject to the deferral bounds in §5).
   - **Align hunks**: edit the smallest coherent set of hunks to match the reference API family while preserving unrelated current-commit content.
   - **Remove**: delete source-only files or CMake entries that are not present in the reference branch and cannot build coherently in this intermediate commit.
   - **Stop**: ask the engineer.

   **If the failure does not clearly map to one of Fold/Defer/Align/Remove, choose Stop.** Do not invent a fifth action. Do not classify a whole-file replacement as "Fold" or "Align hunks."

5. After at most three Fold/Defer/Align/Remove attempts on the same commit, if the build is still failing, choose Stop. Do not continue iterating; the iteration limit exists to prevent unbounded reasoning toward forbidden actions.
6. Rewrite only the current replayed commit after the fix. **Exception**: for the first Group 7 marker checkpoint build, compilation fixes must be committed as new `[compilation]` commit(s) immediately before preserving the `=== MARKER: GROUP 7 — Upstream bug fixes ===` marker itself. Do not alter already build-verified earlier commits.
7. Rebuild and verify the commit passes before applying the next build-required commit.

### 7. Restore Buildability

When replay reaches the exact `=== MARKER: GROUP 7 — Upstream bug fixes ===` source-list commit, run the first build in the configured `$BUILD_DIR` **before** preserving that marker as an empty commit. After each completed source/plugin/build-system cherry-pick after Group 7, run an incremental build at that commit's resulting SHA before applying the next build-required commit. After each path-classified no-build batch after Group 7, run one incremental build at the batch boundary.

Do not run builds for any source-range commit before the Group 7 marker checkpoint. Use a clean build only for the first verification, after CMake/cache breakage, after build-system/generated-header changes that invalidate incremental trust, or for final confidence when time permits.

Before starting the Group 7 marker checkpoint build or any later build-verified cherry-pick, record `LAST_GOOD=$(git rev-parse HEAD)`. `$OUTPUT_BRANCH` must never be left pointing at a boundary-fix commit or post-Group-7 build-required commit that has not passed its required build.

If the Group 7 checkpoint build fails:

1. Follow the Build-Driven Fixes loop in §6.
2. Apply the minimal fixes in the working tree, then create one or more new commits whose subjects start with the literal prefix `[compilation]`. These fix commits must be committed **before** the `=== MARKER: GROUP 7 — Upstream bug fixes ===` marker itself. Verify the order with `git log --oneline -- $LAST_GOOD..HEAD` after preservation.
3. Rebuild until the boundary passes, then preserve the marker as an empty commit.

If a post-Group-7 build fails:

1. Follow the Build-Driven Fixes loop in §6, with the three-attempt limit.
2. If the commit cannot be made buildable within the loop, return `$OUTPUT_BRANCH` to `LAST_GOOD` (resetting if a failing commit was created), capture diagnostics in `$REPORT_FILE`, and ask the engineer.
3. Do not proceed to the next commit until the current one builds.

Missing required build evidence is a stop condition, not a reportable deferral. If a required build was skipped (intentionally or by oversight) and any later commit was applied, the run is **invalid** (see HP-2 and Validity Invariants); stop, report the first skipped index/SHA, and ask whether to reset.

### 8. Execution And Progress

Run the replay in the foreground unless the engineer explicitly asks to background it. Use a TaskList or todo tracker for the long workflow and summarize progress every 10–20 commits, including:

- Current commit count and total
- Current bucket and phase (pre-Group-7, boundary checkpoint, post-Group-7)
- Latest build result
- Notable conflicts or deferrals

Progress reports must not pre-classify upcoming regions, predict that any future region will require snap or build skipping, or refer to "known cascade regions" from any source. (HP-1, HP-3.)

Long build commands may run for a while. Report progress when each build or batch completes to keep the agent session active.

### 9. Direct Execution And Optional Utility Scripts

Direct Git and build commands are the default, portable implementation of this skill. Helper scripts are optional and must comply with the mandatory rules.

Helper-script location: `/home/przemek/.agents/skills/ps-replay+make-buildable/scripts`. If unavailable, check repo-local `scripts/`. If neither location has a needed helper, drive Git, conflict resolution, and builds directly.

The following invariants apply whether using scripts or hand-written shell loops:

1. Generate the source list with `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH`.
2. Locate the exact `=== MARKER: GROUP 7 — Upstream bug fixes ===` subject in the source list before classification. Stop if missing.
3. Force every non-marker commit before the Group 7 marker into the no-build bucket before considering changed paths.
4. Treat the exact Group 7 marker as the first-build checkpoint: run the first build before preserving the marker, and create any required `[compilation]` fix commits before the marker itself.
5. Classify non-marker commits after Group 7 by touched paths of the **source commit** (`git diff-tree --no-commit-id --name-only -r <source-sha>`). Apply the **extension-based Source override** first: if any changed path matches `(?i)\.(h|c|cc|cxx|cpp|hh|hpp|hxx|cmake)$`, the commit is Source bucket regardless of directory prefix (including `mysql-test/`, `plugin/`, `scripts/`, `packaging/`). Only when no path matches the extension override do the directory-prefix no-build / plugin-only / source rules apply. The classification is locked at this point (HP-8); no helper-script mode may reclassify a Source-bucket or Plugin-only-bucket commit as no-build based on the applied commit's post-resolution diff.
6. Apply pre-Group-7 no-build batches in small chronological groups without running builds.
7. Apply post-Group-7 no-build batches in small chronological groups and run an incremental build at each batch boundary.
8. Apply source/plugin/build-system commits after Group 7 singly and build immediately at the resulting SHA before applying the next build-required commit.
9. For every post-Group-7 Source-bucket and Plugin-only-bucket cherry-pick, perform the HP-8 staged-paths cross-check before `git cherry-pick --continue` (or before commit, if the cherry-pick applied cleanly). A helper-script mode that omits this cross-check, that runs any "align source paths to REFERENCE" pass over the worktree/staged tree, or that strips source/plugin/build-system hunks from a Source-bucket commit to escape its per-commit build is disabled by HP-8 regardless of disk presence.
10. Stop on the first conflict, build failure, missing required build record, or HP-8 cross-check failure. Do not let an automation loop auto-resolve conflicts, defer required builds, "align" worktree paths to REFERENCE, or carry failures forward.
11. If the first Group 7 checkpoint build fails, create the required `[compilation]` fix commits before preserving the marker. The fix content must be the minimum needed to compile the current G7 tree; helper-script modes that mass-fold later REFERENCE state into a G7 `[compilation]` commit are disabled by HP-2 / HP-8 / rule 11.
12. Log each source index, original SHA, new SHA, subject, source-commit path list, bucket (and whether locked by HP-8 as Source/Plugin even if post-resolution paths look no-build), whether the no-build bucket was forced by the pre-Group-7 rule, the HP-8 staged-paths cross-check result, apply status, and build result. For every post-Group-7 source/plugin/build-system commit, the log must include that commit's own build log path and PASS result.

#### Available helpers

- `ps_replay_batch.py`: replay a bounded 1-based commit range from a source-list file. Stops on the first conflict, preserves empty marker commits, skips empty non-marker commits, stops on the first build failure or missing required build record. Requires the exact Group 7 marker by default. Use `--build-policy bucketed` only if you have verified by reading the helper's source that it builds each post-Group-7 source/plugin/build-system commit at its resulting SHA before applying the next build-required commit. Use `--classify-only` first to inspect bucket decisions.
- `ps_replay_resolve_conflicts.py`: inspect current conflicts and print conflict blocks with nearby `$REFERENCE_BRANCH` snippets. Does not modify or stage files.
- `ps_replay_build.py`: run a clean or incremental build with the standard configuration, writing a per-run log.
- `ps_replay_errors.py`: extract likely root-cause compiler/linker/CMake/ABI diagnostics from large build logs.
- `ps_replay_scan_range.py`: scan `$BASE..$REFERENCE` (and `$BASE..$TIP` when they differ) for special commits — snap commits, markers, squashes — and surface commits in reference but not in tip. Run during Prepare so reference-only commits cannot be silently missed.
- `ps_replay_conflict_triage.py`: after a stop, classify conflicted files as `auto-match`, `auto-mismatch`, or `unresolved`. `--auto-stage` stages only auto-match files; the rest require manual hunk-level work.
- `ps_replay_resolve_hunks.py`: hunk-level conflict-region resolver. For each `<<<<<<< / ||||||| / ======= / >>>>>>>` block in the listed files (or `--all` for every markered file), score each side's distinct non-trivial lines against the corresponding `$REFERENCE_BRANCH` file and pick the higher-overlap side; HEAD-tiebreak. Replaces only the conflict block; merged context outside markers is untouched. Exit 1 if any region was left unresolved (neither side overlaps reference); those need manual hunk-level work using `git show $REFERENCE:<path>` for inspection only. HP-1 compliant: never copies whole files. Treat the result as best-effort: if the chosen side later breaks the build, fix via Fold/Defer/Align/Remove — do not loop the resolver with looser thresholds.
- `ps_replay_auto_loop.sh`: replay driver that cherry-picks a 1-based source-list range, buckets each commit, auto-resolves DU files absent on REFERENCE, runs `ps_replay_resolve_hunks.py` against any markered files, skips empty cherry-picks (rule 15), and runs the per-commit build for source/plugin commits (rule 10). Stops on unresolved markers, remaining unmerged files, or build failures with the log path. Does **not** auto-fix build failures (those require Fold/Defer/Align/Remove judgment per rule 6). Configured via env vars `PS_REPLAY_SRC_LIST`, `PS_REPLAY_LOG_DIR`, `PS_REPLAY_BUILD_DIR`, `PS_REPLAY_WORKTREE` (default cwd), `PS_REPLAY_REFERENCE` (default `ps-5.7.9-gca-start`), `PS_REPLAY_SCRIPTS` (default the script's own directory). Use this for the bulk of the post-Group-7 replay; switch back to direct git when a stop demands per-commit reasoning.
- `ps_replay_residual_audit.py`: classify hunks in `git diff $OUTPUT $REFERENCE` as whitespace / trivial / substantive during Final Parity.
- `ps_replay_least_conflict.py`: only for `$BASE_BRANCH=mysql-5.6.22`, ranks remaining `Initial Percona Server 5.6.22 tree` candidates by trial-applying each in a temporary worktree. Does not apply for real; use to choose the next candidate, then cherry-pick manually under the main rules.

#### Disabled helpers

Any helper named `snap_*` or any mode of any helper that performs whole-file or whole-tree replacement from `$REFERENCE_BRANCH` is disabled by HP-5, regardless of whether the helper is present on disk. Presence does not constitute approval.

Example diagnosis:

```sh
SKILL_SCRIPT_DIR=/home/przemek/.agents/skills/ps-replay+make-buildable/scripts
python3 "$SKILL_SCRIPT_DIR/ps_replay_errors.py" /tmp/ps-replay-${OUTPUT_BRANCH}-logs/build-58-812714fe16da-ccache.log
python3 "$SKILL_SCRIPT_DIR/ps_replay_build.py" --worktree "$WORKTREE" --build-dir "$BUILD_DIR" --log /tmp/rebuild.log --incremental
```

Example post-Group-7 driver loop:

```sh
SKILL_SCRIPT_DIR=/home/przemek/.agents/skills/ps-replay+make-buildable/scripts
export PS_REPLAY_SRC_LIST="$LOG_DIR/source-list.txt"
export PS_REPLAY_LOG_DIR="$LOG_DIR"
export PS_REPLAY_BUILD_DIR="$BUILD_DIR"
export PS_REPLAY_WORKTREE="$WORKTREE"
export PS_REPLAY_REFERENCE="$REFERENCE_BRANCH"
export PS_REPLAY_SCRIPTS="$SKILL_SCRIPT_DIR"
bash "$SKILL_SCRIPT_DIR/ps_replay_auto_loop.sh" 29 95
# Stops on the first conflict that needs hand-resolution or the first build
# failure. Inspect, fix per Fold/Defer/Align/Remove, amend, re-run with
# updated START.
```

Example hunk resolver invocation (after a stop on conflicts):

```sh
python3 "$SKILL_SCRIPT_DIR/ps_replay_resolve_hunks.py" "$REFERENCE_BRANCH" --all
# Then inspect remaining files (those reported "left unresolved") with
# `git show $REFERENCE_BRANCH:<path>` and edit the conflict region by hand.
```

### 10. Final Parity

Before starting Final Parity, audit that every required post-Group-7 build record exists. Iterate over post-Group-7 source/plugin/build-system commits and confirm each has a per-commit build log with a PASS result at that commit's resulting SHA. **If any required build is missing, do not start Final Parity.** Stop at the first missing source index/SHA and ask the engineer whether to restart from the last build-verified commit.

Once the audit passes, check parity:

```sh
git diff $OUTPUT_BRANCH $REFERENCE_BRANCH
```

If the diff is empty, record the null-diff confirmation and the null-diff SHA in `$REPORT_FILE`, then run the final build at that exact SHA.

If differences remain:

1. Add one or more explicit reconciliation commits that bring `$OUTPUT_BRANCH` to parity with `$REFERENCE_BRANCH` through reviewed path/hunk-level edits. Do not use HP-1 forbidden commands.
2. Confirm `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty and record the null-diff SHA.
3. Re-run the build at the null-diff tip.
4. Document the reconciliation commit and the residual differences it resolved.

If the null-diff final build passes, the task can complete with both parity and buildability.

If the null-diff final build fails:

1. Extract the first actionable error.
2. If the failure can be fixed while preserving null diff, fix the reconciliation hunk and repeat the null-diff build.
3. If preserving null diff and passing the required build conflict, **stop and ask the engineer** which final state to keep:
   - Keep the null-diff tree with the final build failure documented; or
   - Add a narrow final build-fix commit, accepting a documented residual diff.
4. Do not choose buildability over null diff, or null diff over buildability, without explicit current-conversation approval.
5. If the engineer approves a final build-fix residual diff, apply only the smallest build-required hunks, commit them after the null-diff reconciliation commit, run the final build again, and document the residual `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH`.

---

## Report Requirements

Write `$REPORT_FILE` in markdown. It must include:

### Header

- The input branches and report path.
- `$LLM_MODEL`, `$BUILD_DIR`, and the build command used.
- The pre-flight readback, reproduced verbatim, with the timestamp at which it was produced.
- A "Violations encountered" section that explicitly states either `none` or lists every violation with HP-rule, location in the run, and remediation status. The "none" attestation is **mandatory** even when no violations occurred; an absent attestation is itself a reporting violation.

### Per-applied-commit

- Original SHA from `$TIP_BRANCH`.
- New SHA on `$OUTPUT_BRANCH`.
- One-line subject.
- Whether it applied cleanly or required conflict resolution.
- Build result for that commit, **or** the no-build exemption (pre-Group-7 forced no-build / post-Group-7 path-classified no-build batch).
- For every post-Group-7 source/plugin/build-system commit, that commit's own build log path and PASS result at the resulting SHA. The strings `deferred`, `covered by final build`, `covered by reconciliation`, `build-of-record is final`, `covered by G7 [compilation] fold`, `effect already verified at G7`, or any equivalent are unacceptable build results and constitute an HP-2 violation.
- For every post-Group-7 Source-bucket and Plugin-only-bucket commit, the bucket was decided from the source commit's `git diff-tree` (record the source SHA and the source-paths list), and the HP-8 staged-paths cross-check was performed before continuing the cherry-pick (record either `all source paths present in staged tree` or the deferred-hunks ledger entries that account for any absent paths).

### Per-preserved-marker-commit

- Original SHA and new SHA.
- One-line marker subject.
- Confirmation of empty preservation, no tree changes, no build step.

### Per-skipped-empty-commit

- Original SHA and one-line subject.
- Reason it was empty.
- Confirmation that no new SHA was created.

### Per-conflicted-commit

- Conflicted files.
- Short description of each conflict.
- How each conflict was resolved, including the `$REFERENCE_BRANCH` hunk or logic used.

### Sections

- **Deferred-hunks ledger**: every cascade-causing hunk removed from an earlier commit, why it was deferred, and which later commit applied it.
- **Build-driven fixes**: every folded declaration/member/enum, reference-aligned hunk set, removed source-only file or CMake entry, and the build error it fixed.
- **Reordering**: any reordering relative to chronological order, with the specific conflict that motivated it.
- **`mysql-5.6.22` initial-tree selections** (if applicable): every least-conflict selection with candidate index, SHA, conflicted-file count, and selected order.
- **Bucket classification**: bucket per commit, batching decisions, and any mis-bucket corrections.
- **Group 7 checkpoint**: any `[compilation]` fix commits with SHA, subject, changed paths, build error summary, rebuild result, and confirmation that each fix commit was created before the marker itself. Each `[compilation]` commit must also include an attestation that its content is the minimum to make the current G7 tree build and does **not** pre-stage REFERENCE state from later commits (HP-2, HP-8, rule 11).
- **Bucketing lock (HP-8)**: for every post-Group-7 Source-bucket and Plugin-only-bucket commit, the source-SHA-derived path list, whether the **extension-based Source override** fired (and which extensions/paths triggered it), the staged-paths list, the comm-diff result, and either `match` or the ledger entries justifying any missing source paths. Explicit attestation that no Source-bucket commit was rebucketed as no-build after resolution and no "align source paths to REFERENCE" pass was run.
- **Reference-derived fixes**: any partial changes ported from later commits on `$REFERENCE_BRANCH` to preserve buildability.
- **Commit rewrites**: any commit rewritten due to build fixes, with failed SHA, final SHA, and build log path.
- **Buildability confirmation**: confirmation that no non-buildable build-required commits remain on `$OUTPUT_BRANCH`. If the run stopped, identify the last known buildable commit and the blocked source commit.
- **Build-record audit**: confirmation that no required post-Group-7 build was skipped. If any was skipped, mark the run **invalid** from the first skipped source index/SHA and explicitly state that the run cannot be completed by adding builds at the tip.
- **Final parity**: confirmation that `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty at the null-diff SHA, plus the final build result at that SHA.
- **Reconciliation commit** (if any): SHA and explanation.
- **Final build-fix residual** (if approved): engineer approval text, final build-fix SHA, final build log, residual diff paths/hunks, and the reason the null-diff tree could not also be buildable under the required toolchain.

---

## Stop Conditions

Stop and ask the engineer whenever any of the following is **even arguably** the case. The "even arguably" standard is deliberate: where stopping is cheap and rule violation is invalidating, the asymmetry favors stopping.

- `$REFERENCE_BRANCH` does not contain enough information to resolve a conflict at hunk level.
- A dependency cascade cannot be isolated into targeted hunks within the current commit's own changed paths plus a small set of direct-dependency headers.
- A conflict, cascade, or build failure appears to require whole-file or whole-tree reference replacement. Prior reports, memory, rerere, helper-script presence, and model recollection do not constitute approval; stop unless the engineer has explicitly approved the exact file path and reason in the **current conversation**, after this skill was loaded.
- A commit cannot be made buildable within three Fold/Defer/Align/Remove attempts.
- A commit remains non-buildable after minimal `$REFERENCE_BRANCH` fixes and bounded hunk deferral.
- The required toolchain or build dependencies are unavailable.
- The Group 7 marker is missing from the source list.
- A required post-Group-7 build was skipped and any later commit was applied.
- A build-driven fix does not clearly map to Fold, Defer, Align, or Remove.
- The final null-diff tree fails the required build.
- You catch yourself reasoning toward any HP-rule violation.
- You catch yourself reasoning toward "this commit's subject indicates X, so I'll handle it differently" — the only subject-based check is the literal `=== MARKER:` preservation rule (HP-7).
- The HP-8 staged-paths cross-check shows a source/plugin/build-system path from the source commit absent from the staged tree, and the absence is not (a) a fully empty cherry-pick under rule 15 or (b) a bounded deferral recorded in the ledger with a named later target commit.
- You catch yourself reasoning toward "the applied commit no longer touches source paths after resolution, so it's no-build now," "I'll align the source paths to REFERENCE since REFERENCE has the final state anyway," "this source intent was already verified at the G7 [compilation] fold," or "I'll fold the post-G7 REFERENCE state into the G7 fix so later cherry-picks land cleanly" — these are HP-2 / HP-8 / rule 11 violations.
- The pre-flight readback was not produced cleanly.

When stopping, return `$OUTPUT_BRANCH` to `LAST_GOOD` (aborting any in-progress cherry-pick, resetting any failing commit), preserve diagnostics in `$REPORT_FILE`, and describe to the engineer:

1. The current commit being attempted (source SHA, subject, bucket).
2. The specific failure or stop reason.
3. The minimum-fix attempts already made.
4. Two or three concrete options the engineer can choose between (split, defer named hunk, reorder, approve a named exception, restart from earlier checkpoint).

Do not propose options that would require an HP-rule violation. Do not present "snap to reference" as an option.

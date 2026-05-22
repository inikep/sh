---
name: ps-replay+make-buildable
description: Use to replay Percona Server commits from a mysql-5.6.x BASE_BRANCH..TIP_BRANCH range onto a mysql-5.7.x destination base, resolving conflicts with hunk-level guidance from a known-buildable REFERENCE_BRANCH, preserving buildability through bucketing, incremental builds, and targeted fold/defer build fixes, and producing a final branch with null diff to the reference. Use when porting or rebasing a Percona Server commit range with Group 8 marker checkpoint build verification.
---

# Percona Server Replay And Make Buildable

## Purpose

Use this skill to port a Percona Server commit range while maintaining a buildable history and converging exactly to a known-good reference branch *through hunk-level cherry-picks and explicit reconciliation commits, not through tree snapping or build skipping*.

The path to the result is part of the result. A null diff or buildable tip achieved by violating any rule in this skill is **not success**. It is a rule violation that produces an **invalid run**, which must be discarded and redone. This is non-negotiable; the engineer cannot accept an invalid run by approving it after the fact, because invalidity is defined by what was done during the run, not by what the tip looks like.

The task is complete only when **all** of the following hold simultaneously:

1. `$OUTPUT_BRANCH` is rooted at `$DESTINATION_BASE_BRANCH`, e.g. `mysql-5.7.9`.
2. Every commit from `$BASE_BRANCH..$TIP_BRANCH` has been cherry-picked one at a time onto that destination base, **without** consulting any out-of-session source for prior decisions, cascade regions, or approvals.
3. Empty marker commits whose subject begins with one or more `=` characters followed by ` MARKER:` (e.g. `=== MARKER: ...` or `==================== MARKER: ...`) are preserved as empty commits; other empty cherry-picks are skipped.
4. The first build runs **exactly** at the source-list position of `==================== MARKER: GROUP 8 — Upstream bug fixes ====================`, before that empty marker commit is preserved. Every build-required commit after that marker has its own successful build record at that commit's resulting SHA before the next build-required commit is applied.
5. The replay reaches a null diff to `$REFERENCE_BRANCH` through path/hunk-level reconciliation commits. The null-diff tree is then final-build verified. The null-diff reconciliation commit and the final build are **never** a substitute build-of-record for any skipped post-Group-8 required build.
6. `$REPORT_FILE` records the commits, preserved empty marker commits, skipped empty commits, conflicts, build fixes, reordering, the pre-flight readback, and the final parity result, including an explicit "violations encountered: none" attestation if no violations occurred.

## Inputs

- `$BASE_BRANCH`: source-base branch whose tip is the lower bound of the source range (e.g. `mysql-5.6.22`).
- `$TIP_BRANCH`: branch containing commits to port.
- `$DESTINATION_BASE_BRANCH`: destination MySQL base for `$OUTPUT_BRANCH` (e.g. `mysql-5.7.9`).
- `$REFERENCE_BRANCH`: known-buildable branch used as the source of truth for conflict resolution and final tree parity.
- `$OUTPUT_BRANCH`: branch to create from `$DESTINATION_BASE_BRANCH`.
- `$LLM_MODEL`: identifier including model and reasoning level (e.g. `opus-4.7-high`).
- `$REPORT_FILE`: markdown report to produce. Default: `/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}.md`.
- `$RUN_DIR`: run state directory under `/tmp` (e.g. `/tmp/ps-replay-${OUTPUT_BRANCH}`).
- `$BUILD_DIR`: out-of-tree build directory under `$RUN_DIR` (e.g. `/tmp/ps-replay-${OUTPUT_BRANCH}/build`).

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

**Bulk merge-strategy resolution is also forbidden.** The following are banned because they collapse conflict regions to one side without hunk-level review and are functionally indistinguishable from a coarse-grained snap:

- `git cherry-pick -X ours <sha>`, `git cherry-pick -Xours <sha>`, `git cherry-pick --strategy-option=ours`
- `git cherry-pick -X theirs <sha>`, `git cherry-pick -Xtheirs <sha>`, `git cherry-pick --strategy-option=theirs`
- `git merge -X ours`, `git merge -X theirs`, `git rebase -X ours`, `git rebase -X theirs`, and any equivalent `--strategy-option=ours|theirs` on `merge`/`rebase`/`revert`/`am`
- Setting `merge.conflictStyle`, `merge.defaultToUpstream`, or any equivalent config to auto-resolve conflicts in this run
- Using `git checkout --ours <path>` or `git checkout --theirs <path>` on conflicted files to bulk-accept a side instead of hunk-level resolution
- Any helper script that wraps the above, regardless of how it is named

Cherry-picks must run as plain `git cherry-pick <sha>` (with `--allow-empty` only for marker commits per rule 13). Conflicts must be resolved hunk by hunk as described in §3, never by telling Git to prefer HEAD or the incoming side wholesale.

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

### HP-2. Required post-Group-8 builds must not be skipped.

After the `==================== MARKER: GROUP 8 — Upstream bug fixes ====================` checkpoint, every source/plugin/build-system commit must have its own successful build at that commit's resulting SHA before the next build-required commit is applied. Bucketing for this purpose is locked at the source commit's path classification (see HP-8); whatever the post-resolution applied commit's diff happens to look like does not retroactively remove a commit's build requirement.

The following are forbidden:

- Applying any post-Group-8 source/plugin/build-system commit while a previous required build is missing or failing
- Recording `deferred`, `covered by reconciliation`, `final build-of-record`, `covered by final build`, `batch build covers it`, `covered by G8 [compilation] fold`, `effect already verified at G8`, or any equivalent wording in place of a per-commit build PASS
- Citing the null-diff reconciliation commit's build, the final-build-fix commit's build, or any later commit's build as the build-of-record for an earlier required commit
- Citing the Group 8 marker checkpoint build, or any pre-Group-8 build, as the build-of-record for any post-Group-8 commit. Pre-Group-7 builds (including the G8 checkpoint build and its `[compilation]` fix builds) are **never** build-of-record for any post-G8 commit, regardless of what content was folded into them.
- **Bulk forward-folding** of content from *multiple* later source-list commits into a single earlier fix commit (the "G8 mass-fold" pattern and its variants). Forbidden examples:

  - Folding REFERENCE state from many later commits into a single G8 `[compilation]` fix commit so that subsequent post-G8 Source-bucket cherry-picks resolve to empty/no-op and their per-commit builds are escaped. The G8 `[compilation]` fix commits address compile errors of the current G8 tree only; they do not pre-stage content from future commits (see also rule 10).
  - Folding hunks from many later source-list commits (idx N+1, N+2, N+5, ...) into a single earlier fix commit (idx N) in one go, even outside the G8 boundary. Each forward-fold must be a single named-pair entry in the ledger — one earlier target ↔ one later source — and bulk pairing into one earlier commit is forbidden.
  - Any pattern that causes an earlier build to act as build-of-record for content that belongs to **multiple** later commits.

  **Targeted (per-commit) forward-fold is allowed** and is in fact the **preferred** Fold source over REFERENCE-fold when the missing content is attributable to a specific named later source-list commit; see §6 Fold's forward-fold bounds and the §6 Squash action (for the case where most of one later commit is needed). The distinguishing line is: one-to-one targeted forward-fold respects per-commit build-of-record discipline (the forward-folded hunk's build-of-record is its target earlier commit's resulting SHA, which is where the content actually lives); many-to-one bulk forward-fold smuggles content past per-commit builds and is what this prohibition catches.
- Pre-classifying any post-Group-8 source/plugin/build-system commit as build-deferrable during Choose Commit Order or progress reporting

If a required post-Group-8 build was skipped and any later source-range commit was applied, the run is **invalid from the first skipped source index/SHA**. Do not attempt to repair an invalid run by adding builds at the tip. Stop, report the first skipped index/SHA, and ask the engineer whether to reset to the last build-verified commit.

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

The only subject-based syntactic check this skill performs is the marker preservation rule (HP-implicit, see §4): a source commit subject whose first non-whitespace characters are one or more `=` characters immediately followed by ` MARKER:` (e.g. `=== MARKER: ...`, `==================== MARKER: ...`, or any other `=`-prefix width) is preserved as an empty commit. No other subject-derived branching is permitted.

**Why:** Subject lines are metadata, not authority. A commit titled `[reconciliation]` may still carry source hunks that are correct on the destination base, and a commit titled `Percona Server 5.7 port fixes` may carry a fold this run actually needs. Bulk-resetting source modifications to HEAD on a per-commit basis bypasses hunk-level resolution and is functionally a whole-file-from-HEAD replacement, which has the same coarse-grained-substitution failure mode that HP-1 forbids against `$REFERENCE_BRANCH`. The right granularity is always the conflict region.

**How to apply:** Resolve every commit's conflicts at the hunk level using `$REFERENCE_BRANCH` for guidance, regardless of subject. If after hunk-level resolution and the Fold/Defer/Defer-commit/Align/Remove loop a commit still cannot be made buildable, that is a Stop Condition — stop and ask, do not introduce a "this kind of commit always gets reset" shortcut. If a class of commits genuinely doesn't apply to the destination base, that decision belongs to the engineer in the current conversation, named by SHA, not to the model classifying by subject.

### HP-8. Bucketing locks at the source commit. Stripping source modifications to escape the Source bucket is forbidden.

The bucket of a source-list commit is determined **before** cherry-pick by running `git diff-tree --no-commit-id --name-only -r <source-sha>` against the **source commit's SHA** (the SHA from `$BASE_BRANCH..$TIP_BRANCH`). Once classified, the bucket does not change based on what the applied commit's tree happens to look like after conflict resolution, deferral, alignment, or amendment.

The following are forbidden, regardless of justification:

- Re-bucketing a Source-bucket commit (or Plugin-only bucket commit) as no-build because the applied commit's `git diff-tree` no longer touches source paths after resolution or amendment.
- Stripping the source-path hunks of a Source-bucket commit during conflict resolution or post-cherry-pick editing so that the resulting commit lands in the no-build bucket and its required per-commit build is escaped.
- Running any "align source paths to `$REFERENCE_BRANCH`" / "snap to current REFERENCE state" / "drop source modifications already at REFERENCE" pass over the worktree or the staged tree after a cherry-pick, whether implemented via the HP-1-forbidden commands, via a helper script, via a Python/awk/sed loop that reads `$REFERENCE_BRANCH` content, or via hand-edits whose source is `git show $REFERENCE_BRANCH:<path>` for anything other than the specific conflict region being resolved.
- Dressing the forbidden alignment pass in any "PROTECTED set" / "PROTECTED paths" / "exclusion list" / "safe-paths only" / "everything except `sql/sql_acl.cc`" / "skip these N files" framing. Naming a small set of exceptions does not legitimize the operation: the operation is what is forbidden, and excluding a handful of paths from a forbidden whole-tree REFERENCE alignment leaves a forbidden whole-tree REFERENCE alignment on the rest. Any procedure of the form "for every path under this directory (minus an exclusion list), make it match `$REFERENCE_BRANCH`" is an HP-1 + HP-8 violation regardless of how short the exclusion list is and regardless of which paths it names.
- Using `git cherry-pick -X ours` / `-X theirs` (or any of the merge-strategy variants enumerated in HP-1) as the cherry-pick command for the replay. A run that used `cherry-pick -X ours` is treated as if every conflict region resolved by that strategy were resolved by an HP-1 forbidden command, and is invalid from the first such cherry-pick.
- Treating "the applied commit's diff is no-build paths only" as evidence that no per-commit build is required, when the source commit's diff-tree included source/plugin/build-system paths.
- Mass-folding REFERENCE content from later commits into a single G8 `[compilation]` fix commit so that subsequent Source-bucket cherry-picks become empty or no-build (see also HP-2 and rule 10 below). "Minimal G8 fix" means fixing the current G8 tree, not pre-staging future commits' content.

Detection cross-check (mandatory before continuing any Source-bucket cherry-pick): after staging the resolved files but **before** `git cherry-pick --continue`, run `git diff --cached --name-only` and compare to the source commit's `git diff-tree --no-commit-id --name-only -r <source-sha>`. If any source/plugin/build-system path from the source commit is absent from the staged diff, the absence must be accounted for by exactly one of these ledger entries; otherwise **stop and ask the engineer**:

  - A **deferred-hunks** entry with this source commit as the source and a named later target commit (backward hunk-deferral, §5).
  - A **forward-folded-hunks** entry with this source commit as the later-source and a named earlier target commit on `$OUTPUT_BRANCH` whose resulting SHA already contains the absent hunks (forward hunk-fold, §6 Fold). The cross-check is satisfied because the hunks live earlier in the history, not because they were dropped.
  - A **squashed-commits** entry that names this source commit as the absorbed (later) commit of a squash pair, in which case this commit's source-list cursor position is skipped entirely (no cherry-pick happens; see §6 Squash bound (h)).

Do not amend, do not continue, do not "tidy up". This cross-check applies to every post-Group-8 Source-bucket and Plugin-only-bucket cherry-pick.

If, after legitimate hunk-level conflict resolution, a Source-bucket commit ends up with **no diff at all** (`git diff --cached --quiet && git diff --quiet` both return 0), apply rule 14 and skip with `git cherry-pick --skip`. The non-existence of a commit is not the same as a no-build commit, and no per-commit build is owed for a skipped empty cherry-pick. The non-empty, source-paths-stripped case is the forbidden one.

**Why:** Subject-based classification (HP-7) is one route from "commit X is Source-bucket" to "commit X is no-build"; post-resolution path-stripping is another. Both substitute a coarser-grained decision for hunk-level resolution and both cause per-commit builds to be silently skipped. HP-7 closes the first route; HP-8 closes the second. There is no path that converts a Source-bucket commit into a no-build commit without engineer approval, named by SHA, in the current conversation.

### HP-9. Build-Driven Fixes must not undo work that already equals REFERENCE.

When a Build-Driven Fix (BDF) is needed because an API has two forms in flight — an older form and a newer form that matches `$REFERENCE_BRANCH` — the BDF must update the **lagging** side to match REFERENCE, never the side that already matches REFERENCE.

Concretely, the following are forbidden as BDF resolutions:

- Reverting call sites that already pass the REFERENCE-matching argument count/types to match an older macro or declaration that is still in-tree from an earlier squash.
- Reverting a function definition's signature back to an older form to match older callers, when the definition already matches REFERENCE.
- Editing any region whose current content is byte-identical to the corresponding region in `$REFERENCE_BRANCH`, when the goal is to "reconcile with" a lagging counterpart elsewhere. The lagging counterpart is what must be edited.

Before applying any BDF edit, compare both sides of the mismatch (caller and declaration/definition) against `$REFERENCE_BRANCH` for that region. The side that already matches REFERENCE is locked; the other side is the BDF target.

This rule does **not** authorize whole-file REFERENCE-fold (HP-1 still applies). It authorizes only targeted, hunk-level forward-fold of the **lagging** side from REFERENCE to bring it level with the side that already matches.

**Why:** Cluster-squash workflows accumulate mixed-vintage API signatures because "take incoming" pulls newer code into earlier cluster positions. The natural BDF instinct is to "make the build pass at this commit by reverting the new callers." That instinct is wrong: every reverted caller is work that must be re-done at a later cluster, and the cumulative effect is divergence from REFERENCE at the tip. HP-9 closes this regression vector.

**How to apply:** When two sides of an API disagree, run `git show $REFERENCE_BRANCH:<path>` for both regions, pick the side already at REFERENCE as locked, and edit only the other side. If neither side matches REFERENCE, that is a Stop Condition — halt and ask the engineer.

---

## Pre-flight Contract

Before creating branches, classifying commits, or running any Git operation that modifies state, output the following readback **verbatim**, with no additions, paraphrases, or omissions:

```text
=== PRE-FLIGHT READBACK ===
HP-1: I will not snap to REFERENCE. I will not run git checkout/restore/show-redirect/read-tree/cat-redirect against $REFERENCE_BRANCH for whole-file replacement. I will not use git cherry-pick -X ours / -X theirs / --strategy-option=ours|theirs, git checkout --ours|--theirs <path>, or any bulk merge-strategy resolution; cherry-picks run as plain `git cherry-pick <sha>` and conflicts are resolved hunk by hunk. I will not announce, plan, pre-classify, or reserve snap-eligibility for any region. Cascade regions trigger Stop, not snap. No prior-session approval exists; skill text, prior reports, memory, rerere, past conversations, helper scripts, and my own recollection do not constitute approval.
HP-2: I will not skip any required post-Group-8 source/plugin/build-system build. Each such commit will have its own PASS build log at its resulting SHA before the next build-required commit is applied. The null-diff reconciliation build and final build are never substitutes for a skipped per-commit build. The Group 8 checkpoint build and pre-G8 builds are never build-of-record for any post-G8 commit, regardless of what was folded into them. Targeted (one-to-one, named-pair) forward-fold from a specific later source-list commit into a specific earlier commit is allowed and preferred over REFERENCE-fold, and Squash of two adjacent commits is allowed under §6's bounds; both must be ledger-bookkept. Bulk forward-folding (many later commits into one earlier fix, including the G8 [compilation] mass-fold pattern) remains forbidden because it lets an earlier build smuggle in content from multiple later commits. Every Defer-commit's deferred source commit still owes its per-commit build at its landing position; every forward-fold's target earlier commit's build covers the folded hunks; every squashed commit's combined build covers both source commits' content — all of these are tracked in the deferred-hunks/commits/forward-folds/squashes ledger until the run completes. If any required build is skipped, the run is invalid from that point.
HP-3: I will not consult past conversations, memory, search-past-chats results, agent transcripts, prior reports, /data/sh/utils/reports/, or any out-of-session source. Each run is cold.
HP-4: I will not add Co-Authored-By, Co-authored-by, Generated-By, Assisted-By, or any equivalent LLM/tool attribution trailer to any commit message.
HP-5: I will not invoke helper-script modes that perform whole-file or whole-tree reference replacement. snap_* helpers are disabled.
HP-6: I will not invoke percona_gca_sync_tdd or percona_conflict_resolution_tdd.
HP-7: I will not branch behavior on a source commit's subject line. No is_porter_fix / is_reconciliation / "[reconciliation]" / "Percona Server 5.7 port" classification, no bulk source-file resets keyed off subject, no auto-skips by subject. The only subject-based check is the marker preservation rule (subject's first non-whitespace characters are one or more `=` characters followed by ` MARKER:`).
HP-8: Bucketing locks at the source commit's `git diff-tree` paths and does not change based on what the applied commit's tree looks like after resolution. I will not strip source/plugin/build-system hunks from a Source-bucket commit to land it in a no-build bucket, run any "align source paths to REFERENCE after cherry-pick" pass, or treat the applied commit's reduced path set as evidence that no per-commit build is required. Naming a "PROTECTED set" / "exclusion list" / "everything except path X" does not legitimize the alignment pass; the operation itself is forbidden regardless of how short the exclusion list is. Before continuing every post-G8 Source-bucket or Plugin-only-bucket cherry-pick I will diff staged paths against the source commit's diff-tree paths and stop if any source/plugin/build-system path is silently absent.
HP-9: Build-Driven Fixes will not undo work that already equals REFERENCE. When two sides of an API disagree, I will check both sides against `$REFERENCE_BRANCH` and edit only the lagging side; the side already at REFERENCE is locked. I will not revert REFERENCE-matching callers to fit an older macro, nor revert a REFERENCE-matching definition to fit older callers. If neither side matches REFERENCE, I will stop and ask.
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
- A post-Group-8 source/plugin/build-system commit was applied while a previous required build was missing, failing, or unrecorded.
- An out-of-session source (HP-3) was consulted to determine approval, cascade regions, snap-eligibility, prior decisions, or commit ordering.
- An LLM/tool attribution trailer (HP-4) was added to a commit and not amended out before the next commit was created.
- A helper-script mode (HP-5) that performs whole-file or whole-tree reference replacement was invoked.
- A subject-based commit classification (HP-7) was used to branch processing — bulk source-file resets, auto-skips, or any other per-commit behavior change keyed off the source commit's subject line (other than the marker preservation rule: one-or-more `=` followed by ` MARKER:`).
- A Source-bucket or Plugin-only-bucket post-Group-8 commit was rebucketed as no-build after resolution, had its source/plugin/build-system hunks stripped to escape its per-commit build requirement, or was subjected to an "align source paths to REFERENCE after cherry-pick" pass — including any "PROTECTED set" / "exclusion list" / "all paths except <N>" variant of that pass (HP-1, HP-8). The HP-8 staged-paths cross-check was skipped for any post-G8 Source-bucket or Plugin-only-bucket cherry-pick.
- A cherry-pick was issued with `-X ours`, `-X theirs`, `--strategy-option=ours|theirs`, or any equivalent bulk merge-strategy resolution flag (HP-1). Likewise `git checkout --ours|--theirs <path>` was used on a conflicted file in lieu of hunk-level resolution.
- A G8 `[compilation]` fix commit folded content from later commits beyond the minimum required to make the current G8 tree build, so that subsequent post-G8 Source-bucket cherry-picks resolved to empty/no-op and their per-commit builds were escaped (HP-2, HP-8, rule 10). Equivalently, a post-G8 build-fix performed a **bulk** forward-fold of hunks from multiple later source-list commits into one earlier fix commit (HP-2 bulk forward-fold ban). A single targeted (one-to-one) forward-fold per §6 Fold bounds is not a violation.
- The G8 checkpoint build, or any pre-G8 build, was cited as build-of-record for a post-G8 commit (HP-2).
- A Defer-commit decision violated any of the §6 bounds: missing or non-specific landing position; transitively deferred other commits; intervening commits broke for lack of the deferred content with the decision not reversed; bucket/build requirements not preserved at the landing position; the same source commit was Defer-committed more than once; ledger entry missing or never reconciled by Final Parity.
- A Forward-fold decision violated any of the §6 Fold bounds: more than one later source named in a single fold; non-minimal absorption of unrelated content; missing ledger entry; many-to-one bulk pattern in any form (G8 mass-fold or otherwise).
- A Squash decision violated any of the §6 Squash bounds: more than one later commit absorbed; missing quantitative justification; combined message did not preserve both original SHAs; bucket downgraded below the union of the two component buckets; second Squash applied to the combined commit; ledger entry missing.
- A Build-Driven Fix reverted a region that already matched `$REFERENCE_BRANCH` in order to fit a lagging counterpart, instead of forward-folding the lagging counterpart to REFERENCE (HP-9). Editing the REFERENCE-matching side is the violation regardless of whether the build subsequently passed.
- A Squash-cluster decision violated any of the §6 Squash-cluster bounds: cluster not in Phase B manifest; missing or vague engineer approval; partial cluster squash (members left non-squashed); combined commit at wrong position; bucket downgraded below the union of all member buckets; HP-8 cross-check skipped across the combined member-path union; nested cluster squash; ledger entry missing; engineer-approval quote missing.
- The attempt-budget cap was exceeded for a commit without an explicit engineer waiver recorded in the engineer-waivers ledger section. Silent iteration past the cap is a violation even if the build eventually passes.
- A still-deferred set was rebuilt via `git patch-id` without subtracting `applied-equivalents`, `squashed-commits.absorbed_sha`, and `squashed-clusters.member_sha`, causing already-resolved commits to be re-attempted with potentially divergent hunk-resolutions.
- Final Parity proceeded while the deferred-hunks/commits/forward-folds/squashes/clusters/applied-equivalents ledger still contained an unclosed entry.
- The pre-flight readback was missing, paraphrased, or skipped.
- A non-marker empty commit was created, or a marker commit's empty preservation was skipped.
- The Group 8 marker checkpoint build was skipped, or `[compilation]` fix commits were committed after the marker rather than before it.

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
2. Reordering or restructuring the source-list cursor is allowed **only** in these narrow forms, each of which requires explicit ledger bookkeeping:

   - **Conflict-motivated reorder** (§2 Choose Commit Order): chronological order produces a conflict and a specific reordered position demonstrably reduces that conflict to a smaller, hunk-level resolvable form.
   - **Build-motivated whole-commit deferral** (§6 Defer-commit): a commit is mostly premature at its current build position and a specific later landing position lets it build cleanly, under the strict bounds in §6 — a single, specific, named landing commit; no transitively-deferred other commits; intervening commits stay buildable; bucket/build requirements preserved; at most one Defer-commit per source commit; ledger entry required; convergence verified at Final Parity.
   - **Build-motivated whole-commit absorption** (§6 Squash): most of an adjacent later commit's content is required to make the current commit buildable, so the two source commits are combined into a single commit on `$OUTPUT_BRANCH`, under the strict bounds in §6 — exactly two adjacent source commits, specific quantitative justification, single combined build, ledger entry required.
   - **Build-motivated cluster absorption** (§6 Squash-cluster, **ENGINEER-APPROVED**): a tightly-coupled feature implementation cluster identified by Phase B (Prepare step 10) cannot land per-commit because each member depends on multiple other cluster members. All cluster members are combined into one commit, under the strict bounds in §6 Squash-cluster — pre-existing Phase B manifest entry, current-conversation engineer approval naming each member, all-or-none, single combined build, ledger entry required.
   - **Build-motivated hunk movement** (§6 Fold forward-fold, §5 deferred-hunks): individual hunks are folded from a later source-list commit into an earlier one's build-fix (forward-fold), or removed from an earlier commit and applied later with their dependent commit (deferred-hunks). The source-list cursor itself does not move; the hunks move within it. Each movement is a one-to-one ledger entry.

   Record every reordered, deferred, forward-folded, squashed, or cluster-squashed change with original index/SHA, new position/target, and the specific conflict or build failure that motivated the change in `$REPORT_FILE`. If restructuring is being considered for any other reason — convenience, throughput, "it just works better," "let me move several commits to a more convenient cluster" — do not do it. Multi-commit reorders, bulk forward-folds (many-to-one), Squash chains, and ad-hoc multi-commit groupings that do not fit within a single bounded action (including Squash-cluster's Phase-B-manifest-and-approval requirement) are a Stop Condition.
3. Root `$OUTPUT_BRANCH` at `$DESTINATION_BASE_BRANCH`, not at `$BASE_BRANCH`. The source range may be mysql-5.6.x-based while the output branch is mysql-5.7.x-based.
4. Resolve conflicts using `$REFERENCE_BRANCH` as hunk-level or logic-level guidance. `git show $REFERENCE_BRANCH:<path>` is allowed for inspection only (see HP-1). If `rerere` produces a resolution, do not stage it until you have:
   - Confirmed there are no `<<<<<<<`, `=======`, or `>>>>>>>` markers in the file with `git grep -nE '^(<<<<<<<|=======|>>>>>>>)' -- <path>`.
   - Compared the resolved hunks against the corresponding `$REFERENCE_BRANCH` region with `git diff` and confirmed the logic matches.
   - If either check is uncertain, treat the rerere resolution as untrusted and resolve manually.
5. When a commit does not build in isolation **after the Group 8 marker**, classify the failure before editing. The classification must be one of: missing dependency to fold (Fold — preferred source is a named later source-list commit via forward-fold; REFERENCE-fold is the fallback), premature hunk to defer (Defer, hunk-level — §5), premature whole commit to defer-forward to a specific later landing position (§6 Defer-commit), most of an adjacent later commit needed to make the current commit buildable (Squash — §6 Squash), incoherent source-only addition to remove (Remove), or unresolved design issue. **If the failure does not clearly fit one of these categories, stop and ask the engineer.** Do not classify as "fold" what is actually whole-file replacement. Do not classify as "fold" what is actually bulk pre-staging of many later commits' content into one earlier fix (HP-2 bulk forward-fold ban). Do not classify as "defer-commit" what is actually a multi-commit reorder (Defer-commit moves exactly one commit). Do not classify as "squash" what is actually a chain of squashes (Squash absorbs exactly one later commit).
6. First fold in the minimum necessary fixes from later commits on `$REFERENCE_BRANCH`. Defer hunks only when those reference-derived fixes touch more than the affected commit's own changed paths plus a small set of directly-required headers. **If isolating the cascade requires editing files that the current commit did not touch and that are not direct-dependency headers, stop and ask the engineer.** "Cascading and very large" is not a judgment call you make; it is a Stop Condition you trigger.
7. Use commit bucketing and incremental builds to improve throughput, but never use bucketing to skip, defer, or batch a required post-Group-8 build (see HP-2).
8. The exact marker subject `==================== MARKER: GROUP 8 — Upstream bug fixes ====================` is the hard build boundary. Treat every non-marker source-range commit before that marker as part of the No-build bucket regardless of changed paths, including commits that touch `sql/`, `include/`, `storage/`, `cmake/`, generated headers, or any other source/build-system path. If the marker is missing from the source list, **stop and ask the engineer** what boundary to use; do not infer a fallback.
9. For source-range commits before the Group 8 marker, do not run per-commit builds. The first build must start exactly at the Group 8 marker checkpoint, before the marker commit itself is created. For source-range commits after the Group 8 marker, build-verify every completed source/plugin/build-system commit at that commit's resulting SHA before applying the next build-required commit. Only the destination base commit, pre-Group-8 source-range commits, and empty marker commits are exempt.
10. If the first build run at the Group 8 marker checkpoint fails with compilation issues, apply the minimal fixes in one or more new commits **before** preserving the `==================== MARKER: GROUP 8 — Upstream bug fixes ====================` marker itself. Each fix commit subject must start with the literal prefix `[compilation]`, then rebuild before preserving the marker and proceeding. The marker commit, when preserved, must be authored after all `[compilation]` fix commits — verify this with `git log --oneline` before continuing. "Minimal" means the smallest set of edits that makes the current G8 tree compile and link; it does **not** include folding REFERENCE state that addresses compile errors which would only be triggered by later commits. Pre-staging post-G8 content into a G8 `[compilation]` commit is forbidden (HP-2, HP-8): it converts later Source-bucket commits into empty/no-op cherry-picks and lets the G8 build act as a substitute build-of-record for content that belongs to post-G8 commits.
11. Never carry a known non-buildable build-required commit forward (see HP-2). If the current build-required commit cannot be made buildable with at most three minimum-fix attempts, stop and ask.
12. Do not rely on a later merge, final source commit, reconciliation commit, or final build to make earlier unbuildable commits coherent or to replace missing required post-Group-8 build evidence.
13. Preserve empty marker commits whose subject starts with one or more `=` characters followed by ` MARKER:` (e.g. `=== MARKER: GROUP 1 — Squashes ===` or `==================== MARKER: GROUP 8 — Upstream bug fixes ====================`). Use `git cherry-pick --allow-empty <sha>` when possible; if Git reports a marker cherry-pick as empty, create the marker with `git commit --allow-empty -C <sha>` from the cherry-pick state. Preserve the original marker subject/body (including the original `=`-width) and record the new SHA. Do not build after an empty marker because it changes no tree content. **Detection of "marker" is syntactic and width-tolerant**: the source commit subject's first non-whitespace characters must be one or more `=` characters immediately followed by ` MARKER:`. The trailing `=` run width may differ from the leading run; only the leading prefix is checked. If the subject merely contains the word "marker" without a leading `=`-followed-by-`MARKER:` prefix, it is not a marker.
14. Do not create empty commits for non-marker commits. After conflict resolution, hunk deferral, or build-fix folding, if `git diff --cached --quiet && git diff --quiet` reports no changes, the cherry-pick is empty. Skip it with `git cherry-pick --skip` (or abort/reset if no cherry-pick state remains). Document the skip with the original SHA, subject, and reason.
15. Do not add LLM/tool attribution trailers (see HP-4). Inspect every commit message before committing.
16. After all source commits are replayed and every required post-Group-8 build record is present, reconcile the tree to a null diff with `$REFERENCE_BRANCH` through explicit path/hunk-level reconciliation commits. Do not use tree snapping (HP-1).
17. After a null-diff tree exists, run a final build with the required build configuration before declaring completion.
18. If the null-diff tree fails the final build because `$REFERENCE_BRANCH` itself contains code incompatible with the required toolchain, **stop and ask the engineer** whether to keep the null-diff failing tree or add a narrow final build-fix commit. Only with explicit current-conversation approval may the final branch intentionally retain a non-null residual diff. Document the null-diff SHA, final build-fix SHA, residual paths/hunks, and both build results.
19. Do not use scripts from `/data/sh/utils`. Do not read files from `/data/sh/utils/reports/`. Writing `$REPORT_FILE` under `/data/sh/utils/reports/` is allowed (this is an output-only path).

---

## Build Configuration

Use an out-of-tree build directory at `$BUILD_DIR` under the dedicated `/tmp` run directory (`$RUN_DIR`), and configure with these options unless the task explicitly overrides them:

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

A successful build means both CMake configuration and the build step complete without errors. Capture each build in a per-commit log named with the source commit index and SHA; per-batch logs are allowed only for path-classified post-Group-8 no-build batches. Prefer incremental builds in a stable `$BUILD_DIR` to preserve ccache and CMake state. Reconfigure or clean only when forced by CMake/cache breakage or a deep generated-header/build-system change.

If a parallel build exits with truncated diagnostics, rerun `make` in the same build directory, optionally with `-j1`, **only** to expose the first actionable compiler or linker error. After identifying the error, rerun the normal configured build to confirm it still fails the same way before editing any source.

Use `ccache` through CMake compiler launchers, not by replacing `CC` or `CXX`; the underlying compilers remain `gcc-9` and `g++-9`. Do not use MySQL helper-script directories such as `BUILD` or `BUILD-CMAKE` as build output directories.

---

## Workflow

### 1. Prepare

1. Confirm all required inputs are set: `$BASE_BRANCH`, `$TIP_BRANCH`, `$DESTINATION_BASE_BRANCH`, `$REFERENCE_BRANCH`, `$OUTPUT_BRANCH`, `$LLM_MODEL`, `$REPORT_FILE`.
2. **Output the Pre-flight Contract readback verbatim** (see [Pre-flight Contract](#pre-flight-contract)). If the readback is missing, paraphrased, or interleaved, abort the run.
3. Confirm the working tree is clean before starting.
4. If `$REPORT_FILE` is not specified, set it to `/data/sh/utils/reports/${LLM_MODEL}_${OUTPUT_BRANCH}.md`.
5. Set `$RUN_DIR` to a dedicated subdirectory under `/tmp` if not specified, e.g. `/tmp/ps-replay-${OUTPUT_BRANCH}`. Set `$BUILD_DIR` to `$RUN_DIR/build` if not specified. Store all transient run files, generated source lists, ledgers, Phase B artifacts, HP-8 scratch files, and build logs under `$RUN_DIR`.
6. Generate the ordered source list:

   ```sh
   git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH
   ```

7. Inspect the ordered source list subjects and verify the exact marker `==================== MARKER: GROUP 8 — Upstream bug fixes ====================` exists. Record its 1-based source index as the Group 8 boundary. **If it is missing, stop and ask the engineer.** Do not infer a fallback boundary; do not select a "nearby" marker; do not proceed without one.
8. Create `$OUTPUT_BRANCH` from `$DESTINATION_BASE_BRANCH`.
9. Start a **deferred-hunks/commits/forward-folds/squashes/clusters/applied-equivalents ledger** for content whose position in the output history differs from its position in the source list. The ledger has six sections:

   - **Deferred hunks** (backward defer, hunk-level — §5): hunks removed from an earlier commit, each with source commit, file, short reason, and target later commit that will re-apply the hunk.
   - **Deferred commits** (backward defer, whole-commit-level — §6 Defer-commit): whole commits postponed forward, each with original index/SHA, original subject, landing index/SHA, motivating build failure, the dependency the landing commit provides, and (once applied) the new `$OUTPUT_BRANCH` SHA and build log path.
   - **Forward-folded hunks** (forward fold, hunk-level — §6 Fold preferred source): hunks pulled from a later source-list commit into an earlier commit's build-fix, each with later-source idx/SHA, target earlier idx/SHA on `$OUTPUT_BRANCH`, the folded paths/hunks, motivating build failure, and the build log path at the target SHA. When the later-source commit is reached in the replay, the entry accounts for its now-absent paths in the HP-8 staged-paths cross-check.
   - **Squashed commits** (forward fold, whole-commit-level — §6 Squash): pairs of adjacent source-list commits combined into one commit on `$OUTPUT_BRANCH`, each with both original SHAs/subjects, the combined SHA, the build log path at the combined SHA, motivating build failure, and the quantitative justification for "most of N+1 was needed for N."
   - **Squashed clusters** (forward fold, multi-commit, ENGINEER-APPROVED — §6 Squash-cluster): groups of N non-adjacent source-list commits combined into one commit on `$OUTPUT_BRANCH`, each with: cluster name, list of (idx, sha, subject) members, combined SHA, build log path at combined SHA, motivating cluster-blocked classifier output, and explicit engineer-approval text quoting the current-conversation message.
   - **Applied-equivalents** (no-op false-positive shielding): source-list commits whose content was applied to `$OUTPUT_BRANCH` with modifications (e.g. via forward-fold, Align, or hunk-defer at the original position), making the post-hoc `git patch-id` of the source commit not match anything on `$OUTPUT_BRANCH`. Without this section, a still-deferred-list rebuilt by `patch-id` after the fact will list these commits as deferred, and the driver will waste cycles re-attempting them. Each entry: source idx/SHA, new SHA on `$OUTPUT_BRANCH`, reason (`forward-folded` / `align-only` / `partial-hunk` / `squash-component`), and pointer to the ledger entry that records the actual landing.

   All sections must converge before Final Parity: every ledger entry must record the SHA(s) on `$OUTPUT_BRANCH` where the moved/folded/squashed content actually lives, with a PASS build log at that SHA where applicable. Final Parity (§10) verifies the ledger is closed — every entry has a recorded landing/target/combined SHA and (for build-required entries) a PASS log.

   **Ledger storage**: write ledger to `$RUN_DIR/ledger.tsv`. Do not write replay state under the worktree (for example `.ps-replay/`). Keep run state in the dedicated `/tmp` subdirectory so the source tree only contains replayed code changes. Because `/tmp` can be cleared by reboot or cleanup, reproduce the ledger summary in `$REPORT_FILE` after every material state transition; loss of `$RUN_DIR` mid-run is a Stop Condition unless the ledger can be reconstructed exactly from `$REPORT_FILE` and Git history.

10. **Phase B: Pre-flight cluster analysis.** Before any cherry-pick, build a symbol→commit index and a cluster manifest. This converts what would otherwise be ~10+ continuation sessions of trial-and-error into one planning pass.

    For each source-list commit `c`:
    - Extract the symbols `c` *adds* (new function declarations, new struct members, new enum values, new `#define`s, new file creations) via `git diff` + identifier grep against the parent state.
    - Extract the symbols `c` *uses* (function calls, struct-member references, enum values, macros).

    Build `symbol-index.tsv` under `$RUN_DIR`:

    ```
    symbol<TAB>defining_idx<TAB>defining_sha<TAB>kind (decl/member/enum/macro/file)
    ```

    Build a per-commit dependency edge list: for each commit `c`, list the symbols `c` uses that are defined at idx > c's idx (forward dependencies). Each such edge marks `c` as dependent on the defining commit.

    Group commits into **clusters**: a cluster is a strongly-connected component of the dependency graph (mutual or near-mutual dependencies), or a chain of unidirectional dependencies whose head is not within reach of single-hunk forward-fold. The clustering output `clusters.tsv` records:

    ```
    cluster_name<TAB>idx_range<TAB>member_count<TAB>shared_symbols<TAB>suggested_action
    ```

    `cluster_name` is derived from the longest shared subject prefix or the dominant feature keyword in the cluster's symbols (e.g. `threadpool`, `log_archiving`, `fake_changes`, `super_read_only`, `log_slow_filter`). `suggested_action` is one of:

    - `per-commit` — fewer than 3 forward dependencies per member; expected to land via standard §6 actions
    - `defer-cluster-to-tail` — all members can be deferred to land after `idx M` where the cluster's last entry-point dependency lands
    - `squash-cluster` — members form a mutual-dependency knot where each blocks the others; requires §6 Squash-cluster action (engineer approval)

    Present the cluster manifest to the engineer **before** beginning the replay. The engineer may pre-approve `squash-cluster` actions for named clusters at this point, which is then recorded in the squashed-clusters ledger section. Pre-approval here is far cheaper than discovering the same cluster N times across N continuation sessions.

11. **Effort budget envelope.** Ask the engineer for the run's effort budget, with these explicit options:

    - **Per-commit-only, hard 3-attempt cap (skill default)**: stop at the first plateau; deliver whatever per-commit-buildable subset is achieved.
    - **Per-commit-only, tunable cap**: engineer specifies a higher attempt budget (5? 10? unlimited?) per commit. Recorded as an engineer waiver in the ledger (see HP-2/§6).
    - **Per-commit + cluster-squash**: per-commit budget for non-clustered commits; for commits classified as `cluster-blocked`, apply §6 Squash-cluster (engineer-pre-approved per cluster).
    - **Full convergence**: keep going until either every source-list commit has landed (with whatever combination of per-commit, Squash, Squash-cluster, deferral, and final reconciliation is needed) or the engineer terminates the run.

    Record the chosen envelope in `$REPORT_FILE` under a `Run envelope` section. The envelope shapes which §6 actions are available without further consultation (e.g. Squash-cluster is *only* available with envelope-3-or-4 plus per-cluster pre-approval).

### 2. Choose Commit Order

Default to chronological order from `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH`.

Reorder a commit only if all three conditions hold:

1. The chronological position produces a conflict that is **not** safely resolvable by hunk-level edits.
2. A specific alternative position resolves the conflict without producing new conflicts of equal or greater severity.
3. The reordering is recorded in `$REPORT_FILE` with original index, new index, and the specific conflict text that motivated the change.

If conditions 1 and 2 cannot both be demonstrated before the reorder, do not reorder. Convenience-driven reordering is forbidden.

#### Bucketing

Bucket each commit before applying it. Bucketing is a syntactic operation, not a judgment call:

1. **Empty-marker bucket**: source commit subject's first non-whitespace characters are one or more `=` characters immediately followed by ` MARKER:` (any `=`-prefix width). Always preserve as empty commit, regardless of position relative to Group 8. Do not build after.
2. **Forced pre-Group-8 no-build bucket**: source commit's 1-based index is less than the Group 8 marker's index, AND it is not itself the Group 8 marker, AND it is not in the Empty-marker bucket. Apply in chronological batches without running builds. This bucket overrides any path-based classification.
3. **Boundary-build checkpoint**: source commit's subject is exactly `==================== MARKER: GROUP 8 — Upstream bug fixes ====================`. Run the first build before preserving the marker as an empty commit. Create any required `[compilation]` fix commits before the marker itself.
4. **Path-classified buckets** (post-Group-8 only): for non-marker commits after Group 8, run `git diff-tree --no-commit-id --name-only -r <source-sha>` against the **source commit's SHA** (from `$BASE_BRANCH..$TIP_BRANCH`) — never the applied commit's SHA, never the staged tree, never the post-resolution amended commit — and classify by changed paths.

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

The bucket assigned here is **locked** (HP-8). It does not change based on what the applied commit's diff-tree looks like after conflict resolution, deferral, alignment, or amendment. The only legitimate way for a Source-bucket commit not to produce a per-commit build is rule 14: the cherry-pick is fully empty after hunk-level resolution and is therefore skipped — in which case no commit exists, so no build is owed. A non-empty Source-bucket commit whose applied diff has been reduced to no-build paths only is the forbidden case, and the HP-8 staged-paths cross-check in §3 must catch it before the cherry-pick is continued.

If a path-classified no-build batch after Group 8 fails its boundary build, stop, identify the source commit that caused the failure, document the mis-bucket as a violation in `$REPORT_FILE`, and resume with source-bucket rules. If a source/plugin/build-system commit after Group 8 was applied without its required immediate build, the run is invalid (see HP-2 and Validity Invariants).

### 3. Cherry-Pick One Commit

For each selected commit:

```sh
git cherry-pick <sha>
```

The cherry-pick command must be exactly this — plain `git cherry-pick <sha>`, with `--allow-empty` added **only** for marker commits per rule 13. **Do not** pass `-X ours`, `-X theirs`, `-Xours`, `-Xtheirs`, `--strategy-option=ours`, `--strategy-option=theirs`, or any other merge-strategy resolution flag (HP-1). Likewise do not pre-set `merge.conflictStyle` or any config that biases conflict resolution toward one side for this run.

If it applies cleanly, **first check tree-equality** before proceeding to the build step:

- If `git diff HEAD~1 HEAD --quiet` (the new commit's tree equals the previous tip's tree) AND the commit message body is not a marker, the cherry-pick produced an empty commit — git reports `nothing to commit, working tree clean` and may not have advanced HEAD at all. Apply rule 14: drop the cherry-pick state (`git cherry-pick --skip` or `git reset --hard HEAD`) and record the source SHA in the **applied-equivalents** ledger section (Prepare step 9) as kind `empty-skip-equivalent`. Do NOT re-defer this commit — the still-deferred list rebuilt by post-hoc `patch-id` will list it as deferred, but it is in fact resolved (its content is already on `$OUTPUT_BRANCH` via an earlier landing).

This short-circuit prevents the canonical false-positive: a commit that was empty-skipped during an earlier pass gets re-attempted in a later session because `git patch-id <empty>` produces no entry to match against `$OUTPUT_BRANCH`'s patch-id index. The applied-equivalents ledger entry shields it from future re-attempts.

If it conflicts:

1. Identify every conflicted file with `git diff --name-only --diff-filter=U`.
2. For each conflicted file, check whether `rerere` already resolved it:
   - Run `git grep -nE '^(<<<<<<<|=======|>>>>>>>)' -- <path>`. If markers remain, treat as unresolved.
   - If markers are absent, compare hunks against the corresponding `$REFERENCE_BRANCH` region with `git diff <ref-sha>:<path> -- <path>`. If the rerere resolution does not match the reference's logic at the conflict regions, treat as untrusted and resolve manually.
3. By default, replace only the conflict regions with the corresponding content from `$REFERENCE_BRANCH` and leave unrelated local context untouched. Use a text editor or `sed` to edit the worktree file directly, transcribing the reference-region content into the conflict region. **Do not use any HP-1 forbidden command** to perform this transcription. In particular, do **not** use `git checkout --ours <path>` or `git checkout --theirs <path>` to bulk-accept one side of the conflict — those are HP-1 forbidden bulk merge-strategy resolutions.
4. **Whole-file replacement is forbidden** (HP-1) even for test fixtures, generated/preprocessed headers, version files, or coherent API families. If hunk-level resolution is not feasible, stop and ask. "Whole-file replacement minus a PROTECTED set of paths" is still whole-file replacement on the unprotected paths and is forbidden under HP-1 / HP-8 regardless of how small or principled the exclusion list looks.
5. If the file does not exist on `$REFERENCE_BRANCH`, the conflict is between a local addition and a reference-side absence. Remove the conflicting addition hunk only if hunk-level analysis confirms the reference's deletion is the correct logic. Do not delete the whole file unless the entire file is the conflicting change and the engineer has explicitly approved removal in the current conversation.
6. Stage the resolved files: `git add <resolved-files>`.
7. **HP-8 staged-paths cross-check (mandatory for every post-Group-8 Source-bucket and Plugin-only-bucket cherry-pick, whether the cherry-pick conflicted or applied cleanly).** Before continuing, compare the staged tree's touched paths to the source commit's touched paths:

   ```sh
   git diff-tree --no-commit-id --name-only -r <source-sha> | sort -u > "$RUN_DIR/hp8-src-paths.txt"
   { git diff --cached --name-only; git diff --name-only; } | sort -u > "$RUN_DIR/hp8-staged-paths.txt"
   comm -23 "$RUN_DIR/hp8-src-paths.txt" "$RUN_DIR/hp8-staged-paths.txt"
   ```

   For every source/plugin/build-system path that appears in `hp8-src-paths.txt` but not in `hp8-staged-paths.txt`, the source commit's modification of that path is silently absent. Two cases are acceptable:

   1. The full cherry-pick is empty (no diff on any path, staged or unstaged). Apply rule 14 and `git cherry-pick --skip`. No build is owed.
   2. The omission is bounded deferral recorded in the deferred-hunks ledger with a specific named later target commit (rule 5 / §5 bounds).

   Any other case — non-empty cherry-pick where source/plugin/build-system paths from the source commit are silently absent — is an **HP-8 Stop Condition**. Abort the cherry-pick (`git cherry-pick --abort`), return to `LAST_GOOD`, and ask the engineer. Do not amend, do not run an "alignment" pass, do not strip more to make the commit cleaner, do not rebucket as no-build.

8. Continue the cherry-pick: `git cherry-pick --continue`.

If safe hunk-level resolution is not possible at any step, **stop and ask the engineer**. Do not escalate from hunk-level to whole-file replacement on your own authority. Do not "align" the staged tree to `$REFERENCE_BRANCH` after resolution; the conflict regions resolved during the cherry-pick are the only places where `$REFERENCE_BRANCH` content is permitted to enter the worktree, and only via hand-transcription, not via HP-1-forbidden commands.

### 4. Preserve Marker Commits And Drop Other Empty Cherry-Picks

#### Marker commits (subject begins with one or more `=` followed by ` MARKER:`)

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

For each post-Group-8 build failure:

1. Identify the first real error, not just the final `Error 2`. Use `ps_replay_errors.py` if the log is truncated.
2. Map the error to the smallest inconsistent surface: declaration/type mismatch, enum/table mismatch, missing member, missing source file, incoherent CMake entry, unresolved symbol, or ABI check mismatch.
3. **Classify the error using the Phase B symbol index (`$RUN_DIR/symbol-index.tsv`)** before choosing any action. For each undefined identifier in the error, look up its defining commit:

    - `STALE-CACHE` — the defining commit is already on `$OUTPUT_BRANCH` (applied or applied-equivalent). The build cache is stale; reconfigure or rebuild clean before treating this as a real failure.
    - `FUTURE-FOLD-CANDIDATE` — the defining commit is later in the source list AND is the *only* such forward dependency for this commit AND its hunk is small. Standard §6 Fold (forward-fold) applies.
    - `CLUSTER-BLOCKED` — the defining commit is in a cluster (from the Phase B cluster manifest) AND the cluster's `suggested_action` is `defer-cluster-to-tail` or `squash-cluster`. Do NOT attempt single-symbol forward-folds; either defer this commit to the cluster's landing position or invoke Squash-cluster.
    - `INVARIANT-BREAK` — the error is a `compile_time_assert(...)` failure, a signature mismatch (`too few arguments`), a linker error, an array-size assertion, or any other error that indicates adding a single declaration would silently violate an invariant elsewhere (the canonical example: adding `SQLCOM_SHOW_SLAVE_NOLOCK_STAT` to the enum without also extending `com_status_vars` breaks `sizeof(com_status_vars)/sizeof(...) == SQLCOM_END`). Single-symbol forward-fold is dangerous here — verify the surrounding invariants before folding, or escalate to Squash/Squash-cluster.
    - `UNRESOLVED` — no defining commit found in the source list, or the missing symbol is not produced by any later commit. Likely a toolchain mismatch (see rule 18 / G8 `[compilation]` fix), a hand-aligned typo, or a baseline incompatibility.

    The classifier output determines which §6 actions are viable below. Skip the manual symbol-search step — the index is authoritative.

4. Compare the current commit, `HEAD^`, the source commit, and `$REFERENCE_BRANCH` for the affected files using `git diff` and `git show <ref-sha>:<path>` (inspection only — see HP-1).
5. Choose **exactly one** of these actions:
   - **Fold**: add the smallest required declaration/member/enum entry to the current commit so that it builds. Two sources are allowed, in this preference order:

     1. **Forward-fold from a specific named later source-list commit** (**preferred**). When the missing content is cleanly attributable to a specific later commit `idx M, <sha>` in `$BASE_BRANCH..$TIP_BRANCH`, fold exactly the hunks needed from that commit into the current commit. The later commit reflects the *authored intent* for that content — it is what the original engineer actually wrote for this dependency — and is therefore more attributable and more minimal than the final REFERENCE state. Use `git show <later-sha> -- <path>` for inspection and hand-transcribe the needed hunk(s).

        Bounds for forward-fold (every bound must hold; if any is uncertain, choose Stop):

        a. **One named source.** The forward-folded hunks come from a single specifically named later source-list commit, not from "later commits in general" or from a scan of REFERENCE-vs-HEAD.
        b. **Minimal hunks.** Fold only the hunks needed to make the current commit build. Do not absorb unrelated content from the later commit. If "minimal" turns out to mean "most of the later commit," use **Squash** (below) instead.
        c. **Bookkept.** Record in the forward-folded-hunks section of the deferred ledger: source commit (the later commit by idx/SHA), target commit (the current commit by idx/SHA on `$OUTPUT_BRANCH`), the folded hunks (file paths), and the build failure that motivated the fold. When the source later commit is reached in the replay, the HP-8 staged-paths cross-check uses the ledger to account for the now-absent folded paths (see HP-8). If, after subtracting the folded hunks, the source later commit becomes empty, it is skipped per rule 14; if it retains content, it is cherry-picked normally and gets its own per-commit build per HP-2.
        d. **No bulk forward-fold.** Forward-folding hunks from *multiple* later commits into a single earlier fix commit is forbidden (HP-2 G8 mass-fold ban). One earlier-target ↔ one later-source pair per forward-fold; multiple forward-folds are allowed but each must be a separate pairwise entry in the ledger. Do **not** collapse many forward-folds into one G8 `[compilation]` mass-fold commit; the G8 `[compilation]` commits remain reserved for fixing the current G8 tree only (rule 10).
        e. **No build-of-record laundering.** A forward-fold is *not* a substitute for the later commit's own per-commit build when the later commit retains non-folded content. HP-2's "no earlier build is build-of-record for content that belongs to a later commit" still applies *across multiple later commits*. The same-commit case is fine: a forward-folded hunk's build-of-record is the target (earlier) commit's resulting SHA, because that's where the content now lives.

     2. **REFERENCE-fold** (**fallback**). When the missing content cannot be cleanly attributed to a specific later source-list commit — for example, when it is a cross-cutting fix in REFERENCE that doesn't correspond to one source-list commit, or when the candidate later commit also adds a large amount of unrelated content you don't want to absorb — fold the minimum needed reference declaration/member/enum entry from `$REFERENCE_BRANCH`'s tree, hand-transcribed via `git show $REFERENCE_BRANCH:<path>` (inspection only — HP-1). REFERENCE-fold is allowed but disfavored relative to forward-fold; the report must record which source was used and why.

     Whichever source is used: do not classify whole-file replacement as "Fold," do not classify a multi-commit absorption as "Fold" (use Squash), and do not classify a G8-style bulk pre-staging of many later commits as "Fold" (HP-2).

   - **Defer** (hunk-level): remove a premature hunk from the current commit and apply it later with its dependent implementation (subject to the deferral bounds in §5).
   - **Defer-commit** (whole-commit-level): postpone the **entire** current commit to a specific later source-list position where its dependencies have arrived, instead of forcing a sweeping Fold into the current branch. Use this when the failing commit is *mostly* premature for the current build point — i.e., when the minimum Fold required to make it build would itself span **multiple** later source-list commits and would be functionally indistinguishable from a forbidden *bulk* forward-fold (HP-2). A single targeted forward-fold from one specific later commit is the preferred Fold (see Fold above); a Squash absorbs one adjacent later commit. Defer-commit is for the case where neither one targeted forward-fold nor one Squash is enough — i.e., where dependencies on *many* later commits would otherwise need to be pulled backward; moving the current commit forward to where its prerequisites live is cleaner than pulling many prerequisites backward.

     Bounds (every bound must hold; if any is uncertain, choose Stop):

     a. **Specific named landing position.** Identify a specific later source-list commit (by index and SHA, e.g. `idx M, <sha>`) that introduces the missing dependency. The deferred commit will be cherry-picked immediately after that landing commit's required build PASS. "Somewhere later in the post-G8 range" is not specific enough.
     b. **No transitive deferral.** Deferring this commit must **not** require also deferring any other commit. If reasoning indicates "I need to defer N and also N+1 and also N+3," the cascade is not isolated to a single deferral and the situation is a Stop Condition, not a chain of Defer-commits.
     c. **Intervening commits remain buildable.** Each intervening commit (between the original position and the landing position) must continue to build under its own bucket without the deferred commit's content. If any intervening commit later fails its required build because the deferred commit's content is missing, the original Defer-commit decision was wrong — Stop and ask whether to revert the deferral.
     d. **Bucket and build requirements are preserved.** The deferred commit's bucket stays locked at its source-SHA classification (HP-8). When cherry-picked at the landing position, all normal rules apply: hunk-level conflict resolution (§3), HP-8 staged-paths cross-check, and — for Source-bucket and Plugin-only-bucket commits — its own per-commit build at the resulting SHA before the next build-required commit (HP-2). Defer-commit is **not** a way to escape any per-commit build; it only moves *when* the build is required, not *whether*.
     e. **At most one Defer-commit per source commit.** A deferred commit cannot be deferred again to a still-later position; bouncing a commit forward repeatedly is forbidden. If the deferred commit still cannot build at its landing position after its remaining attempts, choose Stop.
     f. **Ledger entry required.** Record in the deferred-commits ledger (see §1 Prepare): original source index/SHA, original subject, landing source index/SHA, the specific build failure that motivated deferral, and the dependency the landing commit provides. Update the ledger when the commit is finally applied at its new position, recording the new `$OUTPUT_BRANCH` SHA and its build log path.
     g. **Convergence required.** Every Defer-commit must actually be applied before Final Parity (§10). The Final Parity audit (rule 16 / §10) verifies that the deferred-commits ledger is empty (every deferred commit has a recorded landing SHA and PASS build). If any deferred commit is still unapplied at Final Parity time, that is a Stop Condition — the run cannot complete with deferred content unaccounted for.

     Defer-commit is **not** a substitute for fixing a small/clean Fold/Defer/Align/Remove or a clean Squash. Prefer the narrower actions first; use Defer-commit when the alternative would be absorbing content from *multiple* later commits into the current one. (When only *one* later commit's content needs to be absorbed and most of it is needed, use **Squash** below.)

   - **Squash** (merge two adjacent commits): when **most** of the content of commit `idx N+1` is required to make commit `idx N` buildable — to the point where a forward-fold would absorb most of N+1's hunks anyway and leave N+1 with only a sliver remainder — combine N and N+1 into a single commit on `$OUTPUT_BRANCH` instead. Squash is the clean alternative to "forward-fold most of N+1 into N, then apply a tiny N+1 remainder"; it eliminates the awkward residual commit.

     Bounds (every bound must hold; if any is uncertain, choose Stop):

     a. **Exactly two source commits, adjacent in dependency order.** Squash absorbs commit N+1 (or another specifically named later commit `idx M, <sha>`) into commit N. It must be a single pair, not a chain `{N, N+1, N+2, ...}`. If multiple later commits would need to be absorbed, use one or more targeted forward-folds with proper ledger entries, or Defer-commit, or Stop and ask — do not chain Squashes.
     b. **Specific quantitative justification.** "Most" must be concrete: at least a majority of the later commit's hunks are required for the earlier commit to build, or the later commit is logically a continuation/fix-up of the earlier commit's intent rather than an independent change. A vague "they feel related" or "it's cleaner this way" is not enough.
     c. **Mechanics.** Cherry-pick N onto `$OUTPUT_BRANCH`, resolve any conflicts hunk-level per §3 (no `-X ours`, no alignment passes — HP-1). Then `git cherry-pick --no-commit <sha-of-N+1>`, resolve its conflicts hunk-level, and `git commit --amend` (or stage-then-commit) to produce a single combined commit. The combined commit's message must preserve both original subjects (joined with a separator) and explicitly record both original SHAs in the body, e.g.:

        ```text
        <subject of N>; squashed with: <subject of N+1>

        Squashed commits:
          - <original sha of N>
          - <original sha of N+1>

        <combined body text, if any>
        ```

     d. **One build, at the combined SHA.** The squashed commit's bucket is the union of the two component buckets — if either was Source bucket (HP-8 extension override or path prefix), the combined commit is Source bucket and gets its own per-commit build at the combined SHA. This single build is the build-of-record for the combined content. This is consistent with HP-2: the content's build happens at the SHA where the content actually lives in the output history.
     e. **No skipped builds for the absorbed commit.** Commit N+1's source SHA does not get its own resulting SHA on `$OUTPUT_BRANCH`, because it was absorbed. The combined commit's build covers it. The HP-8 staged-paths cross-check at the squash time sums both commits' source-path lists and checks that the combined staged tree includes them all (or accounts for any absence via the deferred ledger).
     f. **At most one Squash per source commit.** Commit N can be squashed with at most one later commit; once squashed, the combined commit cannot itself be squashed again with a yet-later commit.
     g. **Ledger entry required.** Record in the squashed-commits section of the deferred ledger: both original SHAs and subjects, the combined SHA on `$OUTPUT_BRANCH`, the build log path at that SHA, the motivating build failure, and the quantitative justification (proportion of N+1's hunks needed for N).
     h. **N+1 is removed from the source-list cursor.** When the replay's cursor would have reached the absorbed commit's index, skip it — the ledger entry serves as the record of where its content went. Document the skip in the per-skipped/squashed-commit section of the report.

     Squash is the right action when forward-fold would leave a clearly-non-empty but uselessly-small remainder; it is not a generic "let me merge two commits for tidiness." If the later commit's residual after forward-fold would still be a meaningful independent change, prefer forward-fold and keep the later commit.

   - **Squash-cluster** (combine N non-adjacent commits into one, **ENGINEER APPROVAL REQUIRED**): when the §6 step 3 classifier reports `CLUSTER-BLOCKED` for a commit whose cluster (from Phase B Prepare step 10) is marked `suggested_action=squash-cluster`, combine all N members of that cluster into a single squash commit at the cluster's earliest member position. This is the canonical action for tightly-coupled feature implementations (threadpool internals, log archiving, fake_changes, super_read_only families, etc.) where each member depends on multiple other cluster members and no single forward-fold or pairwise Squash can break the knot.

     Bounds (every bound must hold; if any is uncertain, choose Stop):

     a. **Pre-existing cluster manifest entry.** The cluster must be in `$RUN_DIR/clusters.tsv` from Phase B (Prepare step 10). Squash-cluster cannot be invoked for an ad-hoc grouping discovered during replay — that path is Defer-commit (one commit) or Squash (two adjacent commits) instead.
     b. **Engineer approval in current conversation.** The engineer must have approved this specific cluster (named by `cluster_name` and the full member idx list) in the current conversation, either at Prepare time (preferred — when the cluster manifest was first presented) or at the moment the classifier first reports `CLUSTER-BLOCKED` for one of its members. Pre-approval of every cluster in a single engineer message at Prepare time is the most efficient path. Approval phrasing like "approved" or "squash that cluster" against the explicit member list is required; vague "go ahead with squashes as needed" is not approval.
     c. **All members or none.** The squash combines all listed cluster members. Partial cluster squashes are forbidden: a residual non-squashed cluster member would still hit `CLUSTER-BLOCKED` on its own.
     d. **Landing position.** The combined commit lands at the cluster's earliest-member source-list position (i.e. the position the first cluster member would have occupied). All other members are removed from the source-list cursor.
     e. **Mechanics.** Cherry-pick the first cluster member onto `$OUTPUT_BRANCH`; for each subsequent member, run `git cherry-pick --no-commit <member-sha>`, resolve any hunk-level conflicts per §3, and `git commit --amend` at the end. The combined commit message must record `Squashed cluster: <cluster_name>` in the subject and list every member's `idx, sha, original subject` in the body.
     f. **One build, at the combined SHA.** The cluster's bucket is the union of all members' buckets — if any member is Source bucket, the combined commit is Source bucket and gets its own per-commit build at the combined SHA. This single build is the build-of-record for all members' content. Consistent with HP-2: builds happen where content lives.
     g. **HP-8 cross-check across all members.** The combined staged tree must include the union of all members' `git diff-tree` paths (or each absence accounted for by a deferred-hunks/forward-folded-hunks ledger entry that names a specific other commit on `$OUTPUT_BRANCH` as the carrier). Naked path absences are an HP-8 violation.
     h. **No Squash-cluster of clusters.** A cluster cannot itself be a member of a larger cluster squash. If two clusters appear to require joint squashing, present that to the engineer as a re-clustering decision in Phase B, not as a nested operation.
     i. **Ledger entry required.** Record in the squashed-clusters section of the ledger: cluster name, member list, combined SHA, build log path with PASS result, the classifier output that motivated the squash, and the exact engineer-approval text quoted from the current conversation.

     Squash-cluster is the **last** of the §6 forward actions to consider: prefer Fold, Defer-hunk, Defer-commit, and pairwise Squash first. Squash-cluster has the broadest scope (and the least precision per-commit-buildability-wise), so it is reserved for cases where the per-commit ceiling has been established and the engineer has approved the trade-off.

   - **Align hunks**: edit the smallest coherent set of hunks to match the reference API family while preserving unrelated current-commit content. Per HP-1 / HP-8 this means hand-editing the hunk; it is never "make file X match `$REFERENCE_BRANCH:X`" or "make every file under directory D match `$REFERENCE_BRANCH` except for a PROTECTED set."
   - **Remove**: delete source-only files or CMake entries that are not present in the reference branch and cannot build coherently in this intermediate commit.
   - **Stop**: ask the engineer.

   **If the failure does not clearly map to one of Fold (forward or REFERENCE) / Defer / Defer-commit / Squash / Squash-cluster / Align / Remove, choose Stop.** Do not invent another action. Do not classify a whole-file replacement as "Fold" or "Align hunks." Do not classify a bulk pre-stage of many later commits into one earlier fix as "Fold" — that is the G8 mass-fold pattern forbidden by HP-2. Do not classify a multi-commit reorder as "Defer-commit" (Defer-commit moves exactly one commit; it does not cascade — see bound (b)). Do not classify a chain of squashes as "Squash" (Squash absorbs exactly one later commit — see Squash bound (a)). Do not classify an ad-hoc group of commits as "Squash-cluster" — Squash-cluster only operates on Phase-B-derived, engineer-approved clusters (see Squash-cluster bound (a)).

6. **Attempt budget per commit.** The default budget is **three** Fold/Defer/Defer-commit/Squash/Squash-cluster/Align/Remove attempts on the same source commit (counted across **all** positions it has been tried at, including the original position before a Defer-commit and the landing position after, including the pre-squash and post-squash states for a Squash, and including each commit's position within a Squash-cluster attempt). If the build is still failing after the budget is exhausted, choose Stop.

   **Per-commit-type budget tuning.** The default may be tuned by source-commit pattern, per the Run envelope (Prepare step 11):

   - `Import X.patch` style commits: default budget = 1. Almost always need cluster-level treatment, not per-commit iteration.
   - Single-file `Fix bug N` style commits: default budget = 5. Often resolve with 1–2 forward-folds.
   - Already-failed commit retried after a dependency lands: default budget = 3.
   - MTR-test-only no-build commits: default budget = 0 (cherry-pick clean or skip).

   **Engineer-tunable cap.** The engineer may increase or lift the cap explicitly in the current conversation, scoped to either (a) all subsequent attempts in the run, (b) a specific named cluster, or (c) a specific named commit. Record each engineer waiver in the ledger's **engineer-waivers** section with timestamp, scope, and verbatim quote. If a commit is about to exceed its budget and the run envelope allows it, the model **must** ask the engineer for a budget increase before continuing — do not silently iterate past the cap. The iteration cap exists to prevent unbounded reasoning toward forbidden actions and to prevent commits from being bounced forward indefinitely; lifting it must be explicit.

7. Rewrite only the current replayed commit after the fix. **Exception**: for the first Group 8 marker checkpoint build, compilation fixes must be committed as new `[compilation]` commit(s) immediately before preserving the `==================== MARKER: GROUP 8 — Upstream bug fixes ====================` marker itself. Do not alter already build-verified earlier commits.
8. Rebuild and verify the commit passes before applying the next build-required commit.

### 7. Restore Buildability

When replay reaches the exact `==================== MARKER: GROUP 8 — Upstream bug fixes ====================` source-list commit, run the first build in the configured `$BUILD_DIR` **before** preserving that marker as an empty commit. After each completed source/plugin/build-system cherry-pick after Group 8, run an incremental build at that commit's resulting SHA before applying the next build-required commit. After each path-classified no-build batch after Group 8, run one incremental build at the batch boundary.

Do not run builds for any source-range commit before the Group 8 marker checkpoint. Use a clean build only for the first verification, after CMake/cache breakage, after build-system/generated-header changes that invalidate incremental trust, or for final confidence when time permits.

Before starting the Group 8 marker checkpoint build or any later build-verified cherry-pick, record `LAST_GOOD=$(git rev-parse HEAD)`. `$OUTPUT_BRANCH` must never be left pointing at a boundary-fix commit or post-Group-8 build-required commit that has not passed its required build.

If the Group 8 checkpoint build fails:

1. Follow the Build-Driven Fixes loop in §6.
2. Apply the minimal fixes in the working tree, then create one or more new commits whose subjects start with the literal prefix `[compilation]`. These fix commits must be committed **before** the `==================== MARKER: GROUP 8 — Upstream bug fixes ====================` marker itself. Verify the order with `git log --oneline -- $LAST_GOOD..HEAD` after preservation.
3. Rebuild until the boundary passes, then preserve the marker as an empty commit.

If a post-Group-8 build fails:

1. Follow the Build-Driven Fixes loop in §6, with the three-attempt limit.
2. If the commit cannot be made buildable within the loop, return `$OUTPUT_BRANCH` to `LAST_GOOD` (resetting if a failing commit was created), capture diagnostics in `$REPORT_FILE`, and ask the engineer.
3. Do not proceed to the next commit until the current one builds.

Missing required build evidence is a stop condition, not a reportable deferral. If a required build was skipped (intentionally or by oversight) and any later commit was applied, the run is **invalid** (see HP-2 and Validity Invariants); stop, report the first skipped index/SHA, and ask whether to reset.

### 8. Execution And Progress

Run the replay in the foreground unless the engineer explicitly asks to background it. Use a TaskList or todo tracker for the long workflow and summarize progress every 10–20 commits, including:

- Current commit count and total
- Current bucket and phase (pre-Group-8, boundary checkpoint, post-Group-8)
- Latest build result
- Notable conflicts or deferrals

Progress reports must not pre-classify upcoming regions, predict that any future region will require snap or build skipping, or refer to "known cascade regions" from any source. (HP-1, HP-3.)

Long build commands may run for a while. Report progress when each build or batch completes to keep the agent session active.

### 9. Direct Execution And Optional Utility Scripts

Direct Git and build commands are the default, portable implementation of this skill. Helper scripts are optional and must comply with the mandatory rules.

Helper-script location: `/home/przemek/.agents/skills/ps-replay+make-buildable/scripts`. If unavailable, check repo-local `scripts/`. If neither location has a needed helper, drive Git, conflict resolution, and builds directly.

The following invariants apply whether using scripts or hand-written shell loops:

1. Generate the source list with `git rev-list --reverse $BASE_BRANCH..$TIP_BRANCH`.
2. Locate the exact `==================== MARKER: GROUP 8 — Upstream bug fixes ====================` subject in the source list before classification. Stop if missing.
3. Force every non-marker commit before the Group 8 marker into the no-build bucket before considering changed paths.
4. Treat the exact Group 8 marker as the first-build checkpoint: run the first build before preserving the marker, and create any required `[compilation]` fix commits before the marker itself.
5. Classify non-marker commits after Group 8 by touched paths of the **source commit** (`git diff-tree --no-commit-id --name-only -r <source-sha>`). Apply the **extension-based Source override** first: if any changed path matches `(?i)\.(h|c|cc|cxx|cpp|hh|hpp|hxx|cmake)$`, the commit is Source bucket regardless of directory prefix (including `mysql-test/`, `plugin/`, `scripts/`, `packaging/`). Only when no path matches the extension override do the directory-prefix no-build / plugin-only / source rules apply. The classification is locked at this point (HP-8); no helper-script mode may reclassify a Source-bucket or Plugin-only-bucket commit as no-build based on the applied commit's post-resolution diff.
6. Apply pre-Group-8 no-build batches in small chronological groups without running builds.
7. Apply post-Group-8 no-build batches in small chronological groups and run an incremental build at each batch boundary.
8. Apply source/plugin/build-system commits after Group 8 singly and build immediately at the resulting SHA before applying the next build-required commit.
9. For every post-Group-8 Source-bucket and Plugin-only-bucket cherry-pick, perform the HP-8 staged-paths cross-check before `git cherry-pick --continue` (or before commit, if the cherry-pick applied cleanly). A helper-script mode that omits this cross-check, that runs any "align source paths to REFERENCE" pass over the worktree/staged tree, or that strips source/plugin/build-system hunks from a Source-bucket commit to escape its per-commit build is disabled by HP-8 regardless of disk presence.
10. Stop on the first conflict, build failure, missing required build record, or HP-8 cross-check failure. Do not let an automation loop auto-resolve conflicts, defer required builds, "align" worktree paths to REFERENCE, or carry failures forward.
11. If the first Group 8 checkpoint build fails, create the required `[compilation]` fix commits before preserving the marker. The fix content must be the minimum needed to compile the current G8 tree; helper-script modes that mass-fold later REFERENCE state into a G8 `[compilation]` commit are disabled by HP-2 / HP-8 / rule 10.
12. Log each source index, original SHA, new SHA, subject, source-commit path list, bucket (and whether locked by HP-8 as Source/Plugin even if post-resolution paths look no-build), whether the no-build bucket was forced by the pre-Group-8 rule, the HP-8 staged-paths cross-check result, apply status, and build result. For every post-Group-8 source/plugin/build-system commit, the log must include that commit's own build log path and PASS result.

#### Available helpers

- `ps_replay_batch.py`: replay a bounded 1-based commit range from a source-list file. Stops on the first conflict, preserves empty marker commits, skips empty non-marker commits, stops on the first build failure or missing required build record. Requires the exact Group 8 marker by default. Use `--build-policy bucketed` only if you have verified by reading the helper's source that it builds each post-Group-8 source/plugin/build-system commit at its resulting SHA before applying the next build-required commit. Use `--classify-only` first to inspect bucket decisions.
- `ps_replay_resolve_conflicts.py`: inspect current conflicts and print conflict blocks with nearby `$REFERENCE_BRANCH` snippets. Does not modify or stage files.
- `ps_replay_build.py`: run a clean or incremental build with the standard configuration, writing a per-run log.
- `ps_replay_errors.py`: extract likely root-cause compiler/linker/CMake/ABI diagnostics from large build logs.
- `ps_replay_scan_range.py`: scan `$BASE..$REFERENCE` (and `$BASE..$TIP` when they differ) for special commits — snap commits, markers, squashes — and surface commits in reference but not in tip. Run during Prepare so reference-only commits cannot be silently missed.
- `ps_replay_conflict_triage.py`: after a stop, classify conflicted files as `auto-match`, `auto-mismatch`, or `unresolved`. `--auto-stage` stages only auto-match files; the rest require manual hunk-level work.
- `ps_replay_resolve_hunks.py`: hunk-level conflict-region resolver. For each `<<<<<<< / ||||||| / ======= / >>>>>>>` block in the listed files (or `--all` for every markered file), score each side's distinct non-trivial lines against the corresponding `$REFERENCE_BRANCH` file and pick the higher-overlap side; HEAD-tiebreak. Replaces only the conflict block; merged context outside markers is untouched. Exit 1 if any region was left unresolved (neither side overlaps reference); those need manual hunk-level work using `git show $REFERENCE:<path>` for inspection only. HP-1 compliant: never copies whole files. Treat the result as best-effort: if the chosen side later breaks the build, fix via Fold (forward or REFERENCE) / Defer / Defer-commit / Squash / Align / Remove — do not loop the resolver with looser thresholds.
- `ps_replay_auto_loop.sh`: replay driver that cherry-picks a 1-based source-list range, buckets each commit, auto-resolves DU files absent on REFERENCE, runs `ps_replay_resolve_hunks.py` against any markered files, skips empty cherry-picks (rule 14), and runs the per-commit build for source/plugin commits (rule 9). Stops on unresolved markers, remaining unmerged files, or build failures with the log path. Does **not** auto-fix build failures (those require Fold/Defer/Defer-commit/Squash/Align/Remove judgment per rule 6 — in particular Forward-fold, Defer-commit, and Squash decisions, all of which require human reasoning about source-commit attribution, landing position, intervening-commit dependencies, and quantitative justification). Configured via env vars `PS_REPLAY_SRC_LIST`, `PS_REPLAY_LOG_DIR`, `PS_REPLAY_BUILD_DIR`, `PS_REPLAY_WORKTREE` (default cwd), `PS_REPLAY_REFERENCE` (default `ps-5.7.9-gca-start`), `PS_REPLAY_SCRIPTS` (default the script's own directory). Use this for the bulk of the post-Group-8 replay; switch back to direct git when a stop demands per-commit reasoning.
- `ps_replay_residual_audit.py`: classify hunks in `git diff $OUTPUT $REFERENCE` as whitespace / trivial / substantive during Final Parity.

#### Disabled helpers

Any helper named `snap_*` or any mode of any helper that performs whole-file or whole-tree replacement from `$REFERENCE_BRANCH` is disabled by HP-5, regardless of whether the helper is present on disk. Presence does not constitute approval.

Example diagnosis:

```sh
SKILL_SCRIPT_DIR=/home/przemek/.agents/skills/ps-replay+make-buildable/scripts
python3 "$SKILL_SCRIPT_DIR/ps_replay_errors.py" "$RUN_DIR/logs/build-58-812714fe16da-ccache.log"
python3 "$SKILL_SCRIPT_DIR/ps_replay_build.py" --worktree "$WORKTREE" --build-dir "$BUILD_DIR" --log "$RUN_DIR/logs/rebuild.log" --incremental
```

Example post-Group-8 driver loop:

```sh
SKILL_SCRIPT_DIR=/home/przemek/.agents/skills/ps-replay+make-buildable/scripts
export PS_REPLAY_SRC_LIST="$RUN_DIR/source-list.txt"
export PS_REPLAY_LOG_DIR="$RUN_DIR/logs"
export PS_REPLAY_BUILD_DIR="$BUILD_DIR"
export PS_REPLAY_WORKTREE="$WORKTREE"
export PS_REPLAY_REFERENCE="$REFERENCE_BRANCH"
export PS_REPLAY_SCRIPTS="$SKILL_SCRIPT_DIR"
bash "$SKILL_SCRIPT_DIR/ps_replay_auto_loop.sh" 29 95
# Stops on the first conflict that needs hand-resolution or the first build
# failure. Inspect, fix per Fold/Defer/Defer-commit/Squash/Align/Remove, amend,
# re-run with updated START.
```

Example hunk resolver invocation (after a stop on conflicts):

```sh
python3 "$SKILL_SCRIPT_DIR/ps_replay_resolve_hunks.py" "$REFERENCE_BRANCH" --all
# Then inspect remaining files (those reported "left unresolved") with
# `git show $REFERENCE_BRANCH:<path>` and edit the conflict region by hand.
```

### 10. Final Parity

Before starting Final Parity, audit that every required post-Group-8 build record exists. Iterate over post-Group-8 source/plugin/build-system commits and confirm each has a per-commit build log with a PASS result at that commit's resulting SHA. **If any required build is missing, do not start Final Parity.** Stop at the first missing source index/SHA and ask the engineer whether to restart from the last build-verified commit.

Also audit the **deferred-hunks/commits/forward-folds/squashes/clusters/applied-equivalents ledger**: every entry must record the SHA on `$OUTPUT_BRANCH` where the moved/folded/squashed content actually lives. Specifically:

- Every **deferred-hunk** entry must record the later commit that re-applied the hunk.
- Every **deferred-commit** entry must have a landing SHA on `$OUTPUT_BRANCH` and a PASS build log at that SHA.
- Every **forward-folded-hunk** entry must record the target earlier-commit SHA on `$OUTPUT_BRANCH` (which already contains the folded hunks at its own PASS build).
- Every **squashed-commits** entry must record the combined SHA on `$OUTPUT_BRANCH` and a PASS build log at that SHA.
- Every **squashed-clusters** entry must record the combined SHA on `$OUTPUT_BRANCH`, a PASS build log at that SHA, and the engineer-approval quote.
- Every **applied-equivalents** entry must point to the actual landing SHA on `$OUTPUT_BRANCH` (which may itself be on another ledger section's row).

**Still-deferred derivation rule.** When rebuilding a `still-deferred` list (e.g. across continuation sessions), do NOT rely on `git patch-id` alone — that produces false positives for commits in the `applied-equivalents` section. The correct still-deferred set is:

```
still-deferred = source-list
              \ patch-id-matched(HEAD)
              \ applied-equivalents.source_sha
              \ squashed-commits.absorbed_sha
              \ squashed-clusters.member_sha
              \ deferred-commits.unresolved_at_session_end (these stay in still-deferred)
```

A continuation session that rebuilds the still-deferred set incorrectly will re-attempt commits that have already been resolved (just under different SHAs), which both wastes effort and can introduce regressions if the re-attempt picks different hunk-resolutions than the original landing.

**If any ledger entry is unclosed, do not start Final Parity.** Stop and ask the engineer whether to close it (apply, re-apply, or revert as appropriate) or to declare the run invalid.

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
- `$LLM_MODEL`, `$RUN_DIR`, `$BUILD_DIR`, and the build command used.
- The pre-flight readback, reproduced verbatim, with the timestamp at which it was produced.
- A "Violations encountered" section that explicitly states either `none` or lists every violation with HP-rule, location in the run, and remediation status. The "none" attestation is **mandatory** even when no violations occurred; an absent attestation is itself a reporting violation.

### Run envelope (Prepare step 11)

- The effort-budget envelope selected by the engineer (per-commit-only with hard cap / per-commit-only tunable / per-commit + cluster-squash / full convergence).
- Default attempt-budget caps by commit-type (or the engineer's override).
- Any engineer waivers granted during the run, with timestamp and verbatim quote (referenced from the engineer-waivers ledger section).

### Phase B cluster manifest (Prepare step 10)

- The full `clusters.tsv` content, or pointer to it under `$RUN_DIR`.
- For each cluster: cluster_name, idx_range, member_count, shared_symbols, suggested_action, and engineer pre-approval status (approved / declined / deferred-to-classifier-time).
- The symbol-index summary: total symbols, count of forward-dep edges, distribution of edge length (target_idx − source_idx).

### Per-applied-commit

- Original SHA from `$TIP_BRANCH`.
- New SHA on `$OUTPUT_BRANCH`.
- One-line subject.
- Whether it applied cleanly or required conflict resolution.
- Build result for that commit, **or** the no-build exemption (pre-Group-8 forced no-build / post-Group-8 path-classified no-build batch).
- For every post-Group-8 source/plugin/build-system commit, that commit's own build log path and PASS result at the resulting SHA. The strings `deferred`, `covered by final build`, `covered by reconciliation`, `build-of-record is final`, `covered by G8 [compilation] fold`, `effect already verified at G8`, or any equivalent are unacceptable build results and constitute an HP-2 violation.
- For every post-Group-8 Source-bucket and Plugin-only-bucket commit, the bucket was decided from the source commit's `git diff-tree` (record the source SHA and the source-paths list), and the HP-8 staged-paths cross-check was performed before continuing the cherry-pick (record either `all source paths present in staged tree` or the deferred-hunks ledger entries that account for any absent paths).

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
- **Deferred-commits ledger**: every whole commit postponed under §6 Defer-commit, with original index/SHA, original subject, landing index/SHA, the motivating build failure, the dependency the landing commit provides, the new `$OUTPUT_BRANCH` SHA assigned at the landing position, the per-commit build log path at that SHA, and the build PASS result. Explicit attestation that bounds (a)–(g) in §6 were honored: specific named landing position, no transitive deferral, intervening commits remained buildable, bucket/build requirements preserved, at most one Defer-commit per source commit, ledger entry recorded, and convergence verified at Final Parity (i.e., the ledger is empty by Final Parity time). If any Defer-commit decision was reversed because an intervening commit failed to build for lack of the deferred content, record the reversal SHA, the intervening commit's index/SHA, and the alternative action chosen.
- **Forward-folded-hunks ledger**: every hunk forward-folded from a later source-list commit into an earlier commit's build-fix under §6 Fold's forward-fold bounds. Per entry: later-source idx/SHA, target earlier idx/SHA on `$OUTPUT_BRANCH`, folded file paths/hunks, the build failure that motivated the fold, the build log path at the target SHA with PASS result, and (when the later-source commit is reached in the replay) whether it was skipped per rule 14 (fully empty after subtraction) or cherry-picked normally with its own build. Explicit attestation that bounds (a)–(e) were honored: one named later source per fold, minimal hunks, ledger entry recorded, no bulk many-to-one pattern, no build-of-record laundering across multiple later commits. Also record, for the run as a whole, whether forward-fold was chosen over REFERENCE-fold (and why) on each Fold-action commit; the preference order in §6 Fold makes REFERENCE-fold the fallback.
- **Squashed-commits ledger**: every Squash applied under §6 Squash, with both original SHAs/subjects, the combined SHA on `$OUTPUT_BRANCH`, the build log path at the combined SHA with PASS result, the motivating build failure, and the quantitative justification for "most of N+1 was needed for N." Explicit attestation that bounds (a)–(h) were honored: exactly two adjacent source commits, specific quantitative justification, mechanics performed without HP-1-forbidden commands, single build at the combined SHA, no skipped builds for the absorbed commit, at most one Squash per source commit, ledger entry recorded, N+1's source-list cursor position skipped.
- **Squashed-clusters ledger**: every Squash-cluster applied under §6 Squash-cluster, with cluster name, full member list (idx, sha, subject), combined SHA on `$OUTPUT_BRANCH`, build log path with PASS result, motivating classifier output (`CLUSTER-BLOCKED` for which symbols), and verbatim engineer-approval quote from the current conversation. Explicit attestation that bounds (a)–(i) were honored: Phase B manifest entry exists, engineer approval is current-conversation and names members, all-or-none, landing at earliest member position, single build at combined SHA, HP-8 cross-check across union of paths, no nested cluster squash, ledger entry recorded, engineer-approval quote captured.
- **Applied-equivalents ledger**: every source-list commit whose content landed on `$OUTPUT_BRANCH` with modifications (forward-fold, Align, partial-hunk, squash component). Per entry: source idx/SHA, new SHA on `$OUTPUT_BRANCH`, modification kind, and pointer to the ledger row recording the actual landing. This shields these commits from false-positive re-attempt by patch-id-based still-deferred derivation across continuation sessions.
- **Engineer-waivers ledger**: every engineer waiver granted during the run. Per entry: timestamp, scope (run-wide / cluster-named / commit-named), rule relaxed (e.g. attempt-cap raised from 3 to N, transitive deferral allowed, cluster pre-approved), and verbatim quote from the engineer's current-conversation message.
- **Phase B cluster manifest**: the `clusters.tsv` content with per-cluster status (manifest-only / approved / declined / used). For each `used` entry, cross-reference the squashed-clusters ledger row.
- **Build-driven fixes**: every folded declaration/member/enum, reference-aligned hunk set, removed source-only file or CMake entry, and the build error it fixed.
- **Reordering**: any reordering relative to chronological order, with the specific conflict that motivated it.
- **Bucket classification**: bucket per commit, batching decisions, and any mis-bucket corrections.
- **Group 8 checkpoint**: any `[compilation]` fix commits with SHA, subject, changed paths, build error summary, rebuild result, and confirmation that each fix commit was created before the marker itself. Each `[compilation]` commit must also include an attestation that its content is the minimum to make the current G8 tree build and does **not** pre-stage REFERENCE state from later commits (HP-2, HP-8, rule 10).
- **Bucketing lock (HP-8)**: for every post-Group-8 Source-bucket and Plugin-only-bucket commit, the source-SHA-derived path list, whether the **extension-based Source override** fired (and which extensions/paths triggered it), the staged-paths list, the comm-diff result, and either `match` or the ledger entries justifying any missing source paths. Explicit attestation that no Source-bucket commit was rebucketed as no-build after resolution and no "align source paths to REFERENCE" pass was run.
- **Reference-derived fixes**: any partial changes ported from later commits on `$REFERENCE_BRANCH` to preserve buildability.
- **Commit rewrites**: any commit rewritten due to build fixes, with failed SHA, final SHA, and build log path.
- **Buildability confirmation**: confirmation that no non-buildable build-required commits remain on `$OUTPUT_BRANCH`. If the run stopped, identify the last known buildable commit and the blocked source commit.
- **Build-record audit**: confirmation that no required post-Group-8 build was skipped. If any was skipped, mark the run **invalid** from the first skipped source index/SHA and explicitly state that the run cannot be completed by adding builds at the tip.
- **Final parity**: confirmation that `git diff $OUTPUT_BRANCH $REFERENCE_BRANCH` is empty at the null-diff SHA, plus the final build result at that SHA.
- **Reconciliation commit** (if any): SHA and explanation.
- **Final build-fix residual** (if approved): engineer approval text, final build-fix SHA, final build log, residual diff paths/hunks, and the reason the null-diff tree could not also be buildable under the required toolchain.

---

## Stop Conditions

Stop and ask the engineer whenever any of the following is **even arguably** the case. The "even arguably" standard is deliberate: where stopping is cheap and rule violation is invalidating, the asymmetry favors stopping.

- `$REFERENCE_BRANCH` does not contain enough information to resolve a conflict at hunk level.
- A dependency cascade cannot be isolated into targeted hunks within the current commit's own changed paths plus a small set of direct-dependency headers.
- A conflict, cascade, or build failure appears to require whole-file or whole-tree reference replacement. Prior reports, memory, rerere, helper-script presence, and model recollection do not constitute approval; stop unless the engineer has explicitly approved the exact file path and reason in the **current conversation**, after this skill was loaded.
- A commit cannot be made buildable within the configured attempt budget (default three) of Fold / Defer / Defer-commit / Squash / Squash-cluster / Align / Remove attempts, counted across all positions it has been tried at, and the engineer has not approved an explicit cap increase in the current conversation (see §6 step 6 Attempt budget).
- A commit remains non-buildable after minimal forward-fold and/or REFERENCE-fold, bounded hunk deferral, a single Defer-commit to a specific named landing position, a single Squash with a specifically named adjacent later commit, and (if the cluster qualifies and is engineer-approved) Squash-cluster.
- The §6 step 3 classifier reports `INVARIANT-BREAK` and the proposed action is a single-symbol forward-fold — verify the surrounding invariant first or escalate to Squash/Squash-cluster.
- The classifier reports `CLUSTER-BLOCKED` and either (a) the cluster has not been engineer-approved for Squash-cluster, (b) the run envelope (Prepare step 11) excludes Squash-cluster, or (c) the cluster has no Phase B manifest entry.
- A Defer-commit would require transitively deferring any other commit, would lack a specific named landing position, or has already been Defer-committed once before (the second-defer ban in §6 bound (e)).
- A previously deferred commit's intervening commits fail to build because of missing deferred content — the original Defer-commit decision was wrong.
- A Forward-fold would require absorbing hunks from multiple later source-list commits into a single earlier fix (HP-2 bulk forward-fold ban). The legitimate alternatives are: multiple separate one-to-one forward-folds (each ledger-bookkept), a Squash (for the case where most of one adjacent commit is needed), a Defer-commit (move the current commit forward), or Stop.
- A Squash would absorb more than one later commit, would not satisfy the "most of N+1 needed for N to build" quantitative justification, or would chain with another Squash on the same source commit.
- A Squash-cluster is being considered but the cluster is not in the Phase B manifest, the engineer has not approved this specific cluster in the current conversation, or the cluster members are not all squash-eligible (e.g. one is itself a previously-squashed combined commit).
- Final Parity is reached while the deferred-hunks/commits/forward-folds/squashes/clusters/applied-equivalents ledger still contains an unclosed entry.
- The required toolchain or build dependencies are unavailable.
- The Group 8 marker is missing from the source list.
- A required post-Group-8 build was skipped and any later commit was applied.
- A build-driven fix does not clearly map to Fold (forward-fold or REFERENCE-fold), Defer (hunk), Defer-commit (whole-commit), Squash (absorb one adjacent later commit), Squash-cluster (Phase-B-manifest, engineer-approved), Align, or Remove.
- The final null-diff tree fails the required build.
- You catch yourself reasoning toward any HP-rule violation.
- You catch yourself reasoning toward "this commit's subject indicates X, so I'll handle it differently" — the only subject-based check is the marker preservation rule (one-or-more `=` followed by ` MARKER:`) (HP-7).
- The HP-8 staged-paths cross-check shows a source/plugin/build-system path from the source commit absent from the staged tree, and the absence is not accounted for by any of: (a) a fully empty cherry-pick under rule 14, (b) a deferred-hunks ledger entry with a named later target commit, (c) a forward-folded-hunks ledger entry naming an earlier target commit on `$OUTPUT_BRANCH` that already contains the absent hunks, or (d) a squashed-commits ledger entry that absorbed this commit into an earlier combined commit.
- You catch yourself reasoning toward "the applied commit no longer touches source paths after resolution, so it's no-build now," "I'll align the source paths to REFERENCE since REFERENCE has the final state anyway," "this source intent was already verified at the G8 [compilation] fold," "I'll fold the post-G8 REFERENCE state into the G8 fix so later cherry-picks land cleanly," "I'll align everything to REFERENCE except a PROTECTED set of paths," "I'll just run `cherry-pick -X ours` to get past the conflicts and clean up after," or "I'll fold hunks from many later commits into one G8 [compilation] commit" — these are HP-1 / HP-2 / HP-8 / rule 10 violations and Stop Conditions in their own right, regardless of how reasonable the framing sounds. (Note: a single targeted forward-fold like "fold idx 334's `packaging/rpm-fedora/rpm-oel` restorations forward into idx 330's build fix" is **allowed and preferred over REFERENCE-fold** under §6 Fold bounds (a)–(e); only bulk many-to-one forward-folds remain forbidden.)
- The pre-flight readback was not produced cleanly.

When stopping, return `$OUTPUT_BRANCH` to `LAST_GOOD` (aborting any in-progress cherry-pick, resetting any failing commit), preserve diagnostics in `$REPORT_FILE`, and describe to the engineer:

1. The current commit being attempted (source SHA, subject, bucket).
2. The specific failure or stop reason.
3. The minimum-fix attempts already made.
4. Two or three concrete options the engineer can choose between (split, defer named hunk, reorder, approve a named exception, restart from earlier checkpoint).

Do not propose options that would require an HP-rule violation. Do not present "snap to reference" as an option.

### Asking the engineer to raise or lift the attempt cap

When a commit's per-commit fixes are converging but the default 3-attempt cap is about to be exhausted, the model **must** ask the engineer for an explicit cap increase before continuing. The ask is short and structured — do not silently iterate past the cap.

When to ask:

- The current commit has used `cap - 1` attempts (one remaining).
- The current attempt's build failed with a new error layer (not a repeat of a prior layer), AND
- The new layer's classifier output (§6 step 3) is `FUTURE-FOLD-CANDIDATE` for a single named later commit, OR `CLUSTER-BLOCKED` for a cluster the engineer pre-approved at Phase B.

The ask format:

> Commit idx N (`<short subject>`) is at attempt `cap-1`. The remaining error is `<symbol-or-error>`, classified `<FUTURE-FOLD-CANDIDATE / CLUSTER-BLOCKED>`, expected to need `<K>` more fold-or-align operations. Raise the cap to `cap+K`, or stop at the current attempt?

The engineer's response goes into the engineer-waivers ledger with timestamp and verbatim quote. If the engineer declines, choose Stop at the cap. Do not ask again for the same commit unless a new symbol/cluster context emerges.

This codifies the contrast between "stop unnecessarily is recoverable; the engineer will tell me to continue" (good) and "iterate silently until the build either passes or violates an invariant" (bad).

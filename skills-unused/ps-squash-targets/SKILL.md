---
name: ps-squash-targets
description: Use when asked to find squash/fold candidates and their targets in a Percona Server commit range — small commits (by line count or removal-heavy) that should be absorbed into related feature commits — without running the heavyweight ps-feature-cluster analysis. Typical triggers, "find best squash candidates/targets", "which small commits can be folded", "don't use ps-feature-cluster". Read-only report; execution is handed to ps-absorb-commit after approval.
---

# Percona Server: lightweight squash-target finder

## Purpose

Given a **candidate range** (commits eligible for squashing) and a **target range**
(commits they may be folded into, usually a superset), produce a ranked, tiered,
numbered report of candidate→target pairs. Raw scoring is deterministic
(`scripts/find_squash_targets.py`); the value you add is the **semantic vetting
pass** — raw file overlap alone produces hot-file false positives and misses
zero-overlap feature owners.

## Inputs

| Variable           | Default              | Meaning                                                        |
| ------------------ | -------------------- | -------------------------------------------------------------- |
| `$CANDIDATE_RANGE` | required             | `A..B` — commits screened as squash candidates.                |
| `$TARGET_RANGE`    | required             | `C..D` — pool of possible targets (usually contains A..B).     |
| `$MAX_LINES`       | `64`                 | Candidate filter: total changed lines ≤ this, OR dels > adds.  |
| `$WORK_DIR`        | `/tmp/squash-targets`| Where `pairs.json` / `pairs.md` land.                          |

## Hard rules

- **HR-1** — Read-only. Never cherry-pick, rebase, or modify branches. Execution belongs to `ps-absorb-commit` after the user approves pairs.
- **HR-2** — Raw script scores are **advisory**. Every pair you report in Tier 1/2 must survive the vetting checklist below. Never present unvetted script output as the answer.
- **HR-3** — Pair size filter: only recommend pairs where at least one side touches ≤8 files. Auto-demote big-vs-big pairs to Tier 3 without asking.
- **HR-4** — Deliverable is a single numbered markdown report; the user replies with `approve N, M-P, ...`. No per-pair AskUserQuestion.
- **HR-5** — Never match on subject text alone. A subject-token similarity with zero file/bug/tag evidence is not a pair.
- **HR-6** — MARKER commits, version bumps, and packaging-only commits are excluded from both pools (the script drops MARKERs; drop the rest during vetting). Classify by **diff content, not subject** — a "Raise version number" subject over a code-fix diff stays in the pool, flagged as mislabeled.
- **HR-7** — When pairs are later executed, every squashed commit's message is preserved, joined by a `==========================================` line.

## Procedure

### 1. Resolve ranges and run the script

Resolve marker subjects (or user-given bounds) to SHAs on the current branch
(`git log --format='%H %s' HEAD | grep "MARKER: GROUP N"` — beware identical
markers on other branches). Then:

```bash
python3 ~/.claude/skills/ps-squash-targets/scripts/find_squash_targets.py --repo "$REPO" \
  --candidate-range "$G_LO..$G_HI~1" --target-range "$T_LO..$T_HI~1" \
  --max-lines "$MAX_LINES" --out "$WORK_DIR"
```

Signals and weights (for interpreting scores): same recurring `[feature_tag]`
prefix +60; shared bug/ticket token (bug N, lp:N, PS-/DB-/MYR-/BLD-/MDEV-N,
`[#NNNN]`) +50; rarity-weighted file overlap up to +40 (`df` in the output =
how many in-range commits touch the file; df≤3 is a rare, load-bearing file,
df≥10 is a hot file that proves nothing).

### 2. Sanity-check the signal mix

Check whether any candidate's `[tag]` actually recurs in range (the script
only awards tag points for recurring tags, but knowing that no tags recur
tells you all matches rest on files/tokens). Dedupe mutual pairs where two
candidates point at each other — keep one direction, normally folding the
later commit into the earlier.

### 3. Vet every top pair (the judgment pass)

For each pair, in score order, decide promote / keep / demote:

- **Hot-file-only → demote.** If every shared file has high df (`sql_select.cc`, `ha_innodb.cc`, `mysqld.cc`, `rpl_slave.cc`), the overlap is noise regardless of score.
- **Created-by-target → promote.** If the candidate's files were *created* by the target (`git log --diff-filter=A --format='%h %s' -- <file>` shows the target), it's a defect-in-feature fix — strongest possible evidence.
- **Revert-annihilation → promote to top.** For removal-heavy candidates, check whether deleted lines were introduced verbatim by one commit (`git log -S '<deleted line>' --reverse -- <file>`). A candidate that exactly undoes a target annihilates on squash. If both halves are in the candidate range and fully annihilate, recommend a **pair-delete** (drop both) rather than a fold that leaves an empty commit. If the introducer is **out of range**, there is no in-range owner — Tier 2 at best, with the unverified annihilation stated.
- **Grab-bag target → demote.** Compiler-warning sweeps, gcc-N/clang-N fix batches, cross-cutting MTR cleanups are not feature owners; folding into them loses history even when a rare file overlaps.
- **Fold direction.** Prefer earlier feature-introducing targets. A *later* target is acceptable only when the candidate is prep/superseded work for it — say so explicitly in the reason.
- **Semantic override.** If a candidate's subject names a feature that exists in range (e.g. a `GLOBAL_TEMPORARY_TABLES` crash fix vs the `[show_temp_tables]` feature commit), check that commit even at zero file overlap — flag the override and the missing overlap in the report.
- **Partial fold.** If only some hunks belong to the target (e.g. re-recorded MTR results of the target's tests plus the candidate's own new test), say "partial — only files X, Y".

### 4. Write the numbered report

Sorted strongest first, grouped into tiers:

- **Tier 1 — strong (recommend):** created-by-target, annihilation, recurring tag, or rare-file overlap *with* a coherent semantic story.
- **Tier 2 — good (verify diff before approving):** plausible but ambiguous — competing targets, later-target direction, partial folds, zero-overlap semantic overrides.
- **Tier 3 — weak (not recommended):** hot-file-only, grab-bag targets, big-vs-big. One line each.
- **No target found:** list remaining candidates.

Per pair: number, candidate `sha + subject + shortstat`, target ditto +
earlier/later, score, and a reason in plain words naming the shared rare files
or the semantic story. Note overrides where your pick differs from the
script's raw top match. End by asking for an `approve N, M-P` list and offer
`ps-absorb-commit` for execution (HR-7 applies there).

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Reporting raw script ranking as final | Vet per step 3; raw score ≠ recommendation (HR-2) |
| Trusting 1-file overlap on a df≥10 file | Demote; only rare files (df≤3) carry signal alone |
| Folding a feature fix into a gcc/clang sweep that shares a file | Grab-bags are never owners; demote |
| Missing the real owner because file sets don't intersect | Semantic-override check on feature-named subjects |
| Asking the user pair-by-pair | One numbered report, `approve N, M-P` reply (HR-4) |
| Recommending two 50-file commits be merged | HR-3 size filter |
| Forgetting both directions of a mutual pair clutter the report | Dedupe, fold later into earlier |

## Companions

- `ps-absorb-commit` — executes approved folds while preserving the final tree.
- `ps-feature-cluster` — the heavyweight alternative (full relatedness graph); use it when the user wants exhaustive clustering rather than a quick squash shortlist.

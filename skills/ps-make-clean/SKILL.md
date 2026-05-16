---
name: ps-make-clean
description: Use to create a cleaned-up branch ($OUTPUT_BRANCH, e.g. ups-X.Y.Z-clean) from a replayed Percona Server branch ($SRC_BRANCH, e.g. ups-X.Y.Z) by (A) stripping transient file paths that never reach tip from every commit in the range, (B) splitting ≤8-line commits — keeping those that touch C/C++ source, squashing the rest into their previous same-path modifier, and (C) squashing related commits by shared launchpad/bug number and by follow-up keyword+path overlap (each pair gated on explicit user approval). The final tip must have a null diff with $SRC_BRANCH's tip.
---

# Percona Server "make clean" branch

## Purpose

Take a replayed branch `$SRC_BRANCH` (rooted at `$BASE_BRANCH`, e.g. `ups-5.6.5` over `mysql-5.6.5`) and produce a cleaner branch `$OUTPUT_BRANCH` (e.g. `ups-5.6.5-clean`) that has:

- The **same tip tree** as `$SRC_BRANCH` (null `git diff`).
- A shorter, more meaningful commit sequence: transient-only commits dropped, trivial non-C/C++ tweaks folded into their semantic owner commit, related commits grouped.

The cleaned branch is for review, archival, and tooling that walks history. It is **not** independently build-verified per commit — buildability is the concern of the predecessor `ps-replay+make-buildable` skill.

## Inputs

- `$SRC_BRANCH`: the replayed branch to clean (e.g. `ups-5.6.5`).
- `$BASE_BRANCH`: the destination base of `$SRC_BRANCH` (e.g. `mysql-5.6.5`). The range `$BASE_BRANCH..$SRC_BRANCH` defines the commits to process.
- `$OUTPUT_BRANCH`: branch to create (e.g. `ups-5.6.5-clean`). If it exists, ask before overwriting.
- `$LOG_DIR`: scratch directory for intermediate artifacts. Default: `/tmp/ps-make-clean-${OUTPUT_BRANCH}-logs`.
- `$REPORT_FILE`: markdown report. Default: `/data/sh/utils/reports/ps-make-clean_${OUTPUT_BRANCH}.md`.

## Hard invariants

1. **Null diff with `$SRC_BRANCH`'s tip is mandatory** at the end of every phase and at the final tip. If any phase produces a non-zero diff, stop and ask.
2. **Phases run in order A → B → C.** Each phase rewrites `$OUTPUT_BRANCH`; later phases consume the result of earlier ones.
3. **Working tree must be clean** at skill start. Refuse to proceed otherwise.
4. **No reference-snap.** Never use `git checkout $SRC_BRANCH -- <path>` or any whole-file-from-source replacement. Conflicts must be resolved by hunk-level edits or "take ours" against the merge marker (resolving the conflict region from the current side is fine; copying a whole file from `$SRC_BRANCH` is not).
5. **Never amend `$SRC_BRANCH`.** All operations target `$OUTPUT_BRANCH` or a temporary helper branch.

## Output report

The skill writes `$REPORT_FILE` with:

- Header (input/output branches, commit counts before/after each phase).
- Phase A: list of transient paths (and the commits that touched only transient paths and were thus dropped).
- Phase B: every small commit, its category (kept-with-C++ / squashed / no-prev-modifier-orphan), its squash target if any.
- Phase C: every squash group with carrier SHA, member SHAs, the bug or follow-up keyword that matched, per-pair user-approval decision (approved / declined / auto-declined-by-size), whether the group was contiguous, and (if non-contiguous) the conflict outcome. Auto-declined-by-size pairs are listed separately with both shortstat lines.
- Final parity: `git diff $OUTPUT_BRANCH $SRC_BRANCH` (must be zero) and final commit count.

---

## Phase A — Strip transient paths

A path is **transient** iff it is touched by some commit in `$BASE_BRANCH..$SRC_BRANCH` AND it is absent from BOTH `$BASE_BRANCH`'s tree AND `$SRC_BRANCH`'s tree. These are paths created and removed wholly within the range.

Compute:

```sh
git log --pretty=format: --name-only $BASE..$SRC | sort -u | sed '/^$/d' > $LOG_DIR/touched.txt
git ls-tree -r --name-only $SRC > $LOG_DIR/tip.txt   # then sort
git ls-tree -r --name-only $BASE > $LOG_DIR/base.txt # then sort
comm -23 <(sort $LOG_DIR/touched.txt) <(sort $LOG_DIR/tip.txt) > $LOG_DIR/touched-not-tip.txt
comm -23 $LOG_DIR/touched-not-tip.txt <(sort $LOG_DIR/base.txt) > $LOG_DIR/transient.txt
```

### Replay strategy

**Do not** use cherry-pick + `git rm` (cherry-pick of a commit that modifies a later-stripped path will fail because earlier strips removed the file the cherry-pick expects). **Do not** use `git diff | git apply` (whitespace handling is lossy).

**Use tree-level plumbing** (`scripts/phase-a-strip.sh`):

For each source SHA in chronological order:

1. Read `<sha>^{tree}` into a temporary index.
2. `git update-index --remove --force-remove` each transient path.
3. `git write-tree` → produces `new_tree`.
4. If `new_tree == HEAD^{tree}`, skip (the commit was entirely transient).
5. Else `git commit-tree new_tree -p HEAD -F <msg>` (with the original commit's author/committer metadata) and `git update-ref HEAD <new_commit>`.

Tree-level plumbing handles binary files, gitlinks (mode 160000 submodule references), and exotic file modes correctly — it never invokes diff/apply.

### Output of phase A

- `$OUTPUT_BRANCH` rooted at `$BASE_BRANCH` with up to N commits (N = source-range size − all-transient drops).
- `git diff $OUTPUT_BRANCH $SRC_BRANCH` must be 0.

---

## Phase B — Small-commit split and squash

For each commit on the post-A `$OUTPUT_BRANCH`:

1. Count diff lines = insertions + deletions (use `git show --shortstat --format= <sha>` — **separately** from `git show --name-only`; the two combined suppress the shortstat line).
2. Get touched paths (use `git show --name-only --format=`).
3. Classify:
   - **Large** (>8 lines): keep as-is.
   - **Small with C/C++ source** (≤8 lines AND touches any `.h`/`.c`/`.cc`/`.cxx`/`.cpp`/`.hh`/`.hpp`/`.hxx`): keep, **print** in the report.
   - **Small without C/C++** (≤8 lines, no C/C++ source paths): squash candidate.

### Previous modifier

For each squash candidate, find its previous modifier: walk back chronologically from the candidate; the first prior commit that touches **any** of the same paths is its prev modifier.

If no prev modifier exists, the candidate is **kept as an orphan** (singleton).

### Chain resolution

Squash candidates may chain (candidate A's prev modifier is itself a candidate B). Resolve each candidate to its ultimate non-candidate root by following the chain.

### Apply

Walk chronologically. For each commit:

- If absorbed (a squash candidate with a non-orphan prev modifier): defer (skip emit at this position).
- If a non-absorbed commit that is the **root** of one or more absorbed commits: cherry-pick `--no-commit` the root, then cherry-pick `--no-commit` each absorbed (in chronological order), then commit with combined message `root_msg + "\n\n-----\n\n" + absorbed_1_msg + ...`. Use the root commit's authorship.
- Else: plain `git cherry-pick`.

The path-overlap chain guarantees the cherry-picks do not conflict on the targeted paths. Intermediate commits between the root and an absorbed member might still conflict on other paths if both touch them — in that case, abort the squash for the specific member and leave it as a singleton.

### Output of phase B

- `$OUTPUT_BRANCH` updated in place (via force-update from a temporary helper branch).
- `git diff $OUTPUT_BRANCH $SRC_BRANCH` must be 0.

---

## Phase C — Squash related commits

Two sub-phases, both gated on path overlap **and** on explicit per-pair user approval.

### Pair size filter (applied before any approval prompt)

Before presenting any (carrier, member) pair for approval — in both C(a) and C(b) — apply the **pair size filter**:

- Compute the file-count of each side from `git show --shortstat --format=` (the "N files changed" number).
- **Keep** the pair only if `min(A_files_changed, B_files_changed) <= 8`.
- **Auto-decline** any pair where both sides modify more than 8 files. Record it in the report under "auto-declined by size filter (both sides >8 files)" with the two shortstat lines and the matched bug/keyword reason.
- The auto-decline is final for this run; the engineer is not asked.

**Why:** big-vs-big squashes are almost always semantically distinct work that the engineer would decline. Asking burns turns; the size filter eliminates the noise floor. The threshold (8 files on the smaller side) is tight enough that a kept pair always has at least one focused commit, which is when squashes are most informative.

**How to apply:** in `scripts/phase-c-plan.py` (or any successor that emits the approval queue), evaluate the filter when building the pair list and partition into `kept` (to ask) and `auto_declined` (to skip). Persist both lists in `phase-c-plan.json` so the report can include them.

### Merge-MySQL exclusion filter (applied before the size filter)

Exclude any (carrier, member) pair where **either** commit's subject contains the substring `Merge MySQL` (case-sensitive). These pairs are stripped from both kept and auto-declined lists and never shown to the engineer.

**Why:** upstream-merge commits (e.g. `(mysql-5.6.16) Merge MySQL 5.6.16`) are semantically distinct from Percona-side fixes that happen to share a bug number or follow-up keyword. Squashing a fix into a multi-thousand-line upstream merge (or vice versa) destroys the merge's reviewability and almost always gets declined. Pre-filtering keeps the report focused on pairs an engineer might plausibly approve.

**How to apply:** when building the pairs list, drop any pair where `git log -1 --format=%s <carrier>` or `git log -1 --format=%s <member>` contains the literal substring `Merge MySQL`. Apply this exclusion **before** the size filter and before writing the pair report.

### C(a) — Bug-number groups

Extract bug references from every commit's subject+body using `scripts/extract-bugs.py`. Patterns:

- `bugs?\.mysql\.com/bug\.php\?id=(\d{4,7})` — MySQL bug-tracker URL
- `(?:^|[^A-Za-z])[Bb]ug[s]?\s*#?\s*(\d{4,7})\b` — `bug #N` / `bug N` / `Bug N` (preceded by non-letter)
- `(?:^|[^A-Za-z])bug(\d{4,7})\b` — filename-style `bug933969.patch` references
- `LP\s+bug\s+#?(\d{4,7})` — Launchpad references
- `bugs?\s+(\d{4,7})\s+and\s+(\d{4,7})` — multi-bug subjects ("Fix bugs N and M")

Normalize to `bug:N` tokens. Commits sharing any token form a group. Group carrier = earliest member by chronological order.

### Pair-report approval flow (mandatory, applies to both C(a) and C(b))

Per-pair `AskUserQuestion` prompts are **forbidden** — too many round-trips when a release range can produce 40+ pairs. Instead:

1. Build the full kept-pairs list (both C(a) and C(b), after the size filter).
2. Write a markdown pair report at `/data/sh/utils/reports/ps-make-clean_${OUTPUT_BRANCH}_phase-c-pairs.md` containing **every** kept pair, numbered globally (C(a) first, then C(b)). Per pair the report must include:
   - Pair number, category (C(a) or C(b)), and the reason of match (shared bug token for C(a), keyword for C(b)).
   - For both A (carrier) and B (member): short SHA, subject, `git show --shortstat --format=` line.
   - **File grouping** (three disjoint groups derived from `git show --name-only --format=`): **common**, **only in A**, **only in B**. List up to ~8 paths per group; if larger, include the count and the first few entries.
   - A header at the top stating the totals (kept by category, auto-declined by size filter) and instructing the engineer to reply with the approved pair numbers, e.g. `approve 1, 5, 12-15, 27` or `approve none`. Numbers not listed are declined.
   - Do **not** include a list of auto-declined pairs in the pair report; the header total is sufficient. Auto-declined entries (size filter, Merge-MySQL filter) belong in the final `$REPORT_FILE`, not the engineer-facing pair report.
3. Send the engineer a single message with the report path and wait for the approval list.
4. Parse the engineer's reply into an approved-pair-number set. Anything outside that set is declined.
5. Record each pair's outcome (approved / declined / auto-declined-by-size) in `$REPORT_FILE` along with shortstat lines, matched token(s)/keyword, and the three file groups.

**Squashing a pair without an explicit approval-list entry is forbidden.** An ambiguous or missing reply is a stop condition.

### C(b) — Follow-up commits

A commit is a follow-up iff BOTH:

- Its subject OR body contains a follow-up keyword (`scripts/follow-up-detect.py` uses: `follow-?up | addendum | amend(?:ment|s)? | refresh | fix(?:es)?\s+(?:test|the|for|up|main) | fixup\s+test | tests?\s+for | (?:more\s+)?test\s+suite\s+fixup | porting\s+(?:to|fix|for) | port\s+(?:fix|to) | manually\s+merge | (?:reverse-)?manual(?:ly)?\s+merge | automerge | merge\s+(?:fix|removal|subunit|build) | rev(?:erse)?\s+manual` — extend as needed).
- It touches at least 3 paths also touched by some chronologically prior commit in the range.

The target (carrier) is the **most recent prior commit with path overlap**. If none, the commit is not a follow-up.

C(b) pairs follow the same pair-report approval flow described above for C(a). Both categories appear in the same numbered pair report, with C(a) listed first, then C(b). The engineer's approve-list applies across both categories.

If multiple C(b) pairs share a transitive carrier, list each direct (carrier, follow-up) pair in the report so the engineer can approve/decline each absorption individually.

### Transitive carrier resolution

A direct map `absorbed → target` is built from user-approved pairs only (both C(a) and C(b) require explicit per-pair approval). Resolve to the ultimate root by following the chain (the carrier of the carrier, etc.). Each absorbed commit is squashed into its ultimate root. Declined pairs are excluded from the map entirely.

### Contiguous-prefix policy and conflict handling

For each group (carrier + chronologically-ordered members), compute the longest **contiguous prefix** (members at consecutive chronological positions). The members in the contiguous prefix are squashed into the carrier with **no conflict risk** (no other commit in the range modifies the same paths between members; otherwise the path-overlap definition would have linked through that intermediate).

Members **outside the contiguous prefix** (later in chronology, with intermediates between them and the carrier) may produce conflicts when reordered next to their carrier. Per the engineer's policy, **attempt the reorder**: insert each non-contiguous member's `pick` line right after the carrier's group in a rebase todo, then `squash` it. If the rebase produces a conflict that cannot be resolved by hunk-level merge of the conflict region:

1. Abort the rebase for that specific member.
2. Leave the member as a singleton (it remains in chronological order with no squash applied).
3. Document the abort in the report with the conflicted paths and the conflict region.

Do not force-resolve by snapping to `$SRC_BRANCH`. Hunk-level resolution only.

### Implementation

The phase-C squasher walks `$OUTPUT_BRANCH` (post-B) chronologically. For each commit:

- If absorbed-non-last and the group is contiguous: defer (it will be applied at the group's last-member emit).
- If absorbed-non-last and the group is non-contiguous: try to pre-insert it adjacent to the carrier via `git rebase -i` with `pick`/`squash`. On unresolved conflict, abort that squash and emit the member as a singleton.
- If carrier or last-member of a contiguous group: cherry-pick all members `--no-commit` in chronological order, then `git commit` with the carrier's authorship and a combined message joined by `\n\n-----\n\n`.
- Else: plain `git cherry-pick`.

### Output of phase C

- `$OUTPUT_BRANCH` updated in place (via force-update from a temporary helper branch).
- `git diff $OUTPUT_BRANCH $SRC_BRANCH` must be 0.

---

## Workflow

1. Validate inputs (`$SRC_BRANCH`, `$BASE_BRANCH`, `$OUTPUT_BRANCH`). Confirm the working tree is clean. Confirm `$BASE_BRANCH` is an ancestor of `$SRC_BRANCH`.
2. If `$OUTPUT_BRANCH` already exists, ask the engineer before overwriting.
3. Compute transient paths (Phase A inputs).
4. Run Phase A → record commit count.
5. Verify null diff vs `$SRC_BRANCH`.
6. Run Phase B → record kept-C++ commits (printed), squashed candidates with chain depth, orphans.
7. Verify null diff vs `$SRC_BRANCH`.
8. Run Phase C → ask the engineer per (carrier, member) pair; record squashed groups, declined pairs, dropped commits, any non-contiguous fall-backs.
9. Verify null diff vs `$SRC_BRANCH`.
10. Write `$REPORT_FILE`.

## Stop conditions

- Working tree dirty at start.
- `$BASE_BRANCH` not an ancestor of `$SRC_BRANCH`.
- Any phase ends with a non-zero diff against `$SRC_BRANCH`'s tip.
- A reorder-driven rebase produces conflicts the script cannot resolve at hunk level, and the engineer has not approved a manual resolution path.
- The engineer interrupts.

## Scripts

- `scripts/phase-a-strip.sh` — Phase A tree-level plumbing replay.
- `scripts/phase-b-analyze.py` — Phase B classifier and chain resolver (small-commit split and squash).
- `scripts/phase-b-apply.sh` — Phase B application via cherry-pick + combined-message commit.
- `scripts/extract-bugs.py` — Phase C bug-token extractor.
- `scripts/follow-up-detect.py` — Phase C keyword + path-overlap follow-up classifier.
- `scripts/phase-c-plan.py` — Phase C squash-plan builder.
- `scripts/phase-c-residuals.py` — Phase C non-contiguous residual reorder/squash attempt.
- `scripts/phase-c-apply.sh` — Phase C contiguous-prefix squasher with non-contiguous reorder attempts.
- `scripts/run.sh` — top-level driver: validates inputs and runs phase-a → phase-b → phase-c.

Each script reads its inputs from the previously written log files in `$LOG_DIR` and writes its own log so the report assembler can produce a complete record.

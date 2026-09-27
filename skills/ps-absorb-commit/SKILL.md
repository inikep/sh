---
name: ps-absorb-commit
description: Use when a Percona Server replay or prune branch contains a commit whose changes should be folded into related commits while preserving the branch's final tree.
---

# Percona Server: Absorb Commit

## Goal

Remove `$ABSORB_COMMIT` by folding its hunks into the commits that own them, then publish `$OUTPUT_BRANCH` with a null diff to `$REFERENCE`.

## Inputs

- `$BASE_BRANCH`: lower bound for final counting, for example `mysql-5.7.9`.
- `$WORK_BRANCH`: branch to rewrite.
- `$REFERENCE`: final tree to preserve, usually the original `$WORK_BRANCH` tip.
- `$ABSORB_BASE`: rebase/absorb anchor; must be an ancestor of `$WORK_BRANCH` and older than every owner in the owner table. For replay branches use the destination base (e.g. `mysql-8.3.0`); owners are often far below `$ABSORB_COMMIT`, beyond `git absorb`'s default stack depth.
- `$ABSORB_COMMIT`: commit to remove.
- `$OUTPUT_BRANCH`: branch to create/update.

## Hard Rules

- **HR-1** Verify ancestry before rewriting. `git merge-base --is-ancestor "$ABSORB_BASE" "$WORK_BRANCH"` and `git merge-base --is-ancestor "$ABSORB_COMMIT" "$WORK_BRANCH"` must succeed. If either fails, stop and find the correct anchor or commit; do not rebase onto a convenient but unrelated base.
- **HR-2** Record starting counts before changing anything: `git rev-list --count "$BASE_BRANCH..$WORK_BRANCH"` and `git rev-list --count "$ABSORB_BASE..$WORK_BRANCH"`. The absorbed result should usually have exactly one fewer commit than the input branch, unless an explicitly marked `[residual] ...` or `[snap] ...` commit is preserved.
- **HR-3** Do not keep `$ABSORB_COMMIT`, an unmarked replacement absorb/snap commit, or any residual `fixup!` commits.
- **HR-4** `git absorb` is advisory only. Its fixup commits are never kept: read its target choices as hints, then reset to `$ABSORB_COMMIT^` and create the fixups yourself from the owner table (HR-4a). Known absorb failures: hunks split across unrelated owners, positional drift (e.g. a fixup that deletes a file's closing `#endif`), repeated-context hunks targeted too early, and hunks left staged with no target. Every hunk must end in exactly one outcome: fold into a concrete in-range owner, direct-edit that owner during rebase, or a `[residual] ...` commit. Never hide a hunk in an arbitrary nearby feature commit. Use `[residual] ...` when the owner is outside the editable range, the hunk is baseline/reference alignment, the owner cannot be identified safely, or a full manual split cannot be completed in the same pass. Residual commits must preserve `$ABSORB_COMMIT`'s original metadata and message body, prefix the subject with `[residual] `, and be reported as residual work.
- **HR-4a** Before creating any fixup, write an owner table covering every hunk of `$ABSORB_COMMIT` (`git diff "$ABSORB_COMMIT^" "$ABSORB_COMMIT"`): `file/hunk -> owner full SHA -> reason`. Reasons are one of: region-last-toucher (`git log -L`), introducer of the symbol/line (`git log -S`), or the in-range commit of the same feature/port (e.g. the `PS-NNNN` 8.x adaptation commit) when it touched the region. Put the table in the report.
- **HR-4b** Moved code stays together. When a hunk removes lines in one place and another hunk adds the same lines elsewhere (declarations, includes, blocks), both go to the same owner, normally the later of the two region owners (the earlier one may not yet contain the lines being removed); splitting them leaves every commit between the two owners with the code duplicated or missing.
- **HR-4c** Fixup subjects must be `fixup! <40-hex owner SHA>` (`git commit -m "fixup! $(git rev-parse <owner>)"`). Do not use `git commit --fixup=<owner>`: autosquash matches its `fixup! <subject>` by subject, and replay branches carry duplicate and 91-char-truncated subjects, so it silently squashes into the wrong commit. Check with `git log --format=%s "$ABSORB_BASE..$ABSORB_COMMIT^" | sort | uniq -d`.
- **HR-5** Preserve the branch's existing ancestry and commit grouping. Do not repair count regressions by changing `$ABSORB_BASE` or rebasing onto another base; if a different anchor is truly needed, first verify it is an ancestor of `$WORK_BRANCH` and treat it as the new `$ABSORB_BASE`.
- **HR-6** Never publish a non-null diff to `$REFERENCE`. If owner retargeting is complete but `HEAD` still differs from `$REFERENCE`, create one additional `[snap] ...` commit that makes the tree match `$REFERENCE`.
- **HR-7** All rebase/autosquash conflicts must be solved with **CDF: Conflict-Driven Fix**. Inspect each conflicted hunk, identify the owning later commit or final local shape, then edit only that hunk.
- **HR-7a** `$REFERENCE` may be inspected for a specific region, but must never be used for whole-file, whole-directory, or subtree replacement during conflict resolution. This applies even when the conflicted commit is the final target commit and the final tree must match `$REFERENCE`.
- **HR-7b** Forbidden conflict shortcuts: `git checkout "$REFERENCE" -- <file>`, `git restore --source "$REFERENCE" <file>`, `git show "$REFERENCE:<file>" > <file>`, `cp` from another worktree, `rsync`, patching a whole file from `$REFERENCE`, or any equivalent full-file/full-tree replacement. The only exception is the final `[snap] ...` step in section 5, after all rebases and retargeting are complete.
- **HR-8** If a rule violation happens, the run is invalid from that point. Stop and report it; do not repair it by later null diff.

## Required Checks

```sh
git status --short --branch
git merge-base --is-ancestor "$ABSORB_BASE" "$WORK_BRANCH"
git merge-base --is-ancestor "$ABSORB_COMMIT" "$WORK_BRANCH"
git rev-list --count "$BASE_BRANCH..$WORK_BRANCH"
git rev-list --count "$ABSORB_BASE..$WORK_BRANCH"
git show --stat --oneline "$ABSORB_COMMIT"
git diff --stat "$WORK_BRANCH" "$REFERENCE"
git branch "backup/absorb-commit-$(date +%Y%m%d%H%M%S)" "$WORK_BRANCH"
```

Stop if ancestry is wrong. Do not rebase onto a convenient unrelated base.

## Workflow

### 1. Absorb the Prefix

Optional hint pass (its commits are thrown away, HR-4):

```sh
git switch -C absorb-commit-work "$ABSORB_COMMIT"
git reset --soft "$ABSORB_COMMIT^"
git absorb --force --base "$ABSORB_BASE"
git log --format='%h %s' "$ABSORB_COMMIT^..HEAD"   # targets = hints only
for c in $(git rev-list --reverse "$ABSORB_COMMIT^..HEAD"); do git show --format='== %s' "$c"; done
git status --short                                  # untargeted leftovers
git reset --hard "$ABSORB_COMMIT^"                  # discard absorb's commits
```

Write the owner table (HR-4a/4b), then create one fixup per owner from `$ABSORB_COMMIT`'s own hunks:

```sh
# whole file to one owner
git diff "$ABSORB_COMMIT^" "$ABSORB_COMMIT" -- <file> | git apply --index
git commit --no-verify -m "fixup! $(git rev-parse <owner>)"
# one file split across owners: stage only that owner's hunks (git apply --index of an
# edited per-hunk patch, or git add -p against a worktree holding $ABSORB_COMMIT's file)
```

When every hunk is staged into a fixup or a residual commit, verify the stack before any rebase:

```sh
test "$(git rev-parse HEAD^{tree})" = "$(git rev-parse "$ABSORB_COMMIT^{tree}")"
git status --short    # must be empty (restore the worktree with git checkout -- . if needed)
```

Hunks without a safe in-range owner become a `[residual] ...` commit: owner outside the editable range, baseline/reference alignment, or unclassified work. Preserve `$ABSORB_COMMIT`'s original metadata and message body, prefix the subject with `[residual] `, and report it as residual work.

Create a residual commit with original metadata and a marked subject:

```sh
residual_msg=$(mktemp)
git log -1 --format=%B "$ABSORB_COMMIT" > "$residual_msg"
sed -i '1s/^/[residual] /' "$residual_msg"
GIT_AUTHOR_NAME="$(git show -s --format=%an "$ABSORB_COMMIT")" \
GIT_AUTHOR_EMAIL="$(git show -s --format=%ae "$ABSORB_COMMIT")" \
GIT_AUTHOR_DATE="$(git show -s --format=%aI "$ABSORB_COMMIT")" \
GIT_COMMITTER_NAME="$(git show -s --format=%cn "$ABSORB_COMMIT")" \
GIT_COMMITTER_EMAIL="$(git show -s --format=%ce "$ABSORB_COMMIT")" \
GIT_COMMITTER_DATE="$(git show -s --format=%cI "$ABSORB_COMMIT")" \
  git commit -F "$residual_msg" --no-verify
```

Useful owner probes:

```sh
git diff --cached --unified=0
git log --reverse --format='%h %s' "$ABSORB_BASE..HEAD" -S'<symbol-or-line>' -- <file>
git log -s --format='%h %s' -L '/<first line of region>/,+<n>:<file>' "$ABSORB_BASE..HEAD"   # region-last-toucher
git blame -L <start>,<end> -- <file>
git show --stat --oneline <candidate>
```

Autosquash the prefix:

```sh
GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash --reapply-cherry-picks --empty=keep "$ABSORB_BASE"
git diff --stat HEAD "$ABSORB_COMMIT"
git log --oneline --grep='^fixup!' "$ABSORB_BASE..HEAD"
diff <(git log --format='%an%x09%ad%x09%s' "$ABSORB_BASE..HEAD") \
     <(git log --format='%an%x09%ad%x09%s' "$ABSORB_BASE..$ABSORB_COMMIT^")
```

The prefix must match `$ABSORB_COMMIT`'s tree, contain no `fixup!` commits, and keep the same author/date/subject sequence as `$ABSORB_COMMIT^` (one per original commit) before replaying later commits.

### 2. Replay the Suffix

If `$ABSORB_COMMIT` was not the tip, replay later commits onto the absorbed prefix:

```sh
absorbed_tip=$(git rev-parse HEAD)
git switch -C absorb-commit-final "$WORK_BRANCH"
git rebase --onto "$absorbed_tip" "$ABSORB_COMMIT" --reapply-cherry-picks --empty=keep
```

If `$ABSORB_COMMIT` was the tip, the absorbed prefix is already the final candidate.

### 3. Conflict-Driven Fix

Resolve every conflict with CDF: inspect the conflict hunk, find the owning later commit or final reference shape, then edit only that hunk.

Required CDF probes:

```sh
git status --short
git diff --cc -- <file>
git show --stat --oneline REBASE_HEAD
git show --unified=40 REBASE_HEAD -- <file>
git show "$REFERENCE:<file>" | sed -n '<start>,<end>p'
git log --format='%h %s' "$ABSORB_BASE..HEAD" -- <file>
```

CDF rules:

- Prefer the later commit being replayed when it legitimately supersedes the absorbed hunk.
- Use `$REFERENCE` only to inspect the specific conflicted region or adjacent final shape.
- Manually edit the smallest block needed, then `git add <file>` and `GIT_EDITOR=: git rebase --continue`.
- Never use `$REFERENCE` for whole-file, whole-directory, or subtree replacement.
- Never run `git checkout "$REFERENCE" -- <file>`, `git restore --source "$REFERENCE" <file>`, or equivalent whole-file conflict shortcuts.
- If repeated context makes patching unsafe, direct-edit the owner with an interactive rebase rather than applying another broad patch.

### 4. Retarget Residuals

After autosquash or suffix replay:

```sh
git diff --stat HEAD "$REFERENCE"
git diff --unified=30 HEAD "$REFERENCE" -- <file>
```

For each residual hunk, identify the later commit that overwrote the intended change and fold the hunk there with a fixup or direct edit. After retargeting is complete, any remaining diff must become one explicit `[snap] ...` commit.

### 5. Snap and Publish

If the final candidate still differs from `$REFERENCE`, create one marked snap commit to reach a null diff:

```sh
if ! git diff --quiet HEAD "$REFERENCE"; then
  snap_patch=$(mktemp)
  git diff --binary HEAD "$REFERENCE" > "$snap_patch"
  git apply --index "$snap_patch"
  git commit -m "[snap] Match reference after absorbing $ABSORB_COMMIT"
  rm -f "$snap_patch"
fi
```

Use the snap only after rebases, conflict resolution, and owner retargeting are complete. Do not use it to cover a skipped owner decision, unresolved conflict shortcut, or any earlier rule violation.

The result is valid only when all checks pass:

```sh
git status --short --branch
git diff --stat HEAD "$REFERENCE"
git log --oneline --grep='^fixup!' "$ABSORB_BASE..HEAD" | wc -l
git log --oneline --grep='^\[snap\]' "$ABSORB_BASE..HEAD"
git merge-base --is-ancestor "$ABSORB_COMMIT" HEAD; echo $?
git rev-list --count "$BASE_BRANCH..HEAD"
```

Expected: clean tree, null diff, zero fixups, `$ABSORB_COMMIT` not an ancestor, and a count that matches the intended squash outcome.
If a `[residual] ...` or `[snap] ...` commit remains, the count may differ from the usual one-fewer result; report the marked commit explicitly.

Then publish:

```sh
git branch -f "$OUTPUT_BRANCH" HEAD
```

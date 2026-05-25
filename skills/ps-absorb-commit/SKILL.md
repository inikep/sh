---
name: ps-absorb-commit
description: Use when a Percona Server replay or prune branch contains a commit whose changes should be folded into related commits while preserving the branch's final tree.
---

# Percona Server: Absorb Commit

## Goal

Remove `$ABSORB_COMMIT` by folding its hunks into the commits that own them, then publish `$OUTPUT_BRANCH` with a null diff to `$REFERENCE` unless the user explicitly allows an exact residual class.

## Inputs

- `$BASE_BRANCH`: lower bound for final counting, for example `mysql-5.7.9`.
- `$WORK_BRANCH`: branch to rewrite.
- `$REFERENCE`: final tree to preserve, usually the original `$WORK_BRANCH` tip.
- `$ABSORB_BASE`: rebase/absorb anchor; must be an ancestor of `$WORK_BRANCH`.
- `$ABSORB_COMMIT`: commit to remove.
- `$OUTPUT_BRANCH`: branch to create/update.

## Hard Rules

- **HR-1** Verify ancestry before rewriting. `git merge-base --is-ancestor "$ABSORB_BASE" "$WORK_BRANCH"` and `git merge-base --is-ancestor "$ABSORB_COMMIT" "$WORK_BRANCH"` must succeed. If either fails, stop and find the correct anchor or commit; do not rebase onto a convenient but unrelated base.
- **HR-2** Record starting counts before changing anything: `git rev-list --count "$BASE_BRANCH..$WORK_BRANCH"` and `git rev-list --count "$ABSORB_BASE..$WORK_BRANCH"`. The absorbed result should usually have exactly one fewer commit than the input branch, unless an explicitly marked `[residual] ...` commit is preserved for unclassified leftovers.
- **HR-3** Do not keep `$ABSORB_COMMIT`, an unmarked replacement absorb/snap commit, or any residual `fixup!` commits.
- **HR-4** `git absorb` is only the first pass. It may leave staged hunks and may target repeated-context hunks too early. Each leftover hunk must be handled by one of three explicit outcomes: fold it into a concrete in-range owner commit, direct-edit that owner during rebase, or preserve it as a `[residual] ...` commit. Never hide leftovers in an arbitrary nearby feature commit. Use `[residual] ...` when the owner is outside the editable range, the hunk is baseline/reference alignment, the owner cannot be identified safely, or a full manual split cannot be completed in the same pass. Residual commits must preserve `$ABSORB_COMMIT`'s original metadata and message body, prefix the subject with `[residual] `, and be reported as residual work.
- **HR-5** Preserve the branch's existing ancestry and commit grouping. Do not repair count regressions by changing `$ABSORB_BASE` or rebasing onto another base; if a different anchor is truly needed, first verify it is an ancestor of `$WORK_BRANCH` and treat it as the new `$ABSORB_BASE`.
- **HR-6** Never accept a non-null diff to `$REFERENCE` unless the user explicitly allows that exact class of residual. Whitespace residuals are still residuals unless explicitly allowed.
- **HR-7** All rebase/autosquash conflicts must be solved with **CDF: Conflict-Driven Fix**. Inspect each conflicted hunk, identify the owning later commit or final local shape, then edit only that hunk.
- **HR-7a** `$REFERENCE` may be inspected for a specific region, but must never be used for whole-file, whole-directory, or subtree replacement. This applies even when the conflicted commit is the final target commit and the final tree must match `$REFERENCE`.
- **HR-7b** Forbidden conflict shortcuts: `git checkout "$REFERENCE" -- <file>`, `git restore --source "$REFERENCE" <file>`, `git show "$REFERENCE:<file>" > <file>`, `cp` from another worktree, `rsync`, patching a whole file from `$REFERENCE`, or any equivalent full-file/full-tree replacement.
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

```sh
git switch -C absorb-commit-work "$ABSORB_COMMIT"
git reset --soft "$ABSORB_COMMIT^"
git absorb --force --base "$ABSORB_BASE"
git status --short
git diff --cached --stat
```

For staged leftovers, choose one of:

- `git commit --fixup=<owner>` when blame, `-S`, or file history identifies an in-range owner.
- A `[residual] ...` commit when leftovers cannot be folded into an in-range owner safely, including leftovers whose natural owner is outside the editable range, baseline/reference alignment, or unclassified work; preserve `$ABSORB_COMMIT`'s original metadata and message body, prefix the subject with `[residual] `, and report it as residual work.

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
git blame -L <start>,<end> -- <file>
git show --stat --oneline <candidate>
```

Autosquash the prefix:

```sh
GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash --reapply-cherry-picks --empty=keep "$ABSORB_BASE"
git diff --stat HEAD "$ABSORB_COMMIT"
git log --oneline --grep='^fixup!' "$ABSORB_BASE..HEAD"
```

The prefix must match `$ABSORB_COMMIT` and contain no `fixup!` commits before replaying later commits.

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

For each residual hunk, identify the later commit that overwrote the intended change and fold the hunk there with a fixup or direct edit. Do not recreate a final snap.

### 5. Publish

The result is valid only when all checks pass:

```sh
git status --short --branch
git diff --stat HEAD "$REFERENCE"
git log --oneline --grep='^fixup!' "$ABSORB_BASE..HEAD" | wc -l
git merge-base --is-ancestor "$ABSORB_COMMIT" HEAD; echo $?
git rev-list --count "$BASE_BRANCH..HEAD"
```

Expected: clean tree, null diff unless the user explicitly allowed an exact residual class under HR-6, zero fixups, `$ABSORB_COMMIT` not an ancestor, and a count that matches the intended squash outcome.
If a `[residual] ...` commit remains, the count may match the input branch instead; report the residual commit explicitly.

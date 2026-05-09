# mysql-5.6.22 Initial Tree Ordering

Use this reference only when `$BASE_BRANCH` is exactly `mysql-5.6.22`. For any other base branch, do not apply these rules unless the engineer explicitly asks for them in the current conversation.

The group is identified by source commit subjects that start with:

```text
Initial Percona Server 5.6.22 tree
```

## Mandatory Rules
For commits in the `"Initial Percona Server 5.6.22 tree"` group, choose the next commit dynamically by least conflicts against the current `$OUTPUT_BRANCH` state. This is intentionally slower and is required.

This branch-specific rule changes commit ordering only. It does not create a special build bucket, batch, or exemption from the main skill's marker, bucketing, or build-verification rules. In particular, the exact `=== MARKER: GROUP 7 — Remaining ===` boundary and Rule 13 still apply to commits selected by least-conflict ordering: source-range commits before the Group 7 marker are not built individually, the first build runs at the Group 7 marker checkpoint before preserving that marker, and every completed source-touching commit after the Group 7 marker must be build-verified before proceeding.

## Workflow
Identify commits whose subjects belong to the `"Initial Percona Server 5.6.22 tree"` group so they can be handled with least-conflict ordering.

### 3. Choose Commit Order
For the `"Initial Percona Server 5.6.22 tree"` group:
1. Trial-apply each remaining candidate against the current `$OUTPUT_BRANCH` state.
2. Count conflicted files.
3. Select the candidate with the fewest conflicts.
4. Abort/reset the trial state.
5. Apply the selected commit for real.
6. Classify and build-verify the applied commit exactly as required by the main skill's active build policy, using the commit's original source-list position relative to the Group 7 marker. Do not select or apply the next initial-tree candidate while a required post-Group-7 build is pending or failing.
7. Repeat until the group is exhausted.

## Execution Notes

- Keep this least-conflict ordering inside the initial-tree group only. The ordering exception is the only branch-specific override; all commits, including initial-tree commits, continue to follow the main skill's bucketing, build, marker, and conflict-resolution rules.
- Trial application is for conflict counting only. Do not resolve trial conflicts, stage trial files, or keep any trial state.
- Always restore the worktree to the exact pre-trial `$OUTPUT_BRANCH` `HEAD` before applying the selected commit for real.
- If two candidates have the same conflicted-file count, prefer the earlier source-list index to keep the reordering minimal.
- Record every selected candidate in `$REPORT_FILE` with its source-list index, original SHA, conflicted-file count from the trial, and the reason `mysql-5.6.22 initial-tree least-conflict ordering`.
- The Group 7 no-build boundary rule still applies. If an initial-tree commit is before `=== MARKER: GROUP 7 — Remaining ===`, it remains in the forced No-build bucket even when selected by least-conflict ordering. If it is after that marker and touches source or build-system paths, it must be applied singly and build-verified immediately.

Optional helper:

```sh
python3 /home/przemek/.agents/skills/ps-replay+make-buildable/scripts/ps_replay_least_conflict.py \
  --base-branch "$BASE_BRANCH" \
  --source-list /tmp/source-list.txt \
  --remaining-indices 10-63 \
  --worktree "$WORKTREE"
```

The helper only ranks remaining candidates; it does not apply the selected commit to `$OUTPUT_BRANCH` for real.


---
name: jira-mtr-fix
description: >
  End-to-end workflow for diagnosing and fixing MySQL/Percona Server bugs from JIRA tickets.
  Given a JIRA ticket number, this skill reads the ticket, creates an MTR (MySQL Test Run)
  test to reproduce the issue, builds MySQL/Percona Server, runs MTR to confirm reproduction,
  iteratively plans, implements, reviews with Codex CLI (gpt-5.4, high reasoning),
  verifies fixes with a passing MTR test, and opens a GitHub PR with the result.
  Use this skill whenever a user mentions a JIRA ticket (e.g. PS-1234, PXC-567, PS-####),
  asks to "fix a bug from JIRA", "reproduce a MySQL issue", "write an MTR test for a ticket",
  or wants to debug/patch MySQL or Percona Server from a ticket number. Also trigger when the
  user mentions "MTR test", "mysql-test-run", or "build and test Percona Server for a bug".
---

# JIRA → MTR → Fix Workflow

A structured, interactive workflow that takes a JIRA ticket number and drives the full
bug-fix lifecycle: read → branch → reproduce → build → run → plan → implement → review → verify → PR.

---

## High-Level Flow

```
 1. READ JIRA          — Fetch ticket details, understand the bug
 2. CREATE BRANCH      — Create a fix branch from the current base before any edits
 3. CREATE MTR TEST    — Write a .test file; stop if the bug cannot be reproduced in MTR
 4. BUILD SERVER       — Compile MySQL/Percona Server
 5. RUN MTR            — Execute the test; check for reproduction
 6. BUG NOT REPRODUCED — If MTR passes unexpectedly, analyze, propose, and confirm retry
 7. PLAN FIX           — Read source, root cause, fix plan; present plan to the user
 8. IMPLEMENT FIX      — Apply patch per agreed plan; rebuild
 9. CODEX CLI REVIEW   — Run Codex review; loop to 8 until no important issues
10. VERIFY             — Re-run MTR and broader suite; confirm no regressions
11. COMMIT & PR        — Commit relevant files, push branch, open GitHub PR
```

Important: proceed with the steps one by one in the order defined above. Don't skip any of them.

If MTR does **not** reproduce the bug, follow **Step 6** and do not proceed to **Step 7**
until reproduction is confirmed.

---

## Step 1 — Read the JIRA Ticket

Use the Atlassian MCP (`https://mcp.atlassian.com/v1/mcp`) to fetch the ticket.

```
Tool: mcp_atlassian → jira_get_issue
Input: { "issue_key": "<TICKET_NUMBER>" }
```

Extract and summarize:
- **Summary / Title**
- **Description** — the full bug report
- **Steps to Reproduce** (if present)
- **Expected vs Actual behavior**
- **Affected versions / components** (e.g. `mysqld`, `InnoDB`, `replication`)
- **Attachments or linked test cases** — download any `.test`, `.sql`, or `.patch` files
- **Comments** — scan for any developer notes, workarounds, or partial fixes

If the ticket cannot be fetched, tell the user and stop.

---

## Step 2 — Create Fix Branch

Create the branch before editing any files so both the MTR test and source fix
land on the same branch. Use the ticket key (lowercased) as the branch name
prefix.

```bash
git switch -c fix/<ticket_lower>
```

If the branch already exists locally, switch to it instead of creating a new one.

---

## Step 3 — Create the MTR Test

### Locate the test suite
Determine the appropriate MTR suite from the component:

| Component / Area         | Suite path                          |
|--------------------------|-------------------------------------|
| InnoDB / storage engine  | `mysql-test/suite/innodb/`          |
| Replication              | `mysql-test/suite/rpl/`             |
| General / SQL            | `mysql-test/t/`                     |
| Percona-specific         | `mysql-test/suite/percona/`         |
| Group Replication        | `mysql-test/suite/group_replication/`|
| XtraDB Cluster           | `mysql-test/suite/galera/`          |

When in doubt, use `mysql-test/t/` or ask the user.

### Write the test file

Create `mysql-test/<suite>/t/<ticket_lower>.test`:

```sql
# MTR test for <TICKET_NUMBER>: <Title>
# Created: <date>
# Reproduces: <one-line description>

--echo # Setup
# ... CREATE TABLE / INSERT / SET GLOBAL as needed

--echo # Reproduce the bug
# ... the exact SQL or sequence that triggers the issue

--echo # Expected: <expected output>
# ... assertions: --error, SELECT result matching, etc.

--echo # Cleanup
# ... DROP TABLE / RESET

--echo # Done
```

Also create the result file `mysql-test/<suite>/r/<ticket_lower>.result` with the
**expected** output (use `--record` on first run to generate, or write manually).

### Evaluate writability

Before proceeding, assess:
- Can the bug be triggered with SQL alone, or does it require source-level changes?
- Is it a crash/assertion? → use `--exec_in_background` + signal check patterns
- Is it a race condition? → mark it with `--source include/have_debug.inc` and use
  `DEBUG_SYNC` points if needed
- Is it OS/hardware-specific? → add `--source include/have_<feature>.inc` guards

**If the bug cannot reasonably be reproduced in MTR** (e.g., hardware-specific,
requires external tooling, needs a full cluster of N nodes with no MTR support),
explain clearly why, output a plain `.sql` workaround script instead if possible,
and **stop the workflow here**.

---

## Step 4 — Build MySQL / Percona Server

> Read `references/build.md` for full cmake flags, dependency list, and
> distro-specific notes before running any build commands.

Quick reference:

```bash
# From the repo root
mkdir -p build && cd build

cmake .. \
  -DCMAKE_BUILD_TYPE=Debug \
  -DWITH_DEBUG=1 \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache \
  -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DWITH_UNIT_TESTS=0 \
  -DWITHOUT_SERVER=0 \
  -DWITH_BOOST=<path_to_boost> \
  $(cat ../cmake_flags.txt 2>/dev/null || true)

make -j$(nproc) mysqld mysql mysql_install_db
```

If the build fails:
1. Show the last 40 lines of build output to the user
2. Attempt to fix trivial issues (missing deps → `apt/yum install`, wrong path, etc.)
3. If not fixable automatically, stop and report

---

## Step 5 — Run MTR to Reproduce

```bash
cd mysql-test

perl mysql-test-run.pl \
  --suite=<suite> \
  --do-test=<ticket_lower> \
  --mysqld=--innodb-buffer-pool-size=64M \
  --force \
  --retry=0 \
  --repeat=3 \
  2>&1 | tee /tmp/mtr_repro.log
```

Parse `/tmp/mtr_repro.log`:
- **FAIL / core dump / assertion** → ✅ Bug reproduced → proceed to Step 7 (Plan)
- **PASS** → ❌ Bug NOT reproduced → proceed to Step 6

---

## Step 6 — Bug Not Reproduced: Propose & Confirm

If MTR passes (bug not yet reproduced or test is incorrect):

1. **Analyze** the ticket description, server version, and test output
2. **Propose** one or more hypotheses about why reproduction failed:
   - Wrong version / compile flags?
   - Test logic doesn't match actual trigger path?
   - Missing config / plugin?
3. **Present** each hypothesis to the user with a suggested change
4. **Ask**: _"Should I apply this change and try again?"_

Wait for user confirmation before looping back to Step 4 or Step 5.
If the user says no or wants to stop, exit gracefully.

---

## Step 7 — Plan the Fix

Once the bug is reproduced:

1. **Trace the failure** — crash trace, assertion, or incorrect result vs expected
2. **Read** the relevant source files (`storage/innobase/`, `sql/`, `plugin/`, etc.)
3. **Determine the root cause** — explain the mechanism clearly
4. **Draft a fix plan** — minimal, surgical approach: which files, what changes, risks, alternatives
5. **Present the plan** to the user and wait for agreement before **Step 8**

Do not implement code changes in this step—only analysis and planning.

---

## Step 8 — Implement the Fix

Follow the **agreed plan** from Step 7:

1. **Implement** the changes — prefer minimal, surgical edits
2. **Apply** using standard `sed`/`patch`/direct edit via `str_replace`
3. **Show the diff** to the user (`git diff`) and explain what changed
4. **Rebuild** (only the affected translation units if possible):
   ```bash
   cd build && make -j$(nproc) mysqld
   ```

---

## Step 9 — Codex CLI Code Review

From the MySQL/Percona Server repo root, run Codex as a separate reviewer with
`gpt-5.4` and high reasoning, passing the ticket ID, one-line summary, agreed
Step 7 plan, and `git diff` as context.

```bash
git diff | codex exec --ephemeral --model gpt-5.4 -c 'model_reasoning_effort="high"' \
  "Adversarially review this diff for <TICKET_NUMBER> (<summary>). Agreed fix plan: <plan>. Classify findings as high, medium, or low importance; focus on correctness, regressions, and MySQL/Percona Server conventions." \
  | tee /tmp/codex_review.log
```

If Codex reports any non-low issues, return to **Step 8**, fix them, rebuild, and
repeat **Step 9**. Stop only when no important issues remain. If `codex` is
unavailable or authentication fails, report that and stop.

---

## Step 10 — Verify: MTR Must Pass

```bash
cd mysql-test

perl mysql-test-run.pl \
  --suite=<suite> \
  --do-test=<ticket_lower> \
  --force \
  --retry=0 \
  --repeat=3 \
  2>&1 | tee /tmp/mtr_verify.log
```

- **PASS** → ✅ Fix verified for the targeted test. Run the broader suite below.
- **FAIL** → ❌ Fix incomplete. Go back to **Step 8** with an updated hypothesis (or **Step 7**
  if the plan or root cause needs revision).

Then run the broader suite to check for regressions:
```bash
perl mysql-test-run.pl --suite=<suite> --force --retry=0 2>&1 | tee /tmp/mtr_regression.log
```

If the broader suite is clean, proceed to **Step 11**.
If the broader suite introduces failures, report them and return to **Step 8**
(or **Step 7** if the plan or root cause needs revision).

---

## Step 11 — Commit, Push & Create PR

Once MTR passes (Step 10) and regressions are clean:

1. **Stage only the files that belong to this fix** (source fix + MTR test +
   result file). Do not use `git add -A` in a dirty worktree:
   ```bash
   git add <changed_source_files> \
     mysql-test/<suite>/t/<ticket_lower>.test \
     mysql-test/<suite>/r/<ticket_lower>.result
   git status --short
   git commit -m "fix(<component>): <short description> (<TICKET_NUMBER>)

   <root cause explanation>
   <what was changed and why>"
   ```
2. **Push** the branch to the remote:
   ```bash
   git push -u origin fix/<ticket_lower>
   ```
3. **Create a GitHub PR** using `gh`:
   ```bash
   gh pr create \
     --title "fix(<component>): <short description> (<TICKET_NUMBER>)" \
     --body "## Summary
   - **Bug**: <one-line description>
   - **Root cause**: <explanation>
   - **Fix**: <what was changed and why>
   - **Test**: \`mysql-test/<suite>/t/<ticket_lower>.test\`
   - **JIRA**: <TICKET_NUMBER>

   ## Test plan
   - [ ] MTR test \`<ticket_lower>\` passes (repeat=3)
   - [ ] Broader \`<suite>\` regression run clean"
   ```
4. **Report** the PR URL to the user.

If `gh` is not available, show the push output and provide a manual PR link
(`https://github.com/<org>/<repo>/compare/fix/<ticket_lower>?expand=1`).

---

## Output at Completion

When the workflow finishes successfully, produce a summary:

```
## Fix Summary for <TICKET_NUMBER>

**Bug**: <one-line description>
**Root cause**: <explanation>
**Fix**: <what was changed and why>
**Test**: mysql-test/<suite>/t/<ticket_lower>.test
**PR**: <PR URL>

### Suggested commit message
fix(<component>): <short description> (<TICKET_NUMBER>)

<longer explanation of root cause and fix>
```

---

## Reference Files

- `references/build.md` — Full build instructions, cmake flags, distro dependencies
- `references/mtr-patterns.md` — Common MTR test patterns (crashes, races, wrong results)
- `references/jira-fields.md` — Guide to interpreting Percona JIRA field conventions

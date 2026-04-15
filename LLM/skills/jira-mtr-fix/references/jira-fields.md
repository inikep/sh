# Interpreting Percona JIRA Fields

## Project Keys

| Key   | Project                        |
|-------|-------------------------------|
| PS    | Percona Server for MySQL       |
| PXC   | Percona XtraDB Cluster         |
| PXB   | Percona XtraBackup             |
| PMM   | Percona Monitoring and Management |
| PSDEV | Percona Server Dev (internal)  |
| PT    | Percona Toolkit                |

## Priority → Urgency Signal

| Priority    | Meaning for bug work                  |
|-------------|---------------------------------------|
| Blocker     | Production-stopping, fix immediately  |
| Critical    | Data loss / crash risk                |
| Major       | Significant regression or wrong result|
| Minor       | Cosmetic or rare edge case            |
| Trivial     | Nice-to-have, low risk                |

## Resolution Field

| Resolution  | Meaning                               |
|-------------|---------------------------------------|
| Fixed       | Fix already committed (check branches)|
| Won't Fix   | Deliberate non-fix — read comments    |
| Duplicate   | See linked "duplicates" ticket        |
| Cannot Reproduce | Test environment was different   |
| Incomplete  | Insufficient info — read comments     |

## Useful Custom Fields (Percona)

- **Affected Versions**: The first version the bug appeared in
- **Fix Version/s**: Target release — sets the branch to work on
- **Components**: Maps to MySQL subsystem (InnoDB, Replication, Optimizer, etc.)
- **Labels**: e.g., `regression`, `data-loss`, `security`, `upstream`
- **Upstream Bug**: Link to bugs.mysql.com if it's an upstream issue

## Reading Comments Strategically

1. **Last 3–5 comments first** — most recent discussion often contains partial patches or root cause analysis
2. Look for comments by `@jenkin`, `@qa-`, or `@robot` — these are automated test results
3. Developer comments starting with "Root cause:" or "Fix:" are gold
4. QA comments with "Tested on version X, reproduced with steps..." tell you the exact repro recipe

## Attachments to Check

| File type   | What it usually contains                          |
|-------------|--------------------------------------------------|
| `.test`     | An MTR test file — use as the starting point     |
| `.patch`    | A candidate fix — apply and verify               |
| `.sql`      | Standalone SQL repro script                      |
| `.txt`      | Stack trace, SHOW ENGINE INNODB STATUS, etc.     |
| `.log`      | Full mysqld error log with crash info            |
| `.ibd`      | Corrupted tablespace file for import test        |

## Linked Issues

- **"is caused by"** / **"causes"** — follow for root cause chain
- **"duplicates"** / **"is duplicated by"** — the "duplicates" ticket is usually more detailed
- **"blocks"** / **"is blocked by"** — dependency order for fix sequencing
- **"relates to"** — tangential, low priority to read

## Branch Naming Conventions

Percona Server branches follow:
```
Percona-Server-X.Y.Z-release   — stable release branch
PS-X.Y                          — development branch for major version
```

For a ticket targeting `8.0.35`, work on the `Percona-Server-8.0.35` or `PS-8.0` branch.

## Extracting Repro Steps

If the ticket has no structured repro steps, look for:
1. SQL queries in code blocks in the description
2. Attachments with `.test` or `.sql`
3. Comments where the reporter says "I ran X and got Y"
4. EXPLAIN output or query plans (suggests optimizer bug)
5. Stack traces (suggests crash → write a crash-triggering test)

If none of these exist, formulate the test from:
- The bug title (e.g., "InnoDB: wrong result with LEFT JOIN" → write a LEFT JOIN test)
- Affected versions (regression → diff behavior between versions)
- Component (InnoDB, replication, etc. → target that subsystem)

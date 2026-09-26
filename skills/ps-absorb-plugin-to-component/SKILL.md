---
name: ps-absorb-plugin-to-component
description: Use when a Percona Server / MySQL branch has a later "convert <name> plugin to a component" commit that must disappear, so the component exists from the plugin's introducing commit and every commit touching it builds (moving plugin/<name> to components/<name>, INSTALL PLUGIN to INSTALL COMPONENT, MYSQL_ADD_PLUGIN to MYSQL_ADD_COMPONENT in history).
---

# Absorb a Plugin-to-Component Conversion

## Overview
Treat the conversion commit X as a **deterministic transformation**, not a set of hunks. Derive rules from X, prove they turn `X^` into `X` byte for byte, apply them to every earlier version of each file, rewrite the trees with plumbing, then require that X becomes a no-op and drop it.

**Don't split X by hunk or splice by line position.** Each feature commit's file is a different version, so X's hunks don't apply to them.

## Inputs
- `BASE`: the range base.
- `HEAD`: the branch to rewrite.
- `A`: the introducing commit (the first commit that adds the plugin).
- `F1..Fn`: the feature commits that change the plugin.
- `X`: the conversion commit.
- `OUT`: the output branch.

The range must be linear.

## Steps
1. **Inventory.** Run `git show -M --summary --stat X`.
   - Take the paths from X; don't invent names.
   - A CMakeLists.txt shown as delete+add is still a rename.
   - List every commit in `A..X^` that touches those paths, `plugin.defs` or the packaging lists.
   - Allowed: A, the feature commits, and commits that only add or reformat other lines next to the plugin's line (e.g. a `procfs` insert). Anything else touching the plugin's own lines: stop and ask.
   - **Scan the input:** `scripts/scan_input.py --start A --end X^ --old-root plugin/<name>/`. It lists sources and includes missing from each commit, and files a later commit restores exactly or almost exactly (e.g. a grab-bag "Revert" that also reverted unrelated upstream files). These are defects of the input: fix them permanently (restore the lost file; keep round-tripped files at their earlier version) and report them. Don't count them as conversion bugs.
   - Build the original A and last feature commit first. If they were already broken before X, report that before starting.
2. **Check dependencies at `A`.** Every API or macro the component code uses must already exist at `A`, for example `mysqlpp/udf_registration.hpp`, `MYSQL_ADD_COMPONENT`, `DISABLE_MISSING_PROFILE_WARNING` and the services. Use `git grep <sym> A -- include cmake CMakeLists.txt`, and check `git log A..X^` on those headers for relevant changes.
   - If a needed header first appears later (commit H > A): when it is self-contained at `A` (all its includes exist there) and its blob doesn't change between H and X, introduce that same blob at `A` with `--add <path>=H:<path>@A`. H then no longer adds it; the final tree is unchanged. Build A and H^ and H. Otherwise stop and ask.
3. **Renames first (optional separate branch).** Use `scripts/rewrite_range.py --move OLD=NEW` from `A` up to `X`, then verify. X then shows in-place edits only.
4. **Choose the mode.** Write the rules for one source file and one test, and run the X^→X gate (step 5) on them.
   - **Rule mode:** everything reproduces X (typical for UDF plugins: renames, descriptor→component macros, test install lines). Continue below.
   - **Backward-chain mode:** source files don't reproduce, because X rewrites APIs (services, sysvar registration, event tracking, THD storage). Use rules only for files that do reproduce (usually tests), and derive everything else with the backward chain (see that section). Tell the user the expected cost up front: a few hours per 10 touchers, mostly on resolutions and compile checks.

   **Write the transforms**: stdin→stdout programs, one per file kind. Adapt the ones in `examples/binlog_utils_udf/`, but re-derive every literal (copyright header, macros, test strings, error names) from X. Transforms run on every commit in `[A, X)` where the file exists, including lines that existed before A (packaging).
   - **.cc:** header and includes; component macros and `REQUIRES_SERVICE_PLACEHOLDER` instead of the plugin descriptor, registry and init boilerplate; drop the "plugin not installed" checks; rename the service pointer and reflow with `clang-format --lines`; add a component tail whose `known_udfs` lists **only the UDFs declared at that commit**. Parse declarations across line breaks.
   - **CMakeLists.txt:** component form from `A`. Keep each commit's own build-flag style so the commit that switched styles still shows that change.
   - **.test/.result:** `INSTALL/UNINSTALL COMPONENT` instead of `INSTALL PLUGIN` + `CREATE/DROP FUNCTION`; the "without loading" check expects `ER_SP_DOES_NOT_EXIST`.
   - **Packaging `.so` names and the `plugin.defs` rename:** from `A`, because that's where the artifact is renamed. If X also moves the `plugin.defs` line below a line added later by commit Q, the move takes effect in Q. Where X adds lines at the end of a list that other commits keep appending to, anchor on the list's end marker (e.g. the blank lines before `# support files`), not on a neighbouring line.
   - **Files with a single pre-X version** (no commit between their introduction and X touches them): use `scripts/replace_if.py X^:<old> X:<new>` as the transform. It emits X's blob and aborts on any other input.
   - **Files X creates** (component `.cc`/`.h` glue): `--add <path>=X:<path>@<introducing commit>`.
   - **Different introduction points** (e.g. tests added before the sources): give each `--move/--transform/--add` its own `@REV`; `--start` is the earliest.
5. **Validation gates.**
   - For every file, `git show X^:<old path> | transform | cmp - <(git show X:<new path>)` must succeed. Don't rewrite until all pass.
   - That only proves the last stage. For each earlier feature commit, pipe each transformed file through `scripts/check_stage.py cc|test|result|any <old_so_name>`: `known_udfs` must match the `DECLARE_*_UDF` declarations, and no plugin leftovers (`mysql_declare_plugin`, `INSTALL PLUGIN`, `SONAME`, the old `.so` name) may remain.
   - **Reverse gate:** `scripts/check_rules_noop.py --x X --prog "<rule prog> {new}" <new roots>`. Your rules applied to X's own files must change nothing. Every line it reports is a rule that over-applies, e.g. a sysvar rename that also hits an identically named UDF (`'audit_log_filter_flush'`) or an option value (`--x.file='audit_log_filter_file'`). Narrow the rule, or protect those lines.
   - Use the clang-format version the repo expects (`clang-format --version`), run from the worktree root so `.clang-format` is found. The first gate catches a mismatch.
6. **Rewrite.**
   ```sh
   scripts/rewrite_range.py --base BASE --head HEAD --start A --drop X \
     --transform "<path>=<prog args>" ... --append-msg-to A --show A --show Fn
   ```
   It rewrites raw commit objects, keeping messages, author and committer. It aborts unless X ends up a no-op, and appends X's message to A's after a `==========================================` line. Back up first, then `git branch OUT <printed tip>`.
7. **Verify.** Run `scripts/verify_rewrite.sh BASE HEAD OUT X <old paths>`. Expect:
   - equal tip trees
   - one fewer commit
   - X no longer an ancestor
   - only A's message changed
   - zero commits touching the old paths
8. **Build threads:** use 3/4 of the available cores, at most 80: `JOBS=$(( $(nproc) * 3 / 4 )); [ $JOBS -gt 80 ] && JOBS=80; ninja -j$JOBS`. When two builds run at the same time, split that budget between them instead of giving each the full count.
   `scripts/build_commit.sh WT BLD SHA [target] [name]` does this, initialises submodules and checks the .so for undefined symbols.
   **Build** A and every Fi at the new SHAs, and confirm `component_<name>.so` is produced. Build any other rewritten commit only if its change touches build inputs (CMake, sources); `plugin.defs`/test/packaging-only changes don't need a build.
9. **MTR.** Default scope is **A plus the last toucher** (tip-equivalent), plus single tests whose expected values you had to guess. Run intermediate commits only if the user asks: they take about 30 minutes each (full build plus suite), no baseline exists (the original commits often don't build, and old tests depend on the old harness), and most failures there are pre-existing (e.g. 8.0-era expectations on an 8.1 server). Report guessed values that weren't run as unverified.
   `scripts/mtr_commit.sh WT BLD TIP <suite>` applies the rules below. Use the in-tree runner if it works. If `mysql-test-run.pl` at old commits doesn't compile, run the test in a scratch `git worktree` of the commit with the tip's `mysql-test-run.pl` and `mysql-test/lib` overlaid, and `MTR_BINDIR=<build>`.
   - Keep the commit's own `include/plugin.defs` unless the newer harness rejects its format. If you overlay it, check the commit's `plugin.defs` line separately by eye.
   - Also run a control test (`main.1st`) with `--suite=main`; failures it shares are harness noise. Naming a test next to `--suite=X` restricts the run to that test; run them separately. Old servers under a new harness trigger the warnings check, so use `--nowarnings`: a test passes when its body completes with no result mismatch.

## Semantic conversions: backward chain
When X rewrites code (APIs, services, registration), rules can't reproduce X from X^. Walk X's content backwards over each toucher T instead: `scripts/backchain.py` computes `before(T) = merge(after(T), T:<old>, T^:<old>)`. Merge in normalized space (`--normalize`); derive rule-reproducible files (tests) with `--transform-files`.
- **Resolutions are edit scripts**, `res/<T12>/<newpath>.res.py` with `resolve(r)`. They are re-applied to a fresh merge on every run, so a change to a later-in-history step can't leave them stale. `scripts/mkres.py CHAIN RES T PATH` writes one from region lambdas (`keep_ours`, `keep_theirs`, `without(...)`) and dry-runs it. For files X restructured, edit `r.ours` with the `reslib` helpers (`drop`, `rep1`, `drop_between`, `drop_function`, `drop_decl_blocks`); they fail loudly when their anchor is gone. Never paste whole-file content: a stored full file (legacy form, still accepted) goes stale as soon as a later step changes.
- **`--special`**: fix recurring patterns in rules, not in many resolutions. Canonicalise after every step, but never rewrite a line that exists verbatim in X's copy of the file.
- **Check the chain after every step:** `scripts/check_chain.py --chain DIR --touchers FILE --map map.py --old-root plugin/<name>/ --allow FILE`.
  - **Anachronisms:** an identifier the plugin first gets in T must not exist before T.
  - **Containment:** before-T and after-T states differ only in paths T touches. For the last toucher any extra path is an error: rules rewrote X's content.
  - Put deliberate component infrastructure in the allowlist, with a reason for each entry (`path:<glob>` for restored files). Also compile every state (`materialize.sh` + `ccheck.sh`, or `build_commit.sh`). A MODULE link hides undefined symbols, so run `nm -uC <so> | grep <namespace>::`.
- **Component infrastructure stays.** Keep what the component needs in every state: registry accessor, component descriptor, sysvar registration, security-context helper and its headers. Don't restore plugin-only APIs (plugin services, THDVARs). Remove X-only features, such as a UDF replacing a sysvar, before the commit that introduced the plugin equivalent.
- **Moved code:** when T moves code from file a to file b, the merge can't carry X's edits across. Reapply them by hand or accept X's own pattern.
- **Clean merges re-add plugin-era blocks** next to the component's version of the same feature (duplicate structs/functions, renumbered variant indexes). For such files write the resolution against `r.ours` and remove only what T added.
- **Missing headers:** the plugin got many through plugin headers. Add them in the states that need them. Keep the rules narrow (file + header), because X relies on transitive includes too.
- **Rewrite:** `scripts/rewrite_chain.py` sets the new roots from the chain state of the latest toucher at or before each commit. It removes the old root, applies the misc transforms and adds, and asserts X is a no-op. Keep a `regen.sh` (chain → rewrite → input fixes such as round-trip pins) so every fix is one re-run. Build the rewritten commits themselves, not only the materialized states.

## Tests
- **Rename rules:** convert sysvar names only in sysvar positions (`SET GLOBAL x_`, `@@x_`, option lines, `restart:` parameters). Keep a collision list of names that are also UDFs or values (`audit_log_filter_flush`). Run the reverse gate above.
- **Per-test setup:** a plugin suite loads the plugin globally (suite.opt plugin-load) and may rely on MTR bootstrap for its tables; a component is installed by each test. `scripts/pair_tests.py` (library and CLI) adds install/tables-init at the top and uninstall/tables-cleanup at the bottom where they're missing, looking through local `.inc` files. Run it from a special rule on every state; it must be a no-op on X.
- **Startup options:** options in `-master.opt` are applied before the test installs the component, so read-only component variables never see them. Convert them to `--let $restart_parameters="restart: --<name>.<var>=..."` after the install (what X does), or expect status/value mismatches in older states.
- **Messages:** the server's own message text (messages_to_clients) and the audit API's event names come from the tree at that commit, not from X. Don't rewrite them in results.

## Common Mistakes
| Mistake | Fix |
|---|---|
| `rebase --autosquash` fixups from X | They 3-way-merge against a distant version, giving whole-file conflicts. Use transforms and plumbing. |
| Hunk splitting or positional splicing | Derive rules; the validation gate proves them. |
| One UDF list for all commits | List only the UDFs present at that commit. |
| Missing multi-line `DECLARE_*_UDF(` | Parse across line breaks and count UDFs per commit. |
| CMakeLists left in `plugin/` | Move it too; `components/*` is globbed. |
| Placing a line next to one that doesn't exist yet | The move takes effect where that line was added. |
| `git log --format=%B` messages, `rebase` dates | Rewrite raw objects to keep metadata. |
| Whole-file copies from the final tree into old commits | Never. Transform each commit's own version. |
| Trusting a failed MTR run at old commits | Check the harness first with the control test. |
| Full-file resolutions | They go stale when a later step changes; write `.res.py` edit scripts (`mkres.py`). |
| Finding anachronisms by compile errors | `check_chain.py` after every step; it takes seconds. |
| Blaming the conversion for broken originals | `scan_input.py` before starting; fix and report input defects separately. |
| `pkill -f PATTERN` from a tool shell | Kills that shell too (its command line contains PATTERN). Use `scripts/killpat.sh 'name[.]sh'`. |
| Reusing one cmake build dir across distant commits | A cache from another commit can hold conflicting options (`WITH_READLINE` vs `WITH_EDITLINE`): pass `-U<var>` or use a fresh dir. |
| Initialising submodules from `.gitmodules` | Old commits list paths that aren't gitlinks yet; use the 160000 entries of `git ls-tree -r HEAD` (`build_commit.sh` does). |
| `grep` on MTR/server logs | They contain binary bytes; plain `grep` silently matches nothing. Use `grep -a`. |
| `git branch -f` on a branch checked out in a worktree | Refused. Report the new SHA and let the user move it (`git reset --keep <sha>`). |
| Long-running jobs started with `&` | Use `setsid nohup ... &` so a finishing tool call doesn't kill them, and watch the log with a monitor. |

## Red Flags: stop
- A transform doesn't reproduce X byte for byte.
- X isn't a no-op after the rewrite.
- A required API is missing at `A`.
- An unexpected commit touches the paths.

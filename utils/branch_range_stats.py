#!/usr/bin/env python3
"""
For BASE_BRANCH..OUTPUT_BRANCH [OUTPUT_BRANCH2] print (in order):
  1) N largest commits (K/M numbers; lines wrapped to --width)
  2) Summary: commits in range, 'merge' subject count, pull-request merge stats, subject-ticket
     patterns (JIRA by project with ≥16 unique by default, Launchpad, Bug #), commits unclassified
     to any of those display classes
  3) If OUTPUT_BRANCH2 is given: JIRA tickets that appear in “big” projects (≥N unique) on
     BASE..OUTPUT but never appear in any subject on BASE..OUTPUT2, with commits on OUTPUT that
     reference each such ticket (commit titles truncated to 104 characters here).
  TDB, DOC, and DB are omitted from all JIRA-style counting and from (3).
  Use --no-subject-extras to skip (2) except commit count and merge line count.
  Use --jira-project-min N to change the JIRA project list threshold.
  Default max line width: 104.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
import textwrap
from collections import defaultdict

MERGE_LINE = re.compile(r"(?i)\bmerge\b")
INS = re.compile(r"(\d+)\s+insertion")
DELL = re.compile(r"(\d+)\s+deletion")

# Subject-line patterns (first line of commit message only, via git log %s)
JIRA_SUBJECT = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{2,})\b")
# Only list JIRA *projects* in the report when they have this many unique tickets
JIRA_PROJECT_LIST_MIN = 16
# Omit these JIRA project keys from stats and from the 3-way “missing vs branch2” list
IGNORED_JIRA_PROJECT_KEYS: frozenset[str] = frozenset({"TDB", "DOC", "DB"})
# First-line subject length when listing commits under each ticket (3-param mode only)
JIRA2_SUBJECT_MAX_LEN = 104
LP_SUBJECT = [
    re.compile(r"(?i)LP#?\s*(\d{4,8})\b"),
    re.compile(r"(?i)LP\s+#\s*(\d{4,8})\b"),
    re.compile(r"(?i)LP\s#(\d{4,8})\b"),
    re.compile(r"(?i)(?<![a-z0-9])lp(\d{5,8})(?![0-9])"),
]
BUG_SUBJECT = re.compile(r"(?i)Bug #(\d{4,7})\b")
# GitHub: "Merge pull request #1234 from ..."
PR_MERGE = re.compile(r"(?i)Merge pull request #(\d+)\b")


def _short(n: int) -> str:
    """Compact value: K/M suffix, no commas (e.g. 2576K, 2.5M)."""
    n = int(n)
    if n < 0:
        return str(n)
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        x = n / 1000.0
        s = f"{x:.1f}".rstrip("0").rstrip(".")
        return f"{s}K"
    x = n / 1_000_000.0
    s = f"{x:.1f}".rstrip("0").rstrip(".")
    return f"{s}M"


def _commit_block(
    tot: int,
    ins: int,
    dele: int,
    sh: str,
    subj: str,
    totw: int,
    insw: int,
    delw: int,
    max_width: int,
) -> list[str]:
    """Prefix + subject; columns padded so all rows have the same prefix width."""
    t_s = _short(tot)
    i_s = "+" + _short(ins)
    d_s = "-" + _short(dele)
    prefix = f"{t_s:>{totw}}  {i_s:>{insw}}  {d_s:>{delw}}  {sh}  "
    if not subj:
        return [prefix.rstrip()]
    line = prefix + subj
    if len(line) > max_width:
        return [line[: max_width - 3] + "..."]
    return [line]


def _run(cmd: list[str], **kwargs) -> str:
    opts: dict = {"text": True, "stderr": subprocess.DEVNULL}
    opts.update(kwargs)
    return subprocess.check_output(cmd, **opts)


def rev_parse(ref: str) -> str:
    try:
        return _run(["git", "rev-parse", "--verify", ref]).strip()
    except subprocess.CalledProcessError:
        print(f"Invalid ref: {ref!r}", file=sys.stderr)
        raise SystemExit(2) from None


def subject_pattern_stats(
    subjects: list[str],
) -> tuple[dict[str, set[str]], set[str], set[str], int, set[str]]:
    """JIRA keys, LP# ids, Bug# ids, # commits with GitHub PR merge, unique PR#."""
    per_proj: dict[str, set[str]] = defaultdict(set)
    lp_nums: set[str] = set()
    bug_nums: set[str] = set()
    pr_ids: set[str] = set()
    pr_merge_commits = 0
    for s in subjects:
        for m in JIRA_SUBJECT.finditer(s):
            full = m.group(1)
            k = full.split("-", 1)[0]
            if k == "LP" or k in IGNORED_JIRA_PROJECT_KEYS:
                continue
            per_proj[k].add(full)
        for pat in LP_SUBJECT:
            for m in pat.finditer(s):
                lp_nums.add(m.group(1))
        for m in BUG_SUBJECT.finditer(s):
            bug_nums.add(m.group(1))
        if PR_MERGE.search(s):
            pr_merge_commits += 1
        for m in PR_MERGE.finditer(s):
            pr_ids.add(m.group(1))
    return per_proj, lp_nums, bug_nums, pr_merge_commits, pr_ids


def subject_has_jira(s: str) -> bool:
    """True if subject has at least one JIRA-style token (PROJ-##) that we count (not LP; not TDB/DOC/DB)."""
    for m in JIRA_SUBJECT.finditer(s):
        k = m.group(1).split("-", 1)[0]
        if k != "LP" and k not in IGNORED_JIRA_PROJECT_KEYS:
            return True
    return False


def subject_matches_any_displayed_class(s: str) -> bool:
    """
    Classified if the subject (first line) matches any class we report: GitHub PR merge,
    JIRA-style, Launchpad (LP#), or Oracle/MySQL Bug #.
    """
    if PR_MERGE.search(s):
        return True
    if subject_has_jira(s):
        return True
    for pat in LP_SUBJECT:
        if pat.search(s):
            return True
    if BUG_SUBJECT.search(s):
        return True
    return False


def count_commits_unclassified_to_displayed(subjects: list[str]) -> int:
    """Commits whose subject does not match any of the above classes."""
    return sum(1 for s in subjects if not subject_matches_any_displayed_class(s))


def jira_tickets_in_big_projects(
    per_proj: dict[str, set[str]], jira_min: int
) -> set[str]:
    """All full ticket ids (e.g. PS-123) from project keys with ≥jira_min unique tickets."""
    out: set[str] = set()
    for k, v in per_proj.items():
        if len(v) >= jira_min:
            out |= v
    return out


def all_jira_id_strings_in_subjects(subjects: list[str]) -> set[str]:
    out: set[str] = set()
    for s in subjects:
        for m in JIRA_SUBJECT.finditer(s):
            t = m.group(1)
            k = t.split("-", 1)[0]
            if k != "LP" and k not in IGNORED_JIRA_PROJECT_KEYS:
                out.add(t)
    return out


def _jira_token_in_subject(ticket: str, subject: str) -> bool:
    return re.search(r"(?<![A-Z0-9])" + re.escape(ticket) + r"(?![A-Z0-9])", subject) is not None


def _print_lines(text: str, wlim: int) -> None:
    for line in textwrap.wrap(text, width=wlim) or [text]:
        print(line)


def _print_subject_extras(
    wlim: int,
    n_commits: int,
    not_classified: int,
    per_proj: dict[str, set[str]],
    lp_nums: set[str],
    bug_nums: set[str],
    pr_merge_commits: int,
    pr_ids: set[str],
    jira_project_min: int,
) -> None:
    all_jira: set[str] = set()
    for v in per_proj.values():
        all_jira |= v
    _print_lines(
        f"GitHub 'Merge pull request #…' commits: {pr_merge_commits} (unique PRs: {len(pr_ids)})",
        wlim,
    )
    _print_lines(
        f"Unique JIRA-style ticket strings: {len(all_jira)}",
        wlim,
    )
    _print_lines(
        f"Commits not classified to any displayed class: {not_classified}  of {n_commits:,}",
        wlim,
    )
    big = {k: v for k, v in per_proj.items() if len(v) >= jira_project_min}
    small = {k: v for k, v in per_proj.items() if len(v) < jira_project_min}
    small_tickets = sum(len(v) for v in small.values())
    _print_lines(
        f"JIRA by project (only projects with ≥{jira_project_min} unique tickets): {len(big)} project(s), "
        f"{sum(len(v) for v in big.values())} unique tickets listed.",
        wlim,
    )
    for proj in sorted(big, key=lambda k: (-len(big[k]), k)):
        _print_lines(f"  {proj}: {len(big[proj])} unique", wlim)
    if small:
        _print_lines(
            f"  (other project keys: {len(small)} key(s) with {small_tickets} unique tickets; "
            f"all below {jira_project_min} per key — not listed.)",
            wlim,
        )
    _print_lines(f"Unique Launchpad (LP#) bug numbers: {len(lp_nums)}", wlim)
    _print_lines(
        f"Unique Oracle/MySQL-style 'Bug #…' numbers in subject: {len(bug_nums)}", wlim
    )


def print_jira_missing_vs_branch2(
    wlim: int,
    base: str,
    tip1: str,
    tip2: str,
    jira_min: int,
    label1: str,
    label2: str,
) -> None:
    """
    Tickets from projects with ≥jira_min unique ids on BASE..tip1 that never appear
    in any first-line subject on BASE..tip2; list commits on tip1 range mentioning each.
    """
    r1, r2 = f"{base}..{tip1}", f"{base}..{tip2}"
    sub1 = _run(["git", "log", r1, "--format=%s"], errors="replace").splitlines()
    sub2 = _run(["git", "log", r2, "--format=%s"], errors="replace").splitlines()
    pp1, _, _, _, _ = subject_pattern_stats(sub1)
    in_big = jira_tickets_in_big_projects(pp1, jira_min)
    all2 = all_jira_id_strings_in_subjects(sub2)

    def _ticket_sort(t: str) -> tuple[str, int, str]:
        if "-" in t:
            a, b = t.rsplit("-", 1)
            if b.isdigit():
                return (a, int(b), t)
        return (t, 0, t)

    missing = sorted(in_big - all2, key=_ticket_sort)

    log_lines = _run(
        ["git", "log", r1, "--reverse", "--format=%H\t%s"],
        errors="replace",
    ).splitlines()
    h_subj: list[tuple[str, str]] = []
    for line in log_lines:
        if "\t" not in line:
            continue
        h, sub = line.split("\t", 1)
        h_subj.append((h, sub))
    print()
    _print_lines(
        f"JIRA tickets (projects with ≥{jira_min} unique on {label1} only) that never appear in "
        f"any first-line subject on {label2}  (`{base}..` vs same base on second tip): {len(missing)} ticket(s).",
        wlim,
    )
    def _trunc_commit_title(s: str) -> str:
        s = s.replace("\n", " ")
        mlen = JIRA2_SUBJECT_MAX_LEN
        if len(s) <= mlen:
            return s
        return s[: mlen - 3] + "..."

    for t in missing:
        hits = [(h, s) for h, s in h_subj if _jira_token_in_subject(t, s)]
        _print_lines(f"  {t}  ({len(hits)} commit(s) on {label1} range)", wlim)
        for h, s in hits:
            sh = h[:12] if len(h) > 12 else h
            one = f"    {sh}  {_trunc_commit_title(s)}"
            for wline in textwrap.wrap(one, width=wlim, subsequent_indent="    ") or [one]:
                print(wline)
    if not missing:
        _print_lines(
            f"  (none: every big-project ticket on {label1} appears at least once on {label2}.)",
            wlim,
        )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Stats for BASE_BRANCH..OUTPUT_BRANCH: commit count, merge grep count, top N by diff size."
    )
    p.add_argument(
        "branches",
        nargs="*",
        metavar="BRANCH",
        help="Two refs: BASE OUTPUT; or three: BASE OUTPUT OUTPUT2 (compare JIRA). "
        "Or omit and use $BASE_BRANCH, $OUTPUT_BRANCH, optional $OUTPUT_BRANCH2",
    )
    p.add_argument(
        "-N",
        "--largest",
        type=int,
        default=32,
        help="how many largest commits to list (default: 32)",
    )
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=32,
        help="parallel workers for shortstat (default: 32)",
    )
    p.add_argument(
        "-w",
        "--width",
        type=int,
        default=104,
        metavar="N",
        help="max line length for commit rows and summary lines (default: 104)",
    )
    p.add_argument(
        "--no-subject-extras",
        action="store_true",
        help="omit pull-request and ticket-pattern summary (JIRA, LP, Bug #)",
    )
    p.add_argument(
        "--jira-project-min",
        type=int,
        default=JIRA_PROJECT_LIST_MIN,
        metavar="N",
        help="only list JIRA projects in the per-project breakdown when they have "
        f"≥N unique tickets (default: {JIRA_PROJECT_LIST_MIN})",
    )
    args = p.parse_args()
    br = args.branches
    oname2: str | None = None
    if len(br) == 3:
        bname, oname, oname2 = br[0], br[1], br[2]
    elif len(br) == 2:
        bname, oname = br[0], br[1]
    elif len(br) == 0:
        bname = os.environ.get("BASE_BRANCH")
        oname = os.environ.get("OUTPUT_BRANCH")
        oname2 = os.environ.get("OUTPUT_BRANCH2")
    else:
        p.print_help()
        print(
            "\nPass two or three branch arguments (BASE OUTPUT [OUTPUT2]), or none with env.",
            file=sys.stderr,
        )
        return 2
    if not bname or not oname:
        p.print_help()
        print(
            "\nSet BASE_BRANCH and OUTPUT_BRANCH (and optional OUTPUT_BRANCH2) or pass "
            "branch arguments.",
            file=sys.stderr,
        )
        return 2

    base = rev_parse(bname)
    tip = rev_parse(oname)
    tip2: str | None = rev_parse(oname2) if oname2 else None
    
    stat_tip = tip2 if tip2 is not None else tip
    rng = f"{base}..{stat_tip}"
    n_commits = int(_run(["git", "rev-list", "--count", rng]).strip())

    # merge-line count: same as git log RANGE --format=%s | grep -Eiw 'merge' | wc -l
    subjects = _run(
        ["git", "log", rng, "--reverse", "--format=%s"]
    ).splitlines()
    merge_commits = [s for s in subjects if MERGE_LINE.search(s)]
    merge_lines = len(merge_commits)

    # i+d per commit (shortstat)
    hashes = _run(
        ["git", "rev-list", "--reverse", rng]
    ).split()

    wlim = max(40, args.width)

    if not hashes:
        print("(no commits in range)\n")
        a_txt = "Commits in range: 0"
        b_txt = "Commits with whole-word 'merge' in the subject: 0"
        for line in textwrap.wrap(a_txt, width=wlim) or [a_txt]:
            print(line)
        for line in textwrap.wrap(b_txt, width=wlim) or [b_txt]:
            print(line)
        if not args.no_subject_extras:
            _print_subject_extras(
                wlim,
                0,
                0,
                defaultdict(set),
                set(),
                set(),
                0,
                set(),
                args.jira_project_min,
            )
        if tip2 is not None and oname2 is not None:
            print_jira_missing_vs_branch2(
                wlim,
                base,
                tip,
                tip2,
                args.jira_project_min,
                oname,
                oname2,
            )
        return 0

    subj_by_h = {
        line.split("\t", 1)[0]: line.split("\t", 1)[1]
        for line in _run(
            ["git", "log", rng, "--reverse", "--format=%H\t%s"]
        ).splitlines()
        if "\t" in line
    }

    def one(h: str) -> tuple[str, int, int, int]:
        st = _run(
            [
                "git",
                "-c",
                "diff.renames=false",
                "show",
                "--no-patch",
                "--format=",
                "--shortstat",
                h,
            ]
        )
        ins = dele = 0
        m1, m2 = INS.search(st), DELL.search(st)
        if m1:
            ins = int(m1.group(1))
        if m2:
            dele = int(m2.group(1))
        tot = ins + dele
        return (h, ins, dele, tot)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        rows = list(ex.map(one, hashes, chunksize=32))
    rows.sort(key=lambda t: (-t[3], -t[2], t[0]))
    top = rows[: max(0, args.largest)]
    all_sum = sum(t[3] for t in rows)
    top_sum = sum(t[3] for t in top)
    n_top = len(top)

    if merge_lines > 0:
        print("Example commits with 'merge' in the subject:")
        seen_patterns = set()
        shown = 0
        
        def _merge_pattern(s: str) -> str:
            s = s.lower()
            if s.startswith("merged "):
                s = "merge " + s[7:]
            elif s.startswith("merging "):
                s = "merge " + s[8:]
            s = s.replace("fixes", "fix")
            s = re.sub(r"[^a-z\s]", " ", s)
            words = s.split()
            if not words:
                return ""
            if len(words) == 1:
                return words[0]
            if len(words) >= 3 and words[0] == "merge" and words[1] == "fix":
                return "merge fix"
            if len(words) >= 3 and words[0] == "merge" and words[1] == "pull" and words[2] == "request":
                return "merge pull request"
            if len(words) >= 3 and words[0] == "merge" and words[1] == "branch":
                return "merge branch"
            if len(words) >= 3 and words[0] == "empty" and words[1] == "merge":
                return "empty merge"
            if len(words) >= 3 and words[0] == "null" and words[1] == "merge":
                return "null merge"
            if len(words) >= 3 and words[0] == "manual" and words[1] == "merge":
                return "manual merge"
            return f"{words[0]} {words[1]}"

        for h in hashes:
            s = subj_by_h.get(h, "")
            if not MERGE_LINE.search(s):
                continue
            pat = _merge_pattern(s)
            if pat not in seen_patterns:
                seen_patterns.add(pat)
                sh = h[:12] if len(h) > 12 else h
                line = f"  {sh}  {s}"
                if len(line) > wlim:
                    line = line[: wlim - 3] + "..."
                print(line)
                shown += 1
                if shown >= 10:
                    break
        print()

    n_list = args.largest
    print(
        f"Top {n_list} by (insertions+deletions) from shortstat "
        "(git -c diff.renames=false), largest first:"
    )
    totw = max(len(_short(t[3])) for t in top) if top else 1
    insw = max(len("+" + _short(t[1])) for t in top) if top else 1
    delw = max(len("-" + _short(t[2])) for t in top) if top else 1
    for h, ins, dele, tot in top:
        sh = h[:12] if len(h) > 12 else h
        subj = subj_by_h.get(h, "")
        for pl in _commit_block(tot, ins, dele, sh, subj, totw, insw, delw, wlim):
            print(pl)
    for line in textwrap.wrap(
        f"total (insertions+deletions) for all commits: {_short(all_sum)}",
        width=wlim,
    ) or [
        f"total (insertions+deletions) for all commits: {_short(all_sum)}"
    ]:
        print(line)
    for line in textwrap.wrap(
        f"total (insertions+deletions) for top {n_top} commits: {_short(top_sum)}",
        width=wlim,
    ) or [
        f"total (insertions+deletions) for top {n_top} commits: {_short(top_sum)}"
    ]:
        print(line)
    print()
    a_txt = f"Commits in range: {n_commits:,}"
    b_txt = f"Commits with whole-word 'merge' in the subject: {merge_lines:,}"
    for line in textwrap.wrap(a_txt, width=wlim) or [a_txt]:
        print(line)
    for line in textwrap.wrap(b_txt, width=wlim) or [b_txt]:
        print(line)
    if not args.no_subject_extras:
        pp, lp, bugs, pr_mc, pr_ids = subject_pattern_stats(subjects)
        n_uncl = count_commits_unclassified_to_displayed(subjects)
        _print_subject_extras(
            wlim,
            n_commits,
            n_uncl,
            pp,
            lp,
            bugs,
            pr_mc,
            pr_ids,
            args.jira_project_min,
        )

    if tip2 is not None and oname2 is not None:
        print_jira_missing_vs_branch2(
            wlim,
            base,
            tip,
            tip2,
            args.jira_project_min,
            oname,
            oname2,
        )

        print()
        print(f"History for '1581949' on {base}..{tip2}:")
        try:
            out = _run(["git", "log", "--oneline", f"{base}..{tip2}"], errors="replace")
            for line in out.splitlines():
                if "1581949" in line:
                    print(line)
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())

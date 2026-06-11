#!/usr/bin/env python3
"""
ps-reorder2.py

Two-pass Percona Server branch reorder tool.

Pass 1 emits g1-g4, the groups that may split or squash source commits.
Pass 2 emits g5-g10, and at each group tries to promote matching g11 commits
with a real git cherry-pick conflict probe. Commits that do not match or do not
probe cleanly remain in g11.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from collections import defaultdict


MAX_SUBJECT_LEN = 91
BATCH_SIZE = 400
OUTPUT_STAT_LINE_LEN = 104


GROUPS = {
    1: "Squashes",
    2: "build-ps",
    3: "CI configs",
    4: "MyRocks: storage and MTR",
    5: "MTR tests",
    6: "Non-code changes",
    7: "TokuDB+MyRocks kernel changes",
    8: "Build/Compilation",
    9: "Upstream bug fixes",
    10: "Code changes",
    11: "New commits",
}


MARKER_SUBJECTS = {
    1: "==================== MARKER: GROUP 1 — Squashes ====================",
    2: "==================== MARKER: GROUP 2 — build-ps ====================",
    3: "==================== MARKER: GROUP 3 — CI configs ====================",
    4: "==================== MARKER: GROUP 4 — MyRocks: storage and MTR ==========",
    5: "==================== MARKER: GROUP 5 — MTR tests ====================",
    6: "==================== MARKER: GROUP 6 — Non-code changes ==================",
    7: "==================== MARKER: GROUP 7 — TokuDB+MyRocks kernel changes =====",
    8: "==================== MARKER: GROUP 8 — Build/Compilation =================",
    9: "==================== MARKER: GROUP 9 — Upstream bug fixes ================",
    10: "==================== MARKER: GROUP 10 — Code changes ====================",
    11: "==================== MARKER: GROUP 11 — New commits ====================",
}


GROUP_NAME_TO_NUMBER = {name: number for number, name in GROUPS.items()}
MARKER_RE = re.compile(r"^={3,} MARKER: GROUP \d+ — (.+?) ={3,}$")


G1_DOC = "doc"
G1_MAN = "man"
G1_INTERNAL = "internal"
G1_TOKUDB_BACKUP = "tokudb-backup-plugin"
G1_STORAGE_TOKUDB = "storage-tokudb"
G1_PS_TOKUDB_ADMIN = "ps-tokudb-admin"
G1_VERSION_UNIV = "version-univ"
G1_TOKUDB_TESTS = "tokudb-tests"


G1_SUBJECTS = {
    G1_DOC: "Squash: doc/",
    G1_MAN: "Squash: man/",
    G1_INTERNAL: "Squash: internal/",
    G1_TOKUDB_BACKUP: "Squash: plugin/tokudb-backup-plugin/",
    G1_STORAGE_TOKUDB: "Squash: storage/tokudb/",
    G1_PS_TOKUDB_ADMIN: "Squash: scripts/ps_tokudb_admin.sh and scripts/fill_help_tables.sql",
    G1_VERSION_UNIV: "Squash: MYSQL_VERSION, VERSION and storage/innobase/include/univ.i",
    G1_TOKUDB_TESTS: "Squash: mysql-test/suite/tokudb* and MTR *toku* tests",
}


CODE_EXTENSIONS = (
    ".h", ".hh", ".hpp", ".hxx",
    ".c", ".cc", ".cpp", ".cxx",
)


class Style:
    def __init__(self):
        self.enabled = False

    def wrap(self, code, text):
        if not self.enabled or not text:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text):
        return self.wrap("1", text)

    def dim(self, text):
        return self.wrap("2", text)

    def red(self, text):
        return self.wrap("31", text)

    def green(self, text):
        return self.wrap("32", text)

    def yellow(self, text):
        return self.wrap("33", text)

    def blue(self, text):
        return self.wrap("34", text)

    def magenta(self, text):
        return self.wrap("35", text)

    def cyan(self, text):
        return self.wrap("36", text)


STYLE = Style()


def configure_color(mode):
    if mode == "always":
        STYLE.enabled = True
    elif mode == "never":
        STYLE.enabled = False
    elif os.environ.get("NO_COLOR") is not None:
        STYLE.enabled = False
    elif os.environ.get("FORCE_COLOR"):
        STYLE.enabled = True
    else:
        STYLE.enabled = sys.stderr.isatty()


def log(message):
    print(message, file=sys.stderr, flush=True)


def fmt_group(group):
    return STYLE.cyan(f"g{group}")


def fmt_sha(sha):
    return STYLE.yellow(sha[:12])


def fmt_subject(subject):
    return STYLE.bold(subject)


def truncate_text(text, max_len=OUTPUT_STAT_LINE_LEN):
    return text if len(text) <= max_len else text[:max_len]


def truncate_subject_for_prefix(prefix, subject):
    return truncate_text(subject, max(0, OUTPUT_STAT_LINE_LEN - len(prefix)))


def log_section(message):
    log(STYLE.bold(STYLE.blue(message)))


def log_marker(group, subject):
    log(f"{STYLE.cyan('marker')} {fmt_group(group)}: {STYLE.dim(subject)}")


def log_emit(group, source_hash, new_hash, subject):
    prefix = f"emit g{group} {source_hash[:12]} -> {new_hash[:12]} "
    subject = truncate_subject_for_prefix(prefix, subject)
    log(
        f"{STYLE.green('emit')} {fmt_group(group)} "
        f"{fmt_sha(source_hash)} -> {fmt_sha(new_hash)} {fmt_subject(subject)}"
    )


def log_skip(group, source_hash, subject):
    prefix = f"skip g{group} {source_hash[:12]} "
    subject = truncate_subject_for_prefix(prefix, subject)
    log(f"{STYLE.yellow('skip')} {fmt_group(group)} {fmt_sha(source_hash)} {subject}")


def log_keep(source_hash, group, reason):
    prefix = f"keep g11 {source_hash[:12]} from g{group}: "
    reason = truncate_text(reason, max(0, OUTPUT_STAT_LINE_LEN - len(prefix)))
    log(
        f"{STYLE.red('keep')} g11 {fmt_sha(source_hash)} "
        f"from {fmt_group(group)}: {STYLE.yellow(reason)}"
    )


def log_move_to_g10(source_hash, group, reason):
    prefix = f"move g10 {source_hash[:12]} from g{group}: "
    reason = truncate_text(reason, max(0, OUTPUT_STAT_LINE_LEN - len(prefix)))
    log(
        f"{STYLE.red('move')} {fmt_group(10)} {fmt_sha(source_hash)} "
        f"from {fmt_group(group)}: {STYLE.yellow(reason)}"
    )


def log_summary(group, promoted, kept_conflict, skipped_empty):
    log(
        f"{fmt_group(group)} promotions: "
        f"{STYLE.green(str(promoted))} promoted, "
        f"{STYLE.red(str(kept_conflict))} conflicted, "
        f"{STYLE.yellow(str(skipped_empty))} empty"
    )


def run_git(args, check=True, env=None, retry_on_lock=True):
    tries = 3 if retry_on_lock else 1
    last = None
    for attempt in range(tries):
        last = subprocess.run(
            ["git"] + list(args),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=env,
        )
        if last.returncode == 0:
            return last
        if retry_on_lock and "index.lock" in (last.stdout + last.stderr):
            time.sleep(0.3 * (attempt + 1))
            continue
        break

    if check and last.returncode != 0:
        cmd = "git " + " ".join(args)
        raise RuntimeError(
            f"{cmd} failed with rc={last.returncode}\n"
            f"STDOUT:\n{last.stdout}\nSTDERR:\n{last.stderr}"
        )
    return last


def git_rev_parse(rev):
    return run_git(["rev-parse", rev]).stdout.strip()


def branch_exists(ref):
    return run_git(["rev-parse", "--verify", "--quiet", ref],
                   check=False).returncode == 0


def current_branch():
    r = run_git(["symbolic-ref", "--short", "-q", "HEAD"], check=False)
    return r.stdout.strip() or None


def ensure_clean_worktree():
    r = run_git(["status", "--porcelain"], check=False)
    if r.stdout.strip():
        raise RuntimeError("working tree is not clean; commit or stash changes")


def get_commit_list(base, head):
    r = run_git(["log", "--first-parent", "--reverse", "--format=%H",
                 f"{base}..{head}"])
    return [line for line in r.stdout.splitlines() if line]


def get_commit_parents(commit):
    r = run_git(["rev-list", "--parents", "-n", "1", commit])
    parts = r.stdout.strip().split()
    return parts[1:]


def get_commit_files(commit):
    parents = get_commit_parents(commit)
    if not parents:
        r = run_git(["ls-tree", "-r", "--name-only", commit])
        return [line for line in r.stdout.splitlines() if line]
    r = run_git(["diff", "--name-only", "--no-renames", parents[0], commit])
    return [line for line in r.stdout.splitlines() if line]


def get_commit_deleted_paths(commit):
    parents = get_commit_parents(commit)
    if not parents:
        return []
    r = run_git([
        "diff", "--name-only", "--diff-filter=D", "--no-renames",
        parents[0], commit,
    ])
    return [line for line in r.stdout.splitlines() if line]


def get_commit_info(commit):
    sep = "\x1f"
    fmt = sep.join(["%H", "%an", "%ae", "%aI", "%cn", "%ce", "%cI", "%s", "%B"])
    r = run_git(["show", "-s", f"--format={fmt}", commit])
    parts = r.stdout.rstrip("\n").split(sep, 8)
    if len(parts) != 9:
        raise RuntimeError(f"could not parse commit metadata for {commit}")
    full_message = parts[8].rstrip("\n")
    body = ""
    if "\n" in full_message:
        body = full_message.split("\n", 1)[1].lstrip("\n")
    return {
        "hash": parts[0],
        "author_name": parts[1],
        "author_email": parts[2],
        "author_date": parts[3],
        "committer_name": parts[4],
        "committer_email": parts[5],
        "committer_date": parts[6],
        "subject": parts[7],
        "body": body,
    }


def marker_group(subject):
    m = MARKER_RE.match(subject)
    if not m:
        return None
    return GROUP_NAME_TO_NUMBER.get(m.group(1).strip())


def parse_source_commits(commits):
    infos = {commit: get_commit_info(commit) for commit in commits}
    has_marker = any(marker_group(info["subject"]) is not None
                     for info in infos.values())
    current = 11
    parsed = []
    removed_markers = []

    for pos, commit in enumerate(commits):
        info = infos[commit]
        group = marker_group(info["subject"])
        if group is not None:
            current = group
            removed_markers.append({
                "hash": commit,
                "subject": info["subject"],
                "reason": f"source marker for group {group} omitted; output markers are regenerated",
            })
            continue
        parsed.append({
            "hash": commit,
            "pos": pos,
            "info": info,
            "source_group": current if has_marker else 11,
            "files": get_commit_files(commit),
        })
    return parsed, removed_markers, has_marker


def final_removed_base_paths(base_hash, input_hash):
    r = run_git([
        "diff", "--name-only", "--diff-filter=D", "--no-renames",
        base_hash, input_hash,
    ])
    return set(line for line in r.stdout.splitlines() if line)


def analyze_removed_paths(parsed, base_hash, input_hash):
    base_removed = final_removed_base_paths(base_hash, input_hash)
    deleted_in_range = set()
    first_removal_info = None

    for src in parsed:
        deleted = set(get_commit_deleted_paths(src["hash"]))
        if not deleted:
            continue
        deleted_in_range.update(deleted)
        if first_removal_info is None and deleted.intersection(base_removed):
            first_removal_info = src["info"]

    transient_candidates = deleted_in_range.difference(base_removed)
    _present_in_base, absent_in_base = split_present_absent(
        base_hash, transient_candidates)
    _present_in_input, absent_in_input = split_present_absent(
        input_hash, absent_in_base)
    transient_removed = set(absent_in_input)

    if base_removed and first_removal_info is None:
        first_removal_info = parsed[-1]["info"] if parsed else get_commit_info(input_hash)

    return {
        "base_removed": base_removed,
        "transient_removed": transient_removed,
        "base_removal_info": first_removal_info,
    }


def is_tokudb_mtr_test_path(path):
    base = os.path.basename(path)
    return (
        path.startswith("mysql-test/suite/tokudb") or
        (path.startswith("mysql-test/") and "toku" in base.lower())
    )


def is_ci_path(path):
    return (
        path == ".travis.yml" or
        path.startswith(".circleci/") or
        path == "azure-pipelines.yml" or
        path == ".cirrus.yml" or
        path == ".clang-tidy" or
        path.startswith(".github/workflows/")
    )


def is_g4_path(path):
    return (
        path == "storage/rocksdb" or
        path.startswith("storage/rocksdb/") or
        path == "mysql-test/suite/rocksdb" or
        path.startswith("mysql-test/suite/rocksdb") or
        path == "mysql-test/include/have_rocksdb.inc" or
        path == "mysql-test/include/have_rocksdb_as_default.inc"
    )


def classify_g1(path):
    if path.startswith("doc/"):
        return G1_DOC
    if path.startswith("man/"):
        return G1_MAN
    if path.startswith("internal/"):
        return G1_INTERNAL
    if path.startswith("plugin/tokudb-backup-plugin/"):
        return G1_TOKUDB_BACKUP
    if path.startswith("storage/tokudb/"):
        return G1_STORAGE_TOKUDB
    if path in {"scripts/ps_tokudb_admin.sh", "scripts/fill_help_tables.sql"}:
        return G1_PS_TOKUDB_ADMIN
    if path in {"MYSQL_VERSION", "VERSION", "storage/innobase/include/univ.i"}:
        return G1_VERSION_UNIV
    if is_tokudb_mtr_test_path(path):
        return G1_TOKUDB_TESTS
    return None


def split_paths(paths):
    g1 = defaultdict(list)
    g2 = []
    g3 = []
    g4 = []
    rest = []

    for path in paths:
        g1_cat = classify_g1(path)
        if g1_cat is not None:
            g1[g1_cat].append(path)
        elif path.startswith("build-ps/") or path.startswith("scripts/systemd/"):
            g2.append(path)
        elif is_ci_path(path):
            g3.append(path)
        elif is_g4_path(path):
            g4.append(path)
        else:
            rest.append(path)
    return g1, g2, g3, g4, rest


def is_code_file(path):
    return path.endswith(CODE_EXTENSIONS)


def is_build_only_file(path):
    base = os.path.basename(path)
    return (
        base == "CMakeLists.txt" or
        path.endswith(".cmake") or
        path.endswith(".cmake.in")
    )


def is_build_only_changes(paths):
    return bool(paths) and all(is_build_only_file(path) for path in paths)


def is_code_changes(paths):
    return bool(paths) and any(is_code_file(path) for path in paths)


def touches_only_mysql_test(paths):
    return bool(paths) and all(path.startswith("mysql-test/") for path in paths)


def is_g5_promotable_path(path):
    return (
        path.startswith("mysql-test/") or
        path.endswith(".test") or
        path.endswith(".result") or
        path.endswith(".results") or
        path.endswith(".opt")
    )


def is_result_file(path):
    return path.endswith(".result")


def is_result_only_commit(paths):
    return bool(paths) and all(is_result_file(path) for path in paths)


def add_subject_prefix(subject, prefix, space_before_plain=False):
    if subject.startswith(prefix):
        return subject
    separator = " " if space_before_plain and not subject.startswith("[") else ""
    return f"{prefix}{separator}{subject}"


def is_g5_promotable_commit(paths):
    return bool(paths) and all(is_g5_promotable_path(path) for path in paths)


def is_upstream_subject(subject):
    return subject.startswith("[upstream]")


def is_kernel_subject_or_path(subject, paths):
    lowered = subject.lower()
    if any(token in lowered for token in ("tokudb", "toku", "myr", "rocks", "rocksdb")):
        return True
    for path in paths:
        lowered_path = path.lower()
        if any(token in lowered_path for token in ("tokudb", "toku", "myr", "rocks", "rocksdb")):
            return True
    return False


def matches_target_group(item, group):
    subject = item["subject"]
    paths = item["files"]

    if group == 5:
        return is_g5_promotable_commit(paths)
    if group == 6:
        return (
            bool(paths) and
            not is_code_changes(paths) and
            not is_build_only_changes(paths)
        )
    if group == 7:
        return is_kernel_subject_or_path(subject, paths)
    if group == 8:
        return is_build_only_changes(paths)
    if group == 9:
        return is_upstream_subject(subject)
    if group == 10:
        return (
            is_code_changes(paths) and
            not matches_target_group(item, 5) and
            not matches_target_group(item, 6) and
            not matches_target_group(item, 7) and
            not matches_target_group(item, 8) and
            not matches_target_group(item, 9)
        )
    raise ValueError(f"invalid target group: {group}")


def make_item(src, files, target_group, kind):
    info = src["info"]
    return {
        "source_hash": src["hash"],
        "source_pos": src["pos"],
        "source_group": src["source_group"],
        "info": info,
        "subject": info["subject"],
        "body": info["body"],
        "files": sorted(set(files)),
        "target_group": target_group,
        "kind": kind,
    }


def add_file_source_override(item, path, source_hash):
    if path not in item["files"]:
        item["files"].append(path)
        item["files"].sort()
    history = item.setdefault("source_history_by_file", {})
    history.setdefault(path, [item["source_hash"]]).append(source_hash)
    item.setdefault("source_by_file", {})[path] = source_hash


def register_result_file_occurrences(item, result_file_last_item):
    for path in item["files"]:
        if is_result_file(path):
            result_file_last_item[path] = item


def squash_result_files_into_previous(paths, source_hash, result_file_last_item):
    remaining = []
    squashed = 0
    for path in paths:
        previous_item = result_file_last_item.get(path)
        if previous_item is None:
            remaining.append(path)
            continue
        add_file_source_override(previous_item, path, source_hash)
        squashed += 1
    return remaining, squashed


def split_g1_paths(paths):
    g1 = defaultdict(list)
    rest = []
    for path in paths:
        cat = classify_g1(path)
        if cat is None:
            rest.append(path)
        else:
            g1[cat].append(path)
    return g1, rest


def plan_commits(parsed, removed_markers, removed_paths, base_hash):
    base_removed = set(removed_paths["base_removed"])
    transient_removed = set(removed_paths["transient_removed"])
    skipped_paths = base_removed.union(transient_removed)
    plan = {
        "g1_files": defaultdict(set),
        "g1_first_info": {},
        "g1_first_pos": {},
        "buckets": {number: [] for number in range(2, 12)},
        "removed": list(removed_markers),
        "base_removed_files": sorted(base_removed),
        "transient_removed_files": sorted(transient_removed),
        "base_removal_info": removed_paths["base_removal_info"],
        "base_removed_refs_skipped": 0,
        "transient_removed_refs_skipped": 0,
        "result_only_files_squashed": 0,
        "result_only_commits_elided": 0,
        "result_only_base_files_kept": 0,
        "result_only_base_commits_kept": 0,
    }

    result_file_last_item = {}

    def append_bucket_item(group, item):
        plan["buckets"][group].append(item)
        register_result_file_occurrences(item, result_file_last_item)

    for src in parsed:
        files = src["files"]
        if skipped_paths:
            base_refs = sum(1 for path in files if path in base_removed)
            transient_refs = sum(1 for path in files if path in transient_removed)
            if base_refs or transient_refs:
                plan["base_removed_refs_skipped"] += base_refs
                plan["transient_removed_refs_skipped"] += transient_refs
                files = [path for path in files if path not in skipped_paths]
                if not files:
                    details = []
                    if base_refs:
                        details.append(f"{base_refs} base_removed_files reference(s)")
                    if transient_refs:
                        details.append(
                            f"{transient_refs} transient_removed_files reference(s)")
                    plan["removed"].append({
                        "hash": src["hash"],
                        "subject": src["info"]["subject"],
                        "reason": (
                            "all changed paths were skipped because they are "
                            f"absent from INPUT ({', '.join(details)})"
                        ),
                    })
                    continue

        g1, files = split_g1_paths(files)

        for cat, paths in g1.items():
            plan["g1_files"][cat].update(paths)
            if cat not in plan["g1_first_info"]:
                plan["g1_first_info"][cat] = src["info"]
                plan["g1_first_pos"][cat] = src["pos"]

        if is_result_only_commit(files):
            result_files_before_squash = list(files)
            files, squashed = squash_result_files_into_previous(
                files, src["hash"], result_file_last_item)
            plan["result_only_files_squashed"] += squashed

            if not files:
                plan["result_only_commits_elided"] += 1
                plan["removed"].append({
                    "hash": src["hash"],
                    "subject": src["info"]["subject"],
                    "reason": (
                        f"all {len(result_files_before_squash)} .result path(s) "
                        "were squashed into previous in-range commit(s)"
                    ),
                })
                continue

            base_result_files, files = split_present_absent(base_hash, files)
            if base_result_files:
                plan["result_only_base_files_kept"] += len(base_result_files)
                plan["result_only_base_commits_kept"] += 1
                item = make_item(src, base_result_files, 11, "result-only")
                item["subject"] = add_subject_prefix(
                    src["info"]["subject"], "[result-only]",
                    space_before_plain=True)
                item["result_only"] = True
                append_bucket_item(11, item)

            if not files:
                continue

        _g1_unused, g2, g3, g4, rest = split_paths(files)

        if g2:
            append_bucket_item(2, make_item(src, g2, 2, "split"))
        if g3:
            append_bucket_item(3, make_item(src, g3, 3, "split"))
        if g4:
            append_bucket_item(4, make_item(src, g4, 4, "split"))

        if not rest:
            if g1 or g2 or g3 or g4:
                plan["removed"].append({
                    "hash": src["hash"],
                    "subject": src["info"]["subject"],
                    "reason": "all paths consumed by g1-g4 split/squash planning",
                })
            else:
                plan["removed"].append({
                    "hash": src["hash"],
                    "subject": src["info"]["subject"],
                    "reason": "source commit has no changed paths",
                })
            continue

        source_group = src["source_group"]
        if 5 <= source_group <= 10:
            append_bucket_item(
                source_group, make_item(src, rest, source_group, "source-group"))
        else:
            append_bucket_item(11, make_item(src, rest, 11, "remaining"))

    for bucket in plan["buckets"].values():
        bucket.sort(key=lambda item: item["source_pos"])
    return plan


def batched(paths, size=BATCH_SIZE):
    for idx in range(0, len(paths), size):
        yield paths[idx:idx + size]


def split_present_absent(treeish, paths):
    if not paths:
        return [], []
    unique = sorted(set(paths))
    present = set()
    for batch in batched(unique):
        r = run_git(["ls-tree", treeish, "--"] + batch, check=False)
        for line in r.stdout.splitlines():
            if "\t" in line:
                present.add(line.split("\t", 1)[1])
    return [path for path in paths if path in present], [path for path in paths if path not in present]


def checkout_paths(treeish, paths):
    for batch in batched(paths):
        run_git(["checkout", treeish, "--"] + batch)


def remove_paths(paths):
    for batch in batched(paths):
        run_git(["rm", "-rf", "--quiet", "--ignore-unmatch", "--"] + batch,
                check=False)


def apply_file_states(treeish, paths):
    paths = sorted(set(paths))
    present, absent = split_present_absent(treeish, paths)
    checkout_paths(treeish, present)
    remove_paths(absent)


def apply_item_file_states(item):
    source_by_file = item.get("source_by_file") or {}
    if not source_by_file:
        apply_file_states(item["source_hash"], item["files"])
        return

    paths_by_source = defaultdict(list)
    for path in item["files"]:
        paths_by_source[source_by_file.get(path, item["source_hash"])].append(path)
    for source_hash, paths in paths_by_source.items():
        apply_file_states(source_hash, paths)


def build_message(subject, body):
    if len(subject) <= MAX_SUBJECT_LEN:
        return subject + ("\n\n" + body if body.strip() else "")
    truncated = subject[:MAX_SUBJECT_LEN]
    full_body = f"Original title:\n{subject}"
    if body.strip():
        full_body += "\n\n" + body
    return truncated + "\n\n" + full_body


def commit_with_info(info, subject, body="", allow_empty=False):
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = info["author_name"]
    env["GIT_AUTHOR_EMAIL"] = info["author_email"]
    env["GIT_AUTHOR_DATE"] = info["author_date"]
    env["GIT_COMMITTER_NAME"] = info["committer_name"]
    env["GIT_COMMITTER_EMAIL"] = info["committer_email"]
    env["GIT_COMMITTER_DATE"] = info["committer_date"]

    cmd = ["commit", "-m", build_message(subject, body)]
    if allow_empty:
        cmd.append("--allow-empty")
    r = run_git(cmd, check=False, env=env)
    if r.returncode == 0:
        return True
    combined = (r.stdout + r.stderr).lower()
    if "nothing to commit" in combined or "no changes added" in combined:
        return False
    raise RuntimeError(
        f"git commit failed for {subject!r}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    )


def emit_marker(group):
    subject = MARKER_SUBJECTS[group]
    run_git(["commit", "--allow-empty", "-m", subject])
    log_marker(group, subject)


def emit_item(item, report, label):
    apply_item_file_states(item)
    ok = commit_with_info(item["info"], item["subject"], item["body"])
    entry = {
        "hash": item["source_hash"],
        "subject": item["subject"],
        "group": item["target_group"],
        "label": label,
    }
    if ok:
        new_head = git_rev_parse("HEAD")
        entry["new_hash"] = new_head
        report["emitted"].append(entry)
        log_emit(item["target_group"], item["source_hash"], new_head,
                 item["subject"])
        return True

    entry["reason"] = "planned item produced no staged changes"
    report["skipped"].append(entry)
    log_skip(item["target_group"], item["source_hash"], item["subject"])
    return False


def emit_squash(input_hash, cat, files, info, report):
    subject = G1_SUBJECTS[cat]
    apply_file_states(input_hash, sorted(files))
    body = (
        f"Squashed {len(files)} path(s) into group 1 category {cat}.\n\n"
        f"First source commit: {info['hash']}"
    )
    ok = commit_with_info(info, subject, body)
    entry = {
        "category": cat,
        "subject": subject,
        "paths": len(files),
        "first_source": info["hash"],
    }
    if ok:
        entry["new_hash"] = git_rev_parse("HEAD")
        report["squashed"].append(entry)
        log(
            f"{STYLE.magenta('squash')} {fmt_group(1)} {STYLE.bold(cat)}: "
            f"{STYLE.green(str(len(files)))} path(s)"
        )
    else:
        entry["reason"] = "squash produced no staged changes"
        report["skipped"].append(entry)
        log(f"{STYLE.yellow('skip')} {fmt_group(1)} {cat}: no staged changes")


def emit_base_removed_files(plan, report):
    files = plan["base_removed_files"]
    if not files:
        log(f"{STYLE.dim('base_removed_files')}: none")
        return False

    info = plan["base_removal_info"]
    remove_paths(files)
    subject = "Remove files deleted by input branch"
    body = (
        f"Removed {len(files)} path(s) that existed in BASE_BRANCH and are "
        "absent from INPUT_BRANCH."
    )
    ok = commit_with_info(info, subject, body)
    entry = {
        "paths": len(files),
        "subject": subject,
        "first_source": info["hash"],
    }
    if ok:
        entry["new_hash"] = git_rev_parse("HEAD")
        report["base_removed"].append(entry)
        log(
            f"{STYLE.red('remove')} {fmt_group(1)} "
            f"{STYLE.yellow(str(len(files)))} base_removed_files"
        )
    else:
        entry["reason"] = "base_removed_files removal produced no staged changes"
        report["skipped"].append(entry)
        log(f"{STYLE.yellow('skip')} {fmt_group(1)} base_removed_files")
    return ok


def is_conflict_output(text):
    lowered = text.lower()
    return any(token in lowered for token in (
        "conflict",
        "would be overwritten",
        "unmerged",
        "needs merge",
    ))


def conflict_summary(output):
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in lines:
        lowered = line.lower()
        if (
            "conflict" in lowered or
            "failed" in lowered or
            "error" in lowered or
            "would be overwritten" in lowered or
            "needs merge" in lowered
        ):
            return line
    return lines[0] if lines else "conflict"


def is_empty_cherry_pick_output(text):
    lowered = text.lower()
    return any(token in lowered for token in (
        "previous cherry-pick is now empty",
        "cherry-pick is now empty",
        "nothing to commit",
        "the previous cherry-pick is now empty",
        "is empty",
    ))


def add_failed_promotion_prefix(subject, group):
    prefix = f"[g{group}]"
    if subject.startswith(prefix):
        return subject
    return f"{prefix}{subject}"


def item_source_pos(item):
    return item.get("source_pos", -1)


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
PATCH_HUNK_CACHE = {}


def item_source_cache_key(item):
    source_by_file = item.get("source_by_file") or {}
    source_history_by_file = item.get("source_history_by_file") or {}
    source_history_key = tuple(
        (path, tuple(sources))
        for path, sources in sorted(source_history_by_file.items())
    )
    return (
        item["source_hash"],
        tuple(sorted(item["files"])),
        tuple(sorted(source_by_file.items())),
        source_history_key,
    )


def range_with_min_width(start, count):
    count = max(count, 1)
    return start, start + count - 1


def item_patch_hunks(item):
    key = item_source_cache_key(item)
    if key in PATCH_HUNK_CACHE:
        return PATCH_HUNK_CACHE[key]

    source_by_file = item.get("source_by_file") or {}
    if source_by_file:
        hunks = []
        paths_by_source = defaultdict(list)
        source_history_by_file = item.get("source_history_by_file") or {}
        for path in item["files"]:
            source_history = source_history_by_file.get(path)
            if source_history:
                for source_hash in source_history:
                    paths_by_source[source_hash].append(path)
            else:
                paths_by_source[source_by_file.get(
                    path, item["source_hash"])].append(path)
        for source_hash, paths in paths_by_source.items():
            hunks.extend(item_patch_hunks({
                "source_hash": source_hash,
                "files": paths,
            }))
        PATCH_HUNK_CACHE[key] = hunks
        return hunks

    parents = get_commit_parents(item["source_hash"])
    if parents:
        args = [
            "diff", "--unified=0", "--no-renames",
            parents[0], item["source_hash"], "--",
        ] + list(item["files"])
    else:
        args = [
            "show", "--format=", "--unified=0", "--no-renames",
            item["source_hash"], "--",
        ] + list(item["files"])
    r = run_git(args, check=False)

    hunks = []
    old_path = None
    new_path = None
    current_path = None
    for line in r.stdout.splitlines():
        if line.startswith("diff --git "):
            old_path = None
            new_path = None
            current_path = None
            continue
        if line.startswith("--- "):
            raw = line[4:]
            old_path = None if raw == "/dev/null" else raw[2:] if raw.startswith("a/") else raw
            current_path = new_path or old_path
            continue
        if line.startswith("+++ "):
            raw = line[4:]
            new_path = None if raw == "/dev/null" else raw[2:] if raw.startswith("b/") else raw
            current_path = new_path or old_path
            continue

        match = HUNK_RE.match(line)
        if not match or current_path is None:
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        hunks.append((
            current_path,
            range_with_min_width(old_start, old_count),
            range_with_min_width(new_start, new_count),
        ))

    PATCH_HUNK_CACHE[key] = hunks
    return hunks


def ranges_overlap(left, right):
    return max(left[0], right[0]) <= min(left[1], right[1])


def patch_hunks_overlap(left, right):
    return (
        left[0] == right[0] and
        (ranges_overlap(left[1], right[1]) or ranges_overlap(left[2], right[2]))
    )


def items_patch_overlap(left, right):
    return any(
        patch_hunks_overlap(left_hunk, right_hunk)
        for left_hunk in item_patch_hunks(left)
        for right_hunk in item_patch_hunks(right)
    )


def promotion_clobber_reason(item, group, plan, ignored_ids=None):
    """Return a reason if moving item to this group can be clobbered later."""
    item_pos = item_source_pos(item)
    if item_pos < 0:
        return None
    ignored_ids = ignored_ids or set()

    protected = []
    for protected_group in range(group + 1, 11):
        protected.extend(plan["buckets"][protected_group])
    protected.extend(plan["buckets"][11])

    item_paths = set(item["files"])
    for other in protected:
        if other is item:
            continue
        if id(other) in ignored_ids:
            continue
        if item_source_pos(other) >= item_pos:
            continue
        if items_patch_overlap(item, other):
            return "unsafe hunk overlap with later group"
        if item_paths.intersection(other["files"]):
            return "full-file-state clobber risk with earlier-source later item"
    return None


def move_failed_promotion_to_g10(item, group, report, reason, emit_now=False):
    moved = dict(item)
    moved["kept_from_group"] = group
    moved["subject"] = add_failed_promotion_prefix(item["subject"], group)
    moved["target_group"] = 10
    moved["kind"] = f"failed-g{group}-promotion-to-g10"
    if emit_now:
        emit_item(moved, report, moved["kind"])
    report["kept"].append({
        "hash": item["source_hash"],
        "subject": moved["subject"],
        "candidate_group": group,
        "reason": reason,
    })
    return moved


def abort_cherry_pick_if_needed():
    run_git(["cherry-pick", "--abort"], check=False)


def probe_clean_cherry_pick(source_hash):
    before = git_rev_parse("HEAD")
    r = run_git(["cherry-pick", "--no-commit", source_hash], check=False)
    combined = r.stdout + r.stderr

    if r.returncode == 0:
        run_git(["reset", "--hard", before])
        return "clean", combined

    abort_cherry_pick_if_needed()
    run_git(["reset", "--hard", before])

    if is_empty_cherry_pick_output(combined):
        return "empty", combined
    if is_conflict_output(combined):
        return "conflict", combined

    raise RuntimeError(
        f"unexpected cherry-pick probe failure for {source_hash}\n"
        f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    )


def promote_from_g11(plan, group, report):
    remaining = []
    promoted = 0
    kept_conflict = 0
    skipped_empty = 0
    resolved_same_pass_ids = set()

    for item in plan["buckets"][11]:
        if item.get("kept_from_group") is not None:
            remaining.append(item)
            continue
        if not matches_target_group(item, group):
            remaining.append(item)
            continue

        if group < 10:
            clobber_reason = promotion_clobber_reason(
                item, group, plan, resolved_same_pass_ids)
        else:
            clobber_reason = None
        if clobber_reason:
            moved = move_failed_promotion_to_g10(
                item, group, report,
                f"overlap/clobber guard: {clobber_reason}; moved to g10")
            plan["buckets"][10].append(moved)
            kept_conflict += 1
            log_move_to_g10(
                item["source_hash"], group,
                f"overlap/clobber guard: {clobber_reason}")
            continue

        status, output = probe_clean_cherry_pick(item["source_hash"])
        if status == "clean":
            moved = dict(item)
            moved["target_group"] = group
            moved["kind"] = f"promoted-g11-to-g{group}"
            emit_item(moved, report, moved["kind"])
            report["promoted"].append({
                "hash": item["source_hash"],
                "subject": item["subject"],
                "to_group": group,
                "reason": "clean cherry-pick probe",
            })
            resolved_same_pass_ids.add(id(item))
            promoted += 1
        elif status == "empty":
            report["skipped"].append({
                "hash": item["source_hash"],
                "subject": item["subject"],
                "group": group,
                "label": f"g11-to-g{group}",
                "reason": "cherry-pick probe was empty at target group",
            })
            skipped_empty += 1
            log(
                f"{STYLE.yellow('empty')} g11->{fmt_group(group)} "
                f"{fmt_sha(item['source_hash'])} {item['subject']}"
            )
            resolved_same_pass_ids.add(id(item))
        else:
            moved = move_failed_promotion_to_g10(
                item, group, report,
                "cherry-pick probe conflicted; moved to g10",
                emit_now=(group == 10))
            if group != 10:
                plan["buckets"][10].append(moved)
            kept_conflict += 1
            log_move_to_g10(item["source_hash"], group, conflict_summary(output))

    plan["buckets"][11] = remaining
    log_summary(group, promoted, kept_conflict, skipped_empty)


def drain_g10_candidates(plan, report):
    remaining = []
    moved_count = 0
    skipped_empty = 0

    for item in plan["buckets"][11]:
        if not matches_target_group(item, 10):
            remaining.append(item)
            continue

        moved = dict(item)
        moved["target_group"] = 10
        moved["kind"] = "g10-code-placement"
        plan["buckets"][10].append(moved)
        report["promoted"].append({
            "hash": item["source_hash"],
            "subject": item["subject"],
            "to_group": 10,
            "reason": "g10 source-order code placement",
        })
        moved_count += 1

    plan["buckets"][11] = remaining
    plan["buckets"][10].sort(key=lambda item: item["source_pos"])
    log_summary(10, moved_count, 0, skipped_empty)


def emit_existing_group(plan, group, report):
    items = sorted(plan["buckets"][group], key=lambda item: item["source_pos"])
    if not items:
        log(f"{fmt_group(group)}: {STYLE.dim('no existing items')}")
    for item in items:
        item["target_group"] = group
        emit_item(item, report, item["kind"])


def remaining_diff_paths(input_hash, output_ref):
    r = run_git(["diff", "--name-only", "--no-renames", output_ref, input_hash],
                check=False)
    return [line for line in r.stdout.splitlines() if line]


def reconcile_to_input(input_hash, output_ref, report):
    paths = remaining_diff_paths(input_hash, output_ref)
    if not paths:
        log(f"{STYLE.green('final tree matches input')}")
        return False

    log(
        f"{STYLE.yellow('final reconciliation')}: "
        f"{STYLE.yellow(str(len(paths)))} differing path(s)"
    )
    apply_file_states(input_hash, paths)
    info = get_commit_info(input_hash)
    body = (
        f"Applied file-state reconciliation for {len(paths)} path(s) so the "
        f"output tree matches {input_hash}."
    )
    ok = commit_with_info(info, "SNAP: reconcile remaining diff to INPUT_BRANCH", body)
    report["reconciliation"] = {
        "paths": len(paths),
        "emitted": bool(ok),
    }
    remaining = remaining_diff_paths(input_hash, output_ref)
    if remaining:
        raise RuntimeError(
            f"reconciliation did not converge; {len(remaining)} path(s) still differ"
        )
    return ok


def create_output_branch(output_branch, base_hash, force):
    if branch_exists(output_branch):
        if not force:
            raise RuntimeError(
                f"output branch {output_branch!r} already exists; pass --force-output"
            )
        if current_branch() == output_branch:
            run_git(["checkout", "--detach", "HEAD"])
        run_git(["branch", "-D", output_branch])
    run_git(["checkout", "-b", output_branch, base_hash])


def build_output(args, input_hash, base_hash, plan, report):
    create_output_branch(args.output_branch, base_hash, args.force_output)

    log_section("pass 1: emit g1-g4")
    emit_marker(1)
    emit_base_removed_files(plan, report)
    for cat in sorted(plan["g1_files"], key=lambda key: plan["g1_first_pos"][key]):
        emit_squash(input_hash, cat, plan["g1_files"][cat],
                    plan["g1_first_info"][cat], report)

    for group in (2, 3, 4):
        emit_marker(group)
        emit_existing_group(plan, group, report)

    log_section("pass 2: emit g5-g10 and promote from g11")
    for group in (5, 6, 7, 8, 9):
        emit_marker(group)
        emit_existing_group(plan, group, report)
        promote_from_g11(plan, group, report)

    emit_marker(10)
    drain_g10_candidates(plan, report)
    emit_existing_group(plan, 10, report)

    emit_marker(11)
    for item in sorted(plan["buckets"][11], key=lambda it: it["source_pos"]):
        item["target_group"] = 11
        emit_item(item, report, "remaining-g11")

    diff_paths = remaining_diff_paths(input_hash, args.output_branch)
    if diff_paths and args.no_reconcile:
        raise RuntimeError(
            f"output tree differs from input by {len(diff_paths)} path(s); "
            "rerun without --no-reconcile to create a final reconciliation commit"
        )
    if diff_paths:
        reconcile_to_input(input_hash, args.output_branch, report)


def log_entries(title, entries, formatter):
    if not entries:
        return
    log(STYLE.bold(title))
    for item in entries:
        log(f"  {formatter(item)}")


def print_final_report(args, base_hash, input_hash, parsed_count,
                       had_markers, plan, report):
    log_section("final report")
    log(f"{STYLE.bold('base')}: {fmt_sha(base_hash)}")
    log(f"{STYLE.bold('input')}: {fmt_sha(input_hash)}")
    log(f"{STYLE.bold('output branch')}: {STYLE.cyan(args.output_branch)}")
    log(f"{STYLE.bold('source commits parsed')}: {parsed_count}")
    marker_status = STYLE.green("yes") if had_markers else STYLE.yellow("no")
    log(f"{STYLE.bold('recognized markers in input')}: {marker_status}")
    log(f"{STYLE.bold('emitted commits')}: {STYLE.green(str(len(report['emitted'])))}")
    log(f"{STYLE.bold('promoted from g11')}: {STYLE.green(str(len(report['promoted'])))}")
    log(
        f"{STYLE.bold('failed promotions moved to g10')}: "
        f"{STYLE.red(str(len(report['kept'])))}"
    )
    log(f"{STYLE.bold('skipped output items')}: {STYLE.yellow(str(len(report['skipped'])))}")
    log(f"{STYLE.bold('g1 squashes')}: {STYLE.magenta(str(len(report['squashed'])))}")
    log(
        f"{STYLE.bold('base removed files')}: "
        f"{STYLE.red(str(len(plan['base_removed_files'])))} "
        f"({plan['base_removed_refs_skipped']} source reference(s) skipped)"
    )
    log(
        f"{STYLE.bold('transient removed files')}: "
        f"{STYLE.red(str(len(plan['transient_removed_files'])))} "
        f"({plan['transient_removed_refs_skipped']} source reference(s) skipped)"
    )
    log(
        f"{STYLE.bold('.result files squashed into previous commits')}: "
        f"{STYLE.magenta(str(plan['result_only_files_squashed']))}"
    )
    log(
        f"{STYLE.bold('.result-only commits elided')}: "
        f"{STYLE.yellow(str(plan['result_only_commits_elided']))}"
    )
    log(
        f"{STYLE.bold('[result-only] commits kept separate')}: "
        f"{STYLE.yellow(str(plan['result_only_base_commits_kept']))}"
    )

    rec = report.get("reconciliation")
    if rec:
        log(
            f"{STYLE.bold('reconciliation')}: "
            f"{STYLE.yellow(str(rec['paths']))} path(s), "
            f"commit emitted={str(rec['emitted']).lower()}"
        )

    log_entries(
        "base removed files",
        report["base_removed"],
        lambda item: (
            f"{fmt_sha(item['first_source'])} {item['subject']} - "
            f"{item['paths']} path(s)"
        ),
    )
    log_entries(
        "promoted from g11",
        report["promoted"],
        lambda item: (
            f"{fmt_sha(item['hash'])} -> {fmt_group(item['to_group'])}: "
            f"{item['subject']}"
        ),
    )
    log_entries(
        "failed promotions moved to g10",
        report["kept"],
        lambda item: (
            f"{fmt_sha(item['hash'])} candidate {fmt_group(item['candidate_group'])}: "
            f"{item['subject']} ({item['reason']})"
        ),
    )
    log_entries(
        "skipped output items",
        report["skipped"],
        lambda item: (
            f"{fmt_sha(item.get('hash') or item.get('first_source', ''))} "
            f"{item.get('subject') or item.get('category', '')} - "
            f"{item.get('reason', 'skipped')}"
        ),
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Reorder a Percona Server branch using the ps-reorder2 two-pass algorithm."
    )
    parser.add_argument("--input-branch", required=True,
                        help="input branch or commit to reorder")
    parser.add_argument("--output-branch", required=True,
                        help="new output branch to create")
    parser.add_argument("--base-branch", required=True,
                        help="base branch or commit where output starts")
    parser.add_argument("--force-output", action="store_true",
                        help="delete and recreate output branch if it exists")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="allow starting from a dirty worktree")
    parser.add_argument("--no-reconcile", action="store_true",
                        help="fail instead of creating a final reconciliation commit")
    parser.add_argument("--color", choices=("auto", "always", "never"),
                        default="auto",
                        help="colorize progress output (default: auto)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    configure_color(args.color)
    if not args.allow_dirty:
        ensure_clean_worktree()

    base_hash = git_rev_parse(args.base_branch)
    input_hash = git_rev_parse(args.input_branch)
    commits = get_commit_list(base_hash, input_hash)
    parsed, removed_markers, had_markers = parse_source_commits(commits)
    removed_paths = analyze_removed_paths(parsed, base_hash, input_hash)
    plan = plan_commits(parsed, removed_markers, removed_paths, base_hash)
    report = {
        "emitted": [],
        "promoted": [],
        "kept": [],
        "skipped": [],
        "squashed": [],
        "base_removed": [],
    }

    log(
        f"{STYLE.bold('input commits')}: {len(commits)} total, "
        f"{len(parsed)} non-marker"
    )
    marker_status = STYLE.green("yes") if had_markers else STYLE.yellow("no")
    log(f"{STYLE.bold('recognized markers')}: {marker_status}")

    build_output(args, input_hash, base_hash, plan, report)
    print_final_report(args, base_hash, input_hash, len(parsed), had_markers,
                       plan, report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"{STYLE.red('error')}: {exc}")
        raise SystemExit(1)

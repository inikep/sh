#!/usr/bin/env python3
"""Cherry-pick a bounded source range under ps-replay+make-buildable rules.

Every non-marker source-range commit before the boundary marker (the Group 9
marker, i.e. the end of Group 8) is forced into the no-build bucket. The
boundary marker is the Group 8 end checkpoint: build before preserving it as
an empty marker commit. All non-marker commits are applied with plain
`git cherry-pick <sha>`. After the checkpoint, source/plugin commits are
HP-8 checked against the resulting output commit and built immediately.
Post-Group-8 no-build batches are build-checked at batch boundaries.

With `--feature-gate`, range-gate evidence JSON files (pre-Group-9 and/or
post-Group-8) are consulted before each non-marker cherry-pick. The driver
stops before applying a commit whose decision hint requires manual review
(pre-Group-9: needs-review and partial-match-review; post-Group-8:
needs-review) so the engineer can decide apply, whole-commit
reference-feature-absent-skip, or partial reference-feature-absent-hunk-drop.
It never auto-skips. Pass `--gate-decided-apply IDX` for indexes already
inspected and decided to apply, or `--gate-decided-apply-file PATH` for a
reviewed batch of indexes.

For repeated, audited path-shape decisions, opt-in acceleration flags can
auto-apply selected gate stops and auto-drop reference-absent conflict paths.
These modes require explicit path globs and never use reference tree
replacement or merge-strategy shortcuts.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_CMAKE_FLAGS = [
    "-DCMAKE_BUILD_TYPE=Debug",
    "-DMYSQL_MAINTAINER_MODE=OFF",
    "-DDOWNLOAD_BOOST=1",
    "-DWITH_BOOST=/tmp/boost",
    "-DWITHOUT_TOKUDB=1",
    "-DWITH_ROCKSDB=OFF",
    "-DENABLE_DOWNLOADS=1",
    "-DWITH_READLINE=system",
    "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
    "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
]
GROUP8_MARKER_SUBJECT = "==================== MARKER: GROUP 9 — Upstream bug fixes ===================="
MARKER_RE = re.compile(r"^\s*=+\sMARKER:")
GATE_STOP_HINTS_PRE = frozenset({"needs-review", "partial-match-review"})
GATE_STOP_HINTS_POST = frozenset({"needs-review"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay a bounded commit batch, stop on conflicts, and build with the skill defaults."
    )
    parser.add_argument("--source-list", type=Path, required=True)
    parser.add_argument("--start", type=int, required=True, help="1-based first source index")
    parser.add_argument("--end", type=int, required=True, help="1-based last source index")
    parser.add_argument("--reference", help="Reference branch used for diagnostics only")
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--report-file", type=Path)
    parser.add_argument(
        "--group8-marker",
        dest="group8_marker",
        default=GROUP8_MARKER_SUBJECT,
        help="Exact Group 8 marker subject that starts post-boundary build verification.",
    )
    parser.add_argument(
        "--group7-marker",
        dest="group8_marker",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--group6-marker",
        dest="group8_marker",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--allow-missing-group8-marker",
        dest="allow_missing_group8_marker",
        action="store_true",
        help="Diagnostic escape hatch: do not fail if the Group 8 marker is absent from the source list.",
    )
    parser.add_argument(
        "--allow-missing-group7-marker",
        dest="allow_missing_group8_marker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--allow-missing-group6-marker",
        dest="allow_missing_group8_marker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--feature-gate",
        dest="feature_gate",
        type=Path,
        action="append",
        default=[],
        help=(
            "Range-gate evidence JSON from ps_replay_range_feature_gate.py "
            "(pre-Group-9 and/or post-Group-8 file). May be passed multiple times; "
            "records are merged by source index. The driver stops before "
            "cherry-picking any commit whose decision hint requires manual review."
        ),
    )
    parser.add_argument(
        "--gate-decided-apply",
        dest="gate_decided_apply",
        type=int,
        action="append",
        default=[],
        help=(
            "1-based source index already inspected against the range gate and "
            "decided to apply; the driver proceeds through it without stopping. "
            "May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--gate-decided-apply-file",
        dest="gate_decided_apply_file",
        type=Path,
        action="append",
        default=[],
        help=(
            "File containing 1-based source indexes already inspected and "
            "decided to apply. Blank lines and # comments are ignored; each "
            "non-comment line may be an integer or start with an integer "
            "followed by whitespace and review notes. May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--gate-auto-apply-path-glob",
        dest="gate_auto_apply_path_glob",
        action="append",
        default=[],
        help=(
            "Opt-in acceleration for feature-gate stops: if every gate-unmatched "
            "path matches one of these globs and every unmatched identifier is "
            "allowed, proceed as gate-decided-apply. May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--gate-auto-apply-unmatched-identifier",
        dest="gate_auto_apply_unmatched_identifier",
        action="append",
        default=[],
        help=(
            "Identifier allowed for --gate-auto-apply-path-glob decisions. "
            "Every unmatched_diff_identifier must be listed here unless there "
            "are no unmatched identifiers. May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--auto-drop-reference-absent-conflict-glob",
        dest="auto_drop_reference_absent_conflict_glob",
        action="append",
        default=[],
        help=(
            "Opt-in conflict acceleration: when every conflicted path matches "
            "one of these globs and is absent from --reference, git rm those "
            "paths and continue/skip the cherry-pick. May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--ledger-file",
        type=Path,
        help="Append TSV ledger rows for automated skips/hunk drops.",
    )
    parser.add_argument(
        "--build-policy",
        choices=("always", "bucketed"),
        default="bucketed",
        help=(
            "Pre-Group-8 commits are always forced into the no-build bucket. "
            "After Group 8, source/plugin commits build immediately; no-build "
            "batches build at fences."
        ),
    )
    parser.add_argument(
        "--nobuild-fence-size",
        type=int,
        default=20,
        help="Build after this many consecutive no-build commits.",
    )
    parser.add_argument(
        "--classify-only",
        action="store_true",
        help=(
            "Print TSV commit bucket classification for the selected range and exit "
            "without modifying the worktree. The forced_pre_group8 column is yes "
            "when the no-build bucket came from the Group 8 boundary override."
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, (os.cpu_count() or 2) * 3 // 4),
    )
    parser.add_argument(
        "--clean-build",
        action="store_true",
        help="Delete and reconfigure the build directory before each build",
    )
    parser.add_argument(
        "--cmake-flag",
        action="append",
        default=[],
        help="Additional CMake flag passed through to ps_replay_build.py. May be passed multiple times.",
    )
    return parser.parse_args()


SOURCE_PREFIXES = (
    "client/",
    "cmake/",
    "extra/",
    "include/",
    "libbinlogevents/",
    "libmysql/",
    "mysys/",
    "mysys_ssl/",
    "plugin/",
    "scripts/",
    "sql/",
    "storage/",
    "strings/",
    "unittest/",
    "vio/",
)
SOURCE_EXACT = {"CMakeLists.txt", "VERSION", "configure.cmake", "config.h.cmake"}
SOURCE_EXTENSIONS = (
    ".h",
    ".c",
    ".cc",
    ".cxx",
    ".cpp",
    ".hh",
    ".hpp",
    ".hxx",
    ".cmake",
)
NOBUILD_PREFIXES = (
    "build-ps/",
    "docs/",
    "man/",
    "mysql-test/",
    "debian/",
    "rpm/",
    "packaging/",
)
NOBUILD_EXACT = {
    ".bzrignore",
    ".gitignore",
    "README",
    "README.md",
    "INSTALL",
    "INSTALL-SOURCE",
    "INSTALL-WIN-SOURCE",
    "LICENSE",
}


def git(worktree: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def out(worktree: Path, args: list[str]) -> str:
    return git(worktree, args).stdout.strip()


def append(report: Path | None, line: str) -> None:
    if report is None:
        return
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("a") as fh:
        fh.write(line + "\n")


def append_ledger(ledger: Path | None, fields: list[str]) -> None:
    if ledger is None:
        return
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a") as fh:
        fh.write("\t".join(fields) + "\n")


def commit_subject(worktree: Path, sha: str) -> str:
    return out(worktree, ["show", "-s", "--format=%s", sha])


def load_subjects(
    worktree: Path,
    commits: list[str],
    start: int,
    end: int,
    marker: str,
    subject_lookup=commit_subject,
) -> tuple[dict[int, str], int | None]:
    """Load selected subjects and scan only as far as needed for marker lookup."""
    subjects: dict[int, str] = {}
    marker_index: int | None = None

    for idx, sha in enumerate(commits, start=1):
        in_selected_range = start <= idx <= end
        scanning_for_marker = marker_index is None

        if in_selected_range or scanning_for_marker:
            subject = subject_lookup(worktree, sha)
            if in_selected_range:
                subjects[idx] = subject
            if scanning_for_marker and subject == marker:
                marker_index = idx

        if marker_index is not None and idx >= end:
            break

    return subjects, marker_index


def changed_paths(worktree: Path, sha: str) -> list[str]:
    output = out(worktree, ["diff-tree", "--no-commit-id", "--name-only", "-r", sha])
    return [line for line in output.splitlines() if line]


def is_marker_subject(subject: str) -> bool:
    return bool(MARKER_RE.match(subject))


def load_gate_records(paths: list[Path]) -> dict[int, dict]:
    records: dict[int, dict] = {}
    for path in paths:
        evidence = json.loads(path.read_text())
        for record in evidence.get("records", []):
            records[int(record["index"])] = record
    return records


def load_decided_apply_indexes(paths: list[Path]) -> set[int]:
    indexes: set[int] = set()
    for path in paths:
        for lineno, raw_line in enumerate(path.read_text().splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            token = line.split(None, 1)[0]
            try:
                idx = int(token)
            except ValueError as exc:
                raise SystemExit(f"{path}:{lineno}: expected source index, got {token!r}") from exc
            if idx <= 0:
                raise SystemExit(f"{path}:{lineno}: source index must be positive, got {idx}")
            indexes.add(idx)
    return indexes


def gate_stop_hint(
    record: dict | None,
    idx: int,
    group8_index: int | None,
    decided_apply: set[int],
) -> str | None:
    """Return the decision hint that requires stopping before cherry-pick, if any.

    Pre-checkpoint commits stop on partial matches too because unmatched diff
    identifiers there are reference-feature-absent-hunk-drop candidates.
    """
    if record is None or idx in decided_apply:
        return None
    pre_checkpoint = group8_index is None or idx < group8_index
    stop_hints = GATE_STOP_HINTS_PRE if pre_checkpoint else GATE_STOP_HINTS_POST
    hint = record.get("decision_hint")
    return hint if hint in stop_hints else None


def matches_any_glob(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, glob) for glob in globs)


def gate_unmatched_paths(record: dict) -> list[str]:
    changed = set(record.get("changed_paths") or [])
    added = set(record.get("added_paths") or [])
    matched_changed = set(record.get("matched_changed_paths") or [])
    matched_added = set(record.get("matched_added_paths") or [])
    return sorted((changed | added) - matched_changed - matched_added)


def gate_auto_apply_reason(
    record: dict,
    path_globs: list[str],
    allowed_unmatched_identifiers: set[str],
) -> str | None:
    if not path_globs:
        return None

    unmatched_paths = gate_unmatched_paths(record)
    if not unmatched_paths:
        return None
    if any(not matches_any_glob(path, path_globs) for path in unmatched_paths):
        return None

    unmatched_identifiers = set(record.get("unmatched_diff_identifiers") or [])
    if unmatched_identifiers - allowed_unmatched_identifiers:
        return None

    return (
        "all gate-unmatched paths match configured globs "
        f"({', '.join(path_globs)}) and unmatched identifiers are allowed"
    )


def has_source_extension(path: str) -> bool:
    """SKILL HP-8 extension-based Source override: any C/C++/CMake file forces Source bucket."""
    lowered = path.lower()
    return lowered.endswith(SOURCE_EXTENSIONS)


def classify_paths(paths: list[str], subject: str) -> str:
    if is_marker_subject(subject):
        return "empty-marker"

    if not paths:
        return "empty"

    # HP-8 extension-based Source override: a single C/C++/CMake-extension path
    # forces Source bucket regardless of directory prefix (including plugin/,
    # mysql-test/, scripts/, packaging/).
    if any(has_source_extension(path) for path in paths):
        return "source"

    if all(path.startswith("plugin/") for path in paths):
        return "plugin"

    if any(path in SOURCE_EXACT or path.startswith(SOURCE_PREFIXES) for path in paths):
        return "source"

    if all(is_no_build_path(path) for path in paths):
        return "no-build"

    return "source"


def is_no_build_path(path: str) -> bool:
    return (
        path in NOBUILD_EXACT
        or path.startswith(NOBUILD_PREFIXES)
        or "/mysql-test/" in path
        or path.endswith((".md", ".rst", ".1", ".8", ".result", ".spec"))
        or ".spec." in path
    )


def conflicted_paths(worktree: Path) -> list[Path]:
    names = set(out(worktree, ["diff", "--name-only", "--diff-filter=U"]).splitlines())
    for line in out(worktree, ["status", "--porcelain"]).splitlines():
        if line[:2] in {"UU", "UD", "DU", "AA", "DD", "AU", "UA"}:
            names.add(line[3:])
    return [Path(name) for name in sorted(name for name in names if name)]


def path_exists_on_reference(worktree: Path, reference: str, path: Path) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{reference}:{path.as_posix()}"],
        cwd=worktree,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def auto_droppable_conflicts(
    worktree: Path,
    reference: str,
    conflicts: list[Path],
    globs: list[str],
) -> tuple[bool, list[Path], list[str]]:
    if not globs or not conflicts:
        return False, [], []

    reasons: list[str] = []
    for path in conflicts:
        path_text = path.as_posix()
        if not matches_any_glob(path_text, globs):
            reasons.append(f"{path_text} does not match configured globs")
            continue
        if path_exists_on_reference(worktree, reference, path):
            reasons.append(f"{path_text} exists on reference")

    if reasons:
        return False, [], reasons
    return True, conflicts, []


def staged_paths(worktree: Path) -> list[str]:
    return [line for line in out(worktree, ["diff", "--cached", "--name-only"]).splitlines() if line]


def describe_conflicts(worktree: Path, reference: str) -> list[Path]:
    paths = conflicted_paths(worktree)
    for path in paths:
        ref_status = "present on reference" if path_exists_on_reference(worktree, reference, path) else "missing from reference"
        print(f"  conflict: {path} ({ref_status})", flush=True)
    return paths


def run_build(args: argparse.Namespace, idx: int, sha: str) -> tuple[int, Path]:
    if args.build_dir is None or args.log_dir is None:
        raise RuntimeError("build-dir and log-dir are required for replay")
    args.log_dir.mkdir(parents=True, exist_ok=True)
    log = args.log_dir / f"build-{idx}-{sha[:12]}-ccache.log"
    build_script = Path(__file__).with_name("ps_replay_build.py")
    if build_script.exists():
        cmd = [
            sys.executable,
            str(build_script),
            "--worktree",
            str(args.worktree.resolve()),
            "--build-dir",
            str(args.build_dir.resolve()),
            "--log",
            str(log),
            "--jobs",
            str(args.jobs),
        ]
        if args.clean_build or not (args.build_dir.resolve() / "CMakeCache.txt").exists():
            pass
        else:
            cmd.append("--incremental")
        for flag in args.cmake_flag:
            cmd.append(f"--cmake-flag={flag}")
        return subprocess.run(cmd, text=True).returncode, log

    build_dir = args.build_dir.resolve()
    if args.clean_build:
        if not str(build_dir).startswith("/tmp/"):
            raise RuntimeError(f"refusing to clean build directory outside /tmp: {build_dir}")
        if build_dir.exists():
            shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    cmake_cmd = ["cmake", str(args.worktree.resolve()), *DEFAULT_CMAKE_FLAGS, *args.cmake_flag]
    make_cmd = ["make", f"-j{args.jobs}"]
    env = {**os.environ, "CC": "gcc-9", "CXX": "g++-9"}
    with log.open("w") as fh:
        if args.clean_build or not (build_dir / "CMakeCache.txt").exists():
            fh.write("$ " + " ".join(cmake_cmd) + "\n\n")
            cmake = subprocess.run(cmake_cmd, cwd=build_dir, text=True, stdout=fh, stderr=subprocess.STDOUT, env=env)
            if cmake.returncode != 0:
                return cmake.returncode, log
        fh.write("\n$ " + " ".join(make_cmd) + "\n\n")
        make = subprocess.run(make_cmd, cwd=build_dir, text=True, stdout=fh, stderr=subprocess.STDOUT, env=env)
        return make.returncode, log


def should_build(
    args: argparse.Namespace,
    bucket: str,
    consecutive_nobuild: int,
    no_build_boundary: bool,
    forced_nobuild: bool = False,
) -> tuple[bool, str]:
    if bucket == "empty-marker":
        return False, "empty-marker-no-tree-change"
    if bucket == "empty":
        return False, "empty-no-tree-change"
    if forced_nobuild:
        return False, "pre-group8-no-build-exempt"
    if args.build_policy == "always":
        return True, "policy-always"
    if bucket in {"source", "plugin"}:
        return True, f"{bucket}-commit"
    if bucket == "no-build" and (
        consecutive_nobuild >= args.nobuild_fence_size or no_build_boundary
    ):
        return True, f"no-build-fence-{consecutive_nobuild}"
    return False, f"defer-{bucket}"


def source_or_plugin_path(path: str) -> bool:
    return (
        has_source_extension(path)
        or path in SOURCE_EXACT
        or path.startswith(SOURCE_PREFIXES)
        or path.startswith("plugin/")
    )


def hp8_check_staged_paths(
    worktree: Path,
    source_paths: list[str],
    idx: int,
    sha: str,
    report_file: Path | None,
) -> bool:
    expected = sorted(path for path in source_paths if source_or_plugin_path(path))
    staged = set(out(worktree, ["diff", "--cached", "--name-only"]).splitlines())
    missing = [path for path in expected if path not in staged]
    if missing:
        message = (
            f"- Commit {idx}: `{sha}` HP-8 staged-paths check failed; "
            f"missing source/plugin paths from staged tree: `{', '.join(missing)}`."
        )
        append(report_file, message)
        print(message, flush=True)
        return False
    append(report_file, f"- Commit {idx}: HP-8 staged-paths check PASS.")
    return True


def hp8_expected_paths(source_paths: list[str]) -> list[str]:
    return sorted(path for path in source_paths if source_or_plugin_path(path))


def hp8_missing_paths(source_paths: list[str], output_paths: list[str]) -> list[str]:
    output = set(output_paths)
    return [path for path in hp8_expected_paths(source_paths) if path not in output]


def hp8_check_output_paths(
    worktree: Path,
    source_paths: list[str],
    idx: int,
    sha: str,
    output_sha: str,
    report_file: Path | None,
) -> bool:
    output_paths = out(worktree, ["diff-tree", "--no-commit-id", "--name-only", "-r", output_sha]).splitlines()
    missing = hp8_missing_paths(source_paths, output_paths)
    if missing:
        message = (
            f"- Commit {idx}: `{sha}` HP-8 output-paths check failed; "
            f"missing source/plugin paths from output commit `{output_sha[:12]}`: "
            f"`{', '.join(missing)}`."
        )
        append(report_file, message)
        print(message, flush=True)
        return False
    append(report_file, f"- Commit {idx}: HP-8 output-paths check PASS.")
    return True


def preserve_empty_marker(worktree: Path, subject: str) -> subprocess.CompletedProcess[str]:
    return git(worktree, ["commit", "--allow-empty", "-m", subject], check=False)


def main() -> int:
    args = parse_args()
    args.worktree = args.worktree.resolve()
    commits = [line.strip() for line in args.source_list.read_text().splitlines() if line.strip()]
    if args.start < 1 or args.end > len(commits) or args.start > args.end:
        raise SystemExit(f"invalid range {args.start}-{args.end} for {len(commits)} commits")

    subjects, group8_index = load_subjects(
        args.worktree,
        commits,
        args.start,
        args.end,
        args.group8_marker,
    )
    if group8_index is None and not args.allow_missing_group8_marker:
        raise SystemExit(
            f"required marker not found in source list: {args.group8_marker}\n"
            "Ask the engineer whether to continue without the boundary, use a different marker, "
            "or change the build policy."
        )

    classified: dict[int, tuple[str, list[str]]] = {}
    forced_pre_group8: set[int] = set()
    for idx in range(args.start, args.end + 1):
        sha = commits[idx - 1]
        subject = subjects[idx]
        paths = changed_paths(args.worktree, sha)
        if group8_index is not None and idx < group8_index and not is_marker_subject(subject):
            bucket = "no-build"
            forced_pre_group8.add(idx)
        else:
            bucket = classify_paths(paths, subject)
        classified[idx] = (bucket, paths)
        if args.classify_only:
            forced = "yes" if idx in forced_pre_group8 else "no"
            print(f"{idx}\t{sha}\t{bucket}\t{forced}\t{subject}\t{','.join(paths)}")

    if args.classify_only:
        return 0

    missing = [
        name
        for name, value in (
            ("--reference", args.reference),
            ("--build-dir", args.build_dir),
            ("--log-dir", args.log_dir),
        )
        if value is None
    ]
    if missing:
        raise SystemExit(f"replay requires: {', '.join(missing)}")

    status = out(args.worktree, ["status", "--short"])
    if status:
        raise SystemExit(f"refusing to start with dirty worktree:\n{status}")

    append(args.report_file, f"\n## Replay batch {args.start}-{args.end}")
    if group8_index is not None:
        append(args.report_file, f"- Boundary marker found at source index {group8_index}: `{args.group8_marker}`.")
        append(args.report_file, "- All non-marker commits before the Group 8 end checkpoint are forced into the no-build bucket.")
    else:
        append(args.report_file, "- Boundary marker not found; missing marker allowed for this diagnostic run.")

    gate_records = load_gate_records(args.feature_gate)
    decided_apply = set(args.gate_decided_apply) | load_decided_apply_indexes(args.gate_decided_apply_file)
    if args.feature_gate:
        names = ", ".join(f"`{path}`" for path in args.feature_gate)
        append(args.report_file, f"- Feature-gate evidence loaded from {names}; {len(gate_records)} records.")
        if decided_apply:
            decided = ", ".join(str(idx) for idx in sorted(decided_apply))
            append(args.report_file, f"- Gate-decided apply indexes: {decided}.")
        if args.gate_auto_apply_path_glob:
            append(
                args.report_file,
                "- Gate auto-apply path globs: "
                f"`{', '.join(args.gate_auto_apply_path_glob)}`; allowed unmatched identifiers: "
                f"`{', '.join(args.gate_auto_apply_unmatched_identifier) or 'none'}`.",
            )
    if args.auto_drop_reference_absent_conflict_glob:
        append(
            args.report_file,
            "- Auto-drop reference-absent conflict globs: "
            f"`{', '.join(args.auto_drop_reference_absent_conflict_glob)}`.",
        )

    consecutive_nobuild = 0
    auto_gate_allowed_ids = set(args.gate_auto_apply_unmatched_identifier)
    for idx in range(args.start, args.end + 1):
        sha = commits[idx - 1]
        subject = subjects[idx]
        bucket, source_paths = classified[idx]
        at_group8 = group8_index is not None and idx == group8_index and subject == args.group8_marker
        post_group8 = group8_index is not None and idx > group8_index and not is_marker_subject(subject)
        print(f"[{idx}/{len(commits)}] cherry-pick {sha[:12]} [{bucket}] {subject}", flush=True)

        if not is_marker_subject(subject):
            stop_hint = gate_stop_hint(gate_records.get(idx), idx, group8_index, decided_apply)
            if stop_hint is not None:
                record = gate_records[idx]
                unmatched = record.get("unmatched_diff_identifiers", [])
                auto_reason = gate_auto_apply_reason(
                    record,
                    args.gate_auto_apply_path_glob,
                    auto_gate_allowed_ids,
                )
                if auto_reason is not None:
                    append(
                        args.report_file,
                        f"- Commit {idx}: `{sha}` auto-applied feature-gate hint `{stop_hint}` (`{subject}`); "
                        f"unmatched diff identifiers: `{', '.join(unmatched) or 'none'}`; {auto_reason}.",
                    )
                    print(f"feature-gate auto-apply: {auto_reason}", flush=True)
                else:
                    append(
                        args.report_file,
                        f"- Commit {idx}: `{sha}` stopped on feature-gate hint `{stop_hint}` (`{subject}`); "
                        f"unmatched diff identifiers: `{', '.join(unmatched) or 'none'}`.",
                    )
                    print(f"feature-gate stop: decision hint {stop_hint}", flush=True)
                    print(f"  unmatched diff identifiers: {', '.join(unmatched) or 'none'}", flush=True)
                    print(
                        "Inspect the source patch against the reference, then either restart with "
                        f"--gate-decided-apply {idx} to apply it, or handle it manually "
                        "(reference-feature-absent-skip, or cherry-pick with "
                        "reference-feature-absent-hunk-drop) and restart the batch after this index.",
                        flush=True,
                    )
                    return 6

        if at_group8:
            print(f"[{idx}/{len(commits)}] Group 8 checkpoint build before marker", flush=True)
            rc, log = run_build(args, idx, sha)
            if rc != 0:
                append(args.report_file, f"- Group 8 checkpoint build result: FAIL (exit {rc}); log `{log}`.")
                print(f"[{idx}/{len(commits)}] checkpoint build failed, log {log}", flush=True)
                return 4
            append(args.report_file, f"- Group 8 checkpoint build result: PASS; log `{log}`.")
            print(f"[{idx}/{len(commits)}] checkpoint build passed", flush=True)

        if bucket == "empty-marker":
            commit = preserve_empty_marker(args.worktree, subject)
            if commit.returncode != 0:
                print(commit.stdout, end="")
                append(args.report_file, f"- Commit {idx}: `{sha}` failed to preserve empty marker (`{subject}`).")
                return 3
            apply_status = "preserved-empty-marker"
        else:
            pick = git(args.worktree, ["cherry-pick", sha], check=False)
            apply_status = "clean"
            if pick.returncode != 0:
                if "previous cherry-pick is now empty" in pick.stdout or "nothing to commit" in pick.stdout:
                    git(args.worktree, ["cherry-pick", "--skip"])
                    append(args.report_file, f"- Commit {idx}: `{sha}` skipped as empty (`{subject}`).")
                    print(f"[{idx}/{len(commits)}] skipped empty", flush=True)
                    continue

                conflicts = describe_conflicts(args.worktree, args.reference)
                if not conflicts:
                    print(pick.stdout, end="")
                    append(args.report_file, f"- Commit {idx}: `{sha}` stopped on unresolved cherry-pick result (`{subject}`).")
                    return 3

                auto_ok, drop_paths, auto_reasons = auto_droppable_conflicts(
                    args.worktree,
                    args.reference,
                    conflicts,
                    args.auto_drop_reference_absent_conflict_glob,
                )
                if auto_ok:
                    git(args.worktree, ["rm", "--", *(path.as_posix() for path in drop_paths)])
                    dropped = ", ".join(path.as_posix() for path in drop_paths)
                    remaining_conflicts = conflicted_paths(args.worktree)
                    if remaining_conflicts:
                        remaining = ", ".join(path.as_posix() for path in remaining_conflicts)
                        append(
                            args.report_file,
                            f"- Commit {idx}: `{sha}` auto-dropped reference-absent conflict paths `{dropped}`, "
                            f"but remaining conflicts require manual resolution: `{remaining}`.",
                        )
                        return 3

                    staged = staged_paths(args.worktree)
                    if not staged:
                        git(args.worktree, ["cherry-pick", "--skip"])
                        append(
                            args.report_file,
                            f"- Commit {idx}: `{sha}` skipped after auto-dropping only reference-absent conflict paths "
                            f"`{dropped}` (`{subject}`).",
                        )
                        append_ledger(
                            args.ledger_file,
                            [
                                "reference-feature-absent-skip",
                                str(idx),
                                sha[:12],
                                f"auto-dropped only reference-absent conflict paths matching configured globs: {dropped}; no output commit",
                            ],
                        )
                        print(f"[{idx}/{len(commits)}] skipped after auto-drop of reference-absent conflicts", flush=True)
                        continue

                    if post_group8 and bucket in {"source", "plugin"}:
                        if not hp8_check_staged_paths(args.worktree, source_paths, idx, sha, args.report_file):
                            return 5

                    continued = git(args.worktree, ["cherry-pick", "--continue", "--no-edit"], check=False)
                    if continued.returncode != 0:
                        if "previous cherry-pick is now empty" in continued.stdout or "nothing to commit" in continued.stdout:
                            git(args.worktree, ["cherry-pick", "--skip"])
                            append(
                                args.report_file,
                                f"- Commit {idx}: `{sha}` skipped as empty after auto-dropping reference-absent "
                                f"conflict paths `{dropped}` (`{subject}`).",
                            )
                            append_ledger(
                                args.ledger_file,
                                [
                                    "reference-feature-absent-skip",
                                    str(idx),
                                    sha[:12],
                                    f"auto-dropped reference-absent conflict paths matching configured globs: {dropped}; cherry-pick became empty",
                                ],
                            )
                            print(f"[{idx}/{len(commits)}] skipped empty after auto-drop", flush=True)
                            continue
                        print(continued.stdout, end="")
                        append(
                            args.report_file,
                            f"- Commit {idx}: `{sha}` auto-dropped reference-absent conflict paths `{dropped}`, "
                            "but cherry-pick --continue failed.",
                        )
                        return 3

                    append(
                        args.report_file,
                        f"- Commit {idx}: `{sha}` auto-dropped reference-absent conflict paths `{dropped}` "
                        f"using configured globs and continued with staged paths `{', '.join(staged)}`.",
                    )
                    append_ledger(
                        args.ledger_file,
                        [
                            "reference-feature-absent-hunk-drop",
                            str(idx),
                            sha[:12],
                            f"auto-dropped reference-absent conflict paths matching configured globs: {dropped}; kept staged paths: {', '.join(staged)}",
                        ],
                    )
                    apply_status = "auto-reference-absent-conflict-drop"
                else:
                    names = ", ".join(path.as_posix() for path in conflicts)
                    reason_suffix = f" Auto-drop not used: {'; '.join(auto_reasons)}." if auto_reasons else ""
                    append(
                        args.report_file,
                        f"- Commit {idx}: `{sha}` stopped on conflicts in `{names}` (`{subject}`); resolve hunks manually using `{args.reference}` as guidance.{reason_suffix}",
                    )
                    print(
                        "Stopped before modifying conflicted files. Resolve hunks manually, run the HP-8 staged-path check before git cherry-pick --continue, build this commit if required, then restart the batch after this index.",
                        flush=True,
                    )
                    return 3

        new_full_sha = out(args.worktree, ["rev-parse", "HEAD"])
        new_sha = new_full_sha[:12]

        if post_group8 and bucket in {"source", "plugin"}:
            if not hp8_check_output_paths(args.worktree, source_paths, idx, sha, new_full_sha, args.report_file):
                return 5
            apply_status = "plain-cherry-pick-hp8-checked"

        forced_note = "; forced pre-Group-8 no-build: yes" if idx in forced_pre_group8 else ""
        append(
            args.report_file,
            f"- Commit {idx}: `{sha}` -> `{new_sha}` `{subject}`; bucket: {bucket}{forced_note}; apply status: {apply_status}.",
        )

        if bucket == "no-build":
            consecutive_nobuild += 1
        else:
            consecutive_nobuild = 0

        build_now, build_reason = should_build(
            args,
            bucket,
            consecutive_nobuild,
            idx == args.end or classified[idx + 1][0] != "no-build",
            idx in forced_pre_group8,
        )
        if not build_now:
            append(args.report_file, f"- Commit {idx} build result: deferred by bucket policy ({build_reason}).")
            print(f"[{idx}/{len(commits)}] build deferred ({build_reason})", flush=True)
            continue

        print(f"[{idx}/{len(commits)}] build start {new_sha} ({build_reason})", flush=True)
        rc, log = run_build(args, idx, sha)
        if rc != 0:
            append(args.report_file, f"- Commit {idx} build result: FAIL (exit {rc}); log `{log}`.")
            print(f"[{idx}/{len(commits)}] build failed, log {log}", flush=True)
            return 4
        append(args.report_file, f"- Commit {idx} build result: PASS; log `{log}`.")
        print(f"[{idx}/{len(commits)}] build passed", flush=True)
        if bucket == "no-build":
            consecutive_nobuild = 0

    print(f"batch {args.start}-{args.end} complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

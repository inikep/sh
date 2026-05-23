#!/usr/bin/env python3
"""Cherry-pick a bounded source range under ps-replay+make-buildable rules.

Every non-marker source-range commit before the Group 8 marker is forced into
the no-build bucket. The Group 8 marker is a checkpoint: build before
preserving it as an empty marker commit. After Group 8, source/plugin commits
are staged with --no-commit, HP-8 checked, committed, and built immediately.
Post-Group-8 no-build batches are build-checked at batch boundaries.
"""

from __future__ import annotations

import argparse
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
GROUP8_MARKER_SUBJECT = "==================== MARKER: GROUP 8 — Upstream bug fixes ===================="
MARKER_RE = re.compile(r"^\s*=+\sMARKER:")


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
    "sql/",
    "storage/",
    "strings/",
    "unittest/",
    "vio/",
)
SOURCE_EXACT = {"CMakeLists.txt", "VERSION"}
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
        or (path.startswith("scripts/") and not path.lower().endswith(".cmake"))
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
        return subprocess.run(cmd, text=True).returncode, log

    build_dir = args.build_dir.resolve()
    if args.clean_build:
        if not str(build_dir).startswith("/tmp/"):
            raise RuntimeError(f"refusing to clean build directory outside /tmp: {build_dir}")
        if build_dir.exists():
            shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    cmake_cmd = ["cmake", str(args.worktree.resolve()), *DEFAULT_CMAKE_FLAGS]
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
        append(args.report_file, f"- Group 8 marker found at source index {group8_index}: `{args.group8_marker}`.")
        append(args.report_file, "- All non-marker commits before Group 8 are forced into the no-build bucket.")
    else:
        append(args.report_file, "- Group 8 marker not found; missing marker allowed for this diagnostic run.")

    consecutive_nobuild = 0
    for idx in range(args.start, args.end + 1):
        sha = commits[idx - 1]
        subject = subjects[idx]
        bucket, source_paths = classified[idx]
        at_group8 = group8_index is not None and idx == group8_index and subject == args.group8_marker
        post_group8 = group8_index is not None and idx > group8_index and not is_marker_subject(subject)
        print(f"[{idx}/{len(commits)}] cherry-pick {sha[:12]} [{bucket}] {subject}", flush=True)

        if at_group8:
            print(f"[{idx}/{len(commits)}] Group 8 checkpoint build before marker", flush=True)
            rc, log = run_build(args, idx, sha)
            if rc != 0:
                append(args.report_file, f"- Group 8 checkpoint build result: FAIL (exit {rc}); log `{log}`.")
                print(f"[{idx}/{len(commits)}] checkpoint build failed, log {log}", flush=True)
                return 4
            append(args.report_file, f"- Group 8 checkpoint build result: PASS; log `{log}`.")
            print(f"[{idx}/{len(commits)}] checkpoint build passed", flush=True)

        pick_args = ["cherry-pick"]
        if bucket == "empty-marker":
            pick_args.append("--allow-empty")
        elif post_group8 and bucket in {"source", "plugin"}:
            pick_args.append("--no-commit")
        pick_args.append(sha)
        pick = git(args.worktree, pick_args, check=False)
        apply_status = "clean"
        if pick.returncode != 0:
            if "previous cherry-pick is now empty" in pick.stdout or "nothing to commit" in pick.stdout:
                if bucket == "empty-marker":
                    commit = git(args.worktree, ["commit", "--allow-empty", "-C", sha], check=False)
                    if commit.returncode != 0:
                        print(commit.stdout, end="")
                        append(args.report_file, f"- Commit {idx}: `{sha}` failed to preserve empty marker (`{subject}`).")
                        return 3
                    apply_status = "preserved-empty-marker"
                else:
                    git(args.worktree, ["cherry-pick", "--skip"])
                    append(args.report_file, f"- Commit {idx}: `{sha}` skipped as empty (`{subject}`).")
                    print(f"[{idx}/{len(commits)}] skipped empty", flush=True)
                    continue

            else:
                conflicts = describe_conflicts(args.worktree, args.reference)
                if not conflicts:
                    print(pick.stdout, end="")
                    append(args.report_file, f"- Commit {idx}: `{sha}` stopped on unresolved cherry-pick result (`{subject}`).")
                    return 3

                names = ", ".join(path.as_posix() for path in conflicts)
                append(
                    args.report_file,
                    f"- Commit {idx}: `{sha}` stopped on conflicts in `{names}` (`{subject}`); resolve hunks manually using `{args.reference}` as guidance.",
                )
                print(
                    "Stopped before modifying conflicted files. Resolve hunks manually, continue/build this commit, then restart the batch after this index.",
                    flush=True,
                )
                return 3

        if bucket == "empty-marker" and apply_status == "clean":
            apply_status = "preserved-empty-marker"

        if post_group8 and bucket in {"source", "plugin"}:
            if git(args.worktree, ["diff", "--cached", "--quiet"], check=False).returncode == 0:
                append(args.report_file, f"- Commit {idx}: `{sha}` skipped as empty after staging (`{subject}`).")
                print(f"[{idx}/{len(commits)}] skipped empty after staging", flush=True)
                git(args.worktree, ["reset", "--hard", "HEAD"], check=False)
                continue
            if not hp8_check_staged_paths(args.worktree, source_paths, idx, sha, args.report_file):
                return 5
            commit = git(args.worktree, ["commit", "-C", sha], check=False)
            if commit.returncode != 0:
                print(commit.stdout, end="")
                append(args.report_file, f"- Commit {idx}: `{sha}` failed to commit after HP-8 check (`{subject}`).")
                return 6
            apply_status = "staged-hp8-checked"

        new_full_sha = out(args.worktree, ["rev-parse", "HEAD"])
        new_sha = new_full_sha[:12]
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

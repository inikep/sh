#!/usr/bin/env python3
"""Run a clean or incremental Percona replay build with the skill defaults.

After a successful ninja build the MTR smoke test (main.1st) runs from the build tree, so a commit
whose mysql-test-run.pl does not compile or whose mysqld cannot bootstrap does not get a PASS record.
Exit status: 0 build and smoke test passed, 5 build passed but the smoke test failed, anything else
is the cmake/ninja failure status."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


MAX_JOBS = 80
SMOKE_FAILED_RC = 5
SMOKE_TIMEOUT = 900

DEFAULT_CMAKE_FLAGS = [
    "-DCMAKE_BUILD_TYPE=Debug",
    "-DMYSQL_MAINTAINER_MODE=OFF",
    "-DDOWNLOAD_BOOST=1",
    "-DWITH_BOOST=/work/mysql-server/_deps",
    "-DWITHOUT_TOKUDB=1",
    "-DWITH_ROCKSDB=OFF",
    "-DWITH_PAM=ON",
    "-DENABLE_DOWNLOADS=1",
    "-DWITH_READLINE=system",
    "-DWITH_CURL=system",
    "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
    "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
    "-DCMAKE_CXX_FLAGS=-fpermissive",
    "-GNinja",
    "-DCMAKE_EXE_LINKER_FLAGS=-fuse-ld=gold",
    "-DCMAKE_SHARED_LINKER_FLAGS=-fuse-ld=gold",
    "-DCMAKE_MODULE_LINKER_FLAGS=-fuse-ld=gold",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure and build a replay worktree using gcc-9/g++-9 and ccache launchers."
    )
    parser.add_argument(
        "--worktree",
        type=Path,
        default=Path.cwd(),
        help="Source worktree to build (default: current directory)",
    )
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, min(MAX_JOBS, (os.cpu_count() or 2) * 3 // 4)),
        help=f"ninja jobs (default: 3/4 of CPUs, capped at {MAX_JOBS})",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Run ninja in the existing build directory without cleaning or reconfiguring",
    )
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="With --incremental, re-run cmake in the existing build directory before ninja",
    )
    parser.add_argument(
        "--cmake-flag",
        action="append",
        default=[],
        help="Additional CMake flag. May be passed multiple times.",
    )
    parser.add_argument(
        "--no-smoke-test",
        action="store_true",
        help="Skip the MTR smoke test (main.1st) after a successful build",
    )
    parser.add_argument(
        "--allow-non-tmp-build-dir",
        action="store_true",
        help="Allow deleting/reusing a build directory outside /tmp for clean builds",
    )
    args = parser.parse_args()
    args.jobs = max(1, min(args.jobs, MAX_JOBS))
    return args


def ensure_safe_build_dir(build_dir: Path, allow_non_tmp: bool) -> None:
    resolved = build_dir.resolve()
    if allow_non_tmp:
        return
    try:
        resolved.relative_to(Path("/tmp"))
    except ValueError as exc:
        raise SystemExit(
            f"refusing to clean build directory outside /tmp: {resolved}; "
            "pass --allow-non-tmp-build-dir to override"
        ) from exc


CMAKE_STAMP_NAME = ".ps_replay_cmake_stamp"


def write_cmake_stamp(worktree: Path, build_dir: Path) -> None:
    """Record the configured commit so callers can skip redundant reconfigures."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if head.returncode == 0:
        (build_dir / CMAKE_STAMP_NAME).write_text(head.stdout.strip() + "\n")


def run_logged(command: list[str], cwd: Path, log_fh) -> int:
    log_fh.write(f"$ cd {cwd}\n")
    log_fh.write("$ " + " ".join(command) + "\n\n")
    log_fh.flush()
    proc = subprocess.run(
        command,
        cwd=cwd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "CC": "gcc-9", "CXX": "g++-9"},
    )
    log_fh.write(f"\n# exit_code={proc.returncode}\n")
    log_fh.flush()
    return proc.returncode


def smoke_log_path(build_log: Path) -> Path:
    return build_log.with_name(build_log.stem + "-mtr-1st.log")


def run_smoke_test(build_dir: Path, build_log: Path) -> tuple[bool, Path, str]:
    """Run main.1st with the build tree's own mysql-test-run.pl.

    Passes only when MTR reports "Completed: All N tests were successful", which also covers the
    shutdown_report pseudo test; a harness that does not compile, a server that fails --initialize or
    a test-count mismatch all fail it."""
    log = smoke_log_path(build_log)
    mtr_dir = build_dir / "mysql-test"
    vardir = build_dir / "mtr-smoke-var"
    cmd = [
        "perl",
        "mysql-test-run.pl",
        f"--vardir={vardir}",
        "--force",
        "--nowarnings",
        "--parallel=1",
        "--max-test-fail=0",
        f"--mysqld=--lc-messages-dir={build_dir / 'share'}",
        "--suite=main",
        "1st",
    ]
    with log.open("w") as fh:
        fh.write(f"$ cd {mtr_dir}\n$ " + " ".join(cmd) + "\n\n")
        fh.flush()
        if not (mtr_dir / "mysql-test-run.pl").exists():
            fh.write("mysql-test-run.pl not found in the build tree\n")
            return False, log, "mysql-test-run.pl missing in build tree"
        try:
            proc = subprocess.run(cmd, cwd=mtr_dir, stdout=fh, stderr=subprocess.STDOUT, text=True,
                                  timeout=SMOKE_TIMEOUT)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            fh.write(f"\n# timed out after {SMOKE_TIMEOUT}s\n")
            return False, log, f"timed out after {SMOKE_TIMEOUT}s"
        fh.write(f"\n# exit_code={rc}\n")
    text = log.read_text(errors="replace")
    completed = [l for l in text.splitlines() if l.startswith("Completed:")]
    if rc == 0 and completed and "were successful" in completed[-1]:
        return True, log, completed[-1]
    lines = text.splitlines()
    reason = ""
    for key in ("Global symbol", "Assertion failure", "Assertion `", "[ fail ]", "*** ERROR", "compilation aborted"):
        reason = next((l.strip() for l in lines if key in l), "")
        if reason:
            break
    return False, log, (reason or f"exit {rc}")[:200]


def main() -> int:
    args = parse_args()
    worktree = args.worktree.resolve()
    build_dir = args.build_dir.resolve()
    args.log.parent.mkdir(parents=True, exist_ok=True)

    if not worktree.exists():
        raise SystemExit(f"worktree does not exist: {worktree}")

    if not args.incremental:
        ensure_safe_build_dir(build_dir, args.allow_non_tmp_build_dir)
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True)
    elif not build_dir.exists():
        raise SystemExit(f"incremental build directory does not exist: {build_dir}")

    with args.log.open("w") as log_fh:
        if not args.incremental or args.reconfigure:
            cmake_cmd = ["cmake", str(worktree), *DEFAULT_CMAKE_FLAGS, *args.cmake_flag]
            rc = run_logged(cmake_cmd, build_dir, log_fh)
            if rc != 0:
                print(f"CMake failed; log: {args.log}")
                return rc
            write_cmake_stamp(worktree, build_dir)

        rc = run_logged(["ninja", f"-j{args.jobs}"], build_dir, log_fh)

    if rc != 0:
        print(f"build failed with exit {rc}; log: {args.log}")
        return rc
    print(f"build passed; log: {args.log}")
    if args.no_smoke_test:
        return 0
    ok, smoke_log, detail = run_smoke_test(build_dir, args.log)
    if ok:
        print(f"smoke test main.1st passed ({detail}); log: {smoke_log}")
        return 0
    print(f"smoke test main.1st FAILED ({detail}); log: {smoke_log}")
    return SMOKE_FAILED_RC


if __name__ == "__main__":
    raise SystemExit(main())

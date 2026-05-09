#!/usr/bin/env python3
"""Run a clean or incremental Percona replay build with the skill defaults."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


DEFAULT_CMAKE_FLAGS = [
    "-DCMAKE_BUILD_TYPE=Debug",
    "-DMYSQL_MAINTAINER_MODE=OFF",
    "-DDOWNLOAD_BOOST=1",
    "-DWITH_BOOST=/tmp/boost",
    "-DWITHOUT_TOKUDB=1",
    "-DENABLE_DOWNLOADS=1",
    "-DWITH_READLINE=system",
    "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
    "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
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
        default=max(1, (os.cpu_count() or 2) * 3 // 4),
        help="make jobs (default: 3/4 of CPUs)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Run make in the existing build directory without cleaning or reconfiguring",
    )
    parser.add_argument(
        "--cmake-flag",
        action="append",
        default=[],
        help="Additional CMake flag. May be passed multiple times.",
    )
    parser.add_argument(
        "--allow-non-tmp-build-dir",
        action="store_true",
        help="Allow deleting/reusing a build directory outside /tmp for clean builds",
    )
    return parser.parse_args()


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
        if not args.incremental:
            cmake_cmd = ["cmake", str(worktree), *DEFAULT_CMAKE_FLAGS, *args.cmake_flag]
            rc = run_logged(cmake_cmd, build_dir, log_fh)
            if rc != 0:
                print(f"CMake failed; log: {args.log}")
                return rc

        rc = run_logged(["make", f"-j{args.jobs}"], build_dir, log_fh)

    if rc == 0:
        print(f"build passed; log: {args.log}")
    else:
        print(f"build failed with exit {rc}; log: {args.log}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

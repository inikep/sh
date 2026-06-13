#!/usr/bin/env python3
"""Compile changed C/C++ source objects in an existing CMake build tree."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find object targets for changed source files and run make on them. "
            "Use this as a cheap compile preflight before a full replay build."
        )
    )
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--cached", action="store_true", help="Use staged diff")
    parser.add_argument(
        "--base",
        default="HEAD^",
        help="Base for working-tree changed paths when --cached is not used",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=max(1, (os.cpu_count() or 2) * 3 // 4),
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Warn instead of failing when no object target is found for a source",
    )
    return parser.parse_args()


def git_text(worktree: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    return proc.stdout.decode("utf-8", errors="replace")


def changed_sources(worktree: Path, cached: bool, base: str) -> list[str]:
    args = ["diff", "--cached", "--name-only"] if cached else ["diff", "--name-only", base]
    paths = git_text(worktree, args).splitlines()
    return [p for p in paths if Path(p).suffix in SOURCE_EXTS and (worktree / p).exists()]


def object_suffixes(source: str) -> list[str]:
    path = Path(source)
    return [
        f"{source}.o",
        f"{path.parent}/{path.name}.o",
        f"{path.name}.o",
    ]


def find_object_targets(build_dir: Path, source: str) -> list[str]:
    matches: list[str] = []
    for obj in build_dir.rglob(f"{Path(source).name}.o"):
        rel = obj.relative_to(build_dir).as_posix()
        if any(rel.endswith(suffix) for suffix in object_suffixes(source)):
            matches.append(rel)
    return sorted(set(matches))


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

    sources = changed_sources(worktree, args.cached, args.base)
    targets: list[str] = []
    missing: list[str] = []
    for source in sources:
        found = find_object_targets(build_dir, source)
        if found:
            targets.extend(found)
        else:
            missing.append(source)

    targets = sorted(set(targets))
    with args.log.open("w") as log_fh:
        log_fh.write(f"# changed sources: {len(sources)}\n")
        for source in sources:
            log_fh.write(f"# source {source}\n")
        for source in missing:
            log_fh.write(f"# missing object target for {source}\n")
        if missing and not args.allow_missing:
            print(f"missing object targets for {len(missing)} changed source file(s); log: {args.log}")
            return 2
        if not targets:
            log_fh.write("# no object targets found\n")
            print(f"changed-object build skipped; log: {args.log}")
            return 0
        rc = run_logged(["make", f"-j{args.jobs}", *targets], build_dir, log_fh)

    if rc == 0:
        print(f"changed-object build passed ({len(targets)} targets); log: {args.log}")
    else:
        print(f"changed-object build failed with exit {rc}; log: {args.log}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

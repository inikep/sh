#!/usr/bin/env python3
"""Recover cherry-pick metadata after sequencer pseudo-files are lost.

This helper is intentionally narrow: it restores CHERRY_PICK_HEAD to a known
source commit and rewrites MERGE_MSG from that commit's message so
`git cherry-pick --continue` can finish an already-resolved index.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore CHERRY_PICK_HEAD and MERGE_MSG for an interrupted cherry-pick."
    )
    parser.add_argument("--commit", required=True, help="Source commit being cherry-picked")
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow recovery even when the index has no unresolved or staged changes.",
    )
    return parser.parse_args()


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


def has_active_resolution_state(worktree: Path) -> bool:
    unmerged = git(worktree, ["diff", "--name-only", "--diff-filter=U"], check=False).stdout.strip()
    staged = git(worktree, ["diff", "--cached", "--name-only"], check=False).stdout.strip()
    return bool(unmerged or staged)


def main() -> int:
    args = parse_args()
    worktree = args.worktree.resolve()

    git(worktree, ["cat-file", "-e", f"{args.commit}^{{commit}}"])
    if not args.force and not has_active_resolution_state(worktree):
        raise SystemExit(
            "refusing recovery: index has no unmerged or staged changes; "
            "use --force only if you verified this is an interrupted cherry-pick"
        )

    full_sha = out(worktree, ["rev-parse", args.commit])
    message = git(worktree, ["show", "-s", "--format=%B", full_sha]).stdout
    merge_msg_path = Path(out(worktree, ["rev-parse", "--git-path", "MERGE_MSG"]))
    if not merge_msg_path.is_absolute():
        merge_msg_path = worktree / merge_msg_path

    git(worktree, ["update-ref", "CHERRY_PICK_HEAD", full_sha])
    merge_msg_path.write_text(message)

    print(f"restored CHERRY_PICK_HEAD={full_sha}")
    print(f"rewrote {merge_msg_path}")
    print("next: resolve/stage remaining files, then run `git cherry-pick --continue`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

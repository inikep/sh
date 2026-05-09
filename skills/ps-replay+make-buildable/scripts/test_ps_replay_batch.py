#!/usr/bin/env python3
"""Focused tests for ps_replay_batch.py helper behavior."""

from pathlib import Path
from unittest.mock import patch
import unittest

import ps_replay_batch


class ArgumentParsingTests(unittest.TestCase):
    def test_group7_marker_is_default_boundary(self):
        argv = ["ps_replay_batch.py", "--source-list", "list.txt", "--start", "1", "--end", "1"]
        with patch("sys.argv", argv):
            args = ps_replay_batch.parse_args()

        self.assertEqual(args.group7_marker, "=== MARKER: GROUP 7 — Remaining ===")
        self.assertFalse(args.allow_missing_group7_marker)

    def test_legacy_group6_options_remain_aliases(self):
        argv = [
            "ps_replay_batch.py",
            "--source-list",
            "list.txt",
            "--start",
            "1",
            "--end",
            "1",
            "--group6-marker",
            "legacy marker",
            "--allow-missing-group6-marker",
        ]
        with patch("sys.argv", argv):
            args = ps_replay_batch.parse_args()

        self.assertEqual(args.group7_marker, "legacy marker")
        self.assertTrue(args.allow_missing_group7_marker)


class SubjectLoadingTests(unittest.TestCase):
    def test_loads_only_selected_range_when_marker_is_inside_range(self):
        commits = [f"sha-{idx}" for idx in range(1, 101)]
        subjects_by_sha = {
            sha: f"subject {idx}"
            for idx, sha in enumerate(commits, start=1)
        }
        subjects_by_sha["sha-45"] = "=== MARKER: GROUP 7 — Remaining ==="
        calls = []

        def lookup(_worktree: Path, sha: str) -> str:
            calls.append(sha)
            return subjects_by_sha[sha]

        subjects, marker_index = ps_replay_batch.load_subjects(
            Path("."), commits, 1, 70, "=== MARKER: GROUP 7 — Remaining ===", lookup
        )

        self.assertEqual(marker_index, 45)
        self.assertEqual(set(subjects), set(range(1, 71)))
        self.assertEqual(calls, commits[:70])

    def test_loads_marker_prefix_and_sparse_selected_range(self):
        commits = [f"sha-{idx}" for idx in range(1, 201)]
        subjects_by_sha = {
            sha: f"subject {idx}"
            for idx, sha in enumerate(commits, start=1)
        }
        subjects_by_sha["sha-45"] = "=== MARKER: GROUP 7 — Remaining ==="
        calls = []

        def lookup(_worktree: Path, sha: str) -> str:
            calls.append(sha)
            return subjects_by_sha[sha]

        subjects, marker_index = ps_replay_batch.load_subjects(
            Path("."), commits, 150, 155, "=== MARKER: GROUP 7 — Remaining ===", lookup
        )

        self.assertEqual(marker_index, 45)
        self.assertEqual(set(subjects), set(range(150, 156)))
        self.assertEqual(calls, commits[:45] + commits[149:155])

    def test_scans_past_selected_range_only_until_marker(self):
        commits = [f"sha-{idx}" for idx in range(1, 101)]
        subjects_by_sha = {
            sha: f"subject {idx}"
            for idx, sha in enumerate(commits, start=1)
        }
        subjects_by_sha["sha-45"] = "=== MARKER: GROUP 7 — Remaining ==="
        calls = []

        def lookup(_worktree: Path, sha: str) -> str:
            calls.append(sha)
            return subjects_by_sha[sha]

        subjects, marker_index = ps_replay_batch.load_subjects(
            Path("."), commits, 1, 40, "=== MARKER: GROUP 7 — Remaining ===", lookup
        )

        self.assertEqual(marker_index, 45)
        self.assertEqual(set(subjects), set(range(1, 41)))
        self.assertEqual(calls, commits[:45])


class BuildPolicyTests(unittest.TestCase):
    def test_forced_pre_group7_no_build_never_builds_at_fence(self):
        class Args:
            build_policy = "bucketed"
            nobuild_fence_size = 5

        build_now, reason = ps_replay_batch.should_build(
            Args(),
            bucket="no-build",
            consecutive_nobuild=5,
            no_build_boundary=True,
            forced_nobuild=True,
        )

        self.assertFalse(build_now)
        self.assertEqual(reason, "pre-group7-no-build-exempt")

    def test_bucketed_source_commit_builds_immediately(self):
        class Args:
            build_policy = "bucketed"
            nobuild_fence_size = 20

        build_now, reason = ps_replay_batch.should_build(
            Args(),
            bucket="source",
            consecutive_nobuild=0,
            no_build_boundary=False,
        )

        self.assertTrue(build_now)
        self.assertEqual(reason, "source-commit")

    def test_bucketed_plugin_commit_builds_immediately(self):
        class Args:
            build_policy = "bucketed"
            nobuild_fence_size = 20

        build_now, reason = ps_replay_batch.should_build(
            Args(),
            bucket="plugin",
            consecutive_nobuild=0,
            no_build_boundary=False,
        )

        self.assertTrue(build_now)
        self.assertEqual(reason, "plugin-commit")


if __name__ == "__main__":
    unittest.main()

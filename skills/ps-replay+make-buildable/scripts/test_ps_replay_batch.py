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


class ClassifyPathsTests(unittest.TestCase):
    """HP-8 extension-based Source override (SKILL.md §2 Bucketing)."""

    def test_marker_subject_is_empty_marker(self):
        self.assertEqual(
            ps_replay_batch.classify_paths(["sql/sql_acl.cc"], "=== MARKER: GROUP 7 — foo"),
            "empty-marker",
        )

    def test_empty_paths_is_empty(self):
        self.assertEqual(ps_replay_batch.classify_paths([], "subject"), "empty")

    def test_cc_in_plugin_is_source_not_plugin(self):
        # HP-8: extension override beats plugin/ prefix rule.
        self.assertEqual(
            ps_replay_batch.classify_paths(["plugin/foo/bar.cc"], "subject"),
            "source",
        )

    def test_header_in_mysql_test_is_source_not_no_build(self):
        # HP-8: extension override beats mysql-test/ no-build rule.
        self.assertEqual(
            ps_replay_batch.classify_paths(["mysql-test/include/foo.h"], "subject"),
            "source",
        )

    def test_cmake_in_packaging_is_source_not_no_build(self):
        self.assertEqual(
            ps_replay_batch.classify_paths(["packaging/rpm-oel/foo.cmake"], "subject"),
            "source",
        )

    def test_uppercase_extension_still_matches(self):
        self.assertEqual(
            ps_replay_batch.classify_paths(["plugin/foo/Bar.CPP"], "subject"),
            "source",
        )

    def test_all_no_build_paths_still_no_build_without_source_extension(self):
        self.assertEqual(
            ps_replay_batch.classify_paths(
                ["mysql-test/r/foo.result", "packaging/rpm-oel/foo.spec"], "subject"
            ),
            "no-build",
        )

    def test_plugin_only_without_source_extensions_is_plugin(self):
        self.assertEqual(
            ps_replay_batch.classify_paths(
                ["plugin/foo/CMakeLists.txt", "plugin/foo/README"], "subject"
            ),
            "plugin",
        )

    def test_sql_directory_is_source(self):
        self.assertEqual(
            ps_replay_batch.classify_paths(["sql/sql_acl.cc"], "subject"),
            "source",
        )


if __name__ == "__main__":
    unittest.main()

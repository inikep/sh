#!/usr/bin/env python3
"""Focused tests for ps_replay_batch.py helper behavior."""

from pathlib import Path
from unittest.mock import patch
import unittest

import ps_replay_batch


class ArgumentParsingTests(unittest.TestCase):
    def test_group8_marker_is_default_boundary(self):
        argv = ["ps_replay_batch.py", "--source-list", "list.txt", "--start", "1", "--end", "1"]
        with patch("sys.argv", argv):
            args = ps_replay_batch.parse_args()

        self.assertEqual(
            args.group8_marker,
            "==================== MARKER: GROUP 9 — Upstream bug fixes ====================",
        )
        self.assertFalse(args.allow_missing_group8_marker)

    def test_legacy_group7_options_remain_aliases(self):
        argv = [
            "ps_replay_batch.py",
            "--source-list",
            "list.txt",
            "--start",
            "1",
            "--end",
            "1",
            "--group7-marker",
            "legacy marker",
            "--allow-missing-group7-marker",
        ]
        with patch("sys.argv", argv):
            args = ps_replay_batch.parse_args()

        self.assertEqual(args.group8_marker, "legacy marker")
        self.assertTrue(args.allow_missing_group8_marker)


class SubjectLoadingTests(unittest.TestCase):
    def test_loads_only_selected_range_when_marker_is_inside_range(self):
        commits = [f"sha-{idx}" for idx in range(1, 101)]
        subjects_by_sha = {
            sha: f"subject {idx}"
            for idx, sha in enumerate(commits, start=1)
        }
        subjects_by_sha["sha-45"] = "==================== MARKER: GROUP 9 — Upstream bug fixes ===================="
        calls = []

        def lookup(_worktree: Path, sha: str) -> str:
            calls.append(sha)
            return subjects_by_sha[sha]

        subjects, marker_index = ps_replay_batch.load_subjects(
            Path("."),
            commits,
            1,
            70,
            "==================== MARKER: GROUP 9 — Upstream bug fixes ====================",
            lookup,
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
        subjects_by_sha["sha-45"] = "==================== MARKER: GROUP 9 — Upstream bug fixes ===================="
        calls = []

        def lookup(_worktree: Path, sha: str) -> str:
            calls.append(sha)
            return subjects_by_sha[sha]

        subjects, marker_index = ps_replay_batch.load_subjects(
            Path("."),
            commits,
            150,
            155,
            "==================== MARKER: GROUP 9 — Upstream bug fixes ====================",
            lookup,
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
        subjects_by_sha["sha-45"] = "==================== MARKER: GROUP 9 — Upstream bug fixes ===================="
        calls = []

        def lookup(_worktree: Path, sha: str) -> str:
            calls.append(sha)
            return subjects_by_sha[sha]

        subjects, marker_index = ps_replay_batch.load_subjects(
            Path("."),
            commits,
            1,
            40,
            "==================== MARKER: GROUP 9 — Upstream bug fixes ====================",
            lookup,
        )

        self.assertEqual(marker_index, 45)
        self.assertEqual(set(subjects), set(range(1, 41)))
        self.assertEqual(calls, commits[:45])


class BuildPolicyTests(unittest.TestCase):
    def test_forced_pre_group8_no_build_never_builds_at_fence(self):
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
        self.assertEqual(reason, "pre-group8-no-build-exempt")

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


class Hp8PathCheckTests(unittest.TestCase):
    def test_missing_paths_uses_source_plugin_subset(self):
        missing = ps_replay_batch.hp8_missing_paths(
            [
                "sql/sql_class.cc",
                "mysql-test/r/source_only.result",
                "plugin/audit/audit_log.cc",
                "docs/readme.md",
            ],
            ["sql/sql_class.cc", "mysql-test/r/source_only.result"],
        )

        self.assertEqual(missing, ["plugin/audit/audit_log.cc"])

    def test_output_paths_can_satisfy_post_boundary_hp8(self):
        missing = ps_replay_batch.hp8_missing_paths(
            ["client/mysqldump.c", "mysql-test/r/mysqldump.result"],
            ["client/mysqldump.c"],
        )

        self.assertEqual(missing, [])


class ReplayCommandSafetyTests(unittest.TestCase):
    def test_batch_driver_does_not_use_no_commit_cherry_pick(self):
        script = Path(ps_replay_batch.__file__).read_text()

        self.assertNotIn('["cherry-pick", "--no-commit"', script)
        self.assertNotIn("cherry-pick --no-commit", script)
        self.assertNotIn("--allow-empty\", sha", script)


class ClassifyPathsTests(unittest.TestCase):
    """HP-8 extension-based Source override (SKILL.md §2 Bucketing)."""

    def test_marker_subject_is_empty_marker(self):
        self.assertEqual(
            ps_replay_batch.classify_paths(["sql/sql_acl.cc"], "=== MARKER: GROUP 7 — foo"),
            "empty-marker",
        )

    def test_wide_marker_subject_is_empty_marker(self):
        self.assertEqual(
            ps_replay_batch.classify_paths(
                ["sql/sql_acl.cc"],
                "==================== MARKER: GROUP 9 — Upstream bug fixes ====================",
            ),
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


class FeatureGateTests(unittest.TestCase):
    def test_no_record_never_stops(self):
        self.assertIsNone(ps_replay_batch.gate_stop_hint(None, 5, 100, set()))

    def test_pre_checkpoint_stops_on_needs_review_and_partial_match(self):
        for hint in ("needs-review", "partial-match-review"):
            record = {"decision_hint": hint}
            self.assertEqual(
                ps_replay_batch.gate_stop_hint(record, 5, 100, set()), hint
            )

    def test_pre_checkpoint_clean_hints_proceed(self):
        for hint in ("reference-present", "message-only-review", "no-diff-identifiers"):
            record = {"decision_hint": hint}
            self.assertIsNone(ps_replay_batch.gate_stop_hint(record, 5, 100, set()))

    def test_post_checkpoint_stops_only_on_needs_review(self):
        self.assertEqual(
            ps_replay_batch.gate_stop_hint({"decision_hint": "needs-review"}, 150, 100, set()),
            "needs-review",
        )
        self.assertIsNone(
            ps_replay_batch.gate_stop_hint(
                {"decision_hint": "partial-match-review"}, 150, 100, set()
            )
        )

    def test_missing_marker_is_treated_as_pre_checkpoint(self):
        record = {"decision_hint": "partial-match-review"}
        self.assertEqual(
            ps_replay_batch.gate_stop_hint(record, 5, None, set()),
            "partial-match-review",
        )

    def test_decided_apply_index_proceeds(self):
        record = {"decision_hint": "needs-review"}
        self.assertIsNone(ps_replay_batch.gate_stop_hint(record, 5, 100, {5}))

    def test_load_decided_apply_indexes_accepts_notes_and_comments(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decided.txt"
            path.write_text(
                "\n"
                "# reviewed MyRocks block\n"
                "58 reference-present after targeted grep\n"
                "59\tapplied-equivalent naming drift\n"
            )

            indexes = ps_replay_batch.load_decided_apply_indexes([path])

        self.assertEqual(indexes, {58, 59})

    def test_load_decided_apply_indexes_rejects_bad_index(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decided.txt"
            path.write_text("not-an-index reviewed\n")

            with self.assertRaises(SystemExit):
                ps_replay_batch.load_decided_apply_indexes([path])

    def test_load_gate_records_merges_files_by_index(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            pre = Path(tmp) / "pre-group9-gate.json"
            post = Path(tmp) / "range-gate.json"
            pre.write_text(json.dumps({"records": [{"index": 3, "decision_hint": "needs-review"}]}))
            post.write_text(json.dumps({"records": [{"index": 120, "decision_hint": "reference-present"}]}))

            records = ps_replay_batch.load_gate_records([pre, post])

        self.assertEqual(set(records), {3, 120})
        self.assertEqual(records[3]["decision_hint"], "needs-review")

    def test_gate_args_default_empty(self):
        argv = ["ps_replay_batch.py", "--source-list", "list.txt", "--start", "1", "--end", "1"]
        with patch("sys.argv", argv):
            args = ps_replay_batch.parse_args()

        self.assertEqual(args.feature_gate, [])
        self.assertEqual(args.gate_decided_apply, [])
        self.assertEqual(args.gate_decided_apply_file, [])
        self.assertEqual(args.gate_auto_apply_path_glob, [])
        self.assertEqual(args.gate_auto_apply_unmatched_identifier, [])
        self.assertEqual(args.auto_drop_reference_absent_conflict_glob, [])
        self.assertIsNone(args.ledger_file)

    def test_gate_auto_apply_requires_configured_path_globs(self):
        record = {
            "changed_paths": ["build-ps/ubuntu/control"],
            "matched_changed_paths": [],
            "unmatched_diff_identifiers": [],
        }

        self.assertIsNone(ps_replay_batch.gate_auto_apply_reason(record, [], set()))

    def test_gate_auto_apply_accepts_only_unmatched_paths_matching_globs(self):
        record = {
            "changed_paths": ["build-ps/debian/control", "build-ps/ubuntu/control"],
            "matched_changed_paths": ["build-ps/debian/control"],
            "unmatched_diff_identifiers": [],
        }

        reason = ps_replay_batch.gate_auto_apply_reason(
            record,
            ["build-ps/ubuntu/**"],
            set(),
        )

        self.assertIsNotNone(reason)

    def test_gate_auto_apply_rejects_unallowed_unmatched_identifier(self):
        record = {
            "changed_paths": ["build-ps/ubuntu/control"],
            "matched_changed_paths": [],
            "unmatched_diff_identifiers": ["key_buffer"],
        }

        self.assertIsNone(
            ps_replay_batch.gate_auto_apply_reason(
                record,
                ["build-ps/ubuntu/**"],
                set(),
            )
        )
        self.assertIsNotNone(
            ps_replay_batch.gate_auto_apply_reason(
                record,
                ["build-ps/ubuntu/**"],
                {"key_buffer"},
            )
        )

    def test_auto_droppable_conflicts_requires_absent_reference_and_matching_glob(self):
        conflicts = [Path("build-ps/ubuntu/control"), Path("build-ps/debian/control.notokudb")]

        with patch("ps_replay_batch.path_exists_on_reference", return_value=False):
            ok, paths, reasons = ps_replay_batch.auto_droppable_conflicts(
                Path("."),
                "reference",
                conflicts,
                ["build-ps/ubuntu/**", "build-ps/debian/*.notokudb"],
            )

        self.assertTrue(ok)
        self.assertEqual(paths, conflicts)
        self.assertEqual(reasons, [])

    def test_auto_droppable_conflicts_rejects_reference_present_path(self):
        conflicts = [Path("build-ps/ubuntu/control")]

        with patch("ps_replay_batch.path_exists_on_reference", return_value=True):
            ok, paths, reasons = ps_replay_batch.auto_droppable_conflicts(
                Path("."),
                "reference",
                conflicts,
                ["build-ps/ubuntu/**"],
            )

        self.assertFalse(ok)
        self.assertEqual(paths, [])
        self.assertEqual(reasons, ["build-ps/ubuntu/control exists on reference"])


if __name__ == "__main__":
    unittest.main()

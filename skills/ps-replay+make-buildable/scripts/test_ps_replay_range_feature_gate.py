#!/usr/bin/env python3
"""Unit tests for ps_replay_range_feature_gate.py evidence classification."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import ps_replay_feature_gate as commit_gate
import ps_replay_range_feature_gate as range_gate


def decide(
    diff_identifiers=(),
    message_identifiers=(),
    changed_paths=(),
    added_paths=(),
    reference_identifiers=(),
    reference_changed_paths=(),
    reference_added_paths=(),
):
    """Thin wrapper so each decision-table case reads as its own evidence."""
    return range_gate.source_record_from_parts_for_test(
        diff_identifiers=list(diff_identifiers),
        message_identifiers=list(message_identifiers),
        changed_paths=list(changed_paths),
        added_paths=list(added_paths),
        reference_identifiers=set(reference_identifiers),
        reference_changed_paths=set(reference_changed_paths),
        reference_added_paths=set(reference_added_paths),
    )


class DecisionTableTests(unittest.TestCase):
    """One case per branch of classify_match, in decision order."""

    def test_no_diff_identifiers_short_circuits(self):
        self.assertEqual(decide(), "no-diff-identifiers")

    def test_message_identifiers_alone_are_still_no_diff_identifiers(self):
        decision = decide(
            message_identifiers=["commit_ordered"],
            changed_paths=["sql/sql_show.cc"],
            reference_changed_paths={"sql/sql_show.cc"},
        )
        self.assertEqual(decision, "no-diff-identifiers")

    def test_unmatched_diff_without_any_match_is_needs_review(self):
        decision = decide(
            diff_identifiers=["feature_token"],
            changed_paths=["sql/sql_show.cc"],
            reference_changed_paths={"sql/other.cc"},
        )
        self.assertEqual(decision, "needs-review")

    def test_unmatched_diff_with_matching_identifier_is_partial_review(self):
        decision = decide(
            diff_identifiers=["feature_token", "present_token"],
            reference_identifiers={"present_token"},
        )
        self.assertEqual(decision, "partial-match-review")

    def test_unmatched_diff_with_matching_path_is_partial_review(self):
        decision = decide(
            diff_identifiers=["feature_token"],
            changed_paths=["sql/sql_show.cc"],
            reference_changed_paths={"sql/sql_show.cc"},
        )
        self.assertEqual(decision, "partial-match-review")

    def test_unmatched_diff_with_matching_added_path_is_partial_review(self):
        decision = decide(
            diff_identifiers=["feature_token"],
            added_paths=["plugin/feat/feat.cc"],
            reference_added_paths={"plugin/feat/feat.cc"},
        )
        self.assertEqual(decision, "partial-match-review")

    def test_all_diff_matched_with_unmatched_message_is_message_only_review(self):
        decision = decide(
            diff_identifiers=["present_token"],
            message_identifiers=["absent_token"],
            reference_identifiers={"present_token"},
        )
        self.assertEqual(decision, "message-only-review")

    def test_everything_matched_is_reference_present(self):
        decision = decide(
            diff_identifiers=["present_token"],
            message_identifiers=["also_present"],
            reference_identifiers={"present_token", "also_present"},
        )
        self.assertEqual(decision, "reference-present")

    def test_matched_path_does_not_rescue_a_fully_unmatched_message_set(self):
        """A path match only downgrades needs-review; it cannot claim presence."""
        decision = decide(
            diff_identifiers=["absent_token"],
            message_identifiers=["absent_message_token"],
            changed_paths=["sql/sql_show.cc"],
            reference_changed_paths={"sql/sql_show.cc"},
        )
        self.assertEqual(decision, "partial-match-review")


def git(worktree, *args):
    subprocess.run(
        ["git", *args],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    )


class SourceRecordDriftTests(unittest.TestCase):
    """source_record() re-implements the shim's matched/unmatched filtering.

    These tests run the production path against a real repository and assert
    it agrees with source_record_from_parts_for_test(), so the two filters
    cannot drift apart unnoticed.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.worktree = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        git(self.worktree, "init", "-q", "-b", "base")
        git(self.worktree, "config", "user.email", "test@example.com")
        git(self.worktree, "config", "user.name", "test")
        (self.worktree / "sql").mkdir()
        (self.worktree / "sql" / "sql_show.cc").write_text("int existing_helper() { return 0; }\n")
        git(self.worktree, "add", "-A")
        git(self.worktree, "commit", "-qm", "base commit")

        # Reference branch: adds present_helper() in sql/sql_show.cc.
        git(self.worktree, "checkout", "-q", "-b", "reference")
        (self.worktree / "sql" / "sql_show.cc").write_text(
            "int existing_helper() { return 0; }\nint present_helper() { return 1; }\n"
        )
        git(self.worktree, "commit", "-qam", "add present_helper")

    def make_source_commit(self, contents: str, subject: str) -> str:
        git(self.worktree, "checkout", "-q", "base")
        git(self.worktree, "checkout", "-q", "-B", "source")
        (self.worktree / "sql" / "sql_show.cc").write_text(contents)
        git(self.worktree, "commit", "-qam", subject)
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.worktree,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    def make_added_file_commit(self, path: str, contents: str, subject: str) -> str:
        """A commit that only adds `path`, so added-path evidence is isolated."""
        git(self.worktree, "checkout", "-q", "base")
        git(self.worktree, "checkout", "-q", "-B", "source")
        target = self.worktree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
        git(self.worktree, "add", "-A")
        git(self.worktree, "commit", "-qm", subject)
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.worktree,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    def reference_sets(self):
        return (
            range_gate.reference_identifiers(self.worktree, "base", "reference"),
            range_gate.changed_paths_in_range(self.worktree, "base", "reference"),
            range_gate.added_paths_in_range(self.worktree, "base", "reference"),
        )

    def assert_production_matches_shim(self, commit):
        ref_ids, ref_changed, ref_added = self.reference_sets()
        record = range_gate.source_record(
            self.worktree, 1, commit, ref_ids, ref_changed, ref_added, 20
        )
        shim_decision = range_gate.source_record_from_parts_for_test(
            diff_identifiers=record["diff_identifiers"],
            message_identifiers=record["message_only_identifiers"],
            changed_paths=record["changed_paths"],
            added_paths=record["added_paths"],
            reference_identifiers=ref_ids,
            reference_changed_paths=ref_changed,
            reference_added_paths=ref_added,
        )
        self.assertEqual(record["decision_hint"], shim_decision)
        return record

    def test_reference_present_commit_agrees_with_shim(self):
        commit = self.make_source_commit(
            "int existing_helper() { return 0; }\nint present_helper() { return 1; }\n",
            "port present_helper",
        )
        record = self.assert_production_matches_shim(commit)
        self.assertEqual(record["decision_hint"], "reference-present")
        self.assertIn("present_helper", record["matched_diff_identifiers"])

    def test_partial_match_commit_agrees_with_shim(self):
        commit = self.make_source_commit(
            "int existing_helper() { return 0; }\n"
            "int present_helper() { return 1; }\n"
            "int absent_helper() { return 2; }\n",
            "port present_helper and absent_helper",
        )
        record = self.assert_production_matches_shim(commit)
        self.assertEqual(record["decision_hint"], "partial-match-review")
        self.assertIn("absent_helper", record["unmatched_diff_identifiers"])

    def test_path_only_match_agrees_with_shim(self):
        """The one case where matched_changed_paths alone decides the hint.

        Without this case a broken path filter in source_record() is
        invisible, because every other case already has identifier evidence.
        """
        commit = self.make_source_commit(
            "int existing_helper() { return 0; }\nint absent_helper() { return 2; }\n",
            "port absent_helper",
        )
        record = self.assert_production_matches_shim(commit)
        self.assertEqual(record["matched_diff_identifiers"], [])
        self.assertEqual(record["matched_changed_paths"], ["sql/sql_show.cc"])
        self.assertEqual(record["decision_hint"], "partial-match-review")

    def test_added_path_absent_from_reference_agrees_with_shim(self):
        """Isolates added-path evidence: a file the reference never added
        must not count as a match."""
        commit = self.make_added_file_commit(
            "plugin/absent/absent_feat.cc",
            "int absent_feature_entry() { return 5; }\n",
            "add absent_feat plugin file",
        )
        record = self.assert_production_matches_shim(commit)
        self.assertEqual(record["added_paths"], ["plugin/absent/absent_feat.cc"])
        self.assertEqual(record["matched_added_paths"], [])
        self.assertEqual(record["matched_changed_paths"], [])
        self.assertEqual(record["decision_hint"], "needs-review")

    def test_message_only_identifiers_are_not_counted_as_diff_evidence(self):
        commit = self.make_source_commit(
            "int existing_helper() { return 0; }\nint present_helper() { return 1; }\n",
            "port present_helper (relates to absent_subject_token)",
        )
        record = self.assert_production_matches_shim(commit)
        self.assertNotIn("absent_subject_token", record["diff_identifiers"])
        self.assertIn("absent_subject_token", record["message_only_identifiers"])
        self.assertIn("absent_subject_token", record["unmatched_message_only_identifiers"])
        self.assertEqual(record["decision_hint"], "message-only-review")

    def test_reference_identifiers_come_from_added_lines_only(self):
        ref_ids, _, _ = self.reference_sets()
        self.assertIn("present_helper", ref_ids)
        self.assertNotIn("existing_helper", ref_ids)


class IdentifierHelperTests(unittest.TestCase):
    def test_range_gate_reuses_the_commit_gate_identifier_regex(self):
        """The range gate imports the per-commit gate as a library module."""
        self.assertIs(range_gate.commit_gate, commit_gate)
        self.assertTrue(commit_gate.interesting_identifier("present_helper"))


if __name__ == "__main__":
    unittest.main()

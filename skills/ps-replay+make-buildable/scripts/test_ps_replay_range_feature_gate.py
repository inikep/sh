#!/usr/bin/env python3
"""Unit tests for ps_replay_range_feature_gate.py evidence classification."""

import unittest

import ps_replay_range_feature_gate as range_gate


class SourceRecordTests(unittest.TestCase):
    def test_unmatched_diff_with_matching_path_is_partial_review(self):
        decision = range_gate.source_record_from_parts_for_test(
            diff_identifiers=["feature_token"],
            message_identifiers=[],
            changed_paths=["sql/sql_show.cc"],
            added_paths=[],
            reference_identifiers=set(),
            reference_changed_paths={"sql/sql_show.cc"},
            reference_added_paths=set(),
        )
        self.assertEqual(decision, "partial-match-review")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Focused tests for ps_replay_feature_gate.py evidence shaping."""

import unittest

import ps_replay_feature_gate


class IdentifierOriginTests(unittest.TestCase):
    def test_message_only_identifiers_are_separated_from_diff_identifiers(self):
        records = ps_replay_feature_gate.extract_identifier_records(
            "\n".join(
                [
                    "diff --git a/include/mysql/plugin.h b/include/mysql/plugin.h",
                    "+void increment_thd_innodb_stats(MYSQL_THD thd);",
                ]
            ),
            "[group_commit] Add commit_ordered handlerton hook",
            "Adds xa_binlog test coverage in the original patch context.",
            [],
            20,
        )

        by_identifier = {record.identifier: record.origins for record in records}

        self.assertIn("diff_added_line", by_identifier["increment_thd_innodb_stats"])
        self.assertIn("message_subject", by_identifier["commit_ordered"])
        self.assertIn("message_body", by_identifier["xa_binlog"])
        self.assertFalse(
            ps_replay_feature_gate.has_diff_origin(
                ps_replay_feature_gate.IdentifierRecord(
                    "commit_ordered",
                    by_identifier["commit_ordered"],
                )
            )
        )


if __name__ == "__main__":
    unittest.main()

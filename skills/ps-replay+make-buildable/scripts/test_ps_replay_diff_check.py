#!/usr/bin/env python3
"""Tests for ps_replay_diff_check.py."""

import unittest

import ps_replay_diff_check


class ParseDiffCheckOutputTests(unittest.TestCase):
    def test_parses_trailing_whitespace_warning_with_added_line(self):
        warnings = ps_replay_diff_check.parse_diff_check_output(
            "mysql-test/r/foo.result:11: trailing whitespace.\n"
            "+abc\tSELECT * FROM `t1` \n"
        )

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].path, "mysql-test/r/foo.result")
        self.assertEqual(warnings[0].line, 11)
        self.assertEqual(warnings[0].message, "trailing whitespace.")
        self.assertEqual(warnings[0].added_line, "abc\tSELECT * FROM `t1` ")


class ReferenceMatchTests(unittest.TestCase):
    def test_warning_matches_reference_when_exact_line_exists(self):
        warning = ps_replay_diff_check.DiffCheckWarning(
            path="mysql-test/r/foo.result",
            line=11,
            message="trailing whitespace.",
            added_line="abc\tSELECT * FROM `t1` ",
        )

        self.assertTrue(
            ps_replay_diff_check.warning_matches_reference(
                warning,
                lambda _path: ["abc\tSELECT * FROM `t1` "],
            )
        )

    def test_warning_does_not_match_reference_when_line_was_normalized(self):
        warning = ps_replay_diff_check.DiffCheckWarning(
            path="mysql-test/r/foo.result",
            line=11,
            message="trailing whitespace.",
            added_line="abc\tSELECT * FROM `t1` ",
        )

        self.assertFalse(
            ps_replay_diff_check.warning_matches_reference(
                warning,
                lambda _path: ["abc\tSELECT * FROM `t1`"],
            )
        )

    def test_non_whitespace_warning_is_not_auto_allowed(self):
        warning = ps_replay_diff_check.DiffCheckWarning(
            path="mysql-test/r/foo.result",
            line=11,
            message="some other warning.",
            added_line="abc ",
        )

        self.assertFalse(
            ps_replay_diff_check.warning_matches_reference(
                warning,
                lambda _path: ["abc "],
            )
        )

    def test_blank_line_at_eof_matches_reference_blank_eof(self):
        warning = ps_replay_diff_check.DiffCheckWarning(
            path="mysql-test/mysql-test-run.pl",
            line=7335,
            message="new blank line at EOF.",
            added_line=None,
        )

        self.assertTrue(
            ps_replay_diff_check.warning_matches_reference(
                warning,
                lambda _path: ["  exit(1);", "}", ""],
            )
        )

    def test_blank_line_at_eof_does_not_match_reference_without_blank_eof(self):
        warning = ps_replay_diff_check.DiffCheckWarning(
            path="mysql-test/mysql-test-run.pl",
            line=7335,
            message="new blank line at EOF.",
            added_line="",
        )

        self.assertFalse(
            ps_replay_diff_check.warning_matches_reference(
                warning,
                lambda _path: ["", "  exit(1);", "}"],
            )
        )


if __name__ == "__main__":
    unittest.main()

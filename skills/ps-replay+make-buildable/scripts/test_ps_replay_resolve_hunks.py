#!/usr/bin/env python3
"""Tests for ps_replay_resolve_hunks.py.

This is the only helper that rewrites worktree files unsupervised, so the
tests pin both the side-picking heuristic and the HP-1 invariant: only
conflict blocks may be replaced, never whole files.
"""

import contextlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import ps_replay_resolve_hunks as resolver


CLASSIC_BLOCK = "\n".join(
    [
        "<<<<<<< HEAD",
        "int head_helper() { return 1; }",
        "=======",
        "int theirs_helper() { return 2; }",
        ">>>>>>> source commit",
    ]
)

DIFF3_BLOCK = "\n".join(
    [
        "<<<<<<< HEAD",
        "int head_helper() { return 1; }",
        "||||||| parent",
        "int parent_helper() { return 0; }",
        "=======",
        "int theirs_helper() { return 2; }",
        ">>>>>>> source commit",
    ]
)


class SplitIntoSegmentsTests(unittest.TestCase):
    def test_merged_context_is_kept_separate_from_the_conflict_block(self):
        text = f"int before() {{}}\n{CLASSIC_BLOCK}\nint after() {{}}\n"

        segments = resolver.split_into_segments(text)

        kinds = [kind for kind, _ in segments]
        self.assertEqual(kinds, ["merged", "conflict", "merged"])
        self.assertEqual(segments[0][1], "int before() {}")
        self.assertEqual(segments[1][1], CLASSIC_BLOCK)
        self.assertEqual(segments[2][1], "int after() {}\n")

    def test_multiple_conflict_blocks_are_split_independently(self):
        text = f"a_line_one\n{CLASSIC_BLOCK}\nb_line_two\n{DIFF3_BLOCK}\nc_line_three\n"

        segments = resolver.split_into_segments(text)

        self.assertEqual(
            [kind for kind, _ in segments],
            ["merged", "conflict", "merged", "conflict", "merged"],
        )

    def test_file_without_markers_is_one_merged_segment(self):
        segments = resolver.split_into_segments("int only() { return 0; }\n")

        self.assertEqual([kind for kind, _ in segments], ["merged"])


class ParseConflictBlockTests(unittest.TestCase):
    def test_classic_block_has_no_parent_side(self):
        head, parent, theirs = resolver.parse_conflict_block(CLASSIC_BLOCK)

        self.assertEqual(head, ["int head_helper() { return 1; }"])
        self.assertIsNone(parent)
        self.assertEqual(theirs, ["int theirs_helper() { return 2; }"])

    def test_diff3_block_separates_the_parent_side(self):
        head, parent, theirs = resolver.parse_conflict_block(DIFF3_BLOCK)

        self.assertEqual(head, ["int head_helper() { return 1; }"])
        self.assertEqual(parent, ["int parent_helper() { return 0; }"])
        self.assertEqual(theirs, ["int theirs_helper() { return 2; }"])

    def test_parent_lines_never_leak_into_theirs(self):
        _, _, theirs = resolver.parse_conflict_block(DIFF3_BLOCK)

        self.assertNotIn("int parent_helper() { return 0; }", theirs)


class OverlapScoreTests(unittest.TestCase):
    def test_counts_distinct_non_trivial_lines_present_in_reference(self):
        score = resolver.overlap_score(
            ["int alpha_helper();", "int beta_helper();"],
            {"int alpha_helper();", "int beta_helper();"},
        )

        self.assertEqual(score, 2)

    def test_duplicate_lines_within_a_side_are_counted_once(self):
        score = resolver.overlap_score(
            ["int alpha_helper();", "int alpha_helper();"],
            {"int alpha_helper();"},
        )

        self.assertEqual(score, 1)

    def test_trivial_and_blank_lines_are_not_counted(self):
        score = resolver.overlap_score(
            ["", "  ", "}", "});"],
            {"", "}", "});"},
        )

        self.assertEqual(score, 0)

    def test_scoring_ignores_leading_and_trailing_whitespace(self):
        score = resolver.overlap_score(
            ["    int alpha_helper();   "],
            {"int alpha_helper();"},
        )

        self.assertEqual(score, 1)

    def test_lines_absent_from_reference_score_zero(self):
        score = resolver.overlap_score(
            ["int alpha_helper();"],
            {"int other_helper();"},
        )

        self.assertEqual(score, 0)


def git(worktree, *args):
    subprocess.run(
        ["git", *args],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    )


@contextlib.contextmanager
def chdir(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class ResolveFileTests(unittest.TestCase):
    """resolve_file() runs git and reads files relative to the current dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.worktree = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        git(self.worktree, "init", "-q", "-b", "base")
        git(self.worktree, "config", "user.email", "test@example.com")
        git(self.worktree, "config", "user.name", "test")
        (self.worktree / "a.cc").write_text("int placeholder() { return 0; }\n")
        git(self.worktree, "add", "-A")
        git(self.worktree, "commit", "-qm", "base commit")
        git(self.worktree, "checkout", "-q", "-b", "reference")

    def set_reference(self, contents: str):
        (self.worktree / "a.cc").write_text(contents)
        git(self.worktree, "commit", "-qam", "reference content")

    def write_conflict(self, contents: str, path: str = "a.cc"):
        (self.worktree / path).write_text(contents)

    def resolve(self, path: str = "a.cc"):
        with chdir(self.worktree):
            return resolver.resolve_file("reference", path)

    def read(self, path: str = "a.cc") -> str:
        return (self.worktree / path).read_text()

    def test_picks_the_side_matching_reference(self):
        self.set_reference("int theirs_helper() { return 2; }\n")
        self.write_conflict(f"int before() {{}}\n{CLASSIC_BLOCK}\nint after() {{}}\n")

        _, conflicts, unresolved = self.resolve()

        self.assertEqual((conflicts, unresolved), (1, 0))
        self.assertEqual(
            self.read(),
            "int before() {}\nint theirs_helper() { return 2; }\nint after() {}\n",
        )

    def test_picks_head_when_head_is_the_side_on_reference(self):
        self.set_reference("int head_helper() { return 1; }\n")
        self.write_conflict(f"{CLASSIC_BLOCK}\n")

        _, conflicts, unresolved = self.resolve()

        self.assertEqual((conflicts, unresolved), (1, 0))
        self.assertEqual(self.read(), "int head_helper() { return 1; }\n")

    def test_equal_overlap_breaks_the_tie_toward_head(self):
        self.set_reference(
            "int head_helper() { return 1; }\nint theirs_helper() { return 2; }\n"
        )
        self.write_conflict(f"{CLASSIC_BLOCK}\n")

        _, _, unresolved = self.resolve()

        self.assertEqual(unresolved, 0)
        self.assertEqual(self.read(), "int head_helper() { return 1; }\n")

    def test_neither_side_on_reference_leaves_the_block_intact(self):
        self.set_reference("int unrelated_helper() { return 9; }\n")
        self.write_conflict(f"int before() {{}}\n{CLASSIC_BLOCK}\nint after() {{}}\n")

        _, conflicts, unresolved = self.resolve()

        self.assertEqual((conflicts, unresolved), (1, 1))
        self.assertIn("<<<<<<< HEAD", self.read())
        self.assertIn(">>>>>>> source commit", self.read())

    def test_missing_path_on_reference_leaves_every_block_unresolved(self):
        self.set_reference("int theirs_helper() { return 2; }\n")
        self.write_conflict(f"{CLASSIC_BLOCK}\n", path="new_file.cc")

        _, conflicts, unresolved = self.resolve("new_file.cc")

        self.assertEqual((conflicts, unresolved), (1, 1))
        self.assertIn("<<<<<<<", self.read("new_file.cc"))

    def test_diff3_parent_side_is_never_written_out(self):
        self.set_reference("int theirs_helper() { return 2; }\n")
        self.write_conflict(f"{DIFF3_BLOCK}\n")

        _, _, unresolved = self.resolve()

        self.assertEqual(unresolved, 0)
        self.assertNotIn("parent_helper", self.read())
        self.assertNotIn("|||||||", self.read())

    def test_only_the_conflict_block_is_replaced_hp1(self):
        """HP-1: merged context must survive byte-for-byte, even when it
        differs from reference."""
        self.set_reference("int theirs_helper() { return 2; }\n")
        self.write_conflict(
            "int local_only_before() { return 7; }\n"
            f"{CLASSIC_BLOCK}\n"
            "int local_only_after() { return 8; }\n"
        )

        self.resolve()
        result = self.read()

        self.assertIn("int local_only_before() { return 7; }", result)
        self.assertIn("int local_only_after() { return 8; }", result)

    def test_resolves_each_block_of_a_multi_conflict_file_independently(self):
        self.set_reference(
            "int head_helper() { return 1; }\nint theirs_helper() { return 2; }\n"
        )
        second_block = "\n".join(
            [
                "<<<<<<< HEAD",
                "int absent_head() { return 3; }",
                "=======",
                "int theirs_helper() { return 2; }",
                ">>>>>>> source commit",
            ]
        )
        self.write_conflict(f"{CLASSIC_BLOCK}\nmid_context_line\n{second_block}\n")

        _, conflicts, unresolved = self.resolve()

        self.assertEqual((conflicts, unresolved), (2, 0))
        self.assertEqual(
            self.read(),
            "int head_helper() { return 1; }\n"
            "mid_context_line\n"
            "int theirs_helper() { return 2; }\n",
        )

    def test_get_reference_text_returns_none_for_a_path_absent_from_reference(self):
        self.set_reference("int theirs_helper() { return 2; }\n")

        with chdir(self.worktree):
            present = resolver.get_reference_text("reference", "a.cc")
            missing = resolver.get_reference_text("reference", "not_on_reference.cc")

        self.assertEqual(present, "int theirs_helper() { return 2; }\n")
        self.assertIsNone(missing)

    def test_file_without_markers_is_left_untouched(self):
        self.set_reference("int theirs_helper() { return 2; }\n")
        original = "int no_conflict_here() { return 0; }\n"
        self.write_conflict(original)

        counts = self.resolve()

        self.assertEqual(counts, (0, 0, 0))
        self.assertEqual(self.read(), original)

    def test_trailing_newline_is_preserved(self):
        self.set_reference("int theirs_helper() { return 2; }\n")
        self.write_conflict(f"{CLASSIC_BLOCK}\n")

        self.resolve()

        self.assertTrue(self.read().endswith("\n"))
        self.assertFalse(self.read().endswith("\n\n"))


class MainExitCodeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.worktree = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        git(self.worktree, "init", "-q", "-b", "base")
        git(self.worktree, "config", "user.email", "test@example.com")
        git(self.worktree, "config", "user.name", "test")
        (self.worktree / "a.cc").write_text("int theirs_helper() { return 2; }\n")
        git(self.worktree, "add", "-A")
        git(self.worktree, "commit", "-qm", "base commit")
        git(self.worktree, "checkout", "-q", "-b", "reference")

    def run_cli(self, *args):
        return subprocess.run(
            ["python3", str(Path(__file__).parent / "ps_replay_resolve_hunks.py"), *args],
            cwd=self.worktree,
            capture_output=True,
            text=True,
        )

    def test_exits_zero_when_every_region_is_resolved(self):
        (self.worktree / "a.cc").write_text(f"{CLASSIC_BLOCK}\n")

        proc = self.run_cli("reference", "a.cc")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("0 left unresolved", proc.stdout)

    def test_exits_one_when_a_region_stays_unresolved(self):
        unresolvable = "\n".join(
            [
                "<<<<<<< HEAD",
                "int absent_head() { return 3; }",
                "=======",
                "int absent_theirs() { return 4; }",
                ">>>>>>> source commit",
            ]
        )
        (self.worktree / "a.cc").write_text(f"{unresolvable}\n")

        proc = self.run_cli("reference", "a.cc")

        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("1 left unresolved", proc.stdout)

    def test_all_is_exclusive_with_explicit_paths(self):
        proc = self.run_cli("reference", "a.cc", "--all")

        self.assertEqual(proc.returncode, 2)
        self.assertIn("--all is exclusive with explicit paths", proc.stderr)

    def test_no_paths_is_an_invocation_error(self):
        proc = self.run_cli("reference")

        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage:", proc.stderr)

    def test_all_finds_tracked_files_with_markers(self):
        (self.worktree / "a.cc").write_text(f"{CLASSIC_BLOCK}\n")

        proc = self.run_cli("reference", "--all")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("a.cc", proc.stdout)


if __name__ == "__main__":
    unittest.main()

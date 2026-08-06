from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ddvc.provenance import cache_key, describe_input, git_state, input_matches


class ProvenanceInputTests(unittest.TestCase):
    def test_file_change_invalidates_recorded_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.txt"
            path.write_text("first")
            record = describe_input(path)
            self.assertTrue(input_matches(record))
            path.write_text("second")
            self.assertFalse(input_matches(record))

    def test_directory_tree_change_invalidates_recorded_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("a")
            record = describe_input(root)
            self.assertEqual(record["kind"], "directory")
            self.assertEqual(record["entries"], 1)
            self.assertTrue(input_matches(record))
            (root / "b.txt").write_text("b")
            self.assertFalse(input_matches(record))

    def test_cache_key_changes_with_declared_input_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("a")
            sources = ["tests/test_provenance_inputs.py"]
            before = cache_key(sources, inputs=[root])
            (root / "b.txt").write_text("b")
            after = cache_key(sources, inputs=[root])
            self.assertNotEqual(before, after)

    @patch("ddvc.provenance._run")
    def test_generated_target_does_not_mark_its_own_build_dirty(self, run) -> None:
        run.side_effect = [
            "abc123",
            " M output/exhibits/result.jsonl\n M src/ddvc/model.py",
            "main",
        ]
        state = git_state(["output/exhibits/result.jsonl"])
        self.assertTrue(state["dirty"])
        self.assertEqual(state["dirty_tracked_files"], ["src/ddvc/model.py"])

    @patch("ddvc.provenance._run")
    def test_only_generated_targets_yield_a_clean_build_state(self, run) -> None:
        run.side_effect = [
            "abc123",
            " M output/exhibits/result.jsonl\n M data/manifests/output/exhibits/result.jsonl.prov.json",
            "main",
        ]
        state = git_state(
            [
                "output/exhibits/result.jsonl",
                "data/manifests/output/exhibits/result.jsonl.prov.json",
            ]
        )
        self.assertFalse(state["dirty"])
        self.assertEqual(state["dirty_tracked_files"], [])

    @patch("ddvc.provenance._run")
    def test_other_generated_outputs_do_not_taint_code_state(self, run) -> None:
        run.side_effect = [
            "abc123",
            " M output/exhibits/first.jsonl\n M data/manifests/output/exhibits/first.jsonl.prov.json",
            "main",
        ]
        state = git_state()
        self.assertFalse(state["dirty"])
        self.assertEqual(
            state["dirty_generated_files"],
            [
                "output/exhibits/first.jsonl",
                "data/manifests/output/exhibits/first.jsonl.prov.json",
            ],
        )

    @patch("ddvc.provenance._run")
    def test_untracked_source_marks_build_dirty(self, run) -> None:
        run.side_effect = [
            "abc123",
            "?? src/ddvc/new_estimator.py\n?? output/exhibits/new.jsonl",
            "main",
        ]
        state = git_state()
        self.assertTrue(state["dirty"])
        self.assertEqual(state["dirty_untracked_files"], ["src/ddvc/new_estimator.py"])
        self.assertEqual(state["dirty_generated_files"], ["output/exhibits/new.jsonl"])


if __name__ == "__main__":
    unittest.main()

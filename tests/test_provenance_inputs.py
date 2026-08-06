from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ddvc.provenance import describe_input, input_matches


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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.tables import write_exhibit, write_panel


class ExhibitWriterTests(unittest.TestCase):
    def test_nonfinite_values_are_strict_json_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "exhibit.jsonl"
            write_exhibit(
                pd.DataFrame({"nan": [float("nan")], "inf": [float("inf")]}),
                out,
                code_sources=["tests/test_tables.py"],
            )
            text = out.read_text()
            self.assertNotIn("NaN", text)
            self.assertNotIn("Infinity", text)
            self.assertEqual(json.loads(text), {"inf": None, "nan": None})

    def test_gzip_output_is_byte_deterministic_across_target_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.jsonl.gz"
            second = root / "second.jsonl.gz"
            frame = pd.DataFrame({"value": [1, 2]})
            for output in (first, second):
                write_exhibit(
                    frame,
                    output,
                    code_sources=["tests/test_tables.py"],
                )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with gzip.open(first, "rt") as handle:
                self.assertEqual(len(handle.readlines()), 2)
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_panel_writer_leaves_no_fixed_or_unique_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "panel.parquet"
            write_panel(
                pd.DataFrame({"value": [1, 2]}),
                output,
                code_sources=["tests/test_tables.py"],
            )
            self.assertEqual(pd.read_parquet(output)["value"].tolist(), [1, 2])
            self.assertEqual(list(root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

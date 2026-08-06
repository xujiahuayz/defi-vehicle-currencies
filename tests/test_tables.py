from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.tables import write_exhibit


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


if __name__ == "__main__":
    unittest.main()

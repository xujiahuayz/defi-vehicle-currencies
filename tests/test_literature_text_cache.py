from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def load_builder():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_literature_text_cache.py"
    spec = importlib.util.spec_from_file_location("build_literature_text_cache", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LiteratureTextCacheTests(unittest.TestCase):
    def test_extracted_text_drops_only_trailing_whitespace(self) -> None:
        builder = load_builder()
        self.assertEqual(
            builder.normalize_extracted_text("value  \n  indented\t\n"),
            "value\n  indented\n",
        )

    def test_sparse_pdf_run_preserves_durable_text_records(self) -> None:
        builder = load_builder()
        previous = {
            "paper-a": {"stem": "paper-a", "pages": 10, "chars": 1000},
            "stale": {"stem": "stale", "pages": 4, "chars": 400},
        }
        current = [{"stem": "paper-b", "pages": 20, "chars": 2000}]
        merged = builder.merge_index_records(current, previous, {"paper-a", "paper-b"})
        self.assertEqual([record["stem"] for record in merged], ["paper-a", "paper-b"])
        self.assertEqual(merged[0]["pages"], 10)

    def test_index_loader_ignores_invalid_and_unkeyed_rows(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.jsonl"
            path.write_text(
                json.dumps({"stem": "paper-a", "pages": 10})
                + "\nnot-json\n"
                + json.dumps({"pages": 20})
                + "\n"
            )
            self.assertEqual(set(builder.load_index(path)), {"paper-a"})


if __name__ == "__main__":
    unittest.main()

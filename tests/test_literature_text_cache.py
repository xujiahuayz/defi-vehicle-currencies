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

    def test_short_math_appendix_keeps_richer_ocr(self) -> None:
        builder = load_builder()
        self.assertTrue(builder.should_keep_existing_extract("x" * 1000, "x" * 60))
        self.assertFalse(builder.should_keep_existing_extract("x" * 100, "x" * 60))
        self.assertFalse(builder.should_keep_existing_extract("x" * 1000, "x" * 900))
        self.assertFalse(builder.needs_ocr({"chars": 1062, "pages": 3}))
        self.assertTrue(builder.needs_ocr({"chars": 66, "pages": 3}))
        self.assertTrue(builder.needs_ocr({"chars": 100, "pages": 0}))

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

    def test_corpus_check_requires_exact_pdf_text_and_checksum_sets(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            papers = root / "papers"
            text = root / "text"
            papers.mkdir()
            text.mkdir()
            paper = papers / "paper-a.pdf"
            paper.write_bytes(b"published article")
            (text / "paper-a.txt").write_text("full text")
            records = {
                "paper-a": {
                    "stem": "paper-a",
                    "pdf_sha256": builder.file_sha256(paper),
                }
            }
            self.assertEqual(builder.validate_corpus(records, papers, text), [])
            (papers / "retired.pdf").write_bytes(b"retired")
            paper.write_bytes(b"changed article")
            errors = builder.validate_corpus(records, papers, text)
            self.assertIn("extra PDF: retired", errors)
            self.assertIn("changed PDF: paper-a", errors)

    def test_corpus_check_rejects_missing_hash_and_extract(self) -> None:
        builder = load_builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            papers = root / "papers"
            text = root / "text"
            papers.mkdir()
            text.mkdir()
            (papers / "paper-a.pdf").write_bytes(b"article")
            errors = builder.validate_corpus(
                {"paper-a": {"stem": "paper-a"}}, papers, text
            )
            self.assertIn("missing text: paper-a", errors)
            self.assertIn("missing PDF checksum: paper-a", errors)
            self.assertEqual(
                builder.validate_corpus({}, papers, text),
                ["empty tracked corpus index", "extra PDF: paper-a"],
            )

    def test_bibliography_title_displaces_publisher_accessibility_cover(self) -> None:
        builder = load_builder()
        entry = builder.Entry(
            key="Kyle1985ContinuousAuctions",
            kind="article",
            fields={"title": "Continuous Auctions and Insider Trading"},
        )
        title, source = builder.title_for_extract(
            "1985-Kyle1985ContinuousAuctions-continuous-auctions-and-insider-trading",
            "===== PAGE 1 =====\nAccessibility support:\nContinuous Auctions and Insider Trading",
            {entry.key: entry},
        )
        self.assertEqual(title, "Continuous Auctions and Insider Trading")
        self.assertEqual(source, "bibliography")

    def test_unmatched_companion_keeps_extracted_title(self) -> None:
        builder = load_builder()
        title, source = builder.title_for_extract(
            "unregistered-companion",
            "===== PAGE 1 =====\nOnline appendix with identifying title",
            {},
        )
        self.assertEqual(title, "Online appendix with identifying title")
        self.assertEqual(source, "extract")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ddvc.venue_corpus import JFE_VENUE_SOURCE_KEYS, resolve_venue_corpus


class VenueCorpusTest(unittest.TestCase):
    def test_conformance_consumers_do_not_depend_on_retired_scratch_corpus(self) -> None:
        root = Path(__file__).resolve().parents[1]
        consumers = (
            "scripts/measure_prose_conventions.py",
            "scripts/find_prose_outliers.py",
            "scripts/measure_venue_optics.py",
            "scripts/measure_venue_shape.py",
            "scripts/check_replacement_headroom.py",
        )
        for relative in consumers:
            text = (root / relative).read_text()
            self.assertNotIn("defi-dominant-currency", text, relative)
            self.assertNotIn("jfe-exemplars", text, relative)

    def test_resolver_uses_source_set_identity_and_primary_checkout_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            primary = root / "primary"
            registry = root / "pdf-sources.json"
            source_sets = {}
            expected = []
            for index, source_key in enumerate(JFE_VENUE_SOURCE_KEYS.values()):
                stem = f"published-{source_key}"
                source_sets[source_key] = {
                    "checks": {"article": f"literature/text/{stem}.txt"}
                }
                owner = worktree if index == 0 else primary
                pdf = owner / "literature" / "papers" / f"{stem}.pdf"
                pdf.parent.mkdir(parents=True, exist_ok=True)
                pdf.write_bytes(b"%PDF-1.4")
                expected.append(pdf.resolve())
            registry.write_text(json.dumps({"source_sets": source_sets}))
            corpus = resolve_venue_corpus(
                repo_root=worktree,
                primary_root=primary,
                source_registry=registry,
            )
            self.assertEqual(corpus.pdfs, tuple(expected))
            self.assertEqual(corpus.missing, ())

    def test_resolver_reports_missing_source_records_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keys = list(JFE_VENUE_SOURCE_KEYS.values())
            registry = root / "pdf-sources.json"
            registry.write_text(
                json.dumps(
                    {
                        "source_sets": {
                            keys[0]: {
                                "checks": {
                                    "article": "literature/text/published-but-absent.txt"
                                }
                            }
                        }
                    }
                )
            )
            corpus = resolve_venue_corpus(
                repo_root=root / "worktree",
                primary_root=root / "primary",
                source_registry=registry,
            )
            self.assertEqual(corpus.pdfs, ())
            self.assertEqual(set(corpus.missing), set(keys))

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


def load_audit():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "audit_state_coverage_materiality.py"
    )
    spec = importlib.util.spec_from_file_location(
        "audit_state_coverage_materiality", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StateCoverageMaterialityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = load_audit()

    def test_tuple_rejects_null_and_blank_sources(self) -> None:
        self.assertEqual(
            self.audit._tuple([None, pd.NA, "", "  ", "curve", "curve"]),
            ("curve",),
        )

    def test_state_gaps_include_missing_failed_and_zero_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quality.parquet"
            pd.DataFrame(
                [
                    {
                        "venue": "curve",
                        "day": "20200101",
                        "usable_rows": 1,
                        "passed": True,
                        "engine": "e1",
                    },
                    {
                        "venue": "curve",
                        "day": "20200102",
                        "usable_rows": 3,
                        "passed": False,
                        "engine": "e1",
                    },
                    {
                        "venue": "balancer",
                        "day": "20200101",
                        "usable_rows": 0,
                        "passed": True,
                        "engine": "e1",
                    },
                    {
                        "venue": "balancer",
                        "day": "20200102",
                        "usable_rows": 2,
                        "passed": True,
                        "engine": "e1",
                    },
                    {
                        "venue": "balancer",
                        "day": "20200103",
                        "usable_rows": 4,
                        "passed": True,
                        "engine": "e1",
                    },
                ]
            ).to_parquet(path, index=False)
            gaps, evidence = self.audit.state_gap_calendar(
                path, frozenset({"20200101", "20200102", "20200103"})
            )
            self.assertEqual(gaps["curve"], {"20200102", "20200103"})
            self.assertEqual(gaps["balancer"], {"20200101"})
            self.assertEqual(
                evidence["gap_reasons"]["curve"],
                {"missing_quality_row": 1, "not_passed": 1},
            )
            self.assertEqual(
                evidence["gap_reasons"]["balancer"], {"no_usable_rows": 1}
            )

    def test_state_gap_calendar_rejects_duplicate_venue_days(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quality.parquet"
            pd.DataFrame(
                [
                    {
                        "venue": source,
                        "day": "20200101",
                        "usable_rows": 1,
                        "passed": True,
                        "engine": "e1",
                    }
                    for source in ("curve", "curve", "balancer")
                ]
            ).to_parquet(path, index=False)
            with self.assertRaisesRegex(ValueError, "duplicate venue-day"):
                self.audit.state_gap_calendar(path, frozenset({"20200101"}))

    def test_year_stress_aggregation_keeps_scope_key(self) -> None:
        cell = {
            "components": 1,
            "notional_usd": 2.0,
            "strict_components": 1,
            "strict_notional_usd": 2.0,
        }
        rows = self.audit.year_stress_cells(
            [
                {
                    "year": 2024,
                    "stress": False,
                    "cells": [
                        {"scope": "all", **cell},
                        {"scope": "curve", **cell},
                    ],
                },
                {
                    "year": 2024,
                    "stress": False,
                    "cells": [{"scope": "all", **cell}],
                },
            ]
        )
        indexed = {row["scope"]: row for row in rows}
        self.assertEqual(indexed["all"]["components"], 2.0)
        self.assertEqual(indexed["curve"]["components"], 1.0)

    def test_pool_input_downgrades_mutated_marker_to_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "raw" / "thegraph" / "curve"
            directory.mkdir(parents=True)
            raw = directory / "curve_swaps_20200101.jsonl.gz"
            line = json.dumps(
                {
                    "hash": "0xabc",
                    "logIndex": 1,
                    "pool": {"id": "0xpool"},
                },
                sort_keys=True,
                separators=(",", ":"),
            ) + "\n"
            with gzip.open(raw, "wt") as handle:
                handle.write(line)
            marker = directory / "curve_meta_20200101.json"
            marker.write_text(
                json.dumps(
                    {
                        "source": "curve",
                        "day": "2020-01-01",
                        "streams": {
                            "swaps": {
                                "logical_content_sha256": hashlib.sha256(
                                    line.encode()
                                ).hexdigest()
                            }
                        },
                    }
                )
            )
            _mapping, _digest, binding = self.audit.raw_pool_map(
                root, "curve", "20200101"
            )
            self.assertEqual(binding["status"], "committed_source_day")
            with gzip.open(raw, "wt") as handle:
                handle.write(line.replace("0xpool", "0xchanged"))
            _mapping, _digest, binding = self.audit.raw_pool_map(
                root, "curve", "20200101"
            )
            self.assertEqual(binding["status"], "diagnostic_unreleased")

    def test_pool_allocation_preserves_component_totals(self) -> None:
        legs = pd.DataFrame(
            [
                {"tx_hash": "a", "component_id": 1, "pool": "p1"},
                {"tx_hash": "a", "component_id": 1, "pool": "p2"},
                {"tx_hash": "b", "component_id": 2, "pool": "p1"},
            ]
        )
        components = pd.DataFrame(
            [
                {
                    "tx_hash": "a",
                    "component_id": 1,
                    "component_notional_usd": 100.0,
                    "within_20pct": True,
                },
                {
                    "tx_hash": "b",
                    "component_id": 2,
                    "component_notional_usd": 40.0,
                    "within_20pct": False,
                },
            ]
        )
        cells = self.audit.allocate_pool_cells(legs, components, source="curve")
        self.assertAlmostEqual(
            sum(row["component_count_allocation"] for row in cells), 2.0
        )
        self.assertAlmostEqual(
            sum(row["notional_usd_allocation"] for row in cells), 140.0
        )
        self.assertAlmostEqual(
            sum(row["strict_component_count_allocation"] for row in cells), 1.0
        )
        self.assertAlmostEqual(
            sum(row["strict_notional_usd_allocation"] for row in cells), 100.0
        )


if __name__ == "__main__":
    unittest.main()

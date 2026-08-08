from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.reconstruct import (
    DEX_FAMILY,
    RECONSTRUCT_CODE_SOURCES,
    ROUTE_SEMANTIC_FUNCTIONS,
    _available_days,
    _process_one,
    active_route_sources,
    read_unified_quality,
    route_input_paths,
)


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


def write_v2_swap(data_root: Path, day: str, *, amount_in: str = "100") -> Path:
    path = route_input_paths(day, ["uniswap_v2"], data_root=data_root)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "id": "swap",
        "transaction": {"id": "0xtx", "blockNumber": "10008566", "timestamp": "1588636801"},
        "timestamp": "1588636801",
        "logIndex": "7",
        "amount0In": amount_in,
        "amount0Out": "0",
        "amount1In": "0",
        "amount1Out": "0.05",
        "amountUSD": amount_in,
        "pair": {
            "id": "0xpool",
            "token0": {"id": USDC, "symbol": "USDC"},
            "token1": {"id": WETH, "symbol": "WETH"},
        },
    }
    with gzip.open(path, "wt") as handle:
        handle.write(json.dumps(row) + "\n")
    return path


class ReconstructGateTests(unittest.TestCase):
    def test_route_engine_tracks_source_genesis_but_not_fetch_orchestration(self) -> None:
        self.assertIn("src/ddvc/fetch/sources.py", RECONSTRUCT_CODE_SOURCES)
        self.assertIn("src/ddvc/source_records.py", RECONSTRUCT_CODE_SOURCES)
        self.assertNotIn("src/ddvc/fetch/raw.py", RECONSTRUCT_CODE_SOURCES)
        self.assertNotIn("run", {function.__name__ for function in ROUTE_SEMANTIC_FUNCTIONS})

    def test_full_route_calendar_is_independent_of_observed_files(self) -> None:
        days = _available_days(list(DEX_FAMILY))
        self.assertEqual((days[0], days[-1], len(days)), ("2020-02-11", "2026-06-30", 2332))
        self.assertEqual(
            sum(len(active_route_sources(day, list(DEX_FAMILY))) for day in days),
            12802,
        )

    def test_missing_launched_source_fails_instead_of_shrinking_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            quality, status = _process_one(
                "2020-05-05",
                ["uniswap_v2"],
                True,
                base / "data",
                base / "unified",
            )
        self.assertEqual(status, "failed")
        self.assertFalse(quality["passed"])
        self.assertEqual(quality["missing_sources"], 1)

    def test_route_day_is_current_only_against_exact_raw_inputs_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data_root, unified_root = base / "data", base / "unified"
            raw = write_v2_swap(data_root, "2020-05-05")
            quality, status = _process_one(
                "2020-05-05",
                ["uniswap_v2"],
                True,
                data_root,
                unified_root,
            )
            self.assertEqual(status, "written")
            self.assertTrue(quality["passed"])
            self.assertEqual(quality["raw_rows"], 1)
            self.assertEqual(quality["output_rows"], 1)
            self.assertIsNotNone(
                read_unified_quality(
                    "2020-05-05",
                    ["uniswap_v2"],
                    data_root=data_root,
                    unified_root=unified_root,
                )
            )
            frame = pd.read_parquet(unified_root / "20200505.parquet")
            self.assertEqual(frame.loc[0, "amount_in"], 100.0)
            write_v2_swap(data_root, "2020-05-05", amount_in="101")
            self.assertIsNone(
                read_unified_quality(
                    "2020-05-05",
                    ["uniswap_v2"],
                    data_root=data_root,
                    unified_root=unified_root,
                )
            )
            raw.unlink()

    def test_empty_but_present_day_materialises_a_typed_empty_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data_root, unified_root = base / "data", base / "unified"
            raw = route_input_paths("2020-05-05", ["uniswap_v2"], data_root=data_root)[0]
            raw.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(raw, "wt"):
                pass
            quality, status = _process_one(
                "2020-05-05",
                ["uniswap_v2"],
                True,
                data_root,
                unified_root,
            )
            frame = pd.read_parquet(unified_root / "20200505.parquet")
        self.assertEqual(status, "written")
        self.assertTrue(quality["passed"])
        self.assertEqual(len(frame), 0)
        self.assertIn("tx_hash", frame.columns)


if __name__ == "__main__":
    unittest.main()

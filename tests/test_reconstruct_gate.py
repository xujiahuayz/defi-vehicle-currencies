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
    _available_days,
    _process_one,
    active_route_sources,
    preflight_route_input_perimeter,
    read_unified_quality,
    route_input_paths,
)


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


def write_v2_swap(data_root: Path, amount_in: str = "100") -> Path:
    day = "2020-05-05"
    path = route_input_paths(day, ["uniswap_v2"], data_root=data_root)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "id": "swap",
        "transaction": {
            "id": "0xtx",
            "blockNumber": "10008566",
            "timestamp": "1588636801",
        },
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
    marker = path.with_name("uniswap_v2_meta_20200505.json")
    marker.write_text(
        json.dumps(
            {
                "source": "uniswap_v2",
                "day": day,
                "streams": {
                    "swaps": {
                        "path": f"uniswap_v2/{path.name}",
                        "rows": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


class ReconstructGateTests(unittest.TestCase):
    def test_route_engine_tracks_source_semantics_not_fetch_orchestration(self) -> None:
        self.assertIn("src/ddvc/fetch/sources.py", RECONSTRUCT_CODE_SOURCES)
        self.assertIn("src/ddvc/source_records.py", RECONSTRUCT_CODE_SOURCES)
        self.assertNotIn("src/ddvc/fetch/raw.py", RECONSTRUCT_CODE_SOURCES)

    def test_full_route_calendar_is_independent_of_observed_files(self) -> None:
        days = _available_days(list(DEX_FAMILY))
        self.assertEqual((days[0], days[-1], len(days)), ("2020-02-11", "2026-06-30", 2332))
        self.assertEqual(
            sum(len(active_route_sources(day, list(DEX_FAMILY))) for day in days),
            12802,
        )

    def test_raw_preflight_fails_before_output_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            marker = base / "unified" / ".quality" / "20200505.json"
            marker.parent.mkdir(parents=True)
            marker.write_text('{"sentinel": true}\n', encoding="utf-8")
            before = marker.read_bytes()
            with self.assertRaisesRegex(FileNotFoundError, "raw preflight failed"):
                preflight_route_input_perimeter(
                    ["2020-05-05"], ["uniswap_v2"], data_root=base / "data"
                )
            self.assertEqual(marker.read_bytes(), before)

    def test_route_day_rebuilds_when_direct_raw_inputs_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data_root, unified_root = base / "data", base / "unified"
            write_v2_swap(data_root)
            quality, status = _process_one(
                "2020-05-05", ["uniswap_v2"], True, data_root, unified_root
            )
            self.assertEqual(status, "written")
            self.assertTrue(quality["passed"])
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
            write_v2_swap(data_root, amount_in="101")
            self.assertIsNone(
                read_unified_quality(
                    "2020-05-05",
                    ["uniswap_v2"],
                    data_root=data_root,
                    unified_root=unified_root,
                )
            )


if __name__ == "__main__":
    unittest.main()

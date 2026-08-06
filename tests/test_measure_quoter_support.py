from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts import measure_quoter_support


class MeasureQuoterSupportTests(unittest.TestCase):
    def test_reported_support_contract_matches_quote_engine(self) -> None:
        self.assertEqual(measure_quoter_support.MAX_INPUT_TO_RESERVE, 0.05)
        self.assertEqual(measure_quoter_support.SUPPORT_QUANTILE, 0.95)

    def test_v4_support_reports_swap_and_value_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "uniswap_v4_swaps_20250124.jsonl.gz"

            def row(fee: int, volume: int) -> dict:
                return {
                    "amountUSD": str(volume),
                    "pool": {
                        "feeTier": fee,
                        "tickSpacing": 10,
                        "hooks": "0x0000000000000000000000000000000000000000",
                        "token0": {"decimals": "18"},
                        "token1": {"decimals": "6"},
                    },
                }

            with gzip.open(path, "wt") as fh:
                for record in (row(500, 100), row(1 << 23, 50)):
                    fh.write(json.dumps(record) + "\n")
            original = measure_quoter_support.V4_RAW
            measure_quoter_support.V4_RAW = root
            try:
                support = measure_quoter_support.measure_v4_support()
            finally:
                measure_quoter_support.V4_RAW = original

        vanilla = support[(support["year"] == "ALL") & support["supported"]].iloc[0]
        self.assertEqual(vanilla["swap_share"], 0.5)
        self.assertAlmostEqual(vanilla["volume_share"], 2 / 3)

    def test_v4_writer_refuses_incomplete_statics(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "year": "ALL",
                    "status": "incomplete_statics",
                    "supported": False,
                    "swaps": 1,
                    "swap_share": 1.0,
                    "volume_usd": 1.0,
                    "volume_share": 1.0,
                }
            ]
        )
        original = measure_quoter_support.measure_v4_support
        measure_quoter_support.measure_v4_support = lambda: frame
        try:
            with self.assertRaisesRegex(RuntimeError, "unusable statics"):
                measure_quoter_support.write_v4_support()
        finally:
            measure_quoter_support.measure_v4_support = original


if __name__ == "__main__":
    unittest.main()

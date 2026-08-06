from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts import measure_quoter_support


class MeasureQuoterSupportTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

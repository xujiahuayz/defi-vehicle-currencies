from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.process.build_v4_candidate_linked_pool_tvl_daily import (
    NATIVE_ETH_ADDRESS,
    TVL_USD_UPPER_BOUND,
    WETH_ADDRESS,
    build_candidate_linked_tvl,
)


USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
DAI_ADDRESS = "0x6b175474e89094c44da98b954eedeac495271d0f"


def write_jsonl_gz(path: Path, rows: list[dict[str, object]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def pool(pool_id: str, token0: dict[str, str], token1: dict[str, str]) -> dict[str, object]:
    return {"id": pool_id, "token0": token0, "token1": token1}


class V4CandidateLinkedPoolTvlDailyTest(unittest.TestCase):
    def test_event_identity_resolves_symbol_only_daily_tvl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path = root / "candidates.parquet"
            pd.DataFrame(
                [
                    {"candidate_address": WETH_ADDRESS, "candidate_symbol": "WETH"},
                    {"candidate_address": USDC_ADDRESS, "candidate_symbol": "USDC"},
                ]
            ).to_parquet(candidate_path, index=False)

            write_jsonl_gz(
                root / "uniswap_v4_daily_20250101.jsonl.gz",
                [
                    {
                        "id": "p1",
                        "pool": pool(
                            "p1",
                            {"symbol": "ETH"},
                            {"symbol": "USDC"},
                        ),
                        "tvlUSD": "1000",
                        "volumeUSD": "25",
                    },
                    {
                        "id": "p2",
                        "pool": pool(
                            "p2",
                            {"symbol": "ETH"},
                            {"symbol": "USDC"},
                        ),
                        "tvlUSD": "2000",
                        "volumeUSD": "50",
                    },
                    {
                        "id": "p3",
                        "pool": pool(
                            "p3",
                            {"symbol": "ETH"},
                            {"symbol": "USDC"},
                        ),
                        "tvlUSD": str(TVL_USD_UPPER_BOUND + 1),
                        "volumeUSD": "75",
                    },
                ],
            )
            write_jsonl_gz(
                root / "uniswap_v4_modify_liquidities_20250101.jsonl.gz",
                [
                    {
                        "id": "m1",
                        "pool": pool(
                            "p1",
                            {"id": NATIVE_ETH_ADDRESS, "symbol": "ETH", "decimals": "18"},
                            {"id": USDC_ADDRESS, "symbol": "USDC", "decimals": "6"},
                        ),
                    },
                    {
                        "id": "m2",
                        "pool": pool(
                            "p3",
                            {"id": NATIVE_ETH_ADDRESS, "symbol": "ETH", "decimals": "18"},
                            {"id": USDC_ADDRESS, "symbol": "USDC", "decimals": "6"},
                        ),
                    },
                ],
            )
            write_jsonl_gz(
                root / "uniswap_v4_swaps_20250101.jsonl.gz",
                [
                    {
                        "id": "s1",
                        "pool": pool(
                            "p2",
                            {"id": NATIVE_ETH_ADDRESS, "symbol": "ETH", "decimals": "18"},
                            {"id": USDC_ADDRESS, "symbol": "USDC", "decimals": "6"},
                        ),
                    },
                    {
                        "id": "s2",
                        "pool": pool(
                            "p2",
                            {"id": NATIVE_ETH_ADDRESS, "symbol": "ETH", "decimals": "18"},
                            {"id": DAI_ADDRESS, "symbol": "DAI", "decimals": "18"},
                        ),
                    },
                ],
            )

            panel, support = build_candidate_linked_tvl(
                event_dir=root,
                candidate_day_path=candidate_path,
            )

            valid = panel[panel["capital_valid"]]
            self.assertEqual(set(valid["candidate_symbol"]), {"USDC", "WETH"})
            self.assertEqual(set(valid["pool"]), {"p1"})
            self.assertTrue(
                (valid["capital_measurement_status"] == "screen_pass_event_address_resolved").all()
            )
            self.assertTrue((valid["candidate_linked_pool_tvl_usd"] == 1000.0).all())

            invalid = panel[~panel["capital_valid"]]
            self.assertIn("unsupported_identity_conflict", set(invalid["capital_measurement_status"]))
            self.assertIn(
                "screen_fail_tvl_above_physical_bound",
                set(invalid["capital_measurement_status"]),
            )
            self.assertEqual(support["raw_daily_rows"], 3)
            self.assertEqual(support["valid_candidate_linked_rows"], 2)
            self.assertEqual(
                support["event_identity"]["event_identity_conflicted_pools"],
                1,
            )


if __name__ == "__main__":
    unittest.main()

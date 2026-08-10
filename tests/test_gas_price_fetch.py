from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from ddvc.gas import load_daily_gas_prices
from ddvc.release_calendar import released_route_days
import scripts.process.fetch_daily_gas_price_graph as gas_fetch


class DailyGasPriceFetchTests(unittest.TestCase):
    @staticmethod
    def calendar_bounds(start_block: int, end_block: int) -> dict[str, int]:
        return {
            "start_timestamp": 1_600_000_000,
            "end_timestamp": 1_800_000_000,
            "start_block": start_block,
            "end_block": end_block,
        }

    @staticmethod
    def block_sample(block: int, gas_prices_wei: list[int] | None = None) -> dict:
        return {
            "block_number": block,
            "block_hash": "0x" + f"{block:064x}",
            "block_timestamp": 1_700_000_000 + block,
            "transaction_count": 2,
            "gas_prices_wei": gas_prices_wei or [1_000_000_000, 2_000_000_000],
        }

    def test_resumability_cache_stays_outside_the_data_tree(self) -> None:
        self.assertTrue(gas_fetch.CACHE.is_relative_to(gas_fetch.SHARED_RUNTIME_DIR))
        self.assertFalse(gas_fetch.CACHE.is_relative_to(gas_fetch.DATA_DIR))

    def test_gas_calendar_excludes_typed_empty_route_days(self) -> None:
        quality = pd.DataFrame(
            {
                "day": ["20200101", "20200102", "20200103"],
                "output_rows": [10, 0, 5],
                "passed": [True, True, True],
            }
        )
        with TemporaryDirectory() as temporary:
            panel = Path(temporary) / "quality.parquet"
            quality.to_parquet(panel, index=False)
            self.assertEqual(
                released_route_days(panel, nonempty=True), ["20200101", "20200103"]
            )

    def test_released_calendar_refuses_a_failed_quality_day(self) -> None:
        quality = pd.DataFrame(
            {"day": ["20200101"], "output_rows": [1], "passed": [False]}
        )
        with TemporaryDirectory() as temporary:
            panel = Path(temporary) / "quality.parquet"
            quality.to_parquet(panel, index=False)
            with self.assertRaisesRegex(RuntimeError, "1 failed day"):
                released_route_days(panel, nonempty=False)

    def test_consumer_refuses_incomplete_required_calendar(self) -> None:
        with TemporaryDirectory() as temporary:
            panel = Path(temporary) / "gas.parquet"
            pd.DataFrame(
                {"day": ["20200101"], "gas_gwei_median": [10.0]}
            ).to_parquet(panel, index=False)
            with self.assertRaisesRegex(ValueError, "misses 1 required dates"):
                load_daily_gas_prices(
                    panel,
                    required_dates=["2020-01-01", "2020-01-02"],
                )

    def test_consumer_refuses_duplicate_dates(self) -> None:
        with TemporaryDirectory() as temporary:
            panel = Path(temporary) / "gas.parquet"
            pd.DataFrame(
                {
                    "date": ["2020-01-01", "2020-01-01"],
                    "gas_gwei_median": [10.0, 11.0],
                }
            ).to_parquet(panel, index=False)
            with self.assertRaisesRegex(ValueError, "duplicate dates"):
                load_daily_gas_prices(panel)

    def test_panel_schema_does_not_depend_on_record_key_order(self) -> None:
        first = {column: index for index, column in enumerate(gas_fetch.PANEL_COLUMNS)}
        second = dict(reversed(first.items()))

        frame = gas_fetch.daily_panel_frame([first, second])

        self.assertEqual(list(frame.columns), gas_fetch.PANEL_COLUMNS)

    def test_legacy_dex_clock_cache_is_not_reused(self) -> None:
        original_cache = gas_fetch.CACHE
        with TemporaryDirectory() as temporary:
            gas_fetch.CACHE = Path(temporary)
            cached = gas_fetch.CACHE / "20210115.json"
            cached.write_text(
                json.dumps(
                    {
                        "day": "20210115",
                        "method": "block_transactions",
                        "n_blocks": 3,
                        "n_tx": 100,
                        "gas_gwei_median": 30.0,
                    }
                )
            )
            try:
                with patch.object(
                    gas_fetch,
                    "block_gas_sample",
                    side_effect=lambda block: self.block_sample(block),
                ) as fetch:
                    row = gas_fetch.fetch_day(
                        "20210115",
                        3,
                        calendar={"20210115": self.calendar_bounds(10, 14)},
                    )
            finally:
                gas_fetch.CACHE = original_cache
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(row["source"], "ethereum_block")
        self.assertEqual(row["method"], "utc_day_block_quantile_transactions")
        self.assertEqual(row["sampling_version"], gas_fetch.BLOCK_SAMPLE_VERSION)
        self.assertEqual(row["sampled_blocks"], [11, 12, 13])

    def test_block_sample_uses_only_exact_utc_bounds(self) -> None:
        self.assertEqual(gas_fetch.sample_blocks_from_bounds(10, 18, 3), [12, 14, 16])
        self.assertNotIn("calendar_source", gas_fetch.PANEL_COLUMNS)

    def test_price_summary_has_one_schema_for_both_fetch_routes(self) -> None:
        row = gas_fetch.summarise_prices(
            "20210115",
            "uniswap_v2",
            "block_transactions",
            [40.0, 10.0, 30.0, 20.0],
            n_blocks=3,
        )
        self.assertEqual(row["n_tx"], 4)
        self.assertEqual(row["n_blocks"], 3)
        self.assertEqual(row["gas_gwei_median"], 25.0)
        self.assertEqual(row["gas_gwei_p25"], 20.0)
        self.assertEqual(row["gas_gwei_p75"], 40.0)

    def test_empty_full_block_response_rotates_to_another_endpoint(self) -> None:
        responses = [
            {"result": {"transactions": []}},
            {
                "result": {
                    "number": hex(100),
                    "hash": "0x" + "1" * 64,
                    "timestamp": hex(1_700_000_000),
                    "transactions": [{"gasPrice": "0x3b9aca00"}],
                }
            },
        ]
        with patch.object(gas_fetch, "rpc_post", side_effect=responses) as request:
            sample = gas_fetch.block_gas_sample(100)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(sample["gas_prices_wei"], [1_000_000_000])

    def test_day_fetch_refuses_one_resolved_block_out_of_three(self) -> None:
        original_cache = gas_fetch.CACHE
        with TemporaryDirectory() as temporary:
            gas_fetch.CACHE = Path(temporary)
            try:
                with patch.object(
                    gas_fetch,
                    "block_gas_sample",
                    side_effect=[self.block_sample(15), None, None],
                ):
                    with self.assertRaisesRegex(RuntimeError, "only 1/3"):
                        gas_fetch.fetch_day(
                            "20250115",
                            3,
                            calendar={"20250115": self.calendar_bounds(10, 30)},
                        )
            finally:
                gas_fetch.CACHE = original_cache


if __name__ == "__main__":
    unittest.main()

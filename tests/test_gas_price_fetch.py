from __future__ import annotations

import gzip
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

    def test_legacy_valid_cache_rows_receive_their_source_identity(self) -> None:
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
                row = gas_fetch.fetch_day("20210115", 3)
            finally:
                gas_fetch.CACHE = original_cache
        self.assertEqual(row["source"], "ethereum_block")
        self.assertEqual(row["method"], "block_transactions")
        self.assertEqual(row["sampling_version"], "full_blocks_v1")

    def test_v2_block_sample_spans_the_day_without_duplicates(self) -> None:
        original_v2 = gas_fetch.RAW_V2
        original_v1 = gas_fetch.RAW_V1
        with TemporaryDirectory() as temporary:
            gas_fetch.RAW_V2 = Path(temporary)
            gas_fetch.RAW_V1 = Path(temporary) / "missing-v1"
            path = gas_fetch.RAW_V2 / "uniswap_v2_swaps_20210115.jsonl.gz"
            with gzip.open(path, "wt") as handle:
                for block in range(10, 15):
                    handle.write(
                        json.dumps({"transaction": {"blockNumber": block}}) + "\n"
                    )
            try:
                blocks, source = gas_fetch.sample_blocks_for_day("20210115", 3)
            finally:
                gas_fetch.RAW_V2 = original_v2
                gas_fetch.RAW_V1 = original_v1
        self.assertEqual(blocks, [10, 12, 14])
        self.assertEqual(source, "uniswap_v2")

    def test_post_v3_block_sample_uses_v3_calendar(self) -> None:
        original_v3 = gas_fetch.RAW_V3
        with TemporaryDirectory() as temporary:
            gas_fetch.RAW_V3 = Path(temporary)
            path = gas_fetch.RAW_V3 / "uniswap_v3_swaps_20250115.jsonl.gz"
            with gzip.open(path, "wt") as handle:
                for block in range(20, 25):
                    handle.write(
                        json.dumps({"transaction": {"blockNumber": block}}) + "\n"
                    )
            try:
                blocks, source = gas_fetch.sample_blocks_for_day("20250115", 3)
            finally:
                gas_fetch.RAW_V3 = original_v3
        self.assertEqual(blocks, [20, 22, 24])
        self.assertEqual(source, "uniswap_v3")

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
            {"result": {"transactions": [{"gasPrice": "0x3b9aca00"}]}},
        ]
        with patch.object(gas_fetch, "rpc_post", side_effect=responses) as request:
            self.assertEqual(gas_fetch.block_gas_prices(100), [1.0])
        self.assertEqual(request.call_count, 2)

    def test_day_fetch_refuses_one_resolved_block_out_of_three(self) -> None:
        original_cache = gas_fetch.CACHE
        with TemporaryDirectory() as temporary:
            gas_fetch.CACHE = Path(temporary)
            try:
                with patch.object(
                    gas_fetch,
                    "sample_blocks_for_day",
                    return_value=([10, 20, 30], "uniswap_v3"),
                ), patch.object(
                    gas_fetch,
                    "block_gas_prices",
                    side_effect=[[1.0, 2.0], [], []],
                ):
                    with self.assertRaisesRegex(RuntimeError, "only 1/3"):
                        gas_fetch.fetch_day("20250115", 3)
            finally:
                gas_fetch.CACHE = original_cache


if __name__ == "__main__":
    unittest.main()

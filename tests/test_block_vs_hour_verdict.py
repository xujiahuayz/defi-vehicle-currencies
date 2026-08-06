from __future__ import annotations

import gzip
import json
import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.analysis.block_timing import (
    PoolView,
    SwapEvent,
    V3DayState,
    load_v3_day,
    oriented_human,
    summarise_timing_conditionals,
    summarise_triangle_maturation,
)
from scripts.validate_realised_route_timing import route_timing_observation, summarise_validation
from scripts.test_block_vs_hour_verdict import _cached_day, _pick_days


class PoolViewTests(unittest.TestCase):
    def test_pre_event_lookup_is_strict_in_block_log_order(self) -> None:
        view = PoolView(
            [
                (100, 3, 1_000, 0, 1.0),
                (100, 9, 1_001, 0, 2.0),
                (101, 1, 1_002, 0, 3.0),
            ]
        )
        self.assertIsNone(view.before(100, 3))
        self.assertEqual(view.before(100, 9), 1.0)
        self.assertEqual(view.before(100, 10), 2.0)
        self.assertEqual(view.before(101, 1), 2.0)
        self.assertEqual(view.before(102, 0), 3.0)

    def test_hour_state_uses_last_observed_post_swap_state(self) -> None:
        view = PoolView(
            [
                (100, 3, 1_000, 0, 1.0),
                (100, 9, 1_001, 0, 2.0),
                (101, 1, 3_601, 1, 3.0),
            ]
        )
        self.assertEqual(view.at_hour(0), 2.0)
        self.assertEqual(view.at_hour(1), 3.0)

    def test_day_loader_indexes_transaction_order_and_token_decimals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "swaps.jsonl.gz"
            rows = []
            for log_index in (9, 3):
                rows.append(
                    {
                        "transaction": {
                            "id": "0xabc",
                            "blockNumber": "100",
                        },
                        "logIndex": str(log_index),
                        "timestamp": "3601",
                        "sqrtPriceX96": str(1 << 96),
                        "pool": {
                            "id": "0xpool",
                            "token0": {
                                "id": "0xa",
                                "decimals": "6",
                            },
                            "token1": {
                                "id": "0xb",
                                "decimals": "18",
                            },
                        },
                    }
                )
            with gzip.open(path, "wt") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            day = load_v3_day(path)
        self.assertEqual(day.transaction_first_log["0xabc"], 3)
        self.assertEqual(day.events[("0xabc", 9)].pool_id, "0xpool")
        self.assertEqual(day.decimals["0xpool"], (6, 18))
        self.assertEqual([state[1] for state in day.series["0xpool"]], [3, 9])

    def test_day_loader_deduplicates_reindexed_copy_of_same_chain_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "swaps.jsonl.gz"
            row = {
                "id": "0xabc#first",
                "transaction": {"id": "0xabc", "blockNumber": "100"},
                "logIndex": "3",
                "timestamp": "3601",
                "sqrtPriceX96": str(1 << 96),
                "amount0": "1",
                "amount1": "-1",
                "pool": {
                    "id": "0xpool",
                    "token0": {"id": "0xa", "decimals": "18"},
                    "token1": {"id": "0xb", "decimals": "18"},
                },
            }
            duplicate = {**row, "id": "0xabc#second"}
            with gzip.open(path, "wt") as handle:
                for observation in (row, duplicate):
                    handle.write(json.dumps(observation) + "\n")
            day = load_v3_day(path)

        self.assertEqual(len(day.events), 1)
        self.assertEqual(len(day.series["0xpool"]), 1)

    def test_day_loader_rejects_conflicting_duplicate_chain_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "swaps.jsonl.gz"
            row = {
                "id": "0xabc#first",
                "transaction": {"id": "0xabc", "blockNumber": "100"},
                "logIndex": "3",
                "timestamp": "3601",
                "sqrtPriceX96": str(1 << 96),
                "amount0": "1",
                "amount1": "-1",
                "pool": {
                    "id": "0xpool",
                    "token0": {"id": "0xa", "decimals": "18"},
                    "token1": {"id": "0xb", "decimals": "18"},
                },
            }
            conflict = {**row, "id": "0xabc#second", "sqrtPriceX96": str(2 << 96)}
            with gzip.open(path, "wt") as handle:
                for observation in (row, conflict):
                    handle.write(json.dumps(observation) + "\n")

            with self.assertRaisesRegex(ValueError, "conflicting V3 transaction-log event"):
                load_v3_day(path)

    def test_day_loader_resolves_missing_decimals_without_zero_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "swaps.jsonl.gz"
            row = {
                "transaction": {"id": "0xabc", "blockNumber": "100"},
                "logIndex": "3",
                "timestamp": "3601",
                "sqrtPriceX96": str(1 << 96),
                "amount0": "1",
                "amount1": "-0.000000000001",
                "pool": {
                    "id": "0xpool",
                    "token0": {"id": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"},
                    "token1": {"id": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"},
                },
            }
            with gzip.open(path, "wt") as handle:
                handle.write(json.dumps(row) + "\n")
            day = load_v3_day(path)
        self.assertEqual(day.decimals["0xpool"], (6, 18))

    def test_day_loader_prefers_consistent_explicit_decimals_over_noisy_inference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "swaps.jsonl.gz"
            row = {
                "transaction": {"id": "0xabc", "blockNumber": "100"},
                "logIndex": "3",
                "timestamp": "3601",
                "sqrtPriceX96": "13682920509911759910807789978049265",
                "amount0": "-0.000003342469470821",
                "amount1": "10",
                "pool": {
                    "id": "0xpool",
                    "token0": {
                        "id": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                        "decimals": "18",
                    },
                    "token1": {
                        "id": "0xd393064eb5d52f98f87e838303570e4e40da0bd5",
                        "decimals": "18",
                    },
                },
            }
            with gzip.open(path, "wt") as handle:
                handle.write(json.dumps(row) + "\n")
            day = load_v3_day(path)

        self.assertEqual(day.decimals["0xpool"], (18, 18))

    def test_day_loader_leaves_unresolved_decimals_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "swaps.jsonl.gz"
            row = {
                "transaction": {"id": "0xabc", "blockNumber": "100"},
                "logIndex": "3",
                "timestamp": "3601",
                "sqrtPriceX96": str(1 << 96),
                "amount0": "1",
                "amount1": "-1",
                "pool": {
                    "id": "0xpool",
                    "token0": {"id": "0x0000000000000000000000000000000000000001"},
                    "token1": {"id": "0x0000000000000000000000000000000000000002"},
                },
            }
            with gzip.open(path, "wt") as handle:
                handle.write(json.dumps(row) + "\n")
            day = load_v3_day(path)
        self.assertNotIn("0xpool", day.decimals)

    def test_human_price_orientation_applies_decimal_scale(self) -> None:
        forward = oriented_human(0.0, "a", "b", 6, 18, "a", "b")
        reverse = oriented_human(0.0, "a", "b", 6, 18, "b", "a")
        self.assertAlmostEqual(float(forward), -12 * math.log(10))
        self.assertAlmostEqual(float(reverse), 12 * math.log(10))

    def test_realised_route_uses_state_before_transaction_first_log(self) -> None:
        pool1 = "pool1"
        pool2 = "pool2"
        sequences = {
            pool1: [
                (99, 1, 3_590, 0, 0.0),
                (100, 3, 3_601, 1, math.log(0.99)),
            ],
            pool2: [
                (99, 2, 3_591, 0, 0.0),
                (100, 5, 3_601, 1, math.log(0.99)),
            ],
        }
        state = V3DayState(
            tokens={pool1: ("a", "k"), pool2: ("k", "b")},
            decimals={pool1: (18, 18), pool2: (18, 18)},
            series=sequences,
            events={
                ("0xtx", 3): SwapEvent(pool1, 100, 3),
                ("0xtx", 5): SwapEvent(pool2, 100, 5),
            },
            transaction_first_log={"0xtx": 3},
        )
        route = pd.Series(
            {
                "route_id": "0xtx:0:k",
                "tx_hash": "0xtx",
                "component_id": 0,
                "timestamp_utc": 3_601,
                "src": "a",
                "tgt": "b",
                "vehicle": "k",
                "realised_amount_in": 100.0,
                "realised_amount_out": 98.0,
            }
        )
        legs = pd.DataFrame(
            [
                {
                    "log_index": 3,
                    "token_in": "a",
                    "token_out": "k",
                    "amount_in": 100.0,
                    "amount_out": 99.0,
                },
                {
                    "log_index": 5,
                    "token_in": "k",
                    "token_out": "b",
                    "amount_in": 99.1,
                    "amount_out": 98.0,
                },
            ]
        )
        observation = route_timing_observation(
            route,
            legs,
            state,
            {pool_id: PoolView(sequence) for pool_id, sequence in sequences.items()},
        )
        self.assertIsNotNone(observation)
        assert observation is not None
        realised_rate = 0.99 * (98.0 / 99.1)
        self.assertAlmostEqual(
            float(observation["own_state_shortfall"]), 1.0 - realised_rate
        )
        self.assertAlmostEqual(
            float(observation["intermediate_conservation_gap"]), 0.1 / 99.1
        )
        self.assertAlmostEqual(
            float(observation["hour_state_shortfall"]),
            1.0 - realised_rate / (0.99 * 0.99),
        )

    def test_validation_summary_keeps_compact_day_and_pooled_rows(self) -> None:
        rows = pd.DataFrame(
            {
                "validation_day": ["20220101", "20220101", "20230101"],
                "own_state_shortfall": [0.01, 0.02, 0.03],
                "hour_state_shortfall": [-0.01, 0.01, 0.02],
                "marginal_state_shift_bps": [20.0, -40.0, 200.0],
                "intermediate_conservation_gap": [0.0, 0.001, 0.0],
            }
        )
        summary = summarise_validation(rows).set_index("validation_day")
        self.assertEqual(list(summary.index), ["all", "20220101", "20230101"])
        self.assertEqual(int(summary.loc["all", "routes"]), 3)
        self.assertAlmostEqual(
            float(summary.loc["all", "state_shift_absolute_over_30bps_share"]),
            2 / 3,
        )

    def test_triangle_maturation_recovers_within_triangle_time_trend(self) -> None:
        rows = []
        dates = pd.date_range("2000-01-01", periods=20, freq="365D")
        for triangle, intercept, missing in (("a", 4.0, set()), ("b", 5.0, {1})):
            for index, date in enumerate(dates):
                if index in missing:
                    continue
                elapsed_years = (date - dates[0]).days / 365.25
                rows.append(
                    {
                        "day": date.strftime("%Y%m%d"),
                        "src": triangle,
                        "tgt": "t",
                        "vehicle": "k",
                        "direct_pool": f"{triangle}-d",
                        "hop1_pool": f"{triangle}-1",
                        "hop2_pool": f"{triangle}-2",
                        "median_gap_bps": math.exp(intercept - 0.2 * elapsed_years),
                        "n_observations": 100,
                    }
                )
        frame = pd.DataFrame(rows)
        frame["median_gap_bps"] = frame["median_gap_bps"].astype(str)
        frame["n_observations"] = frame["n_observations"].astype(object)
        summary = summarise_triangle_maturation(frame, recurrence_thresholds=(2,))
        result = summary[
            summary["panel"].eq("recurrent_support")
            & summary["identity"].eq("economic_triangle")
        ].iloc[0]
        self.assertAlmostEqual(float(result["log_gap_time_beta"]), -0.2, places=3)
        self.assertAlmostEqual(float(result["annual_compression"]), 1 - math.exp(-0.2), places=3)
        self.assertEqual(int(result["absorbed_degrees_of_freedom"]), 1)

        short_lived = []
        for index, date in enumerate(dates[:6]):
            elapsed_years = (date - dates[0]).days / 365.25
            short_lived.append(
                {
                    "day": date.strftime("%Y%m%d"),
                    "src": "c",
                    "tgt": "t",
                    "vehicle": "k",
                    "direct_pool": "c-d",
                    "hop1_pool": "c-1",
                    "hop2_pool": "c-2",
                    "median_gap_bps": math.exp(6.0 - 0.2 * elapsed_years),
                    "n_observations": 100,
                }
            )
        extended = summarise_triangle_maturation(
            pd.DataFrame([*rows, *short_lived]), recurrence_thresholds=(2,)
        )
        recurrent = extended[
            extended["panel"].eq("recurrent_support")
            & extended["identity"].eq("economic_triangle")
        ].iloc[0]
        balanced = extended[
            extended["panel"].eq("horizon_balanced")
            & extended["identity"].eq("economic_triangle")
        ].iloc[0]
        self.assertEqual(int(recurrent["triangles"]), 3)
        self.assertEqual(int(balanced["triangles"]), 2)

    def test_timing_conditionals_stream_daily_frames(self) -> None:
        first = pd.DataFrame(
            {
                "m_own_bps": [1.0] * 30,
                "m_hr_bps": [-1.0] * 30,
                "secs_to_boundary": [30] * 30,
            }
        )
        second = pd.DataFrame(
            {
                "m_own_bps": [1.0] * 30,
                "m_hr_bps": [2.0] * 30,
                "secs_to_boundary": [30] * 30,
            }
        )
        summary = summarise_timing_conditionals(iter((first, second))).set_index(
            ["cut", "bucket"]
        )
        self.assertEqual(int(summary.loc[("pooled", "all"), "observations"]), 60)
        self.assertAlmostEqual(float(summary.loc[("pooled", "all"), "value"]), 0.5)
        self.assertAlmostEqual(
            float(summary.loc[("gap_at_own_event", "under 5 bps"), "value"]),
            0.5,
        )

    def test_even_day_selection_includes_both_sample_endpoints(self) -> None:
        days = [f"202001{day:02d}" for day in range(1, 11)]
        picked = _pick_days(days, 4)
        self.assertEqual(len(picked), 4)
        self.assertEqual(picked[0], days[0])
        self.assertEqual(picked[-1], days[-1])

    def test_daily_cache_requires_a_consistent_completion_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            day = "20200101"
            pd.DataFrame({"n_observations": [2]}).to_parquet(
                cache / f"{day}.triangles.parquet", index=False
            )
            pd.DataFrame({"m_own_bps": [1.0, 2.0]}).to_parquet(
                cache / f"{day}.observations.parquet", index=False
            )
            marker = cache / f"{day}.complete.json"
            marker.write_text(
                json.dumps({"day": day, "triangles": 1, "observations": 2}),
                encoding="utf-8",
            )
            self.assertIsNotNone(_cached_day(cache, day))
            marker.unlink()
            self.assertIsNone(_cached_day(cache, day))


if __name__ == "__main__":
    unittest.main()

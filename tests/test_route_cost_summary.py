from __future__ import annotations

import importlib.util
import math
import sys
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from ddvc.route_cost_summary import summarize_route_cost_panel, write_route_cost_summary


@lru_cache(maxsize=1)
def _claim_defense_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_claim_defense_analytics.py"
    spec = importlib.util.spec_from_file_location("run_claim_defense_analytics_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _legacy_route_cost_decomposition(frame: pd.DataFrame) -> pd.DataFrame:
    module = _claim_defense_module()
    data = frame[frame["vehicle_sym"].eq("WETH")].copy()
    data["direct_quality"] = data["direct_output_usd"] / data["trade_size_usd"]
    rows = []
    for size, group in data.groupby("trade_size_usd"):
        both = group[group["direct_available"] & group["vehicle_available"] & group["direct_cost_advantage"].notna()].copy()
        thin = both[both["direct_quality"].lt(0.90)]
        high = both[both["direct_quality"].ge(0.90)]
        no_direct = group[(~group["direct_available"]) & group["vehicle_available"]]
        pair_days = both.assign(pair_day=both["date"].astype(str) + "|" + both["src"].astype(str) + "|" + both["tgt"].astype(str)).groupby("pair_day", as_index=False)["direct_cost_advantage"].mean()
        advantages = pair_days["direct_cost_advantage"].clip(-10, 10).to_numpy(float)
        t_statistic, p_value = stats.ttest_1samp(advantages, 0.0) if len(advantages) > 2 else (math.nan, math.nan)
        rows.append({
            "Trade size": f"${int(size):,}",
            "Rows": module._int(len(group)),
            "Direct available (%)": module._pct(group["direct_available"].mean()),
            "WETH route available (%)": module._pct(group["vehicle_available"].mean()),
            "No-direct, WETH-available rows": module._int(len(no_direct)),
            "Common-support rows": module._int(len(both)),
            "Median common-support direct cost advantage (fraction)": module._num(both["direct_cost_advantage"].median(), 4),
            "Median thin-direct direct cost advantage (fraction)": module._num(thin["direct_cost_advantage"].median(), 4),
            "Median high-quality-direct cost advantage (fraction)": module._num(high["direct_cost_advantage"].median(), 4),
            "Pair-day t": module._num(t_statistic, 2),
            "p": module._p(p_value),
        })
    return pd.DataFrame(rows)


class RouteCostSummaryTests(unittest.TestCase):
    def test_out_of_core_summary_matches_prespecified_group_statistics(self) -> None:
        frame = pd.DataFrame(
            {
                "vehicle_sym": ["USDC"] * 5 + ["DAI"],
                "trade_size_usd": [1_000.0] * 6,
                "vehicle_available": [True, True, True, False, True, False],
                "direct_available": [True, True, False, True, True, True],
                "direct_cost_advantage": [-0.1, 0.2, math.nan, 0.5, 20.0, 0.1],
                "realized_bridge_volume_usd": [10.0, 20.0, 30.0, 40.0, math.nan, 50.0],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            panel = Path(temporary) / "panel.parquet"
            output = Path(temporary) / "summary.pkl"
            frame.to_parquet(panel, index=False)
            summary = write_route_cost_summary(panel, output)
            self.assertTrue(output.exists())
            pd.testing.assert_frame_equal(summary, summarize_route_cost_panel(panel))
        usdc = summary.loc[summary["vehicle"].eq("USDC")].iloc[0]
        self.assertEqual(int(usdc["rows"]), 5)
        self.assertAlmostEqual(float(usdc["vehicle_available_share"]), 0.8)
        self.assertAlmostEqual(float(usdc["direct_available_share"]), 0.8)
        self.assertEqual(int(usdc["both_available_rows"]), 3)
        self.assertAlmostEqual(float(usdc["vehicle_beats_direct_share"]), 1 / 3)
        self.assertAlmostEqual(float(usdc["direct_cost_advantage_median"]), 0.2)
        self.assertAlmostEqual(float(usdc["direct_cost_advantage_p25"]), 0.05)
        self.assertAlmostEqual(float(usdc["direct_cost_advantage_p75"]), 10.1)
        self.assertAlmostEqual(float(usdc["direct_cost_advantage_winsor_mean"]), 10.1 / 3)
        self.assertEqual(int(usdc["no_direct_vehicle_available_rows"]), 1)
        self.assertAlmostEqual(float(usdc["covered_realized_volume_usd"]), 60.0)
        expected_t, expected_p = stats.ttest_1samp([-0.1, 0.2, 10.0], 0.0)
        self.assertAlmostEqual(float(usdc["t_winsor_mean"]), float(expected_t))
        self.assertAlmostEqual(float(usdc["p_winsor_mean"]), float(expected_p))

    def test_claim_defense_out_of_core_path_matches_legacy_estimator(self) -> None:
        frame = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-04", "2024-01-05", "2024-01-01"]),
            "src": ["a", "a", "a", "a", "c", "c", "c", "a"],
            "tgt": ["b", "b", "b", "b", "d", "d", "d", "b"],
            "vehicle_sym": ["WETH", "WETH", "WETH", "WETH", "WETH", "WETH", "WETH", "USDC"],
            "trade_size_usd": [1_000.0, 1_000.0, 1_000.0, 1_000.0, 10_000.0, 10_000.0, 10_000.0, 1_000.0],
            "direct_output_usd": [950.0, 850.0, 800.0, 920.0, 9_500.0, 8_000.0, 9_900.0, 990.0],
            "direct_available": [True, True, True, False, True, True, True, True],
            "vehicle_available": [True, True, True, True, True, True, True, True],
            "direct_cost_advantage": [0.2, 0.4, -20.0, math.nan, -0.1, 0.3, 0.8, 99.0],
        })
        expected = _legacy_route_cost_decomposition(frame)
        with tempfile.TemporaryDirectory() as temporary:
            panel = Path(temporary) / "panel.parquet"
            frame.to_parquet(panel, index=False)
            actual = _claim_defense_module().route_cost_decomposition(panel, write_outputs=False)
        diagnostic_columns = ["Nonfinite quote rows", "Impossible quote rows"]
        pd.testing.assert_frame_equal(actual.drop(columns=diagnostic_columns), expected)
        self.assertTrue(actual[diagnostic_columns].eq("0").all().all())

    def test_claim_defense_scan_pushes_weth_filter_and_projection_into_parquet(self) -> None:
        frame = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "src": ["a"],
            "tgt": ["b"],
            "vehicle_sym": ["WETH"],
            "trade_size_usd": [1_000.0],
            "direct_output_usd": [990.0],
            "direct_available": [True],
            "vehicle_available": [True],
            "direct_cost_advantage": [0.01],
            "irrelevant_payload": ["must not be projected"],
        })
        with tempfile.TemporaryDirectory() as temporary:
            panel = Path(temporary) / "panel.parquet"
            frame.to_parquet(panel, index=False)
            connection = duckdb.connect()
            try:
                plan = connection.execute("EXPLAIN " + _claim_defense_module().ROUTE_COST_DECOMPOSITION_QUERY, [str(panel)]).fetchone()[1]
            finally:
                connection.close()
        self.assertGreaterEqual(plan.count("READ_PARQUET"), 2)
        self.assertEqual(plan.count("vehicle_sym='WETH'"), 2)
        self.assertNotIn("irrelevant_payload", plan)
        self.assertIn("HASH_GROUP_BY", plan)

    def test_claim_defense_reports_nonfinite_and_impossible_quotes_without_reclassification(self) -> None:
        frame = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "src": ["a", "a", "a"],
            "tgt": ["b", "b", "b"],
            "vehicle_sym": ["WETH", "WETH", "WETH"],
            "trade_size_usd": [1_000.0, 1_000.0, 1_000.0],
            "direct_output_usd": [math.inf, -1.0, 990.0],
            "direct_available": [False, True, True],
            "vehicle_available": [True, False, True],
            "direct_cost_advantage": [math.inf, 0.2, 0.1],
        })
        with tempfile.TemporaryDirectory() as temporary:
            panel = Path(temporary) / "panel.parquet"
            frame.to_parquet(panel, index=False)
            result = _claim_defense_module().route_cost_decomposition(panel, write_outputs=False).iloc[0]
        self.assertEqual(result["Nonfinite quote rows"], "1")
        self.assertEqual(result["Impossible quote rows"], "1")
        self.assertEqual(result["Common-support rows"], "1")

    def test_claim_defense_excludes_duckdb_parquet_nan_from_estimators_and_quality_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            panel = Path(temporary) / "panel.parquet"
            connection = duckdb.connect()
            try:
                connection.execute(
                    """
                    COPY (
                        SELECT * FROM (VALUES
                            (DATE '2024-01-01', 'a', 'b', 'WETH', 1000.0, 940.0, true, true, CAST('NaN' AS DOUBLE)),
                            (DATE '2024-01-02', 'a', 'b', 'WETH', 1000.0, CAST('NaN' AS DOUBLE), true, true, 0.4),
                            (DATE '2024-01-03', 'a', 'b', 'WETH', 1000.0, 950.0, true, true, 0.1),
                            (DATE '2024-01-04', 'a', 'b', 'WETH', 1000.0, 850.0, true, true, 0.2),
                            (DATE '2024-01-05', 'a', 'b', 'WETH', 1000.0, 920.0, true, true, 0.3),
                            (DATE '2024-01-06', 'a', 'b', 'WETH', 1000.0, 930.0, true, true, CAST('Infinity' AS DOUBLE))
                        ) AS rows(date, src, tgt, vehicle_sym, trade_size_usd, direct_output_usd, direct_available, vehicle_available, direct_cost_advantage)
                    ) TO ? (FORMAT PARQUET)
                    """,
                    [str(panel)],
                )
            finally:
                connection.close()
            result = _claim_defense_module().route_cost_decomposition(
                panel, write_outputs=False
            ).iloc[0]
        self.assertEqual(result["Common-support rows"], "4")
        self.assertEqual(
            result["Median common-support direct cost advantage (fraction)"], "0.2500"
        )
        self.assertEqual(
            result["Median thin-direct direct cost advantage (fraction)"], "0.2000"
        )
        self.assertEqual(
            result["Median high-quality-direct cost advantage (fraction)"], "0.2000"
        )
        self.assertEqual(result["Nonfinite quote rows"], "3")

    def test_claim_defense_rejects_invalid_trade_size_before_formatting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            panel = Path(temporary) / "panel.parquet"
            connection = duckdb.connect()
            try:
                connection.execute(
                    """
                    COPY (
                        SELECT * FROM (VALUES
                            (DATE '2024-01-01', 'a', 'b', 'WETH', CAST(NULL AS DOUBLE), 990.0, true, true, 0.1),
                            (DATE '2024-01-02', 'a', 'b', 'WETH', CAST('NaN' AS DOUBLE), 990.0, true, true, 0.1),
                            (DATE '2024-01-03', 'a', 'b', 'WETH', CAST('Infinity' AS DOUBLE), 990.0, true, true, 0.1),
                            (DATE '2024-01-04', 'a', 'b', 'WETH', 0.0, 990.0, true, true, 0.1)
                        ) AS rows(date, src, tgt, vehicle_sym, trade_size_usd, direct_output_usd, direct_available, vehicle_available, direct_cost_advantage)
                    ) TO ? (FORMAT PARQUET)
                    """,
                    [str(panel)],
                )
            finally:
                connection.close()
            with self.assertRaisesRegex(
                ValueError, r"invalid rows: null=1, nonfinite=2, nonpositive=1"
            ):
                _claim_defense_module().route_cost_decomposition(
                    panel, write_outputs=False
                )

    def test_claim_defense_defines_constant_pair_day_ttests(self) -> None:
        module = _claim_defense_module()
        positive = module._pair_day_ttest(
            n=3,
            mean=0.25,
            standard_deviation=1e-16,
            minimum=0.25,
            maximum=0.25,
        )
        zero = module._pair_day_ttest(
            n=3,
            mean=0.0,
            standard_deviation=1e-16,
            minimum=0.0,
            maximum=0.0,
        )
        self.assertEqual(positive, (math.inf, 0.0))
        self.assertTrue(math.isnan(zero[0]))
        self.assertTrue(math.isnan(zero[1]))


if __name__ == "__main__":
    unittest.main()

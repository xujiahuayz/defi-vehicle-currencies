from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from scipy import stats

from ddvc.route_cost_summary import summarize_route_cost_panel, write_route_cost_summary


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


if __name__ == "__main__":
    unittest.main()

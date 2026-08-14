from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_stable_vehicle_leadership_e0.py"
SPEC = importlib.util.spec_from_file_location("stable_vehicle_leadership_e0", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def synthetic_panel() -> pd.DataFrame:
    rows = []
    for year in (2024, 2026):
        for day in range(1, 9):
            usdt_count = 20 + day + (20 if year == 2026 else 0)
            usdc_count = 50 - day - (15 if year == 2026 else 0)
            dai_count = 10
            residual_count = 5
            usdt_value = 200 + 10 * day + (220 if year == 2026 else 0)
            usdc_value = 500 - 10 * day - (150 if year == 2026 else 0)
            dai_value = 100
            residual_value = 50
            rows.append(
                {
                    "date": pd.Timestamp(year, 1, day),
                    "cnt_two_leg_USDT": usdt_count,
                    "cnt_two_leg_USDC": usdc_count,
                    "cnt_two_leg_DAI": dai_count,
                    "cnt_two_leg_stable": usdt_count + usdc_count + dai_count + residual_count,
                    "usd_within_20pct_two_leg_USDT": usdt_value,
                    "usd_within_20pct_two_leg_USDC": usdc_value,
                    "usd_within_20pct_two_leg_DAI": dai_value,
                    "usd_within_20pct_two_leg_stable": usdt_value + usdc_value + dai_value + residual_value,
                }
            )
    return pd.DataFrame(rows)


class StableVehicleLeadershipTests(unittest.TestCase):
    def test_daily_shares_and_residual_are_exhaustive(self) -> None:
        result = MODULE.daily_leadership(synthetic_panel())
        shares = result[["usdt_share", "usdc_share", "dai_share", "residual_share"]]
        np.testing.assert_allclose(shares.sum(axis=1), 1.0)
        self.assertTrue((result["residual_activity"] > 0).all())
        self.assertTrue(
            np.allclose(
                result["usdt_minus_usdc_share"],
                result["usdt_share"] - result["usdc_share"],
            )
        )

    def test_endpoint_inference_detects_usdt_gain(self) -> None:
        daily = MODULE.daily_leadership(synthetic_panel())
        estimates = MODULE.gap_inference(daily)
        primary = estimates[
            estimates["method"].eq("endpoint_year_actual_calendar_hac")
            & estimates["hac_lag_days"].eq(30)
        ]
        self.assertEqual(len(primary), 2)
        self.assertTrue(primary["change"].gt(0).all())
        self.assertTrue(primary["p_value_holm"].notna().all())

    def test_holm_adjustment_is_within_method_and_lag_family(self) -> None:
        daily = MODULE.daily_leadership(synthetic_panel())
        estimates = MODULE.gap_inference(daily)
        for (_method, _lag), family in estimates.groupby(
            ["method", "hac_lag_days"], sort=False
        ):
            expected = MODULE.holm_adjusted_pvalues(family["p_value"])
            np.testing.assert_allclose(family["p_value_holm"], expected)

    def test_persistence_uses_adjacent_days_and_censors_endpoints(self) -> None:
        daily = MODULE.daily_leadership(synthetic_panel())
        result = MODULE.persistence_summaries(daily)
        self.assertTrue(result["adjacent_calendar_day_pairs"].eq(7).all())
        self.assertTrue(result["spell_length_comparison"].str.startswith("not_reported").all())
        self.assertTrue(
            (result["fully_observed_internal_spells"] <= result["observed_spells"]).all()
        )

    def test_named_activity_cannot_exceed_stable_total(self) -> None:
        panel = synthetic_panel()
        panel.loc[0, "cnt_two_leg_stable"] = 1
        with self.assertRaisesRegex(ValueError, "exceeds stable total"):
            MODULE.daily_leadership(panel)

    def test_stale_input_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.jsonl"
            blocker = mock.MagicMock()
            blocker.__enter__.side_effect = RuntimeError("stale")
            with mock.patch.object(MODULE, "current_artifacts", return_value=blocker):
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    MODULE.run(Path(directory) / "input.parquet", output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

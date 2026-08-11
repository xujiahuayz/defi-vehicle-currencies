from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.dynamics import (
    CANONICAL_RESPONSE_HORIZONS,
    DAILY_VOLATILITY_MIN_RETURNS,
    DAILY_VOLATILITY_WINDOW_DAYS,
    WETH_DOWNSIDE_EVENT_THRESHOLD,
    daily_price_risk_features,
    exact_daily_log_return,
    value_at_day_offset,
)
from ddvc.analysis.observations import _add_stress


class CalendarDynamicsTests(unittest.TestCase):
    def test_response_horizon_ladder_has_one_calendar_day_owner(self) -> None:
        self.assertEqual(CANONICAL_RESPONSE_HORIZONS, (1, 7, 30, 120))

    def test_offsets_match_exact_dates_in_an_unbalanced_calendar(self) -> None:
        panel = pd.DataFrame(
            {
                "token": ["A", "A", "A", "B", "B"],
                "date": pd.to_datetime(
                    ["2026-01-01", "2026-01-08", "2026-01-09", "2026-01-01", "2026-01-08"]
                ),
                "value": [1.0, 8.0, 9.0, 101.0, 108.0],
            }
        )

        lag = value_at_day_offset(panel, "value", -7)
        lead = value_at_day_offset(panel, "value", 7)

        np.testing.assert_allclose(
            lag.to_numpy(),
            np.array([np.nan, 1.0, np.nan, np.nan, 101.0]),
            equal_nan=True,
        )
        np.testing.assert_allclose(
            lead.to_numpy(),
            np.array([8.0, np.nan, np.nan, 108.0, np.nan]),
            equal_nan=True,
        )

    def test_duplicate_entity_dates_are_rejected(self) -> None:
        panel = pd.DataFrame(
            {
                "token": ["A", "A"],
                "date": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "value": [1.0, 2.0],
            }
        )
        with self.assertRaisesRegex(ValueError, "must be unique"):
            value_at_day_offset(panel, "value", 1)

    def test_daily_return_does_not_bridge_a_missing_calendar_day(self) -> None:
        panel = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-04"]),
                "price": [8.0, 9.0, 12.0],
            }
        )
        result = exact_daily_log_return(panel, "price")
        np.testing.assert_allclose(
            result.to_numpy(),
            np.array([np.nan, np.nan, np.log(12.0 / 9.0)]),
            equal_nan=True,
        )

    def test_daily_price_risk_features_separate_trailing_and_pre_shock_windows(self) -> None:
        dates = pd.date_range("2026-01-01", periods=36, freq="D")
        increments = np.linspace(-0.03, 0.03, 35)
        increments[-1] = -0.10
        panel = pd.DataFrame(
            {
                "date": dates,
                "price": 100.0 * np.exp(np.r_[0.0, np.cumsum(increments)]),
            }
        )
        risk = daily_price_risk_features(panel, "price")
        row = risk.iloc[-1]
        self.assertEqual(DAILY_VOLATILITY_WINDOW_DAYS, 30)
        self.assertEqual(DAILY_VOLATILITY_MIN_RETURNS, 20)
        self.assertEqual(row["trailing_volatility_valid_returns"], 30)
        self.assertEqual(row["pre_shock_volatility_valid_returns"], 30)
        self.assertAlmostEqual(row["log_return"], increments[-1])
        self.assertAlmostEqual(
            row["trailing_30d_volatility"], np.std(increments[-30:], ddof=1)
        )
        pre_shock = np.std(increments[-31:-1], ddof=1)
        self.assertAlmostEqual(row["pre_shock_30d_volatility"], pre_shock)
        self.assertAlmostEqual(row["downside_stress"], 0.10)
        self.assertAlmostEqual(row["standardized_downside_stress"], 0.10 / pre_shock)
        self.assertTrue(row["stress_event_8pct"])
        self.assertEqual(WETH_DOWNSIDE_EVENT_THRESHOLD, 0.08)

    def test_daily_price_risk_features_preserve_calendar_gaps(self) -> None:
        panel = pd.DataFrame(
            {
                "entity": ["A", "A", "A"],
                "date": pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-04"]),
                "price": [8.0, 9.0, 12.0],
            }
        )
        risk = daily_price_risk_features(
            panel, "price", entity_columns=("entity",)
        )
        np.testing.assert_allclose(
            risk["log_return"].to_numpy(),
            np.array([np.nan, np.nan, np.log(12.0 / 9.0)]),
            equal_nan=True,
        )
        self.assertEqual(risk.iloc[-1]["trailing_volatility_valid_returns"], 1)

    def test_daily_price_risk_features_reject_invalid_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty"):
            daily_price_risk_features(pd.DataFrame(columns=["date", "price"]), "price")
        with self.assertRaisesRegex(ValueError, "nonpositive"):
            daily_price_risk_features(
                pd.DataFrame({"date": ["2026-01-01"], "price": [0.0]}), "price"
            )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            daily_price_risk_features(
                pd.DataFrame(
                    {
                        "date": ["2026-01-01", "2026-01-01"],
                        "price": [1.0, 2.0],
                    }
                ),
                "price",
            )

    def test_observation_stress_uses_shared_daily_price_risk_policy(self) -> None:
        dates = pd.date_range("2026-01-01", periods=3, freq="D")
        panel = pd.DataFrame(
            {
                "token": ["WETH", "WETH", "WETH", "USDC", "USDC", "USDC"],
                "date": list(dates) * 2,
                "weth_price": [100.0, 90.0, 91.0] * 2,
            }
        )
        observed = _add_stress(panel)
        expected = daily_price_risk_features(
            panel.loc[panel["token"].eq("WETH"), ["date", "weth_price"]],
            "weth_price",
        )
        weth = observed.loc[observed["token"].eq("WETH")].reset_index(drop=True)
        np.testing.assert_allclose(
            weth["weth_log_return"], expected["log_return"], equal_nan=True
        )
        np.testing.assert_allclose(
            weth["stress_downside"], expected["downside_stress"], equal_nan=True
        )

    def test_registered_dynamic_builders_use_the_canonical_horizon_owner(self) -> None:
        root = Path(__file__).resolve().parents[1]
        consumers = (
            "src/ddvc/analysis/observations.py",
            "scripts/run_core_rq_experiments.py",
            "scripts/run_feedback_proposition_tests.py",
            "scripts/run_lp_supply_flow_tests.py",
            "scripts/run_p2_dynamic_persistence.py",
            "scripts/run_robustness_tests.py",
        )
        for relative in consumers:
            source = (root / relative).read_text()
            self.assertIn("CANONICAL_RESPONSE_HORIZONS", source, relative)
            self.assertNotIn("1, 7, 14, 30", source, relative)

    def test_registered_stress_builders_require_exact_prior_day_prices(self) -> None:
        root = Path(__file__).resolve().parents[1]
        consumers = (
            "scripts/run_claim_defense_analytics.py",
            "scripts/run_core_rq_experiments.py",
            "scripts/run_empirical_proposition_tests.py",
            "scripts/run_jfe_remaining_blocker_fixes.py",
            "scripts/run_robustness_tests.py",
        )
        for relative in consumers:
            source = (root / relative).read_text()
            self.assertIn("exact_daily_log_return", source, relative)
            self.assertNotIn('weth_price"]).diff()', source, relative)
            self.assertNotIn('weth_price"].shift(', source, relative)
        observations = (root / "src/ddvc/analysis/observations.py").read_text()
        self.assertIn("daily_price_risk_features", observations)
        self.assertNotIn("exact_daily_log_return", observations)
        self.assertNotIn("stress_downside\"] =", observations)

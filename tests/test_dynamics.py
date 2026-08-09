from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.dynamics import (
    CANONICAL_RESPONSE_HORIZONS,
    exact_daily_log_return,
    value_at_day_offset,
)


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
            "src/ddvc/analysis/observations.py",
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

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ddvc.analysis.routing_maturation import (
    MARGINS,
    estimate_dynamics,
    estimate_maturation,
    estimate_transition,
    support_geometry,
)


class RoutingMaturationEstimatorTests(unittest.TestCase):
    def _maturation(self) -> pd.DataFrame:
        rows = []
        for tolerance in (1.0, 0.1, 0.01):
            for year in range(2021, 2026):
                for day in range(1, 5):
                    for cell in range(5):
                        row = {
                            "date": pd.Timestamp(year=year, month=1, day=day),
                            "cell_id": f"cell_{cell}",
                            "route_count": 1 + cell + day,
                            "reproduction_tolerance_bps": tolerance,
                            "recurrent_primary": True,
                            "recurrent_strict": cell < 4,
                        }
                        for index, margin in enumerate(MARGINS):
                            level = 0.02 * index + 0.03 * (year - 2021) + 0.002 * cell
                            row[f"{margin}_over_0p01_share"] = level + 0.1
                            row[f"{margin}_over_1_share"] = level
                            row[f"{margin}_over_10_share"] = level / 2
                            row[f"{margin}_mean_log1p_bps"] = level * 2
                        rows.append(row)
        return pd.DataFrame(rows)

    def _transition(self) -> pd.DataFrame:
        rows = []
        bins = ["b1_0_0p01", "b2_0p01_1", "b3_1_10", "b4_above_10"]
        for year, stable_routes in ((2024, 2), (2026, 6)):
            for day in (1, 2):
                for pair in range(4):
                    for stable, routes in ((0, 8), (1, stable_routes)):
                        rows.append(
                            {
                                "date": pd.Timestamp(year=year, month=1, day=day),
                                "stable_indicator": stable,
                                "route_count": routes,
                                "reproduction_tolerance_bps": 1.0,
                                "endpoint_pair_id": f"pair_{pair}",
                                "opportunity_cell_id": f"opp_{pair}",
                                "within_reach_regret_bin": bins[pair],
                                "reach_increment_bin": bins[(pair + day) % 4],
                                "path_choice_increment_bin": bins[(pair + stable) % 4],
                            }
                        )
        return pd.DataFrame(rows)

    def _dynamics(self) -> pd.DataFrame:
        rng = np.random.default_rng(20260810)
        rows = []
        for horizon in (1, 7, 30, 120):
            for year in range(2021, 2026):
                for day in range(1, 5):
                    for cell in range(5):
                        row = {
                            "cell_id": f"cell_{cell}",
                            "origin_date": pd.Timestamp(year=year, month=1, day=day),
                            "horizon_days": horizon,
                            "target_observed": not (horizon == 120 and cell == 4),
                            "reproduction_tolerance_bps": 1.0,
                        }
                        for index, margin in enumerate(MARGINS):
                            current = 0.1 + 0.02 * index + 0.01 * cell + rng.normal(0, 0.005)
                            row[f"current_{margin}_over_1_share"] = current
                            row[f"future_{margin}_over_1_share"] = (
                                0.5 * current + 0.01 * (year - 2021) + rng.normal(0, 0.005)
                            )
                        rows.append(row)
        return pd.DataFrame(rows)

    def test_maturation_contract_has_four_primary_and_prespecified_sensitivities(self) -> None:
        result = estimate_maturation(self._maturation())
        self.assertEqual(len(result), 40)
        primary = result[result["spec"].eq("primary_annual_profile")]
        self.assertEqual(set(primary["margin"]), set(MARGINS))
        np.testing.assert_allclose(primary["comparison_2025_beta"], 0.12, atol=1e-10)
        self.assertTrue(primary["comparison_2025_holm_p"].notna().all())
        self.assertEqual(
            set(result[result["spec"].eq("linear_elapsed_year_sensitivity")]["margin"]),
            set(MARGINS),
        )

    def test_transition_keeps_route_and_equal_date_weighting_separate(self) -> None:
        result = estimate_transition(self._transition())
        self.assertEqual(set(result["spec"]), {"route_weighted_primary", "equal_date_sensitivity"})
        self.assertTrue((result["common_month_days"] == 2).all())
        self.assertTrue(result["comparison_2026_beta"].gt(0).all())
        self.assertTrue(result["regret_control_count"].gt(0).all())

    def test_exact_horizon_models_preserve_all_four_calendar_links(self) -> None:
        result = estimate_dynamics(self._dynamics())
        self.assertEqual(len(result), 16)
        self.assertEqual(set(result["horizon_days"]), {1, 7, 30, 120})
        short = result[result["horizon_days"].eq(1)]
        long = result[result["horizon_days"].eq(120)]
        self.assertTrue((short["link_coverage"] == 1).all())
        self.assertTrue((long["link_coverage"] == 0.8).all())
        self.assertTrue(result["current_share_beta"].between(0.2, 0.8).all())

    def test_support_geometry_applies_the_predeclared_half_sample_review_gate(self) -> None:
        result = support_geometry(self._maturation())
        self.assertEqual(len(result), 30)
        self.assertFalse(result["support_exit_review_required"].any())

    def test_missing_contract_column_fails_before_fit(self) -> None:
        with self.assertRaisesRegex(ValueError, "lacks columns"):
            estimate_transition(self._transition().drop(columns="opportunity_cell_id"))


if __name__ == "__main__":
    unittest.main()

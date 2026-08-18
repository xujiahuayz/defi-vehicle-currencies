from __future__ import annotations

import unittest

import pandas as pd

from scripts.analyze.run_usdt_integration_decomposition_e0 import (
    build_exhibit,
    midpoint_decomposition,
    ratio_of_totals_cells,
    scope_change_tests,
)


def _panel() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year, single_denominator, single_usdt, cross_denominator, cross_usdt in [
        (2024, 80.0, 10.0, 20.0, 5.0),
        (2026, 70.0, 35.0, 30.0, 15.0),
    ]:
        for day in ("01-01", "01-02"):
            row: dict[str, object] = {"date": pd.Timestamp(f"{year}-{day}")}
            for prefix in ("cnt_", "usd_within_20pct_"):
                row[f"{prefix}single_venue_two_leg_USDT"] = single_usdt / 2
                row[f"{prefix}single_venue_two_leg_USDC"] = (
                    single_denominator - single_usdt
                ) / 2
                row[f"{prefix}single_venue_two_leg_native"] = 0.0
                row[f"{prefix}cross_venue_two_leg_USDT"] = cross_usdt / 2
                row[f"{prefix}cross_venue_two_leg_USDC"] = (
                    cross_denominator - cross_usdt
                ) / 2
                row[f"{prefix}cross_venue_two_leg_native"] = 0.0
            rows.append(row)
    return pd.DataFrame(rows)


class UsdtIntegrationDecompositionTests(unittest.TestCase):
    def test_midpoint_decomposition_separates_within_and_between_scope_change(self) -> None:
        cells = ratio_of_totals_cells(_panel())
        result = midpoint_decomposition(cells)
        episodes = result[result["weighting"].eq("episode")].iloc[0]

        self.assertAlmostEqual(episodes["total_usdt_share_change"], 0.35)
        self.assertAlmostEqual(episodes["within_scope_change"], 0.34375)
        self.assertAlmostEqual(episodes["between_scope_composition_change"], 0.00625)
        self.assertAlmostEqual(episodes["identity_residual"], 0.0)

    def test_scope_change_tests_cover_exact_two_leg_integration_cells(self) -> None:
        tests = scope_change_tests(_panel(), hac_lag=0)

        self.assertEqual(
            set(tests["routing_scope"]),
            {"single_venue_two_leg", "cross_venue_two_leg"},
        )
        self.assertEqual(set(tests["transformation"]), {"share_level", "log_odds"})
        self.assertTrue(tests["change"].notna().all())

    def test_exhibit_contains_tests_cells_and_decomposition(self) -> None:
        exhibit = build_exhibit(_panel())

        self.assertEqual(
            set(exhibit["record_type"]),
            {
                "scope_change_test",
                "endpoint_scope_ratio",
                "midpoint_decomposition",
            },
        )


if __name__ == "__main__":
    unittest.main()

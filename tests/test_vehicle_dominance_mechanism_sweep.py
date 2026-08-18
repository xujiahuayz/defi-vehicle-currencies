from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts.analyze.run_vehicle_dominance_mechanism_sweep import (
    BASELINE_YEAR,
    COMPARISON_YEAR,
    build_candidate_risk_set_design,
    build_stable_turn_on_hazard_design,
    build_transition_design,
    estimate_candidate_risk_set_choice,
    estimate_mechanism_sweep,
    estimate_stable_turn_on_hazard,
)


class VehicleDominanceMechanismSweepTests(unittest.TestCase):
    def test_build_transition_design_and_fit_small_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pair_panel_rows = []
            support_rows = []
            pairs = [
                (f"0xsrc{i:02x}", f"0xtgt{i:02x}")
                for i in range(1, 7)
            ]
            for pair_index, (src, tgt) in enumerate(pairs, start=1):
                for month_day, month, day in (("01-01", 1, 1), ("01-02", 1, 2)):
                    for scope in ("single_venue", "cross_venue"):
                        for year in (BASELINE_YEAR, COMPARISON_YEAR):
                            stable = 0.1 * pair_index
                            if year == COMPARISON_YEAR:
                                stable += 0.05 * pair_index
                            denominator = 10 + pair_index
                            pair_panel_rows.append(
                                {
                                    "metric": "count_share",
                                    "year": year,
                                    "date": pd.Timestamp(year=year, month=month, day=day),
                                    "src": src,
                                    "tgt": tgt,
                                    "month_day": month_day,
                                    "integration_scope": scope,
                                    "native": denominator * (1 - stable),
                                    "stable": denominator * stable,
                                    "denominator": denominator,
                                    "stable_share": stable,
                                }
                            )
                    for year in (BASELINE_YEAR, COMPARISON_YEAR):
                        date = pd.Timestamp(year=year, month=month, day=day)
                        support_rows.append(
                            {
                                "date": date,
                                "src": src,
                                "tgt": tgt,
                                "market_route_count": 100 + 10 * pair_index,
                                "primary_choice_route_count": 80 + 8 * pair_index,
                                "direct_route_count": 20 + pair_index,
                                "direct_split_route_count": 1,
                                "other_candidate_route_count": 0,
                                "multiple_intermediary_route_count": pair_index,
                                "split_or_join_route_count": 0,
                                "nonsequential_two_leg_route_count": 0,
                                "pair_first_supported_date": pd.Timestamp("2020-01-01"),
                                "pair_last_supported_date": pd.Timestamp("2026-06-30"),
                            }
                        )
            pair_panel = pd.DataFrame(pair_panel_rows)
            for metric in (
                "matched_strict_count_share",
                "strict_intermediation_value_share",
            ):
                clone = pair_panel[pair_panel["metric"].eq("count_share")].copy()
                clone["metric"] = metric
                pair_panel = pd.concat([pair_panel, clone], ignore_index=True)
            pair_panel_path = root / "pair_panel.parquet"
            support_path = root / "pair_support.parquet"
            pair_panel.to_parquet(pair_panel_path, index=False)
            pd.DataFrame(support_rows).to_parquet(support_path, index=False)

            design = build_transition_design(pair_panel_path, support_path)
            self.assertIn("stable_share_change", design)
            self.assertGreater(len(design), 0)

            results, support = estimate_mechanism_sweep(design, min_clusters=2)
            self.assertGreater(len(results), 0)
            self.assertEqual(
                set(support["metric"]),
                {
                    "count_share",
                    "matched_strict_count_share",
                    "strict_intermediation_value_share",
                },
            )
            self.assertTrue(
                results["claim_status"].eq("provisional_exploratory").all()
            )
            self.assertIn(
                "regime_persistence",
                set(results["model_id"]),
            )

    def test_candidate_risk_set_choice_reports_within_set_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rows = []
            for year in (BASELINE_YEAR, COMPARISON_YEAR):
                for day in range(1, 8):
                    for pair_index in range(1, 6):
                        src = f"0xsrc{pair_index:02x}"
                        tgt = f"0xtgt{pair_index:02x}"
                        native_routes = 20 + pair_index
                        stable_routes = 5 + int(year == COMPARISON_YEAR)
                        for candidate_type, candidate, route_count in (
                            ("native", "WETH", native_routes),
                            ("stable", "USDC", stable_routes),
                        ):
                            rows.append(
                                {
                                    "date": pd.Timestamp(year=year, month=1, day=day),
                                    "src": src,
                                    "tgt": tgt,
                                    "integration_scope": "single_venue",
                                    "candidate_address": candidate.lower(),
                                    "candidate_symbol": candidate,
                                    "candidate_type": candidate_type,
                                    "route_count": route_count,
                                }
                            )
            choices_path = root / "choices.parquet"
            pd.DataFrame(rows).to_parquet(choices_path, index=False)

            design = build_candidate_risk_set_design(choices_path)
            self.assertTrue(design["has_stable"].eq(1).all())
            self.assertTrue(design["has_native"].eq(1).all())

            results, support = estimate_candidate_risk_set_choice(
                design, min_observations=20, min_clusters=2
            )
            self.assertIn(
                "mixed_native_stable_risk_set_fe",
                set(results["model_id"]),
            )
            penalty = results[
                results["model_id"].eq("mixed_native_stable_risk_set_fe")
                & results["min_total_routes"].eq(1)
                & results["regressor"].eq("is_stable")
            ].iloc[0]
            self.assertLess(penalty["coefficient"], 0)
            self.assertIn("candidate_route_share", set(support["metric"]))

    def test_stable_turn_on_hazard_reports_thick_market_contrast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rows = []
            stable = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
            for year in (BASELINE_YEAR, COMPARISON_YEAR):
                for pair_index in range(1, 13):
                    high_demand = pair_index >= 7
                    src = stable if pair_index % 4 == 0 else f"0xsrc{pair_index:02x}"
                    tgt = f"0xtgt{pair_index:02x}"
                    first_date = pd.Timestamp(year=year, month=1, day=1)
                    for day in range(1, 36):
                        current_date = first_date + pd.Timedelta(days=day - 1)
                        stable_routes = 4 if high_demand and day % 5 == 0 else 0
                        native_routes = 10
                        market_routes = (100 if high_demand else 4) + day
                        rows.append(
                            {
                                "date": current_date,
                                "src": src,
                                "tgt": tgt,
                                "market_route_count": market_routes,
                                "primary_choice_route_count": native_routes + stable_routes,
                                "stable_choice_route_count": stable_routes,
                                "direct_route_count": 1 + int(high_demand),
                                "multiple_intermediary_route_count": pair_index % 3,
                                "split_or_join_route_count": 0,
                                "nonsequential_two_leg_route_count": 0,
                                "pair_first_supported_date": first_date,
                            }
                        )
            path = root / "pair_support.parquet"
            pd.DataFrame(rows).to_parquet(path, index=False)

            design = build_stable_turn_on_hazard_design(path, horizon_days=10)
            self.assertIn("future_stable_turn_on", design)
            self.assertGreater(design["future_stable_turn_on"].mean(), 0)

            results, support = estimate_stable_turn_on_hazard(
                design,
                horizon_days=10,
                min_observations=20,
                min_clusters=2,
            )
            decile = results[
                results["model_id"].eq("stable_turn_on_hazard_decile")
                & results["regressor"].eq("log_market_routes")
            ].iloc[0]
            self.assertGreater(decile["top_minus_bottom_pp"], 0)
            self.assertIn("stable_turn_on_hazard_fe", set(results["model_id"]))
            self.assertEqual(
                set(support["metric"]),
                {"native_only_pair_day_stable_turn_on"},
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts.analyze.run_vehicle_dominance_mechanism_sweep import (
    BASELINE_YEAR,
    COMPARISON_YEAR,
    build_transition_design,
    estimate_mechanism_sweep,
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


if __name__ == "__main__":
    unittest.main()

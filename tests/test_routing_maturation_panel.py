from __future__ import annotations

import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from scripts.build_routing_maturation_panel import (
    build_panels,
    notional_bin_sql,
    observed_reach_sql,
    regret_bin_sql,
    main,
)


class RoutingMaturationPanelTests(unittest.TestCase):
    def test_main_holds_frontier_lease_through_all_output_stamps(self) -> None:
        release = type(
            "Release",
            (),
            {
                "artifacts": {
                    "panel": Path("panel"),
                    "rejections": Path("rejections"),
                    "support": Path("support"),
                },
                "lineage_paths": (Path("current.json"), Path("panel")),
            },
        )()
        events = []

        @contextmanager
        def leased(selected):
            events.append("lease-enter")
            yield selected
            events.append("lease-exit")

        with (
            patch("sys.argv", ["build_routing_maturation_panel.py"]),
            patch("scripts.build_routing_maturation_panel.require_node_d_release"),
            patch(
                "scripts.build_routing_maturation_panel.resolve_frontier_release",
                return_value=release,
            ),
            patch(
                "scripts.build_routing_maturation_panel.current_frontier_release",
                side_effect=leased,
            ),
            patch("scripts.build_routing_maturation_panel.require_current_artifacts"),
            patch(
                "scripts.build_routing_maturation_panel.build_panels",
                return_value={
                    "source_rows": 1,
                    "chosen_reproduction": 1.0,
                    "chosen_state_coverage": 1.0,
                    "chosen_verified_coverage": 1.0,
                    "cell_rows": 1,
                    "transition_rows": 1,
                    "horizon_rows": 1,
                },
            ) as build,
            patch(
                "scripts.build_routing_maturation_panel.stamp",
                side_effect=lambda *_args, **_kwargs: events.append("stamp"),
            ),
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(events, ["lease-enter", "stamp", "stamp", "stamp", "lease-exit"])
        build.assert_called_once()

    def _source(self, root: Path) -> tuple[Path, Path]:
        source = root / "frontier.parquet"
        support = root / "support.parquet"
        rows = []
        for day, vehicle, error, within, reach, path, total, vehicle_type in (
            ("2021-01-01", "0xC", 0.0, 0.0, 0.0, 0.0, 0.0, "native"),
            ("2021-01-02", "0xC", 0.05, 2.0, 3.0, 0.05, 5.05, "native"),
            ("2021-01-02", "0xD", 0.05, 2.0, 3.0, 0.05, 5.05, "stable"),
            ("2021-01-08", "0xC", 0.005, 0.005, 0.5, 12.0, 12.505, "native"),
            ("2024-01-01", "0xC", 0.0, 0.0, 0.0, 0.0, 0.0, "native"),
            ("2024-01-01", "0xD", 0.0, 0.0, 0.0, 12.0, 12.0, "stable"),
            ("2026-01-01", "0xC", 0.0, 0.0, 0.0, 0.0, 0.0, "native"),
            ("2026-01-01", "0xD", 0.0, 0.0, 0.0, 12.0, 12.0, "stable"),
        ):
            rows.append(
                {
                    "date": pd.Timestamp(day),
                    "src": "0xA",
                    "tgt": "0xB",
                    "vehicle": vehicle,
                    "vehicle_type": vehicle_type,
                    "input_usd": 1_000.0,
                    "within_20pct": True,
                    "realised_venues": "uniswap_v3|uniswap_v3",
                    "public_gain_usd": 1.0,
                    "chosen_leg1_validation_error_bps": error,
                    "chosen_leg2_validation_error_bps": error,
                    "chosen_validation_error_bps": error,
                    "chosen_validation_max_abs_error_bps": abs(error),
                    "within_reach_search_regret_bps": within,
                    "reach_increment_bps": reach,
                    "path_choice_increment_bps": path,
                    "public_path_regret_bps": total,
                }
            )
        pd.DataFrame(rows).to_parquet(source, index=False)
        pd.DataFrame(
            {
                "scored_routes": [8],
                "within_20pct_chosen_quote_eligible_routes": [8],
                "within_20pct_chosen_quote_available": [8],
                "within_20pct_chosen_output_mismatch": [0],
            }
        ).to_parquet(support, index=False)
        return source, support

    def test_sql_contracts_are_explicit(self) -> None:
        self.assertIn("least", observed_reach_sql())
        self.assertIn("b5_1m_plus", notional_bin_sql())
        self.assertIn("b4_above_10", regret_bin_sql("x"))

    def test_builds_recurrent_cells_and_exact_calendar_links(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, support = self._source(root)
            cell = root / "cell.parquet"
            transition = root / "transition.parquet"
            dynamics = root / "dynamics.parquet"
            results = build_panels(
                source,
                support,
                cell,
                transition,
                dynamics,
                full_years=(2021,),
                primary_min_days=1,
                strict_min_days=2,
            )
            self.assertEqual(results["source_rows"], 8)
            self.assertEqual(results["chosen_state_coverage"], 1.0)
            self.assertEqual(results["chosen_verified_coverage"], 1.0)
            panel = pd.read_parquet(cell)
            self.assertEqual(set(panel["observed_reach"]), {"uniswap_v3"})
            self.assertEqual(set(panel["notional_bin"]), {"b2_1k_10k"})
            one_bp = panel[
                panel["reproduction_tolerance_bps"].eq(1.0)
                & pd.to_datetime(panel["date"]).dt.year.eq(2021)
            ]
            self.assertTrue(one_bp["recurrent_primary"].all())
            native_cell = one_bp[one_bp["vehicle"].eq("0xc")]
            stable_cell = one_bp[one_bp["vehicle"].eq("0xd")]
            self.assertTrue(native_cell["recurrent_strict"].all())
            self.assertFalse(stable_cell["recurrent_strict"].any())
            linked = pd.read_parquet(dynamics)
            linked["origin_date"] = pd.to_datetime(linked["origin_date"])
            one_day = linked[
                linked["reproduction_tolerance_bps"].eq(1.0)
                & linked["origin_date"].eq(pd.Timestamp("2021-01-01"))
                & linked["horizon_days"].eq(1)
            ].iloc[0]
            self.assertTrue(one_day["target_observed"])
            seven_day = linked[
                linked["reproduction_tolerance_bps"].eq(1.0)
                & linked["origin_date"].eq(pd.Timestamp("2021-01-01"))
                & linked["horizon_days"].eq(7)
            ].iloc[0]
            self.assertTrue(seven_day["target_observed"])
            missing = linked[
                linked["reproduction_tolerance_bps"].eq(1.0)
                & linked["origin_date"].eq(pd.Timestamp("2021-01-02"))
                & linked["horizon_days"].eq(1)
            ].iloc[0]
            self.assertFalse(missing["target_observed"])
            self.assertTrue(pd.isna(missing["future_route_count"]))
            transition_panel = pd.read_parquet(transition)
            self.assertEqual(set(transition_panel["stable_indicator"]), {0, 1})
            self.assertIn("b4_above_10", set(transition_panel["path_choice_increment_bin"]))
            self.assertEqual(transition_panel["endpoint_pair_id"].nunique(), 1)
            self.assertEqual(transition_panel["opportunity_cell_id"].nunique(), 1)
            self.assertGreater(transition_panel["transition_cell_id"].nunique(), 1)
            self.assertEqual(set(transition_panel["reproduction_tolerance_bps"]), {1.0})
            self.assertEqual(set(pd.to_datetime(transition_panel["date"]).dt.year), {2024, 2026})

    def test_rejects_noncanonical_horizons(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, support = self._source(root)
            with self.assertRaisesRegex(ValueError, "dynamic horizons"):
                build_panels(
                    source,
                    support,
                    root / "cell.parquet",
                    root / "transition.parquet",
                    root / "dynamics.parquet",
                    full_years=(2021,),
                    primary_min_days=1,
                    strict_min_days=2,
                    horizons=(1, 7, 30),
                )

    def test_rejects_a_maximum_error_that_ignores_leg_errors(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, support = self._source(root)
            panel = pd.read_parquet(source)
            panel.loc[1, "chosen_validation_max_abs_error_bps"] = 0.0
            panel.to_parquet(source, index=False)
            with self.assertRaisesRegex(ValueError, "validation"):
                build_panels(
                    source,
                    support,
                    root / "cell.parquet",
                    root / "transition.parquet",
                    root / "dynamics.parquet",
                    full_years=(2021,),
                    primary_min_days=1,
                    strict_min_days=2,
                )


if __name__ == "__main__":
    unittest.main()

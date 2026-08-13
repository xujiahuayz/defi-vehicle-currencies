from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.figure_outputs import (
    ASSET_TYPES,
    architecture_support_composition,
    integration_intermediation_bins,
    integration_rotation_slopes,
    render_architecture_support,
    render_integration_intermediation,
    render_integration_rotation_slopes,
    quarterly_vehicle_type_shares,
    render_round_trip_shares,
    render_vehicle_excess_use_heatmap,
    render_vehicle_excess_use_transition,
    render_vehicle_type_shares,
    round_trip_daily_and_quarterly,
    validate_daily_calendar,
    vehicle_excess_use_cross_section,
    vehicle_excess_use_transition,
)


def vehicle_fixture() -> pd.DataFrame:
    rows = []
    for date, scale in (("2024-03-30", 1), ("2024-03-31", 2), ("2024-04-01", 3)):
        row: dict[str, object] = {"date": date}
        for index, asset_type in enumerate(ASSET_TYPES, 1):
            row[f"cnt_{asset_type}"] = scale * index
            row[f"usd_within_20pct_{asset_type}"] = scale * index * 10
        rows.append(row)
    return pd.DataFrame(rows)


def route_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-03-30", periods=4, freq="D"),
            "multi_leg_routes": [100, 200, 100, 100],
            "round_trip_routes": [10, 40, 30, 20],
            "round_trip_share_of_multileg": [0.1, 0.2, 0.3, 0.2],
            "round_trip_usd_share_of_multileg": [0.5, 0.7, 0.2, 0.4],
        }
    )


def integration_fixture() -> pd.DataFrame:
    frame = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=20, freq="D")})
    frame["cross_venue_share"] = [index / 20 for index in range(20)]
    frame["intermediated_share"] = [0.4 - index / 100 for index in range(20)]
    frame["balanced_cross_venue_share"] = [index / 25 for index in range(20)]
    frame["balanced_intermediated_share"] = [0.35 - index / 120 for index in range(20)]
    return frame


def integration_rotation_fixture() -> pd.DataFrame:
    rows = []
    for weighting, support, single_start, single_end, cross_start, cross_end in (
        ("episode", "all_routes", 0.20, 0.43, 0.23, 0.54),
        ("value", "within_20pct", 0.36, 0.71, 0.40, 0.83),
    ):
        for scope, start, end in (
            ("single_venue", single_start, single_end),
            ("cross_venue", cross_start, cross_end),
        ):
            rows.append(
                {
                    "integration_scope": scope,
                    "weighting": weighting,
                    "value_support": support,
                    "transformation": "share_level",
                    "baseline_year": 2024,
                    "comparison_year": 2026,
                    "baseline_daily_mean": start,
                    "comparison_daily_mean": end,
                }
            )
    return pd.DataFrame(rows)


def excess_use_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"lens": "cross_section", "year": 2026, "token": "USDC", "count_excess_use": 1.5, "value_excess_use": 1.1, "is_vehicle": True},
            {"lens": "cross_section", "year": 2026, "token": "WETH", "count_excess_use": 0.8, "value_excess_use": 0.6, "is_vehicle": False},
            {"lens": "fragmentation", "year": 2026, "token": None, "count_excess_use": None, "value_excess_use": None, "is_vehicle": None},
        ]
    )


def excess_use_transition_fixture() -> pd.DataFrame:
    rows = []
    for symbol, count_start, count_end, value_start, value_end in (
        ("USDC", 1.4, 1.5, 1.1, 1.15),
        ("USDT", 1.05, 1.23, 0.59, 1.42),
    ):
        for year, count, value in (
            (2024, count_start, value_start),
            (2026, count_end, value_end),
        ):
            rows.append(
                {
                    "level": "token",
                    "year": year,
                    "symbol": symbol,
                    "vehicle_excess_use_count_ratio": count,
                    "vehicle_excess_use_ratio_within_20pct": value,
                }
            )
    return pd.DataFrame(rows)


def architecture_fixture() -> pd.DataFrame:
    rows = []
    for kind in ("entry", "exit"):
        for threshold in (0.05, 0.10, 0.25):
            rows.append(
                {
                    "kind": kind,
                    "threshold": threshold,
                    "detected_events": 10,
                    "composition_shift_events": 2,
                    "incomplete_window_events": 3,
                    "overlapping_transition_events": 5,
                    "usable_events": 0,
                }
            )
    return pd.DataFrame(rows)


class FigureOutputTests(unittest.TestCase):
    def test_vehicle_quarters_use_ratio_of_totals_and_exhaustive_denominator(self) -> None:
        result = quarterly_vehicle_type_shares(vehicle_fixture())
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result.loc[0, "count_share_native"], 1 / 15)
        self.assertAlmostEqual(result.loc[0, "value_share_stable"], 3 / 15)
        count_columns = [f"count_share_{asset_type}" for asset_type in ASSET_TYPES]
        value_columns = [f"value_share_{asset_type}" for asset_type in ASSET_TYPES]
        self.assertTrue((result[count_columns].sum(axis=1).round(12) == 1).all())
        self.assertTrue((result[value_columns].sum(axis=1).round(12) == 1).all())

    def test_round_trip_quarterly_series_uses_median_daily_share(self) -> None:
        daily, quarterly = round_trip_daily_and_quarterly(route_fixture())
        self.assertEqual(len(daily), 4)
        self.assertEqual(len(quarterly), 2)
        self.assertAlmostEqual(quarterly.loc[0, "round_trip_share_of_multileg"], 0.15)
        self.assertAlmostEqual(quarterly.loc[0, "round_trip_usd_share_of_multileg"], 0.6)

    def test_calendar_gap_fails_closed(self) -> None:
        frame = route_fixture().drop(index=1)
        with self.assertRaisesRegex(ValueError, "not full-calendar"):
            validate_daily_calendar(frame, name="fixture")

    def test_round_trip_count_identity_fails_closed(self) -> None:
        frame = route_fixture()
        frame.loc[0, "round_trip_share_of_multileg"] = 0.9
        with self.assertRaisesRegex(ValueError, "count share disagrees"):
            round_trip_daily_and_quarterly(frame)

    def test_integration_bins_preserve_both_cohorts_and_all_days(self) -> None:
        result = integration_intermediation_bins(integration_fixture(), bins=5)
        self.assertEqual(set(result["cohort"]), {"Full sample", "Balanced cohort"})
        self.assertEqual(len(result), 10)
        self.assertTrue((result.groupby("cohort")["days"].sum() == 20).all())

    def test_integration_rotation_requires_each_regime_and_weighting(self) -> None:
        result = integration_rotation_slopes(integration_rotation_fixture())
        self.assertEqual(len(result), 4)
        with self.assertRaisesRegex(ValueError, "one unique cell"):
            integration_rotation_slopes(integration_rotation_fixture().iloc[:-1])

    def test_excess_use_cross_section_selects_latest_and_orders_candidates(self) -> None:
        result = vehicle_excess_use_cross_section(excess_use_fixture())
        self.assertEqual(result["token"].tolist(), ["USDC", "WETH"])
        self.assertEqual(result["year"].unique().tolist(), [2026])

    def test_excess_use_transition_requires_both_candidates_and_years(self) -> None:
        result = vehicle_excess_use_transition(excess_use_transition_fixture())
        self.assertEqual(len(result), 4)
        self.assertEqual(
            result[["symbol", "year"]].values.tolist(),
            [["USDC", 2024], ["USDC", 2026], ["USDT", 2024], ["USDT", 2026]],
        )
        with self.assertRaisesRegex(ValueError, "one unique cell"):
            vehicle_excess_use_transition(excess_use_transition_fixture().iloc[:-1])

    def test_architecture_support_must_reconcile_to_detected_events(self) -> None:
        result = architecture_support_composition(architecture_fixture())
        self.assertEqual(len(result), 6)
        broken = architecture_fixture()
        broken.loc[0, "usable_events"] = 1
        with self.assertRaisesRegex(ValueError, "do not reconcile"):
            architecture_support_composition(broken)

    def test_renderers_write_vector_pdfs_from_synthetic_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vehicle = root / "vehicle.pdf"
            round_trip = root / "round-trip.pdf"
            integration = root / "integration.pdf"
            integration_rotation = root / "integration-rotation.pdf"
            heatmap = root / "heatmap.pdf"
            architecture = root / "architecture.pdf"
            transition = root / "transition.pdf"
            render_vehicle_type_shares(vehicle_fixture(), vehicle)
            render_round_trip_shares(route_fixture(), round_trip)
            render_integration_intermediation(integration_fixture(), integration)
            render_integration_rotation_slopes(
                integration_rotation_fixture(), integration_rotation
            )
            render_vehicle_excess_use_heatmap(excess_use_fixture(), heatmap)
            render_architecture_support(architecture_fixture(), architecture)
            render_vehicle_excess_use_transition(excess_use_transition_fixture(), transition)
            for path in (
                vehicle,
                round_trip,
                integration,
                integration_rotation,
                heatmap,
                architecture,
                transition,
            ):
                self.assertGreater(path.stat().st_size, 1_000)
                self.assertEqual(path.read_bytes()[:4], b"%PDF")
                self.assertNotIn(b"/Subtype /Image", path.read_bytes())


if __name__ == "__main__":
    unittest.main()

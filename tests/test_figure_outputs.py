from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.figure_outputs import (
    ASSET_TYPES,
    architecture_support_composition,
    integration_intermediation_bins,
    render_architecture_support,
    render_integration_intermediation,
    quarterly_vehicle_type_shares,
    render_round_trip_shares,
    render_vehicle_excess_use_heatmap,
    render_vehicle_type_shares,
    round_trip_daily_and_quarterly,
    validate_daily_calendar,
    vehicle_excess_use_cross_section,
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


def excess_use_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"lens": "cross_section", "year": 2026, "token": "USDC", "count_excess_use": 1.5, "value_excess_use": 1.1, "is_vehicle": True},
            {"lens": "cross_section", "year": 2026, "token": "WETH", "count_excess_use": 0.8, "value_excess_use": 0.6, "is_vehicle": False},
            {"lens": "fragmentation", "year": 2026, "token": None, "count_excess_use": None, "value_excess_use": None, "is_vehicle": None},
        ]
    )


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

    def test_excess_use_cross_section_selects_latest_and_orders_candidates(self) -> None:
        result = vehicle_excess_use_cross_section(excess_use_fixture())
        self.assertEqual(result["token"].tolist(), ["USDC", "WETH"])
        self.assertEqual(result["year"].unique().tolist(), [2026])

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
            heatmap = root / "heatmap.pdf"
            architecture = root / "architecture.pdf"
            render_vehicle_type_shares(vehicle_fixture(), vehicle)
            render_round_trip_shares(route_fixture(), round_trip)
            render_integration_intermediation(integration_fixture(), integration)
            render_vehicle_excess_use_heatmap(excess_use_fixture(), heatmap)
            render_architecture_support(architecture_fixture(), architecture)
            for path in (vehicle, round_trip, integration, heatmap, architecture):
                self.assertGreater(path.stat().st_size, 1_000)
                self.assertEqual(path.read_bytes()[:4], b"%PDF")
                self.assertNotIn(b"/Subtype /Image", path.read_bytes())


if __name__ == "__main__":
    unittest.main()

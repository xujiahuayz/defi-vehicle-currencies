from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ddvc.figure_outputs import (
    ASSET_TYPES,
    quarterly_vehicle_type_shares,
    render_round_trip_shares,
    render_vehicle_type_shares,
    round_trip_daily_and_quarterly,
    validate_daily_calendar,
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

    def test_renderers_write_vector_pdfs_from_synthetic_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vehicle = root / "vehicle.pdf"
            round_trip = root / "round-trip.pdf"
            render_vehicle_type_shares(vehicle_fixture(), vehicle)
            render_round_trip_shares(route_fixture(), round_trip)
            for path in (vehicle, round_trip):
                self.assertGreater(path.stat().st_size, 1_000)
                self.assertEqual(path.read_bytes()[:4], b"%PDF")
                self.assertNotIn(b"/Subtype /Image", path.read_bytes())


if __name__ == "__main__":
    unittest.main()

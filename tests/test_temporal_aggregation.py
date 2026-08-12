from __future__ import annotations

import unittest

import pandas as pd

from ddvc.analysis.dynamics import aggregate_complete_day_bins, anchored_day_bin_start


class TemporalAggregationTests(unittest.TestCase):
    def test_all_seven_week_anchors_are_explicit(self) -> None:
        dates = pd.Series(pd.to_datetime(["2024-01-01", "2024-01-07"]))
        monday = anchored_day_bin_start(dates, anchor_offset_days=0)
        tuesday = anchored_day_bin_start(dates, anchor_offset_days=1)
        self.assertEqual(monday.dt.strftime("%Y-%m-%d").tolist(), ["2024-01-01", "2024-01-01"])
        self.assertEqual(tuesday.dt.strftime("%Y-%m-%d").tolist(), ["2023-12-26", "2024-01-02"])

    def test_complete_bins_are_summed_from_raw_values(self) -> None:
        frame = pd.DataFrame({"date": pd.date_range("2023-12-25", "2024-01-14"), "asset": "x", "value": 1.0})
        result = aggregate_complete_day_bins(
            frame,
            value_columns=["value"],
            group_columns=["asset"],
            anchor_offset_days=0,
        )
        self.assertEqual(
            result["period_start"].dt.strftime("%Y-%m-%d").tolist(),
            ["2023-12-25", "2024-01-01", "2024-01-08"],
        )
        self.assertEqual(result["value"].tolist(), [7.0, 7.0, 7.0])

    def test_missing_calendar_day_drops_its_entire_bin(self) -> None:
        dates = pd.date_range("2024-01-01", "2024-01-14").difference(pd.DatetimeIndex(["2024-01-04"]))
        frame = pd.DataFrame({"date": dates, "asset": "x", "value": 1.0})
        result = aggregate_complete_day_bins(
            frame,
            value_columns=["value"],
            group_columns=["asset"],
            anchor_offset_days=0,
        )
        self.assertEqual(result["period_start"].dt.strftime("%Y-%m-%d").tolist(), ["2024-01-08"])


if __name__ == "__main__":
    unittest.main()

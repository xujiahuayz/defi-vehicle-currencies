from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ddvc.analysis.dynamics import value_at_day_offset


class CalendarDynamicsTests(unittest.TestCase):
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

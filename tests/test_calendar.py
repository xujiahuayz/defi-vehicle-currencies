from __future__ import annotations

import unittest

from ddvc.calendar import nearest_monthly_days


class SamplingCalendarTests(unittest.TestCase):
    def test_nearest_monthly_day_prefers_earlier_date_on_a_tie(self) -> None:
        days = ["20200117", "20200113", "20200220", "20200214"]
        self.assertEqual(
            nearest_monthly_days(days),
            ["20200113", "20200214"],
        )

    def test_calendar_deduplicates_days_and_validates_target(self) -> None:
        self.assertEqual(
            nearest_monthly_days(["20200115", "20200115"]),
            ["20200115"],
        )
        with self.assertRaisesRegex(ValueError, "between 1 and 31"):
            nearest_monthly_days(["20200115"], target_day=0)


if __name__ == "__main__":
    unittest.main()

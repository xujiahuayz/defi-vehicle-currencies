from __future__ import annotations

import unittest

from scripts.build_counterfactual_dominance import counterfactual_days


class CounterfactualDominanceTests(unittest.TestCase):
    def test_default_calendar_is_one_nearest_midmonth_day_per_month(self) -> None:
        available = ["20200101", "20200114", "20200116", "20200202", "20200220"]

        self.assertEqual(counterfactual_days(available), ["20200114", "20200220"])

    def test_explicit_days_preserve_order_and_remove_duplicates_before_limit(self) -> None:
        self.assertEqual(
            counterfactual_days([], explicit=["20220115", "20210115", "20220115"], limit=2),
            ["20220115", "20210115"],
        )


if __name__ == "__main__":
    unittest.main()

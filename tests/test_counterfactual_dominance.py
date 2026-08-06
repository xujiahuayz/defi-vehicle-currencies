from __future__ import annotations

import unittest

import pandas as pd

from scripts.build_counterfactual_dominance import (
    classify_state_support,
    counterfactual_days,
)


class CounterfactualDominanceTests(unittest.TestCase):
    def test_default_calendar_is_one_nearest_midmonth_day_per_month(self) -> None:
        available = ["20200101", "20200114", "20200116", "20200202", "20200220"]

        self.assertEqual(counterfactual_days(available), ["20200114", "20200220"])

    def test_explicit_days_preserve_order_and_remove_duplicates_before_limit(self) -> None:
        self.assertEqual(
            counterfactual_days([], explicit=["20220115", "20210115", "20220115"], limit=2),
            ["20220115", "20210115"],
        )

    def test_state_support_distinguishes_adjacent_bridged_and_liquidity_replay(self) -> None:
        frame = pd.DataFrame(
            {
                "hop1_prior_state_gap_hours": [1, 2, 1],
                "hop2_prior_state_gap_hours": [1, 1, 1],
                "direct_prior_state_gap_hours": [1, 1, 1],
                "hop1_liquidity_events_replayed": [0, 0, 0],
                "hop2_liquidity_events_replayed": [0, 0, 1],
                "direct_liquidity_events_replayed": [0, 0, 0],
            }
        )
        self.assertEqual(
            classify_state_support(frame).tolist(),
            [
                "adjacent_no_liquidity",
                "bridged_no_liquidity",
                "liquidity_replayed",
            ],
        )


if __name__ == "__main__":
    unittest.main()

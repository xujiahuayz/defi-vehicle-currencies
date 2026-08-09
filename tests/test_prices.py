from __future__ import annotations

import unittest

import pandas as pd

from ddvc.prices import day_price_frame, day_prices


class DayPriceTests(unittest.TestCase):
    def test_consensus_screened_volume_weighted_median(self) -> None:
        legs = pd.DataFrame(
            {
                "token_in": ["A", "A", "A"],
                "token_out": ["B", "B", "B"],
                "token_in_sym": ["AAA", "AAA", "AAA"],
                "token_out_sym": ["BBB", "BBB", "BBB"],
                "amount_in": [10.0, 50.0, 2.0],
                "amount_out": [10.0, 50.0, 1.0],
                "amount_usd": [10.0, 100.0, 1.0],
            }
        )
        prices = day_prices(legs)
        self.assertEqual(prices["a"], ("AAA", 2.0))
        self.assertEqual(prices["b"], ("BBB", 2.0))

    def test_high_weight_price_outlier_cannot_capture_the_estimate(self) -> None:
        legs = pd.DataFrame(
            {
                "token_in": ["A"] * 4,
                "token_out": ["B"] * 4,
                "token_in_sym": ["AAA"] * 4,
                "token_out_sym": ["BBB"] * 4,
                "amount_in": [10.0, 20.0, 30.0, 10.0],
                "amount_out": [10.0, 20.0, 30.0, 10.0],
                "amount_usd": [10.0, 20.0, 30.0, 1_000_000.0],
            }
        )
        prices = day_prices(legs)
        self.assertEqual(prices["a"], ("AAA", 1.0))
        self.assertEqual(prices["b"], ("BBB", 1.0))

    def test_incoherent_price_observations_are_rejected(self) -> None:
        legs = pd.DataFrame(
            {
                "token_in": ["A", "A", "A"],
                "token_out": ["B", "B", "B"],
                "token_in_sym": ["AAA", "AAA", "AAA"],
                "token_out_sym": ["BBB", "BBB", "BBB"],
                "amount_in": [1.0, 1.0, 1.0],
                "amount_out": [1.0, 1.0, 1.0],
                "amount_usd": [1.0, 100.0, 10_000.0],
            }
        )
        self.assertEqual(day_prices(legs), {})

    def test_missing_input_columns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "amount_out"):
            day_prices(pd.DataFrame({"amount_usd": [1.0]}))

    def test_price_frame_preserves_validation_evidence(self) -> None:
        legs = pd.DataFrame(
            {
                "token_in": ["A"] * 4,
                "token_out": ["B"] * 4,
                "token_in_sym": ["AAA"] * 4,
                "token_out_sym": ["BBB"] * 4,
                "amount_in": [10.0, 20.0, 30.0, 10.0],
                "amount_out": [10.0, 20.0, 30.0, 10.0],
                "amount_usd": [10.0, 20.0, 30.0, 1_000_000.0],
            }
        )

        frame = day_price_frame(legs).set_index("token")

        self.assertEqual(frame.loc["a", "price_usd"], 1.0)
        self.assertEqual(frame.loc["a", "n_observations"], 4)
        self.assertEqual(frame.loc["a", "n_consensus"], 3)
        self.assertEqual(frame.loc["a", "consensus_share"], 0.75)
        self.assertEqual(frame.loc["a", "price_source"], "canonical_repriced_route_legs")


if __name__ == "__main__":
    unittest.main()

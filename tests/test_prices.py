from __future__ import annotations

import unittest

import pandas as pd

from ddvc.prices import day_prices


class DayPriceTests(unittest.TestCase):
    def test_volume_weighted_median_and_minimum_support(self) -> None:
        legs = pd.DataFrame(
            {
                "token_in": ["A", "A", "A"],
                "token_out": ["B", "B", "B"],
                "token_in_sym": ["AAA", "AAA", "AAA"],
                "token_out_sym": ["BBB", "BBB", "BBB"],
                "amount_in": [10.0, 5.0, 2.0],
                "amount_out": [1.0, 1.0, 1.0],
                "amount_usd": [10.0, 100.0, 1.0],
            }
        )
        prices = day_prices(legs)
        self.assertEqual(prices["a"], ("AAA", 20.0))
        self.assertEqual(prices["b"], ("BBB", 100.0))

    def test_missing_input_columns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "amount_out"):
            day_prices(pd.DataFrame({"amount_usd": [1.0]}))


if __name__ == "__main__":
    unittest.main()

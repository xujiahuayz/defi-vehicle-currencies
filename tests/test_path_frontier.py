from __future__ import annotations

import unittest

from ddvc.pricing.path_frontier import LegQuote, best_public_path, best_vehicle_path


class PathFrontierTests(unittest.TestCase):
    @staticmethod
    def quote_legs(token_in: str, token_out: str, amount_in: float) -> list[LegQuote]:
        rates = {
            ("a", "b"): 0.8,
            ("a", "k"): 0.95,
            ("k", "b"): 0.95,
        }
        rate = rates.get((token_in, token_out))
        if rate is None:
            return []
        return [LegQuote(amount_in * rate, "venue", f"{token_in}{token_out}", 1.0 - rate)]

    def test_fixed_vehicle_is_sequential(self) -> None:
        quote = best_vehicle_path("a", "b", "k", 100.0, quote_legs=self.quote_legs)
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertAlmostEqual(quote.amount_out, 90.25)
        self.assertEqual(quote.vehicle, "k")
        self.assertEqual(quote.pools, ("ak", "kb"))

    def test_public_path_nests_direct_and_vehicle(self) -> None:
        quote = best_public_path("a", "b", ["k"], 100.0, quote_legs=self.quote_legs)
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertAlmostEqual(quote.amount_out, 90.25)
        self.assertEqual(quote.vehicle, "k")

    def test_smaller_first_leg_survives_second_leg_support(self) -> None:
        def quote_legs(token_in: str, token_out: str, amount_in: float) -> list[LegQuote]:
            if (token_in, token_out) == ("a", "k"):
                return [
                    LegQuote(100.0, "v", "large", 0.01),
                    LegQuote(90.0, "v", "small", 0.02),
                ]
            if (token_in, token_out) == ("k", "b") and amount_in <= 90.0:
                return [LegQuote(85.0, "v", "second", 0.03)]
            return []

        quote = best_vehicle_path("a", "b", "k", 100.0, quote_legs=quote_legs)
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote.pools, ("small", "second"))
        self.assertEqual(quote.amount_out, 85.0)


if __name__ == "__main__":
    unittest.main()

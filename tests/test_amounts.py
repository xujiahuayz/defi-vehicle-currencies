from __future__ import annotations

import unittest

from ddvc.amounts import human_to_raw


class AmountTests(unittest.TestCase):
    def test_human_to_raw_preserves_more_than_decimal_context_precision(self) -> None:
        self.assertEqual(
            human_to_raw("134659708639.360367020044220053", 18),
            "134659708639360367020044220053",
        )

    def test_human_to_raw_rejects_sub_base_unit_fraction(self) -> None:
        self.assertIsNone(human_to_raw("0.0000001", 6))

    def test_human_to_raw_keeps_sign_and_trailing_zero_exponent(self) -> None:
        self.assertEqual(human_to_raw("-1.2300", 6), "-1230000")
        self.assertEqual(human_to_raw("0E-100", 18), "0")

    def test_human_to_raw_rejects_non_finite_and_invalid_decimals(self) -> None:
        self.assertIsNone(human_to_raw("NaN", 18))
        self.assertIsNone(human_to_raw("Infinity", 18))
        self.assertIsNone(human_to_raw("1", -1))


if __name__ == "__main__":
    unittest.main()

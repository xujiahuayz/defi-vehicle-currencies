from __future__ import annotations

import unittest

from scripts.verify.validate_v4_quoter import resolve_validation_days


class V4ValidationDayTests(unittest.TestCase):
    def test_default_uses_last_available_day(self) -> None:
        self.assertEqual(
            resolve_validation_days(None, ["20250101", "20250102"]),
            ["20250102"],
        )

    def test_explicit_days_are_deduplicated_in_order(self) -> None:
        self.assertEqual(
            resolve_validation_days(
                ["20250102", "20250101", "20250102"],
                ["20250101", "20250102"],
            ),
            ["20250102", "20250101"],
        )

    def test_unavailable_day_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "20250103"):
            resolve_validation_days(["20250103"], ["20250101", "20250102"])

if __name__ == "__main__":
    unittest.main()

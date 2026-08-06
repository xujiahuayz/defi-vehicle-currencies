from __future__ import annotations

import unittest

from scripts.validate_v4_quoter import iter_pretrade_states, resolve_validation_days


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

    def test_liquidity_changes_are_replayed_between_swaps(self) -> None:
        def row(block: int, log_index: int, **values: object) -> dict[str, object]:
            return {
                "transaction": {"blockNumber": str(block), "timestamp": str(block)},
                "logIndex": str(log_index),
                **values,
            }

        swaps = [row(1, 1), row(2, 3), row(3, 3)]
        changes = [
            row(2, 2, amount="5", tickLower="0", tickUpper="10"),
            row(3, 2, amount="7", tickLower="0", tickUpper="10"),
        ]
        states = list(iter_pretrade_states(swaps, changes, {0: 10}))
        self.assertEqual(states[0][2], {0: 15, 10: -5})
        self.assertEqual(states[1][2], {0: 22, 10: -12})


if __name__ == "__main__":
    unittest.main()

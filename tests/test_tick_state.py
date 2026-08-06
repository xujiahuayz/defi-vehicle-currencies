from __future__ import annotations

import unittest

from ddvc.pricing.tick_state import apply_tick_change, iter_pretrade_states


def row(block: int, log_index: int, **values: object) -> dict[str, object]:
    return {
        "transaction": {"blockNumber": str(block), "timestamp": str(block)},
        "logIndex": str(log_index),
        **values,
    }


class TickStateTests(unittest.TestCase):
    def test_signed_liquidity_changes_are_replayed_between_swaps(self) -> None:
        swaps = [row(1, 1), row(2, 3), row(3, 3)]
        changes = [
            (1, row(2, 2, amount="5", tickLower="0", tickUpper="10")),
            (-1, row(3, 2, amount="3", tickLower="0", tickUpper="10")),
        ]
        states = list(iter_pretrade_states(swaps, changes, {0: 10}))
        self.assertEqual(states[0][2], {0: 15, 10: -5})
        self.assertEqual(states[1][2], {0: 12, 10: -2})

    def test_zeroed_boundary_ticks_are_removed(self) -> None:
        ticks = {0: 5, 10: -5}
        apply_tick_change(
            ticks,
            row(1, 1, amount="5", tickLower="0", tickUpper="10"),
            sign=-1,
        )
        self.assertEqual(ticks, {})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from decimal import Decimal

from ddvc.cpquote import (
    all_in_direct_advantage_bps,
    hour_is_clean,
    ordered_reserve_events,
    reserve_state_before,
    unwind_hour,
)


class ConstantProductStateTests(unittest.TestCase):
    def test_two_hop_gas_increases_the_direct_route_advantage(self) -> None:
        adjusted = all_in_direct_advantage_bps(
            -10.0,
            direct_legs=1,
            vehicle_legs=2,
            notional_usd=1_000.0,
            gas_price_gwei=25.8,
            eth_usd=2_500.0,
        )
        self.assertIsNotNone(adjusted)
        assert adjusted is not None
        self.assertGreater(adjusted, -10.0)

    def test_ordered_state_lookup_uses_strict_block_log_order(self) -> None:
        swaps = [
            ((100, 5), (Decimal("10"), Decimal("-9"))),
            ((100, 9), (Decimal("20"), Decimal("-18"))),
        ]
        events = ordered_reserve_events(
            (Decimal("1030"), Decimal("973")),
            swaps,
        )
        self.assertEqual(events[0].before, (Decimal("1000"), Decimal("1000")))
        self.assertEqual(events[0].after, (Decimal("1010"), Decimal("991")))
        self.assertEqual(events[1].before, events[0].after)
        self.assertEqual(events[1].after, (Decimal("1030"), Decimal("973")))
        self.assertEqual(
            reserve_state_before(events, (100, 5)),
            (Decimal("1000"), Decimal("1000")),
        )
        self.assertEqual(
            reserve_state_before(events, (100, 7)),
            (Decimal("1010"), Decimal("991")),
        )
        self.assertEqual(
            reserve_state_before(events, (100, 9)),
            (Decimal("1010"), Decimal("991")),
        )
        self.assertEqual(
            reserve_state_before(events, (100, 10)),
            (Decimal("1030"), Decimal("973")),
        )

    def test_canonical_unwind_and_cleanliness_share_the_same_deltas(self) -> None:
        deltas = [
            (Decimal("10"), Decimal("-9")),
            (Decimal("20"), Decimal("-18")),
        ]
        stored = (Decimal("1030"), Decimal("973"))
        self.assertEqual(
            unwind_hour(stored, deltas),
            [
                (Decimal("1000"), Decimal("1000")),
                (Decimal("1010"), Decimal("991")),
            ],
        )
        self.assertTrue(
            hour_is_clean((Decimal("1000"), Decimal("1000")), stored, deltas)
        )
        self.assertFalse(
            hour_is_clean((Decimal("999"), Decimal("1000")), stored, deltas)
        )
        self.assertFalse(hour_is_clean(None, stored, deltas))
        self.assertFalse(
            hour_is_clean((Decimal("0"), Decimal("1000")), stored, deltas)
        )


if __name__ == "__main__":
    unittest.main()

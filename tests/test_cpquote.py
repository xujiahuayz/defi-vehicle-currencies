from __future__ import annotations

import unittest
from decimal import Decimal

from ddvc.cpquote import (
    all_in_direct_advantage_bps,
    all_in_direct_advantage_bps_from_units,
    apply_reserve_deltas,
    cost_gap_bps,
    hour_is_clean,
    ordered_reserve_events,
    prior_observed_state,
    reserve_state_before,
    unwind_hour,
)


class ConstantProductStateTests(unittest.TestCase):
    def test_output_cost_gap_is_price_free_and_signed(self) -> None:
        self.assertAlmostEqual(cost_gap_bps(Decimal("110"), Decimal("100")), 1_000.0)
        self.assertAlmostEqual(cost_gap_bps(Decimal("90"), Decimal("100")), -1_000.0)
        self.assertIsNone(cost_gap_bps(Decimal("110"), Decimal("0")))

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

    def test_topology_wrapper_delegates_to_explicit_gas_units(self) -> None:
        topology = all_in_direct_advantage_bps(
            5.0,
            direct_legs=1,
            vehicle_legs=2,
            notional_usd=10_000.0,
            gas_price_gwei=20.0,
            eth_usd=2_500.0,
        )
        explicit = all_in_direct_advantage_bps_from_units(
            5.0,
            direct_gas_units=154_604,
            vehicle_gas_units=228_701,
            notional_usd=10_000.0,
            gas_price_gwei=20.0,
            eth_usd=2_500.0,
        )
        self.assertEqual(topology, explicit)

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

    def test_liquidity_events_share_the_ordered_reserve_timeline(self) -> None:
        changes = [
            ((100, 5), (Decimal("10"), Decimal("-9"))),
            ((100, 7), (Decimal("100"), Decimal("100"))),
        ]
        stored = (Decimal("1110"), Decimal("1091"))
        events = ordered_reserve_events(stored, changes)
        self.assertEqual(
            reserve_state_before(events, (100, 6)),
            (Decimal("1010"), Decimal("991")),
        )
        self.assertEqual(
            reserve_state_before(events, (100, 8)),
            stored,
        )
        self.assertFalse(
            hour_is_clean(
                (Decimal("1000"), Decimal("1000")),
                stored,
                [changes[0][1]],
            )
        )
        self.assertTrue(
            hour_is_clean(
                (Decimal("1000"), Decimal("1000")),
                stored,
                [delta for _order, delta in changes],
            )
        )
        self.assertEqual(
            apply_reserve_deltas(
                (Decimal("1000"), Decimal("1000")),
                [delta for _order, delta in changes],
            ),
            stored,
        )

    def test_duplicate_reserve_events_are_idempotent_and_conflicts_fail(self) -> None:
        delta = (Decimal("10"), Decimal("-9"))
        events = ordered_reserve_events(
            (Decimal("1010"), Decimal("991")),
            [((100, 5), delta), ((100, 5), delta)],
        )
        self.assertEqual(len(events), 1)
        with self.assertRaisesRegex(ValueError, "conflicting reserve changes"):
            ordered_reserve_events(
                (Decimal("1010"), Decimal("991")),
                [((100, 5), delta), ((100, 5), (Decimal("11"), Decimal("-9")))],
            )

    def test_prior_observed_state_advances_across_sparse_periods(self) -> None:
        observed = {
            0: (Decimal("1000"), Decimal("1000")),
            3: (Decimal("1060"), Decimal("970")),
        }
        deltas = {
            1: [(Decimal("10"), Decimal("-5"))],
            2: [(Decimal("20"), Decimal("-10"))],
            3: [(Decimal("30"), Decimal("-15"))],
        }
        self.assertEqual(
            prior_observed_state(observed, deltas, 3),
            ((Decimal("1030"), Decimal("985")), 0),
        )
        self.assertIsNone(prior_observed_state({3: observed[3]}, deltas, 3))

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

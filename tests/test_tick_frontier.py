from __future__ import annotations

import unittest

from ddvc.pricing.tick_frontier import (
    best_tick_public_path,
    best_tick_vehicle_path,
    build_pool_index,
    quote_tick_path,
)
from ddvc.pricing.tick_state import TickPoolState


def state(pool: str, token0: str, token1: str, fee: int) -> TickPoolState:
    return TickPoolState(
        pool=pool,
        token0=token0,
        token1=token1,
        sym0=token0,
        sym1=token1,
        dec0=18,
        dec1=18,
        sqrt_price_x96=1 << 96,
        tick=0,
        fee_pips=fee,
        tick_spacing=60,
        block=1,
        log_index=1,
    )


class TickFrontierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.states = {
            "v3": {
                "ak": state("ak", "a", "k", 500),
                "kb": state("kb", "k", "b", 500),
                "ab": state("ab", "a", "b", 10_000),
            }
        }
        self.ticks = {
            "v3": {
                pool: {-600: 10**25, 600: -(10**25)}
                for pool in self.states["v3"]
            }
        }
        self.index = build_pool_index(self.states)

    def test_public_frontier_nests_the_same_vehicle_frontier(self) -> None:
        vehicle = best_tick_vehicle_path(
            "a",
            "b",
            "k",
            1.0,
            pool_index=self.index,
            states_by_venue=self.states,
            ticks_by_venue=self.ticks,
            allowed_venues=None,
            max_price_impact=0.05,
        )
        public = best_tick_public_path(
            "a",
            "b",
            ["k"],
            1.0,
            pool_index=self.index,
            states_by_venue=self.states,
            ticks_by_venue=self.ticks,
            allowed_venues=None,
            max_price_impact=0.05,
        )
        self.assertIsNotNone(vehicle)
        self.assertIsNotNone(public)
        assert vehicle is not None and public is not None
        self.assertGreaterEqual(public.amount_out, vehicle.amount_out)

    def test_observed_reach_restriction_can_remove_the_frontier(self) -> None:
        quote = best_tick_vehicle_path(
            "a",
            "b",
            "k",
            1.0,
            pool_index=self.index,
            states_by_venue=self.states,
            ticks_by_venue=self.ticks,
            allowed_venues={"v4"},
            max_price_impact=0.05,
        )
        self.assertIsNone(quote)

    def test_identified_path_quotes_the_declared_pools_in_sequence(self) -> None:
        quote = quote_tick_path(
            "a",
            "b",
            "k",
            1.0,
            venues=("v3", "v3"),
            pools=("ak", "kb"),
            states_by_venue=self.states,
            ticks_by_venue=self.ticks,
            max_price_impact=None,
        )
        self.assertIsNotNone(quote)
        assert quote is not None
        self.assertEqual(quote.pools, ("ak", "kb"))
        self.assertGreater(quote.amount_out, 0)


if __name__ == "__main__":
    unittest.main()

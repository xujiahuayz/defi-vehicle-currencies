from __future__ import annotations

import unittest

from ddvc.analysis.transaction_frontier import RealisedTickPath, score_tick_frontier
from ddvc.pricing.tick_frontier import build_pool_index, quote_tick_path
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


class TransactionFrontierTests(unittest.TestCase):
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
        chosen = quote_tick_path(
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
        assert chosen is not None
        self.route = RealisedTickPath(
            "a", "b", "k", 1.0, chosen.amount_out, ("v3", "v3"), ("ak", "kb")
        )

    def test_validated_frontiers_are_nested(self) -> None:
        score = score_tick_frontier(
            self.route,
            vehicles=("k",),
            pool_index=self.index,
            states_by_venue=self.states,
            ticks_by_venue=self.ticks,
            max_price_impact=0.05,
            validation_tolerance=0.01,
        )
        self.assertIsNotNone(score)
        assert score is not None
        self.assertAlmostEqual(float(score["chosen_validation_error_bps"]), 0.0)
        self.assertLessEqual(
            float(score["within_reach_search_regret_bps"]),
            float(score["public_reach_same_vehicle_regret_bps"]),
        )
        self.assertLessEqual(
            float(score["public_reach_same_vehicle_regret_bps"]),
            float(score["public_path_regret_bps"]),
        )

    def test_route_that_fails_exact_output_validation_is_quarantined(self) -> None:
        corrupted = RealisedTickPath(
            self.route.token_in,
            self.route.token_out,
            self.route.vehicle,
            self.route.amount_in,
            2.0 * self.route.amount_out,
            self.route.venues,
            self.route.pools,
        )
        score = score_tick_frontier(
            corrupted,
            vehicles=("k",),
            pool_index=self.index,
            states_by_venue=self.states,
            ticks_by_venue=self.ticks,
            max_price_impact=0.05,
            validation_tolerance=0.01,
        )
        self.assertIsNone(score)

    def test_public_frontier_retains_a_realised_noncandidate_vehicle(self) -> None:
        score = score_tick_frontier(
            self.route,
            vehicles=(),
            pool_index=self.index,
            states_by_venue=self.states,
            ticks_by_venue=self.ticks,
            max_price_impact=0.05,
            validation_tolerance=0.01,
        )
        self.assertIsNotNone(score)
        assert score is not None
        self.assertGreaterEqual(
            float(score["public_path_regret_bps"]),
            float(score["public_reach_same_vehicle_regret_bps"]),
        )


if __name__ == "__main__":
    unittest.main()

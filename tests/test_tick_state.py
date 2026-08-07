from __future__ import annotations

import unittest

from ddvc.pricing.tick_state import (
    absorb_swap_state,
    apply_tick_change,
    iter_pretrade_states,
)


def row(block: int, log_index: int, **values: object) -> dict[str, object]:
    return {
        "transaction": {"blockNumber": str(block), "timestamp": str(block)},
        "logIndex": str(log_index),
        **values,
    }


class TickStateTests(unittest.TestCase):
    def test_v4_swap_state_is_owned_by_the_shared_replay_module(self) -> None:
        record = row(
            5,
            7,
            sqrtPriceX96=str(1 << 96),
            tick="0",
            pool={
                "id": "pool",
                "feeTier": "9000",
                "tickSpacing": "180",
                "hooks": "0x0000000000000000000000000000000000000000",
                "token0": {
                    "id": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                    "symbol": "USDC",
                    "decimals": "6",
                },
                "token1": {
                    "id": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
                    "symbol": "WETH",
                    "decimals": "18",
                },
            },
        )
        state = {}
        absorb_swap_state("uniswap_v4", record, state, swap_samples={})
        self.assertEqual(state["pool"].tick_spacing, 180)
        self.assertEqual((state["pool"].block, state["pool"].log_index), (5, 7))

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

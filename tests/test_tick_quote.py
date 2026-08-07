from __future__ import annotations

import unittest

from ddvc.pricing.tick_quote import prepare_tick_quote_index, quote_tick_state
from ddvc.pricing.tick_state import TickPoolState


class TickQuoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = TickPoolState(
            pool="pool",
            token0="a",
            token1="b",
            sym0="A",
            sym1="B",
            dec0=18,
            dec1=18,
            sqrt_price_x96=1 << 96,
            tick=0,
            fee_pips=3_000,
            tick_spacing=60,
            block=1,
            log_index=1,
        )
        self.ticks = {-600: 10**24, 600: -(10**24)}

    def test_quotes_human_units_in_both_directions(self) -> None:
        forward = quote_tick_state(
            self.state,
            self.ticks,
            "a",
            "b",
            1.0,
            max_price_impact=0.05,
        )
        reverse = quote_tick_state(
            self.state,
            self.ticks,
            "b",
            "a",
            1.0,
            max_price_impact=0.05,
        )
        self.assertIsNotNone(forward)
        self.assertIsNotNone(reverse)
        assert forward is not None and reverse is not None
        self.assertGreater(forward.amount_out, 0)
        self.assertGreater(reverse.amount_out, 0)

    def test_rejects_wrong_pair_and_impact_outside_support(self) -> None:
        self.assertIsNone(
            quote_tick_state(
                self.state,
                self.ticks,
                "a",
                "c",
                1.0,
                max_price_impact=0.05,
            )
        )

    def test_prepared_index_is_quote_equivalent(self) -> None:
        plain = quote_tick_state(
            self.state,
            self.ticks,
            "a",
            "b",
            1.0,
            max_price_impact=0.05,
        )
        prepared = prepare_tick_quote_index(self.ticks)
        indexed = quote_tick_state(
            self.state,
            self.ticks,
            "a",
            "b",
            1.0,
            max_price_impact=0.05,
            prepared=prepared,
        )
        self.assertEqual(plain, indexed)
        self.assertEqual(prepared.active_liquidity(0), 10**24)
        self.assertIsNone(
            quote_tick_state(
                self.state,
                self.ticks,
                "a",
                "b",
                10_000.0,
                max_price_impact=0.000001,
            )
        )


if __name__ == "__main__":
    unittest.main()

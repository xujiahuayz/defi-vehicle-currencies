import unittest

from ddvc.pricing.v3quote import get_sqrt_ratio_at_tick, quote_exact_input


class V3QuoteTests(unittest.TestCase):
    def test_fee_reduces_active_range_output(self) -> None:
        base = dict(
            zero_for_one=False,
            amount_in=10**18,
            sqrt_price_x96=get_sqrt_ratio_at_tick(0),
            liquidity=10**24,
            tick_net={},
            tick_spacing=60,
        )
        no_fee = quote_exact_input(**base, fee_pips=0)
        with_fee = quote_exact_input(**base, fee_pips=3000)

        self.assertGreater(no_fee.amount_out, 0)
        self.assertGreater(with_fee.amount_out, 0)
        self.assertLess(with_fee.amount_out, no_fee.amount_out)

    def test_crosses_initialized_tick(self) -> None:
        quote = quote_exact_input(
            zero_for_one=False,
            amount_in=10**22,
            sqrt_price_x96=get_sqrt_ratio_at_tick(0),
            liquidity=10**18,
            tick_net={60: 10**18},
            tick_spacing=60,
            fee_pips=0,
        )

        self.assertGreaterEqual(quote.crossed_ticks, 1)
        self.assertGreater(quote.amount_out, 0)


if __name__ == "__main__":
    unittest.main()

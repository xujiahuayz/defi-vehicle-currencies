import importlib.util
import sys
import unittest
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from ddvc.pricing.weighted import (
    ONE,
    BalanceEvent,
    WeightedPool,
    quote_exact_input,
    rebuild_pre_trade_balances,
)


@lru_cache(maxsize=1)
def _panel():
    """The route-cost panel module, imported by path because it is a script."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_route_cost_panel.py"
    spec = importlib.util.spec_from_file_location("run_route_cost_panel", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_route_cost_panel"] = module
    spec.loader.exec_module(module)
    return module


def _pool(**kwargs) -> WeightedPool:
    base = dict(
        pool_id="test",
        tokens=("0xaa", "0xbb"),
        balances=(1000 * 10 ** 18, 2000 * 10 ** 18),
        decimals=(18, 18),
        weights=(ONE // 2, ONE // 2),
        fee=3 * 10 ** 15,
    )
    base.update(kwargs)
    return WeightedPool(**base)


class WeightedQuoteTests(unittest.TestCase):
    def test_equal_weights_reproduce_constant_product(self) -> None:
        """The whole claim of the module: Uniswap's curve is the equal-weight special case.

        With W_in = W_out the exponent is one and the weighted form collapses to the v2 reserve
        formula, so a mismatch here means the exponent, the fee rounding or the decimals scaling
        is wrong. The token decimals differ by twelve on purpose, because that is the size of the
        scaling error that reversed a v3 validation earlier in this project.
        """
        pool = _pool(balances=(1000 * 10 ** 18, 2000 * 10 ** 6), decimals=(18, 6))
        amount_in = 10 ** 18
        fee_amount = -(-amount_in * pool.fee // ONE)
        net_in = amount_in - fee_amount
        reserve_in, reserve_out = 1000 * 10 ** 18, 2000 * 10 ** 18
        expected = (reserve_out * net_in // (reserve_in + net_in)) // 10 ** 12

        self.assertEqual(quote_exact_input(pool, "0xaa", "0xbb", amount_in), expected)

    def test_fee_reduces_output(self) -> None:
        pool = _pool()
        no_fee = quote_exact_input(_pool(fee=0), "0xaa", "0xbb", 10 ** 18)
        with_fee = quote_exact_input(pool, "0xaa", "0xbb", 10 ** 18)

        self.assertGreater(with_fee, 0)
        self.assertLess(with_fee, no_fee)

    def test_unquotable_cases_return_none(self) -> None:
        pool = _pool()

        self.assertIsNone(quote_exact_input(pool, "0xcc", "0xbb", 10 ** 18))
        self.assertIsNone(quote_exact_input(pool, "0xaa", "0xaa", 10 ** 18))
        self.assertIsNone(quote_exact_input(pool, "0xaa", "0xbb", 0))
        self.assertIsNone(quote_exact_input(_pool(weights=(0, 0)), "0xaa", "0xbb", 10 ** 18))
        self.assertIsNone(quote_exact_input(_pool(balances=(0, 10 ** 18)),
                                           "0xaa", "0xbb", 10 ** 18))

    def test_rejects_over_the_vault_in_ratio(self) -> None:
        """A swap paying in more than 30% of the input balance reverts, so it has no price."""
        pool = _pool(balances=(100 * 10 ** 18, 100 * 10 ** 18))

        self.assertIsNotNone(quote_exact_input(pool, "0xaa", "0xbb", 29 * 10 ** 18))
        self.assertIsNone(quote_exact_input(pool, "0xaa", "0xbb", 31 * 10 ** 18))

    def test_weight_ratio_override_beats_pool_weights(self) -> None:
        pool = _pool()
        read = quote_exact_input(pool, "0xaa", "0xbb", 10 ** 18)
        overridden = quote_exact_input(pool, "0xaa", "0xbb", 10 ** 18,
                                       weight_ratio=Decimal(4))

        self.assertNotEqual(read, overridden)
        self.assertGreater(overridden, read)      # a heavier input side gives up more output

    def test_reconstruction_recovers_the_state_each_swap_faced(self) -> None:
        """Walking back from the closing snapshot has to land on the balances trades saw.

        Two swaps and a join in between, so the test fails if liquidity events are dropped from
        the walk, which was the defect that excluded good weighted pools.
        """
        opening = (100 * 10 ** 18, 200 * 10 ** 18)
        events = [
            BalanceEvent(deltas=(10 ** 18, -2 * 10 ** 18), is_swap=True),
            BalanceEvent(deltas=(50 * 10 ** 18, 100 * 10 ** 18), is_swap=False),
            BalanceEvent(deltas=(3 * 10 ** 18, -6 * 10 ** 18), is_swap=True),
        ]
        closing = tuple(sum(x) for x in zip(opening, *(e.deltas for e in events)))
        path = rebuild_pre_trade_balances(closing, events)

        self.assertEqual(len(path), 2)
        self.assertEqual(path[0], opening)
        self.assertEqual(path[1], (151 * 10 ** 18, 298 * 10 ** 18))

    def test_reconstruction_refuses_an_impossible_walk(self) -> None:
        events = [BalanceEvent(deltas=(10 ** 30, 0), is_swap=True)]

        self.assertIsNone(rebuild_pre_trade_balances((10 ** 18, 10 ** 18), events))


class BalancerPanelWiringTests(unittest.TestCase):
    """The panel has to actually quote a Balancer pool, not merely be able to hold one.

    This is a behavioural test on purpose. Renaming a pool kind from `v3_exact` to `tick_exact`
    while the dispatch still tested the old string made every concentrated-liquidity pool load,
    enter the pool dict, and then be skipped without quoting or raising, and the panel came out at
    123.8 million rows with no v3 or v4 in it at all, which looks exactly like a successful build.
    A field rename or a lost branch would do the same to Balancer, and a test that asserts a real
    number comes back cannot drift that way.
    """

    def _weighted_pool_entry(self):
        pool = WeightedPool(
            pool_id="0xpool",
            tokens=("0xaa", "0xbb"),
            balances=(80 * 10 ** 18, 200 * 10 ** 6),
            decimals=(18, 6),
            weights=(80 * ONE // 100, 20 * ONE // 100),
            fee=3 * 10 ** 15,
        )
        entry = _panel().Pool(
            source="balancer", pool="0xpool", kind="weighted",
            token0="0xaa", token1="0xbb", sym0="AA", sym1="BB",
            dec0=18, dec1=6, reserve0=0.0, reserve1=0.0, weighted=pool,
        )
        return {frozenset(("0xaa", "0xbb")): [entry]}

    def test_best_quote_prices_a_balancer_pool_in_both_directions(self) -> None:
        pools = self._weighted_pool_entry()

        out, source, pool_id = _panel()._best_quote(pools, "0xaa", "0xbb", 1.0)
        self.assertGreater(out, 0.0)
        self.assertEqual(source, "balancer")
        self.assertEqual(pool_id, "0xpool")

        back, source_back, _ = _panel()._best_quote(pools, "0xbb", "0xaa", 10.0)
        self.assertGreater(back, 0.0)
        self.assertEqual(source_back, "balancer")

    def test_best_quote_matches_the_quoter_on_the_same_state(self) -> None:
        """The panel's unit conversion has to agree with the quoter's raw units.

        A decimals slip here is silent and catastrophic, since it makes one venue quote 1e12 times
        too well and win every leg it appears on.
        """
        pools = self._weighted_pool_entry()
        entry = next(iter(pools.values()))[0]

        out, _, _ = _panel()._best_quote(pools, "0xaa", "0xbb", 1.0)
        direct = quote_exact_input(entry.weighted, "0xaa", "0xbb", 10 ** 18)

        self.assertEqual(out, direct / 10 ** 6)

    def test_weight_ratio_override_is_inverted_for_the_reverse_direction(self) -> None:
        """A fitted exponent is stored for token0 to token1, so the reverse must reciprocate it.

        Storing one ratio and applying it both ways would price one direction of every fitted pool
        on the wrong exponent, which is a wrong number and not a missing one.
        """
        pools = self._weighted_pool_entry()
        entry = next(iter(pools.values()))[0]
        fitted = {frozenset(("0xaa", "0xbb")): [
            _panel().Pool(**{**entry.__dict__, "weight_ratio": Decimal(4)})]}

        forward, _, _ = _panel()._best_quote(fitted, "0xaa", "0xbb", 1.0)
        expected_forward = quote_exact_input(entry.weighted, "0xaa", "0xbb", 10 ** 18,
                                            weight_ratio=Decimal(4))
        reverse, _, _ = _panel()._best_quote(fitted, "0xbb", "0xaa", 10.0)
        expected_reverse = quote_exact_input(entry.weighted, "0xbb", "0xaa", 10 * 10 ** 6,
                                             weight_ratio=1 / Decimal(4))

        self.assertEqual(forward, expected_forward / 10 ** 6)
        self.assertEqual(reverse, expected_reverse / 10 ** 18)

    def test_weighted_source_is_in_the_cache_fingerprint(self) -> None:
        """A quoter outside QUOTE_SOURCES means tightening its gate invalidates no cached day."""
        self.assertIn("src/ddvc/pricing/weighted.py", _panel().QUOTE_SOURCES)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import gzip
import json
import sys
import tempfile
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
from ddvc.state_data import write_multi_asset_partition
from scripts import validate_weighted_quoter


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


class BalancerCanonicalStateTests(unittest.TestCase):
    def test_validator_loads_raw_integer_state_and_events_from_canonical_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, state = root / "raw", root / "state"
            pool = {
                "id": "pool",
                "poolType": "Weighted",
                "swapFee": "0.003",
                "tokensList": ["0xaa", "0xbb"],
                "tokens": [
                    {"address": "0xaa", "symbol": "AA", "decimals": 18, "weight": "0.8"},
                    {"address": "0xbb", "symbol": "BB", "decimals": 6, "weight": "0.2"},
                ],
            }
            rows = {
                "daily": [{"id": "state", "timestamp": 100, "amounts": ["101", "198"], "pool": pool}],
                "swaps": [{
                    "id": "0x" + "1" * 64 + "7",
                    "tx": "0xswap",
                    "block": "10",
                    "timestamp": 99,
                    "poolId": {"id": "pool"},
                    "tokenIn": "0xaa",
                    "tokenOut": "0xbb",
                    "tokenAmountIn": "1",
                    "tokenAmountOut": "2",
                    "valueUSD": "10",
                }],
                "joins_exits": [],
            }
            for stream, records in rows.items():
                path = raw / "balancer" / f"balancer_{stream}_20250101.jsonl.gz"
                path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(path, "wt") as handle:
                    for record in records:
                        handle.write(json.dumps(record) + "\n")
            write_multi_asset_partition(raw, "balancer", "20250101", root=state)
            original = validate_weighted_quoter.MARKET_STATE
            original_source = validate_weighted_quoter.SOURCE_FINGERPRINT_ROOT
            try:
                validate_weighted_quoter.MARKET_STATE = state
                validate_weighted_quoter.SOURCE_FINGERPRINT_ROOT = raw
                validate_weighted_quoter._state.cache_clear()
                pools = validate_weighted_quoter.load_pools("20250101")
                events, volume = validate_weighted_quoter.load_events("20250101")
            finally:
                validate_weighted_quoter.MARKET_STATE = original
                validate_weighted_quoter.SOURCE_FINGERPRINT_ROOT = original_source
                validate_weighted_quoter._state.cache_clear()
        self.assertEqual(pools["pool"]["closing"], (101 * 10 ** 18, 198 * 10 ** 6))
        self.assertEqual(pools["pool"]["weights"], (8 * 10 ** 17, 2 * 10 ** 17))
        self.assertEqual(events["pool"][0][5:7], (10 ** 18, 2 * 10 ** 6))
        self.assertEqual(volume["pool"], 10.0)


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

    def test_shared_tick_quoter_is_in_the_cache_fingerprint(self) -> None:
        """Changing full-input or prepared-index logic must invalidate every tick quote."""
        self.assertIn("src/ddvc/pricing/tick_quote.py", _panel().QUOTE_SOURCES)

    def test_raw_and_unified_inputs_are_in_the_cache_fingerprint(self) -> None:
        """Changing routes or pool state must make the old day cache unreachable."""
        paths = {path.relative_to(_panel().ROOT).as_posix() for path in _panel().QUOTE_INPUTS}
        self.assertIn("data/unified", paths)
        self.assertIn("data/raw/thegraph/uniswap_v4", paths)

    def test_v4_schema_contract_requires_all_quote_statics(self) -> None:
        complete = {
            "pool": {
                "feeTier": "500",
                "tickSpacing": "10",
                "hooks": "0x0000000000000000000000000000000000000000",
                "token0": {"decimals": "18"},
                "token1": {"decimals": "6"},
            }
        }
        self.assertTrue(_panel().v4_statics_complete(complete))
        del complete["pool"]["token1"]["decimals"]
        self.assertFalse(_panel().v4_statics_complete(complete))

    def test_v4_state_uses_declared_tick_spacing_and_excludes_dynamic_fees(self) -> None:
        record = {
            "id": "swap-1",
            "transaction": {"id": "tx", "blockNumber": "1", "timestamp": "2"},
            "logIndex": "3",
            "sqrtPriceX96": str(1 << 96),
            "tick": "0",
            "pool": {
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
        }
        state = {}
        _panel()._absorb_swap_state("uniswap_v4", record, state)
        self.assertEqual(state["pool"].tick_spacing, 180)

        record["pool"]["id"] = "dynamic-pool"
        record["pool"]["feeTier"] = str(1 << 23)
        _panel()._absorb_swap_state("uniswap_v4", record, state)
        self.assertNotIn("dynamic-pool", state)

    def test_v4_schema_preflight_refuses_an_old_nonempty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.jsonl.gz"
            with gzip.open(path, "wt") as fh:
                fh.write(json.dumps({"pool": {"token0": {}, "token1": {}}}) + "\n")
            original = _panel()._raw_path
            try:
                _panel()._raw_path = lambda *_: path
                with self.assertRaisesRegex(RuntimeError, "lack fee/tick-spacing/hook"):
                    _panel()._validate_v4_swap_schema(["20250124"])
            finally:
                _panel()._raw_path = original

    def test_route_worker_count_is_bounded(self) -> None:
        self.assertEqual(_panel().bounded_route_workers(0), 1)
        self.assertEqual(_panel().bounded_route_workers(6), 6)
        self.assertEqual(_panel().bounded_route_workers(100), 10)


if __name__ == "__main__":
    unittest.main()

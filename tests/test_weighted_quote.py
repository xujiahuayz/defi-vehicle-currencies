import gzip
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ddvc.pricing.weighted import (
    ONE,
    BalanceEvent,
    WeightedPool,
    quote_exact_input,
    rebuild_pre_trade_balances,
)
from ddvc.state_data import read_multi_asset_partition, write_multi_asset_partition
from scripts.verify import validate_weighted_quoter

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
            frame = read_multi_asset_partition("balancer", "20250101", root=state, raw_root=raw)

            class Release:
                @staticmethod
                def read_day(day: str):
                    self.assertEqual(day, "20250101")
                    return frame.copy()

            pools = validate_weighted_quoter.load_pools("20250101", Release())
            events, volume = validate_weighted_quoter.load_events("20250101", Release())
        self.assertEqual(pools["pool"]["closing"], (101 * 10 ** 18, 198 * 10 ** 6))
        self.assertEqual(pools["pool"]["weights"], (8 * 10 ** 17, 2 * 10 ** 17))
        self.assertEqual(events["pool"][0][5:7], (10 ** 18, 2 * 10 ** 6))
        self.assertEqual(volume["pool"], 10.0)


class AppendixTierIncidenceTests(unittest.TestCase):
    """The appendix reports how often each acceptance tier binds, so it must reconcile.

    The three tiers of the acceptance rule are not decoration: they say that four fifths of
    the priced Balancer sample is quoted on parameters read from the source and that the
    fitting machinery repairs a minority. That reading is what makes the counterfactual
    credible, and it moves whenever the validation is rerun on different days. Nothing else
    checks it, because the paper's evidence test deliberately verifies that a number cites
    an artefact and not that it matches one.
    """

    EXHIBIT = Path(__file__).resolve().parents[1] / "output" / "exhibits" / "weighted_quoter_validation.jsonl"
    APPENDIX = Path(__file__).resolve().parents[1] / "paper" / "sections" / "08-appendix.tex"

    def _rows(self) -> list[dict]:
        if not self.EXHIBIT.is_file():
            self.skipTest(f"{self.EXHIBIT.name} is not materialised in this checkout")
        return [json.loads(line) for line in self.EXHIBIT.read_text().splitlines() if line.strip()]

    def test_fit_modes_partition_the_priced_pool_days(self) -> None:
        rows = self._rows()
        modes: dict[str, int] = {}
        for row in rows:
            for mode, count in json.loads(row["pools_by_fit_mode"]).items():
                modes[mode] = modes.get(mode, 0) + count
        self.assertEqual(sum(modes.values()), sum(row["pools_priced"] for row in rows))
        self.assertLessEqual(set(modes), {"reported", "fee_fitted", "weight_fitted"})

    def test_appendix_states_the_measured_tier_incidence(self) -> None:
        rows = self._rows()
        modes: dict[str, int] = {}
        for row in rows:
            for mode, count in json.loads(row["pools_by_fit_mode"]).items():
                modes[mode] = modes.get(mode, 0) + count
        priced = sum(row["pools_priced"] for row in rows)
        body = self.APPENDIX.read_text(encoding="utf-8")
        sentence = (
            f"Of the {priced} pool-days accepted across the twelve validation days, "
            f"{modes.get('reported', 0)} clear the gate on reported parameters with nothing "
            f"identified, {modes.get('fee_fitted', 0)} need the swap fee alone, and "
            f"{modes.get('weight_fitted', 0)} need per-token-pair weight ratios."
        )
        self.assertIn(sentence, body)
        self.assertEqual(len(rows), 12)


if __name__ == "__main__":
    unittest.main()

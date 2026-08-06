"""Taxonomy invariants, including the backing dimension added by node C round 2.

The backing cross is not decoration. `docs/node-c-definitions-round2.md` section 3
records that the corpus cuts stablecoins by backing regime and that four of its papers
exist because the regimes behave differently, so a `stable` bucket that pools USDC with
USDe is pooling across the cut the literature treats as the interesting one.
"""

from __future__ import annotations

from datetime import date
import unittest

from ddvc.asset_types import (
    BACKINGS,
    NATIVE_ETH,
    NON_USD_STABLE,
    STABLE,
    STABLE_BACKING,
    TYPES,
    asset_type,
    backing,
    canonical_token,
)


class BackingRegimeTests(unittest.TestCase):
    def test_every_stable_ticker_has_a_backing_regime(self) -> None:
        missing = sorted(set(STABLE.values()) - set(STABLE_BACKING))
        self.assertEqual(missing, [], f"stable tickers with no backing regime: {missing}")

    def test_declared_backings_are_all_in_the_enumeration(self) -> None:
        unknown = sorted(set(STABLE_BACKING.values()) - set(BACKINGS))
        self.assertEqual(unknown, [])

    def test_non_usd_stables_are_flagged_on_both_axes(self) -> None:
        for sym in NON_USD_STABLE:
            self.assertEqual(STABLE_BACKING[sym], "non_usd")

    def test_backing_separates_the_regimes_the_corpus_separates(self) -> None:
        usdc = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        dai = "0x6b175474e89094c44da98b954eedeac495271d0f"
        usde = "0x4c9edd5852cd905f086c759e8383e09bff1e68b3"
        frax = "0x853d955acef822db058eb8505911ed77f175b99e"
        self.assertEqual(asset_type(usdc), "stable")
        self.assertEqual(
            [backing(usdc), backing(dai), backing(usde), backing(frax)],
            ["fiat_reserve", "time_varying", "synthetic", "time_varying"],
        )

    def test_dai_backing_uses_dated_composition_regimes(self) -> None:
        dai = "0x6b175474e89094c44da98b954eedeac495271d0f"
        self.assertEqual(backing(dai, date(2020, 3, 16)), "on_chain_collateralized")
        self.assertEqual(backing(dai, date(2020, 3, 17)), "mixed_with_fiat_stablecoin")
        self.assertEqual(backing(dai, date(2021, 4, 15)), "mixed_with_fiat_stablecoin")
        self.assertEqual(backing(dai, date(2021, 4, 16)), "mixed_including_rwa")

    def test_usds_inherits_the_post_rwa_maker_backing_pool(self) -> None:
        usds = "0xdc035d45d973e3ec169d2276ddab16f1e407384f"
        self.assertEqual(backing(usds, date(2024, 9, 18)), "mixed_including_rwa")

    def test_susd_is_a_synthetic_debt_pool_not_crypto_collateral(self) -> None:
        susd = "0x57ab1ec28d129707052df4df418d58a2d46d5f51"
        self.assertEqual(backing(susd, date(2021, 1, 1)), "synthetic")

    def test_frax_changes_after_the_full_collateralization_target_vote(self) -> None:
        frax = "0x853d955acef822db058eb8505911ed77f175b99e"
        self.assertEqual(backing(frax), "time_varying")
        self.assertEqual(backing(frax, date(2023, 2, 22)), "fractional_algorithmic")
        self.assertEqual(
            backing(frax, date(2023, 2, 23)),
            "transition_to_full_exogenous_collateralization",
        )

    def test_backing_is_not_applicable_outside_the_stable_type(self) -> None:
        weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
        wbtc = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
        self.assertEqual(backing(weth), "not_applicable")
        self.assertEqual(backing(wbtc), "not_applicable")
        self.assertEqual(backing("0xdeadbeef"), "not_applicable")
        self.assertEqual(backing(None), "not_applicable")
        self.assertEqual(backing(float("nan")), "not_applicable")

    def test_backing_is_case_insensitive_like_classify(self) -> None:
        self.assertEqual(
            backing("0xA0B86991C6218B36C1D19D4A2E9EB0CE3606EB48"),
            "fiat_reserve",
        )


class TypeAxisTests(unittest.TestCase):
    def test_the_type_axis_is_unchanged_by_the_backing_addition(self) -> None:
        self.assertEqual(TYPES, ("native", "staked_native", "stable", "imported", "other"))

    def test_native_eth_collapses_onto_weth_only_when_asked(self) -> None:
        weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
        self.assertEqual(canonical_token(NATIVE_ETH), weth)
        self.assertEqual(canonical_token(NATIVE_ETH, unify_wrapped=False), NATIVE_ETH)


if __name__ == "__main__":
    unittest.main()

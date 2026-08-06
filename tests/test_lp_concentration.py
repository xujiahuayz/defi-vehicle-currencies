from __future__ import annotations

import unittest

from ddvc.analysis.lp_concentration import (
    VEHICLE_CANDIDATES,
    _candidate_allocations,
    _pool_snapshot_from_record,
)


class CandidateLiquidityAllocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.address_by_symbol = {
            symbol: address for address, symbol in VEHICLE_CANDIDATES.items()
        }

    def test_candidate_universe_matches_the_main_panel(self) -> None:
        self.assertEqual(
            set(VEHICLE_CANDIDATES.values()),
            {"WETH", "USDC", "USDT", "DAI", "WBTC"},
        )

    def test_pool_with_one_candidate_allocates_all_tvl_to_it(self) -> None:
        weth = self.address_by_symbol["WETH"]
        allocations = _candidate_allocations(
            (weth, "WETH", "0xnotacandidate", "OTHER", 1_000.0)
        )
        self.assertEqual(allocations, ((weth, "WETH", 1.0),))

    def test_pool_with_two_candidates_splits_tvl_equally(self) -> None:
        weth = self.address_by_symbol["WETH"]
        usdc = self.address_by_symbol["USDC"]
        allocations = _candidate_allocations((weth, "WETH", usdc, "USDC", 1_000.0))
        self.assertEqual(
            allocations,
            ((weth, "WETH", 0.5), (usdc, "USDC", 0.5)),
        )
        self.assertEqual(sum(weight for _, _, weight in allocations), 1.0)

    def test_pool_without_a_candidate_is_excluded(self) -> None:
        self.assertEqual(
            _candidate_allocations(
                ("0xnotcandidate0", "OTHER0", "0xnotcandidate1", "OTHER1", 1_000.0)
            ),
            (),
        )

    def test_legacy_daily_schema_uses_exact_registry_addresses(self) -> None:
        weth = self.address_by_symbol["WETH"]
        pool_id = "0xpool"
        record = {
            "tvlUSD": "1000",
            "pool": {
                "id": pool_id,
                "token0": {"symbol": "OTHER"},
                "token1": {"symbol": "WETH"},
            },
        }
        registry = {
            pool_id: ("0xnotacandidate", "OTHER", weth, "WETH"),
        }

        resolved = _pool_snapshot_from_record(record, registry)

        self.assertEqual(
            resolved,
            (pool_id, ("0xnotacandidate", "OTHER", weth, "WETH", 1000.0)),
        )


if __name__ == "__main__":
    unittest.main()

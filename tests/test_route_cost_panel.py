from __future__ import annotations

import unittest

import pandas as pd

from ddvc.asset_types import NATIVE_ETH, WETH
from scripts import run_route_cost_panel


def swap(
    tx_hash: str,
    token_in: str,
    token_out: str,
    token_in_sym: str,
    token_out_sym: str,
    amount_usd: float,
    *,
    component_id: int = 0,
    tin_role: str = "source",
    tout_role: str = "sink",
) -> dict[str, object]:
    return {
        "tx_hash": tx_hash,
        "component_id": component_id,
        "route_class": "single",
        "token_in": token_in,
        "token_out": token_out,
        "token_in_sym": token_in_sym,
        "token_out_sym": token_out_sym,
        "tin_role": tin_role,
        "tout_role": tout_role,
        "amount_usd": amount_usd,
    }


class RouteCostPairSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_unify_wrapped = run_route_cost_panel.UNIFY_WRAPPED
        run_route_cost_panel.UNIFY_WRAPPED = True

    def tearDown(self) -> None:
        run_route_cost_panel.UNIFY_WRAPPED = self.original_unify_wrapped

    def test_canonical_pair_is_not_duplicated_by_eth_and_weth_symbols(self) -> None:
        usdc = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        legs = pd.DataFrame(
            [
                swap("native", NATIVE_ETH, usdc, "ETH", "USDC", 100.0),
                swap("wrapped", WETH, usdc, "WETH", "USDC", 300.0),
            ]
        )
        out = run_route_cost_panel._routes_by_pair(legs, top_pairs=200)
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["src"], WETH)
        self.assertEqual(out.iloc[0]["src_sym"], "WETH")
        self.assertEqual(float(out.iloc[0]["realized_bridge_volume_usd"]), 400.0)
        self.assertEqual(int(out.iloc[0]["n_routes"]), 2)

    def test_components_with_multiple_source_tokens_are_excluded(self) -> None:
        legs = pd.DataFrame(
            [
                {
                    **swap("ambiguous", "a", "k", "A", "K", 100.0, tin_role="source", tout_role="intermediate"),
                    "route_class": "coherent",
                },
                {
                    **swap("ambiguous", "c", "k", "C", "K", 100.0, tin_role="source", tout_role="intermediate"),
                    "route_class": "coherent",
                },
                {
                    **swap("ambiguous", "k", "b", "K", "B", 200.0, tin_role="intermediate", tout_role="sink"),
                    "route_class": "coherent",
                },
            ]
        )
        self.assertTrue(run_route_cost_panel._routes_by_pair(legs, top_pairs=200).empty)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import pandas as pd

from scripts.process.build_route_gas_units import (
    candidate_transactions,
    deterministic_cell_sample,
    parse_receipt,
)

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def leg(
    tx_hash: str,
    log_index: int,
    token_in: str,
    token_out: str,
    tin_role: str,
    tout_role: str,
    *,
    source: str = "uniswap_v2",
    n_components: int = 1,
    route_class: str = "coherent",
) -> dict:
    return {
        "tx_hash": tx_hash,
        "component_id": 0,
        "n_components": n_components,
        "source": source,
        "token_in": token_in,
        "token_out": token_out,
        "amount_usd": 1_000.0,
        "log_index": log_index,
        "route_class": route_class,
        "tin_role": tin_role,
        "tout_role": tout_role,
    }


class RouteGasUnitTests(unittest.TestCase):
    def test_candidates_keep_only_exact_single_component_v2_family_routes(self) -> None:
        frame = pd.DataFrame(
            [
                leg(
                    "direct",
                    0,
                    "a",
                    "b",
                    "source",
                    "sink",
                    route_class="single",
                ),
                leg("via", 0, "a", USDC, "source", "intermediate"),
                leg(
                    "via",
                    1,
                    USDC,
                    "b",
                    "intermediate",
                    "sink",
                    source="sushiswap_v2",
                ),
                leg(
                    "mixed",
                    0,
                    "a",
                    "b",
                    "source",
                    "sink",
                    source="uniswap_v3",
                ),
                leg(
                    "components",
                    0,
                    "a",
                    "b",
                    "source",
                    "sink",
                    n_components=2,
                ),
                leg(
                    "cycle",
                    0,
                    "a",
                    USDC,
                    "intermediate",
                    "intermediate",
                ),
                leg(
                    "cycle",
                    1,
                    USDC,
                    "a",
                    "intermediate",
                    "intermediate",
                ),
                leg(
                    "disconnected",
                    0,
                    "a",
                    USDC,
                    "source",
                    "intermediate",
                ),
                leg(
                    "disconnected",
                    1,
                    "c",
                    "b",
                    "intermediate",
                    "sink",
                ),
            ]
        )
        out = candidate_transactions(frame, "20220115")
        self.assertEqual(set(out["tx_hash"]), {"direct", "via"})
        via = out[out["tx_hash"].eq("via")].iloc[0]
        self.assertEqual(via["legs"], 2)
        self.assertEqual(via["venue_sequence"], "uniswap_v2>sushiswap_v2")
        self.assertEqual(via["mid_type"], "stable")

    def test_hash_sample_is_deterministic_and_capped_within_cells(self) -> None:
        frame = pd.DataFrame(
            {
                "year": [2022] * 5,
                "legs": [1] * 5,
                "venue_sequence": ["uniswap_v2"] * 5,
                "mid_type": ["direct"] * 5,
                "tx_hash": [f"tx-{index}" for index in range(5)],
            }
        )
        first = deterministic_cell_sample(frame, 2)
        second = deterministic_cell_sample(frame.sample(frac=1, random_state=4), 2)
        self.assertEqual(len(first), 2)
        self.assertEqual(set(first["tx_hash"]), set(second["tx_hash"]))

    def test_receipt_parser_normalises_hex_fields(self) -> None:
        row = parse_receipt(
            "0xABC",
            {
                "result": {
                    "gasUsed": "0x3e8",
                    "status": "0x1",
                    "to": "0xROUTER",
                    "from": "0xSENDER",
                    "effectiveGasPrice": "0x64",
                }
            },
        )
        assert row is not None
        self.assertEqual(row["tx_hash"], "0xabc")
        self.assertEqual(row["gas_used"], 1_000)
        self.assertEqual(row["router"], "0xrouter")
        self.assertEqual(row["effective_gas_price_wei"], 100)


if __name__ == "__main__":
    unittest.main()

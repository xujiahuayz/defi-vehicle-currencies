from __future__ import annotations

import unittest
from eth_utils import keccak

from scripts.audit_v2_refetch_receipts import (
    colliding_rows,
    economic_identity,
    receipt_match,
    receipt_swap_log_index,
)


def row(amount0_out: str = "134659708639.360367020044220053") -> dict:
    return {
        "transaction": {"id": "0xtx"},
        "timestamp": "100",
        "logIndex": "7",
        "amount0In": "0",
        "amount1In": "2",
        "amount0Out": amount0_out,
        "amount1Out": "0",
        "pair": {
            "id": "0xpool",
            "token0": {"id": "0xa", "decimals": "18"},
            "token1": {"id": "0xb", "decimals": "18"},
        },
    }


def receipt() -> dict:
    amounts = (0, 2 * 10**18, 134659708639360367020044220053, 0)
    data = "0x" + "".join(value.to_bytes(32, "big").hex() for value in amounts)
    topic = "0x" + keccak(text="Swap(address,uint256,uint256,uint256,uint256,address)").hex()
    return {"logs": [{"address": "0xpool", "topics": [topic], "logIndex": "0x7", "data": data}]}


class V2RefetchAuditTests(unittest.TestCase):
    def test_economic_identity_ignores_provider_event_id(self) -> None:
        first = row()
        second = {**first, "id": "provider-two"}
        self.assertEqual(economic_identity(first), economic_identity(second))

    def test_receipt_match_uses_exact_base_units_and_log_order(self) -> None:
        self.assertTrue(receipt_match(row(), receipt(), {"0xa": 18, "0xb": 18}))
        self.assertFalse(receipt_match(row("134659708639.360367020044220052"), receipt(), {"0xa": 18, "0xb": 18}))

    def test_receipt_resolves_order_without_trusting_provider_log_index(self) -> None:
        provider = {**row(), "logIndex": "3"}
        self.assertEqual(
            receipt_swap_log_index(provider, receipt(), {"0xa": 18, "0xb": 18}),
            7,
        )
        self.assertFalse(receipt_match(provider, receipt(), {"0xa": 18, "0xb": 18}))

    def test_receipt_match_distinguishes_missing_support(self) -> None:
        self.assertIsNone(receipt_match(row(), None, {"0xa": 18, "0xb": 18}))
        self.assertIsNone(receipt_match(row(), receipt(), {"0xa": 18}))

    def test_collision_scan_reports_every_conflicting_provider_row(self) -> None:
        first = {**row(), "id": "first", "transaction": {"id": "0xone", "blockNumber": "10"}}
        second = {
            **row("1"),
            "id": "second",
            "transaction": {"id": "0xtwo", "blockNumber": "10"},
        }
        collisions = colliding_rows([first, second])
        self.assertEqual({item["id"] for item in collisions}, {"first", "second"})


if __name__ == "__main__":
    unittest.main()

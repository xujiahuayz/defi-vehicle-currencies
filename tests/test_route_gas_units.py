from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ddvc.fetch.sources import DEX_SOURCES
from ddvc.quoter import canonical_json_sha256
from ddvc.route_gas import (
    candidate_transactions,
    deterministic_cell_sample,
    estimate_route_gas,
)
from scripts.process import build_route_gas_units as route_gas
from scripts.process.build_route_gas_units import (
    bounded_workers,
    load_receipt_snapshot,
    parse_receipt,
    sample_day,
    worker_batches,
    write_receipt_snapshot,
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
    block_number: int = 100,
) -> dict:
    return {
        "tx_hash": tx_hash,
        "block_number": block_number,
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


def receipt_evidence(
    tx_hash: str,
    block_number: int,
    gas_used: int,
) -> dict[str, object]:
    block_hash = "0x" + f"{block_number:064x}"
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "transactionHash": tx_hash,
            "blockNumber": hex(block_number),
            "blockHash": block_hash,
            "gasUsed": hex(gas_used),
            "status": "0x1",
            "to": "0xrouter",
            "from": "0xsender",
            "effectiveGasPrice": "0x64",
            "logs": [],
        },
    }
    endpoint = {"host": "injected", "endpoint_sha256": "0" * 64}
    return {
        "tx_hash": tx_hash,
        "block_number": block_number,
        "block_hash": block_hash,
        "gas_used": gas_used,
        "status": 1,
        "tx_to": "0xrouter",
        "tx_from": "0xsender",
        "effective_gas_price_wei": 100,
        "rpc_request": {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getTransactionReceipt",
            "params": [tx_hash],
        },
        "rpc_response": response,
        "rpc_endpoint": endpoint,
        "rpc_attempts": [
            {
                "endpoint": endpoint,
                "attempt": 1,
                "classification": "success",
                "http_status": None,
                "rpc_code": None,
                "message": "success",
            }
        ],
        "response_sha256": canonical_json_sha256(response),
    }


class RouteGasUnitTests(unittest.TestCase):
    def test_route_gas_estimates_use_exact_cells_then_label_fallbacks(self) -> None:
        panel = pd.DataFrame(
            {
                "year": [2025, 2025, 2025, 2025, 2024],
                "legs": [1, 1, 2, 2, 2],
                "venue_sequence": [
                    "uniswap_v2",
                    "uniswap_v2",
                    "uniswap_v2>uniswap_v2",
                    "uniswap_v2>uniswap_v2",
                    "uniswap_v2>uniswap_v2",
                ],
                "gas_vehicle": ["direct", "direct", USDC, USDC, USDC],
                "mid_type": ["direct", "direct", "stable", "stable", "stable"],
                "gas_used": [100, 120, 200, 240, 300],
                "status": [1, 1, 1, 1, 1],
            }
        )
        requests = pd.DataFrame(
            {
                "year": [2025, 2025, 2025, 2030],
                "legs": [2, 2, 2, 2],
                "venue_sequence": [
                    "uniswap_v2>uniswap_v2",
                    "uniswap_v2>uniswap_v2",
                    "sushiswap_v2>sushiswap_v2",
                    "unknown>unknown",
                ],
                "gas_vehicle": [USDC, "another-stable", "another-stable", "unknown"],
                "mid_type": ["stable", "stable", "stable", "stable"],
            }
        )
        out = estimate_route_gas(requests, panel)
        self.assertEqual(out.loc[0, "gas_units_median"], 220)
        self.assertEqual(out.loc[0, "gas_support_level"], "year_venue_vehicle")
        self.assertEqual(out.loc[1, "gas_units_median"], 220)
        self.assertEqual(out.loc[1, "gas_support_level"], "year_venue_type")
        self.assertEqual(out.loc[2, "gas_support_level"], "year_type")
        self.assertEqual(out.loc[3, "gas_support_level"], "topology")

    def test_route_gas_broad_fallbacks_are_cell_balanced(self) -> None:
        panel = pd.DataFrame(
            {
                "year": [2025] * 5,
                "legs": [2] * 5,
                "venue_sequence": ["uniswap_v2>uniswap_v2"] * 5,
                "gas_vehicle": [USDC, USDC, USDC, "other", "other"],
                "mid_type": ["stable", "stable", "stable", "other", "other"],
                "gas_used": [100, 100, 100, 300, 300],
                "status": [1] * 5,
            }
        )
        request = pd.DataFrame(
            {
                "year": [2025],
                "legs": [2],
                "venue_sequence": ["missing>missing"],
                "gas_vehicle": ["missing"],
                "mid_type": ["missing"],
            }
        )
        out = estimate_route_gas(request, panel)
        self.assertEqual(out.loc[0, "gas_units_median"], 200)
        self.assertEqual(out.loc[0, "gas_support_cells"], 2)

    def test_worker_count_is_bounded(self) -> None:
        self.assertEqual(bounded_workers(0), 1)
        self.assertEqual(bounded_workers(4), 4)
        self.assertEqual(bounded_workers(100), 8)

    def test_gas_calibration_uses_the_full_released_calendar(self) -> None:
        self.assertNotIn("src/ddvc/calendar.py", route_gas.CODE_SOURCES)
        self.assertIn("src/ddvc/release_calendar.py", route_gas.CODE_SOURCES)
        self.assertNotIn("src/ddvc/calendar.py", route_gas.CANDIDATE_CODE_SOURCES)

    def test_worker_recycling_uses_explicit_bounded_batches(self) -> None:
        batches = worker_batches([str(day) for day in range(19)], workers=2)
        self.assertEqual([len(batch) for batch in batches], [8, 8, 3])
        self.assertEqual([day for batch in batches for day in batch], [str(day) for day in range(19)])

    def test_candidates_cover_every_registered_venue(self) -> None:
        frame = pd.DataFrame(
            [
                leg(
                    f"tx-{source}",
                    0,
                    "a",
                    "b",
                    "source",
                    "sink",
                    source=source,
                    route_class="single",
                )
                for source in DEX_SOURCES
            ]
        )
        out = candidate_transactions(frame, "20220115")
        self.assertEqual(
            set(out["venue_sequence"]),
            set(DEX_SOURCES),
        )

    def test_candidates_keep_only_exact_single_component_registered_routes(self) -> None:
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
                    "v3",
                    0,
                    "a",
                    "b",
                    "source",
                    "sink",
                    source="uniswap_v3",
                    route_class="single",
                ),
                leg(
                    "unknown",
                    0,
                    "a",
                    "b",
                    "source",
                    "sink",
                    source="unknown_dex",
                    route_class="single",
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
        self.assertEqual(set(out["tx_hash"]), {"direct", "via", "v3"})
        via = out[out["tx_hash"].eq("via")].iloc[0]
        self.assertEqual(via["legs"], 2)
        self.assertEqual(via["venue_sequence"], "uniswap_v2>sushiswap_v2")
        self.assertEqual(via["mid_type"], "stable")
        self.assertEqual(via["gas_vehicle"], USDC)

    def test_candidate_roles_come_from_topology_not_stored_value_tolerance(self) -> None:
        frame = pd.DataFrame(
            [
                leg("via", 0, "a", USDC, "sink", "source"),
                leg("via", 1, USDC, "b", "sink", "source"),
            ]
        )
        out = candidate_transactions(frame, "20220115")
        self.assertEqual(set(out["tx_hash"]), {"via"})
        self.assertEqual(out.iloc[0]["mid_type"], "stable")

    def test_hash_sample_is_deterministic_and_capped_within_cells(self) -> None:
        frame = pd.DataFrame(
            {
                "year": [2022] * 5,
                "legs": [1] * 5,
                "venue_sequence": ["uniswap_v2"] * 5,
                "mid_type": ["direct"] * 5,
                "gas_vehicle": ["direct", "direct", "direct", "other", "other"],
                "tx_hash": [f"tx-{index}" for index in range(5)],
            }
        )
        first = deterministic_cell_sample(frame, 2)
        second = deterministic_cell_sample(frame.sample(frac=1, random_state=4), 2)
        self.assertEqual(len(first), 4)
        self.assertEqual(set(first["tx_hash"]), set(second["tx_hash"]))

    def test_partitioned_cell_top_k_equals_full_sample(self) -> None:
        frame = pd.DataFrame(
            {
                "year": [2022] * 8,
                "legs": [2] * 8,
                "venue_sequence": ["uniswap_v2>uniswap_v3"] * 8,
                "mid_type": ["stable"] * 8,
                "gas_vehicle": [USDC] * 8,
                "tx_hash": [f"tx-{index}" for index in range(8)],
            }
        )
        expected = deterministic_cell_sample(frame, 2)
        partitioned = pd.concat(
            [
                deterministic_cell_sample(frame.iloc[:4], 2),
                deterministic_cell_sample(frame.iloc[4:], 2),
            ],
            ignore_index=True,
        )
        actual = deterministic_cell_sample(partitioned, 2)
        self.assertEqual(set(actual["tx_hash"]), set(expected["tx_hash"]))

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
        self.assertEqual(row["tx_to"], "0xrouter")
        self.assertEqual(row["tx_from"], "0xsender")
        self.assertEqual(row["effective_gas_price_wei"], 100)

    def test_receipt_fetch_rotates_past_json_rpc_error_bodies(self) -> None:
        original_cache = route_gas.CACHE
        with tempfile.TemporaryDirectory() as temporary:
            route_gas.CACHE = Path(temporary)
            response = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "transactionHash": "0xabc",
                    "blockNumber": "0xa",
                    "blockHash": "0x" + "a" * 64,
                    "gasUsed": "0x3e8",
                    "status": "0x1",
                    "to": "0xrouter",
                    "from": "0xsender",
                    "effectiveGasPrice": "0x64",
                    "logs": [],
                }
            }
            try:
                with patch.object(route_gas, "rpc_post", return_value=response) as request:
                    fetched = route_gas.fetch_receipt("0xabc", 10)
            finally:
                route_gas.CACHE = original_cache
        self.assertTrue(request.call_args.kwargs["retry_json_errors"])
        self.assertEqual(fetched["block_number"], 10)
        self.assertIn("rpc_response", fetched)

    def test_receipt_snapshot_is_sorted_and_byte_deterministic(self) -> None:
        receipts = [
            receipt_evidence("0xb", 2, 2),
            receipt_evidence("0xa", 1, 1),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "selection.jsonl"
            write_receipt_snapshot(receipts, path)
            first = path.read_bytes()
            write_receipt_snapshot(list(reversed(receipts)), path)
            second = path.read_bytes()
        self.assertEqual(first, second)
        self.assertEqual(
            [json.loads(line)["tx_hash"] for line in first.decode().splitlines()],
            ["0xa", "0xb"],
        )

    def test_previous_receipt_snapshot_is_a_validated_immutable_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "selection.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps(receipt_evidence("0xa", 10, 10)),
                        json.dumps({"tx_hash": "0xA", "gas_used": 10, "status": 1}),
                        json.dumps({"tx_hash": "0xb", "gas_used": 0, "status": 1}),
                        "not-json",
                    ]
                )
            )
            loaded = load_receipt_snapshot(path)
        self.assertEqual(set(loaded), {"0xa"})

    def test_day_candidate_sample_is_resumable_and_schema_checked(self) -> None:
        original = route_gas.UNIFIED
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unified = root / "unified"
            cache = root / "cache"
            unified.mkdir()
            pd.DataFrame(
                [
                    leg(
                        "direct",
                        0,
                        "a",
                        "b",
                        "source",
                        "sink",
                        route_class="single",
                    )
                ]
            ).to_parquet(unified / "20220115.parquet", index=False)
            route_gas.UNIFIED = unified
            try:
                first = sample_day("20220115", 2, str(cache))
                second = sample_day("20220115", 2, str(cache))
            finally:
                route_gas.UNIFIED = original
        self.assertEqual((first[0], len(first[1]), first[2]), (1, 1, False))
        self.assertEqual((second[0], len(second[1]), second[2]), (1, 1, True))


if __name__ == "__main__":
    unittest.main()

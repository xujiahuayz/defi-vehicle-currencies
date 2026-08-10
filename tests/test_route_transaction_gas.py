from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from ddvc.ethereum_blocks import block_header_is_current, parse_block_header
from ddvc.ethereum_receipts import parse_receipt, receipt_is_current
from ddvc.ethereum_receipts import fetch_receipt
from ddvc import quoter
from ddvc.quoter import canonical_json_sha256
from ddvc.gas import load_route_transaction_gas
from scripts.process import build_route_gas_units, build_route_transaction_gas
from scripts.process.build_route_transaction_gas import (
    block_header_requests,
    receipt_panel,
    route_receipt_requests,
    shard_requests,
)


def evidence(request: dict[str, object], response: dict[str, object]) -> dict[str, object]:
    endpoint = {"host": "injected", "endpoint_sha256": "0" * 64}
    return {
        "rpc_request": request,
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


class HttpResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = body

    def __enter__(self) -> HttpResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.body).encode()


def receipt(
    tx_hash: str,
    block_number: int,
    gas_price: int,
    *,
    gas_used: int = 120_000,
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
            "effectiveGasPrice": hex(gas_price),
            "logs": [],
        },
    }
    return {
        "tx_hash": tx_hash,
        "block_number": block_number,
        "block_hash": block_hash,
        "gas_used": gas_used,
        "status": 1,
        "tx_to": "0xrouter",
        "tx_from": "0xsender",
        "effective_gas_price_wei": gas_price,
        **evidence(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getTransactionReceipt",
                "params": [tx_hash],
            },
            response,
        ),
    }


def header(
    block_number: int,
    base_fee: int | None,
    *,
    block_hash: str | None = None,
) -> dict[str, object]:
    block_hash = block_hash or "0x" + f"{block_number:064x}"
    parent_hash = "0x" + f"{block_number - 1:064x}"
    result = {
        "number": hex(block_number),
        "hash": block_hash,
        "parentHash": parent_hash,
        "timestamp": hex(1_700_000_000 + block_number),
    }
    if base_fee is not None:
        result["baseFeePerGas"] = hex(base_fee)
    response = {"jsonrpc": "2.0", "id": 1, "result": result}
    return {
        "block_number": block_number,
        "block_hash": block_hash,
        "parent_hash": parent_hash,
        "timestamp": 1_700_000_000 + block_number,
        "base_fee_per_gas_wei": base_fee,
        **evidence(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getBlockByNumber",
                "params": [hex(block_number), False],
            },
            response,
        ),
    }


def test_route_requests_deduplicate_exact_transaction_identity(tmp_path: Path) -> None:
    source = tmp_path / "gross.parquet"
    pd.DataFrame(
        {"tx": ["0xABC", "0xabc", "0xdef"], "block": [10, 10, 11]}
    ).to_parquet(source, index=False)
    requests = route_receipt_requests(source)
    assert requests.to_dict("records") == [
        {"tx_hash": "0xabc", "block_number": 10},
        {"tx_hash": "0xdef", "block_number": 11},
    ]


def test_receipt_builders_share_one_canonical_cache() -> None:
    assert build_route_gas_units.CACHE == build_route_transaction_gas.CACHE


def test_cache_shards_are_deterministic_disjoint_and_complete() -> None:
    requests = pd.DataFrame(
        {"tx_hash": [f"0x{index}" for index in range(7)], "block_number": range(7)}
    )
    shards = [shard_requests(requests, shard_index=index, shards=2) for index in range(2)]
    assert set(shards[0]["tx_hash"]).isdisjoint(shards[1]["tx_hash"])
    assert sorted(pd.concat(shards)["tx_hash"]) == sorted(requests["tx_hash"])
    with pytest.raises(ValueError, match="0 <= shard-index"):
        shard_requests(requests, shard_index=2, shards=2)


def test_block_header_requests_are_unique_and_sorted() -> None:
    requests = pd.DataFrame(
        {
            "tx_hash": ["0xa", "0xb", "0xc"],
            "block_number": [11, 10, 11],
        }
    )
    assert block_header_requests(requests).to_dict("records") == [
        {"block_number": 10},
        {"block_number": 11},
    ]


def test_route_requests_reject_conflicting_transaction_blocks(tmp_path: Path) -> None:
    source = tmp_path / "gross.parquet"
    pd.DataFrame({"tx": ["0xabc", "0xabc"], "block": [10, 11]}).to_parquet(
        source, index=False
    )
    with pytest.raises(ValueError, match="multiple Ethereum blocks"):
        route_receipt_requests(source)


def test_receipt_panel_marks_zero_effective_price_unsupported(tmp_path: Path) -> None:
    requests = pd.DataFrame(
        {"tx_hash": ["0xabc", "0xdef"], "block_number": [10, 11]}
    )
    panel = receipt_panel(
        [receipt("0xabc", 10, 10_000_000_000), receipt("0xdef", 11, 0)],
        requests,
        [header(10, 8_000_000_000), header(11, None)],
    )
    assert panel["gas_price_supported"].tolist() == [True, False]
    assert panel.loc[0, "realised_gas_cost_wei"] == "1200000000000000"
    assert pd.isna(panel.loc[1, "realised_gas_cost_wei"])
    assert panel["gas_gwei"].iloc[0] == 10.0
    assert pd.isna(panel["gas_gwei"].iloc[1])
    assert panel["gas_price_support_reason"].iloc[1] == "zero_effective_price_private_payment_possible"
    assert panel["base_fee_supported"].tolist() == [True, False]
    assert panel["base_fee_gwei"].iloc[0] == 8.0
    assert pd.isna(panel["base_fee_gwei"].iloc[1])
    assert panel["base_fee_support_reason"].iloc[1] == "pre_eip1559_block_no_base_fee"

    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    loaded = load_route_transaction_gas(
        path,
        required_routes=pd.DataFrame(
            {"tx": ["0xabc", "0xdef"], "block": [10, 11]}
        ),
    )
    assert len(loaded) == 2


def test_route_gas_loader_rejects_inconsistent_realised_cost(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    panel = receipt_panel(
        [receipt("0xabc", 10, 10_000_000_000)],
        requests,
        [header(10, 8_000_000_000)],
    )
    panel.loc[0, "realised_gas_cost_wei"] = "1"
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="inconsistent realised gas cost"):
        load_route_transaction_gas(path)


def test_realised_gas_cost_uses_arbitrary_precision_decimal_text(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    panel = receipt_panel(
        [receipt("0xabc", 10, 10**12, gas_used=30_000_000)],
        requests,
        [header(10, 8_000_000_000)],
    )
    assert panel.loc[0, "realised_gas_cost_wei"] == "30000000000000000000"
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    loaded = load_route_transaction_gas(path)
    assert loaded.loc[0, "realised_gas_cost_wei"] == "30000000000000000000"


def test_loader_rejects_support_flags_inconsistent_with_exact_prices(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    panel = receipt_panel(
        [receipt("0xabc", 10, 0)],
        requests,
        [header(10, 8_000_000_000)],
    )
    panel.loc[0, "gas_price_supported"] = True
    panel.loc[0, "gas_gwei"] = 1.0
    panel.loc[0, "gas_price_support_reason"] = "receipt_effective_gas_price"
    panel.loc[0, "realised_gas_cost_wei"] = "0"
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="support disagrees"):
        load_route_transaction_gas(path)


def test_loader_rejects_base_fee_support_inconsistent_with_header(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    panel = receipt_panel(
        [receipt("0xabc", 10, 10_000_000_000)],
        requests,
        [header(10, 8_000_000_000)],
    )
    panel.loc[0, "base_fee_supported"] = False
    panel.loc[0, "base_fee_gwei"] = None
    panel.loc[0, "base_fee_support_reason"] = "pre_eip1559_block_no_base_fee"
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="support disagrees"):
        load_route_transaction_gas(path)


def test_receipt_fetch_rotates_past_malformed_http_success(tmp_path: Path) -> None:
    exact = receipt("0xabc", 10, 10_000_000_000)["rpc_response"]
    malformed = json.loads(json.dumps(exact))
    malformed["result"]["blockHash"] = None
    quoter._rpc_idx = 0
    quoter._disabled_rpc_urls.clear()
    with (
        patch.object(quoter, "rpc_urls", return_value=["https://first", "https://second"]),
        patch.object(
            quoter.urllib.request,
            "urlopen",
            side_effect=[HttpResponse(malformed), HttpResponse(exact)],
        ) as request,
    ):
        row = fetch_receipt(
            "0xabc",
            cache=tmp_path,
            expected_block=10,
            require_block_hash=True,
            require_evidence=True,
        )
    assert request.call_count == 2
    assert [attempt["classification"] for attempt in row["rpc_attempts"]] == [
        "transient",
        "success",
    ]
    assert receipt_is_current(
        row,
        "0xabc",
        expected_block=10,
        require_block_hash=True,
        require_evidence=True,
    )


def test_receipt_panel_rejects_receipt_header_hash_disagreement() -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    wrong_header = header(10, 8_000_000_000, block_hash="0x" + "f" * 64)
    with pytest.raises(RuntimeError, match="hashes disagree"):
        receipt_panel(
            [receipt("0xabc", 10, 10_000_000_000)],
            requests,
            [wrong_header],
        )


def test_receipt_panel_rejects_self_attested_copied_fields() -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    tampered = receipt("0xabc", 10, 10_000_000_000)
    tampered["gas_used"] = 1
    with pytest.raises(RuntimeError, match="cannot be reopened"):
        receipt_panel(
            [tampered],
            requests,
            [header(10, 8_000_000_000)],
        )


def test_receipt_parser_enforces_requested_block() -> None:
    response = {
        "result": {
            "transactionHash": "0xabc",
            "blockNumber": "0xa",
            "blockHash": "0x" + "a" * 64,
            "gasUsed": "0x1d4c0",
            "status": "0x1",
            "effectiveGasPrice": "0x2540be400",
            "logs": [],
        }
    }
    parsed = parse_receipt("0xabc", response, expected_block=10)
    assert parsed["block_number"] == 10
    assert parsed["block_hash"] == "0x" + "a" * 64
    assert receipt_is_current(
        parsed,
        "0xabc",
        expected_block=10,
        require_block_hash=True,
    )
    assert not receipt_is_current(
        {**parsed, "block_hash": None},
        "0xabc",
        expected_block=10,
        require_block_hash=True,
    )
    with_logs = parse_receipt("0xabc", response, expected_block=10, include_logs=True)
    assert with_logs["logs"] == []
    assert receipt_is_current(
        with_logs,
        "0xabc",
        expected_block=10,
        require_block_hash=True,
        require_logs=True,
    )
    with pytest.raises(ValueError, match="block differs"):
        parse_receipt("0xabc", response, expected_block=11)


def test_block_header_parser_preserves_pre_eip1559_missing_base_fee() -> None:
    response = {
        "result": {
            "number": "0xa",
            "hash": "0x" + "a" * 64,
            "parentHash": "0x" + "b" * 64,
            "timestamp": "0x64",
        }
    }
    parsed = parse_block_header(10, response)
    assert parsed["base_fee_per_gas_wei"] is None
    assert block_header_is_current(parsed, 10)
    post_london = parse_block_header(
        10,
        {
            "result": {
                **response["result"],
                "baseFeePerGas": "0x1dcd65000",
            }
        },
    )
    assert post_london["base_fee_per_gas_wei"] == 8_000_000_000
    with pytest.raises(ValueError, match="returned block"):
        parse_block_header(11, response)


def test_block_header_evidence_rejects_tampered_copied_fields() -> None:
    exact = header(10, 8_000_000_000)
    assert block_header_is_current(exact, 10, require_evidence=True)
    assert not block_header_is_current(
        {**exact, "base_fee_per_gas_wei": 1},
        10,
        require_evidence=True,
    )

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
from ddvc.gas import load_route_transaction_gas, validate_route_transaction_gas_release
from ddvc.provenance import sidecar_path
from scripts.process import build_route_gas_units, build_route_transaction_gas
from scripts.process.build_route_transaction_gas import (
    acquire_exact_cache,
    assemble_exact_outputs,
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
    blob_gas_used: int | None = None,
    blob_gas_price: int | None = None,
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
    if (blob_gas_used is None) != (blob_gas_price is None):
        raise ValueError("test receipts require both blob gas fields or neither")
    if blob_gas_used is not None and blob_gas_price is not None:
        response["result"]["blobGasUsed"] = hex(blob_gas_used)
        response["result"]["blobGasPrice"] = hex(blob_gas_price)
    return {
        "tx_hash": tx_hash,
        "block_number": block_number,
        "block_hash": block_hash,
        "gas_used": gas_used,
        "status": 1,
        "tx_to": "0xrouter",
        "tx_from": "0xsender",
        "effective_gas_price_wei": gas_price,
        "blob_gas_used": blob_gas_used,
        "blob_gas_price_wei": blob_gas_price,
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


def test_route_requests_require_one_single_component_row_per_receipt(tmp_path: Path) -> None:
    source = tmp_path / "gross.parquet"
    pd.DataFrame(
        {"tx": ["0xABC", "0xdef"], "block": [10, 11], "component_id": [0, 0], "receipt_allocation_scope": ["single_reconstructed_component_transaction", "single_reconstructed_component_transaction"]}
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
    pd.DataFrame({"tx": ["0xabc", "0xabc"], "block": [10, 11], "component_id": [0, 1], "receipt_allocation_scope": ["single_reconstructed_component_transaction", "single_reconstructed_component_transaction"]}).to_parquet(
        source, index=False
    )
    with pytest.raises(ValueError, match="cannot be allocated to multiple route rows"):
        route_receipt_requests(source)


def test_route_requests_reject_missing_single_component_contract(tmp_path: Path) -> None:
    source = tmp_path / "gross.parquet"
    pd.DataFrame({"tx": ["0xabc"], "block": [10], "component_id": [0], "receipt_allocation_scope": ["multi_component_unallocated"]}).to_parquet(source, index=False)
    with pytest.raises(ValueError, match="single-component allocation contract"):
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
    assert panel.loc[0, "execution_gas_cost_wei"] == "1200000000000000"
    assert pd.isna(panel.loc[1, "execution_gas_cost_wei"])
    assert panel["blob_gas_cost_wei"].tolist() == ["0", "0"]
    assert panel.loc[0, "receipt_total_gas_cost_wei"] == "1200000000000000"
    assert pd.isna(panel.loc[1, "receipt_total_gas_cost_wei"])
    assert panel["block_timestamp_utc"].tolist() == [1_700_000_010, 1_700_000_011]
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


def test_route_gas_loader_rejects_inconsistent_execution_cost(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    panel = receipt_panel(
        [receipt("0xabc", 10, 10_000_000_000)],
        requests,
        [header(10, 8_000_000_000)],
    )
    panel.loc[0, "execution_gas_cost_wei"] = "1"
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="inconsistent execution gas cost"):
        load_route_transaction_gas(path)


def test_receipt_gas_cost_uses_arbitrary_precision_decimal_text(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    panel = receipt_panel(
        [receipt("0xabc", 10, 10**12, gas_used=30_000_000)],
        requests,
        [header(10, 8_000_000_000)],
    )
    assert panel.loc[0, "execution_gas_cost_wei"] == "30000000000000000000"
    assert panel.loc[0, "receipt_total_gas_cost_wei"] == "30000000000000000000"
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    loaded = load_route_transaction_gas(path)
    assert loaded.loc[0, "receipt_total_gas_cost_wei"] == "30000000000000000000"


def test_receipt_gas_cost_includes_eip4844_blob_fee(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    panel = receipt_panel(
        [
            receipt(
                "0xabc",
                10,
                10_000_000_000,
                blob_gas_used=131_072,
                blob_gas_price=2_000_000_000,
            )
        ],
        requests,
        [header(10, 8_000_000_000)],
    )
    assert panel.loc[0, "execution_gas_cost_wei"] == "1200000000000000"
    assert panel.loc[0, "blob_gas_cost_wei"] == "262144000000000"
    assert panel.loc[0, "receipt_total_gas_cost_wei"] == "1462144000000000"
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    loaded = load_route_transaction_gas(path)
    assert loaded.loc[0, "blob_gas_used"] == 131_072
    assert loaded.loc[0, "blob_gas_price_wei"] == 2_000_000_000


def test_route_gas_loader_rejects_fractional_blob_fields(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    panel = receipt_panel(
        [receipt("0xabc", 10, 10_000_000_000, blob_gas_used=2, blob_gas_price=3)],
        requests,
        [header(10, 8_000_000_000)],
    )
    panel["blob_gas_used"] = panel["blob_gas_used"].astype(float)
    panel.loc[0, "blob_gas_used"] = 1.5
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="malformed blob gas fields"):
        load_route_transaction_gas(path)


def test_arbitrary_precision_blob_fields_round_trip_and_tampering_fails(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    huge_units = 2**80 + 7
    panel = receipt_panel(
        [receipt("0xabc", 10, 10_000_000_000, blob_gas_used=huge_units, blob_gas_price=3)],
        requests,
        [header(10, 8_000_000_000)],
    )
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    loaded = load_route_transaction_gas(path)
    assert loaded.loc[0, "blob_gas_used"] == huge_units
    tampered = panel.copy()
    tampered.loc[0, "blob_gas_cost_wei"] = "1"
    tampered.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="inconsistent blob gas cost"):
        load_route_transaction_gas(path)


def test_route_gas_loader_rejects_fractional_receipt_integers(tmp_path: Path) -> None:
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    panel = receipt_panel(
        [receipt("0xabc", 10, 10_000_000_000)],
        requests,
        [header(10, 8_000_000_000)],
    )
    panel["effective_gas_price_wei"] = panel["effective_gas_price_wei"].astype(float)
    panel.loc[0, "effective_gas_price_wei"] = 1.5
    path = tmp_path / "route-gas.parquet"
    panel.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="malformed receipt integers"):
        load_route_transaction_gas(path)


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
    panel.loc[0, "execution_gas_cost_wei"] = "0"
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


def test_receipt_evidence_rejects_normalized_logs_absent_from_rpc_response() -> None:
    tampered = receipt("0xabc", 10, 10_000_000_000)
    tampered["logs"] = [
        {
            "address": "0x" + "d" * 40,
            "log_index": 1,
            "topics": ["0x" + "e" * 64],
            "data": "0x",
        }
    ]
    assert not receipt_is_current(
        tampered,
        "0xabc",
        expected_block=10,
        require_block_hash=True,
        require_logs=True,
        require_evidence=True,
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


def test_receipt_parser_requires_paired_blob_gas_fields() -> None:
    response = receipt("0xabc", 10, 10_000_000_000)["rpc_response"]
    response["result"]["blobGasUsed"] = hex(131_072)
    assert parse_receipt("0xabc", response, expected_block=10) is None


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


def test_acquisition_and_final_assembly_retain_at_most_one_batch(tmp_path: Path) -> None:
    requests = pd.DataFrame(
        {
            "tx_hash": [f"0x{index:04x}" for index in range(11)],
            "block_number": list(range(10, 21)),
        }
    )
    observed: list[int] = []

    def fetch_receipt_batch(batch, **_kwargs):
        observed.append(len(batch))
        return [object()] * len(batch)

    def fetch_header_batch(batch, **_kwargs):
        observed.append(len(batch))
        return [object()] * len(batch)

    with (
        patch.object(build_route_transaction_gas, "fetch_receipts", side_effect=fetch_receipt_batch),
        patch.object(build_route_transaction_gas, "fetch_headers", side_effect=fetch_header_batch),
    ):
        assert acquire_exact_cache(requests, workers=2, batch_size=3) == (11, 11)
    assert max(observed) == 3

    receipt_cache = tmp_path / "receipts"
    header_cache = tmp_path / "headers"
    receipt_cache.mkdir()
    header_cache.mkdir()
    for row in requests.itertuples(index=False):
        (receipt_cache / f"{row.tx_hash}.json").write_text(
            json.dumps(receipt(row.tx_hash, row.block_number, 10_000_000_000), sort_keys=True),
            encoding="utf-8",
        )
        (header_cache / f"{row.block_number}.json").write_text(
            json.dumps(header(row.block_number, 8_000_000_000), sort_keys=True),
            encoding="utf-8",
        )
    receipt_evidence = tmp_path / "receipts.jsonl"
    block_evidence = tmp_path / "blocks.jsonl"
    output = tmp_path / "gas.parquet"

    with (
        patch.object(build_route_transaction_gas, "CACHE", receipt_cache),
        patch.object(build_route_transaction_gas, "HEADER_CACHE", header_cache),
        patch.object(build_route_transaction_gas, "RECEIPT_EVIDENCE", receipt_evidence),
        patch.object(build_route_transaction_gas, "BLOCK_HEADER_EVIDENCE", block_evidence),
        patch.object(build_route_transaction_gas, "OUT_PANEL", output),
    ):
        support = assemble_exact_outputs(requests, batch_size=3)
    assert support == {
        "rows": 11,
        "gas_price_supported": 11,
        "receipt_evidence_rows": 11,
        "block_evidence_rows": 11,
    }
    assert pd.read_parquet(output).shape[0] == 11
    original = pd.read_parquet(output)
    tampered_receipt = original.copy()
    tampered_receipt.loc[0, "tx_to"] = "0xother"
    tampered_receipt.to_parquet(output, index=False)
    with pytest.raises(ValueError, match="exact receipt evidence"):
        validate_route_transaction_gas_release(output, requests, receipt_snapshot=receipt_evidence, block_header_snapshot=block_evidence, batch_size=3)
    tampered_header = original.copy()
    tampered_header.loc[0, "parent_hash"] = "0x" + "f" * 64
    tampered_header.to_parquet(output, index=False)
    with pytest.raises(ValueError, match="exact block-header evidence"):
        validate_route_transaction_gas_release(output, requests, receipt_snapshot=receipt_evidence, block_header_snapshot=block_evidence, batch_size=3)


def test_route_gas_builder_preserves_prior_pair_when_exact_validation_fails(tmp_path: Path) -> None:
    output = tmp_path / "gas.parquet"
    pd.DataFrame({"prior": [1]}).to_parquet(output, index=False)
    prior = output.read_bytes()
    sidecar = sidecar_path(output)
    sidecar.write_bytes(b"prior-sidecar\n")
    requests = pd.DataFrame({"tx_hash": ["0xabc"], "block_number": [10]})
    evidence = tmp_path / "receipts.jsonl"
    block_evidence = tmp_path / "blocks.jsonl"
    with (
        patch.object(build_route_transaction_gas, "OUT_PANEL", output),
        patch.object(build_route_transaction_gas, "RECEIPT_EVIDENCE", evidence),
        patch.object(build_route_transaction_gas, "BLOCK_HEADER_EVIDENCE", block_evidence),
        patch.object(build_route_transaction_gas, "write_receipt_snapshot", return_value=evidence),
        patch.object(build_route_transaction_gas, "write_block_header_snapshot", return_value=block_evidence),
        patch.object(build_route_transaction_gas, "cached_panel_batches", return_value=[pd.DataFrame({"candidate": [2]})]),
        patch.object(build_route_transaction_gas, "validate_route_transaction_gas_release", side_effect=ValueError("exact validation failed")),
        pytest.raises(ValueError, match="exact validation failed"),
    ):
        assemble_exact_outputs(requests, batch_size=1)
    assert output.read_bytes() == prior
    assert sidecar.read_bytes() == b"prior-sidecar\n"
    assert list(tmp_path.glob(".*.tmp")) == []

from __future__ import annotations

import gzip
import hashlib
import json

from eth_abi import encode as abi_encode
import pytest

from ddvc.fetch.sources import get_source
from ddvc.pricing.v3pools import compute_pool_address
from ddvc.v3_inventory import pool_statics_from_factory
from ddvc.v3_pool_registry import (
    FACTORY_EVENT_TOPICS,
    FEE_AMOUNT_ENABLED_TOPIC,
    POOL_CREATED_TOPIC,
    V3_FACTORY,
    V3_POOL_REGISTRY_SCHEMA_VERSION,
    build_registry,
    decode_fee_amount_enabled,
    decode_pool_created,
    fetch_leaf,
    leaf_complete,
    leaf_paths,
    load_certified_frozen_upper,
    load_registry,
    reopen_registry_evidence,
    root_ranges,
)


TOKEN0 = "0x" + "1" * 40
TOKEN1 = "0x" + "2" * 40
FEE = 3_000
POOL = compute_pool_address(TOKEN0, TOKEN1, FEE)


def frozen_upper(block: int) -> dict[str, object]:
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "number": hex(block),
            "hash": "0x" + "9" * 64,
            "parentHash": "0x" + "8" * 64,
            "timestamp": hex(1_700_000_000),
        },
    }
    endpoint = {"host": "injected", "endpoint_sha256": "0" * 64}
    record = {
        "status": "complete",
        "schema_version": V3_POOL_REGISTRY_SCHEMA_VERSION,
        "block_number": block,
        "block_hash": "0x" + "9" * 64,
        "parent_hash": "0x" + "8" * 64,
        "timestamp": 1_700_000_000,
        "rpc_request": {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getBlockByNumber",
            "params": [hex(block), False],
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
        "response_sha256": hashlib.sha256(
            json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    identity = {
        "block_number": block,
        "block_hash": record["block_hash"],
        "parent_hash": record["parent_hash"],
        "timestamp": record["timestamp"],
    }
    record["header_identity_sha256"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return record


def canonical_record(
    *,
    pool: str = POOL,
    block: int = 105,
    log_index: int = 7,
) -> dict[str, object]:
    return {
        "address": V3_FACTORY,
        "block_number": block,
        "block_hash": "0x" + "a" * 64,
        "transaction_hash": "0x" + "b" * 64,
        "transaction_index": 1,
        "log_index": log_index,
        "topics": [
            POOL_CREATED_TOPIC,
            "0x" + TOKEN0.removeprefix("0x").rjust(64, "0"),
            "0x" + TOKEN1.removeprefix("0x").rjust(64, "0"),
            "0x" + hex(FEE)[2:].rjust(64, "0"),
        ],
        "data": "0x" + abi_encode(["int24", "address"], [60, pool]).hex(),
        "removed": False,
    }


def fee_record(*, block: int = 104, log_index: int = 6) -> dict[str, object]:
    return {
        "address": V3_FACTORY,
        "block_number": block,
        "block_hash": "0x" + "a" * 64,
        "transaction_hash": "0x" + "c" * 64,
        "transaction_index": 0,
        "log_index": log_index,
        "topics": [
            FEE_AMOUNT_ENABLED_TOPIC,
            "0x" + hex(FEE)[2:].rjust(64, "0"),
            "0x" + hex(60)[2:].rjust(64, "0"),
        ],
        "data": "0x",
        "removed": False,
    }


def rpc_record(record: dict[str, object] | None = None) -> dict[str, object]:
    record = record or canonical_record()
    return {
        "address": record["address"],
        "blockNumber": hex(int(record["block_number"])),
        "blockHash": record["block_hash"],
        "transactionHash": record["transaction_hash"],
        "transactionIndex": hex(int(record["transaction_index"])),
        "logIndex": hex(int(record["log_index"])),
        "topics": record["topics"],
        "data": record["data"],
        "removed": False,
    }


def test_pool_created_decodes_and_enforces_create2_identity() -> None:
    decoded = decode_pool_created(canonical_record())
    assert decoded.pool == POOL
    assert decoded.token0 == TOKEN0
    assert decoded.token1 == TOKEN1
    assert decoded.fee == FEE
    with pytest.raises(ValueError, match="CREATE2"):
        decode_pool_created(canonical_record(pool="0x" + "f" * 40))


def test_fee_amount_enabled_decodes_dynamic_factory_tier() -> None:
    assert decode_fee_amount_enabled(fee_record()) == (FEE, 60)


def test_v3_factory_roots_cover_both_edges_once() -> None:
    assert root_ranges(12_345, 32_345) == [
        (12_345, 19_999),
        (20_000, 29_999),
        (30_000, 32_345),
    ]


def test_factory_leaf_is_reused_only_with_exact_frozen_evidence(tmp_path) -> None:
    frozen = frozen_upper(109)
    calls = []

    def rpc(payload, **_kwargs):
        calls.append(payload)
        header = dict(frozen["rpc_response"])
        header["id"] = 2
        return [
            {"jsonrpc": "2.0", "id": 1, "result": [rpc_record()]},
            header,
        ]

    fetch_leaf(
        100,
        109,
        frozen_upper=frozen,
        root=tmp_path,
        rpc_request=rpc,
    )
    assert leaf_complete(100, 109, frozen_upper=frozen, root=tmp_path)
    fetch_leaf(
        100,
        109,
        frozen_upper=frozen,
        root=tmp_path,
        rpc_request=rpc,
    )
    assert len(calls) == 1
    _raw_path, marker_path = leaf_paths(100, 109, root=tmp_path)
    marker = json.loads(marker_path.read_text())
    marker["frozen_upper_response"]["result"]["hash"] = "0x" + "7" * 64
    marker_path.write_text(json.dumps(marker))
    assert not leaf_complete(100, 109, frozen_upper=frozen, root=tmp_path)


def test_full_builder_fetches_missing_root_and_proves_fee_history(tmp_path) -> None:
    deployment = get_source("uniswap_v3").genesis_block
    upper = deployment + 10
    frozen = frozen_upper(upper)
    graph_static = tmp_path / "graph.jsonl.gz"
    with gzip.open(graph_static, "wt") as handle:
        handle.write(
            json.dumps(
                {
                    "id": "0x" + "e" * 40,
                    "token0": {"id": TOKEN0, "symbol": "USDC", "decimals": "6"},
                    "token1": {"id": TOKEN1, "symbol": "WETH", "decimals": "18"},
                }
            )
            + "\n"
        )

    def rpc(payload, **_kwargs):
        if isinstance(payload, dict):
            return frozen["rpc_response"]
        header = dict(frozen["rpc_response"])
        header["id"] = 2
        return [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": [
                    rpc_record(fee_record(block=deployment, log_index=1)),
                    rpc_record(canonical_record(block=deployment + 1, log_index=2)),
                ],
            },
            header,
        ]

    pools, missing = build_registry(
        upper,
        graph_static,
        analysis_cutoff_block=deployment + 1,
        fetch=True,
        workers=1,
        max_attempts=1,
        root=tmp_path,
        rpc_request=rpc,
    )

    assert (pools, missing) == (1, 1)
    certificate = json.loads((tmp_path / "certificate.json").read_text())
    assert certificate["event_topics"] == FACTORY_EVENT_TOPICS
    assert certificate["fee_tick_spacings"] == {str(FEE): 60}
    assert certificate["registry_snapshot_upper_block"] == upper
    assert certificate["analysis_cutoff_block"] == deployment + 1
    assert certificate["analysis_pool_count"] == 1
    assert certificate["graph_only"] == 1
    loaded = load_registry(
        tmp_path / "uniswap_v3_factory_pools.parquet",
        tmp_path / "certificate.json",
    )
    assert [pool.pool for pool in loaded] == [POOL]
    reopened, _certificate = reopen_registry_evidence(root=tmp_path)
    assert reopened == loaded
    certified_upper, _certificate = load_certified_frozen_upper(root=tmp_path)
    assert certified_upper["block_number"] == upper
    statics = pool_statics_from_factory(
        tmp_path / "uniswap_v3_factory_pools.parquet",
        tmp_path / "certificate.json",
        graph_static,
        candidate_tokens={TOKEN0},
    )
    assert statics[POOL].token1 == TOKEN1
    assert statics[POOL].decimals1 == 18


def test_certified_terminal_rejects_certificate_header_drift(tmp_path) -> None:
    deployment = get_source("uniswap_v3").genesis_block
    upper = deployment + 1
    frozen = frozen_upper(upper)
    graph_static = tmp_path / "graph.jsonl.gz"
    with gzip.open(graph_static, "wt") as handle:
        handle.write(json.dumps({"id": POOL}) + "\n")

    def rpc(payload, **_kwargs):
        if isinstance(payload, dict):
            return frozen["rpc_response"]
        header = dict(frozen["rpc_response"])
        header["id"] = 2
        return [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": [
                    rpc_record(fee_record(block=deployment, log_index=1)),
                    rpc_record(canonical_record(block=upper, log_index=2)),
                ],
            },
            header,
        ]

    build_registry(
        upper,
        graph_static,
        fetch=True,
        workers=1,
        max_attempts=1,
        root=tmp_path,
        rpc_request=rpc,
    )
    certificate_path = tmp_path / "certificate.json"
    certificate = json.loads(certificate_path.read_text())
    certificate["registry_snapshot_upper_block_hash"] = "0x" + "7" * 64
    certificate_path.write_text(json.dumps(certificate))
    with pytest.raises(ValueError, match="terminal header"):
        load_certified_frozen_upper(root=tmp_path)

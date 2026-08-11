from __future__ import annotations

from collections import Counter
from dataclasses import replace
from eth_abi import encode as abi_encode
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import pandas as pd
import pyarrow.parquet as pq
import pytest

import scripts.assemble_v3_inventory_event_shards as assemble_v3_inventory_event_shards
import scripts.fetch_v3_inventory_events as fetch_v3_inventory_events
from ddvc.ethereum_logs import file_sha256
from ddvc.fetch.sources import get_source
from ddvc.v3_inventory import (
    EVENT_TOPICS,
    INVENTORY_RAW_GENERATION,
    INVENTORY_RAW_MARKER_SCHEMA_VERSION,
    INVENTORY_ORDERED_MANIFEST_NAME,
    INVENTORY_STATE_GENERATION,
    RAW_LOG_SCHEMA,
    RAW_LOG_STORAGE_FORMAT,
    PoolStatic,
    apply_inventory_event,
    apply_inventory_events,
    assemble_inventory_shards,
    audit_inventory_chunks,
    balance_of_calldata,
    block_ranges,
    canonical_raw_log,
    canonical_inventory_start_block,
    day_for_block,
    decode_balance_of_result,
    decode_inventory_log,
    inventory_chunk_completed,
    inventory_chunk_evidence_path,
    inventory_snapshot_rows,
    inventory_chunk_paths,
    inventory_ordered_manifest_path,
    is_physical_inventory_transfer,
    pool_static_from_graph,
    validate_inventory_ordered_manifest,
    validate_inventory_shard_partition,
)
from ddvc.v3_pool_registry import V3_FACTORY_DEPLOYMENT_BLOCK, V3_POOL_REGISTRY_SCHEMA_VERSION
from ddvc.v3_inventory_calendar import (
    CODE_SOURCES as CALENDAR_CODE_SOURCES,
    _fetch_block_timestamp,
    last_block_before_timestamp,
)
from ddvc.quoter import RpcCapacityError, RpcSemanticError, Throttled
from scripts.build_v3_inventory_panel import (
    CODE_SOURCES as PANEL_CODE_SOURCES,
    inventory_perimeter,
)
from scripts.audit_v3_inventory_balances import audit_sample_table
from ddvc.v3_event_completeness import (
    V3EventPayload,
    V3PoolAuthority,
    canonical_event_map,
    compare_event_maps,
)
from scripts.fetch_v3_inventory_events import (
    default_start_block,
    fetch_chunk,
    quarantine_invalid_chunk,
    run_fetch_jobs,
    safe_retry_reason,
    validate_shard_bounds,
)


def log(event: str, values: list[int], types: list[str]) -> dict:
    topics = [EVENT_TOPICS[event]]
    if event in {"mint", "burn"}:
        topics.extend(
            [
                "0x" + "00" * 32,
                "0x" + abi_encode(["int24"], [-120]).hex(),
                "0x" + abi_encode(["int24"], [120]).hex(),
            ]
        )
    return {
        "address": "0xpool",
        "blockNumber": "0x64",
        "blockHash": "0xblock",
        "logIndex": "0x7",
        "transactionHash": "0xtx",
        "transactionIndex": "0x2",
        "topics": topics,
        "data": "0x" + abi_encode(types, values).hex(),
    }


def frozen_upper(block: int = 220) -> dict[str, object]:
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


def factory_certificate(frozen: dict[str, object]) -> dict[str, object]:
    return {
        "registry_sha256": "1" * 64,
        "registry_snapshot_upper_block": frozen["block_number"],
        "registry_snapshot_upper_block_hash": frozen["block_hash"],
    }


def anchored_rpc(
    logs: list[dict[str, object]],
    frozen: dict[str, object],
    calls: list[tuple[int, int]] | None = None,
):
    def request(payload, **_kwargs):
        assert isinstance(payload, list) and len(payload) == 2
        log_filter = payload[0]["params"][0]
        lower = int(str(log_filter["fromBlock"]), 16)
        upper = int(str(log_filter["toBlock"]), 16)
        if calls is not None:
            calls.append((lower, upper))
        selected = [
            row
            for row in logs
            if lower <= int(str(row["blockNumber"]), 16) <= upper
        ]
        header = dict(frozen["rpc_response"])
        header["id"] = 2
        return [
            {"jsonrpc": "2.0", "id": 1, "result": selected},
            header,
        ]

    return request


def test_collect_and_protocol_collection_reduce_physical_inventory() -> None:
    collect = log(
        "collect",
        ["0x" + "00" * 20, 11, 13],
        ["address", "uint128", "uint128"],
    )
    protocol = log("collect_protocol", [17, 19], ["uint128", "uint128"])
    assert decode_inventory_log(collect)["amount0_delta_raw"] == -11
    assert decode_inventory_log(collect)["amount1_delta_raw"] == -13
    assert decode_inventory_log(protocol)["amount0_delta_raw"] == -17
    assert decode_inventory_log(protocol)["amount1_delta_raw"] == -19


def test_flash_inventory_delta_is_paid_less_borrowed() -> None:
    flash = log(
        "flash",
        [100, 200, 103, 207],
        ["uint256", "uint256", "uint256", "uint256"],
    )
    decoded = decode_inventory_log(flash)
    assert decoded["amount0_delta_raw"] == 3
    assert decoded["amount1_delta_raw"] == 7


def test_raw_mint_uses_exact_integer_transfer_amounts() -> None:
    mint = log(
        "mint",
        ["0x" + "00" * 20, 99, 775_343_764_933_267_394_725_819_694_029, 10**18],
        ["address", "uint128", "uint256", "uint256"],
    )
    decoded = decode_inventory_log(mint)
    assert decoded["amount0_delta_raw"] == 775_343_764_933_267_394_725_819_694_029
    assert decoded["amount1_delta_raw"] == 10**18
    assert decoded["liquidity_amount"] == 99
    assert (decoded["tick_lower"], decoded["tick_upper"]) == (-120, 120)


def test_raw_swap_uses_exact_signed_integer_transfer_amounts() -> None:
    swap = log(
        "swap",
        [-123, 456, 2**96, 999, -12],
        ["int256", "int256", "uint160", "uint128", "int24"],
    )
    decoded = decode_inventory_log(swap)
    assert decoded["amount0_delta_raw"] == -123
    assert decoded["amount1_delta_raw"] == 456
    assert decoded["sqrt_price_x96"] == 2**96
    assert decoded["active_liquidity"] == 999
    assert decoded["tick"] == -12


def test_burn_is_not_a_physical_inventory_transfer() -> None:
    burn = log(
        "burn",
        [123, 456, 789],
        ["uint128", "uint256", "uint256"],
    )
    decoded = decode_inventory_log(burn)
    assert decoded["event_type"] == "burn"
    assert decoded["amount0_delta_raw"] == 456
    assert decoded["amount1_delta_raw"] == 789
    assert decoded["physical_inventory_transfer"] is False
    balances = {"0xpool": (10, 20)}
    assert apply_inventory_event(balances, decoded) == (10, 20)
    assert balances == {"0xpool": (10, 20)}
    last_events: dict[str, tuple[int, int]] = {}
    event_counts: dict[str, int] = {}
    apply_inventory_events(
        balances,
        [decoded],
        last_events=last_events,
        event_counts=event_counts,
    )
    assert balances == {"0xpool": (10, 20)}
    assert last_events == {}
    assert event_counts == {}
    with pytest.raises(ValueError, match="contradictory V3 transfer semantics"):
        is_physical_inventory_transfer({**decoded, "physical_inventory_transfer": True})


def test_graph_source_audit_converts_large_decimal_amounts_exactly() -> None:
    item = static()
    authority = V3PoolAuthority(
        item.pool,
        item.token0,
        item.token1,
        item.decimals0,
        item.decimals1,
        3_000,
        60,
    )
    frame = pd.DataFrame(
        [
            {
                "pool": item.pool,
                "record_type": "liquidity",
                "source_stream": "mints",
                "block_number": 100,
                "log_index": 7,
                "tx_hash": "0xtx",
                "timestamp": 1_700_000_000,
                "token0_raw": item.token0,
                "token1_raw": item.token1,
                "decimals0": item.decimals0,
                "decimals1": item.decimals1,
                "amount0": "775343764933267394725819.694029",
                "amount1": "1",
                "liquidity_delta": 99,
                "tick_lower": -120,
                "tick_upper": 120,
                "sqrt_price_x96": None,
                "tick": None,
            },
            {
                "pool": item.pool,
                "record_type": "liquidity",
                "source_stream": "burns",
                "block_number": 101,
                "log_index": 8,
                "tx_hash": "0xburn",
                "timestamp": 1_700_000_012,
                "token0_raw": item.token0,
                "token1_raw": item.token1,
                "decimals0": item.decimals0,
                "decimals1": item.decimals1,
                "amount0": "2.5",
                "amount1": "3",
                "liquidity_delta": -50,
                "tick_lower": -60,
                "tick_upper": 60,
                "sqrt_price_x96": None,
                "tick": None,
            },
        ]
    )
    events, duplicates = canonical_event_map(frame, {item.pool: authority})
    assert duplicates == Counter(
        {
            ("mint", 100, "0xtx", 7, item.pool): 1,
            ("burn", 101, "0xburn", 8, item.pool): 1,
        }
    )
    assert events[("mint", 100, "0xtx", 7, item.pool)].amount0_raw == (
        775_343_764_933_267_394_725_819_694_029
    )
    assert events[("mint", 100, "0xtx", 7, item.pool)].amount1_raw == 10**18
    assert events[("burn", 101, "0xburn", 8, item.pool)].amount0_raw == 2_500_000
    assert events[("burn", 101, "0xburn", 8, item.pool)].amount1_raw == 3 * 10**18


def test_source_audit_separates_omissions_extras_and_amount_mismatches() -> None:
    mint = ("mint", 100, "0xa", 1, "0xpool")
    swap = ("swap", 101, "0xb", 2, "0xpool")
    graph_only = ("mint", 102, "0xc", 3, "0xpool")
    payload = V3EventPayload(
        1_700_000_000,
        "0xtoken0",
        "0xtoken1",
        6,
        18,
        3_000,
        60,
        1,
        2,
        None,
        None,
        10,
        -60,
        60,
    )
    summaries, exceptions = compare_event_maps(
        "20250115",
        {mint: payload, swap: payload},
        {mint: replace(payload, amount1_raw=9), graph_only: payload},
        Counter({mint: 1, graph_only: 2}),
    )
    by_type = {row["event_type"]: row for row in summaries}
    assert by_type["swap"]["missing_from_canonical"] == 1
    assert by_type["mint"]["canonical_only"] == 1
    assert by_type["mint"]["payload_mismatches"] == 1
    assert by_type["mint"]["canonical_duplicate_rows"] == 1
    assert {row["status"] for row in exceptions} == {
        "missing_from_canonical",
        "canonical_only",
        "payload_mismatch",
        "canonical_duplicate_identity",
    }


def test_block_chunks_cover_the_perimeter_once() -> None:
    assert block_ranges(10, 25, 6) == [(10, 11), (12, 17), (18, 23), (24, 25)]


def test_raw_event_perimeter_starts_at_factory_deployment() -> None:
    assert default_start_block() == get_source("uniswap_v3").factory_deployment_block


def test_raw_event_shard_bounds_must_align_to_canonical_chunks() -> None:
    start = default_start_block()
    terminal = start + 2_499
    ranges = block_ranges(start, terminal, 1_000)
    validate_shard_bounds(ranges[0][0], ranges[1][1], terminal, 1_000)
    with pytest.raises(ValueError, match="align"):
        validate_shard_bounds(ranges[0][0] + 1, ranges[1][1], terminal, 1_000)


def test_full_inventory_fetch_conflicts_with_an_active_shard() -> None:
    start = V3_FACTORY_DEPLOYMENT_BLOCK
    terminal = start + 199
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with (
            patch.object(
                fetch_v3_inventory_events,
                "RAW_MARKET_DATA_LOCK",
                root / "raw-market.lock",
            ),
            patch.object(
                fetch_v3_inventory_events,
                "V3_INVENTORY_RANGE_LOCK_ROOT",
                root / "ranges",
            ),
        ):
            with fetch_v3_inventory_events.inventory_fetch_ownership(
                start=start,
                end=start + 99,
                global_publication=False,
            ):
                with pytest.raises(RuntimeError, match="overlaps active V3 inventory shard fetch"):
                    with fetch_v3_inventory_events.inventory_fetch_ownership(
                        start=start,
                        end=terminal,
                        global_publication=True,
                    ):
                        raise AssertionError("full fetch acquired an active shard interval")
            with fetch_v3_inventory_events.inventory_fetch_ownership(
                start=start,
                end=terminal,
                global_publication=True,
            ):
                pass


def test_inventory_assembly_conflicts_with_an_active_shard() -> None:
    start = V3_FACTORY_DEPLOYMENT_BLOCK
    terminal = start + 199
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        range_root = root / "ranges"
        global_lock = root / "raw-market.lock"
        with (
            patch.object(
                fetch_v3_inventory_events,
                "V3_INVENTORY_RANGE_LOCK_ROOT",
                range_root,
            ),
            patch.object(
                assemble_v3_inventory_event_shards,
                "RAW_MARKET_DATA_LOCK",
                global_lock,
            ),
            patch.object(
                assemble_v3_inventory_event_shards,
                "V3_INVENTORY_RANGE_LOCK_ROOT",
                range_root,
            ),
        ):
            with fetch_v3_inventory_events.inventory_fetch_ownership(
                start=start + 100,
                end=terminal,
                global_publication=False,
            ):
                with pytest.raises(RuntimeError, match="overlaps active V3 inventory shard fetch"):
                    with assemble_v3_inventory_event_shards.inventory_assembly_ownership(
                        terminal=terminal
                    ):
                        raise AssertionError("assembly acquired an active shard interval")


def test_inventory_perimeter_starts_at_first_mint_or_swap_not_first_swap() -> None:
    records = [
        {"record_type": "liquidity", "source_stream": "burns", "block_number": 8},
        {"record_type": "swap", "source_stream": "swaps", "block_number": 12},
        {"record_type": "liquidity", "source_stream": "mints", "block_number": 10},
    ]
    assert canonical_inventory_start_block(records) == 10


def test_panel_inventory_perimeter_starts_at_factory_deployment() -> None:
    start, end = inventory_perimeter(["20210504"], [V3_FACTORY_DEPLOYMENT_BLOCK + 100])
    assert start == V3_FACTORY_DEPLOYMENT_BLOCK
    assert end == V3_FACTORY_DEPLOYMENT_BLOCK + 100


def static() -> PoolStatic:
    return PoolStatic(
        pool="0xpool",
        token0="0xtoken0",
        token1="0xtoken1",
        symbol0="USDC",
        symbol1="WETH",
        decimals0=6,
        decimals1=18,
    )


def test_graph_static_requires_exact_pool_and_token_identities() -> None:
    parsed = pool_static_from_graph(
        {
            "id": "0x" + "01" * 20,
            "token0": {"id": "0x" + "02" * 20, "symbol": "A", "decimals": "6"},
            "token1": {"id": "0x" + "03" * 20, "symbol": "B", "decimals": "18"},
        }
    )
    assert parsed.decimals0 == 6
    with pytest.raises(ValueError, match="exact contract identities"):
        pool_static_from_graph(
            {
                "id": "0xpool",
                "token0": {"id": "0xtoken0", "decimals": "6"},
                "token1": {"id": "0xtoken1", "decimals": "18"},
            }
        )


def test_inventory_checkpoint_preserves_negative_raw_balances_without_flooring() -> None:
    item = static()
    events = [
        {
            "pool": item.pool,
            "block_number": 10,
            "log_index": 1,
            "tx_hash": "0xa",
            "amount0_delta_raw": 2,
            "amount1_delta_raw": -3,
        }
    ]
    balances: dict[str, tuple[int, int]] = {}
    last: dict[str, tuple[int, int]] = {}
    counts: dict[str, int] = {}
    apply_inventory_events(balances, events, last_events=last, event_counts=counts)
    rows = inventory_snapshot_rows(
        day="20250101",
        end_block=20,
        statics={item.pool: item},
        balances=balances,
        last_events=last,
        event_counts=counts,
    )
    assert rows[0]["balance1_raw"] == "-3"
    assert rows[0]["negative_inventory"] is True
    assert rows[0]["replay_arithmetic_valid"] is False
    assert rows[0]["quantity_kind"] == "event_replayed_pool_inventory"
    assert rows[0]["state_generation"] == INVENTORY_STATE_GENERATION
    assert rows[0]["custody_validation_status"] == "pending_historical_balance_validation"
    assert rows[0]["ownership_validation_status"] == (
        "pending_protocol_fee_ownership_reconciliation"
    )


def test_day_calendar_uses_inclusive_strictly_increasing_block_cuts() -> None:
    days = ["20250101", "20250102", "20250103"]
    ends = [100, 200, 300]
    assert day_for_block(100, days, ends) == "20250101"
    assert day_for_block(101, days, ends) == "20250102"
    with pytest.raises(ValueError, match="strictly increasing"):
        day_for_block(1, days, [100, 100, 300])


def test_exact_day_cut_is_last_block_strictly_before_midnight() -> None:
    timestamps = {block: 1_000 + 12 * block for block in range(10, 31)}
    block, block_timestamp, next_timestamp = last_block_before_timestamp(
        1_241, 10, 30, timestamps.__getitem__
    )
    assert block == 20
    assert block_timestamp == 1_240
    assert next_timestamp == 1_252


def test_calendar_provenance_covers_every_semantic_dependency() -> None:
    assert set(CALENDAR_CODE_SOURCES) == {
        "src/ddvc/v3_inventory_calendar.py",
        "src/ddvc/ethereum_blocks.py",
        "src/ddvc/ethereum_day_cuts.py",
        "src/ddvc/fetch/raw.py",
        "src/ddvc/paths.py",
        "src/ddvc/quoter.py",
        "src/ddvc/runtime.py",
        "src/ddvc/state_data.py",
    }


def test_physical_inventory_cache_covers_every_semantic_dependency() -> None:
    assert set(PANEL_CODE_SOURCES) == {
        "scripts/assemble_v3_inventory_event_shards.py",
        "scripts/build_v3_inventory_panel.py",
        "scripts/fetch_v3_inventory_events.py",
        "src/ddvc/asset_types.py",
        "src/ddvc/ethereum_blocks.py",
        "src/ddvc/ethereum_day_cuts.py",
        "src/ddvc/ethereum_logs.py",
        "src/ddvc/fetch/raw.py",
        "src/ddvc/panel_assembly.py",
        "src/ddvc/paths.py",
        "src/ddvc/provenance.py",
        "src/ddvc/runtime.py",
        "src/ddvc/state_data.py",
        "src/ddvc/v3_inventory.py",
        "src/ddvc/v3_inventory_calendar.py",
        "src/ddvc/v3_pool_registry.py",
        "src/ddvc/pricing/v3pools.py",
    }


def test_calendar_rpc_retry_budget_is_not_nested_inside_rpc_post() -> None:
    response = {
        "result": {
            "number": "0x64",
            "hash": "0x" + "a" * 64,
            "parentHash": "0x" + "b" * 64,
            "timestamp": "0x3e8",
        }
    }
    evidence: list[dict[str, object]] = []
    with (
        patch("ddvc.v3_inventory_calendar.rpc_post", side_effect=[Throttled(), response]) as request,
        patch("ddvc.v3_inventory_calendar.time.sleep"),
    ):
        assert _fetch_block_timestamp(100, evidence) == 1_000
    assert request.call_count == 2
    assert all(item.kwargs["retries"] == 1 for item in request.call_args_list)
    assert len(evidence) == 1


def test_fetch_queue_retries_throttled_chunk_without_abandoning_other_work(capsys) -> None:
    calls: dict[tuple[int, int], int] = {}
    frozen = frozen_upper(2)

    def fetch(
        lower: int,
        upper: int,
        _frozen_upper: dict[str, object],
    ) -> dict[str, int]:
        key = (lower, upper)
        calls[key] = calls.get(key, 0) + 1
        if key == (1, 1) and calls[key] == 1:
            raise Throttled("temporary")
        return {"raw_logs": 1}

    totals, failures = run_fetch_jobs(
        [(1, 1), (2, 2)],
        frozen,
        workers=1,
        max_attempts=2,
        fetch=fetch,
    )
    assert totals == {"raw": 2}
    assert failures == []
    assert calls == {(1, 1): 2, (2, 2): 1}
    output = capsys.readouterr().out
    assert "retrying throttled inventory chunk 1-1" in output
    assert "queued_remaining=" in output


def test_fetch_queue_records_semantic_rpc_failure_without_abandoning_other_work(capsys) -> None:
    frozen = frozen_upper(2)
    endpoint = {
        "host": "provider.example",
        "endpoint_sha256": "1" * 64,
    }

    def fetch(
        lower: int,
        upper: int,
        _frozen_upper: dict[str, object],
    ) -> dict[str, int]:
        if (lower, upper) == (1, 1):
            raise RpcSemanticError(
                "invalid upstream response at https://provider.example/key/secret",
                attempts=(
                    {
                        "endpoint": endpoint,
                        "attempt": 1,
                        "classification": "terminal",
                        "http_status": 200,
                        "rpc_code": -32602,
                        "message": "invalid params",
                    },
                ),
            )
        return {"raw_logs": 1}

    totals, failures = run_fetch_jobs(
        [(1, 1), (2, 2)],
        frozen,
        workers=1,
        max_attempts=2,
        fetch=fetch,
    )
    assert totals == {"raw": 1}
    assert len(failures) == 1
    assert failures[0][:2] == (1, 1)
    assert "rpc_code=-32602" in failures[0][2]
    output = capsys.readouterr().out
    assert "terminal semantic inventory chunk 1-1" in output
    assert "message=invalid params" in output
    assert "provider.example" not in output
    assert "secret" not in output


def test_fetch_queue_records_single_block_capacity_once_without_endpoint_leakage(capsys) -> None:
    frozen = frozen_upper(2)
    calls = 0

    def fetch(
        lower: int,
        upper: int,
        _frozen_upper: dict[str, object],
    ) -> dict[str, int]:
        nonlocal calls
        calls += 1
        if (lower, upper) == (1, 1):
            raise RpcCapacityError(
                "capacity at https://provider.example/key/secret",
                attempts=(
                    {
                        "endpoint": {
                            "host": "provider.example",
                            "endpoint_sha256": "1" * 64,
                        },
                        "attempt": 1,
                        "classification": "capacity",
                        "http_status": 200,
                        "rpc_code": 30,
                        "message": "response size",
                    },
                ),
            )
        return {"raw_logs": 1}

    totals, failures = run_fetch_jobs(
        [(1, 1), (2, 2)],
        frozen,
        workers=1,
        max_attempts=12,
        fetch=fetch,
    )
    assert totals == {"raw": 1}
    assert len(failures) == 1
    assert failures[0][:2] == (1, 1)
    assert "rpc_code=30" in failures[0][2]
    assert calls == 2
    output = capsys.readouterr().out
    assert "terminal single-block capacity inventory chunk 1-1" in output
    assert "provider.example" not in output
    assert "secret" not in output


def test_inventory_retry_reason_redacts_endpoints_and_bounds_output() -> None:
    reason = safe_retry_reason(
        Throttled(
            "gateway https://provider.example/v1?api_key=secret failed\n"
            + "x" * 300
        )
    )
    assert "provider.example" not in reason
    assert "secret" not in reason
    assert "<endpoint>" in reason
    assert "\n" not in reason
    assert len(reason) == 200


def test_inventory_fetch_persists_exact_raw_log_parquet() -> None:
    raw = log(
        "swap",
        [-1, 2, 2**96, 99, 0],
        ["int256", "int256", "uint160", "uint128", "int24"],
    )
    raw.update(
        {
            "address": "0x" + "a" * 40,
            "blockHash": "0x" + "b" * 64,
            "transactionHash": "0x" + "c" * 64,
        }
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frozen = frozen_upper()
        metadata = fetch_chunk(
            100,
            100,
            frozen,
            root,
            rpc_request=anchored_rpc([raw], frozen),
        )
        raw_path, _meta_path = inventory_chunk_paths(100, 100, root)
        table = pq.read_table(raw_path)
        assert table.schema == RAW_LOG_SCHEMA
        assert table.to_pylist()[0] == canonical_raw_log(raw)
        assert metadata["storage_format"] == RAW_LOG_STORAGE_FORMAT
        assert metadata["schema_version"] == INVENTORY_RAW_MARKER_SCHEMA_VERSION
        assert metadata["inventory_raw_generation"] == INVENTORY_RAW_GENERATION
        assert metadata["raw_by_event"]["swap"] == 1
        assert inventory_chunk_completed(
            100,
            100,
            root,
            frozen_upper=frozen,
        )


def test_inventory_fetch_splits_storage_chunk_under_rpc_block_cap() -> None:
    calls: list[tuple[int, int]] = []

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frozen = frozen_upper()
        metadata = fetch_chunk(
            100,
            220,
            frozen,
            root,
            rpc_request=anchored_rpc([], frozen, calls),
        )
        assert calls == [(100, 149), (150, 199), (200, 220)]
        assert metadata["rpc_block_cap"] == 50
        assert metadata["rpc_subranges"] == 3
        assert inventory_chunk_completed(
            100,
            220,
            root,
            frozen_upper=frozen,
        )


def test_inventory_fetch_recursively_bisects_capacity_ranges_and_reuses_cache() -> None:
    calls: list[tuple[int, int]] = []
    endpoint = {"host": "provider.example", "endpoint_sha256": "1" * 64}

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frozen = frozen_upper()
        success = anchored_rpc([], frozen)

        def request(payload, **kwargs):
            log_filter = payload[0]["params"][0]
            lower = int(str(log_filter["fromBlock"]), 16)
            upper = int(str(log_filter["toBlock"]), 16)
            calls.append((lower, upper))
            if lower != upper:
                raise RpcCapacityError(
                    "provider response size exceeded",
                    attempts=(
                        {
                            "endpoint": endpoint,
                            "attempt": 1,
                            "classification": "capacity",
                            "http_status": 200,
                            "rpc_code": 30,
                            "message": "response size",
                        },
                    ),
                )
            return success(payload, **kwargs)

        metadata = fetch_chunk(100, 103, frozen, root, rpc_request=request)
        assert calls == [
            (100, 103),
            (100, 101),
            (100, 100),
            (101, 101),
            (102, 103),
            (102, 102),
            (103, 103),
        ]
        assert metadata["rpc_subranges"] == 4
        evidence_path = inventory_chunk_evidence_path(100, 103, root)
        with gzip.open(evidence_path, "rt", encoding="utf-8") as handle:
            evidence = json.load(handle)
        assert [
            (item["start_block"], item["end_block"])
            for item in evidence["rpc_subrange_evidence"]
        ] == [(100, 100), (101, 101), (102, 102), (103, 103)]
        assert inventory_chunk_completed(100, 103, root, frozen_upper=frozen)

        def must_not_refetch(*_args, **_kwargs):
            raise AssertionError("completed exact chunk should be reused")

        assert fetch_chunk(100, 103, frozen, root, rpc_request=must_not_refetch) == metadata

        evidence["rpc_subrange_evidence"][1]["start_block"] = 102
        with gzip.open(evidence_path, "wt", encoding="utf-8") as handle:
            json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        _raw_path, marker_path = inventory_chunk_paths(100, 103, root)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["rpc_evidence_sha256"] = file_sha256(evidence_path)
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        assert not inventory_chunk_completed(100, 103, root, frozen_upper=frozen)


def test_inventory_fetch_fails_closed_on_single_block_capacity_without_endpoint_leakage() -> None:
    endpoint = {"host": "provider.example", "endpoint_sha256": "1" * 64}

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frozen = frozen_upper()

        def request(_payload, **_kwargs):
            raise RpcCapacityError(
                "capacity at https://provider.example/key/secret",
                attempts=(
                    {
                        "endpoint": endpoint,
                        "attempt": 1,
                        "classification": "capacity",
                        "http_status": 200,
                        "rpc_code": 30,
                        "message": "response size",
                    },
                ),
            )

        with pytest.raises(RpcCapacityError, match="single-block") as raised:
            fetch_chunk(100, 100, frozen, root, rpc_request=request)
        detail = str(raised.value)
        assert "block 100" in detail
        assert "rpc_code=30" in detail
        assert "provider.example" not in detail
        assert "secret" not in detail
        assert not any(path.exists() for path in inventory_chunk_paths(100, 100, root))
        assert not inventory_chunk_evidence_path(100, 100, root).exists()


def _two_inventory_shards(base: Path) -> tuple[Path, Path, dict[str, object]]:
    frozen = frozen_upper()
    left, right = base / "left", base / "right"
    fetch_chunk(100, 199, frozen, left, rpc_request=anchored_rpc([], frozen))
    fetch_chunk(200, 220, frozen, right, rpc_request=anchored_rpc([], frozen))
    return left, right, frozen


def test_inventory_shard_assembly_publishes_manifest_last() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        left, right, frozen = _two_inventory_shards(base)
        destination = base / "assembled"
        copied: list[str] = []
        from ddvc import v3_inventory

        real_copyfile = v3_inventory.shutil.copyfile

        def record_copy(source: Path, target: Path) -> Path:
            copied.append(source.name)
            return real_copyfile(source, target)

        with patch("ddvc.v3_inventory.shutil.copyfile", side_effect=record_copy):
            record = assemble_inventory_shards(
                [(left, (100, 199)), (right, (200, 220))],
                destination,
                start=100,
                end=220,
                chunk_size=100,
                frozen_upper=frozen,
                factory_certificate=factory_certificate(frozen),
            )
        assert [Path(name).suffixes for name in copied[:3]] == [
            [".parquet"],
            [".rpc", ".json", ".gz"],
            [".meta", ".json"],
        ]
        assert [Path(name).suffixes for name in copied[3:]] == [
            [".parquet"],
            [".rpc", ".json", ".gz"],
            [".meta", ".json"],
        ]
        assert record["chunk_count"] == 2
        assert record["raw_logs"] == 0
        assert inventory_ordered_manifest_path(destination).name == INVENTORY_ORDERED_MANIFEST_NAME
        assert validate_inventory_ordered_manifest(
            destination,
            [(100, 199), (200, 220)],
            chunk_size=100,
            frozen_upper=frozen,
            factory_certificate=factory_certificate(frozen),
        ) == record


def test_inventory_ordered_manifest_recomputes_portable_digest_on_builder_gate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        left, right, frozen = _two_inventory_shards(base)
        destination = base / "assembled"
        assemble_inventory_shards(
            [(left, (100, 199)), (right, (200, 220))],
            destination,
            start=100,
            end=220,
            chunk_size=100,
            frozen_upper=frozen,
            factory_certificate=factory_certificate(frozen),
        )
        manifest_path = inventory_ordered_manifest_path(destination)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["portable_manifest_sha256"] = "f" * 64
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="aggregate identity"):
            validate_inventory_ordered_manifest(
                destination,
                [(100, 199), (200, 220)],
                chunk_size=100,
                frozen_upper=frozen,
                factory_certificate=factory_certificate(frozen),
                reopen_chunks=False,
            )


def test_inventory_chunk_rejects_tampered_event_counts() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frozen = frozen_upper()
        fetch_chunk(100, 199, frozen, root, rpc_request=anchored_rpc([], frozen))
        _raw, marker_path = inventory_chunk_paths(100, 199, root)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["raw_by_event"]["burn"] = 999
        marker_path.write_text(json.dumps(marker) + "\n", encoding="utf-8")
        assert not inventory_chunk_completed(100, 199, root, frozen_upper=frozen)


def test_inventory_shard_assembly_rejects_any_unexpected_root_entry() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        left, right, frozen = _two_inventory_shards(base)
        (left / "unexpected.txt").write_text("stale\n", encoding="utf-8")
        with pytest.raises(ValueError, match="interrupted or malformed"):
            assemble_inventory_shards(
                [(left, (100, 199)), (right, (200, 220))],
                base / "assembled",
                start=100,
                end=220,
                chunk_size=100,
                frozen_upper=frozen,
                factory_certificate=factory_certificate(frozen),
            )


@pytest.mark.parametrize(
    "shards",
    [
        [(100, 149), (151, 220)],
        [(100, 199), (150, 220)],
        [(100, 150), (151, 220)],
    ],
)
def test_inventory_shard_partition_rejects_gap_overlap_and_unaligned_bounds(
    shards: list[tuple[int, int]],
) -> None:
    with pytest.raises(ValueError, match="gap, overlap, or unaligned"):
        validate_inventory_shard_partition(shards, start=100, end=220, chunk_size=100)


def test_inventory_shard_assembly_rejects_stale_alternate_range() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        left, right, frozen = _two_inventory_shards(base)
        (left / "blocks_00000150_00000199.parquet").write_bytes(b"stale")
        with pytest.raises(ValueError, match="alternate overlapping"):
            assemble_inventory_shards(
                [(left, (100, 199)), (right, (200, 220))],
                base / "assembled",
                start=100,
                end=220,
                chunk_size=100,
                frozen_upper=frozen,
                factory_certificate=factory_certificate(frozen),
            )


def test_inventory_shard_assembly_rejects_collision_without_overwrite() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        left, right, frozen = _two_inventory_shards(base)
        destination = base / "assembled"
        destination.mkdir()
        target = inventory_chunk_paths(100, 199, destination)[0]
        target.write_bytes(b"collision")
        with pytest.raises(FileExistsError, match="merge collision"):
            assemble_inventory_shards(
                [(left, (100, 199)), (right, (200, 220))],
                destination,
                start=100,
                end=220,
                chunk_size=100,
                frozen_upper=frozen,
                factory_certificate=factory_certificate(frozen),
            )
        assert target.read_bytes() == b"collision"
        assert not inventory_ordered_manifest_path(destination).exists()


def test_inventory_shard_assembly_rejects_interrupted_copy_sentinel() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        left, right, frozen = _two_inventory_shards(base)
        destination = base / "assembled"
        destination.mkdir()
        (destination / ".blocks_00000100_00000199.parquet.dead.tmp").write_bytes(b"partial")
        with pytest.raises(ValueError, match="interrupted or malformed"):
            assemble_inventory_shards(
                [(left, (100, 199)), (right, (200, 220))],
                destination,
                start=100,
                end=220,
                chunk_size=100,
                frozen_upper=frozen,
                factory_certificate=factory_certificate(frozen),
            )
        assert not inventory_ordered_manifest_path(destination).exists()


def test_inventory_shard_assembly_rejects_factory_frozen_header_mismatch() -> None:
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        left, right, frozen = _two_inventory_shards(base)
        certificate = factory_certificate(frozen)
        certificate["registry_snapshot_upper_block_hash"] = "0x" + "7" * 64
        with pytest.raises(ValueError, match="factory and frozen-header"):
            assemble_inventory_shards(
                [(left, (100, 199)), (right, (200, 220))],
                base / "assembled",
                start=100,
                end=220,
                chunk_size=100,
                frozen_upper=frozen,
                factory_certificate=certificate,
            )


@pytest.mark.parametrize("tamper", ["rpc_response", "rpc_attempts", "upper_header"])
def test_inventory_chunk_reopens_every_rpc_evidence_field(tamper: str) -> None:
    raw = log(
        "swap",
        [-1, 2, 2**96, 99, 0],
        ["int256", "int256", "uint160", "uint128", "int24"],
    )
    raw.update(
        {
            "address": "0x" + "a" * 40,
            "blockHash": "0x" + "b" * 64,
            "transactionHash": "0x" + "c" * 64,
        }
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frozen = frozen_upper()
        fetch_chunk(
            100,
            100,
            frozen,
            root,
            rpc_request=anchored_rpc([raw], frozen),
        )
        evidence_path = inventory_chunk_evidence_path(100, 100, root)
        with gzip.open(evidence_path, "rt", encoding="utf-8") as handle:
            evidence = json.load(handle)
        subrange = evidence["rpc_subrange_evidence"][0]
        if tamper == "rpc_response":
            subrange["rpc_response"][0]["result"][0]["data"] = "0x00"
        elif tamper == "rpc_attempts":
            subrange["rpc_attempts"] = []
        else:
            subrange["frozen_upper_response"]["result"]["hash"] = "0x" + "7" * 64
        with gzip.open(evidence_path, "wt", encoding="utf-8") as handle:
            json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        _raw_path, marker_path = inventory_chunk_paths(100, 100, root)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["rpc_evidence_sha256"] = file_sha256(evidence_path)
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        assert not inventory_chunk_completed(
            100,
            100,
            root,
            frozen_upper=frozen,
        )


def test_legacy_inventory_chunk_is_recoverably_quarantined() -> None:
    raw = log("collect_protocol", [1, 2], ["uint128", "uint128"])
    raw.update(
        {
            "address": "0x" + "a" * 40,
            "blockHash": "0x" + "b" * 64,
            "transactionHash": "0x" + "c" * 64,
        }
    )
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        root = base / "raw"
        frozen = frozen_upper()
        fetch_chunk(
            100,
            100,
            frozen,
            root,
            rpc_request=anchored_rpc([raw], frozen),
        )
        evidence_path = inventory_chunk_evidence_path(100, 100, root)
        evidence_path.unlink()
        _raw_path, marker_path = inventory_chunk_paths(100, 100, root)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker.pop("inventory_raw_generation")
        marker.pop("schema_version")
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        assert not inventory_chunk_completed(
            100,
            100,
            root,
            frozen_upper=frozen,
        )
        destination = quarantine_invalid_chunk(
            100,
            100,
            frozen_upper=frozen,
            root=root,
        )
        assert destination is not None
        assert not any(root.glob("blocks_00000100_00000100.*"))
        quarantine = json.loads((destination / "quarantine.json").read_text())
        assert quarantine["reason"] == "missing_or_invalid_anchored_rpc_evidence"
        assert sorted(quarantine["files"]) == [
            "blocks_00000100_00000100.meta.json",
            "blocks_00000100_00000100.parquet",
        ]


def test_raw_inventory_chunk_audit_reconciles_content_and_metadata() -> None:
    raw = log("collect_protocol", [1, 2], ["uint128", "uint128"])
    raw.update(
        {
            "address": "0x" + "1" * 40,
            "blockHash": "0x" + "a" * 64,
            "transactionHash": "0x" + "b" * 64,
        }
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frozen = frozen_upper()
        fetch_chunk(
            100,
            100,
            frozen,
            root,
            rpc_request=anchored_rpc([raw], frozen),
        )
        totals = audit_inventory_chunks(
            [(100, 100)],
            root,
            pool_creation_blocks={raw["address"]: 99},
            frozen_upper=frozen,
        )
    assert totals["chunks"] == 1
    assert totals["raw_logs"] == 1
    assert totals["canonical_pool_logs"] == 1
    assert totals["quarantined_logs"] == 0
    assert totals["canonical_by_event"]["collect_protocol"] == 1


def test_raw_inventory_audit_quarantines_nonfactory_and_precreation_logs() -> None:
    canonical = log(
        "swap",
        [-1, 2, 2**96, 99, 0],
        ["int256", "int256", "uint160", "uint128", "int24"],
    )
    canonical.update(
        {
            "address": "0x" + "1" * 40,
            "blockHash": "0x" + "a" * 64,
            "transactionHash": "0x" + "b" * 64,
            "logIndex": "0x1",
        }
    )
    absent = {
        **canonical,
        "address": "0x" + "2" * 40,
        "transactionHash": "0x" + "c" * 64,
        "logIndex": "0x2",
    }
    precreation = {
        **canonical,
        "transactionHash": "0x" + "d" * 64,
        "logIndex": "0x3",
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frozen = frozen_upper()
        fetch_chunk(
            100,
            100,
            frozen,
            root,
            rpc_request=anchored_rpc([canonical, absent, precreation], frozen),
        )
        totals = audit_inventory_chunks(
            [(100, 100)],
            root,
            pool_creation_blocks={canonical["address"]: 101},
            frozen_upper=frozen,
        )
    assert totals["canonical_pool_logs"] == 0
    assert totals["quarantined_logs"] == 3
    assert totals["quarantined_pools"] == 2
    assert totals["quarantine_reasons"] == {
        "absent_from_canonical_poolcreated_registry": 1,
        "predates_canonical_pool_creation": 2,
    }
    ledger = totals["quarantine_pool_ledger"]
    assert [row["reason"] for row in ledger] == [
        "predates_canonical_pool_creation",
        "absent_from_canonical_poolcreated_registry",
    ]
    assert [row["logs"] for row in ledger] == [2, 1]
    assert sum(row["swap_logs"] for row in ledger) == 3


def test_balance_of_call_and_result_are_exact_uint256() -> None:
    calldata = balance_of_calldata("0x" + "12" * 20)
    assert calldata.endswith("12" * 20)
    assert len(calldata) == 74
    assert decode_balance_of_result("0x" + "ff" * 32) == 2**256 - 1


def test_balance_audit_sample_keeps_pool_edges_and_calendar_audit_date_value_mass() -> None:
    token0 = "0x" + "01" * 20
    token1 = "0x" + "02" * 20
    pool = "0x" + "03" * 20
    rows = []
    for day, block in (("20250101", 100), ("20250115", 200), ("20250131", 300)):
        rows.append(
            {
                "venue": "uniswap_v3",
                "day": day,
                "day_end_block": block,
                "pool": pool,
                "token0_address": token0,
                "token0_symbol": "A",
                "token0_decimals": 6,
                "token1_address": token1,
                "token1_symbol": "B",
                "token1_decimals": 18,
                "balance0_raw": "1000000",
                "balance1_raw": "1000000000000000000",
                "balance0_units": 1.0,
                "balance1_units": 1.0,
                "negative_inventory": False,
                "replay_arithmetic_valid": True,
                "quantity_kind": "event_replayed_pool_inventory",
                "custody_validation_status": "pending_historical_balance_validation",
                "ownership_validation_status": "pending_protocol_fee_ownership_reconciliation",
                "state_generation": "test",
            }
        )
    prices = [
        {"day": day, "token": token, "price_usd": price}
        for day in ("20250101", "20250115", "20250131")
        for token, price in ((token0, 1.0), (token1, 2.0))
    ]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        inventory_path = root / "inventory.parquet"
        price_path = root / "prices.parquet"
        pd.DataFrame(rows).to_parquet(inventory_path, index=False)
        pd.DataFrame(prices).to_parquet(price_path, index=False)
        sample = audit_sample_table(inventory_path, price_path).to_pandas()
    assert sample["day"].tolist() == ["20250101", "20250131"]
    final_reason = sample.loc[sample["day"].eq("20250131"), "sample_reason"].iloc[0]
    assert "audit_date_value_mass" in final_reason
    assert "final_observed_pool_cut" in final_reason
    assert bool(sample.loc[sample["day"].eq("20250131"), "full_valuation_support"].iloc[0])


def test_removed_inventory_log_is_rejected() -> None:
    removed = log("collect_protocol", [1, 2], ["uint128", "uint128"])
    removed["removed"] = True
    with pytest.raises(ValueError, match="removed"):
        decode_inventory_log(removed)

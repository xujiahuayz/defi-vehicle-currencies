from __future__ import annotations

import gzip
import json
from pathlib import Path

from eth_abi import encode as abi_encode

from ddvc.ethereum_logs import write_exact_log_chunk
from ddvc.graph_event_order import (
    V3_STATE_EVENT_TOPICS,
    correction_root_for_graph,
    load_graph_events,
    match_event_orders,
    supplement_action,
    supplement_source_row,
    write_correction_generation,
)
from ddvc.state_data import normalise_tick_partition
from ddvc.v2_event_completeness import V2_EVENT_TOPICS


def graph_swap(event_id: str, tx_hash: str, amount0: str, amount1: str) -> dict:
    return {
        "id": event_id,
        "transaction": {"id": tx_hash, "blockNumber": "10", "timestamp": "100"},
        "timestamp": "100",
        "logIndex": "7",
        "amount0": amount0,
        "amount1": amount1,
        "sqrtPriceX96": str(1 << 96),
        "tick": "0",
        "pool": {
            "id": "0xpool",
            "feeTier": "500",
            "token0": {"id": "0xa", "symbol": "A", "decimals": "18"},
            "token1": {"id": "0xb", "symbol": "B", "decimals": "6"},
        },
    }


def exact_swap(tx_hash: str, log_index: int, amount0: int, amount1: int) -> dict[str, object]:
    return {
        "address": "0xpool",
        "block_number": 10,
        "block_hash": "0xblock",
        "transaction_hash": tx_hash,
        "transaction_index": 1,
        "log_index": log_index,
        "topics": [V3_STATE_EVENT_TOPICS["swap"], "0xsender", "0xrecipient"],
        "data": "0x"
        + abi_encode(
            ["int256", "int256", "uint160", "uint128", "int24"],
            [amount0, amount1, 1 << 96, 100, 0],
        ).hex(),
        "removed": False,
    }


def exact_burn(
    tx_hash: str,
    log_index: int,
    amount: int,
    amount0: int,
    amount1: int,
) -> dict[str, object]:
    return {
        "address": "0xpool",
        "block_number": 10,
        "block_hash": "0xblock",
        "transaction_hash": tx_hash,
        "transaction_index": 1,
        "log_index": log_index,
        "topics": [
            V3_STATE_EVENT_TOPICS["burn"],
            "0x" + "0" * 64,
            "0x" + abi_encode(["int24"], [-10]).hex(),
            "0x" + abi_encode(["int24"], [10]).hex(),
        ],
        "data": "0x"
        + abi_encode(
            ["uint128", "uint256", "uint256"],
            [amount, amount0, amount1],
        ).hex(),
        "removed": False,
    }


def write_graph_day(
    raw_root: Path,
    rows: list[dict],
    *,
    mints: list[dict] | None = None,
    burns: list[dict] | None = None,
) -> None:
    venue_root = raw_root / "uniswap_v3"
    venue_root.mkdir(parents=True)
    stream_rows = {"swaps": rows, "mints": mints or [], "burns": burns or []}
    for stream in ("swaps", "mints", "burns"):
        path = venue_root / f"uniswap_v3_{stream}_20250101.jsonl.gz"
        with gzip.open(path, "wt") as handle:
            for row in stream_rows[stream]:
                handle.write(json.dumps(row) + "\n")


def write_v3_statics(raw_root: Path) -> None:
    path = raw_root / "uniswap_v3" / "uniswap_v3_pool_statics_20250101.jsonl.gz"
    with gzip.open(path, "wt") as handle:
        handle.write(
            json.dumps(
                {
                    "id": "0xpool",
                    "token0": {"id": "0xa", "decimals": "18"},
                    "token1": {"id": "0xb", "decimals": "6"},
                }
            )
            + "\n"
        )


def test_v3_receipt_order_generation_repairs_causal_collisions(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    graph_rows = [
        graph_swap("event-one", "0xtx1", "1", "-2"),
        graph_swap("event-two", "0xtx2", "3", "-4"),
    ]
    write_graph_day(raw_root, graph_rows)
    graph = load_graph_events(raw_root, "uniswap_v3", "20250101")
    exact = [
        exact_swap("0xtx1", 99, 10**18, -2 * 10**6),
        exact_swap("0xtx2", 122, 3 * 10**18, -4 * 10**6),
    ]
    corrections, supplements, audit = match_event_orders(graph, exact, "uniswap_v3")
    assert supplements == []
    assert audit["correction_rows"] == 2
    assert {row["chain_log_index"] for row in corrections} == {99, 122}

    correction_root = correction_root_for_graph(raw_root)
    exact_path = correction_root / "uniswap_v3" / "20250101" / "blocks_10_10.parquet"
    exact_marker = exact_path.with_suffix(".meta.json")
    write_exact_log_chunk(
        exact_path,
        exact_marker,
        exact,
        {
            "kind": "test",
            "venue": "uniswap_v3",
            "day": "20250101",
            "start_block": 10,
            "end_block": 10,
            "event_topics": [V3_STATE_EVENT_TOPICS["swap"]],
        },
    )
    write_correction_generation(
        root=correction_root,
        raw_root=raw_root,
        venue="uniswap_v3",
        day="20250101",
        corrections=corrections,
        supplements=[],
        block_timestamp_evidence=[],
        exact_log_paths=[exact_path, exact_marker],
        audit=audit,
        start_block=10,
        end_block=10,
    )
    frame, quality = normalise_tick_partition(raw_root, "uniswap_v3", "20250101")
    assert quality.passed
    assert quality.conflicting_events == 0
    assert set(frame["log_index"].astype(int)) == {99, 122}
    assert len(quality.input_fingerprint) == 64


def test_reconciliation_surfaces_an_exact_event_omitted_by_provider(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    write_graph_day(raw_root, [graph_swap("event-one", "0xtx1", "1", "-2")])
    graph = load_graph_events(raw_root, "uniswap_v3", "20250101")
    exact = [
        exact_swap("0xtx1", 99, 10**18, -2 * 10**6),
        exact_swap("0xtx2", 122, 3 * 10**18, -4 * 10**6),
    ]
    corrections, supplements, audit = match_event_orders(graph, exact, "uniswap_v3")
    assert corrections[0]["chain_log_index"] == 99
    assert [event.tx_hash for event in supplements] == ["0xtx2"]
    assert audit["supplement_rows"] == 1


def test_reconciliation_repairs_duplicates_rounding_and_omissions(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    graph_rows = [
        graph_swap("provider-one", "0xtx1", "1.000000000000000003", "-2"),
        graph_swap("provider-duplicate", "0xtx1", "1.000000000000000003", "-2"),
    ]
    write_graph_day(raw_root, graph_rows)
    write_v3_statics(raw_root)
    exact = [
        exact_swap("0xtx1", 7, 10**18, -2 * 10**6),
        exact_swap("0xtx2", 8, 2 * 10**18, -3 * 10**6),
        exact_burn("0xtx3", 9, 10, 10**18, 2 * 10**6),
        exact_burn("0xtx4", 10, 0, 0, 0),
    ]
    graph = load_graph_events(raw_root, "uniswap_v3", "20250101")
    corrections, missing, audit = match_event_orders(graph, exact, "uniswap_v3")
    assert audit["provider_duplicate_rows"] == 1
    assert audit["payload_mismatches"] == 1
    assert audit["supplement_rows"] == 2
    assert audit["ignored_zero_liquidity_events"] == 1
    assert len(corrections) == 2

    template = graph_rows[0]["pool"]
    supplements = [
        supplement_action(event, supplement_source_row(event, template, 100))
        for event in missing
    ]
    correction_root = correction_root_for_graph(raw_root)
    exact_path = correction_root / "uniswap_v3" / "20250101" / "blocks_10_10.parquet"
    exact_marker = exact_path.with_suffix(".meta.json")
    write_exact_log_chunk(
        exact_path,
        exact_marker,
        exact,
        {
            "kind": "test",
            "venue": "uniswap_v3",
            "day": "20250101",
            "start_block": 10,
            "end_block": 10,
            "event_topics": list(V3_STATE_EVENT_TOPICS.values()),
        },
    )
    write_correction_generation(
        root=correction_root,
        raw_root=raw_root,
        venue="uniswap_v3",
        day="20250101",
        corrections=corrections,
        supplements=supplements,
        block_timestamp_evidence=[
            {
                "request": {
                    "method": "eth_getBlockByNumber",
                    "params": ["0xa", False],
                },
                "response": {"number": "0xa", "timestamp": "0x64"},
            }
        ],
        exact_log_paths=[exact_path, exact_marker],
        audit=audit,
        start_block=10,
        end_block=10,
    )
    frame, quality = normalise_tick_partition(raw_root, "uniswap_v3", "20250101")
    assert quality.passed
    assert quality.duplicate_events == 1
    assert quality.conflicting_events == 0
    assert set(frame["log_index"].astype(int)) == {7, 8, 9}
    corrected = frame.loc[frame["tx_hash"] == "0xtx1"].iloc[0]
    assert corrected["amount0"] == "1"


def test_reconciliation_rejects_ambiguous_structural_payload_matches(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    rows = [
        graph_swap("provider-one", "0xtx1", "1.000000000000000003", "-2"),
        graph_swap("provider-two", "0xtx1", "3.000000000000000003", "-4"),
    ]
    write_graph_day(raw_root, rows)
    graph = load_graph_events(raw_root, "uniswap_v3", "20250101")
    exact = [
        exact_swap("0xtx1", 99, 10**18, -2 * 10**6),
        exact_swap("0xtx1", 100, 3 * 10**18, -4 * 10**6),
    ]
    try:
        match_event_orders(graph, exact, "uniswap_v3")
    except RuntimeError as error:
        assert "ambiguous structural V3 payload" in str(error)
    else:
        raise AssertionError("ambiguous structural payloads did not fail closed")


def test_v3_swap_uses_hashed_pool_statics_when_event_decimals_are_absent(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    row = graph_swap("event-one", "0xtx1", "1", "-2")
    row["pool"]["token0"].pop("decimals")
    row["pool"]["token1"].pop("decimals")
    write_graph_day(raw_root, [row])
    write_v3_statics(raw_root)
    graph = load_graph_events(raw_root, "uniswap_v3", "20250101")
    corrections, supplements, audit = match_event_orders(
        graph,
        [exact_swap("0xtx1", 99, 10**18, -2 * 10**6)],
        "uniswap_v3",
    )
    assert supplements == []
    assert audit["matched_events"] == 1
    assert corrections[0]["chain_log_index"] == 99


def test_v2_events_use_hashed_same_day_snapshot_decimals(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    venue_root = raw_root / "uniswap_v2"
    venue_root.mkdir(parents=True)
    pair = {
        "id": "0xpool",
        "token0": {"id": "0xa", "symbol": "A"},
        "token1": {"id": "0xb", "symbol": "B"},
    }
    swap = {
        "id": "event-one",
        "transaction": {"id": "0xtx1", "blockNumber": "10", "timestamp": "100"},
        "timestamp": "100",
        "logIndex": "7",
        "amount0In": "1",
        "amount1In": "0",
        "amount0Out": "0",
        "amount1Out": "2",
        "pair": pair,
    }
    snapshot_pair = {
        **pair,
        "token0": {**pair["token0"], "decimals": "18"},
        "token1": {**pair["token1"], "decimals": "6"},
    }
    rows = {
        "swaps": [swap],
        "mints": [],
        "burns": [],
        "hourly_reserves": [
            {"id": "state", "hourStartUnix": "0", "pair": snapshot_pair}
        ],
    }
    for stream, stream_rows in rows.items():
        with gzip.open(venue_root / f"uniswap_v2_{stream}_20250101.jsonl.gz", "wt") as handle:
            for row in stream_rows:
                handle.write(json.dumps(row) + "\n")
    exact = [{
        "address": "0xpool",
        "block_number": 10,
        "block_hash": "0xblock",
        "transaction_hash": "0xtx1",
        "transaction_index": 1,
        "log_index": 99,
        "topics": [V2_EVENT_TOPICS["swap"]],
        "data": "0x" + abi_encode(
            ["uint256", "uint256", "uint256", "uint256"],
            [10**18, 0, 0, 2 * 10**6],
        ).hex(),
        "removed": False,
    }]
    graph = load_graph_events(raw_root, "uniswap_v2", "20250101")
    corrections, supplements, audit = match_event_orders(graph, exact, "uniswap_v2")
    assert supplements == []
    assert audit["matched_events"] == 1
    assert corrections[0]["chain_log_index"] == 99

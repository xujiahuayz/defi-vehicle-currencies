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
    write_correction_generation,
)
from ddvc.state_data import normalise_tick_partition


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


def write_graph_day(raw_root: Path, rows: list[dict]) -> None:
    venue_root = raw_root / "uniswap_v3"
    venue_root.mkdir(parents=True)
    for stream in ("swaps", "mints", "burns"):
        path = venue_root / f"uniswap_v3_{stream}_20250101.jsonl.gz"
        with gzip.open(path, "wt") as handle:
            for row in rows if stream == "swaps" else []:
                handle.write(json.dumps(row) + "\n")


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
    corrections, audit = match_event_orders(graph, exact, "uniswap_v3")
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


def test_reconciliation_fails_when_exact_source_has_an_unmatched_event(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    write_graph_day(raw_root, [graph_swap("event-one", "0xtx1", "1", "-2")])
    graph = load_graph_events(raw_root, "uniswap_v3", "20250101")
    exact = [
        exact_swap("0xtx1", 99, 10**18, -2 * 10**6),
        exact_swap("0xtx2", 122, 3 * 10**18, -4 * 10**6),
    ]
    try:
        match_event_orders(graph, exact, "uniswap_v3")
    except RuntimeError as error:
        assert "unmatched economic groups" in str(error)
    else:
        raise AssertionError("unmatched exact event did not fail closed")

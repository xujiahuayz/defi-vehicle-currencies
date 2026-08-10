from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from eth_abi import encode as abi_encode

from ddvc.ethereum_logs import write_exact_log_chunk
from ddvc.graph_event_order import (
    GraphEvent,
    ProviderEventsAbsentError,
    V3_STATE_EVENT_TOPICS,
    correction_root_for_graph,
    load_graph_events,
    match_event_orders,
    portable_evidence_path,
    resolve_portable_evidence_path,
    supplement_action,
    supplement_source_row,
    write_correction_generation,
)
from ddvc.state_data import (
    normalise_cp_partition,
    normalise_tick_partition,
    read_cp_partition,
    read_tick_partition,
    write_cp_partition,
    write_tick_partition,
)
from ddvc.pricing.tick_replay import load_tick_day_events
from ddvc.route_state import OrderedTickStateCursor, TickStateCut
from ddvc.v2_event_completeness import V2_EVENT_TOPICS
from scripts import reconcile_graph_event_order as reconcile


def test_v2_reconcilers_share_one_global_exact_log_path(tmp_path: Path, monkeypatch) -> None:
    import ddvc.v2_event_completeness as v2

    shared = tmp_path / "raw" / "ethereum" / "v2_exact"
    monkeypatch.setattr(v2, "V2_EXACT_LOG_CACHE_ROOT", shared)
    uniswap = reconcile.exact_chunk_paths("uniswap_v2", "20250101", 100, 149)
    sushi = reconcile.exact_chunk_paths("sushiswap_v2", "20260101", 100, 149)
    assert uniswap == sushi
    assert uniswap[0].parent == shared


def test_external_exact_log_provenance_stays_portable(tmp_path: Path) -> None:
    root = tmp_path / "raw" / "ethereum" / "graph_event_order"
    exact = tmp_path / "raw" / "ethereum" / "v2_exact" / "blocks.parquet"
    relative = portable_evidence_path(exact, root)
    assert not Path(relative).is_absolute()
    assert resolve_portable_evidence_path(relative, root).resolve() == exact.resolve()
    with pytest.raises(ValueError, match="escapes"):
        resolve_portable_evidence_path("../../../../outside.parquet", root)


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
    state_root = tmp_path / "state"
    write_tick_partition(raw_root, "uniswap_v3", "20250101", root=state_root)
    released = read_tick_partition(
        "uniswap_v3",
        "20250101",
        root=state_root,
        raw_root=raw_root,
    )
    assert set(released["log_index"].astype(int)) == {99, 122}


def test_missing_provider_log_index_is_repaired_from_exact_chain_order(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    provider = graph_swap("event-one", "0xtx1", "1", "-2")
    provider["logIndex"] = None
    write_graph_day(raw_root, [provider])
    graph = load_graph_events(raw_root, "uniswap_v3", "20250101")
    corrections, supplements, audit = match_event_orders(
        graph,
        [exact_swap("0xtx1", 99, 10**18, -2 * 10**6)],
        "uniswap_v3",
    )
    assert supplements == []
    assert audit["correction_rows"] == 1
    assert corrections[0]["provider_log_index"] is None
    assert corrections[0]["chain_log_index"] == 99

    correction_root = correction_root_for_graph(raw_root)
    exact_path = correction_root / "uniswap_v3" / "20250101" / "blocks_10_10.parquet"
    exact_marker = exact_path.with_suffix(".meta.json")
    write_exact_log_chunk(
        exact_path,
        exact_marker,
        [exact_swap("0xtx1", 99, 10**18, -2 * 10**6)],
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
    assert frame["log_index"].astype(int).tolist() == [99]


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
    state_root = tmp_path / "state"
    write_tick_partition(raw_root, "uniswap_v3", "20250101", root=state_root)
    quote_events = load_tick_day_events(
        state_root,
        "20250101",
        venues=("uniswap_v3",),
        raw_root=raw_root,
    )
    released_transactions = {
        str((event.row.get("transaction") or {}).get("id"))
        for event in quote_events
    }
    assert "0xtx2" in released_transactions
    applied: list[str] = []

    class QuoteReplay:
        @staticmethod
        def apply(event) -> None:
            applied.append(str((event.row.get("transaction") or {}).get("id")))

    cursor = OrderedTickStateCursor(tuple(quote_events))
    cursor.apply_until(QuoteReplay(), TickStateCut.strict_before_event((11, 0)))
    assert "0xtx2" in applied


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
        assert "ambiguous structural payload" in str(error)
    else:
        raise AssertionError("ambiguous structural payloads did not fail closed")


def test_v2_repeated_pool_swaps_use_unique_directional_amount_anchor() -> None:
    graph = [
        GraphEvent(
            venue="uniswap_v2",
            stream="swaps",
            event_id=f"provider-{index}",
            tx_hash="0xtx1",
            pool="0xpool",
            block_number=10,
            provider_log_index=provider_log,
            fingerprint=("swap", amount_in, 0, 0, provider_amount_out),
            decimals0=18,
            decimals1=18,
            needs_complete=False,
        )
        for index, provider_log, amount_in, provider_amount_out in (
            (1, 7, 10, 101),
            (2, 8, 20, 202),
        )
    ]
    exact = [
        {
            "address": "0xpool",
            "block_number": 10,
            "block_hash": "0xblock",
            "transaction_hash": "0xtx1",
            "transaction_index": 1,
            "log_index": chain_log,
            "topics": [V2_EVENT_TOPICS["swap"]],
            "data": "0x"
            + abi_encode(
                ["uint256", "uint256", "uint256", "uint256"],
                [amount_in, 0, 0, chain_amount_out],
            ).hex(),
            "removed": False,
        }
        for chain_log, amount_in, chain_amount_out in (
            (17, 10, 100),
            (18, 20, 200),
        )
    ]
    corrections, supplements, audit = match_event_orders(graph, exact, "uniswap_v2")
    assert supplements == []
    assert audit["matched_events"] == 2
    assert audit["payload_mismatches"] == 2
    assert {
        (row["event_id"], row["chain_log_index"], row["amount1_out_override"])
        for row in corrections
    } == {("provider-1", 17, "0.0000000000000001"), ("provider-2", 18, "0.0000000000000002")}


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
    reverted_swap = {
        **swap,
        "id": "event-reverted",
        "transaction": {"id": "0xtx4", "blockNumber": "10", "timestamp": "100"},
        "logIndex": "9",
    }
    successful_orphan = {
        **swap,
        "id": "event-successful-orphan",
        "transaction": {"id": "0xtx5", "blockNumber": "10", "timestamp": "100"},
        "logIndex": "10",
    }
    burn = {
        "id": "event-burn",
        "transaction": {"id": "0xtx2", "blockNumber": "10", "timestamp": "100"},
        "timestamp": "100",
        "logIndex": "8",
        "amount0": None,
        "amount1": None,
        "needsComplete": True,
        "pair": pair,
    }
    phantom = {
        **burn,
        "id": "event-phantom",
        "transaction": {
            "id": "0xtx3",
            "blockNumber": "10",
            "timestamp": "100",
        },
        "logIndex": None,
    }
    snapshot_pair = {
        **pair,
        "token0": {**pair["token0"], "decimals": "18"},
        "token1": {**pair["token1"], "decimals": "6"},
    }
    rows = {
        "swaps": [swap, reverted_swap, successful_orphan],
        "mints": [],
        "burns": [burn, phantom],
        "hourly_reserves": [
            {
                "id": "state",
                "hourStartUnix": "0",
                "reserve0": "10",
                "reserve1": "20",
                "pair": snapshot_pair,
            }
        ],
    }
    for stream, stream_rows in rows.items():
        with gzip.open(venue_root / f"uniswap_v2_{stream}_20250101.jsonl.gz", "wt") as handle:
            for row in stream_rows:
                handle.write(json.dumps(row) + "\n")
    exact = [
        {
            "address": "0xpool",
            "block_number": 10,
            "block_hash": "0xblock",
            "transaction_hash": "0xtx1",
            "transaction_index": 1,
            "log_index": 99,
            "topics": [V2_EVENT_TOPICS["swap"]],
            "data": "0x"
            + abi_encode(
                ["uint256", "uint256", "uint256", "uint256"],
                [10**18, 0, 0, 3 * 10**6],
            ).hex(),
            "removed": False,
        },
        {
            "address": "0xpool",
            "block_number": 10,
            "block_hash": "0xblock",
            "transaction_hash": "0xtx2",
            "transaction_index": 2,
            "log_index": 100,
            "topics": [V2_EVENT_TOPICS["burn"]],
            "data": "0x"
            + abi_encode(["uint256", "uint256"], [3 * 10**18, 4 * 10**6]).hex(),
            "removed": False,
        },
    ]
    graph = load_graph_events(raw_root, "uniswap_v2", "20250101")
    with pytest.raises(ProviderEventsAbsentError) as absent:
        match_event_orders(graph, exact, "uniswap_v2")
    assert {event.event_id for event in absent.value.events} == {
        "event-reverted",
        "event-successful-orphan",
    }
    corrections, supplements, audit = match_event_orders(
        graph,
        exact,
        "uniswap_v2",
        receipt_statuses={"0xtx4": 0, "0xtx5": 1},
    )
    assert supplements == []
    assert audit["matched_events"] == 2
    assert audit["payload_mismatches"] == 2
    assert audit["incomplete_liquidity_status_repairs"] == 1
    assert audit["exclusion_rows"] == 3
    assert audit["reverted_transaction_exclusions"] == 1
    assert audit["successful_transaction_absence_exclusions"] == 1
    assert audit["incomplete_liquidity_absence_exclusions"] == 1
    swap_correction = next(row for row in corrections if row["event_id"] == "event-one")
    assert swap_correction["amount0_in_override"] == "1"
    assert swap_correction["amount1_out_override"] == "3"
    burn_correction = next(row for row in corrections if row["event_id"] == "event-burn")
    assert burn_correction["needs_complete_override"] is False
    assert burn_correction["amount0_override"] == "3"
    assert burn_correction["amount1_override"] == "4"
    phantom_exclusion = next(
        row for row in corrections if row["event_id"] == "event-phantom"
    )
    assert phantom_exclusion["action"] == "exclusion"
    assert phantom_exclusion["chain_log_index"] is None
    reverted_exclusion = next(
        row for row in corrections if row["event_id"] == "event-reverted"
    )
    assert reverted_exclusion["reason"] == "reverted_transaction_event_absent_from_exact_chain_logs"
    successful_exclusion = next(
        row for row in corrections if row["event_id"] == "event-successful-orphan"
    )
    assert successful_exclusion["reason"] == "provider_event_absent_from_successful_transaction_receipt"

    correction_root = correction_root_for_graph(raw_root)
    exact_path = (
        correction_root.parent
        / "v2_core_event_source"
        / "global_50_block_chunks"
        / "blocks_00000000_00000049.parquet"
    )
    exact_marker = exact_path.with_suffix(".meta.json")
    write_exact_log_chunk(
        exact_path,
        exact_marker,
        exact,
        {
            "kind": "test",
            "venue": "uniswap_v2",
            "day": "20250101",
            "start_block": 10,
            "end_block": 10,
            "event_topics": list(V2_EVENT_TOPICS.values()),
        },
    )
    write_correction_generation(
        root=correction_root,
        raw_root=raw_root,
        venue="uniswap_v2",
        day="20250101",
        corrections=corrections,
        supplements=[],
        block_timestamp_evidence=[],
        exact_log_paths=[exact_path, exact_marker],
        audit=audit,
        start_block=10,
        end_block=10,
        transaction_receipt_evidence=[
            {
                "tx_hash": "0xtx4",
                "block_number": 10,
                "block_hash": "0x" + "c" * 64,
                "gas_used": 100_000,
                "status": 0,
                "tx_to": "0xrouter",
                "tx_from": "0xsender",
                "effective_gas_price_wei": 1,
                "logs": [],
            },
            {
                "tx_hash": "0xtx5",
                "block_number": 10,
                "block_hash": "0x" + "c" * 64,
                "gas_used": 100_000,
                "status": 1,
                "tx_to": "0xrouter",
                "tx_from": "0xsender",
                "effective_gas_price_wei": 1,
                "logs": [
                    {
                        "address": "0x" + "d" * 40,
                        "log_index": 11,
                        "topics": [V2_EVENT_TOPICS["swap"]],
                        "data": "0x",
                    }
                ],
            }
        ],
    )
    frame, quality = normalise_cp_partition(raw_root, "uniswap_v2", "20250101")
    corrected_swap = frame.loc[frame["event_id"] == "event-one"].iloc[0]
    completed = frame.loc[frame["event_id"] == "event-burn"].iloc[0]
    assert quality.passed
    assert corrected_swap["amount0_delta"] == "1"
    assert corrected_swap["amount1_delta"] == "-3"
    assert completed["usable"]
    assert completed["unsupported_reason"] is None
    assert completed["amount0_delta"] == "-3"
    assert completed["amount1_delta"] == "-4"
    assert "event-phantom" not in set(frame["event_id"])
    state_root = tmp_path / "state"
    write_cp_partition(raw_root, "uniswap_v2", "20250101", root=state_root)
    released = read_cp_partition(
        "uniswap_v2",
        "20250101",
        root=state_root,
        raw_root=raw_root,
    )
    assert set(released["event_id"]) == {"state", "event-one", "event-burn"}

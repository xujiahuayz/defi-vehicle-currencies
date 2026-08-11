from __future__ import annotations

import gzip
import json
from pathlib import Path
import sys

import pytest
from eth_abi import encode as abi_encode

from ddvc.ethereum_receipts import parse_receipt, receipt_payload
from ddvc.ethereum_logs import write_exact_log_chunk
from ddvc.graph_event_order import (
    EventOrderCorrections,
    EventOverride,
    GraphEvent,
    ProviderEventsAbsentError,
    SCHEMA_VERSION,
    V3_STATE_EVENT_TOPICS,
    apply_event_override,
    correction_pointer_path,
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
from ddvc.pricing.tick_replay import TickReplayState, load_tick_day_events
from ddvc.pricing.tick_state import TickPoolState
from ddvc.route_state import OrderedTickStateCursor, TickStateCut
from ddvc.quoter import canonical_json_sha256
from ddvc.v2_event_completeness import V2_EVENT_TOPICS, V2_RECONCILIATION_SCOPE
from scripts import reconcile_graph_event_order as reconcile


def test_reconciliation_cli_routes_v2_to_full_audit_owner(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["reconcile_graph_event_order.py", "--venue", "uniswap_v2", "--day", "2020-05-15"],
    )
    with pytest.raises(SystemExit) as error:
        reconcile.main()
    assert error.value.code == 2
    assert "owned by audit_v2_event_completeness.py" in capsys.readouterr().err


def receipt_evidence(
    tx_hash: str,
    *,
    status: int,
    logs: list[dict[str, object]],
) -> dict[str, object]:
    raw_logs = [
        {
            "address": row["address"],
            "logIndex": hex(int(row["log_index"])),
            "topics": row["topics"],
            "data": row["data"],
        }
        for row in logs
    ]
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "transactionHash": tx_hash,
            "blockNumber": "0xa",
            "blockHash": "0x" + "c" * 64,
            "gasUsed": hex(100_000),
            "status": hex(status),
            "to": "0xrouter",
            "from": "0xsender",
            "effectiveGasPrice": "0x1",
            "logs": raw_logs,
        },
    }
    normalized = parse_receipt(
        tx_hash,
        response,
        expected_block=10,
        include_logs=True,
    )
    assert normalized is not None
    endpoint = {"host": "injected", "endpoint_sha256": "0" * 64}
    return {
        **normalized,
        "rpc_request": receipt_payload(tx_hash),
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


def exact_swap(
    tx_hash: str,
    log_index: int,
    amount0: int,
    amount1: int,
    *,
    pool: str = "0xpool",
) -> dict[str, object]:
    return {
        "address": pool,
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


def v2_provider_swap(event_id: str, tx_hash: str, log_index: int = 7) -> dict:
    return {
        "id": event_id,
        "transaction": {"id": tx_hash, "blockNumber": "10", "timestamp": "100"},
        "timestamp": "100",
        "logIndex": str(log_index),
        "amount0In": "1",
        "amount1In": "0",
        "amount0Out": "0",
        "amount1Out": "2",
        "pair": {
            "id": "0xpool",
            "token0": {"id": "0xa", "decimals": "18"},
            "token1": {"id": "0xb", "decimals": "6"},
        },
    }


def v2_provider_action(
    event_id: str,
    tx_hash: str,
    *,
    action: str = "correction",
    provider_occurrence: int = 0,
) -> dict[str, object]:
    row: dict[str, object] = {
        "action": action,
        "schema_version": SCHEMA_VERSION,
        "venue": "uniswap_v2",
        "stream": "swaps",
        "event_id": event_id,
        "tx_hash": tx_hash,
        "pool": "0xpool",
        "block_number": 10,
        "provider_log_index": 7,
        "provider_occurrence": provider_occurrence,
        "chain_log_index": 17 if action == "correction" else None,
    }
    if action == "correction":
        row.update(
            {
                "amount0_in_override": "3",
                "amount1_in_override": "0",
                "amount0_out_override": "0",
                "amount1_out_override": "4",
            }
        )
    else:
        row["reason"] = "duplicate_provider_event"
    return row


def test_apply_event_override_preserves_all_v2_swap_legs() -> None:
    provider = v2_provider_swap("event-one", "0xtx1")
    corrected = apply_event_override(
        provider,
        EventOverride(
            log_index=17,
            amount0_in="3",
            amount1_in="5",
            amount0_out="7",
            amount1_out="11",
        ),
    )
    assert corrected is not None
    assert provider["logIndex"] == "7"
    assert corrected["logIndex"] == "17"
    assert tuple(
        corrected[field]
        for field in ("amount0In", "amount1In", "amount0Out", "amount1Out")
    ) == ("3", "5", "7", "11")
    assert apply_event_override(provider, EventOverride(exclude=True)) is None


def test_reconciled_ledger_applies_every_action_exactly_once() -> None:
    provider_one = v2_provider_swap("event-one", "0xtx1")
    provider_two = v2_provider_swap("event-two", "0xtx2")
    supplement = v2_provider_swap("chain:0xtx3:19", "0xtx3", 19)
    supplement_action_row = {
        "action": "supplement",
        "schema_version": SCHEMA_VERSION,
        "venue": "uniswap_v2",
        "stream": "swaps",
        "event_id": supplement["id"],
        "tx_hash": "0xtx3",
        "pool": "0xpool",
        "block_number": 10,
        "provider_log_index": None,
        "chain_log_index": 19,
        "source_row": supplement,
    }
    ledger = EventOrderCorrections(
        [
            v2_provider_action("event-one", "0xtx1"),
            v2_provider_action("event-two", "0xtx2", action="exclusion"),
            supplement_action_row,
        ]
    )
    rows = list(
        ledger.reconciled_rows(
            "uniswap_v2",
            "swaps",
            [provider_one, provider_two],
        )
    )
    assert rows[0] is not None and rows[0]["logIndex"] == "17"
    assert rows[1] is None
    assert rows[2] == supplement
    ledger.require_fully_applied()
    with pytest.raises(ValueError, match="stream consumed more than once"):
        list(ledger.reconciled_rows("uniswap_v2", "swaps", []))


def test_reconciled_ledger_rejects_duplicate_and_unconsumed_actions() -> None:
    action = v2_provider_action("event-one", "0xtx1")
    with pytest.raises(ValueError, match="duplicate event-order correction"):
        EventOrderCorrections([action, dict(action)])
    ledger = EventOrderCorrections([action])
    with pytest.raises(ValueError, match="stale or unapplied actions"):
        ledger.require_fully_applied()


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


def test_explicit_pool_perimeter_supplements_pool_absent_from_graph(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    write_graph_day(raw_root, [graph_swap("event-one", "0xtx1", "1", "-2")])
    graph = load_graph_events(raw_root, "uniswap_v3", "20250101")
    exact = [
        exact_swap("0xtx1", 99, 10**18, -2 * 10**6),
        exact_swap(
            "0xtx2",
            122,
            3 * 10**18,
            -4 * 10**6,
            pool="0xabsent",
        ),
    ]
    _default_corrections, default_supplements, default_audit = match_event_orders(
        graph,
        exact,
        "uniswap_v3",
    )
    assert default_supplements == []
    assert default_audit["exact_events_in_reconciliation_pool_perimeter"] == 1
    _corrections, supplements, audit = match_event_orders(
        graph,
        exact,
        "uniswap_v3",
        expected_pools={"0xpool", "0xabsent"},
    )
    assert [(event.pool, event.tx_hash) for event in supplements] == [
        ("0xabsent", "0xtx2")
    ]
    assert audit["exact_events_in_graph_pool_perimeter"] == 1
    assert audit["exact_events_in_reconciliation_pool_perimeter"] == 2
    assert audit["supplement_rows"] == 1


def test_explicit_pool_perimeter_rejects_graph_pool_outside_scope() -> None:
    graph = [
        GraphEvent(
            venue="uniswap_v3",
            stream="swaps",
            event_id="provider-one",
            tx_hash="0xtx1",
            pool="0xoutside",
            block_number=10,
            provider_log_index=7,
            fingerprint=("swap", 1, -2, 1 << 96, 0),
            decimals0=18,
            decimals1=6,
            needs_complete=False,
        )
    ]
    with pytest.raises(ValueError, match="outside the expected reconciliation perimeter"):
        match_event_orders(
            graph,
            [],
            "uniswap_v3",
            expected_pools={"0xexpected"},
        )


def test_explicit_pool_perimeter_rejects_case_collisions() -> None:
    with pytest.raises(ValueError, match="pool identity is duplicated"):
        match_event_orders(
            [],
            [],
            "uniswap_v3",
            expected_pools=["0xPool", "0xpool"],
        )


def test_reconciliation_repairs_duplicates_rounding_and_omissions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    graph_rows = [
        graph_swap("provider-one", "0xtx1", "1.000000000000000003", "-2"),
        graph_swap("provider-duplicate", "0xtx1", "1.000000000000000003", "-2"),
    ]
    for row in graph_rows:
        row["sqrtPriceX96"] = str((1 << 96) + 123)
        row["tick"] = "7"
        row["pool"]["tickSpacing"] = "10"
    provider_burn = {
        "id": "provider-burn",
        "transaction": {"id": "0xtx3", "blockNumber": "10", "timestamp": "100"},
        "timestamp": "100",
        "logIndex": "9",
        "amount": "12",
        "amount0": "2",
        "amount1": "3",
        "tickLower": "-20",
        "tickUpper": "20",
        "pool": graph_rows[0]["pool"],
    }
    write_graph_day(raw_root, graph_rows, burns=[provider_burn])
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
    assert audit["provider_duplicate_exclusions"] == 1
    assert audit["payload_mismatches"] == 2
    assert audit["supplement_rows"] == 1
    assert audit["ignored_zero_liquidity_events"] == 1
    assert len(corrections) == 3
    duplicate_exclusion = next(
        row for row in corrections if row["action"] == "exclusion"
    )
    assert duplicate_exclusion["event_id"] == "provider-one"
    assert duplicate_exclusion["reason"] == "duplicate_provider_event"
    burn_correction = next(
        row for row in corrections if row["event_id"] == "provider-burn"
    )
    assert burn_correction["amount0_override"] == "1"
    assert burn_correction["amount1_override"] == "2"
    assert burn_correction["liquidity_amount_override"] == 10
    assert burn_correction["tick_lower_override"] == -10
    assert burn_correction["tick_upper_override"] == 10
    swap_correction = next(
        row for row in corrections if row["event_id"] == "provider-duplicate"
    )
    assert swap_correction["sqrt_price_x96_override"] == 1 << 96
    assert swap_correction["tick_override"] == 0

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
    _, correction_meta = write_correction_generation(
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
    pointer_path = correction_pointer_path(
        correction_root,
        "uniswap_v3",
        "20250101",
    )
    prior_pointer = pointer_path.read_bytes()
    import ddvc.graph_event_order as event_order

    original_write_json = event_order.write_json

    def fail_pointer(path, payload):
        if path == pointer_path:
            raise OSError("simulated pointer publication failure")
        return original_write_json(path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(event_order, "write_json", fail_pointer)
        with pytest.raises(OSError, match="simulated pointer"):
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
                scope="alternate_graph_span",
            )
    assert pointer_path.read_bytes() == prior_pointer
    frame, quality = normalise_tick_partition(raw_root, "uniswap_v3", "20250101")
    assert quality.passed
    assert quality.duplicate_events == 0
    assert quality.conflicting_events == 0
    assert set(frame["log_index"].astype(int)) == {7, 8, 9}
    corrected = frame.loc[frame["tx_hash"] == "0xtx1"].iloc[0]
    assert corrected["amount0"] == "1"
    assert corrected["sqrt_price_x96"] == str(1 << 96)
    assert corrected["tick"] == 0
    corrected_burn = frame.loc[frame["tx_hash"] == "0xtx3"].iloc[0]
    assert corrected_burn["amount0"] == "1"
    assert corrected_burn["amount1"] == "2"
    assert corrected_burn["liquidity_delta"] == "-10"
    assert corrected_burn["tick_lower"] == -10
    assert corrected_burn["tick_upper"] == 10
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
    burn_event = next(
        event
        for event in quote_events
        if str((event.row.get("transaction") or {}).get("id")) == "0xtx3"
    )
    replay = TickReplayState()
    replay.apply(burn_event)
    assert replay.ticks_by_venue["uniswap_v3"]["0xpool"] == {-10: -10, 10: 10}
    swap_event = next(
        event
        for event in quote_events
        if str((event.row.get("transaction") or {}).get("id")) == "0xtx1"
    )
    replay.states_by_venue["uniswap_v3"] = {
        "0xpool": TickPoolState(
            pool="0xpool",
            token0="0xa",
            token1="0xb",
            sym0="A",
            sym1="B",
            dec0=18,
            dec1=6,
            sqrt_price_x96=(1 << 96) + 123,
            tick=7,
            fee_pips=500,
            tick_spacing=10,
            block=9,
            log_index=1,
        )
    }
    replay.apply(swap_event)
    exact_state = replay.states_by_venue["uniswap_v3"]["0xpool"]
    assert exact_state.sqrt_price_x96 == 1 << 96
    assert exact_state.tick == 0
    applied: list[str] = []

    class QuoteReplay:
        @staticmethod
        def apply(event) -> None:
            applied.append(str((event.row.get("transaction") or {}).get("id")))

    cursor = OrderedTickStateCursor(tuple(quote_events))
    cursor.apply_until(QuoteReplay(), TickStateCut.strict_before_event((11, 0)))
    assert "0xtx2" in applied
    metadata = json.loads(correction_meta.read_text(encoding="utf-8"))
    assert metadata["schema_version"] == SCHEMA_VERSION
    metadata["schema_version"] = SCHEMA_VERSION - 1
    correction_meta.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale event-order generation pointer"):
        normalise_tick_partition(raw_root, "uniswap_v3", "20250101")


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


def test_identical_provider_rows_emit_explicit_duplicate_exclusions() -> None:
    graph = [
        GraphEvent(
            venue="uniswap_v2",
            stream="swaps",
            event_id="provider-identical",
            tx_hash="0xtx1",
            pool="0xpool",
            block_number=10,
            provider_log_index=7,
            fingerprint=("swap", 10, 0, 0, 20),
            decimals0=18,
            decimals1=6,
            needs_complete=False,
        )
        for _ in range(3)
    ]
    exact = [
        {
            "address": "0xpool",
            "block_number": 10,
            "block_hash": "0xblock",
            "transaction_hash": "0xtx1",
            "transaction_index": 1,
            "log_index": 7,
            "topics": [V2_EVENT_TOPICS["swap"]],
            "data": "0x"
            + abi_encode(
                ["uint256", "uint256", "uint256", "uint256"],
                [10, 0, 0, 20],
            ).hex(),
            "removed": False,
        }
    ]
    actions, supplements, audit = match_event_orders(graph, exact, "uniswap_v2")
    assert supplements == []
    assert [row["action"] for row in actions] == ["exclusion", "exclusion"]
    assert [row["provider_occurrence"] for row in actions] == [1, 2]
    assert {row["reason"] for row in actions} == {"duplicate_provider_event"}
    assert audit["matched_events"] == 1
    assert audit["provider_duplicate_rows"] == 2
    assert audit["provider_duplicate_exclusions"] == 2
    assert audit["exclusion_rows"] == 2

    ledger = EventOrderCorrections(actions)
    provider_rows = [v2_provider_swap("provider-identical", "0xtx1") for _ in range(3)]
    reconciled = list(ledger.reconciled_rows("uniswap_v2", "swaps", provider_rows))
    assert sum(row is not None for row in reconciled) == 1
    ledger.require_fully_applied()


@pytest.mark.parametrize(
    ("stream", "needs_complete", "receipt_statuses", "reason", "audit_field"),
    [
        (
            "swaps",
            False,
            {"0xtx1": 0},
            "reverted_transaction_event_absent_from_exact_chain_logs",
            "reverted_transaction_exclusions",
        ),
        (
            "swaps",
            False,
            {"0xtx1": 1},
            "provider_event_absent_from_successful_transaction_receipt",
            "successful_transaction_absence_exclusions",
        ),
        (
            "mints",
            True,
            {},
            "incomplete_provider_liquidity_event_absent_from_exact_chain_logs",
            "incomplete_liquidity_absence_exclusions",
        ),
    ],
)
def test_absent_duplicate_groups_separate_one_absence_from_duplicate_exclusions(
    stream: str,
    needs_complete: bool,
    receipt_statuses: dict[str, int],
    reason: str,
    audit_field: str,
) -> None:
    graph = [
        GraphEvent(
            venue="uniswap_v2",
            stream=stream,
            event_id="provider-identical",
            tx_hash="0xtx1",
            pool="0xpool",
            block_number=10,
            provider_log_index=7,
            fingerprint=("swap", 10, 0, 0, 20),
            decimals0=18,
            decimals1=6,
            needs_complete=needs_complete,
        )
        for _ in range(3)
    ]
    actions, supplements, audit = match_event_orders(
        graph,
        [],
        "uniswap_v2",
        receipt_statuses=receipt_statuses,
    )
    assert supplements == []
    assert [row["reason"] for row in actions].count(reason) == 1
    assert [row["reason"] for row in actions].count("duplicate_provider_event") == 2
    assert audit["provider_duplicate_rows"] == 2
    assert audit["provider_duplicate_exclusions"] == 2
    assert audit[audit_field] == 1
    assert audit["exclusion_rows"] == 3


def test_empty_provider_reconciliation_requires_and_uses_explicit_pool_perimeter() -> None:
    exact = [
        {
            "address": "0xpool",
            "block_number": 10,
            "block_hash": "0xblock",
            "transaction_hash": "0xtx1",
            "transaction_index": 1,
            "log_index": 7,
            "topics": [V2_EVENT_TOPICS["swap"]],
            "data": "0x"
            + abi_encode(
                ["uint256", "uint256", "uint256", "uint256"],
                [10, 0, 0, 20],
            ).hex(),
            "removed": False,
        }
    ]
    with pytest.raises(ValueError, match="explicit pool perimeter"):
        match_event_orders([], exact, "uniswap_v2")
    actions, supplements, audit = match_event_orders(
        [],
        exact,
        "uniswap_v2",
        expected_pools={"0xpool"},
    )
    assert actions == []
    assert len(supplements) == 1
    assert audit["exact_events_in_reconciliation_pool_perimeter"] == 1
    assert audit["supplement_rows"] == 1


def test_v2_repeated_pool_swaps_use_unique_constant_log_offset() -> None:
    graph = [
        GraphEvent(
            venue="uniswap_v2",
            stream="swaps",
            event_id=f"provider-{index}",
            tx_hash="0xtx1",
            pool="0xpool",
            block_number=10,
            provider_log_index=provider_log,
            fingerprint=("swap", 10, 0, 0, provider_amount_out),
            decimals0=18,
            decimals1=18,
            needs_complete=False,
        )
        for index, provider_log, provider_amount_out in ((1, 235, 103), (2, 241, 203))
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
                [10, 0, 0, chain_amount_out],
            ).hex(),
            "removed": False,
        }
        for chain_log, chain_amount_out in ((283, 100), (289, 200))
    ]
    corrections, supplements, audit = match_event_orders(graph, exact, "uniswap_v2")
    assert supplements == []
    assert audit["matched_events"] == 2
    assert audit["payload_mismatches"] == 2
    assert {
        (row["event_id"], row["provider_log_index"], row["chain_log_index"])
        for row in corrections
    } == {("provider-1", 235, 283), ("provider-2", 241, 289)}


def test_v2_repeated_pool_swaps_reject_nonconstant_log_offsets() -> None:
    graph = [
        GraphEvent(
            venue="uniswap_v2",
            stream="swaps",
            event_id=f"provider-{index}",
            tx_hash="0xtx1",
            pool="0xpool",
            block_number=10,
            provider_log_index=provider_log,
            fingerprint=("swap", 10, 0, 0, provider_amount_out),
            decimals0=18,
            decimals1=18,
            needs_complete=False,
        )
        for index, provider_log, provider_amount_out in ((1, 235, 103), (2, 241, 203))
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
                [10, 0, 0, chain_amount_out],
            ).hex(),
            "removed": False,
        }
        for chain_log, chain_amount_out in ((283, 100), (290, 200))
    ]
    with pytest.raises(RuntimeError, match="ambiguous structural payload"):
        match_event_orders(graph, exact, "uniswap_v2")


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
            receipt_evidence("0xtx4", status=0, logs=[]),
            receipt_evidence(
                "0xtx5",
                status=1,
                logs=[
                    {
                        "address": "0x" + "d" * 40,
                        "log_index": 11,
                        "topics": [V2_EVENT_TOPICS["swap"]],
                        "data": "0x",
                    }
                ],
            ),
        ],
        scope=V2_RECONCILIATION_SCOPE,
        expected_pools={"0xpool"},
        audited_token_decimals={"0xa": 18, "0xb": 6},
        authority_inputs=[Path(__file__)],
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


def _write_v2_decimal_fixture(
    raw_root: Path,
    *,
    event_decimals0: str | None,
) -> None:
    venue_root = raw_root / "uniswap_v2"
    venue_root.mkdir(parents=True)
    event_pair = {
        "id": "0xpool",
        "token0": {"id": "0xa", "symbol": "A", "decimals": event_decimals0},
        "token1": {"id": "0xb", "symbol": "B"},
    }
    event_pair["token0"] = {
        key: value for key, value in event_pair["token0"].items() if value is not None
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
        "pair": event_pair,
    }
    rows = {
        "swaps": [swap],
        "mints": [],
        "burns": [],
    }
    for stream, stream_rows in rows.items():
        with gzip.open(venue_root / f"uniswap_v2_{stream}_20250101.jsonl.gz", "wt") as handle:
            for row in stream_rows:
                handle.write(json.dumps(row) + "\n")


def test_v2_missing_provider_decimals_are_filled_from_audited_registry(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    _write_v2_decimal_fixture(
        raw_root,
        event_decimals0=None,
    )
    graph = load_graph_events(
        raw_root,
        "uniswap_v2",
        "20250101",
        audited_token_decimals={"0xA": 18, "0xB": 6},
    )
    assert len(graph) == 1
    assert (graph[0].decimals0, graph[0].decimals1) == (18, 6)
    assert graph[0].fingerprint == ("swap", 10**18, 0, 0, 2 * 10**6)


def test_v2_audited_decimals_reject_provider_disagreement(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw" / "thegraph"
    _write_v2_decimal_fixture(
        raw_root,
        event_decimals0="17",
    )
    with pytest.raises(ValueError, match="audited token decimals disagree"):
        load_graph_events(
            raw_root,
            "uniswap_v2",
            "20250101",
            audited_token_decimals={"0xa": 18, "0xb": 6},
        )

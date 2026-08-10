from __future__ import annotations

import json

from eth_abi import encode as abi_encode
import pandas as pd
import pytest

from ddvc.ethereum_day_cuts import (
    utc_day_block_bounds,
    utc_day_timestamps,
    validate_utc_day_block_bounds,
)
from ddvc.fetch.raw import write_jsonl_gz
from ddvc.fetch.sources import get_source
from ddvc.v2_event_completeness import (
    EventAmounts,
    PAIR_CREATED_TOPIC,
    V2_CORE_EVENTS,
    V2_FACTORIES,
    V2_EVENT_SOURCE_SCHEMA_VERSION,
    V2_EVENT_TOPICS,
    V2_EVENT_VENUES,
    V2_POOL_PERIMETER,
    audit_calendar_sha256,
    compare_event_maps,
    decode_v2_log,
    factory_pair_registry,
    graph_core_events,
    raw_core_events,
    validate_v2_event_source_certificate,
)
from scripts import audit_v2_event_completeness as auditor


POOL = "0x" + "a" * 40
TOKEN0 = "0x" + "1" * 40
TOKEN1 = "0x" + "2" * 40
TX = "0x" + "b" * 64


def pair() -> dict[str, object]:
    return {
        "id": POOL,
        "token0": {"id": TOKEN0, "decimals": "6", "symbol": "A"},
        "token1": {"id": TOKEN1, "decimals": "18", "symbol": "B"},
    }


def graph_event(event_type: str) -> dict[str, object]:
    row: dict[str, object] = {
        "id": f"{TX}-0",
        "transaction": {"id": TX, "blockNumber": "100", "timestamp": "1"},
        "timestamp": "1",
        "logIndex": "7",
        "pair": pair(),
    }
    if event_type == "swap":
        row.update(
            {
                "amount0In": "1.25",
                "amount1In": "0",
                "amount0Out": "0",
                "amount1Out": "2",
            }
        )
    else:
        row.update({"amount0": "1.25", "amount1": "2"})
    return row


def raw_event(event_type: str) -> dict[str, object]:
    if event_type == "swap":
        data = abi_encode(
            ["uint256", "uint256", "uint256", "uint256"],
            [1_250_000, 0, 0, 2_000_000_000_000_000_000],
        )
    else:
        data = abi_encode(
            ["uint256", "uint256"],
            [1_250_000, 2_000_000_000_000_000_000],
        )
    return {
        "address": POOL,
        "block_number": 100,
        "block_hash": "0x" + "c" * 64,
        "transaction_hash": TX,
        "transaction_index": 1,
        "log_index": 7,
        "topics": [V2_EVENT_TOPICS[event_type]],
        "data": "0x" + data.hex(),
        "removed": False,
    }


def pair_created_raw(*, ordinal: int = 1) -> dict[str, object]:
    return {
        "address": V2_FACTORIES["uniswap_v2"],
        "block_number": 90,
        "block_hash": "0x" + "d" * 64,
        "transaction_hash": "0x" + "e" * 64,
        "transaction_index": 0,
        "log_index": 3,
        "topics": [
            PAIR_CREATED_TOPIC,
            "0x" + TOKEN0.removeprefix("0x").rjust(64, "0"),
            "0x" + TOKEN1.removeprefix("0x").rjust(64, "0"),
        ],
        "data": "0x" + abi_encode(["address", "uint256"], [POOL, ordinal]).hex(),
        "removed": False,
    }


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (
            "mint",
            EventAmounts(1_250_000, 2_000_000_000_000_000_000, 0, 0, 0, 0),
        ),
        (
            "burn",
            EventAmounts(-1_250_000, -2_000_000_000_000_000_000, 0, 0, 0, 0),
        ),
        (
            "swap",
            EventAmounts(
                1_250_000,
                -2_000_000_000_000_000_000,
                1_250_000,
                0,
                0,
                2_000_000_000_000_000_000,
            ),
        ),
    ],
)
def test_v2_decoder_preserves_exact_identity_and_raw_amounts(
    event_type: str,
    expected: EventAmounts,
) -> None:
    key, amounts = decode_v2_log("uniswap_v2", raw_event(event_type))
    assert key == ("uniswap_v2", event_type, 100, TX, 7, POOL)
    assert amounts == expected


def test_graph_comparison_uses_audited_decimals_and_all_three_streams(tmp_path) -> None:
    venue = "uniswap_v2"
    day = "20250115"
    directory = tmp_path / venue
    directory.mkdir()
    write_jsonl_gz(directory / f"{venue}_hourly_reserves_{day}.jsonl.gz", [{"pair": pair()}])
    for event_type, stream in (("mint", "mints"), ("burn", "burns"), ("swap", "swaps")):
        write_jsonl_gz(directory / f"{venue}_{stream}_{day}.jsonl.gz", [graph_event(event_type)])
    statics, pairs = factory_pair_registry(
        venue,
        [pair_created_raw()],
        {TOKEN0: 6, TOKEN1: 18},
    )
    assert pairs[0].pool == POOL
    graph, duplicates = graph_core_events(tmp_path, venue, day, statics)
    raw = dict(decode_v2_log(venue, raw_event(event_type)) for event_type in V2_CORE_EVENTS)
    summaries, exceptions = compare_event_maps(day, venue, raw, graph, duplicates)
    assert all(row["passed"] for row in summaries)
    assert not exceptions


def test_graph_pool_statics_reject_decimal_registry_disagreement(tmp_path) -> None:
    venue = "uniswap_v2"
    day = "20250115"
    directory = tmp_path / venue
    directory.mkdir()
    for stream in ("mints", "burns", "swaps"):
        write_jsonl_gz(directory / f"{venue}_{stream}_{day}.jsonl.gz", [graph_event(stream[:-1])])
    statics, _pairs = factory_pair_registry(
        venue,
        [pair_created_raw()],
        {TOKEN0: 18, TOKEN1: 18},
    )
    with pytest.raises(ValueError, match="disagree"):
        graph_core_events(tmp_path, venue, day, statics)


def test_factory_registry_keeps_pairs_outside_decimal_registry() -> None:
    statics, pairs = factory_pair_registry("uniswap_v2", [pair_created_raw()], {})
    assert set(statics) == {POOL}
    assert len(pairs) == 1
    assert statics[POOL].decimals0 is None


def test_factory_registry_rejects_a_missing_paircreated_ordinal() -> None:
    with pytest.raises(ValueError, match="sequence is incomplete"):
        factory_pair_registry(
            "uniswap_v2",
            [pair_created_raw(ordinal=2)],
            {},
        )


def test_global_raw_events_are_attributed_only_after_topic_retrieval() -> None:
    clone = raw_event("swap")
    clone["address"] = "0x" + "f" * 40
    events = raw_core_events(
        "uniswap_v2",
        [raw_event("swap"), clone],
        expected_pools={POOL},
        expected_creation_blocks={POOL: 90},
        ignore_unregistered=True,
    )
    assert len(events) == 1
    assert next(iter(events))[-1] == POOL


def test_graph_event_fails_when_amount_token_lacks_audited_decimals(tmp_path) -> None:
    venue = "uniswap_v2"
    day = "20250115"
    directory = tmp_path / venue
    directory.mkdir()
    write_jsonl_gz(
        directory / f"{venue}_mints_{day}.jsonl.gz",
        [graph_event("mint")],
    )
    for stream in ("burns", "swaps"):
        write_jsonl_gz(directory / f"{venue}_{stream}_{day}.jsonl.gz", [])
    statics, _pairs = factory_pair_registry(venue, [pair_created_raw()], {})
    with pytest.raises(ValueError, match="event token decimals are absent"):
        graph_core_events(tmp_path, venue, day, statics)


def test_utc_day_bounds_prove_both_adjacent_boundary_blocks() -> None:
    day = "20250115"
    start, _end = utc_day_timestamps(day)
    timestamp_for_block = lambda block: start - 50 + 10 * block
    record = {
        "status": "complete",
        **utc_day_block_bounds(day, 0, 9_000, timestamp_for_block),
    }
    evidence = []
    for block in {
        int(record["before_start_block"]),
        int(record["start_block"]),
        int(record["end_block"]),
        int(record["after_end_block"]),
    }:
        evidence.append(
            {
                "request": {
                    "method": "eth_getBlockByNumber",
                    "params": [hex(block), False],
                },
                "response": {
                    "number": hex(block),
                    "hash": "0x" + "a" * 64,
                    "parentHash": "0x" + "b" * 64,
                    "timestamp": hex(timestamp_for_block(block)),
                },
            }
        )
    record["rpc_evidence"] = evidence
    validate_utc_day_block_bounds(record, day)
    record["after_end_block_timestamp"] = int(record["after_end_block_timestamp"]) - 1
    with pytest.raises(ValueError, match="timestamp boundaries|incomplete"):
        validate_utc_day_block_bounds(record, day)


def test_exact_rpc_chunk_is_reusable_only_after_its_complete_marker(
    tmp_path,
    monkeypatch,
) -> None:
    canonical = raw_event("swap")
    rpc_log = {
        "address": canonical["address"],
        "blockNumber": hex(int(canonical["block_number"])),
        "blockHash": canonical["block_hash"],
        "transactionHash": canonical["transaction_hash"],
        "transactionIndex": hex(int(canonical["transaction_index"])),
        "logIndex": hex(int(canonical["log_index"])),
        "topics": canonical["topics"],
        "data": canonical["data"],
        "removed": False,
    }
    monkeypatch.setattr(auditor, "RAW_V2_EVENT_ROOT", tmp_path)
    payloads = []

    def rpc_response(payload, **_kwargs):
        payloads.append(payload)
        return {"result": [rpc_log]}

    monkeypatch.setattr(auditor, "rpc_post", rpc_response)
    auditor.fetch_event_chunk("20250115", 90, 110)
    assert "address" not in payloads[0]["params"][0]
    assert set(payloads[0]["params"][0]["topics"][0]) == set(V2_EVENT_TOPICS.values())
    assert auditor.event_chunk_completed(
        "20250115",
        90,
        110,
    )
    _raw, marker = auditor.event_chunk_paths("20250115", 90, 110)
    payload = json.loads(marker.read_text())
    payload["status"] = "incomplete"
    marker.write_text(json.dumps(payload))
    assert not auditor.event_chunk_completed("20250115", 90, 110)


def test_no_fetch_refuses_to_resolve_a_missing_day_cut(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(auditor, "RAW_DAY_BOUND_ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="lacks a current UTC block cut"):
        auditor.load_or_resolve_day_bounds("20250115", fetch=False)


def test_release_certificate_requires_exact_calendar_and_zero_exceptions() -> None:
    days = ["20200214", "20201015"]
    rows = []
    for venue in V2_EVENT_VENUES:
        genesis = get_source(venue).genesis.strftime("%Y%m%d")
        for day in days:
            summaries, _exceptions = compare_event_maps(
                day,
                venue,
                {},
                {},
                set(),
                launch_status="pre_genesis" if day < genesis else "audited",
            )
            rows.extend(summaries)
    summary = pd.DataFrame(rows)
    exceptions = pd.DataFrame()
    certificate = {
        "schema_version": V2_EVENT_SOURCE_SCHEMA_VERSION,
        "status": "pass",
        "audit_calendar_sha256": audit_calendar_sha256(days),
        "audit_dates": len(days),
        "summary_rows": len(rows),
        "exception_rows": 0,
        "venues": list(V2_EVENT_VENUES),
        "event_types": list(V2_CORE_EVENTS),
        "pool_perimeter": V2_POOL_PERIMETER,
        "registry_source": "complete_factory_PairCreated_histories",
        "global_event_query": "topic_only_without_address_filter",
        "factory_pairs": 2,
        "factory_pairs_by_venue": {venue: 1 for venue in V2_EVENT_VENUES},
        "factory_registry_sha256": "a" * 64,
    }
    assert validate_v2_event_source_certificate(summary, exceptions, certificate, days) == (2, 0)
    with pytest.raises(ValueError, match="calendar does not match"):
        validate_v2_event_source_certificate(summary, exceptions, certificate, days[:1])
    with pytest.raises(ValueError, match="exception rows"):
        validate_v2_event_source_certificate(
            summary,
            pd.DataFrame([{"status": "amount_mismatch"}]),
            certificate,
            days,
        )

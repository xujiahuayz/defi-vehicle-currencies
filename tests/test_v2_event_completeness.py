from __future__ import annotations

import io
import gzip
import hashlib
import json
import urllib.error
from types import SimpleNamespace

from eth_abi import encode as abi_encode
import pandas as pd
import pytest

from ddvc.ethereum_day_cuts import (
    utc_day_block_bounds,
    utc_day_timestamps,
    validate_utc_day_block_bounds,
)
from ddvc.ethereum_logs import (
    EXACT_LOG_BLOCK_CAP,
    ExactLogCapacityError,
    ExactLogRpcError,
    RpcEnvelope,
    exact_log_block_ranges,
    file_sha256,
    rpc_post_with_evidence,
    write_exact_log_chunk,
)
from ddvc.fetch.raw import write_jsonl_gz
from ddvc.fetch.sources import get_source
from ddvc.quoter import Throttled, canonical_json_sha256, sanitized_endpoint_identity
from ddvc.v2_event_completeness import (
    ALL_PAIRS_LENGTH_SELECTOR,
    ALL_PAIRS_SELECTOR,
    EventAmounts,
    GET_PAIR_SELECTOR,
    PAIR_CREATED_TOPIC,
    V2_CORE_EVENTS,
    V2_FACTORIES,
    V2_EVENT_SOURCE_SCHEMA_VERSION,
    V2_EVENT_TOPICS,
    V2_EVENT_VENUES,
    V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
    V2_FACTORY_INITIAL_BLOCK_SPAN,
    V2_POOL_PERIMETER,
    V2_TOKEN_DECIMALS_CONTRACT,
    V2_TOKEN_DECIMALS_SCOPE,
    audit_calendar_sha256,
    build_factory_state_proof,
    compare_event_maps,
    decode_v2_log,
    deterministic_factory_state_sample,
    factory_leaf_complete,
    factory_leaf_paths,
    factory_pair_registry,
    factory_registry_sha256,
    factory_root_ranges,
    fetch_factory_root_adaptive,
    fetch_v2_exact_log_chunk,
    frozen_upper_block_path,
    graph_core_events,
    graph_core_events_for_amount_keys,
    load_or_resolve_frozen_upper_block,
    missing_v2_exact_log_ranges,
    raw_core_events,
    read_factory_coverage_records,
    read_v2_exact_logs,
    validate_factory_coverage_manifest,
    validate_factory_coverage_ranges,
    validate_factory_deployment_proof,
    validate_factory_state_proof,
    validate_v2_event_source_certificate,
    validate_v2_event_source_evidence_bundle,
    v2_exact_log_chunk_complete,
    v2_exact_log_chunk_paths,
    v2_exact_log_ranges,
    write_factory_coverage_manifest,
)
from scripts import audit_v2_event_completeness as auditor
from scripts import reconcile_graph_event_order as reconciler


POOL = "0x" + "a" * 40
TOKEN0 = "0x" + "1" * 40
TOKEN1 = "0x" + "2" * 40
TX = "0x" + "b" * 64
INJECTED_ENDPOINT = {"host": "injected", "endpoint_sha256": "0" * 64}


def successful_rpc_attempt(endpoint: dict[str, str]) -> dict[str, object]:
    return {
        "endpoint": endpoint,
        "attempt": 1,
        "classification": "success",
        "http_status": None,
        "rpc_code": None,
        "message": "success",
    }


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


def test_graph_preflight_rejects_a_truncated_gzip_before_rpc_fetch(
    tmp_path, monkeypatch
) -> None:
    venue = "uniswap_v2"
    day = "20250101"
    root = tmp_path / "thegraph"
    paths = []
    for stream in ("swaps", "mints", "burns"):
        path = root / venue / f"{venue}_{stream}_{day}.jsonl.gz"
        write_jsonl_gz(path, [graph_event("swap" if stream == "swaps" else stream[:-1])])
        paths.append(path)
    payload = paths[1].read_bytes()
    paths[1].write_bytes(payload[:-8])
    monkeypatch.setattr(auditor, "GRAPH_ROOT", root)
    monkeypatch.setattr(auditor, "_launched_venues", lambda _day: (venue,))
    with pytest.raises(RuntimeError, match="unreadable Graph event file before RPC fetch"):
        auditor._preflight_graph_streams([day])


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


def pair_created_raw(
    *,
    ordinal: int = 1,
    block_number: int = 90,
    pool: str = POOL,
    token0: str = TOKEN0,
    token1: str = TOKEN1,
    tx_hash: str = "0x" + "e" * 64,
    log_index: int = 3,
    removed: bool = False,
) -> dict[str, object]:
    return {
        "address": V2_FACTORIES["uniswap_v2"],
        "block_number": block_number,
        "block_hash": "0x" + "d" * 64,
        "transaction_hash": tx_hash,
        "transaction_index": 0,
        "log_index": log_index,
        "topics": [
            PAIR_CREATED_TOPIC,
            "0x" + token0.removeprefix("0x").rjust(64, "0"),
            "0x" + token1.removeprefix("0x").rjust(64, "0"),
        ],
        "data": "0x" + abi_encode(["address", "uint256"], [pool, ordinal]).hex(),
        "removed": removed,
    }


def rpc_pair_created_log(**kwargs) -> dict[str, object]:
    record = pair_created_raw(**kwargs)
    return {
        "address": record["address"],
        "blockNumber": hex(int(record["block_number"])),
        "blockHash": record["block_hash"],
        "transactionHash": record["transaction_hash"],
        "transactionIndex": hex(int(record["transaction_index"])),
        "logIndex": hex(int(record["log_index"])),
        "topics": record["topics"],
        "data": record["data"],
        "removed": record["removed"],
    }


def frozen_upper(block: int, *, block_hash: str = "0x" + "9" * 64) -> dict[str, object]:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": [hex(block), False],
    }
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "number": hex(block),
            "hash": block_hash,
            "parentHash": "0x" + "8" * 64,
            "timestamp": hex(1_700_000_000),
        },
    }
    record = {
        "status": "complete",
        "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
        "block_number": block,
        "block_hash": block_hash,
        "parent_hash": "0x" + "8" * 64,
        "timestamp": 1_700_000_000,
        "rpc_request": request,
        "rpc_response": response,
        "rpc_endpoint": INJECTED_ENDPOINT,
        "rpc_attempts": [successful_rpc_attempt(INJECTED_ENDPOINT)],
        "response_sha256": hashlib.sha256(
            json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    record["header_identity_sha256"] = hashlib.sha256(
        json.dumps(
            {
                "block_number": record["block_number"],
                "block_hash": record["block_hash"],
                "parent_hash": record["parent_hash"],
                "timestamp": record["timestamp"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return record


def anchored_rpc_batch(
    payload,
    logs: list[dict[str, object]],
    frozen: dict[str, object],
) -> list[dict[str, object]]:
    assert isinstance(payload, list) and len(payload) == 2
    assert payload[0]["method"] == "eth_getLogs"
    assert payload[1] == {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "eth_getBlockByNumber",
        "params": [hex(int(frozen["block_number"])), False],
    }
    header = dict(frozen["rpc_response"])
    header["id"] = 2
    return [{"jsonrpc": "2.0", "id": 1, "result": logs}, header]


def anchored_marker_evidence(
    records: list[dict[str, object]],
    *,
    start_block: int,
    end_block: int,
    topics: list[str],
    address: str | None,
    frozen: dict[str, object],
) -> dict[str, object]:
    log_filter: dict[str, object] = {
        "fromBlock": hex(start_block),
        "toBlock": hex(end_block),
        "topics": [topics if len(topics) > 1 else topics[0]],
    }
    if address is not None:
        log_filter["address"] = address
    frozen_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "eth_getBlockByNumber",
        "params": [hex(int(frozen["block_number"])), False],
    }
    frozen_response = dict(frozen["rpc_response"])
    frozen_response["id"] = 2
    rpc_response = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": [
                {
                    "address": record["address"],
                    "blockNumber": hex(int(record["block_number"])),
                    "blockHash": record["block_hash"],
                    "transactionHash": record["transaction_hash"],
                    "transactionIndex": hex(int(record["transaction_index"])),
                    "logIndex": hex(int(record["log_index"])),
                    "topics": record["topics"],
                    "data": record["data"],
                    "removed": record["removed"],
                }
                for record in records
            ],
        },
        frozen_response,
    ]
    return {
        "rpc_request": [
            {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [log_filter]},
            frozen_request,
        ],
        "rpc_response": rpc_response,
        "rpc_endpoint": INJECTED_ENDPOINT,
        "rpc_attempts": [successful_rpc_attempt(INJECTED_ENDPOINT)],
        "response_sha256": hashlib.sha256(
            json.dumps(rpc_response, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "frozen_upper_request": frozen_request,
        "frozen_upper_response": frozen_response,
        "frozen_upper_response_sha256": hashlib.sha256(
            json.dumps(frozen_response, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def write_factory_leaf(
    root,
    start_block: int,
    end_block: int,
    records: list[dict[str, object]],
    **marker_overrides,
) -> None:
    frozen = frozen_upper(109)
    raw_path, marker_path = factory_leaf_paths(
        "uniswap_v2",
        start_block,
        end_block,
        root=root,
    )
    marker = {
        "kind": "factory_pair_created",
        "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
        "venue": "uniswap_v2",
        "start_block": start_block,
        "end_block": end_block,
        "root_start_block": start_block,
        "root_end_block": end_block,
        "adaptive_depth": 0,
        "split_ancestry": [],
        "address_filter": V2_FACTORIES["uniswap_v2"],
        "query_scope": "factory_address_and_paircreated_topic",
        "event_topics": [PAIR_CREATED_TOPIC],
        **anchored_marker_evidence(
            records,
            start_block=start_block,
            end_block=end_block,
            topics=[PAIR_CREATED_TOPIC],
            address=V2_FACTORIES["uniswap_v2"],
            frozen=frozen,
        ),
        **marker_overrides,
    }
    write_exact_log_chunk(raw_path, marker_path, records, marker)


def factory_pairs(count: int):
    records = []
    for ordinal in range(1, count + 1):
        token0 = "0x" + f"{ordinal:040x}"
        token1 = "0x" + f"{ordinal + count + 1:040x}"
        pool = "0x" + f"{ordinal + 2 * count + 2:040x}"
        records.append(
            pair_created_raw(
                ordinal=ordinal,
                block_number=90 + ordinal,
                pool=pool,
                token0=token0,
                token1=token1,
                tx_hash="0x" + f"{ordinal:064x}",
                log_index=ordinal,
            )
        )
    return factory_pair_registry("uniswap_v2", records, {})[1]


def state_rpc_for_pairs(pairs, *, all_pairs_length: int | None = None, header_hash=None):
    by_index = {pair.ordinal - 1: pair.pool for pair in pairs}
    by_tokens = {(pair.token0, pair.token1): pair.pool for pair in pairs}
    endpoint = {"host": "state.example", "endpoint_sha256": "3" * 64}
    served_hash = header_hash or "0x" + "9" * 64

    def rpc(payload, **_kwargs):
        if isinstance(payload, list):
            responses = []
            for request in payload:
                block_reference = request["params"][1]
                if (
                    isinstance(block_reference, dict)
                    and block_reference.get("blockHash") != served_hash
                ):
                    responses.append(
                        {
                            "jsonrpc": "2.0",
                            "id": request["id"],
                            "error": {"code": -32001, "message": "unknown block hash"},
                        }
                    )
                    continue
                data = request["params"][0]["data"]
                if data.startswith(ALL_PAIRS_SELECTOR):
                    observed = by_index[int(data[-64:], 16)]
                elif data.startswith(GET_PAIR_SELECTOR):
                    token0 = "0x" + data[-128:-64][-40:]
                    token1 = "0x" + data[-64:][-40:]
                    observed = by_tokens[(token0, token1)]
                else:
                    raise AssertionError(f"unexpected factory state selector: {data[:10]}")
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "result": "0x" + observed.removeprefix("0x").rjust(64, "0"),
                    }
                )
            return RpcEnvelope(responses, endpoint, ())
        method = payload["method"]
        if method == "eth_getBlockByNumber":
            block = int(payload["params"][0], 16)
            return RpcEnvelope(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "number": hex(block),
                        "hash": served_hash,
                        "parentHash": "0x" + "8" * 64,
                        "timestamp": hex(1_700_000_000),
                    },
                },
                endpoint,
                (),
            )
        assert method == "eth_call"
        assert payload["params"][0]["data"] == ALL_PAIRS_LENGTH_SELECTOR
        block_reference = payload["params"][1]
        if (
            isinstance(block_reference, dict)
            and block_reference.get("blockHash") != served_hash
        ):
            return RpcEnvelope(
                {
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "error": {"code": -32001, "message": "unknown block hash"},
                },
                endpoint,
                (),
            )
        observed_length = len(pairs) if all_pairs_length is None else all_pairs_length
        return RpcEnvelope(
            {"jsonrpc": "2.0", "id": payload["id"], "result": hex(observed_length)},
            endpoint,
            (),
        )

    return rpc


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


def test_audit_token_perimeter_comes_from_events_not_the_priced_token_panel(
    tmp_path,
    monkeypatch,
) -> None:
    venue = "uniswap_v2"
    day = "20250115"
    directory = tmp_path / "thegraph" / venue
    directory.mkdir(parents=True)
    write_jsonl_gz(directory / f"{venue}_swaps_{day}.jsonl.gz", [graph_event("swap")])
    for stream in ("mints", "burns"):
        write_jsonl_gz(directory / f"{venue}_{stream}_{day}.jsonl.gz", [])
    statics, pairs = factory_pair_registry(venue, [pair_created_raw()], {})
    monkeypatch.setattr(auditor, "GRAPH_ROOT", tmp_path / "thegraph")
    monkeypatch.setattr(auditor, "_launched_venues", lambda _day: (venue,))
    monkeypatch.setattr(
        auditor,
        "read_v2_exact_logs",
        lambda *_args, **_kwargs: ([raw_event("swap")], [tmp_path / "exact.parquet"]),
    )
    anchors, provider, _inputs, raw_logs = auditor.collect_v2_token_decimals_perimeter(
        [day],
        {day: {"start_block": 100, "end_block": 100}},
        frozen_upper(100),
        {venue: statics},
        {venue: pairs},
        {venue: [pair_created_raw()], "sushiswap_v2": []},
    )
    assert set(anchors) == {TOKEN0, TOKEN1}
    assert {anchor.priority for anchor in anchors.values()} == {0}
    assert provider == {TOKEN0: ["6"], TOKEN1: ["18"]}
    assert raw_logs == 1


def test_factory_registry_rejects_a_missing_paircreated_ordinal() -> None:
    with pytest.raises(ValueError, match="sequence is incomplete"):
        factory_pair_registry(
            "uniswap_v2",
            [pair_created_raw(ordinal=2)],
            {},
        )


def test_factory_registry_rejects_exact_ordinals_in_nonchain_order() -> None:
    records = [
        pair_created_raw(ordinal=1, block_number=91),
        pair_created_raw(
            ordinal=2,
            block_number=90,
            pool="0x" + "c" * 40,
            token0="0x" + "3" * 40,
            token1="0x" + "4" * 40,
            tx_hash="0x" + "f" * 64,
            log_index=2,
        ),
    ]
    with pytest.raises(ValueError, match="chain order"):
        factory_pair_registry("uniswap_v2", records, {})


def test_factory_root_fetch_succeeds_without_split_and_writes_marker_last(
    tmp_path,
    monkeypatch,
) -> None:
    payloads = []
    frozen = frozen_upper(109)

    def rpc(payload, **_kwargs):
        payloads.append(payload)
        endpoint = {"host": "rpc.example", "endpoint_sha256": "4" * 64}
        return RpcEnvelope(
            anchored_rpc_batch(payload, [rpc_pair_created_log(block_number=105)], frozen),
            endpoint,
            (successful_rpc_attempt(endpoint),),
        )

    import ddvc.ethereum_logs as ethereum_logs

    real_write_json = ethereum_logs.write_json
    marker_observations = []

    def write_marker(path, value):
        raw_path = path.with_name(path.name.replace(".meta.json", ".parquet"))
        marker_observations.append(raw_path.is_file())
        real_write_json(path, value)

    monkeypatch.setattr(ethereum_logs, "write_json", write_marker)
    assert fetch_factory_root_adaptive(
        "uniswap_v2",
        100,
        109,
        frozen_upper=frozen,
        root=tmp_path,
        rpc_request=rpc,
    ) == [(100, 109)]
    assert marker_observations == [True]
    assert payloads[0][0]["params"][0] == {
        "fromBlock": hex(100),
        "toBlock": hex(109),
        "topics": [PAIR_CREATED_TOPIC],
        "address": V2_FACTORIES["uniswap_v2"],
    }
    assert factory_leaf_complete("uniswap_v2", 100, 109, frozen_upper=frozen, root=tmp_path)
    _raw_path, marker_path = factory_leaf_paths("uniswap_v2", 100, 109, root=tmp_path)
    marker = json.loads(marker_path.read_text())
    assert marker["root_start_block"] == 100
    assert marker["root_end_block"] == 109
    assert marker["adaptive_depth"] == 0
    assert marker["split_ancestry"] == []


def test_factory_root_capacity_split_has_exact_deterministic_ancestry(tmp_path) -> None:
    calls = []
    frozen = frozen_upper(109)
    capacity_attempt = {
        "endpoint": {"host": "rpc.example", "endpoint_sha256": "4" * 64},
        "attempt": 1,
        "http_status": 408,
        "rpc_code": None,
        "message": "request timeout",
    }

    def rpc(payload, **_kwargs):
        query = payload[0]["params"][0]
        perimeter = (int(query["fromBlock"], 16), int(query["toBlock"], 16))
        calls.append(perimeter)
        if perimeter == (100, 109):
            raise ExactLogCapacityError("capacity", attempts=(capacity_attempt,))
        logs = [rpc_pair_created_log(block_number=102)] if perimeter == (100, 104) else []
        return anchored_rpc_batch(payload, logs, frozen)

    leaves = fetch_factory_root_adaptive(
        "uniswap_v2",
        100,
        109,
        frozen_upper=frozen,
        root=tmp_path,
        rpc_request=rpc,
    )
    assert calls == [(100, 109), (100, 104), (105, 109)]
    assert leaves == [(100, 104), (105, 109)]
    for start, end in leaves:
        _raw_path, marker_path = factory_leaf_paths(
            "uniswap_v2",
            start,
            end,
            root=tmp_path,
        )
        marker = json.loads(marker_path.read_text())
        assert marker["root_start_block"] == 100
        assert marker["root_end_block"] == 109
        assert marker["adaptive_depth"] == 1
        assert marker["split_ancestry"] == [
            {"start_block": 100, "end_block": 109, "attempts": [capacity_attempt]}
        ]
    manifest = write_factory_coverage_manifest(
        "uniswap_v2",
        100,
        frozen,
        leaves,
        root=tmp_path,
    )
    assert validate_factory_coverage_manifest(
        manifest,
        venue="uniswap_v2",
        deployment_block=100,
        frozen_upper=frozen,
        root=tmp_path,
    ) == leaves
    records, inputs = read_factory_coverage_records(
        manifest,
        venue="uniswap_v2",
        deployment_block=100,
        frozen_upper=frozen,
        root=tmp_path,
    )
    assert len(records) == 1
    assert len(inputs) == 4


def test_one_block_factory_capacity_failure_writes_no_leaf(tmp_path) -> None:
    frozen = frozen_upper(100)
    def rpc(_payload, **_kwargs):
        raise ExactLogCapacityError("capacity")

    with pytest.raises(RuntimeError, match="one block"):
        fetch_factory_root_adaptive(
            "uniswap_v2",
            100,
            100,
            frozen_upper=frozen,
            root=tmp_path,
            rpc_request=rpc,
        )
    raw_path, marker_path = factory_leaf_paths("uniswap_v2", 100, 100, root=tmp_path)
    assert not raw_path.exists()
    assert not marker_path.exists()


def test_semantic_rpc_error_never_licenses_factory_bisection(tmp_path) -> None:
    calls = []
    frozen = frozen_upper(109)

    def rpc(payload, **_kwargs):
        calls.append(payload)
        raise ExactLogRpcError("semantic failure")

    with pytest.raises(ExactLogRpcError, match="semantic"):
        fetch_factory_root_adaptive(
            "uniswap_v2",
            100,
            109,
            frozen_upper=frozen,
            root=tmp_path,
            rpc_request=rpc,
        )
    assert len(calls) == 1
    assert not (tmp_path / "uniswap_v2" / "leaves").exists()


def test_unavailable_endpoint_does_not_override_structured_capacity(
    monkeypatch,
) -> None:
    urls = ["https://denied.example/key", "https://capacity.example/key"]
    monkeypatch.setattr("ddvc.quoter.rpc_urls", lambda: urls)

    def urlopen(request, **_kwargs):
        if request.full_url == urls[0]:
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "Forbidden",
                {},
                io.BytesIO(b"{}"),
            )
        raise urllib.error.HTTPError(
            request.full_url,
            408,
            "Request Timeout",
            {},
            io.BytesIO(b"{}"),
        )

    monkeypatch.setattr("ddvc.quoter.urllib.request.urlopen", urlopen)
    with pytest.raises(ExactLogCapacityError) as error:
        rpc_post_with_evidence(
            {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": []},
            retries=1,
        )
    assert [attempt["http_status"] for attempt in error.value.attempts] == [403, 408]


def test_sanitized_endpoint_identity_is_credential_rotation_stable() -> None:
    first = sanitized_endpoint_identity(
        "https://user:secret@rpc.example/v2/private-key?token=first"
    )
    second = sanitized_endpoint_identity(
        "https://other:credential@rpc.example/v2/rotated-key?token=second"
    )
    assert first["host"] == "rpc.example"
    assert first == second
    assert "secret" not in json.dumps(first)


def test_interrupted_adaptive_root_reuses_published_split_without_overlap(tmp_path) -> None:
    first_attempt = True
    frozen = frozen_upper(109)

    def rpc(payload, **_kwargs):
        nonlocal first_attempt
        query = payload[0]["params"][0]
        perimeter = (int(query["fromBlock"], 16), int(query["toBlock"], 16))
        if first_attempt and perimeter == (100, 109):
            raise ExactLogCapacityError("capacity")
        if first_attempt and perimeter == (105, 109):
            first_attempt = False
            raise Throttled("interrupted after left leaf")
        return anchored_rpc_batch(payload, [], frozen)

    with pytest.raises(Throttled, match="interrupted"):
        fetch_factory_root_adaptive(
            "uniswap_v2",
            100,
            109,
            frozen_upper=frozen,
            root=tmp_path,
            rpc_request=rpc,
        )
    assert factory_leaf_complete("uniswap_v2", 100, 104, frozen_upper=frozen, root=tmp_path)
    retried = fetch_factory_root_adaptive(
        "uniswap_v2",
        100,
        109,
        frozen_upper=frozen,
        root=tmp_path,
        rpc_request=rpc,
    )
    assert retried == [(100, 104), (105, 109)]
    published = []
    for marker_path in (tmp_path / "uniswap_v2" / "leaves").glob("*.meta.json"):
        marker = json.loads(marker_path.read_text())
        perimeter = (int(marker["start_block"]), int(marker["end_block"]))
        if factory_leaf_complete("uniswap_v2", *perimeter, frozen_upper=frozen, root=tmp_path):
            published.append(perimeter)
    assert validate_factory_coverage_ranges(published, 100, 109) == retried


def test_factory_leaf_marker_tamper_is_not_reused_or_overwritten(tmp_path) -> None:
    calls = 0
    frozen = frozen_upper(109)

    def rpc(payload, **_kwargs):
        nonlocal calls
        calls += 1
        return anchored_rpc_batch(payload, [], frozen)

    fetch_factory_root_adaptive(
        "uniswap_v2",
        100,
        109,
        frozen_upper=frozen,
        root=tmp_path,
        rpc_request=rpc,
    )
    _raw_path, marker_path = factory_leaf_paths("uniswap_v2", 100, 109, root=tmp_path)
    marker = json.loads(marker_path.read_text())
    marker["raw_logs"] = 1
    marker_path.write_text(json.dumps(marker))
    assert not factory_leaf_complete("uniswap_v2", 100, 109, frozen_upper=frozen, root=tmp_path)
    with pytest.raises(RuntimeError, match="quarantined"):
        fetch_factory_root_adaptive(
            "uniswap_v2",
            100,
            109,
            frozen_upper=frozen,
            root=tmp_path,
            rpc_request=rpc,
        )
    assert calls == 1


@pytest.mark.parametrize(
    "records",
    [
        [pair_created_raw(block_number=99)],
        [{**pair_created_raw(block_number=105), "address": "0x" + "f" * 40}],
        [{**pair_created_raw(block_number=105), "topics": [V2_EVENT_TOPICS["swap"]]}],
        [pair_created_raw(block_number=105, removed=True)],
        [pair_created_raw(block_number=105), pair_created_raw(block_number=105)],
    ],
    ids=["out-of-range", "wrong-factory", "wrong-topic", "removed", "duplicate"],
)
def test_factory_leaf_completeness_revalidates_every_raw_row(tmp_path, records) -> None:
    write_factory_leaf(tmp_path, 100, 109, records)
    assert not factory_leaf_complete("uniswap_v2", 100, 109, frozen_upper=frozen_upper(109), root=tmp_path)


def test_factory_coverage_is_exact_and_roots_are_deterministic() -> None:
    assert factory_root_ranges(12_345, 32_345) == [
        (12_345, 19_999),
        (20_000, 29_999),
        (30_000, 32_345),
    ]
    assert validate_factory_coverage_ranges([(100, 104), (105, 109)], 100, 109) == [
        (100, 104),
        (105, 109),
    ]
    with pytest.raises(ValueError, match="gap"):
        validate_factory_coverage_ranges([(100, 104), (106, 109)], 100, 109)
    with pytest.raises(ValueError, match="overlap"):
        validate_factory_coverage_ranges([(100, 105), (105, 109)], 100, 109)
    assert V2_FACTORY_INITIAL_BLOCK_SPAN == 10_000


def test_factory_manifest_rejects_nonbisecting_leaf_ancestry(tmp_path) -> None:
    ancestry = [{"start_block": 100, "end_block": 109, "attempts": []}]
    for start, end in ((100, 103), (104, 109)):
        write_factory_leaf(
            tmp_path,
            start,
            end,
            [],
            root_start_block=100,
            root_end_block=109,
            adaptive_depth=1,
            split_ancestry=ancestry,
        )
    with pytest.raises(ValueError, match="ancestry|bisection|root"):
        write_factory_coverage_manifest(
            "uniswap_v2",
            100,
            frozen_upper(109),
            [(100, 103), (104, 109)],
            root=tmp_path,
        )


def test_frozen_upper_block_rejects_header_mutation_against_response_identity(tmp_path) -> None:
    block = 109
    load_or_resolve_frozen_upper_block(
        block,
        fetch=True,
        root=tmp_path,
        rpc_request=state_rpc_for_pairs([], header_hash="0x" + "9" * 64),
    )
    path = tmp_path / "frozen_upper_blocks" / f"block_{block:08d}.json"
    record = json.loads(path.read_text())
    record["block_hash"] = "0x" + "7" * 64
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="hash|response"):
        load_or_resolve_frozen_upper_block(
            block,
            fetch=False,
            root=tmp_path,
        )


def test_frozen_upper_block_rejects_unbound_attempt_evidence(tmp_path) -> None:
    block = 109
    path = tmp_path / "frozen_upper_blocks" / f"block_{block:08d}.json"
    path.parent.mkdir(parents=True)
    record = frozen_upper(block)
    record["rpc_attempts"] = [{"classification": "success"}]
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="attempt|endpoint"):
        load_or_resolve_frozen_upper_block(block, fetch=False, root=tmp_path)


def test_frozen_upper_block_rejects_consistently_malformed_hash_identity(tmp_path) -> None:
    block = 109
    path = tmp_path / "frozen_upper_blocks" / f"block_{block:08d}.json"
    path.parent.mkdir(parents=True)
    record = frozen_upper(block)
    malformed_hash = "0x" + "z" * 64
    record["block_hash"] = malformed_hash
    record["rpc_response"]["result"]["hash"] = malformed_hash
    record["response_sha256"] = canonical_json_sha256(record["rpc_response"])
    record["header_identity_sha256"] = canonical_json_sha256(
        {
            "block_number": record["block_number"],
            "block_hash": record["block_hash"],
            "parent_hash": record["parent_hash"],
            "timestamp": record["timestamp"],
        }
    )
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="exact header identity"):
        load_or_resolve_frozen_upper_block(block, fetch=False, root=tmp_path)


def test_factory_state_calls_are_bound_to_the_frozen_upper_hash() -> None:
    pairs = factory_pairs(1)
    frozen = frozen_upper(109, block_hash="0x" + "9" * 64)
    rpc = state_rpc_for_pairs(pairs, header_hash="0x" + "7" * 64)
    with pytest.raises((RuntimeError, ValueError), match="hash|frozen|canonical"):
        build_factory_state_proof(
            "uniswap_v2",
            pairs,
            frozen,
            sample_size=1,
            workers=1,
            rpc_request=rpc,
        )


def test_factory_deployment_proof_binds_upper_code_to_frozen_hash(monkeypatch) -> None:
    venue = "uniswap_v2"
    factory = V2_FACTORIES[venue]
    upper = 109
    upper_hash = "0x" + "9" * 64
    runtime_code = "0x6000"
    endpoint = {"host": "state.example", "endpoint_sha256": "3" * 64}

    def rpc(payload, **_kwargs):
        block_reference = payload["params"][1]
        if isinstance(block_reference, dict):
            assert block_reference == {"blockHash": upper_hash, "requireCanonical": True}
            result = runtime_code
        else:
            result = "0x" if int(block_reference, 16) == 9 else runtime_code
        response = {"jsonrpc": "2.0", "id": 1, "result": result}
        return RpcEnvelope(response, endpoint, (successful_rpc_attempt(endpoint),))

    monkeypatch.setattr(auditor, "rpc_post_with_evidence", rpc)
    evidence = []
    auditor._code_at_block(factory, 9, evidence)
    auditor._code_at_block(factory, 10, evidence)
    auditor._code_at_block(factory, upper, evidence, block_hash=upper_hash)
    record = {
        "status": "complete",
        "schema_version": V2_FACTORY_EVIDENCE_SCHEMA_VERSION,
        "venue": venue,
        "factory": factory,
        "deployment_block": 10,
        "upper_block": upper,
        "upper_block_hash": upper_hash,
        "runtime_code_sha256": hashlib.sha256(bytes.fromhex("6000")).hexdigest(),
        "rpc_evidence": evidence,
    }
    assert validate_factory_deployment_proof(record, venue, upper, upper_hash) == 10
    record["rpc_evidence"][-1]["request"]["params"][1] = hex(upper)
    with pytest.raises(ValueError, match="frozen|hash|code"):
        validate_factory_deployment_proof(record, venue, upper, upper_hash)


def test_factory_state_length_must_equal_exact_paircreated_ordinals() -> None:
    pairs = factory_pairs(1)
    with pytest.raises(ValueError, match="allPairsLength disagrees"):
        build_factory_state_proof(
            "uniswap_v2",
            pairs,
            frozen_upper(109),
            sample_size=1,
            workers=1,
            rpc_request=state_rpc_for_pairs(pairs, all_pairs_length=2),
        )


def test_factory_state_sample_honours_sample_size_one() -> None:
    sample = deterministic_factory_state_sample(factory_pairs(3), sample_size=1)
    assert len(sample) == 1
    assert sample[0].ordinal == 1


def test_fabricated_factory_state_proof_without_exact_rpc_evidence_is_rejected() -> None:
    pairs = factory_pairs(1)
    frozen = frozen_upper(109)
    proof = build_factory_state_proof(
        "uniswap_v2",
        pairs,
        frozen,
        sample_size=1,
        workers=1,
        rpc_request=state_rpc_for_pairs(pairs),
    )
    proof.pop("length_rpc_request", None)
    proof.pop("length_rpc_response_sha256", None)
    for result in proof["sample_results"]:
        for field in ("target", "calldata", "upper_block", "response_sha256"):
            result.pop(field, None)
    with pytest.raises(ValueError, match="evidence|request|response|calldata"):
        validate_factory_state_proof(
            proof,
            venue="uniswap_v2",
            pairs=pairs,
            frozen_upper=frozen,
            sample_size=1,
        )


def test_mutated_factory_state_proof_is_rejected() -> None:
    pairs = factory_pairs(1)
    frozen = frozen_upper(109)
    proof = build_factory_state_proof(
        "uniswap_v2",
        pairs,
        frozen,
        sample_size=1,
        workers=1,
        rpc_request=state_rpc_for_pairs(pairs),
    )
    assert proof["registry_sha256"] == factory_registry_sha256(pairs)
    proof["sample_results"][0]["observed"] = "0x" + "f" * 40
    with pytest.raises(ValueError, match="sample"):
        validate_factory_state_proof(
            proof,
            venue="uniswap_v2",
            pairs=pairs,
            frozen_upper=frozen,
            sample_size=1,
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


def test_graph_only_identity_remains_explicit_without_token_decimals(tmp_path) -> None:
    venue = "uniswap_v2"
    day = "20250115"
    directory = tmp_path / venue
    directory.mkdir()
    write_jsonl_gz(directory / f"{venue}_mints_{day}.jsonl.gz", [graph_event("mint")])
    for stream in ("burns", "swaps"):
        write_jsonl_gz(directory / f"{venue}_{stream}_{day}.jsonl.gz", [])
    statics, _pairs = factory_pair_registry(venue, [pair_created_raw()], {})
    graph, duplicates = graph_core_events_for_amount_keys(
        tmp_path,
        venue,
        day,
        statics,
        amount_keys=set(),
    )
    summaries, exceptions = compare_event_maps(day, venue, {}, graph, duplicates)
    mint = next(row for row in summaries if row["event_type"] == "mint")
    assert mint["graph_only"] == 1
    assert exceptions[0]["status"] == "graph_only"
    assert exceptions[0]["graph_amount0_delta_raw"] is None


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
    frozen = frozen_upper(149)
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
    payloads = []

    def rpc_response(payload, **_kwargs):
        payloads.append(payload)
        return anchored_rpc_batch(payload, [rpc_log], frozen)

    fetch_v2_exact_log_chunk(100, 149, frozen_upper=frozen, root=tmp_path, rpc_request=rpc_response)
    assert "address" not in payloads[0][0]["params"][0]
    assert set(payloads[0][0]["params"][0]["topics"][0]) == set(V2_EVENT_TOPICS.values())
    assert v2_exact_log_chunk_complete(100, 149, frozen_upper=frozen, root=tmp_path)
    fetch_v2_exact_log_chunk(100, 149, frozen_upper=frozen, root=tmp_path, rpc_request=rpc_response)
    assert len(payloads) == 1
    records, inputs = read_v2_exact_logs(100, 110, frozen_upper=frozen, root=tmp_path)
    assert len(records) == 1
    assert len(inputs) == 2
    _raw, marker = v2_exact_log_chunk_paths(100, 149, root=tmp_path)
    payload = json.loads(marker.read_text())
    payload["status"] = "incomplete"
    marker.write_text(json.dumps(payload))
    assert not v2_exact_log_chunk_complete(100, 149, frozen_upper=frozen, root=tmp_path)
    with pytest.raises(RuntimeError, match="must be quarantined"):
        fetch_v2_exact_log_chunk(100, 149, frozen_upper=frozen, root=tmp_path, rpc_request=rpc_response)


def test_exact_rpc_chunk_remains_reusable_when_the_sample_upper_block_advances(
    tmp_path,
) -> None:
    anchored = frozen_upper(149)
    current = frozen_upper(199)

    def rpc_response(payload, **_kwargs):
        return anchored_rpc_batch(payload, [], anchored)

    fetch_v2_exact_log_chunk(
        100,
        149,
        frozen_upper=anchored,
        root=tmp_path,
        rpc_request=rpc_response,
    )
    old_anchor_path = frozen_upper_block_path(149, root=tmp_path)
    old_anchor_path.parent.mkdir(parents=True, exist_ok=True)
    old_anchor_path.write_text(json.dumps(anchored), encoding="utf-8")

    assert v2_exact_log_chunk_complete(
        100,
        149,
        frozen_upper=current,
        root=tmp_path,
    )
    assert missing_v2_exact_log_ranges(
        [(100, 149)],
        frozen_upper=current,
        root=tmp_path,
    ) == []


def test_factory_leaf_remains_reusable_when_the_sample_upper_block_advances(
    tmp_path,
) -> None:
    anchored = frozen_upper(109)
    current = frozen_upper(159)

    def rpc_response(payload, **_kwargs):
        return anchored_rpc_batch(payload, [], anchored)

    fetch_factory_root_adaptive(
        "uniswap_v2",
        100,
        109,
        frozen_upper=anchored,
        root=tmp_path,
        rpc_request=rpc_response,
    )
    old_anchor_path = frozen_upper_block_path(109, root=tmp_path)
    old_anchor_path.parent.mkdir(parents=True, exist_ok=True)
    old_anchor_path.write_text(json.dumps(anchored), encoding="utf-8")

    assert factory_leaf_complete(
        "uniswap_v2",
        100,
        109,
        frozen_upper=current,
        root=tmp_path,
    )


@pytest.mark.parametrize("mutation", ["response", "attempts", "jsonrpc"])
def test_exact_rpc_chunk_rejects_mutated_response_or_attempt_contract(tmp_path, mutation) -> None:
    frozen = frozen_upper(149)
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

    def rpc_response(payload, **_kwargs):
        return anchored_rpc_batch(payload, [rpc_log], frozen)

    fetch_v2_exact_log_chunk(100, 149, frozen_upper=frozen, root=tmp_path, rpc_request=rpc_response)
    _raw, marker_path = v2_exact_log_chunk_paths(100, 149, root=tmp_path)
    marker = json.loads(marker_path.read_text())
    if mutation == "response":
        marker["rpc_response"][0]["result"] = []
    elif mutation == "attempts":
        marker["rpc_attempts"] = [{"classification": "success"}]
    else:
        marker["rpc_response"][0].pop("jsonrpc")
    marker_path.write_text(json.dumps(marker))
    assert not v2_exact_log_chunk_complete(100, 149, frozen_upper=frozen, root=tmp_path)


def test_v2_exact_log_ranges_are_global_not_consumer_edge_aligned() -> None:
    assert EXACT_LOG_BLOCK_CAP == 50
    assert exact_log_block_ranges(151, 250) == [
        (151, 199),
        (200, 249),
        (250, 250),
    ]
    assert v2_exact_log_ranges(151, 250) == [
        (150, 199),
        (200, 249),
        (250, 299),
    ]


def test_missing_exact_log_ranges_are_deduplicated_across_consumers(tmp_path) -> None:
    assert missing_v2_exact_log_ranges(
        [(25, 75), (50, 100)],
        frozen_upper=frozen_upper(149),
        root=tmp_path,
    ) == [(0, 49), (50, 99), (100, 149)]


def test_both_v2_consumers_import_the_same_exact_log_owner() -> None:
    assert auditor.fetch_v2_exact_log_chunk is reconciler.fetch_v2_exact_log_chunk
    assert auditor.read_v2_exact_logs is reconciler.read_v2_exact_logs


def test_no_fetch_refuses_to_resolve_a_missing_day_cut(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(auditor, "RAW_DAY_BOUND_ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="lacks a current UTC block cut"):
        auditor.load_or_resolve_day_bounds("20250115", fetch=False)


def test_day_bound_search_starts_at_a_strictly_prior_protocol_block() -> None:
    assert auditor._day_lower("20200515") == get_source("uniswap_v2").genesis_block
    assert auditor._day_lower("20201015") == get_source("uniswap_v2").genesis_block
    with pytest.raises(RuntimeError, match="strictly prior"):
        auditor._day_lower("20200505")


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
        "first_day": days[0],
        "last_day": days[-1],
        "summary_rows": len(rows),
        "exception_rows": 0,
        "venues": list(V2_EVENT_VENUES),
        "event_types": list(V2_CORE_EVENTS),
        "pool_perimeter": V2_POOL_PERIMETER,
        "registry_source": "complete_factory_PairCreated_histories",
        "global_event_query": "topic_only_without_address_filter",
        "identity_fields": [
            "venue",
            "event_type",
            "block_number",
            "transaction_hash",
            "log_index",
            "pool",
        ],
        "quantity_contract": "exact_raw_token_deltas_and_swap_in_out_fields",
        "token_decimals_contract": V2_TOKEN_DECIMALS_CONTRACT,
        "token_decimals_scope": V2_TOKEN_DECIMALS_SCOPE,
        "raw_factory_chunks": 2,
        "raw_event_chunks": 2,
        "raw_global_event_logs": 0,
        "raw_events": 0,
        "graph_events": 0,
        "matched_identities": 0,
        "missing_from_graph": 0,
        "graph_only": 0,
        "graph_duplicate_identities": 0,
        "amount_mismatches": 0,
        "factory_pairs": 2,
        "factory_pairs_by_venue": {venue: 1 for venue in V2_EVENT_VENUES},
        "factory_registry_sha256": "a" * 64,
        "token_decimals_registry_rows": 2,
        "token_decimals_registry_sha256": "f" * 64,
        "token_decimals_registry_file_sha256": "1" * 64,
        "token_decimals_evidence_files": 2,
        "factory_registry_upper_block": 109,
        "factory_registry_upper_block_hash": "0x" + "9" * 64,
        "factory_registry_upper_block_timestamp": 1_700_000_000,
        "frozen_upper_block_sha256": "d" * 64,
        "factory_deployment_proof_sha256_by_venue": {
            venue: "e" * 64 for venue in V2_EVENT_VENUES
        },
        "factory_coverage_manifest_sha256_by_venue": {
            venue: "b" * 64 for venue in V2_EVENT_VENUES
        },
        "factory_state_proof_sha256_by_venue": {
            venue: "c" * 64 for venue in V2_EVENT_VENUES
        },
        "factory_state_sample_size_by_venue": {
            venue: 1 for venue in V2_EVENT_VENUES
        },
    }
    assert validate_v2_event_source_certificate(summary, exceptions, certificate, days) == (2, 0)
    non_boolean = summary.copy()
    non_boolean["passed"] = 1
    with pytest.raises(ValueError, match="not Boolean"):
        validate_v2_event_source_certificate(non_boolean, exceptions, certificate, days)
    impossible = summary.copy()
    audited_index = impossible.index[impossible["launch_status"] == "audited"][0]
    impossible.loc[audited_index, "raw_events"] = 1
    impossible_certificate = {**certificate, "raw_events": 1, "raw_global_event_logs": 1}
    with pytest.raises(ValueError, match="impossible identity count algebra"):
        validate_v2_event_source_certificate(
            impossible,
            exceptions,
            impossible_certificate,
            days,
        )
    proof_fields = {
        "factory_registry_upper_block",
        "factory_registry_upper_block_hash",
        "factory_registry_upper_block_timestamp",
        "frozen_upper_block_sha256",
        "factory_deployment_proof_sha256_by_venue",
        "factory_coverage_manifest_sha256_by_venue",
        "factory_state_proof_sha256_by_venue",
        "factory_state_sample_size_by_venue",
        "token_decimals_registry_rows",
        "token_decimals_registry_sha256",
        "token_decimals_registry_file_sha256",
        "token_decimals_evidence_files",
    }
    accepted_missing = []
    for field in sorted(proof_fields):
        incomplete = dict(certificate)
        incomplete.pop(field)
        try:
            validate_v2_event_source_certificate(summary, exceptions, incomplete, days)
        except ValueError:
            continue
        accepted_missing.append(field)
    assert not accepted_missing, f"certificate accepted missing proof fields: {accepted_missing}"
    mutations = {
        "factory_registry_upper_block": -1,
        "factory_registry_upper_block_hash": "0x7",
        "factory_registry_upper_block_timestamp": 0,
        "frozen_upper_block_sha256": "d" * 63,
        "factory_deployment_proof_sha256_by_venue": {
            venue: "bad" for venue in V2_EVENT_VENUES
        },
        "factory_coverage_manifest_sha256_by_venue": {
            V2_EVENT_VENUES[0]: "d" * 63
        },
        "factory_state_proof_sha256_by_venue": {
            venue: "not-a-digest" for venue in V2_EVENT_VENUES
        },
        "factory_state_sample_size_by_venue": {
            venue: 2 for venue in V2_EVENT_VENUES
        },
        "token_decimals_registry_rows": 0,
        "token_decimals_registry_sha256": "f" * 63,
        "token_decimals_registry_file_sha256": "bad",
        "token_decimals_evidence_files": 1,
    }
    accepted_mutations = []
    for field, value in mutations.items():
        mutated = {**certificate, field: value}
        try:
            validate_v2_event_source_certificate(summary, exceptions, mutated, days)
        except ValueError:
            continue
        accepted_mutations.append(field)
    assert not accepted_mutations, f"certificate accepted mutated proofs: {accepted_mutations}"
    with pytest.raises(ValueError, match="calendar does not match"):
        validate_v2_event_source_certificate(summary, exceptions, certificate, days[:1])
    with pytest.raises(ValueError, match="exception rows"):
        validate_v2_event_source_certificate(
            summary,
            pd.DataFrame([{"status": "amount_mismatch"}]),
            certificate,
            days,
        )


@pytest.mark.parametrize("artifact", ["coverage", "state"])
def test_release_evidence_bundle_reopens_cited_artifacts(tmp_path, monkeypatch, artifact) -> None:
    import ddvc.v2_event_completeness as completeness

    paths = {}
    for name in ("frozen", "deployment", "coverage", "state"):
        for venue in V2_EVENT_VENUES if name != "frozen" else ("shared",):
            path = tmp_path / f"{name}-{venue}.json"
            path.write_text(json.dumps({"name": name, "venue": venue}))
            paths[(name, venue)] = path

    monkeypatch.setattr(
        completeness,
        "frozen_upper_block_path",
        lambda *_args, **_kwargs: paths[("frozen", "shared")],
    )
    monkeypatch.setattr(
        completeness,
        "factory_deployment_path",
        lambda venue, *_args, **_kwargs: paths[("deployment", venue)],
    )
    monkeypatch.setattr(
        completeness,
        "factory_coverage_manifest_path",
        lambda venue, *_args, **_kwargs: paths[("coverage", venue)],
    )
    monkeypatch.setattr(
        completeness,
        "factory_state_proof_path",
        lambda venue, *_args, **_kwargs: paths[("state", venue)],
    )
    monkeypatch.setattr(completeness, "validate_frozen_upper_block", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        completeness,
        "validate_factory_deployment_proof",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(
        completeness,
        "validate_factory_coverage_manifest",
        lambda *_args, **_kwargs: [(1, 1)],
    )
    monkeypatch.setattr(
        completeness,
        "read_factory_coverage_records",
        lambda *_args, **_kwargs: ([], []),
    )
    monkeypatch.setattr(
        completeness,
        "factory_pair_registry",
        lambda venue, *_args, **_kwargs: (
            {},
            [
                SimpleNamespace(
                    pool="0x" + f"{V2_EVENT_VENUES.index(venue) + 1:040x}"
                )
            ],
        ),
    )
    monkeypatch.setattr(completeness, "validate_factory_state_proof", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(completeness, "factory_registry_sha256", lambda pairs: "a" * 64)

    certificate = {
        "factory_registry_upper_block": 1,
        "factory_registry_upper_block_hash": "0x" + "9" * 64,
        "factory_registry_upper_block_timestamp": 1,
        "frozen_upper_block_sha256": file_sha256(paths[("frozen", "shared")]),
        "factory_deployment_proof_sha256_by_venue": {
            venue: file_sha256(paths[("deployment", venue)]) for venue in V2_EVENT_VENUES
        },
        "factory_coverage_manifest_sha256_by_venue": {
            venue: file_sha256(paths[("coverage", venue)]) for venue in V2_EVENT_VENUES
        },
        "factory_state_proof_sha256_by_venue": {
            venue: file_sha256(paths[("state", venue)]) for venue in V2_EVENT_VENUES
        },
        "factory_state_sample_size_by_venue": {venue: 1 for venue in V2_EVENT_VENUES},
        "factory_pairs_by_venue": {venue: 1 for venue in V2_EVENT_VENUES},
        "factory_pairs": len(V2_EVENT_VENUES),
        "factory_registry_sha256": "a" * 64,
        "raw_factory_chunks": len(V2_EVENT_VENUES),
    }
    frozen_record = {
        "block_hash": certificate["factory_registry_upper_block_hash"],
        "timestamp": certificate["factory_registry_upper_block_timestamp"],
    }
    paths[("frozen", "shared")].write_text(json.dumps(frozen_record))
    certificate["frozen_upper_block_sha256"] = file_sha256(paths[("frozen", "shared")])
    assert validate_v2_event_source_evidence_bundle(certificate, root=tmp_path) == (2, 2)
    paths[(artifact, V2_EVENT_VENUES[0])].write_text("tampered")
    with pytest.raises(ValueError, match=f"{artifact}.*digest"):
        validate_v2_event_source_evidence_bundle(certificate, root=tmp_path)

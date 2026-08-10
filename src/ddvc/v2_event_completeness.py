"""Exact independent-chain completeness contract for V2-family state events."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable, Iterator

from eth_abi import decode as abi_decode
from eth_utils import keccak
import pandas as pd

from ddvc.amounts import human_to_raw
from ddvc.ethereum_logs import rpc_integer
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, OUTPUT_DIR


V2_EVENT_VENUES = ("uniswap_v2", "sushiswap_v2")
V2_CORE_EVENTS = ("burn", "mint", "swap")
V2_EVENT_SIGNATURES = {
    "mint": "Mint(address,uint256,uint256)",
    "burn": "Burn(address,uint256,uint256,address)",
    "swap": "Swap(address,uint256,uint256,uint256,uint256,address)",
}
V2_EVENT_TOPICS = {
    name: "0x" + keccak(text=signature).hex()
    for name, signature in V2_EVENT_SIGNATURES.items()
}
V2_EVENT_BY_TOPIC = {topic: name for name, topic in V2_EVENT_TOPICS.items()}
V2_EVENT_SOURCE_SCHEMA_VERSION = 2
V2_FACTORIES = {
    venue: str(get_source(venue).factory_address).lower()
    for venue in V2_EVENT_VENUES
}
if any(not address.startswith("0x") or len(address) != 42 for address in V2_FACTORIES.values()):
    raise RuntimeError("V2 event-source venues require exact factory addresses in the source registry")
PAIR_CREATED_TOPIC = "0x" + keccak(
    text="PairCreated(address,address,address,uint256)"
).hex()
V2_POOL_PERIMETER = "all_paircreated_pools_from_registered_mainnet_factories"
RAW_V2_EVENT_ROOT = DATA_DIR / "raw" / "ethereum" / "v2_core_event_source"
RAW_V2_FACTORY_ROOT = DATA_DIR / "raw" / "ethereum" / "v2_factory_pair_registry"
RAW_DAY_BOUND_ROOT = DATA_DIR / "raw" / "ethereum" / "utc_day_block_bounds"
V2_EVENT_SOURCE_SUMMARY = DATA_DIR / "processed" / "v2_core_event_source_audit.parquet"
V2_EVENT_SOURCE_EXCEPTIONS = DATA_DIR / "processed" / "v2_core_event_source_exceptions.parquet"
V2_EVENT_SOURCE_CERTIFICATE = OUTPUT_DIR / "exhibits" / "v2_core_event_source_certificate.json"

EventKey = tuple[str, str, int, str, int, str]


@dataclass(frozen=True)
class PoolStatic:
    pool: str
    token0: str
    token1: str
    decimals0: int | None
    decimals1: int | None


@dataclass(frozen=True)
class FactoryPair:
    venue: str
    factory: str
    pool: str
    token0: str
    token1: str
    creation_block: int
    creation_tx_hash: str
    creation_log_index: int
    ordinal: int


@dataclass(frozen=True)
class EventAmounts:
    amount0_delta_raw: int
    amount1_delta_raw: int
    amount0_in_raw: int
    amount1_in_raw: int
    amount0_out_raw: int
    amount1_out_raw: int


def audit_calendar_sha256(days: Iterable[str]) -> str:
    payload = json.dumps(sorted(set(days)), separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def event_key(
    venue: str,
    event_type: str,
    block: object,
    tx_hash: object,
    log_index: object,
    pool: object,
) -> EventKey:
    return (
        str(venue),
        str(event_type),
        int(block),
        str(tx_hash).lower(),
        int(log_index),
        str(pool).lower(),
    )


def _exact_raw(value: object, decimals: int, *, label: str) -> int:
    converted = human_to_raw(value, decimals)
    if converted is None:
        raise ValueError(f"{label} is not an exact base-unit token amount")
    return int(converted)


def _address(value: object, *, label: str) -> str:
    address = str(value or "").lower()
    if not address.startswith("0x") or len(address) != 42:
        raise ValueError(f"{label} lacks an exact contract address")
    return address


def _transaction_hash(value: object, *, label: str) -> str:
    transaction_hash = str(value or "").lower()
    if not transaction_hash.startswith("0x") or len(transaction_hash) != 66:
        raise ValueError(f"{label} lacks an exact transaction hash")
    return transaction_hash


def iter_graph_rows(path: Path) -> Iterator[dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"non-object Graph record in {path.name}")
                yield record


def graph_stream_path(graph_root: Path, venue: str, stream: str, day: str) -> Path:
    return graph_root / venue / f"{venue}_{stream}_{day}.jsonl.gz"


def _pool_static_from_row(
    row: dict[str, object],
    token_decimals: dict[str, int],
) -> PoolStatic:
    pair = row.get("pair")
    if not isinstance(pair, dict):
        raise ValueError("V2 Graph record lacks a pair object")
    token0 = pair.get("token0")
    token1 = pair.get("token1")
    if not isinstance(token0, dict) or not isinstance(token1, dict):
        raise ValueError("V2 Graph pair lacks token objects")
    pool = _address(pair.get("id"), label="V2 pool")
    token0_address = _address(token0.get("id"), label=f"{pool} token0")
    token1_address = _address(token1.get("id"), label=f"{pool} token1")
    decimals0 = token_decimals.get(token0_address)
    decimals1 = token_decimals.get(token1_address)
    for token, expected, label in (
        (token0, decimals0, "token0"),
        (token1, decimals1, "token1"),
    ):
        observed = token.get("decimals")
        if observed is not None and expected is not None and int(observed) != expected:
            raise ValueError(
                f"{pool} {label} decimals disagree with the audited registry: "
                f"{observed} versus {expected}"
            )
    return PoolStatic(pool, token0_address, token1_address, decimals0, decimals1)


def decode_pair_created_log(venue: str, log: dict[str, object]) -> FactoryPair:
    """Decode one canonical factory log into an independently registered V2 pair."""

    factory = _address(log.get("address"), label=f"{venue} factory")
    if factory != V2_FACTORIES[venue]:
        raise ValueError(f"PairCreated log came from an unregistered {venue} factory")
    if bool(log.get("removed")):
        raise ValueError("removed PairCreated log cannot enter the pool registry")
    topics = [str(value).lower() for value in log.get("topics") or []]
    if len(topics) != 3 or topics[0] != PAIR_CREATED_TOPIC:
        raise ValueError("factory log is not an exact PairCreated event")
    token0 = _address("0x" + topics[1][-40:], label="PairCreated token0")
    token1 = _address("0x" + topics[2][-40:], label="PairCreated token1")
    pool, ordinal = abi_decode(
        ["address", "uint256"],
        bytes.fromhex(str(log.get("data") or "0x").removeprefix("0x")),
    )
    return FactoryPair(
        venue=venue,
        factory=factory,
        pool=_address(pool, label="PairCreated pair"),
        token0=token0,
        token1=token1,
        creation_block=rpc_integer(log.get("blockNumber", log.get("block_number"))),
        creation_tx_hash=_transaction_hash(
            log.get("transactionHash", log.get("transaction_hash")),
            label="PairCreated",
        ),
        creation_log_index=rpc_integer(log.get("logIndex", log.get("log_index"))),
        ordinal=int(ordinal),
    )


def factory_pair_registry(
    venue: str,
    records: Iterable[dict[str, object]],
    token_decimals: dict[str, int],
) -> tuple[dict[str, PoolStatic], list[FactoryPair]]:
    """Build a fail-closed pool registry from the factory's complete event history."""

    by_pool: dict[str, FactoryPair] = {}
    by_ordinal: dict[int, FactoryPair] = {}
    for record in records:
        pair = decode_pair_created_log(venue, record)
        if pair.pool in by_pool:
            raise ValueError(f"duplicate PairCreated pool identity: {pair.pool}")
        if pair.ordinal in by_ordinal:
            raise ValueError(f"duplicate PairCreated ordinal: {pair.ordinal}")
        by_pool[pair.pool] = pair
        by_ordinal[pair.ordinal] = pair
    expected_ordinals = set(range(1, len(by_ordinal) + 1))
    if set(by_ordinal) != expected_ordinals:
        missing = sorted(expected_ordinals - set(by_ordinal))[:3]
        raise ValueError(f"factory PairCreated sequence is incomplete; missing={missing}")
    statics = {
        pair.pool: PoolStatic(
            pool=pair.pool,
            token0=pair.token0,
            token1=pair.token1,
            decimals0=token_decimals.get(pair.token0),
            decimals1=token_decimals.get(pair.token1),
        )
        for pair in by_pool.values()
    }
    return statics, sorted(by_pool.values(), key=lambda pair: pair.ordinal)


def _graph_event_amounts(
    row: dict[str, object],
    event_type: str,
    static: PoolStatic,
) -> EventAmounts:
    if static.decimals0 is None or static.decimals1 is None:
        missing = [
            token
            for token, decimals in (
                (static.token0, static.decimals0),
                (static.token1, static.decimals1),
            )
            if decimals is None
        ]
        raise ValueError(
            f"{static.pool} event token decimals are absent from the audited registry: "
            f"{missing}"
        )
    if event_type == "swap":
        amount0_in = _exact_raw(row.get("amount0In") or "0", static.decimals0, label="amount0In")
        amount1_in = _exact_raw(row.get("amount1In") or "0", static.decimals1, label="amount1In")
        amount0_out = _exact_raw(row.get("amount0Out") or "0", static.decimals0, label="amount0Out")
        amount1_out = _exact_raw(row.get("amount1Out") or "0", static.decimals1, label="amount1Out")
        return EventAmounts(
            amount0_in - amount0_out,
            amount1_in - amount1_out,
            amount0_in,
            amount1_in,
            amount0_out,
            amount1_out,
        )
    amount0 = _exact_raw(row.get("amount0"), static.decimals0, label="amount0")
    amount1 = _exact_raw(row.get("amount1"), static.decimals1, label="amount1")
    sign = 1 if event_type == "mint" else -1
    return EventAmounts(sign * amount0, sign * amount1, 0, 0, 0, 0)


def _add_event(
    events: dict[EventKey, EventAmounts],
    duplicates: set[EventKey],
    key: EventKey,
    amounts: EventAmounts,
) -> None:
    if key in events:
        duplicates.add(key)
        return
    events[key] = amounts


def graph_core_events(
    graph_root: Path,
    venue: str,
    day: str,
    statics: dict[str, PoolStatic],
) -> tuple[dict[EventKey, EventAmounts], set[EventKey]]:
    events: dict[EventKey, EventAmounts] = {}
    duplicates: set[EventKey] = set()
    for event_type, stream in (("mint", "mints"), ("burn", "burns"), ("swap", "swaps")):
        for row in iter_graph_rows(graph_stream_path(graph_root, venue, stream, day)):
            pair = row.get("pair")
            pool = _address(pair.get("id") if isinstance(pair, dict) else None, label="V2 event pool")
            static = statics.get(pool)
            if static is None:
                raise ValueError(f"V2 event pool {pool} is absent from the factory registry")
            observed = _pool_static_from_row(row, {
                token: decimals
                for token, decimals in (
                    (static.token0, static.decimals0),
                    (static.token1, static.decimals1),
                )
                if decimals is not None
            })
            if (observed.pool, observed.token0, observed.token1) != (
                static.pool,
                static.token0,
                static.token1,
            ):
                raise ValueError(f"Graph event disagrees with factory pair identity for {pool}")
            transaction = row.get("transaction")
            tx_hash = transaction.get("id") if isinstance(transaction, dict) else transaction
            block = transaction.get("blockNumber") if isinstance(transaction, dict) else None
            key = event_key(
                venue,
                event_type,
                block,
                tx_hash,
                row.get("logIndex"),
                pool,
            )
            _add_event(events, duplicates, key, _graph_event_amounts(row, event_type, static))
    return events, duplicates


def decode_v2_log(venue: str, log: dict[str, object]) -> tuple[EventKey, EventAmounts]:
    """Decode one canonical raw V2 log into exact event identity and raw amounts."""

    if bool(log.get("removed")):
        raise ValueError("removed V2 log cannot enter the source certificate")
    topics = [str(value).lower() for value in log.get("topics") or []]
    if not topics or topics[0] not in V2_EVENT_BY_TOPIC:
        raise ValueError("log is not a registered V2 core event")
    event_type = V2_EVENT_BY_TOPIC[topics[0]]
    data = bytes.fromhex(str(log.get("data") or "0x").removeprefix("0x"))
    if event_type == "swap":
        amount0_in, amount1_in, amount0_out, amount1_out = (
            int(value)
            for value in abi_decode(["uint256", "uint256", "uint256", "uint256"], data)
        )
        amounts = EventAmounts(
            amount0_in - amount0_out,
            amount1_in - amount1_out,
            amount0_in,
            amount1_in,
            amount0_out,
            amount1_out,
        )
    else:
        amount0, amount1 = (int(value) for value in abi_decode(["uint256", "uint256"], data))
        sign = 1 if event_type == "mint" else -1
        amounts = EventAmounts(sign * amount0, sign * amount1, 0, 0, 0, 0)
    key = event_key(
        venue,
        event_type,
        rpc_integer(log.get("blockNumber", log.get("block_number"))),
        log.get("transactionHash", log.get("transaction_hash")),
        rpc_integer(log.get("logIndex", log.get("log_index"))),
        log.get("address"),
    )
    return key, amounts


def raw_core_events(
    venue: str,
    records: Iterable[dict[str, object]],
    *,
    expected_pools: set[str],
    expected_creation_blocks: dict[str, int] | None = None,
    ignore_unregistered: bool = False,
) -> dict[EventKey, EventAmounts]:
    events: dict[EventKey, EventAmounts] = {}
    duplicates: set[EventKey] = set()
    for record in records:
        pool = _address(record.get("address"), label="raw V2 event pool")
        if pool not in expected_pools and ignore_unregistered:
            continue
        key, amounts = decode_v2_log(venue, record)
        if key[-1] not in expected_pools:
            raise ValueError(f"raw V2 log pool outside the declared batch perimeter: {key[-1]}")
        if (
            expected_creation_blocks is not None
            and key[2] < expected_creation_blocks[key[-1]]
        ):
            raise ValueError(f"raw V2 event predates its PairCreated identity: {key}")
        _add_event(events, duplicates, key, amounts)
    if duplicates:
        raise ValueError(f"exact raw V2 audit has {len(duplicates):,} duplicate identities")
    return events


def _amount_columns(prefix: str, amounts: EventAmounts | None) -> dict[str, str | None]:
    values = asdict(amounts) if amounts is not None else {}
    return {
        f"{prefix}_{name}": str(values[name]) if name in values else None
        for name in EventAmounts.__dataclass_fields__
    }


def _exception_row(
    day: str,
    key: EventKey,
    status: str,
    raw: EventAmounts | None,
    graph: EventAmounts | None,
) -> dict[str, object]:
    venue, event_type, block, tx_hash, log_index, pool = key
    return {
        "day": day,
        "venue": venue,
        "event_type": event_type,
        "status": status,
        "block_number": block,
        "tx_hash": tx_hash,
        "log_index": log_index,
        "pool": pool,
        **_amount_columns("raw", raw),
        **_amount_columns("graph", graph),
    }


def compare_event_maps(
    day: str,
    venue: str,
    raw: dict[EventKey, EventAmounts],
    graph: dict[EventKey, EventAmounts],
    graph_duplicates: set[EventKey],
    *,
    launch_status: str = "audited",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    summaries: list[dict[str, object]] = []
    exceptions: list[dict[str, object]] = []
    for event_type in V2_CORE_EVENTS:
        raw_keys = {key for key in raw if key[1] == event_type}
        graph_keys = {key for key in graph if key[1] == event_type}
        matched = raw_keys & graph_keys
        missing = raw_keys - graph_keys
        graph_only = graph_keys - raw_keys
        duplicates = {key for key in graph_duplicates if key[1] == event_type}
        mismatches = {key for key in matched if raw[key] != graph[key]}
        summaries.append(
            {
                "day": day,
                "venue": venue,
                "event_type": event_type,
                "launch_status": launch_status,
                "raw_events": len(raw_keys),
                "graph_events": len(graph_keys),
                "matched_identities": len(matched),
                "missing_from_graph": len(missing),
                "graph_only": len(graph_only),
                "graph_duplicate_identities": len(duplicates),
                "amount_mismatches": len(mismatches),
                "passed": not (missing or graph_only or duplicates or mismatches),
            }
        )
        exceptions.extend(
            _exception_row(day, key, "missing_from_graph", raw[key], None)
            for key in sorted(missing)
        )
        exceptions.extend(
            _exception_row(day, key, "graph_only", None, graph[key])
            for key in sorted(graph_only)
        )
        exceptions.extend(
            _exception_row(day, key, "amount_mismatch", raw[key], graph[key])
            for key in sorted(mismatches)
        )
        exceptions.extend(
            _exception_row(day, key, "graph_duplicate_identity", raw.get(key), graph.get(key))
            for key in sorted(duplicates)
        )
    return summaries, exceptions


def expected_summary_keys(days: Iterable[str]) -> set[tuple[str, str, str]]:
    return {
        (venue, day, event_type)
        for venue in V2_EVENT_VENUES
        for day in days
        for event_type in V2_CORE_EVENTS
    }


def validate_v2_event_source_certificate(
    summary: pd.DataFrame,
    exceptions: pd.DataFrame,
    certificate: dict[str, object],
    expected_days: list[str],
) -> tuple[int, int]:
    """Validate exact calendar, identities, quantities, and zero-exception release."""

    required = {
        "day",
        "venue",
        "event_type",
        "launch_status",
        "raw_events",
        "graph_events",
        "matched_identities",
        "missing_from_graph",
        "graph_only",
        "graph_duplicate_identities",
        "amount_mismatches",
        "passed",
    }
    missing_columns = sorted(required - set(summary.columns))
    if missing_columns:
        raise ValueError(f"V2 event-source summary lacks columns: {missing_columns}")
    if summary.duplicated(["venue", "day", "event_type"]).any():
        raise ValueError("V2 event-source summary contains duplicate keys")
    actual = set(
        summary[["venue", "day", "event_type"]].astype(str).itertuples(index=False, name=None)
    )
    expected = expected_summary_keys(expected_days)
    if actual != expected:
        raise ValueError(
            "V2 event-source calendar does not match the frontier audit calendar: "
            f"missing={sorted(expected - actual)[:3]}, extra={sorted(actual - expected)[:3]}"
        )
    count_columns = [
        "raw_events",
        "graph_events",
        "matched_identities",
        "missing_from_graph",
        "graph_only",
        "graph_duplicate_identities",
        "amount_mismatches",
    ]
    counts = summary[count_columns].apply(pd.to_numeric, errors="coerce")
    if counts.isna().any().any() or (counts < 0).any().any():
        raise ValueError("V2 event-source summary contains invalid counts")
    failures = counts[
        ["missing_from_graph", "graph_only", "graph_duplicate_identities", "amount_mismatches"]
    ].sum(axis=1)
    if not summary["passed"].astype(bool).all() or int(failures.sum()) != 0:
        raise ValueError("V2 event-source summary contains failed comparisons")
    for row in summary.itertuples(index=False):
        genesis = get_source(str(row.venue)).genesis.strftime("%Y%m%d")
        expected_status = "pre_genesis" if str(row.day) < genesis else "audited"
        if str(row.launch_status) != expected_status:
            raise ValueError(
                f"V2 event-source launch status is wrong for {row.venue}/{row.day}: "
                f"{row.launch_status}"
            )
        if expected_status == "pre_genesis" and any(int(getattr(row, name)) for name in count_columns):
            raise ValueError(f"pre-genesis V2 event row is nonzero for {row.venue}/{row.day}")
    if not exceptions.empty:
        raise ValueError(f"V2 event-source certificate has {len(exceptions):,} exception rows")
    expected_hash = audit_calendar_sha256(expected_days)
    expected_certificate = {
        "schema_version": V2_EVENT_SOURCE_SCHEMA_VERSION,
        "status": "pass",
        "audit_calendar_sha256": expected_hash,
        "audit_dates": len(expected_days),
        "summary_rows": len(expected),
        "exception_rows": 0,
        "venues": list(V2_EVENT_VENUES),
        "event_types": list(V2_CORE_EVENTS),
        "pool_perimeter": V2_POOL_PERIMETER,
        "registry_source": "complete_factory_PairCreated_histories",
        "global_event_query": "topic_only_without_address_filter",
    }
    mismatched = {
        key: (certificate.get(key), value)
        for key, value in expected_certificate.items()
        if certificate.get(key) != value
    }
    if mismatched:
        raise ValueError(f"V2 event-source certificate fields are stale: {mismatched}")
    pair_counts = certificate.get("factory_pairs_by_venue")
    if not isinstance(pair_counts, dict) or set(pair_counts) != set(V2_EVENT_VENUES):
        raise ValueError("V2 event-source certificate lacks exact factory pair counts")
    if any(int(pair_counts[venue]) <= 0 for venue in V2_EVENT_VENUES):
        raise ValueError("V2 event-source certificate contains an empty factory registry")
    if int(certificate.get("factory_pairs", -1)) != sum(
        int(pair_counts[venue]) for venue in V2_EVENT_VENUES
    ):
        raise ValueError("V2 event-source certificate factory pair totals disagree")
    registry_hash = str(certificate.get("factory_registry_sha256") or "")
    if len(registry_hash) != 64:
        raise ValueError("V2 event-source certificate lacks a factory-registry digest")
    return len(expected_days), int(counts["raw_events"].sum())


def read_v2_event_source_certificate(
    summary_path: Path = V2_EVENT_SOURCE_SUMMARY,
    exceptions_path: Path = V2_EVENT_SOURCE_EXCEPTIONS,
    certificate_path: Path = V2_EVENT_SOURCE_CERTIFICATE,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    if not summary_path.is_file() or not exceptions_path.is_file() or not certificate_path.is_file():
        missing = [
            path.name
            for path in (summary_path, exceptions_path, certificate_path)
            if not path.is_file()
        ]
        raise FileNotFoundError(f"missing V2 event-source artifacts: {missing}")
    summary = pd.read_parquet(summary_path)
    exceptions = pd.read_parquet(exceptions_path)
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    if not isinstance(certificate, dict):
        raise ValueError("V2 event-source certificate is not a JSON object")
    return summary, exceptions, certificate

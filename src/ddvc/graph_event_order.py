"""Receipt/log-certified causal-order corrections for Graph event rows.

Provider captures remain immutable.  A completed correction generation binds each
changed event to its full provider identity and to independently fetched Ethereum
logs, then becomes an explicit input to canonical state normalization.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable

from eth_abi import decode as abi_decode
from eth_utils import keccak

from ddvc.amounts import human_to_raw
from ddvc.fetch.raw import write_json, write_jsonl_gz
from ddvc.source_records import block_value, transaction_id
from ddvc.v2_event_completeness import V2_EVENT_BY_TOPIC, V2_EVENT_TOPICS
from ddvc.v3_inventory import EVENT_TOPICS as V3_INVENTORY_TOPICS


SCHEMA_VERSION = 1
SUPPORTED_VENUES = frozenset({"uniswap_v2", "sushiswap_v2", "uniswap_v3"})
CORE_STREAMS = ("swaps", "mints", "burns")
V3_BURN_TOPIC = "0x" + keccak(
    text="Burn(address,int24,int24,uint128,uint256,uint256)"
).hex()
V3_STATE_EVENT_TOPICS = {
    "swap": V3_INVENTORY_TOPICS["swap"],
    "mint": V3_INVENTORY_TOPICS["mint"],
    "burn": V3_BURN_TOPIC,
}
V3_STATE_EVENT_BY_TOPIC = {topic: name for name, topic in V3_STATE_EVENT_TOPICS.items()}
STREAM_EVENT_TYPE = {"swaps": "swap", "mints": "mint", "burns": "burn"}
Fingerprint = tuple[object, ...]
CorrectionKey = tuple[str, str, str, str, int, int]


@dataclass(frozen=True)
class GraphEvent:
    stream: str
    event_id: str
    tx_hash: str
    pool: str
    block_number: int
    provider_log_index: int
    fingerprint: Fingerprint

    @property
    def match_key(self) -> tuple[str, str, str, Fingerprint]:
        return self.tx_hash, self.pool, STREAM_EVENT_TYPE[self.stream], self.fingerprint

    @property
    def correction_key(self) -> CorrectionKey:
        return (
            self.stream,
            self.event_id,
            self.tx_hash,
            self.pool,
            self.block_number,
            self.provider_log_index,
        )


@dataclass(frozen=True)
class ChainEvent:
    event_type: str
    tx_hash: str
    pool: str
    block_number: int
    log_index: int
    fingerprint: Fingerprint

    @property
    def match_key(self) -> tuple[str, str, str, Fingerprint]:
        return self.tx_hash, self.pool, self.event_type, self.fingerprint


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def correction_root_for_graph(raw_root: Path) -> Path:
    """Resolve the independent-order evidence sibling of a Graph raw root."""

    return raw_root.parent / "ethereum" / "graph_event_order"


def provider_event_paths(raw_root: Path, venue: str, day: str) -> list[Path]:
    return [raw_root / venue / f"{venue}_{stream}_{day}.jsonl.gz" for stream in CORE_STREAMS]


def v3_pool_static_path(raw_root: Path) -> Path | None:
    candidates = sorted(
        (raw_root / "uniswap_v3").glob("uniswap_v3_pool_statics_*.jsonl.gz")
    )
    if len(candidates) > 1:
        raise RuntimeError("multiple V3 pool-static generations are present")
    return candidates[0] if candidates else None


def provider_order_input_paths(raw_root: Path, venue: str, day: str) -> list[Path]:
    paths = provider_event_paths(raw_root, venue, day)
    if venue == "uniswap_v3" and (static_path := v3_pool_static_path(raw_root)) is not None:
        paths.append(static_path)
    if venue in {"uniswap_v2", "sushiswap_v2"}:
        paths.append(raw_root / venue / f"{venue}_hourly_reserves_{day}.jsonl.gz")
    return paths


def correction_paths(root: Path, venue: str, day: str) -> tuple[Path, Path]:
    directory = root / venue
    return directory / f"{day}.jsonl.gz", directory / f"{day}.meta.json"


def _raw_integer(value: object, decimals: object) -> int:
    converted = human_to_raw(value, int(decimals))
    if converted is None:
        raise ValueError(f"inexact Graph token amount: {value}/{decimals}")
    return int(converted)


def _pool_and_tokens(row: dict, venue: str) -> tuple[dict, dict, dict]:
    pool = row.get("pool") if venue == "uniswap_v3" else row.get("pair")
    if not isinstance(pool, dict):
        raise ValueError("Graph event lacks a pool object")
    token0 = pool.get("token0") or {}
    token1 = pool.get("token1") or {}
    return pool, token0, token1


def graph_fingerprint(
    row: dict,
    venue: str,
    stream: str,
    pool_decimals: dict[str, tuple[int, int]] | None = None,
) -> Fingerprint:
    """Return an exact economic event fingerprint independent of provider order."""

    pool, token0, token1 = _pool_and_tokens(row, venue)
    event_type = STREAM_EVENT_TYPE[stream]
    if venue in {"uniswap_v2", "sushiswap_v2"}:
        decimals0, decimals1 = token0.get("decimals"), token1.get("decimals")
        if decimals0 is None or decimals1 is None:
            decimals = (pool_decimals or {}).get(str(pool.get("id") or "").lower())
            if decimals is not None:
                decimals0, decimals1 = decimals
        if decimals0 is None or decimals1 is None:
            raise ValueError("V2 Graph event lacks token decimals")
        if event_type == "swap":
            return (
                event_type,
                _raw_integer(row.get("amount0In") or "0", decimals0),
                _raw_integer(row.get("amount1In") or "0", decimals1),
                _raw_integer(row.get("amount0Out") or "0", decimals0),
                _raw_integer(row.get("amount1Out") or "0", decimals1),
            )
        return (
            event_type,
            _raw_integer(row.get("amount0"), decimals0),
            _raw_integer(row.get("amount1"), decimals1),
        )
    if venue != "uniswap_v3":
        raise ValueError(f"unsupported Graph event-order venue: {venue}")
    if event_type == "swap":
        decimals0, decimals1 = token0.get("decimals"), token1.get("decimals")
        if decimals0 is None or decimals1 is None:
            decimals = (pool_decimals or {}).get(str(pool.get("id") or "").lower())
            if decimals is not None:
                decimals0, decimals1 = decimals
        if decimals0 is None or decimals1 is None:
            raise ValueError("V3 Graph swap lacks token decimals")
        return (
            event_type,
            _raw_integer(row.get("amount0"), decimals0),
            _raw_integer(row.get("amount1"), decimals1),
            int(row.get("sqrtPriceX96")),
            int(row.get("tick")),
        )
    return (
        event_type,
        int(row.get("amount")),
        int(row.get("tickLower")),
        int(row.get("tickUpper")),
    )


def graph_event(
    row: dict,
    venue: str,
    stream: str,
    pool_decimals: dict[str, tuple[int, int]] | None = None,
) -> GraphEvent:
    pool, _token0, _token1 = _pool_and_tokens(row, venue)
    block = block_value(row)
    tx_hash = transaction_id(row)
    event_id = str(row.get("id") or "")
    pool_id = str(pool.get("id") or "").lower()
    try:
        provider_log_index = int(row.get("logIndex"))
    except (TypeError, ValueError) as error:
        raise ValueError("Graph event lacks a valid provider log index") from error
    if block is None or block < 1 or provider_log_index < 0:
        raise ValueError("Graph event lacks a valid block-log order")
    if not event_id or not tx_hash or not pool_id:
        raise ValueError("Graph event lacks exact event, transaction, or pool identity")
    return GraphEvent(
        stream=stream,
        event_id=event_id,
        tx_hash=str(tx_hash).lower(),
        pool=pool_id,
        block_number=int(block),
        provider_log_index=provider_log_index,
        fingerprint=graph_fingerprint(row, venue, stream, pool_decimals),
    )


def load_v3_pool_decimals(raw_root: Path) -> dict[str, tuple[int, int]]:
    path = v3_pool_static_path(raw_root)
    if path is None:
        return {}
    decimals: dict[str, tuple[int, int]] = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            pool = str(row.get("id") or "").lower()
            token0, token1 = row.get("token0") or {}, row.get("token1") or {}
            value = int(token0.get("decimals")), int(token1.get("decimals"))
            prior = decimals.get(pool)
            if prior is not None and prior != value:
                raise ValueError(f"conflicting V3 pool-static decimals: {pool}")
            decimals[pool] = value
    return decimals


def load_v2_pool_decimals(
    raw_root: Path,
    venue: str,
    day: str,
) -> dict[str, tuple[int, int]]:
    path = raw_root / venue / f"{venue}_hourly_reserves_{day}.jsonl.gz"
    if not path.is_file():
        raise FileNotFoundError(path)
    decimals: dict[str, tuple[int, int]] = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            pair = row.get("pair") or {}
            pool = str(pair.get("id") or "").lower()
            token0, token1 = pair.get("token0") or {}, pair.get("token1") or {}
            if token0.get("decimals") is None or token1.get("decimals") is None:
                continue
            value = int(token0["decimals"]), int(token1["decimals"])
            prior = decimals.get(pool)
            if prior is not None and prior != value:
                raise ValueError(f"conflicting V2 pool-snapshot decimals: {venue}/{pool}")
            decimals[pool] = value
    return decimals


def load_graph_events(raw_root: Path, venue: str, day: str) -> list[GraphEvent]:
    if venue not in SUPPORTED_VENUES:
        raise ValueError(f"unsupported Graph event-order venue: {venue}")
    events: list[GraphEvent] = []
    ids: set[tuple[str, str]] = set()
    pool_decimals = (
        load_v3_pool_decimals(raw_root)
        if venue == "uniswap_v3"
        else load_v2_pool_decimals(raw_root, venue, day)
    )
    for stream, path in zip(CORE_STREAMS, provider_event_paths(raw_root, venue, day), strict=True):
        if not path.is_file():
            raise FileNotFoundError(path)
        with gzip.open(path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = graph_event(json.loads(line), venue, stream, pool_decimals)
                identity = stream, event.event_id
                if identity in ids:
                    raise ValueError(f"duplicate Graph event entity: {identity}")
                ids.add(identity)
                events.append(event)
    if not events:
        raise RuntimeError(f"Graph event-order audit has no events for {venue}/{day}")
    return events


def _topic_int24(topic: str) -> int:
    return int(abi_decode(["int24"], bytes.fromhex(topic.removeprefix("0x")))[0])


def chain_event(record: dict[str, object], venue: str) -> ChainEvent:
    topics = [str(value).lower() for value in record.get("topics") or []]
    if not topics:
        raise ValueError("exact Ethereum event lacks topics")
    data = bytes.fromhex(str(record.get("data") or "0x").removeprefix("0x"))
    if venue in {"uniswap_v2", "sushiswap_v2"}:
        event_type = V2_EVENT_BY_TOPIC.get(topics[0])
        if event_type == "swap":
            values = tuple(int(value) for value in abi_decode(["uint256"] * 4, data))
            fingerprint = (event_type, *values)
        elif event_type in {"mint", "burn"}:
            values = tuple(int(value) for value in abi_decode(["uint256"] * 2, data))
            fingerprint = (event_type, *values)
        else:
            raise ValueError("exact Ethereum event has an unregistered V2 topic")
    elif venue == "uniswap_v3":
        event_type = V3_STATE_EVENT_BY_TOPIC.get(topics[0])
        if event_type == "swap":
            amount0, amount1, sqrt_price, _liquidity, tick = abi_decode(
                ["int256", "int256", "uint160", "uint128", "int24"], data
            )
            fingerprint = (
                event_type,
                int(amount0),
                int(amount1),
                int(sqrt_price),
                int(tick),
            )
        elif event_type == "mint":
            _sender, amount, _amount0, _amount1 = abi_decode(
                ["address", "uint128", "uint256", "uint256"], data
            )
            fingerprint = (
                event_type,
                int(amount),
                _topic_int24(topics[2]),
                _topic_int24(topics[3]),
            )
        elif event_type == "burn":
            amount, _amount0, _amount1 = abi_decode(
                ["uint128", "uint256", "uint256"], data
            )
            fingerprint = (
                event_type,
                int(amount),
                _topic_int24(topics[2]),
                _topic_int24(topics[3]),
            )
        else:
            raise ValueError("exact Ethereum event has an unregistered V3 topic")
    else:
        raise ValueError(f"unsupported exact event-order venue: {venue}")
    return ChainEvent(
        event_type=event_type,
        tx_hash=str(record["transaction_hash"]).lower(),
        pool=str(record["address"]).lower(),
        block_number=int(record["block_number"]),
        log_index=int(record["log_index"]),
        fingerprint=fingerprint,
    )


def event_topics(venue: str) -> list[str]:
    if venue in {"uniswap_v2", "sushiswap_v2"}:
        return [V2_EVENT_TOPICS[name] for name in sorted(V2_EVENT_TOPICS)]
    if venue == "uniswap_v3":
        return [V3_STATE_EVENT_TOPICS[name] for name in sorted(V3_STATE_EVENT_TOPICS)]
    raise ValueError(f"unsupported Graph event-order venue: {venue}")


def match_event_orders(
    graph_events: Iterable[GraphEvent],
    exact_records: Iterable[dict[str, object]],
    venue: str,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Match a complete Graph-observed block span and emit only changed orders."""

    graph = list(graph_events)
    pools = {event.pool for event in graph}
    exact = [
        chain_event(record, venue)
        for record in exact_records
        if str(record.get("address") or "").lower() in pools
    ]
    graph_groups: dict[tuple[str, str, str, Fingerprint], list[GraphEvent]] = defaultdict(list)
    exact_groups: dict[tuple[str, str, str, Fingerprint], list[ChainEvent]] = defaultdict(list)
    for event in graph:
        graph_groups[event.match_key].append(event)
    for event in exact:
        exact_groups[event.match_key].append(event)
    mismatched_groups = {
        key
        for key in set(graph_groups) | set(exact_groups)
        if len(graph_groups.get(key, [])) != len(exact_groups.get(key, []))
    }
    if mismatched_groups:
        graph_only = sum(len(graph_groups.get(key, [])) for key in mismatched_groups)
        exact_only = sum(len(exact_groups.get(key, [])) for key in mismatched_groups)
        raise RuntimeError(
            "exact event-order reconciliation has unmatched economic groups: "
            f"groups={len(mismatched_groups):,}; graph_rows={graph_only:,}; "
            f"exact_rows={exact_only:,}"
        )
    corrections: list[dict[str, object]] = []
    for key in sorted(graph_groups, key=str):
        provider_group = sorted(graph_groups[key], key=lambda event: event.event_id)
        chain_group = sorted(exact_groups[key], key=lambda event: event.log_index)
        for provider, chain in zip(provider_group, chain_group, strict=True):
            if provider.block_number != chain.block_number:
                raise ValueError(
                    f"Graph and chain blocks disagree for {provider.stream}/{provider.event_id}"
                )
            if provider.provider_log_index == chain.log_index:
                continue
            fingerprint_hash = hashlib.sha256(
                json.dumps(provider.fingerprint, separators=(",", ":")).encode()
            ).hexdigest()
            corrections.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "venue": venue,
                    "stream": provider.stream,
                    "event_id": provider.event_id,
                    "tx_hash": provider.tx_hash,
                    "pool": provider.pool,
                    "block_number": provider.block_number,
                    "provider_log_index": provider.provider_log_index,
                    "chain_log_index": chain.log_index,
                    "event_fingerprint_sha256": fingerprint_hash,
                }
            )
    return corrections, {
        "graph_events": len(graph),
        "exact_events_in_graph_pool_perimeter": len(exact),
        "matched_events": len(graph),
        "correction_rows": len(corrections),
        "unmatched_graph_events": 0,
        "unmatched_exact_events": 0,
    }


class EventOrderCorrections:
    """Validated one-use correction registry for one venue-day partition."""

    def __init__(self, rows: Iterable[dict[str, object]]) -> None:
        self._rows: dict[CorrectionKey, int] = {}
        self._used: set[CorrectionKey] = set()
        for row in rows:
            key = (
                str(row["stream"]),
                str(row["event_id"]),
                str(row["tx_hash"]).lower(),
                str(row["pool"]).lower(),
                int(row["block_number"]),
                int(row["provider_log_index"]),
            )
            if key in self._rows:
                raise ValueError(f"duplicate event-order correction: {key}")
            chain_log_index = int(row["chain_log_index"])
            if chain_log_index < 0 or chain_log_index == key[-1]:
                raise ValueError(f"invalid event-order correction: {key}")
            self._rows[key] = chain_log_index

    def resolve(self, venue: str, stream: str, row: dict) -> int | None:
        if not self._rows:
            return None
        pool, _token0, _token1 = _pool_and_tokens(row, venue)
        block = block_value(row)
        try:
            provider_log = int(row.get("logIndex"))
        except (TypeError, ValueError):
            return None
        key = (
            stream,
            str(row.get("id") or ""),
            str(transaction_id(row) or "").lower(),
            str(pool.get("id") or "").lower(),
            int(block or 0),
            provider_log,
        )
        corrected = self._rows.get(key)
        if corrected is not None:
            self._used.add(key)
        return corrected

    def require_fully_applied(self) -> None:
        unused = set(self._rows) - self._used
        if unused:
            raise ValueError(
                f"event-order generation contains {len(unused):,} stale or unapplied corrections"
            )


def write_correction_generation(
    *,
    root: Path,
    raw_root: Path,
    venue: str,
    day: str,
    corrections: list[dict[str, object]],
    exact_log_paths: list[Path],
    audit: dict[str, int],
    start_block: int,
    end_block: int,
) -> tuple[Path, Path]:
    data_path, meta_path = correction_paths(root, venue, day)
    ordered = sorted(
        ({**row, "day": day} for row in corrections),
        key=lambda row: (
            int(row["block_number"]),
            int(row["chain_log_index"]),
            str(row["stream"]),
            str(row["event_id"]),
        ),
    )
    write_jsonl_gz(data_path, ordered)
    provider_paths = provider_order_input_paths(raw_root, venue, day)
    metadata = {
        "status": "complete",
        "schema_version": SCHEMA_VERSION,
        "venue": venue,
        "day": day,
        "scope": "complete_graph_observed_block_span",
        "start_block": start_block,
        "end_block": end_block,
        "event_topics": event_topics(venue),
        "provider_inputs_sha256": {
            path.name: file_sha256(path) for path in provider_paths
        },
        "exact_log_inputs_sha256": {
            str(path.relative_to(root)): file_sha256(path) for path in exact_log_paths
        },
        "corrections_sha256": file_sha256(data_path),
        **audit,
    }
    write_json(meta_path, metadata)
    return data_path, meta_path


def load_event_order_corrections(
    raw_root: Path,
    venue: str,
    day: str,
) -> tuple[EventOrderCorrections | None, list[Path]]:
    root = correction_root_for_graph(raw_root)
    data_path, meta_path = correction_paths(root, venue, day)
    if not data_path.exists() and not meta_path.exists():
        return None, []
    if not data_path.is_file() or not meta_path.is_file():
        raise RuntimeError(f"partial event-order generation for {venue}/{day}")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if (
        metadata.get("status") != "complete"
        or metadata.get("schema_version") != SCHEMA_VERSION
        or metadata.get("venue") != venue
        or metadata.get("day") != day
        or int(metadata.get("unmatched_graph_events", -1)) != 0
        or int(metadata.get("unmatched_exact_events", -1)) != 0
    ):
        raise ValueError(f"invalid event-order generation metadata for {venue}/{day}")
    current_provider = {
        path.name: file_sha256(path) for path in provider_order_input_paths(raw_root, venue, day)
    }
    if metadata.get("provider_inputs_sha256") != current_provider:
        raise ValueError(f"stale event-order generation against Graph inputs: {venue}/{day}")
    if metadata.get("corrections_sha256") != file_sha256(data_path):
        raise ValueError(f"corrupted event-order correction data: {venue}/{day}")
    exact_paths = [root / relative for relative in metadata.get("exact_log_inputs_sha256", {})]
    expected_exact = metadata.get("exact_log_inputs_sha256") or {}
    observed_exact = {
        str(path.relative_to(root)): file_sha256(path)
        for path in exact_paths
        if path.is_file()
    }
    if observed_exact != expected_exact:
        raise ValueError(f"missing or stale exact event-order evidence: {venue}/{day}")
    rows: list[dict[str, object]] = []
    with gzip.open(data_path, "rt") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if (
                    row.get("schema_version") != SCHEMA_VERSION
                    or row.get("venue") != venue
                    or row.get("day") != day
                ):
                    raise ValueError(f"wrong event-order correction schema for {venue}/{day}")
                rows.append(row)
    if len(rows) != int(metadata.get("correction_rows", -1)):
        raise ValueError(f"event-order correction row count differs for {venue}/{day}")
    return EventOrderCorrections(rows), [data_path, meta_path, *exact_paths]

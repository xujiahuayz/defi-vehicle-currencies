"""Exact concentrated-liquidity initialization and V4 state-event evidence.

V3 Initialize remains separate from the completed V3 inventory-event release. V4 state comes from the full PoolManager census; provider V4 event rows are not load-bearing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from eth_abi import decode as abi_decode, encode as abi_encode
from eth_utils import keccak
import pyarrow.parquet as pq

from ddvc.amounts import raw_to_human
from ddvc.ethereum_day_cuts import validate_utc_day_block_bounds
from ddvc.ethereum_logs import (
    RAW_LOG_SCHEMA,
    block_ranges,
    file_sha256,
    validate_anchored_log_evidence,
    validate_canonical_log_records,
    write_exact_log_chunk,
)
from ddvc.fetch.raw import write_json, write_jsonl_gz
from ddvc.paths import TICK_STATE_EVENT_RAW_ROOT
from ddvc.provenance import portable_content_manifest_for_paths, portable_manifest_sha256
from ddvc.runtime import atomic_output
from ddvc.source_records import ZERO_ADDRESS, v4_static_quote_status
from ddvc.v3_pool_registry import V3FactoryPool
from ddvc.v4_contract import (
    UNISWAP_V4_INITIALIZE_TOPIC,
    UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC,
    UNISWAP_V4_POOL_MANAGER_ADDRESS,
    UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK,
    UNISWAP_V4_SWAP_TOPIC,
    decode_v4_state_event_identity,
)


STATE_EVENT_SCHEMA_VERSION = 1
V3_STATE_EVENT_GENERATION = "exact_v3_initialize_with_inventory_precedence_v1"
V4_STATE_EVENT_GENERATION = "exact_v4_poolmanager_state_event_census_v1"
DERIVED_INITIALIZATION_GENERATION = "certified_daily_tick_initializations_v1"
DERIVED_V4_STATE_GENERATION = "certified_daily_v4_exact_state_events_v1"
DAILY_RELEASE_SET_SCHEMA_VERSION = 2
DAILY_INITIALIZATION_RELEASE_GENERATION = "certified_daily_tick_initialization_set_v1"
DAILY_V4_STATE_RELEASE_GENERATION = "certified_daily_v4_exact_state_event_set_v1"
V4_PREFIX_GAP_REASON = "outside_contiguous_exact_prefix"
V4_EXACT_STATE_CHUNK_SIZE = 10_000
V3_INITIALIZE_SIGNATURE = "Initialize(uint160,int24)"
V3_INITIALIZE_TOPIC = "0x" + keccak(text=V3_INITIALIZE_SIGNATURE).hex()
V4_INITIALIZE_TOPIC = UNISWAP_V4_INITIALIZE_TOPIC
VENUE_TOPICS = {
    "uniswap_v3": V3_INITIALIZE_TOPIC,
    "uniswap_v4": V4_INITIALIZE_TOPIC,
}
VENUE_GENERATION_TOPICS = {
    "uniswap_v3": (V3_INITIALIZE_TOPIC,),
    "uniswap_v4": (
        V4_INITIALIZE_TOPIC,
        UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC,
        UNISWAP_V4_SWAP_TOPIC,
    ),
}


def state_event_generation(venue: str) -> str:
    return V3_STATE_EVENT_GENERATION if venue == "uniswap_v3" else V4_STATE_EVENT_GENERATION


@dataclass(frozen=True)
class TickInitialization:
    venue: str
    pool: str
    token0: str
    token1: str
    fee_pips: int
    tick_spacing: int
    hooks: str
    sqrt_price_x96: int
    tick: int
    block_number: int
    block_hash: str
    transaction_hash: str
    transaction_index: int
    log_index: int
    quote_supported: bool
    quote_unsupported_reason: str | None

    @property
    def order(self) -> tuple[int, int]:
        return self.block_number, self.log_index


def _address_topic(topic: object) -> str:
    value = str(topic or "").lower()
    if len(value) != 66 or not value.startswith("0x") or value[2:26] != "0" * 24:
        raise ValueError("Initialize address topic is not canonically ABI-padded")
    return "0x" + value[-40:]


def _event_identity(record: Mapping[str, object]) -> dict[str, object]:
    return {
        "block_number": int(record["block_number"]),
        "block_hash": str(record["block_hash"]).lower(),
        "transaction_hash": str(record["transaction_hash"]).lower(),
        "transaction_index": int(record["transaction_index"]),
        "log_index": int(record["log_index"]),
    }


def decode_v3_initialize(
    record: Mapping[str, object],
    registry: Mapping[str, V3FactoryPool],
) -> TickInitialization:
    """Decode one V3 pool Initialize and require certified factory identity."""

    topics = [str(value).lower() for value in record.get("topics") or []]
    pool = str(record.get("address") or "").lower()
    if topics != [V3_INITIALIZE_TOPIC]:
        raise ValueError("Uniswap V3 Initialize has the wrong topic shape")
    static = registry.get(pool)
    if static is None:
        raise ValueError("Uniswap V3 Initialize pool is outside the certified factory registry")
    data = bytes.fromhex(str(record.get("data") or "0x").removeprefix("0x"))
    if len(data) != 64:
        raise ValueError("Uniswap V3 Initialize has the wrong ABI data length")
    sqrt_price_x96, tick = abi_decode(["uint160", "int24"], data)
    if int(sqrt_price_x96) <= 0 or not -887_272 <= int(tick) <= 887_272:
        raise ValueError("Uniswap V3 Initialize contains an invalid price or tick")
    event_order = (int(record["block_number"]), int(record["log_index"]))
    creation_order = (static.creation_block, static.creation_log_index)
    if event_order <= creation_order:
        raise ValueError("Uniswap V3 Initialize does not follow certified pool creation")
    return TickInitialization(
        venue="uniswap_v3",
        pool=pool,
        token0=static.token0,
        token1=static.token1,
        fee_pips=static.fee,
        tick_spacing=static.tick_spacing,
        hooks=ZERO_ADDRESS,
        sqrt_price_x96=int(sqrt_price_x96),
        tick=int(tick),
        quote_supported=True,
        quote_unsupported_reason=None,
        **_event_identity(record),
    )


def v4_pool_id(
    token0: str,
    token1: str,
    fee_pips: int,
    tick_spacing: int,
    hooks: str,
) -> str:
    """Return the canonical V4 PoolId, keccak256(abi.encode(PoolKey))."""

    encoded = abi_encode(
        ["address", "address", "uint24", "int24", "address"],
        [token0, token1, fee_pips, tick_spacing, hooks],
    )
    return "0x" + keccak(encoded).hex()


def decode_v4_initialize(record: Mapping[str, object]) -> TickInitialization:
    """Decode one canonical PoolManager Initialize, retaining unsupported statics."""

    topics = [str(value).lower() for value in record.get("topics") or []]
    if (
        str(record.get("address") or "").lower() != UNISWAP_V4_POOL_MANAGER_ADDRESS
        or len(topics) != 4
        or topics[0] != V4_INITIALIZE_TOPIC
    ):
        raise ValueError("Uniswap V4 Initialize has the wrong PoolManager or topic shape")
    pool, token0, token1 = topics[1], _address_topic(topics[2]), _address_topic(topics[3])
    data = bytes.fromhex(str(record.get("data") or "0x").removeprefix("0x"))
    if len(data) != 160:
        raise ValueError("Uniswap V4 Initialize has the wrong ABI data length")
    fee_pips, tick_spacing, hooks, sqrt_price_x96, tick = abi_decode(
        ["uint24", "int24", "address", "uint160", "int24"], data
    )
    fee_pips, tick_spacing, hooks = int(fee_pips), int(tick_spacing), str(hooks).lower()
    if token0 >= token1:
        raise ValueError("Uniswap V4 Initialize currency order is noncanonical")
    if pool != v4_pool_id(token0, token1, fee_pips, tick_spacing, hooks):
        raise ValueError("Uniswap V4 Initialize PoolId disagrees with its PoolKey")
    status = v4_static_quote_status(fee_pips, tick_spacing, hooks)
    if (
        int(sqrt_price_x96) <= 0
        or not -887_272 <= int(tick) <= 887_272
        or status == "invalid_statics"
    ):
        raise ValueError("Uniswap V4 Initialize contains an invalid price or tick spacing")
    unsupported = None if status == "vanilla_static_fee" else status
    return TickInitialization(
        venue="uniswap_v4",
        pool=pool,
        token0=token0,
        token1=token1,
        fee_pips=fee_pips,
        tick_spacing=tick_spacing,
        hooks=hooks,
        sqrt_price_x96=int(sqrt_price_x96),
        tick=int(tick),
        quote_supported=unsupported is None,
        quote_unsupported_reason=unsupported,
        **_event_identity(record),
    )


def decode_initializations(
    venue: str,
    records: Iterable[Mapping[str, object]],
    *,
    v3_registry: Mapping[str, V3FactoryPool] | None = None,
) -> list[TickInitialization]:
    """Decode, globally order and certify one-event-per-pool initialization identity."""

    if venue not in VENUE_TOPICS:
        raise ValueError(f"unsupported initialization venue: {venue}")
    if venue == "uniswap_v3" and v3_registry is None:
        raise ValueError("V3 Initialize decoding requires the certified factory registry")
    decoder = (
        (lambda row: decode_v3_initialize(row, v3_registry or {}))
        if venue == "uniswap_v3"
        else decode_v4_initialize
    )
    decoded = sorted((decoder(row) for row in records), key=lambda row: row.order)
    pools: set[str] = set()
    orders: set[tuple[int, int]] = set()
    for row in decoded:
        if row.pool in pools:
            raise ValueError(f"pool has more than one Initialize event: {row.pool}")
        if row.order in orders:
            raise ValueError(f"two Initialize events claim block-log order {row.order}")
        pools.add(row.pool)
        orders.add(row.order)
    return decoded


def state_event_chunk_paths(
    venue: str,
    lower: int,
    upper: int,
    *,
    root: Path = TICK_STATE_EVENT_RAW_ROOT,
) -> tuple[Path, Path, Path]:
    directory = root / "chunks" / venue
    stem = f"blocks_{lower:08d}_{upper:08d}"
    return directory / f"{stem}.parquet", directory / f"{stem}.rpc.json.gz", directory / f"{stem}.meta.json"


def initialization_day_path(raw_root: Path, venue: str, day: str) -> Path:
    """Derived exact daily replay path adjacent to, never inside, provider evidence."""

    return raw_root.parent / "ethereum" / "tick_initializations" / "daily" / venue / f"{day}.jsonl.gz"


def daily_release_set_path(raw_root: Path, venue: str, *, kind: str) -> Path:
    if kind == "initializations":
        directory = initialization_day_path(raw_root, venue, "day").parent
    elif kind == "v4_state" and venue == "uniswap_v4":
        directory = v4_state_day_path(raw_root, "day").parent
    else:
        raise ValueError(f"unsupported tick-state daily release kind: {kind}/{venue}")
    return directory / "release.complete.json"


def state_event_certificate_path(raw_root: Path, venue: str) -> Path:
    return raw_root.parent / "ethereum" / "tick_state_events" / "certificates" / f"{venue}.json"


def state_event_certificate_identity(venue: str) -> str:
    return f"certificates/{venue}.json"


def v4_state_day_path(raw_root: Path, day: str) -> Path:
    return raw_root.parent / "ethereum" / "tick_state_events" / "daily" / "uniswap_v4" / f"{day}.jsonl.gz"


def v4_state_day_inputs(raw_root: Path, day: str) -> tuple[Path, Path, Path]:
    data = v4_state_day_path(raw_root, day)
    return data, data.with_suffix(".meta.json"), state_event_certificate_path(raw_root, "uniswap_v4")


def initialization_day_inputs(raw_root: Path, venue: str, day: str) -> tuple[Path, Path, Path]:
    data = initialization_day_path(raw_root, venue, day)
    return data, data.with_suffix(".meta.json"), state_event_certificate_path(raw_root, venue)


def write_state_event_chunk(
    venue: str,
    lower: int,
    upper: int,
    records: list[dict[str, object]],
    evidence: list[dict[str, object]],
    *,
    frozen_upper: Mapping[str, object],
    root: Path = TICK_STATE_EVENT_RAW_ROOT,
) -> None:
    """Publish one exact RPC evidence triplet, with its marker installed last."""

    raw_path, evidence_path, marker_path = state_event_chunk_paths(venue, lower, upper, root=root)
    address = UNISWAP_V4_POOL_MANAGER_ADDRESS if venue == "uniswap_v4" else None
    generation_topics = list(VENUE_GENERATION_TOPICS[venue])
    validate_canonical_log_records(records, start_block=lower, end_block=upper, topics=generation_topics, address=address)
    anchored: list[dict[str, object]] = []
    expected_lower = lower
    for item in evidence:
        sub_lower, sub_upper = int(item["start_block"]), int(item["end_block"])
        if sub_lower != expected_lower or sub_upper < sub_lower or sub_upper > upper:
            raise ValueError("state-event RPC evidence subranges are gapped or overlapping")
        subrange = {
            "start_block": sub_lower,
            "end_block": sub_upper,
            "event_topics": generation_topics,
            "address_filter": address,
            "rpc_request": item["request"],
            "rpc_response": item["response"],
            "rpc_endpoint": item["endpoint"],
            "rpc_attempts": item["attempts"],
            "response_sha256": item["response_sha256"],
            "frozen_upper_request": item["frozen_upper_request"],
            "frozen_upper_response": item["frozen_upper_response"],
            "frozen_upper_response_sha256": item["frozen_upper_response_sha256"],
        }
        validate_anchored_log_evidence(
            subrange,
            [row for row in records if sub_lower <= int(row["block_number"]) <= sub_upper],
            dict(frozen_upper),
        )
        anchored.append(subrange)
        expected_lower = sub_upper + 1
    if expected_lower != upper + 1:
        raise ValueError("state-event RPC evidence does not close its chunk perimeter")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(evidence_path) as temporary:
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            json.dump(anchored, handle, allow_nan=False, sort_keys=True)
    write_exact_log_chunk(raw_path, marker_path, records, {
        "generation": state_event_generation(venue),
        "schema_version": STATE_EVENT_SCHEMA_VERSION,
        "venue": venue,
        "start_block": lower,
        "end_block": upper,
        "event_topics": generation_topics,
        "address_filter": address,
        "rpc_evidence_file": evidence_path.name,
        "rpc_evidence_sha256": file_sha256(evidence_path),
        "frozen_upper_identity_sha256": frozen_upper["header_identity_sha256"],
    })


def load_state_event_chunk(
    venue: str,
    lower: int,
    upper: int,
    *,
    frozen_upper: Mapping[str, object],
    root: Path = TICK_STATE_EVENT_RAW_ROOT,
) -> list[dict[str, object]]:
    """Reopen one raw/evidence/marker triplet and revalidate its exact RPC identity."""

    raw_path, evidence_path, marker_path = state_event_chunk_paths(venue, lower, upper, root=root)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    with gzip.open(evidence_path, "rt", encoding="utf-8") as handle:
        evidence = json.load(handle)
    table = pq.read_table(raw_path)
    if table.schema != RAW_LOG_SCHEMA:
        raise ValueError("state-event raw chunk schema drifted")
    records = table.to_pylist()
    address = UNISWAP_V4_POOL_MANAGER_ADDRESS if venue == "uniswap_v4" else None
    generation_topics = list(VENUE_GENERATION_TOPICS[venue])
    validate_canonical_log_records(records, start_block=lower, end_block=upper, topics=generation_topics, address=address)
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("state-event chunk lacks RPC evidence subranges")
    expected_lower = lower
    for subrange in evidence:
        sub_lower, sub_upper = int(subrange["start_block"]), int(subrange["end_block"])
        if sub_lower != expected_lower or sub_upper < sub_lower or sub_upper > upper:
            raise ValueError("state-event chunk RPC evidence perimeter drifted")
        validate_anchored_log_evidence(
            subrange,
            [row for row in records if sub_lower <= int(row["block_number"]) <= sub_upper],
            dict(frozen_upper),
        )
        expected_lower = sub_upper + 1
    if expected_lower != upper + 1:
        raise ValueError("state-event chunk RPC evidence does not close its perimeter")
    if (
        marker.get("status") != "complete"
        or marker.get("generation") != state_event_generation(venue)
        or int(marker.get("schema_version", -1)) != STATE_EVENT_SCHEMA_VERSION
        or marker.get("venue") != venue
        or marker.get("event_topics") != generation_topics
        or int(marker.get("start_block", -1)) != lower
        or int(marker.get("end_block", -1)) != upper
        or int(marker.get("raw_logs", -1)) != len(records)
        or marker.get("raw_sha256") != file_sha256(raw_path)
        or marker.get("rpc_evidence_sha256") != file_sha256(evidence_path)
        or marker.get("frozen_upper_identity_sha256") != frozen_upper.get("header_identity_sha256")
    ):
        raise ValueError("state-event chunk marker is stale or incomplete")
    return records


def semantic_sha256(rows: Iterable[TickInitialization]) -> str:
    payload = [asdict(row) for row in rows]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def scientific_support_calendar(days: Iterable[str], support_end_day: str) -> list[dict[str, object]]:
    """Normalize one monotone day calendar whose scientific support closes once."""

    normalized_days = [str(day).replace("-", "") for day in days]
    normalized_end = str(support_end_day).replace("-", "")
    if not normalized_days or normalized_days != sorted(normalized_days) or len(normalized_days) != len(set(normalized_days)) or normalized_end not in normalized_days:
        raise ValueError("scientific-support calendar must be sorted, unique, and contain its support end")
    return [{"day": day, "scientific_support": day <= normalized_end} for day in normalized_days]


def scientific_support_calendar_sha256(days: Iterable[str], support_end_day: str) -> str:
    return hashlib.sha256(json.dumps(scientific_support_calendar(days, support_end_day), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def exact_v4_prefix_gap_ledger(
    certified_ranges: Iterable[tuple[int, int]],
    requested_ranges: Iterable[tuple[int, int]],
    *,
    frozen_upper_block: int,
    canonical_start_block: int = UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK,
) -> list[dict[str, object]]:
    """Derive the exact requested suffix excluded after a contiguous V4 prefix."""

    certified = [(int(lower), int(upper)) for lower, upper in certified_ranges]
    requested = [(int(lower), int(upper)) for lower, upper in requested_ranges]
    if frozen_upper_block < 0:
        raise ValueError("V4 frozen upper block is invalid")
    for label, ranges in (("certified", certified), ("requested", requested)):
        if not ranges or ranges != sorted(ranges) or any(lower < 0 or upper < lower or upper > frozen_upper_block or (index and lower != ranges[index - 1][1] + 1) for index, (lower, upper) in enumerate(ranges)):
            raise ValueError(f"V4 {label} range perimeter is empty, noncanonical, or outside the frozen upper block")
    if requested[0][0] != canonical_start_block or requested[-1][1] != frozen_upper_block:
        raise ValueError("V4 requested range perimeter does not span deployment through the frozen upper block")
    canonical = block_ranges(canonical_start_block, frozen_upper_block, V4_EXACT_STATE_CHUNK_SIZE)
    if requested != canonical:
        raise ValueError("V4 requested range perimeter is not the canonical aligned chunk partition")
    if len(certified) > len(requested) or certified != requested[: len(certified)]:
        raise ValueError("V4 certified ranges are not an exact prefix of the requested perimeter")
    return [{"lower": lower, "upper": upper, "reason": V4_PREFIX_GAP_REASON} for lower, upper in requested[len(certified) :]]


def validate_v4_prefix_certificate(certificate: Mapping[str, object]) -> None:
    """Recompute the exact V4 certified-prefix and excluded-suffix identities."""

    raw_requested = certificate.get("requested_ranges")
    if not isinstance(raw_requested, list) or any(not isinstance(item, list) or len(item) != 2 for item in raw_requested):
        raise ValueError("V4 exact-prefix certificate lacks its requested range perimeter")
    requested = [(int(item[0]), int(item[1])) for item in raw_requested]
    chunk_count = int(certificate.get("chunk_count", -1))
    if chunk_count < 1 or chunk_count > len(requested):
        raise ValueError("V4 exact-prefix certificate has an invalid certified chunk count")
    certified = requested[:chunk_count]
    expected_gaps = exact_v4_prefix_gap_ledger(certified, requested, frozen_upper_block=int(certificate.get("frozen_upper_block", -1)))
    if int(certificate.get("canonical_start_block", -1)) != UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK or int(certificate.get("start_block", -1)) != certified[0][0] or int(certificate.get("end_block", -1)) != certified[-1][1] or certificate.get("exact_state_gap_ledger") != expected_gaps or certificate.get("exact_state_gap_ledger_sha256") != hashlib.sha256(json.dumps(expected_gaps, sort_keys=True, separators=(",", ":")).encode()).hexdigest() or int(certificate.get("requested_range_count", -1)) != len(requested) or certificate.get("requested_range_manifest_sha256") != hashlib.sha256(json.dumps(requested, separators=(",", ":")).encode()).hexdigest() or not certified[0][0] <= int(certificate.get("support_end_block", -1)) <= certified[-1][1]:
        raise ValueError("V4 exact-prefix certificate disagrees with its requested suffix perimeter")


def certify_state_event_generation(
    venue: str,
    ranges: Iterable[tuple[int, int]],
    *,
    frozen_upper: Mapping[str, object],
    raw_root: Path,
    support_end_block: int | None = None,
    requested_ranges: Iterable[tuple[int, int]] | None = None,
) -> tuple[list[TickInitialization] | list[dict[str, object]], dict[str, object]]:
    """Reopen a contiguous chunk perimeter and certify its ordered semantic release."""

    ordered_ranges = [(int(lower), int(upper)) for lower, upper in ranges]
    if not ordered_ranges or ordered_ranges != sorted(ordered_ranges) or any(
        upper < lower or (index and lower != ordered_ranges[index - 1][1] + 1)
        for index, (lower, upper) in enumerate(ordered_ranges)
    ):
        raise ValueError("state-event chunk perimeter is empty, gapped, or overlapping")
    if support_end_block is not None and venue != "uniswap_v4":
        raise ValueError("an exact-state support cut is only defined for Uniswap V4")
    if support_end_block is not None and not ordered_ranges[0][0] <= support_end_block <= ordered_ranges[-1][1]:
        raise ValueError("V4 support end block lies outside the certified chunk perimeter")
    requested_perimeter = ordered_ranges if requested_ranges is None else [(int(lower), int(upper)) for lower, upper in requested_ranges]
    normalized_gaps = exact_v4_prefix_gap_ledger(ordered_ranges, requested_perimeter, frozen_upper_block=int(frozen_upper["block_number"])) if venue == "uniswap_v4" else []
    paths: list[Path] = []
    decoded: list[TickInitialization] = []
    v3_initialization_evidence: list[dict[str, object]] = []
    initialized_by_pool: dict[str, TickInitialization] = {}
    missing: set[str] = set()
    nonpreceding: set[str] = set()
    raw_log_count = 0
    exact_modify_count = 0
    exact_swap_count = 0
    excluded_tail: list[dict[str, object]] = []
    last_order: tuple[int, int] | None = None
    for lower, upper in ordered_ranges:
        records = load_state_event_chunk(venue, lower, upper, frozen_upper=frozen_upper, root=raw_root)
        paths.extend(state_event_chunk_paths(venue, lower, upper, root=raw_root))
        for row in records:
            raw_log_count += 1
            order = (int(row["block_number"]), int(row["log_index"]))
            if last_order is not None and order <= last_order:
                raise ValueError("state-event chunks are not globally strictly ordered")
            last_order = order
            topic = str((row.get("topics") or [""])[0]).lower()
            if support_end_block is not None and order[0] > support_end_block:
                excluded_tail.append(
                    {
                        "address": str(row["address"]).lower(),
                        "block_number": order[0],
                        "block_hash": str(row["block_hash"]).lower(),
                        "transaction_hash": str(row["transaction_hash"]).lower(),
                        "transaction_index": int(row["transaction_index"]),
                        "log_index": order[1],
                        "topic0": topic,
                    }
                )
                continue
            if venue == "uniswap_v3":
                evidence = {
                    "address": str(row["address"]).lower(),
                    "data": str(row["data"]).lower(),
                    "topics": [str(value).lower() for value in row.get("topics") or []],
                    **_event_identity(row),
                }
                v3_initialization_evidence.append(evidence)
                continue
            if topic == V4_INITIALIZE_TOPIC:
                initialization = decode_v4_initialize(row)
                if initialization.pool in initialized_by_pool:
                    raise ValueError(f"duplicate V4 Initialize for PoolId {initialization.pool}")
                decoded.append(initialization)
                initialized_by_pool[initialization.pool] = initialization
                continue
            kind = "modify_liquidity" if topic == UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC else "swap"
            event = decode_v4_state_event_identity(row, kind)
            exact_modify_count += int(kind == "modify_liquidity")
            exact_swap_count += int(kind == "swap")
            initialization = initialized_by_pool.get(str(event["pool"]))
            if initialization is None:
                missing.add(str(event["pool"]))
            elif initialization.order >= order:
                nonpreceding.add(str(event["pool"]))
    if missing or nonpreceding:
        raise ValueError(f"state-event generation violates Initialize precedence: missing={sorted(missing)[:3]}, nonpreceding={sorted(nonpreceding)[:3]}")
    source_manifest = portable_content_manifest_for_paths(raw_root, paths)
    certificate = {
        "status": "pass",
        "schema_version": STATE_EVENT_SCHEMA_VERSION,
        "generation": state_event_generation(venue),
        "venue": venue,
        "start_block": ordered_ranges[0][0],
        "end_block": ordered_ranges[-1][1],
        "chunk_count": len(ordered_ranges),
        "raw_logs": raw_log_count,
        "initialize_events": len(v3_initialization_evidence) if venue == "uniswap_v3" else len(decoded),
        "protocol_static_quote_supported_pools": sum(row.quote_supported for row in decoded),
        "unsupported_hooked_or_dynamic_pools": sum(not row.quote_supported for row in decoded),
        "exact_modify_liquidity_events": exact_modify_count,
        "exact_swap_events": exact_swap_count,
        "semantic_sha256": hashlib.sha256(json.dumps(v3_initialization_evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest() if venue == "uniswap_v3" else semantic_sha256(decoded),
        "frozen_upper_identity_sha256": frozen_upper["header_identity_sha256"],
        "source_manifest": source_manifest,
        "source_manifest_sha256": portable_manifest_sha256(source_manifest),
    }
    if venue == "uniswap_v4":
        certificate.update({
            "state_events_checked": exact_modify_count + exact_swap_count,
            "state_event_pools_missing_initialize": 0,
            "state_event_pools_nonpreceding_initialize": 0,
            "registry_pools_zero_initialize": 0,
            "registry_pools_zero_initialize_sha256": hashlib.sha256(b"[]").hexdigest(),
            "precedence_status": "pass",
            "support_end_block": support_end_block if support_end_block is not None else ordered_ranges[-1][1],
            "exact_state_gap_ledger": normalized_gaps,
            "exact_state_gap_ledger_sha256": hashlib.sha256(json.dumps(normalized_gaps, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "requested_range_count": len(requested_perimeter),
            "requested_range_manifest_sha256": hashlib.sha256(json.dumps(requested_perimeter, separators=(",", ":")).encode()).hexdigest(),
            "requested_ranges": [[lower, upper] for lower, upper in requested_perimeter],
            "canonical_start_block": UNISWAP_V4_POOL_MANAGER_DEPLOYMENT_BLOCK,
            "frozen_upper_block": int(frozen_upper["block_number"]),
            "semantically_excluded_tail_logs": len(excluded_tail),
            "semantically_excluded_tail_logs_sha256": hashlib.sha256(json.dumps(excluded_tail, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        })
        validate_v4_prefix_certificate(certificate)
    certificate["certificate_identity_sha256"] = certificate_identity_sha256(certificate)
    return (v3_initialization_evidence if venue == "uniswap_v3" else decoded), certificate


def iter_v4_state_events(
    ranges: Iterable[tuple[int, int]],
    *,
    frozen_upper: Mapping[str, object],
    raw_root: Path,
    support_end_block: int | None = None,
) -> Iterable[dict[str, object]]:
    """Reopen the certified chunk perimeter and yield exact V4 consumers once."""

    for lower, upper in sorted((int(lower), int(upper)) for lower, upper in ranges):
        for row in load_state_event_chunk("uniswap_v4", lower, upper, frozen_upper=frozen_upper, root=raw_root):
            if support_end_block is not None and int(row["block_number"]) > support_end_block:
                continue
            topic = str((row.get("topics") or [""])[0]).lower()
            if topic == UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC:
                yield decode_v4_state_event_identity(row, "modify_liquidity")
            elif topic == UNISWAP_V4_SWAP_TOPIC:
                yield decode_v4_state_event_identity(row, "swap")


def certify_state_event_precedence(
    certificate: Mapping[str, object],
    initializations: Iterable[TickInitialization | Mapping[str, object]],
    state_events: Iterable[Mapping[str, object]],
    *,
    registry_pools: Mapping[str, V3FactoryPool] | Iterable[str] | None = None,
) -> tuple[list[TickInitialization], dict[str, object]]:
    """Own the V3 registry perimeter and require precedence only within it."""

    raw_initializations = list(initializations)
    if isinstance(registry_pools, Mapping):
        registry_mapping = {str(pool).lower(): row for pool, row in registry_pools.items()}
    else:
        registry_mapping = {}
    outside_initialize_identities: list[dict[str, object]] = []
    initialization_rows: list[TickInitialization] = []
    for row in raw_initializations:
        if isinstance(row, TickInitialization):
            initialization_rows.append(row)
            continue
        pool = str(row.get("address") or "").lower()
        if pool not in registry_mapping:
            outside_initialize_identities.append(
                {
                    "pool": pool,
                    "block_number": int(row["block_number"]),
                    "block_hash": str(row["block_hash"]).lower(),
                    "transaction_hash": str(row["transaction_hash"]).lower(),
                    "transaction_index": int(row["transaction_index"]),
                    "log_index": int(row["log_index"]),
                    "reason": "absent_from_canonical_poolcreated_registry",
                }
            )
            continue
        initialization_rows.append(decode_v3_initialize(row, registry_mapping))
    initialization_rows.sort(key=lambda row: row.order)
    by_pool = {row.pool: row for row in initialization_rows}
    if len(by_pool) != len(initialization_rows):
        raise ValueError("precedence certificate received duplicate Initialize identities")
    if registry_mapping:
        registry = set(registry_mapping)
    else:
        registry = {str(pool).lower() for pool in registry_pools or ()}
    missing: set[str] = set()
    nonpreceding: set[str] = set()
    consuming_registry: set[str] = set()
    admitted_identities: list[dict[str, object]] = []
    outside_identities: list[dict[str, object]] = []
    outside_groups: dict[tuple[str, str], dict[str, object]] = {}
    for event in state_events:
        pool = str(event["pool"]).lower()
        identity = {
            "pool": pool,
            "kind": str(event.get("kind") or "unknown"),
            "block_number": int(event["block_number"]),
            "transaction_index": int(event.get("transaction_index", -1)),
            "log_index": int(event["log_index"]),
            "transaction_hash": str(event.get("transaction_hash") or "").lower(),
        }
        if registry and pool not in registry:
            outside_identities.append(identity)
            group_key = (identity["kind"], "absent_from_canonical_poolcreated_registry")
            group = outside_groups.setdefault(
                group_key,
                {
                    "kind": identity["kind"],
                    "reason": group_key[1],
                    "events": 0,
                    "first_block": identity["block_number"],
                    "last_block": identity["block_number"],
                },
            )
            group["events"] = int(group["events"]) + 1
            group["first_block"] = min(int(group["first_block"]), int(identity["block_number"]))
            group["last_block"] = max(int(group["last_block"]), int(identity["block_number"]))
            continue
        consuming_registry.add(pool)
        admitted_identities.append(identity)
        initialization = by_pool.get(pool)
        if initialization is None:
            missing.add(pool)
            continue
        order = (int(event["block_number"]), int(event["log_index"]))
        if initialization.order >= order:
            nonpreceding.add(pool)
    zero_initialize = sorted(registry - set(by_pool))
    zero_initialize_zero_consumer = sorted((registry - set(by_pool)) - consuming_registry)
    initialized_without_consumer = sorted((registry & set(by_pool)) - consuming_registry)
    outside_identities.sort(key=lambda row: (int(row["block_number"]), int(row["transaction_index"]), int(row["log_index"]), str(row["pool"])))
    admitted_identities.sort(key=lambda row: (int(row["block_number"]), int(row["transaction_index"]), int(row["log_index"]), str(row["pool"])))
    outside_summary = [outside_groups[key] for key in sorted(outside_groups)]
    outside_initialize_identities.sort(key=lambda row: (int(row["block_number"]), int(row["transaction_index"]), int(row["log_index"]), str(row["pool"])))
    result = {
        **{key: value for key, value in certificate.items() if key != "certificate_identity_sha256"},
        "initialize_events": len(initialization_rows),
        "registry_initializations_semantic_sha256": semantic_sha256(initialization_rows),
        "outside_registry_initialize_lookalikes": len(outside_initialize_identities),
        "outside_registry_initialize_lookalikes_sha256": hashlib.sha256(json.dumps(outside_initialize_identities, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "protocol_static_quote_supported_pools": sum(row.quote_supported for row in initialization_rows),
        "unsupported_hooked_or_dynamic_pools": sum(not row.quote_supported for row in initialization_rows),
        "state_events_checked": len(admitted_identities),
        "state_event_source_identities_sha256": hashlib.sha256(json.dumps(admitted_identities, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "outside_registry_consumer_lookalikes": len(outside_identities),
        "outside_registry_consumer_lookalikes_sha256": hashlib.sha256(json.dumps(outside_identities, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "outside_registry_consumer_lookalikes_by_kind_block_span_reason": outside_summary,
        "outside_registry_consumer_lookalikes_summary_sha256": hashlib.sha256(json.dumps(outside_summary, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "state_event_pools_missing_initialize": len(missing),
        "state_event_pools_nonpreceding_initialize": len(nonpreceding),
        "registry_pools_zero_initialize": len(zero_initialize),
        "registry_pools_zero_initialize_sha256": hashlib.sha256(json.dumps(zero_initialize, separators=(",", ":")).encode()).hexdigest(),
        "registry_pools_zero_initialize_zero_consumer": len(zero_initialize_zero_consumer),
        "registry_pools_zero_initialize_zero_consumer_sha256": hashlib.sha256(json.dumps(zero_initialize_zero_consumer, separators=(",", ":")).encode()).hexdigest(),
        "registry_pools_initialized_without_consumer": len(initialized_without_consumer),
        "registry_pools_initialized_without_consumer_sha256": hashlib.sha256(json.dumps(initialized_without_consumer, separators=(",", ":")).encode()).hexdigest(),
        "precedence_status": "pass" if not missing and not nonpreceding else "fail",
    }
    if missing or nonpreceding:
        raise ValueError(
            "state-event generation violates Initialize precedence: "
            f"missing={sorted(missing)[:3]}, nonpreceding={sorted(nonpreceding)[:3]}"
        )
    result["certificate_identity_sha256"] = certificate_identity_sha256(result)
    return initialization_rows, result


def certificate_identity_sha256(certificate: Mapping[str, object]) -> str:
    payload = {key: value for key, value in certificate.items() if key != "certificate_identity_sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def certify_materialization_support(
    certificate: Mapping[str, object],
    rows: Iterable[TickInitialization],
    token_metadata: Mapping[str, tuple[str, int]],
) -> dict[str, object]:
    """Separate protocol-static eligibility from metadata-complete quote support."""

    initializations = list(rows)
    initialization_tokens = {token for row in initializations for token in (row.token0, row.token1)}
    absent_tokens = initialization_tokens - set(token_metadata)
    result = {key: value for key, value in certificate.items() if key != "certificate_identity_sha256"}
    result["protocol_static_quote_supported_pools"] = sum(row.quote_supported for row in initializations)
    result["metadata_supported_pools"] = sum(row.token0 in token_metadata and row.token1 in token_metadata for row in initializations)
    result["materialized_quote_supported_pools"] = sum(row.quote_supported and row.token0 in token_metadata and row.token1 in token_metadata for row in initializations)
    result["initialize_tokens"] = len(initialization_tokens)
    result["initialize_tokens_outside_metadata_scope"] = len(absent_tokens)
    result["initialize_pools_excluded_unknown_token_metadata"] = sum(row.token0 in absent_tokens or row.token1 in absent_tokens for row in initializations)
    if str(result.get("token_metadata_scope", "")).startswith("exact_anchor_v2_registry"):
        result["venue_initialization_tokens_outside_v2_audit_scope"] = len(absent_tokens)
        result["venue_initialization_pools_outside_v2_audit_scope"] = result["initialize_pools_excluded_unknown_token_metadata"]
    result["certificate_identity_sha256"] = certificate_identity_sha256(result)
    return result


def _validated_day_cuts(
    day_cuts: Mapping[str, Mapping[str, object]],
) -> list[tuple[str, Mapping[str, object]]]:
    ordered = sorted((str(day), record) for day, record in day_cuts.items())
    if not ordered:
        raise ValueError("daily tick-state release requires a nonempty UTC-day calendar")
    prior_upper: int | None = None
    for day, record in ordered:
        validate_utc_day_block_bounds(dict(record), day)
        lower, upper = int(record["start_block"]), int(record["end_block"])
        if prior_upper is not None and lower != prior_upper + 1:
            raise ValueError("daily tick-state release block cuts are not contiguous")
        prior_upper = upper
    return ordered


def _day_cut_identity(record: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_daily_release_set(
    raw_root: Path,
    venue: str,
    *,
    kind: str,
    generation: str,
    cuts: list[tuple[str, Mapping[str, object]]],
    data_paths: list[Path],
    certificate_path: Path,
) -> Path:
    if len(cuts) != len(data_paths):
        raise ValueError("daily tick-state release perimeter disagrees with its data files")
    entries: list[dict[str, object]] = []
    for (day, cut), data_path in zip(cuts, data_paths, strict=True):
        marker_path = data_path.with_suffix(".meta.json")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        support_value = marker.get("scientific_support", True)
        if not isinstance(support_value, bool):
            raise ValueError("daily tick-state scientific support must be boolean")
        entries.append(
            {
                "day": day,
                "start_block": int(cut["start_block"]),
                "end_block": int(cut["end_block"]),
                "day_cut_sha256": _day_cut_identity(cut),
                "data_file": data_path.name,
                "data_sha256": file_sha256(data_path),
                "marker_file": marker_path.name,
                "marker_sha256": file_sha256(marker_path),
                "scientific_support": support_value,
            }
        )
    supported_days = [str(item["day"]) for item in entries if item["scientific_support"]]
    if not supported_days:
        raise ValueError("daily tick-state release has no scientifically supported prefix")
    normalized_support = scientific_support_calendar([str(item["day"]) for item in entries], supported_days[-1])
    if normalized_support != [{"day": item["day"], "scientific_support": item["scientific_support"]} for item in entries]:
        raise ValueError("daily tick-state scientific support reopens after its prefix")
    support_calendar_sha256 = scientific_support_calendar_sha256([str(item["day"]) for item in entries], supported_days[-1])
    source_certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    if kind == "v4_state" and source_certificate.get("support_end_day") is not None and source_certificate.get("scientific_support_calendar_sha256") != support_calendar_sha256:
        raise ValueError("daily V4 scientific-support calendar disagrees with its prefix certificate")
    record = {
        "status": "complete",
        "schema_version": DAILY_RELEASE_SET_SCHEMA_VERSION,
        "generation": generation,
        "kind": kind,
        "venue": venue,
        "days": [day for day, _cut in cuts],
        "day_count": len(entries),
        "calendar_sha256": hashlib.sha256(
            json.dumps([day for day, _cut in cuts], separators=(",", ":")).encode()
        ).hexdigest(),
        "scientific_support_calendar_sha256": support_calendar_sha256,
        "day_cut_manifest_sha256": hashlib.sha256(
            json.dumps(
                [
                    {
                        "day": item["day"],
                        "start_block": item["start_block"],
                        "end_block": item["end_block"],
                        "day_cut_sha256": item["day_cut_sha256"],
                    }
                    for item in entries
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "certificate_file": certificate_path.name,
        "certificate_sha256": file_sha256(certificate_path),
        "entries": entries,
    }
    record["certificate_identity_sha256"] = certificate_identity_sha256(record)
    path = daily_release_set_path(raw_root, venue, kind=kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    return path


def _validate_daily_release_member(
    raw_root: Path,
    venue: str,
    day: str,
    *,
    kind: str,
    generation: str,
    data_path: Path,
    marker_path: Path,
    certificate_path: Path,
) -> dict[str, object]:
    release_path = daily_release_set_path(raw_root, venue, kind=kind)
    release = json.loads(release_path.read_text(encoding="utf-8"))
    source_certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    entries = release.get("entries")
    days = release.get("days")
    if not isinstance(entries, list) or not isinstance(days, list):
        raise ValueError("daily tick-state release set is malformed")
    if any(not isinstance(item, dict) for item in entries):
        raise ValueError("daily tick-state release set contains a malformed member")
    expected_names = {str(item.get("data_file")) for item in entries if isinstance(item, dict)}
    actual_names = {path.name for path in release_path.parent.glob("*.jsonl.gz")}
    selected = [item for item in entries if isinstance(item, dict) and item.get("day") == day]
    cut_manifest = [
        {
            "day": item["day"],
            "start_block": item["start_block"],
            "end_block": item["end_block"],
            "day_cut_sha256": item["day_cut_sha256"],
        }
        for item in entries
    ]
    support_calendar = [
        {"day": item["day"], "scientific_support": item.get("scientific_support")}
        for item in entries
    ]
    supported_days = [str(item["day"]) for item in support_calendar if item["scientific_support"] is True]
    support_calendar_valid = bool(supported_days) and support_calendar == scientific_support_calendar(days, supported_days[-1])
    expected_support_calendar_sha256 = scientific_support_calendar_sha256(days, supported_days[-1]) if support_calendar_valid else None
    members_exist = all(
        (release_path.parent / str(item["data_file"])).is_file()
        and (release_path.parent / str(item["marker_file"])).is_file()
        for item in entries
    )
    if (
        release.get("status") != "complete"
        or int(release.get("schema_version", -1)) != DAILY_RELEASE_SET_SCHEMA_VERSION
        or release.get("generation") != generation
        or release.get("kind") != kind
        or release.get("venue") != venue
        or int(release.get("day_count", -1)) != len(entries)
        or len(days) != len(entries)
        or days != sorted(days)
        or [item.get("day") for item in entries if isinstance(item, dict)] != days
        or len(selected) != 1
        or expected_names != actual_names
        or not members_exist
        or release.get("calendar_sha256")
        != hashlib.sha256(json.dumps(days, separators=(",", ":")).encode()).hexdigest()
        or release.get("day_cut_manifest_sha256")
        != hashlib.sha256(
            json.dumps(cut_manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        or release.get("scientific_support_calendar_sha256")
        != expected_support_calendar_sha256
        or not support_calendar_valid
        or release.get("certificate_file") != certificate_path.name
        or release.get("certificate_sha256") != file_sha256(certificate_path)
        or (kind == "v4_state" and source_certificate.get("support_end_day") is not None and source_certificate.get("scientific_support_calendar_sha256") != release.get("scientific_support_calendar_sha256"))
        or release.get("certificate_identity_sha256") != certificate_identity_sha256(release)
    ):
        raise ValueError(
            f"daily tick-state release is stale or uncertified: incomplete set {kind}/{venue}"
        )
    entry = selected[0]
    if (
        entry.get("data_file") != data_path.name
        or entry.get("data_sha256") != file_sha256(data_path)
        or entry.get("marker_file") != marker_path.name
        or entry.get("marker_sha256") != file_sha256(marker_path)
    ):
        raise ValueError(
            f"daily tick-state release is stale or uncertified: drifted member {kind}/{venue}/{day}"
        )
    return entry


def write_daily_initializations(
    venue: str,
    rows: Iterable[TickInitialization],
    *,
    day_cuts: Mapping[str, Mapping[str, object]],
    token_metadata: Mapping[str, tuple[str, int]],
    raw_root: Path,
    generation_certificate: Mapping[str, object],
) -> list[Path]:
    """Materialize certified initialization rows into exact UTC-day replay inputs."""

    remaining = iter(sorted(rows, key=lambda row: row.order))
    current = next(remaining, None)
    output: list[Path] = []
    seen: set[str] = set()
    if (
        generation_certificate.get("status") != "pass"
        or generation_certificate.get("generation") != state_event_generation(venue)
        or generation_certificate.get("venue") != venue
        or generation_certificate.get("precedence_status") != "pass"
        or generation_certificate.get("certificate_identity_sha256")
        != certificate_identity_sha256(generation_certificate)
    ):
        raise ValueError("daily Initialize materialization requires a valid precedence certificate")
    certificate_path = state_event_certificate_path(raw_root, venue)
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(certificate_path, dict(generation_certificate))
    certificate_sha256 = file_sha256(certificate_path)
    cuts = _validated_day_cuts(day_cuts)
    for day, cut in cuts:
        lower, upper = int(cut["start_block"]), int(cut["end_block"])
        if current is not None and current.block_number < lower:
            raise ValueError(f"Initialize row falls before the certified day bound: {current.pool}")
        path = initialization_day_path(raw_root, venue, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        daily_rows: list[dict[str, object]] = []
        while current is not None and current.block_number <= upper:
            row = current
            if row.pool in seen:
                raise ValueError(f"duplicate daily Initialize identity: {row.pool}")
            meta0, meta1 = token_metadata.get(row.token0), token_metadata.get(row.token1)
            metadata_supported = meta0 is not None and meta1 is not None
            meta0 = meta0 or ("", None)
            meta1 = meta1 or ("", None)
            daily_rows.append({
                        "id": f"{row.transaction_hash}#{row.log_index}",
                        "transaction": {"id": row.transaction_hash, "blockNumber": row.block_number},
                        "logIndex": row.log_index,
                        "sqrtPriceX96": str(row.sqrt_price_x96),
                        "tick": row.tick,
                        "pool": {
                            "id": row.pool,
                            "feeTier": row.fee_pips,
                            "tickSpacing": row.tick_spacing,
                            "hooks": row.hooks,
                            "token0": {"id": row.token0, "symbol": meta0[0], "decimals": meta0[1]},
                            "token1": {"id": row.token1, "symbol": meta1[0], "decimals": meta1[1]},
                        },
                        "quoteUnsupportedReason": row.quote_unsupported_reason if metadata_supported else "unknown_token_metadata",
                    })
            seen.add(row.pool)
            current = next(remaining, None)
        write_jsonl_gz(path, daily_rows)
        write_json(path.with_suffix(".meta.json"), {
            "status": "complete",
            "schema_version": STATE_EVENT_SCHEMA_VERSION,
            "generation": DERIVED_INITIALIZATION_GENERATION,
            "venue": venue,
            "day": day,
            "start_block": lower,
            "end_block": upper,
            "day_cut_sha256": _day_cut_identity(cut),
            "rows": len(daily_rows),
            "data_sha256": file_sha256(path),
            "certificate_identity": state_event_certificate_identity(venue),
            "certificate_sha256": certificate_sha256,
        })
        output.append(path)
    if current is not None:
        raise ValueError(f"Initialize row falls outside the certified day calendar: {current.pool}")
    _write_daily_release_set(
        raw_root,
        venue,
        kind="initializations",
        generation=DAILY_INITIALIZATION_RELEASE_GENERATION,
        cuts=cuts,
        data_paths=output,
        certificate_path=certificate_path,
    )
    return output


def _materialized_v4_state_row(
    row: Mapping[str, object],
    statics: Mapping[str, TickInitialization],
    token_metadata: Mapping[str, tuple[str, int]],
) -> dict[str, object]:
    pool_id = str(row["pool"]).lower()
    static = statics.get(pool_id)
    if static is None:
        raise ValueError(f"exact V4 state event lacks certified Initialize: {pool_id}")
    meta0, meta1 = token_metadata.get(static.token0), token_metadata.get(static.token1)
    metadata_supported = meta0 is not None and meta1 is not None
    meta0, meta1 = meta0 or ("", None), meta1 or ("", None)
    common = {
        "id": f'{row["transaction_hash"]}#{row["log_index"]}',
        "eventKind": "swap" if row["kind"] == "swap" else "modify_liquidity",
        "transaction": {"id": row["transaction_hash"], "blockNumber": row["block_number"]},
        "logIndex": row["log_index"],
        "pool": {
            "id": pool_id,
            "feeTier": static.fee_pips,
            "tickSpacing": static.tick_spacing,
            "hooks": static.hooks,
            "token0": {"id": static.token0, "symbol": meta0[0], "decimals": meta0[1]},
            "token1": {"id": static.token1, "symbol": meta1[0], "decimals": meta1[1]},
        },
        "quoteUnsupportedReason": static.quote_unsupported_reason if metadata_supported else "unknown_token_metadata",
    }
    if row["kind"] == "swap":
        if static.quote_supported and int(row["fee"]) != static.fee_pips:
            raise ValueError(f"exact V4 static-fee Swap disagrees with Initialize fee: {pool_id}")
        raw0 = int(row["amount0"])
        raw1 = int(row["amount1"])
        common.update({
            "amount0Raw": str(raw0),
            "amount1Raw": str(raw1),
            "amount0": raw_to_human(raw0, int(meta0[1])) if metadata_supported else None,
            "amount1": raw_to_human(raw1, int(meta1[1])) if metadata_supported else None,
            "sqrtPriceX96": str(row["sqrt_price_x96"]),
            "tick": int(row["tick"]),
        })
    elif row["kind"] == "modify_liquidity":
        common.update({"amount": str(row["liquidity_delta"]), "tickLower": int(row["tick_lower"]), "tickUpper": int(row["tick_upper"])})
    else:
        raise ValueError(f'unsupported exact V4 state event kind: {row["kind"]}')
    return common


def write_daily_v4_state_events(
    rows: Iterable[Mapping[str, object]],
    initializations: Iterable[TickInitialization],
    *,
    day_cuts: Mapping[str, Mapping[str, object]],
    token_metadata: Mapping[str, tuple[str, int]],
    raw_root: Path,
    generation_certificate: Mapping[str, object],
) -> list[Path]:
    """Materialize the certified V4 state census, never provider event rows."""

    venue = "uniswap_v4"
    certificate_path = state_event_certificate_path(raw_root, venue)
    if (
        generation_certificate.get("status") != "pass"
        or generation_certificate.get("generation") != state_event_generation(venue)
        or generation_certificate.get("venue") != venue
        or generation_certificate.get("precedence_status") != "pass"
        or generation_certificate.get("certificate_identity_sha256")
        != certificate_identity_sha256(generation_certificate)
        or not certificate_path.is_file()
        or json.loads(certificate_path.read_text(encoding="utf-8")) != dict(generation_certificate)
    ):
        raise ValueError(f"daily {venue} state materialization requires its exact census certificate")
    statics = {row.pool: row for row in initializations}
    ordered = iter(rows)
    current = next(ordered, None)
    last_order: tuple[int, int] | None = None
    output: list[Path] = []
    emitted = 0
    cuts = _validated_day_cuts(day_cuts)
    support_end_day = str(generation_certificate.get("support_end_day") or cuts[-1][0])
    support_end_block = int(generation_certificate.get("support_end_block", cuts[-1][1]["end_block"]))
    support_matches = [
        (day, cut)
        for day, cut in cuts
        if day == support_end_day and int(cut["end_block"]) == support_end_block
    ]
    if len(support_matches) != 1:
        raise ValueError("exact V4 prefix certificate must end on one full UTC-day cut")
    if generation_certificate.get("support_end_day") is not None:
        validate_v4_prefix_certificate(generation_certificate)
    support_by_day = {str(item["day"]): bool(item["scientific_support"]) for item in scientific_support_calendar((day for day, _cut in cuts), support_end_day)}
    for day, cut in cuts:
        lower, upper = int(cut["start_block"]), int(cut["end_block"])
        if current is not None and int(current["block_number"]) < lower:
            raise ValueError(f"exact {venue} state row falls before the certified day bound")
        daily_rows: list[dict[str, object]] = []
        scientific_support = support_by_day[day]
        while scientific_support and current is not None and int(current["block_number"]) <= upper:
            order = (int(current["block_number"]), int(current["log_index"]))
            if last_order is not None and order <= last_order:
                raise ValueError("exact V4 state rows are not globally strictly ordered")
            last_order = order
            daily_rows.append(_materialized_v4_state_row(current, statics, token_metadata))
            emitted += 1
            current = next(ordered, None)
        path = v4_state_day_path(raw_root, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl_gz(path, daily_rows)
        write_json(path.with_suffix(".meta.json"), {
            "status": "complete",
            "schema_version": STATE_EVENT_SCHEMA_VERSION,
            "generation": DERIVED_V4_STATE_GENERATION,
            "venue": venue,
            "day": day,
            "start_block": lower,
            "end_block": upper,
            "day_cut_sha256": _day_cut_identity(cut),
            "rows": len(daily_rows),
            "initialize_rows": 0,
            "modify_liquidity_rows": sum(row["eventKind"] == "modify_liquidity" for row in daily_rows),
            "swap_rows": sum(row["eventKind"] == "swap" for row in daily_rows),
            "data_sha256": file_sha256(path),
            "certificate_identity": state_event_certificate_identity(venue),
            "certificate_sha256": file_sha256(certificate_path),
            "scientific_support": scientific_support,
            "support_end_day": support_end_day,
            "support_end_block": support_end_block,
        })
        output.append(path)
    if current is not None:
        raise ValueError(f"exact {venue} state rows fall outside the certified support calendar")
    expected = int(generation_certificate.get("exact_modify_liquidity_events", -1)) + int(generation_certificate.get("exact_swap_events", -1))
    if emitted != expected:
        raise ValueError(f"exact V4 daily state count drifted: emitted={emitted}, certified={expected}")
    _write_daily_release_set(
        raw_root,
        venue,
        kind="v4_state",
        generation=DAILY_V4_STATE_RELEASE_GENERATION,
        cuts=cuts,
        data_paths=output,
        certificate_path=certificate_path,
    )
    return output


def validate_v4_state_day(raw_root: Path, day: str) -> tuple[Path, Path, Path]:
    """Reopen a daily exact V4 state stream and bind it to its full census."""

    venue = "uniswap_v4"
    data, marker_path, certificate_path = v4_state_day_inputs(raw_root, day)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    if certificate.get("support_end_day") is not None:
        validate_v4_prefix_certificate(certificate)
    release_entry = _validate_daily_release_member(
        raw_root,
        venue,
        day,
        kind="v4_state",
        generation=DAILY_V4_STATE_RELEASE_GENERATION,
        data_path=data,
        marker_path=marker_path,
        certificate_path=certificate_path,
    )
    if (
        marker.get("status") != "complete"
        or marker.get("generation") != DERIVED_V4_STATE_GENERATION
        or marker.get("venue") != venue
        or marker.get("day") != day
        or int(marker.get("start_block", -1)) != int(release_entry["start_block"])
        or int(marker.get("end_block", -1)) != int(release_entry["end_block"])
        or marker.get("day_cut_sha256") != release_entry.get("day_cut_sha256")
        or marker.get("data_sha256") != file_sha256(data)
        or marker.get("certificate_identity") != state_event_certificate_identity(venue)
        or marker.get("certificate_sha256") != file_sha256(certificate_path)
        or marker.get("scientific_support") is not bool(release_entry.get("scientific_support"))
        or (certificate.get("support_end_day") is not None and marker.get("support_end_day") != certificate.get("support_end_day"))
        or (certificate.get("support_end_block") is not None and int(marker.get("support_end_block", -1)) != int(certificate["support_end_block"]))
        or certificate.get("status") != "pass"
        or certificate.get("generation") != state_event_generation(venue)
        or certificate.get("venue") != venue
        or certificate.get("precedence_status") != "pass"
        or certificate.get("certificate_identity_sha256") != certificate_identity_sha256(certificate)
    ):
        raise ValueError(f"daily exact V4 state input is stale or uncertified: {day}")
    with gzip.open(data, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    if (
        int(marker.get("rows", -1)) != len(rows)
        or int(marker.get("swap_rows", -1)) != sum(row.get("eventKind") == "swap" for row in rows)
        or int(marker.get("modify_liquidity_rows", -1)) != sum(row.get("eventKind") == "modify_liquidity" for row in rows)
        or any(row.get("eventKind") not in {"swap", "modify_liquidity"} for row in rows)
        or (marker.get("scientific_support") is False and rows)
    ):
        raise ValueError(f"daily exact V4 state row contract drifted: {day}")
    return data, marker_path, certificate_path


def validate_initialization_day(raw_root: Path, venue: str, day: str) -> tuple[Path, Path, Path]:
    """Reopen one daily Initialize input and bind it to its source generation."""

    data, marker_path, certificate_path = initialization_day_inputs(raw_root, venue, day)
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    release_entry = _validate_daily_release_member(
        raw_root,
        venue,
        day,
        kind="initializations",
        generation=DAILY_INITIALIZATION_RELEASE_GENERATION,
        data_path=data,
        marker_path=marker_path,
        certificate_path=certificate_path,
    )
    if (
        marker.get("status") != "complete"
        or marker.get("generation") != DERIVED_INITIALIZATION_GENERATION
        or marker.get("venue") != venue
        or marker.get("day") != day
        or int(marker.get("start_block", -1)) != int(release_entry["start_block"])
        or int(marker.get("end_block", -1)) != int(release_entry["end_block"])
        or marker.get("day_cut_sha256") != release_entry.get("day_cut_sha256")
        or marker.get("data_sha256") != file_sha256(data)
        or marker.get("certificate_identity") != state_event_certificate_identity(venue)
        or marker.get("certificate_sha256") != file_sha256(certificate_path)
        or certificate.get("status") != "pass"
        or certificate.get("generation") != state_event_generation(venue)
        or certificate.get("venue") != venue
        or certificate.get("certificate_identity_sha256") != certificate_identity_sha256(certificate)
        or certificate.get("precedence_status") != "pass"
    ):
        raise ValueError(f"daily Initialize input is stale or uncertified: {venue}/{day}")
    with gzip.open(data, "rt", encoding="utf-8") as handle:
        rows = sum(bool(line.strip()) for line in handle)
    if int(marker.get("rows", -1)) != rows:
        raise ValueError(f"daily Initialize row count drifted: {venue}/{day}")
    return data, marker_path, certificate_path

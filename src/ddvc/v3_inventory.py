"""Uniswap V3 event semantics needed to reconstruct event-accounted pool inventories."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from decimal import Decimal
import gzip
import json
from pathlib import Path
from typing import Iterable, Iterator

from eth_abi import decode as abi_decode
from eth_utils import keccak
import pyarrow.parquet as pq

from ddvc.ethereum_logs import (
    EXACT_LOG_BLOCK_CAP,
    RAW_LOG_SCHEMA,
    RAW_LOG_STORAGE_FORMAT,
    block_ranges,
    canonical_raw_log,
    exact_log_block_ranges,
    file_sha256,
    rpc_integer,
    validate_anchored_log_evidence,
    validate_canonical_log_records,
)
from ddvc.v3_pool_registry import load_registry


EVENT_SIGNATURES = {
    "mint": "Mint(address,address,int24,int24,uint128,uint256,uint256)",
    "burn": "Burn(address,int24,int24,uint128,uint256,uint256)",
    "swap": "Swap(address,address,int256,int256,uint160,uint128,int24)",
    "collect": "Collect(address,address,int24,int24,uint128,uint128)",
    "flash": "Flash(address,address,uint256,uint256,uint256,uint256)",
    "collect_protocol": "CollectProtocol(address,address,uint128,uint128)",
}
EVENT_TOPICS = {
    name: "0x" + keccak(text=signature).hex()
    for name, signature in EVENT_SIGNATURES.items()
}
EVENT_BY_TOPIC = {topic: name for name, topic in EVENT_TOPICS.items()}
BALANCE_OF_SELECTOR = "0x" + keccak(text="balanceOf(address)")[:4].hex()
INVENTORY_RAW_MARKER_SCHEMA_VERSION = 5
INVENTORY_RAW_GENERATION = "uniswap_v3_anchored_global_state_and_inventory_topics_v5"
INVENTORY_RAW_EVIDENCE_KIND = "uniswap_v3_state_and_inventory_rpc_evidence_v2"
INVENTORY_STATE_GENERATION = "uniswap_v3_factory_perimeter_inventory_v5"
INVENTORY_QUANTITY_KIND = "event_replayed_pool_inventory"
PENDING_CUSTODY_STATUS = "pending_historical_balance_validation"
PENDING_OWNERSHIP_STATUS = "pending_protocol_fee_ownership_reconciliation"


@dataclass(frozen=True)
class PoolStatic:
    pool: str
    token0: str
    token1: str
    symbol0: str
    symbol1: str
    decimals0: int
    decimals1: int


def pool_static_from_graph(record: dict[str, object]) -> PoolStatic:
    """Parse one immutable Graph pool row under exact address/decimal contracts."""

    token0 = record.get("token0")
    token1 = record.get("token1")
    if not isinstance(token0, dict) or not isinstance(token1, dict):
        raise ValueError("V3 pool static lacks token objects")
    pool = str(record.get("id") or "").lower()
    token0_address = str(token0.get("id") or "").lower()
    token1_address = str(token1.get("id") or "").lower()
    if not all(
        value.startswith("0x") and len(value) == 42
        for value in (pool, token0_address, token1_address)
    ):
        raise ValueError("V3 pool static lacks exact contract identities")
    decimals0 = int(token0.get("decimals"))
    decimals1 = int(token1.get("decimals"))
    if not 0 <= decimals0 <= 255 or not 0 <= decimals1 <= 255:
        raise ValueError("V3 pool static has invalid token decimals")
    return PoolStatic(
        pool=pool,
        token0=token0_address,
        token1=token1_address,
        symbol0=str(token0.get("symbol") or ""),
        symbol1=str(token1.get("symbol") or ""),
        decimals0=decimals0,
        decimals1=decimals1,
    )


def pool_statics_from_factory(
    registry_path: Path,
    certificate_path: Path,
    graph_static_path: Path,
    *,
    candidate_tokens: set[str],
) -> dict[str, PoolStatic]:
    """Join exact factory identities to provider token metadata without widening the census."""

    token_metadata: dict[str, tuple[str, int]] = {}
    graph_pools: dict[str, PoolStatic] = {}
    with gzip.open(graph_static_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            static = pool_static_from_graph(json.loads(line))
            if static.pool in graph_pools:
                raise ValueError(f"duplicate Graph V3 pool identity: {static.pool}")
            graph_pools[static.pool] = static
            for token, symbol, decimals in (
                (static.token0, static.symbol0, static.decimals0),
                (static.token1, static.symbol1, static.decimals1),
            ):
                prior = token_metadata.get(token)
                if prior is not None and prior[1] != decimals:
                    raise ValueError(f"conflicting Graph token decimals for {token}")
                if prior is None or (not prior[0] and symbol):
                    token_metadata[token] = (symbol, decimals)
    statics: dict[str, PoolStatic] = {}
    for factory_pool in load_registry(registry_path, certificate_path):
        if not ({factory_pool.token0, factory_pool.token1} & candidate_tokens):
            continue
        graph_static = graph_pools.get(factory_pool.pool)
        if graph_static is not None and (
            graph_static.token0 != factory_pool.token0
            or graph_static.token1 != factory_pool.token1
        ):
            raise ValueError(
                f"Graph V3 statics conflict with factory identity for {factory_pool.pool}"
            )
        metadata0 = token_metadata.get(factory_pool.token0)
        metadata1 = token_metadata.get(factory_pool.token1)
        if metadata0 is None or metadata1 is None:
            raise RuntimeError(
                f"factory V3 pool lacks token metadata enrichment: {factory_pool.pool}"
            )
        statics[factory_pool.pool] = PoolStatic(
            pool=factory_pool.pool,
            token0=factory_pool.token0,
            token1=factory_pool.token1,
            symbol0=metadata0[0],
            symbol1=metadata1[0],
            decimals0=metadata0[1],
            decimals1=metadata1[1],
        )
    if not statics:
        raise RuntimeError("candidate-linked certified V3 factory registry is empty")
    return statics


def inventory_chunk_paths(lower: int, upper: int, root: Path) -> tuple[Path, Path]:
    stem = f"blocks_{lower:08d}_{upper:08d}"
    return root / f"{stem}.parquet", root / f"{stem}.meta.json"


def inventory_chunk_evidence_path(lower: int, upper: int, root: Path) -> Path:
    stem = f"blocks_{lower:08d}_{upper:08d}"
    return root / f"{stem}.rpc.json.gz"


def iter_decoded_inventory_logs(
    path: Path,
    *,
    lower: int | None = None,
    upper: int | None = None,
    pools: set[str] | None = None,
) -> Iterator[dict[str, object]]:
    """Stream decoded exact logs under optional block and pool perimeters."""

    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=50_000):
        for raw in batch.to_pylist():
            block = int(raw["block_number"])
            pool = str(raw["address"]).lower()
            if lower is not None and block < lower:
                continue
            if upper is not None and block > upper:
                continue
            if pools is not None and pool not in pools:
                continue
            yield decode_inventory_log(raw)


def inventory_chunk_completed(
    lower: int,
    upper: int,
    root: Path,
    *,
    frozen_upper: dict[str, object],
    event_topics: set[str] | frozenset[str] = frozenset(EVENT_TOPICS.values()),
) -> bool:
    raw, meta = inventory_chunk_paths(lower, upper, root)
    evidence_path = inventory_chunk_evidence_path(lower, upper, root)
    if not raw.is_file() or not meta.is_file() or not evidence_path.is_file():
        return False
    try:
        marker = json.loads(meta.read_text(encoding="utf-8"))
        with gzip.open(evidence_path, "rt", encoding="utf-8") as handle:
            evidence = json.load(handle)
        table = pq.read_table(raw)
        records = validate_canonical_log_records(
            table.to_pylist(),
            start_block=lower,
            end_block=upper,
            topics=sorted(event_topics),
            address=None,
        )
        expected_ranges = exact_log_block_ranges(lower, upper)
        subranges = evidence.get("rpc_subrange_evidence")
        if not isinstance(subranges, list) or len(subranges) != len(expected_ranges):
            return False
        for (rpc_lower, rpc_upper), subrange in zip(
            expected_ranges, subranges, strict=True
        ):
            if not isinstance(subrange, dict) or (
                int(subrange.get("start_block", -1)),
                int(subrange.get("end_block", -1)),
            ) != (rpc_lower, rpc_upper):
                return False
            subrange_records = [
                record
                for record in records
                if rpc_lower <= int(record["block_number"]) <= rpc_upper
            ]
            validate_anchored_log_evidence(subrange, subrange_records, frozen_upper)
    except (
        IndexError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return False
    return bool(
        marker.get("status") == "complete"
        and int(marker.get("from_block", -1)) == lower
        and int(marker.get("to_block", -1)) == upper
        and set(marker.get("event_topics") or []) == set(event_topics)
        and marker.get("storage_format") == RAW_LOG_STORAGE_FORMAT
        and int(marker.get("raw_logs", -1)) == len(records)
        and table.schema == RAW_LOG_SCHEMA
        and int(marker.get("schema_version", -1))
        == INVENTORY_RAW_MARKER_SCHEMA_VERSION
        and marker.get("inventory_raw_generation") == INVENTORY_RAW_GENERATION
        and set((marker.get("raw_by_event") or {}).keys()) == set(EVENT_TOPICS)
        and int(marker.get("rpc_block_cap", -1)) == EXACT_LOG_BLOCK_CAP
        and int(marker.get("rpc_subranges", -1)) == len(expected_ranges)
        and marker.get("rpc_evidence_file") == evidence_path.name
        and marker.get("rpc_evidence_sha256") == file_sha256(evidence_path)
        and marker.get("raw_sha256") == file_sha256(raw)
        and evidence.get("status") == "complete"
        and evidence.get("kind") == INVENTORY_RAW_EVIDENCE_KIND
        and int(evidence.get("schema_version", -1))
        == INVENTORY_RAW_MARKER_SCHEMA_VERSION
        and evidence.get("inventory_raw_generation") == INVENTORY_RAW_GENERATION
        and int(evidence.get("from_block", -1)) == lower
        and int(evidence.get("to_block", -1)) == upper
        and set(evidence.get("event_topics") or []) == set(event_topics)
        and int(evidence.get("raw_logs", -1)) == len(records)
        and int(evidence.get("frozen_upper_block", -1))
        == int(frozen_upper["block_number"])
        and evidence.get("frozen_upper_block_hash") == frozen_upper["block_hash"]
        and evidence.get("frozen_upper_identity_sha256")
        == frozen_upper["header_identity_sha256"]
    )


def audit_inventory_chunks(
    ranges: Iterable[tuple[int, int]],
    root: Path,
    *,
    pool_creation_blocks: dict[str, int],
    frozen_upper: dict[str, object],
) -> dict[str, object]:
    """Read every raw log and classify it against the factory-created perimeter."""

    expected_topics = set(EVENT_TOPICS.values())
    canonical_by_event = {name: 0 for name in EVENT_TOPICS}
    quarantined_by_event = {name: 0 for name in EVENT_TOPICS}
    quarantine_reasons = {
        "absent_from_canonical_poolcreated_registry": 0,
        "predates_canonical_pool_creation": 0,
    }
    quarantined_pools: set[str] = set()
    quarantine_pool_counts: dict[tuple[str, str], dict[str, object]] = {}
    totals: dict[str, object] = {
        "chunks": 0,
        "raw_logs": 0,
        "canonical_pool_logs": 0,
        "quarantined_logs": 0,
    }
    for lower, upper in ranges:
        raw_path, meta_path = inventory_chunk_paths(lower, upper, root)
        if not inventory_chunk_completed(
            lower,
            upper,
            root,
            frozen_upper=frozen_upper,
        ):
            raise RuntimeError(f"incomplete V3 inventory chunk {lower}-{upper}")
        metadata = json.loads(meta_path.read_text())
        keys: set[tuple[int, str, int]] = set()
        raw_logs = 0
        raw_by_event = {name: 0 for name in EVENT_TOPICS}
        for decoded in iter_decoded_inventory_logs(raw_path):
            block = int(decoded["block_number"])
            if not lower <= block <= upper:
                raise ValueError(
                    f"V3 inventory log block {block} lies outside {lower}-{upper}"
                )
            identity = (
                block,
                str(decoded["tx_hash"]),
                int(decoded["log_index"]),
            )
            if identity in keys:
                raise ValueError(f"duplicate V3 inventory log within chunk: {identity}")
            keys.add(identity)
            raw_logs += 1
            pool = str(decoded["pool"])
            event_type = str(decoded["event_type"])
            raw_by_event[event_type] += 1
            creation_block = pool_creation_blocks.get(pool)
            if creation_block is None:
                reason = "absent_from_canonical_poolcreated_registry"
                quarantined_pools.add(pool)
                quarantined_by_event[event_type] += 1
                quarantine_reasons[reason] += 1
            elif block < creation_block:
                reason = "predates_canonical_pool_creation"
                quarantined_pools.add(pool)
                quarantined_by_event[event_type] += 1
                quarantine_reasons[reason] += 1
            else:
                canonical_by_event[event_type] += 1
                continue
            quarantine_key = (pool, reason)
            quarantine_row = quarantine_pool_counts.setdefault(
                quarantine_key,
                {
                    "pool": pool,
                    "reason": reason,
                    "first_block": block,
                    "last_block": block,
                    "logs": 0,
                    **{f"{name}_logs": 0 for name in EVENT_TOPICS},
                },
            )
            quarantine_row["first_block"] = min(
                int(quarantine_row["first_block"]), block
            )
            quarantine_row["last_block"] = max(
                int(quarantine_row["last_block"]), block
            )
            quarantine_row["logs"] = int(quarantine_row["logs"]) + 1
            event_column = f"{event_type}_logs"
            quarantine_row[event_column] = int(quarantine_row[event_column]) + 1
        if set(metadata.get("event_topics") or []) != expected_topics:
            raise ValueError(f"V3 inventory chunk {lower}-{upper} has a topic perimeter drift")
        if int(metadata.get("raw_logs", -1)) != raw_logs:
            raise ValueError(f"V3 inventory chunk {lower}-{upper} raw row count differs")
        if metadata.get("inventory_raw_generation") is not None:
            recorded_by_event = {
                str(key): int(value)
                for key, value in (metadata.get("raw_by_event") or {}).items()
            }
            if recorded_by_event != raw_by_event:
                raise ValueError(f"V3 inventory chunk {lower}-{upper} event counts differ")
        totals["chunks"] = int(totals["chunks"]) + 1
        totals["raw_logs"] = int(totals["raw_logs"]) + raw_logs
    temporaries = list(root.glob(".*.tmp"))
    if temporaries:
        raise RuntimeError(f"V3 inventory raw perimeter contains {len(temporaries):,} temporaries")
    canonical_logs = sum(canonical_by_event.values())
    quarantined_logs = sum(quarantined_by_event.values())
    if canonical_logs + quarantined_logs != int(totals["raw_logs"]):
        raise AssertionError("V3 factory-perimeter classification does not conserve raw logs")
    totals.update(
        {
            "canonical_pool_logs": canonical_logs,
            "quarantined_logs": quarantined_logs,
            "canonical_by_event": canonical_by_event,
            "quarantined_by_event": quarantined_by_event,
            "quarantine_reasons": quarantine_reasons,
            "quarantined_pools": len(quarantined_pools),
            "quarantine_pool_ledger": [
                quarantine_pool_counts[key] for key in sorted(quarantine_pool_counts)
            ],
        }
    )
    return totals


def _field(record: object, name: str) -> object:
    return record.get(name) if isinstance(record, dict) else getattr(record, name, None)


def canonical_inventory_start_block(records: Iterable[object]) -> int:
    """Return the first canonical Mint or Swap block in an ordered or unordered frame."""

    blocks: list[int] = []
    for record in records:
        record_type = str(_field(record, "record_type") or "")
        source_stream = str(_field(record, "source_stream") or "")
        if record_type == "swap" or (
            record_type == "liquidity" and source_stream == "mints"
        ):
            blocks.append(int(_field(record, "block_number")))
    if not blocks or min(blocks) <= 0:
        raise ValueError("canonical V3 state lacks an inventory-changing event")
    return min(blocks)


def is_physical_inventory_transfer(event: dict[str, object]) -> bool:
    """Return physical-transfer status and reject a contradictory Burn marker."""

    event_type = str(event.get("event_type") or "")
    declared = event.get("physical_inventory_transfer")
    expected = event_type != "burn" if event_type else bool(declared if declared is not None else True)
    if declared is not None and bool(declared) != expected:
        raise ValueError(f"contradictory V3 transfer semantics for {event_type or 'untyped event'}")
    return expected


def apply_inventory_event(
    balances: dict[str, tuple[int, int]], event: dict[str, object]
) -> tuple[int, int]:
    """Apply one signed physical-balance event and return the new pool inventory."""

    pool = str(event["pool"]).lower()
    before0, before1 = balances.get(pool, (0, 0))
    if not is_physical_inventory_transfer(event):
        return before0, before1
    after = (
        before0 + int(event["amount0_delta_raw"]),
        before1 + int(event["amount1_delta_raw"]),
    )
    balances[pool] = after
    return after


def apply_inventory_events(
    balances: dict[str, tuple[int, int]],
    events: Iterable[dict[str, object]],
    *,
    last_events: dict[str, tuple[int, int]] | None = None,
    event_counts: dict[str, int] | None = None,
) -> None:
    """Apply one strictly ordered, unique event stream and retain checkpoint state."""

    prior_key: tuple[int, int] | None = None
    identities: set[tuple[int, str, int]] = set()
    for event in events:
        key = (int(event["block_number"]), int(event["log_index"]))
        identity = (key[0], str(event["tx_hash"]), key[1])
        if prior_key is not None and key < prior_key:
            raise ValueError("V3 inventory events are not in block-log order")
        if identity in identities:
            raise ValueError(f"duplicate V3 inventory event: {identity}")
        identities.add(identity)
        if is_physical_inventory_transfer(event):
            apply_inventory_event(balances, event)
            pool = str(event["pool"]).lower()
            if last_events is not None:
                last_events[pool] = key
            if event_counts is not None:
                event_counts[pool] = event_counts.get(pool, 0) + 1
        prior_key = key


def inventory_snapshot_rows(
    *,
    day: str,
    end_block: int,
    statics: dict[str, PoolStatic],
    balances: dict[str, tuple[int, int]],
    last_events: dict[str, tuple[int, int]],
    event_counts: dict[str, int],
) -> list[dict[str, object]]:
    """Materialize an exact day-end inventory checkpoint for every seen pool."""

    rows: list[dict[str, object]] = []
    for pool in sorted(balances):
        if pool not in statics or pool not in last_events or pool not in event_counts:
            raise ValueError(f"incomplete V3 inventory checkpoint state for {pool}")
        static = statics[pool]
        balance0, balance1 = balances[pool]
        last_block, last_log = last_events[pool]
        negative = balance0 < 0 or balance1 < 0
        rows.append(
            {
                "venue": "uniswap_v3",
                "day": day,
                "day_end_block": int(end_block),
                "pool": pool,
                "token0_address": static.token0,
                "token0_symbol": static.symbol0,
                "token0_decimals": static.decimals0,
                "token1_address": static.token1,
                "token1_symbol": static.symbol1,
                "token1_decimals": static.decimals1,
                "balance0_raw": str(balance0),
                "balance1_raw": str(balance1),
                "balance0_units": float(Decimal(balance0) / (Decimal(10) ** static.decimals0)),
                "balance1_units": float(Decimal(balance1) / (Decimal(10) ** static.decimals1)),
                "negative_inventory": negative,
                "replay_arithmetic_valid": not negative,
                "last_event_block": last_block,
                "last_event_log_index": last_log,
                "cumulative_inventory_events": event_counts[pool],
                "quantity_kind": INVENTORY_QUANTITY_KIND,
                "state_generation": INVENTORY_STATE_GENERATION,
                "custody_validation_status": PENDING_CUSTODY_STATUS,
                "ownership_validation_status": PENDING_OWNERSHIP_STATUS,
            }
        )
    return rows


def day_for_block(block: int, days: list[str], end_blocks: list[int]) -> str:
    """Assign a block to the first research day whose inclusive cut contains it."""

    if len(days) != len(end_blocks) or not days:
        raise ValueError("inventory day/block calendar is empty or misaligned")
    if any(right <= left for left, right in zip(end_blocks, end_blocks[1:])):
        raise ValueError("inventory day-end blocks are not strictly increasing")
    position = bisect_left(end_blocks, int(block))
    if position == len(days):
        raise ValueError(f"block {block} lies after the research calendar")
    return days[position]


def balance_of_calldata(holder: str) -> str:
    address = holder.lower().removeprefix("0x")
    if len(address) != 40:
        raise ValueError(f"invalid balanceOf holder address: {holder}")
    return BALANCE_OF_SELECTOR + address.rjust(64, "0")


def decode_balance_of_result(value: object) -> int:
    text = str(value or "")
    if not text.startswith("0x") or len(text) > 66:
        raise ValueError("invalid balanceOf JSON-RPC result")
    return int(text, 16)


def decode_inventory_log(log: dict) -> dict[str, object]:
    """Decode one V3 state or inventory log with explicit transfer semantics."""

    if bool(log.get("removed")):
        raise ValueError("removed log cannot enter canonical V3 inventory")
    topics = [str(value).lower() for value in log.get("topics") or []]
    if not topics or topics[0] not in EVENT_BY_TOPIC:
        raise ValueError("log is not a registered V3 inventory event")
    event_type = EVENT_BY_TOPIC[topics[0]]
    data = bytes.fromhex(str(log.get("data") or "0x").removeprefix("0x"))
    if event_type == "mint":
        _sender, _amount, amount0, amount1 = abi_decode(
            ["address", "uint128", "uint256", "uint256"], data
        )
        delta0, delta1 = int(amount0), int(amount1)
    elif event_type == "burn":
        _amount, amount0, amount1 = abi_decode(
            ["uint128", "uint256", "uint256"], data
        )
        delta0, delta1 = int(amount0), int(amount1)
    elif event_type == "swap":
        amount0, amount1, _sqrt_price, _liquidity, _tick = abi_decode(
            ["int256", "int256", "uint160", "uint128", "int24"], data
        )
        delta0, delta1 = int(amount0), int(amount1)
    elif event_type == "collect":
        _recipient, amount0, amount1 = abi_decode(
            ["address", "uint128", "uint128"], data
        )
        delta0, delta1 = -int(amount0), -int(amount1)
    elif event_type == "flash":
        amount0, amount1, paid0, paid1 = abi_decode(
            ["uint256", "uint256", "uint256", "uint256"], data
        )
        delta0, delta1 = int(paid0) - int(amount0), int(paid1) - int(amount1)
    else:
        amount0, amount1 = abi_decode(["uint128", "uint128"], data)
        delta0, delta1 = -int(amount0), -int(amount1)
    block = rpc_integer(log.get("blockNumber", log.get("block_number")))
    log_index = rpc_integer(log.get("logIndex", log.get("log_index")))
    tx_hash = str(log.get("transactionHash") or log.get("transaction_hash") or "").lower()
    pool = str(log["address"]).lower()
    timestamp_value = log.get("blockTimestamp")
    timestamp = int(str(timestamp_value), 16) if timestamp_value is not None else None
    return {
        "event_type": event_type,
        "pool": pool,
        "block_number": block,
        "log_index": log_index,
        "tx_hash": tx_hash,
        "event_id": f"{tx_hash}:{log_index}",
        "timestamp": timestamp,
        "amount0_delta_raw": delta0,
        "amount1_delta_raw": delta1,
        "physical_inventory_transfer": event_type != "burn",
    }

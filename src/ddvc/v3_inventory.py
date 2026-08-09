"""Uniswap V3 event semantics needed to reconstruct event-accounted pool inventories."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import gzip
import json
from pathlib import Path
from typing import Iterable

from eth_abi import decode as abi_decode
from eth_utils import keccak


EVENT_SIGNATURES = {
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
INVENTORY_STATE_GENERATION = "uniswap_v3_event_replayed_inventory_v1"
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


def block_ranges(start: int, end: int, chunk_size: int) -> list[tuple[int, int]]:
    """Partition an inclusive block perimeter exactly once on aligned boundaries."""

    if start < 0 or end < start or chunk_size <= 0:
        raise ValueError("invalid block-range perimeter")
    ranges: list[tuple[int, int]] = []
    lower = start
    while lower <= end:
        upper = min(((lower // chunk_size) + 1) * chunk_size - 1, end)
        ranges.append((lower, upper))
        lower = upper + 1
    return ranges


def inventory_chunk_paths(lower: int, upper: int, root: Path) -> tuple[Path, Path]:
    stem = f"blocks_{lower:08d}_{upper:08d}"
    return root / f"{stem}.jsonl.gz", root / f"{stem}.meta.json"


def inventory_chunk_completed(
    lower: int,
    upper: int,
    root: Path,
    *,
    event_topics: set[str] | frozenset[str] = frozenset(EVENT_TOPICS.values()),
) -> bool:
    raw, meta = inventory_chunk_paths(lower, upper, root)
    if not raw.is_file() or not meta.is_file():
        return False
    try:
        record = json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        record.get("status") == "complete"
        and int(record.get("from_block", -1)) == lower
        and int(record.get("to_block", -1)) == upper
        and set(record.get("event_topics") or []) == set(event_topics)
    )


def pool_addresses_from_graph(path: Path) -> set[str]:
    """Load the complete immutable V3 pool-address perimeter once."""

    pools: set[str] = set()
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            pool = str(json.loads(line).get("id") or "").lower()
            if not pool.startswith("0x") or len(pool) != 42:
                raise ValueError("V3 immutable pool registry contains an invalid address")
            if pool in pools:
                raise ValueError(f"duplicate V3 immutable pool address: {pool}")
            pools.add(pool)
    if not pools:
        raise RuntimeError("V3 immutable pool registry is empty")
    return pools


def audit_inventory_chunks(
    ranges: Iterable[tuple[int, int]],
    root: Path,
    *,
    known_pools: set[str],
) -> dict[str, int]:
    """Read every raw log and reconcile its exact chunk metadata contract."""

    expected_topics = set(EVENT_TOPICS.values())
    totals = {"chunks": 0, "raw_logs": 0, "recognized_v3_logs": 0}
    for lower, upper in ranges:
        raw_path, meta_path = inventory_chunk_paths(lower, upper, root)
        if not inventory_chunk_completed(lower, upper, root):
            raise RuntimeError(f"incomplete V3 inventory chunk {lower}-{upper}")
        metadata = json.loads(meta_path.read_text())
        keys: set[tuple[int, str, int]] = set()
        raw_logs = 0
        recognized = 0
        by_event = {name: 0 for name in EVENT_TOPICS}
        with gzip.open(raw_path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw = json.loads(line)
                decoded = decode_inventory_log(raw)
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
                if str(decoded["pool"]) in known_pools:
                    recognized += 1
                    by_event[str(decoded["event_type"])] += 1
        if set(metadata.get("event_topics") or []) != expected_topics:
            raise ValueError(f"V3 inventory chunk {lower}-{upper} has a topic perimeter drift")
        if int(metadata.get("raw_logs", -1)) != raw_logs:
            raise ValueError(f"V3 inventory chunk {lower}-{upper} raw row count differs")
        if int(metadata.get("recognized_v3_logs", -1)) != recognized:
            raise ValueError(f"V3 inventory chunk {lower}-{upper} recognized row count differs")
        if int(metadata.get("unrecognized_logs", -1)) != raw_logs - recognized:
            raise ValueError(f"V3 inventory chunk {lower}-{upper} unrecognized row count differs")
        recorded_by_event = {
            str(key): int(value)
            for key, value in (metadata.get("recognized_by_event") or {}).items()
        }
        if recorded_by_event != by_event:
            raise ValueError(f"V3 inventory chunk {lower}-{upper} event counts differ")
        totals["chunks"] += 1
        totals["raw_logs"] += raw_logs
        totals["recognized_v3_logs"] += recognized
    temporaries = list(root.glob(".*.tmp"))
    if temporaries:
        raise RuntimeError(f"V3 inventory raw perimeter contains {len(temporaries):,} temporaries")
    return totals


def _field(record: object, name: str) -> object:
    return record.get(name) if isinstance(record, dict) else getattr(record, name, None)


def decimal_to_raw(value: object, decimals: int) -> int:
    """Convert an exact token-decimal string to raw units without rounding."""

    try:
        scaled = Decimal(str(value)) * (Decimal(10) ** int(decimals))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"invalid token amount {value!r}") from error
    if not scaled.is_finite() or scaled != scaled.to_integral_value():
        raise ValueError(f"token amount {value!r} is not exact at {decimals} decimals")
    return int(scaled)


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


def canonical_inventory_event(record: object, static: PoolStatic) -> dict[str, object] | None:
    """Map one canonical V3 Mint/Swap/Burn row to a physical-balance delta."""

    record_type = str(_field(record, "record_type") or "")
    source_stream = str(_field(record, "source_stream") or "")
    if record_type == "liquidity" and source_stream == "burns":
        return None
    if record_type == "swap":
        event_type = "swap"
    elif record_type == "liquidity" and source_stream == "mints":
        event_type = "mint"
    else:
        return None
    pool = str(_field(record, "pool") or "").lower()
    if pool != static.pool:
        raise ValueError(f"canonical inventory event pool differs from static identity: {pool}")
    block = int(_field(record, "block_number"))
    log_index = int(_field(record, "log_index"))
    tx_hash = str(_field(record, "tx_hash") or "").lower()
    if block <= 0 or log_index < 0 or not tx_hash:
        raise ValueError("canonical inventory event lacks exact block-log identity")
    delta0 = decimal_to_raw(_field(record, "amount0"), static.decimals0)
    delta1 = decimal_to_raw(_field(record, "amount1"), static.decimals1)
    if event_type == "mint" and (delta0 < 0 or delta1 < 0):
        raise ValueError("V3 mint has a negative physical-balance delta")
    return {
        "event_type": event_type,
        "pool": pool,
        "block_number": block,
        "log_index": log_index,
        "tx_hash": tx_hash,
        "event_id": f"{tx_hash}:{log_index}",
        "amount0_delta_raw": delta0,
        "amount1_delta_raw": delta1,
    }


def apply_inventory_event(
    balances: dict[str, tuple[int, int]], event: dict[str, object]
) -> tuple[int, int]:
    """Apply one signed physical-balance event and return the new pool inventory."""

    pool = str(event["pool"]).lower()
    before0, before1 = balances.get(pool, (0, 0))
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
    """Decode one inventory-changing V3 log into signed raw token deltas."""

    if bool(log.get("removed")):
        raise ValueError("removed log cannot enter canonical V3 inventory")
    topics = [str(value).lower() for value in log.get("topics") or []]
    if not topics or topics[0] not in EVENT_BY_TOPIC:
        raise ValueError("log is not a registered V3 inventory event")
    event_type = EVENT_BY_TOPIC[topics[0]]
    data = bytes.fromhex(str(log.get("data") or "0x").removeprefix("0x"))
    if event_type == "collect":
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
    block = int(str(log["blockNumber"]), 16)
    log_index = int(str(log["logIndex"]), 16)
    tx_hash = str(log["transactionHash"]).lower()
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
    }

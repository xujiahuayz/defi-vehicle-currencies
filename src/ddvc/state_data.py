"""Canonical, materialised market-state inputs for empirical runners.

Raw provider JSON is immutable evidence. This module is the only boundary that
translates its source-specific schemas into stable research records. Downstream
replay and quote code reads the materialised partitions, never provider rows.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from ddvc.amounts import human_to_raw
from ddvc.asset_types import canonical_token
from ddvc.paths import DATA_DIR
from ddvc.provenance import cache_key
from ddvc.runtime import atomic_output
from ddvc.source_records import block_value, timestamp_value, transaction_id, v4_pool_quote_supported


SCHEMA_VERSION = 1
CODE_SOURCES = [
    "src/ddvc/state_data.py",
    "src/ddvc/amounts.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/source_records.py",
]
STATE_ENGINE = cache_key(CODE_SOURCES)
STATE_ROOT = DATA_DIR / "processed" / "market_state" / f"engine_{STATE_ENGINE}"
RAW_ROOT = DATA_DIR / "raw" / "thegraph"
QUALITY_COLUMNS = [
    "schema_version",
    "family",
    "venue",
    "day",
    "input_fingerprint",
    "raw_rows",
    "canonical_rows",
    "snapshot_rows",
    "swap_rows",
    "liquidity_rows",
    "usable_rows",
    "missing_order",
    "missing_identity",
    "missing_required_streams",
    "duplicate_events",
    "conflicting_events",
    "invalid_swap_sign",
    "invalid_state",
    "unsupported_state",
    "zero_swap_amounts",
    "missing_quote_statics",
    "quote_supported_swaps",
    "passed",
]
TICK_COLUMNS = [
    "schema_version",
    "venue",
    "day",
    "record_type",
    "source_stream",
    "event_id",
    "tx_hash",
    "block_number",
    "log_index",
    "timestamp",
    "pool",
    "token0_raw",
    "token1_raw",
    "token0",
    "token1",
    "symbol0",
    "symbol1",
    "decimals0",
    "decimals1",
    "fee_pips",
    "tick_spacing",
    "hooks",
    "amount0",
    "amount1",
    "value_usd",
    "sqrt_price_x96",
    "tick",
    "liquidity_delta",
    "tick_lower",
    "tick_upper",
    "quote_supported",
    "usable",
    "unsupported_reason",
]
TICK_STREAMS: dict[str, tuple[tuple[str, str, int], ...]] = {
    "uniswap_v3": (
        ("swaps", "swap", 0),
        ("mints", "liquidity", 1),
        ("burns", "liquidity", -1),
    ),
    "uniswap_v4": (
        ("swaps", "swap", 0),
        ("modify_liquidities", "liquidity", 1),
    ),
}
CP_COLUMNS = [
    "schema_version",
    "venue",
    "day",
    "record_type",
    "source_stream",
    "event_id",
    "tx_hash",
    "block_number",
    "log_index",
    "timestamp",
    "period_start",
    "period_end",
    "pool",
    "token0_raw",
    "token1_raw",
    "token0",
    "token1",
    "symbol0",
    "symbol1",
    "decimals0",
    "decimals1",
    "amount0_delta",
    "amount1_delta",
    "reserve0",
    "reserve1",
    "value_usd",
    "quote_supported",
    "usable",
    "unsupported_reason",
]
CP_STREAMS: dict[str, tuple[tuple[str, str, int], ...]] = {
    "uniswap_v2": (
        ("hourly_reserves", "snapshot", 0),
        ("swaps", "swap", 0),
        ("mints", "liquidity", 1),
        ("burns", "liquidity", -1),
    ),
    "sushiswap_v2": (
        ("hourly_reserves", "snapshot", 0),
        ("swaps", "swap", 0),
    ),
}
MULTI_ASSET_COLUMNS = [
    "schema_version",
    "venue",
    "day",
    "record_type",
    "source_stream",
    "event_id",
    "tx_hash",
    "block_number",
    "log_index",
    "timestamp",
    "pool",
    "pool_type",
    "snapshot_position",
    "token_raw",
    "token",
    "token_symbol",
    "decimals",
    "balance_raw",
    "weight_1e18",
    "fee_1e18",
    "amp_reported",
    "token_in_raw",
    "token_out_raw",
    "token_in",
    "token_out",
    "amount_in_raw",
    "amount_out_raw",
    "balance_delta_raw",
    "value_usd",
    "quote_supported",
    "usable",
    "unsupported_reason",
]
MULTI_ASSET_STREAMS: dict[str, tuple[tuple[str, str, int], ...]] = {
    "curve": (
        ("daily", "snapshot", 0),
        ("swaps", "swap", 0),
    ),
    "balancer": (
        ("daily", "snapshot", 0),
        ("swaps", "swap", 0),
        ("joins_exits", "liquidity", 0),
    ),
}
FAMILY_STREAMS = {
    "tick": TICK_STREAMS,
    "constant_product": CP_STREAMS,
    "multi_asset": MULTI_ASSET_STREAMS,
}


@dataclass(frozen=True)
class StatePartitionQuality:
    schema_version: int
    family: str
    venue: str
    day: str
    input_fingerprint: str
    raw_rows: int
    canonical_rows: int
    snapshot_rows: int
    swap_rows: int
    liquidity_rows: int
    usable_rows: int
    missing_order: int
    missing_identity: int
    missing_required_streams: int
    duplicate_events: int
    conflicting_events: int
    invalid_swap_sign: int
    invalid_state: int
    unsupported_state: int
    zero_swap_amounts: int
    missing_quote_statics: int
    quote_supported_swaps: int
    passed: bool


def quality_counters() -> dict[str, int]:
    """One counter vocabulary shared across every canonical state family."""
    return {
        "raw_rows": 0,
        "snapshot_rows": 0,
        "swap_rows": 0,
        "liquidity_rows": 0,
        "missing_order": 0,
        "missing_identity": 0,
        "missing_required_streams": 0,
        "duplicate_events": 0,
        "conflicting_events": 0,
        "invalid_swap_sign": 0,
        "invalid_state": 0,
        "unsupported_state": 0,
        "zero_swap_amounts": 0,
        "missing_quote_statics": 0,
        "quote_supported_swaps": 0,
    }


def finish_quality(
    *,
    family: str,
    venue: str,
    day: str,
    inputs: list[Path],
    frame: pd.DataFrame,
    counters: dict[str, int],
) -> StatePartitionQuality:
    # Every malformed source record is retained but marked unusable. A partition is
    # ambiguous only when two different payloads claim the same causal identity;
    # unlike a quarantined row, retaining either conflicting payload could poison state.
    hard_failures = counters["conflicting_events"] + counters["missing_required_streams"]
    return StatePartitionQuality(
        schema_version=SCHEMA_VERSION,
        family=family,
        venue=venue,
        day=day,
        input_fingerprint=partition_input_fingerprint(inputs),
        canonical_rows=len(frame),
        usable_rows=int(frame["usable"].sum()) if not frame.empty else 0,
        passed=hard_failures == 0,
        **counters,
    )


def raw_stream_path(raw_root: Path, venue: str, stream: str, day: str) -> Path:
    return raw_root / venue / f"{venue}_{stream}_{day}.jsonl.gz"


def state_partition_path(
    family: str,
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
) -> Path:
    return root / family / venue / f"{day}.parquet"


def state_quality_path(
    family: str,
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
) -> Path:
    return root / family / venue / f"{day}.quality.json"


def available_state_days(
    family: str,
    venue: str,
    *,
    root: Path = STATE_ROOT,
) -> list[str]:
    """Days with both a materialised partition and its quality marker."""
    if family not in FAMILY_STREAMS or venue not in FAMILY_STREAMS[family]:
        raise ValueError(f"unsupported canonical state family/venue: {family}/{venue}")
    directory = root / family / venue
    return sorted(
        path.stem
        for path in directory.glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].parquet")
        if path.with_suffix(".quality.json").exists()
    )


def tick_partition_path(venue: str, day: str, *, root: Path = STATE_ROOT) -> Path:
    return state_partition_path("tick", venue, day, root=root)


def tick_quality_path(venue: str, day: str, *, root: Path = STATE_ROOT) -> Path:
    return state_quality_path("tick", venue, day, root=root)


def cp_partition_path(venue: str, day: str, *, root: Path = STATE_ROOT) -> Path:
    return state_partition_path("constant_product", venue, day, root=root)


def cp_quality_path(venue: str, day: str, *, root: Path = STATE_ROOT) -> Path:
    return state_quality_path("constant_product", venue, day, root=root)


def multi_asset_partition_path(venue: str, day: str, *, root: Path = STATE_ROOT) -> Path:
    return state_partition_path("multi_asset", venue, day, root=root)


def multi_asset_quality_path(venue: str, day: str, *, root: Path = STATE_ROOT) -> Path:
    return state_quality_path("multi_asset", venue, day, root=root)


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    return str(value) if value is not None and value != "" else None


def _stream_inputs(raw_root: Path, family: str, venue: str, day: str) -> list[Path]:
    return [
        raw_stream_path(raw_root, venue, stream, day)
        for stream, _kind, _sign in FAMILY_STREAMS[family][venue]
        if raw_stream_path(raw_root, venue, stream, day).exists()
    ]


def _missing_stream_count(raw_root: Path, family: str, venue: str, day: str) -> int:
    return sum(
        not raw_stream_path(raw_root, venue, stream, day).exists()
        for stream, _kind, _sign in FAMILY_STREAMS[family][venue]
    )


def partition_input_fingerprint(paths: list[Path]) -> str:
    """Cheap partition identity; raw files are immutable and atomically replaced."""
    digest = hashlib.sha256()
    for path in sorted(paths):
        stat = path.stat()
        digest.update(path.name.encode())
        digest.update(str(stat.st_size).encode())
        digest.update(str(stat.st_mtime_ns).encode())
    return digest.hexdigest()


def _swap_sign(amount0: object, amount1: object) -> str:
    try:
        first, second = Decimal(str(amount0)), Decimal(str(amount1))
    except (InvalidOperation, TypeError, ValueError):
        return "invalid"
    if first == 0 or second == 0:
        return "zero"
    return "valid" if first * second < 0 else "invalid"


def _normalise_tick_row(
    row: dict,
    *,
    venue: str,
    day: str,
    stream: str,
    record_type: str,
    liquidity_sign: int,
) -> tuple[dict[str, object], dict[str, bool]]:
    pool = row.get("pool") or {}
    token0 = pool.get("token0") or {}
    token1 = pool.get("token1") or {}
    raw0 = str(token0.get("id") or "").lower()
    raw1 = str(token1.get("id") or "").lower()
    canonical0 = canonical_token(raw0) if raw0 else None
    canonical1 = canonical_token(raw1) if raw1 else None
    block = block_value(row)
    log_index = _optional_int(row.get("logIndex"))
    timestamp = timestamp_value(row)
    tx_hash = transaction_id(row)
    pool_id = str(pool.get("id") or "").lower()
    missing_order = block is None or block <= 0 or log_index is None or log_index < 0
    missing_identity = (
        not tx_hash
        or not pool_id
        or timestamp is None
        or (record_type == "swap" and (not raw0 or not raw1))
    )
    sign_state = _swap_sign(row.get("amount0"), row.get("amount1")) if record_type == "swap" else "valid"
    missing_statics = False
    if record_type == "swap" and venue == "uniswap_v4":
        missing_statics = any(
            pool.get(field) in (None, "")
            for field in ("feeTier", "tickSpacing", "hooks")
        ) or any(token.get("decimals") in (None, "") for token in (token0, token1))
    quote_supported = bool(
        record_type == "swap"
        and sign_state == "valid"
        and not missing_order
        and not missing_identity
        and (venue != "uniswap_v4" or v4_pool_quote_supported(row))
    )
    reasons: list[str] = []
    if missing_order:
        reasons.append("missing_block_log_order")
    if missing_identity:
        reasons.append("missing_event_identity")
    if sign_state == "invalid":
        reasons.append("invalid_swap_sign")
    elif sign_state == "zero":
        reasons.append("zero_swap_amounts")
    if missing_statics:
        reasons.append("missing_quote_statics")
    usable = not missing_order and not missing_identity and sign_state != "invalid"
    liquidity_delta = None
    if record_type == "liquidity":
        try:
            liquidity_delta = str(liquidity_sign * int(row.get("amount") or 0))
        except (TypeError, ValueError):
            reasons.append("invalid_liquidity_delta")
            usable = False
    normalised = {
        "schema_version": SCHEMA_VERSION,
        "venue": venue,
        "day": day,
        "record_type": record_type,
        "source_stream": stream,
        "event_id": _text(row.get("id")),
        "tx_hash": str(tx_hash).lower() if tx_hash else None,
        "block_number": block,
        "log_index": log_index,
        "timestamp": timestamp,
        "pool": pool_id or None,
        "token0_raw": raw0 or None,
        "token1_raw": raw1 or None,
        "token0": canonical0,
        "token1": canonical1,
        "symbol0": _text(token0.get("symbol")),
        "symbol1": _text(token1.get("symbol")),
        "decimals0": _optional_int(token0.get("decimals")),
        "decimals1": _optional_int(token1.get("decimals")),
        "fee_pips": _optional_int(pool.get("feeTier")),
        "tick_spacing": _optional_int(pool.get("tickSpacing")),
        "hooks": _text(pool.get("hooks")),
        "amount0": _text(row.get("amount0")),
        "amount1": _text(row.get("amount1")),
        "value_usd": _text(row.get("amountUSD")),
        "sqrt_price_x96": _text(row.get("sqrtPriceX96") or row.get("sqrtPrice")),
        "tick": _optional_int(row.get("tick")),
        "liquidity_delta": liquidity_delta,
        "tick_lower": _optional_int(row.get("tickLower")),
        "tick_upper": _optional_int(row.get("tickUpper")),
        "quote_supported": quote_supported,
        "usable": usable,
        "unsupported_reason": "|".join(reasons) if reasons else None,
    }
    flags = {
        "missing_order": missing_order,
        "missing_identity": missing_identity,
        "invalid_swap_sign": sign_state == "invalid",
        "invalid_state": False,
        "unsupported_state": False,
        "zero_swap_amounts": sign_state == "zero",
        "missing_quote_statics": missing_statics,
    }
    return normalised, flags


def normalise_tick_partition(
    raw_root: Path,
    venue: str,
    day: str,
) -> tuple[pd.DataFrame, StatePartitionQuality]:
    """Normalise and audit one concentrated-liquidity venue-day."""
    if venue not in TICK_STREAMS:
        raise ValueError(f"unsupported tick venue: {venue}")
    inputs = _stream_inputs(raw_root, "tick", venue, day)
    rows: list[dict[str, object]] = []
    counters = quality_counters()
    counters["missing_required_streams"] = _missing_stream_count(
        raw_root, "tick", venue, day
    )
    by_order: dict[tuple[int, int], dict[str, object]] = {}
    for stream, record_type, sign in TICK_STREAMS[venue]:
        path = raw_stream_path(raw_root, venue, stream, day)
        if not path.exists():
            continue
        with gzip.open(path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                counters["raw_rows"] += 1
                source = json.loads(line)
                record, flags = _normalise_tick_row(
                    source,
                    venue=venue,
                    day=day,
                    stream=stream,
                    record_type=record_type,
                    liquidity_sign=sign,
                )
                counters[f"{record_type}_rows"] += 1
                for name, flagged in flags.items():
                    counters[name] += int(flagged)
                counters["quote_supported_swaps"] += int(record["quote_supported"])
                if record["block_number"] is not None and record["log_index"] is not None:
                    key = (int(record["block_number"]), int(record["log_index"]))
                    prior = by_order.get(key)
                    if prior is not None:
                        comparable = {k: v for k, v in record.items() if k != "event_id"}
                        prior_comparable = {k: v for k, v in prior.items() if k != "event_id"}
                        if comparable == prior_comparable:
                            counters["duplicate_events"] += 1
                        else:
                            counters["conflicting_events"] += 1
                        continue
                    by_order[key] = record
                rows.append(record)
    frame = pd.DataFrame(rows, columns=TICK_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["block_number", "log_index", "record_type", "event_id"],
            na_position="last",
            kind="stable",
        ).reset_index(drop=True)
        for column in (
            "schema_version",
            "block_number",
            "log_index",
            "timestamp",
            "decimals0",
            "decimals1",
            "fee_pips",
            "tick_spacing",
            "tick",
            "tick_lower",
            "tick_upper",
        ):
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    quality = finish_quality(
        family="tick",
        venue=venue,
        day=day,
        inputs=inputs,
        frame=frame,
        counters=counters,
    )
    return frame, quality


def _decimal_text(value: object) -> str | None:
    try:
        return format(Decimal(str(value)), "f")
    except (InvalidOperation, TypeError, ValueError):
        return None


def _cp_swap_delta(row: dict) -> tuple[str | None, str | None, str]:
    try:
        amount0_in = Decimal(str(row.get("amount0In") or "0"))
        amount0_out = Decimal(str(row.get("amount0Out") or "0"))
        amount1_in = Decimal(str(row.get("amount1In") or "0"))
        amount1_out = Decimal(str(row.get("amount1Out") or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return None, None, "invalid"
    if min(amount0_in, amount0_out, amount1_in, amount1_out) < 0:
        return None, None, "invalid"
    delta0 = amount0_in - amount0_out
    delta1 = amount1_in - amount1_out
    if delta0 == 0 or delta1 == 0:
        state = "zero"
    else:
        state = "valid" if delta0 * delta1 < 0 else "invalid"
    return format(delta0, "f"), format(delta1, "f"), state


def _normalise_cp_row(
    row: dict,
    *,
    venue: str,
    day: str,
    stream: str,
    record_type: str,
    liquidity_sign: int,
) -> tuple[dict[str, object], dict[str, bool]]:
    pair = row.get("pair") or {}
    token0 = pair.get("token0") or {}
    token1 = pair.get("token1") or {}
    raw0 = str(token0.get("id") or "").lower()
    raw1 = str(token1.get("id") or "").lower()
    canonical0 = canonical_token(raw0) if raw0 else None
    canonical1 = canonical_token(raw1) if raw1 else None
    pool = str(pair.get("id") or "").lower()
    period_start = _optional_int(row.get("hourStartUnix")) if record_type == "snapshot" else None
    period_end = period_start + 3600 if period_start is not None else None
    timestamp = period_end if record_type == "snapshot" else timestamp_value(row)
    block = None if record_type == "snapshot" else block_value(row)
    log_index = None if record_type == "snapshot" else _optional_int(row.get("logIndex"))
    tx_hash = None if record_type == "snapshot" else transaction_id(row)
    known_incomplete = bool(record_type == "liquidity" and row.get("needsComplete"))
    missing_order = bool(
        record_type != "snapshot"
        and not known_incomplete
        and (block is None or block <= 0 or log_index is None or log_index < 0)
    )
    missing_identity = bool(
        not pool
        or timestamp is None
        or not raw0
        or not raw1
        or (record_type != "snapshot" and not tx_hash)
    )
    missing_statics = False
    amount0_delta = amount1_delta = reserve0 = reserve1 = None
    sign_state = "valid"
    invalid_state = False
    if record_type == "swap":
        amount0_delta, amount1_delta, sign_state = _cp_swap_delta(row)
    elif record_type == "liquidity":
        amount0 = None if known_incomplete else _decimal_text(row.get("amount0"))
        amount1 = None if known_incomplete else _decimal_text(row.get("amount1"))
        if known_incomplete:
            pass
        elif amount0 is None or amount1 is None:
            invalid_state = True
        else:
            first, second = Decimal(amount0), Decimal(amount1)
            if first < 0 or second < 0:
                invalid_state = True
            amount0_delta = format(liquidity_sign * first, "f")
            amount1_delta = format(liquidity_sign * second, "f")
    else:
        reserve0 = _decimal_text(row.get("reserve0"))
        reserve1 = _decimal_text(row.get("reserve1"))
        if reserve0 is None or reserve1 is None:
            invalid_state = True
        else:
            invalid_state = Decimal(reserve0) < 0 or Decimal(reserve1) < 0
    zero_amounts = bool(record_type == "swap" and sign_state == "zero")
    unsupported_state = bool(known_incomplete or (record_type == "swap" and sign_state != "valid"))
    snapshot_supported = bool(
        record_type == "snapshot"
        and reserve0 is not None
        and reserve1 is not None
        and Decimal(reserve0) > 0
        and Decimal(reserve1) > 0
    )
    quote_supported = bool(
        (snapshot_supported or (record_type == "swap" and sign_state == "valid"))
        and not missing_order
        and not missing_identity
        and not invalid_state
        and not unsupported_state
    )
    reasons: list[str] = []
    if missing_order:
        reasons.append("missing_block_log_order")
    if missing_identity:
        reasons.append("missing_event_identity")
    if missing_statics:
        reasons.append("missing_quote_statics")
    if sign_state == "invalid":
        reasons.append("invalid_swap_sign")
    elif zero_amounts:
        reasons.append("zero_swap_amounts")
    if invalid_state:
        reasons.append("invalid_state")
    if known_incomplete:
        reasons.append("incomplete_liquidity_event")
    if record_type == "snapshot" and not invalid_state and not snapshot_supported:
        reasons.append("empty_reserve_state")
    usable = not any((missing_order, missing_identity, invalid_state, unsupported_state))
    record = {
        "schema_version": SCHEMA_VERSION,
        "venue": venue,
        "day": day,
        "record_type": record_type,
        "source_stream": stream,
        "event_id": _text(row.get("id")),
        "tx_hash": str(tx_hash).lower() if tx_hash else None,
        "block_number": block,
        "log_index": log_index,
        "timestamp": timestamp,
        "period_start": period_start,
        "period_end": period_end,
        "pool": pool or None,
        "token0_raw": raw0 or None,
        "token1_raw": raw1 or None,
        "token0": canonical0,
        "token1": canonical1,
        "symbol0": _text(token0.get("symbol")),
        "symbol1": _text(token1.get("symbol")),
        "decimals0": _optional_int(token0.get("decimals")),
        "decimals1": _optional_int(token1.get("decimals")),
        "amount0_delta": amount0_delta,
        "amount1_delta": amount1_delta,
        "reserve0": reserve0,
        "reserve1": reserve1,
        "value_usd": _text(row.get("amountUSD") or row.get("hourlyVolumeUSD")),
        "quote_supported": quote_supported,
        "usable": usable,
        "unsupported_reason": "|".join(reasons) if reasons else None,
    }
    flags = {
        "missing_order": missing_order,
        "missing_identity": missing_identity,
        "invalid_swap_sign": sign_state == "invalid",
        "invalid_state": invalid_state,
        "unsupported_state": unsupported_state,
        "zero_swap_amounts": zero_amounts,
        "missing_quote_statics": missing_statics,
    }
    return record, flags


def normalise_cp_partition(
    raw_root: Path,
    venue: str,
    day: str,
) -> tuple[pd.DataFrame, StatePartitionQuality]:
    """Normalise and audit one constant-product venue-day."""
    if venue not in CP_STREAMS:
        raise ValueError(f"unsupported constant-product venue: {venue}")
    inputs = _stream_inputs(raw_root, "constant_product", venue, day)
    rows: list[dict[str, object]] = []
    counters = quality_counters()
    counters["missing_required_streams"] = _missing_stream_count(
        raw_root, "constant_product", venue, day
    )
    event_orders: dict[tuple[int, int], dict[str, object]] = {}
    snapshot_keys: dict[tuple[str, int], dict[str, object]] = {}
    for stream, record_type, sign in CP_STREAMS[venue]:
        path = raw_stream_path(raw_root, venue, stream, day)
        if not path.exists():
            continue
        with gzip.open(path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                counters["raw_rows"] += 1
                record, flags = _normalise_cp_row(
                    json.loads(line),
                    venue=venue,
                    day=day,
                    stream=stream,
                    record_type=record_type,
                    liquidity_sign=sign,
                )
                counters[f"{record_type}_rows"] += 1
                for name, flagged in flags.items():
                    counters[name] += int(flagged)
                counters["quote_supported_swaps"] += int(
                    record_type == "swap" and record["quote_supported"]
                )
                if record_type == "snapshot" and record["pool"] and record["period_start"] is not None:
                    key = (str(record["pool"]), int(record["period_start"]))
                    prior = snapshot_keys.get(key)
                    snapshot_keys[key] = record
                elif record["block_number"] is not None and record["log_index"] is not None:
                    key = (int(record["block_number"]), int(record["log_index"]))
                    prior = event_orders.get(key)
                    event_orders[key] = record
                else:
                    prior = None
                if prior is not None:
                    comparable = {name: value for name, value in record.items() if name != "event_id"}
                    prior_comparable = {name: value for name, value in prior.items() if name != "event_id"}
                    if comparable == prior_comparable:
                        counters["duplicate_events"] += 1
                    else:
                        counters["conflicting_events"] += 1
                    continue
                rows.append(record)
    frame = pd.DataFrame(rows, columns=CP_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["timestamp", "block_number", "log_index", "record_type", "event_id"],
            na_position="first",
            kind="stable",
        ).reset_index(drop=True)
        for column in (
            "schema_version",
            "block_number",
            "log_index",
            "timestamp",
            "period_start",
            "period_end",
            "decimals0",
            "decimals1",
        ):
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    quality = finish_quality(
        family="constant_product",
        venue=venue,
        day=day,
        inputs=inputs,
        frame=frame,
        counters=counters,
    )
    return frame, quality


def _event_log_index(row: dict, venue: str) -> int | None:
    explicit = _optional_int(row.get("logIndex"))
    if explicit is not None:
        return explicit
    if venue != "balancer":
        return None
    event_id = str(row.get("id") or "")
    if len(event_id) <= 66:
        return 0
    suffix = event_id[66:].lstrip("-#")
    return _optional_int(suffix)


def _multi_base(
    *,
    venue: str,
    day: str,
    record_type: str,
    stream: str,
    row: dict,
    pool: str,
    pool_type: str | None,
    timestamp: int | None,
    tx_hash: str | None = None,
    block: int | None = None,
    log_index: int | None = None,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "venue": venue,
        "day": day,
        "record_type": record_type,
        "source_stream": stream,
        "event_id": _text(row.get("id")),
        "tx_hash": tx_hash,
        "block_number": block,
        "log_index": log_index,
        "timestamp": timestamp,
        "pool": pool or None,
        "pool_type": pool_type,
        "snapshot_position": "closing_identified" if record_type == "snapshot_token" else None,
        "token_raw": None,
        "token": None,
        "token_symbol": None,
        "decimals": None,
        "balance_raw": None,
        "weight_1e18": None,
        "fee_1e18": None,
        "amp_reported": None,
        "token_in_raw": None,
        "token_out_raw": None,
        "token_in": None,
        "token_out": None,
        "amount_in_raw": None,
        "amount_out_raw": None,
        "balance_delta_raw": None,
        "value_usd": None,
        "quote_supported": False,
        "usable": False,
        "unsupported_reason": None,
    }


def _multi_snapshot_records(
    row: dict,
    *,
    venue: str,
    day: str,
) -> tuple[list[dict[str, object]], dict[str, bool], dict[str, object] | None]:
    pool_data = row.get("pool") or {}
    pool = str(pool_data.get("id") or "").lower()
    timestamp = timestamp_value(row)
    pool_type = _text(pool_data.get("poolType") or pool_data.get("symbol"))
    if venue == "curve":
        tokens = pool_data.get("inputTokens") or []
        raw_balances = row.get("inputTokenBalances") or []
        state_absent = not raw_balances
        token_order = [str(token.get("id") or "").lower() for token in tokens]
        balance_by_token = dict(zip(token_order, raw_balances)) if len(tokens) == len(raw_balances) else {}
        fee = None
        amp = _text(pool_data.get("amp"))
    else:
        tokens = pool_data.get("tokens") or []
        token_order = [str(token).lower() for token in (pool_data.get("tokensList") or [])]
        human_balances = row.get("amounts") or []
        state_absent = not human_balances
        human_by_token = dict(zip(token_order, human_balances)) if len(token_order) == len(human_balances) else {}
        balance_by_token = {}
        for token in tokens:
            address = str(token.get("address") or "").lower()
            decimals = _optional_int(token.get("decimals"))
            balance_by_token[address] = (
                human_to_raw(human_by_token.get(address), decimals)
                if decimals is not None and address in human_by_token
                else None
            )
        fee = human_to_raw(pool_data.get("swapFee"), 18)
        amp = _text(pool_data.get("amp"))
    invalid_state = bool(
        not pool
        or timestamp is None
        or not tokens
        or (
            not state_absent
            and (
                len(balance_by_token) != len(tokens)
                or len(set(token_order)) != len(token_order)
            )
        )
    )
    missing_statics = False
    records: list[dict[str, object]] = []
    meta_tokens: dict[str, dict[str, object]] = {}
    for token_data in tokens:
        raw_token = str(token_data.get("id") or token_data.get("address") or "").lower()
        decimals = _optional_int(token_data.get("decimals"))
        balance = balance_by_token.get(raw_token)
        weight = human_to_raw(token_data.get("weight"), 18) if token_data.get("weight") is not None else None
        token_invalid = bool(
            not state_absent
            and (
                not raw_token
                or balance is None
                or _decimal_text(balance) is None
                or Decimal(str(balance or 0)) < 0
            )
        )
        invalid_state = invalid_state or token_invalid
        missing_statics = missing_statics or (not state_absent and decimals is None)
        record = _multi_base(
            venue=venue,
            day=day,
            record_type="snapshot_token",
            stream="daily",
            row=row,
            pool=pool,
            pool_type=pool_type,
            timestamp=timestamp,
        )
        record.update(
            {
                "token_raw": raw_token or None,
                "token": canonical_token(raw_token) if raw_token else None,
                "token_symbol": _text(token_data.get("symbol")),
                "decimals": decimals,
                "balance_raw": _text(balance),
                "weight_1e18": weight,
                "fee_1e18": fee,
                "amp_reported": amp,
                "value_usd": _text(row.get("dailyVolumeUSD") or row.get("swapVolume")),
                "quote_supported": bool(
                    not state_absent
                    and not token_invalid
                    and Decimal(str(balance)) > 0
                ),
                "usable": bool(
                    not state_absent
                    and not token_invalid
                    and decimals is not None
                ),
            }
        )
        records.append(record)
        if raw_token:
            meta_tokens[raw_token] = {
                "decimals": decimals,
                "symbol": _text(token_data.get("symbol")),
            }
    reasons: list[str] = []
    if invalid_state:
        reasons.append("invalid_state")
    if state_absent:
        reasons.append("missing_snapshot_state")
    if missing_statics:
        reasons.append("missing_quote_statics")
    reason = "|".join(reasons) if reasons else None
    for record in records:
        if reason:
            record["unsupported_reason"] = reason
            record["usable"] = False
            record["quote_supported"] = False
    meta = None
    if pool and not state_absent and not invalid_state and not missing_statics:
        meta = {
            "pool_type": pool_type,
            "tokens": meta_tokens,
            "fee_1e18": fee,
            "amp_reported": amp,
        }
    return records, {
        "missing_order": False,
        "missing_identity": not pool or timestamp is None,
        "invalid_swap_sign": False,
        "invalid_state": invalid_state,
        "unsupported_state": state_absent,
        "zero_swap_amounts": False,
        "missing_quote_statics": missing_statics,
    }, meta


def _multi_swap_record(
    row: dict,
    *,
    venue: str,
    day: str,
    pool_meta: dict[str, dict[str, object]],
) -> tuple[dict[str, object], dict[str, bool]]:
    pool_data = row.get("pool") or row.get("poolId") or {}
    pool = str(pool_data.get("id") or "").lower()
    meta = pool_meta.get(pool)
    token_in_data = row.get("tokenIn") or {}
    token_out_data = row.get("tokenOut") or {}
    token_in = str(
        (token_in_data.get("id") or "") if isinstance(token_in_data, dict) else (token_in_data or "")
    ).lower()
    token_out = str(
        (token_out_data.get("id") or "") if isinstance(token_out_data, dict) else (token_out_data or "")
    ).lower()
    block = block_value(row)
    log_index = _event_log_index(row, venue)
    timestamp = timestamp_value(row)
    tx_hash = str(transaction_id(row) or row.get("hash") or row.get("tx") or "").lower()
    missing_order = block is None or block <= 0 or log_index is None or log_index < 0
    missing_identity = not pool or not token_in or not token_out or not tx_hash or timestamp is None
    unsupported_state = meta is None or token_in not in (meta or {}).get("tokens", {}) or token_out not in (meta or {}).get("tokens", {})
    amount_in = row.get("amountIn") if venue == "curve" else row.get("tokenAmountIn")
    amount_out = row.get("amountOut") if venue == "curve" else row.get("tokenAmountOut")
    if venue == "balancer" and not unsupported_state:
        decimals_in = int(meta["tokens"][token_in]["decimals"])
        decimals_out = int(meta["tokens"][token_out]["decimals"])
        amount_in = human_to_raw(amount_in, decimals_in)
        amount_out = human_to_raw(amount_out, decimals_out)
    else:
        amount_in = _text(amount_in)
        amount_out = _text(amount_out)
    invalid_state = bool(
        amount_in is None
        or amount_out is None
        or _decimal_text(amount_in) is None
        or _decimal_text(amount_out) is None
        or Decimal(str(amount_in or 0)) < 0
        or Decimal(str(amount_out or 0)) < 0
    )
    zero_amounts = bool(
        not invalid_state and (Decimal(str(amount_in)) == 0 or Decimal(str(amount_out)) == 0)
    )
    reasons: list[str] = []
    if missing_order:
        reasons.append("missing_block_log_order")
    if missing_identity:
        reasons.append("missing_event_identity")
    if unsupported_state:
        reasons.append("missing_day_snapshot")
    if invalid_state:
        reasons.append("invalid_state")
    elif zero_amounts:
        reasons.append("zero_swap_amounts")
    usable = not any((missing_order, missing_identity, unsupported_state, invalid_state))
    record = _multi_base(
        venue=venue,
        day=day,
        record_type="swap",
        stream="swaps",
        row=row,
        pool=pool,
        pool_type=_text((meta or {}).get("pool_type")),
        timestamp=timestamp,
        tx_hash=tx_hash or None,
        block=block,
        log_index=log_index,
    )
    record.update(
        {
            "fee_1e18": (meta or {}).get("fee_1e18"),
            "amp_reported": (meta or {}).get("amp_reported"),
            "token_in_raw": token_in or None,
            "token_out_raw": token_out or None,
            "token_in": canonical_token(token_in) if token_in else None,
            "token_out": canonical_token(token_out) if token_out else None,
            "amount_in_raw": amount_in,
            "amount_out_raw": amount_out,
            "value_usd": _text(row.get("valueUSD") or row.get("amountInUSD") or row.get("amountOutUSD")),
            "quote_supported": usable and not zero_amounts,
            "usable": usable,
            "unsupported_reason": "|".join(reasons) if reasons else None,
        }
    )
    return record, {
        "missing_order": missing_order,
        "missing_identity": missing_identity,
        "invalid_swap_sign": False,
        "invalid_state": invalid_state,
        "unsupported_state": unsupported_state,
        "zero_swap_amounts": zero_amounts,
        "missing_quote_statics": False,
    }


def _balancer_liquidity_records(
    row: dict,
    *,
    day: str,
    pool_meta: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, bool]]:
    pool_data = row.get("pool") or {}
    pool = str(pool_data.get("id") or "").lower()
    meta = pool_meta.get(pool)
    token_order = [str(value).lower() for value in (pool_data.get("tokensList") or [])]
    amounts = row.get("amounts") or []
    block = block_value(row)
    log_index = _event_log_index(row, "balancer")
    timestamp = timestamp_value(row)
    tx_hash = str(transaction_id(row) or row.get("tx") or "").lower()
    missing_order = block is None or block <= 0 or log_index is None or log_index < 0
    missing_identity = not pool or not tx_hash or timestamp is None
    unsupported_state = meta is None or any(token not in (meta or {}).get("tokens", {}) for token in token_order)
    invalid_state = not token_order or len(token_order) != len(amounts) or len(set(token_order)) != len(token_order)
    sign = -1 if str(row.get("type") or "").lower() == "exit" else 1
    records: list[dict[str, object]] = []
    for token, amount in zip(token_order, amounts):
        decimals = None if unsupported_state else _optional_int(meta["tokens"][token]["decimals"])
        raw_amount = human_to_raw(amount, decimals) if decimals is not None else None
        token_invalid = bool(
            not unsupported_state
            and (raw_amount is None or Decimal(str(raw_amount or 0)) < 0)
        )
        invalid_state = invalid_state or token_invalid
        record = _multi_base(
            venue="balancer",
            day=day,
            record_type="liquidity_token",
            stream="joins_exits",
            row=row,
            pool=pool,
            pool_type=_text((meta or {}).get("pool_type")),
            timestamp=timestamp,
            tx_hash=tx_hash or None,
            block=block,
            log_index=log_index,
        )
        record.update(
            {
                "token_raw": token or None,
                "token": canonical_token(token) if token else None,
                "token_symbol": _text((meta or {}).get("tokens", {}).get(token, {}).get("symbol")),
                "decimals": decimals,
                "balance_delta_raw": format(sign * Decimal(str(raw_amount)), "f") if raw_amount is not None else None,
                "value_usd": _text(row.get("valueUSD")),
                "usable": not any((missing_order, missing_identity, unsupported_state, token_invalid)),
            }
        )
        records.append(record)
    reasons: list[str] = []
    if missing_order:
        reasons.append("missing_block_log_order")
    if missing_identity:
        reasons.append("missing_event_identity")
    if unsupported_state:
        reasons.append("missing_day_snapshot")
    if invalid_state:
        reasons.append("invalid_state")
    reason = "|".join(reasons) if reasons else None
    for record in records:
        if reason:
            record["unsupported_reason"] = reason
            record["usable"] = False
    return records, {
        "missing_order": missing_order,
        "missing_identity": missing_identity,
        "invalid_swap_sign": False,
        "invalid_state": invalid_state,
        "unsupported_state": unsupported_state,
        "zero_swap_amounts": False,
        "missing_quote_statics": False,
    }


def normalise_multi_asset_partition(
    raw_root: Path,
    venue: str,
    day: str,
) -> tuple[pd.DataFrame, StatePartitionQuality]:
    """Normalise Curve or Balancer snapshots and ordered state changes."""
    if venue not in MULTI_ASSET_STREAMS:
        raise ValueError(f"unsupported multi-asset venue: {venue}")
    inputs = _stream_inputs(raw_root, "multi_asset", venue, day)
    rows: list[dict[str, object]] = []
    counters = quality_counters()
    counters["missing_required_streams"] = _missing_stream_count(
        raw_root, "multi_asset", venue, day
    )
    pool_meta: dict[str, dict[str, object]] = {}
    snapshot_path = raw_stream_path(raw_root, venue, "daily", day)
    if snapshot_path.exists():
        with gzip.open(snapshot_path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                counters["raw_rows"] += 1
                counters["snapshot_rows"] += 1
                records, flags, meta = _multi_snapshot_records(json.loads(line), venue=venue, day=day)
                for name, flagged in flags.items():
                    counters[name] += int(flagged)
                rows.extend(records)
                if meta is not None and records:
                    pool_meta[str(records[0]["pool"])] = meta
    event_orders: dict[tuple[int, int], str] = {}
    for stream, record_type, _sign in MULTI_ASSET_STREAMS[venue][1:]:
        path = raw_stream_path(raw_root, venue, stream, day)
        if not path.exists():
            continue
        with gzip.open(path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                source = json.loads(line)
                counters["raw_rows"] += 1
                counters[f"{record_type}_rows"] += 1
                if record_type == "swap":
                    records_and_flags = _multi_swap_record(source, venue=venue, day=day, pool_meta=pool_meta)
                    records, flags = [records_and_flags[0]], records_and_flags[1]
                else:
                    records, flags = _balancer_liquidity_records(source, day=day, pool_meta=pool_meta)
                for name, flagged in flags.items():
                    counters[name] += int(flagged)
                counters["quote_supported_swaps"] += int(
                    record_type == "swap" and records and records[0]["quote_supported"]
                )
                if records and records[0]["block_number"] is not None and records[0]["log_index"] is not None:
                    key = (int(records[0]["block_number"]), int(records[0]["log_index"]))
                    fingerprint = json.dumps(records, sort_keys=True, default=str)
                    prior = event_orders.get(key)
                    if prior is not None:
                        if prior == fingerprint:
                            counters["duplicate_events"] += 1
                        else:
                            counters["conflicting_events"] += 1
                        continue
                    event_orders[key] = fingerprint
                rows.extend(records)
    frame = pd.DataFrame(rows, columns=MULTI_ASSET_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(
            ["timestamp", "block_number", "log_index", "record_type", "event_id", "token_raw"],
            na_position="first",
            kind="stable",
        ).reset_index(drop=True)
        for column in (
            "schema_version",
            "block_number",
            "log_index",
            "timestamp",
            "decimals",
        ):
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    quality = finish_quality(
        family="multi_asset",
        venue=venue,
        day=day,
        inputs=inputs,
        frame=frame,
        counters=counters,
    )
    return frame, quality


def _write_state_partition(
    frame: pd.DataFrame,
    quality: StatePartitionQuality,
    panel_path: Path,
    marker_path: Path,
) -> StatePartitionQuality:
    with atomic_output(panel_path) as temporary:
        frame.to_parquet(temporary, index=False)
    with atomic_output(marker_path) as temporary:
        temporary.write_text(
            json.dumps(asdict(quality), allow_nan=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return quality


def _read_state_quality(
    *,
    marker: Path,
    panel: Path,
    inputs: list[Path],
) -> StatePartitionQuality | None:
    if not marker.exists() or not panel.exists():
        return None
    quality = StatePartitionQuality(**json.loads(marker.read_text(encoding="utf-8")))
    current = partition_input_fingerprint(inputs)
    if quality.schema_version != SCHEMA_VERSION or quality.input_fingerprint != current:
        return None
    return quality


def _read_state_partition(
    path: Path,
    columns: list[str],
    *,
    family: str,
    current_input_fingerprint: str,
    include_quarantined: bool,
    allow_failed_partition: bool,
) -> pd.DataFrame:
    marker = path.with_suffix(".quality.json")
    if not marker.exists():
        raise ValueError(f"canonical {family} quality marker missing: {path}")
    quality = StatePartitionQuality(**json.loads(marker.read_text(encoding="utf-8")))
    if quality.input_fingerprint != current_input_fingerprint:
        raise ValueError(f"canonical {family} partition is stale against its source inputs: {path}")
    if not allow_failed_partition and not quality.passed:
        raise ValueError(f"canonical {family} partition failed its identity gate: {path}")
    frame = pd.read_parquet(path)
    if list(frame.columns) != columns:
        raise ValueError(f"canonical {family} schema mismatch: {path}")
    if not frame.empty and set(frame["schema_version"]) != {SCHEMA_VERSION}:
        raise ValueError(f"canonical {family} schema version mismatch: {path}")
    if not include_quarantined and not frame.empty:
        frame = frame[frame["usable"]].reset_index(drop=True)
    return frame


def write_tick_partition(
    raw_root: Path,
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
) -> StatePartitionQuality:
    frame, quality = normalise_tick_partition(raw_root, venue, day)
    return _write_state_partition(
        frame,
        quality,
        tick_partition_path(venue, day, root=root),
        tick_quality_path(venue, day, root=root),
    )


def read_tick_quality(
    raw_root: Path,
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
) -> StatePartitionQuality | None:
    return _read_state_quality(
        marker=tick_quality_path(venue, day, root=root),
        panel=tick_partition_path(venue, day, root=root),
        inputs=_stream_inputs(raw_root, "tick", venue, day),
    )


def read_tick_partition(
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
    raw_root: Path = RAW_ROOT,
    include_quarantined: bool = False,
    allow_failed_partition: bool = False,
) -> pd.DataFrame:
    path = tick_partition_path(venue, day, root=root)
    return _read_state_partition(
        path,
        TICK_COLUMNS,
        family="tick",
        current_input_fingerprint=partition_input_fingerprint(
            _stream_inputs(raw_root, "tick", venue, day)
        ),
        include_quarantined=include_quarantined,
        allow_failed_partition=allow_failed_partition,
    )


def write_cp_partition(
    raw_root: Path,
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
) -> StatePartitionQuality:
    frame, quality = normalise_cp_partition(raw_root, venue, day)
    return _write_state_partition(
        frame,
        quality,
        cp_partition_path(venue, day, root=root),
        cp_quality_path(venue, day, root=root),
    )


def read_cp_quality(
    raw_root: Path,
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
) -> StatePartitionQuality | None:
    return _read_state_quality(
        marker=cp_quality_path(venue, day, root=root),
        panel=cp_partition_path(venue, day, root=root),
        inputs=_stream_inputs(raw_root, "constant_product", venue, day),
    )


def read_cp_partition(
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
    raw_root: Path = RAW_ROOT,
    include_quarantined: bool = False,
    allow_failed_partition: bool = False,
) -> pd.DataFrame:
    path = cp_partition_path(venue, day, root=root)
    return _read_state_partition(
        path,
        CP_COLUMNS,
        family="constant-product",
        current_input_fingerprint=partition_input_fingerprint(
            _stream_inputs(raw_root, "constant_product", venue, day)
        ),
        include_quarantined=include_quarantined,
        allow_failed_partition=allow_failed_partition,
    )


def write_multi_asset_partition(
    raw_root: Path,
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
) -> StatePartitionQuality:
    frame, quality = normalise_multi_asset_partition(raw_root, venue, day)
    return _write_state_partition(
        frame,
        quality,
        multi_asset_partition_path(venue, day, root=root),
        multi_asset_quality_path(venue, day, root=root),
    )


def read_multi_asset_quality(
    raw_root: Path,
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
) -> StatePartitionQuality | None:
    return _read_state_quality(
        marker=multi_asset_quality_path(venue, day, root=root),
        panel=multi_asset_partition_path(venue, day, root=root),
        inputs=_stream_inputs(raw_root, "multi_asset", venue, day),
    )


def read_multi_asset_partition(
    venue: str,
    day: str,
    *,
    root: Path = STATE_ROOT,
    raw_root: Path = RAW_ROOT,
    include_quarantined: bool = False,
    allow_failed_partition: bool = False,
) -> pd.DataFrame:
    path = multi_asset_partition_path(venue, day, root=root)
    return _read_state_partition(
        path,
        MULTI_ASSET_COLUMNS,
        family="multi-asset",
        current_input_fingerprint=partition_input_fingerprint(
            _stream_inputs(raw_root, "multi_asset", venue, day)
        ),
        include_quarantined=include_quarantined,
        allow_failed_partition=allow_failed_partition,
    )

"""Exact UTC day-end block calendar for physical Uniswap V3 inventory replay."""

from __future__ import annotations

from concurrent.futures import as_completed
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

import pandas as pd

from ddvc.fetch.raw import write_json
from ddvc.paths import DATA_DIR, SHARED_RUNTIME_DIR
from ddvc.provenance import require_current_artifacts, stamp
from ddvc.quoter import Throttled, rpc_post
from ddvc.runtime import atomic_output, interruptible_thread_pool
from ddvc.state_data import available_state_days


RAW_DAY_CUT_ROOT = DATA_DIR / "raw" / "ethereum" / "uniswap_v3_inventory_day_cuts"
V3_GRAPH_ROOT = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
CALENDAR = DATA_DIR / "processed" / "v3_inventory_day_calendar.parquet"
CALENDAR_LOCK = SHARED_RUNTIME_DIR / "v3-inventory-day-calendar.lock"
CODE_SOURCES = [
    "src/ddvc/v3_inventory_calendar.py",
    "src/ddvc/fetch/raw.py",
    "src/ddvc/paths.py",
    "src/ddvc/quoter.py",
    "src/ddvc/runtime.py",
    "src/ddvc/state_data.py",
]
RPC_CALL_MAX_ATTEMPTS = 12


def last_block_before_timestamp(
    target_timestamp: int,
    lower_block: int,
    upper_block: int,
    timestamp_for_block,
) -> tuple[int, int, int]:
    """Resolve the last block strictly before a UTC cut from a valid bracket."""

    target = int(target_timestamp)
    lower = int(lower_block)
    upper = int(upper_block)
    if lower < 0 or upper <= lower:
        raise ValueError("invalid block bracket")
    lower_timestamp = int(timestamp_for_block(lower))
    upper_timestamp = int(timestamp_for_block(upper))
    if not lower_timestamp < target <= upper_timestamp:
        raise ValueError(
            f"block bracket does not straddle timestamp {target}: "
            f"{lower}={lower_timestamp}, {upper}={upper_timestamp}"
        )
    while upper - lower > 1:
        midpoint = (lower + upper) // 2
        if int(timestamp_for_block(midpoint)) < target:
            lower = midpoint
        else:
            upper = midpoint
    return lower, int(timestamp_for_block(lower)), int(timestamp_for_block(upper))


def raw_day_metadata(day: str) -> dict[str, object]:
    path = V3_GRAPH_ROOT / f"uniswap_v3_meta_{day}.json"
    if not path.is_file():
        raise RuntimeError(f"V3 day {day} lacks raw block metadata")
    return json.loads(path.read_text())


def _target_timestamp(day: str) -> int:
    current = datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
    return int((current + timedelta(days=1)).timestamp())


def _day_cut_path(day: str) -> Path:
    return RAW_DAY_CUT_ROOT / f"{day}.json"


def _cached_day_cut(day: str, target_timestamp: int) -> dict[str, object] | None:
    path = _day_cut_path(day)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text())
        return record if (
            record.get("status") == "complete"
            and record.get("day") == day
            and int(record.get("target_timestamp", -1)) == target_timestamp
            and int(record.get("day_end_block_timestamp", target_timestamp)) < target_timestamp
            and int(record.get("next_block_timestamp", -1)) >= target_timestamp
            and int(record.get("next_block", -1)) == int(record.get("day_end_block", -1)) + 1
        ) else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _fetch_block_timestamp(block: int, evidence: list[dict[str, object]]) -> int:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": [hex(block), False],
    }
    for attempt in range(RPC_CALL_MAX_ATTEMPTS):
        try:
            response = rpc_post(
                payload,
                timeout=30,
                retries=1,
                retry_json_errors=True,
            )
            break
        except Throttled:
            if attempt == RPC_CALL_MAX_ATTEMPTS - 1:
                raise
            time.sleep(min(2 ** attempt, 30))
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict) or result.get("timestamp") is None:
        raise RuntimeError(f"historical Ethereum block {block} lacks a timestamp")
    returned_block = int(str(result.get("number")), 16)
    if returned_block != block:
        raise ValueError(f"Ethereum RPC returned block {returned_block} for requested {block}")
    timestamp = int(str(result["timestamp"]), 16)
    evidence.append(
        {
            "request": payload,
            "response": {
                "number": result.get("number"),
                "hash": result.get("hash"),
                "parentHash": result.get("parentHash"),
                "timestamp": result.get("timestamp"),
            },
        }
    )
    return timestamp


def _resolve_day_cut(day: str, lower: int, upper: int) -> dict[str, object]:
    target = _target_timestamp(day)
    cached = _cached_day_cut(day, target)
    if cached is not None:
        return cached
    evidence: list[dict[str, object]] = []
    timestamps: dict[int, int] = {}

    def timestamp_for_block(block: int) -> int:
        if block not in timestamps:
            timestamps[block] = _fetch_block_timestamp(block, evidence)
        return timestamps[block]

    if timestamp_for_block(lower) >= target:
        raise RuntimeError(f"V3 metadata lower bracket for {day} is not inside the UTC day")
    expansion = max(1_000, upper - lower)
    while timestamp_for_block(upper) < target:
        upper += expansion
        expansion *= 2
    block, block_timestamp, next_timestamp = last_block_before_timestamp(
        target,
        lower,
        upper,
        timestamp_for_block,
    )
    record = {
        "status": "complete",
        "day": day,
        "target_timestamp": target,
        "day_end_block": block,
        "day_end_block_timestamp": block_timestamp,
        "next_block": block + 1,
        "next_block_timestamp": next_timestamp,
        "initial_lower_bracket": lower,
        "resolved_upper_bracket": upper,
        "rpc_evidence": evidence,
    }
    write_json(_day_cut_path(day), record)
    return record


def build_day_calendar(*, workers: int = 2) -> tuple[int, int, int]:
    days = available_state_days("tick", "uniswap_v3")
    if not days:
        raise RuntimeError("canonical V3 state calendar is empty")
    metadata = [raw_day_metadata(day) for day in days]
    brackets = []
    for index, day in enumerate(days):
        lower_value = metadata[index].get("max_block")
        upper_value = (
            metadata[index + 1].get("min_block")
            if index + 1 < len(days)
            else metadata[index].get("head_block_at_fetch")
        )
        if lower_value is None or upper_value is None:
            raise RuntimeError(f"V3 day {day} lacks a block bracket for its UTC cut")
        brackets.append((day, int(lower_value), int(upper_value)))
    RAW_DAY_CUT_ROOT.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    with interruptible_thread_pool(max_workers=max(1, min(workers, 4))) as executor:
        futures = {
            executor.submit(_resolve_day_cut, day, lower, upper): day
            for day, lower, upper in brackets
        }
        for index, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if index % 100 == 0 or index == len(futures):
                print(f"  exact V3 day cuts [{index:,}/{len(futures):,}]", flush=True)
    frame = pd.DataFrame.from_records(records).sort_values("day").reset_index(drop=True)
    if frame["day"].tolist() != days:
        raise RuntimeError("exact V3 day calendar differs from the canonical state calendar")
    end_blocks = frame["day_end_block"].astype("int64").tolist()
    if any(right <= left for left, right in zip(end_blocks, end_blocks[1:])):
        raise RuntimeError("exact V3 day-end block cuts are not strictly increasing")
    columns = [
        "day",
        "target_timestamp",
        "day_end_block",
        "day_end_block_timestamp",
        "next_block",
        "next_block_timestamp",
        "initial_lower_bracket",
        "resolved_upper_bracket",
    ]
    with atomic_output(CALENDAR) as temporary:
        frame[columns].to_parquet(temporary, index=False)
    stamp(
        CALENDAR,
        code_sources=CODE_SOURCES,
        inputs=[V3_GRAPH_ROOT, RAW_DAY_CUT_ROOT],
        rows=len(frame),
        notes="exact UTC day-end Ethereum block calendar; raw RPC evidence persisted per cut",
    )
    return len(frame), end_blocks[0], end_blocks[-1]


def load_day_calendar() -> tuple[list[str], list[int]]:
    require_current_artifacts([CALENDAR], consumer="V3 physical-inventory replay")
    frame = pd.read_parquet(CALENDAR)
    days = frame["day"].astype(str).tolist()
    end_blocks = frame["day_end_block"].astype("int64").tolist()
    expected = available_state_days("tick", "uniswap_v3")
    if days != expected:
        raise RuntimeError("exact V3 day calendar differs from the canonical state calendar")
    if any(right <= left for left, right in zip(end_blocks, end_blocks[1:])):
        raise RuntimeError("exact V3 day-end block cuts are not strictly increasing")
    return days, end_blocks

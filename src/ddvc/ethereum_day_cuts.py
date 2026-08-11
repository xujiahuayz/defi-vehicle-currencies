"""Exact Ethereum block boundaries for UTC-day event audits."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from typing import Callable

from ddvc.ethereum_blocks import block_header_payload, request_block_header
from ddvc.fetch.raw import write_json
from ddvc.paths import DATA_DIR
from ddvc.quoter import Throttled, rpc_post


RPC_CALL_MAX_ATTEMPTS = 12
RAW_DAY_BOUND_ROOT = DATA_DIR / "raw" / "ethereum" / "utc_day_block_bounds"
UTC_DAY_BLOCK_CALENDAR = DATA_DIR / "processed" / "ethereum_utc_day_calendar.parquet"


def day_bound_path(day: str, *, root: Path | None = None) -> Path:
    return (root or RAW_DAY_BOUND_ROOT) / f"{day}.json"


def load_utc_day_block_bounds(day: str, *, root: Path | None = None) -> dict[str, object]:
    path = day_bound_path(day, root=root)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") != "complete":
            raise ValueError("incomplete UTC block-bound record")
        validate_utc_day_block_bounds(record, day)
        return record
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"missing or invalid exact UTC block bounds for {day}") from exc


def load_or_resolve_utc_day_block_bounds(
    day: str,
    upper_block: int | Callable[[], int],
    *,
    fetch: bool,
    root: Path | None = None,
    lower_block: int | Callable[[], int] = 0,
    previous_record: dict[str, object] | None = None,
    rpc_request=rpc_post,
    sleeper=time.sleep,
) -> dict[str, object]:
    """Load one exact UTC perimeter or resolve it against a known-later block."""

    try:
        return load_utc_day_block_bounds(day, root=root)
    except RuntimeError:
        if not fetch:
            raise
    resolved_lower = int(lower_block() if callable(lower_block) else lower_block)
    resolved_upper = int(upper_block() if callable(upper_block) else upper_block)
    evidence: list[dict[str, object]] = []
    timestamps: dict[int, int] = {}

    def timestamp_for_block(block: int) -> int:
        if block not in timestamps:
            timestamps[block] = fetch_block_timestamp(
                block,
                evidence,
                rpc_request=rpc_request,
                sleeper=sleeper,
            )
        return timestamps[block]

    adjacent_seed = _adjacent_day_boundary_seed(day, previous_record)
    if adjacent_seed is None:
        bounds = utc_day_block_bounds(day, resolved_lower, resolved_upper, timestamp_for_block)
    else:
        timestamps.update(adjacent_seed["timestamps"])
        evidence.extend(adjacent_seed["evidence"])
        bounds = _utc_day_block_bounds_from_previous(
            day,
            adjacent_seed["record"],
            resolved_upper,
            timestamp_for_block,
        )
    record = {"status": "complete", **bounds, "rpc_evidence": evidence}
    validate_utc_day_block_bounds(record, day)
    path = day_bound_path(day, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    return record


def _adjacent_day_boundary_seed(
    day: str,
    previous_record: dict[str, object] | None,
) -> dict[str, object] | None:
    """Return a validated exact boundary seed for the immediately prior UTC day."""

    if previous_record is None:
        return None
    try:
        current = datetime.strptime(day, "%Y%m%d")
        previous_day = (current - timedelta(days=1)).strftime("%Y%m%d")
        validate_utc_day_block_bounds(previous_record, previous_day)
        end_block = int(previous_record["end_block"])
        after_end_block = int(previous_record["after_end_block"])
        evidence_by_block: dict[int, dict[str, object]] = {}
        for item in previous_record["rpc_evidence"]:
            request = item["request"]
            requested = int(str(request["params"][0]), 16)
            if requested in {end_block, after_end_block}:
                evidence_by_block[requested] = item
        end_evidence = evidence_by_block[end_block]
        after_end_evidence = evidence_by_block[after_end_block]
        start_timestamp, _ = utc_day_timestamps(day)
        if (
            int(previous_record["end_timestamp"]) != start_timestamp
            or int(previous_record["after_end_block"]) != int(previous_record["end_block"]) + 1
        ):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "record": previous_record,
        "timestamps": {
            end_block: int(previous_record["end_block_timestamp"]),
            after_end_block: int(previous_record["after_end_block_timestamp"]),
        },
        "evidence": [deepcopy(end_evidence), deepcopy(after_end_evidence)],
    }


def _utc_day_block_bounds_from_previous(
    day: str,
    previous_record: dict[str, object],
    upper_block: int,
    timestamp_for_block: Callable[[int], int],
) -> dict[str, int | str]:
    """Resolve one UTC day from the exact closing boundary of its predecessor."""

    start_timestamp, end_timestamp = utc_day_timestamps(day)
    before_start = int(previous_record["end_block"])
    start_block = int(previous_record["after_end_block"])
    prior_day_blocks = int(previous_record["end_block"]) - int(previous_record["start_block"]) + 1
    if prior_day_blocks < 1 or int(upper_block) <= before_start:
        raise ValueError("invalid adjacent-day block bracket")
    candidate_upper = min(int(upper_block), before_start + 2 * prior_day_blocks)
    while int(timestamp_for_block(candidate_upper)) < end_timestamp and candidate_upper < int(upper_block):
        next_upper = min(int(upper_block), before_start + 2 * (candidate_upper - before_start))
        if next_upper <= candidate_upper:
            break
        candidate_upper = next_upper
    end_block, end_block_timestamp, after_end_timestamp = last_block_before_timestamp(
        end_timestamp,
        before_start,
        candidate_upper,
        timestamp_for_block,
    )
    return {
        "day": day,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "start_block": start_block,
        "start_block_timestamp": int(previous_record["after_end_block_timestamp"]),
        "end_block": end_block,
        "end_block_timestamp": end_block_timestamp,
        "before_start_block": before_start,
        "before_start_block_timestamp": int(previous_record["end_block_timestamp"]),
        "after_end_block": end_block + 1,
        "after_end_block_timestamp": after_end_timestamp,
        "initial_lower_bracket": before_start,
        "initial_upper_bracket": candidate_upper,
    }


def utc_day_timestamps(day: str) -> tuple[int, int]:
    start = datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def last_block_before_timestamp(
    target_timestamp: int,
    lower_block: int,
    upper_block: int,
    timestamp_for_block: Callable[[int], int],
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


def fetch_block_timestamp(
    block: int,
    evidence: list[dict[str, object]],
    *,
    rpc_request=rpc_post,
    sleeper=time.sleep,
    max_attempts: int = RPC_CALL_MAX_ATTEMPTS,
) -> int:
    """Fetch one exact block timestamp and retain its auditable RPC response."""

    payload = block_header_payload(block)
    header: dict[str, object] | None = None
    for attempt in range(max_attempts):
        try:
            header = request_block_header(
                block,
                rpc_request=rpc_request,
                retries=1,
            )
            break
        except Throttled:
            if attempt == max_attempts - 1:
                raise
            sleeper(min(2**attempt, 30))
    if header is None:
        raise RuntimeError(f"historical Ethereum block {block} lacks a timestamp")
    timestamp = int(header["timestamp"])
    evidence.append(
        {
            "request": payload,
            "response": {
                "number": hex(int(header["block_number"])),
                "hash": header["block_hash"],
                "parentHash": header["parent_hash"],
                "timestamp": hex(timestamp),
            },
        }
    )
    return timestamp


def utc_day_block_bounds(
    day: str,
    lower_block: int,
    upper_block: int,
    timestamp_for_block: Callable[[int], int],
) -> dict[str, int | str]:
    """Return the exact inclusive Ethereum block perimeter for one UTC day."""

    start_timestamp, end_timestamp = utc_day_timestamps(day)
    before_start, before_start_timestamp, start_block_timestamp = last_block_before_timestamp(
        start_timestamp,
        lower_block,
        upper_block,
        timestamp_for_block,
    )
    end_block, end_block_timestamp, after_end_timestamp = last_block_before_timestamp(
        end_timestamp,
        before_start,
        upper_block,
        timestamp_for_block,
    )
    return {
        "day": day,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "start_block": before_start + 1,
        "start_block_timestamp": start_block_timestamp,
        "end_block": end_block,
        "end_block_timestamp": end_block_timestamp,
        "before_start_block": before_start,
        "before_start_block_timestamp": before_start_timestamp,
        "after_end_block": end_block + 1,
        "after_end_block_timestamp": after_end_timestamp,
        "initial_lower_bracket": int(lower_block),
        "initial_upper_bracket": int(upper_block),
    }


def validate_utc_day_block_bounds(record: dict[str, object], day: str) -> None:
    """Fail closed unless a persisted record proves both UTC boundaries exactly."""

    start_timestamp, end_timestamp = utc_day_timestamps(day)
    expected = {
        "day": day,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError(f"stale UTC block-bound record for {day}")
    start_block = int(record["start_block"])
    end_block = int(record["end_block"])
    if start_block > end_block:
        raise ValueError(f"empty or inverted Ethereum block perimeter for {day}")
    if int(record["before_start_block"]) + 1 != start_block:
        raise ValueError(f"non-adjacent UTC start boundary for {day}")
    if int(record["after_end_block"]) != end_block + 1:
        raise ValueError(f"non-adjacent UTC end boundary for {day}")
    if not (
        int(record["before_start_block_timestamp"]) < start_timestamp
        <= int(record["start_block_timestamp"])
        and int(record["end_block_timestamp"]) < end_timestamp
        <= int(record["after_end_block_timestamp"])
    ):
        raise ValueError(f"unproved UTC timestamp boundaries for {day}")
    evidence = record.get("rpc_evidence")
    if not isinstance(evidence, list):
        raise ValueError(f"UTC block-bound record lacks RPC evidence for {day}")
    observed: dict[int, int] = {}
    observed_hashes: dict[int, str] = {}
    observed_parents: dict[int, str] = {}
    for item in evidence:
        request = item.get("request") if isinstance(item, dict) else None
        response = item.get("response") if isinstance(item, dict) else None
        if not isinstance(request, dict) or not isinstance(response, dict):
            raise ValueError(f"malformed UTC block-bound RPC evidence for {day}")
        params = request.get("params")
        if request.get("method") != "eth_getBlockByNumber" or not isinstance(params, list) or not params:
            raise ValueError(f"wrong RPC method in UTC block-bound evidence for {day}")
        requested = int(str(params[0]), 16)
        returned = int(str(response.get("number")), 16)
        if returned != requested:
            raise ValueError(f"mismatched block identity in UTC block-bound evidence for {day}")
        block_hash = str(response.get("hash") or "").lower()
        parent_hash = str(response.get("parentHash") or "").lower()
        if not block_hash.startswith("0x") or not parent_hash.startswith("0x"):
            raise ValueError(f"missing block hashes in UTC block-bound evidence for {day}")
        observed[returned] = int(str(response.get("timestamp")), 16)
        observed_hashes[returned] = block_hash
        observed_parents[returned] = parent_hash
    required_evidence = {
        int(record["before_start_block"]): int(record["before_start_block_timestamp"]),
        int(record["start_block"]): int(record["start_block_timestamp"]),
        int(record["end_block"]): int(record["end_block_timestamp"]),
        int(record["after_end_block"]): int(record["after_end_block_timestamp"]),
    }
    if any(observed.get(block) != timestamp for block, timestamp in required_evidence.items()):
        raise ValueError(f"UTC block-bound RPC evidence is incomplete for {day}")
    before_start_block = int(record["before_start_block"])
    start_block = int(record["start_block"])
    end_block = int(record["end_block"])
    after_end_block = int(record["after_end_block"])
    if (
        observed_parents.get(start_block) != observed_hashes.get(before_start_block)
        or observed_parents.get(after_end_block) != observed_hashes.get(end_block)
    ):
        raise ValueError(f"UTC block-bound RPC evidence breaks parent linkage for {day}")

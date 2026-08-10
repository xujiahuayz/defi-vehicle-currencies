"""Exact Ethereum block boundaries for UTC-day event audits."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from typing import Callable

from ddvc.quoter import Throttled, rpc_post


RPC_CALL_MAX_ATTEMPTS = 12


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

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": [hex(block), False],
    }
    response: object | None = None
    for attempt in range(max_attempts):
        try:
            response = rpc_request(
                payload,
                timeout=30,
                retries=1,
                retry_json_errors=True,
            )
            break
        except Throttled:
            if attempt == max_attempts - 1:
                raise
            sleeper(min(2**attempt, 30))
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
        if not str(response.get("hash") or "").startswith("0x") or not str(
            response.get("parentHash") or ""
        ).startswith("0x"):
            raise ValueError(f"missing block hashes in UTC block-bound evidence for {day}")
        observed[returned] = int(str(response.get("timestamp")), 16)
    required_evidence = {
        int(record["before_start_block"]): int(record["before_start_block_timestamp"]),
        int(record["start_block"]): int(record["start_block_timestamp"]),
        int(record["end_block"]): int(record["end_block_timestamp"]),
        int(record["after_end_block"]): int(record["after_end_block_timestamp"]),
    }
    if any(observed.get(block) != timestamp for block, timestamp in required_evidence.items()):
        raise ValueError(f"UTC block-bound RPC evidence is incomplete for {day}")

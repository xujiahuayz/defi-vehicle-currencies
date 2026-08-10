#!/usr/bin/env python3
"""Build the chain-wide exact UTC-day block calendar used by neutral samplers."""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from datetime import datetime, timedelta
import json
from pathlib import Path

import pandas as pd

from ddvc.data_release import require_node_d_release
from ddvc.ethereum_day_cuts import (
    RAW_DAY_BOUND_ROOT,
    UTC_DAY_BLOCK_CALENDAR,
    load_or_resolve_utc_day_block_bounds,
    load_utc_day_block_bounds,
    utc_day_timestamps,
    validate_utc_day_block_bounds,
)
from ddvc.fetch.raw import write_json
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.provenance import stamp
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.release_calendar import released_route_days
from ddvc.runtime import atomic_output, bounded_workers, exclusive_job, interruptible_thread_pool
from ddvc.v3_inventory_calendar import RAW_DAY_CUT_ROOT


GRAPH_ROOT = DATA_DIR / "raw" / "thegraph"
GRAPH_VENUES = ("uniswap_v1", "uniswap_v2", "uniswap_v3")
CODE_SOURCES = [
    "scripts/build_ethereum_day_calendar.py",
    "src/ddvc/ethereum_day_cuts.py",
    "src/ddvc/fetch/raw.py",
    "src/ddvc/release_calendar.py",
]
CALENDAR_COLUMNS = [
    "day",
    "start_timestamp",
    "end_timestamp",
    "start_block",
    "start_block_timestamp",
    "end_block",
    "end_block_timestamp",
    "before_start_block",
    "before_start_block_timestamp",
    "after_end_block",
    "after_end_block_timestamp",
]


def _previous_day(day: str) -> str:
    return (datetime.strptime(day, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")


def _v3_cut(day: str) -> dict[str, object] | None:
    path = RAW_DAY_CUT_ROOT / f"{day}.json"
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    target = utc_day_timestamps(day)[1]
    if not (
        record.get("status") == "complete"
        and record.get("day") == day
        and int(record.get("target_timestamp", -1)) == target
        and int(record.get("day_end_block", -1)) + 1 == int(record.get("next_block", -2))
        and int(record.get("day_end_block_timestamp", target)) < target
        <= int(record.get("next_block_timestamp", -1))
        and isinstance(record.get("rpc_evidence"), list)
    ):
        return None
    return record


def promote_adjacent_v3_cuts(day: str) -> dict[str, object] | None:
    previous = _v3_cut(_previous_day(day))
    current = _v3_cut(day)
    if previous is None or current is None:
        return None
    start_timestamp, end_timestamp = utc_day_timestamps(day)
    if int(previous["target_timestamp"]) != start_timestamp:
        return None
    record = {
        "status": "complete",
        "day": day,
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "start_block": int(previous["next_block"]),
        "start_block_timestamp": int(previous["next_block_timestamp"]),
        "end_block": int(current["day_end_block"]),
        "end_block_timestamp": int(current["day_end_block_timestamp"]),
        "before_start_block": int(previous["day_end_block"]),
        "before_start_block_timestamp": int(previous["day_end_block_timestamp"]),
        "after_end_block": int(current["next_block"]),
        "after_end_block_timestamp": int(current["next_block_timestamp"]),
        "initial_lower_bracket": int(previous.get("initial_lower_bracket", previous["day_end_block"])),
        "initial_upper_bracket": int(current.get("resolved_upper_bracket", current["next_block"])),
        "rpc_evidence": [*previous["rpc_evidence"], *current["rpc_evidence"]],
        "promoted_from": "uniswap_v3_inventory_day_cuts",
    }
    validate_utc_day_block_bounds(record, day)
    path = RAW_DAY_BOUND_ROOT / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    return record


def graph_head_upper(day: str) -> int:
    upper_blocks: list[int] = []
    for venue in GRAPH_VENUES:
        path = GRAPH_ROOT / venue / f"{venue}_meta_{day}.json"
        if not path.is_file():
            continue
        metadata = json.loads(path.read_text(encoding="utf-8"))
        value = metadata.get("head_block_at_fetch")
        if value is not None:
            upper_blocks.append(int(value))
    if not upper_blocks:
        raise RuntimeError(f"no raw metadata supplies an upper block bracket for {day}")
    return max(upper_blocks)


def resolve_day(day: str, *, fetch: bool) -> dict[str, object]:
    try:
        return load_utc_day_block_bounds(day)
    except RuntimeError:
        promoted = promote_adjacent_v3_cuts(day)
        if promoted is not None:
            return promoted
    return load_or_resolve_utc_day_block_bounds(
        day,
        graph_head_upper(day),
        fetch=fetch,
    )


def build_calendar(days: list[str], *, fetch: bool, workers: int) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    with interruptible_thread_pool(max_workers=bounded_workers(workers, maximum=4)) as executor:
        futures = {executor.submit(resolve_day, day, fetch=fetch): day for day in days}
        for index, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if index % 100 == 0 or index == len(futures):
                print(f"  exact UTC day bounds [{index:,}/{len(futures):,}]", flush=True)
    frame = pd.DataFrame.from_records(records, columns=CALENDAR_COLUMNS).sort_values("day").reset_index(drop=True)
    if frame["day"].tolist() != days:
        raise RuntimeError("Ethereum UTC calendar differs from the released route calendar")
    if frame["day"].duplicated().any():
        raise RuntimeError("Ethereum UTC calendar contains duplicate days")
    starts = frame["start_block"].astype("int64").tolist()
    ends = frame["end_block"].astype("int64").tolist()
    if any(start > end for start, end in zip(starts, ends)):
        raise RuntimeError("Ethereum UTC calendar contains an inverted day")
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args()
    require_node_d_release(routes=True)
    days = released_route_days(UNIFIED_QUALITY_PANEL, nonempty=True)
    with exclusive_job(RAW_MARKET_DATA_LOCK, job="exact Ethereum UTC-day calendar"):
        frame = build_calendar(days, fetch=not args.no_fetch, workers=args.workers)
        with atomic_output(UTC_DAY_BLOCK_CALENDAR) as temporary:
            frame.to_parquet(temporary, index=False)
        stamp(
            UTC_DAY_BLOCK_CALENDAR,
            code_sources=CODE_SOURCES,
            inputs=[UNIFIED_QUALITY_PANEL, RAW_DAY_BOUND_ROOT],
            rows=len(frame),
            notes="exact chain-wide UTC-day Ethereum block perimeter for neutral sampling",
        )
    print(f"PASS: exact Ethereum UTC calendar days={len(frame):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

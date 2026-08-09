#!/usr/bin/env python3
"""Reconstruct exact day-end Uniswap V3 physical pool inventories from events."""

from __future__ import annotations

import argparse
from bisect import bisect_left
from contextlib import ExitStack
import gzip
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.fetch.raw import write_json
from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.paths import (
    DATA_DIR,
    MARKET_STATE_LOCK,
    RAW_MARKET_DATA_LOCK,
)
from ddvc.provenance import cache_key, sidecar_path, stamp
from ddvc.runtime import atomic_output, exclusive_job
from ddvc.state_data import STATE_ROOT, available_state_days, read_tick_partition
from ddvc.v3_inventory import (
    INVENTORY_STATE_GENERATION,
    PoolStatic,
    apply_inventory_events,
    audit_inventory_chunks,
    block_ranges,
    canonical_inventory_event,
    canonical_inventory_start_block,
    decode_inventory_log,
    inventory_chunk_completed,
    inventory_chunk_paths,
    inventory_snapshot_rows,
    pool_addresses_from_graph,
    pool_static_from_graph,
)
from ddvc.v3_inventory_calendar import (
    CALENDAR,
    CALENDAR_LOCK,
    V3_GRAPH_ROOT,
    build_day_calendar,
    load_day_calendar,
    raw_day_metadata,
)


RAW_INVENTORY_ROOT = DATA_DIR / "raw" / "ethereum" / "uniswap_v3_inventory_events"
STATIC_PATH = V3_GRAPH_ROOT / "uniswap_v3_pool_statics_20260630.jsonl.gz"
CACHE_ROOT = STATE_ROOT.parent / "_v3_pool_inventory_day_cache"
OUT = DATA_DIR / "processed" / "v3_pool_inventory_daily.parquet"
CHUNK_SIZE = 1_000
CODE_SOURCES = [
    "scripts/build_v3_inventory_panel.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/fetch/raw.py",
    "src/ddvc/v3_inventory.py",
    "src/ddvc/panel_assembly.py",
    "src/ddvc/paths.py",
    "src/ddvc/runtime.py",
    "src/ddvc/state_data.py",
    "src/ddvc/v3_inventory_calendar.py",
]
INPUTS = [
    STATE_ROOT / "tick" / "uniswap_v3",
    RAW_INVENTORY_ROOT,
    V3_GRAPH_ROOT,
    CALENDAR,
]

RAW_EVENT_SCHEMA = pa.schema(
    [
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("pool", pa.string(), nullable=False),
        pa.field("block_number", pa.int64(), nullable=False),
        pa.field("log_index", pa.int64(), nullable=False),
        pa.field("tx_hash", pa.string(), nullable=False),
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("amount0_delta_raw", pa.string(), nullable=False),
        pa.field("amount1_delta_raw", pa.string(), nullable=False),
    ]
)

INVENTORY_SCHEMA = pa.schema(
    [
        pa.field("venue", pa.string(), nullable=False),
        pa.field("day", pa.string(), nullable=False),
        pa.field("day_end_block", pa.int64(), nullable=False),
        pa.field("pool", pa.string(), nullable=False),
        pa.field("token0_address", pa.string(), nullable=False),
        pa.field("token0_symbol", pa.string(), nullable=False),
        pa.field("token0_decimals", pa.int16(), nullable=False),
        pa.field("token1_address", pa.string(), nullable=False),
        pa.field("token1_symbol", pa.string(), nullable=False),
        pa.field("token1_decimals", pa.int16(), nullable=False),
        pa.field("balance0_raw", pa.string(), nullable=False),
        pa.field("balance1_raw", pa.string(), nullable=False),
        pa.field("balance0_units", pa.float64(), nullable=False),
        pa.field("balance1_units", pa.float64(), nullable=False),
        pa.field("negative_inventory", pa.bool_(), nullable=False),
        pa.field("replay_arithmetic_valid", pa.bool_(), nullable=False),
        pa.field("last_event_block", pa.int64(), nullable=False),
        pa.field("last_event_log_index", pa.int64(), nullable=False),
        pa.field("cumulative_inventory_events", pa.int64(), nullable=False),
        pa.field("quantity_kind", pa.string(), nullable=False),
        pa.field("state_generation", pa.string(), nullable=False),
        pa.field("custody_validation_status", pa.string(), nullable=False),
        pa.field("ownership_validation_status", pa.string(), nullable=False),
    ]
)


def _write_table(rows: list[dict[str, object]], schema: pa.Schema, path: Path) -> None:
    table = pa.Table.from_pylist(rows, schema=schema)
    with atomic_output(path) as temporary:
        pq.write_table(table, temporary, compression="snappy")


def _metadata_path(path: Path) -> Path:
    return path.with_suffix(".meta.json")


def _checkpoint_complete(path: Path, *, day: str, end_block: int, generation: str) -> bool:
    metadata_path = _metadata_path(path)
    if not path.is_file() or not metadata_path.is_file():
        return False
    try:
        record = json.loads(metadata_path.read_text())
        rows = pq.ParquetFile(path).metadata.num_rows
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        record.get("status") == "complete"
        and record.get("day") == day
        and int(record.get("day_end_block", -1)) == end_block
        and record.get("generation") == generation
        and int(record.get("rows", -1)) == rows
    )


def _write_checkpoint_metadata(
    path: Path, *, day: str, end_block: int, generation: str, rows: int
) -> None:
    write_json(
        _metadata_path(path),
        {
            "status": "complete",
            "day": day,
            "day_end_block": end_block,
            "generation": generation,
            "rows": rows,
        },
    )


def load_candidate_statics(path: Path = STATIC_PATH) -> dict[str, PoolStatic]:
    statics: dict[str, PoolStatic] = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if not line.strip():
                continue
            static = pool_static_from_graph(json.loads(line))
            if static.token0 in VEHICLE_CANDIDATES or static.token1 in VEHICLE_CANDIDATES:
                if static.pool in statics:
                    raise ValueError(f"duplicate immutable V3 pool identity: {static.pool}")
                statics[static.pool] = static
    if not statics:
        raise RuntimeError("candidate-linked V3 immutable pool registry is empty")
    return statics


def inventory_perimeter(days: list[str], end_blocks: list[int]) -> tuple[int, int]:
    first_state = read_tick_partition("uniswap_v3", days[0])
    start = canonical_inventory_start_block(first_state.to_dict("records"))
    end = end_blocks[-1]
    if start > end_blocks[0]:
        raise RuntimeError("first V3 inventory event lies after the first daily block cut")
    return start, end


def require_complete_raw_chunks(start: int, end: int) -> list[tuple[int, int]]:
    last_day = available_state_days("tick", "uniswap_v3")[-1]
    terminal = int(raw_day_metadata(last_day)["head_block_at_fetch"])
    if terminal < end:
        raise RuntimeError("V3 raw-event fetch terminal lies before the exact research cut")
    ranges = [
        item
        for item in block_ranges(start, terminal, CHUNK_SIZE)
        if item[0] <= end
    ]
    missing = [item for item in ranges if not inventory_chunk_completed(*item, RAW_INVENTORY_ROOT)]
    if missing:
        sample = ", ".join(f"{lower}-{upper}" for lower, upper in missing[:3])
        raise RuntimeError(
            f"V3 event-accounted inventory replay requires all raw event chunks; "
            f"missing={len(missing):,}/{len(ranges):,}; first={sample}"
        )
    totals = audit_inventory_chunks(
        ranges,
        RAW_INVENTORY_ROOT,
        known_pools=pool_addresses_from_graph(STATIC_PATH),
    )
    print(
        f"PASS: V3 raw inventory chunks={totals['chunks']:,}; "
        f"logs={totals['raw_logs']:,}; registered={totals['recognized_v3_logs']:,}",
        flush=True,
    )
    return ranges


def ranges_by_day(
    ranges: list[tuple[int, int]], days: list[str], end_blocks: list[int]
) -> dict[str, list[tuple[int, int]]]:
    result = {day: [] for day in days}
    for lower, upper in ranges:
        first = bisect_left(end_blocks, lower)
        last = bisect_left(end_blocks, upper)
        for position in range(first, min(last, len(days) - 1) + 1):
            result[days[position]].append((lower, upper))
    return result


def _raw_inventory_events_for_day(
    *,
    lower: int,
    upper: int,
    ranges: list[tuple[int, int]],
    statics: dict[str, PoolStatic],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for block_lower, block_upper in ranges:
        raw_path, _ = inventory_chunk_paths(block_lower, block_upper, RAW_INVENTORY_ROOT)
        with gzip.open(raw_path, "rt") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw = json.loads(line)
                block = int(str(raw["blockNumber"]), 16)
                pool = str(raw["address"]).lower()
                if lower <= block <= upper and pool in statics:
                    decoded = decode_inventory_log(raw)
                    rows.append(
                        {
                            **decoded,
                            "amount0_delta_raw": str(decoded["amount0_delta_raw"]),
                            "amount1_delta_raw": str(decoded["amount1_delta_raw"]),
                        }
                    )
    rows.sort(key=lambda row: (int(row["block_number"]), int(row["log_index"])))
    identities = {
        (int(row["block_number"]), str(row["tx_hash"]), int(row["log_index"]))
        for row in rows
    }
    if len(identities) != len(rows):
        raise ValueError("duplicate extra V3 inventory event within one day")
    return rows


def _canonical_swap_events_for_day(
    day: str, lower: int, upper: int, statics: dict[str, PoolStatic]
) -> list[dict[str, object]]:
    state = read_tick_partition("uniswap_v3", day)
    pool_identity = state["pool"].astype(str).str.lower()
    candidate_rows = state[pool_identity.isin(statics) & state["record_type"].eq("swap")]
    rows: list[dict[str, object]] = []
    for record in candidate_rows.to_dict("records"):
        static = statics[str(record["pool"]).lower()]
        event = canonical_inventory_event(record, static)
        if event is not None:
            block = int(event["block_number"])
            if not lower <= block <= upper:
                raise ValueError(f"canonical V3 event {event['event_id']} lies outside day {day}")
            rows.append(event)
    return rows


def _load_resume_state(
    path: Path,
) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]], dict[str, int]]:
    columns = [
        "pool",
        "balance0_raw",
        "balance1_raw",
        "last_event_block",
        "last_event_log_index",
        "cumulative_inventory_events",
    ]
    frame = pd.read_parquet(path, columns=columns)
    if frame["pool"].duplicated().any():
        raise ValueError("V3 inventory checkpoint has duplicate pools")
    balances = {
        row.pool: (int(row.balance0_raw), int(row.balance1_raw))
        for row in frame.itertuples(index=False)
    }
    last_events = {
        row.pool: (int(row.last_event_block), int(row.last_event_log_index))
        for row in frame.itertuples(index=False)
    }
    event_counts = {
        row.pool: int(row.cumulative_inventory_events)
        for row in frame.itertuples(index=False)
    }
    return balances, last_events, event_counts


def build(*, force: bool = False) -> tuple[int, int, int]:
    days, end_blocks = load_day_calendar()
    start, end = inventory_perimeter(days, end_blocks)
    ranges = require_complete_raw_chunks(start, end)
    statics = load_candidate_statics()
    generation = cache_key(CODE_SOURCES, inputs=INPUTS)
    root = CACHE_ROOT / f"engine_{generation}"
    raw_event_root = root / "raw_inventory_events"
    inventory_root = root / "inventory"
    raw_event_root.mkdir(parents=True, exist_ok=True)
    inventory_root.mkdir(parents=True, exist_ok=True)
    day_ranges = ranges_by_day(ranges, days, end_blocks)

    if force:
        for directory in (raw_event_root, inventory_root):
            for path in directory.glob("*"):
                if path.is_file():
                    path.unlink()

    prefix = 0
    for index, (day, end_block) in enumerate(zip(days, end_blocks, strict=True)):
        path = inventory_root / f"{day}.parquet"
        if _checkpoint_complete(path, day=day, end_block=end_block, generation=generation):
            prefix = index + 1
        else:
            break
    if prefix:
        balances, last_events, event_counts = _load_resume_state(
            inventory_root / f"{days[prefix - 1]}.parquet"
        )
    else:
        balances, last_events, event_counts = {}, {}, {}

    print(
        f"V3 inventory replay: days={len(days):,}; pools={len(statics):,}; "
        f"raw_chunks={len(ranges):,}; resume={prefix:,}; generation={generation}",
        flush=True,
    )
    for position in range(prefix, len(days)):
        day = days[position]
        end_block = end_blocks[position]
        lower = start if position == 0 else end_blocks[position - 1] + 1
        raw_event_path = raw_event_root / f"{day}.parquet"
        if not _checkpoint_complete(
            raw_event_path, day=day, end_block=end_block, generation=generation
        ):
            raw_events = _raw_inventory_events_for_day(
                lower=lower,
                upper=end_block,
                ranges=day_ranges[day],
                statics=statics,
            )
            _write_table(raw_events, RAW_EVENT_SCHEMA, raw_event_path)
            _write_checkpoint_metadata(
                raw_event_path,
                day=day,
                end_block=end_block,
                generation=generation,
                rows=len(raw_events),
            )
        else:
            raw_events = pd.read_parquet(raw_event_path).to_dict("records")
        canonical_swaps = _canonical_swap_events_for_day(day, lower, end_block, statics)
        events = [*canonical_swaps, *raw_events]
        for event in events:
            event["amount0_delta_raw"] = int(event["amount0_delta_raw"])
            event["amount1_delta_raw"] = int(event["amount1_delta_raw"])
        events.sort(key=lambda row: (int(row["block_number"]), int(row["log_index"])))
        apply_inventory_events(
            balances,
            events,
            last_events=last_events,
            event_counts=event_counts,
        )
        snapshot = inventory_snapshot_rows(
            day=day,
            end_block=end_block,
            statics=statics,
            balances=balances,
            last_events=last_events,
            event_counts=event_counts,
        )
        inventory_path = inventory_root / f"{day}.parquet"
        _write_table(snapshot, INVENTORY_SCHEMA, inventory_path)
        _write_checkpoint_metadata(
            inventory_path,
            day=day,
            end_block=end_block,
            generation=generation,
            rows=len(snapshot),
        )
        if (position + 1) % 50 == 0 or position + 1 == len(days):
            print(
                f"  V3 inventory [{position + 1:,}/{len(days):,}] {day}; "
                f"pools={len(snapshot):,}; events={len(events):,}; "
                f"negative={sum(bool(row['negative_inventory']) for row in snapshot):,}",
                flush=True,
            )

    files = [inventory_root / f"{day}.parquet" for day in days]
    for day, end_block, path in zip(days, end_blocks, files, strict=True):
        if not _checkpoint_complete(path, day=day, end_block=end_block, generation=generation):
            raise RuntimeError(f"V3 inventory checkpoint is incomplete after build: {day}")
    sidecar_path(OUT).unlink(missing_ok=True)
    result = assemble_parquet_shards(
        files,
        OUT,
        unique_keys=("venue", "day", "pool"),
        progress=lambda index, total, rows: print(
            f"  inventory assembly [{index:,}/{total:,}] rows={rows:,}", flush=True
        )
        if index % 100 == 0 or index == total
        else None,
    )
    negative = sum(balance0 < 0 or balance1 < 0 for balance0, balance1 in balances.values())
    stamp(
        OUT,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
        rows=result.rows,
        notes=(
            f"event-complete V3 pool-inventory replay generation {generation}; "
            "custody and protocol-fee ownership remain separate promotion gates; "
            f"resumable cache {root.name}; balanceOf validation still required"
        ),
    )
    return result.rows, len(balances), negative


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--calendar-only", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.calendar_only:
        with exclusive_job(CALENDAR_LOCK, job="exact V3 inventory day calendar"):
            rows, first, last = build_day_calendar(workers=args.workers)
        print(
            f"wrote {CALENDAR}: rows={rows:,}; exact cuts={first:,}-{last:,}",
            flush=True,
        )
        return 0
    with ExitStack() as stack:
        stack.enter_context(exclusive_job(RAW_MARKET_DATA_LOCK, job="V3 inventory replay"))
        stack.enter_context(exclusive_job(MARKET_STATE_LOCK, job="V3 inventory replay"))
        rows, pools, negative = build(force=args.force)
    print(
        f"wrote {OUT}: rows={rows:,}; pools={pools:,}; final-negative={negative:,}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

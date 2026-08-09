#!/usr/bin/env python3
"""Materialize canonical address-day token prices before panel estimation."""

from __future__ import annotations

import argparse
from functools import partial
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.data_release import expected_route_days, require_node_d_release
from ddvc.panel_assembly import assemble_parquet_shards
from ddvc.paths import DATA_DIR, TOKEN_PRICE_DAILY_PANEL, TOKEN_PRICE_LOCK
from ddvc.prices import PRICE_COLUMNS, day_price_frame
from ddvc.provenance import cache_key, sidecar_path, stamp
from ddvc.reconstruct import UNIFIED_QUALITY_PANEL
from ddvc.runtime import (
    atomic_output,
    bounded_workers,
    exclusive_job,
    interruptible_process_pool,
)


UNIFIED = DATA_DIR / "unified"
CACHE_ROOT = DATA_DIR / "processed" / "_token_price_day_cache"
CODE_SOURCES = [
    "scripts/build_token_price_panel.py",
    "src/ddvc/panel_assembly.py",
    "src/ddvc/paths.py",
    "src/ddvc/prices.py",
]
INPUTS = [UNIFIED, UNIFIED_QUALITY_PANEL]
PRICE_SCHEMA = pa.schema(
    [
        pa.field("day", pa.string(), nullable=False),
        pa.field("token", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("price_usd", pa.float64(), nullable=False),
        pa.field("n_observations", pa.int64(), nullable=False),
        pa.field("n_consensus", pa.int64(), nullable=False),
        pa.field("consensus_share", pa.float64(), nullable=False),
        pa.field("gross_weight_usd", pa.float64(), nullable=False),
        pa.field("consensus_weight_usd", pa.float64(), nullable=False),
        pa.field("price_source", pa.string(), nullable=False),
        pa.field("validation_status", pa.string(), nullable=False),
    ]
)


def _write_day(day: str, root: Path, force: bool) -> tuple[str, int]:
    output = root / f"{day}.parquet"
    if output.exists() and not force:
        return day, pq.ParquetFile(output).metadata.num_rows
    legs = pq.read_table(UNIFIED / f"{day}.parquet", columns=PRICE_COLUMNS).to_pandas()
    frame = day_price_frame(legs)
    frame.insert(0, "day", day)
    table = pa.Table.from_pandas(frame, schema=PRICE_SCHEMA, preserve_index=False)
    with atomic_output(output) as temporary:
        pq.write_table(table, temporary, compression="snappy")
    return day, len(frame)


def _candidate_coverage(panel: Path) -> tuple[int, int, str | None, str | None]:
    from ddvc.asset_types import VEHICLE_CANDIDATES

    con = duckdb.connect()
    try:
        rows = con.execute(
            """
            WITH candidate(token) AS (SELECT unnest(?)),
            expected AS (
                SELECT day, token
                FROM (SELECT unnest(?) AS day)
                CROSS JOIN candidate
            ), actual AS (
                SELECT day, token FROM read_parquet(?)
                WHERE token IN (SELECT token FROM candidate)
            ), missing AS (
                SELECT e.* FROM expected e LEFT JOIN actual a USING (day, token)
                WHERE a.token IS NULL
            )
            SELECT (SELECT count(*) FROM expected),
                (SELECT count(*) FROM actual), min(day), max(day)
            FROM missing
            """,
            [
                sorted(VEHICLE_CANDIDATES),
                expected_route_days(),
                str(panel),
            ],
        ).fetchone()
    finally:
        con.close()
    return int(rows[0]), int(rows[1]), rows[2], rows[3]


def build(*, workers: int = 2, force: bool = False) -> int:
    require_node_d_release(routes=True)
    generation = cache_key(CODE_SOURCES, inputs=INPUTS)
    root = CACHE_ROOT / f"engine_{generation}"
    root.mkdir(parents=True, exist_ok=True)
    for temporary in root.glob(".*.tmp"):
        temporary.unlink()
    days = expected_route_days()
    jobs = bounded_workers(workers, maximum=4)
    worker = partial(_write_day, root=root, force=force)
    with interruptible_process_pool(jobs) as pool:
        for index, (day, rows) in enumerate(pool.map(worker, days), 1):
            if index % 100 == 0 or index == len(days):
                print(
                    f"token prices [{index:,}/{len(days):,}] {day}; rows={rows:,}",
                    flush=True,
                )
    if cache_key(CODE_SOURCES, inputs=INPUTS) != generation:
        raise RuntimeError("token-price inputs or code changed during materialization")
    files = [root / f"{day}.parquet" for day in days]
    if any(not path.exists() for path in files):
        raise RuntimeError("token-price day cache is incomplete")
    sidecar_path(TOKEN_PRICE_DAILY_PANEL).unlink(missing_ok=True)
    assembled = assemble_parquet_shards(
        files,
        TOKEN_PRICE_DAILY_PANEL,
        unique_keys=("day", "token"),
    )
    stamp(
        TOKEN_PRICE_DAILY_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[*INPUTS, root],
        rows=assembled.rows,
        notes=f"canonical address-day price generation {generation}",
    )
    expected, actual, first_missing, last_missing = _candidate_coverage(
        TOKEN_PRICE_DAILY_PANEL
    )
    print(
        f"PASS: token prices={assembled.rows:,}; candidate-days={actual:,}/{expected:,}; "
        f"missing_span={first_missing or 'none'}..{last_missing or 'none'}",
        flush=True,
    )
    return assembled.rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    with exclusive_job(TOKEN_PRICE_LOCK, job="canonical token-price panel build"):
        build(workers=args.workers, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

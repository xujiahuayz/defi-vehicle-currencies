#!/usr/bin/env python3
"""Normalize retained provider records into the direct market-state panels.

Each family is written to ``data/processed/market_state/<family>/<venue>/<day>.parquet``.
The central quality table records schemas, row counts, support, and exclusions.
"""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from dataclasses import asdict

import pandas as pd

from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK, SHARED_RUNTIME_DIR
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.state_data import (
    CODE_SOURCES,
    FAMILY_STREAMS,
    QUALITY_COLUMNS,
    read_cp_quality,
    read_multi_asset_quality,
    write_cp_partition,
    write_multi_asset_partition,
)
from ddvc.tables import write_panel


RAW = DATA_DIR / "raw" / "thegraph"
QUALITY_PANEL = DATA_DIR / "processed" / "market_state_quality.parquet"
LOCK = SHARED_RUNTIME_DIR / "market-state.lock"


def selected_days(venue: str, start: str | None, end: str | None) -> list[str]:
    """Return the inclusive research-calendar slice available after venue genesis."""

    genesis = get_source(venue).genesis.strftime("%Y%m%d")
    lower = max(genesis, (start or RESEARCH_SAMPLE_START).replace("-", ""))
    upper = min(RESEARCH_SAMPLE_END, (end or RESEARCH_SAMPLE_END).replace("-", ""))
    return calendar_days(lower, upper) if lower <= upper else []


def market_state_quality_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Build the one directly consumed quality table."""

    records: list[dict[str, object]] = []
    for row in rows:
        record = dict(row)
        record["scientific_support"] = True
        records.append(record)
    return pd.DataFrame(
        records, columns=[*QUALITY_COLUMNS, "scientific_support"]
    ).sort_values(["family", "venue", "day"], kind="stable").reset_index(drop=True)


def build_family(
    family: str,
    venues: list[str],
    *,
    start: str | None,
    end: str | None,
    workers: int,
    force: bool,
) -> list[dict[str, object]]:
    """Build stale or absent direct partitions and return all selected quality rows."""

    readers = {
        "constant_product": read_cp_quality,
        "multi_asset": read_multi_asset_quality,
    }
    writers = {
        "constant_product": write_cp_partition,
        "multi_asset": write_multi_asset_partition,
    }
    jobs: list[tuple[str, str]] = []
    qualities: list[dict[str, object]] = []
    for venue in venues:
        for day in selected_days(venue, start, end):
            cached = None if force else readers[family](RAW, venue, day)
            if cached is None:
                jobs.append((venue, day))
            else:
                qualities.append(asdict(cached))
    if not jobs:
        return qualities
    print(f"building {len(jobs):,} {family} partition(s)", flush=True)
    with interruptible_process_pool(workers) as pool:
        futures = {
            pool.submit(writers[family], RAW, venue, day): (venue, day)
            for venue, day in jobs
        }
        for index, future in enumerate(as_completed(futures), 1):
            qualities.append(asdict(future.result()))
            if index % 100 == 0 or index == len(futures):
                print(f"  {family} [{index:,}/{len(futures):,}]", flush=True)
    return qualities


def _summary(quality: pd.DataFrame) -> pd.DataFrame:
    summary = (
        quality.groupby(["family", "venue"], as_index=False)
        .agg(
            partitions=("day", "size"),
            raw_rows=("raw_rows", "sum"),
            canonical_rows=("canonical_rows", "sum"),
            snapshot_rows=("snapshot_rows", "sum"),
            swap_rows=("swap_rows", "sum"),
            liquidity_rows=("liquidity_rows", "sum"),
            usable_rows=("usable_rows", "sum"),
            missing_order=("missing_order", "sum"),
            missing_identity=("missing_identity", "sum"),
            missing_required_streams=("missing_required_streams", "sum"),
            invalid_state=("invalid_state", "sum"),
            unsupported_state=("unsupported_state", "sum"),
            quote_supported_swaps=("quote_supported_swaps", "sum"),
            failed_partitions=("passed", lambda values: int((~values).sum())),
        )
    )
    summary["quarantined_rows"] = summary["canonical_rows"] - summary["usable_rows"]
    summary["quote_support_pct"] = (
        100
        * summary["quote_supported_swaps"]
        / summary["swap_rows"].where(summary["swap_rows"] > 0)
    ).round(3)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("all", *FAMILY_STREAMS), default="all")
    parser.add_argument("--venue", action="append")
    parser.add_argument("--start", default=RESEARCH_SAMPLE_START)
    parser.add_argument("--end", default=RESEARCH_SAMPLE_END)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.family == "all" and args.venue:
        parser.error("--venue requires one explicit --family")
    families = list(FAMILY_STREAMS) if args.family == "all" else [args.family]
    if args.family != "all":
        unknown = sorted(set(args.venue or ()) - set(FAMILY_STREAMS[args.family]))
        if unknown:
            parser.error(f"unsupported venue(s): {', '.join(unknown)}")
    full_run = (
        args.family == "all"
        and args.start.replace("-", "") == RESEARCH_SAMPLE_START
        and args.end.replace("-", "") == RESEARCH_SAMPLE_END
    )

    with exclusive_job(
        RAW_MARKET_DATA_LOCK,
        job="raw market-data fetch or canonical materialisation",
    ), exclusive_job(LOCK, job="canonical market-state build"):
        rows: list[dict[str, object]] = []
        for family in families:
            rows.extend(
                build_family(
                    family,
                    args.venue or list(FAMILY_STREAMS[family]),
                    start=args.start,
                    end=args.end,
                    workers=bounded_workers(args.workers, maximum=10),
                    force=args.force,
                )
            )
        quality = market_state_quality_frame(rows)
        failed = quality.loc[~quality["passed"].astype(bool)]
        if not full_run:
            print(f"PARTIAL: checked {len(quality):,} partition(s)", flush=True)
            return int(not failed.empty)

        write_panel(quality, QUALITY_PANEL)
        summary = _summary(quality)
        print(summary.to_string(index=False), flush=True)
        if not failed.empty:
            print(
                f"FAILED: partitions={len(failed):,}",
                flush=True,
            )
            return 1
        print(f"PASS: {len(quality):,} direct market-state partitions", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

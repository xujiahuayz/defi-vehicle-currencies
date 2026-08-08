#!/usr/bin/env python3
"""Build and audit canonical market-state inputs before empirical execution."""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.data_release import (
    V4_STATIC_QUARANTINE_PANEL,
    audit_cross_venue_order_conflicts,
    audit_v4_pool_static_conflicts,
)
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, OUTPUT_DIR, RAW_MARKET_DATA_LOCK
from ddvc.provenance import stamp
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.state_data import (
    CODE_SOURCES,
    FAMILY_STREAMS,
    QUALITY_COLUMNS,
    STATE_ROOT,
    read_cp_quality,
    read_multi_asset_quality,
    read_tick_quality,
    write_cp_partition,
    write_multi_asset_partition,
    write_tick_partition,
    tick_partition_path,
)
from ddvc.tables import write_exhibit, write_panel


RAW = DATA_DIR / "raw" / "thegraph"
QUALITY_PANEL = DATA_DIR / "processed" / "market_state_quality.parquet"
QUALITY_EXHIBIT = OUTPUT_DIR / "exhibits" / "market_state_quality.jsonl"
LOCK = DATA_DIR / "processed" / ".market_state.lock"


def selected_days(
    venue: str,
    start: str | None,
    end: str | None,
) -> list[str]:
    genesis = get_source(venue).genesis.strftime("%Y%m%d")
    lower = max(genesis, (start or RESEARCH_SAMPLE_START).replace("-", ""))
    upper = (end or RESEARCH_SAMPLE_END).replace("-", "")
    return calendar_days(lower, upper) if lower <= upper else []


def build_family(
    family: str,
    venues: list[str],
    *,
    start: str | None,
    end: str | None,
    workers: int,
    force: bool,
) -> list[dict[str, object]]:
    readers = {
        "tick": read_tick_quality,
        "constant_product": read_cp_quality,
        "multi_asset": read_multi_asset_quality,
    }
    writers = {
        "tick": write_tick_partition,
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
    if jobs:
        print(f"building {len(jobs):,} canonical {family} partitions with {workers} workers", flush=True)
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
        allowed_venues = FAMILY_STREAMS[args.family]
        unknown = sorted(set(args.venue or ()) - set(allowed_venues))
        if unknown:
            parser.error(f"unsupported venue(s) for {args.family}: {', '.join(unknown)}")
    full_run = (
        args.family == "all"
        and args.start.replace("-", "") == RESEARCH_SAMPLE_START
        and args.end.replace("-", "") == RESEARCH_SAMPLE_END
    )
    with exclusive_job(
        RAW_MARKET_DATA_LOCK,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        with exclusive_job(LOCK, job="canonical market-state build"):
            rows: list[dict[str, object]] = []
            for family in families:
                venues = args.venue or list(FAMILY_STREAMS[family])
                rows.extend(
                    build_family(
                        family,
                        venues,
                        start=args.start,
                        end=args.end,
                        workers=bounded_workers(args.workers, maximum=10),
                        force=args.force,
                    )
                )
            quality = pd.DataFrame(rows, columns=QUALITY_COLUMNS).sort_values(
                ["family", "venue", "day"]
            )
            failed = quality[~quality["passed"]]
            if not full_run:
                print(
                    f"PARTIAL: built/audited {len(quality):,} partition(s); "
                    "the global six-venue quality ledger was not published",
                    flush=True,
                )
                if not failed.empty:
                    print(f"FAILED: {len(failed):,} selected partition(s) violate the data contract")
                    return 1
                return 0
            tick_paths = {
                venue: [
                    tick_partition_path(venue, str(day), root=STATE_ROOT)
                    for day in quality.loc[
                        (quality["family"] == "tick") & (quality["venue"] == venue),
                        "day",
                    ]
                ]
                for venue in FAMILY_STREAMS["tick"]
            }
            cross_venue_conflicts, conflict_samples = audit_cross_venue_order_conflicts(
                tick_paths
            )
            v4_static_quarantine = audit_v4_pool_static_conflicts(
                tick_paths["uniswap_v4"]
            )
            write_panel(
                v4_static_quarantine,
                V4_STATIC_QUARANTINE_PANEL,
                code_sources=[
                    *CODE_SOURCES,
                    "src/ddvc/data_release.py",
                    "scripts/build_market_state.py",
                ],
                inputs=[STATE_ROOT / "tick" / "uniswap_v4"],
                notes="complete V4 pool exclusion set for provider-supplied immutable-static drift",
            )
            quality["cross_venue_order_conflicts"] = cross_venue_conflicts
            quality["v4_static_conflict_pools"] = len(v4_static_quarantine)
            all_venues = [venue for venues in FAMILY_STREAMS.values() for venue in venues]
            write_panel(
                quality,
                QUALITY_PANEL,
                code_sources=[
                    *CODE_SOURCES,
                    "src/ddvc/data_release.py",
                    "scripts/build_market_state.py",
                ],
                inputs=[*[RAW / venue for venue in all_venues], STATE_ROOT],
                notes=f"canonical market-state engine {STATE_ROOT.name}",
            )
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
                    invalid_swap_sign=("invalid_swap_sign", "sum"),
                    invalid_state=("invalid_state", "sum"),
                    unsupported_state=("unsupported_state", "sum"),
                    zero_swap_amounts=("zero_swap_amounts", "sum"),
                    missing_quote_statics=("missing_quote_statics", "sum"),
                    quote_supported_swaps=("quote_supported_swaps", "sum"),
                    conflicting_events=("conflicting_events", "sum"),
                    failed_partitions=("passed", lambda values: int((~values).sum())),
                )
            )
            summary["quarantined_rows"] = summary["canonical_rows"] - summary["usable_rows"]
            summary["quote_support_pct"] = (
                100 * summary["quote_supported_swaps"] / summary["swap_rows"].where(summary["swap_rows"] > 0)
            ).round(3)
            summary["static_conflict_rows"] = 0
            v4_summary = (summary["family"] == "tick") & (
                summary["venue"] == "uniswap_v4"
            )
            summary.loc[v4_summary, "static_conflict_rows"] = int(
                v4_static_quarantine["swap_rows"].sum()
            )
            summary["released_quote_supported_swaps"] = (
                summary["quote_supported_swaps"]
                - summary["static_conflict_rows"]
            )
            summary["released_quote_support_pct"] = (
                100
                * summary["released_quote_supported_swaps"]
                / summary["swap_rows"].where(summary["swap_rows"] > 0)
            ).round(3)
            write_exhibit(
                summary,
                QUALITY_EXHIBIT,
                code_sources=[*CODE_SOURCES, "scripts/build_market_state.py"],
                inputs=[QUALITY_PANEL],
                notes="full-calendar canonical market-state quality gate",
            )
            print(summary.to_string(index=False), flush=True)
            print(
                f"cross-venue block-log conflicts: {cross_venue_conflicts:,}",
                flush=True,
            )
            print(
                f"V4 pools quarantined for immutable-static drift: "
                f"{len(v4_static_quarantine):,}",
                flush=True,
            )
            for row in v4_static_quarantine.head(3).to_dict("records"):
                print(f"  V4 quarantine sample: {row}", flush=True)
            for sample in conflict_samples:
                print(f"  conflict sample: {sample}", flush=True)
            if not failed.empty:
                print(f"FAILED: {len(failed):,} canonical partition(s) violate the data contract")
                return 1
            if cross_venue_conflicts:
                print("FAILED: canonical tick state has cross-venue causal-order conflicts")
                return 1
            print(f"PASS: {len(quality):,} canonical partitions under {STATE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

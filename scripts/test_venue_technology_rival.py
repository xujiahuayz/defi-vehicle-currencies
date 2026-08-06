#!/usr/bin/env python3
"""Does stable excess use survive outside venues specialised around stable assets?

The old diagnostic sampled every ninetieth day, measured only intermediation share, and
called Curve plus Balancer "StableSwap" even though Balancer mixes weighted and stable
families. This full-sample replacement measures the same excess-use ratio as the primary
result: intermediary share divided by endpoint-demand share on complete route components.

Constant-product-family routes are the discriminating scope. Curve and Balancer are
reported separately as composition diagnostics, with Balancer left technologically
unlabelled. A component enters a scope only when every leg belongs to it.

Reads   data/unified/YYYYMMDD.parquet
Writes  output/exhibits/venue_technology_rival.jsonl
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.asset_types import CURRENCY_TYPES
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit
from ddvc.vehicle_extent import (
    REQUIRED_COLUMNS,
    aggregate_vehicle_extent,
    compute_vehicle_extent,
    restrict_routes_to_venues,
)
from ddvc.venues import VENUE_ROBUSTNESS_SCOPES

UNIFIED = DATA_DIR / "unified"
OUT = OUTPUT_DIR / "exhibits" / "venue_technology_rival.jsonl"
INPUT_COLUMNS = REQUIRED_COLUMNS + ["source"]
CODE_SOURCES = [
    "scripts/test_venue_technology_rival.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/vehicle_extent.py",
    "src/ddvc/venues.py",
]
MAX_WORKERS = 8


def bounded_workers(requested: int) -> int:
    return min(MAX_WORKERS, max(1, requested))


def support_status(daily: pd.DataFrame) -> pd.DataFrame:
    """State whether a scope-year contains intermediation that identifies the ratio."""
    support = daily.groupby(["year", "scope"], as_index=False).agg(
        intermediate_usd_support=("intermediate_usd", "sum"),
        intermediate_routes_support=("intermediate_routes", "sum"),
        endpoint_usd_support=("endpoint_usd", "sum"),
        endpoint_routes_support=("endpoint_routes", "sum"),
    )
    support["support_status"] = "identified"
    no_intermediation = support["intermediate_routes_support"].eq(0) | support[
        "intermediate_usd_support"
    ].le(0)
    no_endpoints = support["endpoint_routes_support"].eq(0) | support[
        "endpoint_usd_support"
    ].le(0)
    support.loc[no_endpoints, "support_status"] = "no_endpoint_demand"
    support.loc[~no_endpoints & no_intermediation, "support_status"] = "no_intermediation"
    return support


def one_day(path: Path) -> pd.DataFrame:
    legs = pd.read_parquet(path, columns=INPUT_COLUMNS)
    rows: list[pd.DataFrame] = []
    for scope, venues in VENUE_ROBUSTNESS_SCOPES:
        scoped = legs if venues is None else restrict_routes_to_venues(legs, venues)
        extent = compute_vehicle_extent(scoped)
        if extent.empty:
            continue
        route_components = int(extent["routes_clean"].iloc[0])
        extent = extent[extent["asset_type"].isin(CURRENCY_TYPES)]
        if extent.empty:
            continue
        grouped = extent.groupby("asset_type", as_index=False).agg(
            intermediate_usd=("intermediate_usd", "sum"),
            endpoint_usd=("endpoint_usd", "sum"),
            intermediate_routes=("intermediate_routes", "sum"),
            endpoint_routes=("endpoint_routes", "sum"),
        )
        grouped.insert(0, "scope", scope)
        grouped.insert(0, "date", pd.to_datetime(path.stem, format="%Y%m%d"))
        grouped["route_components"] = route_components
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    workers = bounded_workers(args.workers)

    files = sorted(UNIFIED.glob("[0-9]" * 8 + ".parquet"))
    if not files:
        print("no unified route files")
        return 1
    print(f"measuring {len(files):,} days across four venue scopes", flush=True)
    parts: list[pd.DataFrame] = []
    failures: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one_day, path): path for path in files}
        for i, future in enumerate(as_completed(futures), 1):
            path = futures[future]
            try:
                got = future.result()
                if not got.empty:
                    parts.append(got)
            except Exception as exc:
                failures.append((path.name, f"{type(exc).__name__}: {exc}"))
            if i % 250 == 0:
                print(f"  {i:,}/{len(files):,}", flush=True)
    if failures:
        for name, error in failures[:10]:
            print(f"  FAILED {name}: {error}")
        print(f"{len(failures)} day(s) failed; refusing a partial result")
        return 1

    daily = pd.concat(parts, ignore_index=True)
    daily["year"] = daily["date"].dt.year
    result = aggregate_vehicle_extent(
        daily,
        ["year", "scope", "asset_type"],
        level="asset_type",
        period_keys=["year", "scope"],
    )
    coverage = (
        daily[["date", "year", "scope", "route_components"]]
        .drop_duplicates()
        .groupby(["year", "scope"], as_index=False)
        .agg(route_components=("route_components", "sum"))
    )
    result = result.merge(coverage, on=["year", "scope"], how="left")
    result = result.merge(support_status(daily), on=["year", "scope"], how="left")
    write_exhibit(
        result,
        OUT,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED],
        notes="complete route components; candidate-currency denominator; unsupported scope-years labelled",
    )

    for scope in result["scope"].drop_duplicates():
        table = result[result["scope"].eq(scope)].pivot(
            index="year", columns="asset_type", values="vehicle_excess_use_ratio"
        )
        print(f"\n{scope}, value-weighted excess use")
        print(table.reindex(columns=["native", "stable"]).round(2).to_string())
    print(f"\nwrote {OUT.relative_to(OUTPUT_DIR.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

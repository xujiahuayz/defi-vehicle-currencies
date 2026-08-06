#!/usr/bin/env python3
"""Build the paper's primary vehicle-extent measure over the full unified sample.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/vehicle_excess_use_daily.parquet
        output/exhibits/vehicle_excess_use.jsonl
        output/exhibits/vehicle_excess_use_quarterly.jsonl
"""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from pathlib import Path

import pandas as pd

from ddvc.asset_types import CURRENCY_TYPES, backing
from ddvc.paths import REPO_ROOT
from ddvc.runtime import exclusive_job, interruptible_process_pool
from ddvc.tables import write_exhibit, write_panel
from ddvc.vehicle_extent import (
    REQUIRED_COLUMNS,
    aggregate_vehicle_extent,
    compute_vehicle_extent,
)

UNIFIED = REPO_ROOT / "data" / "unified"
OUT_PANEL = REPO_ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"
OUT_EXHIBIT = REPO_ROOT / "output" / "exhibits" / "vehicle_excess_use.jsonl"
OUT_QUARTERLY = REPO_ROOT / "output" / "exhibits" / "vehicle_excess_use_quarterly.jsonl"
LOCK = OUT_PANEL.with_suffix(".lock")
MAX_WORKERS = 8
CODE_SOURCES = [
    "scripts/build_vehicle_excess_use.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/vehicle_extent.py",
    "src/ddvc/route_roles.py",
]


def bounded_workers(requested: int) -> int:
    return min(MAX_WORKERS, max(1, requested))


def one_day(path: Path) -> pd.DataFrame:
    legs = pd.read_parquet(path, columns=REQUIRED_COLUMNS)
    out = compute_vehicle_extent(legs)
    if out.empty:
        return out
    out.insert(0, "date", pd.to_datetime(path.stem, format="%Y%m%d"))
    return out


def _scope(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    out = frame.copy()
    out.insert(0, "scope", scope)
    return out


def stable_backing_year(candidate: pd.DataFrame) -> pd.DataFrame:
    """Compare backing regimes within stablecoins, not against other currency types."""
    stable = candidate[candidate["asset_type"].eq("stable")].copy()
    return _scope(
        aggregate_vehicle_extent(
            stable,
            ["year", "backing"],
            level="stable_backing",
            period_keys=["year"],
        ),
        "stable_currencies",
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    workers = bounded_workers(args.workers)

    files = sorted(UNIFIED.glob("*.parquet"))
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"no unified files under {UNIFIED.relative_to(REPO_ROOT)}")
        return 1
    print(
        f"measuring excess use on {len(files):,} days with {workers} workers",
        flush=True,
    )
    parts: list[pd.DataFrame] = []
    failures: list[tuple[str, str]] = []
    with interruptible_process_pool(workers) as pool:
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
        print(f"{len(failures)} day(s) failed; refusing a partial panel")
        return 1
    panel = pd.concat(parts, ignore_index=True).sort_values(
        ["date", "intermediate_share"], ascending=[True, False]
    )
    write_panel(
        panel,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED],
        notes="cycles excluded; endpoints include direct and indirect clean routes",
    )

    panel["year"] = panel["date"].dt.year
    panel["quarter"] = panel["date"].dt.to_period("Q").astype(str)
    candidate = panel[panel["asset_type"].isin(CURRENCY_TYPES)].copy()
    candidate["backing"] = [
        backing(token, observed)
        for token, observed in zip(candidate["token"], candidate["date"], strict=True)
    ]
    type_year = _scope(
        aggregate_vehicle_extent(
            candidate,
            ["year", "asset_type"],
            level="asset_type",
            period_keys=["year"],
        ),
        "candidate_currencies",
    )
    token_year = _scope(
        aggregate_vehicle_extent(
            candidate,
            ["year", "token", "symbol", "asset_type"],
            level="token",
            period_keys=["year"],
        ),
        "candidate_currencies",
    )
    token_year = token_year[
        token_year["endpoint_share"].ge(0.001)
        | token_year["intermediate_share"].ge(0.001)
    ]
    all_asset_type_year = _scope(
        aggregate_vehicle_extent(
            panel,
            ["year", "asset_type"],
            level="asset_type",
            period_keys=["year"],
        ),
        "all_assets_diagnostic",
    )
    backing_year = stable_backing_year(candidate)
    type_quarter = _scope(
        aggregate_vehicle_extent(
            candidate,
            ["quarter", "asset_type"],
            level="asset_type",
            period_keys=["quarter"],
        ),
        "candidate_currencies",
    )
    exhibit = pd.concat(
        [type_year, token_year, backing_year, all_asset_type_year],
        ignore_index=True,
        sort=False,
    )
    write_exhibit(
        exhibit,
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
    )
    write_exhibit(
        type_quarter,
        OUT_QUARTERLY,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
    )
    print(f"\n{panel.date.nunique():,} days, {len(panel):,} token-days")
    print("annual excess-use ratio by asset type, prespecified currencies only")
    table = type_year.pivot(
        index="year", columns="asset_type", values="vehicle_excess_use_ratio"
    )
    print(table.round(2).to_string())
    count_table = type_year.pivot(
        index="year", columns="asset_type", values="vehicle_excess_use_count_ratio"
    )
    print("\ncount-weighted robustness")
    print(count_table.round(2).to_string())
    backing_table = backing_year.pivot(
        index="year", columns="backing", values="vehicle_excess_use_ratio"
    )
    print("\nstable-backing robustness, value weighted")
    print(backing_table.round(2).to_string())
    unsupported = panel[
        (panel["intermediate_share"] > 0) & (~panel["endpoint_supported"])
    ]
    print(
        f"\n{len(unsupported):,} token-days carry intermediation but zero endpoint "
        "demand; retained as unsupported diagnostics"
    )
    print(
        f"wrote {OUT_PANEL.relative_to(REPO_ROOT)}, {OUT_EXHIBIT.relative_to(REPO_ROOT)}, "
        f"and {OUT_QUARTERLY.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="vehicle excess-use panel"):
        raise SystemExit(main())

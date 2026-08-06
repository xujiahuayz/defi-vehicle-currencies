#!/usr/bin/env python3
"""Build the paper's primary vehicle-extent measure over the full unified sample.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/vehicle_excess_use_daily.parquet
        output/exhibits/vehicle_excess_use.jsonl
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
from ddvc.asset_types import CURRENCY_TYPES
from ddvc.provenance import stamp
from ddvc.tables import write_exhibit
from ddvc.vehicle_extent import REQUIRED_COLUMNS, compute_vehicle_extent

UNIFIED = ROOT / "data" / "unified"
OUT_PANEL = ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"
OUT_EXHIBIT = ROOT / "output" / "exhibits" / "vehicle_excess_use.jsonl"
CODE_SOURCES = [
    "scripts/build_vehicle_excess_use.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/vehicle_extent.py",
]


def one_day(path: Path) -> pd.DataFrame:
    legs = pd.read_parquet(path, columns=REQUIRED_COLUMNS)
    out = compute_vehicle_extent(legs)
    if out.empty:
        return out
    out.insert(0, "date", pd.to_datetime(path.stem, format="%Y%m%d"))
    return out


def _aggregate(frame: pd.DataFrame, keys: list[str], level: str) -> pd.DataFrame:
    out = frame.groupby(keys, as_index=False).agg(
        intermediate_usd=("intermediate_usd", "sum"),
        endpoint_usd=("endpoint_usd", "sum"),
        days=("date", "nunique"),
    )
    by_year = out.groupby("year")
    out["intermediate_share"] = (
        out["intermediate_usd"] / by_year["intermediate_usd"].transform("sum")
    )
    out["endpoint_share"] = (
        out["endpoint_usd"] / by_year["endpoint_usd"].transform("sum")
    )
    out["vehicle_excess_use_ratio"] = (
        out["intermediate_share"]
        / out["endpoint_share"].where(out["endpoint_share"].gt(0))
    )
    out.insert(0, "level", level)
    return out


def _scope(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    out = frame.copy()
    out.insert(0, "scope", scope)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    files = sorted(UNIFIED.glob("*.parquet"))
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"no unified files under {UNIFIED.relative_to(ROOT)}")
        return 1
    print(
        f"measuring excess use on {len(files):,} days with {args.workers} workers",
        flush=True,
    )
    parts: list[pd.DataFrame] = []
    failures: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
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
    OUT_PANEL.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PANEL.with_suffix(".tmp.parquet")
    panel.to_parquet(tmp, index=False)
    tmp.replace(OUT_PANEL)

    panel["year"] = panel["date"].dt.year
    candidate = panel[panel["asset_type"].isin(CURRENCY_TYPES)]
    type_year = _scope(
        _aggregate(candidate, ["year", "asset_type"], "asset_type"),
        "candidate_currencies",
    )
    token_year = _scope(
        _aggregate(
            candidate, ["year", "token", "symbol", "asset_type"], "token"
        ),
        "candidate_currencies",
    )
    token_year = token_year[
        token_year["endpoint_share"].ge(0.001)
        | token_year["intermediate_share"].ge(0.001)
    ]
    all_asset_type_year = _scope(
        _aggregate(panel, ["year", "asset_type"], "asset_type"),
        "all_assets_diagnostic",
    )
    exhibit = pd.concat(
        [type_year, token_year, all_asset_type_year], ignore_index=True, sort=False
    )
    write_exhibit(exhibit, OUT_EXHIBIT)
    stamp(
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED],
        rows=len(panel),
        notes="cycles excluded; endpoints include direct and indirect clean routes",
    )
    stamp(
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
        rows=len(exhibit),
    )

    print(f"\n{panel.date.nunique():,} days, {len(panel):,} token-days")
    print("annual excess-use ratio by asset type, prespecified currencies only")
    table = type_year.pivot(
        index="year", columns="asset_type", values="vehicle_excess_use_ratio"
    )
    print(table.round(2).to_string())
    unsupported = panel[
        (panel["intermediate_share"] > 0) & (~panel["endpoint_supported"])
    ]
    print(
        f"\n{len(unsupported):,} token-days carry intermediation but zero endpoint "
        "demand; retained as unsupported diagnostics"
    )
    print(
        f"wrote {OUT_PANEL.relative_to(ROOT)} and {OUT_EXHIBIT.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

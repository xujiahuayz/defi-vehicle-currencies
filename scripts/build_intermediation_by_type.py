#!/usr/bin/env python3
"""Daily vehicle-type composition, split by single- versus cross-venue routes.

Each coherent non-cyclic route contributes one episode for every intermediary it uses.
The cross-venue split tests whether the native-to-stable transition is confined to the
aggregator-era integration margin or also occurs inside venue-local routing.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/intermediation_by_type_daily.parquet
        output/exhibits/intermediation_by_type.jsonl
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.asset_types import TYPES, classify
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.realised import realised_routes
from ddvc.tables import write_exhibit, write_panel

UNIFIED = DATA_DIR / "unified"
OUT_PARQUET = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "intermediation_by_type.jsonl"
MAX_WORKERS = 8
CODE_SOURCES = [
    "scripts/build_intermediation_by_type.py",
    "src/ddvc/realised.py",
    "src/ddvc/asset_types.py",
]
INTEGRATION_SCOPES = ("single_venue", "cross_venue")


def bounded_workers(requested: int) -> int:
    return min(MAX_WORKERS, max(1, requested))


def empty_day(day: str) -> dict[str, object]:
    out: dict[str, object] = {
        "date": pd.to_datetime(day, format="%Y%m%d"),
        "routes_intermediated": 0,
        "episodes": 0,
    }
    for asset_type in TYPES:
        out[f"cnt_{asset_type}"] = 0
        out[f"usd_{asset_type}"] = 0.0
        for scope in INTEGRATION_SCOPES:
            out[f"cnt_{scope}_{asset_type}"] = 0
            out[f"usd_{scope}_{asset_type}"] = 0.0
    return out


def one_day(path: Path) -> dict[str, object]:
    try:
        routes = realised_routes(path.stem, path.parent)
    except Exception as exc:
        return {"date": path.stem, "error": f"{type(exc).__name__}: {exc}"[:160]}
    if routes.empty:
        return empty_day(path.stem)

    routes["asset_type"] = routes["vehicle"].map(
        {value: classify(value)[1] for value in routes["vehicle"].unique()}
    )
    routes["symbol"] = routes["vehicle"].map(
        {value: classify(value)[0] for value in routes["vehicle"].unique()}
    )
    routes["integration_scope"] = routes["cross_venue"].map(
        {False: "single_venue", True: "cross_venue"}
    )
    out = empty_day(path.stem)
    out["routes_intermediated"] = int(
        routes[["tx_hash", "component_id"]].drop_duplicates().shape[0]
    )
    out["episodes"] = int(len(routes))
    for asset_type in TYPES:
        selected = routes[routes["asset_type"].eq(asset_type)]
        out[f"cnt_{asset_type}"] = int(len(selected))
        out[f"usd_{asset_type}"] = float(selected["usd"].sum())
        for scope in INTEGRATION_SCOPES:
            cell = selected[selected["integration_scope"].eq(scope)]
            out[f"cnt_{scope}_{asset_type}"] = int(len(cell))
            out[f"usd_{scope}_{asset_type}"] = float(cell["usd"].sum())
    for symbol, count in routes["symbol"].dropna().value_counts().items():
        out[f"cnt_{symbol}"] = int(count)
    return out


def annual_composition(panel: pd.DataFrame) -> pd.DataFrame:
    data = panel.copy()
    data["year"] = pd.to_datetime(data["date"]).dt.year
    columns = [
        column
        for column in data.columns
        if column.startswith("cnt_") or column.startswith("usd_")
    ]
    annual = data.groupby("year", as_index=False)[columns].sum()
    rows: list[dict[str, object]] = []
    for observed in annual.itertuples(index=False):
        for scope in ("all", *INTEGRATION_SCOPES):
            count_columns = {
                asset_type: f"cnt_{asset_type}" if scope == "all" else f"cnt_{scope}_{asset_type}"
                for asset_type in TYPES
            }
            value_columns = {
                asset_type: f"usd_{asset_type}" if scope == "all" else f"usd_{scope}_{asset_type}"
                for asset_type in TYPES
            }
            count_total = sum(float(getattr(observed, column)) for column in count_columns.values())
            value_total = sum(float(getattr(observed, column)) for column in value_columns.values())
            for asset_type in TYPES:
                count = float(getattr(observed, count_columns[asset_type]))
                value = float(getattr(observed, value_columns[asset_type]))
                rows.append(
                    {
                        "year": int(observed.year),
                        "integration_scope": scope,
                        "asset_type": asset_type,
                        "episodes": int(count),
                        "episode_share": count / count_total if count_total else None,
                        "usd": value,
                        "usd_share": value / value_total if value_total else None,
                    }
                )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    workers = bounded_workers(args.workers)

    days = sorted(UNIFIED.glob("*.parquet"))
    if args.limit:
        days = days[: args.limit]
    if not days:
        print(f"no unified day files under {UNIFIED.relative_to(REPO_ROOT)}")
        return 1
    print(f"reducing {len(days):,} days with {workers} workers", flush=True)

    rows: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one_day, day): day for day in days}
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            (errors if "error" in result else rows).append(result)
            if index % 250 == 0:
                print(f"  {index:,}/{len(days):,}", flush=True)
    if errors:
        for error in errors[:10]:
            print(f"FAILED {error['date']}: {error['error']}")
        print(f"{len(errors)} day(s) failed; refusing partial output")
        return 1
    if len(rows) != len(days):
        print(f"expected {len(days):,} days but built {len(rows):,}; refusing partial output")
        return 1

    panel = pd.DataFrame(rows).sort_values("date").reset_index(drop=True).fillna(0)
    for asset_type in TYPES:
        panel[f"share_{asset_type}"] = panel[f"cnt_{asset_type}"] / panel["episodes"].where(
            panel["episodes"].gt(0)
        )
    annual = annual_composition(panel)
    write_panel(
        panel,
        OUT_PARQUET,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED],
        notes="clean coherent non-cyclic realised routes; one episode per intermediary",
    )
    write_exhibit(
        annual,
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PARQUET],
    )

    print(
        f"\n{len(panel):,} days, {int(panel.routes_intermediated.sum()):,} "
        f"intermediated routes, {int(panel.episodes.sum()):,} episodes"
    )
    for scope in ("all", *INTEGRATION_SCOPES):
        view = annual[
            annual["integration_scope"].eq(scope)
            & annual["asset_type"].isin(["native", "stable"])
        ].pivot(index="year", columns="asset_type", values="episode_share")
        print(f"\n{scope}: native and stable episode shares")
        print(view.round(3).to_string())
    print(f"\nwrote {OUT_PARQUET.relative_to(REPO_ROOT)} and {OUT_EXHIBIT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

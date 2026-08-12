#!/usr/bin/env python3
"""Decompose count-versus-value vehicle dominance into observable swap styles.

The unit is one clean route-intermediary episode. The panel compares count and strict
value on identical within-20-percent support, then separates sequential from branched
split/join execution, two-leg from longer routes, and single- from cross-venue routing.
Daily pooled value caps expose whether a small upper tail drives value-weighted shares.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/vehicle_swap_style_daily.parquet
        output/exhibits/vehicle_swap_style.jsonl
"""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import CURRENCY_TYPES, classify
from ddvc.data_release import require_node_d_release
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.realised import realised_routes
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.tables import write_exhibit, write_panel


UNIFIED = DATA_DIR / "unified"
OUT_PANEL = DATA_DIR / "processed" / "vehicle_swap_style_daily.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "vehicle_swap_style.jsonl"
LOCK = OUT_PANEL.with_suffix(".lock")
CODE_SOURCES = [
    "scripts/build_vehicle_swap_style.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/realised.py",
    "src/ddvc/route_roles.py",
]
GROUPS = ["asset_type", "morphology", "integration", "complexity"]
CAP_QUANTILES = (0.90, 0.95, 0.99)


def reduce_routes(routes: pd.DataFrame, day: str) -> pd.DataFrame:
    """Reduce one day's route-intermediary episodes on matched count/value support."""

    columns = [
        "date",
        *GROUPS,
        "episodes_all",
        "episodes_strict",
        "strict_value_usd",
        "strict_value_capped_p90_usd",
        "strict_value_capped_p95_usd",
        "strict_value_capped_p99_usd",
        "strict_value_median_usd",
        "strict_value_p90_usd",
        "strict_value_p99_usd",
        "daily_cap_p90_usd",
        "daily_cap_p95_usd",
        "daily_cap_p99_usd",
    ]
    if routes.empty:
        return pd.DataFrame(columns=columns)
    data = routes.copy()
    labels = data["vehicle"].map(classify)
    data["asset_type"] = labels.map(lambda item: item[1])
    data = data[data["asset_type"].isin(CURRENCY_TYPES)].copy()
    if data.empty:
        return pd.DataFrame(columns=columns)
    route_keys = ["tx_hash", "component_id"]
    data["intermediary_count"] = data.groupby(route_keys)["vehicle"].transform("nunique")
    data["morphology"] = np.where(
        data["legs"].eq(data["intermediary_count"] + 1),
        "sequential",
        "branched_split_join",
    )
    data["integration"] = np.where(data["cross_venue"], "cross_venue", "single_venue")
    data["complexity"] = np.where(data["legs"].eq(2), "two_leg", "more_than_two_legs")
    data["strict"] = data["within_20pct"] & pd.to_numeric(data["usd"], errors="coerce").gt(0)
    strict = data.loc[data["strict"], "usd"]
    caps = {
        quantile: float(strict.quantile(quantile)) if not strict.empty else np.nan
        for quantile in CAP_QUANTILES
    }
    for quantile, cap in caps.items():
        suffix = int(quantile * 100)
        data[f"strict_value_capped_p{suffix}_usd"] = np.where(
            data["strict"],
            pd.to_numeric(data["usd"], errors="coerce").clip(upper=cap),
            0.0,
        )
    data["strict_value_usd"] = pd.to_numeric(data["usd"], errors="coerce").where(data["strict"], 0.0)
    rows: list[dict[str, object]] = []
    for key, group in data.groupby(GROUPS, sort=True):
        supported = group[group["strict"]]
        row: dict[str, object] = dict(zip(GROUPS, key, strict=True))
        row.update(
            {
                "date": pd.to_datetime(day, format="%Y%m%d"),
                "episodes_all": int(len(group)),
                "episodes_strict": int(len(supported)),
                "strict_value_usd": float(group["strict_value_usd"].sum()),
                "strict_value_median_usd": float(supported["usd"].median()) if not supported.empty else np.nan,
                "strict_value_p90_usd": float(supported["usd"].quantile(0.90)) if not supported.empty else np.nan,
                "strict_value_p99_usd": float(supported["usd"].quantile(0.99)) if not supported.empty else np.nan,
            }
        )
        for quantile, cap in caps.items():
            suffix = int(quantile * 100)
            row[f"strict_value_capped_p{suffix}_usd"] = float(group[f"strict_value_capped_p{suffix}_usd"].sum())
            row[f"daily_cap_p{suffix}_usd"] = cap
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def one_day(path: Path) -> pd.DataFrame:
    return reduce_routes(
        realised_routes(path.stem, path.parent, require_positive_value=False),
        path.stem,
    )


def annual_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight daily stable/native shares for the main observable style cuts."""

    data = panel[panel["asset_type"].isin(["native", "stable"])].copy()
    data["year"] = pd.to_datetime(data["date"]).dt.year
    weight_columns = [
        "episodes_all",
        "episodes_strict",
        "strict_value_usd",
        "strict_value_capped_p90_usd",
        "strict_value_capped_p95_usd",
        "strict_value_capped_p99_usd",
    ]
    frames = []
    for dimension in ("all", "morphology", "integration", "complexity"):
        keys = ["date", "year", "asset_type"]
        if dimension != "all":
            keys.insert(2, dimension)
        daily = data.groupby(keys, as_index=False)[weight_columns].sum()
        denominators = [key for key in keys if key != "asset_type"]
        totals = daily.groupby(denominators)[weight_columns].transform("sum")
        share_columns = []
        for column in weight_columns:
            share = f"{column}_share"
            daily[share] = daily[column] / totals[column].where(totals[column].gt(0))
            share_columns.append(share)
        annual_keys = ["year", "asset_type"]
        if dimension != "all":
            annual_keys.insert(1, dimension)
        summary = daily.groupby(annual_keys, as_index=False)[share_columns].mean()
        summary.insert(0, "dimension", dimension)
        frames.append(summary)
    return pd.concat(frames, ignore_index=True, sort=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    require_node_d_release(routes=True)
    paths = sorted(UNIFIED.glob("*.parquet"))
    if args.limit:
        paths = paths[: args.limit]
    parts = []
    failures = []
    with interruptible_process_pool(bounded_workers(args.workers)) as pool:
        futures = {pool.submit(one_day, path): path for path in paths}
        for index, future in enumerate(as_completed(futures), 1):
            path = futures[future]
            try:
                part = future.result()
                if not part.empty:
                    parts.append(part)
            except Exception as exc:
                failures.append((path.name, f"{type(exc).__name__}: {exc}"))
            if index % 250 == 0 or index == len(paths):
                print(f"swap style [{index:,}/{len(paths):,}]", flush=True)
    if failures:
        print(f"{len(failures)} day(s) failed; first={failures[0]}")
        return 1
    if args.limit:
        print(f"smoke reduction complete on {len(paths):,} days; canonical outputs unchanged")
        return 0
    panel = pd.concat(parts, ignore_index=True).sort_values(["date", *GROUPS])
    write_panel(
        panel,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED],
        notes="route-intermediary episodes; matched within-20-percent count/value support; daily pooled value caps; observed on-chain morphology does not identify frontend or human authorship",
    )
    write_exhibit(
        annual_summary(panel),
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
    )
    print(f"wrote {OUT_PANEL.relative_to(DATA_DIR.parent)} and {OUT_EXHIBIT.relative_to(OUTPUT_DIR.parent)}")
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="vehicle swap-style panel"):
        raise SystemExit(main())

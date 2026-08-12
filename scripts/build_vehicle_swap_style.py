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

from ddvc.analysis.dynamics import aggregate_complete_day_bins
from ddvc.asset_types import CURRENCY_TYPES, classify
from ddvc.data_release import (
    release_preinstall_validator,
    released_route_partitions,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.realised import ROUTE_COLUMNS, realised_routes
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.tables import write_exhibit, write_panel


OUT_PANEL = DATA_DIR / "processed" / "vehicle_swap_style_daily.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "vehicle_swap_style.jsonl"
LOCK = OUT_PANEL.with_suffix(".lock")
CODE_SOURCES = [
    "scripts/build_vehicle_swap_style.py",
    "src/ddvc/analysis/dynamics.py",
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


def _period_shares(
    period: pd.DataFrame,
    dimension: str,
    weight_columns: list[str],
) -> pd.DataFrame:
    """Construct native/stable shares only after aggregating raw quantities."""

    time_columns = [
        column for column in ("date", "period_start", "year") if column in period
    ]
    keys = [*time_columns, "asset_type"]
    if dimension != "all":
        keys.insert(len(time_columns), dimension)
    values = period.groupby(keys, as_index=False)[weight_columns].sum()
    denominator_keys = [column for column in keys if column != "asset_type"]
    cells = values[denominator_keys].drop_duplicates().merge(
        pd.DataFrame({"asset_type": ["native", "stable"]}),
        how="cross",
    )
    values = cells.merge(values, on=keys, how="left", validate="one_to_one")
    values[weight_columns] = values[weight_columns].fillna(0.0)
    totals = values.groupby(denominator_keys)[weight_columns].transform("sum")
    for column in weight_columns:
        values[f"{column}_share"] = values[column] / totals[column].where(
            totals[column].gt(0)
        )
    return values


def _mean_period_shares(
    period: pd.DataFrame,
    dimension: str,
    weight_columns: list[str],
    *,
    observation_clock: str,
    anchor_offset_days: int,
) -> pd.DataFrame:
    """Average period shares within year while recording the exact clock."""

    shares = _period_shares(period, dimension, weight_columns)
    period_column = "date" if observation_clock == "daily" else "period_start"
    annual_keys = (
        ["year", "asset_type"]
        if dimension == "all"
        else ["year", dimension, "asset_type"]
    )
    share_columns = [f"{column}_share" for column in weight_columns]
    summary = shares.groupby(annual_keys, as_index=False)[share_columns].mean()
    counts = (
        shares.groupby(annual_keys)[period_column]
        .nunique()
        .rename("periods")
        .reset_index()
    )
    summary = summary.merge(counts, on=annual_keys, how="left", validate="one_to_one")
    summary.insert(0, "dimension", dimension)
    summary.insert(1, "observation_clock", observation_clock)
    summary.insert(2, "anchor_offset_days", anchor_offset_days)
    return summary


def annual_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """Daily and seven-anchor weekly stable/native shares for observable style cuts."""

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
    frames: list[pd.DataFrame] = []
    for dimension in ("all", "morphology", "integration", "complexity"):
        frames.append(
            _mean_period_shares(
                data,
                dimension,
                weight_columns,
                observation_clock="daily",
                anchor_offset_days=-1,
            )
        )
        group_columns = (
            ["asset_type"] if dimension == "all" else [dimension, "asset_type"]
        )
        daily_raw = data.groupby(["date", *group_columns], as_index=False)[
            weight_columns
        ].sum()
        for anchor_offset_days in range(7):
            weekly_raw = aggregate_complete_day_bins(
                daily_raw,
                value_columns=weight_columns,
                group_columns=group_columns,
                anchor_offset_days=anchor_offset_days,
            )
            if not weekly_raw.empty:
                frames.append(
                    _mean_period_shares(
                        weekly_raw,
                        dimension,
                        weight_columns,
                        observation_clock="weekly",
                        anchor_offset_days=anchor_offset_days,
                    )
                )
    return pd.concat(frames, ignore_index=True, sort=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--panel-only", action="store_true")
    args = parser.parse_args()
    route_release = released_route_partitions(ROUTE_COLUMNS)
    paths = list(route_release.paths)
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
        inputs=list(route_release.provenance_anchors),
        notes=(
            "route-intermediary episodes; matched within-20-percent count/value support; "
            "daily pooled value caps; observed on-chain morphology does not identify "
            "frontend or human authorship"
        ),
        preinstall_validator=release_preinstall_validator(route_release),
    )
    if args.panel_only:
        print(f"wrote analysis-ready panel {OUT_PANEL.relative_to(DATA_DIR.parent)}")
        return 0
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

#!/usr/bin/env python3
"""Build the paper's primary vehicle-extent measure over the full unified sample.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/vehicle_excess_use_daily.parquet
        output/exhibits/vehicle_excess_use.jsonl
        output/exhibits/vehicle_excess_use_quarterly.jsonl
        output/exhibits/vehicle_excess_use_transition.jsonl
"""

from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    common_calendar_day_mask,
    holm_adjusted_pvalues,
    year_endpoint_change,
)
from ddvc.analysis.dynamics import aggregate_complete_day_bins
from ddvc.asset_types import CURRENCY_TYPES, backing
from ddvc.data_release import require_node_d_release
from ddvc.paths import REPO_ROOT
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
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
OUT_TRANSITION = REPO_ROOT / "output" / "exhibits" / "vehicle_excess_use_transition.jsonl"
LOCK = OUT_PANEL.with_suffix(".lock")
CODE_SOURCES = [
    "scripts/build_vehicle_excess_use.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/vehicle_extent.py",
    "src/ddvc/route_roles.py",
    "src/ddvc/analysis/dynamics.py",
    "src/ddvc/analysis/regression.py",
]
HAC_LAG = 30
WEEKLY_HAC_LAG_DAYS = 28


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


def token_excess_use_transition_tests(
    panel: pd.DataFrame,
    *,
    focal_symbol: str = "USDT",
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Test whether intermediary use rises beyond endpoint demand on daily and weekly clocks."""

    data = panel[panel["asset_type"].isin(CURRENCY_TYPES)].copy()
    data["year"] = pd.to_datetime(data["date"]).dt.year
    data = data[data["year"].between(baseline_year, comparison_year)]
    daily = data.loc[
        common_calendar_day_mask(
            data["date"],
            data["year"],
            baseline_year=baseline_year,
            comparison_year=comparison_year,
        )
    ].copy()
    if focal_symbol not in set(daily["symbol"].dropna()):
        raise ValueError(f"focal token {focal_symbol} is absent")
    specifications = (
        ("episode", "all_routes", "intermediate_routes", "endpoint_routes"),
        (
            "value",
            "within_20pct",
            "intermediate_usd_within_20pct",
            "endpoint_usd_within_20pct",
        ),
    )
    raw_columns = sorted(
        {
            field
            for _weighting, _support, intermediate_field, endpoint_field in specifications
            for field in (intermediate_field, endpoint_field)
        }
    )
    group_columns = [
        column
        for column in ("token", "symbol", "asset_type")
        if column in data.columns
    ]
    clocks: list[tuple[str, int, int, pd.DataFrame]] = [
        ("daily", -1, hac_lag, daily)
    ]
    daily_raw = data.groupby(["date", *group_columns], as_index=False)[
        raw_columns
    ].sum()
    for anchor_offset_days in range(7):
        weekly = aggregate_complete_day_bins(
            daily_raw,
            value_columns=raw_columns,
            group_columns=group_columns,
            anchor_offset_days=anchor_offset_days,
        )
        if weekly.empty:
            continue
        endpoint = weekly[weekly["year"].isin([baseline_year, comparison_year])]
        terminal_month_day = (
            endpoint.groupby("year")["period_end"].max().dt.strftime("%m-%d")
        )
        if set(terminal_month_day.index) != {baseline_year, comparison_year}:
            continue
        common_terminal = min(
            terminal_month_day.loc[baseline_year],
            terminal_month_day.loc[comparison_year],
        )
        weekly = weekly[
            weekly["period_end"].dt.strftime("%m-%d").le(common_terminal)
        ].copy()
        weekly = weekly.rename(columns={"period_start": "date"})
        clocks.append(("weekly", anchor_offset_days, WEEKLY_HAC_LAG_DAYS, weekly))
    rows: list[dict[str, object]] = []
    for observation_clock, anchor_offset_days, clock_hac_lag, clock_data in clocks:
        for (
            weighting,
            value_support,
            intermediate_field,
            endpoint_field,
        ) in specifications:
            totals = clock_data.groupby(["date", "year"], as_index=False)[
                [intermediate_field, endpoint_field]
            ].sum()
            focal = (
                clock_data[clock_data["symbol"].eq(focal_symbol)]
                .groupby(["date", "year"], as_index=False)[
                    [intermediate_field, endpoint_field]
                ]
                .sum()
            )
            focal = totals.merge(
                focal,
                on=["date", "year"],
                how="left",
                suffixes=("_total", ""),
                validate="one_to_one",
            )
            focal[[intermediate_field, endpoint_field]] = focal[
                [intermediate_field, endpoint_field]
            ].fillna(0.0)
            focal["intermediate_share"] = pd.to_numeric(
                focal[intermediate_field], errors="coerce"
            ) / focal[f"{intermediate_field}_total"].where(
                focal[f"{intermediate_field}_total"].gt(0)
            )
            focal["endpoint_share"] = pd.to_numeric(
                focal[endpoint_field], errors="coerce"
            ) / focal[f"{endpoint_field}_total"].where(
                focal[f"{endpoint_field}_total"].gt(0)
            )
            for transformation in ("share_gap", "log_excess_ratio"):
                sample = focal[["date", "year", "intermediate_share", "endpoint_share"]].copy()
                if transformation == "share_gap":
                    sample["estimand"] = sample["intermediate_share"] - sample["endpoint_share"]
                else:
                    sample = sample[
                        sample["intermediate_share"].gt(0)
                        & sample["endpoint_share"].gt(0)
                    ]
                    sample["estimand"] = np.log(
                        sample["intermediate_share"] / sample["endpoint_share"]
                    )
                sample = sample.dropna(subset=["estimand"])
                estimate = year_endpoint_change(
                    sample["estimand"],
                    sample["year"],
                    baseline_year=baseline_year,
                    comparison_year=comparison_year,
                    hac_lag=clock_hac_lag,
                    dates=sample["date"],
                )
                rows.append(
                    {
                        "focal_symbol": focal_symbol,
                        "observation_clock": observation_clock,
                        "anchor_offset_days": anchor_offset_days,
                        "weighting": weighting,
                        "value_support": value_support,
                        "transformation": transformation,
                        "baseline_year": baseline_year,
                        "comparison_year": comparison_year,
                        "baseline_period_mean": estimate.baseline_mean,
                        "comparison_period_mean": estimate.comparison_mean,
                        "change": estimate.change,
                        "hac_standard_error": estimate.standard_error,
                        "t_statistic": estimate.t_statistic,
                        "p_value": estimate.p_value,
                        "periods": estimate.n_observations,
                        "period_days": 1 if observation_clock == "daily" else 7,
                        "hac_lag_days": clock_hac_lag,
                        "share_perimeter": "prespecified_currency_types",
                    }
                )
    result = pd.DataFrame(rows)
    result["p_value_holm"] = result.groupby(
        ["observation_clock", "anchor_offset_days"]
    )["p_value"].transform(holm_adjusted_pvalues)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--panel-only", action="store_true")
    args = ap.parse_args()
    require_node_d_release(routes=True)
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
    if args.limit is not None:
        print(
            f"smoke reduction complete on {len(files):,} days; canonical outputs unchanged"
        )
        return 0
    write_panel(
        panel,
        OUT_PANEL,
        code_sources=CODE_SOURCES,
        inputs=[UNIFIED],
        notes=(
            "topology-valid cycles excluded; counts use full support; value fields "
            "retain all routes plus nested 2x and 20 percent "
            "source-intermediary-sink coherence bands"
        ),
    )
    if args.panel_only:
        print(f"wrote analysis-ready panel {OUT_PANEL.relative_to(REPO_ROOT)}")
        return 0

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
    transition = token_excess_use_transition_tests(panel)
    write_exhibit(
        transition,
        OUT_TRANSITION,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PANEL],
        notes=(
            "seasonally balanced daily and seven-anchor weekly USDT "
            "intermediary-minus-endpoint use on the prespecified currency perimeter; "
            "Newey-West Bartlett covariance"
        ),
    )
    print(f"\n{panel.date.nunique():,} days, {len(panel):,} token-days")
    print("annual excess-use ratio by asset type, prespecified currencies only (20 percent value-coherence support)")
    table = type_year.pivot(
        index="year", columns="asset_type", values="vehicle_excess_use_ratio_within_20pct"
    )
    print(table.round(2).to_string())
    count_table = type_year.pivot(
        index="year", columns="asset_type", values="vehicle_excess_use_count_ratio"
    )
    print("\ncount-weighted robustness")
    print(count_table.round(2).to_string())
    backing_table = backing_year.pivot(
        index="year", columns="backing", values="vehicle_excess_use_ratio_within_20pct"
    )
    print("\nstable-backing robustness, value weighted on 20 percent coherence support")
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
        f"{OUT_QUARTERLY.relative_to(REPO_ROOT)}, and {OUT_TRANSITION.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="vehicle excess-use panel"):
        raise SystemExit(main())

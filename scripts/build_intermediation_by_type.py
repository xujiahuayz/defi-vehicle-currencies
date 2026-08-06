#!/usr/bin/env python3
"""Daily vehicle-type composition by venue integration and route complexity.

Each coherent non-cyclic route contributes one episode for every intermediary it uses.
The cross-venue split tests whether the native-to-stable transition is confined to the
aggregator-era integration margin or also occurs inside venue-local routing.
The leg-count split tests the narrower composition rival that the transition is confined
to increasingly complex routes; leg count is not interpreted as execution efficiency.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/intermediation_by_type_daily.parquet
        output/exhibits/intermediation_by_type.jsonl
        output/exhibits/intermediation_integration_rival.jsonl
        output/exhibits/intermediation_complexity_rival.jsonl
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import as_completed
from pathlib import Path

import pandas as pd

from ddvc.analysis.regression import common_calendar_day_mask, year_endpoint_change
from ddvc.asset_types import TYPES, classify
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.realised import realised_routes
from ddvc.runtime import exclusive_job, interruptible_process_pool
from ddvc.tables import write_exhibit, write_panel

UNIFIED = DATA_DIR / "unified"
OUT_PARQUET = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "intermediation_by_type.jsonl"
OUT_RIVAL = OUTPUT_DIR / "exhibits" / "intermediation_integration_rival.jsonl"
OUT_COMPLEXITY_RIVAL = OUTPUT_DIR / "exhibits" / "intermediation_complexity_rival.jsonl"
LOCK = OUT_PARQUET.with_suffix(".lock")
MAX_WORKERS = 8
HAC_LAG = 30
INTEGRATION_RIVAL_WINDOWS = ((2023, 2024), (2024, 2026))
CODE_SOURCES = [
    "scripts/build_intermediation_by_type.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/realised.py",
    "src/ddvc/route_roles.py",
    "src/ddvc/asset_types.py",
]
INTEGRATION_SCOPES = ("single_venue", "cross_venue")
COMPLEXITY_SCOPES = (
    "two_leg",
    "more_than_two_legs",
    "single_venue_two_leg",
    "cross_venue_two_leg",
    "single_venue_more_than_two_legs",
    "cross_venue_more_than_two_legs",
)


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
        for scope in COMPLEXITY_SCOPES:
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
    routes["complexity_scope"] = routes["legs"].eq(2).map(
        {True: "two_leg", False: "more_than_two_legs"}
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
        for complexity_scope in ("two_leg", "more_than_two_legs"):
            complexity_cell = selected[
                selected["complexity_scope"].eq(complexity_scope)
            ]
            out[f"cnt_{complexity_scope}_{asset_type}"] = int(len(complexity_cell))
            out[f"usd_{complexity_scope}_{asset_type}"] = float(
                complexity_cell["usd"].sum()
            )
            for integration_scope in INTEGRATION_SCOPES:
                scope = f"{integration_scope}_{complexity_scope}"
                cell = complexity_cell[
                    complexity_cell["integration_scope"].eq(integration_scope)
                ]
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


def _stable_share_change_tests(
    panel: pd.DataFrame,
    *,
    scopes: tuple[str, ...],
    scope_field: str,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Estimate the stable share change within prespecified route regimes."""
    data = panel.copy().sort_values("date", kind="stable")
    data["year"] = pd.to_datetime(data["date"]).dt.year
    data = data[data["year"].between(baseline_year, comparison_year)]
    data = data.loc[
        common_calendar_day_mask(
            data["date"],
            data["year"],
            baseline_year=baseline_year,
            comparison_year=comparison_year,
        )
    ]
    years = sorted(int(value) for value in data["year"].unique())
    if baseline_year not in years or comparison_year not in years:
        raise ValueError("route-regime rival requires both comparison endpoint years")
    rows: list[dict[str, object]] = []
    for weighting, column_prefix in (("episode", "cnt_"), ("value", "usd_")):
        for scope in scopes:
            scope_prefix = "" if scope == "all" else f"{scope}_"
            stable = pd.to_numeric(
                data[f"{column_prefix}{scope_prefix}stable"], errors="coerce"
            )
            native = pd.to_numeric(
                data[f"{column_prefix}{scope_prefix}native"], errors="coerce"
            )
            denominator = stable + native
            sample = data[["year"]].copy()
            sample["share"] = stable / denominator.where(denominator.gt(0))
            sample = sample.dropna(subset=["share"])
            estimate = year_endpoint_change(
                sample["share"],
                sample["year"],
                baseline_year=baseline_year,
                comparison_year=comparison_year,
                hac_lag=hac_lag,
            )
            rows.append(
                {
                    scope_field: scope,
                    "weighting": weighting,
                    "baseline_year": baseline_year,
                    "comparison_year": comparison_year,
                    "baseline_daily_mean": estimate.baseline_mean,
                    "comparison_daily_mean": estimate.comparison_mean,
                    "change": estimate.change,
                    "hac_standard_error": estimate.standard_error,
                    "t_statistic": estimate.t_statistic,
                    "p_value": estimate.p_value,
                    "days": estimate.n_observations,
                    "hac_lag_days": hac_lag,
                    "calendar_support": "month-days observed in both endpoint years",
                    "share_denominator": "native_plus_stable",
                }
            )
    return pd.DataFrame(rows)


def integration_rival_tests(
    panel: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Estimate the stable share change within each integration regime."""
    return _stable_share_change_tests(
        panel,
        scopes=("all", *INTEGRATION_SCOPES),
        scope_field="integration_scope",
        baseline_year=baseline_year,
        comparison_year=comparison_year,
        hac_lag=hac_lag,
    )


def integration_rival_windows(
    panel: pd.DataFrame,
    *,
    windows: tuple[tuple[int, int], ...] = INTEGRATION_RIVAL_WINDOWS,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Measure the prespecified reversal and subsequent transition windows."""
    return pd.concat(
        [
            integration_rival_tests(
                panel,
                baseline_year=baseline_year,
                comparison_year=comparison_year,
                hac_lag=hac_lag,
            )
            for baseline_year, comparison_year in windows
        ],
        ignore_index=True,
    )


def complexity_rival_tests(
    panel: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Estimate stable-share changes within route-complexity and integration cells."""
    return _stable_share_change_tests(
        panel,
        scopes=COMPLEXITY_SCOPES,
        scope_field="routing_scope",
        baseline_year=baseline_year,
        comparison_year=comparison_year,
        hac_lag=hac_lag,
    )


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
    with interruptible_process_pool(workers) as pool:
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
    rival = integration_rival_windows(panel)
    complexity_rival = complexity_rival_tests(panel)
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
    write_exhibit(
        rival,
        OUT_RIVAL,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PARQUET],
        notes="equal-weighted daily stable share within native plus stable; Newey-West Bartlett covariance",
    )
    write_exhibit(
        complexity_rival,
        OUT_COMPLEXITY_RIVAL,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PARQUET],
        notes="equal-weighted daily stable share within native plus stable by route-complexity and integration cell; leg count is a complexity proxy, not an efficiency measure; Newey-West Bartlett covariance",
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
    for (baseline_year, comparison_year), comparison in rival.groupby(
        ["baseline_year", "comparison_year"], sort=True
    ):
        print(f"\n{baseline_year} to {comparison_year} stable-share changes, daily HAC inference")
        print(
            comparison[
                [
                    "integration_scope",
                    "weighting",
                    "baseline_daily_mean",
                    "comparison_daily_mean",
                    "change",
                    "hac_standard_error",
                    "p_value",
                ]
            ].round(4).to_string(index=False)
        )
    print("\n2024 to 2026 stable-share changes by route-complexity cell")
    print(
        complexity_rival[
            [
                "routing_scope",
                "weighting",
                "baseline_daily_mean",
                "comparison_daily_mean",
                "change",
                "hac_standard_error",
                "p_value",
            ]
        ].round(4).to_string(index=False)
    )
    print(
        f"\nwrote {OUT_PARQUET.relative_to(REPO_ROOT)}, "
        f"{OUT_EXHIBIT.relative_to(REPO_ROOT)}, {OUT_RIVAL.relative_to(REPO_ROOT)}, "
        f"and {OUT_COMPLEXITY_RIVAL.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="intermediation-by-type panel"):
        sys.exit(main())

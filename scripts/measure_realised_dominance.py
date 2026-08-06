#!/usr/bin/env python3
"""Separate forced from chosen vehicle use at the same hourly cost opportunity set.

For each realised coherent vehicle route, this estimator matches the route to the
counterfactual panel in the same UTC hour and at the nearest notional in log size.
It reports routes with no supported direct quote, routes with both route families
supported, unsupported routes, and dominance only inside the both-supported sample.

The match is an hourly proxy, not transaction-state identification. Any claim about
what the router could have chosen remains withheld until transaction-state counterfactual validation passes.

Reads   data/unified/YYYYMMDD.parquet
        data/empirical/route_cost_panel_v2.parquet
Writes  output/exhibits/realised_dominance.jsonl
        output/exhibits/realised_dominance_reweighting.jsonl
        output/exhibits/intermediation_choice_regime_rival.jsonl
        data/processed/realised_dominance_daily.parquet
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from ddvc.analysis.regression import common_calendar_day_mask, year_endpoint_change
from ddvc.asset_types import classify
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.provenance import verify
from ddvc.realised import (
    cost_panel_days,
    match_realised_to_cost_panel,
    read_cost_panel_day,
    realised_routes,
)
from ddvc.runtime import exclusive_job
from ddvc.tables import write_exhibit, write_panel

PANEL = DATA_DIR / "empirical" / "route_cost_panel_v2.parquet"
OUT = OUTPUT_DIR / "exhibits" / "realised_dominance.jsonl"
TYPE_OUT = OUTPUT_DIR / "exhibits" / "realised_dominance_reweighting.jsonl"
CHOICE_OUT = OUTPUT_DIR / "exhibits" / "intermediation_choice_regime_rival.jsonl"
DAILY_OUT = DATA_DIR / "processed" / "realised_dominance_daily.parquet"
LOCK = DAILY_OUT.with_suffix(".lock")
CODE_SOURCES = [
    "scripts/measure_realised_dominance.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/realised.py",
    "src/ddvc/route_roles.py",
    "src/ddvc/asset_types.py",
]
RIVAL_WINDOWS = ((2023, 2024), (2024, 2026))
CHOICE_STATUSES = ("forced_no_direct", "chosen_with_direct")
HAC_LAG = 30
SIZE_SCOPES = (
    ("all_routes", None, None),
    ("within_2x", 0.5, 2.0),
    ("within_20pct", 0.8, 1.2),
)


def summarise_matches(matches: pd.DataFrame, period: str) -> pd.DataFrame:
    """Additive cells that can be pooled without averaging daily rates."""
    if matches.empty:
        return pd.DataFrame()
    data = matches.copy()
    data["mid_type"] = data["vehicle"].map(
        {value: classify(value)[1] for value in data["vehicle"].unique()}
    )
    data["dominated_flag"] = data["dominated"].eq(True)
    data["dominated_usd"] = data["usd"].where(data["dominated_flag"], 0.0)
    rows: list[pd.DataFrame] = []
    ratio = pd.to_numeric(data["quoted_to_realised_size"], errors="coerce")
    for scope, lower, upper in SIZE_SCOPES:
        selected = (
            data
            if lower is None or upper is None
            else data[ratio.between(lower, upper, inclusive="both")]
        )
        if selected.empty:
            continue
        summary = (
            selected.groupby(["mid_type", "match_status"], as_index=False)
            .agg(
                routes=("route_id", "size"),
                usd=("usd", "sum"),
                dominated_routes=("dominated_flag", "sum"),
                dominated_usd=("dominated_usd", "sum"),
            )
        )
        summary.insert(0, "size_scope", scope)
        rows.append(summary)
    out = pd.concat(rows, ignore_index=True)
    out.insert(0, "period", period)
    return out


def pool_summaries(cells: pd.DataFrame, period: str) -> pd.DataFrame:
    if cells.empty:
        return cells
    out = (
        cells.groupby(["size_scope", "mid_type", "match_status"], as_index=False)[
            ["routes", "usd", "dominated_routes", "dominated_usd"]
        ]
        .sum()
    )
    totals = out.groupby(["size_scope", "mid_type"])
    out["route_share_within_type"] = out["routes"] / totals["routes"].transform("sum")
    out["usd_share_within_type"] = out["usd"] / totals["usd"].transform("sum")
    comparable = out["match_status"].eq("chosen_with_direct")
    out["dominated_share"] = (
        out["dominated_routes"] / out["routes"].where(comparable & out["routes"].gt(0))
    )
    out["dominated_usd_share"] = (
        out["dominated_usd"] / out["usd"].where(comparable & out["usd"].gt(0))
    )
    out.insert(0, "period", period)
    return out


def choice_regime_rival_tests(
    cells: pd.DataFrame,
    *,
    windows: tuple[tuple[int, int], ...] = RIVAL_WINDOWS,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Stable-share changes within the panel-supported route-opportunity regimes."""
    data = cells[
        cells["mid_type"].isin(["native", "stable"])
        & cells["match_status"].isin(CHOICE_STATUSES)
    ].copy()
    data["date"] = pd.to_datetime(data["period"], format="%Y%m%d")
    rows: list[dict[str, object]] = []
    for size_scope in data["size_scope"].drop_duplicates():
        for match_status in CHOICE_STATUSES:
            selected = data[
                data["size_scope"].eq(size_scope)
                & data["match_status"].eq(match_status)
            ]
            for weighting, value_column in (("episode", "routes"), ("value", "usd")):
                daily = selected.pivot_table(
                    index="date",
                    columns="mid_type",
                    values=value_column,
                    aggfunc="sum",
                    fill_value=0.0,
                ).reset_index()
                for asset_type in ("native", "stable"):
                    if asset_type not in daily:
                        daily[asset_type] = 0.0
                daily["year"] = daily["date"].dt.year
                denominator = daily["native"] + daily["stable"]
                daily["stable_share"] = daily["stable"] / denominator.where(
                    denominator.gt(0)
                )
                for baseline_year, comparison_year in windows:
                    sample = daily[daily["year"].between(baseline_year, comparison_year)]
                    sample = sample.loc[
                        common_calendar_day_mask(
                            sample["date"],
                            sample["year"],
                            baseline_year=baseline_year,
                            comparison_year=comparison_year,
                        )
                    ].dropna(subset=["stable_share"])
                    estimate = year_endpoint_change(
                        sample["stable_share"],
                        sample["year"],
                        baseline_year=baseline_year,
                        comparison_year=comparison_year,
                        hac_lag=hac_lag,
                    )
                    rows.append(
                        {
                            "size_scope": size_scope,
                            "match_status": match_status,
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=None, help="first N panel days")
    parser.add_argument(
        "--reuse-daily",
        action="store_true",
        help="rebuild only derived exhibits from a current daily match panel",
    )
    args = parser.parse_args()
    if args.reuse_daily and args.days is not None:
        parser.error("--reuse-daily and --days cannot be combined")

    if not PANEL.exists():
        print(f"missing {PANEL.relative_to(REPO_ROOT)}")
        return 1

    if args.reuse_daily:
        verdict = verify(DAILY_OUT)
        if verdict.get("status") != "ok":
            print(f"daily match panel is {verdict.get('status')}; refusing reuse")
            return 1
        cells = pd.read_parquet(DAILY_OUT)
        print(f"reusing {len(cells):,} daily additive match cells", flush=True)
    else:
        import duckdb

        connection = duckdb.connect()
        daily: list[pd.DataFrame] = []
        try:
            all_days = cost_panel_days(connection, PANEL)
            days = all_days[: max(0, args.days)] if args.days is not None else all_days
            if not days:
                print("no priced days in the route-cost panel")
                return 1
            print(f"matching realised routes on {len(days):,} priced days", flush=True)

            for index, day in enumerate(days, 1):
                realised = realised_routes(day)
                if realised.empty:
                    continue
                quoted = read_cost_panel_day(connection, PANEL, day)
                matched = match_realised_to_cost_panel(realised, quoted)
                summary = summarise_matches(matched, day)
                if not summary.empty:
                    daily.append(summary)
                if index % 25 == 0 or index == len(days):
                    chosen = int(matched["match_status"].eq("chosen_with_direct").sum())
                    no_direct = int(matched["match_status"].eq("forced_no_direct").sum())
                    print(
                        f"  {index:,}/{len(days):,} {day}: {len(realised):,} vehicle routes, "
                        f"{chosen:,} both-supported, {no_direct:,} no-supported-direct",
                        flush=True,
                    )
        finally:
            connection.close()
        if not daily:
            print("no realised vehicle route matched the priced calendar")
            return 1
        cells = pd.concat(daily, ignore_index=True)
        if args.days is not None and len(days) < len(all_days):
            print("partial smoke run complete; canonical outputs unchanged")
            return 0
        write_panel(
            cells,
            DAILY_OUT,
            code_sources=CODE_SOURCES,
            inputs=[PANEL, DATA_DIR / "unified"],
            notes="daily additive exact-hour match cells with nested notional support",
        )
    cells["year"] = cells["period"].str[:4]
    pooled = [pool_summaries(cells, "ALL")]
    for year, group in cells.groupby("year"):
        pooled.append(pool_summaries(group, str(year)))
    result = pd.concat(pooled, ignore_index=True)
    write_exhibit(
        result,
        OUT,
        code_sources=CODE_SOURCES,
        inputs=[DAILY_OUT],
        notes="exact-hour, nearest-log-size proxy; transaction-state choice claims withheld",
    )
    type_detail = result[result["period"].eq("ALL")].copy()
    write_exhibit(
        type_detail,
        TYPE_OUT,
        code_sources=CODE_SOURCES,
        inputs=[DAILY_OUT],
        notes="type-stratified cells; no composition reweighting imposed",
    )
    choice_rival = choice_regime_rival_tests(cells)
    write_exhibit(
        choice_rival,
        CHOICE_OUT,
        code_sources=CODE_SOURCES,
        inputs=[DAILY_OUT],
        notes="equal-weighted daily stable share within native plus stable; hour-end support regimes are descriptive proxies, not transaction-state choice",
    )

    overall = result[result["period"].eq("ALL")]
    for size_scope, support in overall.groupby("size_scope", sort=False):
        print(f"\nfull-period exact-hour decomposition: {size_scope}")
        for row in support.itertuples(index=False):
            dominated = (
                f", dominated {row.dominated_share:.1%}"
                if row.match_status == "chosen_with_direct"
                else ""
            )
            print(
                f"  {row.mid_type:<14} {row.match_status:<27} "
                f"{row.routes:>10,.0f} ({row.route_share_within_type:>6.1%}){dominated}"
            )
    print("\nchoice-regime stable-share changes")
    print(
        choice_rival[
            [
                "baseline_year",
                "comparison_year",
                "size_scope",
                "match_status",
                "weighting",
                "change",
                "hac_standard_error",
                "p_value",
                "days",
            ]
        ].round(4).to_string(index=False)
    )
    print(
        f"\nwrote {DAILY_OUT.relative_to(REPO_ROOT)}, {OUT.relative_to(REPO_ROOT)}, "
        f"{TYPE_OUT.relative_to(REPO_ROOT)}, and {CHOICE_OUT.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="realised route-to-cost matches"):
        sys.exit(main())

#!/usr/bin/env python3
"""Separate forced from chosen vehicle use at the same hourly cost opportunity set.

For each realised coherent vehicle route, this estimator matches the route to the
counterfactual panel in the same UTC hour and at the nearest notional in log size.
It reports forced routes (no direct quote), chosen routes (both route families
available), unsupported routes, and dominance only inside the chosen sample.

The match is an hourly proxy, not transaction-state identification. Any claim about
what the router could have chosen remains withheld until transaction-state counterfactual validation passes.

Reads   data/unified/YYYYMMDD.parquet
        data/empirical/route_cost_panel_v2.parquet
Writes  output/exhibits/realised_dominance.jsonl
        output/exhibits/realised_dominance_reweighting.jsonl
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from ddvc.asset_types import classify
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.realised import (
    cost_panel_days,
    match_realised_to_cost_panel,
    read_cost_panel_day,
    realised_routes,
)
from ddvc.tables import write_exhibit

PANEL = DATA_DIR / "empirical" / "route_cost_panel_v2.parquet"
OUT = OUTPUT_DIR / "exhibits" / "realised_dominance.jsonl"
TYPE_OUT = OUTPUT_DIR / "exhibits" / "realised_dominance_reweighting.jsonl"
CODE_SOURCES = [
    "scripts/measure_realised_dominance.py",
    "src/ddvc/realised.py",
    "src/ddvc/asset_types.py",
]


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
    out = (
        data.groupby(["mid_type", "match_status"], as_index=False)
        .agg(
            routes=("route_id", "size"),
            usd=("usd", "sum"),
            dominated_routes=("dominated_flag", "sum"),
            dominated_usd=("dominated_usd", "sum"),
        )
    )
    out.insert(0, "period", period)
    return out


def pool_summaries(cells: pd.DataFrame, period: str) -> pd.DataFrame:
    if cells.empty:
        return cells
    out = (
        cells.groupby(["mid_type", "match_status"], as_index=False)[
            ["routes", "usd", "dominated_routes", "dominated_usd"]
        ]
        .sum()
    )
    totals = out.groupby("mid_type")
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=None, help="first N panel days")
    args = parser.parse_args()

    if not PANEL.exists():
        print(f"missing {PANEL.relative_to(REPO_ROOT)}")
        return 1

    import duckdb

    connection = duckdb.connect()
    daily: list[pd.DataFrame] = []
    try:
        days = cost_panel_days(connection, PANEL)
        if args.days is not None:
            days = days[: max(0, args.days)]
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
                forced = int(matched["match_status"].eq("forced_no_direct").sum())
                print(
                    f"  {index:,}/{len(days):,} {day}: {len(realised):,} vehicle routes, "
                    f"{chosen:,} chosen-with-direct, {forced:,} forced",
                    flush=True,
                )
    finally:
        connection.close()
    if not daily:
        print("no realised vehicle route matched the priced calendar")
        return 1

    cells = pd.concat(daily, ignore_index=True)
    cells["year"] = cells["period"].str[:4]
    pooled = [pool_summaries(cells, "ALL")]
    for year, group in cells.groupby("year"):
        pooled.append(pool_summaries(group, str(year)))
    result = pd.concat(pooled, ignore_index=True)
    write_exhibit(
        result,
        OUT,
        code_sources=CODE_SOURCES,
        inputs=[PANEL, DATA_DIR / "unified"],
        notes="exact-hour, nearest-log-size proxy; transaction-state choice claims withheld",
    )
    type_detail = result[result["period"].eq("ALL")].copy()
    write_exhibit(
        type_detail,
        TYPE_OUT,
        code_sources=CODE_SOURCES,
        inputs=[PANEL, DATA_DIR / "unified"],
        notes="type-stratified cells; no composition reweighting imposed",
    )

    overall = result[result["period"].eq("ALL")]
    print("\nfull-period exact-hour decomposition")
    for row in overall.itertuples(index=False):
        dominated = (
            f", dominated {row.dominated_share:.1%}"
            if row.match_status == "chosen_with_direct"
            else ""
        )
        print(
            f"  {row.mid_type:<14} {row.match_status:<27} "
            f"{row.routes:>10,.0f} ({row.route_share_within_type:>6.1%}){dominated}"
        )
    print(f"\nwrote {OUT.relative_to(REPO_ROOT)} and {TYPE_OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

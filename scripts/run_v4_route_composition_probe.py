#!/usr/bin/env python3
"""Compare V3 and V4 vehicle composition on matched ordered-pair weeks.

This is a route-only descriptive probe.  It holds the ordered source/destination
assets and calendar week fixed, then compares the share of pure Uniswap V3 and
pure Uniswap V4 intermediary routes carried by stablecoins and by ETH/WETH.
Architecture adoption is endogenous, so the estimates are not treatment
effects.  Two-way CR1 inference allows dependence within ordered pairs and
weeks; pooled route- and value-weighted differences are descriptive companions.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import holm_adjusted_pvalues, ols_clustered
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.provenance import current_artifacts
from ddvc.tables import write_exhibit


ROUTES = DATA_DIR / "empirical" / "v4_settlement_route_units.parquet"
RESULTS = OUTPUT_DIR / "exhibits" / "v4_route_composition_probe_results.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits" / "v4_route_composition_probe_support.jsonl"
DEXES = ("uniswap_v3", "uniswap_v4")
STABLE_VEHICLES = ("USDC", "USDT", "DAI")
NATIVE_VEHICLES = ("ETH/WETH",)
CODE_SOURCES = [
    "scripts/run_v4_route_composition_probe.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/tables.py",
]


def aggregate_pair_weeks(routes: Path) -> pd.DataFrame:
    """Aggregate route units before loading them into pandas."""

    connection = duckdb.connect()
    try:
        frame = connection.execute(
            """
            SELECT
                CAST(week AS DATE) AS week,
                CAST(src AS VARCHAR) AS src,
                CAST(sink AS VARCHAR) AS sink,
                CAST(dex AS VARCHAR) AS dex,
                count(*)::BIGINT AS routes,
                sum(route_usd)::DOUBLE AS route_usd,
                sum(CASE WHEN vehicle IN ('USDC', 'USDT', 'DAI') THEN 1 ELSE 0 END)::BIGINT
                    AS stable_routes,
                sum(CASE WHEN vehicle IN ('USDC', 'USDT', 'DAI') THEN route_usd ELSE 0 END)::DOUBLE
                    AS stable_route_usd,
                sum(CASE WHEN vehicle = 'ETH/WETH' THEN 1 ELSE 0 END)::BIGINT
                    AS native_routes,
                sum(CASE WHEN vehicle = 'ETH/WETH' THEN route_usd ELSE 0 END)::DOUBLE
                    AS native_route_usd
            FROM read_parquet(?)
            WHERE dex IN ('uniswap_v3', 'uniswap_v4')
            GROUP BY week, src, sink, dex
            """,
            [str(routes)],
        ).df()
    finally:
        connection.close()
    if frame.empty:
        raise ValueError("V3/V4 route-composition input is empty")
    if frame.duplicated(["week", "src", "sink", "dex"]).any():
        raise ValueError("V3/V4 route-composition aggregation repeats a pair-week architecture")
    return frame


def matched_pair_weeks(aggregate: pd.DataFrame, *, min_routes: int) -> pd.DataFrame:
    if min_routes < 1:
        raise ValueError("matched V3/V4 support requires at least one route")
    value_columns = [
        "routes",
        "route_usd",
        "stable_routes",
        "stable_route_usd",
        "native_routes",
        "native_route_usd",
    ]
    wide = aggregate.pivot(
        index=["week", "src", "sink"], columns="dex", values=value_columns
    )
    required = [(column, dex) for column in value_columns for dex in DEXES]
    missing = [column for column in required if column not in wide.columns]
    if missing:
        raise ValueError(f"matched V3/V4 support lacks columns: {missing}")
    wide = wide.dropna(subset=[("routes", dex) for dex in DEXES]).copy()
    for dex in DEXES:
        wide = wide[wide[("routes", dex)].ge(min_routes)]
    wide = wide.reset_index()
    wide.columns = [
        column if isinstance(column, str) else "_".join(part for part in column if part)
        for column in wide.columns
    ]
    wide["ordered_pair"] = wide["src"].astype(str) + "|" + wide["sink"].astype(str)
    for dex in DEXES:
        routes = wide[f"routes_{dex}"].astype(float)
        value = wide[f"route_usd_{dex}"].astype(float)
        if routes.le(0).any() or value.le(0).any():
            raise ValueError("matched V3/V4 pair-weeks require positive count and value denominators")
        wide[f"stable_count_share_{dex}"] = wide[f"stable_routes_{dex}"] / routes
        wide[f"native_count_share_{dex}"] = wide[f"native_routes_{dex}"] / routes
        wide[f"stable_value_share_{dex}"] = wide[f"stable_route_usd_{dex}"] / value
        wide[f"native_value_share_{dex}"] = wide[f"native_route_usd_{dex}"] / value
    return wide


def _pooled_share(frame: pd.DataFrame, numerator: str, denominator: str, dex: str) -> float:
    return float(frame[f"{numerator}_{dex}"].sum() / frame[f"{denominator}_{dex}"].sum())


def estimate_composition(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    definitions = (
        ("stable_count_share", "stable_routes", "routes"),
        ("stable_value_share", "stable_route_usd", "route_usd"),
        ("native_count_share", "native_routes", "routes"),
        ("native_value_share", "native_route_usd", "route_usd"),
    )
    for outcome, numerator, denominator in definitions:
        v3 = frame[f"{outcome}_uniswap_v3"].astype(float)
        v4 = frame[f"{outcome}_uniswap_v4"].astype(float)
        difference = v4 - v3
        fit = ols_clustered(
            difference,
            np.ones(len(frame)),
            frame["week"],
            add_constant=False,
            additional_clusters=(frame["ordered_pair"],),
            min_observations=30,
            min_clusters=10,
        )
        standard_error = float(fit.standard_errors[0])
        if not np.isfinite(standard_error) or standard_error <= 0:
            raise RuntimeError(f"{outcome} has invalid two-way clustered variance")
        degrees_freedom = fit.n_clusters - 1
        critical = float(stats.t.ppf(0.975, degrees_freedom))
        estimate = float(fit.beta[0])
        cluster_counts = fit.cluster_counts
        rows.append(
            {
                "outcome": outcome,
                "matched_pair_weeks": int(fit.n_observations),
                "ordered_pair_clusters": int(cluster_counts[1]),
                "calendar_week_clusters": int(cluster_counts[0]),
                "v3_equal_cell_mean": float(v3.mean()),
                "v4_equal_cell_mean": float(v4.mean()),
                "v4_minus_v3": estimate,
                "standard_error": standard_error,
                "t_statistic": float(fit.t_statistics[0]),
                "p_value": float(fit.p_values[0]),
                "confidence_interval_lower": estimate - critical * standard_error,
                "confidence_interval_upper": estimate + critical * standard_error,
                "v3_pooled_share": _pooled_share(frame, numerator, denominator, "uniswap_v3"),
                "v4_pooled_share": _pooled_share(frame, numerator, denominator, "uniswap_v4"),
                "covariance": "two_way_ordered_pair_calendar_week_cr1",
                "claim_status": "descriptive_matched_realised_route_composition",
            }
        )
    result = pd.DataFrame(rows)
    result["p_value_holm"] = holm_adjusted_pvalues(result["p_value"])
    return result


def support_record(frame: pd.DataFrame, *, min_routes: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "matched_pair_weeks": len(frame),
                "ordered_pairs": int(frame["ordered_pair"].nunique()),
                "calendar_weeks": int(pd.to_datetime(frame["week"]).nunique()),
                "first_week": str(pd.to_datetime(frame["week"]).min().date()),
                "last_week": str(pd.to_datetime(frame["week"]).max().date()),
                "minimum_routes_per_architecture": min_routes,
                "v3_routes": int(frame["routes_uniswap_v3"].sum()),
                "v4_routes": int(frame["routes_uniswap_v4"].sum()),
                "stable_vehicles": "|".join(STABLE_VEHICLES),
                "native_vehicle": "|".join(NATIVE_VEHICLES),
                "comparison": "same_ordered_source_destination_and_calendar_week",
                "omitted_dimensions": "feasible_routes|route_size|router|hooks|fees|liquidity|selection_into_v4",
            }
        ]
    )


def run(
    routes: Path,
    *,
    min_routes: int,
    results_output: Path,
    support_output: Path,
) -> pd.DataFrame:
    with current_artifacts([routes], consumer="V4 matched route-composition probe"):
        aggregate = aggregate_pair_weeks(routes)
        matched = matched_pair_weeks(aggregate, min_routes=min_routes)
        results = estimate_composition(matched)
        support = support_record(matched, min_routes=min_routes)
        notes = (
            "Exploratory route-only V3/V4 composition comparison on exact ordered-pair weeks; "
            "architecture selection remains endogenous and no causal treatment claim is admitted"
        )
        write_exhibit(
            results,
            results_output,
            code_sources=CODE_SOURCES,
            inputs=[routes],
            notes=notes,
        )
        write_exhibit(
            support,
            support_output,
            code_sources=CODE_SOURCES,
            inputs=[routes],
            notes=notes,
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, default=ROUTES)
    parser.add_argument("--min-routes", type=int, default=5)
    parser.add_argument("--results-output", type=Path, default=RESULTS)
    parser.add_argument("--support-output", type=Path, default=SUPPORT)
    args = parser.parse_args()
    results = run(
        args.routes,
        min_routes=args.min_routes,
        results_output=args.results_output,
        support_output=args.support_output,
    )
    for row in results.itertuples(index=False):
        print(
            f"{row.outcome}: {100 * row.v4_minus_v3:+.2f} pp "
            f"(SE {100 * row.standard_error:.2f}; Holm p={row.p_value_holm:.4g})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Decompose USDT's two-leg vehicle transition by venue-integration mix.

This is an E0 route-only diagnostic. It does not open raw acquisition or
state-dependent frontier data. The estimand asks whether USDT's 2024 to 2026
rise among native-currency, USDC and USDT exact two-leg routes is a within-cell
transition, or mostly a migration toward cross-venue routes where USDT was
already more likely to be the vehicle.

Reads   data/processed/intermediation_by_type_daily.parquet
Writes  output/exhibits/e0_usdt_integration_decomposition.jsonl
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    common_calendar_day_mask,
    holm_adjusted_pvalues,
    year_endpoint_change,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import bounded_workers, interruptible_process_pool
from ddvc.tables import write_exhibit
from scripts.process.build_intermediation_by_type import (
    HAC_LAG,
    INTEGRATION_SCOPES,
    TOKEN_INTERACTION_COMPONENTS,
    one_day,
    value_field,
)


UNIFIED = DATA_DIR / "unified"
INTERMEDIATION = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "e0_usdt_integration_decomposition.jsonl"
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
FOCAL_SYMBOL = "USDT"
CODE_SOURCES = [
    "scripts/analyze/run_usdt_integration_decomposition_e0.py",
    "scripts/process/build_intermediation_by_type.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/tables.py",
]
ESTIMANDS = (
    ("episode", "all_routes", "cnt_"),
    ("value", "within_20pct", "usd_within_20pct_"),
)


def _cell_columns(prefix: str, scope: str) -> tuple[str, list[str]]:
    routing_scope = f"{scope}_two_leg"
    focal = f"{prefix}{routing_scope}_{FOCAL_SYMBOL}"
    components = [
        f"{prefix}{routing_scope}_{component}"
        for component in TOKEN_INTERACTION_COMPONENTS
    ]
    return focal, components


def required_columns() -> set[str]:
    columns = {"date"}
    for _weighting, _value_support, prefix in ESTIMANDS:
        for scope in INTEGRATION_SCOPES:
            focal, components = _cell_columns(prefix, scope)
            columns.update([focal, *components])
    return columns


def has_required_columns(panel: pd.DataFrame) -> bool:
    return required_columns().issubset(panel.columns)


def reduce_unified_days(
    *,
    unified_root: Path = UNIFIED,
    workers: int = 8,
    limit: int | None = None,
) -> pd.DataFrame:
    """Build the narrow token-integration panel directly from released route files."""

    paths = sorted(unified_root.glob("*.parquet"))
    if limit is not None:
        paths = paths[:limit]
    if not paths:
        raise FileNotFoundError(f"no unified day files under {unified_root}")
    rows: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    with interruptible_process_pool(bounded_workers(workers)) as pool:
        futures = {pool.submit(one_day, path): path for path in paths}
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            (errors if "error" in result else rows).append(result)
            if index % 250 == 0 or index == len(paths):
                print(f"  reduced {index:,}/{len(paths):,} unified days", flush=True)
    if errors:
        first = errors[0]
        raise RuntimeError(
            f"{len(errors):,} unified day reduction(s) failed; first "
            f"{first['date']}: {first['error']}"
        )
    panel = pd.DataFrame(rows).sort_values("date").reset_index(drop=True).fillna(0)
    missing = sorted(required_columns() - set(panel.columns))
    if missing:
        raise ValueError(f"direct unified reduction missed required columns: {missing}")
    return panel


def _endpoint_sample(
    panel: pd.DataFrame,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> pd.DataFrame:
    data = panel.copy().sort_values("date", kind="stable")
    data["date"] = pd.to_datetime(data["date"])
    data["year"] = data["date"].dt.year
    data = data[data["year"].between(baseline_year, comparison_year)]
    data = data.loc[
        common_calendar_day_mask(
            data["date"],
            data["year"],
            baseline_year=baseline_year,
            comparison_year=comparison_year,
        )
    ].copy()
    observed = set(int(value) for value in data["year"].unique())
    if {baseline_year, comparison_year} - observed:
        raise ValueError("USDT integration decomposition requires both endpoint years")
    return data


def scope_change_tests(
    panel: pd.DataFrame,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Estimate USDT-share changes separately inside single- and cross-venue routes."""

    data = _endpoint_sample(
        panel,
        baseline_year=baseline_year,
        comparison_year=comparison_year,
    )
    rows: list[dict[str, object]] = []
    for weighting, value_support, prefix in ESTIMANDS:
        for scope in INTEGRATION_SCOPES:
            focal, components = _cell_columns(prefix, scope)
            missing = sorted(set([focal, *components]) - set(data.columns))
            if missing:
                raise ValueError(f"intermediation panel is missing columns: {missing}")
            sample = data[["date", "year"]].copy()
            denominator = sum(
                pd.to_numeric(data[column], errors="coerce") for column in components
            )
            sample["share"] = pd.to_numeric(data[focal], errors="coerce") / denominator.where(
                denominator.gt(0)
            )
            for transformation in ("share_level", "log_odds"):
                transformed = sample.dropna(subset=["share"]).copy()
                if transformation == "log_odds":
                    transformed = transformed[
                        transformed["share"].between(0, 1, inclusive="neither")
                    ].copy()
                    transformed["estimand"] = np.log(
                        transformed["share"] / (1 - transformed["share"])
                    )
                else:
                    transformed["estimand"] = transformed["share"]
                estimate = year_endpoint_change(
                    transformed["estimand"],
                    transformed["year"],
                    baseline_year=baseline_year,
                    comparison_year=comparison_year,
                    hac_lag=hac_lag,
                    dates=transformed["date"],
                )
                rows.append(
                    {
                        "record_type": "scope_change_test",
                        "focal_symbol": FOCAL_SYMBOL,
                        "comparison_components": "+".join(TOKEN_INTERACTION_COMPONENTS),
                        "routing_scope": f"{scope}_two_leg",
                        "weighting": weighting,
                        "value_support": value_support,
                        "transformation": transformation,
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
                    }
                )
    result = pd.DataFrame(rows)
    result["p_value_holm"] = result.groupby(
        ["weighting", "value_support", "transformation"], sort=False
    )["p_value"].transform(holm_adjusted_pvalues)
    return result


def ratio_of_totals_cells(
    panel: pd.DataFrame,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> pd.DataFrame:
    """Return endpoint-year USDT shares and route-mix weights by integration scope."""

    data = _endpoint_sample(
        panel,
        baseline_year=baseline_year,
        comparison_year=comparison_year,
    )
    rows: list[dict[str, object]] = []
    for weighting, value_support, prefix in ESTIMANDS:
        by_scope: list[pd.DataFrame] = []
        for scope in INTEGRATION_SCOPES:
            focal, components = _cell_columns(prefix, scope)
            frame = data[["year"]].copy()
            frame["routing_scope"] = f"{scope}_two_leg"
            frame["focal"] = pd.to_numeric(data[focal], errors="coerce")
            frame["denominator"] = sum(
                pd.to_numeric(data[column], errors="coerce") for column in components
            )
            by_scope.append(frame)
        stacked = pd.concat(by_scope, ignore_index=True)
        totals = stacked.groupby("year", as_index=False)["denominator"].sum().rename(
            columns={"denominator": "total_denominator"}
        )
        grouped = (
            stacked.groupby(["year", "routing_scope"], as_index=False)[
                ["focal", "denominator"]
            ]
            .sum()
            .merge(totals, on="year", validate="many_to_one")
        )
        grouped["usdt_share"] = grouped["focal"] / grouped["denominator"].where(
            grouped["denominator"].gt(0)
        )
        grouped["route_mix_weight"] = grouped["denominator"] / grouped[
            "total_denominator"
        ].where(grouped["total_denominator"].gt(0))
        for row in grouped.itertuples(index=False):
            rows.append(
                {
                    "record_type": "endpoint_scope_ratio",
                    "focal_symbol": FOCAL_SYMBOL,
                    "comparison_components": "+".join(TOKEN_INTERACTION_COMPONENTS),
                    "routing_scope": row.routing_scope,
                    "weighting": weighting,
                    "value_support": value_support,
                    "year": int(row.year),
                    "usdt_share": float(row.usdt_share),
                    "route_mix_weight": float(row.route_mix_weight),
                    "focal_numerator": float(row.focal),
                    "scope_denominator": float(row.denominator),
                    "total_denominator": float(row.total_denominator),
                }
            )
    return pd.DataFrame(rows)


def midpoint_decomposition(
    cells: pd.DataFrame,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> pd.DataFrame:
    """Oaxaca-style midpoint decomposition of the total USDT-share change."""

    rows: list[dict[str, object]] = []
    for (weighting, value_support), group in cells.groupby(
        ["weighting", "value_support"], sort=False
    ):
        wide = group.pivot(
            index="routing_scope",
            columns="year",
            values=["usdt_share", "route_mix_weight"],
        )
        if baseline_year not in wide["usdt_share"] or comparison_year not in wide["usdt_share"]:
            raise ValueError("endpoint-scope ratios are missing an endpoint year")
        p0 = wide["usdt_share"][baseline_year].astype(float)
        p1 = wide["usdt_share"][comparison_year].astype(float)
        w0 = wide["route_mix_weight"][baseline_year].astype(float)
        w1 = wide["route_mix_weight"][comparison_year].astype(float)
        total_change = float((w1 * p1).sum() - (w0 * p0).sum())
        within_scope_change = float((((w0 + w1) / 2) * (p1 - p0)).sum())
        between_scope_composition_change = float((((p0 + p1) / 2) * (w1 - w0)).sum())
        rows.append(
            {
                "record_type": "midpoint_decomposition",
                "focal_symbol": FOCAL_SYMBOL,
                "comparison_components": "+".join(TOKEN_INTERACTION_COMPONENTS),
                "weighting": weighting,
                "value_support": value_support,
                "baseline_year": baseline_year,
                "comparison_year": comparison_year,
                "total_usdt_share_change": total_change,
                "within_scope_change": within_scope_change,
                "between_scope_composition_change": between_scope_composition_change,
                "identity_residual": total_change
                - within_scope_change
                - between_scope_composition_change,
                "within_scope_share_of_change": within_scope_change / total_change
                if total_change
                else np.nan,
                "between_scope_share_of_change": between_scope_composition_change
                / total_change
                if total_change
                else np.nan,
                "interpretation": "positive within-scope share means USDT rises inside fixed integration cells; positive between-scope share means migration toward cells with higher USDT shares contributes",
            }
        )
    return pd.DataFrame(rows)


def build_exhibit(panel: pd.DataFrame) -> pd.DataFrame:
    tests = scope_change_tests(panel)
    cells = ratio_of_totals_cells(panel)
    decomposition = midpoint_decomposition(cells)
    return pd.concat([tests, cells, decomposition], ignore_index=True, sort=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    panel = pd.read_parquet(INTERMEDIATION)
    inputs: list[Path] = [INTERMEDIATION]
    if args.limit is not None or not has_required_columns(panel):
        print(
            "released intermediation panel lacks token-integration columns; "
            "reducing directly from data/unified",
            flush=True,
        )
        panel = reduce_unified_days(workers=args.workers, limit=args.limit)
        inputs = [UNIFIED]
    exhibit = build_exhibit(panel)
    write_exhibit(
        exhibit,
        OUT_EXHIBIT,
        code_sources=CODE_SOURCES,
        inputs=inputs,
        notes=(
            "route-only E0 diagnostic: USDT share among native-currency, USDC "
            "and USDT exact two-leg routes, decomposed into within-integration "
            "change and single/cross-venue route-mix composition; Newey-West "
            "Bartlett covariance for daily endpoint-year changes"
        ),
    )
    summary = exhibit[exhibit["record_type"].eq("midpoint_decomposition")]
    print(summary.round(4).to_string(index=False))
    print(f"wrote {OUT_EXHIBIT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

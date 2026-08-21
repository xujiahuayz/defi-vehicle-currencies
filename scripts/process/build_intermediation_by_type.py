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
        output/exhibits/intermediation_integration_interaction.jsonl
        output/exhibits/intermediation_token_integration_interaction.jsonl
        output/exhibits/intermediation_complexity_rival.jsonl
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
from ddvc.asset_types import TYPES, VEHICLE_CANDIDATE_SYMBOLS, classify
from ddvc.datasets import route_partitions, validate_before_install
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.route_roles import VALUE_SUPPORT_SCOPES
from ddvc.realised import ROUTE_COLUMNS, realised_routes
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.tables import write_exhibit, write_panel

UNIFIED = DATA_DIR / "unified"
OUT_PARQUET = DATA_DIR / "processed" / "intermediation_by_type_daily.parquet"
OUT_EXHIBIT = OUTPUT_DIR / "exhibits" / "intermediation_by_type.jsonl"
OUT_HALF_YEAR = OUTPUT_DIR / "exhibits" / "intermediation_by_halfyear.jsonl"
OUT_RIVAL = OUTPUT_DIR / "exhibits" / "intermediation_integration_rival.jsonl"
OUT_INTERACTION = OUTPUT_DIR / "exhibits" / "intermediation_integration_interaction.jsonl"
OUT_TOKEN_INTERACTION = OUTPUT_DIR / "exhibits" / "intermediation_token_integration_interaction.jsonl"
OUT_COMPLEXITY_RIVAL = OUTPUT_DIR / "exhibits" / "intermediation_complexity_rival.jsonl"
LOCK = SHARED_RUNTIME_DIR / "intermediation-by-type.lock"
HAC_LAG = 30
INTEGRATION_RIVAL_WINDOWS = ((2023, 2024), (2024, 2026))
CODE_SOURCES = [
    "scripts/process/build_intermediation_by_type.py",
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
VEHICLE_TRANSITION_SCOPES = (
    "two_leg",
    "single_venue_two_leg",
    "cross_venue_two_leg",
)
STABLE_SHARE_ESTIMANDS = (
    ("episode", "all_routes", "cnt_"),
    ("value", "all_routes", "usd_"),
    ("value", "within_2x", "usd_within_2x_"),
    ("value", "within_20pct", "usd_within_20pct_"),
)
VEHICLE_TRANSITION_ESTIMANDS = (
    ("episode", "all_routes", "cnt_"),
    ("value", "within_20pct", "usd_within_20pct_"),
)
VEHICLE_TRANSITION_SPECIFICATIONS = (
    len(VEHICLE_TRANSITION_SCOPES) * len(VEHICLE_TRANSITION_ESTIMANDS) * 2
)
TOKEN_INTERACTION_COMPONENTS = ("native", "USDC", "USDT")


def value_field(asset_type: str, *, scope: str = "all", support: str = "all_routes") -> str:
    scope_prefix = "" if scope == "all" else f"{scope}_"
    support_prefix = "usd_" if support == "all_routes" else f"usd_{support}_"
    return f"{support_prefix}{scope_prefix}{asset_type}"


def empty_day(day: str) -> dict[str, object]:
    out: dict[str, object] = {
        "date": pd.to_datetime(day, format="%Y%m%d"),
        "routes_intermediated": 0,
        "episodes": 0,
    }
    for asset_type in TYPES:
        out[f"cnt_{asset_type}"] = 0
        out[f"route_cnt_{asset_type}"] = 0
        for support in VALUE_SUPPORT_SCOPES:
            out[value_field(asset_type, support=support)] = 0.0
        for scope in INTEGRATION_SCOPES:
            out[f"cnt_{scope}_{asset_type}"] = 0
            for support in VALUE_SUPPORT_SCOPES:
                out[value_field(asset_type, scope=scope, support=support)] = 0.0
        for scope in COMPLEXITY_SCOPES:
            out[f"cnt_{scope}_{asset_type}"] = 0
            for support in VALUE_SUPPORT_SCOPES:
                out[value_field(asset_type, scope=scope, support=support)] = 0.0
    for symbol in VEHICLE_CANDIDATE_SYMBOLS:
        out[f"cnt_{symbol}"] = 0
        for scope in VEHICLE_TRANSITION_SCOPES:
            out[f"cnt_{scope}_{symbol}"] = 0
            for support in VALUE_SUPPORT_SCOPES:
                out[value_field(symbol, scope=scope, support=support)] = 0.0
    return out


def one_day(path: Path) -> dict[str, object]:
    try:
        routes = realised_routes(
            path.stem,
            path.parent,
            require_positive_value=False,
        )
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
    route_type_presence = routes[
        ["tx_hash", "component_id", "asset_type"]
    ].drop_duplicates()
    for asset_type in TYPES:
        selected = routes[routes["asset_type"].eq(asset_type)]
        out[f"cnt_{asset_type}"] = int(len(selected))
        out[f"route_cnt_{asset_type}"] = int(
            route_type_presence["asset_type"].eq(asset_type).sum()
        )
        for support in VALUE_SUPPORT_SCOPES:
            supported = selected if support == "all_routes" else selected[selected[support]]
            out[value_field(asset_type, support=support)] = float(supported["usd"].sum())
        for scope in INTEGRATION_SCOPES:
            cell = selected[selected["integration_scope"].eq(scope)]
            out[f"cnt_{scope}_{asset_type}"] = int(len(cell))
            for support in VALUE_SUPPORT_SCOPES:
                supported = cell if support == "all_routes" else cell[cell[support]]
                out[value_field(asset_type, scope=scope, support=support)] = float(
                    supported["usd"].sum()
                )
        for complexity_scope in ("two_leg", "more_than_two_legs"):
            complexity_cell = selected[
                selected["complexity_scope"].eq(complexity_scope)
            ]
            out[f"cnt_{complexity_scope}_{asset_type}"] = int(len(complexity_cell))
            for support in VALUE_SUPPORT_SCOPES:
                supported = (
                    complexity_cell
                    if support == "all_routes"
                    else complexity_cell[complexity_cell[support]]
                )
                out[value_field(asset_type, scope=complexity_scope, support=support)] = float(
                    supported["usd"].sum()
                )
            for integration_scope in INTEGRATION_SCOPES:
                scope = f"{integration_scope}_{complexity_scope}"
                cell = complexity_cell[
                    complexity_cell["integration_scope"].eq(integration_scope)
                ]
                out[f"cnt_{scope}_{asset_type}"] = int(len(cell))
                for support in VALUE_SUPPORT_SCOPES:
                    supported = cell if support == "all_routes" else cell[cell[support]]
                    out[value_field(asset_type, scope=scope, support=support)] = float(
                        supported["usd"].sum()
                    )
    for symbol in VEHICLE_CANDIDATE_SYMBOLS:
        selected = routes[routes["symbol"].eq(symbol)]
        out[f"cnt_{symbol}"] = int(len(selected))
        two_leg = selected[selected["complexity_scope"].eq("two_leg")]
        for scope in VEHICLE_TRANSITION_SCOPES:
            cell = two_leg
            if scope != "two_leg":
                integration_scope = scope.removesuffix("_two_leg")
                cell = cell[cell["integration_scope"].eq(integration_scope)]
            out[f"cnt_{scope}_{symbol}"] = int(len(cell))
            for support in VALUE_SUPPORT_SCOPES:
                supported = cell if support == "all_routes" else cell[cell[support]]
                out[value_field(symbol, scope=scope, support=support)] = float(
                    supported["usd"].sum()
                )
    return out


def annual_composition(panel: pd.DataFrame) -> pd.DataFrame:
    data = panel.copy()
    data["year"] = pd.to_datetime(data["date"]).dt.year
    columns = [
        column
        for column in data.columns
        if column.startswith("cnt_")
        or column.startswith("route_cnt_")
        or column.startswith("usd_")
    ]
    columns.append("routes_intermediated")
    annual = data.groupby("year", as_index=False)[columns].sum()
    rows: list[dict[str, object]] = []
    for observed in annual.itertuples(index=False):
        for scope in ("all", *INTEGRATION_SCOPES):
            count_columns = {
                asset_type: f"cnt_{asset_type}" if scope == "all" else f"cnt_{scope}_{asset_type}"
                for asset_type in TYPES
            }
            count_total = sum(float(getattr(observed, column)) for column in count_columns.values())
            for asset_type in TYPES:
                count = float(getattr(observed, count_columns[asset_type]))
                row = {
                    "year": int(observed.year),
                    "integration_scope": scope,
                    "asset_type": asset_type,
                    "episodes": int(count),
                    "episode_share": count / count_total if count_total else None,
                }
                if scope == "all":
                    route_count = float(
                        getattr(observed, f"route_cnt_{asset_type}")
                    )
                    row["route_count"] = int(route_count)
                    row["route_participation_share"] = (
                        route_count / float(getattr(observed, "routes_intermediated"))
                        if getattr(observed, "routes_intermediated")
                        else None
                    )
                for support in VALUE_SUPPORT_SCOPES:
                    value_columns = {
                        candidate: value_field(candidate, scope=scope, support=support)
                        for candidate in TYPES
                    }
                    value_total = sum(
                        float(getattr(observed, column)) for column in value_columns.values()
                    )
                    value = float(getattr(observed, value_columns[asset_type]))
                    suffix = "" if support == "all_routes" else f"_{support}"
                    row[f"usd{suffix}"] = value
                    row[f"usd_share{suffix}"] = value / value_total if value_total else None
                rows.append(row)
    return pd.DataFrame(rows)


def halfyear_composition(panel: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the same exhaustive route composition in six-month periods."""

    data = panel.copy()
    dates = pd.to_datetime(data["date"])
    data["year"] = dates.dt.year
    data["half"] = np.where(dates.dt.month.le(6), 1, 2)
    data["period_order"] = data["year"] * 2 + data["half"] - 1
    columns = [
        column
        for column in data.columns
        if column.startswith("cnt_")
        or column.startswith("route_cnt_")
        or column.startswith("usd_")
    ]
    columns.append("routes_intermediated")
    grouped = data.groupby(["year", "half", "period_order"], as_index=False)[columns].sum()
    rows: list[dict[str, object]] = []
    for observed in grouped.itertuples(index=False):
        for scope in ("all", *INTEGRATION_SCOPES):
            count_columns = {
                asset_type: f"cnt_{asset_type}" if scope == "all" else f"cnt_{scope}_{asset_type}"
                for asset_type in TYPES
            }
            count_total = sum(float(getattr(observed, column)) for column in count_columns.values())
            for asset_type in TYPES:
                count = float(getattr(observed, count_columns[asset_type]))
                row = {
                    "period": f"{int(observed.year)} H{int(observed.half)}",
                    "period_order": int(observed.period_order),
                    "year": int(observed.year),
                    "half": int(observed.half),
                    "integration_scope": scope,
                    "asset_type": asset_type,
                    "episodes": int(count),
                    "episode_share": count / count_total if count_total else None,
                }
                if scope == "all":
                    route_count = float(getattr(observed, f"route_cnt_{asset_type}"))
                    row["route_count"] = int(route_count)
                    row["route_participation_share"] = (
                        route_count / float(getattr(observed, "routes_intermediated"))
                        if getattr(observed, "routes_intermediated")
                        else None
                    )
                for support in VALUE_SUPPORT_SCOPES:
                    value_columns = {
                        candidate: value_field(candidate, scope=scope, support=support)
                        for candidate in TYPES
                    }
                    value_total = sum(
                        float(getattr(observed, column)) for column in value_columns.values()
                    )
                    value = float(getattr(observed, value_columns[asset_type]))
                    suffix = "" if support == "all_routes" else f"_{support}"
                    row[f"usd{suffix}"] = value
                    row[f"usd_share{suffix}"] = value / value_total if value_total else None
                rows.append(row)
    return pd.DataFrame(rows)


def _stable_share_samples(
    panel: pd.DataFrame,
    *,
    scopes: tuple[str, ...],
    scope_field: str,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    estimands: tuple[tuple[str, str, str], ...] = STABLE_SHARE_ESTIMANDS,
):
    """Yield the exact transformed samples shared by support and estimation."""

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
    for weighting, value_support, column_prefix in estimands:
        for scope in scopes:
            scope_prefix = "" if scope == "all" else f"{scope}_"
            stable_column = f"{column_prefix}{scope_prefix}stable"
            native_column = f"{column_prefix}{scope_prefix}native"
            if stable_column not in data or native_column not in data:
                continue
            stable = pd.to_numeric(
                data[stable_column], errors="coerce"
            )
            native = pd.to_numeric(
                data[native_column], errors="coerce"
            )
            denominator = stable + native
            base_sample = data[["date", "year"]].copy()
            base_sample["share"] = stable / denominator.where(denominator.gt(0))
            base_sample = base_sample.dropna(subset=["share"])
            for transformation in ("share_level", "log_odds"):
                sample = base_sample.copy()
                if transformation == "log_odds":
                    sample = sample[sample["share"].between(0, 1, inclusive="neither")]
                    sample["estimand"] = np.log(sample["share"] / (1 - sample["share"]))
                else:
                    sample["estimand"] = sample["share"]
                yield (
                    {
                        scope_field: scope,
                        "weighting": weighting,
                        "value_support": value_support,
                        "transformation": transformation,
                        "baseline_year": baseline_year,
                        "comparison_year": comparison_year,
                    },
                    sample,
                )


def _stable_share_change_tests(
    panel: pd.DataFrame,
    *,
    scopes: tuple[str, ...],
    scope_field: str,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int = HAC_LAG,
    estimands: tuple[tuple[str, str, str], ...] = STABLE_SHARE_ESTIMANDS,
) -> pd.DataFrame:
    """Estimate the stable share change within prespecified route regimes."""

    rows: list[dict[str, object]] = []
    for identity, sample in _stable_share_samples(
        panel,
        scopes=scopes,
        scope_field=scope_field,
        baseline_year=baseline_year,
        comparison_year=comparison_year,
        estimands=estimands,
    ):
        estimate = year_endpoint_change(
            sample["estimand"],
            sample["year"],
            baseline_year=baseline_year,
            comparison_year=comparison_year,
            hac_lag=hac_lag,
            dates=sample["date"],
        )
        rows.append(
            {
                **identity,
                "baseline_daily_mean": estimate.baseline_mean,
                "comparison_daily_mean": estimate.comparison_mean,
                "change": estimate.change,
                "hac_standard_error": estimate.standard_error,
                "t_statistic": estimate.t_statistic,
                "p_value": estimate.p_value,
                "days": estimate.n_observations,
                "hac_lag_days": hac_lag,
                "calendar_support": "daily observations at calendar month-and-day positions observed in both endpoint years; calendar-day HAC excludes unsupported gaps",
                "share_denominator": "native_plus_stable",
            }
        )
    result = pd.DataFrame(rows)
    family = [
        "baseline_year",
        "comparison_year",
        "weighting",
        "value_support",
        "transformation",
    ]
    result["p_value_holm"] = result.groupby(family, sort=False)["p_value"].transform(
        holm_adjusted_pvalues
    )
    return result


def vehicle_transition_tests(
    panel: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Estimate the E0 transition family on exact two-leg routing strata."""

    result = _stable_share_change_tests(
        panel,
        scopes=VEHICLE_TRANSITION_SCOPES,
        scope_field="routing_scope",
        baseline_year=baseline_year,
        comparison_year=comparison_year,
        hac_lag=hac_lag,
        estimands=VEHICLE_TRANSITION_ESTIMANDS,
    )
    if len(result) != VEHICLE_TRANSITION_SPECIFICATIONS:
        raise ValueError("vehicle-transition estimator does not cover its exact specification perimeter")
    return result


def vehicle_transition_support_geometry(
    panel: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    minimum_endpoint_days: int = HAC_LAG + 1,
) -> pd.DataFrame:
    """Gate every E0 transition specification on its exact pre-fit sample."""

    if minimum_endpoint_days < 2:
        raise ValueError("vehicle-transition support minimum must be at least two days")
    rows: list[dict[str, object]] = []
    for identity, sample in _stable_share_samples(
        panel,
        scopes=VEHICLE_TRANSITION_SCOPES,
        scope_field="routing_scope",
        baseline_year=baseline_year,
        comparison_year=comparison_year,
        estimands=VEHICLE_TRANSITION_ESTIMANDS,
    ):
        counts = sample.groupby("year", observed=True).size()
        baseline_days = int(counts.get(baseline_year, 0))
        comparison_days = int(counts.get(comparison_year, 0))
        review = min(baseline_days, comparison_days) < minimum_endpoint_days
        rows.append(
            {
                "record_type": "support",
                "family": "vehicle_transition",
                **identity,
                "baseline_supported_days": baseline_days,
                "comparison_supported_days": comparison_days,
                "minimum_endpoint_days": minimum_endpoint_days,
                "support_exit_review_required": review,
                "support_reason": (
                    "insufficient endpoint-year days for the declared HAC horizon"
                    if review
                    else "pass"
                ),
            }
        )
    result = pd.DataFrame(rows)
    if len(result) != VEHICLE_TRANSITION_SPECIFICATIONS:
        raise ValueError("vehicle-transition support does not cover its exact specification perimeter")
    return result


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


def integration_interaction_tests(
    panel: pd.DataFrame,
    *,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Test whether the stable-share change differs across integration regimes."""

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
    rows: list[dict[str, object]] = []
    for weighting, value_support, column_prefix in STABLE_SHARE_ESTIMANDS:
        shares: dict[str, pd.Series] = {}
        for scope in INTEGRATION_SCOPES:
            stable = pd.to_numeric(data[f"{column_prefix}{scope}_stable"], errors="coerce")
            native = pd.to_numeric(data[f"{column_prefix}{scope}_native"], errors="coerce")
            shares[scope] = stable / (stable + native).where((stable + native).gt(0))
        for transformation in ("share_level", "log_odds"):
            sample = data[["date", "year"]].copy()
            for scope in INTEGRATION_SCOPES:
                share = shares[scope]
                if transformation == "log_odds":
                    share = np.log(share / (1 - share)).where(
                        share.between(0, 1, inclusive="neither")
                    )
                sample[scope] = share
            sample = sample.dropna(subset=list(INTEGRATION_SCOPES))
            sample["estimand"] = sample["cross_venue"] - sample["single_venue"]
            estimate = year_endpoint_change(
                sample["estimand"],
                sample["year"],
                baseline_year=baseline_year,
                comparison_year=comparison_year,
                hac_lag=hac_lag,
                dates=sample["date"],
            )
            rows.append(
                {
                    "weighting": weighting,
                    "value_support": value_support,
                    "transformation": transformation,
                    "baseline_year": baseline_year,
                    "comparison_year": comparison_year,
                    "baseline_cross_minus_single": estimate.baseline_mean,
                    "comparison_cross_minus_single": estimate.comparison_mean,
                    "differential_change": estimate.change,
                    "hac_standard_error": estimate.standard_error,
                    "t_statistic": estimate.t_statistic,
                    "p_value": estimate.p_value,
                    "days": estimate.n_observations,
                    "hac_lag_days": hac_lag,
                    "null_hypothesis": "cross_venue_change_equals_single_venue_change",
                    "interpretation_boundary": "descriptive interaction; integration regime is selected and the coefficient is not a causal effect of integration",
                }
            )
    result = pd.DataFrame(rows)
    result["p_value_holm"] = holm_adjusted_pvalues(result["p_value"])
    return result


def integration_interaction_windows(
    panel: pd.DataFrame,
    *,
    windows: tuple[tuple[int, int], ...] = INTEGRATION_RIVAL_WINDOWS,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Test integration-regime interactions over each declared transition window."""

    return pd.concat(
        [
            integration_interaction_tests(
                panel,
                baseline_year=baseline_year,
                comparison_year=comparison_year,
                hac_lag=hac_lag,
            )
            for baseline_year, comparison_year in windows
        ],
        ignore_index=True,
    )


def token_integration_interaction_tests(
    panel: pd.DataFrame,
    *,
    focal_symbol: str = "USDT",
    comparison_components: tuple[str, ...] = TOKEN_INTERACTION_COMPONENTS,
    baseline_year: int = 2024,
    comparison_year: int = 2026,
    hac_lag: int = HAC_LAG,
) -> pd.DataFrame:
    """Test a token's share transition across exact two-leg integration regimes."""

    if focal_symbol not in comparison_components:
        raise ValueError("focal token must be included in the comparison set")
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
    rows: list[dict[str, object]] = []
    estimands = (
        ("episode", "all_routes", "cnt_"),
        ("value", "within_20pct", "usd_within_20pct_"),
    )
    for weighting, value_support, prefix in estimands:
        shares: dict[str, pd.Series] = {}
        for integration_scope in INTEGRATION_SCOPES:
            scope = f"{integration_scope}_two_leg"
            focal = pd.to_numeric(data[f"{prefix}{scope}_{focal_symbol}"], errors="coerce")
            denominator = sum(
                pd.to_numeric(data[f"{prefix}{scope}_{component}"], errors="coerce")
                for component in comparison_components
            )
            shares[integration_scope] = focal / denominator.where(denominator.gt(0))
        for transformation in ("share_level", "log_odds"):
            sample = data[["date", "year"]].copy()
            for integration_scope in INTEGRATION_SCOPES:
                share = shares[integration_scope]
                if transformation == "log_odds":
                    share = np.log(share / (1 - share)).where(
                        share.between(0, 1, inclusive="neither")
                    )
                sample[integration_scope] = share
            sample = sample.dropna(subset=list(INTEGRATION_SCOPES))
            sample["estimand"] = sample["cross_venue"] - sample["single_venue"]
            estimate = year_endpoint_change(
                sample["estimand"],
                sample["year"],
                baseline_year=baseline_year,
                comparison_year=comparison_year,
                hac_lag=hac_lag,
                dates=sample["date"],
            )
            rows.append(
                {
                    "focal_symbol": focal_symbol,
                    "comparison_components": "+".join(comparison_components),
                    "weighting": weighting,
                    "value_support": value_support,
                    "transformation": transformation,
                    "baseline_year": baseline_year,
                    "comparison_year": comparison_year,
                    "baseline_cross_minus_single": estimate.baseline_mean,
                    "comparison_cross_minus_single": estimate.comparison_mean,
                    "differential_change": estimate.change,
                    "hac_standard_error": estimate.standard_error,
                    "t_statistic": estimate.t_statistic,
                    "p_value": estimate.p_value,
                    "days": estimate.n_observations,
                    "hac_lag_days": hac_lag,
                }
            )
    result = pd.DataFrame(rows)
    result["p_value_holm"] = holm_adjusted_pvalues(result["p_value"])
    return result


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
    parser.add_argument("--panel-only", action="store_true")
    args = parser.parse_args()
    workers = bounded_workers(args.workers)

    route_release = route_partitions(ROUTE_COLUMNS, nonempty=False)
    days = list(route_release.paths)
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
        panel[f"route_participation_share_{asset_type}"] = (
            panel[f"route_cnt_{asset_type}"]
            / panel["routes_intermediated"].where(panel["routes_intermediated"].gt(0))
        )
    if args.limit is not None:
        print(
            f"smoke reduction complete on {len(panel):,} days; canonical outputs unchanged"
        )
        return 0
    write_panel(
        panel,
        OUT_PARQUET,
        code_sources=CODE_SOURCES,
        inputs=list(route_release.paths),
        notes="topology-valid non-cyclic routes; counts use full topology support; values report all, 2x and 20 percent source-intermediary-sink coherence bands",
        preinstall_validator=validate_before_install(route_release),
    )
    if args.panel_only:
        print(f"wrote analysis-ready panel {OUT_PARQUET.relative_to(REPO_ROOT)}")
        return 0
    annual = annual_composition(panel)
    rival = integration_rival_windows(panel)
    interaction = integration_interaction_windows(panel)
    token_interaction = token_integration_interaction_tests(panel)
    complexity_rival = complexity_rival_tests(panel)
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
        interaction,
        OUT_INTERACTION,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PARQUET],
        notes="paired-date cross-venue minus single-venue stable-share interaction; Newey-West Bartlett covariance; descriptive because integration regime is selected",
    )
    write_exhibit(
        token_interaction,
        OUT_TOKEN_INTERACTION,
        code_sources=CODE_SOURCES,
        inputs=[OUT_PARQUET],
        notes="paired-date USDT share interaction among exact two-leg native-currency, USDC and USDT routes; native currency combines ETH and WETH; Newey-West Bartlett covariance",
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
                    "value_support",
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
                "value_support",
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
        f"{OUT_INTERACTION.relative_to(REPO_ROOT)}, "
        f"{OUT_TOKEN_INTERACTION.relative_to(REPO_ROOT)}, "
        f"and {OUT_COMPLEXITY_RIVAL.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="intermediation-by-type panel"):
        sys.exit(main())

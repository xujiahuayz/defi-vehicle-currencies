#!/usr/bin/env python3
"""Measure route-scope and WETH-eligibility heterogeneity in the matched panel."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    linear_contrast,
    ols_clustered,
    year_endpoint_change,
)
from ddvc.model_artifacts import attach_spec_ids
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output
from ddvc.tables import write_exhibit


PAIR_PANEL = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_panel.parquet"
HETEROGENEITY = OUTPUT_DIR / "exhibits" / "route_methodology_heterogeneity.jsonl"
HETEROGENEITY_DECK_VALUES = (
    OUTPUT_DIR / "exhibits" / "route_methodology_heterogeneity_deck_values.tex"
)
CODE_SOURCES = [
    "scripts/analyze/run_route_heterogeneity.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/model_artifacts.py",
]
COUNT_METRICS = ("count_share", "matched_strict_count_share")
HETEROGENEITY_METRICS = (*COUNT_METRICS, "strict_intermediation_value_share")
GROUP_KEYS = ("src", "tgt", "month_day", "integration_scope")
MAJOR_ENDPOINT_TOKENS = {
    "USDT": "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "USDC": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "WETH": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
}


def _matched_metric(panel: pd.DataFrame, metric: str) -> pd.DataFrame:
    required = {
        "metric", "year", "date", *GROUP_KEYS, "native", "stable", "denominator",
        "stable_share",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"route methodology panel lacks columns: {missing}")
    data = panel[panel["metric"].eq(metric)].copy()
    if data.empty:
        raise ValueError(f"route methodology panel lacks metric {metric}")
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    if not data["year"].isin((2024, 2026)).all():
        raise ValueError("route methodology panel contains an unexpected year")
    for column in ("native", "stable", "denominator"):
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column]).all() or data[column].lt(0).any():
            raise ValueError(f"route methodology panel has invalid {column}")
    if not np.allclose(data["native"] + data["stable"], data["denominator"]):
        raise ValueError("route methodology grouped counts do not reconcile")
    if metric in COUNT_METRICS and not np.allclose(
        data[["native", "stable"]], np.rint(data[["native", "stable"]])
    ):
        raise ValueError("grouped-binomial route counts must be integer valued")
    counts = data.groupby(list(GROUP_KEYS), observed=True)["year"].agg(["size", "nunique"])
    if not counts.eq(2).all().all():
        raise ValueError(f"{metric} does not have exactly two endpoint years per matched cell")
    return data.sort_values([*GROUP_KEYS, "year"], kind="stable").reset_index(drop=True)


def paired_calendar_comparison(panel: pd.DataFrame, metric: str, *, hac_lag: int = 30) -> list[dict[str, object]]:
    """Compare ratios of totals after aggregating matched cells by calendar day."""

    data = _matched_metric(panel, metric)
    daily = data.groupby(["year", "month_day"], observed=True)[["stable", "denominator"]].sum()
    daily["share"] = daily["stable"] / daily["denominator"]
    wide = daily["share"].unstack("year").dropna(subset=[2024, 2026]).sort_index()
    change = (wide[2026] - wide[2024]).to_numpy(float)
    n = len(change)
    estimate = float(change.mean())
    ordinary_se = float(change.std(ddof=1) / np.sqrt(n))
    centered = change - estimate
    gamma0 = float(centered @ centered / n)
    long_run = gamma0
    for lag in range(1, min(hac_lag, n - 1) + 1):
        covariance = float(centered[lag:] @ centered[:-lag] / n)
        long_run += 2.0 * (1.0 - lag / (hac_lag + 1.0)) * covariance
    hac_se = float(np.sqrt(max(long_run, 0.0) / n))
    rows = []
    for method, standard_error, covariance in (
        ("paired_calendar_t", ordinary_se, "iid_calendar_day_diagnostic"),
        ("paired_calendar_hac_t", hac_se, f"newey_west_calendar_day_lag_{hac_lag}"),
    ):
        statistic = estimate / standard_error
        p_value = float(2.0 * stats.t.sf(abs(statistic), n - 1))
        rows.append(
            {
                "method": method,
                "metric": metric,
                "coefficient": estimate,
                "standard_error": standard_error,
                "t_statistic": float(statistic),
                "p_value": p_value,
                "observations": n,
                "matched_cells": int(len(data) // 2),
                "fixed_effects": "paired_month_day",
                "covariance": covariance,
                "estimand": (
                    "mean 2026-versus-2024 change in the calendar-day ratio of total stable "
                    "routes to total stable-plus-native routes across matched cells"
                ),
                "interpretation": (
                    "serial_dependence_diagnostic_only_allows_activity_reallocation_across_cells"
                    if method == "paired_calendar_t" else
                    "calendar_dependence_robust_noncausal_change_allows_activity_reallocation_across_cells"
                ),
                "falsifier": "paired_calendar_mean_change_is_zero_or_reverses",
            }
        )
    return rows


def endpoint_year_calendar_comparison(
    panel: pd.DataFrame,
    metric: str,
    *,
    hac_lag: int = 30,
) -> dict[str, object]:
    """Estimate the same daily-share contrast with HAC on actual endpoint-year dates."""

    data = _matched_metric(panel, metric)
    daily = (
        data.groupby(["year", "date", "month_day"], observed=True)[
            ["stable", "denominator"]
        ]
        .sum()
        .reset_index()
        .sort_values("date", kind="stable")
    )
    daily["share"] = daily["stable"] / daily["denominator"]
    result = year_endpoint_change(
        daily["share"],
        daily["year"],
        baseline_year=2024,
        comparison_year=2026,
        hac_lag=hac_lag,
        dates=daily["date"],
    )
    critical = float(stats.t.ppf(0.975, result.degrees_freedom))
    return {
        "method": "endpoint_year_calendar_hac_t",
        "metric": metric,
        "coefficient": result.change,
        "standard_error": result.standard_error,
        "t_statistic": result.t_statistic,
        "p_value": result.p_value,
        "confidence_interval_lower": result.change - critical * result.standard_error,
        "confidence_interval_upper": result.change + critical * result.standard_error,
        "observations": result.n_observations,
        "matched_cells": int(len(data) // 2),
        "fixed_effects": "endpoint_year_indicator",
        "covariance": f"newey_west_actual_calendar_day_lag_{hac_lag}",
        "estimand": (
            "2026-versus-2024 change in the equal-weighted endpoint-year daily ratio of "
            "total stable routes to total stable-plus-native routes on common month-days"
        ),
        "interpretation": "primary_calendar_time_inference_2025_excluded_noncausal",
        "inference_assumption": (
            "serial covariance follows actual calendar distance within endpoint years; the "
            "unsupported 2025 interval creates no artificial adjacency or cross-year covariance"
        ),
        "falsifier": "endpoint_year_daily_mean_change_is_zero_or_reverses",
    }


def _fit_share_change_by_group(
    data: pd.DataFrame,
    *,
    group_column: str,
    levels: tuple[str, ...],
    analysis_block: str,
    multiplicity_family: str,
    declaration_status: str,
) -> tuple[list[dict[str, object]], object]:
    """Estimate within-cell share changes by declared groups with two-way clustering."""

    if group_column not in data:
        raise ValueError(f"share-change heterogeneity lacks {group_column}")
    observed_levels = set(data[group_column].dropna().astype(str))
    if not set(levels).issubset(observed_levels):
        missing = sorted(set(levels) - observed_levels)
        raise ValueError(f"share-change heterogeneity lacks levels: {missing}")
    selected = data[data[group_column].astype(str).isin(levels)].copy()
    fixed_effect = pd.Series(
        list(selected[list(GROUP_KEYS)].itertuples(index=False, name=None)),
        index=selected.index,
        name="matched_route_cell",
    )
    pair_cluster = pd.Series(
        list(selected[["src", "tgt"]].itertuples(index=False, name=None)),
        index=selected.index,
        name="ordered_endpoint_pair",
    )
    regressors = pd.DataFrame(
        {
            level: (
                selected["year"].eq(2026)
                & selected[group_column].astype(str).eq(level)
            ).astype(float)
            for level in levels
        },
        index=selected.index,
    )
    absorbed = absorb_fixed_effects(
        pd.concat([selected[["stable_share"]], regressors], axis=1),
        fixed_effect,
        weights=selected["denominator"],
    )
    fit = ols_clustered(
        absorbed["stable_share"],
        absorbed[list(levels)],
        pair_cluster,
        add_constant=False,
        absorbed_groups=(fixed_effect,),
        additional_clusters=(selected["date"],),
        weights=selected["denominator"],
        min_observations=4,
        min_clusters=2,
    )
    if not (
        np.isfinite(fit.beta).all()
        and np.isfinite(fit.covariance).all()
        and np.isfinite(fit.p_values).all()
    ):
        raise RuntimeError(f"{analysis_block} grouped share-change fit is nonfinite")
    degrees_freedom = fit.n_clusters - 1
    critical = float(stats.t.ppf(0.975, degrees_freedom))
    rows: list[dict[str, object]] = []
    for index, level in enumerate(levels):
        level_data = selected[selected[group_column].astype(str).eq(level)]
        baseline = level_data[level_data["year"].eq(2024)]
        estimate = float(fit.beta[index])
        standard_error = float(fit.standard_errors[index])
        rows.append(
            {
                "row_type": "estimate",
                "analysis_block": analysis_block,
                "method": "denominator_weighted_cell_fixed_effect_wls",
                "metric": str(selected["metric"].iloc[0]),
                "dimension": group_column,
                "level": level,
                "contrast": None,
                "coefficient": estimate,
                "standard_error": standard_error,
                "t_statistic": float(fit.t_statistics[index]),
                "p_value": float(fit.p_values[index]),
                "confidence_interval_lower": estimate - critical * standard_error,
                "confidence_interval_upper": estimate + critical * standard_error,
                "observations": int(len(level_data)),
                "matched_cells": int(len(baseline)),
                "ordered_pair_clusters": int(
                    baseline[["src", "tgt"]].drop_duplicates().shape[0]
                ),
                "calendar_date_clusters": int(level_data["date"].nunique()),
                "baseline_denominator_mass": float(
                    baseline["denominator"].sum()
                ),
                "comparison_denominator_mass": float(
                    level_data.loc[level_data["year"].eq(2026), "denominator"].sum()
                ),
                "fixed_effects": "ordered_endpoint_pair_x_month_day_x_integration_scope",
                "covariance": "two_way_ordered_pair_calendar_date_cr1",
                "estimand": "2026-versus-2024 stable-share change within matched realised-route cells",
                "multiplicity_family": multiplicity_family,
                "declaration_status": declaration_status,
                "mechanical_boundary": (
                    "baseline stable-share state constrains the direction of feasible changes"
                    if group_column == "baseline_stable_state"
                    else None
                ),
                "interpretation": "descriptive_within_realised_market_heterogeneity_noncausal",
            }
        )
    return rows, fit


def _baseline_stable_state(data: pd.DataFrame) -> pd.DataFrame:
    """Attach economically defined zero, mixed, and all-stable baseline states."""

    baseline = data.loc[
        data["year"].eq(2024), [*GROUP_KEYS, "stable_share"]
    ].rename(columns={"stable_share": "baseline_stable_share"})
    if baseline.duplicated(list(GROUP_KEYS)).any():
        raise ValueError("baseline stable-state mapping is not unique by matched cell")
    baseline_share = baseline["baseline_stable_share"].to_numpy(float)
    baseline["baseline_stable_state"] = np.select(
        [np.isclose(baseline_share, 0.0), np.isclose(baseline_share, 1.0)],
        ["zero_stable", "all_stable"],
        default="mixed_native_stable",
    )
    merged = data.merge(
        baseline[[*GROUP_KEYS, "baseline_stable_state"]],
        on=list(GROUP_KEYS),
        how="left",
        validate="many_to_one",
    )
    if merged["baseline_stable_state"].isna().any():
        raise RuntimeError("baseline stable-state mapping left unmatched cells")
    return merged


def _holm_by_family(rows: pd.DataFrame) -> pd.DataFrame:
    """Apply Holm control within named, predeclared inferential families."""

    output = rows.copy()
    output["p_value_holm"] = np.nan
    estimable = output["row_type"].eq("estimate") & output["p_value"].notna()
    for _family, index in output.loc[estimable].groupby(
        "multiplicity_family", sort=False
    ).groups.items():
        output.loc[index, "p_value_holm"] = holm_adjusted_pvalues(
            output.loc[index, "p_value"]
        )
    return output


def _newey_west_mean(values: np.ndarray, *, lag: int) -> dict[str, float | int]:
    """Return inference for a sample mean with a Bartlett Newey-West covariance."""

    observations = len(values)
    if observations < 4:
        raise ValueError("Newey-West mean requires at least four observations")
    effective_lag = min(lag, observations - 1)
    estimate = float(np.mean(values))
    centered = values - estimate
    long_run_variance = float(centered @ centered / observations)
    for offset in range(1, effective_lag + 1):
        covariance = float(centered[offset:] @ centered[:-offset] / observations)
        long_run_variance += 2.0 * (1.0 - offset / (effective_lag + 1.0)) * covariance
    standard_error = float(np.sqrt(max(long_run_variance, 0.0) / observations))
    if standard_error == 0.0:
        statistic = 0.0 if estimate == 0.0 else float(np.sign(estimate) * np.inf)
        p_value = 1.0 if estimate == 0.0 else 0.0
    else:
        statistic = estimate / standard_error
        p_value = float(2.0 * stats.t.sf(abs(statistic), observations - 1))
    critical = float(stats.t.ppf(0.975, observations - 1))
    return {
        "coefficient": estimate,
        "standard_error": standard_error,
        "t_statistic": float(statistic),
        "p_value": p_value,
        "confidence_interval_lower": estimate - critical * standard_error,
        "confidence_interval_upper": estimate + critical * standard_error,
        "observations": observations,
        "hac_lag": effective_lag,
    }


def strict_value_non_weth_composition(
    panel: pd.DataFrame,
    *,
    hac_lags: tuple[int, ...] = (7, 14, 30, 60),
) -> pd.DataFrame:
    """Decompose non-WETH strict-value rotation into activity and within-group terms."""

    metric = "strict_intermediation_value_share"
    data = _matched_metric(panel, metric)
    weth = MAJOR_ENDPOINT_TOKENS["WETH"]
    data = data[~data["src"].eq(weth) & ~data["tgt"].eq(weth)].copy()
    daily_rows: list[dict[str, float | str]] = []
    for month_day, day in data.groupby("month_day", sort=True, observed=True):
        baseline_dates = day.loc[day["year"].eq(2024), "date"].drop_duplicates()
        comparison_dates = day.loc[day["year"].eq(2026), "date"].drop_duplicates()
        if len(baseline_dates) != 1 or len(comparison_dates) != 1:
            raise RuntimeError(f"non-WETH strict-value day {month_day} lacks unique dates")
        wide = day.pivot(
            index=["src", "tgt", "integration_scope"],
            columns="year",
            values=["stable_share", "denominator"],
        )
        if wide.isna().any().any():
            raise RuntimeError(f"non-WETH strict-value day {month_day} is not matched")
        share_0 = wide[("stable_share", 2024)].to_numpy(float)
        share_1 = wide[("stable_share", 2026)].to_numpy(float)
        mass_0 = wide[("denominator", 2024)].to_numpy(float)
        mass_1 = wide[("denominator", 2026)].to_numpy(float)
        weight_0 = mass_0 / mass_0.sum()
        weight_1 = mass_1 / mass_1.sum()
        total = float(weight_1 @ share_1 - weight_0 @ share_0)
        activity = float((weight_1 - weight_0) @ ((share_1 + share_0) / 2.0))
        within = float((share_1 - share_0) @ ((weight_1 + weight_0) / 2.0))
        activity_level_0 = float(weight_0 @ ((share_1 + share_0) / 2.0))
        activity_level_1 = float(weight_1 @ ((share_1 + share_0) / 2.0))
        within_level_0 = float(((weight_1 + weight_0) / 2.0) @ share_0)
        within_level_1 = float(((weight_1 + weight_0) / 2.0) @ share_1)
        residual = total - activity - within
        if abs(residual) > 1e-12:
            raise RuntimeError(
                f"non-WETH strict-value decomposition fails on {month_day}: {residual}"
            )
        daily_rows.append(
            {
                "month_day": month_day,
                "baseline_date": pd.Timestamp(baseline_dates.iloc[0]),
                "comparison_date": pd.Timestamp(comparison_dates.iloc[0]),
                "total_change": total,
                "activity_weight_reallocation": activity,
                "within_group_share_change": within,
                "total_level_2024": float(weight_0 @ share_0),
                "total_level_2026": float(weight_1 @ share_1),
                "activity_level_2024": activity_level_0,
                "activity_level_2026": activity_level_1,
                "within_level_2024": within_level_0,
                "within_level_2026": within_level_1,
                "identity_residual": residual,
                "baseline_denominator_mass": float(mass_0.sum()),
                "comparison_denominator_mass": float(mass_1.sum()),
            }
        )
    daily = pd.DataFrame(daily_rows).sort_values("month_day", kind="stable")
    if len(daily) < 4:
        raise RuntimeError("non-WETH strict-value decomposition has fewer than four common days")
    interpretation = {
        "total_change": "descriptive_change_in_non_weth_endpoint_strict_value_share",
        "activity_weight_reallocation": (
            "routed_value_reallocated_toward_trading_pair_route_scope_groups_with_higher_stable_share"
        ),
        "within_group_share_change": (
            "stable_share_changed_within_the_same_trading_pair_route_scope_group"
        ),
    }
    rows: list[dict[str, object]] = []
    baseline_mass = float(daily["baseline_denominator_mass"].sum())
    comparison_mass = float(daily["comparison_denominator_mass"].sum())
    matched_cells = int(len(data) // 2)
    for lag in hac_lags:
        for component in (
            "total_change",
            "activity_weight_reallocation",
            "within_group_share_change",
        ):
            paired_inference = _newey_west_mean(
                daily[component].to_numpy(float), lag=lag
            )
            rows.append(
                {
                    "row_type": "estimate",
                    "analysis_block": "non_weth_strict_value_midpoint_decomposition",
                    "method": "paired_month_day_midpoint_kitagawa_hac",
                    "metric": metric,
                    "dimension": "decomposition_component",
                    "level": component,
                    "contrast": None,
                    **paired_inference,
                    "matched_cells": matched_cells,
                    "ordered_pair_clusters": int(
                        data[["src", "tgt"]].drop_duplicates().shape[0]
                    ),
                    "calendar_date_clusters": int(data["date"].nunique()),
                    "baseline_denominator_mass": baseline_mass,
                    "comparison_denominator_mass": comparison_mass,
                    "identity_residual_max_abs": float(
                        daily["identity_residual"].abs().max()
                    ),
                    "fixed_effects": "none_exact_daily_accounting",
                    "covariance": f"newey_west_paired_month_day_difference_lag_{lag}",
                    "estimand": (
                        "181-day mean midpoint decomposition of the 2026-versus-2024 "
                        "strict-value stable-share change after excluding WETH endpoints"
                    ),
                    "multiplicity_family": f"non_weth_strict_value_midpoint_paired.lag_{lag}",
                    "declaration_status": "e0_reopened_after_j1_mechanical_eligibility_review",
                    "mechanical_boundary": (
                        "exact accounting on realised matched route groups; activity weights are "
                        "not an exogenous treatment and within-group shares do not fix feasible routes"
                    ),
                    "interpretation": interpretation[component],
                    "inference_assumption": (
                        "same month-days are differenced before HAC, permitting matched seasonal-day "
                        "cross-year covariance despite the two-year calendar separation"
                    ),
                    "primary_covariance": False,
                }
            )
            level_prefix = {
                "total_change": "total_level",
                "activity_weight_reallocation": "activity_level",
                "within_group_share_change": "within_level",
            }[component]
            endpoint_series = pd.DataFrame(
                {
                    "value": pd.concat(
                        [
                            daily[f"{level_prefix}_2024"],
                            daily[f"{level_prefix}_2026"],
                        ],
                        ignore_index=True,
                    ),
                    "year": [2024] * len(daily) + [2026] * len(daily),
                    "date": pd.concat(
                        [daily["baseline_date"], daily["comparison_date"]],
                        ignore_index=True,
                    ),
                }
            ).sort_values("date", kind="stable")
            endpoint = year_endpoint_change(
                endpoint_series["value"],
                endpoint_series["year"],
                baseline_year=2024,
                comparison_year=2026,
                hac_lag=lag,
                dates=endpoint_series["date"],
            )
            endpoint_t = endpoint.t_statistic
            endpoint_p = endpoint.p_value
            if endpoint.standard_error == 0.0:
                endpoint_t = 0.0 if endpoint.change == 0.0 else float(
                    np.sign(endpoint.change) * np.inf
                )
                endpoint_p = 1.0 if endpoint.change == 0.0 else 0.0
            critical = float(stats.t.ppf(0.975, endpoint.degrees_freedom))
            rows.append(
                {
                    "row_type": "estimate",
                    "analysis_block": "non_weth_strict_value_midpoint_decomposition",
                    "method": "endpoint_year_midpoint_kitagawa_calendar_hac",
                    "metric": metric,
                    "dimension": "decomposition_component",
                    "level": component,
                    "contrast": None,
                    "coefficient": endpoint.change,
                    "standard_error": endpoint.standard_error,
                    "t_statistic": endpoint_t,
                    "p_value": endpoint_p,
                    "confidence_interval_lower": endpoint.change
                    - critical * endpoint.standard_error,
                    "confidence_interval_upper": endpoint.change
                    + critical * endpoint.standard_error,
                    "observations": endpoint.n_observations,
                    "hac_lag": lag,
                    "matched_cells": matched_cells,
                    "ordered_pair_clusters": int(
                        data[["src", "tgt"]].drop_duplicates().shape[0]
                    ),
                    "calendar_date_clusters": int(data["date"].nunique()),
                    "baseline_denominator_mass": baseline_mass,
                    "comparison_denominator_mass": comparison_mass,
                    "identity_residual_max_abs": float(
                        daily["identity_residual"].abs().max()
                    ),
                    "fixed_effects": "endpoint_year_indicator_on_symmetric_component_levels",
                    "covariance": f"newey_west_actual_calendar_day_lag_{lag}",
                    "estimand": (
                        "181-day mean midpoint decomposition of the 2026-versus-2024 "
                        "strict-value stable-share change after excluding WETH endpoints"
                    ),
                    "multiplicity_family": f"non_weth_strict_value_midpoint_primary.lag_{lag}",
                    "declaration_status": "e0_reopened_after_j1_mechanical_eligibility_review",
                    "mechanical_boundary": (
                        "exact accounting on realised matched route groups; activity weights are "
                        "not an exogenous treatment and within-group shares do not fix feasible routes"
                    ),
                    "interpretation": interpretation[component],
                    "inference_assumption": (
                        "serial covariance follows actual calendar distance within endpoint years; "
                        "2025 is excluded and the unsupported interval creates no artificial adjacency"
                    ),
                    "primary_covariance": lag == 30,
                }
            )
    return pd.DataFrame(rows)


def route_heterogeneity_results(panel: pd.DataFrame) -> pd.DataFrame:
    """Test declared scope heterogeneity and endpoint concentration sensitivity."""

    rows: list[dict[str, object]] = []
    for metric in COUNT_METRICS:
        data = _matched_metric(panel, metric)
        integration_family = f"integration_scope.{metric}"
        scope_rows, scope_fit = _fit_share_change_by_group(
            data,
            group_column="integration_scope",
            levels=("single_venue", "cross_venue"),
            analysis_block="ex_ante_integration_scope",
            multiplicity_family=integration_family,
            declaration_status="locked_panel_dimension_predeclared_before_estimation",
        )
        rows.extend(scope_rows)
        scope_difference = linear_contrast(scope_fit, (-1.0, 1.0))
        rows.append(
            {
                "row_type": "estimate",
                "analysis_block": "ex_ante_integration_scope",
                "method": "denominator_weighted_cell_fixed_effect_wls_contrast",
                "metric": metric,
                "dimension": "integration_scope",
                "level": None,
                "contrast": "cross_venue_minus_single_venue",
                "coefficient": scope_difference.estimate,
                "standard_error": scope_difference.standard_error,
                "t_statistic": scope_difference.t_statistic,
                "p_value": scope_difference.p_value,
                "confidence_interval_lower": scope_difference.confidence_interval_lower,
                "confidence_interval_upper": scope_difference.confidence_interval_upper,
                "observations": int(len(data)),
                "matched_cells": int(len(data) // 2),
                "ordered_pair_clusters": int(scope_fit.cluster_counts[0]),
                "calendar_date_clusters": int(scope_fit.cluster_counts[1]),
                "fixed_effects": "ordered_endpoint_pair_x_month_day_x_integration_scope",
                "covariance": "two_way_ordered_pair_calendar_date_cr1",
                "estimand": "difference in within-cell stable-share changes across realised integration scopes",
                "multiplicity_family": integration_family,
                "declaration_status": "locked_panel_dimension_predeclared_before_estimation",
                "mechanical_boundary": None,
                "interpretation": "descriptive_scope_heterogeneity_noncausal",
            }
        )

        state_data = _baseline_stable_state(data)
        state_levels = ("zero_stable", "mixed_native_stable", "all_stable")
        baseline_support = state_data[state_data["year"].eq(2024)]
        for level in state_levels:
            level_support = baseline_support[
                baseline_support["baseline_stable_state"].eq(level)
            ]
            if (
                len(level_support) < 500
                or level_support[["src", "tgt"]].drop_duplicates().shape[0] < 50
            ):
                raise RuntimeError(
                    f"baseline-state heterogeneity lacks credible support for {level}"
                )
        state_rows, _state_fit = _fit_share_change_by_group(
            state_data,
            group_column="baseline_stable_state",
            levels=state_levels,
            analysis_block="appendix_mechanical_baseline_state_bounds",
            multiplicity_family=f"baseline_stable_state.{metric}",
            declaration_status="appendix_only_mechanically_bounded_diagnostic",
        )
        rows.extend(state_rows)

    weth = MAJOR_ENDPOINT_TOKENS["WETH"]
    for metric in HETEROGENEITY_METRICS:
        data = _matched_metric(panel, metric)
        baseline = data[data["year"].eq(2024)]
        weth_endpoint = data["src"].eq(weth) | data["tgt"].eq(weth)
        weth_rows = data[weth_endpoint]
        if weth_rows.empty:
            raise RuntimeError(f"{metric} has no WETH-endpoint support")
        if not (
            np.allclose(weth_rows["stable_share"], 1.0)
            and np.allclose(weth_rows["native"], 0.0)
            and np.allclose(weth_rows["stable"], weth_rows["denominator"])
        ):
            raise RuntimeError(
                f"{metric} violates the mechanical WETH-endpoint intermediary identity"
            )
        rows.append(
            {
                "row_type": "assessment",
                "analysis_block": "mechanical_weth_endpoint_identity",
                "method": "deterministic_eligibility_identity",
                "metric": metric,
                "dimension": "weth_endpoint_status",
                "level": "weth_is_source_or_destination",
                "contrast": None,
                "observations": int(len(weth_rows)),
                "matched_cells": int(len(weth_rows) // 2),
                "stable_share_minimum": float(weth_rows["stable_share"].min()),
                "stable_share_maximum": float(weth_rows["stable_share"].max()),
                "native_mass_maximum": float(weth_rows["native"].max()),
                "mechanical_boundary": (
                    "WETH cannot be both a route endpoint and the intermediary; within the "
                    "native-WETH-versus-stablecoin comparison, every WETH-endpoint route is "
                    "therefore assigned stable share one"
                ),
                "interpretation": "eligibility_identity_not_estimated_behavior",
                "declaration_status": "identity_reopened_after_j1_mechanical_eligibility_review",
            }
        )

        scenario_data = {
            "full_matched_panel": data,
            "exclude_WETH_endpoints": data[~weth_endpoint].copy(),
        }
        full_pairs = baseline[["src", "tgt"]].drop_duplicates().shape[0]
        for scenario, retained in scenario_data.items():
            retained_baseline = retained[retained["year"].eq(2024)]
            retained_comparison = retained[retained["year"].eq(2026)]
            support = {
                "matched_cell_share_of_full": float(len(retained_baseline) / len(baseline)),
                "ordered_pair_share_of_full": float(
                    retained_baseline[["src", "tgt"]].drop_duplicates().shape[0]
                    / full_pairs
                ),
                "baseline_denominator_mass_share_of_full": float(
                    retained_baseline["denominator"].sum()
                    / baseline["denominator"].sum()
                ),
                "comparison_denominator_mass_share_of_full": float(
                    retained_comparison["denominator"].sum()
                    / data.loc[data["year"].eq(2026), "denominator"].sum()
                ),
            }
            aggregate = next(
                row
                for row in paired_calendar_comparison(retained, metric)
                if row["method"] == "paired_calendar_hac_t"
            )
            aggregate_critical = float(
                stats.t.ppf(0.975, int(aggregate["observations"]) - 1)
            )
            rows.append(
                {
                    "row_type": "estimate",
                    "analysis_block": "weth_endpoint_mechanical_allocation",
                    "method": "paired_calendar_hac_t",
                    "metric": metric,
                    "dimension": "weth_endpoint_sample",
                    "level": scenario,
                    "contrast": None,
                    "coefficient": aggregate["coefficient"],
                    "standard_error": aggregate["standard_error"],
                    "t_statistic": aggregate["t_statistic"],
                    "p_value": aggregate["p_value"],
                    "confidence_interval_lower": float(aggregate["coefficient"])
                    - aggregate_critical * float(aggregate["standard_error"]),
                    "confidence_interval_upper": float(aggregate["coefficient"])
                    + aggregate_critical * float(aggregate["standard_error"]),
                    "observations": aggregate["observations"],
                    "matched_cells": aggregate["matched_cells"],
                    "ordered_pair_clusters": int(
                        retained[["src", "tgt"]].drop_duplicates().shape[0]
                    ),
                    "calendar_date_clusters": int(retained["date"].nunique()),
                    "fixed_effects": "paired_month_day",
                    "covariance": aggregate["covariance"],
                    "estimand": aggregate["estimand"],
                    "multiplicity_family": f"weth_endpoint.aggregate_paired_sensitivity.{metric}",
                    "declaration_status": "identity_reopened_after_j1_mechanical_eligibility_review",
                    "mechanical_boundary": (
                        "excluding WETH endpoints removes route groups in which native-WETH "
                        "intermediation is mechanically ineligible"
                        if scenario == "exclude_WETH_endpoints"
                        else "full matched route panel includes mechanically all-stable WETH-endpoint groups"
                    ),
                    "interpretation": "paired_month_day_covariance_sensitivity_noncausal",
                    "inference_assumption": (
                        "same month-days are differenced before HAC, permitting matched seasonal-day "
                        "cross-year covariance despite the two-year calendar separation"
                    ),
                    "primary_covariance": False,
                    **support,
                }
            )
            endpoint_aggregate = endpoint_year_calendar_comparison(retained, metric)
            rows.append(
                {
                    "row_type": "estimate",
                    "analysis_block": "weth_endpoint_mechanical_allocation",
                    **endpoint_aggregate,
                    "dimension": "weth_endpoint_sample",
                    "level": scenario,
                    "contrast": None,
                    "ordered_pair_clusters": int(
                        retained[["src", "tgt"]].drop_duplicates().shape[0]
                    ),
                    "calendar_date_clusters": int(retained["date"].nunique()),
                    "multiplicity_family": f"weth_endpoint.aggregate_primary.{metric}",
                    "declaration_status": "identity_reopened_after_j1_mechanical_eligibility_review",
                    "mechanical_boundary": (
                        "excluding WETH endpoints removes route groups in which native-WETH "
                        "intermediation is mechanically ineligible"
                        if scenario == "exclude_WETH_endpoints"
                        else "full matched route panel includes mechanically all-stable WETH-endpoint groups"
                    ),
                    "primary_covariance": True,
                    **support,
                }
            )
            retained = retained.assign(weth_endpoint_sample="retained")
            within_rows, _within_fit = _fit_share_change_by_group(
                retained,
                group_column="weth_endpoint_sample",
                levels=("retained",),
                analysis_block="weth_endpoint_mechanical_allocation",
                multiplicity_family=f"weth_endpoint.within_group.{metric}",
                declaration_status="identity_reopened_after_j1_mechanical_eligibility_review",
            )
            within = within_rows[0]
            within.update(
                {
                    "dimension": "weth_endpoint_sample",
                    "level": scenario,
                    "mechanical_boundary": (
                        "fixed effects compare the same ordered source-destination, month-day, "
                        "and realised route-scope group; feasible routes and venue identity remain unfixed"
                    ),
                    "interpretation": "descriptive_within_matched_route_group_change_noncausal",
                    **support,
                }
            )
            rows.append(within)

        for year in (2024, 2026):
            year_data = data[data["year"].eq(year)]
            year_weth = year_data[
                year_data["src"].eq(weth) | year_data["tgt"].eq(weth)
            ]
            rows.append(
                {
                    "row_type": "assessment",
                    "analysis_block": "weth_endpoint_support",
                    "method": "exact_support_accounting",
                    "metric": metric,
                    "dimension": "endpoint_year",
                    "level": str(year),
                    "contrast": None,
                    "observations": int(len(year_weth)),
                    "matched_cells": int(len(year_weth)),
                    "support_share": float(len(year_weth) / len(year_data)),
                    "denominator_mass": float(year_weth["denominator"].sum()),
                    "denominator_mass_share": float(
                        year_weth["denominator"].sum() / year_data["denominator"].sum()
                    ),
                    "interpretation": "weth_endpoint_share_of_matched_route_support_and_mass",
                    "mechanical_boundary": "support and mass accounting; no behavioral coefficient",
                }
            )

        excluded_major = frozenset(MAJOR_ENDPOINT_TOKENS.values())
        leave_three = data[
            ~data["src"].isin(excluded_major) & ~data["tgt"].isin(excluded_major)
        ]
        leave_three_baseline = leave_three[leave_three["year"].eq(2024)]
        rows.append(
            {
                "row_type": "assessment",
                "analysis_block": "major_endpoint_leave_three_support",
                "method": "support_attrition_accounting_not_robustness",
                "metric": metric,
                "dimension": "endpoint_sample",
                "level": "exclude_USDT_USDC_WETH_endpoints",
                "contrast": None,
                "observations": int(len(leave_three)),
                "matched_cells": int(len(leave_three_baseline)),
                "matched_cell_share_of_full": float(
                    len(leave_three_baseline) / len(baseline)
                ),
                "ordered_pair_share_of_full": float(
                    leave_three_baseline[["src", "tgt"]].drop_duplicates().shape[0]
                    / full_pairs
                ),
                "baseline_denominator_mass_share_of_full": float(
                    leave_three_baseline["denominator"].sum()
                    / baseline["denominator"].sum()
                ),
                "comparison_denominator_mass_share_of_full": float(
                    leave_three.loc[leave_three["year"].eq(2026), "denominator"].sum()
                    / data.loc[data["year"].eq(2026), "denominator"].sum()
                ),
                "interpretation": "severe_support_attrition_precludes_robustness_language",
                "mechanical_boundary": "reports surviving support only; not an alternative population estimate",
            }
        )

    rows.extend(strict_value_non_weth_composition(panel).to_dict("records"))
    output = _holm_by_family(pd.DataFrame(rows))
    return attach_spec_ids(
        output,
        prefix="route_methodology_heterogeneity",
        columns=("row_type", "analysis_block", "method", "metric", "dimension", "level", "contrast"),
    )


def _signed_pp(value: float) -> str:
    points = 100.0 * value
    if abs(points) < 0.05:
        return "$0.0$ pp"
    return f"${points:+.1f}$ pp"


def _share(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def render_heterogeneity_deck_values(
    results: pd.DataFrame,
) -> str:
    """Render the WETH-eligibility values used by the paper and deck."""

    def estimate(metric: str, level: str, method: str) -> pd.Series:
        selected = results[
            results["analysis_block"].eq("weth_endpoint_mechanical_allocation")
            & results["metric"].eq(metric)
            & results["level"].eq(level)
            & results["method"].eq(method)
        ]
        if len(selected) != 1:
            raise ValueError(
                f"expected one WETH allocation estimate for {metric}/{level}/{method}"
            )
        return selected.iloc[0]

    def support(metric: str, year: int) -> pd.Series:
        selected = results[
            results["analysis_block"].eq("weth_endpoint_support")
            & results["metric"].eq(metric)
            & results["level"].eq(str(year))
        ]
        if len(selected) != 1:
            raise ValueError(f"expected one WETH support row for {metric}/{year}")
        return selected.iloc[0]

    def decomposition(component: str) -> pd.Series:
        selected = results[
            results["analysis_block"].eq(
                "non_weth_strict_value_midpoint_decomposition"
            )
            & results["method"].eq(
                "endpoint_year_midpoint_kitagawa_calendar_hac"
            )
            & results["level"].eq(component)
            & results["hac_lag"].eq(30)
        ]
        if len(selected) != 1:
            raise ValueError(f"expected one primary decomposition row for {component}")
        return selected.iloc[0]

    count_full = estimate(
        "count_share", "full_matched_panel", "endpoint_year_calendar_hac_t"
    )
    count_no_weth = estimate(
        "count_share", "exclude_WETH_endpoints", "endpoint_year_calendar_hac_t"
    )
    count_within_full = estimate(
        "count_share", "full_matched_panel", "denominator_weighted_cell_fixed_effect_wls"
    )
    count_within_no_weth = estimate(
        "count_share",
        "exclude_WETH_endpoints",
        "denominator_weighted_cell_fixed_effect_wls",
    )
    value_full = estimate(
        "strict_intermediation_value_share",
        "full_matched_panel",
        "endpoint_year_calendar_hac_t",
    )
    value_no_weth = estimate(
        "strict_intermediation_value_share",
        "exclude_WETH_endpoints",
        "endpoint_year_calendar_hac_t",
    )
    count_2024 = support("count_share", 2024)
    count_2026 = support("count_share", 2026)
    value_2024 = support("strict_intermediation_value_share", 2024)
    value_2026 = support("strict_intermediation_value_share", 2026)
    value_activity = decomposition("activity_weight_reallocation")
    value_within = decomposition("within_group_share_change")
    if any(
        int(row["observations"]) != 362
        for row in (count_full, count_no_weth, value_full, value_no_weth)
    ):
        raise ValueError("presentation binding requires the exact 181-day matched calendar")
    lines = [
        "% Generated by scripts/analyze/run_route_heterogeneity.py; do not edit.",
        "% Supporting descriptive analysis; WETH eligibility is a mechanical sample boundary.",
        "% SAMPLE: exact two-leg native-WETH-versus-stablecoin routes; 181 common month-days; 2024 versus January-June 2026",
        "% LITERATURE-GROUNDING: Mukhin (2022) raw text lines 777-850 (trade-flow switching order); Gopinath-Stein (2021) lines 1280-1305 (share feedback); Carletti et al. (2021) lines 120-220 (funding-share substitution with unchanged total funding)",
        f"\\newcommand{{\\WethCountFullChange}}{{{_signed_pp(float(count_full['coefficient']))}}}",
        f"\\newcommand{{\\WethCountFullCILower}}{{{_signed_pp(float(count_full['confidence_interval_lower']))}}}",
        f"\\newcommand{{\\WethCountFullCIUpper}}{{{_signed_pp(float(count_full['confidence_interval_upper']))}}}",
        f"\\newcommand{{\\WethCountNoEndpointChange}}{{{_signed_pp(float(count_no_weth['coefficient']))}}}",
        f"\\newcommand{{\\WethCountNoEndpointCILower}}{{{_signed_pp(float(count_no_weth['confidence_interval_lower']))}}}",
        f"\\newcommand{{\\WethCountNoEndpointCIUpper}}{{{_signed_pp(float(count_no_weth['confidence_interval_upper']))}}}",
        f"\\newcommand{{\\WethCountWithinFullChange}}{{{_signed_pp(float(count_within_full['coefficient']))}}}",
        f"\\newcommand{{\\WethCountWithinFullCILower}}{{{_signed_pp(float(count_within_full['confidence_interval_lower']))}}}",
        f"\\newcommand{{\\WethCountWithinFullCIUpper}}{{{_signed_pp(float(count_within_full['confidence_interval_upper']))}}}",
        f"\\newcommand{{\\WethCountWithinNoEndpointChange}}{{{_signed_pp(float(count_within_no_weth['coefficient']))}}}",
        f"\\newcommand{{\\WethCountWithinNoEndpointCILower}}{{{_signed_pp(float(count_within_no_weth['confidence_interval_lower']))}}}",
        f"\\newcommand{{\\WethCountWithinNoEndpointCIUpper}}{{{_signed_pp(float(count_within_no_weth['confidence_interval_upper']))}}}",
        f"\\newcommand{{\\WethValueFullChange}}{{{_signed_pp(float(value_full['coefficient']))}}}",
        f"\\newcommand{{\\WethValueFullCILower}}{{{_signed_pp(float(value_full['confidence_interval_lower']))}}}",
        f"\\newcommand{{\\WethValueFullCIUpper}}{{{_signed_pp(float(value_full['confidence_interval_upper']))}}}",
        f"\\newcommand{{\\WethValueNoEndpointChange}}{{{_signed_pp(float(value_no_weth['coefficient']))}}}",
        f"\\newcommand{{\\WethValueNoEndpointCILower}}{{{_signed_pp(float(value_no_weth['confidence_interval_lower']))}}}",
        f"\\newcommand{{\\WethValueNoEndpointCIUpper}}{{{_signed_pp(float(value_no_weth['confidence_interval_upper']))}}}",
        f"\\newcommand{{\\WethValueActivityChange}}{{{_signed_pp(float(value_activity['coefficient']))}}}",
        f"\\newcommand{{\\WethValueActivityCILower}}{{{_signed_pp(float(value_activity['confidence_interval_lower']))}}}",
        f"\\newcommand{{\\WethValueActivityCIUpper}}{{{_signed_pp(float(value_activity['confidence_interval_upper']))}}}",
        f"\\newcommand{{\\WethValueWithinChange}}{{{_signed_pp(float(value_within['coefficient']))}}}",
        f"\\newcommand{{\\WethValueWithinCILower}}{{{_signed_pp(float(value_within['confidence_interval_lower']))}}}",
        f"\\newcommand{{\\WethValueWithinCIUpper}}{{{_signed_pp(float(value_within['confidence_interval_upper']))}}}",
        f"\\newcommand{{\\WethCountMassBase}}{{{_share(float(count_2024['denominator_mass_share']))}}}",
        f"\\newcommand{{\\WethCountMassEnd}}{{{_share(float(count_2026['denominator_mass_share']))}}}",
        f"\\newcommand{{\\WethValueMassBase}}{{{_share(float(value_2024['denominator_mass_share']))}}}",
        f"\\newcommand{{\\WethValueMassEnd}}{{{_share(float(value_2026['denominator_mass_share']))}}}",
        f"\\newcommand{{\\WethCountMatchedGroups}}{{{int(count_full['matched_cells']):,}}}",
        f"\\newcommand{{\\WethCountNoEndpointGroups}}{{{int(count_no_weth['matched_cells']):,}}}",
    ]
    return "\n".join(lines) + "\n"


def run_heterogeneity(
    *,
    panel_path: Path = PAIR_PANEL,
    result_path: Path = HETEROGENEITY,
    deck_values_path: Path | None = HETEROGENEITY_DECK_VALUES,
) -> pd.DataFrame:
    """Write the supporting eligibility and heterogeneity results."""

    panel = pd.read_parquet(panel_path)
    results = route_heterogeneity_results(panel)
    write_exhibit(
        results,
        result_path,
        code_sources=CODE_SOURCES,
        inputs=[panel_path],
        notes=(
            "Supporting descriptive analysis of realised-integration-scope heterogeneity, "
            "mechanically bounded baseline-state diagnostics, the deterministic "
            "WETH-endpoint eligibility identity, and full-versus-exclude-WETH comparisons "
            "with two-way clustered or calendar-HAC "
            "inference and Holm control; the joint USDT-USDC-WETH "
            "leave-out is support-attrition accounting, not robustness; positive composition "
            "framing is grounded to raw passages at literature/text/"
            "2022-Mukhin2022InternationalPriceSystem-an-equilibrium-model-of-the-international-price-system.txt:777-850, "
            "2021-GopinathStein2021Making-banking-trade-and-the-making-of-a-dominant-currency.txt:1280-1305, "
            "and 2021-CarlettiDeMarcoIoannidouSette2021PatientLenders-banks-as-patient-lenders-evidence-from-a-tax-reform.txt:120-220"
        ),
    )
    if deck_values_path is not None:
        rendered = render_heterogeneity_deck_values(results)
        with atomic_output(deck_values_path) as temporary:
            temporary.write_text(rendered, encoding="utf-8")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=PAIR_PANEL)
    parser.add_argument("--results", type=Path, default=HETEROGENEITY)
    parser.add_argument(
        "--deck-values",
        type=Path,
        default=HETEROGENEITY_DECK_VALUES,
    )
    args = parser.parse_args()
    results = run_heterogeneity(
        panel_path=args.panel,
        result_path=args.results,
        deck_values_path=args.deck_values,
    )
    print(results.to_json(orient="records"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

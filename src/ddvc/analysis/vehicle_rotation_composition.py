"""Locked pair-panel and realised-composition accounting for vehicle rotation."""

from __future__ import annotations

from itertools import permutations
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    ols_clustered,
)
from ddvc.calendar import RESEARCH_SAMPLE_END


BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
METRICS = {
    "count_share": "route_count",
    "matched_strict_count_share": "within_20pct_routes",
    "strict_intermediation_value_share": "within_20pct_value_usd",
}
REPORTING_SCOPES = ("pooled", "single_venue", "cross_venue")
PAIR_KEYS = ("src", "tgt")
PAIR_PANEL_KEYS = (*PAIR_KEYS, "month_day", "integration_scope")
REQUIRED_CHOICE_COLUMNS = {
    "date",
    *PAIR_KEYS,
    "candidate_address",
    "candidate_type",
    "venue_sequence",
    "integration_scope",
    *METRICS.values(),
}
PAIR_MEMBERSHIP_ORDER = ("common", "baseline_exclusive", "comparison_exclusive")


def estimate_pair_fixed_effect_rotation(pair_panel: pd.DataFrame) -> pd.DataFrame:
    """Fit the locked 2026 coefficient inside pair-month-day-scope cells.

    This is the inferential companion to the descriptive decomposition. It asks
    whether stable share changes inside cells that hold the ordered endpoint
    pair, calendar position, and realised integration scope fixed. It does not
    hold the feasible route set, notional, or router decision state fixed.
    """

    required = {
        "metric",
        "source_column",
        "year",
        "date",
        *PAIR_PANEL_KEYS,
        "denominator",
        "stable_share",
    }
    missing = sorted(required - set(pair_panel.columns))
    if missing:
        raise ValueError(f"vehicle-rotation pair panel lacks columns: {missing}")
    data = pair_panel.copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    if not data["year"].isin((BASELINE_YEAR, COMPARISON_YEAR)).all():
        raise ValueError("vehicle-rotation pair panel has an unexpected endpoint year")
    if not data["date"].dt.year.eq(data["year"]).all():
        raise ValueError("vehicle-rotation pair-panel dates disagree with endpoint years")
    for column in ("denominator", "stable_share"):
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column]).all():
            raise ValueError(f"vehicle-rotation pair panel has nonfinite {column}")
    if data["denominator"].le(0).any():
        raise ValueError("vehicle-rotation pair panel requires positive denominator mass")
    if not data["stable_share"].between(0.0, 1.0).all():
        raise ValueError("vehicle-rotation pair panel has a share outside zero and one")
    if data.duplicated(["metric", "year", *PAIR_PANEL_KEYS]).any():
        raise ValueError("vehicle-rotation pair panel contains duplicate endpoint cells")

    rows: list[dict[str, object]] = []
    for metric in METRICS:
        selected = data[data["metric"].eq(metric)].copy()
        if selected.empty:
            raise ValueError(f"vehicle-rotation pair panel lacks metric {metric}")
        source_columns = selected["source_column"].drop_duplicates()
        if len(source_columns) != 1 or source_columns.iloc[0] != METRICS[metric]:
            raise ValueError(f"vehicle-rotation {metric} source column disagrees")
        endpoint_counts = selected.groupby(list(PAIR_PANEL_KEYS))["year"].agg(
            ["size", "nunique"]
        )
        if not endpoint_counts.eq(2).all().all():
            raise ValueError(
                f"vehicle-rotation {metric} fixed-effect cells require both endpoint years"
            )

        fixed_effect = pd.Series(
            list(selected[list(PAIR_PANEL_KEYS)].itertuples(index=False, name=None)),
            index=selected.index,
            name="pair_month_day_scope",
        )
        pair_cluster = pd.Series(
            list(selected[list(PAIR_KEYS)].itertuples(index=False, name=None)),
            index=selected.index,
            name="ordered_endpoint_pair",
        )
        year_indicator = selected["year"].eq(COMPARISON_YEAR).astype(float)
        weights = selected["denominator"].astype(float)
        absorbed = absorb_fixed_effects(
            selected[["stable_share"]].assign(year_indicator=year_indicator),
            fixed_effect,
            weights=weights,
        )
        fit = ols_clustered(
            absorbed["stable_share"],
            absorbed[["year_indicator"]],
            pair_cluster,
            add_constant=False,
            absorbed_groups=(fixed_effect,),
            additional_clusters=(selected["date"],),
            weights=weights,
            min_observations=4,
            min_clusters=2,
        )

        endpoints = selected.pivot(
            index=list(PAIR_PANEL_KEYS),
            columns="year",
            values=["stable_share", "denominator"],
        )
        baseline_weight = endpoints[("denominator", BASELINE_YEAR)].to_numpy(float)
        comparison_weight = endpoints[("denominator", COMPARISON_YEAR)].to_numpy(float)
        effective_weight = (
            baseline_weight
            * comparison_weight
            / (baseline_weight + comparison_weight)
        )
        cell_change = (
            endpoints[("stable_share", COMPARISON_YEAR)].to_numpy(float)
            - endpoints[("stable_share", BASELINE_YEAR)].to_numpy(float)
        )
        direct_coefficient = float(np.average(cell_change, weights=effective_weight))
        coefficient = float(fit.beta[0])
        if not np.isclose(coefficient, direct_coefficient, atol=1e-12, rtol=1e-10):
            raise RuntimeError(
                f"vehicle-rotation {metric} WLS coefficient disagrees with paired identity"
            )
        standard_error = float(fit.standard_errors[0])
        t_statistic = float(fit.t_statistics[0])
        p_value = float(fit.p_values[0])
        degrees_freedom = fit.n_clusters - 1
        critical = (
            float(stats.t.ppf(0.975, degrees_freedom))
            if degrees_freedom > 0 and np.isfinite(standard_error)
            else float("nan")
        )
        cluster_counts = fit.cluster_counts or (fit.n_clusters, fit.n_clusters)
        rows.append(
            {
                "metric": metric,
                "source_column": str(source_columns.iloc[0]),
                "baseline_year": BASELINE_YEAR,
                "comparison_year": COMPARISON_YEAR,
                "coefficient": coefficient,
                "coefficient_pp": 100.0 * coefficient,
                "standard_error": standard_error,
                "standard_error_pp": 100.0 * standard_error,
                "t_statistic": t_statistic,
                "p_value": p_value,
                "confidence_interval_lower": coefficient - critical * standard_error,
                "confidence_interval_upper": coefficient + critical * standard_error,
                "observations": fit.n_observations,
                "fixed_effect_cells": int(len(endpoints)),
                "ordered_pair_clusters": int(cluster_counts[0]),
                "calendar_date_clusters": int(cluster_counts[1]),
                "absorbed_degrees_of_freedom": fit.absorbed_degrees_of_freedom,
                "baseline_denominator_mass": float(baseline_weight.sum()),
                "comparison_denominator_mass": float(comparison_weight.sum()),
                "effective_weight_mass": float(effective_weight.sum()),
                "estimator_id": "weighted_stable_share_saturated_pair_month_day_scope_fe_v1",
                "covariance_id": "two_way_ordered_pair_calendar_date_cr1",
                "fixed_effects": "ordered_endpoint_pair_x_month_day_x_integration_scope",
                "estimand_scope": "common_pair_month_day_realised_integration_scope",
                "mechanism_status": "descriptive_fixed_realised_scope_noncausal",
                "omitted_dimensions": "feasible_routes|notional|router_state|search_efficiency",
            }
        )
    result = pd.DataFrame(rows)
    result["p_value_holm"] = holm_adjusted_pvalues(result["p_value"])
    return result


def load_market_incidence_annual_pairs(
    pair_support_path: Path,
    choices_path: Path,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> pd.DataFrame:
    """Aggregate the released pair ledger on the decomposition's common calendar."""

    connection = duckdb.connect()
    try:
        return connection.execute(
            """
            WITH common_days AS (
                SELECT strftime(date, '%m-%d') AS month_day
                FROM read_parquet(?)
                WHERE year(date) IN (?, ?)
                GROUP BY 1
                HAVING count(DISTINCT year(date)) = 2
            )
            SELECT
                year(date)::INTEGER AS year,
                src,
                tgt,
                sum(market_route_count)::DOUBLE AS market_route_count,
                sum(primary_choice_route_count)::DOUBLE AS primary_choice_route_count,
                sum(native_choice_route_count)::DOUBLE AS native_choice_route_count,
                sum(stable_choice_route_count)::DOUBLE AS stable_choice_route_count
            FROM read_parquet(?)
            WHERE year(date) IN (?, ?)
              AND strftime(date, '%m-%d') IN (SELECT month_day FROM common_days)
            GROUP BY 1, 2, 3
            ORDER BY 2, 3, 1
            """,
            [
                str(choices_path),
                baseline_year,
                comparison_year,
                str(pair_support_path),
                baseline_year,
                comparison_year,
            ],
        ).fetchdf()
    finally:
        connection.close()


def _weighted_stable_share(frame: pd.DataFrame, suffix: str) -> float:
    denominator = float(frame[f"primary_{suffix}"].sum())
    if denominator <= 0:
        raise ValueError("market-incidence decomposition lacks positive primary mass")
    return float(frame[f"stable_{suffix}"].sum() / denominator)


def _factor_share(market: np.ndarray, incidence: np.ndarray, stable_share: np.ndarray) -> float:
    mass = market * incidence
    denominator = float(mass.sum())
    if denominator <= 0:
        raise ValueError("market-incidence factor state has zero primary mass")
    return float(np.dot(mass, stable_share) / denominator)


def vehicle_rotation_market_incidence_decomposition(
    annual_pairs: pd.DataFrame,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bridge support turnover and Shapley M/I/s terms for count rotation.

    M is observed market-route activity, I is realised primary vehicle-route
    incidence, and s is stable share conditional on that realised vehicle role.
    None is interpreted as availability, demand, preference, or treatment.
    """

    required = {
        "year",
        *PAIR_KEYS,
        "market_route_count",
        "primary_choice_route_count",
        "native_choice_route_count",
        "stable_choice_route_count",
    }
    missing = sorted(required - set(annual_pairs.columns))
    if missing:
        raise ValueError(f"market-incidence annual pairs lack columns: {missing}")
    data = annual_pairs.copy()
    if data.duplicated(["year", *PAIR_KEYS]).any():
        raise ValueError("market-incidence annual pairs contain duplicate year-pair keys")
    if set(data["year"].unique()) != {baseline_year, comparison_year}:
        raise ValueError("market-incidence decomposition requires both endpoint years")
    quantities = [
        "market_route_count",
        "primary_choice_route_count",
        "native_choice_route_count",
        "stable_choice_route_count",
    ]
    for column in quantities:
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column]).all() or data[column].lt(0).any():
            raise ValueError(f"market-incidence pairs contain invalid {column}")
    if not data["primary_choice_route_count"].eq(
        data["native_choice_route_count"] + data["stable_choice_route_count"]
    ).all():
        raise ValueError("market-incidence primary mass does not reconcile by type")
    if not data["primary_choice_route_count"].le(data["market_route_count"]).all():
        raise ValueError("market-incidence primary mass exceeds observed market activity")

    renamed = data.rename(
        columns={
            "market_route_count": "market",
            "primary_choice_route_count": "primary",
            "stable_choice_route_count": "stable",
        }
    )
    baseline = renamed[renamed["year"].eq(baseline_year)].drop(
        columns=["year", "native_choice_route_count"]
    )
    comparison = renamed[renamed["year"].eq(comparison_year)].drop(
        columns=["year", "native_choice_route_count"]
    )
    merged = baseline.merge(
        comparison,
        on=list(PAIR_KEYS),
        how="outer",
        suffixes=("_baseline", "_comparison"),
        validate="one_to_one",
    ).fillna(0.0)
    for suffix in ("baseline", "comparison"):
        merged[f"incidence_{suffix}"] = np.divide(
            merged[f"primary_{suffix}"],
            merged[f"market_{suffix}"],
            out=np.zeros(len(merged), dtype=float),
            where=merged[f"market_{suffix}"].to_numpy() > 0,
        )
        merged[f"stable_share_{suffix}"] = np.divide(
            merged[f"stable_{suffix}"],
            merged[f"primary_{suffix}"],
            out=np.zeros(len(merged), dtype=float),
            where=merged[f"primary_{suffix}"].to_numpy() > 0,
        )

    established = merged["market_baseline"].gt(0) & merged["market_comparison"].gt(0)
    common_role = merged["primary_baseline"].gt(0) & merged["primary_comparison"].gt(0)
    if not common_role.any():
        raise ValueError("market-incidence decomposition has no common vehicle-role pairs")
    common = merged[common_role].copy()

    all_shares = {
        suffix: _weighted_stable_share(merged, suffix)
        for suffix in ("baseline", "comparison")
    }
    established_shares = {
        suffix: _weighted_stable_share(merged[established], suffix)
        for suffix in ("baseline", "comparison")
    }
    common_shares = {
        suffix: _weighted_stable_share(common, suffix)
        for suffix in ("baseline", "comparison")
    }

    factors = ("market", "incidence", "stable_share")
    endpoint = {
        factor: {
            "baseline": common[f"{factor}_baseline"].to_numpy(dtype=float),
            "comparison": common[f"{factor}_comparison"].to_numpy(dtype=float),
        }
        for factor in factors
    }
    shapley = dict.fromkeys(factors, 0.0)
    orders = tuple(permutations(factors))
    for order in orders:
        state = {factor: endpoint[factor]["baseline"] for factor in factors}
        prior = _factor_share(state["market"], state["incidence"], state["stable_share"])
        for factor in order:
            state[factor] = endpoint[factor]["comparison"]
            current = _factor_share(
                state["market"], state["incidence"], state["stable_share"]
            )
            shapley[factor] += (current - prior) / len(orders)
            prior = current

    market_support_bridge = (
        all_shares["comparison"] - established_shares["comparison"]
    ) - (all_shares["baseline"] - established_shares["baseline"])
    vehicle_role_support_bridge = (
        established_shares["comparison"] - common_shares["comparison"]
    ) - (established_shares["baseline"] - common_shares["baseline"])
    total_change = all_shares["comparison"] - all_shares["baseline"]
    identity_error = total_change - (
        market_support_bridge
        + vehicle_role_support_bridge
        + shapley["market"]
        + shapley["incidence"]
        + shapley["stable_share"]
    )
    if not np.isclose(identity_error, 0.0, atol=1e-12, rtol=0.0):
        raise RuntimeError(f"market-incidence identity failed: {identity_error}")

    summary = pd.DataFrame(
        [
            {
                "metric": "count_share",
                "source_column": "pair_support_count_accounting",
                "reporting_scope": "pooled",
                "baseline_year": baseline_year,
                "comparison_year": comparison_year,
                "baseline_stable_share": all_shares["baseline"],
                "comparison_stable_share": all_shares["comparison"],
                "total_change": total_change,
                "established_market_baseline_stable_share": established_shares["baseline"],
                "established_market_comparison_stable_share": established_shares["comparison"],
                "established_market_total_change": established_shares["comparison"]
                - established_shares["baseline"],
                "common_role_baseline_stable_share": common_shares["baseline"],
                "common_role_comparison_stable_share": common_shares["comparison"],
                "common_role_total_change": common_shares["comparison"]
                - common_shares["baseline"],
                "market_pair_support_bridge": market_support_bridge,
                "vehicle_role_support_bridge": vehicle_role_support_bridge,
                "market_activity_reweighting": shapley["market"],
                "vehicle_incidence_reweighting": shapley["incidence"],
                "within_pair_stable_share": shapley["stable_share"],
                "identity_error": identity_error,
                "formula_id": "shapley_market_incidence_stable_bridge_v1",
                "estimand_scope": "raw_pooled_count_share_market_incidence_bridge",
                "mechanism_status": "descriptive_observed_activity_and_realised_incidence_noncausal",
                "omitted_dimensions": "architecture|opportunity_set|demand|preference|search_efficiency",
            }
        ]
    )

    support_rows: list[dict[str, object]] = []
    year_specs = (
        (baseline_year, "baseline", "comparison"),
        (comparison_year, "comparison", "baseline"),
    )
    for year, suffix, other in year_specs:
        positive = merged[f"primary_{suffix}"].gt(0)
        statuses = np.select(
            [
                merged[f"market_{other}"].eq(0),
                merged[f"primary_{other}"].eq(0),
            ],
            [
                "market_pair_support_turnover",
                "vehicle_role_support_turnover_established_market",
            ],
            default="common_vehicle_role",
        )
        total_primary = float(merged.loc[positive, f"primary_{suffix}"].sum())
        for status in (
            "market_pair_support_turnover",
            "vehicle_role_support_turnover_established_market",
            "common_vehicle_role",
        ):
            selected = positive & pd.Series(statuses, index=merged.index).eq(status)
            primary_mass = float(merged.loc[selected, f"primary_{suffix}"].sum())
            stable_mass = float(merged.loc[selected, f"stable_{suffix}"].sum())
            support_rows.append(
                {
                    "record_type": "market_incidence_support",
                    "metric": "count_share",
                    "reporting_scope": "pooled",
                    "endpoint_year": year,
                    "support_status": status,
                    "unit": "ordered_endpoint_pair",
                    "units": int(selected.sum()),
                    "primary_choice_mass": primary_mass,
                    "primary_choice_mass_share": primary_mass / total_primary,
                    "stable_choice_mass": stable_mass,
                    "stable_share": stable_mass / primary_mass if primary_mass > 0 else 0.0,
                }
            )
    support = pd.DataFrame(support_rows)
    return summary, support


def _common_calendar_choices(
    choices: pd.DataFrame,
    *,
    baseline_year: int,
    comparison_year: int,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    data = choices.copy()
    missing = sorted(REQUIRED_CHOICE_COLUMNS - set(data.columns))
    if missing:
        raise ValueError(f"vehicle-rotation choices lack columns: {missing}")
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data = data[data["date"].dt.year.isin((baseline_year, comparison_year))].copy()
    if set(data["date"].dt.year.unique()) != {baseline_year, comparison_year}:
        raise ValueError("vehicle-rotation decomposition requires both endpoint years")
    locked_sample_end = pd.to_datetime(RESEARCH_SAMPLE_END, format="%Y%m%d")
    if data["date"].max() > locked_sample_end:
        raise ValueError("vehicle-rotation choices exceed the locked sample end")
    if data.duplicated(
        [
            "date",
            *PAIR_KEYS,
            "candidate_address",
            "integration_scope",
            "venue_sequence",
        ]
    ).any():
        raise ValueError("vehicle-rotation choices contain duplicate release keys")
    if not data["candidate_type"].isin(("native", "stable")).all():
        raise ValueError("vehicle-rotation choices contain a non-primary candidate type")
    if not data["integration_scope"].isin(REPORTING_SCOPES[1:]).all():
        raise ValueError("vehicle-rotation choices contain an invalid integration scope")
    for column in METRICS.values():
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column]).all() or data[column].lt(0).any():
            raise ValueError(f"vehicle-rotation choices contain invalid {column} magnitudes")
    data["year"] = data["date"].dt.year
    data["month_day"] = data["date"].dt.strftime("%m-%d")
    observed_month_days = {
        year: set(data.loc[data["year"].eq(year), "month_day"])
        for year in (baseline_year, comparison_year)
    }
    common_month_days = tuple(
        sorted(observed_month_days[baseline_year] & observed_month_days[comparison_year])
    )
    if not common_month_days:
        raise ValueError("vehicle-rotation endpoint years have no common month-day support")
    data = data[data["month_day"].isin(common_month_days)].copy()
    return data, common_month_days


def _candidate_wide(
    data: pd.DataFrame,
    *,
    group_keys: list[str],
    metric_column: str,
) -> pd.DataFrame:
    grouped = (
        data.groupby([*group_keys, "candidate_type"], as_index=False, sort=True)[
            metric_column
        ]
        .sum()
    )
    wide = grouped.pivot(
        index=group_keys,
        columns="candidate_type",
        values=metric_column,
    ).fillna(0.0)
    for candidate_type in ("native", "stable"):
        if candidate_type not in wide:
            wide[candidate_type] = 0.0
    wide = wide.reset_index()
    wide["denominator"] = wide["native"] + wide["stable"]
    return wide


def _pair_panel_for_metric(
    data: pd.DataFrame,
    *,
    metric: str,
    metric_column: str,
    baseline_year: int,
    comparison_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cells = _candidate_wide(
        data,
        group_keys=["year", "date", *PAIR_PANEL_KEYS],
        metric_column=metric_column,
    )
    positive = cells[cells["denominator"].gt(0)].copy()
    support = (
        positive.groupby([*PAIR_PANEL_KEYS, "year"], as_index=False, sort=True)[
            "denominator"
        ]
        .sum()
        .pivot(index=list(PAIR_PANEL_KEYS), columns="year", values="denominator")
        .fillna(0.0)
        .reset_index()
        .rename(
            columns={
                baseline_year: "baseline_denominator",
                comparison_year: "comparison_denominator",
            }
        )
    )
    for column in ("baseline_denominator", "comparison_denominator"):
        if column not in support:
            support[column] = 0.0
    support["endpoint_years"] = support[
        ["baseline_denominator", "comparison_denominator"]
    ].gt(0).sum(axis=1)
    common_keys = support[support["endpoint_years"].eq(2)][list(PAIR_PANEL_KEYS)]
    panel = positive.merge(
        common_keys,
        on=list(PAIR_PANEL_KEYS),
        how="inner",
        validate="many_to_one",
    )
    panel["stable_share"] = panel["stable"] / panel["denominator"]
    panel.insert(0, "metric", metric)
    panel.insert(1, "source_column", metric_column)
    panel = panel.sort_values(
        ["metric", "date", *PAIR_KEYS, "integration_scope"], kind="stable"
    ).reset_index(drop=True)

    support["support_status"] = np.select(
        [
            support["endpoint_years"].eq(2),
            support["baseline_denominator"].gt(0),
        ],
        ["common", "baseline_only"],
        default="comparison_only",
    )
    support_rows = (
        support.groupby("support_status", as_index=False, sort=True)
        .agg(
            units=("endpoint_years", "size"),
            baseline_denominator=("baseline_denominator", "sum"),
            comparison_denominator=("comparison_denominator", "sum"),
        )
    )
    zero_rows = int(cells["denominator"].eq(0).sum())
    support_rows["record_type"] = "pair_month_day_scope_support"
    support_rows["metric"] = metric
    support_rows["reporting_scope"] = "scope_specific"
    support_rows["unit"] = "ordered_endpoint_pair_month_day_integration_scope"
    support_rows["zero_denominator_cell_years"] = zero_rows
    return panel, support_rows


def _annual_pair_mass(
    data: pd.DataFrame,
    *,
    metric_column: str,
    reporting_scope: str,
) -> pd.DataFrame:
    selected = (
        data
        if reporting_scope == "pooled"
        else data[data["integration_scope"].eq(reporting_scope)]
    )
    if selected.empty:
        return pd.DataFrame(columns=["year", *PAIR_KEYS, "native", "stable", "denominator"])
    return _candidate_wide(
        selected,
        group_keys=["year", *PAIR_KEYS],
        metric_column=metric_column,
    )


def _decompose_metric_scope(
    annual: pd.DataFrame,
    *,
    metric: str,
    metric_column: str,
    reporting_scope: str,
    baseline_year: int,
    comparison_year: int,
    common_month_days: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    baseline = annual[annual["year"].eq(baseline_year)].drop(columns="year")
    comparison = annual[annual["year"].eq(comparison_year)].drop(columns="year")
    merged = baseline.merge(
        comparison,
        on=list(PAIR_KEYS),
        how="outer",
        suffixes=("_baseline", "_comparison"),
        validate="one_to_one",
    )
    for column in ("native", "stable", "denominator"):
        for suffix in ("baseline", "comparison"):
            merged[f"{column}_{suffix}"] = pd.to_numeric(
                merged[f"{column}_{suffix}"], errors="coerce"
            ).fillna(0.0)
    positive_baseline = merged["denominator_baseline"].gt(0)
    positive_comparison = merged["denominator_comparison"].gt(0)
    union = positive_baseline | positive_comparison
    merged = merged[union].copy()
    if merged.empty or not positive_baseline[union].any() or not positive_comparison[union].any():
        raise ValueError(
            f"vehicle-rotation {metric} {reporting_scope} scope lacks positive support "
            "in an endpoint year"
        )
    merged["pair_membership"] = np.select(
        [positive_baseline[union] & positive_comparison[union], positive_baseline[union]],
        ["common", "baseline_exclusive"],
        default="comparison_exclusive",
    )
    for suffix in ("baseline", "comparison"):
        denominator = merged[f"denominator_{suffix}"]
        merged[f"stable_share_{suffix}"] = np.divide(
            merged[f"stable_{suffix}"],
            denominator,
            out=np.zeros(len(merged), dtype=float),
            where=denominator.to_numpy() > 0,
        )

    common = merged["pair_membership"].eq("common")
    total_baseline = float(merged["denominator_baseline"].sum())
    total_comparison = float(merged["denominator_comparison"].sum())
    common_mass_baseline = float(merged.loc[common, "denominator_baseline"].sum())
    common_mass_comparison = float(merged.loc[common, "denominator_comparison"].sum())
    W_baseline = common_mass_baseline / total_baseline
    W_comparison = common_mass_comparison / total_comparison
    E_baseline = 1.0 - W_baseline
    E_comparison = 1.0 - W_comparison
    merged["q_baseline"] = 0.0
    merged["q_comparison"] = 0.0
    if common_mass_baseline > 0:
        merged.loc[common, "q_baseline"] = (
            merged.loc[common, "denominator_baseline"] / common_mass_baseline
        )
    if common_mass_comparison > 0:
        merged.loc[common, "q_comparison"] = (
            merged.loc[common, "denominator_comparison"] / common_mass_comparison
        )
    S_C_baseline = float(
        (merged.loc[common, "q_baseline"] * merged.loc[common, "stable_share_baseline"]).sum()
    )
    S_C_comparison = float(
        (
            merged.loc[common, "q_comparison"]
            * merged.loc[common, "stable_share_comparison"]
        ).sum()
    )
    exclusive_baseline = merged["pair_membership"].eq("baseline_exclusive")
    exclusive_comparison = merged["pair_membership"].eq("comparison_exclusive")
    S_E_baseline = (
        float(merged.loc[exclusive_baseline, "stable_baseline"].sum())
        / float(merged.loc[exclusive_baseline, "denominator_baseline"].sum())
        if E_baseline > 0
        else 0.0
    )
    S_E_comparison = (
        float(merged.loc[exclusive_comparison, "stable_comparison"].sum())
        / float(merged.loc[exclusive_comparison, "denominator_comparison"].sum())
        if E_comparison > 0
        else 0.0
    )

    W_bar = 0.5 * (W_baseline + W_comparison)
    E_bar = 0.5 * (E_baseline + E_comparison)
    q_bar = 0.5 * (merged["q_baseline"] + merged["q_comparison"])
    s_bar = 0.5 * (merged["stable_share_baseline"] + merged["stable_share_comparison"])
    within_common = float(
        W_bar
        * (
            q_bar[common]
            * (
                merged.loc[common, "stable_share_comparison"]
                - merged.loc[common, "stable_share_baseline"]
            )
        ).sum()
    )
    common_pair_reweighting = float(
        W_bar
        * (
            s_bar[common]
            * (
                merged.loc[common, "q_comparison"]
                - merged.loc[common, "q_baseline"]
            )
        ).sum()
    )
    common_support_mass = float(
        (0.5 * (S_C_baseline + S_C_comparison) - 0.5 * (S_E_baseline + S_E_comparison))
        * (W_comparison - W_baseline)
    )
    exclusive_pair_contribution = float(
        E_bar * (S_E_comparison - S_E_baseline)
    )
    baseline_stable_share = float(merged["stable_baseline"].sum() / total_baseline)
    comparison_stable_share = float(merged["stable_comparison"].sum() / total_comparison)
    total_change = comparison_stable_share - baseline_stable_share
    identity_error = total_change - (
        within_common
        + common_pair_reweighting
        + common_support_mass
        + exclusive_pair_contribution
    )
    if not np.isclose(identity_error, 0.0, atol=1e-12, rtol=0.0):
        raise RuntimeError(
            f"vehicle-rotation decomposition identity failed for {metric} "
            f"{reporting_scope}: {identity_error}"
        )
    summary = pd.DataFrame(
        [
            {
                "metric": metric,
                "source_column": metric_column,
                "reporting_scope": reporting_scope,
                "baseline_year": baseline_year,
                "comparison_year": comparison_year,
                "common_month_days": len(common_month_days),
                "common_calendar_end": max(common_month_days),
                "baseline_stable_share": baseline_stable_share,
                "comparison_stable_share": comparison_stable_share,
                "total_change": total_change,
                "within_common": within_common,
                "common_pair_reweighting": common_pair_reweighting,
                "common_support_mass": common_support_mass,
                "exclusive_pair_contribution": exclusive_pair_contribution,
                "support_and_exclusive_joint": common_support_mass
                + exclusive_pair_contribution,
                "identity_error": identity_error,
                "W_baseline": W_baseline,
                "W_comparison": W_comparison,
                "E_baseline": E_baseline,
                "E_comparison": E_comparison,
                "S_C_baseline": S_C_baseline,
                "S_C_comparison": S_C_comparison,
                "S_E_baseline": S_E_baseline,
                "S_E_comparison": S_E_comparison,
                "zero_exclusive_baseline_normalized": E_baseline == 0,
                "zero_exclusive_comparison_normalized": E_comparison == 0,
                "formula_id": "midpoint_common_exclusive_support_v1",
                "estimand_scope": "raw_pooled_conditional_stable_share_change"
                if reporting_scope == "pooled"
                else f"raw_{reporting_scope}_conditional_stable_share_change",
                "mechanism_status": "descriptive_realised_composition_noncausal",
                "omitted_dimensions": "notional_bin|exact_search_efficiency_state",
            }
        ]
    )
    totals = {baseline_year: total_baseline, comparison_year: total_comparison}
    support_rows: list[dict[str, object]] = []
    for membership in PAIR_MEMBERSHIP_ORDER:
        selected = merged[merged["pair_membership"].eq(membership)]
        support_rows.append(
            {
                "record_type": "decomposition_pair_support",
                "metric": metric,
                "reporting_scope": reporting_scope,
                "unit": "ordered_endpoint_pair",
                "support_status": membership,
                "units": len(selected),
                "baseline_denominator": float(selected["denominator_baseline"].sum()),
                "comparison_denominator": float(selected["denominator_comparison"].sum()),
                "baseline_denominator_share": float(
                    selected["denominator_baseline"].sum() / totals[baseline_year]
                ),
                "comparison_denominator_share": float(
                    selected["denominator_comparison"].sum() / totals[comparison_year]
                ),
                "zero_denominator_cell_years": 0,
            }
        )
    return summary, pd.DataFrame(support_rows)


def vehicle_rotation_composition(
    choices: pd.DataFrame,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return the locked common-support pair panel and four-term decomposition.

    The decomposition describes realised native-versus-stable composition. It
    does not identify adoption, preference, or an exogenous opportunity change;
    notional and exact search-efficiency state remain outside this input.
    """

    data, common_month_days = _common_calendar_choices(
        choices,
        baseline_year=baseline_year,
        comparison_year=comparison_year,
    )
    panels: list[pd.DataFrame] = []
    summaries: list[pd.DataFrame] = []
    support_frames: list[pd.DataFrame] = []
    for metric, metric_column in METRICS.items():
        panel, panel_support = _pair_panel_for_metric(
            data,
            metric=metric,
            metric_column=metric_column,
            baseline_year=baseline_year,
            comparison_year=comparison_year,
        )
        panels.append(panel)
        support_frames.append(panel_support)
        for reporting_scope in REPORTING_SCOPES:
            annual = _annual_pair_mass(
                data,
                metric_column=metric_column,
                reporting_scope=reporting_scope,
            )
            summary, decomposition_support = _decompose_metric_scope(
                annual,
                metric=metric,
                metric_column=metric_column,
                reporting_scope=reporting_scope,
                baseline_year=baseline_year,
                comparison_year=comparison_year,
                common_month_days=common_month_days,
            )
            summaries.append(summary)
            support_frames.append(decomposition_support)
    pair_panel = pd.concat(panels, ignore_index=True, sort=False)
    decomposition = pd.concat(summaries, ignore_index=True, sort=False).sort_values(
        ["metric", "reporting_scope"], kind="stable"
    ).reset_index(drop=True)
    support = pd.concat(support_frames, ignore_index=True, sort=False).sort_values(
        ["record_type", "metric", "reporting_scope", "support_status"], kind="stable"
    ).reset_index(drop=True)
    return pair_panel, decomposition, support

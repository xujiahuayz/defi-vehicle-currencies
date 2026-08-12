"""Registered E1 stable-versus-native vehicle-transition estimators."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.regression import absorb_fixed_effects, holm_adjusted_pvalues, ols_clustered
from ddvc.model_registry import canonical_hash


BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
EXPECTED_E1_DESIGN_HASH = "6990b221624cb3fffd7d00fcdd07827c4966cfe4d92c24723209d1a278bf80d4"
PAIR_PANEL_DESIGN_ID = "e1_1_pair_panel"
PAIR_DECOMPOSITION_DESIGN_ID = "e1_2_conditional_pair_decomposition"
ESTIMATOR_ID = "weighted_stable_share_saturated_pair_month_day_scope_fe_v1"
DECOMPOSITION_FORMULA_ID = "midpoint_common_exclusive_support_v1"
IDENTITY_TOLERANCE = 1e-12
INTEGRATION_SCOPES = ("single_venue", "cross_venue")
REPORTING_SCOPES = ("pooled", *INTEGRATION_SCOPES)
PAIR_PANEL_OUTPUT_COLUMNS = (
    "spec_id",
    "design_id",
    "design_hash",
    "estimator_id",
    "measure_id",
    "source_column",
    "baseline_year",
    "comparison_year",
    "coefficient",
    "coefficient_percentage_points",
    "standard_error",
    "standard_error_percentage_points",
    "t_statistic",
    "p_value",
    "p_value_holm",
    "confidence_interval_lower",
    "confidence_interval_upper",
    "n_observations",
    "n_fixed_effect_cells",
    "n_ordered_endpoint_pairs",
    "n_calendar_dates",
    "pair_clusters",
    "date_clusters",
    "effective_cell_weight_sum",
    "endpoint_release_generation",
)
DECOMPOSITION_OUTPUT_COLUMNS = (
    "spec_id",
    "design_id",
    "design_hash",
    "formula_id",
    "measure_id",
    "integration_scope",
    "baseline_year",
    "comparison_year",
    "baseline_stable_share",
    "comparison_stable_share",
    "delta_total",
    "within_common",
    "common_pair_reweighting",
    "common_support_mass",
    "exclusive_pair_contribution",
    "common_support_plus_exclusive_contribution",
    "reconstructed_delta",
    "closure_error",
    "identity_absolute_tolerance",
    "baseline_total_mass",
    "comparison_total_mass",
    "baseline_common_mass_share",
    "comparison_common_mass_share",
    "endpoint_release_generation",
)
SUPPORT_OUTPUT_COLUMNS = (
    "record_type",
    "design_hash",
    "measure_id",
    "integration_scope",
    "source_column",
    "source_choice_rows",
    "endpoint_positive_cell_rows",
    "common_support_observations",
    "common_support_cells",
    "one_sided_cell_rows_excluded",
    "ordered_endpoint_pairs",
    "calendar_dates",
    "common_month_days",
    "baseline_pair_count",
    "comparison_pair_count",
    "common_pair_count",
    "baseline_exclusive_pair_count",
    "comparison_exclusive_pair_count",
    "baseline_total_mass",
    "comparison_total_mass",
    "baseline_common_mass",
    "comparison_common_mass",
    "baseline_exclusive_mass",
    "comparison_exclusive_mass",
    "baseline_zero_exclusive_mass",
    "comparison_zero_exclusive_mass",
    "endpoint_release_generation",
)


@dataclass(frozen=True)
class MeasureContract:
    """One registered conditional stable-share measure."""

    measure_id: str
    source_column: str
    support: str
    weight: str


@dataclass(frozen=True)
class E1Outputs:
    """The three registered E1 artifacts before marker-last publication."""

    pair_panel: pd.DataFrame
    pair_decomposition: pd.DataFrame
    pair_support: pd.DataFrame


def _json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"E1 specification is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError("E1 specification must be a JSON object")
    return payload


def load_registered_e1_design(path: Path) -> tuple[dict[str, Any], tuple[MeasureContract, ...]]:
    """Load the exact registered E1 contract and reject coherent design drift."""

    specification = _json_object(path)
    declared_lock_hash = str(specification.get("lock_hash") or "")
    actual_lock_hash = canonical_hash({key: value for key, value in specification.items() if key != "lock_hash"})
    if specification.get("schema_version") != 1 or declared_lock_hash != actual_lock_hash:
        raise ValueError("E1 specification lock identity is stale or malformed")
    claims = [claim for claim in specification.get("claims", []) if isinstance(claim, dict) and claim.get("id") == "vehicle_transition"]
    if len(claims) != 1:
        raise ValueError("E1 specification requires exactly one vehicle_transition claim")
    claim = claims[0]
    design = claim.get("e1_design")
    if (
        claim.get("execution_gate") != "open"
        or claim.get("status") != "candidate_primary"
        or not isinstance(design, dict)
        or claim.get("e1_design_hash") != EXPECTED_E1_DESIGN_HASH
        or canonical_hash(design) != EXPECTED_E1_DESIGN_HASH
    ):
        raise ValueError("E1 registered design hash or execution status has drifted")
    pair = design.get("pair_panel")
    decomposition = design.get("pair_decomposition")
    if not isinstance(pair, dict) or not isinstance(decomposition, dict):
        raise ValueError("E1 registered design lacks its pair-panel or decomposition contract")
    exact_pair_fields = {
        "id": PAIR_PANEL_DESIGN_ID,
        "comparison_years": [BASELINE_YEAR, COMPARISON_YEAR],
        "cell_keys": ["src", "tgt", "date", "integration_scope"],
        "common_support_keys": ["src", "tgt", "month_day", "integration_scope"],
        "candidate_types": ["native", "stable"],
        "estimator_id": ESTIMATOR_ID,
        "fixed_effect_cell_keys": ["src", "tgt", "month_day", "integration_scope"],
        "clusters": ["ordered_endpoint_pair", "calendar_date"],
        "coefficient": "indicator for 2026 with 2024 omitted",
    }
    if any(pair.get(key) != value for key, value in exact_pair_fields.items()):
        raise ValueError("E1 pair-panel registered schema has drifted")
    multiplicity = pair.get("multiplicity")
    raw_measures = pair.get("primary_measures")
    if (
        multiplicity != {
            "method": "Holm",
            "family": [
                "count_share",
                "matched_strict_count_share",
                "strict_intermediation_value_share",
            ],
        }
        or not isinstance(raw_measures, list)
        or len(raw_measures) != 3
    ):
        raise ValueError("E1 primary coefficient family has drifted")
    measures = tuple(
        MeasureContract(
            measure_id=str(record.get("id") or ""),
            source_column=str(record.get("source_column") or ""),
            support=str(record.get("support") or ""),
            weight=str(record.get("weight") or ""),
        )
        for record in raw_measures
        if isinstance(record, dict)
    )
    if tuple(measure.measure_id for measure in measures) != tuple(multiplicity["family"]):
        raise ValueError("E1 primary measures disagree with the Holm family")
    exact_decomposition_fields = {
        "id": PAIR_DECOMPOSITION_DESIGN_ID,
        "comparison_years": [BASELINE_YEAR, COMPARISON_YEAR],
        "candidate_types": ["native", "stable"],
        "measure_ids": list(multiplicity["family"]),
        "components": [
            "within_common",
            "common_pair_reweighting",
            "common_support_mass",
            "exclusive_pair_contribution",
        ],
        "formula_id": DECOMPOSITION_FORMULA_ID,
        "identity_absolute_tolerance": IDENTITY_TOLERANCE,
        "denominator_scope": "native-plus-stable conditional choice mass for the selected measure",
        "forbidden_denominator": "full-market strict-value mass",
        "reporting": ["pooled integration scopes", "single-venue and cross-venue decomposition"],
    }
    if any(decomposition.get(key) != value for key, value in exact_decomposition_fields.items()):
        raise ValueError("E1 pair-decomposition registered schema has drifted")
    return claim, measures


def _validated_dates(values: pd.Series, *, label: str) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce").dt.normalize()
    if dates.isna().any():
        raise ValueError(f"E1 {label} contains an invalid calendar date")
    return dates


def release_calendar(bundle: Any) -> pd.DatetimeIndex:
    """Recover the observable endpoint-release calendar from all four tables."""

    dates: list[pd.Series] = []
    for name in ("choices", "choice_audit", "pair_support", "exclusions"):
        table = getattr(bundle, name)
        if "date" not in table.columns:
            raise ValueError(f"E1 endpoint release {name} table lacks date")
        if not table.empty:
            dates.append(_validated_dates(table["date"], label=f"{name} table"))
    if not dates:
        raise ValueError("E1 endpoint release has no observable calendar")
    return pd.DatetimeIndex(pd.concat(dates, ignore_index=True).drop_duplicates().sort_values())


def _validate_choice_measure(choices: pd.DataFrame, measure: MeasureContract) -> pd.DataFrame:
    required = [
        "src",
        "tgt",
        "date",
        "integration_scope",
        "candidate_type",
        measure.source_column,
    ]
    missing = sorted(set(required) - set(choices.columns))
    if missing:
        raise ValueError(f"E1 choices lack registered columns for {measure.measure_id}: {missing}")
    frame = choices[required].copy()
    frame["date"] = _validated_dates(frame["date"], label="choices")
    if not frame["candidate_type"].isin(("native", "stable")).all():
        raise ValueError("E1 choices contain a candidate outside native and stable")
    if not frame["integration_scope"].isin(INTEGRATION_SCOPES).all():
        raise ValueError("E1 choices contain an unregistered integration scope")
    mass = pd.to_numeric(frame[measure.source_column], errors="coerce")
    if not np.isfinite(mass.to_numpy(dtype=float)).all() or mass.lt(0).any():
        raise ValueError(f"E1 {measure.measure_id} mass must be finite and nonnegative")
    if measure.source_column.endswith("routes") or measure.source_column == "route_count":
        if not mass.eq(np.floor(mass)).all():
            raise ValueError(f"E1 {measure.measure_id} count mass must be integral")
    frame["mass"] = mass.astype(float)
    return frame


def _choice_cells(choices: pd.DataFrame, measure: MeasureContract) -> pd.DataFrame:
    frame = _validate_choice_measure(choices, measure)
    keys = ["src", "tgt", "date", "integration_scope"]
    cells = (
        frame.groupby([*keys, "candidate_type"], as_index=False, sort=True)["mass"]
        .sum()
        .pivot(index=keys, columns="candidate_type", values="mass")
        .fillna(0.0)
        .reset_index()
    )
    cells.columns.name = None
    for candidate in ("native", "stable"):
        if candidate not in cells:
            cells[candidate] = 0.0
    cells["denominator_mass"] = cells["native"] + cells["stable"]
    cells = cells[cells["denominator_mass"].gt(0)].copy()
    cells["stable_share"] = cells["stable"] / cells["denominator_mass"]
    cells["year"] = cells["date"].dt.year.astype(int)
    cells["month_day"] = cells["date"].dt.strftime("%m-%d")
    return cells.sort_values(keys, kind="stable").reset_index(drop=True)


def _pair_panel_from_cells(
    cells: pd.DataFrame,
    *,
    source_choice_rows: int,
    measure_id: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    endpoint = cells[cells["year"].isin((BASELINE_YEAR, COMPARISON_YEAR))].copy()
    common_keys = ["src", "tgt", "month_day", "integration_scope"]
    geometry = endpoint.groupby(common_keys, sort=True).agg(rows=("year", "size"), years=("year", "nunique"))
    common_index = geometry[geometry["rows"].eq(2) & geometry["years"].eq(2)].index
    indexed = endpoint.set_index(common_keys)
    common = indexed.loc[indexed.index.isin(common_index)].reset_index()
    if common.empty:
        raise ValueError(f"E1 {measure_id} has no common endpoint-year support")
    if common.duplicated([*common_keys, "year"]).any():
        raise ValueError(f"E1 {measure_id} has duplicate endpoint-year cells")
    observed_years = common.groupby(common_keys)["year"].agg(lambda values: tuple(sorted(values)))
    if not observed_years.map(
        lambda years: years == (BASELINE_YEAR, COMPARISON_YEAR)
    ).all():
        raise ValueError(f"E1 {measure_id} common support is not a two-year panel")
    common["comparison"] = common["year"].eq(COMPARISON_YEAR).astype(float)
    common["ordered_endpoint_pair"] = list(zip(common["src"], common["tgt"], strict=True))
    common["fixed_effect_cell"] = list(
        zip(
            common["src"],
            common["tgt"],
            common["month_day"],
            common["integration_scope"],
            strict=True,
        )
    )
    common = common.sort_values([*common_keys, "year"], kind="stable").reset_index(drop=True)
    support = {
        "source_choice_rows": source_choice_rows,
        "endpoint_positive_cell_rows": len(endpoint),
        "common_support_observations": len(common),
        "common_support_cells": len(common_index),
        "one_sided_cell_rows_excluded": len(endpoint) - len(common),
        "ordered_endpoint_pairs": common["ordered_endpoint_pair"].nunique(),
        "calendar_dates": common["date"].nunique(),
    }
    return common, support


def pair_panel_for_measure(choices: pd.DataFrame, measure: MeasureContract) -> tuple[pd.DataFrame, dict[str, int]]:
    """Build the exact two-endpoint-year common-support panel for one measure."""

    return _pair_panel_from_cells(
        _choice_cells(choices, measure),
        source_choice_rows=len(choices),
        measure_id=measure.measure_id,
    )


def fit_pair_panel_measure(
    choices: pd.DataFrame,
    measure: MeasureContract,
    *,
    endpoint_release_generation: str,
    precomputed_cells: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fit one registered saturated-cell WLS coefficient with pair/date CR1."""

    panel, support = _pair_panel_from_cells(
        _choice_cells(choices, measure) if precomputed_cells is None else precomputed_cells,
        source_choice_rows=len(choices),
        measure_id=measure.measure_id,
    )
    fixed_effect = panel["fixed_effect_cell"]
    weights = panel["denominator_mass"]
    absorbed = absorb_fixed_effects(
        panel[["stable_share", "comparison"]],
        fixed_effect,
        weights=weights,
    )
    fit = ols_clustered(
        absorbed["stable_share"],
        absorbed[["comparison"]],
        panel["ordered_endpoint_pair"],
        add_constant=False,
        absorbed_groups=(fixed_effect,),
        additional_clusters=(panel["date"],),
        weights=weights,
        min_observations=2,
        min_clusters=2,
    )
    if len(fit.beta) != 1 or not np.isfinite(fit.beta).all() or not np.isfinite(fit.covariance).all():
        raise ValueError(f"E1 {measure.measure_id} fitted coefficient or CR1 covariance is invalid")
    by_cell = panel.pivot(index="fixed_effect_cell", columns="year", values=["stable_share", "denominator_mass"])
    if set(by_cell["stable_share"].columns) != {BASELINE_YEAR, COMPARISON_YEAR}:
        raise ValueError(f"E1 {measure.measure_id} lost an endpoint year during fit verification")
    effective_weight = (
        by_cell["denominator_mass"][BASELINE_YEAR]
        * by_cell["denominator_mass"][COMPARISON_YEAR]
        / (
            by_cell["denominator_mass"][BASELINE_YEAR]
            + by_cell["denominator_mass"][COMPARISON_YEAR]
        )
    )
    differences = by_cell["stable_share"][COMPARISON_YEAR] - by_cell["stable_share"][BASELINE_YEAR]
    direct_coefficient = float(np.average(differences, weights=effective_weight))
    coefficient = float(fit.beta[0])
    if not math.isclose(coefficient, direct_coefficient, rel_tol=0, abs_tol=1e-12):
        raise ValueError(f"E1 {measure.measure_id} WLS coefficient fails its effective-cell-weight identity")
    standard_error = float(fit.standard_errors[0])
    p_value = float(fit.p_values[0])
    if not np.isfinite([standard_error, p_value]).all() or standard_error <= 0:
        raise ValueError(f"E1 {measure.measure_id} inference is not finite and positive")
    degrees_freedom = fit.n_clusters - 1
    critical = float(stats.t.ppf(0.975, degrees_freedom))
    result = {
        "spec_id": f"{PAIR_PANEL_DESIGN_ID}.{measure.measure_id}",
        "design_id": PAIR_PANEL_DESIGN_ID,
        "design_hash": EXPECTED_E1_DESIGN_HASH,
        "estimator_id": ESTIMATOR_ID,
        "measure_id": measure.measure_id,
        "source_column": measure.source_column,
        "baseline_year": BASELINE_YEAR,
        "comparison_year": COMPARISON_YEAR,
        "coefficient": coefficient,
        "coefficient_percentage_points": 100.0 * coefficient,
        "standard_error": standard_error,
        "standard_error_percentage_points": 100.0 * standard_error,
        "t_statistic": coefficient / standard_error,
        "p_value": p_value,
        "p_value_holm": float("nan"),
        "confidence_interval_lower": coefficient - critical * standard_error,
        "confidence_interval_upper": coefficient + critical * standard_error,
        "n_observations": fit.n_observations,
        "n_fixed_effect_cells": support["common_support_cells"],
        "n_ordered_endpoint_pairs": support["ordered_endpoint_pairs"],
        "n_calendar_dates": support["calendar_dates"],
        "pair_clusters": int(fit.cluster_counts[0]),
        "date_clusters": int(fit.cluster_counts[1]),
        "effective_cell_weight_sum": float(effective_weight.sum()),
        "endpoint_release_generation": endpoint_release_generation,
    }
    support_row = {
        "record_type": "pair_panel",
        "design_hash": EXPECTED_E1_DESIGN_HASH,
        "measure_id": measure.measure_id,
        "integration_scope": "saturated_single_and_cross",
        "source_column": measure.source_column,
        **support,
        "common_month_days": panel["month_day"].nunique(),
        "endpoint_release_generation": endpoint_release_generation,
    }
    return result, support_row


def _endpoint_common_month_days(calendar: pd.DatetimeIndex) -> set[str]:
    years = pd.Series(calendar.year, index=calendar)
    month_days = pd.Series(calendar.strftime("%m-%d"), index=calendar)
    baseline = set(month_days[years.eq(BASELINE_YEAR)])
    comparison = set(month_days[years.eq(COMPARISON_YEAR)])
    common = baseline & comparison
    if not common:
        raise ValueError("E1 decomposition has no common endpoint-year month-days")
    return common


def decompose_measure(
    choices: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    measure: MeasureContract,
    *,
    integration_scope: str,
    endpoint_release_generation: str,
    precomputed_cells: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute the registered exact four-term raw pooled-share decomposition."""

    if integration_scope not in REPORTING_SCOPES:
        raise ValueError(f"E1 decomposition has an unregistered scope: {integration_scope}")
    cells = (
        _choice_cells(choices, measure)
        if precomputed_cells is None
        else precomputed_cells.copy()
    )
    if integration_scope != "pooled":
        cells = cells[cells["integration_scope"].eq(integration_scope)].copy()
    common_days = _endpoint_common_month_days(calendar)
    cells = cells[
        cells["year"].isin((BASELINE_YEAR, COMPARISON_YEAR))
        & cells["month_day"].isin(common_days)
    ].copy()
    pair_year = cells.groupby(["src", "tgt", "year"], as_index=False, sort=True).agg(
        stable_mass=("stable", "sum"),
        total_mass=("denominator_mass", "sum"),
    )
    pair_year = pair_year[pair_year["total_mass"].gt(0)].copy()
    masses: dict[int, dict[tuple[str, str], tuple[float, float]]] = {}
    for year in (BASELINE_YEAR, COMPARISON_YEAR):
        selected = pair_year[pair_year["year"].eq(year)]
        masses[year] = {
            (str(row.src), str(row.tgt)): (float(row.total_mass), float(row.stable_mass))
            for row in selected.itertuples(index=False)
        }
        if not masses[year]:
            raise ValueError(f"E1 {measure.measure_id}/{integration_scope} decomposition lacks {year} mass")
    baseline_pairs = set(masses[BASELINE_YEAR])
    comparison_pairs = set(masses[COMPARISON_YEAR])
    common_pairs = sorted(baseline_pairs & comparison_pairs)
    exclusive = {
        BASELINE_YEAR: sorted(baseline_pairs - comparison_pairs),
        COMPARISON_YEAR: sorted(comparison_pairs - baseline_pairs),
    }
    totals = {
        year: sum(total for total, _stable in masses[year].values())
        for year in (BASELINE_YEAR, COMPARISON_YEAR)
    }
    stable_totals = {
        year: sum(stable for _total, stable in masses[year].values())
        for year in (BASELINE_YEAR, COMPARISON_YEAR)
    }
    common_mass = {
        year: sum(masses[year][pair][0] for pair in common_pairs)
        for year in (BASELINE_YEAR, COMPARISON_YEAR)
    }
    exclusive_mass = {year: totals[year] - common_mass[year] for year in totals}
    common_weight = {year: common_mass[year] / totals[year] for year in totals}
    exclusive_weight = {year: 1.0 - common_weight[year] for year in totals}
    common_share: dict[int, float] = {}
    pair_weight: dict[int, dict[tuple[str, str], float]] = {}
    pair_share: dict[int, dict[tuple[str, str], float]] = {}
    exclusive_share: dict[int, float] = {}
    for year in (BASELINE_YEAR, COMPARISON_YEAR):
        pair_weight[year] = {
            pair: masses[year][pair][0] / common_mass[year] if common_mass[year] > 0 else 0.0
            for pair in common_pairs
        }
        pair_share[year] = {
            pair: masses[year][pair][1] / masses[year][pair][0]
            for pair in common_pairs
        }
        common_share[year] = sum(pair_weight[year][pair] * pair_share[year][pair] for pair in common_pairs)
        exclusive_stable = sum(masses[year][pair][1] for pair in exclusive[year])
        exclusive_share[year] = exclusive_stable / exclusive_mass[year] if exclusive_mass[year] > 0 else 0.0
    midpoint_common_weight = 0.5 * (common_weight[BASELINE_YEAR] + common_weight[COMPARISON_YEAR])
    midpoint_exclusive_weight = 0.5 * (exclusive_weight[BASELINE_YEAR] + exclusive_weight[COMPARISON_YEAR])
    within_common = midpoint_common_weight * sum(
        0.5 * (pair_weight[BASELINE_YEAR][pair] + pair_weight[COMPARISON_YEAR][pair])
        * (pair_share[COMPARISON_YEAR][pair] - pair_share[BASELINE_YEAR][pair])
        for pair in common_pairs
    )
    common_pair_reweighting = midpoint_common_weight * sum(
        0.5 * (pair_share[BASELINE_YEAR][pair] + pair_share[COMPARISON_YEAR][pair])
        * (pair_weight[COMPARISON_YEAR][pair] - pair_weight[BASELINE_YEAR][pair])
        for pair in common_pairs
    )
    midpoint_common_share = 0.5 * (common_share[BASELINE_YEAR] + common_share[COMPARISON_YEAR])
    midpoint_exclusive_share = 0.5 * (exclusive_share[BASELINE_YEAR] + exclusive_share[COMPARISON_YEAR])
    common_support_mass = (midpoint_common_share - midpoint_exclusive_share) * (
        common_weight[COMPARISON_YEAR] - common_weight[BASELINE_YEAR]
    )
    exclusive_pair_contribution = midpoint_exclusive_weight * (
        exclusive_share[COMPARISON_YEAR] - exclusive_share[BASELINE_YEAR]
    )
    stable_share = {year: stable_totals[year] / totals[year] for year in totals}
    delta_total = stable_share[COMPARISON_YEAR] - stable_share[BASELINE_YEAR]
    reconstructed = within_common + common_pair_reweighting + common_support_mass + exclusive_pair_contribution
    closure_error = reconstructed - delta_total
    if not math.isclose(reconstructed, delta_total, rel_tol=0, abs_tol=IDENTITY_TOLERANCE):
        raise ValueError(
            f"E1 {measure.measure_id}/{integration_scope} decomposition fails exact closure: {closure_error}"
        )
    result = {
        "spec_id": f"{PAIR_DECOMPOSITION_DESIGN_ID}.{measure.measure_id}.{integration_scope}",
        "design_id": PAIR_DECOMPOSITION_DESIGN_ID,
        "design_hash": EXPECTED_E1_DESIGN_HASH,
        "formula_id": DECOMPOSITION_FORMULA_ID,
        "measure_id": measure.measure_id,
        "integration_scope": integration_scope,
        "baseline_year": BASELINE_YEAR,
        "comparison_year": COMPARISON_YEAR,
        "baseline_stable_share": stable_share[BASELINE_YEAR],
        "comparison_stable_share": stable_share[COMPARISON_YEAR],
        "delta_total": delta_total,
        "within_common": within_common,
        "common_pair_reweighting": common_pair_reweighting,
        "common_support_mass": common_support_mass,
        "exclusive_pair_contribution": exclusive_pair_contribution,
        "common_support_plus_exclusive_contribution": common_support_mass
        + exclusive_pair_contribution,
        "reconstructed_delta": reconstructed,
        "closure_error": closure_error,
        "identity_absolute_tolerance": IDENTITY_TOLERANCE,
        "baseline_total_mass": totals[BASELINE_YEAR],
        "comparison_total_mass": totals[COMPARISON_YEAR],
        "baseline_common_mass_share": common_weight[BASELINE_YEAR],
        "comparison_common_mass_share": common_weight[COMPARISON_YEAR],
        "endpoint_release_generation": endpoint_release_generation,
    }
    support = {
        "record_type": "pair_decomposition",
        "design_hash": EXPECTED_E1_DESIGN_HASH,
        "measure_id": measure.measure_id,
        "integration_scope": integration_scope,
        "source_column": measure.source_column,
        "common_month_days": len(common_days),
        "baseline_pair_count": len(baseline_pairs),
        "comparison_pair_count": len(comparison_pairs),
        "common_pair_count": len(common_pairs),
        "baseline_exclusive_pair_count": len(exclusive[BASELINE_YEAR]),
        "comparison_exclusive_pair_count": len(exclusive[COMPARISON_YEAR]),
        "baseline_total_mass": totals[BASELINE_YEAR],
        "comparison_total_mass": totals[COMPARISON_YEAR],
        "baseline_common_mass": common_mass[BASELINE_YEAR],
        "comparison_common_mass": common_mass[COMPARISON_YEAR],
        "baseline_exclusive_mass": exclusive_mass[BASELINE_YEAR],
        "comparison_exclusive_mass": exclusive_mass[COMPARISON_YEAR],
        "baseline_zero_exclusive_mass": exclusive_mass[BASELINE_YEAR] == 0,
        "comparison_zero_exclusive_mass": exclusive_mass[COMPARISON_YEAR] == 0,
        "endpoint_release_generation": endpoint_release_generation,
    }
    return result, support


def _ordered_frame(records: list[dict[str, Any]], columns: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(records)
    missing = sorted(set(columns) - set(frame.columns))
    extra = sorted(set(frame.columns) - set(columns))
    if missing or extra:
        raise ValueError(f"E1 output schema mismatch: missing={missing}; extra={extra}")
    return frame.loc[:, list(columns)]


def build_e1_outputs(
    choices: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    measures: tuple[MeasureContract, ...],
    *,
    endpoint_release_generation: str,
) -> E1Outputs:
    """Build, reconcile, and validate all three registered E1 artifacts."""

    if not endpoint_release_generation:
        raise ValueError("E1 outputs require the endpoint-release generation")
    pair_rows: list[dict[str, Any]] = []
    support_rows: list[dict[str, Any]] = []
    decomposition_rows: list[dict[str, Any]] = []
    for measure in measures:
        cells = _choice_cells(choices, measure)
        result, support = fit_pair_panel_measure(
            choices,
            measure,
            endpoint_release_generation=endpoint_release_generation,
            precomputed_cells=cells,
        )
        pair_rows.append(result)
        support_rows.append(support)
        for scope in REPORTING_SCOPES:
            decomposition, decomposition_support = decompose_measure(
                choices,
                calendar,
                measure,
                integration_scope=scope,
                endpoint_release_generation=endpoint_release_generation,
                precomputed_cells=cells,
            )
            decomposition_rows.append(decomposition)
            support_rows.append(decomposition_support)
    if len(pair_rows) != 3:
        raise ValueError("E1 pair panel must contain exactly three primary coefficients")
    raw_pvalues = np.array([row["p_value"] for row in pair_rows], dtype=float)
    adjusted = holm_adjusted_pvalues(raw_pvalues)
    if not np.isfinite(adjusted).all() or len(adjusted) != 3:
        raise ValueError("E1 Holm family must contain exactly three finite coefficients")
    for row, value in zip(pair_rows, adjusted, strict=True):
        row["p_value_holm"] = float(value)
    pair_panel = _ordered_frame(pair_rows, PAIR_PANEL_OUTPUT_COLUMNS)
    decomposition = _ordered_frame(decomposition_rows, DECOMPOSITION_OUTPUT_COLUMNS)
    support = pd.DataFrame.from_records(support_rows).reindex(columns=SUPPORT_OUTPUT_COLUMNS)
    validate_e1_outputs(E1Outputs(pair_panel, decomposition, support), measures=measures)
    return E1Outputs(pair_panel, decomposition, support)


def validate_e1_outputs(outputs: E1Outputs, *, measures: tuple[MeasureContract, ...]) -> None:
    """Reject incomplete, mis-keyed, nonfinite, or arithmetically stale E1 outputs."""

    pair = outputs.pair_panel
    decomposition = outputs.pair_decomposition
    support = outputs.pair_support
    if tuple(pair.columns) != PAIR_PANEL_OUTPUT_COLUMNS or tuple(decomposition.columns) != DECOMPOSITION_OUTPUT_COLUMNS or tuple(support.columns) != SUPPORT_OUTPUT_COLUMNS:
        raise ValueError("E1 output columns differ from the registered schema")
    measure_ids = [measure.measure_id for measure in measures]
    if pair["measure_id"].tolist() != measure_ids or pair["spec_id"].duplicated().any():
        raise ValueError("E1 pair-panel rows differ from the three registered measures")
    numeric_pair = pair[
        [
            "coefficient",
            "standard_error",
            "t_statistic",
            "p_value",
            "p_value_holm",
            "confidence_interval_lower",
            "confidence_interval_upper",
            "effective_cell_weight_sum",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric_pair.to_numpy(dtype=float)).all() or numeric_pair["standard_error"].le(0).any():
        raise ValueError("E1 pair-panel estimates or inference are invalid")
    if not pair["p_value_holm"].ge(pair["p_value"] - 1e-15).all():
        raise ValueError("E1 Holm p-values cannot be smaller than raw p-values")
    expected_holm = holm_adjusted_pvalues(pair["p_value"].to_numpy(dtype=float))
    if not np.allclose(
        pair["p_value_holm"].to_numpy(dtype=float),
        expected_holm,
        rtol=0,
        atol=1e-15,
    ):
        raise ValueError("E1 Holm p-values do not reproduce across exactly three coefficients")
    coefficient = pair["coefficient"].to_numpy(dtype=float)
    standard_error = pair["standard_error"].to_numpy(dtype=float)
    t_statistic = coefficient / standard_error
    degrees_freedom = np.minimum(
        pair["pair_clusters"].to_numpy(dtype=int),
        pair["date_clusters"].to_numpy(dtype=int),
    ) - 1
    expected_pvalue = 2 * stats.t.sf(np.abs(t_statistic), degrees_freedom)
    critical = stats.t.ppf(0.975, degrees_freedom)
    exact_inference = (
        np.allclose(pair["coefficient_percentage_points"], 100 * coefficient, rtol=0, atol=1e-12)
        and np.allclose(pair["standard_error_percentage_points"], 100 * standard_error, rtol=0, atol=1e-12)
        and np.allclose(pair["t_statistic"], t_statistic, rtol=0, atol=1e-12)
        and np.allclose(pair["p_value"], expected_pvalue, rtol=0, atol=1e-15)
        and np.allclose(pair["confidence_interval_lower"], coefficient - critical * standard_error, rtol=0, atol=1e-12)
        and np.allclose(pair["confidence_interval_upper"], coefficient + critical * standard_error, rtol=0, atol=1e-12)
    )
    if not exact_inference:
        raise ValueError("E1 pair-panel inference fields do not reproduce")
    expected_decomposition = {(measure, scope) for measure in measure_ids for scope in REPORTING_SCOPES}
    observed_decomposition = set(zip(decomposition["measure_id"], decomposition["integration_scope"], strict=True))
    if len(decomposition) != 9 or observed_decomposition != expected_decomposition or decomposition["spec_id"].duplicated().any():
        raise ValueError("E1 decomposition differs from its nine-row registered perimeter")
    components = decomposition[
        [
            "within_common",
            "common_pair_reweighting",
            "common_support_mass",
            "exclusive_pair_contribution",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    reconstructed = components.sum(axis=1)
    delta = pd.to_numeric(decomposition["delta_total"], errors="coerce")
    errors = reconstructed - delta
    if not np.isfinite(np.column_stack([components.to_numpy(), delta.to_numpy(), errors.to_numpy()])).all() or (errors.abs() > IDENTITY_TOLERANCE).any():
        raise ValueError("E1 decomposition does not close within 1e-12")
    recorded_error = pd.to_numeric(decomposition["closure_error"], errors="coerce")
    if not np.allclose(recorded_error, errors, rtol=0, atol=1e-15):
        raise ValueError("E1 decomposition closure evidence is stale")
    if not np.allclose(
        decomposition["common_support_plus_exclusive_contribution"],
        decomposition["common_support_mass"] + decomposition["exclusive_pair_contribution"],
        rtol=0,
        atol=1e-15,
    ):
        raise ValueError("E1 zero-exclusive normalization joint term is stale")
    expected_support = {(measure, "pair_panel", "saturated_single_and_cross") for measure in measure_ids}
    expected_support |= {(measure, "pair_decomposition", scope) for measure in measure_ids for scope in REPORTING_SCOPES}
    observed_support = set(zip(support["measure_id"], support["record_type"], support["integration_scope"], strict=True))
    if len(support) != 12 or observed_support != expected_support:
        raise ValueError("E1 support output differs from its exact twelve-row perimeter")
    measure_sources = {measure.measure_id: measure.source_column for measure in measures}
    if not support.apply(
        lambda row: row["source_column"] == measure_sources[row["measure_id"]],
        axis=1,
    ).all():
        raise ValueError("E1 support rows disagree with the registered measure columns")
    panel_support = support[support["record_type"].eq("pair_panel")].set_index("measure_id")
    pair_by_measure = pair.set_index("measure_id")
    for measure_id in measure_ids:
        evidence = panel_support.loc[measure_id]
        result = pair_by_measure.loc[measure_id]
        common_observations = int(evidence["common_support_observations"])
        common_cells = int(evidence["common_support_cells"])
        endpoint_rows = int(evidence["endpoint_positive_cell_rows"])
        excluded_rows = int(evidence["one_sided_cell_rows_excluded"])
        if (
            common_observations != 2 * common_cells
            or endpoint_rows != common_observations + excluded_rows
            or common_cells <= 0
            or int(evidence["ordered_endpoint_pairs"]) < 2
            or int(evidence["calendar_dates"]) < 2
            or int(result["n_observations"]) != common_observations
            or int(result["n_fixed_effect_cells"]) != common_cells
            or int(result["n_ordered_endpoint_pairs"]) != int(evidence["ordered_endpoint_pairs"])
            or int(result["n_calendar_dates"]) != int(evidence["calendar_dates"])
            or int(result["pair_clusters"]) != int(evidence["ordered_endpoint_pairs"])
            or int(result["date_clusters"]) != int(evidence["calendar_dates"])
        ):
            raise ValueError(f"E1 {measure_id} pair-panel support does not reconcile")
    decomposition_support = support[support["record_type"].eq("pair_decomposition")].set_index(
        ["measure_id", "integration_scope"]
    )
    decomposition_by_key = decomposition.set_index(["measure_id", "integration_scope"])
    for key in expected_decomposition:
        evidence = decomposition_support.loc[key]
        result = decomposition_by_key.loc[key]
        baseline_total = float(evidence["baseline_total_mass"])
        comparison_total = float(evidence["comparison_total_mass"])
        baseline_common = float(evidence["baseline_common_mass"])
        comparison_common = float(evidence["comparison_common_mass"])
        baseline_exclusive = float(evidence["baseline_exclusive_mass"])
        comparison_exclusive = float(evidence["comparison_exclusive_mass"])
        if (
            int(evidence["common_month_days"]) <= 0
            or baseline_total <= 0
            or comparison_total <= 0
            or int(evidence["baseline_pair_count"])
            != int(evidence["common_pair_count"])
            + int(evidence["baseline_exclusive_pair_count"])
            or int(evidence["comparison_pair_count"])
            != int(evidence["common_pair_count"])
            + int(evidence["comparison_exclusive_pair_count"])
            or not math.isclose(baseline_total, baseline_common + baseline_exclusive, rel_tol=0, abs_tol=1e-9)
            or not math.isclose(comparison_total, comparison_common + comparison_exclusive, rel_tol=0, abs_tol=1e-9)
            or bool(evidence["baseline_zero_exclusive_mass"]) != (baseline_exclusive == 0)
            or bool(evidence["comparison_zero_exclusive_mass"]) != (comparison_exclusive == 0)
            or not math.isclose(float(result["baseline_total_mass"]), baseline_total, rel_tol=0, abs_tol=1e-9)
            or not math.isclose(float(result["comparison_total_mass"]), comparison_total, rel_tol=0, abs_tol=1e-9)
            or not math.isclose(float(result["baseline_common_mass_share"]), baseline_common / baseline_total, rel_tol=0, abs_tol=1e-12)
            or not math.isclose(float(result["comparison_common_mass_share"]), comparison_common / comparison_total, rel_tol=0, abs_tol=1e-12)
        ):
            raise ValueError(f"E1 {key} decomposition support does not reconcile")
    if not pair["design_hash"].eq(EXPECTED_E1_DESIGN_HASH).all() or not decomposition["design_hash"].eq(EXPECTED_E1_DESIGN_HASH).all() or not support["design_hash"].eq(EXPECTED_E1_DESIGN_HASH).all():
        raise ValueError("E1 output design hash has drifted")
    generations = pd.concat(
        [
            pair["endpoint_release_generation"],
            decomposition["endpoint_release_generation"],
            support["endpoint_release_generation"],
        ],
        ignore_index=True,
    )
    if generations.nunique() != 1 or not str(generations.iloc[0]):
        raise ValueError("E1 outputs do not bind one endpoint-release generation")

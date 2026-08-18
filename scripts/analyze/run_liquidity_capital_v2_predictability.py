#!/usr/bin/env python3
"""Estimate V2 deposited-capital and vehicle-use predictability in both directions.

This runner consumes only the independently released V2 candidate-day and
exact-horizon panels. It never opens, fills, or conditions execution on a V3
flow artifact. The estimates are predictive associations, not causal feedback.

The registered runner reads exactly two processed panels and writes one result
and one support file. Presentation values are rendered downstream by the
tabulation stage. The estimates are predictive associations, not causal feedback.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, holm_adjusted_pvalues, ols_clustered
from ddvc.liquidity_predictability import (
    HORIZONS,
    V2_CANDIDATE_DAY_COLUMNS,
    V3_LAUNCH_DATE,
    validate_v2_candidate_day_panel,
    validate_v2_exact_horizon_panel,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output


CANDIDATE_DAY_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_candidate_day.parquet"
EXACT_HORIZON_INPUT = REPO_ROOT / "data/processed/liquidity_capital_v2_exact_horizons.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/liquidity_capital_v2_predictability.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/liquidity_capital_v2_support.jsonl"
PRIMARY_HORIZONS = (1, 7, 30)
DK_LAG = 30
ROUTE_MEASURES = {
    "intermediary_episode_share": "future_intermediary_episode_share_change",
    "vehicle_excess_use_count_ratio": "future_vehicle_excess_use_count_ratio_change",
}
CAPITAL_MEASURES = {
    "log_deposited_capital": "log1p_deposited_capital_usd",
    "five_candidate_capital_share": "five_candidate_capital_share",
}


def attach_spec_ids(
    frame: pd.DataFrame, *, prefix: str, columns: tuple[str, ...]
) -> pd.DataFrame:
    """Attach readable row labels used by downstream selectors."""

    output = frame.copy()
    labels = output.loc[:, list(columns)].astype(str).agg("-".join, axis=1)
    output["spec_id"] = prefix + ":" + labels.str.replace(r"\s+", "_", regex=True)
    return output




def _assert_released_origin_identity(
    candidate_day: pd.DataFrame, exact_horizons: pd.DataFrame
) -> None:
    keys = ["origin_date", "candidate_address"]
    expected = (
        candidate_day.sort_values(keys)
        .loc[:, list(V2_CANDIDATE_DAY_COLUMNS)]
        .reset_index(drop=True)
    )
    actual = (
        exact_horizons.sort_values([*keys, "horizon_days"])
        .drop_duplicates(keys)
        .loc[:, list(V2_CANDIDATE_DAY_COLUMNS)]
        .sort_values(keys)
        .reset_index(drop=True)
    )
    expected["origin_date"] = pd.to_datetime(expected["origin_date"])
    actual["origin_date"] = pd.to_datetime(actual["origin_date"])
    try:
        pd.testing.assert_frame_equal(
            actual,
            expected,
            check_dtype=False,
            check_categorical=False,
            check_exact=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as error:
        raise ValueError(
            "released V2 exact-horizon origins do not reproduce the released "
            "V2 candidate-day panel"
        ) from error






def _perimeter(panel: pd.DataFrame, name: str) -> pd.DataFrame:
    data = panel.copy()
    if name == "pre_v3_launch":
        data = data[data["target_date"] < V3_LAUNCH_DATE]
    elif name == "post_v3_launch":
        data = data[data["origin_date"] >= V3_LAUNCH_DATE]
    elif name != "full_v2_calendar":
        raise ValueError(f"unknown V2 calendar perimeter: {name}")
    return data


def _calendar_score_hac_covariance(
    x: np.ndarray,
    residual: np.ndarray,
    dates: pd.Series,
    *,
    lag_days: int,
    scale: float,
) -> np.ndarray:
    """Aggregate scores by date and preserve zero-score dates between observations."""

    design = np.asarray(x, dtype=float)
    errors = np.asarray(residual, dtype=float).reshape(-1)
    if design.ndim == 1:
        design = design[:, None]
    parsed_dates = pd.to_datetime(dates, errors="coerce").dt.normalize()
    if (
        lag_days < 0
        or len(design) != len(errors)
        or len(design) != len(parsed_dates)
        or parsed_dates.isna().any()
    ):
        raise ValueError("calendar score HAC inputs are invalid")
    scores = pd.DataFrame(design * errors[:, None])
    scores.insert(0, "origin_date", parsed_dates.to_numpy())
    daily = scores.groupby("origin_date", sort=True).sum()
    calendar = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(calendar, fill_value=0.0)
    score_array = daily.to_numpy(float)
    meat = score_array.T @ score_array
    for offset in range(1, min(lag_days, len(score_array) - 1) + 1):
        weight = 1.0 - offset / (lag_days + 1.0)
        autocovariance = score_array[offset:].T @ score_array[:-offset]
        meat += weight * (autocovariance + autocovariance.T)
    xtx_inverse = np.linalg.pinv(design.T @ design)
    return scale * xtx_inverse @ meat @ xtx_inverse


def _fit_fe(
    sample: pd.DataFrame,
    outcome: str,
    predictor: str,
    *,
    expected_candidates: int = 5,
    with_two_way: bool = True,
) -> tuple[object, object | None]:
    """Fit one absorbed specification under the claim's own covariance contract.

    `expected_candidates` exists for the leave-one-candidate influence refits and
    for nothing else: the headline perimeter is the fixed five, and a fit that
    silently lost a candidate must still fail. The two-way candidate sensitivity
    is skipped when a candidate is dropped, because four clusters is below the
    five the registered sensitivity already declares as its own limitation.
    """

    required = [outcome, predictor, "candidate_address", "origin_date"]
    data = sample[required].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if (
        len(data) < 100
        or data["origin_date"].nunique() < 20
        or data["candidate_address"].nunique() != expected_candidates
    ):
        raise ValueError("V2 predictability fit has insufficient candidate-date support")
    residual = absorb_fixed_effects(
        data[[outcome, predictor]], data["candidate_address"], data["origin_date"]
    )
    primary_base = ols_clustered(
        residual[outcome], residual[[predictor]], data["origin_date"],
        add_constant=False,
        absorbed_groups=(data["candidate_address"], data["origin_date"]),
        min_observations=100,
        min_clusters=20,
    )
    x = residual[[predictor]].to_numpy(float)
    y = residual[outcome].to_numpy(float)
    fitted_residual = y - x @ primary_base.beta
    n = primary_base.n_observations
    denominator_dof = n - 1 - primary_base.absorbed_degrees_of_freedom
    if denominator_dof <= 0:
        raise ValueError("V2 predictability fit has no residual degrees of freedom")
    observed_dates = data["origin_date"].nunique()
    scale = (observed_dates / (observed_dates - 1)) * ((n - 1) / denominator_dof)
    primary = replace(
        primary_base,
        covariance=_calendar_score_hac_covariance(
            x,
            fitted_residual,
            data["origin_date"],
            lag_days=DK_LAG,
            scale=scale,
        ),
    )
    two_way = (
        ols_clustered(
            residual[outcome], residual[[predictor]], data["candidate_address"],
            add_constant=False,
            absorbed_groups=(data["candidate_address"], data["origin_date"]),
            min_observations=100,
            min_clusters=5,
            additional_clusters=(data["origin_date"],),
        )
        if with_two_way
        else None
    )
    if not np.isfinite(primary.beta[0]) or not np.isfinite(primary.standard_errors[0]):
        raise ValueError("V2 predictability primary covariance is not estimable")
    return primary, two_way


def _month_block_bootstrap(
    sample: pd.DataFrame,
    outcome: str,
    predictor: str,
    *,
    repetitions: int,
    seed: int,
) -> tuple[float, float, int]:
    """Resample whole calendar months and re-absorb both fixed effects."""

    data = sample[[outcome, predictor, "candidate_address", "origin_date"]].dropna().copy()
    data["month"] = data["origin_date"].dt.to_period("M").astype(str)
    months = sorted(data["month"].unique())
    if len(months) < 12:
        return np.nan, np.nan, 0
    rng = np.random.default_rng(seed)
    estimates: list[float] = []
    for repetition in range(repetitions):
        pieces = []
        for draw, month in enumerate(rng.choice(months, size=len(months), replace=True)):
            piece = data[data["month"].eq(month)].copy()
            piece["bootstrap_date"] = str(draw) + ":" + piece["origin_date"].astype(str)
            pieces.append(piece)
        boot = pd.concat(pieces, ignore_index=True)
        residual = absorb_fixed_effects(
            boot[[outcome, predictor]], boot["candidate_address"], boot["bootstrap_date"]
        ).dropna()
        x = residual[predictor].to_numpy(float)
        denominator = float(x @ x)
        if denominator > 0:
            estimates.append(float(x @ residual[outcome].to_numpy(float) / denominator))
    if len(estimates) < max(20, repetitions // 2):
        return np.nan, np.nan, len(estimates)
    values = np.asarray(estimates)
    p_value = min(1.0, 2.0 * min(float((values <= 0).mean()), float((values >= 0).mean())))
    return float(values.std(ddof=1)), p_value, len(values)


def _attach_full_calendar_decision(estimates: pd.DataFrame) -> pd.DataFrame:
    """Adjudicate exact reciprocal pairs on the full calendar and nowhere else."""

    output = estimates.copy()
    output["adjudication_primary"] = (
        output["perimeter"].eq("full_v2_calendar")
        & output["primary_horizon"]
    )
    output["analysis_role"] = np.select(
        [
            output["perimeter"].eq("full_v2_calendar")
            & output["primary_horizon"],
            output["perimeter"].eq("full_v2_calendar"),
        ],
        ["primary_adjudication", "long_horizon_sensitivity"],
        default="calendar_heterogeneity_only",
    )
    output["reciprocal_pair_pass"] = pd.Series(pd.NA, index=output.index, dtype="boolean")
    output["reciprocal_positive_significant_horizons"] = pd.NA
    output["alternative_sign_concordant"] = pd.Series(
        pd.NA, index=output.index, dtype="boolean"
    )
    output["claim_decision_pass"] = pd.Series(pd.NA, index=output.index, dtype="boolean")
    full = output[output["perimeter"].eq("full_v2_calendar")]
    pair_records: dict[str, tuple[bool, str]] = {}
    for pair_id, pair in full.groupby("measure_pair_id", sort=False):
        qualifying: list[int] = []
        for horizon in PRIMARY_HORIZONS:
            rows = pair[pair["horizon_days"].eq(horizon)].set_index("direction")
            if set(rows.index) != {"route_to_capital", "capital_to_route"}:
                raise ValueError(f"reciprocal V2 pair is incomplete: {pair_id}, {horizon}")
            if (
                rows["coefficient"].gt(0).all()
                and rows["p_value_holm"].lt(0.05).all()
            ):
                qualifying.append(horizon)
        long_rows = pair[pair["horizon_days"].eq(120)]
        if set(long_rows["direction"]) != {"route_to_capital", "capital_to_route"}:
            raise ValueError(f"reciprocal V2 long-horizon pair is incomplete: {pair_id}")
        significant_reversal = (
            long_rows["coefficient"].lt(0) & long_rows["p_value"].lt(0.05)
        ).any()
        pair_records[pair_id] = (
            len(qualifying) >= 2 and not bool(significant_reversal),
            "|".join(str(value) for value in qualifying) or "none",
        )

    route_concordance: dict[str, bool] = {}
    for route_measure, rows in full[full["primary_horizon"]].groupby(
        "route_measure", sort=False
    ):
        medians = rows.groupby(["capital_measure", "direction"])["coefficient"].median()
        significant_negative = (
            rows["coefficient"].lt(0) & rows["p_value_holm"].lt(0.05)
        ).any()
        route_concordance[route_measure] = bool(
            len(medians) == len(CAPITAL_MEASURES) * 2
            and medians.gt(0).all()
            and not significant_negative
        )
    claim_pass = any(
        pair_pass
        and route_concordance.get(
            full.loc[full["measure_pair_id"].eq(pair_id), "route_measure"].iloc[0],
            False,
        )
        for pair_id, (pair_pass, _horizons) in pair_records.items()
    )
    for pair_id, (pair_pass, horizons) in pair_records.items():
        pair_mask = output["perimeter"].eq("full_v2_calendar") & output[
            "measure_pair_id"
        ].eq(pair_id)
        route_measure = output.loc[pair_mask, "route_measure"].iloc[0]
        output.loc[pair_mask, "reciprocal_pair_pass"] = pair_pass
        output.loc[
            pair_mask, "reciprocal_positive_significant_horizons"
        ] = horizons
        output.loc[pair_mask, "alternative_sign_concordant"] = route_concordance[
            route_measure
        ]
        output.loc[pair_mask, "claim_decision_pass"] = claim_pass
    output["decision_rule"] = (
        "full_calendar_only; exact route/capital measure pair positive with Holm q<0.05 "
        "in both directions at the same at least two of 1/7/30 days; no significantly "
        "negative 120-day reversal; positive primary-horizon median and no significant "
        "negative coefficient under both capital measurement alternatives"
    )
    return output


def estimate_v2_predictability(
    panel: pd.DataFrame, *, bootstrap_repetitions: int = 199, seed: int = 57291
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit every locked V2 direction, measure, horizon, and calendar perimeter."""

    validate_v2_exact_horizon_panel(panel, HORIZONS)
    panel = panel.copy()
    panel["origin_date"] = pd.to_datetime(panel["origin_date"])
    panel["target_date"] = pd.to_datetime(panel["target_date"])
    rows: list[dict[str, object]] = []
    support: list[dict[str, object]] = []
    perimeters = ("full_v2_calendar", "pre_v3_launch", "post_v3_launch")
    for perimeter in perimeters:
        scoped = _perimeter(panel, perimeter)
        for horizon in HORIZONS:
            horizon_data = scoped[scoped["horizon_days"].eq(horizon)]
            for route_measure, future_route in ROUTE_MEASURES.items():
                for capital_label, capital_suffix in CAPITAL_MEASURES.items():
                    capital_level = f"v2_{capital_suffix}"
                    future_capital = f"future_v2_{capital_suffix}_change"
                    for direction, outcome, predictor in (
                        ("route_to_capital", future_capital, route_measure),
                        ("capital_to_route", future_route, capital_level),
                    ):
                        fit_sample = horizon_data[[outcome, predictor, "candidate_address", "origin_date"]].dropna()
                        support.append({
                            "measurement_family": "v2_family_deposited_capital_stock",
                            "perimeter": perimeter,
                            "horizon_days": horizon,
                            "direction": direction,
                            "route_measure": route_measure,
                            "capital_measure": capital_label,
                            "measure_pair_id": f"{route_measure}__{capital_label}",
                            "observations": int(len(fit_sample)),
                            "origin_dates": int(fit_sample["origin_date"].nunique()),
                            "candidates": int(fit_sample["candidate_address"].nunique()),
                            "origin_start": fit_sample["origin_date"].min(),
                            "origin_end": fit_sample["origin_date"].max(),
                        })
                        primary, two_way = _fit_fe(horizon_data, outcome, predictor)
                        boot_se, boot_p, boot_n = _month_block_bootstrap(
                            horizon_data, outcome, predictor,
                            repetitions=bootstrap_repetitions,
                            seed=seed + horizon + len(rows),
                        )
                        se = float(primary.standard_errors[0])
                        rows.append({
                            "claim_id": "liquidity_capital_v2_predictability",
                            "measurement_family": "v2_family_deposited_capital_stock",
                            "perimeter": perimeter,
                            "horizon_days": horizon,
                            "primary_horizon": horizon in PRIMARY_HORIZONS,
                            "direction": direction,
                            "route_measure": route_measure,
                            "capital_measure": capital_label,
                            "measure_pair_id": f"{route_measure}__{capital_label}",
                            "outcome": outcome,
                            "predictor": predictor,
                            "coefficient": float(primary.beta[0]),
                            "standard_error": se,
                            "t_statistic": float(primary.t_statistics[0]),
                            "p_value": float(primary.p_values[0]),
                            "confidence_interval_lower": float(primary.beta[0] - 1.96 * se),
                            "confidence_interval_upper": float(primary.beta[0] + 1.96 * se),
                            "two_way_candidate_date_standard_error": float(two_way.standard_errors[0]),
                            "two_way_candidate_date_p_value": float(two_way.p_values[0]),
                            "month_block_bootstrap_standard_error": boot_se,
                            "month_block_bootstrap_p_value": boot_p,
                            "month_block_bootstrap_successful_refits": boot_n,
                            "observations": primary.n_observations,
                            "origin_date_clusters": primary.n_clusters,
                            "candidate_clusters": int(fit_sample["candidate_address"].nunique()),
                            "calendar_span_days": (
                                int(
                                    (fit_sample["origin_date"].max() - fit_sample["origin_date"].min()).days
                                )
                                + 1
                            ),
                            "zero_score_calendar_days": (
                                int(
                                    (fit_sample["origin_date"].max() - fit_sample["origin_date"].min()).days
                                )
                                + 1
                                - int(fit_sample["origin_date"].nunique())
                            ),
                            "fixed_effects": "candidate_and_origin_date",
                            "primary_covariance": "candidate_date_score_hac_bartlett_30_calendar_days_zero_score_gaps_preserved",
                            "two_way_cluster_limitation": "five_candidate_clusters",
                            "interpretation": "temporally_ordered_predictability_not_causal_feedback",
                        })
    estimates = pd.DataFrame(rows)
    estimates["p_value_holm"] = np.nan
    primary = estimates["primary_horizon"]
    family = ["perimeter", "direction"]
    for _key, indices in estimates[primary].groupby(family, sort=False).groups.items():
        estimates.loc[indices, "p_value_holm"] = holm_adjusted_pvalues(estimates.loc[indices, "p_value"])
    estimates = _attach_full_calendar_decision(estimates)
    estimates = attach_spec_ids(
        estimates,
        prefix="liquidity-capital-v2",
        columns=("perimeter", "direction", "route_measure", "capital_measure", "horizon_days"),
    )
    return estimates, pd.DataFrame(support).drop_duplicates().reset_index(drop=True)




def run(*, bootstrap_repetitions: int = 199) -> tuple[Path, Path]:
    candidate_day = pd.read_parquet(CANDIDATE_DAY_INPUT)
    panel = pd.read_parquet(EXACT_HORIZON_INPUT)
    validate_v2_candidate_day_panel(candidate_day)
    validate_v2_exact_horizon_panel(panel)
    _assert_released_origin_identity(candidate_day, panel)
    estimates, support = estimate_v2_predictability(
        panel, bootstrap_repetitions=bootstrap_repetitions
    )

    for frame, path in ((estimates, RESULT_OUTPUT), (support, SUPPORT_OUTPUT)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_output(path) as temporary:
            frame.to_json(
                temporary,
                orient="records",
                lines=True,
                date_format="iso",
            )
    return RESULT_OUTPUT, SUPPORT_OUTPUT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-repetitions", type=int, default=199)
    args = parser.parse_args()
    if args.bootstrap_repetitions < 20:
        raise ValueError("month-block bootstrap requires at least 20 repetitions")
    try:
        paths = run(bootstrap_repetitions=args.bootstrap_repetitions)
    except (RuntimeError, ValueError, FileNotFoundError) as error:
        print(f"INPUT BLOCKED: {error}")
        return 2
    print("wrote " + ", ".join(str(path) for path in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

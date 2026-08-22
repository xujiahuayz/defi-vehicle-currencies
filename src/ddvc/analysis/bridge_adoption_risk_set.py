"""At-risk weekly stable-bridge adoption estimates.

The unit is an ordered endpoint pair and calendar week.  A pair enters the
risk set only after recent WETH-mediated activity and leaves at its first
stablecoin-mediated route.  Stablecoin weak-leg capital can be zero; no
capital threshold or eventual-adoption condition defines the sample.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered


MODEL_CONTROLS = (
    "log_weth_depth",
    "log_prior_native_routes",
    "prior_native_active_days_10",
)


def prepare_adoption_risk_panel(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate a strictly preweek-capital risk panel and add estimands."""

    required = {
        "pair_id",
        "src",
        "tgt",
        "week_start",
        "first_native_date",
        "first_stable_date",
        "prior_native_routes",
        "prior_native_active_days",
        "stable_weak_leg_usd",
        "weth_weak_leg_usd",
        "lead_stable_weak_leg_usd",
        "lead_weth_weak_leg_usd",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"bridge-adoption risk panel lacks columns: {missing}")

    data = frame.copy()
    for column in ("week_start", "first_native_date"):
        data[column] = pd.to_datetime(data[column], errors="raise").dt.normalize()
    data["first_stable_date"] = pd.to_datetime(
        data["first_stable_date"], errors="coerce"
    ).dt.normalize()
    numeric = [
        "prior_native_routes",
        "prior_native_active_days",
        "stable_weak_leg_usd",
        "weth_weak_leg_usd",
        "lead_stable_weak_leg_usd",
        "lead_weth_weak_leg_usd",
    ]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="raise")
    if data.duplicated(["pair_id", "week_start"]).any():
        raise ValueError("bridge-adoption risk panel has duplicate pair-weeks")
    if not data["week_start"].dt.dayofweek.eq(0).all():
        raise ValueError("bridge-adoption risk weeks must begin on Monday")
    if data[["prior_native_routes", "prior_native_active_days"]].le(0).any().any():
        raise ValueError("every risk week must have strictly prior WETH activity")
    if data[["stable_weak_leg_usd", "weth_weak_leg_usd"]].lt(0).any().any():
        raise ValueError("current weak-leg capital cannot be negative")
    if not data["weth_weak_leg_usd"].gt(0).all():
        raise ValueError("current WETH weak-leg capital must be positive")
    later_than_event = data["first_stable_date"].notna() & data["week_start"].gt(
        data["first_stable_date"].dt.to_period("W-SUN").dt.start_time
    )
    if later_than_event.any():
        raise ValueError("risk observations cannot follow first stablecoin use")
    invalid_order = data["first_stable_date"].notna() & data[
        "first_stable_date"
    ].le(data["first_native_date"])
    if invalid_order.any():
        raise ValueError("stablecoin use must follow the first WETH route")

    event_week = data["first_stable_date"].dt.to_period("W-SUN").dt.start_time
    data["adopted_this_week"] = (
        data["first_stable_date"].notna() & data["week_start"].eq(event_week)
    ).astype(float)
    if data.groupby("pair_id")["adopted_this_week"].sum().gt(1).any():
        raise ValueError("a pair can adopt at most once")

    total_depth = data["stable_weak_leg_usd"] + data["weth_weak_leg_usd"]
    data["stable_depth_share"] = data["stable_weak_leg_usd"] / total_depth
    data["stable_depth_share_10pp"] = data["stable_depth_share"] / 0.10
    data["positive_stable_support"] = data["stable_weak_leg_usd"].gt(0).astype(float)
    data["log_depth_advantage"] = np.log1p(data["stable_weak_leg_usd"]) - np.log1p(
        data["weth_weak_leg_usd"]
    )
    data["log_weth_depth"] = np.log1p(data["weth_weak_leg_usd"])
    data["log_prior_native_routes"] = np.log1p(data["prior_native_routes"])
    data["prior_native_active_days_10"] = data["prior_native_active_days"] / 10.0

    lead_total = (
        data["lead_stable_weak_leg_usd"] + data["lead_weth_weak_leg_usd"]
    )
    data["lead_stable_depth_share_10pp"] = np.where(
        data["lead_weth_weak_leg_usd"].gt(0) & lead_total.gt(0),
        data["lead_stable_weak_leg_usd"] / lead_total / 0.10,
        np.nan,
    )

    data["pair_age_weeks"] = (
        (data["week_start"] - data["first_native_date"]).dt.days.clip(lower=0) // 7
    ).astype(int)
    data["age_bin"] = pd.cut(
        data["pair_age_weeks"],
        bins=[-1, 4, 12, 26, 52, 104, np.inf],
        labels=["00_04", "05_12", "13_26", "27_52", "53_104", "105_plus"],
    ).astype(str)
    data = data.sort_values(["pair_id", "week_start"], kind="stable").reset_index(
        drop=True
    )
    if data.empty:
        raise ValueError("bridge-adoption risk panel is empty")
    return data


def adoption_support_rows(
    panel: pd.DataFrame,
    *,
    min_prior_native_routes: int,
    min_prior_native_active_days: int,
) -> pd.DataFrame:
    """Describe risk-set coverage, including pairs that never adopt."""

    pair_information = panel.groupby("pair_id", as_index=False).agg(
        adopted=("adopted_this_week", "max"),
        first_stable_date=("first_stable_date", "first"),
    )
    pair_week_counts = panel.groupby("pair_id").size()
    zero_depth = panel["stable_weak_leg_usd"].eq(0)
    positive_depth = panel["stable_weak_leg_usd"].gt(0)
    adoption = panel["adopted_this_week"].eq(1)
    rows = [
        {
            "record_type": "bridge_adoption_risk_support",
            "model_id": "primary_risk_set",
            "pair_weeks": int(len(panel)),
            "pairs": int(panel["pair_id"].nunique()),
            "adopting_pairs": int(pair_information["adopted"].sum()),
            "never_adopting_pairs": int(
                pair_information["first_stable_date"].isna().sum()
            ),
            "censored_before_observed_adoption_pairs": int(
                (
                    pair_information["first_stable_date"].notna()
                    & pair_information["adopted"].eq(0)
                ).sum()
            ),
            "pairs_with_multiple_weeks": int(pair_week_counts.ge(2).sum()),
            "zero_stable_depth_pair_weeks": int(zero_depth.sum()),
            "positive_stable_depth_pair_weeks": int(positive_depth.sum()),
            "adoption_rate_per_pair_week": float(panel["adopted_this_week"].mean()),
            "adoptions_with_zero_stable_depth": int((adoption & zero_depth).sum()),
            "adoptions_with_positive_stable_depth": int(
                (adoption & positive_depth).sum()
            ),
            "zero_stable_depth_adoption_rate": float(
                panel.loc[zero_depth, "adopted_this_week"].mean()
            ),
            "positive_stable_depth_adoption_rate": float(
                panel.loc[positive_depth, "adopted_this_week"].mean()
            ),
            "first_week": panel["week_start"].min().date().isoformat(),
            "last_week": panel["week_start"].max().date().isoformat(),
            "min_prior_native_routes_28d": int(min_prior_native_routes),
            "min_prior_native_active_days_28d": int(min_prior_native_active_days),
            "capital_timing": "prior-calendar state at the start of the week",
            "outcome": "first observed DAI, USDC, or USDT intermediary route during the week",
            "endpoint_scope": "neither endpoint is WETH, DAI, USDC, or USDT",
            "weight": "equal pair-week",
        }
    ]
    return pd.DataFrame(rows)


def _full_rank_columns(frame: pd.DataFrame, preferred: Iterable[str]) -> list[str]:
    """Retain preferred columns in order while dropping absorbed collinearity."""

    columns: list[str] = []
    design = np.empty((len(frame), 0), dtype=float)
    rank = 0
    for column in preferred:
        candidate = np.column_stack([design, frame[column].to_numpy(dtype=float)])
        candidate_rank = int(np.linalg.matrix_rank(candidate))
        if candidate_rank > rank:
            columns.append(column)
            design = candidate
            rank = candidate_rank
    return columns


def _fit_within_pair_week_model(
    panel: pd.DataFrame,
    *,
    model_id: str,
    focal_predictors: tuple[str, ...],
    min_observations: int,
    min_clusters: int,
    positive_depth_only: bool = False,
) -> list[dict[str, object]]:
    """Fit one equal-pair-week LPM with pair and calendar-week effects."""

    age_controls = pd.get_dummies(
        panel["age_bin"], prefix="age", drop_first=True, dtype=float
    )
    data = pd.concat([panel, age_controls], axis=1)
    if positive_depth_only:
        data = data[data["stable_weak_leg_usd"].gt(0)].copy()
    candidate_columns = [*focal_predictors, *MODEL_CONTROLS, *age_controls.columns]
    data = data.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["adopted_this_week", "pair_id", "week_start", *candidate_columns]
    ).copy()
    multiweek = data.groupby("pair_id")["week_start"].transform("size").ge(2)
    data = data[multiweek].copy()
    if data.empty:
        raise ValueError(f"{model_id} has no multiweek risk-set observations")
    values = data[["adopted_this_week", *candidate_columns]]
    residual = absorb_fixed_effects(values, data["pair_id"], data["week_start"])
    regressors = _full_rank_columns(residual, candidate_columns)
    missing_focal = sorted(set(focal_predictors) - set(regressors))
    if missing_focal:
        raise ValueError(f"{model_id} loses focal predictors after absorption: {missing_focal}")
    fit = ols_clustered(
        residual["adopted_this_week"],
        residual[regressors],
        data["pair_id"],
        add_constant=False,
        absorbed_groups=(data["pair_id"], data["week_start"]),
        additional_clusters=(data["week_start"],),
        min_observations=min_observations,
        min_clusters=min_clusters,
    )
    rows: list[dict[str, object]] = []
    for predictor in focal_predictors:
        position = regressors.index(predictor)
        coefficient = float(fit.beta[position])
        standard_error = float(fit.standard_errors[position])
        scale = 100.0
        if predictor in {
            "stable_depth_share_10pp",
            "lead_stable_depth_share_10pp",
        }:
            magnitude = "percentage points of weekly adoption per 10 pp depth share"
            coefficient_pp_per_10x = np.nan
            standard_error_pp_per_10x = np.nan
        elif predictor == "positive_stable_support":
            magnitude = "percentage points of weekly adoption for any positive stable depth"
            coefficient_pp_per_10x = np.nan
            standard_error_pp_per_10x = np.nan
        else:
            magnitude = "percentage points of weekly adoption per log-depth advantage"
            coefficient_pp_per_10x = scale * coefficient * np.log(10.0)
            standard_error_pp_per_10x = scale * standard_error * np.log(10.0)
        rows.append(
            {
                "record_type": "bridge_adoption_risk_model",
                "model_id": model_id,
                "predictor": predictor,
                "coefficient": coefficient,
                "standard_error": standard_error,
                "p_value": float(fit.p_values[position]),
                "coefficient_pp": scale * coefficient,
                "standard_error_pp": scale * standard_error,
                "coefficient_pp_per_10x": float(coefficient_pp_per_10x),
                "standard_error_pp_per_10x": float(
                    standard_error_pp_per_10x
                ),
                "magnitude": magnitude,
                "pair_weeks": int(fit.n_observations),
                "pairs": int(data["pair_id"].nunique()),
                "adoptions": int(data["adopted_this_week"].sum()),
                "risk_set_adoption_rate": float(data["adopted_this_week"].mean()),
                "pair_clusters": int(fit.cluster_counts[0]),
                "calendar_week_clusters": int(fit.cluster_counts[1]),
                "fixed_effects": "ordered endpoint pair and calendar week",
                "baseline_hazard": "pair age bins",
                "controls": "log WETH weak-leg depth, prior-28-day WETH routes and active days",
                "positive_depth_only": bool(positive_depth_only),
                "capital_margin": (
                    "extensive"
                    if predictor == "positive_stable_support"
                    else "intensive among positive-support pair-weeks"
                    if positive_depth_only
                    else "relative share or depth"
                ),
                "weight": "equal pair-week",
            }
        )
    return rows


def estimate_adoption_models(
    panel: pd.DataFrame,
    *,
    min_observations: int = 200,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate support, conditional depth, and future-depth comparisons."""

    specifications = (
        (
            "m1_preweek_relative_depth",
            ("stable_depth_share_10pp",),
            False,
        ),
        (
            "m2_preweek_log_depth_advantage",
            ("log_depth_advantage",),
            False,
        ),
        (
            "m3_future_depth_time_reversal",
            ("lead_stable_depth_share_10pp",),
            False,
        ),
        (
            "m4_preweek_and_future_depth",
            ("stable_depth_share_10pp", "lead_stable_depth_share_10pp"),
            False,
        ),
        (
            "m5_any_preweek_stable_support",
            ("positive_stable_support",),
            False,
        ),
        (
            "m6_positive_support_log_depth_advantage",
            ("log_depth_advantage",),
            True,
        ),
    )
    rows: list[dict[str, object]] = []
    for model_id, predictors, positive_depth_only in specifications:
        rows.extend(
            _fit_within_pair_week_model(
                panel,
                model_id=model_id,
                focal_predictors=predictors,
                min_observations=min_observations,
                min_clusters=min_clusters,
                positive_depth_only=positive_depth_only,
            )
        )
    return pd.DataFrame(rows)

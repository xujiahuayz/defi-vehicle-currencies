#!/usr/bin/env python3
"""Estimate whether persistent WETH volatility shifts V4 participation timing.

The primary state is lagged 30-day mean one-minute realised WETH volatility.
The unit is a vehicle-day. Regressions absorb vehicle and origin-date effects,
allow current-activity controls and each vehicle to have their own volatility
exposure, and cluster by origin date. The primary LP-action sample excludes
zero-liquidity updates and requires 180 prior days.

Transaction origins proxy for account participation. They do not identify the
beneficial owner of an LP position. The estimates are predictive associations,
not causal effects of volatility or V4 architecture.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from ddvc.analysis.regression import (
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    linear_contrast,
    ols_clustered,
)
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit
from scripts.analyze.run_v4_flash_lp_mechanism_exploration import (
    CONTROLS,
    build_mechanism_panel,
    load_inputs,
)
from scripts.analyze.run_v4_lp_origin_timing import (
    EVENT_DIR,
    build_origin_timing_panel,
    load_raw_origin_actions,
)
from scripts.process.build_v4_lp_action_candidate_daily import vehicle_candidate_map


WETH_INTRADAY_INPUT = REPO_ROOT / "data/processed/external_weth_usd_intraday.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v4_lp_volatility_state.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_lp_volatility_state_support.jsonl"

PRIMARY_STATE_DAYS = 30
SENSITIVITY_STATE_DAYS = 7
STATE_WINDOWS = (PRIMARY_STATE_DAYS, SENSITIVITY_STATE_DAYS)
OUTCOMES = (
    "near_log1p_incumbent_actions",
    "late_log1p_first_active_origins",
)
SAMPLE_VARIANTS = (
    ("primary_nonzero_180", False, 180),
    ("all_updates_180", True, 180),
    ("nonzero_90", False, 90),
)
CODE_SOURCES = [
    "scripts/analyze/run_v4_lp_volatility_state.py",
    "scripts/analyze/run_v4_lp_origin_timing.py",
    "scripts/analyze/run_v4_flash_lp_mechanism_exploration.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/processed/external_weth_usd_intraday.parquet",
    "data/raw/thegraph/uniswap_v4",
    "data/processed/v4_flash_accounting_candidate_daily.parquet",
    "data/processed/v4_lp_flow_candidate_daily.parquet",
    "data/processed/v4_lp_action_candidate_daily.parquet",
    "data/processed/v4_candidate_linked_pool_tvl_daily.parquet",
]


def load_lagged_weth_volatility(
    path: Path = WETH_INTRADAY_INPUT,
    *,
    windows: Sequence[int] = STATE_WINDOWS,
) -> pd.DataFrame:
    """Build lagged rolling mean daily realised volatility from one-minute prices."""

    if not windows or any(int(window) <= 0 for window in windows):
        raise ValueError("volatility windows must be positive")
    frame = pd.read_parquet(
        path,
        columns=[
            "bucket_start_utc",
            "available_at_utc",
            "weth_usd",
            "validation_status",
        ],
    )
    frame = frame[frame["validation_status"].eq("valid")].copy()
    if frame.empty:
        raise ValueError("intraday WETH panel has no valid prices")
    frame["timestamp"] = pd.to_datetime(
        frame["bucket_start_utc"], unit="s", utc=True
    )
    frame["available_at"] = pd.to_datetime(
        frame["available_at_utc"], unit="s", utc=True
    )
    if frame["available_at"].lt(frame["timestamp"]).any():
        raise ValueError("WETH prices are marked available before their price buckets")
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    frame["origin_date"] = frame["timestamp"].dt.tz_convert(None).dt.normalize()
    prices = frame["weth_usd"].astype(float)
    if prices.le(0).any() or not np.isfinite(prices).all():
        raise ValueError("intraday WETH prices must be finite and positive")
    frame["log_return"] = np.log(prices).diff()
    daily = (
        frame.groupby("origin_date", as_index=False, sort=True)
        .agg(
            minute_returns=("log_return", "count"),
            realised_variance=(
                "log_return",
                lambda values: float(np.nansum(np.square(values))),
            ),
        )
        .sort_values("origin_date")
    )
    daily["daily_realised_volatility"] = np.sqrt(
        daily["realised_variance"].astype(float)
    )
    for window in windows:
        column = f"lagged_{int(window)}d_weth_volatility"
        daily[column] = (
            daily["daily_realised_volatility"]
            .rolling(int(window), min_periods=int(window))
            .mean()
            .shift(1)
        )
    return daily[
        [
            "origin_date",
            "minute_returns",
            "daily_realised_volatility",
            *[f"lagged_{int(window)}d_weth_volatility" for window in windows],
        ]
    ]


def attach_volatility_state(
    panel: pd.DataFrame,
    volatility: pd.DataFrame,
    *,
    state_window_days: int,
) -> pd.DataFrame:
    """Attach and standardise the lagged state over the estimation dates."""

    state_column = f"lagged_{int(state_window_days)}d_weth_volatility"
    if state_column not in volatility.columns:
        raise ValueError(f"volatility panel lacks {state_column}")
    result = panel.merge(
        volatility[["origin_date", state_column]],
        on="origin_date",
        how="inner",
        validate="many_to_one",
    ).dropna(subset=[state_column])
    if result.empty:
        raise ValueError("volatility-state panel is empty")
    mean = float(result[state_column].mean())
    standard_deviation = float(result[state_column].std())
    if not np.isfinite(standard_deviation) or standard_deviation <= 0:
        raise ValueError("volatility state has no usable variation")
    result["weth_volatility_z"] = (
        result[state_column].astype(float) - mean
    ) / standard_deviation
    result.attrs["state_column"] = state_column
    result.attrs["state_mean"] = mean
    result.attrs["state_standard_deviation"] = standard_deviation
    return result


def _state_design(
    panel: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    result = panel.copy()
    result["internal_x_weth_volatility"] = (
        result["internal_tx_share"].astype(float)
        * result["weth_volatility_z"].astype(float)
    )
    controls_x_state: list[str] = []
    for control in CONTROLS:
        column = f"{control}_x_weth_volatility"
        result[column] = (
            result[control].astype(float) * result["weth_volatility_z"].astype(float)
        )
        controls_x_state.append(column)
    candidate_x_state: list[str] = []
    symbols = sorted(result["candidate_symbol"].astype(str).unique())
    for symbol in symbols[1:]:
        column = f"candidate_{symbol.lower()}_x_weth_volatility"
        result[column] = (
            result["candidate_symbol"].eq(symbol).astype(float)
            * result["weth_volatility_z"].astype(float)
        )
        candidate_x_state.append(column)
    regressors = [
        "internal_tx_share",
        "internal_x_weth_volatility",
        *CONTROLS,
        *controls_x_state,
        *candidate_x_state,
    ]
    return result, regressors


def fit_volatility_state(
    panel: pd.DataFrame,
    *,
    sample_variant: str,
    state_window_days: int,
    outcomes: Sequence[str] = OUTCOMES,
    min_observations: int = 300,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Fit internal-routing state interactions and low/mean/high contrasts."""

    design, regressors = _state_design(panel)
    rows: list[dict[str, object]] = []
    for outcome in outcomes:
        columns = [outcome, *regressors]
        data = design[
            ["origin_date", "candidate_symbol", *columns]
        ].dropna()
        residual = absorb_fixed_effects(
            data[columns], data["candidate_symbol"], data["origin_date"]
        )
        fit = ols_clustered(
            residual[outcome],
            residual[regressors],
            data["origin_date"],
            add_constant=False,
            absorbed_groups=(data["candidate_symbol"], data["origin_date"]),
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        contrasts = {}
        for label, state_value in (("low", -1.0), ("mean", 0.0), ("high", 1.0)):
            weights = np.zeros(len(regressors), dtype=float)
            weights[0] = 0.1
            weights[1] = 0.1 * state_value
            contrasts[label] = linear_contrast(fit, weights)
        rows.append(
            {
                "record_type": "v4_lp_volatility_state_regression",
                "analysis_status": "exploratory_mechanism",
                "sample_variant": sample_variant,
                "state_window_days": int(state_window_days),
                "outcome": outcome,
                "main_effect_per_10pp_at_mean_state": float(0.1 * fit.beta[0]),
                "main_standard_error": float(0.1 * fit.standard_errors[0]),
                "main_p_value": float(fit.p_values[0]),
                "interaction_per_10pp_per_1sd_volatility": float(0.1 * fit.beta[1]),
                "interaction_standard_error": float(0.1 * fit.standard_errors[1]),
                "interaction_p_value": float(fit.p_values[1]),
                **{
                    f"{label}_state_effect_per_10pp": float(contrast.estimate)
                    for label, contrast in contrasts.items()
                },
                **{
                    f"{label}_state_standard_error": float(contrast.standard_error)
                    for label, contrast in contrasts.items()
                },
                **{
                    f"{label}_state_ci_lower": float(contrast.confidence_interval_lower)
                    for label, contrast in contrasts.items()
                },
                **{
                    f"{label}_state_ci_upper": float(contrast.confidence_interval_upper)
                    for label, contrast in contrasts.items()
                },
                **{
                    f"{label}_state_p_value": float(contrast.p_value)
                    for label, contrast in contrasts.items()
                },
                "n_observations": int(fit.n_observations),
                "date_clusters": int(fit.n_clusters),
                "fixed_effects": "candidate+origin_date",
                "controls": "+".join(CONTROLS),
                "state_controls": "candidate-specific+origin-control-specific volatility slopes",
            }
        )
    result = pd.DataFrame(rows)
    result["interaction_holm_p_value"] = holm_adjusted_pvalues(
        result["interaction_p_value"]
    )
    return result


def leave_one_candidate_out(
    panel: pd.DataFrame,
    *,
    outcome: str = "late_log1p_first_active_origins",
    min_observations: int = 300,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Refit the persistent-volatility interaction after each vehicle exclusion."""

    rows: list[dict[str, object]] = []
    for excluded in sorted(panel["candidate_symbol"].astype(str).unique()):
        sample = panel[~panel["candidate_symbol"].eq(excluded)].copy()
        design, regressors = _state_design(sample)
        columns = [outcome, *regressors]
        data = design[
            ["origin_date", "candidate_symbol", *columns]
        ].dropna()
        residual = absorb_fixed_effects(
            data[columns], data["candidate_symbol"], data["origin_date"]
        )
        fit = ols_clustered(
            residual[outcome],
            residual[regressors],
            data["origin_date"],
            add_constant=False,
            absorbed_groups=(data["candidate_symbol"], data["origin_date"]),
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        rows.append(
            {
                "record_type": "v4_lp_volatility_state_leave_one_candidate_out",
                "analysis_status": "exploratory_mechanism",
                "sample_variant": "primary_nonzero_180",
                "state_window_days": PRIMARY_STATE_DAYS,
                "outcome": outcome,
                "excluded_candidate": excluded,
                "interaction_per_10pp_per_1sd_volatility": float(0.1 * fit.beta[1]),
                "interaction_standard_error": float(0.1 * fit.standard_errors[1]),
                "interaction_p_value": float(fit.p_values[1]),
                "n_observations": int(fit.n_observations),
                "date_clusters": int(fit.n_clusters),
            }
        )
    return pd.DataFrame(rows)


def run(
    *,
    event_dir: Path = EVENT_DIR,
    volatility_path: Path = WETH_INTRADAY_INPUT,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> tuple[pd.DataFrame, dict[str, object]]:
    flash, flow, actions, tvl = load_inputs()
    base = build_mechanism_panel(flash, flow, actions, tvl, horizons=(120,))
    all_updates, nonzero_updates, raw_support = load_raw_origin_actions(
        event_dir=event_dir,
        candidate_map=vehicle_candidate_map(),
    )
    volatility = load_lagged_weth_volatility(volatility_path)
    result_frames: list[pd.DataFrame] = []
    variant_support: dict[str, object] = {}
    primary_state_panel: pd.DataFrame | None = None
    for variant, include_zero, prior_days in SAMPLE_VARIANTS:
        daily = all_updates if include_zero else nonzero_updates
        timing_panel = build_origin_timing_panel(daily, base, prior_days=prior_days)
        state_support: dict[str, object] = {}
        for state_window_days in STATE_WINDOWS:
            state_panel = attach_volatility_state(
                timing_panel,
                volatility,
                state_window_days=state_window_days,
            )
            result_frames.append(
                fit_volatility_state(
                    state_panel,
                    sample_variant=variant,
                    state_window_days=state_window_days,
                )
            )
            state_support[str(state_window_days)] = {
                "candidate_days": int(len(state_panel)),
                "dates": int(state_panel["origin_date"].nunique()),
                "state_mean": float(state_panel.attrs["state_mean"]),
                "state_standard_deviation": float(
                    state_panel.attrs["state_standard_deviation"]
                ),
            }
            if (
                variant == "primary_nonzero_180"
                and state_window_days == PRIMARY_STATE_DAYS
            ):
                primary_state_panel = state_panel
        variant_support[variant] = {
            "prior_days": int(prior_days),
            "includes_zero_liquidity_updates": int(include_zero),
            "states": state_support,
        }
    if primary_state_panel is None:
        raise ValueError("primary persistent-volatility panel was not built")
    result_frames.append(leave_one_candidate_out(primary_state_panel))
    results = pd.concat(result_frames, ignore_index=True, sort=False)
    support = {
        "record_type": "v4_lp_volatility_state_support",
        "analysis_status": "exploratory_mechanism",
        **raw_support,
        "primary_state": (
            "lagged 30-day mean daily realised WETH volatility from valid "
            "one-minute external prices"
        ),
        "sensitivity_state": "lagged 7-day mean daily realised WETH volatility",
        "state_timing": "all state prices are available before the origin date",
        "primary_outcomes": "+".join(OUTCOMES),
        "multiple_testing": "Holm across the two state interactions within sample and state window",
        "identity_boundary": (
            "transaction origin is an account-participation proxy, not verified "
            "LP-position beneficial ownership"
        ),
        "sample_variants": variant_support,
    }
    write_exhibit(
        results,
        result_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    write_exhibit(
        pd.DataFrame([support]),
        support_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    return results, support


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-dir", type=Path, default=EVENT_DIR)
    parser.add_argument("--volatility", type=Path, default=WETH_INTRADAY_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    results, support = run(
        event_dir=args.event_dir,
        volatility_path=args.volatility,
        result_output=args.output,
        support_output=args.support_output,
    )
    primary_rows = results[
        results["record_type"].eq("v4_lp_volatility_state_regression")
        & results["sample_variant"].eq("primary_nonzero_180")
        & results["state_window_days"].eq(PRIMARY_STATE_DAYS)
    ]
    print(
        f"wrote {len(results):,} V4 volatility-state rows; "
        f"primary family has {len(primary_rows):,} outcomes and "
        f"{support['sample_variants']['primary_nonzero_180']['states']['30']['dates']:,} dates"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compare V3 and V4 LP-action responses on the same V4-active origins.

Reads:
  data/processed/liquidity_capital_v2_candidate_day.parquet
  data/processed/v3_lp_action_candidate_daily.parquet
  data/processed/v4_lp_action_candidate_daily.parquet
  data/processed/v4_flash_accounting_candidate_daily.parquet

Writes:
  output/exhibits/v3_v4_lp_protocol_contrast.jsonl
  output/exhibits/v3_v4_lp_protocol_contrast_support.jsonl

The unit is a stacked protocol--candidate--origin-day row.  The sample is
restricted to candidate-origin days with observed V4 singleton swap activity, so
the comparison is not driven by pre-V4 zero-filled rows.  Candidate-date fixed
effects compare V3 and V4 on the same candidate and day; protocol fixed effects
absorb level differences between the two protocols.  The coefficient of interest
is the V4 indicator interacted with the stable route-minus-capital gap.  It
measures whether the stable shortfall has a larger future LP-action association
under V4 than under V3.  This is exploratory protocol-contrast evidence, not a
causal design.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit
from scripts.analyze.run_liquidity_provision_behavior_exploration import (
    CANDIDATE_DAY_INPUT,
    V3_LP_ACTION_HORIZONS,
    candidate_share_gap_panel,
    load_candidate_day,
    load_v3_lp_actions,
    load_v4_lp_actions,
    route_capital_gap_v3_lp_action_horizon_panel,
    route_capital_gap_v4_lp_action_horizon_panel,
    supported_candidate_days,
)
from scripts.analyze.run_v4_flash_lp_mechanism_exploration import (
    load_inputs as load_v4_inputs,
)


RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v3_v4_lp_protocol_contrast.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_v4_lp_protocol_contrast_support.jsonl"

OUTCOMES = (
    "future_log1p_total_lp_actions",
    "future_log1p_total_origin_count",
)
CONTROLS = (
    "v4_x_stable_gap",
    "origin_log1p_total_lp_actions",
    "origin_log1p_total_origin_count",
)
CODE_SOURCES = [
    "scripts/analyze/run_v3_v4_lp_protocol_contrast.py",
    "scripts/analyze/run_liquidity_provision_behavior_exploration.py",
    "scripts/process/build_v3_lp_action_candidate_daily.py",
    "scripts/process/build_v4_lp_action_candidate_daily.py",
    "scripts/process/build_v4_flash_accounting_candidate_daily.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
    "data/processed/v3_lp_action_candidate_daily.parquet",
    "data/processed/v4_lp_action_candidate_daily.parquet",
    "data/processed/v4_flash_accounting_candidate_daily.parquet",
]


def _normalise_key(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["origin_date"] = pd.to_datetime(result["origin_date"]).dt.normalize()
    result["candidate_address"] = result["candidate_address"].astype(str).str.lower()
    return result


def load_share_gap_panel(path: Path = CANDIDATE_DAY_INPUT) -> pd.DataFrame:
    """Return the route-capital gap panel used by LP-action horizon builders."""

    candidate_day = load_candidate_day(path)
    return candidate_share_gap_panel(supported_candidate_days(candidate_day))


def load_v4_active_origins() -> pd.DataFrame:
    """Return candidate-origin days with observed V4 singleton swap activity."""

    flash, *_ = load_v4_inputs()
    required = {"origin_date", "candidate_address", "candidate_tx_count"}
    missing = sorted(required - set(flash.columns))
    if missing:
        raise ValueError(f"V4 flash-accounting panel lacks columns: {missing}")
    active = flash[flash["candidate_tx_count"].astype(float) > 0][
        ["origin_date", "candidate_address"]
    ].drop_duplicates()
    if active.empty:
        raise ValueError("V4-active origin set is empty")
    return _normalise_key(active)


def stack_v3_v4_lp_protocol_panel(
    v3_panel: pd.DataFrame,
    v4_panel: pd.DataFrame,
    v4_active_origins: pd.DataFrame,
) -> pd.DataFrame:
    """Stack V3 and V4 LP-action outcomes on common V4-active origins."""

    key = [
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "is_stable",
        "route_capital_gap_5",
        "horizon_days",
    ]
    v3_required = {
        *key,
        "future_log1p_v3_total_lp_actions",
        "future_log1p_v3_total_origin_count",
        "origin_log1p_v3_total_lp_actions",
        "origin_log1p_v3_total_origin_count",
    }
    v4_required = {
        *key,
        "future_log1p_v4_total_lp_actions",
        "future_log1p_v4_total_origin_count",
        "origin_log1p_v4_total_lp_actions",
        "origin_log1p_v4_total_origin_count",
    }
    missing_v3 = sorted(v3_required - set(v3_panel.columns))
    missing_v4 = sorted(v4_required - set(v4_panel.columns))
    if missing_v3:
        raise ValueError(f"V3 LP-action horizon panel lacks columns: {missing_v3}")
    if missing_v4:
        raise ValueError(f"V4 LP-action horizon panel lacks columns: {missing_v4}")
    active = _normalise_key(v4_active_origins)[["origin_date", "candidate_address"]]
    if active.duplicated(["origin_date", "candidate_address"]).any():
        raise ValueError("V4-active origin keys are not unique")

    v3 = _normalise_key(v3_panel).merge(
        active,
        on=["origin_date", "candidate_address"],
        how="inner",
        validate="many_to_one",
    )
    v3 = v3[
        key
        + [
            "future_log1p_v3_total_lp_actions",
            "future_log1p_v3_total_origin_count",
            "origin_log1p_v3_total_lp_actions",
            "origin_log1p_v3_total_origin_count",
        ]
    ].rename(
        columns={
            "future_log1p_v3_total_lp_actions": "future_log1p_total_lp_actions",
            "future_log1p_v3_total_origin_count": "future_log1p_total_origin_count",
            "origin_log1p_v3_total_lp_actions": "origin_log1p_total_lp_actions",
            "origin_log1p_v3_total_origin_count": "origin_log1p_total_origin_count",
        }
    )
    v3["protocol"] = "v3"
    v3["is_v4"] = 0.0

    v4 = _normalise_key(v4_panel).merge(
        active,
        on=["origin_date", "candidate_address"],
        how="inner",
        validate="many_to_one",
    )
    v4 = v4[
        key
        + [
            "future_log1p_v4_total_lp_actions",
            "future_log1p_v4_total_origin_count",
            "origin_log1p_v4_total_lp_actions",
            "origin_log1p_v4_total_origin_count",
        ]
    ].rename(
        columns={
            "future_log1p_v4_total_lp_actions": "future_log1p_total_lp_actions",
            "future_log1p_v4_total_origin_count": "future_log1p_total_origin_count",
            "origin_log1p_v4_total_lp_actions": "origin_log1p_total_lp_actions",
            "origin_log1p_v4_total_origin_count": "origin_log1p_total_origin_count",
        }
    )
    v4["protocol"] = "v4"
    v4["is_v4"] = 1.0

    stacked = pd.concat([v3, v4], ignore_index=True)
    if stacked.empty:
        raise ValueError("stacked V3/V4 LP protocol panel is empty")
    stacked["stable_gap"] = np.where(
        stacked["is_stable"].astype(bool),
        stacked["route_capital_gap_5"].astype(float),
        0.0,
    )
    stacked["v4_x_stable_gap"] = (
        stacked["is_v4"].astype(float) * stacked["stable_gap"].astype(float)
    )
    stacked["candidate_date_id"] = (
        stacked["candidate_address"].astype(str)
        + "|"
        + pd.to_datetime(stacked["origin_date"]).dt.strftime("%Y-%m-%d")
    )
    stacked = stacked.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[
            "future_log1p_total_lp_actions",
            "future_log1p_total_origin_count",
            *CONTROLS,
        ]
    )
    if stacked.empty:
        raise ValueError("stacked V3/V4 LP protocol panel is empty after filtering")
    return stacked


def fit_v3_v4_lp_protocol_contrast(
    panel: pd.DataFrame,
    *,
    horizons: Sequence[int] = V3_LP_ACTION_HORIZONS,
    outcomes: Sequence[str] = OUTCOMES,
    min_observations: int = 300,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Fit candidate-date and protocol FE protocol-contrast regressions."""

    required = {
        "origin_date",
        "candidate_date_id",
        "protocol",
        "v4_x_stable_gap",
        "origin_log1p_total_lp_actions",
        "origin_log1p_total_origin_count",
        "horizon_days",
        *outcomes,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"stacked V3/V4 LP protocol panel lacks columns: {missing}")

    rows: list[dict[str, object]] = []
    for horizon in horizons:
        horizon_panel = panel[panel["horizon_days"].eq(int(horizon))].copy()
        for outcome in outcomes:
            data = horizon_panel[
                [
                    "origin_date",
                    "candidate_date_id",
                    "protocol",
                    *CONTROLS,
                    outcome,
                ]
            ].dropna()
            if len(data) < min_observations:
                continue
            residual = absorb_fixed_effects(
                data[[outcome, *CONTROLS]],
                data["candidate_date_id"],
                data["protocol"],
            )
            fit = ols_clustered(
                residual[outcome],
                residual[list(CONTROLS)],
                data["origin_date"],
                add_constant=False,
                absorbed_groups=(data["candidate_date_id"], data["protocol"]),
                min_observations=min_observations,
                min_clusters=min_clusters,
            )
            for term, coefficient, standard_error, t_statistic, p_value in zip(
                CONTROLS,
                fit.beta,
                fit.standard_errors,
                fit.t_statistics,
                fit.p_values,
                strict=True,
            ):
                coefficient = float(coefficient)
                standard_error = float(standard_error)
                rows.append(
                    {
                        "record_type": "v3_v4_lp_protocol_contrast",
                        "analysis_status": "exploratory_protocol_contrast",
                        "sample": "v4_active_origin_candidate_dates_stacked_v3_v4",
                        "horizon_days": int(horizon),
                        "outcome": outcome,
                        "term": term,
                        "coefficient": coefficient,
                        "standard_error": standard_error,
                        "t_statistic": float(t_statistic),
                        "p_value": float(p_value),
                        "effect_per_10pp_stable_gap_v4_minus_v3": (
                            0.10 * coefficient
                            if term == "v4_x_stable_gap"
                            else np.nan
                        ),
                        "standard_error_per_10pp_stable_gap_v4_minus_v3": (
                            0.10 * standard_error
                            if term == "v4_x_stable_gap"
                            else np.nan
                        ),
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate_date+protocol",
                        "covariance": "origin_date_clustered",
                        "activity_controls": (
                            "origin_log1p_total_lp_actions+"
                            "origin_log1p_total_origin_count"
                        ),
                        "interpretation": (
                            "same candidate-date V4-minus-V3 future LP-action "
                            "association of a stable route-minus-capital "
                            "shortfall, net of same-protocol current action "
                            "activity; exploratory contrast, not causal"
                        ),
                    }
                )
    if not rows:
        raise ValueError("no V3/V4 LP protocol-contrast regressions were estimated")
    return pd.DataFrame(rows)


def support_record(panel: pd.DataFrame, results: pd.DataFrame) -> dict[str, object]:
    """Summarise the V3/V4 protocol-contrast design."""

    origin_candidates = panel[
        ["origin_date", "candidate_address", "candidate_symbol"]
    ].drop_duplicates()
    return {
        "record_type": "v3_v4_lp_protocol_contrast_support",
        "analysis_status": "exploratory_protocol_contrast",
        "sample": "v4_active_origin_candidate_dates_stacked_v3_v4",
        "protocols": "+".join(sorted(panel["protocol"].unique())),
        "candidate_count": int(origin_candidates["candidate_address"].nunique()),
        "candidate_symbols": "+".join(sorted(origin_candidates["candidate_symbol"].unique())),
        "origin_candidate_dates": int(len(origin_candidates)),
        "stacked_horizon_rows": int(len(panel)),
        "first_date": str(pd.to_datetime(panel["origin_date"]).min().date()),
        "last_date": str(pd.to_datetime(panel["origin_date"]).max().date()),
        "date_count": int(pd.to_datetime(panel["origin_date"]).nunique()),
        "horizons": "+".join(str(int(value)) for value in sorted(panel["horizon_days"].unique())),
        "result_rows": int(len(results)),
        "contrast_rows": int(results["term"].eq("v4_x_stable_gap").sum()),
        "fixed_effects": "candidate_date+protocol",
        "cluster": "origin_date",
        "quantity": (
            "future V3 mint/burn and V4 modify-liquidity action counts and "
            "active origin counts on the same V4-active origin candidate-dates; "
            "not deposited capital, LP inventory, executable depth, or causal "
            "protocol treatment"
        ),
    }


def run(
    *,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
) -> int:
    share_gap = load_share_gap_panel(candidate_day_path)
    v3_actions = load_v3_lp_actions()
    v4_actions = load_v4_lp_actions()
    v3_panel = route_capital_gap_v3_lp_action_horizon_panel(
        share_gap,
        actions=v3_actions,
    )
    v4_panel = route_capital_gap_v4_lp_action_horizon_panel(
        share_gap,
        actions=v4_actions,
    )
    active = load_v4_active_origins()
    panel = stack_v3_v4_lp_protocol_panel(v3_panel, v4_panel, active)
    results = fit_v3_v4_lp_protocol_contrast(panel)
    support = pd.DataFrame([support_record(panel, results)])
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    display_output = result_output.resolve()
    try:
        display_output = display_output.relative_to(REPO_ROOT)
    except ValueError:
        pass
    print(
        f"wrote {len(results):,} V3/V4 LP protocol-contrast rows to {display_output}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--candidate-day", type=Path, default=CANDIDATE_DAY_INPUT)
    args = parser.parse_args()
    return run(
        result_output=args.result_output,
        support_output=args.support_output,
        candidate_day_path=args.candidate_day,
    )


if __name__ == "__main__":
    raise SystemExit(main())

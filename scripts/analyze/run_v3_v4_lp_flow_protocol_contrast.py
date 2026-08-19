#!/usr/bin/env python3
"""Compare V3 and V4 LP-flow responses on the same V4-active origins.

Reads:
  data/processed/liquidity_capital_v2_candidate_day.parquet
  data/processed/v3_lp_flow_candidate_daily.parquet
  data/processed/v4_lp_flow_candidate_daily.parquet
  data/processed/v4_flash_accounting_candidate_daily.parquet

Writes:
  output/exhibits/v3_v4_lp_flow_protocol_contrast.jsonl
  output/exhibits/v3_v4_lp_flow_protocol_contrast_support.jsonl

The unit is a stacked protocol--candidate--origin-day row. The sample is
restricted to candidate-origin days with observed V4 singleton swap activity, so
the comparison is not driven by pre-V4 zero-filled rows. Candidate-date fixed
effects compare V3 and V4 on the same candidate and day; protocol fixed effects
absorb level differences between the two protocols. The coefficient of interest
is the V4 indicator interacted with the stable route-minus-capital gap. It
measures whether the stable shortfall has a larger future candidate-token
LP-dollar-flow association under V4 than under V3. This is exploratory
protocol-contrast evidence, not a causal design.
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
    supported_candidate_days,
)
from scripts.analyze.run_v3_v4_lp_protocol_contrast import (
    load_share_gap_panel,
    load_v4_active_origins,
)


V3_FLOW_INPUT = REPO_ROOT / "data/processed/v3_lp_flow_candidate_daily.parquet"
V4_FLOW_INPUT = REPO_ROOT / "data/processed/v4_lp_flow_candidate_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v3_v4_lp_flow_protocol_contrast.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_v4_lp_flow_protocol_contrast_support.jsonl"

OUTCOMES = (
    "future_log1p_gross_lp_flow_usd",
    "future_log1p_add_lp_flow_usd",
    "future_log1p_remove_lp_flow_usd",
)
CONTROLS = (
    "v4_x_stable_gap",
    "origin_log1p_gross_lp_flow_usd",
    "origin_log1p_add_lp_flow_usd",
    "origin_log1p_remove_lp_flow_usd",
    "origin_log1p_sender_days",
)
FLOW_MEASURES = (
    "gross_lp_flow_usd_screened",
    "add_lp_flow_usd_screened",
    "remove_lp_flow_usd_screened",
    "net_add_lp_flow_usd_screened",
    "narrow_medium_flow_usd_screened",
    "broad_flow_usd_screened",
    "lp_flow_sender_count",
)
CODE_SOURCES = [
    "scripts/analyze/run_v3_v4_lp_flow_protocol_contrast.py",
    "scripts/process/build_v3_lp_flow_candidate_daily.py",
    "scripts/process/build_v4_lp_flow_candidate_daily.py",
    "scripts/analyze/run_v3_v4_lp_protocol_contrast.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/processed/liquidity_capital_v2_candidate_day.parquet",
    "data/processed/v3_lp_flow_candidate_daily.parquet",
    "data/processed/v4_lp_flow_candidate_daily.parquet",
    "data/processed/v4_flash_accounting_candidate_daily.parquet",
]


def _normalise_key(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["origin_date"] = pd.to_datetime(result["origin_date"]).dt.normalize()
    result["candidate_address"] = result["candidate_address"].astype(str).str.lower()
    return result


def load_v3_lp_flows(path: Path = V3_FLOW_INPUT) -> pd.DataFrame:
    """Load the processed Uniswap V3 candidate-side LP-flow panel."""

    frame = pd.read_parquet(path)
    required = {"origin_date", "candidate_address", "candidate_symbol"} | {
        f"v3_{measure}" for measure in FLOW_MEASURES
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"V3 LP-flow panel lacks columns: {missing}")
    frame = _normalise_key(frame)
    frame["candidate_symbol"] = frame["candidate_symbol"].astype(str)
    return frame


def load_v4_lp_flows(path: Path = V4_FLOW_INPUT) -> pd.DataFrame:
    """Load the processed Uniswap V4 candidate-side LP-flow panel."""

    frame = pd.read_parquet(path)
    required = {"origin_date", "candidate_address", "candidate_symbol"} | {
        f"v4_{measure}" for measure in FLOW_MEASURES
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"V4 LP-flow panel lacks columns: {missing}")
    frame = _normalise_key(frame)
    frame["candidate_symbol"] = frame["candidate_symbol"].astype(str)
    return frame


def route_capital_gap_lp_flow_horizon_panel(
    share_gap_panel: pd.DataFrame,
    *,
    flows: pd.DataFrame,
    prefix: str,
    horizons: tuple[int, ...] = V3_LP_ACTION_HORIZONS,
) -> pd.DataFrame:
    """Attach future candidate-side LP-dollar flows to route-capital gaps."""

    if prefix not in {"v3", "v4"}:
        raise ValueError("prefix must be v3 or v4")
    if not horizons:
        raise ValueError("at least one LP-flow horizon is required")
    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "route_capital_gap_5",
        "is_stable",
    }
    missing = sorted(required - set(share_gap_panel.columns))
    if missing:
        raise ValueError(f"share-gap panel lacks LP-flow columns: {missing}")
    flow_columns = [f"{prefix}_{measure}" for measure in FLOW_MEASURES]
    missing_flows = sorted({"origin_date", "candidate_address", *flow_columns} - set(flows.columns))
    if missing_flows:
        raise ValueError(f"{prefix.upper()} LP-flow panel lacks columns: {missing_flows}")

    base = share_gap_panel[list(required)].copy()
    base["origin_date"] = pd.to_datetime(base["origin_date"]).dt.normalize()
    base["candidate_address"] = base["candidate_address"].astype(str).str.lower()
    base["candidate_symbol"] = base["candidate_symbol"].astype(str)
    flow_frame = _normalise_key(flows)
    flow_frame = (
        flow_frame.groupby(
            ["origin_date", "candidate_address"], as_index=False, sort=True
        )[flow_columns]
        .sum()
    )
    origin_flow_columns = [f"origin_{column}" for column in flow_columns]
    origin_flow_frame = flow_frame.rename(
        columns={column: f"origin_{column}" for column in flow_columns}
    )

    horizon_rows: list[pd.DataFrame] = []
    max_horizon = max(horizons)
    for candidate_address, candidate_base in base.groupby(
        "candidate_address", sort=True
    ):
        candidate_base = candidate_base.sort_values("origin_date").copy()
        start = candidate_base["origin_date"].min()
        end = candidate_base["origin_date"].max() + pd.Timedelta(days=max_horizon)
        calendar = pd.DataFrame(
            {
                "origin_date": pd.date_range(start, end, freq="D"),
                "candidate_address": candidate_address,
            }
        )
        calendar = calendar.merge(
            flow_frame[flow_frame["candidate_address"].eq(candidate_address)],
            on=["origin_date", "candidate_address"],
            how="left",
        )
        calendar[flow_columns] = calendar[flow_columns].fillna(0.0)
        for column in flow_columns:
            calendar[f"{column}_cumulative"] = calendar[column].cumsum()
        cumulative = calendar[
            ["origin_date", *[f"{column}_cumulative" for column in flow_columns]]
        ]
        origin = candidate_base.merge(
            origin_flow_frame,
            on=["origin_date", "candidate_address"],
            how="left",
            validate="one_to_one",
        )
        origin[origin_flow_columns] = origin[origin_flow_columns].fillna(0.0)
        origin = origin.merge(
            cumulative,
            on="origin_date",
            how="left",
            validate="one_to_one",
        )
        for horizon in horizons:
            target = cumulative.copy()
            target["origin_date"] = target["origin_date"] - pd.Timedelta(
                days=horizon
            )
            joined = origin.merge(
                target,
                on="origin_date",
                how="inner",
                suffixes=("", "_target"),
                validate="one_to_one",
            )
            if joined.empty:
                continue
            joined["horizon_days"] = int(horizon)
            for column in flow_columns:
                joined[f"future_{column}"] = (
                    joined[f"{column}_cumulative_target"]
                    - joined[f"{column}_cumulative"]
                )
            horizon_rows.append(joined)
    if not horizon_rows:
        raise ValueError(f"{prefix.upper()} LP-flow horizon panel is empty")
    panel = pd.concat(horizon_rows, ignore_index=True, sort=False)
    gross = panel[f"future_{prefix}_gross_lp_flow_usd_screened"].astype(float)
    add = panel[f"future_{prefix}_add_lp_flow_usd_screened"].astype(float)
    remove = panel[f"future_{prefix}_remove_lp_flow_usd_screened"].astype(float)
    narrow_medium = panel[f"future_{prefix}_narrow_medium_flow_usd_screened"].astype(float)
    broad = panel[f"future_{prefix}_broad_flow_usd_screened"].astype(float)
    panel[f"future_log1p_{prefix}_gross_lp_flow_usd"] = np.log1p(gross)
    panel[f"future_log1p_{prefix}_add_lp_flow_usd"] = np.log1p(add)
    panel[f"future_log1p_{prefix}_remove_lp_flow_usd"] = np.log1p(remove)
    panel[f"future_{prefix}_net_add_flow_balance"] = (add - remove) / gross.add(1.0)
    panel[f"future_{prefix}_narrow_medium_flow_value_share"] = np.where(
        gross > 0,
        narrow_medium / gross,
        np.nan,
    )
    panel[f"future_{prefix}_broad_flow_value_share"] = np.where(
        gross > 0,
        broad / gross,
        np.nan,
    )
    panel[f"future_log1p_{prefix}_sender_days"] = np.log1p(
        panel[f"future_{prefix}_lp_flow_sender_count"].astype(float)
    )
    panel[f"origin_log1p_{prefix}_gross_lp_flow_usd"] = np.log1p(
        panel[f"origin_{prefix}_gross_lp_flow_usd_screened"].astype(float)
    )
    panel[f"origin_log1p_{prefix}_add_lp_flow_usd"] = np.log1p(
        panel[f"origin_{prefix}_add_lp_flow_usd_screened"].astype(float)
    )
    panel[f"origin_log1p_{prefix}_remove_lp_flow_usd"] = np.log1p(
        panel[f"origin_{prefix}_remove_lp_flow_usd_screened"].astype(float)
    )
    panel[f"origin_log1p_{prefix}_sender_days"] = np.log1p(
        panel[f"origin_{prefix}_lp_flow_sender_count"].astype(float)
    )
    return panel.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[
            "route_capital_gap_5",
            "is_stable",
            f"future_log1p_{prefix}_gross_lp_flow_usd",
            f"future_log1p_{prefix}_add_lp_flow_usd",
            f"future_log1p_{prefix}_remove_lp_flow_usd",
            f"origin_log1p_{prefix}_gross_lp_flow_usd",
            f"origin_log1p_{prefix}_add_lp_flow_usd",
            f"origin_log1p_{prefix}_remove_lp_flow_usd",
            f"origin_log1p_{prefix}_sender_days",
        ]
    )


def stack_v3_v4_lp_flow_protocol_panel(
    v3_panel: pd.DataFrame,
    v4_panel: pd.DataFrame,
    v4_active_origins: pd.DataFrame,
) -> pd.DataFrame:
    """Stack V3 and V4 LP-flow outcomes on common V4-active origins."""

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
        "future_log1p_v3_gross_lp_flow_usd",
        "future_log1p_v3_add_lp_flow_usd",
        "future_log1p_v3_remove_lp_flow_usd",
        "origin_log1p_v3_gross_lp_flow_usd",
        "origin_log1p_v3_add_lp_flow_usd",
        "origin_log1p_v3_remove_lp_flow_usd",
        "origin_log1p_v3_sender_days",
    }
    v4_required = {
        *key,
        "future_log1p_v4_gross_lp_flow_usd",
        "future_log1p_v4_add_lp_flow_usd",
        "future_log1p_v4_remove_lp_flow_usd",
        "origin_log1p_v4_gross_lp_flow_usd",
        "origin_log1p_v4_add_lp_flow_usd",
        "origin_log1p_v4_remove_lp_flow_usd",
        "origin_log1p_v4_sender_days",
    }
    missing_v3 = sorted(v3_required - set(v3_panel.columns))
    missing_v4 = sorted(v4_required - set(v4_panel.columns))
    if missing_v3:
        raise ValueError(f"V3 LP-flow horizon panel lacks columns: {missing_v3}")
    if missing_v4:
        raise ValueError(f"V4 LP-flow horizon panel lacks columns: {missing_v4}")
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
            "future_log1p_v3_gross_lp_flow_usd",
            "future_log1p_v3_add_lp_flow_usd",
            "future_log1p_v3_remove_lp_flow_usd",
            "origin_log1p_v3_gross_lp_flow_usd",
            "origin_log1p_v3_add_lp_flow_usd",
            "origin_log1p_v3_remove_lp_flow_usd",
            "origin_log1p_v3_sender_days",
        ]
    ].rename(
        columns={
            "future_log1p_v3_gross_lp_flow_usd": "future_log1p_gross_lp_flow_usd",
            "future_log1p_v3_add_lp_flow_usd": "future_log1p_add_lp_flow_usd",
            "future_log1p_v3_remove_lp_flow_usd": "future_log1p_remove_lp_flow_usd",
            "origin_log1p_v3_gross_lp_flow_usd": "origin_log1p_gross_lp_flow_usd",
            "origin_log1p_v3_add_lp_flow_usd": "origin_log1p_add_lp_flow_usd",
            "origin_log1p_v3_remove_lp_flow_usd": "origin_log1p_remove_lp_flow_usd",
            "origin_log1p_v3_sender_days": "origin_log1p_sender_days",
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
            "future_log1p_v4_gross_lp_flow_usd",
            "future_log1p_v4_add_lp_flow_usd",
            "future_log1p_v4_remove_lp_flow_usd",
            "origin_log1p_v4_gross_lp_flow_usd",
            "origin_log1p_v4_add_lp_flow_usd",
            "origin_log1p_v4_remove_lp_flow_usd",
            "origin_log1p_v4_sender_days",
        ]
    ].rename(
        columns={
            "future_log1p_v4_gross_lp_flow_usd": "future_log1p_gross_lp_flow_usd",
            "future_log1p_v4_add_lp_flow_usd": "future_log1p_add_lp_flow_usd",
            "future_log1p_v4_remove_lp_flow_usd": "future_log1p_remove_lp_flow_usd",
            "origin_log1p_v4_gross_lp_flow_usd": "origin_log1p_gross_lp_flow_usd",
            "origin_log1p_v4_add_lp_flow_usd": "origin_log1p_add_lp_flow_usd",
            "origin_log1p_v4_remove_lp_flow_usd": "origin_log1p_remove_lp_flow_usd",
            "origin_log1p_v4_sender_days": "origin_log1p_sender_days",
        }
    )
    v4["protocol"] = "v4"
    v4["is_v4"] = 1.0

    stacked = pd.concat([v3, v4], ignore_index=True)
    if stacked.empty:
        raise ValueError("stacked V3/V4 LP-flow protocol panel is empty")
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
        subset=[*OUTCOMES, *CONTROLS]
    )
    if stacked.empty:
        raise ValueError("stacked V3/V4 LP-flow protocol panel is empty after filtering")
    return stacked


def fit_v3_v4_lp_flow_protocol_contrast(
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
        "horizon_days",
        *CONTROLS,
        *outcomes,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"stacked V3/V4 LP-flow panel lacks columns: {missing}")

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
                        "record_type": "v3_v4_lp_flow_protocol_contrast",
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
                            "origin_log1p_gross_lp_flow_usd+"
                            "origin_log1p_add_lp_flow_usd+"
                            "origin_log1p_remove_lp_flow_usd+"
                            "origin_log1p_sender_days"
                        ),
                        "interpretation": (
                            "same candidate-date V4-minus-V3 future LP-dollar-flow "
                            "association of a stable route-minus-capital shortfall, "
                            "net of same-protocol current flow activity; "
                            "exploratory contrast, not causal"
                        ),
                    }
                )
    if not rows:
        raise ValueError("no V3/V4 LP-flow protocol-contrast regressions were estimated")
    return pd.DataFrame(rows)


def support_record(panel: pd.DataFrame, results: pd.DataFrame) -> dict[str, object]:
    """Summarize the V3/V4 LP-flow protocol-contrast design."""

    origin_candidates = panel[
        ["origin_date", "candidate_address", "candidate_symbol"]
    ].drop_duplicates()
    return {
        "record_type": "v3_v4_lp_flow_protocol_contrast_support",
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
            "future V3 mint/burn and V4 modify-liquidity candidate-token-side "
            "USD flow on the same V4-active origin candidate-dates; not whole-pool "
            "TVL, LP inventory, executable depth, or causal protocol treatment"
        ),
    }


def run(
    *,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    candidate_day_path: Path = CANDIDATE_DAY_INPUT,
    v3_flow_path: Path = V3_FLOW_INPUT,
    v4_flow_path: Path = V4_FLOW_INPUT,
) -> int:
    share_gap = load_share_gap_panel(candidate_day_path)
    v3_panel = route_capital_gap_lp_flow_horizon_panel(
        share_gap,
        flows=load_v3_lp_flows(v3_flow_path),
        prefix="v3",
    )
    v4_panel = route_capital_gap_lp_flow_horizon_panel(
        share_gap,
        flows=load_v4_lp_flows(v4_flow_path),
        prefix="v4",
    )
    active = load_v4_active_origins()
    panel = stack_v3_v4_lp_flow_protocol_panel(v3_panel, v4_panel, active)
    results = fit_v3_v4_lp_flow_protocol_contrast(panel)
    support = pd.DataFrame([support_record(panel, results)])
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    display_output = result_output.resolve()
    try:
        display_output = display_output.relative_to(REPO_ROOT)
    except ValueError:
        pass
    print(
        f"wrote {len(results):,} V3/V4 LP-flow protocol-contrast rows to "
        f"{display_output}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--candidate-day", type=Path, default=CANDIDATE_DAY_INPUT)
    parser.add_argument("--v3-flow", type=Path, default=V3_FLOW_INPUT)
    parser.add_argument("--v4-flow", type=Path, default=V4_FLOW_INPUT)
    args = parser.parse_args()
    return run(
        result_output=args.result_output,
        support_output=args.support_output,
        candidate_day_path=args.candidate_day,
        v3_flow_path=args.v3_flow,
        v4_flow_path=args.v4_flow,
    )


if __name__ == "__main__":
    raise SystemExit(main())

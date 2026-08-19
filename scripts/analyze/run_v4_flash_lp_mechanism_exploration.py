#!/usr/bin/env python3
"""Estimate V4 flash-accounting intensity against future LP behavior.

Reads:
  data/processed/v4_flash_accounting_candidate_daily.parquet
  data/processed/v4_lp_flow_candidate_daily.parquet
  data/processed/v4_lp_action_candidate_daily.parquet
  data/processed/v4_candidate_linked_pool_tvl_daily.parquet

Writes:
  output/exhibits/v4_flash_lp_mechanism_exploration.jsonl
  output/exhibits/v4_flash_lp_mechanism_support.jsonl

The unit is candidate-day. Regressions absorb candidate and origin-date fixed
effects and cluster by origin date. Outcomes are future V4 LP dollar flow,
candidate-linked pool TVL, and position-management measures over 7, 30, and
120 day horizons. The evidence is exploratory mechanism evidence; it is not a
claim that flash accounting causally moves LP capital.
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


FLASH_INPUT = REPO_ROOT / "data/processed/v4_flash_accounting_candidate_daily.parquet"
LP_FLOW_INPUT = REPO_ROOT / "data/processed/v4_lp_flow_candidate_daily.parquet"
LP_ACTION_INPUT = REPO_ROOT / "data/processed/v4_lp_action_candidate_daily.parquet"
POOL_TVL_INPUT = REPO_ROOT / "data/processed/v4_candidate_linked_pool_tvl_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v4_flash_lp_mechanism_exploration.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v4_flash_lp_mechanism_support.jsonl"

HORIZONS = (7, 30, 120)
PREDICTORS = ("internal_tx_share", "multi_leg_tx_share", "netting_reduction_share")
OUTCOMES = (
    "future_log1p_gross_lp_flow_usd",
    "future_log1p_add_lp_flow_usd",
    "future_log1p_remove_lp_flow_usd",
    "future_net_add_flow_balance",
    "future_delta_log1p_tvl_usd",
    "future_log1p_lp_actions",
    "future_narrow_medium_flow_value_share",
    "future_broad_flow_value_share",
    "future_narrow_medium_action_share",
    "future_wide_very_wide_action_share",
    "future_full_range_action_share",
)
CONTROLS = (
    "log1p_swap_leg_assignments",
    "log1p_current_gross_flow_usd",
    "log1p_current_tvl_usd",
    "log1p_current_actions",
    "current_narrow_medium_share",
)
CODE_SOURCES = [
    "scripts/analyze/run_v4_flash_lp_mechanism_exploration.py",
    "scripts/process/build_v4_flash_accounting_candidate_daily.py",
    "scripts/process/build_v4_lp_flow_candidate_daily.py",
    "scripts/process/build_v4_lp_action_candidate_daily.py",
    "scripts/process/build_v4_candidate_linked_pool_tvl_daily.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/processed/v4_flash_accounting_candidate_daily.parquet",
    "data/processed/v4_lp_flow_candidate_daily.parquet",
    "data/processed/v4_lp_action_candidate_daily.parquet",
    "data/processed/v4_candidate_linked_pool_tvl_daily.parquet",
]


def _normalise_candidate_day(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["origin_date"] = pd.to_datetime(result["origin_date"]).dt.normalize()
    result["candidate_address"] = result["candidate_address"].astype(str).str.lower()
    result["candidate_symbol"] = result["candidate_symbol"].astype(str)
    return result


def _require_columns(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name} lacks required columns: {missing}")


def load_inputs(
    *,
    flash_path: Path = FLASH_INPUT,
    flow_path: Path = LP_FLOW_INPUT,
    action_path: Path = LP_ACTION_INPUT,
    tvl_path: Path = POOL_TVL_INPUT,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    flash = _normalise_candidate_day(pd.read_parquet(flash_path))
    flow = _normalise_candidate_day(pd.read_parquet(flow_path))
    actions = _normalise_candidate_day(pd.read_parquet(action_path))
    tvl = _normalise_candidate_day(pd.read_parquet(tvl_path))
    _require_columns(
        flash,
        {
            "candidate_tx_count",
            "swap_leg_assignments",
            "multi_leg_tx_count",
            "internal_tx_count",
            "netting_reduction_tx_count",
            "multi_leg_tx_share",
            "internal_tx_share",
            "netting_reduction_share",
        },
        "V4 flash-accounting panel",
    )
    _require_columns(
        flow,
        {
            "v4_gross_lp_flow_usd_screened",
            "v4_add_lp_flow_usd_screened",
            "v4_remove_lp_flow_usd_screened",
            "v4_narrow_medium_flow_usd_screened",
            "v4_broad_flow_usd_screened",
            "v4_lp_flow_screened_assignments",
        },
        "V4 LP-flow panel",
    )
    _require_columns(
        actions,
        {
            "v4_total_lp_actions",
            "v4_add_events",
            "v4_remove_events",
            "v4_narrow_range_events",
            "v4_medium_range_events",
            "v4_wide_range_events",
            "v4_very_wide_range_events",
            "v4_full_range_events",
            "v4_total_origin_count",
        },
        "V4 LP-action panel",
    )
    _require_columns(
        tvl,
        {
            "capital_valid",
            "candidate_linked_pool_tvl_usd",
            "candidate_linked_pool_volume_usd",
            "pool",
        },
        "V4 candidate-linked TVL panel",
    )
    return flash, flow, actions, tvl


def build_mechanism_panel(
    flash: pd.DataFrame,
    flow: pd.DataFrame,
    actions: pd.DataFrame,
    tvl: pd.DataFrame,
    *,
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    """Return candidate-day horizon rows for flash-accounting mechanism regressions."""

    flow_columns = [
        "v4_gross_lp_flow_usd_screened",
        "v4_add_lp_flow_usd_screened",
        "v4_remove_lp_flow_usd_screened",
        "v4_narrow_medium_flow_usd_screened",
        "v4_broad_flow_usd_screened",
        "v4_lp_flow_screened_assignments",
    ]
    action_columns = [
        "v4_total_lp_actions",
        "v4_add_events",
        "v4_remove_events",
        "v4_narrow_range_events",
        "v4_medium_range_events",
        "v4_wide_range_events",
        "v4_very_wide_range_events",
        "v4_full_range_events",
        "v4_total_origin_count",
    ]
    key = ["origin_date", "candidate_address", "candidate_symbol"]
    flow_daily = flow.groupby(key, as_index=False, sort=True)[flow_columns].sum()
    action_daily = actions.groupby(key, as_index=False, sort=True)[action_columns].sum()
    tvl_valid = tvl[tvl["capital_valid"].astype(bool)].copy()
    tvl_daily = (
        tvl_valid.groupby(key, as_index=False, sort=True)
        .agg(
            v4_candidate_linked_pool_tvl_usd=("candidate_linked_pool_tvl_usd", "sum"),
            v4_candidate_linked_pool_volume_usd=("candidate_linked_pool_volume_usd", "sum"),
            v4_candidate_linked_pool_count=("pool", "nunique"),
        )
    )
    candidates = flash[key[1:]].drop_duplicates().sort_values(key[1:]).reset_index(drop=True)
    dates = pd.DataFrame(
        {
            "origin_date": pd.date_range(
                flash["origin_date"].min(),
                flash["origin_date"].max(),
                freq="D",
            )
        }
    )
    base = candidates.merge(dates, how="cross")
    base = base.merge(flash, on=key, how="left")
    base = base.merge(flow_daily, on=key, how="left")
    base = base.merge(action_daily, on=key, how="left")
    base = base.merge(tvl_daily, on=key, how="left")
    fill_columns = [
        column
        for column in [
            *flow_columns,
            *action_columns,
            "candidate_tx_count",
            "swap_leg_assignments",
            "multi_leg_tx_count",
            "internal_tx_count",
            "netting_reduction_tx_count",
            "gross_abs_amount",
            "net_abs_amount",
            "netting_reduction_amount",
            "multi_leg_tx_share",
            "internal_tx_share",
            "netting_reduction_share",
            "v4_candidate_linked_pool_tvl_usd",
            "v4_candidate_linked_pool_volume_usd",
            "v4_candidate_linked_pool_count",
        ]
        if column in base.columns
    ]
    base[fill_columns] = base[fill_columns].fillna(0.0)
    base = base.sort_values(["candidate_address", "origin_date"]).reset_index(drop=True)
    base["log1p_swap_leg_assignments"] = np.log1p(base["swap_leg_assignments"].astype(float))
    base["log1p_current_gross_flow_usd"] = np.log1p(
        base["v4_gross_lp_flow_usd_screened"].astype(float)
    )
    base["log1p_current_tvl_usd"] = np.log1p(
        base["v4_candidate_linked_pool_tvl_usd"].astype(float)
    )
    base["log1p_current_actions"] = np.log1p(base["v4_total_lp_actions"].astype(float))
    base["current_narrow_medium_share"] = (
        base["v4_narrow_range_events"].astype(float)
        + base["v4_medium_range_events"].astype(float)
    ) / (base["v4_total_lp_actions"].astype(float) + 1.0)

    horizon_rows: list[pd.DataFrame] = []
    cumulative_columns = [
        "v4_gross_lp_flow_usd_screened",
        "v4_add_lp_flow_usd_screened",
        "v4_remove_lp_flow_usd_screened",
        "v4_narrow_medium_flow_usd_screened",
        "v4_broad_flow_usd_screened",
        "v4_total_lp_actions",
        "v4_add_events",
        "v4_remove_events",
        "v4_narrow_range_events",
        "v4_medium_range_events",
        "v4_wide_range_events",
        "v4_very_wide_range_events",
        "v4_full_range_events",
    ]
    for _candidate, candidate_panel in base.groupby("candidate_address", sort=True):
        candidate_panel = candidate_panel.sort_values("origin_date").copy()
        for column in cumulative_columns:
            candidate_panel[f"{column}_cumulative"] = candidate_panel[column].cumsum()
        for horizon in horizons:
            origin = candidate_panel[
                [
                    "origin_date",
                    "candidate_address",
                    "candidate_symbol",
                    *PREDICTORS,
                    *CONTROLS,
                    "v4_candidate_linked_pool_tvl_usd",
                ]
            ].copy()
            origin["horizon_days"] = int(horizon)
            for column in cumulative_columns:
                origin[f"future_{column}"] = (
                    candidate_panel[f"{column}_cumulative"].shift(-horizon).to_numpy()
                    - candidate_panel[f"{column}_cumulative"].to_numpy()
                )
            origin["future_tvl_usd"] = candidate_panel[
                "v4_candidate_linked_pool_tvl_usd"
            ].shift(-horizon).to_numpy()
            origin["future_delta_log1p_tvl_usd"] = np.log1p(
                origin["future_tvl_usd"]
            ) - np.log1p(origin["v4_candidate_linked_pool_tvl_usd"])
            horizon_rows.append(origin)
    panel = pd.concat(horizon_rows, ignore_index=True, sort=False)
    panel["future_log1p_gross_lp_flow_usd"] = np.log1p(
        panel["future_v4_gross_lp_flow_usd_screened"]
    )
    panel["future_log1p_add_lp_flow_usd"] = np.log1p(
        panel["future_v4_add_lp_flow_usd_screened"]
    )
    panel["future_log1p_remove_lp_flow_usd"] = np.log1p(
        panel["future_v4_remove_lp_flow_usd_screened"]
    )
    panel["future_log1p_lp_actions"] = np.log1p(panel["future_v4_total_lp_actions"])
    panel["future_net_add_flow_balance"] = (
        panel["future_v4_add_lp_flow_usd_screened"]
        - panel["future_v4_remove_lp_flow_usd_screened"]
    ) / (panel["future_v4_gross_lp_flow_usd_screened"] + 1.0)
    gross_flow = panel["future_v4_gross_lp_flow_usd_screened"].astype(float)
    panel["future_narrow_medium_flow_value_share"] = np.where(
        gross_flow > 0,
        panel["future_v4_narrow_medium_flow_usd_screened"].astype(float) / gross_flow,
        np.nan,
    )
    panel["future_broad_flow_value_share"] = np.where(
        gross_flow > 0,
        panel["future_v4_broad_flow_usd_screened"].astype(float) / gross_flow,
        np.nan,
    )
    panel["future_narrow_medium_action_share"] = (
        panel["future_v4_narrow_range_events"] + panel["future_v4_medium_range_events"]
    ) / (panel["future_v4_total_lp_actions"] + 1.0)
    panel["future_wide_very_wide_action_share"] = (
        panel["future_v4_wide_range_events"] + panel["future_v4_very_wide_range_events"]
    ) / (panel["future_v4_total_lp_actions"] + 1.0)
    panel["future_full_range_action_share"] = (
        panel["future_v4_full_range_events"] / (panel["future_v4_total_lp_actions"] + 1.0)
    )
    return panel


def fit_mechanism_regressions(
    panel: pd.DataFrame,
    *,
    horizons: Sequence[int] = HORIZONS,
    predictors: Sequence[str] = PREDICTORS,
    outcomes: Sequence[str] = OUTCOMES,
    controls: Sequence[str] = CONTROLS,
    min_observations: int = 100,
    min_clusters: int = 30,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for horizon in horizons:
        horizon_panel = panel[panel["horizon_days"].eq(horizon)].copy()
        for predictor in predictors:
            for outcome in outcomes:
                columns = [outcome, predictor, *controls]
                data = horizon_panel[
                    ["origin_date", "candidate_symbol", *columns]
                ].dropna()
                if len(data) < min_observations:
                    continue
                residual = absorb_fixed_effects(
                    data[columns],
                    data["candidate_symbol"],
                    data["origin_date"],
                )
                fit = ols_clustered(
                    residual[outcome],
                    residual[[predictor, *controls]],
                    data["origin_date"],
                    add_constant=False,
                    absorbed_groups=(data["candidate_symbol"], data["origin_date"]),
                    min_observations=min_observations,
                    min_clusters=min_clusters,
                )
                rows.append(
                    {
                        "record_type": "v4_flash_lp_mechanism_regression",
                        "analysis_status": "exploratory_mechanism",
                        "horizon_days": int(horizon),
                        "predictor": predictor,
                        "outcome": outcome,
                        "coefficient": float(fit.beta[0]),
                        "standard_error": float(fit.standard_errors[0]),
                        "t_statistic": float(fit.t_statistics[0]),
                        "p_value": float(fit.p_values[0]),
                        "effect_per_10pp_predictor": float(0.1 * fit.beta[0]),
                        "n_observations": int(fit.n_observations),
                        "date_clusters": int(fit.n_clusters),
                        "fixed_effects": "candidate+origin_date",
                        "controls": "+".join(controls),
                        "interpretation": (
                            "association of current V4 singleton flash-accounting "
                            "intensity with future candidate-side LP flow, "
                            "candidate-linked pool TVL, and position management; "
                            "not a causal claim"
                        ),
                    }
                )
    if not rows:
        raise ValueError("no V4 flash-LP mechanism regressions were estimated")
    return pd.DataFrame(rows)


def support_record(
    *,
    flash: pd.DataFrame,
    flow: pd.DataFrame,
    actions: pd.DataFrame,
    tvl: pd.DataFrame,
    panel: pd.DataFrame,
    results: pd.DataFrame,
) -> dict[str, object]:
    return {
        "record_type": "v4_flash_lp_mechanism_support",
        "analysis_status": "exploratory_mechanism",
        "candidate_days": int(panel[["origin_date", "candidate_address"]].drop_duplicates().shape[0]),
        "horizon_rows": int(len(panel)),
        "result_rows": int(len(results)),
        "candidate_count": int(panel["candidate_address"].nunique()),
        "first_date": panel["origin_date"].min().strftime("%Y-%m-%d"),
        "last_date": panel["origin_date"].max().strftime("%Y-%m-%d"),
        "flash_rows": int(len(flash)),
        "flow_rows": int(len(flow)),
        "action_rows": int(len(actions)),
        "tvl_rows": int(len(tvl)),
        "valid_tvl_rows": int(tvl["capital_valid"].astype(bool).sum()),
        "horizons": ",".join(str(value) for value in HORIZONS),
        "predictors": "+".join(PREDICTORS),
        "outcomes": "+".join(OUTCOMES),
        "fixed_effects": "candidate+origin_date",
        "cluster": "origin_date",
        "quantity": (
            "V4 singleton netting proxies matched to candidate-side LP USD flows, "
            "LP action/range counts, and screened candidate-linked pool TVL"
        ),
    }


def run(
    *,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
    flash_path: Path = FLASH_INPUT,
    flow_path: Path = LP_FLOW_INPUT,
    action_path: Path = LP_ACTION_INPUT,
    tvl_path: Path = POOL_TVL_INPUT,
) -> int:
    flash, flow, actions, tvl = load_inputs(
        flash_path=flash_path,
        flow_path=flow_path,
        action_path=action_path,
        tvl_path=tvl_path,
    )
    panel = build_mechanism_panel(flash, flow, actions, tvl)
    results = fit_mechanism_regressions(panel)
    support = pd.DataFrame(
        [
            support_record(
                flash=flash,
                flow=flow,
                actions=actions,
                tvl=tvl,
                panel=panel,
                results=results,
            )
        ]
    )
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(support, support_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    display_output = result_output.resolve()
    try:
        display_output = display_output.relative_to(REPO_ROOT)
    except ValueError:
        pass
    print(
        f"wrote {len(results):,} V4 flash-LP mechanism rows to "
        f"{display_output}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    parser.add_argument("--flash", type=Path, default=FLASH_INPUT)
    parser.add_argument("--flow", type=Path, default=LP_FLOW_INPUT)
    parser.add_argument("--actions", type=Path, default=LP_ACTION_INPUT)
    parser.add_argument("--tvl", type=Path, default=POOL_TVL_INPUT)
    args = parser.parse_args()
    return run(
        result_output=args.result_output,
        support_output=args.support_output,
        flash_path=args.flash,
        flow_path=args.flow,
        action_path=args.actions,
        tvl_path=args.tvl,
    )


if __name__ == "__main__":
    raise SystemExit(main())

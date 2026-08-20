#!/usr/bin/env python3
"""Compare internal routing and later LP participation in V3 and V4.

The unit is a stacked protocol-candidate-day row on dates with positive swap
activity for the same candidate in both protocols.  Internal same-asset routing
is constructed identically from protocol-specific swap legs.  Liquidity actions
use nonzero mint, burn, or modify-liquidity events and transaction origins.

The regression first differences V4 and V3 outcomes for the same candidate and
day, then absorbs candidate and date effects.  Activity controls receive
protocol-specific slopes.  The coefficient of interest is the difference between
the V4 and V3 internal-routing slopes.  It is a protocol contrast, not a causal
effect of V4 adoption or proof of beneficial LP ownership.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
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
from scripts.analyze.run_v4_lp_volatility_state import (
    PRIMARY_STATE_DAYS,
    WETH_INTRADAY_INPUT,
    attach_volatility_state,
    load_lagged_weth_volatility,
)


V3_ROUTING_INPUT = REPO_ROOT / "data/processed/v3_internal_routing_candidate_daily.parquet"
V4_ROUTING_INPUT = REPO_ROOT / "data/processed/v4_flash_accounting_candidate_daily.parquet"
ORIGIN_ACTION_INPUT = (
    REPO_ROOT / "data/processed/v3_v4_lp_origin_candidate_daily.parquet"
)
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/v3_v4_internal_routing_participation.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_v4_internal_routing_participation_support.jsonl"

NEAR_DAYS = 30
LATE_DAYS = 120
PRIMARY_PRIOR_DAYS = 180
ROBUSTNESS_PRIOR_DAYS = 90
OUTCOMES = (
    "near_log1p_incumbent_actions",
    "late_log1p_first_active_origins",
)
CONTROLS = (
    "multi_leg_tx_share",
    "log1p_candidate_tx_count",
    "log1p_prior_30d_actions",
)

CODE_SOURCES = [
    "scripts/analyze/run_v3_v4_internal_routing_participation.py",
    "scripts/process/build_v3_internal_routing_candidate_daily.py",
    "scripts/process/build_v3_v4_lp_origin_candidate_daily.py",
    "scripts/process/build_v4_flash_accounting_candidate_daily.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/processed/external_weth_usd_intraday.parquet",
    "data/processed/v3_internal_routing_candidate_daily.parquet",
    "data/processed/v4_flash_accounting_candidate_daily.parquet",
    "data/processed/v3_v4_lp_origin_candidate_daily.parquet",
]

OriginDaily = dict[str, dict[pd.Timestamp, dict[str, int]]]


def protocol_difference_data(panel: pd.DataFrame, outcome: str) -> pd.DataFrame:
    """Return one V4-minus-V3 row per paired candidate-day."""

    protocol_columns = [
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        outcome,
        "internal_tx_share",
        *CONTROLS,
    ]
    v3 = panel[panel["protocol"].eq("v3")][protocol_columns].copy()
    v4 = panel[panel["protocol"].eq("v4")][protocol_columns].copy()
    keys = ["origin_date", "candidate_address"]
    data = v3.merge(
        v4,
        on=keys,
        how="inner",
        suffixes=("_v3", "_v4"),
        validate="one_to_one",
    )
    data["outcome_difference"] = data[f"{outcome}_v4"] - data[f"{outcome}_v3"]
    data["v4_internal_tx_share"] = data["internal_tx_share_v4"]
    data["v3_internal_tx_share"] = data["internal_tx_share_v3"]
    for control in CONTROLS:
        data[f"v4_{control}"] = data[f"{control}_v4"]
        data[f"v3_{control}"] = data[f"{control}_v3"]
    return data


def load_processed_origin_actions(
    path: Path = ORIGIN_ACTION_INPUT,
) -> tuple[OriginDaily, OriginDaily, dict[str, object]]:
    """Load processed nonzero LP actions for V3 and V4."""

    required = {
        "protocol",
        "candidate_address",
        "origin_date",
        "origin",
        "action_count",
    }
    frame = pd.read_parquet(path)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"processed origin-action panel lacks columns: {missing}")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=list(required))
    frame["protocol"] = frame["protocol"].astype(str).str.lower()
    frame["candidate_address"] = frame["candidate_address"].astype(str).str.lower()
    frame["origin"] = frame["origin"].astype(str).str.lower()
    frame["origin_date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
    frame["action_count"] = frame["action_count"].astype(int)
    if frame["action_count"].le(0).any():
        raise ValueError("processed origin-action counts must be positive")
    if set(frame["protocol"]) != {"v3", "v4"}:
        raise ValueError("processed origin-action panel must contain V3 and V4")
    daily_by_protocol: dict[str, OriginDaily] = {}
    support: dict[str, object] = {}
    for protocol in ("v3", "v4"):
        subset = frame[frame["protocol"].eq(protocol)]
        daily: OriginDaily = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        for row in subset.itertuples(index=False):
            daily[row.candidate_address][row.origin_date][row.origin] += int(
                row.action_count
            )
        daily_by_protocol[protocol] = daily
        support[protocol] = {
            "candidate_day_origin_rows": int(len(subset)),
            "candidate_event_assignments": int(subset["action_count"].sum()),
            "candidates": int(subset["candidate_address"].nunique()),
            "dates": int(subset["origin_date"].nunique()),
        }
    return daily_by_protocol["v3"], daily_by_protocol["v4"], support


def load_common_routing_days(
    *,
    v3_path: Path = V3_ROUTING_INPUT,
    v4_path: Path = V4_ROUTING_INPUT,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Return positive-activity candidate-days observed in both protocols."""

    columns = [
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "candidate_tx_count",
        "swap_leg_assignments",
        "multi_leg_tx_share",
        "internal_tx_share",
    ]
    v3 = pd.read_parquet(v3_path, columns=columns)
    v4 = pd.read_parquet(v4_path, columns=columns)
    for frame in (v3, v4):
        frame["origin_date"] = pd.to_datetime(frame["origin_date"]).dt.normalize()
        frame["candidate_address"] = frame["candidate_address"].astype(str).str.lower()
    v3 = v3[v3["candidate_tx_count"].astype(float) > 0].copy()
    v4 = v4[v4["candidate_tx_count"].astype(float) > 0].copy()
    keys = ["origin_date", "candidate_address"]
    common = v3[keys].merge(v4[keys], on=keys, how="inner").drop_duplicates()
    if common.empty:
        raise ValueError("V3 and V4 have no common positive-routing candidate-days")
    v3 = v3.merge(common, on=keys, how="inner", validate="one_to_one")
    v4 = v4.merge(common, on=keys, how="inner", validate="one_to_one")
    support = {
        "common_candidate_days": int(len(common)),
        "common_dates": int(common["origin_date"].nunique()),
        "common_candidates": int(common["candidate_address"].nunique()),
    }
    return v3, v4, support


def build_protocol_timing_panel(
    daily: OriginDaily,
    routing: pd.DataFrame,
    *,
    protocol: str,
    prior_days: int,
    near_days: int = NEAR_DAYS,
    late_days: int = LATE_DAYS,
) -> pd.DataFrame:
    """Attach incumbent and first-active future outcomes to routing days."""

    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "candidate_tx_count",
        "swap_leg_assignments",
        "multi_leg_tx_share",
        "internal_tx_share",
    }
    missing = sorted(required - set(routing.columns))
    if missing:
        raise ValueError(f"{protocol} routing panel lacks columns: {missing}")
    if not 0 < near_days < late_days or prior_days <= 0:
        raise ValueError("invalid participation timing windows")

    rows: list[dict[str, object]] = []
    for address, group in routing.groupby("candidate_address", sort=True):
        address_daily = daily.get(str(address), {})
        active_dates = sorted(address_daily)
        if not active_dates:
            continue
        first_available = active_dates[0]
        last_available = active_dates[-1]
        for record in group.itertuples(index=False):
            date = pd.Timestamp(record.origin_date).normalize()
            if date < first_available + pd.Timedelta(days=prior_days):
                continue
            if date + pd.Timedelta(days=late_days) > last_available:
                continue
            prior_start = date - pd.Timedelta(days=prior_days)
            recent_start = date - pd.Timedelta(days=30)
            near_end = date + pd.Timedelta(days=near_days)
            late_end = date + pd.Timedelta(days=late_days)
            prior_origins: set[str] = set()
            recent_actions = 0
            near_counts: dict[str, int] = defaultdict(int)
            late_counts: dict[str, int] = defaultdict(int)
            for active_date in active_dates:
                if active_date < prior_start:
                    continue
                if active_date <= date:
                    prior_origins.update(address_daily[active_date])
                    if active_date >= recent_start:
                        recent_actions += sum(address_daily[active_date].values())
                elif active_date <= near_end:
                    for origin, count in address_daily[active_date].items():
                        near_counts[origin] += count
                elif active_date <= late_end:
                    for origin, count in address_daily[active_date].items():
                        late_counts[origin] += count
                else:
                    break
            current = address_daily.get(date, {})
            near_incumbent_actions = sum(
                count for origin, count in near_counts.items() if origin in prior_origins
            )
            late_first_active = set(late_counts) - prior_origins - set(near_counts)
            rows.append(
                {
                    "origin_date": date,
                    "candidate_address": str(address),
                    "candidate_symbol": str(record.candidate_symbol),
                    "protocol": protocol,
                    "is_v4": float(protocol == "v4"),
                    "prior_days": int(prior_days),
                    "internal_tx_share": float(record.internal_tx_share),
                    "multi_leg_tx_share": float(record.multi_leg_tx_share),
                    "log1p_candidate_tx_count": np.log1p(float(record.candidate_tx_count)),
                    "log1p_swap_leg_assignments": np.log1p(
                        float(record.swap_leg_assignments)
                    ),
                    "log1p_current_actions": np.log1p(sum(current.values())),
                    "log1p_current_origins": np.log1p(len(current)),
                    "log1p_prior_30d_actions": np.log1p(recent_actions),
                    "near_log1p_incumbent_actions": np.log1p(
                        near_incumbent_actions
                    ),
                    "late_log1p_first_active_origins": np.log1p(
                        len(late_first_active)
                    ),
                }
            )
    if not rows:
        raise ValueError(f"{protocol} participation timing panel is empty")
    return pd.DataFrame(rows)


def stack_protocol_panels(v3: pd.DataFrame, v4: pd.DataFrame) -> pd.DataFrame:
    """Keep paired candidate-days for the first-difference comparison."""

    keys = ["origin_date", "candidate_address"]
    paired = v3[keys].merge(v4[keys], on=keys, how="inner").drop_duplicates()
    v3 = v3.merge(paired, on=keys, how="inner", validate="one_to_one")
    v4 = v4.merge(paired, on=keys, how="inner", validate="one_to_one")
    stacked = pd.concat([v3, v4], ignore_index=True, sort=False)
    stacked["candidate_date_id"] = (
        stacked["candidate_address"].astype(str)
        + "|"
        + pd.to_datetime(stacked["origin_date"]).dt.strftime("%Y-%m-%d")
    )
    if stacked["candidate_date_id"].value_counts().ne(2).any():
        raise ValueError("protocol comparison requires one V3 and one V4 row per candidate-day")
    return stacked


def fit_protocol_comparison(
    panel: pd.DataFrame,
    *,
    sample_variant: str,
    outcomes: Sequence[str] = OUTCOMES,
    min_observations: int = 300,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Estimate the V4-minus-V3 difference in the internal-routing slope."""

    rows: list[dict[str, object]] = []
    for outcome in outcomes:
        data = protocol_difference_data(panel, outcome)
        keys = ["origin_date", "candidate_address"]
        terms = [
            "v4_internal_tx_share",
            "v3_internal_tx_share",
            *(f"v4_{control}" for control in CONTROLS),
            *(f"v3_{control}" for control in CONTROLS),
        ]
        columns = ["outcome_difference", *terms]
        data = data.replace([np.inf, -np.inf], np.nan).dropna(
            subset=[*keys, "candidate_symbol_v4", *columns]
        )
        residual = absorb_fixed_effects(
            data[columns], data["candidate_address"], data["origin_date"]
        )
        design = residual[terms].to_numpy(float)
        if np.linalg.matrix_rank(design) != len(terms):
            raise ValueError("protocol-comparison design is rank deficient")
        fit = ols_clustered(
            residual["outcome_difference"],
            residual[terms],
            data["origin_date"],
            add_constant=False,
            absorbed_groups=(data["candidate_address"], data["origin_date"]),
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        v4_index = terms.index("v4_internal_tx_share")
        v3_index = terms.index("v3_internal_tx_share")
        v4_slope = float(fit.beta[v4_index])
        v3_slope = -float(fit.beta[v3_index])
        contrast_weights = np.zeros(len(terms), dtype=float)
        contrast_weights[v4_index] = 1.0
        contrast_weights[v3_index] = 1.0
        slope_difference = linear_contrast(fit, contrast_weights)
        rows.append(
            {
                "record_type": "v3_v4_internal_routing_participation_regression",
                "analysis_status": "exploratory_protocol_contrast",
                "sample_variant": sample_variant,
                "outcome": outcome,
                "v3_slope_per_10pp": 0.1 * v3_slope,
                "v3_standard_error_per_10pp": 0.1
                * float(fit.standard_errors[v3_index]),
                "v3_slope_p_value": float(fit.p_values[v3_index]),
                "v4_slope_per_10pp": 0.1 * v4_slope,
                "v4_standard_error_per_10pp": 0.1
                * float(fit.standard_errors[v4_index]),
                "v4_slope_p_value": float(fit.p_values[v4_index]),
                "v4_minus_v3_per_10pp": 0.1 * slope_difference.estimate,
                "v4_minus_v3_standard_error_per_10pp": 0.1
                * slope_difference.standard_error,
                "v4_minus_v3_p_value": slope_difference.p_value,
                "n_observations": int(fit.n_observations),
                "candidate_days": int(len(data)),
                "date_clusters": int(fit.n_clusters),
                "sample_start_date": str(data["origin_date"].min().date()),
                "sample_end_date": str(data["origin_date"].max().date()),
                "fixed_effects": "candidate+origin_date_after_protocol_difference",
                "controls": "+".join(CONTROLS),
                "control_slopes": "protocol_specific",
                "interpretation": (
                    "V4-minus-V3 difference in the association between "
                    "protocol-specific internal routing and later transaction-origin "
                    "participation; predictive protocol contrast, not causal adoption"
                ),
            }
        )
    result = pd.DataFrame(rows)
    result["v4_minus_v3_holm_p_value"] = holm_adjusted_pvalues(
        result["v4_minus_v3_p_value"]
    )
    return result


def fit_protocol_volatility_comparison(
    panel: pd.DataFrame,
    volatility: pd.DataFrame,
    *,
    sample_variant: str,
    state_window_days: int = PRIMARY_STATE_DAYS,
    outcomes: Sequence[str] = OUTCOMES,
    min_observations: int = 300,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Compare V3 and V4 routing slopes as persistent volatility changes."""

    rows: list[dict[str, object]] = []
    for outcome in outcomes:
        data = attach_volatility_state(
            protocol_difference_data(panel, outcome),
            volatility,
            state_window_days=state_window_days,
        )
        main_terms = ["v4_internal_tx_share", "v3_internal_tx_share"]
        interaction_terms: list[str] = []
        for protocol in ("v4", "v3"):
            term = f"{protocol}_internal_x_weth_volatility"
            data[term] = (
                data[f"{protocol}_internal_tx_share"]
                * data["weth_volatility_z"]
            )
            interaction_terms.append(term)
        control_terms = [
            *(f"v4_{control}" for control in CONTROLS),
            *(f"v3_{control}" for control in CONTROLS),
        ]
        control_state_terms: list[str] = []
        for term in control_terms:
            state_term = f"{term}_x_weth_volatility"
            data[state_term] = data[term] * data["weth_volatility_z"]
            control_state_terms.append(state_term)
        candidate_state_terms: list[str] = []
        symbols = sorted(data["candidate_symbol_v4"].astype(str).unique())
        for symbol in symbols[1:]:
            term = f"candidate_{symbol.lower()}_x_weth_volatility"
            data[term] = (
                data["candidate_symbol_v4"].eq(symbol).astype(float)
                * data["weth_volatility_z"]
            )
            candidate_state_terms.append(term)
        terms = [
            *main_terms,
            *interaction_terms,
            *control_terms,
            *control_state_terms,
            *candidate_state_terms,
        ]
        columns = ["outcome_difference", *terms]
        data = data.replace([np.inf, -np.inf], np.nan).dropna(
            subset=["origin_date", "candidate_address", *columns]
        )
        residual = absorb_fixed_effects(
            data[columns], data["candidate_address"], data["origin_date"]
        )
        design = residual[terms].to_numpy(float)
        if np.linalg.matrix_rank(design) != len(terms):
            raise ValueError("protocol-state comparison design is rank deficient")
        fit = ols_clustered(
            residual["outcome_difference"],
            residual[terms],
            data["origin_date"],
            add_constant=False,
            absorbed_groups=(data["candidate_address"], data["origin_date"]),
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        v4_main_index = terms.index("v4_internal_tx_share")
        v3_main_index = terms.index("v3_internal_tx_share")
        v4_state_index = terms.index("v4_internal_x_weth_volatility")
        v3_state_index = terms.index("v3_internal_x_weth_volatility")
        weights = np.zeros(len(terms), dtype=float)
        weights[v4_state_index] = 1.0
        weights[v3_state_index] = 1.0
        state_difference = linear_contrast(fit, weights)
        rows.append(
            {
                "record_type": "v3_v4_internal_routing_volatility_regression",
                "analysis_status": "exploratory_protocol_state_contrast",
                "sample_variant": sample_variant,
                "state_window_days": int(state_window_days),
                "outcome": outcome,
                "v3_main_slope_per_10pp": -0.1 * float(fit.beta[v3_main_index]),
                "v4_main_slope_per_10pp": 0.1 * float(fit.beta[v4_main_index]),
                "v3_state_interaction_per_10pp_per_1sd": -0.1
                * float(fit.beta[v3_state_index]),
                "v3_state_interaction_standard_error": 0.1
                * float(fit.standard_errors[v3_state_index]),
                "v3_state_interaction_p_value": float(fit.p_values[v3_state_index]),
                "v4_state_interaction_per_10pp_per_1sd": 0.1
                * float(fit.beta[v4_state_index]),
                "v4_state_interaction_standard_error": 0.1
                * float(fit.standard_errors[v4_state_index]),
                "v4_state_interaction_p_value": float(fit.p_values[v4_state_index]),
                "v4_minus_v3_state_interaction_per_10pp_per_1sd": 0.1
                * state_difference.estimate,
                "v4_minus_v3_state_interaction_standard_error": 0.1
                * state_difference.standard_error,
                "v4_minus_v3_state_interaction_p_value": state_difference.p_value,
                "n_observations": int(fit.n_observations),
                "candidate_days": int(len(data)),
                "date_clusters": int(fit.n_clusters),
                "sample_start_date": str(data["origin_date"].min().date()),
                "sample_end_date": str(data["origin_date"].max().date()),
                "fixed_effects": "candidate+origin_date_after_protocol_difference",
                "controls": "+".join(CONTROLS),
                "state_controls": (
                    "candidate-specific+protocol-control-specific volatility slopes"
                ),
                "interpretation": (
                    "V4-minus-V3 difference in the change in routing-linked future "
                    "participation associated with one standard deviation more "
                    "lagged persistent volatility; predictive, not causal"
                ),
            }
        )
    result = pd.DataFrame(rows)
    result["v4_minus_v3_state_interaction_holm_p_value"] = holm_adjusted_pvalues(
        result["v4_minus_v3_state_interaction_p_value"]
    )
    return result


def run(
    *,
    v3_routing_path: Path = V3_ROUTING_INPUT,
    v4_routing_path: Path = V4_ROUTING_INPUT,
    origin_action_path: Path = ORIGIN_ACTION_INPUT,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> tuple[pd.DataFrame, dict[str, object]]:
    v3_routing, v4_routing, routing_support = load_common_routing_days(
        v3_path=v3_routing_path, v4_path=v4_routing_path
    )
    v3_daily, v4_daily, origin_support = load_processed_origin_actions(
        origin_action_path
    )
    volatility = load_lagged_weth_volatility(WETH_INTRADAY_INPUT)

    result_frames: list[pd.DataFrame] = []
    variant_support: dict[str, dict[str, int]] = {}
    stacked_variants: dict[str, pd.DataFrame] = {}
    for variant, prior_days in (
        ("primary_common_routing_180", PRIMARY_PRIOR_DAYS),
        ("common_routing_90", ROBUSTNESS_PRIOR_DAYS),
    ):
        v3_panel = build_protocol_timing_panel(
            v3_daily, v3_routing, protocol="v3", prior_days=prior_days
        )
        v4_panel = build_protocol_timing_panel(
            v4_daily, v4_routing, protocol="v4", prior_days=prior_days
        )
        stacked = stack_protocol_panels(v3_panel, v4_panel)
        stacked_variants[variant] = stacked
        result_frames.append(
            fit_protocol_comparison(stacked, sample_variant=variant)
        )
        candidate_days = int(stacked["candidate_date_id"].nunique())
        variant_support[variant] = {
            "candidate_days": candidate_days,
            "stacked_rows": int(len(stacked)),
            "dates": int(stacked["origin_date"].nunique()),
            "candidates": int(stacked["candidate_address"].nunique()),
            "prior_days": int(prior_days),
            "sample_start_date": str(stacked["origin_date"].min().date()),
            "sample_end_date": str(stacked["origin_date"].max().date()),
        }
        if variant == "primary_common_routing_180":
            for symbol in sorted(stacked["candidate_symbol"].unique()):
                leave_one = stacked[~stacked["candidate_symbol"].eq(symbol)].copy()
                result_frames.append(
                    fit_protocol_comparison(
                        leave_one,
                        sample_variant=f"primary_exclude_{symbol}",
                        min_observations=200,
                    )
                )

    primary_ids = set(
        stacked_variants["primary_common_routing_180"]["candidate_date_id"]
    )
    matched_90 = stacked_variants["common_routing_90"][
        stacked_variants["common_routing_90"]["candidate_date_id"].isin(primary_ids)
    ].copy()
    matched_variant = "common_routing_90_on_primary_calendar"
    result_frames.append(
        fit_protocol_comparison(matched_90, sample_variant=matched_variant)
    )
    variant_support[matched_variant] = {
        "candidate_days": int(matched_90["candidate_date_id"].nunique()),
        "stacked_rows": int(len(matched_90)),
        "dates": int(matched_90["origin_date"].nunique()),
        "candidates": int(matched_90["candidate_address"].nunique()),
        "prior_days": ROBUSTNESS_PRIOR_DAYS,
        "sample_start_date": str(matched_90["origin_date"].min().date()),
        "sample_end_date": str(matched_90["origin_date"].max().date()),
    }
    early_90 = stacked_variants["common_routing_90"][
        ~stacked_variants["common_routing_90"]["candidate_date_id"].isin(primary_ids)
    ].copy()
    early_variant = "common_routing_90_early_calendar"
    result_frames.append(
        fit_protocol_comparison(
            early_90,
            sample_variant=early_variant,
            min_observations=300,
        )
    )
    variant_support[early_variant] = {
        "candidate_days": int(early_90["candidate_date_id"].nunique()),
        "stacked_rows": int(len(early_90)),
        "dates": int(early_90["origin_date"].nunique()),
        "candidates": int(early_90["candidate_address"].nunique()),
        "prior_days": ROBUSTNESS_PRIOR_DAYS,
        "sample_start_date": str(early_90["origin_date"].min().date()),
        "sample_end_date": str(early_90["origin_date"].max().date()),
    }
    result_frames.append(
        fit_protocol_volatility_comparison(
            stacked_variants["primary_common_routing_180"],
            volatility,
            sample_variant="primary_common_routing_180_volatility_state",
        )
    )

    results = pd.concat(result_frames, ignore_index=True, sort=False)
    support = {
        "record_type": "v3_v4_internal_routing_participation_support",
        "analysis_status": "exploratory_protocol_contrast",
        **routing_support,
        "processed_origin_actions": origin_support,
        "near_window": "days_1_30",
        "late_window": "days_31_120",
        "primary_sample": "positive candidate transaction count in V3 and V4; nonzero LP actions; 180 prior days",
        "identity_boundary": (
            "transaction origin is a participation proxy, not verified beneficial "
            "ownership of an LP position"
        ),
        "multiple_testing": "Holm across the two interaction outcomes within each sample variant",
        "protocol_state_test": (
            "lagged 30-day mean daily realised WETH volatility; common mature "
            "calendar; candidate-specific and protocol-control-specific state slopes"
        ),
        "sample_variants": variant_support,
    }
    write_exhibit(results, result_output, code_sources=CODE_SOURCES, inputs=INPUTS)
    write_exhibit(
        pd.DataFrame([support]),
        support_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    return results, support


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3-routing", type=Path, default=V3_ROUTING_INPUT)
    parser.add_argument("--v4-routing", type=Path, default=V4_ROUTING_INPUT)
    parser.add_argument("--origin-actions", type=Path, default=ORIGIN_ACTION_INPUT)
    parser.add_argument("--output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    results, support = run(
        v3_routing_path=args.v3_routing,
        v4_routing_path=args.v4_routing,
        origin_action_path=args.origin_actions,
        result_output=args.output,
        support_output=args.support,
    )
    primary = results[
        results["record_type"].eq("v3_v4_internal_routing_participation_regression")
        & results["sample_variant"].eq("primary_common_routing_180")
    ]
    print(
        f"wrote {len(results):,} V3/V4 protocol-contrast estimates; "
        f"primary sample has {support['sample_variants']['primary_common_routing_180']['candidate_days']:,} candidate-days; "
        f"primary interactions {primary['v4_minus_v3_per_10pp'].round(4).tolist()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

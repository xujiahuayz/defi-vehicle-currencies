"""Non-closing exploratory sub-ledger for paired WETH-versus-comparator quotes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy import stats

from ddvc.analysis.dominance_cost_contract import (
    COMPARATOR_VEHICLES,
    NATIVE_VEHICLE,
    OUTCOME_REQUIRED_SUPPORT_STAGE,
    PAIR_CELL_KEYS,
)
from ddvc.analysis.regression import (
    ClusteredOLSResult,
    LinearContrastResult,
    absorb_fixed_effects,
    holm_adjusted_pvalues,
    joint_wald_f,
    linear_contrast,
    ols_clustered,
)
from ddvc.liquidity_predictability import LOOKAHEAD_SAFE_COVARIATE_COLUMNS
from ddvc.transaction_targets import EXACT_VENUES


PRIMARY_OUTCOME = "weth_symmetric_output_edge_bps"
LOG_OUTCOME = "weth_log_output_ratio"
SIGNED_OUTCOME = "weth_signed_win"
NOTIONAL_OUTCOME = "weth_output_gain_bps_of_notional"
DIRECT_OUTCOME = "weth_direct_threshold_edge"
OUTCOMES = (PRIMARY_OUTCOME, LOG_OUTCOME, SIGNED_OUTCOME, NOTIONAL_OUTCOME, DIRECT_OUTCOME)

RISK_CONTROLS = (
    "weth_minus_comparator_lag1_log_return",
    "weth_minus_comparator_lag1_trailing_30d_volatility",
)
USE_CONTROLS = (
    "weth_minus_comparator_lag1_intermediary_episode_share",
    "weth_minus_comparator_lag1_vehicle_excess_use_count_ratio",
    "weth_minus_comparator_lag1_log1p_route_total_count",
)
LIQUIDITY_MECHANISM_CONTROLS = (
    "weth_minus_comparator_lag1_v2_log1p_deposited_capital_usd",
    "weth_minus_comparator_lag1_v2_five_candidate_capital_share",
    "weth_minus_comparator_lag1_v3_signed_log1p_net_flow_per_1000",
    "weth_minus_comparator_lag1_v3_gross_candidate_flow_share",
)
HETEROGENEITY_CONTROLS = (
    "architecture_comparator_tick_only",
    "architecture_weth_tick_only",
    "architecture_both_constant_product",
    "candidate_breadth_3",
    "candidate_breadth_2",
    "stable_comparator_lag1_downside_log_return",
)
CALENDAR_YEARS = tuple(range(2020, 2027))
CALENDAR_YEAR_CONTROLS = tuple(f"calendar_year_{year}" for year in CALENDAR_YEARS[1:])
CONTROL_BLOCK_COLUMNS = {
    "risk": RISK_CONTROLS,
    "lagged_use": USE_CONTROLS,
    "lagged_liquidity_mechanism": LIQUIDITY_MECHANISM_CONTROLS,
    "architecture_breadth_depeg": HETEROGENEITY_CONTROLS,
    "calendar_year": CALENDAR_YEAR_CONTROLS,
}

CONTROL_SOURCE_COLUMNS = (
    "covariate_observation_cutoff_date",
    "covariate_lag_days",
    "lag1_candidate_log_return",
    "lag1_candidate_return_supported",
    "lag1_candidate_trailing_30d_volatility",
    "lag1_candidate_volatility_supported",
    "lag1_route_day_supported",
    "lag1_route_endpoint_supported",
    "lag1_intermediary_episode_share",
    "lag1_vehicle_excess_use_count_ratio",
    "lag1_route_total_count",
    "lag1_v2_capital_day_supported",
    "lag1_v2_log1p_deposited_capital_usd",
    "lag1_v2_five_candidate_capital_share",
    "lag1_v3_flow_day_supported",
    "lag1_v3_signed_log1p_net_flow_per_1000",
    "lag1_v3_gross_candidate_flow_share",
)
if not set(CONTROL_SOURCE_COLUMNS).issubset(LOOKAHEAD_SAFE_COVARIATE_COLUMNS):
    raise RuntimeError("dominance-cost exploratory controls escaped the canonical look-ahead-safe owner")

PAIR_REQUIRED_COLUMNS = {
    *PAIR_CELL_KEYS,
    "comparator_symbol",
    "available_candidate_count",
    "weth_hop1_source",
    "weth_hop2_source",
    "comparator_hop1_source",
    "comparator_hop2_source",
    *OUTCOMES,
}
CONTROL_REQUIRED_COLUMNS = {"origin_date", "candidate_address", "candidate_symbol", *CONTROL_SOURCE_COLUMNS}
TICK_VENUES = frozenset({"uniswap_v3", "uniswap_v4"})
STABLE_COMPARATORS = frozenset({"USDC", "USDT", "DAI"})
EXPLORATORY_STATUS = "exploratory_not_admissible"
PROVISIONAL_STATUS = "provisional_diagnostic_only"
ALLOWED_STATUSES = frozenset({EXPLORATORY_STATUS, PROVISIONAL_STATUS})
MIN_CLUSTER_COUNT = 20
STREAMING_MEMORY_LIMIT = "512MB"
SUBLEDGER_ID = "native_versus_comparator_indirect_cost_exploratory_subledger"
CAPABLE_OF_E0_CLOSURE = False
UNAVAILABLE_COVERAGE_GAPS = {
    "aggregator_attribution": ("validated_aggregator_identity", "validated_aggregator_adoption_date"),
    "contract_feasible_reach": ("observed_reach", "contract_feasible_reach"),
    "all_in_gas": ("gross_output", "route_gas_units", "effective_gas_price", "native_asset_usd"),
    "quote_validation": ("quote_reproduction_error_bps", "quote_support_status"),
}


@dataclass(frozen=True)
class FitSpecification:
    """One multivariate fit, counted once regardless of coefficient count."""

    spec_id: str
    outcome: str
    sample: str
    controls: tuple[str, ...]
    fixed_effects: tuple[str, ...]
    control_blocks: tuple[str, ...]


@dataclass(frozen=True)
class FittedSpecification:
    """A fitted ledger row plus the exact centering arithmetic."""

    fit: ClusteredOLSResult
    names: tuple[str, ...]
    dropped: tuple[str, ...]
    raw_control_means: dict[str, float]


FIT_LEDGER = (
    FitSpecification("dc00_full_primary", PRIMARY_OUTCOME, "primary_full", (), (), ("unadjusted",)),
    FitSpecification("dc01_risk_support_bridge", PRIMARY_OUTCOME, "risk_complete", (), (), ("risk_support_bridge",)),
    FitSpecification("dc02_risk_absorbed_slope_diagnostic", PRIMARY_OUTCOME, "risk_complete", RISK_CONTROLS, ("date", "quote_design_cell"), ("risk", "fe_slope_diagnostic", "stable_endpoint_comparator_notional_hour_design")),
    FitSpecification("dc03_risk_matched_symmetric", PRIMARY_OUTCOME, "risk_complete", RISK_CONTROLS, (), ("risk", "matched_cell")),
    FitSpecification("dc04_risk_matched_log", LOG_OUTCOME, "risk_complete", RISK_CONTROLS, (), ("risk", "matched_cell", "outcome_robustness")),
    FitSpecification("dc05_use_support_bridge", PRIMARY_OUTCOME, "use_complete", RISK_CONTROLS, (), ("risk", "use_support_bridge", "matched_cell")),
    FitSpecification("dc06_predetermined_use", PRIMARY_OUTCOME, "use_complete", (*RISK_CONTROLS, *USE_CONTROLS), (), ("risk", "lagged_use", "matched_cell")),
    FitSpecification("dc07_mechanism_support_bridge", PRIMARY_OUTCOME, "mechanism_complete", (*RISK_CONTROLS, *USE_CONTROLS), (), ("risk", "lagged_use", "mechanism_support_bridge", "matched_cell")),
    FitSpecification("dc08_lagged_liquidity_mechanism", PRIMARY_OUTCOME, "mechanism_complete", (*RISK_CONTROLS, *USE_CONTROLS, *LIQUIDITY_MECHANISM_CONTROLS), (), ("risk", "lagged_use", "lagged_liquidity_mechanism", "matched_cell")),
    FitSpecification("dc09_heterogeneity_support_bridge", PRIMARY_OUTCOME, "heterogeneity_complete", (*RISK_CONTROLS, *USE_CONTROLS), (), ("risk", "lagged_use", "heterogeneity_support_bridge", "matched_cell")),
    FitSpecification("dc10_architecture_breadth_depeg", PRIMARY_OUTCOME, "heterogeneity_complete", (*RISK_CONTROLS, *USE_CONTROLS, *HETEROGENEITY_CONTROLS), (), ("risk", "lagged_use", "architecture_breadth_depeg", "matched_cell")),
    FitSpecification("dc11_log_output_robustness", LOG_OUTCOME, "use_complete", (*RISK_CONTROLS, *USE_CONTROLS), (), ("risk", "lagged_use", "matched_cell", "outcome_robustness")),
    FitSpecification("dc12_signed_win_robustness", SIGNED_OUTCOME, "use_complete", (*RISK_CONTROLS, *USE_CONTROLS), (), ("risk", "lagged_use", "matched_cell", "outcome_robustness")),
    FitSpecification("dc13_notional_gain_robustness", NOTIONAL_OUTCOME, "use_complete", (*RISK_CONTROLS, *USE_CONTROLS), (), ("risk", "lagged_use", "matched_cell", "outcome_robustness")),
    FitSpecification("dc14_direct_threshold_support", DIRECT_OUTCOME, "direct_complete", (*RISK_CONTROLS, *USE_CONTROLS), (), ("risk", "lagged_use", "matched_cell", "direct_threshold")),
    FitSpecification("dc15_calendar_year_heterogeneity", PRIMARY_OUTCOME, "calendar_complete", CALENDAR_YEAR_CONTROLS, (), ("calendar_year", "time_heterogeneity_not_aggregator_attribution")),
    FitSpecification("dc16_calendar_year_stable_design_sensitivity", PRIMARY_OUTCOME, "calendar_complete", CALENDAR_YEAR_CONTROLS, ("quote_design_cell",), ("calendar_year", "stable_endpoint_comparator_notional_hour_design", "time_heterogeneity_not_aggregator_attribution")),
)
if len(FIT_LEDGER) != 17 or len({spec.spec_id for spec in FIT_LEDGER}) != 17:
    raise RuntimeError("dominance-cost exploratory sub-ledger must contain exactly seventeen unique fits")

PROVISIONAL_SUBSETS = {
    "unadjusted": ("dc00_full_primary",),
    "predetermined": (
        "dc00_full_primary",
        "dc01_risk_support_bridge",
        "dc02_risk_absorbed_slope_diagnostic",
        "dc03_risk_matched_symmetric",
        "dc04_risk_matched_log",
        "dc05_use_support_bridge",
        "dc06_predetermined_use",
        "dc11_log_output_robustness",
        "dc12_signed_win_robustness",
        "dc13_notional_gain_robustness",
        "dc14_direct_threshold_support",
        "dc15_calendar_year_heterogeneity",
        "dc16_calendar_year_stable_design_sensitivity",
    ),
    "all": tuple(spec.spec_id for spec in FIT_LEDGER),
}


def _required(frame: pd.DataFrame, required: Iterable[str], *, label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} lacks columns: {missing}")


def _finite(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    return pd.Series(np.isfinite(frame[list(columns)].to_numpy(dtype=float)).all(axis=1), index=frame.index)


def _prefixed_controls(controls: pd.DataFrame, prefix: str) -> pd.DataFrame:
    renamed = controls[["origin_date", "candidate_address", *CONTROL_SOURCE_COLUMNS]].copy()
    renamed = renamed.rename(columns={column: f"{prefix}_{column}" for column in CONTROL_SOURCE_COLUMNS})
    return renamed


def _numeric_domain(
    frame: pd.DataFrame,
    column: str,
    *,
    lower: float | None = None,
    upper: float | None = None,
) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    if np.isinf(values.to_numpy(dtype=float)).any():
        raise ValueError(f"candidate-day control contains infinite values: {column}")
    observed = values.notna()
    if lower is not None and (values.loc[observed] < lower).any():
        raise ValueError(f"candidate-day control violates its lower bound: {column}")
    if upper is not None and (values.loc[observed] > upper).any():
        raise ValueError(f"candidate-day control violates its upper bound: {column}")
    return values


def _validate_control_domains(controls: pd.DataFrame) -> None:
    flag_columns = (
        "lag1_candidate_return_supported",
        "lag1_candidate_volatility_supported",
        "lag1_route_day_supported",
        "lag1_route_endpoint_supported",
        "lag1_v2_capital_day_supported",
        "lag1_v3_flow_day_supported",
    )
    for column in flag_columns:
        if not controls[column].map(lambda value: isinstance(value, (bool, np.bool_))).all():
            raise ValueError(f"candidate-day support flag is not boolean: {column}")
    numeric = {
        "lag1_candidate_log_return": (None, None),
        "lag1_candidate_trailing_30d_volatility": (0.0, None),
        "lag1_intermediary_episode_share": (0.0, 1.0),
        "lag1_vehicle_excess_use_count_ratio": (0.0, None),
        "lag1_route_total_count": (0.0, None),
        "lag1_v2_log1p_deposited_capital_usd": (0.0, None),
        "lag1_v2_five_candidate_capital_share": (0.0, 1.0),
        "lag1_v3_signed_log1p_net_flow_per_1000": (None, None),
        "lag1_v3_gross_candidate_flow_share": (0.0, 1.0),
    }
    values = {
        column: _numeric_domain(controls, column, lower=bounds[0], upper=bounds[1])
        for column, bounds in numeric.items()
    }
    supported_fields = (
        ("lag1_candidate_return_supported", ("lag1_candidate_log_return",)),
        ("lag1_candidate_volatility_supported", ("lag1_candidate_trailing_30d_volatility",)),
        (
            "lag1_route_endpoint_supported",
            (
                "lag1_intermediary_episode_share",
                "lag1_vehicle_excess_use_count_ratio",
                "lag1_route_total_count",
            ),
        ),
        (
            "lag1_v2_capital_day_supported",
            ("lag1_v2_log1p_deposited_capital_usd", "lag1_v2_five_candidate_capital_share"),
        ),
        (
            "lag1_v3_flow_day_supported",
            ("lag1_v3_signed_log1p_net_flow_per_1000", "lag1_v3_gross_candidate_flow_share"),
        ),
    )
    for flag, columns in supported_fields:
        support = controls[flag].astype(bool)
        for column in columns:
            if values[column].loc[support].isna().any():
                raise ValueError(f"candidate-day supported control is missing: {flag}/{column}")


def _validate_inputs(pair_panel: pd.DataFrame, candidate_day: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    _required(pair_panel, PAIR_REQUIRED_COLUMNS, label="dominance-cost pair panel")
    pair = pair_panel.copy()
    pair["date"] = pd.to_datetime(pair["date"], errors="coerce").dt.normalize()
    for column in ("src", "tgt", "comparator"):
        pair[column] = pair[column].astype(str).str.lower()
    if pair.empty or pair["date"].isna().any() or pair.duplicated(list(PAIR_CELL_KEYS)).any():
        raise ValueError("dominance-cost pair panel has invalid dates, duplicate keys, or no rows")
    expected_comparator_symbols = pair["comparator"].map(COMPARATOR_VEHICLES)
    if expected_comparator_symbols.isna().any() or not pair["comparator_symbol"].astype(str).eq(expected_comparator_symbols).all():
        raise ValueError("dominance-cost comparator address-symbol mapping is invalid")
    source_columns = (
        "weth_hop1_source",
        "weth_hop2_source",
        "comparator_hop1_source",
        "comparator_hop2_source",
    )
    if any(not pair[column].isin(EXACT_VENUES).all() for column in source_columns):
        raise ValueError("dominance-cost pair panel contains an unknown architecture source")
    candidate_count = pd.to_numeric(pair["available_candidate_count"], errors="coerce")
    if candidate_count.isna().any() or not candidate_count.between(2, 5).all() or not candidate_count.eq(candidate_count.astype(int)).all():
        raise ValueError("dominance-cost available-candidate count is outside two through five")
    trade_size = pd.to_numeric(pair["trade_size_usd"], errors="coerce")
    if trade_size.isna().any() or not np.isfinite(trade_size).all() or not trade_size.gt(0).all():
        raise ValueError("dominance-cost trade size must be finite and positive")
    reserve_hour = pd.to_numeric(pair["reserve_hour_utc"], errors="coerce")
    if reserve_hour.isna().any() or not np.isfinite(reserve_hour).all() or not reserve_hour.between(0, 23).all() or not reserve_hour.eq(np.floor(reserve_hour)).all():
        raise ValueError("dominance-cost reserve hour must be a finite integer from zero through twenty-three")
    pair["reserve_hour_utc"] = reserve_hour.astype(int)
    if not _finite(pair, (PRIMARY_OUTCOME, LOG_OUTCOME, SIGNED_OUTCOME, NOTIONAL_OUTCOME)).all():
        raise ValueError("dominance-cost pair panel contains nonfinite primary outcomes")
    if pair[PRIMARY_OUTCOME].abs().gt(20_000.0).any() or not pair[SIGNED_OUTCOME].isin((-1, 0, 1)).all():
        raise ValueError("dominance-cost pair panel violates an outcome domain")
    direct_observed = pair[DIRECT_OUTCOME].notna()
    if not pair.loc[direct_observed, DIRECT_OUTCOME].isin((-1, 0, 1)).all():
        raise ValueError("dominance-cost direct-threshold outcome violates its domain")
    if candidate_day is None:
        return pair, None
    _required(candidate_day, CONTROL_REQUIRED_COLUMNS, label="candidate-day control panel")
    controls = candidate_day.copy()
    controls["origin_date"] = pd.to_datetime(controls["origin_date"], errors="coerce").dt.normalize()
    controls["candidate_address"] = controls["candidate_address"].astype(str).str.lower()
    if controls.empty or controls["origin_date"].isna().any() or controls.duplicated(["origin_date", "candidate_address"]).any():
        raise ValueError("candidate-day control panel has invalid dates, duplicate keys, or no rows")
    cutoff = pd.to_datetime(controls["covariate_observation_cutoff_date"], errors="coerce").dt.normalize()
    if cutoff.isna().any() or not cutoff.equals(controls["origin_date"] - pd.Timedelta(days=1)) or not pd.to_numeric(controls["covariate_lag_days"], errors="coerce").eq(1).all():
        raise ValueError("candidate-day controls are not dated at the exact prior calendar day")
    expected_symbols = {NATIVE_VEHICLE: "WETH", **COMPARATOR_VEHICLES}
    locked = controls.loc[controls["candidate_address"].isin(expected_symbols)].copy()
    expected = locked["candidate_address"].map(expected_symbols)
    if locked.empty or not locked["candidate_symbol"].astype(str).eq(expected).all():
        raise ValueError("candidate-day control address-symbol mapping is invalid")
    native_controls = controls.loc[
        controls["candidate_address"].eq(NATIVE_VEHICLE), "candidate_symbol"
    ]
    if native_controls.empty or not native_controls.eq("WETH").all():
        raise ValueError("candidate-day native control identity is not WETH")
    _validate_control_domains(controls)
    return pair, controls


def prepare_analysis_panel(pair_panel: pd.DataFrame, candidate_day: pd.DataFrame | None) -> pd.DataFrame:
    """Join the canonical candidate-day controls twice without rebuilding any control."""

    pair, controls = _validate_inputs(pair_panel, candidate_day)
    pair["ordered_endpoint_pair"] = pair["src"] + "|" + pair["tgt"]
    pair["quote_design_cell"] = pair["ordered_endpoint_pair"] + "|" + pair["comparator"] + "|" + pair["trade_size_usd"].astype(str) + "|" + pair["reserve_hour_utc"].astype(str)
    pair["primary_full"] = _finite(pair, [PRIMARY_OUTCOME])
    pair["direct_outcome_supported"] = _finite(pair, [DIRECT_OUTCOME])
    years = pair["date"].dt.year
    if not years.isin(CALENDAR_YEARS).all():
        raise ValueError("dominance-cost dates fall outside the predeclared 2020-2026 calendar")
    for year in CALENDAR_YEARS[1:]:
        pair[f"calendar_year_{year}"] = years.eq(year).astype(float)
    pair["calendar_complete"] = pair["primary_full"]
    if controls is None:
        for sample in ("risk_complete", "use_complete", "mechanism_complete", "heterogeneity_complete", "direct_complete"):
            pair[sample] = False
        return pair

    comparator_controls = _prefixed_controls(controls, "comparator")
    pair = pair.merge(
        comparator_controls,
        left_on=["date", "comparator"],
        right_on=["origin_date", "candidate_address"],
        how="left",
        validate="many_to_one",
    ).drop(columns=["origin_date", "candidate_address"])
    weth_controls = _prefixed_controls(
        controls.loc[controls["candidate_address"].eq(NATIVE_VEHICLE)],
        "weth",
    )
    pair = pair.merge(
        weth_controls.drop(columns="candidate_address"),
        left_on="date",
        right_on="origin_date",
        how="left",
        validate="many_to_one",
    ).drop(columns="origin_date")

    pair[RISK_CONTROLS[0]] = pair["weth_lag1_candidate_log_return"] - pair["comparator_lag1_candidate_log_return"]
    pair[RISK_CONTROLS[1]] = pair["weth_lag1_candidate_trailing_30d_volatility"] - pair["comparator_lag1_candidate_trailing_30d_volatility"]
    pair[USE_CONTROLS[0]] = pair["weth_lag1_intermediary_episode_share"] - pair["comparator_lag1_intermediary_episode_share"]
    pair[USE_CONTROLS[1]] = pair["weth_lag1_vehicle_excess_use_count_ratio"] - pair["comparator_lag1_vehicle_excess_use_count_ratio"]
    pair[USE_CONTROLS[2]] = np.log1p(pair["weth_lag1_route_total_count"].astype(float)) - np.log1p(pair["comparator_lag1_route_total_count"].astype(float))
    for target, source in zip(
        LIQUIDITY_MECHANISM_CONTROLS,
        (
            "lag1_v2_log1p_deposited_capital_usd",
            "lag1_v2_five_candidate_capital_share",
            "lag1_v3_signed_log1p_net_flow_per_1000",
            "lag1_v3_gross_candidate_flow_share",
        ),
        strict=True,
    ):
        pair[target] = pair[f"weth_{source}"] - pair[f"comparator_{source}"]

    weth_tick = pair[["weth_hop1_source", "weth_hop2_source"]].isin(TICK_VENUES).any(axis=1)
    comparator_tick = pair[["comparator_hop1_source", "comparator_hop2_source"]].isin(TICK_VENUES).any(axis=1)
    pair["architecture_pair"] = np.select(
        [weth_tick & comparator_tick, weth_tick, comparator_tick],
        ["both_tick", "weth_tick_only", "comparator_tick_only"],
        default="both_constant_product",
    )
    breadth = pd.to_numeric(pair["available_candidate_count"], errors="coerce")
    pair["candidate_breadth"] = np.select([breadth.eq(2), breadth.eq(3), breadth.isin([4, 5])], ["2", "3", "4_5"], default=None)
    stable = pair["comparator_symbol"].isin(STABLE_COMPARATORS)
    pair["stable_comparator_lag1_downside_log_return"] = (-pair["comparator_lag1_candidate_log_return"]).clip(lower=0).where(stable, 0.0)

    architecture_dummies = pd.get_dummies(
        pd.Categorical(pair["architecture_pair"], categories=("both_tick", "comparator_tick_only", "weth_tick_only", "both_constant_product")),
        prefix="architecture",
        dtype=float,
    ).drop(columns="architecture_both_tick")
    breadth_dummies = pd.get_dummies(
        pd.Categorical(pair["candidate_breadth"], categories=("4_5", "3", "2")),
        prefix="candidate_breadth",
        dtype=float,
    ).drop(columns="candidate_breadth_4_5")
    pair = pd.concat([pair, architecture_dummies, breadth_dummies], axis=1)

    risk_support = (
        pair["weth_lag1_candidate_return_supported"].fillna(False).astype(bool)
        & pair["comparator_lag1_candidate_return_supported"].fillna(False).astype(bool)
        & pair["weth_lag1_candidate_volatility_supported"].fillna(False).astype(bool)
        & pair["comparator_lag1_candidate_volatility_supported"].fillna(False).astype(bool)
        & _finite(pair, RISK_CONTROLS)
    )
    use_support = (
        risk_support
        & pair["weth_lag1_route_day_supported"].fillna(False).astype(bool)
        & pair["comparator_lag1_route_day_supported"].fillna(False).astype(bool)
        & pair["weth_lag1_route_endpoint_supported"].fillna(False).astype(bool)
        & pair["comparator_lag1_route_endpoint_supported"].fillna(False).astype(bool)
        & _finite(pair, USE_CONTROLS)
    )
    mechanism_support = (
        use_support
        & pair["weth_lag1_v2_capital_day_supported"].fillna(False).astype(bool)
        & pair["comparator_lag1_v2_capital_day_supported"].fillna(False).astype(bool)
        & pair["weth_lag1_v3_flow_day_supported"].fillna(False).astype(bool)
        & pair["comparator_lag1_v3_flow_day_supported"].fillna(False).astype(bool)
        & _finite(pair, LIQUIDITY_MECHANISM_CONTROLS)
    )
    heterogeneity_support = (
        use_support
        & pair["candidate_breadth"].notna()
        & pair["architecture_pair"].notna()
        & _finite(pair, HETEROGENEITY_CONTROLS)
    )
    pair["risk_complete"] = pair["primary_full"] & risk_support
    pair["use_complete"] = pair["primary_full"] & use_support
    pair["mechanism_complete"] = pair["primary_full"] & mechanism_support
    pair["heterogeneity_complete"] = pair["primary_full"] & heterogeneity_support
    pair["direct_complete"] = pair["direct_outcome_supported"] & use_support
    member_source_columns = [
        f"{prefix}_{column}"
        for prefix in ("weth", "comparator")
        for column in CONTROL_SOURCE_COLUMNS
    ]
    return pair.drop(columns=member_source_columns)


def _design_matrix(frame: pd.DataFrame, controls: Sequence[str]) -> pd.DataFrame:
    if not controls:
        return pd.DataFrame(index=pd.RangeIndex(len(frame)))
    return frame[list(controls)].astype(float).reset_index(drop=True)


def _independent_columns(values: pd.DataFrame, required: set[str]) -> tuple[list[str], list[str]]:
    if values.shape[1] == 0:
        return [], []
    matrix = values.to_numpy(dtype=float)
    if set(values.columns) == required:
        rank = int(np.linalg.matrix_rank(matrix))
        if rank != values.shape[1]:
            raise ValueError("required dominance-cost regressors are collinear")
        return list(values.columns), []
    kept: list[str] = []
    dropped: list[str] = []
    rank = 0
    for column in values.columns:
        candidate = values[[*kept, column]].to_numpy(dtype=float)
        candidate_rank = int(np.linalg.matrix_rank(candidate))
        if candidate_rank > rank:
            kept.append(column)
            rank = candidate_rank
        elif column in required:
            raise ValueError(f"required dominance-cost regressor is absorbed or collinear: {column}")
        else:
            dropped.append(column)
    return kept, dropped


def _fit(frame: pd.DataFrame, spec: FitSpecification) -> FittedSpecification:
    y = frame[spec.outcome].astype(float).reset_index(drop=True)
    x = _design_matrix(frame, spec.controls)
    raw_control_means = {column: float(x[column].mean()) for column in x.columns}
    dates = frame["date"].reset_index(drop=True)
    endpoints = frame["ordered_endpoint_pair"].reset_index(drop=True)
    groups = tuple(frame[column].reset_index(drop=True) for column in spec.fixed_effects)
    if groups:
        y = absorb_fixed_effects(y, *groups)
        x = absorb_fixed_effects(x, *groups)
    elif spec.controls:
        x = x - pd.Series(raw_control_means)
    required = set(spec.controls)
    kept, dropped = _independent_columns(x, required)
    add_constant = not groups
    fit = ols_clustered(
        y,
        x[kept],
        dates,
        add_constant=add_constant,
        absorbed_groups=groups,
        additional_clusters=(endpoints,),
        min_observations=max(len(kept) + 2, 8),
        min_clusters=MIN_CLUSTER_COUNT,
    )
    if not np.isfinite(fit.beta).all() or not np.isfinite(fit.covariance).all():
        raise ValueError(f"dominance-cost specification is unidentified: {spec.spec_id}")
    names = tuple((["constant"] if add_constant else []) + kept)
    declared_variances = np.diag(fit.covariance)
    if not np.isfinite(declared_variances).all() or np.any(declared_variances <= 0):
        raise ValueError(
            f"dominance-cost specification has a non-positive or nonfinite declared coefficient variance: {spec.spec_id}"
        )
    return FittedSpecification(
        fit=fit,
        names=names,
        dropped=tuple(dropped),
        raw_control_means=raw_control_means,
    )


def sample_sha256(frame: pd.DataFrame) -> str:
    """Hash the exact sorted economic keys of one fitted sample."""

    keys = frame[list(PAIR_CELL_KEYS)].copy().sort_values(list(PAIR_CELL_KEYS), kind="stable")
    digest = hashlib.sha256()
    for row in keys.itertuples(index=False, name=None):
        digest.update("\x1f".join(str(value) for value in row).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _json_mapping(names: Sequence[str], values: Sequence[float]) -> str:
    return json.dumps({name: float(value) for name, value in zip(names, values, strict=True)}, sort_keys=True)


def _control_blocks(spec: FitSpecification) -> dict[str, tuple[str, ...]]:
    return {
        block: tuple(column for column in columns if column in spec.controls)
        for block, columns in CONTROL_BLOCK_COLUMNS.items()
        if any(column in spec.controls for column in columns)
    }


def _joint_tests(
    fitted: FittedSpecification, spec: FitSpecification
) -> dict[str, dict[str, float | int | str | None]]:
    tests: dict[str, dict[str, float | int | str | None]] = {}
    blocks = _control_blocks(spec)
    if spec.controls:
        blocks = {"all_declared_slopes": tuple(spec.controls), **blocks}
    for block, columns in blocks.items():
        try:
            statistic, numerator_df, denominator_df, p_value = joint_wald_f(
                fitted.fit, fitted.names, columns
            )
            tests[block] = {
                "status": "estimated",
                "f_statistic": statistic,
                "numerator_df": numerator_df,
                "denominator_df": denominator_df,
                "p_value": p_value,
                "reason": None,
            }
        except ValueError as error:
            tests[block] = {
                "status": "unavailable",
                "f_statistic": None,
                "numerator_df": len(columns),
                "denominator_df": fitted.fit.n_clusters - 1,
                "p_value": None,
                "reason": str(error),
            }
    return tests


def _decomposition(
    fitted: FittedSpecification, spec: FitSpecification
) -> tuple[float | None, dict[str, float], dict[str, float], float | None]:
    if spec.fixed_effects:
        return None, {}, {}, None
    coefficients = dict(zip(fitted.names, fitted.fit.beta, strict=True))
    contributions = {
        column: coefficients[column] * fitted.raw_control_means[column]
        for column in spec.controls
    }
    block_contributions = {
        block: float(sum(contributions[column] for column in columns))
        for block, columns in _control_blocks(spec).items()
    }
    centered_intercept = coefficients["constant"]
    zero_difference_intercept = float(centered_intercept - sum(contributions.values()))
    reconstructed_mean = float(zero_difference_intercept + sum(contributions.values()))
    return zero_difference_intercept, contributions, block_contributions, reconstructed_mean


def _contrast_record(result: LinearContrastResult) -> dict[str, float | int]:
    return {
        "estimate": float(result.estimate),
        "standard_error": float(result.standard_error),
        "t_statistic": float(result.t_statistic),
        "p_value": float(result.p_value),
        "confidence_interval_lower": float(result.confidence_interval_lower),
        "confidence_interval_upper": float(result.confidence_interval_upper),
        "degrees_freedom": int(result.degrees_freedom),
    }


def _decomposition_inference(
    fitted: FittedSpecification, spec: FitSpecification
) -> tuple[
    dict[str, float | int] | None,
    dict[str, float | int] | None,
    dict[str, dict[str, float | int]],
    tuple[str, ...],
    list[list[float]],
]:
    if spec.fixed_effects:
        return None, None, {}, (), []
    name_positions = {name: position for position, name in enumerate(fitted.names)}
    raw_mean_weights = np.zeros(len(fitted.names))
    raw_mean_weights[name_positions["constant"]] = 1.0
    raw_mean = linear_contrast(fitted.fit, raw_mean_weights)
    reference_weights = raw_mean_weights.copy()
    for column in spec.controls:
        reference_weights[name_positions[column]] = -fitted.raw_control_means[column]
    reference_profile = linear_contrast(fitted.fit, reference_weights)

    blocks = _control_blocks(spec)
    block_names = tuple(blocks)
    block_weights = np.zeros((len(block_names), len(fitted.names)))
    block_results: dict[str, dict[str, float | int]] = {}
    for row, block in enumerate(block_names):
        for column in blocks[block]:
            block_weights[row, name_positions[column]] = fitted.raw_control_means[column]
        block_results[block] = _contrast_record(
            linear_contrast(fitted.fit, block_weights[row])
        )
    block_covariance = block_weights @ fitted.fit.covariance @ block_weights.T
    block_covariance = (block_covariance + block_covariance.T) / 2
    if not np.isfinite(block_covariance).all():
        raise ValueError(
            f"dominance-cost block-contribution covariance is nonfinite: {spec.spec_id}"
        )
    return (
        _contrast_record(raw_mean),
        _contrast_record(reference_profile),
        block_results,
        block_names,
        block_covariance.tolist(),
    )


def _fixed_effect_support(frame: pd.DataFrame, spec: FitSpecification) -> dict[str, object]:
    if "quote_design_cell" not in spec.fixed_effects:
        return {}
    dates_per_cell = frame.groupby("quote_design_cell", sort=False)["date"].nunique()
    repeated = set(dates_per_cell.index[dates_per_cell.ge(2)])
    repeated_rows = frame["quote_design_cell"].isin(repeated)
    groups = tuple(frame[column].reset_index(drop=True) for column in spec.fixed_effects)
    within = absorb_fixed_effects(frame[list(spec.controls)].astype(float).reset_index(drop=True), *groups)
    within_rank = int(np.linalg.matrix_rank(within.to_numpy(dtype=float)))
    if not repeated or within_rank != len(spec.controls):
        raise ValueError(f"dominance-cost stable-design fixed effects lack identifying support: {spec.spec_id}")
    support = {
        "support_kind": "within_date_quote_design" if spec.spec_id == "dc02_risk_absorbed_slope_diagnostic" else "within_calendar_year_quote_design",
        "quote_design_cells": int(len(dates_per_cell)),
        "cells_observed_on_multiple_dates": int(len(repeated)),
        "observations_in_multiple_date_cells": int(repeated_rows.sum()),
        "share_in_multiple_date_cells": float(repeated_rows.mean()),
        "declared_regressors": len(spec.controls),
        "within_fixed_effect_regressor_rank": within_rank,
        "all_declared_regressors_identified": within_rank == len(spec.controls),
        "identification": "within stable quote-design cells over time",
    }
    if spec.spec_id == "dc16_calendar_year_stable_design_sensitivity":
        years_by_cell = frame.assign(calendar_year=frame["date"].dt.year).groupby("quote_design_cell", sort=False)["calendar_year"].agg(lambda values: frozenset(int(value) for value in values))
        spanning = set(years_by_cell.index[years_by_cell.map(len).ge(2)])
        spanning_rows = frame["quote_design_cell"].isin(spanning)
        bridge_counts = {
            f"{left}_{right}": int(sum(left in years and right in years for years in years_by_cell))
            for left, right in zip(CALENDAR_YEARS, CALENDAR_YEARS[1:])
        }
        if not spanning:
            raise ValueError("dominance-cost calendar-year sensitivity lacks cross-year quote-design support")
        support.update(
            {
                "cells_spanning_multiple_calendar_years": int(len(spanning)),
                "observations_in_multiple_calendar_year_cells": int(spanning_rows.sum()),
                "share_in_multiple_calendar_year_cells": float(spanning_rows.mean()),
                "adjacent_calendar_year_bridge_cell_counts": bridge_counts,
            }
        )
    return support


def reference_profile_definition(spec: FitSpecification) -> str:
    if spec.spec_id == "dc15_calendar_year_heterogeneity":
        return "2020 reference-year mean among raw quote attempts; later calendar-year indicators equal deviations from this reference"
    if spec.fixed_effects:
        return "not applicable because fixed-effect absorption removes an average reference-profile intercept"
    if not spec.controls:
        return "exact matched-pair raw mean on the fitted support"
    return "zero continuous WETH-minus-comparator attribute differences; architecture=both_tick, candidate breadth=4_5, and stable-comparator downside shock=zero where those regressors are present"


def specification_semantics(spec: FitSpecification) -> dict[str, object]:
    """Own the exact interpretation strings and ownership flags for one ledger row."""

    estimates_average_edge = not spec.fixed_effects
    auxiliary_scope = (
        "date and stable ordered-endpoint-pair-by-comparator-by-notional-by-reserve-hour fixed effects; candidate-day risk slopes are identified only by within-design-cell changes over time"
        if spec.spec_id == "dc02_risk_absorbed_slope_diagnostic"
        else "raw quote-attempt-composition year profile, not market maturation or aggregator attribution"
        if spec.spec_id == "dc15_calendar_year_heterogeneity"
        else "within stable ordered-endpoint-pair-by-comparator-by-notional-by-reserve-hour cells; not market maturation or aggregator attribution"
        if spec.spec_id == "dc16_calendar_year_stable_design_sensitivity"
        else None
    )
    return {
        "inference_owner": "pair_difference_regression_two_way_date_ordered_endpoint_pair_cr1",
        "controls_mean_centered": bool(spec.controls and estimates_average_edge),
        "estimand": "regression_adjusted_mean_at_sample_mean_covariates" if estimates_average_edge and spec.controls else "matched_pair_raw_mean" if estimates_average_edge else "conditional_slope_surface_no_average_weth_edge_coefficient",
        "auxiliary_scope": auxiliary_scope,
        "estimates_average_weth_edge": estimates_average_edge,
        "decomposition_status": "descriptive_not_causal" if estimates_average_edge else "not_applicable_to_absorbed_slope_diagnostic",
        "raw_mean_owner": "intercept_only_support_bridge" if estimates_average_edge and not spec.controls else "separate_intercept_only_support_bridge",
        "zero_difference_reference_category_profile_definition": reference_profile_definition(spec),
    }


def support_evidence(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    primary_rows = max(int(panel["primary_full"].sum()), 1)
    evidence_columns = list(dict.fromkeys([*PAIR_CELL_KEYS, "date", "ordered_endpoint_pair"]))
    for sample in ("primary_full", "calendar_complete", "risk_complete", "use_complete", "mechanism_complete", "heterogeneity_complete", "direct_complete"):
        selected = panel.loc[panel[sample].fillna(False).astype(bool), evidence_columns]
        rows.append(
            {
                "sample": sample,
                "observations": len(selected),
                "share_of_primary": len(selected) / primary_rows,
                "dates": selected["date"].nunique(),
                "ordered_endpoint_pairs": selected["ordered_endpoint_pair"].nunique(),
                "sample_sha256": sample_sha256(selected),
            }
        )
    return pd.DataFrame(rows)


def _streamed_sample_sha256(connection: duckdb.DuckDBPyConnection) -> str:
    """Hash canonical pair keys in bounded ordered batches."""

    query = """
        SELECT date || ' 00:00:00', CAST(CAST(reserve_hour_utc AS BIGINT) AS VARCHAR), LOWER(src), LOWER(tgt), CAST(trade_size_usd AS VARCHAR), LOWER(comparator)
        FROM pair
        ORDER BY date, CAST(reserve_hour_utc AS BIGINT), LOWER(src), LOWER(tgt), trade_size_usd, LOWER(comparator)
    """
    digest = hashlib.sha256()
    connection.execute(query)
    for batch in connection.to_arrow_reader(batch_size=65_536):
        columns = [column.to_pylist() for column in batch.columns]
        for row in zip(*columns, strict=True):
            digest.update("\x1f".join(row).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _empty_support_row(sample: str, primary_rows: int) -> dict[str, object]:
    return {
        "sample": sample,
        "observations": 0,
        "share_of_primary": 0.0 if primary_rows else 0.0,
        "dates": 0,
        "ordered_endpoint_pairs": 0,
        "sample_sha256": hashlib.sha256().hexdigest(),
    }


def fit_unadjusted_parquet(
    path: Path,
    *,
    status: str = PROVISIONAL_STATUS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit dc00 from bounded sufficient statistics without materializing route strings."""

    if status not in ALLOWED_STATUSES:
        raise ValueError(f"dominance-cost fit status is invalid: {status}")
    path = path.resolve()
    parquet = pq.ParquetFile(path)
    required = {*PAIR_CELL_KEYS, "comparator_symbol", PRIMARY_OUTCOME}
    missing = sorted(required - set(parquet.schema_arrow.names))
    if missing:
        raise ValueError(f"dominance-cost pair panel lacks columns: {missing}")
    with TemporaryDirectory(prefix="ddvc-e0-duck-") as temporary:
        connection = duckdb.connect()
        try:
            connection.execute(f"SET memory_limit='{STREAMING_MEMORY_LIMIT}'")
            connection.execute("SET threads=1")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute(f"SET temp_directory='{temporary}'")
            connection.from_parquet(str(path)).create_view("pair")
            row = connection.execute(
                f"""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE date IS NULL OR reserve_hour_utc IS NULL OR src IS NULL OR tgt IS NULL OR trade_size_usd IS NULL OR comparator IS NULL OR comparator_symbol IS NULL OR {PRIMARY_OUTCOME} IS NULL),
                       COUNT(*) FILTER (WHERE TRY_CAST(date AS DATE) IS NULL OR STRFTIME(TRY_CAST(date AS DATE), '%Y-%m-%d') <> date),
                       COUNT(*) FILTER (WHERE reserve_hour_utc IS NULL OR NOT ISFINITE(reserve_hour_utc) OR reserve_hour_utc < 0 OR reserve_hour_utc > 23 OR reserve_hour_utc <> FLOOR(reserve_hour_utc)),
                       COUNT(*) FILTER (WHERE NOT ISFINITE(trade_size_usd) OR trade_size_usd <= 0),
                       COUNT(*) FILTER (WHERE NOT ISFINITE({PRIMARY_OUTCOME}) OR ABS({PRIMARY_OUTCOME}) > 20000),
                       COUNT(*) FILTER (WHERE YEAR(TRY_CAST(date AS DATE)) NOT BETWEEN 2020 AND 2026)
                FROM pair
                """
            ).fetchone()
            if row is None or row[0] < 1:
                raise ValueError("dominance-cost pair panel has no rows")
            labels = ("required fields", "date", "reserve hour", "trade size", "primary outcome", "calendar")
            violations = [label for label, count in zip(labels, row[1:], strict=True) if count]
            if violations:
                raise ValueError(f"dominance-cost streamed input violates: {violations}")
            observed = {
                (str(address).lower(), str(symbol))
                for address, symbol in connection.execute("SELECT DISTINCT comparator, comparator_symbol FROM pair").fetchall()
            }
            expected = {(address, symbol) for address, symbol in COMPARATOR_VEHICLES.items()}
            if not observed or not observed.issubset(expected):
                raise ValueError("dominance-cost comparator address-symbol mapping is invalid")
            duplicate = connection.execute(
                """
                SELECT 1 FROM pair
                GROUP BY date, CAST(reserve_hour_utc AS BIGINT), LOWER(src), LOWER(tgt), trade_size_usd, LOWER(comparator)
                HAVING COUNT(*) > 1 LIMIT 1
                """
            ).fetchone()
            if duplicate is not None:
                raise ValueError("dominance-cost pair panel has duplicate canonical keys")

            y = pq.read_table(path, columns=[PRIMARY_OUTCOME]).column(0).combine_chunks().to_numpy(zero_copy_only=False)
            n = len(y)
            if n != int(row[0]):
                raise RuntimeError("dominance-cost streamed projection changed row count")
            coefficient = float((np.linalg.pinv(np.array([[float(n)]])) @ np.array([np.ones(n) @ y])).item())

            def cluster_meat(group_by: str) -> tuple[float, int]:
                value = connection.execute(
                    f"SELECT SUM(score * score), COUNT(*) FROM (SELECT SUM({PRIMARY_OUTCOME} - ?) AS score FROM pair GROUP BY {group_by})",
                    [coefficient],
                ).fetchone()
                if value is None:
                    raise RuntimeError("dominance-cost streamed cluster aggregation failed")
                return float(value[0]), int(value[1])

            date_meat, date_clusters = cluster_meat("date")
            endpoint_meat, endpoint_clusters = cluster_meat("LOWER(src), LOWER(tgt)")
            intersection_meat, intersection_clusters = cluster_meat("date, LOWER(src), LOWER(tgt)")
            if min(date_clusters, endpoint_clusters) < MIN_CLUSTER_COUNT:
                raise ValueError("dominance-cost streamed fit has too few clusters")
            covariance = (
                date_clusters / (date_clusters - 1) * date_meat
                + endpoint_clusters / (endpoint_clusters - 1) * endpoint_meat
                - intersection_clusters / (intersection_clusters - 1) * intersection_meat
            ) / n**2
            if not np.isfinite(covariance) or covariance <= 0:
                raise ValueError("dominance-cost streamed fit has invalid two-way CR1 variance")
            standard_error = float(np.sqrt(covariance))
            degrees_freedom = min(date_clusters, endpoint_clusters) - 1
            t_statistic = coefficient / standard_error
            p_value = float(2 * stats.t.sf(abs(t_statistic), degrees_freedom))
            critical = float(stats.t.ppf(0.975, degrees_freedom))
            contrast = {
                "estimate": coefficient,
                "standard_error": standard_error,
                "t_statistic": t_statistic,
                "p_value": p_value,
                "confidence_interval_lower": coefficient - critical * standard_error,
                "confidence_interval_upper": coefficient + critical * standard_error,
                "degrees_freedom": degrees_freedom,
            }
            sample_hash = _streamed_sample_sha256(connection)
            unconditional_mean = float(np.mean(y))
            n_pairs = int(connection.execute("SELECT COUNT(*) FROM (SELECT DISTINCT LOWER(src), LOWER(tgt) FROM pair)").fetchone()[0])
        finally:
            connection.close()

    semantics = specification_semantics(FIT_LEDGER[0])
    record = {
        "spec_id": "dc00_full_primary",
        "subledger_id": SUBLEDGER_ID,
        "capable_of_e0_closure": CAPABLE_OF_E0_CLOSURE,
        "status": status,
        "outcome": PRIMARY_OUTCOME,
        "support_stage": OUTCOME_REQUIRED_SUPPORT_STAGE[PRIMARY_OUTCOME],
        "sample": "primary_full",
        "sample_sha256": sample_hash,
        "n_observations": n,
        "n_dates": date_clusters,
        "n_ordered_endpoint_pairs": n_pairs,
        "cluster_counts": json.dumps([date_clusters, endpoint_clusters]),
        "clustering": "two_way_date_ordered_endpoint_pair_cr1",
        "inference_owner": semantics["inference_owner"],
        "fixed_effects": "[]",
        "control_blocks": json.dumps(["unadjusted"]),
        "controls": "[]",
        "controls_mean_centered": semantics["controls_mean_centered"],
        "estimand": semantics["estimand"],
        "auxiliary_scope": semantics["auxiliary_scope"],
        "estimates_average_weth_edge": semantics["estimates_average_weth_edge"],
        "exact_sample_unconditional_mean": unconditional_mean,
        "exact_sample_unconditional_median": float(np.median(y)),
        "exact_sample_unconditional_standard_deviation": float(np.std(y, ddof=1)),
        "decomposition_status": semantics["decomposition_status"],
        "raw_control_means": "{}",
        "zero_difference_reference_category_profile_estimate": coefficient,
        "zero_difference_reference_category_profile_definition": semantics["zero_difference_reference_category_profile_definition"],
        "raw_mean_owner": semantics["raw_mean_owner"],
        "raw_mean_inference": json.dumps(contrast, sort_keys=True),
        "regression_adjusted_mean_at_sample_means_inference": json.dumps(contrast, sort_keys=True),
        "zero_difference_reference_category_profile_inference": json.dumps(contrast, sort_keys=True),
        "control_contributions_to_raw_mean_gap": "{}",
        "block_contributions_to_raw_mean_gap": "{}",
        "block_contribution_contrast_inference": "{}",
        "block_contribution_covariance_labels": "[]",
        "block_contribution_covariance": "[]",
        "decomposition_reconstructed_mean": coefficient,
        "decomposition_identity_error": coefficient - unconditional_mean,
        "joint_slope_tests": "{}",
        "regressors": json.dumps(["constant"]),
        "dropped_collinear_design_columns": "[]",
        "coefficients": json.dumps({"constant": coefficient}, sort_keys=True),
        "standard_errors": json.dumps({"constant": standard_error}, sort_keys=True),
        "t_statistics": json.dumps({"constant": t_statistic}, sort_keys=True),
        "p_values": json.dumps({"constant": p_value}, sort_keys=True),
        "holm_p_values_within_fit_exploratory_only": json.dumps({"constant": p_value}, sort_keys=True),
        "fixed_effect_support": "{}",
    }
    support = [
        {"sample": "primary_full", "observations": n, "share_of_primary": 1.0, "dates": date_clusters, "ordered_endpoint_pairs": n_pairs, "sample_sha256": sample_hash},
        {"sample": "calendar_complete", "observations": n, "share_of_primary": 1.0, "dates": date_clusters, "ordered_endpoint_pairs": n_pairs, "sample_sha256": sample_hash},
        *[_empty_support_row(sample, n) for sample in ("risk_complete", "use_complete", "mechanism_complete", "heterogeneity_complete", "direct_complete")],
    ]
    return pd.DataFrame([record]), pd.DataFrame(support)


def fit_dominance_cost_e0(
    pair_panel: pd.DataFrame,
    candidate_day: pd.DataFrame | None,
    *,
    specification_ids: Sequence[str] | None = None,
    status: str = EXPLORATORY_STATUS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit a predeclared non-closing subset and return one row per multivariate fit."""

    if status not in ALLOWED_STATUSES:
        raise ValueError(f"dominance-cost fit status is invalid: {status}")
    panel = prepare_analysis_panel(pair_panel, candidate_day)
    selected_ids = (
        tuple(spec.spec_id for spec in FIT_LEDGER)
        if specification_ids is None
        else tuple(specification_ids)
    )
    unknown = sorted(set(selected_ids) - {spec.spec_id for spec in FIT_LEDGER})
    if not selected_ids or unknown or len(selected_ids) != len(set(selected_ids)):
        raise ValueError(f"dominance-cost fit subset is invalid: unknown={unknown}")
    support = support_evidence(panel)
    support_by_sample = support.set_index("sample")
    records = []
    for spec in FIT_LEDGER:
        if spec.spec_id not in selected_ids:
            continue
        fit_columns = list(dict.fromkeys([spec.outcome, "date", "ordered_endpoint_pair", *spec.controls, *spec.fixed_effects]))
        sample = panel.loc[
            panel[spec.sample].fillna(False).astype(bool), fit_columns
        ]
        if sample.empty:
            raise ValueError(f"dominance-cost specification has no supported observations: {spec.spec_id}")
        fitted = _fit(sample, spec)
        fit = fitted.fit
        names = fitted.names
        adjusted = holm_adjusted_pvalues(fit.p_values)
        unconditional = sample[spec.outcome].astype(float)
        unconditional_mean = float(unconditional.mean())
        semantics = specification_semantics(spec)
        estimates_average_edge = bool(semantics["estimates_average_weth_edge"])
        zero_intercept, contributions, block_contributions, reconstructed_mean = _decomposition(
            fitted, spec
        )
        (
            regression_adjusted_mean_inference,
            reference_profile_inference,
            block_contribution_inference,
            block_covariance_labels,
            block_contribution_covariance,
        ) = _decomposition_inference(fitted, spec)
        identity_error = (
            None if reconstructed_mean is None else reconstructed_mean - unconditional_mean
        )
        if identity_error is not None and abs(identity_error) > 1e-9 * max(abs(unconditional_mean), 1.0):
            raise RuntimeError(f"dominance-cost decomposition identity failed: {spec.spec_id}")
        if regression_adjusted_mean_inference is not None and abs(float(regression_adjusted_mean_inference["estimate"]) - unconditional_mean) > 1e-9 * max(abs(unconditional_mean), 1.0):
            raise RuntimeError(f"dominance-cost adjusted-mean contrast identity failed: {spec.spec_id}")
        raw_mean_inference = regression_adjusted_mean_inference if not spec.controls and not spec.fixed_effects else None
        records.append(
            {
                "spec_id": spec.spec_id,
                "subledger_id": SUBLEDGER_ID,
                "capable_of_e0_closure": CAPABLE_OF_E0_CLOSURE,
                "status": status,
                "outcome": spec.outcome,
                "support_stage": OUTCOME_REQUIRED_SUPPORT_STAGE[spec.outcome],
                "sample": spec.sample,
                "sample_sha256": support_by_sample.loc[spec.sample, "sample_sha256"],
                "n_observations": fit.n_observations,
                "n_dates": sample["date"].nunique(),
                "n_ordered_endpoint_pairs": sample["ordered_endpoint_pair"].nunique(),
                "cluster_counts": json.dumps(list(fit.cluster_counts)),
                "clustering": "two_way_date_ordered_endpoint_pair_cr1",
                "inference_owner": semantics["inference_owner"],
                "fixed_effects": json.dumps(list(spec.fixed_effects)),
                "control_blocks": json.dumps(list(spec.control_blocks)),
                "controls": json.dumps(list(spec.controls)),
                "controls_mean_centered": semantics["controls_mean_centered"],
                "estimand": semantics["estimand"],
                "auxiliary_scope": semantics["auxiliary_scope"],
                "estimates_average_weth_edge": semantics["estimates_average_weth_edge"],
                "exact_sample_unconditional_mean": unconditional_mean,
                "exact_sample_unconditional_median": float(unconditional.median()),
                "exact_sample_unconditional_standard_deviation": float(unconditional.std(ddof=1)),
                "decomposition_status": semantics["decomposition_status"],
                "raw_control_means": json.dumps(fitted.raw_control_means, sort_keys=True),
                "zero_difference_reference_category_profile_estimate": zero_intercept,
                "zero_difference_reference_category_profile_definition": semantics["zero_difference_reference_category_profile_definition"],
                "raw_mean_owner": semantics["raw_mean_owner"],
                "raw_mean_inference": json.dumps(raw_mean_inference, sort_keys=True),
                "regression_adjusted_mean_at_sample_means_inference": json.dumps(regression_adjusted_mean_inference, sort_keys=True),
                "zero_difference_reference_category_profile_inference": json.dumps(reference_profile_inference, sort_keys=True),
                "control_contributions_to_raw_mean_gap": json.dumps(contributions, sort_keys=True),
                "block_contributions_to_raw_mean_gap": json.dumps(block_contributions, sort_keys=True),
                "block_contribution_contrast_inference": json.dumps(block_contribution_inference, sort_keys=True),
                "block_contribution_covariance_labels": json.dumps(block_covariance_labels),
                "block_contribution_covariance": json.dumps(block_contribution_covariance),
                "decomposition_reconstructed_mean": reconstructed_mean,
                "decomposition_identity_error": identity_error,
                "joint_slope_tests": json.dumps(_joint_tests(fitted, spec), sort_keys=True),
                "regressors": json.dumps(names),
                "dropped_collinear_design_columns": json.dumps(fitted.dropped),
                "fixed_effect_support": json.dumps(_fixed_effect_support(sample, spec), sort_keys=True),
                "coefficients": _json_mapping(names, fit.beta),
                "standard_errors": _json_mapping(names, fit.standard_errors),
                "t_statistics": _json_mapping(names, fit.t_statistics),
                "p_values": _json_mapping(names, fit.p_values),
                "holm_p_values_within_fit_exploratory_only": _json_mapping(names, adjusted),
            }
        )
    results = pd.DataFrame(records)
    if len(results) != len(selected_ids) or set(results["spec_id"]) != set(selected_ids):
        raise RuntimeError("dominance-cost fitted perimeter is incomplete")
    return results, support

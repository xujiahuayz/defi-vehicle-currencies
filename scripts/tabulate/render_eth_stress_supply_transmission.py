#!/usr/bin/env python3
"""Render the ETH-stress LP-supply and execution-transmission appendix table."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ddvc.analysis.regression import holm_adjusted_pvalues
from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


LP_MODELS = OUTPUT_DIR / "exhibits/lp_stable_demand_stress_models.jsonl"
LP_SUPPORT = OUTPUT_DIR / "exhibits/lp_stable_demand_stress_support.jsonl"
CHAIN_MODELS = OUTPUT_DIR / "exhibits/eth_stress_executability.jsonl"
CHAIN_SUPPORT = OUTPUT_DIR / "exhibits/eth_stress_executability_support.jsonl"
INTRADAY_MODELS = (
    OUTPUT_DIR / "exhibits/eth_intraday_executable_route_chain.jsonl"
)
INTRADAY_SUPPORT = (
    OUTPUT_DIR / "exhibits/eth_intraday_executable_route_chain_support.jsonl"
)
VALUES_OUTPUT = (
    OUTPUT_DIR / "exhibits/eth_stress_supply_transmission_values.tex"
)


TABLE_NOTE = (
    "Panel A compares stablecoin-facing and WETH-facing pools for the same "
    "endpoint-week. ETH measures are dated $t$ and liquidity outcomes $t+1$. "
    "Additions and withdrawals use log one plus dollar flow divided by initial "
    "capital; net supply uses the inverse hyperbolic sine of the corresponding "
    "net flow. The v2 quantity divides net LP-token liquidity by initial "
    "square-root reserves. Pools have at least $50,000 of capital. Models include "
    "endpoint-by-week and pool fixed effects, prior fee yield, relative-price "
    "volatility, prior flows, capital, and pool age, and cluster standard errors "
    "by pool and week. The "
    "v3 net-supply response to an ETH decline has raw $p=0.017$ and Holm "
    "$p=0.067$; its addition and withdrawal components are individually "
    "imprecise. Panel B retains exact two-leg opportunities with both vehicle "
    "families feasible and positive prior-calendar weak-leg full-range capital. "
    "Capital is deposited Uniswap v2 and SushiSwap v2 capital on the weaker leg "
    "and records a mark-to-market pool state; Panel A measures provider flows. "
    "Output holds the pair, input, pre-transaction state, and venue set fixed. "
    "Models include pair and month-of-year fixed effects, log input value, ETH "
    "volatility, and calendar time, and cluster standard errors by pair and exact date. "
    "Panel C begins at the first strictly available Coinbase minute close at "
    "which ETH's trailing six-hour decline crosses 10%; events are at least "
    "48 hours apart. It quotes exact pre-transaction Uniswap v2 and SushiSwap "
    "v2 output at the observed notional from six hours before through 24 hours "
    "after each event. Models include event-by-pair and relative-hour effects and "
    "log input value; standard errors are clustered by event and pair. Four dates "
    "are excluded because conflicting event records prevent an unambiguous "
    "pre-transaction state. Stars in Panel A and the first rows of Panels B and C "
    "use Holm-adjusted p-values within their outcome families. Panel B's three "
    "capital--price--choice links form a separate Holm family; Panel C's "
    "output-to-choice row uses its raw p-value. Exact output measures the amount "
    "quoted at the observed trade size; depth beyond that notional lies outside "
    "the comparison. "
    r"Asterisks \(*\), \(**\), and \(***\) denote statistical significance "
    r"at the 10\%, 5\%, and 1\% levels, respectively. The estimates are predictive "
    "associations."
)


@dataclass(frozen=True)
class LPRow:
    venue: str
    outcome_name: str
    outcome: str
    family: str
    label: str
    macro_prefix: str


LP_ROWS: tuple[LPRow, ...] = (
    LPRow(
        "uniswap_v3",
        "additions",
        "next_log1p_add_flow_ratio",
        "primary_additions",
        r"v3 additions, $\ln(1+A/K)$",
        "EthStressVThreeAdditions",
    ),
    LPRow(
        "uniswap_v3",
        "withdrawals",
        "next_log1p_remove_flow_ratio",
        "secondary_withdrawals",
        r"v3 withdrawals, $\ln(1+W/K)$",
        "EthStressVThreeWithdrawals",
    ),
    LPRow(
        "uniswap_v3",
        "net_supply",
        "next_asinh_net_flow_ratio",
        "secondary_net_supply",
        r"v3 net supply, $\operatorname{asinh}((A-W)/K)$",
        "EthStressVThreeNetSupply",
    ),
    LPRow(
        "uniswap_v2",
        "v2_quantity_net_supply",
        "next_asinh_net_liquidity_ratio",
        "secondary_v2_quantity_net_supply",
        r"v2 net liquidity units, $\operatorname{asinh}(\Delta L/\sqrt{k})$",
        "EthStressVTwoNetLiquidity",
    ),
)

STRESS_COLUMNS: tuple[tuple[str, str, str], ...] = (
    (
        "stable_x_eth_realized_volatility",
        "10 pp higher ETH volatility",
        "Volatility",
    ),
    (
        "stable_x_eth_decline",
        "ETH price fall [0.10 log point]",
        "Decline",
    ),
)


@dataclass(frozen=True)
class ChainCell:
    model_id: str
    outcome: str
    predictor: str
    row: int
    column: int
    scale: float
    digits: int
    p_field: str
    macro_prefix: str


CHAIN_CELLS: tuple[ChainCell, ...] = (
    ChainCell(
        "m1_relative_usd_depth",
        "stable_minus_weth_log_v2_depth",
        "eth_decline_per_10pp",
        0,
        0,
        1.0,
        4,
        "holm_p_value",
        "EthStressDeclineRelativeDepth",
    ),
    ChainCell(
        "m2_exact_output_advantage",
        "stable_output_advantage_100bp",
        "eth_decline_per_10pp",
        0,
        1,
        100.0,
        2,
        "holm_p_value",
        "EthStressDeclineOutput",
    ),
    ChainCell(
        "m3_realised_stable_choice",
        "chosen_stable",
        "eth_decline_per_10pp",
        0,
        2,
        100.0,
        2,
        "holm_p_value",
        "EthStressDeclineChoice",
    ),
    ChainCell(
        "m4_output_advantage_conditioned_on_depth",
        "stable_output_advantage_100bp",
        "stable_v2_capital_advantage_10pp",
        1,
        1,
        100.0,
        2,
        "p_value",
        "EthStressDepthOutput",
    ),
    ChainCell(
        "m5_realised_choice_conditioned_on_output_and_depth",
        "chosen_stable",
        "stable_v2_capital_advantage_10pp",
        1,
        2,
        100.0,
        2,
        "p_value",
        "EthStressDepthChoice",
    ),
    ChainCell(
        "m5_realised_choice_conditioned_on_output_and_depth",
        "chosen_stable",
        "stable_output_advantage_100bp",
        2,
        2,
        100.0,
        2,
        "p_value",
        "EthStressOutputChoice",
    ),
)

CHAIN_ROW_LABELS = (
    r"ETH price fall, days $-30$ to $-1$ [0.10 log point]",
    r"Stable share of joint weak-leg USD capital [10 pp]",
    r"Stablecoin exact-output advantage [100 bp]",
)


@dataclass(frozen=True)
class IntradayCell:
    model_id: str
    outcome: str
    predictor: str
    row: int
    column: int
    scale: float
    digits: int
    p_field: str
    macro_prefix: str


INTRADAY_CELLS: tuple[IntradayCell, ...] = (
    IntradayCell(
        "m2_quote_pair_event_and_relative_hour",
        "stable_output_advantage_100bp",
        "eth_decline_6h_per_10pp",
        0,
        0,
        100.0,
        2,
        "holm_p_value",
        "EthIntradayDeclineOutput",
    ),
    IntradayCell(
        "m3_choice_pair_event_and_relative_hour",
        "chosen_stable",
        "eth_decline_6h_per_10pp",
        0,
        1,
        100.0,
        2,
        "holm_p_value",
        "EthIntradayDeclineChoice",
    ),
    IntradayCell(
        "m4_choice_conditioned_on_exact_quote",
        "chosen_stable",
        "stable_output_advantage_100bp",
        1,
        1,
        100.0,
        2,
        "p_value",
        "EthIntradayOutputChoice",
    ),
)

INTRADAY_ROW_LABELS = (
    r"ETH price fall, trailing six hours [0.10 log point]",
    r"Stablecoin exact-output advantage [100 bp]",
)


def _one(
    frame: pd.DataFrame,
    selector: dict[str, object],
    *,
    description: str,
) -> pd.Series:
    selected = frame
    for column, expected in selector.items():
        if column not in selected.columns:
            raise ValueError(f"{description} lacks selector column: {column}")
        selected = selected.loc[selected[column].eq(expected)]
    if len(selected) != 1:
        raise ValueError(
            f"expected one {description} row for {selector}; found {len(selected)}"
        )
    return selected.iloc[0]


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _cell(
    row: pd.Series,
    *,
    scale: float = 1.0,
    digits: int = 4,
    p_field: str = "holm_p_value",
) -> str:
    coefficient = scale * float(row["coefficient"])
    standard_error = scale * float(row["standard_error"])
    p_value = float(row[p_field])
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${coefficient:+.{digits}f}{_stars(p_value)}$"
        r"\\"
        f"$({standard_error:.{digits}f})$"
        r"\end{tabular}"
    )


def _macro(name: str, value: str) -> str:
    return f"\\newcommand{{\\{name}}}{{{value}}}"


def _tex_integer(value: object) -> str:
    return f"{int(round(float(value))):,}".replace(",", "{,}")


def _tex_p(value: object) -> str:
    numeric = float(value)
    if numeric < 0.001:
        return "$p<0.001$"
    return f"$p={numeric:.3f}$"


def _tex_p_value(value: object) -> str:
    """Return a bare value for prose that supplies its own punctuation."""

    numeric = float(value)
    if numeric < 0.001:
        return "$<0.001$"
    return f"${numeric:.3f}$"


def _tex_effect(
    row: pd.Series,
    *,
    scale: float,
    digits: int,
    unit: str = "",
) -> str:
    suffix = f" {unit}" if unit else ""
    return f"${scale * float(row['coefficient']):+.{digits}f}${suffix}"


def _tex_se(
    row: pd.Series,
    *,
    scale: float,
    digits: int,
    unit: str = "",
) -> str:
    suffix = f" {unit}" if unit else ""
    return f"${scale * float(row['standard_error']):.{digits}f}${suffix}"


def _validate_lp_models(models: pd.DataFrame) -> dict[tuple[str, str], pd.Series]:
    required = {
        "record_type",
        "venue",
        "outcome_name",
        "outcome",
        "multiplicity_family",
        "predictor",
        "coefficient",
        "standard_error",
        "p_value",
        "holm_p_value",
        "focal_family_member",
        "effect_unit",
        "material_capital_usd",
        "observations",
        "pools",
        "weeks",
        "fixed_effects",
        "covariance",
        "stress_timing",
        "outcome_timing",
        "conditioning",
        "interpretation",
        "route_use_variables",
    }
    missing = sorted(required - set(models.columns))
    if missing:
        raise ValueError(f"ETH-stress LP models lack fields: {missing}")

    rows: dict[tuple[str, str], pd.Series] = {}
    expected_units = {
        "stable_x_eth_realized_volatility": (
            "per_10pp_higher_annualized_weekly_eth_volatility"
        ),
        "stable_x_eth_decline": "per_0p10_log_point_eth_price_fall",
    }
    for definition in LP_ROWS:
        for predictor, _, _ in STRESS_COLUMNS:
            row = _one(
                models,
                {
                    "record_type": "lp_stable_demand_stress_coefficient",
                    "venue": definition.venue,
                    "outcome_name": definition.outcome_name,
                    "outcome": definition.outcome,
                    "multiplicity_family": definition.family,
                    "predictor": predictor,
                },
                description="ETH-stress LP model",
            )
            numeric = row[
                [
                    "coefficient",
                    "standard_error",
                    "p_value",
                    "holm_p_value",
                    "observations",
                    "pools",
                    "weeks",
                ]
            ].astype(float)
            if not np.isfinite(numeric.to_numpy()).all():
                raise ValueError("ETH-stress LP model contains nonfinite values")
            if not bool(row["focal_family_member"]):
                raise ValueError("ETH-stress LP table row is outside its Holm family")
            if float(row["material_capital_usd"]) != 50_000.0:
                raise ValueError("ETH-stress LP table expects the $50,000 sample")
            if row["fixed_effects"] != "endpoint_x_week+pool":
                raise ValueError("ETH-stress LP model has unexpected fixed effects")
            if row["covariance"] != "pool_and_week_cluster_cr1":
                raise ValueError("ETH-stress LP model has unexpected covariance")
            if row["stress_timing"] != "week_t_monday_through_sunday":
                raise ValueError("ETH-stress LP model has unexpected stress timing")
            if row["outcome_timing"] != "week_t_plus_1":
                raise ValueError("ETH-stress LP model has unexpected outcome timing")
            if row["effect_unit"] != expected_units[predictor]:
                raise ValueError("ETH-stress LP model has unexpected effect unit")
            if (
                row["interpretation"]
                != "predictive_stablecoin_minus_weth_lp_supply_response"
                or row["route_use_variables"] != "none"
            ):
                raise ValueError("ETH-stress LP model has unexpected interpretation")
            rows[(definition.macro_prefix, predictor)] = row

    v3_net_decline = rows[("EthStressVThreeNetSupply", "stable_x_eth_decline")]
    if not np.isclose(float(v3_net_decline["p_value"]), 0.01678557, atol=5e-5):
        raise ValueError("V3 decline/net raw p-value changed; revisit the table note")
    if not np.isclose(float(v3_net_decline["holm_p_value"]), 0.0671423, atol=5e-5):
        raise ValueError("V3 decline/net Holm p-value changed; revisit the table note")
    return rows


def _validate_lp_support(support: pd.DataFrame) -> dict[str, pd.Series]:
    rows: dict[str, pd.Series] = {}
    for venue in ("uniswap_v2", "uniswap_v3"):
        row = _one(
            support,
            {
                "record_type": "lp_stable_demand_stress_sample_support",
                "venue": venue,
            },
            description="ETH-stress LP support",
        )
        if row["comparison"] != "stablecoin_leg_minus_weth_leg_for_same_endpoint_week":
            raise ValueError("ETH-stress LP support has unexpected comparison")
        if row["route_use_variables"] != "none":
            raise ValueError("ETH-stress LP support unexpectedly uses route outcomes")
        rows[venue] = row
    return rows


def _validate_chain_models(models: pd.DataFrame) -> dict[str, pd.Series]:
    required = {
        "record_type",
        "model_id",
        "outcome",
        "predictor",
        "coefficient",
        "standard_error",
        "p_value",
        "holm_p_value",
        "observations",
        "ordered_pairs",
        "dates",
        "fixed_effects",
        "time_controls",
        "date_effects",
        "covariance",
        "stress_timing",
        "exact_route_state",
        "causal_interpretation",
    }
    missing = sorted(required - set(models.columns))
    if missing:
        raise ValueError(f"ETH-stress execution models lack fields: {missing}")

    rows: dict[str, pd.Series] = {}
    anchors: list[pd.Series] = []
    for definition in CHAIN_CELLS:
        row = _one(
            models,
            {
                "record_type": "eth_stress_executability_regression",
                "model_id": definition.model_id,
                "outcome": definition.outcome,
                "predictor": definition.predictor,
            },
            description="ETH-stress execution model",
        )
        numeric_fields = [
            "coefficient",
            "standard_error",
            "p_value",
            "observations",
            "ordered_pairs",
            "dates",
        ]
        if definition.p_field == "holm_p_value":
            numeric_fields.append("holm_p_value")
        numeric = row[numeric_fields].astype(float)
        if not np.isfinite(numeric.to_numpy()).all():
            raise ValueError("ETH-stress execution model contains nonfinite values")
        if row["fixed_effects"] != "ordered_pair+calendar_month":
            raise ValueError("ETH-stress execution model has unexpected fixed effects")
        if row["time_controls"] != "linear_calendar_time_in_years":
            raise ValueError("ETH-stress execution model has unexpected time controls")
        if row["date_effects"] != "not_absorbed_marketwide_eth_return_is_date_level":
            raise ValueError("ETH-stress execution model has unexpected date-effects field")
        if row["covariance"] != "ordered_pair_and_exact_date_cluster_cr1":
            raise ValueError("ETH-stress execution model has unexpected covariance")
        if row["stress_timing"] != "canonical_weth_return_days_minus_30_through_minus_1":
            raise ValueError("ETH-stress execution model has unexpected stress timing")
        if row["exact_route_state"] != "same_pair_notional_pretrade_state_and_public_venue_set":
            raise ValueError("ETH-stress execution model has unexpected quote state")
        if bool(row["causal_interpretation"]):
            raise ValueError("ETH-stress execution model cannot carry a causal label")
        rows[definition.macro_prefix] = row
        anchors.append(row)

    for field in ("observations", "ordered_pairs", "dates"):
        if len({int(round(float(row[field]))) for row in anchors}) != 1:
            raise ValueError(f"ETH-stress execution models differ in {field}")

    conditional_prefixes = [
        definition.macro_prefix
        for definition in CHAIN_CELLS
        if definition.p_field == "p_value"
    ]
    conditional_adjusted = holm_adjusted_pvalues(
        np.array(
            [float(rows[prefix]["p_value"]) for prefix in conditional_prefixes]
        )
    )
    for prefix, adjusted_p_value in zip(
        conditional_prefixes, conditional_adjusted, strict=True
    ):
        row = rows[prefix].copy()
        row["p_value"] = float(adjusted_p_value)
        rows[prefix] = row
    return rows


def _validate_chain_support(support: pd.DataFrame) -> pd.Series:
    row = _one(
        support,
        {"record_type": "eth_stress_executability_support"},
        description="ETH-stress execution support",
    )
    expected = {
        "depth_interpretation": "mark_to_market_pool_state_not_provider_flow",
        "depth_measure": "prior_calendar_v2_sushiv2_weak_leg_deposited_usd_capital",
        "output_interpretation": "exact_executable_output_same_pretrade_state",
        "choice_interpretation": "realised_vehicle_family_conditional_both_feasible",
        "lp_withdrawal_interpretation": "measured_separately_not_in_this_output",
    }
    for field, value in expected.items():
        if row[field] != value:
            raise ValueError(f"ETH-stress execution support has unexpected {field}")
    return row


def _validate_intraday_models(models: pd.DataFrame) -> dict[str, pd.Series]:
    required = {
        "record_type",
        "model_id",
        "outcome",
        "predictor",
        "coefficient",
        "standard_error",
        "p_value",
        "holm_p_value",
        "observations",
        "events",
        "ordered_pairs",
        "fixed_effects",
        "covariance",
        "eth_timing",
        "sample",
        "venue_scope",
        "quote_interpretation",
        "depth_interpretation",
        "causal_interpretation",
    }
    missing = sorted(required - set(models.columns))
    if missing:
        raise ValueError(f"intraday ETH-route models lack fields: {missing}")

    rows: dict[str, pd.Series] = {}
    anchors: list[pd.Series] = []
    for definition in INTRADAY_CELLS:
        row = _one(
            models,
            {
                "record_type": (
                    "eth_intraday_executable_route_chain_regression"
                ),
                "model_id": definition.model_id,
                "outcome": definition.outcome,
                "predictor": definition.predictor,
            },
            description="intraday ETH-route model",
        )
        numeric_fields = [
            "coefficient",
            "standard_error",
            "p_value",
            "observations",
            "events",
            "ordered_pairs",
        ]
        if definition.p_field == "holm_p_value":
            numeric_fields.append("holm_p_value")
        numeric = row[numeric_fields].astype(float)
        if not np.isfinite(numeric.to_numpy()).all():
            raise ValueError("intraday ETH-route model contains nonfinite values")
        expected = {
            "fixed_effects": "event_pair+relative_hour_bin",
            "covariance": "stress_event_and_ordered_pair_cluster_cr1",
            "eth_timing": "strictly_available_coinbase_close_t_minus_6h_to_t",
            "sample": "v2_sushiv2_nonvehicle_endpoints_both_families_executable",
            "venue_scope": "uniswap_v2+sushiswap_v2",
            "quote_interpretation": (
                "exact_pretransaction_output_at_observed_notional"
            ),
            "depth_interpretation": (
                "not_dollar_tvl_and_not_a_complete_depth_curve"
            ),
        }
        for field, value in expected.items():
            if row[field] != value:
                raise ValueError(
                    f"intraday ETH-route model has unexpected {field}"
                )
        if bool(row["causal_interpretation"]):
            raise ValueError("intraday ETH-route model cannot carry a causal label")
        rows[definition.macro_prefix] = row
        anchors.append(row)

    for field in ("observations", "events", "ordered_pairs"):
        if len({int(round(float(row[field]))) for row in anchors}) != 1:
            raise ValueError(f"intraday ETH-route models differ in {field}")
    return rows


def _validate_intraday_support(support: pd.DataFrame) -> tuple[pd.Series, int]:
    row = _one(
        support,
        {"record_type": "eth_intraday_executable_route_chain_support"},
        description="intraday ETH-route support",
    )
    expected = {
        "event_definition": (
            "first_strictly_available_6h_eth_decline_crossing_10_percent"
        ),
        "event_window_hours": "-6_to_+24",
        "event_cooldown_hours": 48,
        "price_source": "coinbase_exchange_eth_usd_spot_1m_close",
        "price_timing": "latest_available_close_strictly_before_transaction",
        "endpoint_scope": "neither_endpoint_is_weth_dai_usdc_or_usdt",
        "venue_scope": "uniswap_v2+sushiswap_v2",
        "quote_interpretation": (
            "exact_pretransaction_output_at_observed_notional"
        ),
        "depth_interpretation": (
            "not_dollar_tvl_and_not_a_complete_depth_curve"
        ),
    }
    for field, value in expected.items():
        if row[field] != value:
            raise ValueError(
                f"intraday ETH-route support has unexpected {field}"
            )
    if bool(row["causal_interpretation"]):
        raise ValueError("intraday ETH-route support cannot carry a causal label")
    numeric = row[
        [
            "events",
            "days_replayed",
            "window_targets",
            "exactly_reproduced_routes",
            "chosen_reproduction_share",
            "contestable_clean_routes",
            "ordered_pairs",
        ]
    ].astype(float)
    if not np.isfinite(numeric.to_numpy()).all() or (numeric <= 0).any():
        raise ValueError("intraday ETH-route support contains invalid counts")
    excluded = support.loc[
        support["record_type"].eq(
            "eth_intraday_executable_route_chain_day_support"
        )
        & support["state_status"].eq(
            "excluded_exact_event_contract_failure"
        )
    ]
    if len(excluded) != 4:
        raise ValueError("intraday ETH-route support expects four excluded days")
    return row, len(excluded)


def render_eth_stress_supply_transmission(
    lp_models: pd.DataFrame,
    lp_support: pd.DataFrame,
    chain_models: pd.DataFrame,
    chain_support: pd.DataFrame,
    intraday_models: pd.DataFrame,
    intraday_support: pd.DataFrame,
) -> str:
    """Render a compact three-panel appendix table."""

    lp_rows = _validate_lp_models(lp_models)
    _validate_lp_support(lp_support)
    chain_rows = _validate_chain_models(chain_models)
    _validate_chain_support(chain_support)
    intraday_rows = _validate_intraday_models(intraday_models)
    _validate_intraday_support(intraday_support)

    lines = [
        r"\textit{Panel A. Stablecoin-minus-WETH liquidity-supply responses}",
        r"\par\smallskip",
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.55\hsize\raggedright\arraybackslash}X*{2}{>{\hsize=0.725\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"Outcome in week $t+1$ & 10 pp higher ETH volatility & ETH price fall [0.10 log point] \\",
        r"\midrule",
    ]
    for definition in LP_ROWS:
        cells = [
            _cell(lp_rows[(definition.macro_prefix, predictor)])
            for predictor, _, _ in STRESS_COLUMNS
        ]
        lines.append(definition.label + " & " + " & ".join(cells) + r" \\")
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
            r"\par\medskip",
            r"\textit{Panel B. ETH-price declines, weak-leg capital, quotes, and route use}",
            r"\par\smallskip",
            r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.65\hsize\raggedright\arraybackslash}X*{3}{>{\hsize=0.78\hsize\centering\arraybackslash}X}@{}}",
            r"\toprule",
            r"Regressor & Log stable/WETH USD capital & Stablecoin output lead [bp] & Stablecoin chosen [pp] \\",
            r"\midrule",
        ]
    )
    matrix: list[list[str]] = [["", "", ""] for _ in CHAIN_ROW_LABELS]
    for definition in CHAIN_CELLS:
        matrix[definition.row][definition.column] = _cell(
            chain_rows[definition.macro_prefix],
            scale=definition.scale,
            digits=definition.digits,
            p_field=definition.p_field,
        )
    for label, cells in zip(CHAIN_ROW_LABELS, matrix, strict=True):
        lines.append(label + " & " + " & ".join(cells) + r" \\")
    anchor = chain_rows[CHAIN_CELLS[0].macro_prefix]
    lines.extend(
        [
            r"\midrule",
            "Observations & "
            + " & ".join([f"{int(anchor['observations']):,}"] * 3)
            + r" \\",
            r"\bottomrule",
            r"\end{tabularx}",
            r"\par\medskip",
            r"\textit{Panel C. Six-hour ETH-price declines, exact quotes, and route use}",
            r"\par\smallskip",
            r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.55\hsize\raggedright\arraybackslash}X*{2}{>{\hsize=0.725\hsize\centering\arraybackslash}X}@{}}",
            r"\toprule",
            r"Regressor & Stablecoin output lead [bp] & Stablecoin chosen [pp] \\",
            r"\midrule",
        ]
    )
    intraday_matrix: list[list[str]] = [
        ["", ""] for _ in INTRADAY_ROW_LABELS
    ]
    for definition in INTRADAY_CELLS:
        intraday_matrix[definition.row][definition.column] = _cell(
            intraday_rows[definition.macro_prefix],
            scale=definition.scale,
            digits=definition.digits,
            p_field=definition.p_field,
        )
    for label, cells in zip(
        INTRADAY_ROW_LABELS, intraday_matrix, strict=True
    ):
        lines.append(label + " & " + " & ".join(cells) + r" \\")
    intraday_anchor = intraday_rows[INTRADAY_CELLS[0].macro_prefix]
    intraday_counts = (
        ("Observations", "observations"),
        ("Stress events", "events"),
        ("Endpoint pairs", "ordered_pairs"),
    )
    lines.append(r"\midrule")
    for label, field in intraday_counts:
        value = f"{int(intraday_anchor[field]):,}"
        lines.append(f"{label} & {value} & {value}" + r" \\")
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(lines)


def render_eth_stress_supply_transmission_values(
    lp_models: pd.DataFrame,
    lp_support: pd.DataFrame,
    chain_models: pd.DataFrame,
    chain_support: pd.DataFrame,
    intraday_models: pd.DataFrame,
    intraday_support: pd.DataFrame,
) -> str:
    """Return prose-ready values from the rows used by the appendix table."""

    lp_rows = _validate_lp_models(lp_models)
    lp_support_rows = _validate_lp_support(lp_support)
    chain_rows = _validate_chain_models(chain_models)
    support = _validate_chain_support(chain_support)
    intraday_rows = _validate_intraday_models(intraday_models)
    intraday_sample, intraday_excluded_days = _validate_intraday_support(
        intraday_support
    )

    lines = [
        "% Generated by scripts/tabulate/render_eth_stress_supply_transmission.py; do not edit.",
    ]
    for definition in LP_ROWS:
        for predictor, _, suffix in STRESS_COLUMNS:
            row = lp_rows[(definition.macro_prefix, predictor)]
            prefix = f"{definition.macro_prefix}{suffix}"
            lines.extend(
                [
                    _macro(prefix + "Effect", _tex_effect(row, scale=1.0, digits=4)),
                    _macro(prefix + "SE", _tex_se(row, scale=1.0, digits=4)),
                    _macro(prefix + "RawP", _tex_p(row["p_value"])),
                    _macro(prefix + "HolmP", _tex_p(row["holm_p_value"])),
                ]
            )

    for venue, prefix in (
        ("uniswap_v2", "EthStressVTwo"),
        ("uniswap_v3", "EthStressVThree"),
    ):
        row = lp_support_rows[venue]
        lines.extend(
            [
                _macro(prefix + "N", _tex_integer(row["observations"])),
                _macro(prefix + "Pools", _tex_integer(row["pools"])),
                _macro(prefix + "Weeks", _tex_integer(row["weeks"])),
            ]
        )

    v3_net_decline = lp_rows[
        ("EthStressVThreeNetSupply", "stable_x_eth_decline")
    ]
    lines.append(
        _macro(
            "EthStressVThreeNetSupplyDeclineHolmValue",
            _tex_p_value(v3_net_decline["holm_p_value"]),
        )
    )

    units = {
        "EthStressDeclineRelativeDepth": "",
        "EthStressDeclineOutput": "bp",
        "EthStressDeclineChoice": "pp",
        "EthStressDepthOutput": "bp",
        "EthStressDepthChoice": "pp",
        "EthStressOutputChoice": "pp",
    }
    for definition in CHAIN_CELLS:
        row = chain_rows[definition.macro_prefix]
        unit = units[definition.macro_prefix]
        lines.extend(
            [
                _macro(
                    definition.macro_prefix + "Effect",
                    _tex_effect(
                        row,
                        scale=definition.scale,
                        digits=definition.digits,
                        unit=unit,
                    ),
                ),
                _macro(
                    definition.macro_prefix + "SE",
                    _tex_se(
                        row,
                        scale=definition.scale,
                        digits=definition.digits,
                        unit=unit,
                    ),
                ),
                _macro(
                    definition.macro_prefix + "P",
                    _tex_p(row[definition.p_field]),
                ),
            ]
        )

    anchor = chain_rows[CHAIN_CELLS[0].macro_prefix]
    lines.extend(
        [
            _macro("EthStressExecutionN", _tex_integer(anchor["observations"])),
            _macro("EthStressExecutionPairs", _tex_integer(anchor["ordered_pairs"])),
            _macro("EthStressExecutionDates", _tex_integer(anchor["dates"])),
            _macro(
                "EthStressPositiveDepthOpportunities",
                _tex_integer(support["common_positive_depth_rows"]),
            ),
            _macro(
                "EthStressPositiveDepthCoverage",
                f"{100.0 * float(support['common_positive_depth_share_of_contestable']):.1f}\\%",
            ),
            _macro(
                "EthStressMedianInput",
                rf"\${_tex_integer(support['median_input_usd'])}",
            ),
        ]
    )
    intraday_units = {
        "EthIntradayDeclineOutput": "bp",
        "EthIntradayDeclineChoice": "pp",
        "EthIntradayOutputChoice": "pp",
    }
    for definition in INTRADAY_CELLS:
        row = intraday_rows[definition.macro_prefix]
        unit = intraday_units[definition.macro_prefix]
        lines.extend(
            [
                _macro(
                    definition.macro_prefix + "Effect",
                    _tex_effect(
                        row,
                        scale=definition.scale,
                        digits=definition.digits,
                        unit=unit,
                    ),
                ),
                _macro(
                    definition.macro_prefix + "SE",
                    _tex_se(
                        row,
                        scale=definition.scale,
                        digits=definition.digits,
                        unit=unit,
                    ),
                ),
                _macro(
                    definition.macro_prefix + "P",
                    _tex_p_value(row[definition.p_field]),
                ),
            ]
        )
    intraday_anchor = intraday_rows[INTRADAY_CELLS[0].macro_prefix]
    lines.extend(
        [
            _macro(
                "EthIntradayN",
                _tex_integer(intraday_anchor["observations"]),
            ),
            _macro(
                "EthIntradayEstimationEvents",
                _tex_integer(intraday_anchor["events"]),
            ),
            _macro(
                "EthIntradayEstimationPairs",
                _tex_integer(intraday_anchor["ordered_pairs"]),
            ),
            _macro(
                "EthIntradayAllEvents",
                _tex_integer(intraday_sample["events"]),
            ),
            _macro(
                "EthIntradayCleanRoutes",
                _tex_integer(intraday_sample["contestable_clean_routes"]),
            ),
            _macro(
                "EthIntradayExactRoutes",
                _tex_integer(intraday_sample["exactly_reproduced_routes"]),
            ),
            _macro(
                "EthIntradayReproductionShare",
                f"{100.0 * float(intraday_sample['chosen_reproduction_share']):.2f}\\%",
            ),
            _macro(
                "EthIntradayExcludedDays",
                _tex_integer(intraday_excluded_days),
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    lp_models = pd.read_json(LP_MODELS, lines=True)
    lp_support = pd.read_json(LP_SUPPORT, lines=True)
    chain_models = pd.read_json(CHAIN_MODELS, lines=True)
    chain_support = pd.read_json(CHAIN_SUPPORT, lines=True)
    intraday_models = pd.read_json(INTRADAY_MODELS, lines=True)
    intraday_support = pd.read_json(INTRADAY_SUPPORT, lines=True)
    write_table_artifacts(
        "eth_stress_supply_transmission",
        render_eth_stress_supply_transmission(
            lp_models,
            lp_support,
            chain_models,
            chain_support,
            intraday_models,
            intraday_support,
        ),
        preview_width="8.5in",
    )
    with atomic_output(VALUES_OUTPUT) as temporary:
        temporary.write_text(
            render_eth_stress_supply_transmission_values(
                lp_models,
                lp_support,
                chain_models,
                chain_support,
                intraday_models,
                intraday_support,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

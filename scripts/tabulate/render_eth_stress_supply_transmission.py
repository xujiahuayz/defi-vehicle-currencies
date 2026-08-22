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
VALUES_OUTPUT = (
    OUTPUT_DIR / "exhibits/eth_stress_supply_transmission_values.tex"
)


TABLE_NOTE = (
    "Panel A compares stablecoin-facing and WETH-facing pools for the same "
    "endpoint and week. ETH volatility and price declines are measured during week "
    "$t$; liquidity outcomes occur during week $t+1$. Additions and "
    "withdrawals are log one plus the dollar flow divided by initial pool "
    "capital. Net supply is the inverse hyperbolic sine of net dollar flow "
    "divided by initial capital. The v2 liquidity-unit outcome instead divides "
    "net LP-token liquidity by initial square-root reserves, making the measure "
    "price-neutral. Pools have at least $50,000 of capital. Models absorb "
    "endpoint-by-week and pool fixed effects, control for prior fee yield, "
    "endpoint--vehicle relative-price volatility, additions, withdrawals, "
    "capital, and pool age, and cluster standard errors by pool and week. The "
    "v3 net-supply response to an ETH decline has raw $p=0.017$ and Holm "
    "$p=0.067$; its addition and withdrawal components are individually "
    "imprecise. Panel B uses exact two-leg opportunities for which stablecoin "
    "and WETH routes are both feasible and both prior-calendar weak-leg "
    "full-range capital measures are positive. Dollar capital is deposited "
    "Uniswap v2 and SushiSwap v2 capital on the weaker leg. It is a "
    "mark-to-market pool state; Panel A measures provider flows. Exact output holds "
    "the pair, input, pre-transaction state, and public venue set fixed. Panel "
    "B models absorb pair and month-of-year fixed effects, control for log "
    "input value, ETH volatility, and linear calendar time, and cluster "
    "standard errors by pair and exact date. The market-wide ETH-price decline exhausts "
    "exact-date variation, so the models use month-of-year effects and linear "
    "calendar time. Stars in Panel A and the first row of "
    "Panel B use Holm-adjusted p-values within their declared outcome families. "
    "The three capital--price--choice links in Panel B form a separate Holm family. "
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


def render_eth_stress_supply_transmission(
    lp_models: pd.DataFrame,
    lp_support: pd.DataFrame,
    chain_models: pd.DataFrame,
    chain_support: pd.DataFrame,
) -> str:
    """Render a compact two-panel appendix table."""

    lp_rows = _validate_lp_models(lp_models)
    _validate_lp_support(lp_support)
    chain_rows = _validate_chain_models(chain_models)
    _validate_chain_support(chain_support)

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
            "",
        ]
    )
    return "\n".join(lines)


def render_eth_stress_supply_transmission_values(
    lp_models: pd.DataFrame,
    lp_support: pd.DataFrame,
    chain_models: pd.DataFrame,
    chain_support: pd.DataFrame,
) -> str:
    """Return prose-ready values from the rows used by the appendix table."""

    lp_rows = _validate_lp_models(lp_models)
    lp_support_rows = _validate_lp_support(lp_support)
    chain_rows = _validate_chain_models(chain_models)
    support = _validate_chain_support(chain_support)

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
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    lp_models = pd.read_json(LP_MODELS, lines=True)
    lp_support = pd.read_json(LP_SUPPORT, lines=True)
    chain_models = pd.read_json(CHAIN_MODELS, lines=True)
    chain_support = pd.read_json(CHAIN_SUPPORT, lines=True)
    write_table_artifacts(
        "eth_stress_supply_transmission",
        render_eth_stress_supply_transmission(
            lp_models,
            lp_support,
            chain_models,
            chain_support,
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
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

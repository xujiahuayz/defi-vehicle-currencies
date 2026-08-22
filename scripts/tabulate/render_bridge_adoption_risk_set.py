#!/usr/bin/env python3
"""Render the at-risk stable-bridge adoption timing table and value macros."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output
from ddvc.tables import read_exhibit


RESULTS = OUTPUT_DIR / "exhibits/bridge_adoption_risk_set.jsonl"
VALUES = OUTPUT_DIR / "exhibits/bridge_adoption_risk_set_values.tex"

PRIMARY_SAMPLE = "primary_10_routes_3_days"
STRICT_SAMPLE = "strict_50_routes_5_days"


def _one_model(
    results: pd.DataFrame,
    sample_id: str,
    model_id: str,
    predictor: str,
) -> pd.Series:
    selected = results[
        results["record_type"].eq("bridge_adoption_risk_model")
        & results["sample_id"].eq(sample_id)
        & results["model_id"].eq(model_id)
        & results["predictor"].eq(predictor)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one bridge-adoption model row for "
            f"{sample_id}/{model_id}/{predictor}; found {len(selected)}"
        )
    return selected.iloc[0]


def _one_support(results: pd.DataFrame, sample_id: str) -> pd.Series:
    selected = results[
        results["record_type"].eq("bridge_adoption_risk_support")
        & results["sample_id"].eq(sample_id)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one bridge-adoption support row for {sample_id}; "
            f"found {len(selected)}"
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


def _cell(row: pd.Series) -> str:
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${float(row['coefficient_pp']):+.2f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({float(row['standard_error_pp']):.2f})$"
        r"\end{tabular}"
    )


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}".replace(",", "{,}")


def _p_value(value: object) -> str:
    number = float(value)
    if number < 0.001:
        return "$p<0.001$"
    return f"$p={number:.3f}$"


def _sample_rows(results: pd.DataFrame, sample_id: str) -> list[str]:
    preweek = _one_model(
        results,
        sample_id,
        "m1_preweek_relative_depth",
        "stable_depth_share_10pp",
    )
    future = _one_model(
        results,
        sample_id,
        "m3_future_depth_time_reversal",
        "lead_stable_depth_share_10pp",
    )
    joint_preweek = _one_model(
        results,
        sample_id,
        "m4_preweek_and_future_depth",
        "stable_depth_share_10pp",
    )
    joint_future = _one_model(
        results,
        sample_id,
        "m4_preweek_and_future_depth",
        "lead_stable_depth_share_10pp",
    )
    return [
        r"Preweek stable share of joint weak-leg capital [10 pp] & "
        + _cell(preweek)
        + r" &  & "
        + _cell(joint_preweek)
        + r" \\",
        r"Next-week stable share of joint weak-leg capital [10 pp] &  & "
        + _cell(future)
        + r" & "
        + _cell(joint_future)
        + r" \\",
        r"Pair-weeks & "
        + f"{int(preweek['pair_weeks']):,} & {int(future['pair_weeks']):,} & "
        + f"{int(joint_preweek['pair_weeks']):,} "
        + r"\\",
        r"Ordered endpoint pairs & "
        + f"{int(preweek['pairs']):,} & {int(future['pairs']):,} & "
        + f"{int(joint_preweek['pairs']):,} "
        + r"\\",
        r"First stable-route adoptions & "
        + f"{int(preweek['adoptions']):,} & {int(future['adoptions']):,} & "
        + f"{int(joint_preweek['adoptions']):,} "
        + r"\\",
    ]


def render_bridge_adoption_risk_set(results: pd.DataFrame) -> str:
    """Return a compact appendix table for the primary and strict risk sets."""

    _one_support(results, PRIMARY_SAMPLE)
    _one_support(results, STRICT_SAMPLE)
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xccc@{}}",
        r"\toprule",
        r" & (1) Preweek & (2) Next week & (3) Joint timing \\",
        r"\midrule",
        r"\multicolumn{4}{@{}l}{\textit{Panel A. At least 10 WETH routes on three days during the prior 28 days}} \\",
        *_sample_rows(results, PRIMARY_SAMPLE),
        r"\addlinespace",
        r"\multicolumn{4}{@{}l}{\textit{Panel B. At least 50 WETH routes on five days during the prior 28 days}} \\",
        *_sample_rows(results, STRICT_SAMPLE),
        r"\bottomrule",
        r"\end{tabularx}",
        "% Suggested paper note: The unit is an ordered endpoint-pair week before the pair's first observed DAI-, USDC-, or USDT-mediated route. Neither endpoint is WETH or one of those stablecoins. Every risk week has recent WETH-mediated activity, and stablecoin weak-leg capital may equal zero. Capital is prior-calendar full-range reserve value in Uniswap v2 and SushiSwap v2 at the start of the week; each vehicle's two-leg measure is its weaker leg, and stablecoin capital is the largest value across DAI, USDC, and USDT. The outcome is first stablecoin-mediated route use during the week. Linear probability models absorb pair and calendar-week fixed effects, include pair-age bins, log WETH depth, and prior WETH-route activity, weight pair-weeks equally, and cluster standard errors by pair and week. Column 2 uses next week's capital. In column 3, its coefficient measures future capital conditional on preweek capital; it can reflect capital adjustments following adoption and therefore does not establish that capital precedes use. Asterisks *, **, and *** denote two-sided significance at the 10%, 5%, and 1% levels, respectively. The estimates describe equilibrium timing; the capital measure omits concentrated-liquidity venues.",
        "",
    ]
    return "\n".join(lines)


def render_bridge_adoption_risk_set_values(results: pd.DataFrame) -> str:
    """Return appendix-ready value macros from the same model rows."""

    primary_support = _one_support(results, PRIMARY_SAMPLE)
    strict_support = _one_support(results, STRICT_SAMPLE)
    primary_preweek = _one_model(
        results,
        PRIMARY_SAMPLE,
        "m1_preweek_relative_depth",
        "stable_depth_share_10pp",
    )
    primary_future = _one_model(
        results,
        PRIMARY_SAMPLE,
        "m3_future_depth_time_reversal",
        "lead_stable_depth_share_10pp",
    )
    primary_joint_preweek = _one_model(
        results,
        PRIMARY_SAMPLE,
        "m4_preweek_and_future_depth",
        "stable_depth_share_10pp",
    )
    primary_joint_future = _one_model(
        results,
        PRIMARY_SAMPLE,
        "m4_preweek_and_future_depth",
        "lead_stable_depth_share_10pp",
    )
    strict_preweek = _one_model(
        results,
        STRICT_SAMPLE,
        "m1_preweek_relative_depth",
        "stable_depth_share_10pp",
    )
    strict_future = _one_model(
        results,
        STRICT_SAMPLE,
        "m3_future_depth_time_reversal",
        "lead_stable_depth_share_10pp",
    )

    def effect(name: str, row: pd.Series) -> list[str]:
        return [
            f"\\newcommand{{\\{name}}}{{${float(row['coefficient_pp']):+.2f}$ pp}}",
            f"\\newcommand{{\\{name}SE}}{{${float(row['standard_error_pp']):.2f}$ pp}}",
            f"\\newcommand{{\\{name}P}}{{{_p_value(row['p_value'])}}}",
        ]

    lines = [
        "% Generated by scripts/tabulate/render_bridge_adoption_risk_set.py; do not edit.",
        f"\\newcommand{{\\BridgeAdoptionRiskPairWeeks}}{{{_integer(primary_support['pair_weeks'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskPairs}}{{{_integer(primary_support['pairs'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskAdoptions}}{{{_integer(primary_support['adopting_pairs'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskZeroDepthWeeks}}{{{_integer(primary_support['zero_stable_depth_pair_weeks'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskStrictPairWeeks}}{{{_integer(strict_support['pair_weeks'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskStrictPairs}}{{{_integer(strict_support['pairs'])}}}",
        *effect("BridgeAdoptionRiskPreweek", primary_preweek),
        *effect("BridgeAdoptionRiskFuture", primary_future),
        *effect("BridgeAdoptionRiskJointPreweek", primary_joint_preweek),
        *effect("BridgeAdoptionRiskJointFuture", primary_joint_future),
        *effect("BridgeAdoptionRiskStrictPreweek", strict_preweek),
        *effect("BridgeAdoptionRiskStrictFuture", strict_future),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    results = read_exhibit(RESULTS)
    write_table_artifacts(
        "bridge_adoption_risk_set",
        render_bridge_adoption_risk_set(results),
        preview_width="7.5in",
    )
    with atomic_output(VALUES) as temporary:
        temporary.write_text(
            render_bridge_adoption_risk_set_values(results), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

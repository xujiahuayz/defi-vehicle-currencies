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


def _cell(
    row: pd.Series,
    *,
    coefficient_column: str = "coefficient_pp",
    standard_error_column: str = "standard_error_pp",
) -> str:
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${float(row[coefficient_column]):+.2f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({float(row[standard_error_column]):.2f})$"
        r"\end{tabular}"
    )


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}".replace(",", "{,}")


def _outcome_mean(row: pd.Series) -> str:
    value = row.get("risk_set_adoption_rate")
    if value is None or pd.isna(value):
        value = float(row["adoptions"]) / float(row["pair_weeks"])
    return f"{100.0 * float(value):.2f}"


def _p_value(value: object) -> str:
    number = float(value)
    if number < 0.001:
        return "$p<0.001$"
    return f"$p={number:.3f}$"


def _sample_rows(results: pd.DataFrame, sample_id: str) -> list[str]:
    any_support = _one_model(
        results,
        sample_id,
        "m5_any_preweek_stable_support",
        "positive_stable_support",
    )
    positive_depth = _one_model(
        results,
        sample_id,
        "m6_positive_support_log_depth_advantage",
        "log_depth_advantage",
    )
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
    model_rows = (
        any_support,
        positive_depth,
        preweek,
        future,
        joint_preweek,
    )
    return [
        r"Any measured V2 stable bridge capital before the week [0/1] & "
        + _cell(any_support)
        + r" &  &  &  &  \\",
        r"Stable/WETH weak-leg capital ratio, positive-support weeks [10$\times$] &  & "
        + _cell(
            positive_depth,
            coefficient_column="coefficient_pp_per_10x",
            standard_error_column="standard_error_pp_per_10x",
        )
        + r" &  &  &  \\",
        r"Preweek stable share of joint weak-leg capital [10 pp] &  &  & "
        + _cell(preweek)
        + r" &  & "
        + _cell(joint_preweek)
        + r" \\",
        r"Next-week stable share of joint weak-leg capital [10 pp] &  &  &  & "
        + _cell(future)
        + r" & "
        + _cell(joint_future)
        + r" \\",
        "Pair-weeks & "
        + " & ".join(f"{int(row['pair_weeks']):,}" for row in model_rows)
        + r" \\",
        "Ordered endpoint pairs & "
        + " & ".join(f"{int(row['pairs']):,}" for row in model_rows)
        + r" \\",
        "First-use events & "
        + " & ".join(f"{int(row['adoptions']):,}" for row in model_rows)
        + r" \\",
        "Outcome mean [\\%] & "
        + " & ".join(_outcome_mean(row) for row in model_rows)
        + r" \\",
    ]


def render_bridge_adoption_risk_set(results: pd.DataFrame) -> str:
    """Return a compact appendix table for the primary and strict risk sets."""

    _one_support(results, PRIMARY_SAMPLE)
    _one_support(results, STRICT_SAMPLE)
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=2.4\hsize\raggedright\arraybackslash}X*{5}{>{\hsize=0.72\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"Outcome & \multicolumn{5}{c}{First stablecoin route use during the week [0/1]} \\",
        r" & \shortstack{(1)\\Any\\support} & \shortstack{(2)\\Capital\\ratio} & \shortstack{(3)\\Preweek\\share} & \shortstack{(4)\\Next-week\\share} & \shortstack{(5)\\Joint\\timing} \\",
        r"\midrule",
        r"\multicolumn{6}{@{}l}{\textit{Panel A. Prior 28 days: at least 10 WETH routes on three days}} \\",
        *_sample_rows(results, PRIMARY_SAMPLE),
        r"\addlinespace",
        r"\multicolumn{6}{@{}l}{\textit{Panel B. Prior 28 days: at least 50 WETH routes on five days}} \\",
        *_sample_rows(results, STRICT_SAMPLE),
        r"\bottomrule",
        r"\end{tabularx}",
        (
            r"% Suggested paper note: The unit is an ordered endpoint-pair week before the pair's first observed DAI-, USDC-, or USDT-mediated route. Neither endpoint is WETH or one of those stablecoins. Every pair-week has recent WETH-mediated activity, and stablecoin weak-leg capital may equal zero. Capital is prior-calendar full-range reserve value in Uniswap v2 and SushiSwap v2 at the start of the week; each vehicle's two-leg measure is its weaker leg, and stablecoin capital is the largest value across DAI, USDC, and USDT. The outcome is first stablecoin-mediated route use during the week. "
            r"Column 1 compares positive measured V2 stablecoin support with zero measured V2 support. Column 2 is limited to pairs observed for at least two positive-support weeks and reports a $\ln(10)$ increase in the stablecoin-to-WETH log-capital advantage; conditional on WETH weak-leg capital, this is approximately a tenfold rise in stablecoin weak-leg capital. Columns 3--5 use stablecoin's share of joint stablecoin and WETH weak-leg capital. "
            r"Linear probability models absorb pair and calendar-week fixed effects, include pair-age bins, log WETH weak-leg capital, and prior WETH-route activity, weight pair-weeks equally, and cluster standard errors by pair and week. Columns 4 and 5 measure next-week association, which may include capital adjustments following adoption. "
            r"Asterisks *, **, and *** denote two-sided significance at the 10%, 5%, and 1% levels, respectively. The estimates describe equilibrium timing and cover full-range V2 capital; concentrated-liquidity venues remain outside this capital measure."
        ),
        "",
    ]
    return "\n".join(lines)


def render_bridge_adoption_risk_set_values(results: pd.DataFrame) -> str:
    """Return appendix-ready value macros from the same model rows."""

    primary_support = _one_support(results, PRIMARY_SAMPLE)
    strict_support = _one_support(results, STRICT_SAMPLE)
    primary_any_support = _one_model(
        results,
        PRIMARY_SAMPLE,
        "m5_any_preweek_stable_support",
        "positive_stable_support",
    )
    primary_positive_depth = _one_model(
        results,
        PRIMARY_SAMPLE,
        "m6_positive_support_log_depth_advantage",
        "log_depth_advantage",
    )
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
    strict_any_support = _one_model(
        results,
        STRICT_SAMPLE,
        "m5_any_preweek_stable_support",
        "positive_stable_support",
    )
    strict_positive_depth = _one_model(
        results,
        STRICT_SAMPLE,
        "m6_positive_support_log_depth_advantage",
        "log_depth_advantage",
    )

    def effect(
        name: str,
        row: pd.Series,
        *,
        coefficient_column: str = "coefficient_pp",
        standard_error_column: str = "standard_error_pp",
    ) -> list[str]:
        return [
            f"\\newcommand{{\\{name}}}{{${float(row[coefficient_column]):+.2f}$ pp}}",
            f"\\newcommand{{\\{name}SE}}{{${float(row[standard_error_column]):.2f}$ pp}}",
            f"\\newcommand{{\\{name}P}}{{{_p_value(row['p_value'])}}}",
        ]

    lines = [
        "% Generated by scripts/tabulate/render_bridge_adoption_risk_set.py; do not edit.",
        f"\\newcommand{{\\BridgeAdoptionRiskPairWeeks}}{{{_integer(primary_support['pair_weeks'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskPairs}}{{{_integer(primary_support['pairs'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskAdoptions}}{{{_integer(primary_support['adopting_pairs'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskZeroDepthWeeks}}{{{_integer(primary_support['zero_stable_depth_pair_weeks'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskPositiveDepthWeeks}}{{{_integer(primary_support['positive_stable_depth_pair_weeks'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskZeroDepthAdoptions}}{{{_integer(primary_support['adoptions_with_zero_stable_depth'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskPositiveDepthAdoptions}}{{{_integer(primary_support['adoptions_with_positive_stable_depth'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskStrictPairWeeks}}{{{_integer(strict_support['pair_weeks'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskStrictPairs}}{{{_integer(strict_support['pairs'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskIntensivePairWeeks}}{{{_integer(primary_positive_depth['pair_weeks'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskIntensivePairs}}{{{_integer(primary_positive_depth['pairs'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskIntensiveAdoptions}}{{{_integer(primary_positive_depth['adoptions'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskStrictIntensivePairWeeks}}{{{_integer(strict_positive_depth['pair_weeks'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskStrictIntensivePairs}}{{{_integer(strict_positive_depth['pairs'])}}}",
        f"\\newcommand{{\\BridgeAdoptionRiskStrictIntensiveAdoptions}}{{{_integer(strict_positive_depth['adoptions'])}}}",
        *effect("BridgeAdoptionRiskAnySupport", primary_any_support),
        *effect(
            "BridgeAdoptionRiskIntensiveTenfold",
            primary_positive_depth,
            coefficient_column="coefficient_pp_per_10x",
            standard_error_column="standard_error_pp_per_10x",
        ),
        *effect("BridgeAdoptionRiskPreweek", primary_preweek),
        *effect("BridgeAdoptionRiskFuture", primary_future),
        *effect("BridgeAdoptionRiskJointPreweek", primary_joint_preweek),
        *effect("BridgeAdoptionRiskJointFuture", primary_joint_future),
        *effect("BridgeAdoptionRiskStrictAnySupport", strict_any_support),
        *effect(
            "BridgeAdoptionRiskStrictIntensiveTenfold",
            strict_positive_depth,
            coefficient_column="coefficient_pp_per_10x",
            standard_error_column="standard_error_pp_per_10x",
        ),
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

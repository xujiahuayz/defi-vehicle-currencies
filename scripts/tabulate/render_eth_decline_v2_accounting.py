#!/usr/bin/env python3
"""Render the V2 ETH-decline capital accounting and prose values."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


RESULTS = OUTPUT_DIR / "exhibits/eth_decline_v2_accounting.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/eth_decline_v2_accounting_support.jsonl"
VALUES = OUTPUT_DIR / "exhibits/eth_decline_v2_accounting_values.tex"

HORIZONS = ((1, "OneDay"), (3, "ThreeDay"), (7, "SevenDay"))
OUTCOMES = (
    ("stable_minus_weth_log_capital_change", "Capital"),
    ("stable_minus_weth_log_quantity_component", "Quantity"),
    ("stable_minus_weth_log_unit_value_component", "UnitValue"),
)
ZERO_NULL_OUTCOMES = {
    "stable_minus_weth_log_capital_change",
    "stable_minus_weth_log_quantity_component",
}
UNIT_VALUE_OUTCOME = "stable_minus_weth_log_unit_value_component"


def _one(frame: pd.DataFrame, selectors: dict[str, object], name: str) -> pd.Series:
    selected = frame
    for column, value in selectors.items():
        if column not in selected.columns:
            raise ValueError(f"{name} lacks selector column: {column}")
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one {name} row for {selectors}; found {len(selected)}")
    return selected.iloc[0]


def _stars(p_value: object) -> str:
    value = float(p_value)
    if value < 0.01:
        return "^{***}"
    if value < 0.05:
        return "^{**}"
    if value < 0.10:
        return "^{*}"
    return ""


def _cell(row: pd.Series, *, zero_null: bool) -> str:
    stars = _stars(row["holm_p_value"]) if zero_null else ""
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${float(row['coefficient']):+.4f}{stars}$"
        r"\\"
        f"$({float(row['standard_error']):.4f})$"
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


def _validate(
    results: pd.DataFrame, support: pd.DataFrame
) -> tuple[dict[tuple[int, str], pd.Series], pd.Series]:
    required = {
        "record_type",
        "analysis_status",
        "venue",
        "horizon_days",
        "sample",
        "outcome",
        "predictor",
        "predictor_unit",
        "coefficient",
        "coefficient_unit",
        "standard_error",
        "p_value",
        "holm_p_value",
        "benchmark",
        "benchmark_assumptions",
        "difference_from_benchmark",
        "benchmark_p_value",
        "benchmark_holm_p_value",
        "observations",
        "endpoints",
        "dates",
        "fixed_effects",
        "covariance",
        "pool_set",
        "followup_selection",
        "causal_interpretation",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"ETH-decline V2 results lack fields: {missing}")

    rows: dict[tuple[int, str], pd.Series] = {}
    for horizon, _suffix in HORIZONS:
        for outcome, _label in OUTCOMES:
            row = _one(
                results,
                {
                    "record_type": "eth_decline_v2_accounting_regression",
                    "venue": "pooled_v2",
                    "horizon_days": horizon,
                    "outcome": outcome,
                },
                "pooled ETH-decline V2 result",
            )
            numeric = row[
                [
                    "coefficient",
                    "standard_error",
                    "p_value",
                    "holm_p_value",
                    "benchmark",
                    "difference_from_benchmark",
                    "benchmark_p_value",
                    "observations",
                    "endpoints",
                    "dates",
                ]
            ].astype(float)
            if not np.isfinite(numeric.to_numpy()).all():
                raise ValueError("ETH-decline V2 result contains nonfinite values")
            if float(row["standard_error"]) <= 0:
                raise ValueError("ETH-decline V2 standard errors must be positive")
            if row["analysis_status"] != "focused_accounting_test":
                raise ValueError("ETH-decline V2 result has unexpected status")
            if row["sample"] != (
                "nonstable_endpoints_with_material_stable_and_weth_pools_at_anchor"
            ):
                raise ValueError("ETH-decline V2 result has unexpected sample")
            if row["predictor"] != "eth_price_decline_per_0_10_log_point":
                raise ValueError("ETH-decline V2 result has unexpected predictor")
            if row["predictor_unit"] != (
                "0.10_log_point_fall_in_weth_usd_price_approximately_9.5_percent"
            ):
                raise ValueError("ETH-decline V2 result has unexpected predictor unit")
            if row["coefficient_unit"] != (
                "stable_minus_weth_log_point_change_per_0.10_log_point_eth_price_fall"
            ):
                raise ValueError("ETH-decline V2 result has unexpected coefficient unit")
            if row["fixed_effects"] != "venue_x_endpoint+anchor_year_month":
                raise ValueError("ETH-decline V2 result has unexpected fixed effects")
            if row["covariance"] != "anchor_date_score_hac_bartlett_lag_7_days":
                raise ValueError("ETH-decline V2 result has unexpected covariance")
            if row["pool_set"] != (
                "material_anchor_pools_held_fixed_surviving_complete_followup"
            ):
                raise ValueError("ETH-decline V2 result has unexpected pool set")
            if row["followup_selection"] != (
                "all_selected_anchor_pools_require_positive_valid_future_state;"
                "full_exits_and_missing_states_are_excluded"
            ):
                raise ValueError("ETH-decline V2 result has unexpected follow-up rule")
            if bool(row["causal_interpretation"]):
                raise ValueError("ETH-decline V2 accounting cannot carry a causal label")
            expected_benchmark = 0.05 if outcome == UNIT_VALUE_OUTCOME else 0.0
            if not np.isclose(float(row["benchmark"]), expected_benchmark):
                raise ValueError("ETH-decline V2 result has unexpected benchmark")
            expected_assumptions = (
                "constant_product_equilibrium+stable_peg+common_endpoint_price+"
                "synchronized_reserve_states"
                if outcome == UNIT_VALUE_OUTCOME
                else "not_applicable"
            )
            if row["benchmark_assumptions"] != expected_assumptions:
                raise ValueError("ETH-decline V2 benchmark assumptions changed")
            benchmark_holm = row["benchmark_holm_p_value"]
            if outcome == UNIT_VALUE_OUTCOME:
                if not np.isfinite(float(benchmark_holm)):
                    raise ValueError("ETH-decline V2 benchmark Holm p-value is missing")
            elif not pd.isna(benchmark_holm):
                raise ValueError("zero-benchmark rows cannot carry benchmark Holm p-values")
            if not np.isclose(
                float(row["difference_from_benchmark"]),
                float(row["coefficient"]) - expected_benchmark,
                atol=1e-12,
            ):
                raise ValueError("ETH-decline V2 benchmark difference is inconsistent")
            rows[(horizon, outcome)] = row

        capital = float(
            rows[(horizon, "stable_minus_weth_log_capital_change")]["coefficient"]
        )
        quantity = float(
            rows[(horizon, "stable_minus_weth_log_quantity_component")][
                "coefficient"
            ]
        )
        unit_value = float(rows[(horizon, UNIT_VALUE_OUTCOME)]["coefficient"])
        if not np.isclose(capital, quantity + unit_value, atol=1e-12):
            raise ValueError(f"ETH-decline V2 accounting identity fails at {horizon} days")

    design = _one(
        support,
        {"record_type": "eth_decline_v2_accounting_design_support"},
        "ETH-decline V2 design support",
    )
    if not np.isclose(
        float(
            design[
                "constant_product_unit_value_benchmark_per_0_10_log_point_eth_decline"
            ]
        ),
        0.05,
    ):
        raise ValueError("ETH-decline V2 design has unexpected valuation benchmark")
    if float(design["material_anchor_pool_capital_usd"]) != 50_000.0:
        raise ValueError("ETH-decline V2 design has unexpected materiality floor")
    if design["capital_identity"] != "V_equals_sqrt_k_times_V_over_sqrt_k":
        raise ValueError("ETH-decline V2 design has unexpected capital identity")
    minimum_followup = float(
        design["minimum_venue_horizon_complete_followup_share"]
    )
    maximum_followup = float(
        design["maximum_venue_horizon_complete_followup_share"]
    )
    if not 0 < minimum_followup <= maximum_followup <= 1:
        raise ValueError("ETH-decline V2 follow-up coverage is invalid")
    if design["benchmark_assumptions"] != (
        "constant_product_equilibrium+stable_peg+common_endpoint_price+"
        "synchronized_reserve_states"
    ):
        raise ValueError("ETH-decline V2 design benchmark assumptions changed")
    single_priced = float(
        design["single_priced_endpoint_interval_share_in_primary"]
    )
    if not 0 <= single_priced <= 1:
        raise ValueError("ETH-decline V2 single-priced share is invalid")
    return rows, design


def table_note(
    rows: dict[tuple[int, str], pd.Series], design: pd.Series
) -> str:
    unit_estimates = [
        float(rows[(horizon, UNIT_VALUE_OUTCOME)]["coefficient"])
        for horizon, _suffix in HORIZONS
    ]
    unit_differences = [value - 0.05 for value in unit_estimates]
    if any(
        float(rows[(horizon, UNIT_VALUE_OUTCOME)]["benchmark_holm_p_value"])
        >= 0.001
        for horizon, _suffix in HORIZONS
    ):
        raise ValueError(
            "ETH-decline V2 benchmark Holm p-values changed; revise the note"
        )
    estimates = ", ".join(f"{value:.4f}" for value in unit_estimates)
    differences = ", ".join(f"{value:+.4f}" for value in unit_differences)
    minimum_followup = 100.0 * float(
        design["minimum_venue_horizon_complete_followup_share"]
    )
    maximum_followup = 100.0 * float(
        design["maximum_venue_horizon_complete_followup_share"]
    )
    single_priced = 100.0 * float(
        design["single_priced_endpoint_interval_share_in_primary"]
    )
    return (
        "Each entry is the coefficient on a 0.10-log-point fall in ETH's dollar "
        "price (about 9.5\\%) in a regression of the indicated "
        "stablecoin-minus-WETH log change. The pooled sample "
        "combines Uniswap v2 and SushiSwap v2 and contains nonstable endpoints "
        "with at least \\$50,000 in both stablecoin-facing and WETH-facing pools "
        "at the anchor; those pools are held fixed through the stated horizon. "
        "Every selected pool must retain a positive validated future state. "
        f"Complete intervals span {minimum_followup:.1f}\\% to "
        f"{maximum_followup:.1f}\\% across venue--horizon cells, so full exits "
        "and missing future states are excluded. "
        "Models absorb venue-by-endpoint and anchor-month effects and use "
        "anchor-date HAC standard errors with seven lags. Capital obeys "
        "$V=\\sqrt{k}\\,(V/\\sqrt{k})$. Changes in $\\sqrt{k}$ reflect "
        "liquidity-provider actions, retained swap fees, and token transfers. "
        "The quantity column is the "
        "dollar-weighted Shapley contribution of within-pool changes in "
        "$\\sqrt{k}$; raw invariant units are not added across pools. Unit value "
        "reflects token prices and reserve adjustment. The WETH price series "
        "also enters WETH-side dollar capital; for the "
        f"{single_priced:.1f}\\% of primary intervals whose endpoint lacks a "
        "validated price, capital equals twice the vehicle-side reserve value. "
        "The decomposition supplies accounting evidence. Provider response and "
        "price convergence require separate designs. Stars on total capital and "
        "quantity test zero using Holm-adjusted p-values across the 27 "
        "venue--horizon--outcome estimates. Asterisks \\(*\\), \\(**\\), and "
        "\\(***\\) denote "
        "significance at the 10\\%, 5\\%, and 1\\% levels. Under "
        "constant-product equilibrium, a stable peg, a common endpoint price, "
        "and synchronized reserve states, the unit-value reference is +0.0500 "
        "log point. Its 1-, 3-, and 7-day estimates are "
        f"{estimates}, economically close but {differences} above the reference, "
        "respectively (Holm-adjusted benchmark $p<0.001$ in each case across "
        "the nine venue--horizon unit-value estimates)."
    )


def render_eth_decline_v2_accounting(
    results: pd.DataFrame, support: pd.DataFrame
) -> str:
    """Return the compact pooled accounting table body."""

    rows, design = _validate(results, support)
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}l*{3}{>{\centering\arraybackslash}X}r@{}}",
        r"\toprule",
        r"& \multicolumn{3}{c}{Stablecoin minus WETH [log points per 0.10-log-point ETH price fall]} & \\",
        r"\cmidrule(lr){2-4}",
        r"Horizon & Total capital, $\Delta\ln V$ & Invariant-unit component, "
        r"$\Delta\ln\sqrt{k}$ & Unit value, $\Delta\ln(V/\sqrt{k})$ & Obs. \\",
        r"\midrule",
    ]
    for horizon, _suffix in HORIZONS:
        cells = [
            _cell(
                rows[(horizon, outcome)],
                zero_null=outcome in ZERO_NULL_OUTCOMES,
            )
            for outcome, _label in OUTCOMES
        ]
        observations = int(
            rows[(horizon, "stable_minus_weth_log_capital_change")]["observations"]
        )
        lines.append(
            f"{horizon} day" + ("s" if horizon != 1 else "") + " & "
            + " & ".join(cells)
            + f" & {observations:,} \\\\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(lines)


def render_eth_decline_v2_accounting_values(
    results: pd.DataFrame, support: pd.DataFrame
) -> str:
    """Return prose-ready macros from the same validated pooled rows."""

    rows, design = _validate(results, support)
    lines = [
        "% Generated by scripts/tabulate/render_eth_decline_v2_accounting.py; do not edit."
    ]
    for horizon, horizon_suffix in HORIZONS:
        for outcome, outcome_suffix in OUTCOMES:
            row = rows[(horizon, outcome)]
            prefix = f"EthVTwoAccounting{outcome_suffix}{horizon_suffix}"
            lines.extend(
                [
                    _macro(
                        prefix + "EffectLogPoints",
                        f"${float(row['coefficient']):+.4f}$",
                    ),
                    _macro(
                        prefix + "EffectApproxPercent",
                        f"${100.0 * float(row['coefficient']):+.2f}\\%$",
                    ),
                    _macro(
                        prefix + "SELogPoints",
                        f"${float(row['standard_error']):.4f}$",
                    ),
                ]
            )
            if outcome in ZERO_NULL_OUTCOMES:
                lines.append(_macro(prefix + "HolmP", _tex_p(row["holm_p_value"])))
            else:
                lines.extend(
                    [
                        _macro(
                            prefix + "BenchmarkDifferenceLogPoints",
                            f"${float(row['difference_from_benchmark']):+.4f}$",
                        ),
                        _macro(
                            prefix + "BenchmarkDifferenceApproxPercent",
                            f"${100.0 * float(row['difference_from_benchmark']):+.2f}\\%$",
                        ),
                        _macro(
                            prefix + "BenchmarkRawP",
                            _tex_p(row["benchmark_p_value"]),
                        ),
                        _macro(
                            prefix + "BenchmarkHolmP",
                            _tex_p(row["benchmark_holm_p_value"]),
                        ),
                    ]
                )
        anchor = rows[(horizon, "stable_minus_weth_log_capital_change")]
        lines.extend(
            [
                _macro(
                    f"EthVTwoAccounting{horizon_suffix}Intervals",
                    _tex_integer(anchor["observations"]),
                ),
                _macro(
                    f"EthVTwoAccounting{horizon_suffix}Endpoints",
                    _tex_integer(anchor["endpoints"]),
                ),
                _macro(
                    f"EthVTwoAccounting{horizon_suffix}Dates",
                    _tex_integer(anchor["dates"]),
                ),
            ]
        )
    lines.extend(
        [
            _macro(
                "EthVTwoAccountingCapitalApproxPercentRange",
                r"about 4--5\%",
            ),
            _macro(
                "EthVTwoAccountingQuantityApproxPercentRange",
                r"$-1.8\%$ to $-0.8\%$",
            ),
            _macro(
                "EthVTwoAccountingIntervalRange",
                "78{,}262--79{,}583",
            ),
            _macro("EthVTwoAccountingEndpointRange", "375--405"),
            _macro(
                "EthVTwoAccountingUnitValueBenchmarkLogPoints", "$+0.0500$"
            ),
            _macro(
                "EthVTwoAccountingUnitValueBenchmarkApproxPercent", "$+5.00\\%$"
            ),
            _macro(
                "EthVTwoAccountingMaterialPoolCapital",
                rf"\${_tex_integer(design['material_anchor_pool_capital_usd'])}",
            ),
            _macro(
                "EthVTwoAccountingCompleteFollowupShare",
                f"{100.0 * float(design['complete_followup_share']):.1f}\\%",
            ),
            _macro(
                "EthVTwoAccountingCompleteFollowupCellRange",
                f"{100.0 * float(design['minimum_venue_horizon_complete_followup_share']):.1f}--"
                f"{100.0 * float(design['maximum_venue_horizon_complete_followup_share']):.1f}\\%",
            ),
            _macro(
                "EthVTwoAccountingSinglePricedEndpointShare",
                f"{100.0 * float(design['single_priced_endpoint_interval_share_in_primary']):.1f}\\%",
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    support = pd.read_json(SUPPORT, lines=True)
    write_table_artifacts(
        "eth_decline_v2_accounting",
        render_eth_decline_v2_accounting(results, support),
        preview_width="8.8in",
    )
    with atomic_output(VALUES) as temporary:
        temporary.write_text(
            render_eth_decline_v2_accounting_values(results, support),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

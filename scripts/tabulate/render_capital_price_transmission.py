#!/usr/bin/env python3
"""Render the compact capital-to-price-to-route transmission table."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


CHOICE_RESULTS = OUTPUT_DIR / "exhibits/contestable_vehicle_choice.jsonl"
CROSSING_RESULTS = OUTPUT_DIR / "exhibits/price_rank_crossing.jsonl"
EXECUTABILITY_RESULTS = OUTPUT_DIR / "exhibits/eth_stress_executability.jsonl"


def _one(frame: pd.DataFrame, selector: dict[str, object], name: str) -> pd.Series:
    selected = frame
    for column, value in selector.items():
        if column not in selected.columns:
            raise ValueError(f"{name} lacks {column}")
        selected = selected.loc[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one {name} row for {selector}; found {len(selected)}")
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


def _bp_cell(row: pd.Series) -> str:
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${100.0 * float(row['coefficient']):+.2f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({100.0 * float(row['standard_error']):.2f})$"
        r"\end{tabular}"
    )


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}"


def render_capital_price_transmission(
    choice: pd.DataFrame,
    crossing: pd.DataFrame,
    executability: pd.DataFrame,
) -> str:
    """Return three short regression panels linking capital, prices, and routes."""

    capital_to_output = _one(
        executability,
        {
            "record_type": "eth_stress_executability_regression",
            "model_id": "m4_output_advantage_conditioned_on_depth",
            "sample": "common_exact_routes_positive_both_v2_weak_legs",
            "outcome": "stable_output_advantage_100bp",
            "predictor": "stable_v2_capital_advantage_10pp",
        },
        "capital-to-exact-output",
    )
    if capital_to_output["fixed_effects"] != "ordered_pair+calendar_month":
        raise ValueError(
            "capital-to-exact-output model requires pair and calendar-month effects"
        )
    if capital_to_output["covariance"] != "ordered_pair_and_exact_date_cluster_cr1":
        raise ValueError(
            "capital-to-exact-output model requires pair/exact-date clustering"
        )
    if (
        capital_to_output["exact_route_state"]
        != "same_pair_notional_pretrade_state_and_public_venue_set"
    ):
        raise ValueError(
            "capital-to-exact-output model requires a common exact-route state"
        )

    choice_base = {
        "record_type": "contestable_vehicle_choice_regression",
        "sample": "mature_exclusive_entry_positive_v2_bridge_capital",
        "outcome": "incumbent_retained",
    }
    price_only_output = _one(
        choice,
        {
            **choice_base,
            "model_id": "exclusive_retention_price_only_positive_v2_capital",
            "regressor": "incumbent_output_advantage_100bp",
        },
        "price-only route-retention",
    )
    joint_output = _one(
        choice,
        {
            **choice_base,
            "model_id": "exclusive_retention_price_v2_capital",
            "regressor": "incumbent_output_advantage_100bp",
        },
        "joint route-retention output",
    )
    joint_capital = _one(
        choice,
        {
            **choice_base,
            "model_id": "exclusive_retention_price_v2_capital",
            "regressor": "incumbent_v2_capital_advantage_10pp",
        },
        "joint route-retention capital",
    )
    for row in (price_only_output, joint_output, joint_capital):
        if row["fixed_effects"] != "ordered_endpoint_pair+calendar_date":
            raise ValueError("route-retention models require pair and date effects")
        if row["covariance"] != "two_way_ordered_pair_calendar_date_cr1":
            raise ValueError("route-retention models require pair/date clustering")
    if int(price_only_output["observations"]) != int(joint_output["observations"]):
        raise ValueError("route-retention columns must use the same observations")

    persistence = _one(
        crossing,
        {
            "record_type": "price_rank_crossing_regression",
            "model_id": "material_next_month_price_rank_persistence",
            "sample": "material_crossings_with_next_month",
            "outcome": "challenger_leads_next_month",
            "regressor": "challenger_capital_share_10pp",
        },
        "price-rank persistence",
    )
    crossing_change = _one(
        crossing,
        {
            "record_type": "price_rank_crossing_regression",
            "model_id": "actual_crossing_vs_pre_event_placebo",
            "sample": "material_crossings_with_months_minus3_to_zero",
            "outcome": "route_share_change",
            "regressor": "actual_crossing",
        },
        "crossing route-share change",
    )
    if persistence["fixed_effects"] != "crossing_calendar_month":
        raise ValueError("price-rank persistence requires crossing-month effects")
    if persistence["covariance"] != "two_way_ordered_pair_calendar_month_cr1":
        raise ValueError("price-rank persistence requires pair/month clustering")
    if crossing_change["fixed_effects"] != "crossing_event":
        raise ValueError("crossing comparison requires event effects")
    if crossing_change["covariance"] != "ordered_pair_cluster_cr1":
        raise ValueError("crossing comparison requires pair clustering")

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.55\hsize\raggedright\arraybackslash}X*{2}{>{\hsize=.725\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"\multicolumn{3}{@{}l}{\textit{Panel A. Full-range capital and size-specific exact output}} \\",
        r"Outcome; estimate [bp] & \multicolumn{2}{c}{Stablecoin exact-output advantage} \\",
        r"\midrule",
        "Stablecoin prior full-range capital-share advantage [10 pp] & "
        + r"\multicolumn{2}{c}{"
        + _bp_cell(capital_to_output)
        + r"} \\",
        r"\addlinespace",
        r"Observations & \multicolumn{2}{c}{"
        + _integer(capital_to_output["observations"])
        + r"} \\",
        r"Ordered endpoint pairs & \multicolumn{2}{c}{"
        + _integer(capital_to_output["ordered_pairs"])
        + r"} \\",
        r"Pair and calendar-month fixed effects & \multicolumn{2}{c}{Yes} \\",
        r"\midrule",
        r"\multicolumn{3}{@{}l}{\textit{Panel B. Route retention inside established endpoint pairs}} \\",
        r" & (1) & (2) \\",
        r"Outcome; estimates [pp] & Incumbent retained & Incumbent retained \\",
        r"\midrule",
        "Incumbent exact-output advantage [100 bp] & "
        + _cell(price_only_output)
        + " & "
        + _cell(joint_output)
        + r" \\",
        "Incumbent prior full-range capital-share advantage [10 pp] &  & "
        + _cell(joint_capital)
        + r" \\",
        r"\addlinespace",
        r"Dependent mean [\%] & "
        + f"{100.0 * float(price_only_output['dependent_mean']):.1f} & "
        + f"{100.0 * float(joint_output['dependent_mean']):.1f}"
        + r" \\",
        "Within $R^2$ & "
        + f"{float(price_only_output['within_r_squared']):.3f} & "
        + f"{float(joint_output['within_r_squared']):.3f}"
        + r" \\",
        "Observations & "
        + _integer(price_only_output["observations"])
        + " & "
        + _integer(joint_output["observations"])
        + r" \\",
        "Pair clusters & "
        + _integer(price_only_output["ordered_pair_clusters"])
        + " & "
        + _integer(joint_output["ordered_pair_clusters"])
        + r" \\",
        r"Pair and date fixed effects & Yes & Yes \\",
        r"\midrule",
        r"\multicolumn{3}{@{}l}{\textit{Panel C. Route allocation when exact-price leadership changes}} \\",
        r" & (1) & (2) \\",
        r"Outcome; estimates [pp] & Challenger leads next month & Incumbent-share change \\",
        r"\midrule",
        "Challenger prior weak-leg capital share [10 pp] & "
        + _cell(persistence)
        + r" &  \\",
        "Exact-price crossing [vs. the same event's earlier movement] &  & "
        + _cell(crossing_change)
        + r" \\",
        r"\addlinespace",
        "Observations & "
        + _integer(persistence["observations"])
        + " & "
        + _integer(crossing_change["observations"])
        + r" \\",
        "Ordered endpoint pairs & "
        + _integer(persistence["ordered_pairs"])
        + " & "
        + _integer(crossing_change["ordered_pairs"])
        + r" \\",
        r"Crossing-month fixed effects & Yes & No \\",
        r"Crossing-event fixed effects & No & Yes \\",
        r"\bottomrule",
        r"\end{tabularx}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    choice = pd.read_json(CHOICE_RESULTS, lines=True)
    crossing = pd.read_json(CROSSING_RESULTS, lines=True)
    executability = pd.read_json(EXECUTABILITY_RESULTS, lines=True)
    write_table_artifacts(
        "capital_price_transmission",
        render_capital_price_transmission(choice, crossing, executability),
        preview_width="8.0in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render the exact pre-transaction vehicle frontier table and shared values."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_presentation_source
from ddvc.runtime import atomic_output


RESULTS = OUTPUT_DIR / "exhibits/exact_vehicle_frontier_monthly.jsonl"
VALUES = OUTPUT_DIR / "exhibits/exact_vehicle_frontier_values.tex"


def _single(frame: pd.DataFrame, **conditions: object) -> pd.Series:
    selected = frame
    for column, value in conditions.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one row for {conditions}; found {len(selected)}")
    return selected.iloc[0]


def _integer(value: float) -> str:
    return f"{value:,.0f}".replace(",", "{,}")


def _pct(value: float, decimals: int = 1) -> str:
    return f"{100.0 * value:.{decimals}f}"


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _estimate_cell(row: pd.Series) -> str:
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${float(row['change_pp']):+.2f}{_stars(float(row['p_value_holm']))}$"
        r"\\"
        f"$({float(row['standard_error_pp']):.2f})$"
        r"\end{tabular}"
    )


def _selected_rows(results: pd.DataFrame) -> dict[str, pd.Series]:
    required = {
        "record_type",
        "scope",
        "label",
        "routes",
        "dates",
        "chosen_stable_share",
        "public_stable_share",
        "gain_over_1bp_share",
        "within_reach_regret_over_1bp_share",
        "same_vehicle_public_regret_over_1bp_share",
        "median_gain_bps_if_over_1bp",
        "gain_over_100pct_routes",
        "change_pp",
        "standard_error_pp",
        "p_value_holm",
        "exact_venue_share",
        "chosen_reproduction_share",
        "minimum_input_usd",
        "gain_threshold_bps",
        "max_price_impact",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"exact frontier results lack columns: {missing}")
    rows = {
        "main": _single(
            results,
            record_type="frontier_summary",
            scope="pooled",
            label="common_support",
        ),
        "standard": _single(
            results,
            record_type="frontier_summary",
            scope="pooled",
            label="common_support_standard_quote",
        ),
        "high": _single(
            results,
            record_type="frontier_summary",
            scope="pooled",
            label="common_support_at_least_10000usd",
        ),
        "route": _single(
            results,
            record_type="stable_share_inference",
            scope="common_support",
            label="route",
        ),
        "value": _single(
            results,
            record_type="stable_share_inference",
            scope="common_support",
            label="input_value",
        ),
        "high_route": _single(
            results,
            record_type="stable_share_inference",
            scope="common_support_at_least_10000usd",
            label="route",
        ),
        "support": _single(
            results,
            record_type="frontier_support",
            scope="period",
            label="pooled",
        ),
    }
    main, standard = rows["main"], rows["standard"]
    if not (
        int(main["routes"]) > 700_000
        and float(main["same_vehicle_public_regret_over_1bp_share"]) > 0.40
        and float(main["gain_over_1bp_share"])
        - float(main["same_vehicle_public_regret_over_1bp_share"])
        < 0.05
        and abs(float(rows["route"]["change_pp"])) < 3.0
        and abs(
            float(main["gain_over_1bp_share"])
            - float(standard["gain_over_1bp_share"])
        )
        < 0.001
    ):
        raise ValueError("exact frontier headline no longer holds; reassess the result")
    return rows


def render_exact_vehicle_frontier(results: pd.DataFrame) -> str:
    rows = _selected_rows(results)
    main, route, value = rows["main"], rows["route"], rows["value"]
    within = float(main["within_reach_regret_over_1bp_share"])
    same = float(main["same_vehicle_public_regret_over_1bp_share"])
    public = float(main["gain_over_1bp_share"])
    chosen_stable = float(main["chosen_stable_share"])
    public_stable = float(main["public_stable_share"])
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X*{4}{>{\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"\multicolumn{5}{l}{\textit{Panel A. Coverage and quote validation}} \\",
        "Linear routes in the exact venue set [\\%] & "
        + rf"\multicolumn{{4}}{{r}}{{{_pct(float(rows['support']['exact_venue_share']))}}} \\",
        "Mapped observed routes reproduced within 1 bp [\\%] & "
        + rf"\multicolumn{{4}}{{r}}{{{_pct(float(rows['support']['chosen_reproduction_share']))}}} \\",
        r"\midrule",
        r"\multicolumn{5}{l}{\textit{Panel B. Nested opportunity set}} \\",
        r" & Realised route & Same vehicle, used venues & Same vehicle, all exact venues & Any named vehicle or direct \\",
        r"\midrule",
        r"Routes with more than 1 bp higher output [\%] & "
        f"0.0 & {_pct(within)} & {_pct(same)} & {_pct(public)} " + r"\\",
        r"Stablecoin vehicle share [\%] & "
        f"{_pct(chosen_stable)} & {_pct(chosen_stable)} & {_pct(chosen_stable)} & {_pct(public_stable)} "
        + r"\\",
        r"\midrule",
        "Full-set minus realised stablecoin share [pp] & "
        + r"\multicolumn{3}{r}{Route weighted} & "
        + _estimate_cell(route)
        + r" \\",
        " & "
        + r"\multicolumn{3}{r}{Input-value weighted} & "
        + _estimate_cell(value)
        + r" \\",
        r"\midrule",
        "Routes / dates & "
        + rf"\multicolumn{{4}}{{r}}{{{_integer(float(main['routes']))} / {int(main['dates'])}}} \\",
        r"\bottomrule",
        r"\end{tabularx}",
        "",
    ]
    return "\n".join(lines)


def render_values(results: pd.DataFrame) -> str:
    rows = _selected_rows(results)
    main, high, route, value, support = (
        rows["main"],
        rows["high"],
        rows["route"],
        rows["value"],
        rows["support"],
    )
    additional = float(main["gain_over_1bp_share"]) - float(
        main["same_vehicle_public_regret_over_1bp_share"]
    )
    lines = [
        "% Generated by scripts/tabulate/render_exact_vehicle_frontier.py; do not edit.",
        f"\\newcommand{{\\ExactFrontierRoutes}}{{{_integer(float(main['routes']))}}}",
        f"\\newcommand{{\\ExactFrontierDates}}{{{int(main['dates'])}}}",
        f"\\newcommand{{\\ExactFrontierMinimumInput}}{{\\${float(main['minimum_input_usd']):,.0f}}}",
        f"\\newcommand{{\\ExactFrontierGainThreshold}}{{{float(main['gain_threshold_bps']):.0f} bp}}",
        f"\\newcommand{{\\ExactFrontierImpactLimit}}{{{100.0 * float(main['max_price_impact']):.0f}\\%}}",
        f"\\newcommand{{\\ExactFrontierWithinShare}}{{{_pct(float(main['within_reach_regret_over_1bp_share']))}\\%}}",
        f"\\newcommand{{\\ExactFrontierSameVehicleShare}}{{{_pct(float(main['same_vehicle_public_regret_over_1bp_share']))}\\%}}",
        f"\\newcommand{{\\ExactFrontierAllPathShare}}{{{_pct(float(main['gain_over_1bp_share']))}\\%}}",
        f"\\newcommand{{\\ExactFrontierVehicleAddition}}{{{100.0 * additional:.1f} pp}}",
        f"\\newcommand{{\\ExactFrontierMedianGain}}{{{float(main['median_gain_bps_if_over_1bp']):.1f} bp}}",
        f"\\newcommand{{\\ExactFrontierStableChange}}{{{float(route['change_pp']):+.1f} pp}}",
        f"\\newcommand{{\\ExactFrontierStableDecline}}{{{abs(float(route['change_pp'])):.1f} pp}}",
        f"\\newcommand{{\\ExactFrontierStableChangeSE}}{{{float(route['standard_error_pp']):.1f} pp}}",
        f"\\newcommand{{\\ExactFrontierStableValueChange}}{{{float(value['change_pp']):+.1f} pp}}",
        f"\\newcommand{{\\ExactFrontierStableValueDecline}}{{{abs(float(value['change_pp'])):.1f} pp}}",
        f"\\newcommand{{\\ExactFrontierHighNotionalChange}}{{{float(rows['high_route']['change_pp']):+.1f} pp}}",
        f"\\newcommand{{\\ExactFrontierHighNotionalDecline}}{{{abs(float(rows['high_route']['change_pp'])):.1f} pp}}",
        f"\\newcommand{{\\ExactFrontierHighNotionalRoutes}}{{{_integer(float(high['routes']))}}}",
        f"\\newcommand{{\\ExactFrontierVenueCoverage}}{{{_pct(float(support['exact_venue_share']))}\\%}}",
        f"\\newcommand{{\\ExactFrontierReproduction}}{{{_pct(float(support['chosen_reproduction_share']))}\\%}}",
        f"\\newcommand{{\\ExactFrontierExtremeRoutes}}{{{_integer(float(main['gain_over_100pct_routes']))}}}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    require_presentation_source(RESULTS)
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "exact_vehicle_frontier",
        render_exact_vehicle_frontier(results),
        preview_width="8.5in",
    )
    with atomic_output(VALUES) as temporary:
        temporary.write_text(render_values(results), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

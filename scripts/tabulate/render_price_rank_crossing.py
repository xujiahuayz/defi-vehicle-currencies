#!/usr/bin/env python3
"""Render price-rank crossing dynamics and regressions."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.runtime import atomic_output


RESULTS = OUTPUT_DIR / "exhibits/price_rank_crossing.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/price_rank_crossing_support.jsonl"
VALUES = OUTPUT_DIR / "exhibits/price_rank_crossing_values.tex"

MODEL_COLUMNS = (
    "material_immediate_route_share_change",
    "material_next_month_price_rank_persistence",
    "all_next_month_price_rank_persistence",
    "actual_crossing_vs_pre_event_placebo",
)


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}"


def _event_row(
    results: pd.DataFrame, *, dimension: str, event_time: int
) -> pd.Series:
    selected = results[
        results["record_type"].eq("price_rank_crossing_event_time")
        & results["sample"].eq("material_balanced_seven_month")
        & results["dimension"].eq(dimension)
        & results["event_time_month"].eq(event_time)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one {dimension} event-time row at {event_time}; "
            f"found {len(selected)}"
        )
    return selected.iloc[0]


def _model_row(results: pd.DataFrame, model_id: str, regressor: str) -> pd.Series:
    selected = results[
        results["record_type"].eq("price_rank_crossing_regression")
        & results["model_id"].eq(model_id)
        & results["regressor"].eq(regressor)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one {regressor} row for {model_id}; found {len(selected)}"
        )
    return selected.iloc[0]


def _follow_up_row(results: pd.DataFrame, follow_up_rank: str) -> pd.Series:
    selected = results[
        results["record_type"].eq("price_rank_crossing_follow_up")
        & results["sample"].eq("material_crossings_with_next_month")
        & results["follow_up_rank"].eq(follow_up_rank)
    ]
    if len(selected) != 1:
        raise ValueError(
            f"expected one follow-up row for {follow_up_rank}; found {len(selected)}"
        )
    return selected.iloc[0]


def _validate(results: pd.DataFrame, support: pd.DataFrame) -> None:
    required_results = {
        "record_type",
        "sample",
        "events",
        "ordered_pairs",
    }
    required_support = {
        "record_type",
        "material_events",
        "material_event_pairs",
        "material_stable_challenger_events",
        "material_native_challenger_events",
        "material_balanced_seven_month_events",
        "price_lead_threshold_bps",
        "material_minimum_routes_each_crossing_month",
        "material_minimum_input_usd_each_crossing_month",
        "event_selection_uses_future_information",
    }
    missing_results = sorted(required_results - set(results.columns))
    missing_support = sorted(required_support - set(support.columns))
    if missing_results:
        raise ValueError(f"price-rank results lack fields: {missing_results}")
    if missing_support:
        raise ValueError(f"price-rank support lacks fields: {missing_support}")
    if len(support) != 1:
        raise ValueError("price-rank support must contain one row")
    row = support.iloc[0]
    if bool(row["event_selection_uses_future_information"]):
        raise ValueError("price-rank event dating must exclude future information")
    if float(row["price_lead_threshold_bps"]) != 1.0:
        raise ValueError("price-rank table requires the one-basis-point threshold")
    if int(row["material_stable_challenger_events"]) != int(
        row["material_native_challenger_events"]
    ):
        raise ValueError("reverse crossing counts no longer balance")
    if int(row["material_minimum_routes_each_crossing_month"]) != 2:
        raise ValueError("material crossing sample requires two monthly quotes")
    if float(row["material_minimum_input_usd_each_crossing_month"]) != 1_000.0:
        raise ValueError("material crossing sample requires $1,000 per month")
    for dimension in ("all_crossings", "stable_challenger", "native_challenger"):
        for event_time in range(-3, 4):
            _event_row(results, dimension=dimension, event_time=event_time)
    for model_id in MODEL_COLUMNS[:3]:
        _model_row(results, model_id, "challenger_capital_share_10pp")
    _model_row(results, MODEL_COLUMNS[3], "actual_crossing")
    _model_row(
        results,
        MODEL_COLUMNS[3],
        "actual_x_challenger_capital_share_10pp",
    )


def _event_cell(row: pd.Series) -> str:
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"{float(row['mean_incumbent_route_share_pp']):.1f}"
        r"\\"
        f"({float(row['standard_error_pp']):.1f})"
        r"\end{tabular}"
    )


def _estimate_cell(row: pd.Series) -> str:
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${float(row['coefficient_pp']):+.2f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({float(row['standard_error_pp']):.2f})$"
        r"\end{tabular}"
    )


def _blank() -> str:
    return ""


def render_price_rank_crossing(
    results: pd.DataFrame, support: pd.DataFrame
) -> str:
    """Return the event-time and regression panels as a TeX fragment."""

    _validate(results, support)
    event_lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.25\hsize\raggedright\arraybackslash}X*{3}{>{\hsize=.75\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"\multicolumn{4}{@{}l}{\textit{Panel A. Incumbent route share around an exact-price rank crossing [pp]}} \\",
        r"Event month & All crossings & Stable challenger & Native challenger \\",
        r"\midrule",
    ]
    for event_time in range(-3, 4):
        label = f"{event_time:+d}" if event_time else "0 (crossing)"
        cells = [
            _event_cell(_event_row(results, dimension=dimension, event_time=event_time))
            for dimension in (
                "all_crossings",
                "stable_challenger",
                "native_challenger",
            )
        ]
        event_lines.append(label + " & " + " & ".join(cells) + r" \\")
    event_lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
        ]
    )

    capital_rows = [
        _model_row(results, model_id, "challenger_capital_share_10pp")
        for model_id in MODEL_COLUMNS[:3]
    ]
    placebo_actual = _model_row(results, MODEL_COLUMNS[3], "actual_crossing")
    placebo_capital = _model_row(
        results,
        MODEL_COLUMNS[3],
        "actual_x_challenger_capital_share_10pp",
    )
    model_support = [
        _model_row(results, model_id, "stable_challenger")
        for model_id in MODEL_COLUMNS[:3]
    ] + [placebo_actual]
    regression_lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.55\hsize\raggedright\arraybackslash}X*{4}{>{\hsize=.75\hsize\centering\arraybackslash}X}@{}}",
        r"\toprule",
        r"\multicolumn{5}{@{}l}{\textit{Panel B. Immediate response and next-month price-rank persistence}} \\",
        r" & \multicolumn{1}{c}{Incumbent-share change} & \multicolumn{2}{c}{Challenger leads next month} & \multicolumn{1}{c}{Actual vs. placebo} \\",
        r"\cmidrule(lr){2-2}\cmidrule(lr){3-4}\cmidrule(l){5-5}",
        r" & Activity floor & Activity floor & All crossings & Activity floor \\",
        r" & (1) & (2) & (3) & (4) \\",
        r"\midrule",
        r"Challenger weak-leg capital share, $Q_{e,-1}$ [10 pp] & "
        + " & ".join([*(_estimate_cell(row) for row in capital_rows), _blank()])
        + r" \\",
        "Actual crossing [vs. months -3 to -2] & "
        + " & ".join([_blank(), _blank(), _blank(), _estimate_cell(placebo_actual)])
        + r" \\",
        r"Actual crossing $\times$ challenger capital [10 pp] & "
        + " & ".join([_blank(), _blank(), _blank(), _estimate_cell(placebo_capital)])
        + r" \\",
        r"\addlinespace",
        r"Crossing controls & Yes & Yes & Yes & Yes \\",
        r"Crossing-month fixed effects & Yes & Yes & Yes & No \\",
        r"Crossing-event fixed effects & No & No & No & Yes \\",
        "Observations & "
        + " & ".join(_integer(row["observations"]) for row in model_support)
        + r" \\",
        "Crossing events & "
        + " & ".join(_integer(row["events"]) for row in model_support)
        + r" \\",
        "Ordered endpoint pairs & "
        + " & ".join(_integer(row["ordered_pairs"]) for row in model_support)
        + r" \\",
        r"\bottomrule",
        r"\end{tabularx}",
    ]
    return (
        "\n".join(event_lines)
        + "\n\n\\vspace{0.65em}\n\n"
        + "\n".join(regression_lines)
        + "\n"
    )


def render_price_rank_crossing_values(
    results: pd.DataFrame, support: pd.DataFrame
) -> str:
    """Return generated paper/deck macros for the promoted estimates."""

    _validate(results, support)
    support_row = support.iloc[0]
    prior = _event_row(results, dimension="all_crossings", event_time=-1)
    crossing = _event_row(results, dimension="all_crossings", event_time=0)
    following = _event_row(results, dimension="all_crossings", event_time=1)
    placebo = _model_row(results, MODEL_COLUMNS[3], "actual_crossing")
    capital = _model_row(
        results, MODEL_COLUMNS[1], "challenger_capital_share_10pp"
    )
    still_ahead = _follow_up_row(results, "challenger_still_ahead")
    retaken = _follow_up_row(results, "incumbent_ahead_again")

    def pct(value: object) -> str:
        return f"{100.0 * float(value):.1f}\\%"

    def pp(value: object, digits: int = 1) -> str:
        return f"{float(value):.{digits}f}~pp"

    lines = [
        "% Generated by scripts/tabulate/render_price_rank_crossing.py; do not edit.",
        f"\\newcommand{{\\RankCrossingEvents}}{{{int(support_row['material_events']):,}}}",
        f"\\newcommand{{\\RankCrossingPairs}}{{{int(support_row['material_event_pairs']):,}}}",
        f"\\newcommand{{\\RankCrossingBalancedEvents}}{{{int(support_row['material_balanced_seven_month_events']):,}}}",
        f"\\newcommand{{\\RankCrossingPriorShare}}{{{pct(float(prior['mean_incumbent_route_share']))}}}",
        f"\\newcommand{{\\RankCrossingCurrentShare}}{{{pct(float(crossing['mean_incumbent_route_share']))}}}",
        f"\\newcommand{{\\RankCrossingNextShare}}{{{pct(float(following['mean_incumbent_route_share']))}}}",
        f"\\newcommand{{\\RankCrossingPlaceboEffect}}{{{pp(float(placebo['coefficient_pp']))}}}",
        f"\\newcommand{{\\RankCrossingPlaceboDrop}}{{{pp(abs(float(placebo['coefficient_pp'])))}}}",
        f"\\newcommand{{\\RankCrossingCapitalPersistence}}{{{pp(float(capital['coefficient_pp']), 2)}}}",
        f"\\newcommand{{\\RankCrossingStillAhead}}{{{pct(float(still_ahead['event_share']))}}}",
        f"\\newcommand{{\\RankCrossingRetaken}}{{{pct(float(retaken['event_share']))}}}",
        f"\\newcommand{{\\RankCrossingStillAheadShare}}{{{pct(float(still_ahead['mean_incumbent_route_share']))}}}",
        f"\\newcommand{{\\RankCrossingRetakenShare}}{{{pct(float(retaken['mean_incumbent_route_share']))}}}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    support = pd.read_json(SUPPORT, lines=True)
    write_table_artifacts(
        "price_rank_crossing",
        render_price_rank_crossing(results, support),
        preview_width="8.5in",
    )
    with atomic_output(VALUES) as temporary:
        temporary.write_text(
            render_price_rank_crossing_values(results, support), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

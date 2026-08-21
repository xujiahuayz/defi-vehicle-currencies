#!/usr/bin/env python3
"""Render bridge formation dated from prior-calendar deposited capital."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR
from ddvc.tables import read_exhibit


RESULTS = OUTPUT_DIR / "exhibits/bridge_exante.jsonl"


def _one(results: pd.DataFrame, record_type: str, model_id: str, **filters: object) -> pd.Series:
    selected = results[
        results["record_type"].eq(record_type) & results["model_id"].eq(model_id)
    ]
    for column, value in filters.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(
            f"expected one {record_type}/{model_id} row with {filters}; found {len(selected)}"
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


def _regression_cell(row: pd.Series, estimate: str, standard_error: str) -> str:
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${float(row[estimate]):+.2f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({float(row[standard_error]):.2f})$"
        r"\end{tabular}"
    )


def render_bridge_exante(results: pd.DataFrame) -> str:
    adoption_30 = _one(
        results, "exante_bridge_adoption", "within_30_days"
    )
    adoption_120 = _one(
        results, "exante_bridge_adoption", "within_120_days"
    )
    retention = _one(
        results,
        "exante_bridge_retention",
        "stable_route_observed_days_30_119",
    )
    retained_share = _one(
        results,
        "exante_bridge_retention",
        "stable_route_share_days_30_119",
    )
    change_30 = _one(
        results,
        "exante_bridge_paired_change",
        "stable_route_share_change",
        period="post_0_29",
    )
    change_120 = _one(
        results,
        "exante_bridge_paired_change",
        "stable_route_share_change",
        period="post_30_119",
    )
    depth_30 = _one(
        results,
        "exante_bridge_relative_depth",
        "stable_route_share_on_relative_depth",
        period="post_0_29",
    )
    depth_120 = _one(
        results,
        "exante_bridge_relative_depth",
        "stable_route_share_on_relative_depth",
        period="post_30_119",
    )

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xcc@{}}",
        r"\toprule",
        r"Quantity & Estimate & Events \\",
        r"\midrule",
        r"\multicolumn{3}{@{}l}{\textit{Panel A. Route use after the lagged-capital threshold}} \\",
        f"First supported stablecoin route within 30 days & "
        f"{100 * float(adoption_30['estimate']):.1f}\\% & {int(adoption_30['events']):,} "
        + r"\\",
        f"First supported stablecoin route within 120 days & "
        f"{100 * float(adoption_120['estimate']):.1f}\\% & {int(adoption_120['events']):,} "
        + r"\\",
        f"Stablecoin used during days 30--119, among first-month adopters & "
        f"{100 * float(retention['estimate']):.1f}\\% & {int(retention['events']):,} "
        + r"\\",
        f"Stablecoin route share during days 30--119, same pairs & "
        f"{100 * float(retained_share['estimate']):.1f}\\% & {int(retained_share['events']):,} "
        + r"\\",
        r"\addlinespace",
        r"\multicolumn{3}{@{}l}{\textit{Panel B. Change from the prior 30 calendar days}} \\",
        "Stablecoin route share, days 0--29 [pp] & "
        + _regression_cell(change_30, "coefficient_pp", "standard_error_pp")
        + f" & {int(change_30['events']):,} "
        + r"\\",
        "Stablecoin route share, days 30--119 [pp] & "
        + _regression_cell(change_120, "coefficient_pp", "standard_error_pp")
        + f" & {int(change_120['events']):,} "
        + r"\\",
        r"\addlinespace",
        r"\multicolumn{3}{@{}l}{\textit{Panel C. Prior-day weak-leg depth and route allocation}} \\",
        r"10 pp higher stablecoin share of relative depth, days 0--29 [pp] & "
        + _regression_cell(
            depth_30,
            "coefficient_pp_per_10pp_depth_share",
            "standard_error_pp_per_10pp_depth_share",
        )
        + f" & {int(depth_30['events']):,} "
        + r"\\",
        r"10 pp higher stablecoin share of relative depth, days 30--119 [pp] & "
        + _regression_cell(
            depth_120,
            "coefficient_pp_per_10pp_depth_share",
            "standard_error_pp_per_10pp_depth_share",
        )
        + f" & {int(depth_120['events']):,} "
        + r"\\",
        r"\bottomrule",
        r"\end{tabularx}",
        "% Paper note: The event is the first date on which DAI, USDC, or USDT has at least USD 10,000 of prior-calendar deposited capital on both route legs. Every pair used WETH earlier and has no earlier observed stablecoin route. Panel A follows the stablecoin or stablecoins that cross the threshold on the event date. Panels B and C use all native- and stablecoin-mediated routes. Panel B reports activity-weighted paired changes with pair- and event-date-clustered standard errors. Panel C includes bridge-event effects, calendar-month effects, seven-day event-age controls, and pair- and date-clustered standard errors. Asterisks *, **, and *** denote statistical significance at the 10%, 5%, and 1% levels, respectively.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    results = read_exhibit(RESULTS)
    write_table_artifacts(
        "bridge_exante",
        render_bridge_exante(results),
        preview_width="7.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

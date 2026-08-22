#!/usr/bin/env python3
"""Render exact-chain route-reconstruction validation for the appendix."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


INPUT = OUTPUT_DIR / "exhibits" / "route_reconstruction_exact_chain_validation.jsonl"

VENUE_LABELS = {
    "uniswap_v2": "Uniswap v2",
    "sushiswap_v2": "SushiSwap v2",
    "uniswap_v3": "Uniswap v3",
}
DIMENSION_LABELS = {
    "endpoint_pair": "Endpoint pair",
    "intermediary_identity": "Intermediary tokens",
    "vehicle_class": "Intermediary asset types",
    "leg_count": "Leg count",
    "exact_two_leg_inclusion": "Two-leg inclusion",
}
COMPONENT_LABELS = {
    "total_change": "Stablecoin-share change",
    "within_common": "Within continuing pairs",
    "common_pair_reweighting": "Reallocation across continuing pairs",
    "common_support_mass": "Weight on continuing pairs",
    "exclusive_pair_contribution": "Pairs present in one window",
}


def _pct(value: float, digits: int = 4) -> str:
    return f"{100.0 * float(value):.{digits}f}"


def _pp(value: float, digits: int = 3) -> str:
    return f"{float(value):+.{digits}f}"


def render_table(results: pd.DataFrame) -> str:
    event = results[results["record_type"].eq("event_reconciliation")]
    assignments = results[results["record_type"].eq("route_assignment")]
    shares = results[results["record_type"].eq("stable_share")]
    decomposition = results[
        results["record_type"].eq("sampled_decomposition")
    ]
    boundary = results[results["record_type"].eq("release_boundary")].iloc[0]
    support = results[results["record_type"].eq("support")].iloc[0]

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrrrrr@{}}",
        r"\toprule",
        r"\multicolumn{7}{@{}l}{\textit{Panel A. Swap events against full-day Ethereum logs}} \\",
        r"Venue & Days & Provider swaps & Provider only & Chain only & Precision [\%] & Recall [\%] \\",
        r"\midrule",
    ]
    for venue in ("uniswap_v2", "sushiswap_v2", "uniswap_v3"):
        row = event[event["venue"].eq(venue)].iloc[0]
        lines.append(
            f"{VENUE_LABELS[venue]} & {int(row['audited_days'])} & "
            f"{int(row['provider_swaps']):,} & {int(row['provider_only_swaps']):,} & "
            f"{int(row['chain_only_swaps']):,} & {_pct(row['precision'])} & "
            f"{_pct(row['recall'])} \\\\"
        )
    lines.extend(
        [
            r"\addlinespace",
            r"\multicolumn{7}{@{}l}{\textit{Panel B. Assignments in transactions touched by a swap correction}} \\",
            r"Assignment & \multicolumn{2}{r}{Linked transactions} & \multicolumn{2}{r}{Changed} & \multicolumn{2}{r}{Unchanged [\%]} \\",
            r"\midrule",
        ]
    )
    for dimension in DIMENSION_LABELS:
        row = assignments[assignments["dimension"].eq(dimension)].iloc[0]
        lines.append(
            rf"{DIMENSION_LABELS[dimension]} & \multicolumn{{2}}{{r}}{{{int(row['linked_transactions']):,}}} & "
            rf"\multicolumn{{2}}{{r}}{{{int(row['changed_transactions']):,}}} & "
            rf"\multicolumn{{2}}{{r}}{{{_pct(row['unchanged_share'], 3)}}} \\"
        )
    lines.extend(
        [
            r"\addlinespace",
            r"\multicolumn{7}{@{}l}{\textit{Panel C. Stablecoin shares on corrected route dates}} \\",
            r"Measure & \multicolumn{2}{r}{Provider rows [\%]} & \multicolumn{2}{r}{Corrected rows [\%]} & \multicolumn{2}{r}{Change [pp]} \\",
            r"\midrule",
        ]
    )
    share_labels = {
        "route_count": "Route count",
        "within_20pct_value_usd": "Routed value",
    }
    for metric in share_labels:
        row = shares[shares["metric"].eq(metric)].iloc[0]
        lines.append(
            rf"{share_labels[metric]} & \multicolumn{{2}}{{r}}{{{_pct(row['raw_stable_share'], 3)}}} & "
            rf"\multicolumn{{2}}{{r}}{{{_pct(row['corrected_stable_share'], 3)}}} & "
            rf"\multicolumn{{2}}{{r}}{{{_pp(row['difference_pp'])}}} \\"
        )
    lines.extend(
        [
            r"\addlinespace",
            r"\multicolumn{7}{@{}l}{\textit{Panel D. January--June sampled decomposition, 2024 to 2026 [pp]}} \\",
            r" & \multicolumn{3}{c}{Route count} & \multicolumn{3}{c}{Routed value} \\",
            r"\cmidrule(lr){2-4}\cmidrule(l){5-7}",
            r"Component & Provider & Corrected & Change & Provider & Corrected & Change \\",
            r"\midrule",
        ]
    )
    for component in COMPONENT_LABELS:
        count = decomposition[
            decomposition["metric"].eq("count_share")
            & decomposition["component"].eq(component)
        ].iloc[0]
        value = decomposition[
            decomposition["metric"].eq("strict_intermediation_value_share")
            & decomposition["component"].eq(component)
        ].iloc[0]
        lines.append(
            f"{COMPONENT_LABELS[component]} & {_pp(count['raw_pp'])} & "
            f"{_pp(count['corrected_pp'])} & {_pp(count['difference_pp'])} & "
            f"{_pp(value['raw_pp'])} & {_pp(value['corrected_pp'])} & "
            f"{_pp(value['difference_pp'])} \\\\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    results = pd.read_json(INPUT, lines=True)
    write_table_artifacts(
        "route_reconstruction_exact_chain_validation",
        render_table(results),
        preview_width="10.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render the independent Uniswap v4 route-label validation panel."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


INPUT = OUTPUT_DIR / "exhibits" / "v4_route_label_validation.jsonl"
EVENT_LABELS = {
    "event_identity": "Directional Swap event",
    "pool_identity": "PoolId",
    "pool_currency_identity": "Pool currencies",
    "raw_amount_identity": "Signed raw amounts (covered)",
    "direction_identity": "Input and output currencies",
    "block_identity": "Block number",
}
ROUTE_LABELS = {
    "endpoint_pair": "Endpoint pair",
    "intermediary_identity": "Intermediary currencies",
    "leg_order": "Ordered legs",
}


def _pct(value: object) -> str:
    return "--" if pd.isna(value) else f"{100.0 * float(value):.4f}"


def render_table(results: pd.DataFrame) -> str:
    event = results[results["record_type"].eq("pooled_event_label")]
    route = results[results["record_type"].eq("pooled_route_label")]
    support = results[results["record_type"].eq("support")].iloc[0]
    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrrrr@{}}",
        r"\toprule",
        r"\multicolumn{6}{@{}l}{\textit{Panel A. PoolManager Swap labels}} \\",
        r"Label & Provider & Exact & Precision [\%] & Recall [\%] & \multicolumn{1}{c}{Days} \\",
        r"\midrule",
    ]
    for dimension, label in EVENT_LABELS.items():
        row = event[event["dimension"].eq(dimension)].iloc[0]
        lines.append(
            f"{label} & {int(row['provider_assignments']):,} & "
            f"{int(row['exact_assignments']):,} & {_pct(row['precision'])} & "
            f"{_pct(row['recall'])} & {int(support['covered_days'])} \\\\"
        )
    lines.extend(
        [
            r"\addlinespace",
            rf"\multicolumn{{6}}{{@{{}}l}}{{\textit{{Panel B. Route labels in {int(support['v4_only_observed_transactions']):,} observed v4-only transactions}}}} \\",
            r"Label & Provider & Exact & Precision [\%] & Recall [\%] & Exact tx [\%] \\",
            r"\midrule",
        ]
    )
    for dimension, label in ROUTE_LABELS.items():
        row = route[route["dimension"].eq(dimension)].iloc[0]
        lines.append(
            f"{label} & {int(row['provider_assignments']):,} & "
            f"{int(row['exact_assignments']):,} & {_pct(row['precision'])} & "
            f"{_pct(row['recall'])} & {_pct(row['exact_match_share'])} \\\\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
        ]
    )
    return "\n".join(lines) + "\n"


def main(input_path: Path = INPUT) -> int:
    results = pd.read_json(input_path, lines=True)
    write_table_artifacts(
        "v4_route_label_validation",
        render_table(results),
        preview_width="8.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

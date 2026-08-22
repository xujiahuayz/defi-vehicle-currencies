#!/usr/bin/env python3
"""Render venue-exclusion sensitivities for the pair decomposition."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = (
    OUTPUT_DIR / "exhibits/vehicle_transition_venue_exclusion_decomposition.jsonl"
)
SUPPORT = OUTPUT_DIR / "exhibits/vehicle_transition_venue_exclusion_support.jsonl"

VARIANTS = (
    ("all_venues", "All venues"),
    ("exclude_curve", "Excluding Curve"),
    ("exclude_uniswap_v1", "Excluding Uniswap v1"),
    ("exclude_uniswap_v2", "Excluding Uniswap v2"),
    ("exclude_uniswap_v3", "Excluding Uniswap v3"),
    ("exclude_uniswap_v4", "Excluding Uniswap v4"),
    ("exclude_balancer", "Excluding Balancer"),
    ("exclude_sushiswap_v2", "Excluding SushiSwap v2"),
    ("exclude_sushiswap_v3", "Excluding SushiSwap v3"),
    ("exclude_fluid", "Excluding Fluid"),
    ("audited_venue_families_only", "Uniswap v2/v3 and SushiSwap v2"),
)

PANELS = (
    ("count_share", "Panel A. Route count"),
    ("strict_intermediation_value_share", "Panel B. Routed value"),
)


def _one(frame: pd.DataFrame, **filters: str) -> pd.Series:
    selected = frame
    for column, value in filters.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        detail = ", ".join(f"{key}={value}" for key, value in filters.items())
        raise ValueError(f"expected one row for {detail}, found {len(selected)}")
    return selected.iloc[0]


def _pp(value: object) -> str:
    return f"${float(value):+.2f}$"


def _pct(value: object) -> str:
    return f"{100.0 * float(value):.1f}"


def render_table(results: pd.DataFrame, support: pd.DataFrame) -> str:
    """Return the two-panel venue-exclusion table body."""

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrrrrrr@{}}",
        r"\toprule",
        r"& \multicolumn{5}{c}{Stablecoin-share change [pp]} & \multicolumn{2}{c}{Retained activity [\%]} \\",
        r"\cmidrule(lr){2-6}\cmidrule(l){7-8}",
        r"Venue set & Total & Within & Reweight & Support & Period-only & 2024 H1 & 2026 H1 \\",
        r"\midrule",
    ]
    for panel_index, (metric, panel_label) in enumerate(PANELS):
        if panel_index:
            lines.append(r"\addlinespace")
        lines.append(rf"\multicolumn{{8}}{{@{{}}l}}{{\textit{{{panel_label}}}}} \\")
        for variant_id, label in VARIANTS:
            row = _one(results, variant_id=variant_id, metric=metric)
            support_row = _one(support, variant_id=variant_id)
            if abs(float(row["identity_error"])) > 1e-10:
                raise ValueError(f"decomposition identity fails for {variant_id}, {metric}")
            mass_prefix = "route_count" if metric == "count_share" else "supported_value"
            lines.append(
                f"{label} & {_pp(row['total_change_pp'])} & "
                f"{_pp(row['within_common_pp'])} & "
                f"{_pp(row['common_pair_reweighting_pp'])} & "
                f"{_pp(row['common_support_mass_pp'])} & "
                f"{_pp(row['exclusive_pair_contribution_pp'])} & "
                f"{_pct(support_row[f'baseline_{mass_prefix}_retained_share'])} & "
                f"{_pct(support_row[f'comparison_{mass_prefix}_retained_share'])}"
                + r" \\"
            )
    lines.extend([r"\bottomrule", r"\end{tabularx}", ""])
    return "\n".join(lines)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    support = pd.read_json(SUPPORT, lines=True)
    write_table_artifacts(
        "vehicle_rotation_venue_exclusion",
        render_table(results, support),
        preview_width="9.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

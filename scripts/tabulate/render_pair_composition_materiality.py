#!/usr/bin/env python3
"""Render material-pair sensitivities for the composition decomposition."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


INPUT = (
    OUTPUT_DIR / "exhibits/vehicle_transition_pair_materiality_decomposition.jsonl"
)

ROWS = (
    ("route_count_floor_5", r"$\geq 5$ routes"),
    ("route_count_floor_10", r"$\geq 10$ routes"),
    ("supported_value_floor_5000", r"$\geq \$5{,}000$ value"),
    ("supported_value_floor_50000", r"$\geq \$50{,}000$ value"),
)


def _one(results: pd.DataFrame, spec_id: str) -> pd.Series:
    selected = results[results["robustness_spec_id"].eq(spec_id)]
    if len(selected) != 1:
        raise ValueError(
            f"expected one material-pair row for {spec_id}, found {len(selected)}"
        )
    return selected.iloc[0]


def _pct(value: object) -> str:
    return f"{100.0 * float(value):.2f}"


def _pp(value: object) -> str:
    return f"${100.0 * float(value):+.2f}$"


def render_table(results: pd.DataFrame) -> str:
    """Return a compact four-row appendix table body."""

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrrrrrr@{}}",
        r"\toprule",
        r"& \multicolumn{2}{c}{Stablecoin share [\%]} & \multicolumn{5}{c}{Change [pp]} \\",
        r"\cmidrule(lr){2-3}\cmidrule(l){4-8}",
        r"Pair-period floor & 2024 H1 & 2026 H1 & Total & Within & Reweight & Support & Period-only \\",
        r"\midrule",
    ]
    for spec_id, label in ROWS:
        row = _one(results, spec_id)
        identity_error = float(row["identity_error"])
        if abs(identity_error) > 1e-10:
            raise ValueError(
                f"material-pair identity fails for {spec_id}: {identity_error}"
            )
        lines.append(
            f"{label} & {_pct(row['baseline_stable_share'])} & "
            f"{_pct(row['comparison_stable_share'])} & "
            f"{_pp(row['total_change'])} & {_pp(row['within_common'])} & "
            f"{_pp(row['common_pair_reweighting'])} & "
            f"{_pp(row['common_support_mass'])} & "
            f"{_pp(row['exclusive_pair_contribution'])}" + r" \\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    results = pd.read_json(INPUT, lines=True)
    write_table_artifacts(
        "pair_composition_materiality",
        render_table(results),
        preview_width="9.2in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

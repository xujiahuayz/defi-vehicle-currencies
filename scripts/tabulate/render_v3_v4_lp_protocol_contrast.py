#!/usr/bin/env python3
"""Render the V3-versus-V4 LP protocol-contrast table."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "v3_v4_lp_protocol_contrast.jsonl"

OUTCOMES = {
    "future_log1p_total_lp_actions": "LP actions",
    "future_log1p_total_origin_count": "Active origins",
}
HORIZONS = (7, 30, 120)


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _cell(row: pd.Series) -> str:
    effect = float(row["effect_per_10pp_stable_gap_v4_minus_v3"])
    standard_error = float(
        row["standard_error_per_10pp_stable_gap_v4_minus_v3"]
    )
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.3f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({standard_error:.3f})$"
        r"\end{tabular}"
    )


def render_v3_v4_lp_protocol_contrast(results: pd.DataFrame) -> str:
    required = {
        "horizon_days",
        "outcome",
        "term",
        "effect_per_10pp_stable_gap_v4_minus_v3",
        "standard_error_per_10pp_stable_gap_v4_minus_v3",
        "p_value",
        "n_observations",
        "date_clusters",
        "fixed_effects",
        "activity_controls",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"V3/V4 LP protocol-contrast results lack columns: {missing}")
    contrasts = results[
        results["term"].eq("v4_x_stable_gap")
        & results["horizon_days"].isin(HORIZONS)
        & results["outcome"].isin(OUTCOMES)
    ].copy()
    if contrasts.empty:
        raise ValueError("V3/V4 LP protocol-contrast table has no contrast rows")
    duplicates = contrasts.duplicated(["horizon_days", "outcome"])
    if duplicates.any():
        raise ValueError("V3/V4 LP protocol-contrast table rows are not unique")
    observed = set(zip(contrasts["horizon_days"], contrasts["outcome"], strict=False))
    expected = {(horizon, outcome) for horizon in HORIZONS for outcome in OUTCOMES}
    if observed != expected:
        raise ValueError(
            "V3/V4 LP protocol-contrast table row set is incomplete: "
            f"missing={sorted(expected - observed)}"
        )
    if set(contrasts["fixed_effects"]) != {"candidate_date+protocol"}:
        raise ValueError("unexpected fixed effects in V3/V4 LP protocol contrast")
    if contrasts["activity_controls"].nunique() != 1:
        raise ValueError("V3/V4 LP protocol-contrast table mixes controls")

    rows: list[str] = []
    rows.append(r"\begin{tabularx}{0.82\linewidth}{@{}l*{3}{>{\centering\arraybackslash}X}@{}}")
    rows.append(r"\toprule")
    rows.append("Outcome & 7 days & 30 days & 120 days " + r"\\")
    rows.append(r"\midrule")
    for outcome, label in OUTCOMES.items():
        cells = []
        for horizon in HORIZONS:
            row = contrasts[
                contrasts["outcome"].eq(outcome)
                & contrasts["horizon_days"].eq(horizon)
            ].iloc[0]
            cells.append(_cell(row))
        rows.append(f"{label} & " + " & ".join(cells) + r" \\")
    rows.append(r"\midrule")
    observations = sorted(int(value) for value in contrasts["n_observations"].unique())
    clusters = sorted(int(value) for value in contrasts["date_clusters"].unique())
    if len(observations) != 1 or len(clusters) != 1:
        raise ValueError("V3/V4 LP protocol-contrast table mixes support counts")
    rows.append(
        "Stacked observations / dates & "
        + r"\multicolumn{3}{r}{"
        + f"{observations[0]:,} / {clusters[0]:,}"
        + r"} \\"
    )
    rows.append(r"Candidate-date and protocol effects & \multicolumn{3}{r}{Yes} \\")
    rows.append(r"Current protocol LP controls & \multicolumn{3}{r}{Yes} \\")
    rows.append(r"\bottomrule")
    rows.append(r"\end{tabularx}")
    rows.append("")
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "v3_v4_lp_protocol_contrast",
        render_v3_v4_lp_protocol_contrast(results),
        preview_width="7.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

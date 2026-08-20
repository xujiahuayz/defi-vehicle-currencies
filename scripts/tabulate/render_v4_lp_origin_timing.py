#!/usr/bin/env python3
"""Render the V4 transaction-origin participation timing table."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits/v4_lp_origin_timing.jsonl"
PRIMARY_SAMPLE = "primary_nonzero_180"
PREDICTORS = {
    "internal_tx_share": "Internal same-asset share",
    "multi_leg_tx_share": "Multi-leg transaction share",
    "netting_reduction_share": "Gross-to-net reduction share",
}
OUTCOMES = {
    "near_log1p_new_origins": "Newly active origins, days 1 to 30",
    "near_log1p_incumbent_actions": "Incumbent-origin actions, days 1 to 30",
    "late_log1p_first_active_origins": "First-active origins, days 31 to 120",
    "late_log1p_incumbent_actions": "Incumbent-origin actions, days 31 to 120",
}


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _cell(row: pd.Series) -> str:
    effect = float(row["effect_per_10pp_predictor"])
    se = float(row["standard_error_per_10pp_predictor"])
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.3f}{_stars(float(row['holm_p_value']))}$"
        r"\\"
        f"$({se:.3f})$"
        r"\end{tabular}"
    )


def render_v4_lp_origin_timing(results: pd.DataFrame) -> str:
    required = {
        "sample_variant",
        "predictor",
        "outcome",
        "effect_per_10pp_predictor",
        "standard_error_per_10pp_predictor",
        "holm_p_value",
        "n_observations",
        "date_clusters",
        "fixed_effects",
        "controls",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"V4 origin-timing results lack columns: {missing}")
    sample = results[
        results["sample_variant"].eq(PRIMARY_SAMPLE)
        & results["predictor"].isin(PREDICTORS)
        & results["outcome"].isin(OUTCOMES)
    ].copy()
    expected = {
        (predictor, outcome)
        for predictor in PREDICTORS
        for outcome in OUTCOMES
    }
    observed = set(zip(sample["predictor"], sample["outcome"], strict=False))
    if observed != expected or len(sample) != len(expected):
        raise ValueError(
            "V4 origin-timing table row set is incomplete: "
            f"missing={sorted(expected - observed)}"
        )
    if set(sample["fixed_effects"]) != {"candidate+origin_date"}:
        raise ValueError("V4 origin-timing table mixes fixed-effect designs")
    if sample["controls"].nunique() != 1:
        raise ValueError("V4 origin-timing table mixes control sets")
    n_values = sample["n_observations"].astype(int).unique()
    cluster_values = sample["date_clusters"].astype(int).unique()
    if len(n_values) != 1 or len(cluster_values) != 1:
        raise ValueError("V4 origin-timing table mixes samples")

    rows = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X*{4}{>{\centering\arraybackslash}X}@{}}",
        r"\toprule",
        "Flash-accounting proxy ($M_{c,t}$) & "
        + " & ".join(OUTCOMES.values())
        + r" \\",
        r"\midrule",
    ]
    for predictor, label in PREDICTORS.items():
        cells = []
        for outcome in OUTCOMES:
            row = sample[
                sample["predictor"].eq(predictor)
                & sample["outcome"].eq(outcome)
            ].iloc[0]
            cells.append(_cell(row))
        rows.append(f"{label} & " + " & ".join(cells) + r" \\")
    rows.extend(
        [
            r"\midrule",
            "Observations / date clusters & "
            + rf"\multicolumn{{4}}{{r}}{{{int(n_values[0]):,} / {int(cluster_values[0]):,}}} \\",
            r"Vehicle and date effects & \multicolumn{4}{r}{Yes} \\",
            r"Origin-day activity controls & \multicolumn{4}{r}{Yes} \\",
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "v4_lp_origin_timing",
        render_v4_lp_origin_timing(results),
        preview_width="8.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

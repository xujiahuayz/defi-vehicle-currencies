#!/usr/bin/env python3
"""Render the V4 flash-accounting/stable-gap interaction table."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "v4_flash_gap_interaction_exploration.jsonl"
HORIZON_DAYS = 120

PREDICTORS = {
    "internal_tx_share": "Stable gap $\\times$ internal same-asset share",
    "multi_leg_tx_share": "Stable gap $\\times$ multi-leg transaction share",
    "netting_reduction_share": "Stable gap $\\times$ gross-to-net reduction share",
}
OUTCOMES = {
    "future_delta_log1p_tvl_usd": ("Vehicle-linked TVL", "log pts"),
    "future_log1p_lp_actions": ("LP actions", "log pts"),
    "future_narrow_medium_action_share": ("Narrow/medium ranges", "pp"),
    "future_wide_very_wide_action_share": ("Wide/very-wide ranges", "pp"),
}


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _effect(row: pd.Series) -> tuple[float, float]:
    coefficient = float(row["coefficient"])
    standard_error = float(row["standard_error"])
    if str(row["outcome"]).endswith("_action_share"):
        return coefficient, standard_error
    return 0.01 * coefficient, 0.01 * standard_error


def _cell(row: pd.Series) -> str:
    effect, se = _effect(row)
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.3f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({se:.3f})$"
        r"\end{tabular}"
    )


def render_v4_flash_gap_interactions(results: pd.DataFrame) -> str:
    required = {
        "horizon_days",
        "flash_predictor",
        "outcome",
        "term",
        "coefficient",
        "standard_error",
        "p_value",
        "n_observations",
        "date_clusters",
        "fixed_effects",
        "activity_controls",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"V4 flash-gap interaction results lack columns: {missing}")
    interactions = results[
        results["horizon_days"].eq(HORIZON_DAYS)
        & results["flash_predictor"].isin(PREDICTORS)
        & results["outcome"].isin(OUTCOMES)
        & results["term"].eq(
            "route_capital_gap_5_x_" + results["flash_predictor"].astype(str)
        )
    ].copy()
    if interactions.empty:
        raise ValueError("V4 flash-gap interaction table has no interaction rows")
    duplicates = interactions.duplicated(["flash_predictor", "outcome"])
    if duplicates.any():
        raise ValueError("V4 flash-gap interaction table rows are not unique")
    observed = set(
        zip(interactions["flash_predictor"], interactions["outcome"], strict=False)
    )
    expected = {
        (predictor, outcome)
        for predictor in PREDICTORS
        for outcome in OUTCOMES
    }
    if observed != expected:
        raise ValueError(
            "V4 flash-gap interaction table row set is incomplete: "
            f"missing={sorted(expected - observed)}"
        )
    if set(interactions["fixed_effects"]) != {"candidate_address+origin_date"}:
        raise ValueError("unexpected fixed effects in V4 flash-gap interactions")
    if interactions["activity_controls"].nunique() != 1:
        raise ValueError("V4 flash-gap table mixes activity-control sets")

    rows: list[str] = []
    rows.append(
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X"
        r"*{4}{>{\centering\arraybackslash}X}@{}}"
    )
    rows.append(r"\toprule")
    rows.append(
        "Interaction term ($G^S_{c,t}\\times M_{c,t}$) & "
        + " & ".join(
            f"{label} [{'log points' if unit == 'log pts' else unit}]"
            for label, unit in OUTCOMES.values()
        )
        + r" \\"
    )
    rows.append(r"\midrule")
    for predictor, label in PREDICTORS.items():
        cells = []
        for outcome in OUTCOMES:
            row = interactions[
                interactions["flash_predictor"].eq(predictor)
                & interactions["outcome"].eq(outcome)
            ].iloc[0]
            cells.append(_cell(row))
        rows.append(f"{label} & " + " & ".join(cells) + r" \\")
    rows.append(r"\midrule")
    observations = sorted(int(value) for value in interactions["n_observations"].unique())
    clusters = sorted(int(value) for value in interactions["date_clusters"].unique())
    if len(observations) != 1 or len(clusters) != 1:
        raise ValueError("V4 flash-gap table mixes observation or cluster counts")
    rows.append(
        "Observations / date clusters & "
        + r"\multicolumn{4}{r}{"
        + f"{observations[0]:,} / {clusters[0]:,}"
        + r"} \\"
    )
    rows.append(r"Asset and date effects & \multicolumn{4}{r}{Yes} \\")
    rows.append(r"Origin-day activity controls & \multicolumn{4}{r}{Yes} \\")
    rows.append(r"\bottomrule")
    rows.append(r"\end{tabularx}")
    rows.append("")
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "v4_flash_gap_interactions",
        render_v4_flash_gap_interactions(results),
        preview_width="8.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

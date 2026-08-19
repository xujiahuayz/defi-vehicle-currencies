#!/usr/bin/env python3
"""Render the paper's V4 flash-accounting LP mechanism regression table."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "v4_flash_lp_mechanism_exploration.jsonl"

HORIZON_DAYS = 120
PREDICTORS = {
    "internal_tx_share": "Internal same-asset share",
    "multi_leg_tx_share": "Multi-leg transaction share",
    "netting_reduction_share": "Gross-to-net reduction share",
}
OUTCOMES = {
    "future_log1p_gross_lp_flow_usd": ("Future LP flow", "log pts"),
    "future_delta_log1p_tvl_usd": ("Vehicle-linked TVL", "log pts"),
    "future_log1p_lp_actions": ("LP actions", "log pts"),
    "future_narrow_medium_flow_value_share": ("Flow narrow/medium", "pp"),
    "future_broad_flow_value_share": ("Flow broad", "pp"),
    "future_narrow_medium_action_share": ("Action narrow/medium", "pp"),
    "future_wide_very_wide_action_share": ("Action wide/very-wide", "pp"),
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
    if row["outcome"] in {
        "future_narrow_medium_flow_value_share",
        "future_broad_flow_value_share",
        "future_narrow_medium_action_share",
        "future_wide_very_wide_action_share",
    }:
        return 10.0 * coefficient, 10.0 * standard_error
    return 0.10 * coefficient, 0.10 * standard_error


def _cell(row: pd.Series) -> str:
    effect, se = _effect(row)
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.3f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({se:.3f})$"
        r"\end{tabular}"
    )


def render_v4_flash_lp_mechanism(results: pd.DataFrame) -> str:
    """Render a compact 120-day regression table from the V4 mechanism exhibit."""

    required = {
        "horizon_days",
        "predictor",
        "outcome",
        "coefficient",
        "standard_error",
        "p_value",
        "n_observations",
        "date_clusters",
        "fixed_effects",
        "controls",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"V4 mechanism results lack required columns: {missing}")
    sample = results[
        results["horizon_days"].eq(HORIZON_DAYS)
        & results["predictor"].isin(PREDICTORS)
        & results["outcome"].isin(OUTCOMES)
    ].copy()
    if sample.empty:
        raise ValueError("V4 mechanism table has no 120-day rows")
    duplicates = sample.duplicated(["predictor", "outcome"])
    if duplicates.any():
        raise ValueError("V4 mechanism table rows are not unique")
    observed = set(zip(sample["predictor"], sample["outcome"], strict=False))
    expected = {
        (predictor, outcome)
        for predictor in PREDICTORS
        for outcome in OUTCOMES
    }
    if observed != expected:
        raise ValueError(
            "V4 mechanism table row set is incomplete: "
            f"missing={sorted(expected - observed)}"
        )
    fixed_effects = set(sample["fixed_effects"])
    if fixed_effects != {"candidate+origin_date"}:
        raise ValueError(f"unexpected fixed effects: {sorted(fixed_effects)}")
    controls = set(sample["controls"])
    if len(controls) != 1:
        raise ValueError("V4 mechanism table mixes control sets")

    rows: list[str] = []
    outcome_count = len(OUTCOMES)
    rows.append(
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X"
        + f"*{{{outcome_count}}}{{>{{\\centering\\arraybackslash}}X}}@{{}}}}"
    )
    rows.append(r"\toprule")
    rows.append(
        "Flash-accounting proxy & "
        + " & ".join(f"{label} ({unit})" for label, unit in OUTCOMES.values())
        + r" \\"
    )
    rows.append(r"\midrule")
    for predictor, predictor_label in PREDICTORS.items():
        cells = []
        for outcome in OUTCOMES:
            row = sample[
                sample["predictor"].eq(predictor)
                & sample["outcome"].eq(outcome)
            ].iloc[0]
            cells.append(_cell(row))
        rows.append(f"{predictor_label} & " + " & ".join(cells) + r" \\")
    rows.append(r"\midrule")
    observations = sorted(int(value) for value in sample["n_observations"].unique())
    clusters = sorted(int(value) for value in sample["date_clusters"].unique())
    if len(observations) != 1 or len(clusters) != 1:
        raise ValueError("V4 mechanism table mixes observation or cluster counts")
    rows.append(
        "Observations / date clusters & "
        + rf"\multicolumn{{{outcome_count}}}{{r}}{{"
        + f"{observations[0]:,} / {clusters[0]:,}"
        + r"} \\"
    )
    rows.append(rf"Asset and date effects & \multicolumn{{{outcome_count}}}{{r}}{{Yes}} \\")
    rows.append(rf"Origin-day activity controls & \multicolumn{{{outcome_count}}}{{r}}{{Yes}} \\")
    rows.append(r"\bottomrule")
    rows.append(r"\end{tabularx}")
    rows.append("")
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "v4_flash_lp_mechanism",
        render_v4_flash_lp_mechanism(results),
        preview_width="8.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

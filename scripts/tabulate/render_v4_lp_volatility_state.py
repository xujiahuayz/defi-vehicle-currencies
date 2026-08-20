#!/usr/bin/env python3
"""Render the V4 liquidity-participation volatility-state table."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits/v4_lp_volatility_state.jsonl"
PRIMARY_SAMPLE = "primary_nonzero_180"
PRIMARY_STATE_DAYS = 30
OUTCOMES = {
    "near_log1p_incumbent_actions": "Incumbent-origin actions, days 1 to 30",
    "late_log1p_first_active_origins": "First-active origins, days 31 to 120",
}


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _cell(effect: float, standard_error: float, p_value: float) -> str:
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.3f}{_stars(p_value)}$"
        r"\\"
        f"$({standard_error:.3f})$"
        r"\end{tabular}"
    )


def render_v4_lp_volatility_state(results: pd.DataFrame) -> str:
    required = {
        "record_type",
        "sample_variant",
        "state_window_days",
        "outcome",
        "main_effect_per_10pp_at_mean_state",
        "main_standard_error",
        "main_p_value",
        "interaction_per_10pp_per_1sd_volatility",
        "interaction_standard_error",
        "interaction_holm_p_value",
        "n_observations",
        "date_clusters",
        "fixed_effects",
        "controls",
        "state_controls",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"V4 volatility-state results lack columns: {missing}")
    sample = results[
        results["record_type"].eq("v4_lp_volatility_state_regression")
        & results["sample_variant"].eq(PRIMARY_SAMPLE)
        & results["state_window_days"].eq(PRIMARY_STATE_DAYS)
        & results["outcome"].isin(OUTCOMES)
    ].copy()
    if set(sample["outcome"]) != set(OUTCOMES) or len(sample) != len(OUTCOMES):
        raise ValueError("V4 volatility-state table lacks the primary outcome family")
    if set(sample["fixed_effects"]) != {"candidate+origin_date"}:
        raise ValueError("V4 volatility-state table mixes fixed-effect designs")
    if sample["controls"].nunique() != 1 or sample["state_controls"].nunique() != 1:
        raise ValueError("V4 volatility-state table mixes control sets")
    observations = sample["n_observations"].astype(int).unique()
    clusters = sample["date_clusters"].astype(int).unique()
    if len(observations) != 1 or len(clusters) != 1:
        raise ValueError("V4 volatility-state table mixes samples")

    ordered = {row.outcome: row for row in sample.itertuples(index=False)}
    main_cells = [
        _cell(
            float(ordered[outcome].main_effect_per_10pp_at_mean_state),
            float(ordered[outcome].main_standard_error),
            float(ordered[outcome].main_p_value),
        )
        for outcome in OUTCOMES
    ]
    interaction_cells = [
        _cell(
            float(ordered[outcome].interaction_per_10pp_per_1sd_volatility),
            float(ordered[outcome].interaction_standard_error),
            float(ordered[outcome].interaction_holm_p_value),
        )
        for outcome in OUTCOMES
    ]
    rows = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X*{2}{>{\centering\arraybackslash}X}@{}}",
        r"\toprule",
        " & " + " & ".join(OUTCOMES.values()) + r" \\",
        r"\midrule",
        "Internal same-asset share & " + " & ".join(main_cells) + r" \\",
        r"$\times$ lagged 30-day WETH volatility [1 SD] & "
        + " & ".join(interaction_cells)
        + r" \\",
        r"\midrule",
        "Observations / date clusters & "
        + rf"\multicolumn{{2}}{{r}}{{{int(observations[0]):,} / {int(clusters[0]):,}}} \\",
        r"Vehicle and date effects & \multicolumn{2}{r}{Yes} \\",
        r"Origin-day activity controls & \multicolumn{2}{r}{Yes} \\",
        r"Vehicle and control volatility slopes & \multicolumn{2}{r}{Yes} \\",
        r"\bottomrule",
        r"\end{tabularx}",
        "",
    ]
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "v4_lp_volatility_state",
        render_v4_lp_volatility_state(results),
        preview_width="7.4in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

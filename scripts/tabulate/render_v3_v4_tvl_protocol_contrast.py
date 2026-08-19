#!/usr/bin/env python3
"""Render the V3-versus-V4 candidate-linked TVL protocol-contrast table."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "v3_v4_tvl_protocol_contrast.jsonl"

OUTCOMES = {
    "future_delta_log1p_tvl": "Reported TVL growth",
    "future_delta_log1p_pool_count": "Pool-footprint growth",
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
    se = float(row["standard_error_per_10pp_stable_gap_v4_minus_v3"])
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.3f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({se:.3f})$"
        r"\end{tabular}"
    )


def render_v3_v4_tvl_protocol_contrast(results: pd.DataFrame) -> str:
    """Render V4-minus-V3 stable-gap reported-TVL contrasts."""

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
        "controls",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"V3/V4 TVL protocol-contrast results lack columns: {missing}")
    sample = results[
        results["term"].eq("v4_x_stable_gap")
        & results["horizon_days"].isin(HORIZONS)
        & results["outcome"].isin(OUTCOMES)
    ].copy()
    if sample.empty:
        raise ValueError("V3/V4 TVL protocol-contrast table has no contrast rows")
    duplicates = sample.duplicated(["horizon_days", "outcome"])
    if duplicates.any():
        raise ValueError("V3/V4 TVL protocol-contrast table rows are not unique")
    observed = set(zip(sample["horizon_days"], sample["outcome"], strict=False))
    expected = {(horizon, outcome) for horizon in HORIZONS for outcome in OUTCOMES}
    if observed != expected:
        raise ValueError(
            "V3/V4 TVL protocol-contrast table row set is incomplete: "
            f"missing={sorted(expected - observed)}"
        )
    if set(sample["fixed_effects"]) != {"candidate-date+protocol"}:
        raise ValueError("unexpected fixed effects in V3/V4 TVL protocol contrast")
    if set(sample["controls"]) != {"origin_log1p_tvl+origin_log1p_pool_count"}:
        raise ValueError("unexpected controls in V3/V4 TVL protocol contrast")

    rows: list[str] = []
    rows.append(
        r"\begin{tabularx}{\linewidth}{@{}"
        r">{\hsize=1.20\hsize\raggedright\arraybackslash}X"
        r"*{2}{>{\hsize=0.90\hsize\centering\arraybackslash}X}@{}}"
    )
    rows.append(r"\toprule")
    rows.append(
        "Horizon & " + " & ".join(OUTCOMES.values()) + r" \\"
    )
    rows.append(r"\midrule")
    for horizon in HORIZONS:
        cells = []
        for outcome in OUTCOMES:
            row = sample[
                sample["horizon_days"].eq(horizon)
                & sample["outcome"].eq(outcome)
            ].iloc[0]
            cells.append(_cell(row))
        rows.append(f"{horizon} days & " + " & ".join(cells) + r" \\")
    rows.append(r"\midrule")
    for horizon in HORIZONS:
        horizon_sample = sample[sample["horizon_days"].eq(horizon)]
        observations = sorted(int(value) for value in horizon_sample["n_observations"].unique())
        clusters = sorted(int(value) for value in horizon_sample["date_clusters"].unique())
        if len(observations) != 1 or len(clusters) != 1:
            raise ValueError("V3/V4 TVL protocol table mixes support counts")
        rows.append(
            f"Obs. / date clusters ({horizon}d) & "
            + r"\multicolumn{2}{r}{"
            + f"{observations[0]:,} / {clusters[0]:,}"
            + r"} \\"
        )
    rows.append(r"Asset-date and protocol effects & \multicolumn{2}{r}{Yes} \\")
    rows.append(r"Origin TVL and pool-count controls & \multicolumn{2}{r}{Yes} \\")
    rows.append(r"\bottomrule")
    rows.append(r"\end{tabularx}")
    rows.append("")
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "v3_v4_tvl_protocol_contrast",
        render_v3_v4_tvl_protocol_contrast(results),
        preview_width="7.0in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

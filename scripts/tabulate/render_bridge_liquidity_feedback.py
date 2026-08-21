#!/usr/bin/env python3
"""Render conditional bridge-depth and route-use level regressions."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "bridge_liquidity_feedback.jsonl"
HORIZONS = (30, 60, 120)


@dataclass(frozen=True)
class FeedbackRow:
    forward_label: str
    reverse_label: str
    unit: str
    selector: dict[str, object]
    scale: float


TABLE_ROWS: tuple[FeedbackRow, ...] = (
    FeedbackRow(
        forward_label=r"$R_{b,t}\rightarrow B_{b,t+h}$, pooled",
        reverse_label=r"$R_{b,t+h}\rightarrow B_{b,t}$, pooled",
        unit="log points",
        selector={
            "record_type": "bridge_liquidity_feedback_regression",
            "model_id": "future_bridge_depth_level",
            "outcome": "depth_outcome",
            "regressor": "route_share_predictor",
        },
        scale=0.10,
    ),
    FeedbackRow(
        forward_label=r"$R_{b,t}\rightarrow B_{b,t+h}$, stablecoin",
        reverse_label=r"$R_{b,t+h}\rightarrow B_{b,t}$, stablecoin",
        unit="log points",
        selector={
            "record_type": "bridge_liquidity_feedback_regression",
            "model_id": "future_bridge_depth_level_stable_candidate",
            "outcome": "depth_outcome",
            "regressor": "route_share_predictor",
        },
        scale=0.10,
    ),
    FeedbackRow(
        forward_label=r"$B_{b,t}\rightarrow R_{b,t+h}$, pooled",
        reverse_label=r"$B_{b,t+h}\rightarrow R_{b,t}$, pooled",
        unit="pp",
        selector={
            "record_type": "bridge_liquidity_feedback_regression",
            "model_id": "future_route_share_level",
            "outcome": "route_share_outcome",
            "regressor": "depth_predictor",
        },
        scale=100.0,
    ),
    FeedbackRow(
        forward_label=r"$B_{b,t}\rightarrow R_{b,t+h}$, stablecoin",
        reverse_label=r"$B_{b,t+h}\rightarrow R_{b,t}$, stablecoin",
        unit="pp",
        selector={
            "record_type": "bridge_liquidity_feedback_regression",
            "model_id": "future_route_share_level_stable_candidate",
            "outcome": "route_share_outcome",
            "regressor": "depth_predictor",
        },
        scale=100.0,
    ),
)


PANELS = (
    (
        "Panel A: Forward levels, route-activity weights",
        "forward",
        "activity",
    ),
    (
        "Panel B: Time-reversed benchmark, route-activity weights",
        "time_reversed",
        "activity",
    ),
    (
        "Panel C: Forward levels, equal pair-date-scope weights",
        "forward",
        "pair",
    ),
    (
        "Panel D: Time-reversed benchmark, equal pair-date-scope weights",
        "time_reversed",
        "pair",
    ),
)


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _select_one(
    results: pd.DataFrame,
    selector: dict[str, object],
    *,
    horizon: int,
    timing: str,
    weight_scheme: str,
) -> pd.Series:
    selected = results[
        results["horizon_days"].eq(horizon)
        & results["timing"].eq(timing)
        & results["weight_scheme"].eq(weight_scheme)
    ]
    for column, value in selector.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(
            "expected one bridge-depth row for "
            f"horizon={horizon}, timing={timing}, weight={weight_scheme}, "
            f"selector={selector}; found {len(selected)}"
        )
    return selected.iloc[0]


def _cell(row: pd.Series, *, scale: float) -> str:
    effect = scale * float(row["coefficient"])
    standard_error = scale * float(row["standard_error"])
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.3f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({standard_error:.3f})$"
        r"\end{tabular}"
    )


def render_bridge_liquidity_feedback(results: pd.DataFrame) -> str:
    required = {
        "claim_status",
        "record_type",
        "model_id",
        "timing",
        "weight_scheme",
        "horizon_days",
        "outcome",
        "regressor",
        "coefficient",
        "standard_error",
        "p_value",
        "n_observations",
        "ordered_pair_clusters",
        "date_clusters",
        "fixed_effects",
        "initial_level_controls",
        "covariance",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"bridge-depth results lack required columns: {missing}")
    if not results["claim_status"].dropna().eq("provisional_exploratory").all():
        raise ValueError("bridge-depth table expects provisional_exploratory rows")

    rows: list[str] = []
    rows.append(
        r"\begin{tabularx}{\linewidth}{@{}"
        r">{\hsize=1.72\hsize\raggedright\arraybackslash}X"
        r"*{3}{>{\hsize=0.76\hsize\centering\arraybackslash}X}@{}}"
    )
    rows.append(r"\toprule")
    rows.append(r"Conditional level equation & 30 days & 60 days & 120 days \\")
    rows.append(r"\midrule")
    for panel_index, (panel_label, timing, weight_scheme) in enumerate(PANELS):
        if panel_index:
            rows.append(r"\addlinespace")
        rows.append(
            rf"\multicolumn{{4}}{{@{{}}l}}{{\textit{{{panel_label}}}}} \\"
        )
        for table_row in TABLE_ROWS:
            cells = [
                _cell(
                    _select_one(
                        results,
                        table_row.selector,
                        horizon=horizon,
                        timing=timing,
                        weight_scheme=weight_scheme,
                    ),
                    scale=table_row.scale,
                )
                for horizon in HORIZONS
            ]
            label = (
                table_row.forward_label
                if timing == "forward"
                else table_row.reverse_label
            )
            rows.append(
                f"{label} [{table_row.unit}] & " + " & ".join(cells) + r" \\"
            )
    rows.append(r"\midrule")
    for label, table_row in (
        ("Pooled rows / pair clusters / dates", TABLE_ROWS[0]),
        ("Stablecoin rows / pair clusters / dates", TABLE_ROWS[1]),
    ):
        count_cells = []
        for horizon in HORIZONS:
            estimate = _select_one(
                results,
                table_row.selector,
                horizon=horizon,
                timing="forward",
                weight_scheme="activity",
            )
            count_cells.append(
                f"{int(estimate['n_observations']):,} / "
                f"{int(estimate['ordered_pair_clusters']):,} / "
                f"{int(estimate['date_clusters']):,}"
            )
        rows.append(label + " & " + " & ".join(count_cells) + r" \\")
    rows.append(r"Bridge and date effects & \multicolumn{3}{r}{Yes} \\")
    rows.append(r"Initial outcome level & \multicolumn{3}{r}{Cubic} \\")
    rows.append(r"Two-way clustered covariance & \multicolumn{3}{r}{Pair and date} \\")
    rows.append(r"\bottomrule")
    rows.append(r"\end{tabularx}")
    rows.append("")
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "bridge_liquidity_feedback",
        render_bridge_liquidity_feedback(results),
        preview_width="8.0in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

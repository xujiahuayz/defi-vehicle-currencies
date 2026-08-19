#!/usr/bin/env python3
"""Render the paper's dynamic local bridge-liquidity feedback table."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "bridge_liquidity_feedback.jsonl"
HORIZONS = (30, 120)


@dataclass(frozen=True)
class FeedbackRow:
    label: str
    unit: str
    selector: dict[str, object]
    scale: float


TABLE_ROWS: tuple[FeedbackRow, ...] = (
    FeedbackRow(
        label="Route use to bridge depth, pooled",
        unit="log pts",
        selector={
            "record_type": "bridge_liquidity_feedback_regression",
            "model_id": "future_bridge_depth_growth",
            "outcome": "future_delta_log_bridge_min_capital",
            "regressor": "route_share_five",
        },
        scale=0.10,
    ),
    FeedbackRow(
        label="Route use to bridge depth, stable",
        unit="log pts",
        selector={
            "record_type": "bridge_liquidity_feedback_regression",
            "model_id": "future_bridge_depth_growth_stable_candidate",
            "outcome": "future_delta_log_bridge_min_capital",
            "regressor": "stable_total_route_share_five",
        },
        scale=0.10,
    ),
    FeedbackRow(
        label="Bridge depth to route use, pooled",
        unit="pp",
        selector={
            "record_type": "bridge_liquidity_feedback_regression",
            "model_id": "future_route_share_growth",
            "outcome": "future_delta_route_share_five",
            "regressor": "log_bridge_min_capital",
        },
        scale=100.0,
    ),
    FeedbackRow(
        label="Bridge depth to route use, stable",
        unit="pp",
        selector={
            "record_type": "bridge_liquidity_feedback_regression",
            "model_id": "future_route_share_growth_stable_candidate",
            "outcome": "future_delta_route_share_five",
            "regressor": "stable_total_log_bridge_min_capital",
        },
        scale=100.0,
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


def _select_one(results: pd.DataFrame, selector: dict[str, object], horizon: int) -> pd.Series:
    selected = results[results["horizon_days"].eq(horizon)]
    for column, value in selector.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(
            f"expected one bridge-feedback row for horizon={horizon}, "
            f"selector={selector}; found {len(selected)}"
        )
    return selected.iloc[0]


def _support_one(results: pd.DataFrame, horizon: int) -> pd.Series:
    selected = results[
        results["record_type"].eq("bridge_liquidity_feedback_support")
        & results["horizon_days"].eq(horizon)
    ]
    if len(selected) != 1:
        raise ValueError(f"expected one bridge-feedback support row for {horizon}d")
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
        "covariance",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"bridge-feedback results lack required columns: {missing}")
    if not results["claim_status"].dropna().eq("provisional_exploratory").all():
        raise ValueError("bridge-feedback table expects provisional_exploratory rows")

    rows: list[str] = []
    rows.append(
        r"\begin{tabularx}{0.90\linewidth}{@{}>{\raggedright\arraybackslash}X"
        r">{\centering\arraybackslash}p{0.75in}"
        r"*{2}{>{\centering\arraybackslash}p{1.05in}}@{}}"
    )
    rows.append(r"\toprule")
    rows.append(r"Feedback margin & Unit & 30 days & 120 days \\")
    rows.append(r"\midrule")
    for table_row in TABLE_ROWS:
        cells = [
            _cell(
                _select_one(results, table_row.selector, horizon),
                scale=table_row.scale,
            )
            for horizon in HORIZONS
        ]
        rows.append(
            f"{table_row.label} & {table_row.unit} & "
            + " & ".join(cells)
            + r" \\"
        )
    rows.append(r"\midrule")
    support_cells = []
    for horizon in HORIZONS:
        support = _support_one(results, horizon)
        support_cells.append(
            f"{int(support['candidate_rows']):,} / "
            f"{int(support['ordered_pairs']):,} / "
            f"{int(support['days']):,}"
        )
    rows.append(
        "Rows / ultimate pairs / dates & "
        + r"\multicolumn{1}{c}{} & "
        + " & ".join(support_cells)
        + r" \\"
    )
    rows.append(r"Asset and date effects & \multicolumn{3}{r}{Yes} \\")
    rows.append(r"Two-way clustered covariance & \multicolumn{3}{r}{Ordered ultimate pair and date} \\")
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

#!/usr/bin/env python3
"""Render publication-style determinants-of-vehicle-rotation regressions.

Unlike the exploratory coefficient inventories, this table holds the outcome,
sample construction, fixed effects, weighting, and covariance design fixed while
adding economically related regressor blocks across columns.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "vehicle_dominance_mechanism_sweep.jsonl"


@dataclass(frozen=True)
class Specification:
    model_id: str
    heading: str


SPECIFICATIONS = (
    Specification("share_change_market_state", "Market state"),
    Specification("share_change_route_architecture", "Route architecture"),
    Specification("share_change_baseline_state", "Joint baseline"),
    Specification("share_change_state_and_dynamics", "{}+ dynamics"),
)

REGRESSORS = (
    ("baseline_log_market_routes", "Log baseline market routes"),
    ("baseline_direct_route_share", "Baseline direct-route share"),
    ("baseline_complex_route_share", "Baseline complex-route share"),
    ("baseline_primary_choice_share", "Baseline primary-choice share"),
    ("baseline_pair_age_log", "Log baseline ultimate-pair age"),
    ("cross_venue", "Cross-venue scope"),
    ("market_route_growth_log", "Log market-route growth"),
    ("direct_route_share_change", "Change in direct-route share"),
    ("complex_route_share_change", "Change in complex-route share"),
)

PANELS = (
    ("count_share", "Panel A: Route-count stable-share change"),
    (
        "strict_intermediation_value_share",
        "Panel B: Routed-value stable-share change",
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


def _model_rows(results: pd.DataFrame, metric: str, model_id: str) -> pd.DataFrame:
    selected = results[
        results["metric"].eq(metric)
        & results["model_id"].eq(model_id)
        & results["outcome"].eq("stable_share_change")
    ].copy()
    if selected.empty:
        raise ValueError(f"missing determinants model {metric}:{model_id}")
    if selected["regressor"].duplicated().any():
        raise ValueError(f"duplicate regressors in {metric}:{model_id}")
    return selected.set_index("regressor", drop=False)


def _coefficient_cell(rows: pd.DataFrame, regressor: str) -> str:
    if regressor not in rows.index:
        return ""
    row = rows.loc[regressor]
    return f"${float(row['coefficient_pp']):+.3f}{_stars(float(row['p_value']))}$"


def _standard_error_cell(rows: pd.DataFrame, regressor: str) -> str:
    if regressor not in rows.index:
        return ""
    return f"({float(rows.loc[regressor, 'standard_error_pp']):.3f})"


def _integer(value: object) -> str:
    return f"{int(round(float(value))):,}"


def render_vehicle_dominance_determinants(results: pd.DataFrame) -> str:
    required = {
        "metric",
        "model_id",
        "outcome",
        "regressor",
        "coefficient_pp",
        "standard_error_pp",
        "p_value",
        "observations",
        "ordered_pair_clusters",
        "month_day_clusters",
        "r_squared_within",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"dominance results lack table fields: {missing}")

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}X*{4}{>{\centering\arraybackslash}p{0.92in}}@{}}",
        r"\toprule",
        r" & (1) & (2) & (3) & (4) \\",
        " & " + " & ".join(spec.heading for spec in SPECIFICATIONS) + r" \\",
        r"\midrule",
    ]
    for metric, panel_heading in PANELS:
        models = [
            _model_rows(results, metric, specification.model_id)
            for specification in SPECIFICATIONS
        ]
        lines.append(rf"\multicolumn{{5}}{{@{{}}l}}{{\textit{{{panel_heading}}}}} \\")
        for regressor, label in REGRESSORS:
            lines.append(
                label
                + " & "
                + " & ".join(_coefficient_cell(model, regressor) for model in models)
                + r" \\"
            )
            lines.append(
                " & "
                + " & ".join(_standard_error_cell(model, regressor) for model in models)
                + r" \\"
            )
        anchors = [model.iloc[0] for model in models]
        lines.extend(
            [
                r"\addlinespace",
                "Within $R^2$ & "
                + " & ".join(f"{float(row['r_squared_within']):.3f}" for row in anchors)
                + r" \\",
                "Observations & "
                + " & ".join(_integer(row["observations"]) for row in anchors)
                + r" \\",
                "Ordered ultimate-pair clusters & "
                + " & ".join(_integer(row["ordered_pair_clusters"]) for row in anchors)
                + r" \\",
                "Month-day clusters & "
                + " & ".join(_integer(row["month_day_clusters"]) for row in anchors)
                + r" \\",
                r"Month-day fixed effects & Yes & Yes & Yes & Yes \\",
                r"Harmonic route-mass weights & Yes & Yes & Yes & Yes \\",
            ]
        )
        if metric != PANELS[-1][0]:
            lines.append(r"\midrule")
    lines.extend([r"\bottomrule", r"\end{tabularx}", ""])
    return "\n".join(lines)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "vehicle_dominance_determinants",
        render_vehicle_dominance_determinants(results),
        preview_width="8.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

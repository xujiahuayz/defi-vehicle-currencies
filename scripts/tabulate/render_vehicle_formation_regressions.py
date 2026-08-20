#!/usr/bin/env python3
"""Render the paper's market-birth vehicle-formation regression table."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "vehicle_formation_exploration.jsonl"


@dataclass(frozen=True)
class TableRow:
    screen: str
    outcome: str
    regressor: str
    selector: dict[str, object]
    scale: str


TABLE_ROWS: tuple[TableRow, ...] = (
    TableRow(
        screen="Entry persistence",
        outcome="Stable follow-up share ($S_{p,t+h}$), 30 days",
        regressor="Entry stable share ($S^{\\mathrm{entry}}_{p,t}$)",
        selector={
            "record_type": "entry_path_dependence_regression",
            "horizon_days": 30.0,
            "outcome": "stable_share",
            "predictor": "entry_stable_share",
        },
        scale="coefficient_per_10pp_entry_share",
    ),
    TableRow(
        screen="Entry persistence",
        outcome="Stable follow-up share ($S_{p,t+h}$), 120 days",
        regressor="Entry stable share ($S^{\\mathrm{entry}}_{p,t}$)",
        selector={
            "record_type": "entry_path_dependence_regression",
            "horizon_days": 120.0,
            "outcome": "stable_share",
            "predictor": "entry_stable_share",
        },
        scale="coefficient_per_10pp_entry_share",
    ),
    TableRow(
        screen="Entry persistence",
        outcome="Stable-majority follow-up, 120 days",
        regressor=(
            "Stable-majority entry "
            "($\\mathbf 1\\{S^{\\mathrm{entry}}_{p,t}>1/2\\}$)"
        ),
        selector={
            "record_type": "entry_path_dependence_regression",
            "horizon_days": 120.0,
            "outcome": "stable_dominant_followup",
            "predictor": "entry_stable_dominant",
        },
        scale="binary_share",
    ),
    TableRow(
        screen="No-direct-route split",
        outcome="Stable follow-up share ($S_{p,t+h}$), 120 days",
        regressor=(
            "Entry stable share ($S^{\\mathrm{entry}}_{p,t}$), "
            "no direct route"
        ),
        selector={
            "record_type": "entry_path_dependence_direct_route_regression",
            "horizon_days": 120.0,
            "direct_route_bucket": "no_direct_route",
            "outcome": "stable_share",
            "predictor": "entry_stable_share",
        },
        scale="coefficient_per_10pp_entry_share",
    ),
    TableRow(
        screen="Value-weighted entry",
        outcome="Stable value share, 120 days",
        regressor="Entry stable value share",
        selector={
            "record_type": "entry_value_path_dependence_regression",
            "horizon_days": 120.0,
            "outcome": "stable_value_share",
            "predictor": "entry_stable_value_share",
        },
        scale="coefficient_per_10pp_entry_value_share",
    ),
    TableRow(
        screen="Named-stable identity",
        outcome="Own-stable follow-up share, 120 days",
        regressor="Entry named-stable share",
        selector={
            "record_type": "entry_stable_candidate_identity_regression",
            "horizon_days": 120.0,
            "outcome": "own_candidate_followup_share",
            "predictor": "entry_candidate_share",
            "sample": "non_weth_stable_entry_candidate",
        },
        scale="coefficient_per_10pp_entry_candidate_share",
    ),
    TableRow(
        screen="Secure-volume endpoint",
        outcome="Entry stable share ($S^{\\mathrm{entry}}_{p,t}$)",
        regressor="Stable endpoint $\\times$ 2026",
        selector={
            "record_type": "entry_driver_regression",
            "outcome": "stable_share",
            "predictor": "is_2026_x_stable_endpoint",
        },
        scale="binary_share",
    ),
    TableRow(
        screen="Route architecture",
        outcome="Entry stable share ($S^{\\mathrm{entry}}_{p,t}$)",
        regressor="Direct-route share ($D_{p,t}$) $\\times$ 2026",
        selector={
            "record_type": "entry_route_architecture_regression",
            "outcome": "stable_share",
            "predictor": "is_2026_x_direct_share",
        },
        scale="ten_pp_share",
    ),
    TableRow(
        screen="Route architecture",
        outcome="Entry stable share ($S^{\\mathrm{entry}}_{p,t}$)",
        regressor="Complex-route share ($C_{p,t}$) $\\times$ 2026",
        selector={
            "record_type": "entry_route_architecture_regression",
            "outcome": "stable_share",
            "predictor": "is_2026_x_complex_share",
        },
        scale="ten_pp_share",
    ),
)

SCALE_SE_COLUMNS = {
    "coefficient_per_10pp_entry_share": "standard_error_per_10pp_entry_share",
    "coefficient_per_10pp_entry_value_share": (
        "standard_error_per_10pp_entry_value_share"
    ),
    "coefficient_per_10pp_entry_candidate_share": (
        "standard_error_per_10pp_entry_candidate_share"
    ),
}


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _select_one(results: pd.DataFrame, row: TableRow) -> pd.Series:
    sample = results.copy()
    for column, expected in row.selector.items():
        if column not in sample.columns:
            raise ValueError(f"formation results lack selector column: {column}")
        sample = sample[sample[column].eq(expected)]
    if len(sample) != 1:
        raise ValueError(f"expected one row for {row.regressor}, found {len(sample)}")
    return sample.iloc[0]


def _reported_effect(result: pd.Series, scale: str) -> tuple[float, float]:
    coefficient = float(result["coefficient"])
    standard_error = float(result["standard_error"])
    if scale == "binary_share":
        coefficient *= 100.0
        standard_error *= 100.0
    elif scale not in SCALE_SE_COLUMNS and scale != "ten_pp_share":
        raise ValueError(f"unknown table scale: {scale}")
    return coefficient, standard_error


def _effect_cell(result: pd.Series, scale: str) -> str:
    effect, standard_error = _reported_effect(result, scale)
    decimals = 1 if scale == "binary_share" else 2
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.{decimals}f}{_stars(float(result['p_value']))}$"
        r"\\"
        f"$({standard_error:.{decimals}f})$"
        r"\end{tabular}"
    )


def _obs_cell(result: pd.Series) -> str:
    observations = int(round(float(result["observations"])))
    clusters = int(round(float(result["entry_date_clusters"])))
    return f"{observations:,} / {clusters:,}"


def render_vehicle_formation_regressions(results: pd.DataFrame) -> str:
    """Render the formation regression table from the exploration exhibit."""

    required = {
        "record_type",
        "outcome",
        "predictor",
        "coefficient",
        "standard_error",
        "p_value",
        "observations",
        "entry_date_clusters",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"formation results lack required columns: {missing}")

    rows: list[str] = []
    rows.append(
        r"\begin{tabularx}{\linewidth}{@{}"
        r">{\hsize=0.78\hsize\raggedright\arraybackslash}X"
        r">{\hsize=1.08\hsize\raggedright\arraybackslash}X"
        r">{\hsize=1.14\hsize\raggedright\arraybackslash}X"
        r"cr@{}}"
    )
    rows.append(r"\toprule")
    rows.append(
        r"Model & Outcome & Regressor & Coefficient / (s.e.) & Obs. / clusters \\"
    )
    rows.append(r"\midrule")
    for row in TABLE_ROWS:
        result = _select_one(results, row)
        rows.append(
            f"{row.screen} & {row.outcome} & {row.regressor} & "
            f"{_effect_cell(result, row.scale)} & {_obs_cell(result)} \\\\"
        )
    rows.append(r"\bottomrule")
    rows.append(r"\end{tabularx}")
    rows.append("")
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "vehicle_formation_regressions",
        render_vehicle_formation_regressions(results),
        preview_width="8.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

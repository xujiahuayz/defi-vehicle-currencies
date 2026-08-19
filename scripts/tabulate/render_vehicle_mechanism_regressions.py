#!/usr/bin/env python3
"""Render the paper's vehicle-dominance mechanism regression table."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "vehicle_dominance_mechanism_sweep.jsonl"


@dataclass(frozen=True)
class TableRow:
    margin: str
    outcome: str
    regressor_label: str
    selector: dict[str, object]


TABLE_ROWS: tuple[TableRow, ...] = (
    TableRow(
        margin="Turn-on",
        outcome="Stable appears",
        regressor_label="Baseline route count",
        selector={
            "model_id": "turn_on_lpm",
            "metric": "count_share",
            "outcome": "stable_turn_on",
            "regressor": "baseline_log_market_routes",
        },
    ),
    TableRow(
        margin="Turn-on",
        outcome="Stable appears",
        regressor_label="Direct-route share",
        selector={
            "model_id": "turn_on_lpm",
            "metric": "count_share",
            "outcome": "stable_turn_on",
            "regressor": "baseline_direct_route_share",
        },
    ),
    TableRow(
        margin="Turn-on",
        outcome="Stable appears",
        regressor_label="Complex-route share",
        selector={
            "model_id": "turn_on_lpm",
            "metric": "count_share",
            "outcome": "stable_turn_on",
            "regressor": "baseline_complex_route_share",
        },
    ),
    TableRow(
        margin="Thin/direct",
        outcome="Stable appears",
        regressor_label="Direct share $\\times$ thinness",
        selector={
            "model_id": "turn_on_direct_thin_interaction",
            "metric": "count_share",
            "outcome": "stable_turn_on",
            "regressor": "baseline_direct_x_thin",
        },
    ),
    TableRow(
        margin="Leader switch",
        outcome="Stable becomes leader",
        regressor_label="Baseline route count",
        selector={
            "model_id": "leader_switch_lpm",
            "metric": "count_share",
            "outcome": "stable_leader_switch",
            "regressor": "baseline_log_market_routes",
        },
    ),
    TableRow(
        margin="Rolling hazard",
        outcome="Stable appears within 30d",
        regressor_label="Origin route count",
        selector={
            "model_id": "stable_turn_on_hazard_fe",
            "outcome": "future_stable_turn_on",
            "regressor": "log_market_routes",
        },
    ),
    TableRow(
        margin="Rolling hazard",
        outcome="Stable appears within 30d",
        regressor_label="Ultimate-pair age",
        selector={
            "model_id": "stable_turn_on_hazard_fe",
            "outcome": "future_stable_turn_on",
            "regressor": "pair_age_log",
        },
    ),
    TableRow(
        margin="Mixed risk set",
        outcome="Vehicle route share",
        regressor_label="Same-day reach",
        selector={
            "model_id": "mixed_native_stable_risk_set_centrality_fe",
            "metric": "candidate_route_share",
            "outcome": "candidate_route_share",
            "regressor": "log_leaveout_candidate_pair_scopes",
            "min_total_routes": 5.0,
        },
    ),
    TableRow(
        margin="Mixed risk set",
        outcome="Vehicle route share",
        regressor_label="Prior-30d reach",
        selector={
            "model_id": "mixed_native_stable_risk_set_lag30_reach_fe",
            "metric": "candidate_route_share",
            "outcome": "candidate_route_share",
            "regressor": "log_lag30_candidate_pair_scopes",
            "min_total_routes": 5.0,
        },
    ),
    TableRow(
        margin="Issuer split",
        outcome="Vehicle route share",
        regressor_label="USDC $\\times$ 2026",
        selector={
            "model_id": "mixed_native_stable_risk_set_issuer_reach_fe",
            "metric": "candidate_route_share",
            "outcome": "candidate_route_share",
            "regressor": "is_usdc_x_2026",
            "min_total_routes": 5.0,
        },
    ),
    TableRow(
        margin="Issuer split",
        outcome="Vehicle route share",
        regressor_label="USDT $\\times$ 2026",
        selector={
            "model_id": "mixed_native_stable_risk_set_issuer_reach_fe",
            "metric": "candidate_route_share",
            "outcome": "candidate_route_share",
            "regressor": "is_usdt_x_2026",
            "min_total_routes": 5.0,
        },
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


def _select_one(results: pd.DataFrame, selector: dict[str, object]) -> pd.Series:
    selected = results
    for column, value in selector.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one vehicle-mechanism row for {selector}; found {len(selected)}")
    return selected.iloc[0]


def _cell(row: pd.Series) -> str:
    effect = float(row["coefficient_pp"])
    standard_error = float(row["standard_error_pp"])
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.1f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({standard_error:.1f})$"
        r"\end{tabular}"
    )


def _support(row: pd.Series) -> str:
    observations = int(row["observations"])
    if not pd.isna(row.get("date_clusters")):
        clusters = int(row["date_clusters"])
    else:
        clusters = int(row["month_day_clusters"])
    return f"{observations:,} / {clusters:,}"


def render_vehicle_mechanism_regressions(results: pd.DataFrame) -> str:
    required = {
        "model_id",
        "outcome",
        "regressor",
        "coefficient_pp",
        "standard_error_pp",
        "p_value",
        "observations",
        "fixed_effects",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"vehicle-mechanism results lack required columns: {missing}")

    rows: list[str] = []
    rows.append(
        r"\begin{tabularx}{\linewidth}{@{}"
        r">{\hsize=0.72\hsize\raggedright\arraybackslash}X"
        r">{\hsize=1.05\hsize\raggedright\arraybackslash}X"
        r">{\hsize=1.23\hsize\raggedright\arraybackslash}X"
        r"cr@{}}"
    )
    rows.append(r"\toprule")
    rows.append(r"Margin & Outcome & Regressor & Coefficient [pp] & Obs. / clusters \\")
    rows.append(r"\midrule")
    for table_row in TABLE_ROWS:
        row = _select_one(results, table_row.selector)
        rows.append(
            f"{table_row.margin} & {table_row.outcome} & "
            f"{table_row.regressor_label} & {_cell(row)} & {_support(row)} \\\\"
        )
    rows.append(r"\bottomrule")
    rows.append(r"\end{tabularx}")
    rows.append("")
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "vehicle_mechanism_regressions",
        render_vehicle_mechanism_regressions(results),
        preview_width="8.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

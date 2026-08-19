#!/usr/bin/env python3
"""Render the paper's liquidity-provision behavior regression table."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


RESULTS = OUTPUT_DIR / "exhibits" / "liquidity_provision_behavior_exploration.jsonl"


@dataclass(frozen=True)
class TableRow:
    margin: str
    outcome: str
    horizon: str
    unit: str
    selector: dict[str, object]


TABLE_ROWS: tuple[TableRow, ...] = (
    TableRow(
        margin="V2 stock",
        outcome="Capital share change",
        horizon="120d",
        unit="pp",
        selector={
            "record_type": "route_capital_gap_closing_stable_interaction",
            "horizon_days": 120.0,
            "outcome": "future_v2_five_candidate_capital_share_change",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V2 stock",
        outcome="Log deposited capital",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_closing_stable_interaction",
            "horizon_days": 120.0,
            "outcome": "future_v2_log1p_deposited_capital_usd_change",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="Portfolio rank",
        outcome="Capital-rank catch-up",
        horizon="120d",
        unit="ranks",
        selector={
            "record_type": "route_capital_gap_rank_transition",
            "horizon_days": 120.0,
            "outcome": "future_capital_rank_improvement",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="Same pool",
        outcome="Same-pool capital",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_same_pool_reallocation",
            "horizon_days": 120.0,
            "outcome": "future_log_pool_candidate_capital_change",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="Pool footprint",
        outcome="Incumbent-pool capital",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_pool_entry_response",
            "horizon_days": 120.0,
            "outcome": "future_log_incumbent_capital_change",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="Rent incidence",
        outcome="V3 fee yield",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_v3_fee_incidence",
            "horizon_days": 120.0,
            "outcome": "future_log_fee_yield_bps_change",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V3 churn",
        outcome="Mint events",
        horizon="30d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_v3_lp_action",
            "horizon_days": 30.0,
            "outcome": "future_log1p_v3_mint_events",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V3 churn",
        outcome="Burn events",
        horizon="30d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_v3_lp_action",
            "horizon_days": 30.0,
            "outcome": "future_log1p_v3_burn_events",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V3 churn",
        outcome="Net mint-burn balance",
        horizon="30d",
        unit="events",
        selector={
            "record_type": "route_capital_gap_v3_lp_action",
            "horizon_days": 30.0,
            "outcome": "future_v3_net_mint_event_balance",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V3 activity-controlled",
        outcome="Provider-day activity",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_v3_lp_action_activity_control",
            "horizon_days": 120.0,
            "outcome": "future_log1p_v3_total_origin_count",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V4 accounting",
        outcome="Multi-leg transaction share",
        horizon="same day",
        unit="pp",
        selector={
            "record_type": "route_capital_gap_v4_flash_accounting",
            "outcome": "multi_leg_tx_share",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V4 accounting",
        outcome="Internal same-asset share",
        horizon="same day",
        unit="pp",
        selector={
            "record_type": "route_capital_gap_v4_flash_accounting",
            "outcome": "internal_tx_share",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V4 accounting",
        outcome="Gross-to-net reduction share",
        horizon="same day",
        unit="pp",
        selector={
            "record_type": "route_capital_gap_v4_flash_accounting",
            "outcome": "netting_reduction_share",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V4 LP flow",
        outcome="Gross vehicle-side flow",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_v4_lp_flow",
            "horizon_days": 120.0,
            "outcome": "future_log1p_v4_gross_lp_flow_usd_screened",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V4 LP flow",
        outcome="Add flow",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_v4_lp_flow",
            "horizon_days": 120.0,
            "outcome": "future_log1p_v4_add_lp_flow_usd_screened",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V4 LP flow",
        outcome="Remove flow",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_v4_lp_flow",
            "horizon_days": 120.0,
            "outcome": "future_log1p_v4_remove_lp_flow_usd_screened",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V4 activity-controlled",
        outcome="LP actions",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_v4_lp_action_activity_control_v4_active",
            "horizon_days": 120.0,
            "outcome": "future_log1p_v4_total_lp_actions",
            "predictor": "stable_total_route_capital_gap_5",
        },
    ),
    TableRow(
        margin="V4 activity-controlled",
        outcome="Sender-days",
        horizon="120d",
        unit="log pts",
        selector={
            "record_type": "route_capital_gap_v4_lp_action_activity_control_v4_active",
            "horizon_days": 120.0,
            "outcome": "future_log1p_v4_sender_count",
            "predictor": "stable_total_route_capital_gap_5",
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


def _select_one(results: pd.DataFrame, row: TableRow) -> pd.Series:
    sample = results.copy()
    for column, expected in row.selector.items():
        if column not in sample.columns:
            raise ValueError(f"liquidity results lack selector column: {column}")
        sample = sample[sample[column].eq(expected)]
    if len(sample) != 1:
        raise ValueError(f"expected one row for {row.outcome}, found {len(sample)}")
    return sample.iloc[0]


def _scaled_effect(result: pd.Series, unit: str) -> tuple[float, float, int]:
    coefficient = result.get("coefficient_per_10pp_gap")
    standard_error = result.get("standard_error_per_10pp_gap")
    if pd.isna(coefficient) or pd.isna(standard_error):
        coefficient = 0.10 * float(result["coefficient"])
        standard_error = 0.10 * float(result["standard_error"])
    else:
        coefficient = float(coefficient)
        standard_error = float(standard_error)
    if unit == "pp":
        return 100.0 * coefficient, 100.0 * standard_error, 1
    return coefficient, standard_error, 3


def _effect_cell(result: pd.Series, unit: str) -> str:
    effect, standard_error, digits = _scaled_effect(result, unit)
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.{digits}f}{_stars(float(result['p_value']))}$"
        r"\\"
        f"$({standard_error:.{digits}f})$"
        r"\end{tabular}"
    )


def _int_cell(result: pd.Series, column: str) -> str:
    return f"{int(round(float(result[column]))):,}"


def render_liquidity_provision_regressions(results: pd.DataFrame) -> str:
    """Render the liquidity-provision table from the exploration exhibit."""

    required = {
        "record_type",
        "outcome",
        "predictor",
        "coefficient",
        "standard_error",
        "p_value",
        "n_observations",
        "date_clusters",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise ValueError(f"liquidity results lack required columns: {missing}")

    rows: list[str] = []
    rows.append(
        r"\begin{tabularx}{\linewidth}{@{}"
        r">{\raggedright\arraybackslash}X"
        r">{\raggedright\arraybackslash}X"
        r"c"
        r"c"
        r"c"
        r"r"
        r"r@{}}"
    )
    rows.append(r"\toprule")
    rows.append(
        r"Margin & Outcome & Horizon & Effect & Unit & Obs. & Clusters \\"
    )
    rows.append(r"\midrule")
    for row in TABLE_ROWS:
        result = _select_one(results, row)
        rows.append(
            f"{row.margin} & {row.outcome} & {row.horizon} & "
            f"{_effect_cell(result, row.unit)} & {row.unit} & "
            f"{_int_cell(result, 'n_observations')} & "
            f"{_int_cell(result, 'date_clusters')} \\\\"
        )
    rows.append(r"\bottomrule")
    rows.append(r"\end{tabularx}")
    rows.append("")
    return "\n".join(rows)


def main() -> int:
    results = pd.read_json(RESULTS, lines=True)
    write_table_artifacts(
        "liquidity_provision_regressions",
        render_liquidity_provision_regressions(results),
        preview_width="9in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

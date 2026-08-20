#!/usr/bin/env python3
"""Render the main-text V3-versus-V4 liquidity-provider comparison."""

from __future__ import annotations

import pandas as pd

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


ACTION_RESULTS = OUTPUT_DIR / "exhibits" / "v3_v4_lp_protocol_contrast.jsonl"
FLOW_RESULTS = OUTPUT_DIR / "exhibits" / "v3_v4_lp_flow_protocol_contrast.jsonl"
STOCK_RESULTS = OUTPUT_DIR / "exhibits" / "v3_v4_tvl_protocol_contrast.jsonl"

ROWS = (
    ("actions", "future_log1p_total_lp_actions", 120, "LP actions", "log points"),
    ("actions", "future_log1p_total_origin_count", 120, "Active provider origins", "log points"),
    ("flows", "future_log1p_gross_lp_flow_usd", 120, "Gross vehicle-side flow", "log points"),
    ("flows", "future_log1p_add_lp_flow_usd", 120, "Add-side flow", "log points"),
    ("flows", "future_log1p_remove_lp_flow_usd", 120, "Remove-side flow", "log points"),
    ("flows", "future_narrow_medium_flow_value_share", 30, "Narrow/medium flow share", "pp"),
    ("stocks", "future_delta_log1p_tvl", 120, "Reported liquidity", "log points"),
    ("stocks", "future_delta_log1p_pool_count", 120, "Pool footprint", "log points"),
)


def _stars(p_value: float) -> str:
    if p_value < 0.01:
        return "^{***}"
    if p_value < 0.05:
        return "^{**}"
    if p_value < 0.10:
        return "^{*}"
    return ""


def _cell(row: pd.Series, *, unit: str) -> str:
    effect = float(row["effect_per_10pp_stable_gap_v4_minus_v3"])
    standard_error = float(
        row["standard_error_per_10pp_stable_gap_v4_minus_v3"]
    )
    if unit == "pp":
        effect *= 100.0
        standard_error *= 100.0
    return (
        r"\begin{tabular}{@{}c@{}}"
        f"${effect:+.3f}{_stars(float(row['p_value']))}$"
        r"\\"
        f"$({standard_error:.3f})$"
        r"\end{tabular}"
    )


def render_v3_v4_lp_summary(
    action_results: pd.DataFrame,
    flow_results: pd.DataFrame,
    stock_results: pd.DataFrame,
) -> str:
    """Render selected economic margins from the three complete contrast grids."""

    frames = {
        "actions": action_results,
        "flows": flow_results,
        "stocks": stock_results,
    }
    required = {
        "horizon_days",
        "outcome",
        "term",
        "effect_per_10pp_stable_gap_v4_minus_v3",
        "standard_error_per_10pp_stable_gap_v4_minus_v3",
        "p_value",
        "n_observations",
        "date_clusters",
    }
    for name, frame in frames.items():
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"{name} contrast results lack columns: {missing}")

    selected: list[tuple[pd.Series, int, str, str]] = []
    for family, outcome, horizon, label, unit in ROWS:
        frame = frames[family]
        rows = frame[
            frame["term"].eq("v4_x_stable_gap")
            & frame["outcome"].eq(outcome)
            & frame["horizon_days"].eq(horizon)
        ]
        if len(rows) != 1:
            raise ValueError(
                f"expected one {family}/{outcome}/{horizon}-day contrast, found {len(rows)}"
            )
        selected.append((rows.iloc[0], horizon, label, unit))

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\hsize=1.35\hsize\raggedright\arraybackslash}X>{\centering\arraybackslash}X>{\centering\arraybackslash}X>{\centering\arraybackslash}X@{}}",
        r"\toprule",
        r"Provider outcome & Horizon & V4-minus-V3 effect & Obs. / dates \\",
        r"\midrule",
    ]
    for row, horizon, label, unit in selected:
        lines.append(
            f"{label} [{unit}] & {horizon} days & {_cell(row, unit=unit)} & "
            f"{int(row['n_observations']):,} / {int(row['date_clusters']):,} "
            + r"\\"
        )
    lines.extend(
        [
            r"\midrule",
            r"Vehicle-date and protocol effects & \multicolumn{3}{r}{Yes} \\",
            r"Origin provider controls & \multicolumn{3}{r}{Yes} \\",
            r"\bottomrule",
            r"\end{tabularx}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    action_results = pd.read_json(ACTION_RESULTS, lines=True)
    flow_results = pd.read_json(FLOW_RESULTS, lines=True)
    stock_results = pd.read_json(STOCK_RESULTS, lines=True)
    write_table_artifacts(
        "v3_v4_lp_summary",
        render_v3_v4_lp_summary(action_results, flow_results, stock_results),
        preview_width="7.5in",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

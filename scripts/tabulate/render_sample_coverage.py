#!/usr/bin/env python3
"""Render coverage of the processed empirical samples."""

from __future__ import annotations

import pandas as pd

from ddvc.paths import DATA_DIR, LP_CAPITAL_CONCENTRATION_PANEL
from ddvc.paper_tables import write_table_artifacts


BRIDGE_PANEL = DATA_DIR / "empirical" / "bridge_daily.parquet"
ROUTE_COST_PANEL = DATA_DIR / "empirical" / "route_cost_panel_v2.parquet"
V4_ROUTE_UNITS = DATA_DIR / "empirical" / "v4_settlement_route_units.parquet"


def count(value: int | float) -> str:
    return f"{int(round(float(value))):,}"


def number(value: float, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}"


def row(*cells: str) -> str:
    return " & ".join(cells) + r" \\"


bridge = pd.read_parquet(BRIDGE_PANEL)
route = pd.read_parquet(
    ROUTE_COST_PANEL,
    columns=["date", "direct_available", "vehicle_available", "direct_cost_advantage"],
)
lp = pd.read_parquet(LP_CAPITAL_CONCENTRATION_PANEL)
units = pd.read_parquet(
    V4_ROUTE_UNITS,
    columns=["date"],
)

bridge_days = bridge.drop_duplicates("date").copy()
active_bridge_days = bridge_days[bridge_days["indirect_route_count"].gt(0)]
common_support = route[
    route["direct_available"]
    & route["vehicle_available"]
    & route["direct_cost_advantage"].notna()
]

rows = [
    (
        "Vehicle-use token-day panel",
        str(active_bridge_days["date"].min()),
        str(active_bridge_days["date"].max()),
        count(active_bridge_days["date"].nunique()),
        count(len(bridge)),
        f"\\${number(active_bridge_days['indirect_route_volume_usd'].sum() / 1e12)}tn indirect route volume",
    ),
    (
        "Candidate-linked liquidity panel",
        str(lp["date"].min()),
        str(lp["date"].max()),
        count(lp["date"].nunique()),
        count(len(lp)),
        f"\\${number(lp['total_lp_capital_usd'].mean() / 1e9)}bn mean linked liquidity",
    ),
    (
        "Route-cost counterfactual panel",
        str(route["date"].min()),
        str(route["date"].max()),
        count(route["date"].nunique()),
        count(len(route)),
        f"{count(len(common_support))} common-support quotes",
    ),
    (
        "Pure V3/V4 route-unit panel",
        str(units["date"].min()),
        str(units["date"].max()),
        count(units["date"].nunique()),
        count(len(units)),
        "Complete coherent components assigned to one architecture",
    ),
]

lines = [
    r"% Requires \usepackage{booktabs,tabularx,array}.",
    r"\begingroup",
    r"\renewcommand{\arraystretch}{1.15}",
    r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xllrr>{\raggedright\arraybackslash}X@{}}",
    r"\toprule",
    row("Sample", "Start", "End", "Days", "Observations", "Main quantity"),
    r"\midrule",
]
lines.extend(row(*item) for item in rows)
lines.extend(
    [
        r"\bottomrule",
        r"\end{tabularx}",
        r"\endgroup",
    ]
)

write_table_artifacts(
    "sample_coverage",
    "\n".join(lines) + "\n",
    preview_width="9in",
    inputs=[BRIDGE_PANEL, ROUTE_COST_PANEL, LP_CAPITAL_CONCENTRATION_PANEL, V4_ROUTE_UNITS],
    notes=(
        "Legacy sample-coverage inspection table; route_cost_panel_v2 is withdrawn "
        "pending its registered rebuild and this renderer must not be used meanwhile."
    ),
)

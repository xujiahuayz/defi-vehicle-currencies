#!/usr/bin/env python3
"""Render coverage of the processed empirical samples."""

from __future__ import annotations

import pandas as pd

from ddvc.paths import DATA_DIR
from utils import ROOT, write_table_artifacts


def count(value: int | float) -> str:
    return f"{int(round(float(value))):,}"


def number(value: float, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}"


def row(*cells: str) -> str:
    return " & ".join(cells) + r" \\"


bridge = pd.read_parquet(DATA_DIR / "empirical" / "bridge_daily.parquet")
route = pd.read_parquet(
    DATA_DIR / "empirical" / "route_cost_panel_v2.parquet",
    columns=["date", "direct_available", "vehicle_available", "vehicle_route_advantage"],
)
lp = pd.read_parquet(DATA_DIR / "exhibits" / "lp_concentration.parquet")
units = pd.read_parquet(
    DATA_DIR / "empirical" / "v4_settlement_route_units.parquet",
    columns=["date"],
)
cells = pd.read_parquet(DATA_DIR / "empirical" / "v4_settlement_eligible_cells.parquet")
settlement = pd.read_parquet(DATA_DIR / "empirical" / "v4_settlement_sample.parquet")

bridge_days = bridge.drop_duplicates("date").copy()
active_bridge_days = bridge_days[bridge_days["indirect_route_count"].gt(0)]
common_support = route[
    route["direct_available"]
    & route["vehicle_available"]
    & route["vehicle_route_advantage"].notna()
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
        f"\\${number(lp['total_lp_liquidity_usd'].mean() / 1e9)}bn mean linked liquidity",
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
        "V4 settlement route-unit panel",
        str(units["date"].min()),
        str(units["date"].max()),
        count(units["date"].nunique()),
        count(len(units)),
        f"{count(len(cells))} matched cells; {count(len(settlement))} receipt observations",
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
        r"\par\smallskip",
        r"\begin{minipage}{\linewidth}\footnotesize",
        r"\textit{Notes:} Processed empirical samples are built from the DVC raw layer through "
        r"2026-06-30. Observation units are stated in each sample name. The route-cost panel "
        r"uses daily state cutoffs and three trade-size buckets.",
        r"\end{minipage}",
        r"\endgroup",
    ]
)

out_tex, out_pdf = write_table_artifacts(
    "sample_coverage",
    "\n".join(lines) + "\n",
    preview_width="9in",
)
print(f"wrote {out_tex.relative_to(ROOT)}")
print(f"wrote {out_pdf.relative_to(ROOT)}")

#!/usr/bin/env python3
"""Direct runner for Table 1: summary statistics."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ddvc.analysis.observations import DEFAULT_OBSERVATIONS_TABLE
from ddvc.variable_registry import SUMMARY_SPECS
from utils import ROOT, write_table_artifacts


@dataclass(frozen=True)
class SummaryRow:
    panel: str
    variable: str
    observations: int
    mean: float
    std_dev: float
    p25: float
    median: float
    p75: float


def latex_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("$", r"\$")
        .replace("#", r"\#")
        .replace("_", r"\_")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def format_count(value: int) -> str:
    return f"{int(value):,}"


def format_number(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000:
        return f"{value:,.0f}"
    if abs_value >= 100:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def summary_row(panel: str, variable: str, values: pd.Series) -> SummaryRow:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        raise ValueError(f"No non-missing observations for {panel}: {variable}")
    return SummaryRow(
        panel=panel,
        variable=variable,
        observations=int(clean.shape[0]),
        mean=float(clean.mean()),
        std_dev=float(clean.std()),
        p25=float(clean.quantile(0.25)),
        median=float(clean.median()),
        p75=float(clean.quantile(0.75)),
    )


if not DEFAULT_OBSERVATIONS_TABLE.exists():
    raise FileNotFoundError(
        f"Required input is missing: {DEFAULT_OBSERVATIONS_TABLE}. "
        "Run .venv/bin/python scripts/process/build_observations_table.py first."
    )

panel = pd.read_parquet(DEFAULT_OBSERVATIONS_TABLE)
panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
day_panel = panel.drop_duplicates("date").sort_values("date")

panel_order = {
    "Daily route activity": 0,
    "Vehicle-use measures, token-day": 1,
    "Liquidity and route-cost opportunity": 2,
    "Settlement-transfer sample": 3,
}
summary_specs = sorted(
    SUMMARY_SPECS,
    key=lambda spec: (
        panel_order.get(spec.summary_panel or spec.group, 99),
        SUMMARY_SPECS.index(spec),
    ),
)

rows: list[SummaryRow] = []
for spec in summary_specs:
    if spec.column not in panel.columns:
        raise KeyError(f"Registered summary column missing from observations table: {spec.column}")
    source = day_panel if spec.summary_level == "day" else panel
    label = spec.summary_label or spec.name
    rows.append(summary_row(spec.summary_panel or spec.group, label, source[spec.column] * spec.summary_scale))

lines = [
    r"% Requires \usepackage{booktabs,tabularx,array}.",
    r"\begingroup",
    r"\renewcommand{\arraystretch}{1.15}",
    r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrrrrr@{}}",
    r"\toprule",
    r"Variable & Obs. & Mean & Std. dev. & p25 & Median & p75 \\",
    r"\midrule",
]
current_panel: str | None = None
for row in rows:
    if row.panel != current_panel:
        if current_panel is not None:
            lines.append(r"\addlinespace")
        lines.append(rf"\multicolumn{{7}}{{l}}{{\textit{{{latex_escape(row.panel)}}}}} \\")
        current_panel = row.panel
    cells = [
        latex_escape(row.variable),
        format_count(row.observations),
        format_number(row.mean),
        format_number(row.std_dev),
        format_number(row.p25),
        format_number(row.median),
        format_number(row.p75),
    ]
    lines.append(" & ".join(cells) + r" \\")

lines.extend([r"\bottomrule", r"\end{tabularx}", r"\endgroup"])

out_tex, out_pdf = write_table_artifacts(
    "summary_statistics",
    "\n".join(lines) + "\n",
    preview_width="9in",
)
print(f"wrote {out_tex.relative_to(ROOT)}")
print(f"wrote {out_pdf.relative_to(ROOT)}")

#!/usr/bin/env python3
"""Render the paper's within-day intermediary-role control ladder.

Each cell is selected by its full scientific identity (specification, sample and
term) rather than by row order, so a reordering of the exhibit cannot silently
move a five-token magnitude into a thirty-seven-token cell.
"""

from __future__ import annotations

import json
import math

from ddvc.paper_tables import write_table_artifacts
from ddvc.paths import OUTPUT_DIR


INPUT = OUTPUT_DIR / "exhibits" / "excess_use_date_fe_ladder.jsonl"
ALL = "all_endpoint_supported"
DASH = "---"
ROWS = (
    ("Pooled", "L1 pooled type dummies", False),
    ("{}+ day effects", "L2 + date FE", False),
    ("{}+ own endpoint share", "L3 + date FE + own demand share", True),
    ("{}+ currency effects", "L4 two-way token + date FE", True),
)


def _cell(rows: list[dict], spec: str, term: str) -> dict | None:
    matches = [r for r in rows if r["spec"] == spec and r["sample"] == ALL and r["term"] == term]
    if len(matches) > 1:
        raise ValueError(f"ladder exhibit has {len(matches)} rows for {spec}/{term}")
    return matches[0] if matches else None


def _pp(row: dict | None) -> str:
    if row is None:
        return DASH
    value = float(row["beta"])
    if not math.isfinite(value):
        raise ValueError("a displayed coefficient must be finite")
    return f"${value:+.2f}$"


def _pp_se(row: dict | None) -> str:
    if row is None:
        return DASH
    return f"({float(row['se']):.2f})"


def _slope(row: dict | None) -> str:
    if row is None:
        return DASH
    return f"{float(row['beta']):.3f}"


def _slope_se(row: dict | None) -> str:
    if row is None:
        return DASH
    return f"({float(row['se']):.3f})"


def render_within_day_ladder(rows: list[dict]) -> str:
    headline = _cell(rows, "L3 + date FE + own demand share", "demand")
    if headline is None:
        raise ValueError("ladder exhibit lacks its headline demand row")
    body: list[str] = []
    for label, spec, has_demand in ROWS:
        native = _cell(rows, spec, "native")
        stable = _cell(rows, spec, "stable")
        demand = _cell(rows, spec, "demand") if has_demand else None
        absorbed = _cell(rows, spec, "demand") or native
        absorbed_display = (
            f"{int(absorbed['absorbed_df']):,}" if absorbed is not None else DASH
        )
        body.append(
            f"{label} & {_pp(native)} & {_pp(stable)} & {_slope(demand)} "
            f"& {absorbed_display} \\\\"
        )
        body.append(
            f" & {_pp_se(native)} & {_pp_se(stable)} & {_slope_se(demand)} & \\\\"
        )
    return "\n".join(
        [
            r"\begin{tabular}{lcccr}",
            r"\toprule",
            r" & \multicolumn{2}{c}{Class premium (pp)} & Demand & Absorbed \\",
            r"\cmidrule(lr){2-3}",
            r"Specification & Native & Stable & pass-through & effects \\",
            r"\midrule",
            *body,
            r"\bottomrule",
            r"\end{tabular}",
        ]
    ) + "\n"


records = [
    json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines()
]
write_table_artifacts(
    "within_day_ladder",
    render_within_day_ladder(records),
    preview_width="7.0in",
)

#!/usr/bin/env python3
"""Render raw data coverage and observation counts by AMM."""

from __future__ import annotations

import pandas as pd

from ddvc.analysis.raw_data_inventory import summarize_raw_data_inventory
from ddvc.paths import DATA_DIR
from utils import ROOT, write_table_artifacts


INVENTORY = DATA_DIR / "processed" / "raw_data_inventory.parquet"
AMM_LABELS = {
    "uniswap_v1": "Uniswap V1",
    "curve": "Curve",
    "uniswap_v2": "Uniswap V2",
    "sushiswap_v2": "SushiSwap V2",
    "balancer": "Balancer",
    "uniswap_v3": "Uniswap V3",
    "sushiswap_v3": "SushiSwap V3",
    "fluid": "Fluid",
    "uniswap_v4": "Uniswap V4",
}
AMM_ORDER = list(AMM_LABELS)
BACKEND_LABELS = {"thegraph": "The Graph", "dune": "Dune"}


def count(value: int) -> str:
    return f"{int(value):,}"


def row(*cells: str) -> str:
    return " & ".join(cells) + r" \\"


if not INVENTORY.exists():
    raise FileNotFoundError(
        f"Required input is missing: {INVENTORY}. "
        "Run .venv/bin/python scripts/process/build_raw_data_inventory.py first."
    )

coverage = summarize_raw_data_inventory(pd.read_parquet(INVENTORY))
coverage["order"] = coverage["source"].map({name: i for i, name in enumerate(AMM_ORDER)})
coverage = coverage.sort_values("order")

overall_start = coverage["start"].min()
overall_end = coverage["end"].max()
totals = {
    column: int(coverage[column].sum())
    for column in [
        "active_days",
        "swap_records",
        "daily_state_records",
        "hourly_state_records",
        "lp_event_records",
        "raw_files",
        "compressed_bytes",
        "total_records",
    ]
}

lines = [
    r"% Requires \usepackage{booktabs,tabularx,array}.",
    r"\begingroup",
    r"\renewcommand{\arraystretch}{1.15}",
    r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xllrr@{}}",
    r"\toprule",
    r"\multicolumn{5}{@{}l}{\textit{Panel A. Fetched swap-source coverage}} \\",
    row("AMM", "Backend", "Positive-swap dates", "Positive-swap days", "Swap records"),
    r"\midrule",
]
for item in coverage.itertuples(index=False):
    lines.append(
        row(
            AMM_LABELS[item.source],
            BACKEND_LABELS[item.backend],
            f"{item.start:%Y-%m-%d}--{item.end:%Y-%m-%d}",
            count(item.active_days),
            count(item.swap_records),
        )
    )
lines.extend(
    [
        r"\midrule",
        row(
            "All AMMs",
            "",
            f"{overall_start:%Y-%m-%d}--{overall_end:%Y-%m-%d}",
            count(totals["active_days"]),
            count(totals["swap_records"]),
        ),
        r"\bottomrule",
        r"\end{tabularx}",
        r"\par\medskip",
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrr@{}}",
        r"\toprule",
        r"\multicolumn{4}{@{}l}{\textit{Panel B. Raw storage and total records}} \\",
        row("AMM", "Raw files", "Compressed GB", "All raw records"),
        r"\midrule",
    ]
)
for item in coverage.itertuples(index=False):
    lines.append(
        row(
            AMM_LABELS[item.source],
            count(item.raw_files),
            f"{item.compressed_bytes / 1e9:.2f}",
            count(item.total_records),
        )
    )
lines.extend(
    [
        r"\midrule",
        row(
            "All AMMs",
            count(totals["raw_files"]),
            f"{totals['compressed_bytes'] / 1e9:.2f}",
            count(totals["total_records"]),
        ),
        r"\bottomrule",
        r"\end{tabularx}",
        r"\par\medskip",
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrr@{}}",
        r"\toprule",
        r"\multicolumn{4}{@{}l}{\textit{Panel C. Ancillary raw-stream records}} \\",
        row("AMM", "Daily pool states", "Hourly reserve states", "LP events"),
        r"\midrule",
    ]
)
for item in coverage.itertuples(index=False):
    lines.append(
        row(
            AMM_LABELS[item.source],
            count(item.daily_state_records),
            count(item.hourly_state_records),
            count(item.lp_event_records),
        )
    )
lines.extend(
    [
        r"\midrule",
        row(
            "All AMMs",
            count(totals["daily_state_records"]),
            count(totals["hourly_state_records"]),
            count(totals["lp_event_records"]),
        ),
        r"\bottomrule",
        r"\end{tabularx}",
        r"\par\smallskip",
        r"\begin{minipage}{\linewidth}\footnotesize",
        r"\textit{Notes:} Counts describe persisted raw source records through 2026-06-30. "
        r"Positive-swap days are AMM-days and are summed in the total row. Compressed GB "
        r"uses decimal gigabytes; raw-file counts exclude metadata sidecars. Daily and hourly "
        r"states are pool-day and pair-hour records, respectively. LP events combine fetched "
        r"Uniswap V3 mints and burns with Uniswap V4 liquidity modifications. The all-record "
        r"total therefore combines distinct raw observation units. For Uniswap V1, one "
        r"swap-source record is a transaction row that can contain multiple purchase events.",
        r"\end{minipage}",
        r"\endgroup",
    ]
)

out_tex, out_pdf = write_table_artifacts(
    "data_coverage",
    "\n".join(lines) + "\n",
    preview_width="8.5in",
)
print(f"wrote {out_tex.relative_to(ROOT)}")
print(f"wrote {out_pdf.relative_to(ROOT)}")

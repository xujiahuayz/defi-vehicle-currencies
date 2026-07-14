#!/usr/bin/env python3
"""Render Table 1: summary statistics.

One script owns exactly one exhibit. It reads the rebuilt DVC analysis panels and
writes the journal-facing LaTeX table.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = ROOT / "output"
TABLES = OUT / "tables"

OUT_STEM = "table_01_summary_statistics"
OUT_TEX = TABLES / f"{OUT_STEM}.tex"
VEHICLE_TOKENS = ("WETH", "USDC", "USDT", "DAI", "WBTC")


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


def _require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Required input is missing: {path}")
    return path


def _as_date_string(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.strftime("%Y-%m-%d")


def _summary(panel: str, variable: str, values: pd.Series) -> SummaryRow:
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


def _load_inputs() -> dict[str, pd.DataFrame]:
    route_daily = pd.read_parquet(_require(DATA / "empirical" / "route_denominator_daily.parquet"))
    core = pd.read_parquet(_require(DATA / "empirical" / "core_token_day_panel.parquet"))
    v4 = pd.read_csv(_require(DATA / "empirical" / "v4_settlement_transfer_detail.csv"))

    route_daily = route_daily.copy()
    core = core.copy()
    route_daily["date"] = _as_date_string(route_daily["date"])
    core["date"] = _as_date_string(core["date"])
    return {"route_daily": route_daily, "core": core, "v4": v4}


def build_summary_rows() -> list[SummaryRow]:
    inputs = _load_inputs()
    route_daily = inputs["route_daily"]
    core = inputs["core"]
    v4 = inputs["v4"]

    core = core[core["token"].isin(VEHICLE_TOKENS)].copy()
    core = core.merge(
        route_daily[["date", "all_route_volume_usd"]],
        on="date",
        how="left",
    )
    core["all_route_bridge_share"] = core["bridge_volume_usd"] / core["all_route_volume_usd"]

    active_core = core[core["indirect_route_count"].gt(0)].copy()
    route_cost_core = core[core["quote_rows"].fillna(0).gt(0)].copy()
    lp_core = core[core["lp_concentration_share"].notna()].copy()

    rows: list[SummaryRow] = []

    rows.extend(
        [
            _summary("Panel A. Daily route activity", "Total route volume ($bn)", route_daily["all_route_volume_usd"] / 1e9),
            _summary(
                "Panel A. Daily route activity",
                "Indirect route volume ($bn)",
                route_daily["indirect_route_volume_usd"] / 1e9,
            ),
            _summary("Panel A. Daily route activity", "Indirect route share (%)", 100 * route_daily["indirect_route_share"]),
            _summary("Panel A. Daily route activity", "Total route count", route_daily["all_route_count"]),
            _summary("Panel A. Daily route activity", "Indirect route count", route_daily["indirect_route_count"]),
        ]
    )

    rows.extend(
        [
            _summary("Panel B. Vehicle-use measures, token-day", "BridgeShare (%)", 100 * active_core["BridgeShare"]),
            _summary("Panel B. Vehicle-use measures, token-day", "All-route bridge share (%)", 100 * active_core["all_route_bridge_share"]),
            _summary("Panel B. Vehicle-use measures, token-day", "Bridge count share (%)", 100 * active_core["BridgeCountShare"]),
            _summary("Panel B. Vehicle-use measures, token-day", "Pair coverage (%)", 100 * active_core["PairCoverage"]),
            _summary("Panel B. Vehicle-use measures, token-day", "Main-vehicle pair share (%)", 100 * active_core["PairMainVehicleShare"]),
            _summary("Panel B. Vehicle-use measures, token-day", "Bridge volume ($mn)", active_core["bridge_volume_usd"] / 1e6),
        ]
    )

    rows.extend(
        [
            _summary("Panel C. Liquidity and route-cost opportunity", "Vehicle-linked LP liquidity ($bn)", lp_core["total_lp_liquidity_usd"] / 1e9),
            _summary("Panel C. Liquidity and route-cost opportunity", "LP concentration (%)", 100 * lp_core["lp_concentration_share"]),
            _summary("Panel C. Liquidity and route-cost opportunity", "Direct route available (%)", 100 * route_cost_core["direct_available_share"]),
            _summary("Panel C. Liquidity and route-cost opportunity", "Vehicle route available (%)", 100 * route_cost_core["vehicle_available_share"]),
            _summary(
                "Panel C. Liquidity and route-cost opportunity",
                "No-direct vehicle route (%)",
                100 * route_cost_core["no_direct_vehicle_available_share"],
            ),
            _summary(
                "Panel C. Liquidity and route-cost opportunity",
                "Vehicle advantage (bp)",
                route_cost_core["route_cost_advantage_median_bps"],
            ),
            _summary("Panel C. Liquidity and route-cost opportunity", "Vehicle beats direct route (%)", 100 * route_cost_core["vehicle_beats_direct_share"]),
            _summary("Panel C. Liquidity and route-cost opportunity", "Thin direct route share (%)", 100 * route_cost_core["thin_direct_share"]),
        ]
    )

    rows.extend(
        [
            _summary("Panel D. Settlement-transfer sample", "Matched route value ($000)", v4["route_usd"] / 1_000),
            _summary("Panel D. Settlement-transfer sample", "Receipt found (%)", 100 * v4["receipt_found"].astype(float)),
            _summary(
                "Panel D. Settlement-transfer sample",
                "Intermediary transfer incidence (%)",
                100 * v4["has_matching_transfer"].astype(float),
            ),
            _summary("Panel D. Settlement-transfer sample", "Matching intermediary-transfer logs", v4["matching_transfer_logs"]),
            _summary("Panel D. Settlement-transfer sample", "Receipt log count", v4["total_logs"]),
        ]
    )

    return rows


def _format_count(value: int) -> str:
    return f"{int(value):,}"


def _format_number(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000:
        return f"{value:,.0f}"
    if abs_value >= 100:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def _latex_escape(value: object) -> str:
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


def _write_latex(rows: list[SummaryRow]) -> None:
    lines = [
        r"\begin{table}[!htbp]",
        r"\centering",
        r"\caption{Summary statistics}",
        r"\label{tab:summary-statistics}",
        r"\small",
        r"\begin{tabular}{@{}lrrrrrr@{}}",
        r"\toprule",
        r"Variable & Obs. & Mean & Std. dev. & p25 & Median & p75 \\",
        r"\midrule",
    ]

    current_panel: str | None = None
    for row in rows:
        if row.panel != current_panel:
            if current_panel is not None:
                lines.append(r"\addlinespace")
            lines.append(rf"\multicolumn{{7}}{{l}}{{\textit{{{_latex_escape(row.panel)}}}}} \\")
            current_panel = row.panel
        cells = [
            _latex_escape(row.variable),
            _format_count(row.observations),
            _format_number(row.mean),
            _format_number(row.std_dev),
            _format_number(row.p25),
            _format_number(row.median),
            _format_number(row.p75),
        ]
        lines.append(" & ".join(cells) + r" \\")

    note = (
        "Notes: The table reports summary statistics for the main variables used in the empirical analysis. "
        "Panel A is at the day level. Panel B is at the candidate-vehicle-token-by-day level and is restricted "
        "to days with positive indirect routing. Panel C uses candidate-vehicle-token days with non-missing "
        "liquidity or quote-opportunity measures. Panel D uses the matched V3/V4 receipt-level settlement sample. "
        "BridgeShare uses indirect route volume as the denominator; all-route bridge share uses total route volume."
    )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\vspace{0.35em}",
            r"\begin{minipage}{0.98\linewidth}",
            rf"\footnotesize {_latex_escape(note)}",
            r"\end{minipage}",
            r"\end{table}",
        ]
    )
    OUT_TEX.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    rows = build_summary_rows()
    _write_latex(rows)
    print(f"wrote {OUT_TEX.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build paper-facing exhibit tables and figures from DVC empirical outputs.

This is intentionally a presentation layer. It does not refetch data and does
not rerun long counterfactual panels. It reads the canonical empirical outputs
and writes publication-ready CSV/LaTeX tables plus compact PDF figures.
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"
MANIFEST = OUT / "exhibits" / "paper_exhibit_manifest.md"

VEHICLE_ORDER = ["WETH", "USDC", "USDT", "DAI", "WBTC"]


def _ensure_dirs() -> None:
    for path in (TABLES, FIGURES, MANIFEST.parent):
        path.mkdir(parents=True, exist_ok=True)


def _pct(x: float, digits: int = 1) -> str:
    if pd.isna(x):
        return ""
    return f"{100 * float(x):.{digits}f}"


def _num(x: float, digits: int = 2) -> str:
    if pd.isna(x):
        return ""
    return f"{float(x):.{digits}f}"


def _int(x: float) -> str:
    if pd.isna(x):
        return ""
    return f"{int(round(float(x))):,}"


def _p(x: float) -> str:
    if pd.isna(x):
        return ""
    x = float(x)
    if x < 0.001:
        return "<0.001"
    return f"{x:.3f}"


def _latex_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("$", "\\$")
        .replace("#", "\\#")
        .replace("_", "\\_")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def _write_table(
    df: pd.DataFrame,
    stem: str,
    caption: str,
    label: str,
    *,
    align: str | None = None,
    note: str | None = None,
) -> None:
    csv_path = TABLES / f"{stem}.csv"
    tex_path = TABLES / f"{stem}.tex"
    df.to_csv(csv_path, index=False)
    align = align or ("l" + "r" * (len(df.columns) - 1))
    lines = [
        "\\begin{table}[!htbp]",
        "\\centering",
        f"\\caption{{{_latex_escape(caption)}}}",
        f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{align}}}",
        "\\toprule",
        " & ".join(_latex_escape(c) for c in df.columns) + " \\\\",
        "\\midrule",
    ]
    for row in df.itertuples(index=False, name=None):
        lines.append(" & ".join(_latex_escape(v) for v in row) + " \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}"])
    if note:
        lines.extend(["\\begin{flushleft}", f"\\footnotesize {_latex_escape(note)}", "\\end{flushleft}"])
    lines.append("\\end{table}")
    tex_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _copy_if_exists(src: Path, dest: Path) -> None:
    if src.exists():
        shutil.copy2(src, dest)


def build_table_bridge_measurement() -> None:
    summary = pd.read_csv(EMP / "bridge_measure_summary_by_year.csv")
    years = [2020, 2022, 2024, 2026]
    rows = []
    for token in VEHICLE_ORDER:
        row: dict[str, str] = {"Token": token}
        for year in years:
            g = summary[(summary["year"] == year) & (summary["token"] == token)]
            if g.empty:
                row[f"{year} BridgeShare (%)"] = ""
            else:
                r = g.iloc[0]
                row[f"{year} BridgeShare (%)"] = _pct(r["BridgeShare"])
        g2026 = summary[(summary["year"] == 2026) & (summary["token"] == token)]
        if g2026.empty:
            row["2026 VShare (%)"] = ""
            row["2026 PairCoverage (%)"] = ""
        else:
            r = g2026.iloc[0]
            row["2026 VShare (%)"] = _pct(r["VShare"])
            row["2026 PairCoverage (%)"] = _pct(r["PairCoverage"])
        rows.append(row)
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_01_bridge_measurement",
        "Vehicle use and raw volume share by year.",
        "tab:bridge-measurement",
        note=(
            "BridgeShare is the share of indirect route volume in which the token is an "
            "intermediate. VShare is total token volume share and includes endpoint demand. "
            "PairCoverage is the share of active endpoint pairs for which the token appears "
            "as an intermediate."
        ),
    )


def build_table_route_cost() -> None:
    df = pd.read_csv(EMP / "route_cost_panel_v2_summary.csv")
    weth = df[df["vehicle"].eq("WETH")].sort_values("trade_size_usd")
    rows = []
    for r in weth.itertuples(index=False):
        rows.append({
            "Trade size": f"${_int(r.trade_size_usd)}",
            "Common-support rows": _int(r.both_available_rows),
            "WETH beats direct (%)": _pct(r.vehicle_beats_direct_share),
            "Median advantage (bp)": _num(r.median_advantage_bps, 1),
            "p25 (bp)": _num(r.p25_advantage_bps, 1),
            "p75 (bp)": _num(r.p75_advantage_bps, 1),
            "t": _num(r.t_winsor_mean, 2),
            "p": _p(r.p_winsor_mean),
            "No-direct rows": _int(r.no_direct_vehicle_available_rows),
        })
    _write_table(
        pd.DataFrame(rows),
        "table_02_route_cost_advantage",
        "Direct routes and WETH vehicle-route execution costs.",
        "tab:route-cost-advantage",
        note=(
            "Advantage is output value on the best WETH vehicle route minus the best direct "
            "route, in basis points of direct-route output. Quotes use V2-style reserves plus "
            "exact Uniswap V3 tick-net liquidity reconstructed from raw events."
        ),
    )

    app = df.sort_values(["trade_size_usd", "vehicle"]).copy()
    out = pd.DataFrame({
        "Vehicle": app["vehicle"],
        "Trade size": app["trade_size_usd"].map(lambda x: f"${_int(x)}"),
        "Available (%)": app["vehicle_available_share"].map(_pct),
        "Beats direct (%)": app["vehicle_beats_direct_share"].map(_pct),
        "Median advantage (bp)": app["median_advantage_bps"].map(lambda x: _num(x, 1)),
        "t": app["t_winsor_mean"].map(lambda x: _num(x, 2)),
        "p": app["p_winsor_mean"].map(_p),
        "No-direct rows": app["no_direct_vehicle_available_rows"].map(_int),
    })
    _write_table(
        out,
        "table_a01_route_cost_all_vehicles",
        "Route-cost counterfactuals for all vehicle candidates.",
        "tab:route-cost-all-vehicles",
    )


def build_table_liquidity_stickiness() -> None:
    formation = pd.read_csv(EMP / "liquidity_formation_tests.csv")
    stick = pd.read_csv(EMP / "bridge_stickiness_tests.csv")
    rows = []
    for r in formation.itertuples(index=False):
        rows.append({
            "Test": str(r.name).replace("P2 ", ""),
            "N": _int(r.n),
            "Coefficient": _num(r.beta, 3),
            "SE": _num(r.se, 3),
            "t": _num(r.t, 2),
            "p": _p(r.p),
        })
    for r in stick.itertuples(index=False):
        rows.append({
            "Test": str(r.name).replace("P2 stickiness AR(1): ", "AR(1), "),
            "N": _int(r.n),
            "Coefficient": _num(r.beta, 3),
            "SE": _num(r.se, 3),
            "t": _num(r.t, 2),
            "p": _p(r.p),
        })
    _write_table(
        pd.DataFrame(rows),
        "table_03_liquidity_stickiness",
        "Liquidity concentration and persistence of vehicle use.",
        "tab:liquidity-stickiness",
        note=(
            "The formation rows regress seven-day-ahead BridgeShare on vehicle-linked LP "
            "concentration. The AR(1) rows estimate daily persistence by token."
        ),
    )


def build_table_stress() -> None:
    common = pd.read_csv(EMP / "stress_common_support_summary.csv")
    events = pd.read_csv(EMP / "stress_common_support_events.csv")
    r = common.iloc[0]
    out = pd.DataFrame([{
        "Design": "Common-support stress events",
        "Events": _int(r["n"]),
        "Effect (pp)": _num(100 * r["beta"], 2),
        "SE (pp)": _num(100 * r["se"], 2),
        "t": _num(r["t"], 2),
        "p": _p(r["p"]),
    }])
    _write_table(
        out,
        "table_04_stress_rotation",
        "Stress rotation in common-support vehicle-route opportunities.",
        "tab:stress-rotation",
        note=(
            "Effect is the event-day change in WETH-minus-stable BridgeShare relative to "
            "the same endpoint pairs' prior 14-day baseline."
        ),
    )

    top = events.sort_values("downside_stress", ascending=False).head(10).copy()
    app = pd.DataFrame({
        "Event date": top["event_date"],
        "WETH downside (%)": top["downside_stress"].map(_pct),
        "Endpoint pairs": top["n_pairs"].map(_int),
        "Effect (pp)": top["weighted_effect"].map(lambda x: _num(100 * x, 2)),
    })
    _write_table(
        app,
        "table_a02_stress_events",
        "Largest WETH downside events used in the common-support design.",
        "tab:stress-events",
    )


def build_table_v4() -> None:
    dex = pd.read_csv(EMP / "v4_settlement_dex_summary.csv")
    paired = pd.read_csv(EMP / "v4_settlement_paired.csv")
    hetero = pd.read_csv(EMP / "v4_settlement_heterogeneity.csv")
    v3 = dex[dex["dex"].eq("uniswap_v3")].iloc[0]
    v4 = dex[dex["dex"].eq("uniswap_v4")].iloc[0]
    diff = paired.iloc[0] if not paired.empty else None
    out = pd.DataFrame([
        {
            "DEX": "Uniswap V3",
            "Observations": _int(v3["observations"]),
            "Cells": _int(v3["cells"]),
            "Receipt found (%)": _pct(v3["receipt_found_share"]),
            "Transfer incidence (%)": _pct(v3["transfer_share"]),
            "Median route size": f"${_int(v3['median_route_usd'])}",
        },
        {
            "DEX": "Uniswap V4",
            "Observations": _int(v4["observations"]),
            "Cells": _int(v4["cells"]),
            "Receipt found (%)": _pct(v4["receipt_found_share"]),
            "Transfer incidence (%)": _pct(v4["transfer_share"]),
            "Median route size": f"${_int(v4['median_route_usd'])}",
        },
    ])
    if diff is not None:
        p_text = _p(diff["p"])
        test_text = f"t={_num(diff['t'], 2)}, p{p_text}" if p_text.startswith("<") else f"t={_num(diff['t'], 2)}, p={p_text}"
        out.loc[len(out)] = {
            "DEX": "V4 - V3",
            "Observations": "",
            "Cells": _int(diff["cells"]),
            "Receipt found (%)": "",
            "Transfer incidence (%)": _num(100 * diff["diff"], 1),
            "Median route size": test_text,
        }
    _write_table(
        out,
        "table_05_v4_settlement",
        "V4 flash accounting and physical intermediary-token transfers.",
        "tab:v4-settlement",
        note=(
            "Route units are matched by week, endpoint pair, and intermediate vehicle token. "
            "The outcome is whether the receipt contains an ERC-20 Transfer log for the "
            "intermediate token."
        ),
    )

    h = hetero.copy()
    app = pd.DataFrame({
        "Vehicle": h["vehicle"],
        "Cells": h["cells"].map(_int),
        "V3 transfer (%)": h["v3_mean"].map(_pct),
        "V4 transfer (%)": h["v4_mean"].map(_pct),
        "V4 - V3 (pp)": h["diff"].map(lambda x: _num(100 * x, 1)),
        "t": h["t"].map(lambda x: _num(x, 2)),
        "p": h["p"].map(_p),
    })
    _write_table(
        app,
        "table_a03_v4_vehicle_heterogeneity",
        "V4 settlement-transfer incidence by vehicle token.",
        "tab:v4-vehicle-heterogeneity",
    )


def build_table_v3_architecture() -> None:
    df = pd.read_csv(EMP / "v3_architecture_tests.csv")
    rows = []
    for r in df.itertuples(index=False):
        rows.append({
            "Token": str(r.name).replace("P4a V3 post: ", "").replace(" BridgeShare", ""),
            "Post-V3 shift (pp)": _num(100 * r.beta, 2),
            "SE (pp)": _num(100 * r.se, 2),
            "t": _num(r.t, 2),
            "p": _p(r.p),
            "N": _int(r.n),
        })
    _write_table(
        pd.DataFrame(rows),
        "table_a04_v3_architecture_screen",
        "Uniswap V3 launch-window screen for bridge-share changes.",
        "tab:v3-architecture-screen",
        note=(
            "This is a launch-window screen, not the final architecture design. The final "
            "claim should use pair-level direct-route feasibility and route costs."
        ),
    )


def build_figures() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _copy_if_exists(EMP / "bridge_share_timeseries.pdf", FIGURES / "figure_01_bridge_share_timeseries.pdf")
    _copy_if_exists(EMP / "lp_concentration_vehicle_timeseries.pdf", FIGURES / "figure_04_lp_concentration_timeseries.pdf")

    summary = pd.read_csv(EMP / "bridge_measure_summary_by_year.csv")
    y2026 = summary[summary["year"].eq(2026)].copy()
    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    for _, r in y2026.iterrows():
        ax.scatter(100 * r["VShare"], 100 * r["BridgeShare"], s=70)
        ax.annotate(r["token"], (100 * r["VShare"], 100 * r["BridgeShare"]), xytext=(5, 4), textcoords="offset points")
    lim = max(35, 100 * max(y2026["VShare"].max(), y2026["BridgeShare"].max()) * 1.08)
    ax.plot([0, lim], [0, lim], color="0.6", linewidth=1, linestyle="--")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("VShare, raw volume share (%)")
    ax.set_ylabel("BridgeShare, intermediate-route share (%)")
    ax.set_title("Vehicle use is not the same as endpoint volume")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure_02_bridge_vs_volume_share.pdf")
    plt.close(fig)

    route = pd.read_csv(EMP / "route_cost_panel_v2_summary.csv")
    weth = route[route["vehicle"].eq("WETH")].sort_values("trade_size_usd")
    x = np.arange(len(weth))
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    med = weth["median_advantage_bps"].to_numpy()
    p25 = weth["p25_advantage_bps"].to_numpy()
    p75 = weth["p75_advantage_bps"].to_numpy()
    ax.errorbar(x, med, yerr=[med - p25, p75 - med], fmt="o-", capsize=4, linewidth=1.5)
    ax.axhline(0, color="0.4", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels([f"${_int(v)}" for v in weth["trade_size_usd"]])
    ax.set_ylabel("WETH vehicle-route advantage (bp)")
    ax.set_xlabel("Trade size")
    ax.set_title("WETH route-cost advantage by trade size")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure_03_route_cost_advantage.pdf")
    plt.close(fig)

    events = pd.read_csv(EMP / "stress_common_support_events.csv")
    events["event_date"] = pd.to_datetime(events["event_date"])
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.bar(events["event_date"], 100 * events["weighted_effect"], width=8, color=np.where(events["weighted_effect"] < 0, "#4c78a8", "#f58518"))
    ax.axhline(0, color="0.3", linewidth=1)
    ax.set_ylabel("WETH-minus-stable effect (pp)")
    ax.set_xlabel("Stress event date")
    ax.set_title("Stress rotates vehicle use away from WETH")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure_05_stress_common_support.pdf")
    plt.close(fig)

    dex = pd.read_csv(EMP / "v4_settlement_dex_summary.csv")
    fig, ax = plt.subplots(figsize=(5.2, 4.0))
    labels = ["V3", "V4"]
    vals = [
        100 * float(dex[dex["dex"].eq("uniswap_v3")]["transfer_share"].iloc[0]),
        100 * float(dex[dex["dex"].eq("uniswap_v4")]["transfer_share"].iloc[0]),
    ]
    ax.bar(labels, vals, color=["#54a24b", "#e45756"])
    ax.set_ylim(0, 105)
    ax.set_ylabel("Intermediary-token transfer incidence (%)")
    ax.set_title("V4 partially virtualizes settlement")
    for i, v in enumerate(vals):
        ax.text(i, v + 2, f"{v:.1f}%", ha="center")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure_06_v4_settlement_transfer_incidence.pdf")
    plt.close(fig)


def write_manifest() -> None:
    text = """# Paper Exhibit Manifest

Generated by `scripts/build_paper_exhibits.py`.

## Main Tables

Table 1. Vehicle use and raw volume share by year.

Table 2. Direct routes and WETH vehicle-route execution costs.

Table 3. Liquidity concentration and persistence of vehicle use.

Table 4. Stress rotation in common-support vehicle-route opportunities.

Table 5. V4 flash accounting and physical intermediary-token transfers.

## Main Figures

Figure 1. BridgeShare of major vehicle candidates over time.

Figure 2. Vehicle use is not the same as endpoint volume.

Figure 3. WETH route-cost advantage by trade size.

Figure 4. Vehicle-linked liquidity concentration over time.

Figure 5. Stress rotates vehicle use away from WETH.

Figure 6. V4 partially virtualizes settlement.

## Appendix Tables

Table A1. Route-cost counterfactuals for all vehicle candidates.

Table A2. Largest WETH downside events used in the common-support design.

Table A3. V4 settlement-transfer incidence by vehicle token.

Table A4. Uniswap V3 launch-window screen for bridge-share changes.
"""
    MANIFEST.write_text(text, encoding="utf-8")


def main() -> int:
    _ensure_dirs()
    build_table_bridge_measurement()
    build_table_route_cost()
    build_table_liquidity_stickiness()
    build_table_stress()
    build_table_v4()
    build_table_v3_architecture()
    build_figures()
    write_manifest()
    print(f"wrote tables -> {TABLES}")
    print(f"wrote figures -> {FIGURES}")
    print(f"wrote manifest -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

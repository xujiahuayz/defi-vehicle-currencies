#!/usr/bin/env python3
"""Build paper-facing exhibit tables and figures from DVC empirical outputs.

This is intentionally a presentation-layer orchestrator. It does not refetch
data and does not rerun long counterfactual panels. New journal-facing exhibits
should live as one-script-per-exhibit units under scripts/tabulate, scripts/figure,
or scripts/diagram; this file only preserves the older bundle entry point.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paper_tables import (
    _int,
    _num,
    _p,
    _pct,
    _write_table,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"
MANIFEST = OUT / "exhibits" / "paper_exhibit_manifest.md"
TABULATE = ROOT / "scripts" / "tabulate"

VEHICLE_ORDER = ["WETH", "USDC", "USDT", "DAI", "WBTC"]


def _ensure_dirs() -> None:
    for path in (TABLES, FIGURES, MANIFEST.parent):
        path.mkdir(parents=True, exist_ok=True)


def _with_canonical_vol_share(df: pd.DataFrame) -> pd.DataFrame:
    """Accept old empirical pickles while exposing only the canonical name."""

    if "VolShare" in df.columns:
        return df
    if "VShare" in df.columns:
        return df.rename(columns={"VShare": "VolShare"})
    raise ValueError("Empirical summary has no VolShare column.")


def _copy_if_exists(src: Path, dest: Path) -> None:
    if src.exists():
        shutil.copy2(src, dest)


def build_table_bridge_measurement() -> None:
    summary = _with_canonical_vol_share(
        pd.read_pickle(EMP / "bridge_measure_summary_by_year.pkl")
    )
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
            row["2026 VolShare (%)"] = ""
            row["2026 PairCoverage (%)"] = ""
        else:
            r = g2026.iloc[0]
            row["2026 VolShare (%)"] = _pct(r["VolShare"])
            row["2026 PairCoverage (%)"] = _pct(r["PairCoverage"])
        rows.append(row)
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_02_bridge_measurement",
        "Vehicle use and raw volume share by year.",
        "tab:bridge-measurement",
        note=(
            "BridgeShare is the share of indirect route volume in which the token is an "
            "intermediate. VolShare is total token volume share and includes endpoint demand. "
            "PairCoverage is the share of active endpoint pairs for which the token appears "
            "as an intermediate."
        ),
    )


def build_table_sample_coverage() -> None:
    subprocess.run(
        [sys.executable, str(TABULATE / "render_sample_coverage.py")],
        check=True,
    )


def build_table_data_coverage() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "process" / "build_raw_data_inventory.py")],
        check=True,
    )
    subprocess.run(
        [sys.executable, str(TABULATE / "render_data_coverage.py")],
        check=True,
    )


def build_table_summary_statistics() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "process" / "build_observations_table.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "tabulate" / "render_summary_statistics.py")], check=True)


def build_table_route_cost() -> None:
    df = pd.read_pickle(EMP / "route_cost_panel_v2_summary.pkl")
    panel = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet", columns=[
        "vehicle_sym", "trade_size_usd", "direct_available", "vehicle_available",
        "direct_output_usd", "direct_cost_advantage",
    ])
    weth = df[df["vehicle"].eq("WETH")].sort_values("trade_size_usd")
    rows = []
    for r in weth.itertuples(index=False):
        g = panel[(panel["vehicle_sym"].eq("WETH")) & (panel["trade_size_usd"].eq(r.trade_size_usd))]
        high_quality = g[
            g["direct_available"]
            & g["vehicle_available"]
            & g["direct_cost_advantage"].notna()
            & ((g["direct_output_usd"] / g["trade_size_usd"]) >= 0.90)
        ]
        rows.append({
            "Trade size": f"${_int(r.trade_size_usd)}",
            "Direct available (%)": _pct(r.direct_available_share),
            "WETH route available (%)": _pct(r.vehicle_available_share),
            "No-direct rows": _int(r.no_direct_vehicle_available_rows),
            "Common rows": _int(r.both_available_rows),
            "Median direct cost advantage (fraction)": _num(r.direct_cost_advantage_median, 4),
            "HQ-direct median direct cost advantage (fraction)": _num(
                high_quality["direct_cost_advantage"].median(), 4
            ),
        })
    _write_table(
        pd.DataFrame(rows),
        "table_03_direct_cost_advantage",
        "Direct-route availability and WETH indirect-route cost comparison.",
        "tab:direct-cost-advantage",
        note=(
            "DirectCostAdvantage is direct-route output minus WETH indirect-route output, "
            "as a fraction of direct-route output. HQ-direct restricts common-support "
            "rows to cases where the direct route returns at least 90 percent of notional. "
            "The table emphasizes availability and thin-direct-route value, not a universal "
            "WETH cost advantage."
        ),
    )

    app = df.sort_values(["trade_size_usd", "vehicle"]).copy()
    out = pd.DataFrame({
        "Vehicle": app["vehicle"],
        "Trade size": app["trade_size_usd"].map(lambda x: f"${_int(x)}"),
        "Available (%)": app["vehicle_available_share"].map(_pct),
        "Beats direct (%)": app["vehicle_beats_direct_share"].map(_pct),
        "Median direct cost advantage (fraction)": app["direct_cost_advantage_median"].map(
            lambda x: _num(x, 4)
        ),
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


def build_table_stress() -> None:
    common = pd.read_pickle(EMP / "stress_common_support_summary.pkl")
    events = pd.read_pickle(EMP / "stress_common_support_events.pkl")
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
        "table_05_stress_rotation",
        "Stress rotation in common-support indirect-route opportunities.",
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


def build_table_v3_architecture() -> None:
    df = pd.read_pickle(EMP / "v3_architecture_tests.pkl")
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


def build_figure_bridge_vs_volume_share() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summary = _with_canonical_vol_share(
        pd.read_pickle(EMP / "bridge_measure_summary_by_year.pkl")
    )
    y2026 = summary[summary["year"].eq(2026)].copy()
    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    for _, r in y2026.iterrows():
        ax.scatter(100 * r["VolShare"], 100 * r["BridgeShare"], s=70)
        ax.annotate(
            r["token"],
            (100 * r["VolShare"], 100 * r["BridgeShare"]),
            xytext=(5, 4),
            textcoords="offset points",
        )
    lim = max(35, 100 * max(y2026["VolShare"].max(), y2026["BridgeShare"].max()) * 1.08)
    ax.plot([0, lim], [0, lim], color="0.6", linewidth=1, linestyle="--")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("VolShare, raw volume share (%)")
    ax.set_ylabel("BridgeShare, intermediate-route share (%)")
    ax.set_title("Vehicle use is not the same as endpoint volume")
    fig.tight_layout()
    fig.savefig(FIGURES / "bridge_vs_volume_share.pdf")
    plt.close(fig)


def build_figures() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _copy_if_exists(EMP / "bridge_share_timeseries.pdf", FIGURES / "bridge_share_timeseries.pdf")
    _copy_if_exists(EMP / "lp_concentration_vehicle_timeseries.pdf", FIGURES / "lp_concentration_timeseries.pdf")
    build_figure_bridge_vs_volume_share()

    route = pd.read_pickle(EMP / "route_cost_panel_v2_summary.pkl")
    weth = route[route["vehicle"].eq("WETH")].sort_values("trade_size_usd")
    x = np.arange(len(weth))
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    med = weth["direct_cost_advantage_median"].to_numpy()
    p25 = weth["direct_cost_advantage_p25"].to_numpy()
    p75 = weth["direct_cost_advantage_p75"].to_numpy()
    ax.errorbar(x, med, yerr=[med - p25, p75 - med], fmt="o-", capsize=4, linewidth=1.5)
    ax.axhline(0, color="0.4", linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels([f"${_int(v)}" for v in weth["trade_size_usd"]])
    ax.set_ylabel("Direct cost advantage (fraction)")
    ax.set_xlabel("Trade size")
    ax.set_title("Direct cost advantage against WETH route")
    fig.tight_layout()
    fig.savefig(FIGURES / "direct_cost_advantage.pdf")
    plt.close(fig)

    events = pd.read_pickle(EMP / "stress_common_support_events.pkl")
    events["event_date"] = pd.to_datetime(events["event_date"])
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.bar(events["event_date"], 100 * events["weighted_effect"], width=8, color=np.where(events["weighted_effect"] < 0, "#4c78a8", "#f58518"))
    ax.axhline(0, color="0.3", linewidth=1)
    ax.set_ylabel("WETH-minus-stable effect (pp)")
    ax.set_xlabel("Stress event date")
    ax.set_title("Stress rotates vehicle use away from WETH")
    fig.tight_layout()
    fig.savefig(FIGURES / "stress_common_support.pdf")
    plt.close(fig)

def write_manifest() -> None:
    text = """# Paper Exhibit Manifest

Generated by `scripts/build_paper_exhibits.py`.

## Main Tables

sample_coverage. Sample coverage for empirical exhibits.

data_coverage. Raw source-record coverage and observation counts by AMM.

summary_statistics. Summary statistics for main empirical variables.

bridge_measurement. Vehicle use and raw volume share by year.

direct_cost_advantage. Direct routes and WETH indirect-route execution costs.

stress_rotation. Stress rotation in common-support indirect-route opportunities.

## Main Figures

Figure 1. BridgeShare of major vehicle candidates over time.

Figure 2. Vehicle use is not the same as endpoint volume.

Figure 3. Direct cost advantage against the WETH route by trade size.

Figure 4. Vehicle-linked liquidity concentration over time.

Figure 5. Stress rotates vehicle use away from WETH.

## Appendix Tables

Table A1. Route-cost counterfactuals for all vehicle candidates.

Table A2. Largest WETH downside events used in the common-support design.

Table A4. Uniswap V3 launch-window screen for bridge-share changes.

## Robustness Tables

measurement_robustness. Vehicle-use measurement robustness.

stress_robustness. Stress-rotation robustness to event weighting and subsamples.

route_cost_robustness. Route-cost robustness to direct-route quality filters.

"""
    MANIFEST.write_text(text, encoding="utf-8")


def main() -> int:
    _ensure_dirs()
    build_table_data_coverage()
    build_table_sample_coverage()
    build_table_bridge_measurement()
    build_table_summary_statistics()
    build_table_route_cost()
    build_table_stress()
    build_table_v3_architecture()
    build_figures()
    write_manifest()
    print(f"wrote tables -> {TABLES}")
    print(f"wrote figures -> {FIGURES}")
    print(f"wrote manifest -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

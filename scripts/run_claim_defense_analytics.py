#!/usr/bin/env python3
"""Additional claim-defense analytics before manuscript drafting.

This script intentionally stays close to already-built panels:
1. stress event-window sensitivity and placebo dates;
2. P1 route-cost decomposition into availability, thin-direct, and common support.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _pct, _write_table  # noqa: E402


def _load_module(name: str, file: str):
    path = SCRIPTS / file
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stress_window_and_placebo() -> pd.DataFrame:
    weekly = _load_module("stress_weekly", "run_stress_weekly_common_support.py")
    empirical = _load_module("dvc_empirical", "run_empirical_proposition_tests.py")
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "weth_price"])
    px = bridge.dropna().drop_duplicates("date").sort_values("date").copy()
    px["date"] = pd.to_datetime(px["date"])
    px["weth_ret"] = np.log(px["weth_price"]).diff()
    px.loc[px["weth_ret"].abs() > 0.5, "weth_ret"] = np.nan
    px["downside_stress"] = (-px["weth_ret"]).clip(lower=0)

    events = (
        px[px["downside_stress"].ge(0.08)]
        .nlargest(20, "downside_stress")
        [["date", "downside_stress"]]
        .copy()
    )
    placebo = events.copy()
    placebo["date"] = placebo["date"] - pd.Timedelta(days=60)
    placebo = placebo.merge(
        px[["date", "downside_stress"]].rename(columns={"downside_stress": "placebo_stress"}),
        on="date",
        how="inner",
    )
    placebo = placebo[placebo["placebo_stress"].lt(0.02)].head(len(events))

    all_dates: set[str] = set()
    for d in pd.concat([events["date"], placebo["date"]], ignore_index=True):
        for b in range(1, 29):
            all_dates.add(weekly._stamp(d - pd.Timedelta(days=b)))
        for k in range(7):
            all_dates.add(weekly._stamp(d + pd.Timedelta(days=k)))
    panel = weekly._build_panel(all_dates, empirical)

    rows = []
    for sample_name, event_frame in [("stress", events), ("placebo", placebo.rename(columns={"placebo_stress": "downside_stress"}))]:
        for event_days in [1, 2, 3, 7]:
            effects = []
            n_pairs = []
            for ev in event_frame.itertuples(index=False):
                d = pd.Timestamp(ev.date)
                event = weekly._window_gap(panel, d, event_days).rename(
                    columns={"gap": "event_gap", "total": "event_total", "days": "event_days_seen"}
                )
                base = weekly._window_gap(panel, d - pd.Timedelta(days=28), 28).rename(
                    columns={"gap": "baseline_gap", "total": "baseline_total", "days": "baseline_days_seen"}
                )
                comp = event.merge(base, on="pair", how="inner")
                comp = comp[comp["baseline_days_seen"].ge(7)]
                if comp.empty:
                    continue
                comp["effect"] = comp["event_gap"] - comp["baseline_gap"]
                effects.append(float(np.average(comp["effect"], weights=comp["event_total"].clip(lower=1e-9))))
                n_pairs.append(len(comp))
            arr = np.array(effects, dtype=float)
            t, p = stats.ttest_1samp(arr, 0.0) if len(arr) > 2 else (math.nan, math.nan)
            rows.append({
                "Sample": sample_name,
                "Event window": f"{event_days} day" if event_days == 1 else f"{event_days} days",
                "Events": _int(len(arr)),
                "Mean pairs": _int(np.mean(n_pairs) if n_pairs else math.nan),
                "Effect (pp)": _num(100 * arr.mean(), 2) if len(arr) else "",
                "SE (pp)": _num(100 * stats.sem(arr), 2) if len(arr) > 1 else "",
                "t": _num(t, 2),
                "p": _p(p),
                "Negative share (%)": _pct(float(np.mean(arr < 0)) if len(arr) else math.nan),
            })
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "stress_window_placebo.csv", index=False)
    _write_table(
        out,
        "table_r11_stress_window_placebo",
        "Stress-rotation event-window and placebo checks.",
        "tab:stress-window-placebo",
        note=(
            "Effects are WETH-minus-stable BridgeShare changes within common endpoint-pair "
            "sets relative to the prior 28 days. Placebo dates move each stress event 60 "
            "days earlier and keep only low-stress placebo dates."
        ),
    )
    return out


def route_cost_decomposition() -> pd.DataFrame:
    panel = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet")
    d = panel[panel["vehicle_sym"].eq("WETH")].copy()
    d["direct_quality"] = d["direct_output_usd"] / d["trade_size_usd"]
    d["adv_bps"] = d["vehicle_route_advantage"] * 10_000.0
    rows = []
    for size, g in d.groupby("trade_size_usd"):
        both = g[g["direct_available"] & g["vehicle_available"] & g["adv_bps"].notna()].copy()
        thin = both[both["direct_quality"].lt(0.995)]
        high = both[both["direct_quality"].ge(0.995)]
        no_direct = g[(~g["direct_available"]) & g["vehicle_available"]]
        grouped = (
            both.assign(pair_day=both["date"].astype(str) + "|" + both["src"].astype(str) + "|" + both["tgt"].astype(str))
            .groupby("pair_day", as_index=False)["adv_bps"]
            .mean()
        )
        adv = grouped["adv_bps"].clip(lower=-100_000, upper=100_000).to_numpy(float)
        t, p = stats.ttest_1samp(adv, 0.0) if len(adv) > 2 else (math.nan, math.nan)
        rows.append({
            "Trade size": f"${int(size):,}",
            "Rows": _int(len(g)),
            "Direct available (%)": _pct(g["direct_available"].mean()),
            "WETH route available (%)": _pct(g["vehicle_available"].mean()),
            "No-direct, WETH-available rows": _int(len(no_direct)),
            "Common-support rows": _int(len(both)),
            "Median common-support advantage (bp)": _num(both["adv_bps"].median(), 2),
            "Median thin-direct advantage (bp)": _num(thin["adv_bps"].median(), 2),
            "Median high-quality-direct advantage (bp)": _num(high["adv_bps"].median(), 2),
            "Pair-day t": _num(t, 2),
            "p": _p(p),
        })
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "route_cost_decomposition.csv", index=False)
    _write_table(
        out,
        "table_r12_route_cost_decomposition",
        "Route-cost value decomposition for WETH vehicle routes.",
        "tab:route-cost-decomposition",
        note=(
            "The table separates route availability, missing-direct-route support, thin-direct "
            "markets, and common-support price improvement. High-quality direct routes are "
            "rows where direct output is at least 99.5 percent of notional."
        ),
    )
    return out


def main() -> int:
    stress_window_and_placebo()
    route_cost_decomposition()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

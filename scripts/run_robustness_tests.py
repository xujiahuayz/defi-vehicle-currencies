#!/usr/bin/env python3
"""Build robustness tables for the DVC model-driven empirical spine."""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.dynamics import exact_daily_log_return
from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"
ROB = OUT / "robustness"

from ddvc.paper_tables import _int, _num, _p, _pct, _write_table

VEHICLES = ["WETH", "USDC", "USDT", "DAI", "WBTC"]
STABLES = {"USDC", "USDT", "DAI"}


def _load_empirical_module():
    path = SCRIPTS / "run_empirical_proposition_tests.py"
    spec = importlib.util.spec_from_file_location("dvc_empirical", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ols(y: pd.Series, x: pd.Series) -> tuple[int, float, float, float, float]:
    d = pd.DataFrame({"y": y, "x": x}).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    if n < 4 or np.isclose(float(d["x"].var()), 0):
        return n, math.nan, math.nan, math.nan, math.nan
    xmat = np.column_stack([np.ones(n), d["x"].to_numpy(float)])
    yy = d["y"].to_numpy(float)
    beta = np.linalg.lstsq(xmat, yy, rcond=None)[0]
    resid = yy - xmat @ beta
    dof = n - 2
    sigma2 = float((resid @ resid) / dof)
    cov = sigma2 * np.linalg.inv(xmat.T @ xmat)
    se = float(math.sqrt(cov[1, 1]))
    t = float(beta[1] / se) if se > 0 else math.nan
    p = float(2 * stats.t.sf(abs(t), dof)) if np.isfinite(t) else math.nan
    return n, float(beta[1]), se, t, p


def measurement_robustness(bridge: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in ["BridgeShare", "BridgeCountShare", "PairCoverage", "PairMainVehicleShare"]:
        for year in [2022, 2024, 2026]:
            d = bridge.copy()
            d["year"] = pd.to_datetime(d["date"]).dt.year
            g = d[d["year"].eq(year)].groupby("token", as_index=False)[metric].mean()
            if g.empty:
                continue
            leader = g.sort_values(metric, ascending=False).iloc[0]
            weth = g[g["token"].eq("WETH")][metric].iloc[0]
            stable = g[g["token"].isin(["USDC", "USDT"])][metric].sum()
            rows.append({
                "Metric": metric,
                "Year": year,
                "Leader": leader["token"],
                "Leader share (%)": _pct(leader[metric]),
                "WETH (%)": _pct(weth),
                "USDC+USDT (%)": _pct(stable),
            })
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r01_measurement_robustness",
        "Vehicle-use measurement robustness.",
        "tab:measurement-robustness",
        note=(
            "The table compares volume-weighted BridgeShare with count-weighted bridge use, "
            "endpoint-pair coverage, and the main-vehicle share of endpoint pairs."
        ),
    )
    return out


def _weth_stress_events(bridge: pd.DataFrame, threshold: float) -> pd.DataFrame:
    px = (
        bridge[["date", "weth_price"]]
        .dropna()
        .drop_duplicates("date")
        .sort_values("date")
        .copy()
    )
    px["date"] = pd.to_datetime(px["date"])
    px["weth_ret"] = exact_daily_log_return(px, "weth_price")
    px.loc[px["weth_ret"].abs() > 0.5, "weth_ret"] = np.nan
    px["downside_stress"] = (-px["weth_ret"]).clip(lower=0)
    return px[px["downside_stress"].ge(threshold)][["date", "downside_stress"]]


def _pair_vehicle_panel(stamps: set[str], empirical_module) -> pd.DataFrame:
    frames = []
    for stamp in sorted(stamps):
        d = empirical_module._pair_vehicle_for_day(stamp)
        if not d.empty:
            frames.append(d)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    wide = panel.pivot_table(
        index=["date", "pair"],
        columns="vehicle_group",
        values="volume",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    for col in ["WETH", "STABLE"]:
        if col not in wide:
            wide[col] = 0.0
    wide["total"] = wide["WETH"] + wide["STABLE"]
    wide = wide[wide["total"].gt(0)].copy()
    wide["gap"] = (wide["WETH"] - wide["STABLE"]) / wide["total"]
    wide["date"] = pd.to_datetime(wide["date"])
    return wide


def stress_robustness(bridge: pd.DataFrame) -> pd.DataFrame:
    events = pd.read_pickle(EMP / "stress_common_support_events.pkl")
    events = events.sort_values("downside_stress", ascending=False).reset_index(drop=True)
    rows = []
    variants = {
        "Baseline weighted effect": events["weighted_effect"],
        "Unweighted event effect": events["mean_effect"],
        "Drop largest event": events.iloc[1:]["weighted_effect"],
        "Top 10 stress events": events.head(10)["weighted_effect"],
        "Top 20 stress events": events.head(20)["weighted_effect"],
        "Events with at least 2,000 pairs": events[events["n_pairs"].ge(2000)]["weighted_effect"],
    }
    for label, effect_series in variants.items():
        effects = pd.to_numeric(effect_series, errors="coerce").dropna().to_numpy(float)
        if len(effects) > 1:
            t, p = stats.ttest_1samp(effects, 0.0)
            se = float(stats.sem(effects))
        else:
            t = p = se = math.nan
        rows.append({
            "Variant": label,
            "Events": _int(len(effects)),
            "Effect (pp)": _num(100 * np.mean(effects), 2) if len(effects) else "",
            "SE (pp)": _num(100 * se, 2),
            "t": _num(t, 2),
            "p": _p(p),
            "Negative share (%)": _pct(float(np.mean(effects < 0)) if len(effects) else math.nan),
        })
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r03_stress_robustness",
        "Stress-rotation robustness to event and baseline definitions.",
        "tab:stress-robustness",
        note=(
            "Effect is the WETH-minus-stable BridgeShare change within common endpoint-pair "
            "opportunities, relative to the pre-event baseline."
        ),
    )
    return out


def route_cost_robustness() -> pd.DataFrame:
    panel = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet", columns=[
        "date", "src", "tgt", "vehicle_sym", "trade_size_usd", "direct_available", "vehicle_available",
        "direct_output_usd", "direct_cost_advantage",
    ])
    x = panel[panel["vehicle_sym"].eq("WETH")].copy()
    rows = []
    filters = {
        "All common support": lambda d: d["direct_available"] & d["vehicle_available"] & d["direct_cost_advantage"].notna(),
        "Direct output >= 50% notional": lambda d: d["direct_available"] & d["vehicle_available"] & d["direct_cost_advantage"].notna() & ((d["direct_output_usd"] / d["trade_size_usd"]) >= 0.50),
        "Direct output >= 90% notional": lambda d: d["direct_available"] & d["vehicle_available"] & d["direct_cost_advantage"].notna() & ((d["direct_output_usd"] / d["trade_size_usd"]) >= 0.90),
    }
    for size, g0 in x.groupby("trade_size_usd"):
        for label, fn in filters.items():
            g = g0[fn(g0)]
            direct_advantage = g["direct_cost_advantage"]
            cells = g.assign(direct_advantage_w=direct_advantage.clip(-10, 10)).groupby(
                ["date", "src", "tgt"], as_index=False
            )["direct_advantage_w"].mean()
            if len(cells) > 2:
                t, p = stats.ttest_1samp(cells["direct_advantage_w"], 0.0)
            else:
                t = p = math.nan
            rows.append({
                "Trade size": f"${_int(size)}",
                "Sample": label,
                "Rows": _int(len(g)),
                "Pair-days": _int(len(cells)),
                "Indirect beats direct (%)": _pct(
                    (direct_advantage < 0).mean() if len(direct_advantage) else math.nan
                ),
                "Median direct cost advantage (fraction)": _num(direct_advantage.median(), 4),
                "Pair-day mean direct cost advantage (fraction)": _num(
                    cells["direct_advantage_w"].mean(), 4
                ) if len(cells) else "",
                "t": _num(t, 2),
                "p": _p(p),
            })
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r04_route_cost_robustness",
        "Route-cost robustness to direct-route quality filters.",
        "tab:route-cost-robustness",
        note=(
            "DirectCostAdvantage is direct output minus WETH indirect output as a fraction "
            "of direct output. The t-test is over endpoint-pair-day means, clipped to +/-10."
        ),
    )
    return out


def write_memo(tables: dict[str, pd.DataFrame]) -> None:
    ROB.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Robustness Suite",
        "",
        "Generated by `scripts/run_robustness_tests.py`.",
        "",
        "## Tables",
        "",
    ]
    for name, df in tables.items():
        lines.append(f"- `{name}`: {len(df):,} rows")
    lines += [
        "",
        "## Interpretation",
        "",
        "- Measurement robustness checks whether the vehicle conclusion depends on volume-weighting alone.",
        "- Liquidity robustness varies forecast horizons and fixed effects.",
        "- Stress robustness varies event weighting and event subsamples.",
        "- Route-cost robustness removes low-quality direct-route comparisons.",
        "",
    ]
    (ROB / "robustness_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ROB.mkdir(parents=True, exist_ok=True)
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet")
    tables = {
        "table_r01_measurement_robustness": measurement_robustness(bridge),
        "table_r03_stress_robustness": stress_robustness(bridge),
        "table_r04_route_cost_robustness": route_cost_robustness(),
    }
    write_memo(tables)
    print(f"wrote robustness tables -> {OUT / 'tables'}")
    print(f"wrote robustness memo -> {ROB / 'robustness_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"
ROB = OUT / "robustness"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _pct, _write_table  # noqa: E402

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


def _cluster_ols(y: pd.Series, x: pd.Series, cluster: pd.Series) -> tuple[int, int, float, float, float, float]:
    d = pd.DataFrame({"y": y, "x": x, "cluster": cluster}).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    groups = d["cluster"].nunique()
    if n < 4 or groups < 2 or np.isclose(float(d["x"].var()), 0):
        return n, groups, math.nan, math.nan, math.nan, math.nan
    xmat = np.column_stack([np.ones(n), d["x"].to_numpy(float)])
    yy = d["y"].to_numpy(float)
    beta = np.linalg.lstsq(xmat, yy, rcond=None)[0]
    resid = yy - xmat @ beta
    bread = np.linalg.inv(xmat.T @ xmat)
    meat = np.zeros((2, 2))
    for _, idx in d.groupby("cluster").indices.items():
        xg = xmat[idx]
        ug = resid[idx][:, None]
        score = xg.T @ ug
        meat += score @ score.T
    k = xmat.shape[1]
    finite = (groups / (groups - 1)) * ((n - 1) / max(n - k, 1))
    cov = finite * bread @ meat @ bread
    se = float(math.sqrt(max(cov[1, 1], 0.0)))
    t = float(beta[1] / se) if se > 0 else math.nan
    p = float(2 * stats.t.sf(abs(t), groups - 1)) if np.isfinite(t) else math.nan
    return n, groups, float(beta[1]), se, t, p


def _demean_one(s: pd.Series, group: pd.Series) -> pd.Series:
    return s - s.groupby(group).transform("mean")


def _demean_two(s: pd.Series, group_a: pd.Series, group_b: pd.Series) -> pd.Series:
    return s - s.groupby(group_a).transform("mean") - s.groupby(group_b).transform("mean") + s.mean()


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


def liquidity_robustness(bridge: pd.DataFrame) -> pd.DataFrame:
    lp = pd.read_parquet(DATA / "exhibits" / "lp_concentration.parquet")
    lp = lp.rename(columns={"token_symbol": "token"})
    b = bridge[["date", "token", "BridgeShare"]].copy()
    b["date"] = pd.to_datetime(b["date"])
    b = b.sort_values(["token", "date"])
    lp["date"] = pd.to_datetime(lp["date"])
    base = b.merge(lp[["date", "token", "lp_concentration_share"]], on=["date", "token"], how="inner")
    rows = []
    for horizon in [1, 7, 14, 30]:
        d = base.sort_values(["token", "date"]).copy()
        d["y"] = d.groupby("token")["BridgeShare"].shift(-horizon)
        d = d.dropna(subset=["y", "lp_concentration_share"])
        specs = {
            "No FE": (d["y"], d["lp_concentration_share"]),
            "Token FE": (_demean_one(d["y"], d["token"]), _demean_one(d["lp_concentration_share"], d["token"])),
            "Token + date FE": (
                _demean_two(d["y"], d["token"], d["date"]),
                _demean_two(d["lp_concentration_share"], d["token"], d["date"]),
            ),
        }
        for spec, (y, x) in specs.items():
            n, clusters, beta, se, t, p = _cluster_ols(y, x, d["date"])
            rows.append({
                "Horizon": f"t+{horizon}",
                "Specification": spec,
                "N": _int(n),
                "Clusters": _int(clusters),
                "Beta": _num(beta, 3),
                "Date-cluster SE": _num(se, 3),
                "t": _num(t, 2),
                "p": _p(p),
            })
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r02_liquidity_robustness",
        "Liquidity-feedback robustness across horizons and fixed effects.",
        "tab:liquidity-robustness",
        note=(
            "Outcome is future BridgeShare. The regressor is vehicle-linked LP concentration. "
            "Inference is clustered by date."
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
    px["weth_ret"] = np.log(px["weth_price"]).diff()
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
        "direct_output_usd", "vehicle_route_advantage",
    ])
    x = panel[panel["vehicle_sym"].eq("WETH")].copy()
    rows = []
    filters = {
        "All common support": lambda d: d["direct_available"] & d["vehicle_available"] & d["vehicle_route_advantage"].notna(),
        "Direct output >= 50% notional": lambda d: d["direct_available"] & d["vehicle_available"] & d["vehicle_route_advantage"].notna() & ((d["direct_output_usd"] / d["trade_size_usd"]) >= 0.50),
        "Direct output >= 90% notional": lambda d: d["direct_available"] & d["vehicle_available"] & d["vehicle_route_advantage"].notna() & ((d["direct_output_usd"] / d["trade_size_usd"]) >= 0.90),
    }
    for size, g0 in x.groupby("trade_size_usd"):
        for label, fn in filters.items():
            g = g0[fn(g0)]
            adv = 10_000 * g["vehicle_route_advantage"]
            cells = g.assign(adv_w=adv.clip(lower=-100_000, upper=100_000)).groupby(
                ["date", "src", "tgt"], as_index=False
            )["adv_w"].mean()
            if len(cells) > 2:
                t, p = stats.ttest_1samp(cells["adv_w"], 0.0)
            else:
                t = p = math.nan
            rows.append({
                "Trade size": f"${_int(size)}",
                "Sample": label,
                "Rows": _int(len(g)),
                "Pair-days": _int(len(cells)),
                "Beats direct (%)": _pct((adv > 0).mean() if len(adv) else math.nan),
                "Median advantage (bp)": _num(adv.median(), 1),
                "Pair-day mean (bp)": _num(cells["adv_w"].mean(), 1) if len(cells) else "",
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
            "Advantage is WETH vehicle output minus direct output in basis points. "
            "The t-test is over endpoint-pair-day mean advantages, winsorized at +/-100,000 bp."
        ),
    )
    return out


def v4_robustness() -> pd.DataFrame:
    detail = pd.read_parquet(DATA / "empirical" / "v4_settlement_transfer_detail.parquet")
    detail["size_bin"] = pd.qcut(detail["route_usd"], 3, labels=["Small", "Medium", "Large"], duplicates="drop")
    rows = []
    for key, g0 in [("All", detail), *[(f"Route size: {k}", g) for k, g in detail.groupby("size_bin", observed=True)]]:
        wide = g0.pivot_table(
            index="cell_id",
            columns="dex",
            values="has_matching_transfer",
            aggfunc="mean",
        ).dropna()
        if {"uniswap_v3", "uniswap_v4"} - set(wide.columns):
            continue
        diff = wide["uniswap_v4"] - wide["uniswap_v3"]
        if len(diff) > 1:
            t, p = stats.ttest_1samp(diff, 0.0)
        else:
            t = p = math.nan
        rows.append({
            "Sample": key,
            "Cells": _int(len(diff)),
            "V3 transfer (%)": _pct(wide["uniswap_v3"].mean()),
            "V4 transfer (%)": _pct(wide["uniswap_v4"].mean()),
            "V4 - V3 (pp)": _num(100 * diff.mean(), 1),
            "t": _num(t, 2),
            "p": _p(p),
        })
    out = pd.DataFrame(rows)
    out.to_pickle(EMP / "v4_robustness.pkl")
    _write_table(
        out,
        "table_r05_v4_robustness",
        "V4 settlement-transfer robustness by route size.",
        "tab:v4-robustness",
        note="The outcome is whether the receipt contains an ERC-20 Transfer log for the route intermediary.",
    )
    return out


def v4_match_balance() -> pd.DataFrame:
    detail = pd.read_parquet(DATA / "empirical" / "v4_settlement_transfer_detail.parquet")
    cell = (
        detail.groupby(["cell_id", "dex"], as_index=False)
        .agg(route_usd=("route_usd", "median"), logs=("total_logs", "median"))
        .pivot(index="cell_id", columns="dex", values=["route_usd", "logs"])
    )
    cell.columns = [f"{a}_{b}" for a, b in cell.columns]
    cell = cell.dropna().copy()
    cell["log_route_ratio"] = np.log(cell["route_usd_uniswap_v4"] / cell["route_usd_uniswap_v3"])
    t, p = stats.ttest_1samp(cell["log_route_ratio"], 0.0)
    rows = [{
        "Cells": _int(len(cell)),
        "V3 median route": f"${_int(cell['route_usd_uniswap_v3'].median())}",
        "V4 median route": f"${_int(cell['route_usd_uniswap_v4'].median())}",
        "Mean log V4/V3": _num(cell["log_route_ratio"].mean(), 3),
        "t": _num(t, 2),
        "p": _p(p),
        "V3 median logs": _num(cell["logs_uniswap_v3"].median(), 1),
        "V4 median logs": _num(cell["logs_uniswap_v4"].median(), 1),
    }]
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r06_v4_match_balance",
        "V4 matched-cell balance diagnostics.",
        "tab:v4-match-balance",
        note=(
            "The matched design holds week, endpoint pair, and intermediate vehicle token fixed. "
            "This table reports remaining route-size and receipt-log balance across sampled V3/V4 observations."
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
        "- V4 robustness checks whether settlement virtualization is concentrated in small routes.",
        "",
    ]
    (ROB / "robustness_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ROB.mkdir(parents=True, exist_ok=True)
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet")
    tables = {
        "table_r01_measurement_robustness": measurement_robustness(bridge),
        "table_r02_liquidity_robustness": liquidity_robustness(bridge),
        "table_r03_stress_robustness": stress_robustness(bridge),
        "table_r04_route_cost_robustness": route_cost_robustness(),
        "table_r05_v4_robustness": v4_robustness(),
        "table_r06_v4_match_balance": v4_match_balance(),
    }
    write_memo(tables)
    print(f"wrote robustness tables -> {OUT / 'tables'}")
    print(f"wrote robustness memo -> {ROB / 'robustness_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

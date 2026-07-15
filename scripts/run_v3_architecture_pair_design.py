#!/usr/bin/env python3
"""Pair-level V3 architecture design.

This upgrades the aggregate V3 launch screen by using the route-cost panel
around the May 2021 Uniswap V3 launch and comparing the same endpoint pairs
before and after the concentrated-liquidity architecture becomes available.
"""
from __future__ import annotations

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


def _cluster_pair_ols(y: pd.Series, x: pd.Series, cluster: pd.Series) -> tuple[int, int, float, float, float, float]:
    d = pd.DataFrame({"y": y, "x": x, "cluster": cluster}).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    c = d["cluster"].nunique()
    if n < 10 or c < 2 or np.isclose(float(d["x"].var()), 0):
        return n, c, math.nan, math.nan, math.nan, math.nan
    xmat = np.column_stack([np.ones(n), d["x"].to_numpy(float)])
    yy = d["y"].to_numpy(float)
    beta = np.linalg.lstsq(xmat, yy, rcond=None)[0]
    resid = yy - xmat @ beta
    bread = np.linalg.inv(xmat.T @ xmat)
    meat = np.zeros((2, 2))
    for _, idx in d.groupby("cluster").indices.items():
        score = xmat[idx].T @ resid[idx][:, None]
        meat += score @ score.T
    finite = (c / (c - 1)) * ((n - 1) / max(n - xmat.shape[1], 1))
    cov = finite * bread @ meat @ bread
    se = float(math.sqrt(max(cov[1, 1], 0.0)))
    t = float(beta[1] / se) if se > 0 else math.nan
    p = float(2 * stats.t.sf(abs(t), c - 1)) if np.isfinite(t) else math.nan
    return n, c, float(beta[1]), se, t, p


def _demean(s: pd.Series, g: pd.Series) -> pd.Series:
    return s - s.groupby(g).transform("mean")


def run() -> pd.DataFrame:
    launch = pd.Timestamp("2021-05-05")
    panel = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet")
    d = panel[panel["vehicle_sym"].eq("WETH")].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d["date"] >= launch - pd.Timedelta(days=365)) & (d["date"] <= launch + pd.Timedelta(days=365))]
    d["pair"] = d["src"].astype(str) + "->" + d["tgt"].astype(str)
    d["post_v3"] = (d["date"] >= launch).astype(float)
    d["adv_bps"] = d["vehicle_route_advantage"] * 10_000.0
    d["no_direct_weth_available"] = (~d["direct_available"]) & d["vehicle_available"]
    d["direct_quality"] = d["direct_output_usd"] / d["trade_size_usd"]
    pre_pairs = set(d.loc[d["post_v3"].eq(0), "pair"])
    post_pairs = set(d.loc[d["post_v3"].eq(1), "pair"])
    d = d[d["pair"].isin(pre_pairs & post_pairs)].copy()

    rows = []
    outcomes = {
        "Direct-route availability": d["direct_available"].astype(float),
        "WETH-route availability": d["vehicle_available"].astype(float),
        "No-direct WETH availability": d["no_direct_weth_available"].astype(float),
        "Direct-route quality": d["direct_quality"].replace([np.inf, -np.inf], np.nan).clip(lower=0, upper=2),
        "Common-support WETH advantage": d["adv_bps"].where(d["direct_available"] & d["vehicle_available"]).clip(-100_000, 100_000),
    }
    for name, y_raw in outcomes.items():
        y = _demean(y_raw, d["pair"])
        x = _demean(d["post_v3"], d["pair"])
        n, clusters, beta, se, t, p = _cluster_pair_ols(y, x, d["pair"])
        scale = 100 if "availability" in name.lower() else 1
        rows.append({
            "Outcome": name,
            "Rows": _int(n),
            "Pairs": _int(clusters),
            "Post-V3 effect": _num(scale * beta, 2),
            "SE": _num(scale * se, 2),
            "t": _num(t, 2),
            "p": _p(p),
            "Units": "pp" if "availability" in name.lower() else "bp/ratio",
        })

    summary = d.groupby("post_v3").agg(
        rows=("pair", "size"),
        pairs=("pair", "nunique"),
        direct_available=("direct_available", "mean"),
        vehicle_available=("vehicle_available", "mean"),
        no_direct_weth=("no_direct_weth_available", "mean"),
    ).reset_index()
    summary.to_pickle(EMP / "v3_pair_architecture_summary.pkl")
    out = pd.DataFrame(rows)
    out.to_pickle(EMP / "v3_pair_architecture_tests.pkl")
    _write_table(
        out,
        "table_r14_v3_pair_architecture",
        "Pair-level route feasibility around the Uniswap V3 launch.",
        "tab:v3-pair-architecture",
        note=(
            "The sample is the balanced set of endpoint pairs observed before and after the "
            "May 5, 2021 Uniswap V3 launch. Specifications partial out endpoint-pair fixed "
            "effects and cluster by endpoint pair."
        ),
    )
    print(f"wrote {len(out)} V3 architecture rows")
    return out


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

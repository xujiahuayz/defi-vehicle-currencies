#!/usr/bin/env python3
"""Pair-level V3 architecture design.

This upgrades the aggregate V3 launch screen by using the route-cost panel
around the May 2021 Uniswap V3 launch and comparing the same endpoint pairs
before and after the concentrated-liquidity architecture becomes available.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

from ddvc.paper_tables import _int, _num, _p, _pct, _write_table


def run() -> pd.DataFrame:
    launch = pd.Timestamp("2021-05-05")
    panel = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet")
    d = panel[panel["vehicle_sym"].eq("WETH")].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d["date"] >= launch - pd.Timedelta(days=365)) & (d["date"] <= launch + pd.Timedelta(days=365))]
    d["pair"] = d["src"].astype(str) + "->" + d["tgt"].astype(str)
    d["post_v3"] = (d["date"] >= launch).astype(float)
    d["direct_cost_advantage_w"] = d["direct_cost_advantage"].clip(-10, 10)
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
        "Direct cost advantage against WETH route": d["direct_cost_advantage_w"].where(
            d["direct_available"] & d["vehicle_available"]
        ),
    }
    for name, y_raw in outcomes.items():
        y = absorb_fixed_effects(y_raw, d["pair"])
        x = absorb_fixed_effects(d["post_v3"], d["pair"])
        fit = ols_clustered(y, x, d["pair"], absorbed_groups=(d["pair"],), min_observations=10)
        n, clusters = fit.n_observations, fit.n_clusters
        beta, se, t, p = fit.beta[1], fit.standard_errors[1], fit.t_statistics[1], fit.p_values[1]
        scale = 100 if "availability" in name.lower() else 1
        rows.append({
            "Outcome": name,
            "Rows": _int(n),
            "Pairs": _int(clusters),
            "Post-V3 effect": _num(scale * beta, 2),
            "SE": _num(scale * se, 2),
            "t": _num(t, 2),
            "p": _p(p),
            "Units": "pp" if "availability" in name.lower() else "fraction/ratio",
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

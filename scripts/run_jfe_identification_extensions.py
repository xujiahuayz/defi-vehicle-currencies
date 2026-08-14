#!/usr/bin/env python3
"""Event-time and pre-trend diagnostics for the V3 architecture analysis."""
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

from ddvc.paper_tables import _int, _num, _p, _write_table


def v3_event_time_pretrends() -> pd.DataFrame:
    launch = pd.Timestamp("2021-05-05")
    panel = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet")
    d = panel[panel["vehicle_sym"].eq("WETH")].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d["date"] >= launch - pd.Timedelta(days=365)) & (d["date"] <= launch + pd.Timedelta(days=365))]
    d["pair"] = d["src"].astype(str) + "->" + d["tgt"].astype(str)
    d["rel_month"] = ((d["date"].dt.year - launch.year) * 12 + (d["date"].dt.month - launch.month)).astype(int)
    d["post_v3"] = (d["date"] >= launch).astype(float)
    d["no_direct_weth_available"] = (~d["direct_available"]) & d["vehicle_available"]
    d["direct_quality"] = (d["direct_output_usd"] / d["trade_size_usd"]).replace([np.inf, -np.inf], np.nan).clip(0, 2)
    d["direct_cost_advantage_w"] = d["direct_cost_advantage"].clip(-10, 10)

    pre_pairs = set(d.loc[d["post_v3"].eq(0), "pair"])
    post_pairs = set(d.loc[d["post_v3"].eq(1), "pair"])
    d = d[d["pair"].isin(pre_pairs & post_pairs)].copy()

    # Monthly aggregation reduces the daily firehose and makes event-time plots
    # interpretable. Pair fixed effects are partialled out below.
    d["direct_available_f"] = d["direct_available"].astype(float)
    d["vehicle_available_f"] = d["vehicle_available"].astype(float)
    d["no_direct_weth_f"] = d["no_direct_weth_available"].astype(float)
    monthly = (
        d.groupby(["pair", "rel_month"], as_index=False)
        .agg(
            direct_available=("direct_available_f", "mean"),
            vehicle_available=("vehicle_available_f", "mean"),
            no_direct_weth=("no_direct_weth_f", "mean"),
            direct_quality=("direct_quality", "mean"),
            direct_cost_advantage=("direct_cost_advantage_w", "mean"),
        )
    )
    monthly["post_v3"] = (monthly["rel_month"] >= 0).astype(float)
    monthly.to_pickle(EMP / "v3_event_time_monthly.pkl")
    rows = []
    outcomes = [
        ("direct_available", "Direct-route availability", "pp"),
        ("vehicle_available", "WETH-route availability", "pp"),
        ("no_direct_weth", "No-direct WETH availability", "pp"),
        ("direct_quality", "Direct-route quality", "ratio"),
        ("direct_cost_advantage", "Direct cost advantage against WETH route", "fraction"),
    ]
    for col, label, units in outcomes:
        y = absorb_fixed_effects(monthly[col], monthly["pair"])
        post = absorb_fixed_effects(monthly["post_v3"], monthly["pair"])
        fit = ols_clustered(y, post, monthly["pair"], absorbed_groups=(monthly["pair"],), min_observations=10)
        n, c = fit.n_observations, fit.n_clusters
        beta, se, t, p = fit.beta[1], fit.standard_errors[1], fit.t_statistics[1], fit.p_values[1]

        pre = monthly[monthly["rel_month"].between(-12, -1)].copy()
        y_pre = absorb_fixed_effects(pre[col], pre["pair"])
        x_pre = absorb_fixed_effects(pre["rel_month"].astype(float), pre["pair"])
        pre_fit = ols_clustered(y_pre, x_pre, pre["pair"], absorbed_groups=(pre["pair"],), min_observations=10)
        npre, cpre = pre_fit.n_observations, pre_fit.n_clusters
        slope, slope_se, slope_t, slope_p = (
            pre_fit.beta[1],
            pre_fit.standard_errors[1],
            pre_fit.t_statistics[1],
            pre_fit.p_values[1],
        )

        scale = 100 if units == "pp" else 1
        rows.append(
            {
                "Outcome": label,
                "Rows": _int(n),
                "Pairs": _int(c),
                "Post effect": _num(scale * beta, 2),
                "Post t": _num(t, 2),
                "Post p": _p(p),
                "Pretrend slope": _num(scale * slope, 3),
                "Pretrend t": _num(slope_t, 2),
                "Pretrend p": _p(slope_p),
                "Units": units,
            }
        )

    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r19_v3_event_time_pretrends",
        "Uniswap V3 architecture: event-time estimates and pre-trends.",
        "tab:v3-event-time-pretrends",
        note=(
            "The sample is the balanced endpoint-pair monthly panel one year before and "
            "after Uniswap V3 launch. Post effects and pretrend slopes partial out pair "
            "fixed effects and cluster by endpoint pair."
        ),
    )
    out.to_pickle(EMP / "v3_event_time_pretrends.pkl")
    return out


def main() -> int:
    EMP.mkdir(parents=True, exist_ok=True)
    v3_event_time_pretrends()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Identification-oriented extensions for the JFE pre-write pass.

These checks tighten two architecture claims that the independent review flagged:

1. V3 launch evidence needs event-time/pre-trend diagnostics, not only a
   before/after pair fixed-effect estimate.
2. V4 settlement virtualization needs parser/receipt validation, not only the
   transfer-incidence difference.
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


def _cluster_ols(y: pd.Series, x: pd.Series, cluster: pd.Series) -> tuple[int, int, float, float, float, float]:
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


def _demean(s: pd.Series, by: pd.Series) -> pd.Series:
    return s - s.groupby(by).transform("mean")


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
    d["adv_bps"] = (d["vehicle_route_advantage"] * 10_000.0).clip(-100_000, 100_000)

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
            common_support_adv=("adv_bps", "mean"),
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
        ("common_support_adv", "Common-support WETH advantage", "bp"),
    ]
    for col, label, units in outcomes:
        y = _demean(monthly[col], monthly["pair"])
        post = _demean(monthly["post_v3"], monthly["pair"])
        n, c, beta, se, t, p = _cluster_ols(y, post, monthly["pair"])

        pre = monthly[monthly["rel_month"].between(-12, -1)].copy()
        y_pre = _demean(pre[col], pre["pair"])
        x_pre = _demean(pre["rel_month"].astype(float), pre["pair"])
        npre, cpre, slope, slope_se, slope_t, slope_p = _cluster_ols(y_pre, x_pre, pre["pair"])

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


def v4_receipt_parser_validation() -> pd.DataFrame:
    detail = pd.read_parquet(DATA / "empirical" / "v4_settlement_transfer_detail.parquet")
    if detail.empty:
        raise RuntimeError("Missing V4 settlement transfer detail; run run_v4_settlement_identification.py first.")
    detail["has_matching_transfer"] = detail["has_matching_transfer"].astype(bool)
    detail["receipt_found"] = detail["receipt_found"].astype(bool)

    rows = []
    for dex, g in detail.groupby("dex"):
        no_transfer = g[~g["has_matching_transfer"]]
        rows.append(
            {
                "Check": f"{dex} receipt coverage",
                "Observations": _int(len(g)),
                "Pass rate (%)": _pct(g["receipt_found"].mean()),
                "Mean total logs": _num(g["total_logs"].mean(), 2),
                "Mean matching transfers": _num(g["matching_transfer_logs"].mean(), 2),
                "Interpretation": "Receipts found; parser input available",
            }
        )
        rows.append(
            {
                "Check": f"{dex} positive transfer incidence",
                "Observations": _int(len(g)),
                "Pass rate (%)": _pct(g["has_matching_transfer"].mean()),
                "Mean total logs": _num(g["total_logs"].mean(), 2),
                "Mean matching transfers": _num(g["matching_transfer_logs"].mean(), 2),
                "Interpretation": "Transfer topic/address parser detects intermediary movement",
            }
        )
        if len(no_transfer):
            rows.append(
                {
                    "Check": f"{dex} no-transfer receipts still populated",
                    "Observations": _int(len(no_transfer)),
                    "Pass rate (%)": _pct(no_transfer["total_logs"].gt(0).mean()),
                    "Mean total logs": _num(no_transfer["total_logs"].mean(), 2),
                    "Mean matching transfers": _num(no_transfer["matching_transfer_logs"].mean(), 2),
                    "Interpretation": "No-transfer cases are not empty/missing receipts",
                }
            )

    audit = (
        detail[(detail["dex"].eq("uniswap_v4")) & (~detail["has_matching_transfer"]) & detail["receipt_found"]]
        .sort_values("route_usd", ascending=False)
        .head(25)
        [["week", "src", "sink", "vehicle", "tx_hash", "route_usd", "total_logs", "matching_transfer_logs"]]
    )
    audit.to_pickle(EMP / "v4_no_transfer_manual_audit_sample.pkl")
    out = pd.DataFrame(rows)
    _write_table(
        out,
        "table_r20_v4_receipt_parser_validation",
        "Receipt-parser validation for V4 settlement virtualization.",
        "tab:v4-parser-validation",
        note=(
            "V3 acts as a positive control because matched V3 route units should contain "
            "intermediary-token ERC-20 transfers. V4 no-transfer receipts are separately "
            "checked to ensure the absence is not caused by missing or empty receipts. A "
            "manual-audit sample of V4 no-transfer transactions is exported."
        ),
    )
    out.to_pickle(EMP / "v4_receipt_parser_validation.pkl")
    return out


def main() -> int:
    EMP.mkdir(parents=True, exist_ok=True)
    v3_event_time_pretrends()
    v4_receipt_parser_validation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

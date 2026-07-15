#!/usr/bin/env python3
"""Empirical tests for liquidity-route feedback and netting-related LP response."""
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

from build_paper_exhibits import _int, _num, _p, _write_table  # noqa: E402


def _demean_two(s: pd.Series, a: pd.Series, b: pd.Series) -> pd.Series:
    return s - s.groupby(a).transform("mean") - s.groupby(b).transform("mean") + s.mean()


def _cluster_ols_multi(y: pd.Series, xvars: pd.DataFrame, cluster: pd.Series) -> tuple[int, int, dict[str, float]]:
    d = pd.concat([y.rename("y"), xvars, cluster.rename("cluster")], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    c = d["cluster"].nunique()
    names = list(xvars.columns)
    empty = {f"{name}_{stat}": math.nan for name in names for stat in ["beta", "se", "t", "p"]}
    if n < 20 or c < 2:
        return n, c, empty
    x = np.column_stack([np.ones(n)] + [d[name].to_numpy(float) for name in names])
    yy = d["y"].to_numpy(float)
    if np.linalg.matrix_rank(x) < x.shape[1]:
        return n, c, empty
    beta = np.linalg.lstsq(x, yy, rcond=None)[0]
    resid = yy - x @ beta
    bread = np.linalg.inv(x.T @ x)
    meat = np.zeros((x.shape[1], x.shape[1]))
    for _, idx in d.groupby("cluster").indices.items():
        score = x[idx].T @ resid[idx][:, None]
        meat += score @ score.T
    finite = (c / (c - 1)) * ((n - 1) / max(n - x.shape[1], 1))
    cov = finite * bread @ meat @ bread
    out: dict[str, float] = {}
    for j, name in enumerate(names, start=1):
        se = float(math.sqrt(max(cov[j, j], 0.0)))
        t = float(beta[j] / se) if se > 0 else math.nan
        p = float(2 * stats.t.sf(abs(t), c - 1)) if np.isfinite(t) else math.nan
        out[f"{name}_beta"] = float(beta[j])
        out[f"{name}_se"] = se
        out[f"{name}_t"] = t
        out[f"{name}_p"] = p
    return n, c, out


def p2_feedback_loop() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "token", "BridgeShare"])
    lp = pd.read_parquet(DATA / "exhibits" / "lp_concentration.parquet").rename(columns={"token_symbol": "token"})
    d = bridge.merge(
        lp[["date", "token", "lp_concentration_share", "total_lp_liquidity_usd"]],
        on=["date", "token"],
        how="inner",
    )
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["token", "date"])
    rows = []
    for h in [1, 7, 14, 30]:
        dd = d.copy()
        dd["future_bridge_share"] = dd.groupby("token")["BridgeShare"].shift(-h)
        dd["future_lp_concentration"] = dd.groupby("token")["lp_concentration_share"].shift(-h)
        dd["future_log_lp_liquidity"] = np.log1p(dd.groupby("token")["total_lp_liquidity_usd"].shift(-h))
        x = pd.DataFrame(
            {
                "lp_concentration": _demean_two(dd["lp_concentration_share"], dd["token"], dd["date"]),
                "current_bridge_share": _demean_two(dd["BridgeShare"], dd["token"], dd["date"]),
            }
        )
        n, clusters, res = _cluster_ols_multi(
            _demean_two(dd["future_bridge_share"], dd["token"], dd["date"]),
            x,
            dd["date"],
        )
        rows.append(
            {
                "Panel": "A. Liquidity -> future intermediation",
                "Horizon": f"t+{h}",
                "Outcome": "future BridgeShare",
                "N": _int(n),
                "Date clusters": _int(clusters),
                "Main regressor": "LP concentration",
                "Beta": _num(res["lp_concentration_beta"], 3),
                "SE": _num(res["lp_concentration_se"], 3),
                "t": _num(res["lp_concentration_t"], 2),
                "p": _p(res["lp_concentration_p"]),
                "Control": f"current BridgeShare beta { _num(res['current_bridge_share_beta'], 3) }",
            }
        )
        x_rev = pd.DataFrame(
            {
                "current_bridge_share": _demean_two(dd["BridgeShare"], dd["token"], dd["date"]),
                "lp_concentration": _demean_two(dd["lp_concentration_share"], dd["token"], dd["date"]),
            }
        )
        for outcome, label in [
            ("future_lp_concentration", "future LP concentration"),
            ("future_log_lp_liquidity", "future log LP liquidity"),
        ]:
            n, clusters, res = _cluster_ols_multi(
                _demean_two(dd[outcome], dd["token"], dd["date"]),
                x_rev,
                dd["date"],
            )
            rows.append(
                {
                    "Panel": "B. Intermediation -> future liquidity",
                    "Horizon": f"t+{h}",
                    "Outcome": label,
                    "N": _int(n),
                    "Date clusters": _int(clusters),
                    "Main regressor": "current BridgeShare",
                    "Beta": _num(res["current_bridge_share_beta"], 3),
                    "SE": _num(res["current_bridge_share_se"], 3),
                    "t": _num(res["current_bridge_share_t"], 2),
                    "p": _p(res["current_bridge_share_p"]),
                    "Control": f"LP concentration beta { _num(res['lp_concentration_beta'], 3) }",
                }
            )
    out = pd.DataFrame(rows)
    EMP.mkdir(parents=True, exist_ok=True)
    out.to_pickle(EMP / "p2_liquidity_route_feedback.pkl")
    _write_table(
        out,
        "table_r32_p2_liquidity_route_feedback",
        "Bidirectional liquidity-route feedback.",
        "tab:p2-liquidity-route-feedback",
        note=(
            "All regressions residualize by token and date fixed effects and cluster by date. "
            "Panel A asks whether vehicle-linked LP concentration predicts future BridgeShare. "
            "Panel B asks whether current BridgeShare predicts future LP concentration or log LP liquidity."
        ),
    )
    return out


def _vehicle_key(s: object) -> str:
    value = str(s)
    return "WETH" if value == "ETH/WETH" else value


def p4b_netting_lp_response() -> pd.DataFrame:
    detail = pd.read_parquet(DATA / "empirical" / "v4_settlement_transfer_detail.parquet")
    v4 = detail[detail["dex"].eq("uniswap_v4") & detail["receipt_found"]].copy()
    v4["token"] = v4["vehicle"].map(_vehicle_key)
    exposure = (
        v4.groupby("token", as_index=False)
        .agg(
            v4_routes=("has_matching_transfer", "size"),
            netting_exposure=("has_matching_transfer", lambda x: 1.0 - float(pd.Series(x).mean())),
            median_route_usd=("route_usd", "median"),
        )
    )
    lp = pd.read_parquet(DATA / "exhibits" / "lp_concentration.parquet").rename(columns={"token_symbol": "token"})
    lp["date"] = pd.to_datetime(lp["date"])
    lp["week"] = lp["date"].dt.to_period("W-MON").dt.start_time
    event_week = pd.Timestamp("2025-01-20")
    lo = event_week - pd.Timedelta(weeks=52)
    hi = event_week + pd.Timedelta(weeks=74)
    weekly = (
        lp[(lp["week"] >= lo) & (lp["week"] <= hi)]
        .groupby(["week", "token"], as_index=False)
        .agg(
            lp_concentration_share=("lp_concentration_share", "mean"),
            total_lp_liquidity_usd=("total_lp_liquidity_usd", "mean"),
        )
    )
    d = weekly.merge(exposure, on="token", how="inner")
    d["post"] = (d["week"] >= event_week).astype(float)
    d["post_x_netting_exposure"] = d["post"] * d["netting_exposure"]
    d["log_lp_liquidity"] = np.log1p(d["total_lp_liquidity_usd"])
    rows = []
    for outcome, label in [
        ("lp_concentration_share", "LP concentration"),
        ("log_lp_liquidity", "log LP liquidity"),
    ]:
        x = pd.DataFrame(
            {
                "post_x_netting_exposure": _demean_two(d["post_x_netting_exposure"], d["token"], d["week"]),
            }
        )
        n, clusters, res = _cluster_ols_multi(_demean_two(d[outcome], d["token"], d["week"]), x, d["week"])
        beta = res["post_x_netting_exposure_beta"]
        rows.append(
            {
                "Panel": "A. LP response around settlement-netting architecture",
                "Outcome": label,
                "N": _int(n),
                "Week clusters": _int(clusters),
                "Vehicles": _int(d["token"].nunique()),
                "Treatment / exposure": "post x netting exposure",
                "Beta": _num(beta, 3),
                "SE": _num(res["post_x_netting_exposure_se"], 3),
                "t": _num(res["post_x_netting_exposure_t"], 2),
                "p": _p(res["post_x_netting_exposure_p"]),
                "Interpretation": "token and week fixed effects; suggestive event evidence",
            }
        )
    for _, r in exposure.sort_values("netting_exposure", ascending=False).iterrows():
        rows.append(
            {
                "Panel": "B. Netting exposure by vehicle",
                "Outcome": r["token"],
                "N": _int(r["v4_routes"]),
                "Week clusters": "",
                "Vehicles": "",
                "Treatment / exposure": "1 - V4 transfer incidence",
                "Beta": _num(r["netting_exposure"], 3),
                "SE": "",
                "t": "",
                "p": "",
                "Interpretation": f"median route ${_int(r['median_route_usd'])}",
            }
        )
    out = pd.DataFrame(rows)
    EMP.mkdir(parents=True, exist_ok=True)
    exposure.to_pickle(EMP / "p4b_netting_exposure_by_vehicle.pkl")
    out.to_pickle(EMP / "p4b_netting_lp_response.pkl")
    _write_table(
        out,
        "table_r33_p4b_netting_lp_response",
        "Settlement netting exposure and LP response.",
        "tab:p4b-netting-lp-response",
        note=(
            "Panel A estimates whether vehicles with higher V4 no-transfer exposure show stronger post-launch LP "
            "concentration or log-liquidity changes, residualizing by token and week fixed effects. This is suggestive "
            "mechanism evidence, not a clean exogenous adoption design. Panel B reports the exposure measure."
        ),
    )
    return out


def main() -> int:
    p2_feedback_loop()
    p4b_netting_lp_response()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

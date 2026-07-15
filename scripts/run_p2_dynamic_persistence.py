#!/usr/bin/env python3
"""Dynamic P2 alignment test.

The revised model treats liquidity concentration and current bridge use as
reduced-form predictors of future bridge use:

    E[BridgeShare_{k,t+h}] = alpha_k + beta L_{k,t} + rho BridgeShare_{k,t}.

This script estimates that object directly. It is still not causal LP feedback,
but it makes P2 fully aligned with the bounded model.
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

from build_paper_exhibits import _int, _num, _p, _write_table  # noqa: E402


def _demean_two(s: pd.Series, a: pd.Series, b: pd.Series) -> pd.Series:
    return s - s.groupby(a).transform("mean") - s.groupby(b).transform("mean") + s.mean()


def _cluster_ols_multi(y: pd.Series, xvars: pd.DataFrame, cluster: pd.Series) -> tuple[int, int, dict[str, float]]:
    d = pd.concat([y.rename("y"), xvars, cluster.rename("cluster")], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    c = d["cluster"].nunique()
    names = list(xvars.columns)
    if n < 20 or c < 2:
        return n, c, {f"{name}_{stat}": math.nan for name in names for stat in ["beta", "se", "t", "p"]}
    x = np.column_stack([np.ones(n)] + [d[name].to_numpy(float) for name in names])
    yy = d["y"].to_numpy(float)
    if np.linalg.matrix_rank(x) < x.shape[1]:
        return n, c, {f"{name}_{stat}": math.nan for name in names for stat in ["beta", "se", "t", "p"]}
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


def run() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "token", "BridgeShare"])
    lp = pd.read_parquet(DATA / "exhibits" / "lp_concentration.parquet").rename(columns={"token_symbol": "token"})
    d = bridge.merge(lp[["date", "token", "lp_concentration_share"]], on=["date", "token"], how="inner")
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["token", "date"])
    rows = []
    for h in [1, 7, 14, 30]:
        dd = d.copy()
        dd["future_bridge_share"] = dd.groupby("token")["BridgeShare"].shift(-h)
        y = _demean_two(dd["future_bridge_share"], dd["token"], dd["date"])
        x = pd.DataFrame(
            {
                "lp_concentration": _demean_two(dd["lp_concentration_share"], dd["token"], dd["date"]),
                "current_bridge_share": _demean_two(dd["BridgeShare"], dd["token"], dd["date"]),
            }
        )
        n, clusters, res = _cluster_ols_multi(y, x, dd["date"])
        rows.append(
            {
                "Horizon": f"t+{h}",
                "N": _int(n),
                "Date clusters": _int(clusters),
                "LP beta": _num(res["lp_concentration_beta"], 3),
                "LP SE": _num(res["lp_concentration_se"], 3),
                "LP t": _num(res["lp_concentration_t"], 2),
                "LP p": _p(res["lp_concentration_p"]),
                "Persistence beta": _num(res["current_bridge_share_beta"], 3),
                "Persistence SE": _num(res["current_bridge_share_se"], 3),
                "Persistence t": _num(res["current_bridge_share_t"], 2),
                "Persistence p": _p(res["current_bridge_share_p"]),
            }
        )
    out = pd.DataFrame(rows)
    EMP.mkdir(parents=True, exist_ok=True)
    out.to_pickle(EMP / "p2_dynamic_persistence.pkl")
    _write_table(
        out,
        "table_r31_p2_dynamic_persistence",
        "Dynamic bridge-use persistence and liquidity concentration.",
        "tab:p2-dynamic-persistence",
        note=(
            "Outcome is future BridgeShare. Regressors are current LP concentration and "
            "current BridgeShare. Variables are residualized by token and date fixed effects; "
            "standard errors are clustered by date. The table estimates the reduced-form P2 "
            "model and is not a causal LP-feedback design."
        ),
    )
    return out


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

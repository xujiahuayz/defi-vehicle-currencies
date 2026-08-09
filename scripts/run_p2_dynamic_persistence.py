#!/usr/bin/env python3
"""Dynamic P2 alignment test.

The revised model treats lagged liquidity concentration and bridge use as
reduced-form predictors of current bridge use:

    E[BridgeShare_{k,t}] = alpha_k + beta L_{k,t-tau} + rho BridgeShare_{k,t-tau}.

This script estimates that object directly. It is still not causal LP feedback,
but it makes P2 fully aligned with the bounded model.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.analysis.dynamics import value_at_day_offset
from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.paths import LP_CAPITAL_CONCENTRATION_PANEL

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

from ddvc.paper_tables import _int, _num, _p, _write_table


def run() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "token", "BridgeShare"])
    lp = pd.read_parquet(LP_CAPITAL_CONCENTRATION_PANEL).rename(columns={"token_symbol": "token"})
    d = bridge.merge(lp[["date", "token", "lp_capital_share"]], on=["date", "token"], how="inner")
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["token", "date"])
    rows = []
    for h in [1, 7, 14, 30]:
        dd = d.copy()
        dd["future_bridge_share"] = value_at_day_offset(dd, "BridgeShare", h)
        y = absorb_fixed_effects(dd["future_bridge_share"], dd["token"], dd["date"])
        x = pd.DataFrame(
            {
                "lp_concentration": absorb_fixed_effects(dd["lp_capital_share"], dd["token"], dd["date"]),
                "current_bridge_share": absorb_fixed_effects(dd["BridgeShare"], dd["token"], dd["date"]),
            }
        )
        fit = ols_clustered(y, x, dd["date"], absorbed_groups=(dd["token"], dd["date"]), min_observations=20)
        n, clusters = fit.n_observations, fit.n_clusters
        res = fit.named_statistics(list(x.columns), offset=1)
        rows.append(
            {
                "Horizon (days)": h,
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
            "Outcome is VehicleShare. Regressors are lagged LP concentration and "
            "lagged VehicleShare. Variables are residualized by token and date fixed effects; "
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

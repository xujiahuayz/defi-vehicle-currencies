#!/usr/bin/env python3
"""Is the native asset a better intermediary, holding the trade fixed, across venues?

This supersedes the v2-only test in `scripts/run_dominance_regressions.py`, whose
fixed-effects estimate rested on 703 identifying pair-day cells out of 22,991 and
3,865 routes out of 102,845, so 96.2% of the data contributed nothing. That design
identified only from cells where a native and a non-native intermediary HAPPENED to
be used on the same pair the same day, which within a single venue is rare. Its
coefficient flipped from -0.049 (p=0.008) pooled to +0.094 (p=0.269) with pair-day
effects, and calling that a null overstated an underpowered estimate.

The multi-venue route-cost panel is built differently and the difference is the
point. For every pair and day it quotes the counterfactual through EVERY vehicle
candidate, so a cell contains all candidates by construction rather than by
coincidence. Identification stops being a matter of luck, and the comparison
becomes what it should always have been: for this trade, at this state, would
routing through the native asset have cost more or less than routing through a
stablecoin or an imported asset?

Design. A cell is (source token, target token, date, trade size). Within a cell,
pool depth on both legs, token characteristics, that day's volatility and the gas
regime are all held fixed, so the residual variation is which asset the route went
through. Trade size enters the cell definition because gas is a fixed cost per
route, so dominance is mechanically size-dependent and pooling sizes would compare
a $1,000 trade against a $100,000 one.

Reported for every specification: the number of clusters AND the number of cells
that actually identify the estimate, plus the minimum detectable effect. A negative
result is only informative once bounded, so an estimate is never described as a
null without the effect size the design could have rejected.

Reads   data/empirical/route_cost_panel_v2.parquet
        data/processed/daily_gas_eth.parquet
Writes  output/exhibits/vehicle_dominance_multivenue.jsonl
"""

from __future__ import annotations

import argparse
import sys
from math import erfc, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
GAS = ROOT / "data" / "processed" / "daily_gas_eth.parquet"
OUT = ROOT / "output" / "exhibits" / "vehicle_dominance_multivenue.jsonl"


def ols_cluster(y: np.ndarray, X: np.ndarray, cluster: np.ndarray,
                k_absorbed: int = 0) -> tuple[np.ndarray, np.ndarray, int]:
    """OLS with one-way cluster-robust standard errors."""
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    meat = np.zeros((X.shape[1], X.shape[1]))
    uniq, inv = np.unique(cluster, return_inverse=True)
    for gi in range(len(uniq)):
        m = inv == gi
        s = X[m].T @ resid[m]
        meat += np.outer(s, s)
    n, k = X.shape
    g = len(uniq)
    dof = max(1, n - k - k_absorbed)
    scale = (g / max(1, g - 1)) * ((n - 1) / dof)
    V = XtX_inv @ meat @ XtX_inv * scale
    return beta, np.sqrt(np.maximum(np.diag(V), 0)), g


def pval(t: float) -> float:
    return erfc(abs(t) / sqrt(2)) if np.isfinite(t) else float("nan")


def demean(df: pd.DataFrame, cols: list[str], group: pd.Series) -> pd.DataFrame:
    return df[cols] - df[cols].groupby(group).transform("mean")


def report(name: str, y, X, cols, cluster, k_absorbed=0,
           ident_cells: int | None = None) -> dict:
    b, se, g = ols_cluster(y, X, cluster, k_absorbed)
    i = cols.index("native")
    t = b[i] / se[i] if se[i] > 0 else np.nan
    p = pval(t)
    # Minimum detectable effect at 80% power, 5% two-sided: 2.80 standard errors.
    mde = 2.80 * se[i]
    print(f"\n{name}")
    print(f"  n={len(y):,}  clusters={g:,}" +
          (f"  identifying cells={ident_cells:,}" if ident_cells is not None else ""))
    print(f"  {'term':<20}{'coef':>10}{'se':>10}{'t':>8}{'p':>9}")
    for j, c in enumerate(cols):
        tj = b[j] / se[j] if se[j] > 0 else np.nan
        star = "***" if pval(tj) < 0.01 else "**" if pval(tj) < 0.05 else "*" if pval(tj) < 0.10 else ""
        print(f"  {c:<20}{b[j]:>10.4f}{se[j]:>10.4f}{tj:>8.2f}{pval(tj):>9.3f} {star}")
    print(f"  minimum detectable effect (80% power): {mde:.4f}  "
          f"[{'estimate exceeds it' if abs(b[i]) > mde else 'BOUNDED NEGATIVE: cannot rule out effects below this'}]")
    return {"spec": name, "n": int(len(y)), "clusters": int(g),
            "identifying_cells": ident_cells, "coef": float(b[i]),
            "se": float(se[i]), "t": float(t), "p": float(p), "mde_80": float(mde)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-notional", type=float, default=100.0)
    args = ap.parse_args()

    d = pd.read_parquet(PANEL)
    n0 = len(d)
    d = d[d.direct_available & d.vehicle_available].copy()
    print(f"panel {n0:,} rows -> {len(d):,} with BOTH a direct and a vehicle route quoted")

    # Junk screen. This project has repeatedly been misled by unclassified tokens
    # producing absurd notionals and gaps, so the filter is applied and reported.
    d["adv"] = pd.to_numeric(d.direct_cost_advantage, errors="coerce")
    keep = d.adv.abs().le(1.0) & d.trade_size_usd.ge(args.min_notional)
    print(f"  economic screen |advantage| <= 100% and notional >= ${args.min_notional:,.0f}: "
          f"keeps {keep.mean():.2%}, drops {int((~keep).sum()):,}")
    d = d[keep].copy()

    d["mid_type"] = [classify(v)[1] for v in d.vehicle]
    d["native"] = (d.mid_type == "native").astype(float)
    d["dominated"] = (d.adv > 0).astype(float)
    d["log_usd"] = np.log(d.trade_size_usd.clip(lower=1))
    d["pair"] = d.src.astype(str) + "_" + d.tgt.astype(str)
    d["cell"] = d.pair + "_" + pd.to_datetime(d.date).dt.strftime("%Y%m%d") + \
        "_" + d.trade_size_usd.astype(str)
    d["year"] = pd.to_datetime(d.date).dt.year

    print(f"\nvehicle mix: {d.mid_type.value_counts().to_dict()}")
    print(f"native-intermediated share {d.native.mean():.1%}   "
          f"overall dominated {d.dominated.mean():.1%}")

    rows = []
    y = d.dominated.to_numpy()
    cl = d.pair.to_numpy()

    X1 = np.column_stack([np.ones(len(d)), d.native])
    rows.append(report("(1) pooled", y, X1, ["const", "native"], cl))

    X2 = np.column_stack([np.ones(len(d)), d.native, d.log_usd])
    rows.append(report("(2) + log notional", y, X2, ["const", "native", "log_usd"], cl))

    yd = pd.get_dummies(d.year, prefix="y", drop_first=True).astype(float)
    X3 = np.column_stack([np.ones(len(d)), d.native, d.log_usd, yd.to_numpy()])
    rows.append(report("(3) + year effects", y, X3,
                       ["const", "native", "log_usd"] + list(yd.columns), cl))

    # (4) the identifying design. A cell holds the pair, the day AND the trade
    # size, so gas as a share of notional is fixed too.
    mix = d.groupby("cell").native.agg(["mean", "size"])
    ident = mix[(mix["mean"] > 0) & (mix["mean"] < 1)].index
    c = d[d.cell.isin(ident)].copy()
    dm = demean(c, ["dominated", "native"], c.cell)
    rows.append(report("(4) pair-by-day-by-size FE", dm.dominated.to_numpy(),
                       np.column_stack([dm.native]), ["native"],
                       c.pair.to_numpy(), k_absorbed=c.cell.nunique(),
                       ident_cells=c.cell.nunique()))

    dmg = demean(c.assign(g=c.adv), ["g", "native"], c.cell)
    rows.append(report("(5) same design, continuous cost advantage",
                       dmg.g.to_numpy(), np.column_stack([dmg.native]),
                       ["native"], c.pair.to_numpy(),
                       k_absorbed=c.cell.nunique(), ident_cells=c.cell.nunique()))

    print(f"\nidentification: {c.cell.nunique():,} of {d.cell.nunique():,} cells "
          f"({c.cell.nunique()/max(d.cell.nunique(),1):.1%}) contain both a native and "
          f"a non-native candidate, covering {len(c):,} of {len(d):,} rows "
          f"({len(c)/max(len(d),1):.1%})")
    print("  compare the v2-only design: 703 of 22,991 cells (3.1%), 3,865 of 102,845 rows (3.8%)")

    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

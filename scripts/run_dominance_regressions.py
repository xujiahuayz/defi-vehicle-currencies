#!/usr/bin/env python3
"""Is the native intermediary less often dominated, holding the trade fixed?

The descriptive split says native-intermediated routes are dominated less often
than others. That comparison is confounded: native routes plausibly sit on more
liquid pairs and in deeper pools, so the raw gap may say nothing about the asset's
role and everything about where it happens to be used.

The controlled version compares routes between the SAME two tokens on the SAME
day that used DIFFERENT intermediaries. Within such a cell, pair liquidity, token
characteristics, the day's volatility and the gas regime are all held fixed by
construction, so the remaining variation is which asset the route went through.

Specifications, in increasing strictness:
  (1) pooled                     dominated ~ native
  (2) + size                     adds log notional, since gas is fixed per route
                                 and dominance is mechanically size-dependent
  (3) + venue and year effects   absorbs venue mix and slow-moving regime shifts
  (4) pair-by-day fixed effects  the identifying design; only cells that used both
                                 a native and a non-native intermediary contribute

Inference clusters by pair throughout, since routes on one pair share pool state.
Column (4) additionally reports the number of identifying cells, because a
within-cell estimator is only as good as the number of cells that actually switch.

Outcome is a linear probability model on `dominated`, with the continuous
`gap_bps` reported alongside so the result does not rest on one functional form.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "processed" / "counterfactual_dominance_clean.parquet"
OUT = ROOT / "output" / "exhibits" / "dominance_regressions.parquet"


def demean(df: pd.DataFrame, cols: list[str], group: pd.Series) -> pd.DataFrame:
    """Absorb a fixed effect by within-group demeaning."""
    return df[cols] - df[cols].groupby(group).transform("mean")


def ols_cluster(y: np.ndarray, X: np.ndarray, cluster: np.ndarray,
                k_absorbed: int = 0) -> tuple[np.ndarray, np.ndarray, int]:
    """OLS with cluster-robust standard errors. Returns (beta, se, n_clusters)."""
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    meat = np.zeros((X.shape[1], X.shape[1]))
    uniq = np.unique(cluster)
    for c in uniq:
        m = cluster == c
        Xg, ug = X[m], resid[m]
        s = Xg.T @ ug
        meat += np.outer(s, s)
    n, k = X.shape
    g = len(uniq)
    dof = max(1, n - k - k_absorbed)
    scale = (g / max(1, g - 1)) * ((n - 1) / dof)
    V = XtX_inv @ meat @ XtX_inv * scale
    return beta, np.sqrt(np.maximum(np.diag(V), 0)), g


def report(name: str, y, X, cols, cluster, k_absorbed=0, extra: str = "") -> dict:
    b, se, g = ols_cluster(y, X, cluster, k_absorbed)
    print(f"\n{name}   n={len(y):,}  clusters={g:,}  {extra}")
    print(f"  {'term':<22}{'coef':>10}{'se':>10}{'t':>8}{'p':>9}")
    out = {"spec": name, "n": len(y), "clusters": g}
    for i, c in enumerate(cols):
        t = b[i] / se[i] if se[i] > 0 else np.nan
        # normal approximation; cluster counts here are in the hundreds or more
        from math import erfc, sqrt
        p = erfc(abs(t) / sqrt(2)) if np.isfinite(t) else np.nan
        star = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
        print(f"  {c:<22}{b[i]:>10.4f}{se[i]:>10.4f}{t:>8.2f}{p:>9.3f} {star}")
        if c == "native":
            out.update(coef=b[i], se=se[i], t=t, p=p)
    return out


def main() -> int:
    f = pd.read_parquet(PANEL)
    f["pair"] = f.token_in + "_" + f.token_out
    f["cell"] = f.pair + "_" + f.date.dt.strftime("%Y%m%d")
    f["native"] = (f.mid_type == "native").astype(float)
    f["dominated"] = (f.gap_bps > 0).astype(float)
    f["log_usd"] = np.log(f.usd.clip(lower=1))
    f["year"] = f.date.dt.year
    f = f[np.isfinite(f.log_usd)].copy()

    print(f"panel: {len(f):,} routes, {f.pair.nunique():,} pairs, "
          f"{f.date.nunique()} days, {f.native.mean():.1%} native-intermediated")

    rows = []
    y = f.dominated.to_numpy()
    cl = f.pair.to_numpy()

    X1 = np.column_stack([np.ones(len(f)), f.native])
    rows.append(report("(1) pooled", y, X1, ["const", "native"], cl))

    X2 = np.column_stack([np.ones(len(f)), f.native, f.log_usd])
    rows.append(report("(2) + log notional", y, X2, ["const", "native", "log_usd"], cl))

    d = pd.get_dummies(f.year, prefix="y", drop_first=True).astype(float)
    X3 = np.column_stack([np.ones(len(f)), f.native, f.log_usd, d.to_numpy()])
    rows.append(report("(3) + year effects", y, X3,
                       ["const", "native", "log_usd"] + list(d.columns), cl))

    # (4) the identifying design: pair-by-day cells that used both a native and a
    # non-native intermediary. Everything else is absorbed.
    mix = f.groupby("cell").native.agg(["mean", "size"])
    ident = mix[(mix["mean"] > 0) & (mix["mean"] < 1)].index
    c = f[f.cell.isin(ident)].copy()
    dm = demean(c, ["dominated", "native", "log_usd"], c.cell)
    X4 = np.column_stack([dm.native, dm.log_usd])
    rows.append(report("(4) pair-by-day FE", dm.dominated.to_numpy(), X4,
                       ["native", "log_usd"], c.pair.to_numpy(),
                       k_absorbed=c.cell.nunique(),
                       extra=f"identifying cells={c.cell.nunique():,}"))

    # same design on the continuous outcome, so the result is not an artefact of
    # the binary threshold
    dmg = demean(c.assign(gap=c.gap_bps), ["gap", "native", "log_usd"], c.cell)
    rows.append(report("(5) pair-by-day FE, gap_bps outcome",
                       dmg.gap.to_numpy(),
                       np.column_stack([dmg.native, dmg.log_usd]),
                       ["native", "log_usd"], c.pair.to_numpy(),
                       k_absorbed=c.cell.nunique()))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(OUT, index=False)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    print("\nReading: a negative `native` coefficient in (4) means that, among trades")
    print("between the same two tokens on the same day, routing through the native")
    print("asset was less likely to be dominated by an available direct pool.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

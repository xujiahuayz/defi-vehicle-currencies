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

from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
from ddvc.tables import write_exhibit

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "processed" / "counterfactual_dominance_clean.parquet"
OUT = ROOT / "output" / "exhibits" / "dominance_regressions.jsonl"



# Control-window widths in DAYS. Integers only: a calendar month drifts between 28
# and 31 days, so a month-based window silently changes width across the sample,
# and pandas rejects several multiples of a week as non-fixed frequencies. A plain
# day count is uniform, orderable and needs no frequency strings.
WINDOW_DAYS = (1, 3, 7, 14, 30, 60, 120)


def day_index(dates: pd.Series) -> pd.Series:
    """Whole days since a fixed epoch, safe against the column's time unit.

    Never take `astype("int64")` on a datetime column to get a day number: these
    panels are `datetime64[us]`, so that yields MICROseconds and dividing by a
    nanosecond constant silently collapses distinct days together. Subtracting a
    timestamp and reading `.dt.days` is unit-agnostic.
    """
    return (pd.to_datetime(dates).dt.normalize() - pd.Timestamp("2000-01-01")).dt.days


def pval(t: float) -> float:
    from math import erfc, sqrt
    return erfc(abs(t) / sqrt(2)) if np.isfinite(t) else float("nan")


def report(name: str, y, X, cols, cluster, k_absorbed=0, extra: str = "") -> dict:
    fit = ols_clustered(
        y,
        X,
        cluster,
        add_constant=False,
        k_absorbed=k_absorbed,
    )
    b, se, g = fit.beta, fit.standard_errors, fit.n_clusters
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
    dm = absorb_fixed_effects(c[["dominated", "native", "log_usd"]], c.cell)
    X4 = np.column_stack([dm.native, dm.log_usd])
    rows.append(report("(4) pair-by-day FE", dm.dominated.to_numpy(), X4,
                       ["native", "log_usd"], c.pair.to_numpy(),
                       k_absorbed=c.cell.nunique(),
                       extra=f"identifying cells={c.cell.nunique():,}"))

    # same design on the continuous outcome, so the result is not an artefact of
    # the binary threshold
    dmg = absorb_fixed_effects(
        c.assign(gap=c.gap_bps)[["gap", "native", "log_usd"]],
        c.cell,
    )
    rows.append(report("(5) pair-by-day FE, gap_bps outcome",
                       dmg.gap.to_numpy(),
                       np.column_stack([dmg.native, dmg.log_usd]),
                       ["native", "log_usd"], c.pair.to_numpy(),
                       k_absorbed=c.cell.nunique()))

    # Widening the cell trades conditioning for power, so show the trade rather
    # than settle it. Identification needs a native AND a non-native intermediary to
    # have actually been USED on the same pair inside the same window, which at daily
    # width is a coincidence. Note what widening does and does not buy here: the
    # panel samples every 12th day, so windows below 14 days cannot merge two
    # observations at all, and beyond that the identifying CELL count falls while the
    # identifying ROW count rises, because cells merge into fewer, larger ones.
    print("\ncontrol-window ladder (window in days; cell = pair x window x nothing else):")
    print(f"  {'window':>8}{'cells':>9}{'ident.':>8}{'ident%':>8}{'rows':>9}"
          f"{'coef':>9}{'se':>8}{'p':>7}{'MDE80':>8}")
    di = day_index(f.date)
    for w in WINDOW_DAYS:
        cw = f.pair + "_" + (di // w).astype(str)
        mx = f.assign(_c=cw).groupby("_c").native.agg(["mean", "size"])
        idw = mx[(mx["mean"] > 0) & (mx["mean"] < 1)].index
        sub = f.assign(_c=cw)
        sub = sub[sub._c.isin(idw)]
        if sub.empty:
            continue
        dmw = absorb_fixed_effects(sub[["dominated", "native", "log_usd"]], sub._c)
        fit = ols_clustered(
            dmw.dominated.to_numpy(),
            np.column_stack([dmw.native, dmw.log_usd]),
            sub.pair.to_numpy(),
            add_constant=False,
            k_absorbed=sub._c.nunique(),
        )
        b, se, g = fit.beta, fit.standard_errors, fit.n_clusters
        tt = b[0] / se[0] if se[0] > 0 else float("nan")
        print(f"  {str(w) + 'd':>8}{cw.nunique():>9,}{len(idw):>8,}"
              f"{len(idw) / max(cw.nunique(), 1):>7.1%}{len(sub):>9,}"
              f"{b[0]:>9.4f}{se[0]:>8.4f}{pval(tt):>7.3f}{2.80 * se[0]:>8.4f}")
        rows.append({"spec": f"(4w) pair-by-{w}d FE", "n": int(len(sub)),
                     "clusters": int(g), "coef": float(b[0]), "se": float(se[0]),
                     "t": float(tt), "p": float(pval(tt)),
                     "identifying_cells": int(len(idw)), "mde_80": float(2.80 * se[0])})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    print("\nReading: a negative `native` coefficient in (4) means that, among trades")
    print("between the same two tokens on the same day, routing through the native")
    print("asset was less likely to be dominated by an available direct pool.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

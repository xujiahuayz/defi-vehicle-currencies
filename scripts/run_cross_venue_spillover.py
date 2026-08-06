#!/usr/bin/env python3
"""Cross-venue spillover from an architecture change, measured off the treated venue.

The estimand. For an architecture change on venue A, does the vehicle role move
on the venues that did not change? Every outcome is measured on untreated venues
only, and every headline outcome is a COMPOSITION contrast within a day, which is
what makes the design survive the confound that killed the version-1 event study:
a macro episode on the launch date hits every asset type on the untreated venues
on the same day, so it cannot produce a change in the native-minus-stable share.

Three events:
  Uniswap V3, 2021-05-05.  Treated uniswap_v3. Untreated uniswap_v2, sushiswap_v2,
                           curve, balancer.
  Uniswap V4, 2025-01-31.  Treated uniswap_v4. Untreated everything else. V4 also
                           restored native ETH as a pool asset with no wrapping,
                           which is a vehicle-currency mechanism directly.
  The Merge, 2022-09-15.   PLACEBO. Block time and gas dynamics changed; no AMM
                           architecture did. A spillover design should find
                           nothing here, and what it does find bounds how much of
                           any real estimate is a date artefact.

Inference basis, stated because it is not the default. A handful of venues means
clustering on venue is unavailable: the V3 event has four untreated venues and
the V4 event has seven, and a cluster-robust variance with that few groups is not
a variance estimate. So the identifying units are DAYS, the analytic standard
error is Newey-West with a Bartlett kernel, and every coefficient additionally
carries a randomisation p-value built by re-running the identical specification
at every admissible placebo date in the sample. The randomisation test is the one
to believe: it is exact under the sharp null of no date effect and it prices in
whatever serial correlation the series actually has, including the kind Newey-West
misses.

Reads   data/processed/cross_venue_spillover_daily.parquet
Writes  output/exhibits/cross_venue_spillover_estimates.jsonl
        output/exhibits/cross_venue_spillover_pretrends.jsonl
        output/exhibits/cross_venue_spillover_screens.jsonl
        output/figures/cross_venue_spillover.pdf

Run     .venv/bin/python scripts/run_cross_venue_spillover.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.tables import write_exhibit  # noqa: E402

PANEL = ROOT / "data" / "processed" / "cross_venue_spillover_daily.parquet"
EX = ROOT / "output" / "exhibits"
FIG = ROOT / "output" / "figures"

EVENTS = [
    ("uniswap_v3_launch", "2021-05-05", "untreated_v3", False),
    ("uniswap_v4_launch", "2025-01-31", "untreated_v4", False),
    ("the_merge_placebo_v3set", "2022-09-15", "untreated_v3", True),
    ("the_merge_placebo_v4set", "2022-09-15", "untreated_v4", True),
]

# Outcome label -> (numerator column, denominator column). A difference outcome
# is registered as its own regression and never read off two point estimates,
# because comparing subsample estimates by eye is how an insignificant gradient
# became load-bearing in this project four times.
OUTCOMES = {
    "route_share_native": ("cnt_native", "episodes"),
    "route_share_stable": ("cnt_stable", "episodes"),
    "btw_share_native": ("btw_native", "btw_total"),
    "btw_share_stable": ("btw_stable", "btw_total"),
    "newpair_share_native": ("new_native", "newpairs"),
    "newpair_share_stable": ("new_stable", "newpairs"),
}
DIFFS = {
    "route_share_native_less_stable": ("route_share_native", "route_share_stable"),
    "btw_share_native_less_stable": ("btw_share_native", "btw_share_stable"),
    "newpair_share_native_less_stable": ("newpair_share_native",
                                         "newpair_share_stable"),
}

WINDOW = 180        # days each side, primary
BIN = 30            # event-time bin width for the pre-trend exhibit
MIN_DENOM = 25      # a day with fewer than this many episodes carries no share
HAC_LAG = 30        # Bartlett bandwidth, one month of daily autocorrelation
RI_GAP = 200        # placebo dates must sit this far from every real event


# ----------------------------------------------------------------- estimation


def ols_hac(y: np.ndarray, x: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """OLS with a Newey-West Bartlett covariance. Returns (beta, cov)."""
    n, k = x.shape
    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ (x.T @ y)
    u = y - x @ beta
    s = (x * u[:, None])
    meat = s.T @ s
    for j in range(1, min(lag, n - 1) + 1):
        w = 1.0 - j / (lag + 1.0)
        g = s[j:].T @ s[:-j]
        meat += w * (g + g.T)
    scale = n / max(n - k, 1)
    cov = xtx_inv @ meat @ xtx_inv * scale
    return beta, cov


def break_spec(d: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Level break at the event, on top of a linear trend that may itself break.

    The Post coefficient is the jump at event time zero. The trend interaction is
    carried so a pre-existing drift cannot be collected as a jump, which is the
    single most common way a spillover claim is manufactured.
    """
    t = d["rel"].to_numpy(float) / 100.0
    post = (d["rel"].to_numpy() >= 0).astype(float)
    x = np.column_stack([np.ones(len(d)), t, post, t * post])
    return d["y"].to_numpy(float), x


def fit_break(d: pd.DataFrame) -> dict:
    y, x = break_spec(d)
    beta, cov = ols_hac(y, x, HAC_LAG)
    se = float(np.sqrt(max(cov[2, 2], 0.0)))
    dfree = max(len(d) - x.shape[1], 1)
    t = float(beta[2] / se) if se > 0 else np.nan
    return {"jump": float(beta[2]), "se": se, "t": t,
            "p": float(2 * stats.t.sf(abs(t), dfree)) if np.isfinite(t) else np.nan,
            "trend_change": float(beta[3]),
            "trend_change_se": float(np.sqrt(max(cov[3, 3], 0.0)))}


def pretrend_test(d: pd.DataFrame) -> dict:
    """Wald test that every pre-event bin coefficient is zero.

    A spillover claim with a pre-trend is not a spillover claim, so this runs on
    the pre-window alone with bin dummies against the omitted bin nearest the
    event, and its p-value is reported next to every estimate.
    """
    pre = d[d["rel"] < 0].copy()
    if pre.empty:
        return {"pretrend_p": np.nan, "pretrend_bins": 0, "pretrend_maxabs": np.nan}
    # floor puts rel in [-30,-1] into bin -1, the bin adjacent to the event
    pre["bin"] = np.floor(pre["rel"] / BIN).astype(int)
    bins = sorted(pre["bin"].unique())
    omit = max(bins)
    use = [b for b in bins if b != omit]
    if not use:
        return {"pretrend_p": np.nan, "pretrend_bins": 0, "pretrend_maxabs": np.nan}
    x = np.column_stack([np.ones(len(pre))]
                        + [(pre["bin"] == b).to_numpy(float) for b in use])
    y = pre["y"].to_numpy(float)
    beta, cov = ols_hac(y, x, HAC_LAG)
    r = np.zeros((len(use), x.shape[1]))
    for i in range(len(use)):
        r[i, i + 1] = 1.0
    rb = r @ beta
    rcr = r @ cov @ r.T
    try:
        wald = float(rb @ np.linalg.pinv(rcr) @ rb)
    except np.linalg.LinAlgError:
        return {"pretrend_p": np.nan, "pretrend_bins": len(use),
                "pretrend_maxabs": np.nan}
    return {"pretrend_p": float(stats.chi2.sf(wald, len(use))),
            "pretrend_bins": len(use),
            "pretrend_maxabs": float(np.nanmax(np.abs(beta[1:])))}


def event_time_bins(d: pd.DataFrame) -> pd.DataFrame:
    """Binned event-time means, so the pre-trend can be read as well as tested."""
    b = d.copy()
    b["bin"] = np.floor(b["rel"] / BIN).astype(int)
    g = b.groupby("bin").agg(mean=("y", "mean"), sd=("y", "std"), days=("y", "size"))
    base = float(g.loc[-1, "mean"]) if -1 in g.index else float(b.y.mean())
    g["vs_bin_minus1"] = g["mean"] - base
    return g.reset_index()


def randomisation(series: pd.DataFrame, real_dates: list[pd.Timestamp],
                  window: int, step: int) -> np.ndarray:
    """Distribution of the Post coefficient at admissible placebo dates."""
    dates = series["date"].to_numpy()
    lo, hi = series["date"].min(), series["date"].max()
    out = []
    cand = pd.date_range(lo + pd.Timedelta(days=window),
                         hi - pd.Timedelta(days=window), freq=f"{step}D")
    for c in cand:
        if any(abs((c - r).days) < RI_GAP for r in real_dates):
            continue
        m = (dates >= np.datetime64(c - pd.Timedelta(days=window))) & \
            (dates <= np.datetime64(c + pd.Timedelta(days=window)))
        d = series.loc[m].copy()
        if len(d) < 120:
            continue
        d["rel"] = (d["date"] - c).dt.days
        if (d["rel"] >= 0).sum() < 40 or (d["rel"] < 0).sum() < 40:
            continue
        y, x = break_spec(d)
        try:
            beta = np.linalg.pinv(x.T @ x) @ (x.T @ y)
        except np.linalg.LinAlgError:
            continue
        out.append(float(beta[2]))
    return np.asarray(out)


# ----------------------------------------------------------------------- main


def build_series(panel: pd.DataFrame, venue_set: str, outcome: str) -> pd.DataFrame:
    d = panel[panel.venue_set == venue_set].copy()
    if outcome in DIFFS:
        a, b = DIFFS[outcome]
        na, da = OUTCOMES[a]
        nb, db = OUTCOMES[b]
        d = d[(d[da] >= MIN_DENOM) & (d[db] >= MIN_DENOM)]
        d["y"] = d[na] / d[da] - d[nb] / d[db]
    else:
        num, den = OUTCOMES[outcome]
        d = d[d[den] >= MIN_DENOM]
        d["y"] = d[num] / d[den]
    keep = ["date", "y", "episodes", "nodes", "routes_intermediated", "newpairs"]
    return d[keep].dropna(subset=["y"]).sort_values("date").reset_index(drop=True)


def estimate(panel: pd.DataFrame, s: pd.DataFrame, ev_name: str, ev_date: str,
             vset: str, is_placebo: bool, outcome: str, window: int,
             donut: int, ri_step: int, real_dates: list) -> tuple[dict, pd.DataFrame] | None:
    ev = pd.Timestamp(ev_date)
    m = (s.date >= ev - pd.Timedelta(days=window)) & \
        (s.date <= ev + pd.Timedelta(days=window))
    d = s.loc[m].copy()
    d["rel"] = (d["date"] - ev).dt.days
    if donut:
        # The launch fortnight is mechanical churn on every venue, so a donut
        # variant asks whether the break survives dropping it.
        d = d[d.rel.abs() > donut]
    n_pre = int((d.rel < 0).sum())
    n_post = int((d.rel >= 0).sum())
    if n_pre < 40 or n_post < 40:
        return None
    fit = fit_break(d)
    pre = pretrend_test(d)
    ri = randomisation(s, real_dates, window, ri_step)
    ri_p = float((np.abs(ri) >= abs(fit["jump"])).mean()) if len(ri) else np.nan
    # Minimum detectable effect at 80% power, 5% two-sided. Reported for every
    # estimate so a small coefficient is a bounded negative and not a null. The
    # randomisation version is the one to quote, since it uses the spread the
    # design actually produces at dates where nothing happened.
    # Under the randomisation null the 95th percentile of |b| is the 5% critical
    # value, so 80% power needs (1.96+0.84)/1.96 = 1.43 of it.
    mde_ri = float(np.percentile(np.abs(ri), 95)) * 1.43 if len(ri) >= 20 else np.nan
    row = {
        "event": ev_name, "event_date": ev_date, "venue_set": vset,
        "placebo": is_placebo, "outcome": outcome,
        "window": window, "donut": donut,
        "days_pre": n_pre, "days_post": n_post,
        "untreated_venues": int(panel.loc[panel.venue_set == vset,
                                          "venues_present"].max()),
        "pre_mean": float(d.loc[d.rel < 0, "y"].mean()),
        "episodes_pre": int(d.loc[d.rel < 0, "episodes"].sum()),
        "episodes_post": int(d.loc[d.rel >= 0, "episodes"].sum()),
        "routes_pre": int(d.loc[d.rel < 0, "routes_intermediated"].sum()),
        "routes_post": int(d.loc[d.rel >= 0, "routes_intermediated"].sum()),
        "graph_nodes_mean": float(d["nodes"].mean()),
        **fit,
        "ri_draws": int(len(ri)), "ri_p": ri_p,
        "mde_hac_80pct": 2.802 * fit["se"], "mde_randomisation": mde_ri,
        **pre,
    }
    b = event_time_bins(d)
    b["event"] = ev_name
    b["outcome"] = outcome
    return row, b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--windows", default="90,270", help="robustness windows")
    ap.add_argument("--ri-step", type=int, default=7)
    ap.add_argument("--no-figure", action="store_true")
    args = ap.parse_args()

    panel = pd.read_parquet(PANEL)
    panel["date"] = pd.to_datetime(panel["date"])
    tcols = [c for c in panel.columns if c.startswith("btw_")]
    panel["btw_total"] = panel[tcols].sum(axis=1)

    real_dates = [pd.Timestamp(e[1]) for e in EVENTS]
    rows, pre_rows, rob = [], [], []
    alt = [int(w) for w in args.windows.split(",") if w.strip()]

    for ev_name, ev_date, vset, is_placebo in EVENTS:
        for outcome in list(OUTCOMES) + list(DIFFS):
            s = build_series(panel, vset, outcome)
            if s.empty:
                continue
            got = estimate(panel, s, ev_name, ev_date, vset, is_placebo, outcome,
                           args.window, 0, args.ri_step, real_dates)
            if got is None:
                continue
            rows.append(got[0])
            pre_rows.append(got[1])
            for w in alt:
                g = estimate(panel, s, ev_name, ev_date, vset, is_placebo, outcome,
                             w, 0, args.ri_step, real_dates)
                if g:
                    rob.append(g[0])
            g = estimate(panel, s, ev_name, ev_date, vset, is_placebo, outcome,
                         args.window, 14, args.ri_step, real_dates)
            if g:
                rob.append(g[0])

    est = pd.DataFrame(rows)
    EX.mkdir(parents=True, exist_ok=True)
    write_exhibit(pd.DataFrame(rob), EX / "cross_venue_spillover_robustness.jsonl")
    write_exhibit(est, EX / "cross_venue_spillover_estimates.jsonl")
    write_exhibit(pd.concat(pre_rows, ignore_index=True),
                  EX / "cross_venue_spillover_pretrends.jsonl")

    # Screens, reported and not assumed.
    scr = []
    for vset, g in panel.groupby("venue_set"):
        scr.append({
            "venue_set": vset,
            "days": int(len(g)),
            "days_dropped_thin_episodes": int((g.episodes < MIN_DENOM).sum()),
            "routes_multi": int(g.routes_multi.sum()),
            "routes_roundtrip_dropped": int(g.routes_roundtrip.sum()),
            "roundtrip_share": float(g.routes_roundtrip.sum()
                                     / max(g.routes_multi.sum(), 1)),
            "episodes": int(g.episodes.sum()),
            "edges_predust": int(g.edges_predust.sum()),
            "edges_kept": int(g.edges.sum()),
            "dust_edge_share": float(1 - g.edges.sum() / max(g.edges_predust.sum(), 1)),
            "newpairs": int(g.newpairs.sum()),
        })
    write_exhibit(pd.DataFrame(scr), EX / "cross_venue_spillover_screens.jsonl")

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    show = ["event", "outcome", "days_pre", "days_post", "pre_mean", "jump", "se",
            "p", "ri_p", "mde_randomisation", "pretrend_p"]
    print("\nSPILLOVER ESTIMATES (outcome measured on untreated venues only)\n")
    for ev in est.event.unique():
        print(f"--- {ev} ---")
        print(est[est.event == ev][show].to_string(index=False,
                                                   float_format=lambda v: f"{v:.4f}"))
        print()
    print("SCREENS\n", pd.DataFrame(scr).to_string(index=False))

    if not args.no_figure:
        make_figure(pd.concat(pre_rows, ignore_index=True))
    return 0


def make_figure(bins: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    keys = [("uniswap_v3_launch", "Uniswap V3 launch"),
            ("uniswap_v4_launch", "Uniswap V4 launch"),
            ("the_merge_placebo_v4set", "The Merge (placebo)")]
    outs = [("route_share_native_less_stable", "route share, native less stable"),
            ("btw_share_native_less_stable", "betweenness share, native less stable")]
    FIG.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(len(outs), len(keys), figsize=(11, 6), sharey="row")
    for i, (ocol, olab) in enumerate(outs):
        for j, (ev, elab) in enumerate(keys):
            ax = axes[i, j]
            b = bins[(bins.event == ev) & (bins.outcome == ocol)].sort_values("bin")
            if len(b):
                ax.axhline(0, lw=0.6, color="0.6")
                ax.axvline(-0.5, lw=0.8, color="0.3", ls="--")
                ax.plot(b["bin"], b["vs_bin_minus1"], marker="o", ms=3, lw=1.1)
            if i == 0:
                ax.set_title(elab, fontsize=9)
            if j == 0:
                ax.set_ylabel(olab, fontsize=8)
            ax.set_xlabel(f"event time, {BIN}-day bins", fontsize=8)
            ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "cross_venue_spillover.pdf")
    print(f"\nwrote {(FIG / 'cross_venue_spillover.pdf').relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())

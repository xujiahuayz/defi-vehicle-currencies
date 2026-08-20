#!/usr/bin/env python3
"""The Uniswap V1-to-V2 natural experiment: a mandated vehicle currency losing its mandate.

Why this exists. Uniswap V1 held one ETH<->token pool per token, so ETH intermediated every token-to-token trade by protocol construction. Uniswap V2 (2020-05-05) allowed arbitrary ERC20/ERC20 pools and removed that mandate. If vehicle-currency dominance were purely a technological artefact it should collapse the moment the artefact is withdrawn, and if it is an equilibrium resting on thick-market externalities it should persist. This script runs the three measurements that separate those, plus the adversarial checks that decide whether any of it survives as identification.

Test 1, the differential migration. V1 died after V2 launched, which is mechanical and uninteresting. The non-mechanical quantity is whether the FORCED part of V1 flow (token-to-token, which V2 made strictly cheaper by replacing two hops with one) left faster than the ETH-PAIRED part (which V2 made only marginally cheaper). A common shock to V1 as a venue cannot produce a divergence between two flow types inside the same venue, so the differential absorbs the migration confound that a level series cannot.

Test 2, voluntary vehicle persistence. For an unordered token pair that acquired a direct non-ETH V2 pool, how long did trade between those tokens keep routing through ETH afterwards? Before the direct pool exists, ETH routing is mandatory and measures nothing. After it exists, ETH routing is a choice. This is the paper's core question with the mandate held fixed by construction.

The V1 restriction. Test 2 is sharpest on tokens that lived under the V1 mandate. The original V1 pull omitted token addresses, so a separate static fetch now retains the subgraph's exact one-exchange-per-token registry. Test 2 runs on all V2 pairs and then on pairs whose two tokens are both present in that V1 registry.

Sanity filters, because this project has repeatedly been misled by null-symbol tokens producing absurd notionals. Pairs need both symbols present in the V2 panel, a minimum trade count, and per-trade notionals inside a plausible band. Every filter reports how much it removed.

Reads   data/processed/v1_trade_classes_daily.parquet
        data/processed/v1_exchange_day.parquet
        data/processed/v1_exchange_token_crosswalk.parquet
        data/unified/YYYYMMDD.parquet
Writes  data/processed/v2_pair_routing_daily.parquet
        output/exhibits/v1_forced_vehicle_*.jsonl

Run     ./scripts/run scripts/analyze/run_v1_forced_vehicle_tests.py [--workers N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.tables import write_exhibit

ROOT = Path(__file__).resolve().parents[2]

PROC = ROOT / "data" / "processed"
UNIFIED = ROOT / "data" / "unified"
EX = ROOT / "output" / "exhibits"

V2_LAUNCH = pd.Timestamp("2020-05-05")
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
NATIVE_ETH = {WETH, "0x0000000000000000000000000000000000000000",
              "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"}

# --- pair-routing sanity filters ---
PR_MIN_TRADES = 20      # trades of a pair inside the window
PR_USD_LO, PR_USD_HI = 100.0, 50_000_000.0

CLASSES = ("eth_to_token", "token_to_eth", "token_to_token",
           "same_exchange_rt", "multi_exchange")


def md(df: pd.DataFrame) -> str:
    """Markdown table without pandas.to_markdown.

    Keep this report independent of pandas' optional `tabulate` formatter and its
    version-specific output details.
    """
    def cell(v: object) -> str:
        if isinstance(v, float):
            if pd.isna(v):
                return ""
            # a whole number that only became a float because its column is mixed
            # dtype should not print as "2,020.0000"
            if v == int(v) and abs(v) >= 1000:
                return f"{int(v):,}"
            return f"{v:,.4f}" if abs(v) < 1e4 else f"{v:,.0f}"
        if isinstance(v, (int, np.integer)):
            return f"{v:,}"
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)

    df = df.copy()
    # a year is a label, not a quantity: print 2020, never 2,020.0000
    for c in ("year", "cohort", "cal_year"):
        if c in df.columns:
            df[c] = df[c].astype("Int64").astype(str)
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(cell(r[c]) for c in cols) + " |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Test 1: differential migration of forced versus ETH-paired V1 flow
# ---------------------------------------------------------------------------
def test1_differential(out: list[str]) -> pd.DataFrame:
    d = pd.read_parquet(PROC / "v1_trade_classes_daily.parquet")
    d["n_pair"] = d.n_eth_to_token + d.n_token_to_eth
    d["eth_pair"] = d.eth_eth_to_token + d.eth_token_to_eth

    def win(lo_d: int, hi_d: int) -> pd.DataFrame:
        return d[(d.date >= V2_LAUNCH + pd.Timedelta(days=lo_d))
                 & (d.date < V2_LAUNCH + pd.Timedelta(days=hi_d))]

    rows = []
    for label, lo, hi in (("-365 to -183", -365, -183), ("-182 to -1", -182, 0),
                          ("0 to +181", 0, 182), ("+182 to +364", 182, 365),
                          ("+365 to +729", 365, 730)):
        w = win(lo, hi)
        tot_eth = w.eth_pair.sum() + w.eth_token_to_token.sum()
        rows.append({
            "window_days": label,
            "swap_tx": int(w.n_swap_tx.sum()),
            "eth_paired_tx": int(w.n_pair.sum()),
            "t2t_tx": int(w.n_token_to_token.sum()),
            "t2t_strict_tx": int(w.n_token_to_token_strict.sum()),
            "t2t_share_count": w.n_token_to_token.sum() / max(w.n_swap_tx.sum(), 1),
            "t2t_share_strict": w.n_token_to_token_strict.sum() / max(w.n_swap_tx.sum(), 1),
            "t2t_share_eth_vol": w.eth_token_to_token.sum() / max(tot_eth, 1),
        })
    tab = pd.DataFrame(rows)
    base = tab.loc[tab.window_days == "-182 to -1"].iloc[0]
    tab["eth_paired_vs_pre"] = tab.eth_paired_tx / base.eth_paired_tx
    tab["t2t_vs_pre"] = tab.t2t_tx / base.t2t_tx
    # >1 means forced flow contracted faster than ETH-paired flow
    tab["differential"] = tab.eth_paired_vs_pre / tab.t2t_vs_pre

    out.append("## Test 1. Forced routing left V1 faster than ETH-paired flow\n")
    out.append(md(tab))

    # monthly series, for the shape of the response
    m = d.set_index("date").resample("MS").agg(
        {"n_swap_tx": "sum", "n_pair": "sum", "n_token_to_token": "sum",
         "n_token_to_token_strict": "sum", "eth_pair": "sum",
         "eth_token_to_token": "sum"})
    m["t2t_share"] = m.n_token_to_token / m.n_swap_tx
    m["t2t_share_strict"] = m.n_token_to_token_strict / m.n_swap_tx
    m = m.loc["2019-11":"2021-06"]
    out.append("\nMonthly, V2 launched 2020-05-05:\n")
    out.append(
        md(m.reset_index().assign(month=lambda x: x.date.dt.strftime("%Y-%m"))[
            ["month", "n_swap_tx", "n_pair", "n_token_to_token", "t2t_share",
             "t2t_share_strict"]
        ])
    )
    write_exhibit(m, EX / "v1_forced_vehicle_monthly.jsonl")
    write_exhibit(tab, EX / "v1_forced_vehicle_windows.jsonl")
    test1_thinning_check(d, out)
    return tab


def test1_thinning_check(d: pd.DataFrame, out: list[str]) -> None:
    """The confound that kills Test 1, quantified rather than mentioned.

    A token-to-token trade needs BOTH of its tokens to have a live V1 exchange, while
    an ETH-paired trade needs one. As the V1 exchange network thinned, the set of
    feasible token-to-token pairs shrank roughly with the square of the number of live
    exchanges while feasible ETH-paired trades shrank roughly linearly, so the RATIO of
    the two should fall roughly in proportion to the exchange count even if no trader
    changed behaviour and no mandate had been removed. Excess close to one therefore
    means thinning alone accounts for the observed differential.

    The N-squared benchmark is a crude combinatorial heuristic, not a theorem: it
    assumes trade propensity is uniform across pairs, and real V1 activity was
    concentrated in a few tokens. It is reported as an order-of-magnitude benchmark and
    the conclusion drawn from it is deliberately weak.
    """
    e = pd.read_parquet(PROC / "v1_exchange_day.parquet")
    e["tot"] = e.n_pair.fillna(0) + e.n_t2t.fillna(0)
    act = e[e.tot > 0].copy()
    act["m"] = act.date.dt.to_period("M")
    n_all = act.groupby("m").exchange.nunique().rename("N_traded")
    per = act.groupby(["m", "exchange"]).tot.sum().reset_index()
    n_10 = (per[per.tot >= 10].groupby("m").exchange.nunique()
            .rename("N_over_10_trades"))

    mm = d.set_index("date").resample("MS").agg(
        {"n_pair": "sum", "n_token_to_token": "sum"})
    mm.index = mm.index.to_period("M")
    mm = mm.join(n_all).join(n_10)
    mm["ratio"] = mm.n_token_to_token / mm.n_pair
    b = mm.loc["2020-05"]
    rows = []
    for k in ["2020-01", "2020-02", "2020-03", "2020-04", "2020-05", "2020-06",
              "2020-07", "2020-08", "2020-09", "2020-10", "2020-11", "2020-12",
              "2021-03", "2021-06", "2021-12"]:
        if k not in mm.index:
            continue
        r = mm.loc[k]
        rows.append({
            "month": k, "exchanges_traded": int(r.N_traded),
            "exchanges_over_10_trades": int(r.N_over_10_trades),
            "t2t_per_eth_paired": r.ratio,
            "ratio_vs_2020_05": r.ratio / b.ratio,
            "N_vs_2020_05": r.N_over_10_trades / b.N_over_10_trades,
            "excess_over_thinning": (r.ratio / b.ratio)
            / (r.N_over_10_trades / b.N_over_10_trades),
        })
    out.append("\n### Test 1's confound: the V1 exchange network was thinning\n")
    out.append(md(pd.DataFrame(rows)))
    out.append("\nExcess near 1.0 means the fall in token-to-token relative to "
               "ETH-paired trade is what the shrinking exchange network predicts on its "
               "own, with nothing left for the removal of the mandate to explain.\n")


# ---------------------------------------------------------------------------
# Crosswalk: exact V1 exchange address -> ERC20 token registry
# ---------------------------------------------------------------------------
def load_crosswalk(out: list[str]) -> pd.DataFrame:
    path = PROC / "v1_exchange_token_crosswalk.parquet"
    xw = pd.read_parquet(path)
    required = {"exchange", "token", "symbol", "resolved", "v1_era"}
    if not required.issubset(xw.columns) or xw.empty:
        raise ValueError(f"exact V1 crosswalk is incomplete: {path}")
    resolved = xw[xw.resolved].copy()
    if resolved.exchange.duplicated().any() or resolved.token.duplicated().any():
        raise ValueError("exact V1 crosswalk is not one-to-one")
    observed = pd.read_parquet(PROC / "v1_exchange_day.parquet", columns=["exchange"])
    observed_exchanges = set(observed.exchange.astype(str).str.lower())
    missing = observed_exchanges - set(resolved.exchange.astype(str).str.lower())
    if missing:
        raise ValueError(
            f"exact V1 crosswalk misses {len(missing):,}/{len(observed_exchanges):,} "
            "observed exchanges"
        )
    out.append("\n### Exact V1 exchange-to-token map\n")
    out.append(
        f"The retained V1 exchange registry resolves all {len(observed_exchanges):,} "
        f"exchange addresses in the daily panel. It contains {resolved.token.nunique():,} "
        f"distinct tokens, including {int(resolved.v1_era.sum()):,} whose exchanges "
        "traded before V2 launched. Token identities come directly from the V1 "
        "subgraph; no price-series matching is used.\n"
    )
    return resolved


# ---------------------------------------------------------------------------
# Test 2: routing choice per token pair, once a direct pool exists
# ---------------------------------------------------------------------------
def one_unified_day(path: Path) -> dict | None:
    """Direct and ETH-routed trade per unordered token pair, on uniswap_v2 only."""
    cols = ["tx_hash", "component_id", "token_in", "token_out", "amount_usd",
            "log_index", "source"]
    try:
        df = pd.read_parquet(path, columns=cols)
    except (OSError, ValueError, KeyError) as exc:
        return {"date": path.stem, "error": f"{type(exc).__name__}: {exc}"[:160]}
    df = df[df.source == "uniswap_v2"]
    if df.empty:
        return None
    df = df.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    key = ["tx_hash", "component_id"]
    df["nleg"] = df.groupby(key).log_index.transform("size")

    recs = []

    def unordered(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Sort the two endpoints so a pair has one key regardless of trade direction.
        np.minimum has no loop for string dtypes, hence the explicit where."""
        lo = np.where(x <= y, x, y)
        return lo, np.where(x <= y, y, x)

    # one-leg components: a direct trade of the pair it touches
    s1 = df[df.nleg == 1]
    if len(s1):
        a, b = unordered(s1.token_in.to_numpy(str), s1.token_out.to_numpy(str))
        recs.append(pd.DataFrame({"t0": a, "t1": b, "usd": s1.amount_usd.to_numpy(),
                                  "kind": "direct"}))
    # two-leg components: ETH-routed only if the interior token is the native asset
    s2 = df[df.nleg == 2]
    if len(s2):
        g = s2.groupby(key, sort=False)
        first, last = g.head(1).reset_index(drop=True), g.tail(1).reset_index(drop=True)
        mid = first.token_out.to_numpy(str)
        a0, b0 = first.token_in.to_numpy(str), last.token_out.to_numpy(str)
        usd = np.maximum(first.amount_usd.to_numpy(), last.amount_usd.to_numpy())
        is_eth = np.isin(mid, list(NATIVE_ETH))
        keep = is_eth & (a0 != b0) & ~np.isin(a0, list(NATIVE_ETH)) \
            & ~np.isin(b0, list(NATIVE_ETH))
        if keep.any():
            a, b = unordered(a0[keep], b0[keep])
            recs.append(pd.DataFrame({"t0": a, "t1": b, "usd": usd[keep],
                                      "kind": "eth_routed"}))
    if not recs:
        return None
    r = pd.concat(recs, ignore_index=True)
    agg = r.groupby(["t0", "t1", "kind"], as_index=False).agg(
        n=("usd", "size"), usd=("usd", "sum"), usd_med=("usd", "median"))
    agg["date"] = pd.to_datetime(path.stem, format="%Y%m%d")
    return {"date": path.stem, "_agg": agg,
            "n_legs": len(df), "n_1leg": int((df.nleg == 1).sum()),
            "n_2leg": int((df.nleg == 2).sum()),
            "n_moreleg": int((df.nleg > 2).sum())}


def build_pair_routing(workers: int, out: list[str]) -> pd.DataFrame:
    from concurrent.futures import ProcessPoolExecutor, as_completed
    days = sorted(UNIFIED.glob("*.parquet"))
    print(f"reducing {len(days):,} unified days", flush=True)
    aggs, err, meta = [], [], []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one_unified_day, d): d for d in days}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r is None:
                continue
            if "error" in r:
                err.append(r)
                continue
            aggs.append(r.pop("_agg"))
            meta.append(r)
            if i % 400 == 0:
                print(f"  unified {i:,}/{len(days):,}", flush=True)
    if err:
        out.append(f"\n{len(err)} unified day(s) failed to read; first: "
                   f"{err[0]['date']} {err[0]['error']}\n")
    pr = pd.concat(aggs, ignore_index=True)
    md = pd.DataFrame(meta)
    out.append(f"\nUniswap-V2 legs read from the unified layer: {md.n_legs.sum():,} "
               f"over {len(md):,} days. Single-leg components {md.n_1leg.sum():,}, "
               f"two-leg {md.n_2leg.sum():,}, three-or-more-leg {md.n_moreleg.sum():,} "
               f"(the last are outside this test, which needs an unambiguous single "
               f"intermediary).\n")
    pr.to_parquet(PROC / "v2_pair_routing_daily.parquet", index=False)
    return pr


def weth_pairing_fact(pr: pd.DataFrame, out: list[str]) -> None:
    """After the mandate was withdrawn, did anyone stop pairing against the native asset?

    This is the plainest available reading of the dependent variable and it needs no
    route reconstruction: among single-leg V2 trades, the share executed on a pool that
    contains WETH. On V1 this was 100% by construction. It is a statement about which
    pools exist and get used, not about routing choice, and it is Uniswap-V2-only.
    """
    d = pr[pr.kind == "direct"].copy()
    d["weth"] = (d.t0 == WETH) | (d.t1 == WETH)
    d["y"] = d.date.dt.year
    g = d.groupby(["y", "weth"]).agg(n=("n", "sum"), usd=("usd", "sum")).unstack()
    rows = []
    for y in g.index:
        nt, nf = g.loc[y, ("n", True)], g.loc[y, ("n", False)]
        ut, uf = g.loc[y, ("usd", True)], g.loc[y, ("usd", False)]
        rows.append({"year": int(y), "single_leg_trades": int(nt + nf),
                     "weth_pool_share_count": nt / (nt + nf),
                     "weth_pool_share_value": ut / (ut + uf)})
    out.append("\n### The mandate was withdrawn and native-asset pairing did not "
               "retreat\n")
    out.append(md(pd.DataFrame(rows)))

    fp = pd.read_parquet(PROC / "v2_pair_first_trade.parquet")
    fp["weth"] = (fp.token0 == WETH) | (fp.token1 == WETH)
    fp["y"] = fp.first_trade.dt.year
    nb = fp.groupby("y").weth.agg(["size", "mean"]).reset_index()
    nb.columns = ["year", "new_pairs_first_traded", "share_including_weth"]
    out.append(f"\nOf {len(fp):,} pairs that ever traded on V2, "
               f"{int(fp.weth.sum()):,} ({fp.weth.mean():.1%}) include WETH. New pairs "
               f"by the year they first traded:\n")
    out.append(md(nb))


def test2_persistence(pr: pd.DataFrame, xw: pd.DataFrame, out: list[str]) -> None:
    dec = pd.read_parquet(PROC / "v2_token_decimals.parquet")
    known = set(dec.token)

    w = pr.pivot_table(index=["t0", "t1", "date"], columns="kind",
                       values=["n", "usd", "usd_med"], fill_value=0).reset_index()
    w.columns = ["_".join([c for c in col if c]).strip("_") for col in w.columns]
    for c in ("n_direct", "n_eth_routed", "usd_direct", "usd_eth_routed"):
        if c not in w:
            w[c] = 0.0
    w["med"] = w[["usd_med_direct", "usd_med_eth_routed"]].max(axis=1)

    n_raw = len(w)
    # sanity filters, each reported
    f_sym = w[w.t0.isin(known) & w.t1.isin(known)]
    f_usd = f_sym[(f_sym.med >= PR_USD_LO) & (f_sym.med <= PR_USD_HI)]
    out.append(f"\n### Test 2 sample construction\n")
    out.append(f"| filter | pair-days remaining | share kept |\n|---|---|---|\n")
    out.append(f"| pair-days with any V2 trade | {n_raw:,} | 1.000 |\n")
    out.append(f"| both tokens in the V2 decimals map | {len(f_sym):,} | "
               f"{len(f_sym) / n_raw:.3f} |\n")
    out.append(f"| median trade notional in ${PR_USD_LO:,.0f}-${PR_USD_HI:,.0f} | "
               f"{len(f_usd):,} | {len(f_usd) / n_raw:.3f} |\n")
    w = f_usd

    # first day the pair traded directly; ETH routing after that is a choice
    first_direct = (w[w.n_direct > 0].groupby(["t0", "t1"]).date.min()
                    .rename("t_direct"))
    w = w.merge(first_direct, on=["t0", "t1"], how="inner")
    w["wk"] = ((w.date - w.t_direct).dt.days // 7)

    # pairs must show real ETH routing at some point, else there is nothing to persist
    tot = w.groupby(["t0", "t1"]).agg(
        n_eth=("n_eth_routed", "sum"), n_dir=("n_direct", "sum"),
        t_direct=("t_direct", "first"))
    live = tot[(tot.n_eth + tot.n_dir >= PR_MIN_TRADES) & (tot.n_eth > 0)]
    out.append(f"| pairs with a direct pool and >= {PR_MIN_TRADES} trades and any "
               f"ETH-routed trade | {len(live):,} pairs | |\n")

    w = w.merge(live[[]], on=["t0", "t1"], how="inner").sort_values(
        ["t0", "t1", "date"]).reset_index(drop=True)

    # LIVE-ALTERNATIVE condition. Dating availability at the direct pool's first trade
    # is not enough: a pool that traded once and then went dormant is not a usable
    # alternative, and a pair whose direct pool died will show a near-100% ETH-routed
    # share that has nothing to do with anyone choosing the vehicle. Require a direct
    # trade inside the trailing 28 days for the alternative to count as available.
    w["last_direct"] = w.date.where(w.n_direct > 0)
    w["last_direct"] = w.groupby(["t0", "t1"], sort=False).last_direct.ffill()
    w["alive"] = (w.date - w.last_direct).dt.days <= 28
    post = w[w.wk >= 0].copy()

    def profile(x: pd.DataFrame, label: str) -> pd.DataFrame:
        b = x.assign(bucket=pd.cut(
            x.wk, [-1, 0, 1, 3, 7, 12, 25, 51, 10**6],
            labels=["wk 0", "wk 1", "wk 2-3", "wk 4-7", "wk 8-12", "wk 13-25",
                    "wk 26-51", "wk 52+"]))
        g = b.groupby("bucket", observed=True).agg(
            trades=("n_direct", "sum"), eth_trades=("n_eth_routed", "sum"),
            usd_direct=("usd_direct", "sum"), usd_eth=("usd_eth_routed", "sum"))
        g.insert(
            0,
            "pairs",
            b[["bucket", "t0", "t1"]]
            .drop_duplicates()
            .groupby("bucket", observed=True)
            .size(),
        )
        g["eth_share_count"] = g.eth_trades / (g.eth_trades + g.trades)
        g["eth_share_value"] = g.usd_eth / (g.usd_eth + g.usd_direct)
        # per-pair shares as well as pooled ones: the pooled figure is dominated by a
        # handful of very large pairs, and the two answers differ sharply
        pp = b.groupby(["bucket", "t0", "t1"], observed=True).agg(
            d=("n_direct", "sum"), e=("n_eth_routed", "sum"))
        pp["s"] = pp.e / (pp.e + pp.d)
        g["eth_share_median_pair"] = pp.groupby("bucket", observed=True).s.median()
        g["eth_share_mean_pair"] = pp.groupby("bucket", observed=True).s.mean()
        out.append(f"\n{label}\n")
        out.append(md(g.reset_index()))
        return g

    profile(post, "**A. All V2 pairs**, weeks since a direct pool first traded, with no "
                  "condition on the direct pool still being usable:")
    profile(post[post.alive],
            "**B. The same, restricted to pair-days on which the direct pool traded "
            "within the trailing 28 days.** This is the specification to read:")
    out.append(f"\nOf {len(post):,} pair-days after a direct pool first traded, "
               f"{int(post.alive.sum()):,} ({post.alive.mean():.1%}) have a live direct "
               f"pool. Per pair, the median share of days with a live direct pool is "
               f"{post.groupby(['t0', 't1']).alive.mean().median():.2f}.\n")

    # cohort and calendar decomposition: the horizon profile is confounded by both
    al = post[post.alive].copy()
    al["cohort"] = al.t_direct.dt.year
    al["cal_year"] = al.date.dt.year
    al["h"] = pd.cut(al.wk, [-1, 0, 3, 12, 25, 51, 10**6],
                     labels=["wk 0", "wk 1-3", "wk 4-12", "wk 13-25", "wk 26-51",
                             "wk 52+"])
    for by, title in (("cohort", "the year the direct pool arrived"),
                      ("cal_year", "the calendar year of observation")):
        pp = al.groupby([by, "h", "t0", "t1"], observed=True).agg(
            d=("n_direct", "sum"), e=("n_eth_routed", "sum"))
        pp["s"] = pp.e / (pp.e + pp.d)
        piv = pp.groupby([by, "h"], observed=True).s.median().unstack()
        out.append(f"\nMedian per-pair ETH-routed share of trade count, by {title} "
                   f"(rows) and weeks since availability (columns):\n")
        out.append(md(piv.reset_index()))

    # Restrict to tokens whose V1 exchange traded before V2 launched, and keep only
    # days on which the newly available direct alternative remained active.
    v1tok = set(xw[xw.v1_era].token)
    r = post[post.alive & post.t0.isin(v1tok) & post.t1.isin(v1tok)]
    out.append(f"\nTokens traded on V1 before V2 launched: {len(v1tok):,}. "
               f"Pairs in the test with both tokens in that pre-V2 set and an active "
               f"direct alternative: "
               f"{r.groupby(['t0', 't1']).ngroups:,}.\n")
    if r.groupby(["t0", "t1"]).ngroups >= 5:
        profile(r, "**Pre-V2 V1-token pairs with an active direct alternative**, weeks "
                   "since a direct pool first traded:")
    else:
        out.append("\nToo few V1-token pairs survive to profile; the V1-restricted "
                   "version of Test 2 is not identified and is not reported.\n")

    # per-pair survival, on live-alternative days only: weeks until the ETH-routed
    # count share first drops below a level. This is a noisy statistic, since one quiet
    # week can trip a threshold the pair then reverts above, so it is reported next to
    # the share profile rather than in place of it.
    wk = post[post.alive].groupby(["t0", "t1", "wk"], as_index=False).agg(
        e=("n_eth_routed", "sum"), d=("n_direct", "sum"))
    wk["sh"] = wk.e / (wk.e + wk.d)
    rows = []
    for lvl in (0.5, 0.25, 0.10):
        below = wk[wk.sh < lvl].groupby(["t0", "t1"]).wk.min()
        allp = wk.groupby(["t0", "t1"]).wk.max()
        rows.append({
            "threshold": f"ETH-routed share < {lvl:.0%}",
            "pairs_reaching_it": int(len(below)),
            "of_pairs": int(len(allp)),
            "median_weeks": float(below.median()) if len(below) else float("nan"),
            "p75_weeks": float(below.quantile(0.75)) if len(below) else float("nan"),
        })
    out.append("\nPer-pair time from the direct pool's first trade to the ETH-routed "
               "share falling below a level:\n")
    out.append(md(pd.DataFrame(rows)))

    # the pre-direct baseline: was ETH routing even the norm before a direct pool?
    pre = w[w.wk < 0]
    if len(pre):
        out.append(f"\nBefore the direct pool existed, these pairs traded "
                   f"{int(pre.n_eth_routed.sum()):,} times through ETH and "
                   f"{int(pre.n_direct.sum()):,} times directly (the latter must be "
                   f"zero by construction and is a check on the window logic).\n")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--reuse-pair-routing", action="store_true")
    args = ap.parse_args()

    EX.mkdir(parents=True, exist_ok=True)
    out: list[str] = []

    test1_differential(out)
    xw = load_crosswalk(out)

    prp = PROC / "v2_pair_routing_daily.parquet"
    if args.reuse_pair_routing and prp.exists():
        pr = pd.read_parquet(prp)
        out.append("\n(pair-routing panel reused from disk)\n")
    else:
        pr = build_pair_routing(args.workers, out)
    weth_pairing_fact(pr, out)
    test2_persistence(pr, xw, out)

    text = "".join(out)
    (EX / "v1_forced_vehicle_report.md").write_text(text)
    print(text)
    print(f"\nwrote {(EX / 'v1_forced_vehicle_report.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Daily vehicle-role outcomes measured ONLY on venues that did not change.

Why this panel exists. Version 1 of this project ran an event study around the
Uniswap V3 launch and it died on a confound: the launch date is also a macro
date, so a break there is unattributable. The spillover design fixes that by
never measuring the treated venue. If an architecture change on venue A moves
the vehicle role on venues that did not change, a shared macro episode cannot be
the explanation for a change in the COMPOSITION of routing on B, because any
macro shock hits every asset type on B on the same day and the composition
contrast differences it out.

Three outcome families, all restricted to untreated venues:

  INTERMEDIATION COMPOSITION. Among multi-leg routes whose every leg settles on
  an untreated venue, the share of intermediation episodes passing through each
  asset type. Route purity matters: a route with one leg on the treated venue is
  partly treated, and including it would smuggle the mechanical migration back
  in.

  BETWEENNESS CENTRALITY. The token graph rebuilt from untreated-venue legs
  alone, betweenness summed by asset type and expressed as a share of the total.
  This is the sharpest of the three because it asks whether the architecture
  change altered which asset is structurally indispensable somewhere it did not
  operate.

  NEW-PAIR COMPOSITION. Among token pairs appearing for the first time anywhere
  on the untreated venues, the share whose counterparty set includes each asset
  type. A pair is created by somebody choosing what to pair a new token WITH,
  which is the vehicle decision at the moment of listing.

Two untreated sets, one per event:
  untreated_v3   uniswap_v2, sushiswap_v2, curve, balancer   (V3 launch, 2021-05)
  untreated_v4   every venue except uniswap_v4               (V4 launch, 2025-01)
The Merge placebo has no treated venue, so it is run on both sets.

Screens, all reported by the script that consumes this panel: legs priced at
zero or above 1e9 USD are dropped as pricing junk, graph edges below a notional
floor are dropped as dust, and round-trip routes (first input token equal to
last output token) are dropped as atomic arbitrage or wash trading.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/cross_venue_spillover_daily.parquet

Run     .venv/bin/python scripts/build_cross_venue_spillover_panel.py [--workers N]
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.asset_types import TYPES, classify  # noqa: E402
from ddvc.tables import write_panel  # noqa: E402

UNIFIED = ROOT / "data" / "unified"
OUT_PANEL = ROOT / "data" / "processed" / "cross_venue_spillover_daily.parquet"

# Untreated venue sets, keyed by the event they serve.
UNTREATED = {
    "untreated_v3": {"uniswap_v2", "sushiswap_v2", "curve", "balancer"},
    "untreated_v4": {"uniswap_v1", "uniswap_v2", "uniswap_v3", "sushiswap_v2",
                     "sushiswap_v3", "curve", "balancer", "fluid"},
}

COLS = ["tx_hash", "log_index", "source", "token_in", "token_out",
        "amount_usd", "component_id", "route_class"]

MAX_USD = 1e9          # above this a leg is a pricing artefact, not a trade
MIN_EDGE_USD = 1000.0  # dust pairs carry no routing information


def _load(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_parquet(path, columns=COLS)
    except Exception:
        return None
    return None if df.empty else df


def _unordered(d: pd.DataFrame) -> tuple:
    """Canonical (low, high) token ordering, so a pair is one edge and not two.

    Row-wise DataFrame.min on string columns falls back to a Python loop and was
    two thirds of this script's runtime; the numpy form is the same answer.
    """
    ti = d["token_in"].to_numpy(dtype=object)
    to = d["token_out"].to_numpy(dtype=object)
    first = ti < to
    return np.where(first, ti, to), np.where(first, to, ti)


@lru_cache(maxsize=200_000)
def _type_of(token: str) -> str:
    return classify(token)[1]


def _intermediation(df: pd.DataFrame) -> dict:
    """Asset-type composition of intermediation on pure-untreated multi-leg routes.

    Same object as scripts/build_intermediation_by_type.py, so the two series are
    comparable: multi-leg routes only, round trips excluded, every interior token
    of a route counted once, and a route contributing its notional to each
    interior token it uses.
    """
    out: dict = {"routes_multi": 0, "routes_intermediated": 0,
                 "routes_roundtrip": 0, "episodes": 0}
    for t in TYPES:
        out[f"cnt_{t}"] = 0
        out[f"usd_{t}"] = 0.0
    if df.empty:
        return out

    d = df
    g = d.groupby("rid", sort=False)
    size = g["log_index"].transform("size").to_numpy()
    pos = g.cumcount().to_numpy()
    first_in = g["token_in"].transform("first").to_numpy()
    last_out = g["token_out"].transform("last").to_numpy()
    notional = g["amount_usd"].transform("max").to_numpy()

    multi = size > 1
    roundtrip = first_in == last_out
    out["routes_multi"] = int((multi & (pos == 0)).sum())
    out["routes_roundtrip"] = int((multi & roundtrip & (pos == 0)).sum())
    out["routes_intermediated"] = int((multi & ~roundtrip & (pos == 0)).sum())

    interior = multi & ~roundtrip & (pos < size - 1)
    if not interior.any():
        return out
    keep = d.loc[interior, ["rid", "token_out"]].copy()
    keep["usd"] = notional[interior]
    # one episode per (route, interior token), so a route that revisits a token
    # counts it once
    keep = keep.drop_duplicates(["rid", "token_out"])
    keep = keep[keep.token_out.astype(bool)]
    keep["atype"] = [_type_of(t) for t in keep.token_out]
    cnt = keep.groupby("atype").size()
    val = keep.groupby("atype")["usd"].sum()
    out["episodes"] = int(cnt.sum())
    for t in TYPES:
        out[f"cnt_{t}"] = int(cnt.get(t, 0))
        out[f"usd_{t}"] = float(val.get(t, 0.0))
    return out


def _centrality(df: pd.DataFrame) -> dict:
    """Betweenness by asset type on the untreated-venue token graph."""
    import networkx as nx

    d = df[df.route_class.isin(["single", "coherent"])]
    d = d[(d.amount_usd > 0) & (d.amount_usd < MAX_USD)]
    out = {"nodes": 0, "edges": 0, "edges_predust": 0}
    for t in TYPES:
        out[f"btw_{t}"] = 0.0
    if d.empty:
        return out
    a, b = _unordered(d)
    e = (pd.DataFrame({"a": a, "b": b, "usd": d["amount_usd"].to_numpy()})
         .groupby(["a", "b"], as_index=False)["usd"].sum())
    out["edges_predust"] = int(len(e))
    e = e[e.usd >= MIN_EDGE_USD]
    if len(e) < 4:
        return out

    g = nx.Graph()
    g.add_edges_from(zip(e.a, e.b))
    if g.number_of_nodes() < 4:
        return out
    out["nodes"] = int(g.number_of_nodes())
    out["edges"] = int(g.number_of_edges())
    # Topological betweenness, computed exactly. Pivot sampling is avoided
    # because the estimand here is a daily time series and sampling noise would
    # enter the event-study residual; unweighted because the question is which
    # asset a path MUST pass through when no direct edge exists, which is the
    # structural-indispensability reading and the one that is not a restatement
    # of the volume share already measured by the intermediation outcome.
    topo = nx.betweenness_centrality(g, normalized=True)
    for node, v in topo.items():
        out[f"btw_{_type_of(node)}"] += float(v)
    return out


def one_day(path: Path) -> list[dict]:
    df = _load(path)
    if df is None:
        return []
    date = pd.to_datetime(path.stem, format="%Y%m%d")
    # One integer route id, assigned once: every downstream groupby is then on an
    # int64 key and not a 66-character hash, which is most of the runtime.
    df = df.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    df["rid"] = ((df.tx_hash != df.tx_hash.shift())
                 | (df.component_id != df.component_id.shift())).cumsum().to_numpy()
    rows = []
    # Before a venue launches, its untreated set selects every leg in the file, so
    # the two sets coincide and the expensive part is computed once.
    cache: dict[frozenset, dict] = {}
    present = set(df.source.unique())
    for name, venues in UNTREATED.items():
        key = frozenset(present & venues)
        if key in cache:
            rows.append({**cache[key], "date": date, "venue_set": name})
            continue
        d = df[df.source.isin(venues)]
        if d.empty:
            continue
        # route purity: a component with any leg on the treated venue is dropped
        off = (df.assign(_off=~df.source.isin(venues))
                 .groupby("rid", sort=False)["_off"].transform("max"))
        dd = df[~off.to_numpy()]
        n_pure = int(dd.rid.nunique()) if len(dd) else 0
        row = {"date": date, "venue_set": name,
               "legs_untreated": int(len(d)),
               "legs_all": int(len(df)),
               "routes_pure": n_pure,
               "venues_present": int(d.source.nunique())}
        row.update(_intermediation(dd))
        row.update(_centrality(d))
        cache[key] = {k: v for k, v in row.items() if k != "venue_set"}
        rows.append(row)
    return rows


def new_pairs(days: list[Path]) -> pd.DataFrame:
    """First-appearance date of every unordered token pair, per untreated set."""
    seen: dict[str, set] = {k: set() for k in UNTREATED}
    rows = []
    for path in days:
        try:
            df = pd.read_parquet(path, columns=["source", "token_in", "token_out",
                                                "amount_usd"])
        except Exception:
            continue
        if df.empty:
            continue
        df = df[(df.amount_usd > 0) & (df.amount_usd < MAX_USD)]
        date = pd.to_datetime(path.stem, format="%Y%m%d")
        for name, venues in UNTREATED.items():
            d = df[df.source.isin(venues)]
            if d.empty:
                continue
            a, b = _unordered(d)
            e = (pd.DataFrame({"a": a, "b": b, "usd": d["amount_usd"].to_numpy()})
                 .groupby(["a", "b"], as_index=False)["usd"].sum())
            e = e[e.usd >= MIN_EDGE_USD]
            fresh = [(x, y) for x, y in zip(e.a, e.b) if (x, y) not in seen[name]]
            seen[name].update(fresh)
            cnt: dict[str, int] = {}
            for x, y in fresh:
                for t in {_type_of(x), _type_of(y)}:
                    cnt[t] = cnt.get(t, 0) + 1
            row = {"date": date, "venue_set": name, "newpairs": len(fresh)}
            for t in TYPES:
                row[f"new_{t}"] = int(cnt.get(t, 0))
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    days = sorted(UNIFIED.glob("[0-9]" * 8 + ".parquet"))
    if args.limit:
        days = days[: args.limit]
    if not days:
        sys.exit(f"no unified day files under {UNIFIED}")
    print(f"reducing {len(days):,} days with {args.workers} workers", flush=True)

    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one_day, d): d for d in days}
        for i, f in enumerate(as_completed(futs), 1):
            rows.extend(f.result())
            if i % 250 == 0:
                print(f"  {i:,}/{len(days):,}", flush=True)

    panel = pd.DataFrame(rows).sort_values(["venue_set", "date"]).reset_index(drop=True)
    print("folding first-appearance dates for new pairs", flush=True)
    np_df = new_pairs(days)
    panel = panel.merge(np_df, on=["date", "venue_set"], how="left")
    for t in TYPES:
        panel[f"new_{t}"] = panel[f"new_{t}"].fillna(0).astype(int)
    panel["newpairs"] = panel["newpairs"].fillna(0).astype(int)

    write_panel(panel, OUT_PANEL)
    print(f"\nwrote {OUT_PANEL.relative_to(ROOT)}  rows={len(panel):,}")
    for name, g in panel.groupby("venue_set"):
        print(f"\n{name}: {len(g):,} days  {g.date.min().date()} to {g.date.max().date()}")
        print(f"  intermediated routes {g.routes_intermediated.sum():,}   "
              f"episodes {g.episodes.sum():,}   new pairs {g.newpairs.sum():,}")
        y = g.set_index("date").resample("YS")[[f"cnt_{t}" for t in TYPES]].sum()
        tot = y.sum(axis=1).clip(lower=1)
        print("  native / stable share of intermediation episodes by year:")
        for idx, r in y.iterrows():
            print(f"    {idx.year}  native {r['cnt_native']/tot[idx]:6.1%}   "
                  f"stable {r['cnt_stable']/tot[idx]:6.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

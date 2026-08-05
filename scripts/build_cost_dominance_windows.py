#!/usr/bin/env python3
"""Do windows exist where the incumbent intermediated route is cost-dominated?

This is the measurement the paper's central claim depends on. The FX inertia
literature's stated limit is that an incumbent vehicle currency's cost advantage
is itself a consequence of its incumbency, so the data never contain the state in
which a currency holds the vehicle role while being strictly cost-dominated by a
rival. If on-chain routing does contain that state, the claim to overcome the
limit is available. If it does not, the paper claims better measurement and
nothing more. Settle it before writing any framing.

Design, deliberately a first-pass EXISTENCE test on realised trades only. No
counterfactual quoting at historical pool state, which is a much larger build and
belongs in the full design once existence is established.

For each (day, ordered pair) where BOTH a direct single-leg route and an indirect
multi-leg route executed, within trade-size bins:

  realised rate  = amount_out / amount_in        (comparable within pair+direction)
  direct_rate    = median realised rate of direct routes in that cell
  indirect_rate  = median realised rate of indirect routes in that cell
  dominated      = direct_rate exceeds indirect_rate by more than a threshold

A cell where `dominated` holds AND indirect volume share stays high is a
candidate cost-dominance window: traders kept routing through an intermediary
while the direct market was realising strictly better prices at comparable size.

What this test can and cannot support, stated up front so the output is not
over-read:
  CAN   establish that such cells exist and how common they are
  CAN   show the intermediary's volume share inside them
  CANNOT price the road not taken (needs counterfactual quoting)
  CANNOT separate gas, since realised rates are gross of gas. A two-hop route is
        mechanically more gas-expensive, so a direct route winning on rate need
        not win all-in. This biases TOWARD finding dominance, which is the
        direction that would manufacture the result, so it is reported as an
        upper bound and the gas-inclusive version is required before any claim.
  CANNOT exclude MEV: sandwiched trades depress realised rates.

Size bins matter because price impact is convex, so comparing a small direct
trade against a large intermediated one is not like-for-like.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/cost_dominance_cells.parquet
        output/exhibits/cost_dominance_summary.parquet
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
UNIFIED = ROOT / "data" / "unified"
OUT_PARQUET = ROOT / "data" / "processed" / "cost_dominance_cells.parquet"
OUT_CSV = ROOT / "output" / "exhibits" / "cost_dominance_summary.parquet"

from ddvc.asset_types import classify  # noqa: E402

COLS = ["tx_hash", "component_id", "token_in", "token_out", "token_in_sym",
        "token_out_sym", "amount_in", "amount_out", "amount_usd", "log_index"]

# trade-size bins in USD; price impact is convex so cells must be size-matched
BINS = [0, 1_000, 10_000, 100_000, np.inf]
BIN_LABELS = ["<1k", "1k-10k", "10k-100k", ">100k"]

# minimum trades per side before a cell is comparable at all
MIN_PER_SIDE = 3
# a rate gap this large or more counts as domination (10 bps)
GAP_BPS = 10.0


def one_day(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_parquet(path, columns=COLS)
    except Exception:
        return None
    if df.empty:
        return None

    df = df.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    g = df.groupby(["tx_hash", "component_id"], sort=False)

    # collapse each route to one row: endpoints, notional, leg count, intermediary
    first = g.first()
    last = g.last()
    n_legs = g.size()
    usd = g["amount_usd"].max()
    # route-level input and output amounts come from the first and last legs
    route = pd.DataFrame({
        "token_in": first["token_in"],
        "token_out": last["token_out"],
        "sym_in": first["token_in_sym"],
        "sym_out": last["token_out_sym"],
        "amount_in": first["amount_in"],
        "amount_out": last["amount_out"],
        "usd": usd,
        "legs": n_legs,
    })
    # interior token of a two-leg route identifies the intermediary
    route["mid"] = np.where(n_legs == 2, first["token_out"], None)

    route = route[(route.amount_in > 0) & (route.amount_out > 0)]
    route = route[route.token_in != route.token_out]        # drop round trips
    if route.empty:
        return None

    route["rate"] = route.amount_out / route.amount_in
    route["indirect"] = route.legs > 1
    route["size_bin"] = pd.cut(route.usd, BINS, labels=BIN_LABELS, right=False)
    route["date"] = pd.to_datetime(path.stem, format="%Y%m%d")

    # cells: date x ordered pair x size bin, requiring both sides present
    key = ["date", "token_in", "token_out", "size_bin"]
    agg = route.groupby(key, observed=True).apply(
        lambda x: pd.Series({
            "n_direct": int((~x.indirect).sum()),
            "n_indirect": int(x.indirect.sum()),
            "rate_direct": x.loc[~x.indirect, "rate"].median(),
            "rate_indirect": x.loc[x.indirect, "rate"].median(),
            "usd_direct": x.loc[~x.indirect, "usd"].sum(),
            "usd_indirect": x.loc[x.indirect, "usd"].sum(),
            "sym_in": x.sym_in.iloc[0],
            "sym_out": x.sym_out.iloc[0],
            "mid_native_share": float(
                np.mean([classify(m)[1] == "native" for m in x.loc[x.indirect, "mid"] if isinstance(m, str)])
            ) if x.indirect.any() and any(
                isinstance(m, str) for m in x.loc[x.indirect, "mid"]) else np.nan,
        }), include_groups=False
    ).reset_index()

    both = agg[(agg.n_direct >= MIN_PER_SIDE) & (agg.n_indirect >= MIN_PER_SIDE)].copy()
    if both.empty:
        return None
    # positive gap = direct realises a better rate = direct dominates on rate
    both["gap_bps"] = 1e4 * (both.rate_direct - both.rate_indirect) / both.rate_indirect
    both["dominated"] = both.gap_bps >= GAP_BPS
    both["indirect_usd_share"] = both.usd_indirect / (both.usd_direct + both.usd_indirect)
    return both


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--stride", type=int, default=1, help="sample every Nth day")
    args = ap.parse_args()

    days = sorted(UNIFIED.glob("*.parquet"))[:: args.stride]
    if args.limit:
        days = days[: args.limit]
    print(f"scanning {len(days):,} days with {args.workers} workers", flush=True)

    parts = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one_day, d): d for d in days}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r is not None and len(r):
                parts.append(r)
            if i % 200 == 0:
                print(f"  {i:,}/{len(days):,}", flush=True)

    if not parts:
        sys.exit("no comparable cells found")
    cells = pd.concat(parts, ignore_index=True).sort_values("date")

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(OUT_PARQUET, index=False)

    n = len(cells)
    dom = cells[cells.dominated]
    print(f"\ncomparable cells (both routes, >={MIN_PER_SIDE} trades each side): {n:,}")
    print(f"pairs covered: {cells.groupby(['token_in','token_out']).ngroups:,}")
    print(f"date range: {cells.date.min().date()} to {cells.date.max().date()}")
    print(f"\ncells where the DIRECT route realises a better rate by >= {GAP_BPS:.0f} bps: "
          f"{len(dom):,} ({100*len(dom)/n:.1f}%)")
    if len(dom):
        print(f"  in those cells, median indirect volume share: {dom.indirect_usd_share.median():.1%}")
        print(f"  cells where direct dominates AND indirect still carries >50% of volume: "
              f"{int((dom.indirect_usd_share > 0.5).sum()):,} "
              f"({100*(dom.indirect_usd_share > 0.5).mean():.1f}% of dominated cells)")
        print(f"  median gap in dominated cells: {dom.gap_bps.median():.0f} bps")
        print(f"  median native-intermediary share in dominated cells: "
              f"{dom.mid_native_share.median():.1%}")

    print("\nby size bin:")
    for b in BIN_LABELS:
        s = cells[cells.size_bin == b]
        if not len(s):
            continue
        d = s[s.dominated]
        print(f"  {b:>9}  cells {len(s):7,}  dominated {100*len(d)/len(s):5.1f}%"
              f"  median indirect share in dominated {d.indirect_usd_share.median() if len(d) else float('nan'):.1%}")

    print("\nby year:")
    yr = cells.set_index("date").groupby([pd.Grouper(freq="YS")])
    summary = []
    for idx, s in yr:
        idx = idx[0] if isinstance(idx, tuple) else idx
        d = s[s.dominated]
        row = {"year": idx.year, "cells": len(s),
               "pct_dominated": 100 * len(d) / len(s) if len(s) else np.nan,
               "median_indirect_share_in_dominated": d.indirect_usd_share.median() if len(d) else np.nan,
               "persistent_cells": int((d.indirect_usd_share > 0.5).sum())}
        summary.append(row)
        print(f"  {row['year']}  cells {row['cells']:7,}  dominated {row['pct_dominated']:5.1f}%"
              f"  median indirect share {row['median_indirect_share_in_dominated']:6.1%}"
              f"  persistent {row['persistent_cells']:6,}")
    pd.DataFrame(summary).to_parquet(OUT_CSV, index=False)
    print(f"\nwrote {OUT_PARQUET.relative_to(ROOT)} and {OUT_CSV.relative_to(ROOT)}")
    print("\nREAD THIS BEFORE USING THE NUMBERS: rates are gross of gas, so a "
          "two-hop route losing on rate may still win all-in. This is an upper "
          "bound on cost dominance and the gas-inclusive version is required "
          "before any claim reaches a paper.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Daily share of intermediation captured by each candidate asset, and by asset TYPE.

The paper's central descriptive question: when a trade passes through an
intermediary, which asset does it pass through, and has that migrated over the
sample from the native platform asset toward the stable numeraire? That is the
dominance-transition question of the FX literature, measured directly.

Asset types come from src/ddvc/asset_types.py, which holds the taxonomy, the
address lists, and the registered specification alternatives. The claim is about
currency TYPES; tickers are proxies for a type and never the object of interest.

Intermediary extraction. For a reconstructed route with legs A->K->B the
intermediary is K. For A->K1->K2->B both K1 and K2 intermediate, so every
interior token is counted once per route. A route contributes its notional to
each interior token it uses, so type shares are shares of intermediation
episodes rather than a partition of trade value.

Filters, matching scripts/build_cross_venue_routing_series.py so the two series
are comparable: multi-leg routes only, and round trips (first input token equal
to last output token) excluded as atomic arbitrage or wash trading. That filter
is not cosmetic here either; round trips concentrate in the native asset and
would inflate its measured intermediation share.

Reads   data/unified/YYYYMMDD.parquet
Writes  data/processed/intermediation_by_type_daily.parquet
        output/exhibits/intermediation_by_type.jsonl

Run     .venv/bin/python scripts/build_intermediation_by_type.py [--workers N]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
UNIFIED = ROOT / "data" / "unified"
OUT_PARQUET = ROOT / "data" / "processed" / "intermediation_by_type_daily.parquet"
OUT_EXHIBIT = ROOT / "output" / "exhibits" / "intermediation_by_type.jsonl"

from ddvc.asset_types import TYPES, classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

COLS = ["tx_hash", "component_id", "token_in", "token_out", "amount_usd", "log_index"]


def one_day(path: Path) -> dict | None:
    try:
        df = pd.read_parquet(path, columns=COLS)
    except Exception as exc:
        return {"date": path.stem, "error": str(exc)[:120]}
    if df.empty:
        return None

    # leg order within a route matters for identifying interior tokens
    df = df.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    g = df.groupby(["tx_hash", "component_id"], sort=False)

    legs = g.size()
    multi = legs[legs > 1].index
    if len(multi) == 0:
        return {"date": pd.to_datetime(path.stem, format="%Y%m%d"),
                "routes_intermediated": 0}

    sub = df.set_index(["tx_hash", "component_id"]).loc[multi]
    n_routes = 0
    cnt: Counter = Counter()
    val: Counter = Counter()
    tok_cnt: Counter = Counter()

    for _, r in sub.groupby(level=[0, 1], sort=False):
        tin = r["token_in"].tolist()
        tout = r["token_out"].tolist()
        if tin[0] == tout[-1]:
            continue  # round trip: atomic arbitrage or wash, no value moved
        n_routes += 1
        notional = float(r["amount_usd"].max())
        # interior tokens: every output that is not the route's final output
        interior = {t for t in tout[:-1] if t}
        for tok in interior:
            sym, typ = classify(tok)
            cnt[typ] += 1
            val[typ] += notional
            if sym:
                tok_cnt[sym] += 1

    out = {"date": pd.to_datetime(path.stem, format="%Y%m%d"),
           "routes_intermediated": n_routes,
           "episodes": int(sum(cnt.values()))}
    for t in TYPES:
        out[f"cnt_{t}"] = int(cnt.get(t, 0))
        out[f"usd_{t}"] = float(val.get(t, 0.0))
    for sym, n in tok_cnt.items():
        out[f"cnt_{sym}"] = int(n)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    days = sorted(UNIFIED.glob("*.parquet"))
    if args.limit:
        days = days[: args.limit]
    if not days:
        sys.exit(f"no unified day files under {UNIFIED}")
    print(f"reducing {len(days):,} days with {args.workers} workers", flush=True)

    rows, errors = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one_day, d): d for d in days}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r is None:
                continue
            (errors if "error" in r else rows).append(r)
            if i % 250 == 0:
                print(f"  {i:,}/{len(days):,}", flush=True)

    if errors:
        print(f"\n{len(errors)} day(s) failed:")
        for e in errors[:5]:
            print("  ", e["date"], e["error"])

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df = df[df.get("episodes", 0) > 0].copy()
    for t in TYPES:
        df[f"share_{t}"] = df[f"cnt_{t}"] / df["episodes"]

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_EXHIBIT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    write_exhibit(df, OUT_EXHIBIT)

    y = df.set_index("date").resample("YS").agg(
        {**{f"cnt_{t}": "sum" for t in TYPES},
         **{f"usd_{t}": "sum" for t in TYPES},
         "episodes": "sum", "routes_intermediated": "sum"}
    )
    print(f"\ndays: {len(df):,}   {df.date.min().date()} to {df.date.max().date()}")
    print(f"intermediated routes: {df.routes_intermediated.sum():,}   "
          f"intermediation episodes: {df.episodes.sum():,}")
    hdr = "  year " + "".join(f"{t:>15}" for t in TYPES)
    print("\nshare of intermediation episodes by asset TYPE (count-weighted):")
    print(hdr)
    for idx, r in y.iterrows():
        tot = r.episodes or 1
        print(f"  {idx.year} " + "".join(f"{r[f'cnt_{t}']/tot:14.1%} " for t in TYPES))
    print("\nsame, value-weighted (secondary; see the round-trip caveat):")
    print(hdr)
    for idx, r in y.iterrows():
        tot = sum(r[f"usd_{t}"] for t in TYPES) or 1
        print(f"  {idx.year} " + "".join(f"{r[f'usd_{t}']/tot:14.1%} " for t in TYPES))
    print(f"\nwrote {OUT_PARQUET.relative_to(ROOT)} and {OUT_EXHIBIT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

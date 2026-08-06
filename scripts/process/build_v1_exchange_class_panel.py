#!/usr/bin/env python3
"""Per-exchange, per-day Uniswap V1 activity split by trade class, plus the forced-route adjacency.

Why this exists rather than reusing `data/processed/v1_exchange_day.parquet`. That panel splits an exchange's daily legs into exactly two buckets, `n_t2t` and `n_pair`, and everything that is not a forced token-to-token route lands in `n_pair`. Liquidity provision and withdrawal (the `no_event` class, 2.19% of V1 transactions), single-pool round trips (0.44%) and three-or-more-exchange transactions (0.50%) are therefore counted as ETH-paired swaps. That is harmless for the aggregate shares in `docs/finding-v1-forced-vehicle.md` section 2, but the token-level test in section 8 needs a clean denominator, because its outcome variable is the decay of an exchange's OWN ETH-paired swap flow and its treatment is the share of its flow that was forced routing. Mixing liquidity events into the outcome would put fund flows into a trade-count series, and mixing them into the denominator of the treatment would shrink the treatment toward zero by an amount that varies across exchanges with how often their LPs rebalanced.

The forced-route signature is the one established in section 1 and is not the one the original brief for that work stated. The V1 subgraph keys `transaction` on `txhash-exchangeAddress`, so a token-to-token trade calls `tokenToEthSwap` on exchange A and `ethToTokenSwap` on exchange B and materialises as TWO rows sharing one transaction hash, one carrying only `ethPurchaseEvents` and one carrying only `tokenPurchaseEvents`. A single row carrying BOTH arrays is a round trip through one pool and is not a forced route.

Directionality is kept. In a forced route the sell leg is the exchange whose token was the input and the buy leg is the exchange whose token was the output, so an exchange can be a forced-routing SOURCE, a forced-routing DESTINATION, or both, and the two are separately visible here.

Reads   data/raw/thegraph/uniswap_v1/uniswap_v1_swaps_YYYYMMDD.jsonl.gz
Writes  data/processed/v1_exchange_class_day.parquet   one row per exchange-day, legs and ETH by class
        data/processed/v1_t2t_route_pairs_daily.parquet  one row per (day, sell exchange, buy exchange)

Run     ./scripts/run scripts/process/build_v1_exchange_class_panel.py [--workers N]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc import provenance
from ddvc.tables import write_panel

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "data" / "raw" / "thegraph" / "uniswap_v1"
OUT_EXCH = ROOT / "data" / "processed" / "v1_exchange_class_day.parquet"
OUT_PAIRS = ROOT / "data" / "processed" / "v1_t2t_route_pairs_daily.parquet"

# Same tolerance as scripts/build_v1_forced_vehicle.py: the ETH sold on one exchange is
# the ETH spent on the other, so legs agreeing beyond rounding is the physical evidence
# that a route happened rather than a bot bundling two unrelated swaps.
STRICT_TOL = 0.01

COUNT_COLS = ("n_e2t", "n_t2e", "n_t2t_sell", "n_t2t_buy", "n_t2t_strict",
              "n_rt", "n_multi", "n_noevent")
ETH_COLS = ("eth_e2t", "eth_t2e", "eth_t2t", "eth_rt", "eth_multi")


def _day(path: Path) -> str:
    return path.name.split("_")[-1].split(".")[0]


def _f(x: object) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _blank() -> dict[str, float]:
    return {c: 0.0 for c in COUNT_COLS + ETH_COLS}


def one_day(path: Path) -> dict | None:
    """Classify one day of V1 transactions and attribute each leg to its exchange."""
    try:
        with gzip.open(path, "rt") as fh:
            rows = [json.loads(line) for line in fh]
    except (OSError, EOFError, json.JSONDecodeError) as exc:
        return {"date": _day(path), "error": f"{type(exc).__name__}: {exc}"[:160]}
    if not rows:
        return None

    by_tx: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_tx[str(r.get("id", "")).split("-")[0]].append(r)

    exch: dict[str, dict[str, float]] = defaultdict(_blank)
    pairs: dict[tuple[str, str], int] = defaultdict(int)
    n_tx = 0
    n_t2t = 0

    for legs in by_tx.values():
        desc = []
        for r in legs:
            ep = r.get("ethPurchaseEvents") or []
            tp = r.get("tokenPurchaseEvents") or []
            desc.append({
                "ex": r.get("exchangeAddress"),
                "n_ep": len(ep), "n_tp": len(tp),
                "eth_ep": sum(_f(e.get("ethAmount")) for e in ep),
                "eth_tp": sum(_f(e.get("ethAmount")) for e in tp),
            })
        n_tx += 1
        sells = [d for d in desc if d["n_ep"] and not d["n_tp"]]   # token -> ETH
        buys = [d for d in desc if d["n_tp"] and not d["n_ep"]]    # ETH -> token
        boths = [d for d in desc if d["n_tp"] and d["n_ep"]]

        if len(desc) == 2 and len(sells) == 1 and len(buys) == 1:
            s, b = sells[0], buys[0]
            a, c = s["eth_ep"], b["eth_tp"]
            strict = a > 0 and c > 0 and abs(a - c) / max(a, c) <= STRICT_TOL
            exch[s["ex"]]["n_t2t_sell"] += 1
            exch[s["ex"]]["eth_t2t"] += a
            exch[b["ex"]]["n_t2t_buy"] += 1
            exch[b["ex"]]["eth_t2t"] += c
            if strict:
                exch[s["ex"]]["n_t2t_strict"] += 1
                exch[b["ex"]]["n_t2t_strict"] += 1
            pairs[(str(s["ex"]), str(b["ex"]))] += 1
            n_t2t += 1
            continue
        if len(desc) == 1 and boths:
            exch[desc[0]["ex"]]["n_rt"] += 1
            exch[desc[0]["ex"]]["eth_rt"] += max(desc[0]["eth_ep"], desc[0]["eth_tp"])
            continue
        if len(desc) == 1 and buys:
            exch[desc[0]["ex"]]["n_e2t"] += 1
            exch[desc[0]["ex"]]["eth_e2t"] += desc[0]["eth_tp"]
            continue
        if len(desc) == 1 and sells:
            exch[desc[0]["ex"]]["n_t2e"] += 1
            exch[desc[0]["ex"]]["eth_t2e"] += desc[0]["eth_ep"]
            continue
        if len(desc) == 1:
            exch[desc[0]["ex"]]["n_noevent"] += 1
            continue
        for d in desc:
            exch[d["ex"]]["n_multi"] += 1
            exch[d["ex"]]["eth_multi"] += max(d["eth_ep"], d["eth_tp"])

    return {
        "date": _day(path), "n_rows": len(rows), "n_tx": n_tx, "n_t2t": n_t2t,
        "_exch": [{"exchange": k, **v} for k, v in exch.items()],
        "_pairs": [{"sell_exchange": a, "buy_exchange": b, "n": n}
                   for (a, b), n in pairs.items()],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    days = sorted(V1.glob("uniswap_v1_swaps_*.jsonl.gz"))
    if not days:
        sys.exit(f"no V1 swaps files under {V1}")
    print(f"V1 swap days: {len(days):,}", flush=True)

    ok, err = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one_day, d): d for d in days}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r is None:
                continue
            (err if "error" in r else ok).append(r)
            if i % 500 == 0:
                print(f"  {i:,}/{len(days):,}", flush=True)
    print(f"days parsed: {len(ok):,}   failed: {len(err):,}")
    for e in err[:5]:
        print("  ", e["date"], e["error"])

    exch = pd.DataFrame([{"date": r["date"], **d} for r in ok for d in r["_exch"]])
    prs = pd.DataFrame([{"date": r["date"], **d} for r in ok for d in r["_pairs"]])
    exch["date"] = pd.to_datetime(exch["date"], format="%Y%m%d")
    prs["date"] = pd.to_datetime(prs["date"], format="%Y%m%d")
    for c in COUNT_COLS:
        exch[c] = exch[c].astype("int64")
    exch = exch.sort_values(["exchange", "date"]).reset_index(drop=True)
    prs = prs.sort_values(["date", "sell_exchange", "buy_exchange"]).reset_index(drop=True)

    write_panel(exch, OUT_EXCH)
    write_panel(prs, OUT_PAIRS)
    src = ["scripts/process/build_v1_exchange_class_panel.py", "src/ddvc/tables.py"]
    provenance.stamp(OUT_EXCH, code_sources=src, rows=len(exch),
                     notes="per-exchange-day V1 legs by trade class")
    provenance.stamp(OUT_PAIRS, code_sources=src, rows=len(prs),
                     notes="daily forced-route adjacency, sell exchange to buy exchange")

    tot_tx = sum(r["n_tx"] for r in ok)
    print(f"\ntransactions {tot_tx:,}   forced routes {sum(r['n_t2t'] for r in ok):,}   "
          f"entity rows {sum(r['n_rows'] for r in ok):,}")
    print(f"exchange-days {len(exch):,} over {exch.exchange.nunique():,} exchanges, "
          f"{exch.date.min().date()} to {exch.date.max().date()}")
    print(f"route-pair-days {len(prs):,} over "
          f"{prs.groupby(['sell_exchange', 'buy_exchange']).ngroups:,} ordered pairs")
    print("\nlegs by class, whole sample:")
    for c in COUNT_COLS:
        print(f"  {c:<14}{int(exch[c].sum()):>12,}")
    print(f"\nwrote {OUT_EXCH.relative_to(ROOT)}, {OUT_PAIRS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Uniswap V1's forced-vehicle architecture: classify every V1 transaction by trade direction.

Why this exists. Uniswap V1 gave each ERC20 token exactly one exchange contract holding an ETH<->token pair, so a token-to-token trade had no direct pool and was routed through ETH by the protocol itself. ETH was therefore a MANDATED vehicle currency on V1, not a chosen one. Uniswap V2 (2020-05-05) allowed arbitrary ERC20/ERC20 pairs and removed the mandate. That is an architectural discontinuity in this paper's dependent variable, and measuring it needs a per-transaction classification of V1 flow into ETH->token, token->ETH, and token->token-via-ETH.

The institutional premise has to be verified before anything is built on it, because the obvious reading of the subgraph schema is wrong. The V1 subgraph keys its `transaction` entity on `txhash-exchangeAddress`, so a token-to-token trade, which calls tokenToEthSwap on exchange A and then ethToTokenSwap on exchange B inside one transaction, materialises as TWO rows sharing a tx hash: one carrying only `ethPurchaseEvents` (token sold for ETH) and one carrying only `tokenPurchaseEvents` (ETH spent on token). It does NOT materialise as a single row carrying both event arrays. Rows carrying both arrays exist but are rare and are a different object (one exchange traded in both directions inside one transaction, i.e. a round trip through a single pool). This script measures both signatures separately and reports the ETH-amount agreement between the two legs of a candidate token-to-token route, which is the direct evidence that ETH physically flowed from one exchange to the other rather than the two legs being unrelated.

Volume is denominated in ETH throughout, not USD. Every V1 event reports `ethAmount`, so ETH is the natively common unit and using it sidesteps the repriced-junk-token problem that has repeatedly produced absurd notionals in this project. A USD series is attached from V1's own daily stream (ethUSD = price * tokenPriceUSD, median across exchanges on the day) and is reported as secondary.

For a forced token-to-token route the ETH leg is counted ONCE, at the mean of the two legs' ethAmount, because the same ETH is both sold and spent. Counting both would double the measured routing volume.

Reads   data/raw/thegraph/uniswap_v1/uniswap_v1_swaps_YYYYMMDD.jsonl.gz
        data/raw/thegraph/uniswap_v1/uniswap_v1_daily_YYYYMMDD.jsonl.gz
Writes  data/processed/v1_trade_classes_daily.parquet
        data/processed/v1_exchange_day.parquet
        output/exhibits/v1_trade_classes_daily.jsonl

Run     ./scripts/run scripts/process/build_v1_forced_vehicle.py [--workers N]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.tables import write_exhibit

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "data" / "raw" / "thegraph" / "uniswap_v1"
OUT_DAILY = ROOT / "data" / "processed" / "v1_trade_classes_daily.parquet"
OUT_EXCH = ROOT / "data" / "processed" / "v1_exchange_day.parquet"
OUT_EXHIBIT = ROOT / "output" / "exhibits" / "v1_trade_classes_daily.jsonl"

# Trade classes. The first three are the partition the paper cares about; the
# last three are residual patterns kept visible rather than folded away, because
# silently bucketing them is how a mandate claim gets overstated.
CLASSES = (
    "eth_to_token",      # one exchange, tokenPurchase only: ETH sold for a token
    "token_to_eth",      # one exchange, ethPurchase only: token sold for ETH
    "token_to_token",    # two exchanges, one each direction: FORCED route via ETH
    "same_exchange_rt",  # one exchange carrying both directions: round trip
    "multi_exchange",    # three or more exchanges, or any other mixed pattern
    "no_event",          # NOT a swap: liquidity add/remove, fee == 0, no events
)

# `no_event` transactions carry neither event array and a zero fee, and inspection
# confirms they are liquidity provision and withdrawal: the V1 subgraph's
# `transaction` entity covers those alongside swaps. They ran 12.6% of entity rows
# on the first days of the sample, so leaving them in the denominator would deflate
# every trade-class share. Shares below are taken over SWAP transactions only.
SWAP_CLASSES = tuple(c for c in CLASSES if c != "no_event")

# `token_to_token_strict` is a subset of `token_to_token`, reported alongside it and
# never added to the partition. Tolerance on the two legs' ETH amounts: the routed
# ETH is identical by construction, so anything above rounding is a different object.
STRICT_TOL = 0.01
EXTRA = ("token_to_token_strict",)


def _day(path: Path) -> str:
    """YYYYMMDD out of uniswap_v1_<stream>_YYYYMMDD.jsonl.gz. `Path.stem` only strips
    one suffix, so it leaves `.jsonl` attached and slicing the stem yields garbage."""
    return path.name.split("_")[-1].split(".")[0]


def _f(x: object) -> float:
    try:
        return float(x)  # noqa: TRY300
    except (TypeError, ValueError):
        return 0.0


def _frac_digits(x: object) -> int:
    """Fractional digits in a subgraph BigDecimal string.

    Carried because it is the only identifying signal about a V1 exchange's token
    besides its price. The Graph prints a token amount as the raw integer divided by
    10**decimals with no padding, so the fractional digit count is at most the token's
    decimals and equals them whenever the last raw digit is nonzero. Taking the maximum
    across many exchange-days therefore recovers the token's decimals, which separates
    the six-decimal stablecoins from the eighteen-decimal ones that a price match alone
    cannot tell apart. Read from the STRING: float() would destroy the precision.
    """
    if not isinstance(x, str) or "." not in x:
        return 0
    return len(x.split(".", 1)[1].rstrip("0"))


def one_swaps_day(path: Path) -> dict | None:
    """Classify one day of V1 transactions. Returns daily aggregates plus per-exchange rows."""
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

    n_tx = Counter()
    eth_vol = Counter()
    # leg-agreement evidence for the forced-route claim
    agree_num: list[float] = []
    # per-exchange-per-day activity, split by whether the exchange leg was part
    # of a forced token-to-token route or an ETH-paired trade
    exch: dict[str, dict[str, float]] = defaultdict(
        lambda: {"n_pair": 0.0, "n_t2t": 0.0, "eth_pair": 0.0, "eth_t2t": 0.0}
    )
    rows_both = 0
    n_legs = 0

    for legs in by_tx.values():
        # per-leg direction counts and ETH amounts
        desc = []
        for r in legs:
            ep = r.get("ethPurchaseEvents") or []
            tp = r.get("tokenPurchaseEvents") or []
            if ep and tp:
                rows_both += 1
            desc.append(
                {
                    "ex": r.get("exchangeAddress"),
                    "n_ep": len(ep),
                    "n_tp": len(tp),
                    "eth_ep": sum(_f(e.get("ethAmount")) for e in ep),
                    "eth_tp": sum(_f(e.get("ethAmount")) for e in tp),
                }
            )
        n_legs += len(desc)
        sells = [d for d in desc if d["n_ep"] and not d["n_tp"]]   # token -> ETH
        buys = [d for d in desc if d["n_tp"] and not d["n_ep"]]    # ETH -> token
        boths = [d for d in desc if d["n_tp"] and d["n_ep"]]

        if len(desc) == 1 and boths:
            cls = "same_exchange_rt"
            v = max(desc[0]["eth_ep"], desc[0]["eth_tp"])
        elif len(desc) == 1 and buys:
            cls, v = "eth_to_token", desc[0]["eth_tp"]
        elif len(desc) == 1 and sells:
            cls, v = "token_to_eth", desc[0]["eth_ep"]
        elif len(desc) == 1:
            cls, v = "no_event", 0.0
        elif len(desc) == 2 and len(sells) == 1 and len(buys) == 1:
            cls = "token_to_token"
            a, b = sells[0]["eth_ep"], buys[0]["eth_tp"]
            v = 0.5 * (a + b)
            if a > 0 and b > 0:
                gap = abs(a - b) / max(a, b)
                agree_num.append(gap)
                # STRICT forced route: the ETH sold on one exchange is the ETH spent
                # on the other, so the two legs must carry the same amount. A loose
                # pair can instead be two unrelated swaps an arbitrage bot bundled
                # into one transaction, which is not a routed trade at all.
                if gap <= STRICT_TOL:
                    n_tx["token_to_token_strict"] += 1
                    eth_vol["token_to_token_strict"] += v
        else:
            cls = "multi_exchange"
            v = max(
                sum(d["eth_ep"] for d in desc), sum(d["eth_tp"] for d in desc)
            )

        n_tx[cls] += 1
        eth_vol[cls] += v
        for d in desc:
            e = exch[d["ex"]]
            if cls == "token_to_token":
                e["n_t2t"] += 1
                e["eth_t2t"] += max(d["eth_ep"], d["eth_tp"])
            else:
                e["n_pair"] += 1
                e["eth_pair"] += max(d["eth_ep"], d["eth_tp"])

    out = {
        "date": _day(path),
        "n_rows": len(rows),
        # CLASSES only: token_to_token_strict is a reported subset, not a partition cell
        "n_tx": int(sum(n_tx[c] for c in CLASSES)),
        "n_legs": n_legs,
        "rows_both_arrays": rows_both,
        "n_exchanges": len(exch),
        "t2t_leg_agree_n": len(agree_num),
        "t2t_leg_agree_median": (
            float(pd.Series(agree_num).median()) if agree_num else float("nan")
        ),
        "t2t_leg_agree_p99": (
            float(pd.Series(agree_num).quantile(0.99)) if agree_num else float("nan")
        ),
        "t2t_leg_exact_share": (
            float((pd.Series(agree_num) < 1e-9).mean()) if agree_num else float("nan")
        ),
    }
    for c in CLASSES + EXTRA:
        out[f"n_{c}"] = int(n_tx.get(c, 0))
        out[f"eth_{c}"] = float(eth_vol.get(c, 0.0))
    out["_exchanges"] = [{"exchange": k, **v} for k, v in exch.items()]
    return out


def one_daily_day(path: Path) -> dict | None:
    """Per-exchange price and liquidity snapshot, plus the day's implied ETH/USD."""
    try:
        with gzip.open(path, "rt") as fh:
            rows = [json.loads(line) for line in fh]
    except (OSError, EOFError, json.JSONDecodeError) as exc:
        return {"date": _day(path), "error": f"{type(exc).__name__}: {exc}"[:160]}
    if not rows:
        return None
    # last observation of the day per exchange
    rows.sort(key=lambda r: int(r.get("timestamp") or 0))
    last: dict[str, dict] = {}
    eth_usd: list[float] = []
    # decimals evidence takes the max over EVERY row of the day, not just the last
    # one, since a single snapshot can end in a zero digit and understate decimals
    fd: dict[str, int] = defaultdict(int)
    for r in rows:
        ex = r.get("exchangeAddress")
        last[ex] = r
        fd[ex] = max(
            fd[ex],
            _frac_digits(r.get("tokenBalance")),
            _frac_digits(r.get("tokenLiquidity")),
            _frac_digits(r.get("tradeVolumeToken")),
        )
        p, tu = _f(r.get("price")), _f(r.get("tokenPriceUSD"))
        if p > 0 and tu > 0:
            eth_usd.append(p * tu)
    recs = [
        {
            "date": _day(path),
            "exchange": ex,
            "token_price_usd": _f(r.get("tokenPriceUSD")),
            "price_token_per_eth": _f(r.get("price")),
            "eth_liquidity": _f(r.get("ethLiquidity")),
            "token_liquidity": _f(r.get("tokenLiquidity")),
            "combined_balance_eth": _f(r.get("combinedBalanceInEth")),
            "token_frac_digits": fd[ex],
        }
        for ex, r in last.items()
    ]
    return {
        "date": _day(path),
        "eth_usd": float(pd.Series(eth_usd).median()) if eth_usd else float("nan"),
        "n_price_obs": len(eth_usd),
        "_recs": recs,
    }


def _run(fn, paths: list[Path], workers: int, label: str) -> tuple[list[dict], list[dict]]:
    ok, err = [], []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fn, p): p for p in paths}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r is None:
                continue
            (err if "error" in r else ok).append(r)
            if i % 500 == 0:
                print(f"  {label} {i:,}/{len(paths):,}", flush=True)
    return ok, err


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    swaps = sorted(V1.glob("uniswap_v1_swaps_*.jsonl.gz"))
    dailies = sorted(V1.glob("uniswap_v1_daily_*.jsonl.gz"))
    if args.limit:
        swaps, dailies = swaps[: args.limit], dailies[: args.limit]
    if not swaps:
        sys.exit(f"no V1 swaps files under {V1}")
    print(f"V1 swaps days: {len(swaps):,}   daily days: {len(dailies):,}", flush=True)

    srows, serr = _run(one_swaps_day, swaps, args.workers, "swaps")
    drows, derr = _run(one_daily_day, dailies, args.workers, "daily")
    for name, e in (("swaps", serr), ("daily", derr)):
        if e:
            print(f"\n{len(e)} {name} day(s) failed to parse:")
            for x in e[:5]:
                print("  ", x["date"], x["error"])

    exch_rows = [
        {"date": r["date"], **d} for r in srows for d in r.pop("_exchanges")
    ]
    price_rows = [d for r in drows for d in r.pop("_recs")]

    daily = pd.DataFrame(srows)
    daily["date"] = pd.to_datetime(daily["date"], format="%Y%m%d")
    px = pd.DataFrame(drows)
    px["date"] = pd.to_datetime(px["date"], format="%Y%m%d")
    daily = daily.merge(px[["date", "eth_usd", "n_price_obs"]], on="date", how="left")
    daily = daily.sort_values("date").reset_index(drop=True)
    for c in CLASSES + EXTRA:
        daily[f"usd_{c}"] = daily[f"eth_{c}"] * daily["eth_usd"]
    daily["n_swap_tx"] = daily["n_tx"] - daily["n_no_event"]

    exch = pd.DataFrame(exch_rows)
    exch["date"] = pd.to_datetime(exch["date"], format="%Y%m%d")
    pxe = pd.DataFrame(price_rows)
    pxe["date"] = pd.to_datetime(pxe["date"], format="%Y%m%d")
    exch = exch.merge(pxe, on=["date", "exchange"], how="outer")
    exch = exch.sort_values(["exchange", "date"]).reset_index(drop=True)

    OUT_DAILY.parent.mkdir(parents=True, exist_ok=True)
    OUT_EXHIBIT.parent.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(OUT_DAILY, index=False)
    exch.to_parquet(OUT_EXCH, index=False)
    write_exhibit(daily, OUT_EXHIBIT)

    tot_tx = daily["n_tx"].sum()
    tot_swap = daily["n_swap_tx"].sum()
    print(f"\ndays with data: {len(daily):,}   "
          f"{daily.date.min().date()} to {daily.date.max().date()}")
    print(f"transactions: {tot_tx:,}   of which swaps: {tot_swap:,}   "
          f"entity rows: {daily.n_rows.sum():,}   legs: {daily.n_legs.sum():,}")
    print(f"non-swap (liquidity) transactions dropped from shares: "
          f"{daily.n_no_event.sum():,} ({daily.n_no_event.sum() / max(tot_tx, 1):.2%})")
    print(f"rows carrying BOTH event arrays: {daily.rows_both_arrays.sum():,} "
          f"({daily.rows_both_arrays.sum() / max(daily.n_rows.sum(), 1):.4%} of rows)")

    print("\nshare of V1 SWAP transactions and of ETH volume by trade class, whole sample:")
    print(f"  {'class':<18}{'n_tx':>12}{'share':>9}{'eth_vol':>16}{'share':>9}")
    tot_eth = sum(daily[f"eth_{c}"].sum() for c in SWAP_CLASSES)
    for c in SWAP_CLASSES:
        n, v = daily[f"n_{c}"].sum(), daily[f"eth_{c}"].sum()
        print(f"  {c:<18}{n:>12,}{n / max(tot_swap, 1):>8.2%}{v:>16,.0f}"
              f"{v / max(tot_eth, 1):>9.2%}")

    ag = daily.dropna(subset=["t2t_leg_agree_median"])
    w = ag["t2t_leg_agree_n"]
    print("\nforced-route verification: |ethAmount(sell leg) - ethAmount(buy leg)| / max")
    print(f"  candidate token->token routes with both legs priced: "
          f"{int(ag.t2t_leg_agree_n.sum()):,}")
    print(f"  volume-weighted mean of daily medians: "
          f"{(ag.t2t_leg_agree_median * w).sum() / w.sum():.3e}")
    print(f"  share of routes with the two legs EXACTLY equal: "
          f"{(ag.t2t_leg_exact_share * w).sum() / w.sum():.2%}")
    print(f"  share within {STRICT_TOL:.0%} (the strict forced-route definition): "
          f"{daily.n_token_to_token_strict.sum() / max(daily.n_token_to_token.sum(), 1):.2%}")

    yr = daily.set_index("date").resample("YS").agg(
        {**{f"n_{c}": "sum" for c in CLASSES + EXTRA},
         **{f"eth_{c}": "sum" for c in CLASSES + EXTRA}, "n_swap_tx": "sum"}
    )
    print("\ntoken->token (forced-route) share of V1 swaps, by year:")
    print(f"  {'year':<6}{'swap tx':>12}{'t2t count sh':>14}{'t2t eth sh':>12}"
          f"{'strict count sh':>17}")
    for idx, r in yr.iterrows():
        eth_tot = sum(r[f"eth_{c}"] for c in SWAP_CLASSES) or 1
        print(f"  {idx.year:<6}{int(r.n_swap_tx):>12,}"
              f"{r.n_token_to_token / max(r.n_swap_tx, 1):>13.2%}"
              f"{r.eth_token_to_token / eth_tot:>12.2%}"
              f"{r.n_token_to_token_strict / max(r.n_swap_tx, 1):>16.2%}")

    print(f"\nwrote {OUT_DAILY.relative_to(ROOT)}, {OUT_EXCH.relative_to(ROOT)}, "
          f"{OUT_EXHIBIT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

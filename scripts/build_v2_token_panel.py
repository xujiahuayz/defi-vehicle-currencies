#!/usr/bin/env python3
"""Uniswap V2 token panel: daily USD prices, decimals, and the arrival date of every pair.

Why this exists. Two questions about the V1-to-V2 architectural discontinuity need V2-side inputs that no existing artefact in this repo supplies.

First, the exchange-to-token crosswalk. The V1 raw fetch (see `src/ddvc/fetch/schemas.py`) requested `exchangeAddress` but never `tokenAddress`, and the V1 `meta` files hold only fetch provenance. So NOTHING in this repo maps a V1 exchange contract to the token it held, and no such mapping can be recovered by lookup. What the V1 daily stream does carry per exchange per day is `tokenPriceUSD` and a token balance printed at the token's own decimal precision. Both are identifying signals against a V2 token panel, so this script builds that panel: a daily median USD price per token, and a token decimals map. Identification is then a price-series match under a decimals constraint, executed in `scripts/run_v1_forced_vehicle_tests.py`, which reports its resolution rate rather than assuming success.

Second, pair arrival. The sharpest test of voluntary vehicle persistence asks how long ETH stayed the routing intermediary between two tokens AFTER a direct non-ETH pair between them became available. That needs, per unordered token pair, the first date the pair traded on V2.

Availability is dated at FIRST TRADE, not pair creation, because the `swaps` stream is 329 MB against 2.4 GB for `hourly_reserves` and a pair that has never traded is weak evidence of a usable alternative. This dates availability weakly LATE, which shortens any measured persistence window, so it biases against finding persistence rather than manufacturing it. The direction is stated where the result is reported.

Token USD prices come from `amountUSD` divided by the token amount on the same side of the swap, medianed within a token-day. The subgraph's own `amountUSD` is used rather than a reconstruction, so the price panel inherits whatever repricing failures the subgraph has; that is the reason the crosswalk demands a decimals match as well as a price match, and the reason unresolved exchanges are reported as unresolved instead of matched loosely.

Reads   data/raw/thegraph/uniswap_v2/uniswap_v2_swaps_YYYYMMDD.jsonl.gz
        data/raw/thegraph/uniswap_v2/uniswap_v2_hourly_reserves_YYYYMMDD.jsonl.gz (sampled)
Writes  data/processed/v2_token_price_daily.parquet
        data/processed/v2_token_decimals.parquet
        data/processed/v2_pair_first_trade.parquet

Run     ./scripts/run scripts/build_v2_token_panel.py [--workers N] [--until YYYYMMDD]
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "data" / "raw" / "thegraph" / "uniswap_v2"
OUT_PRICE = ROOT / "data" / "processed" / "v2_token_price_daily.parquet"
OUT_DEC = ROOT / "data" / "processed" / "v2_token_decimals.parquet"
OUT_PAIR = ROOT / "data" / "processed" / "v2_pair_first_trade.parquet"

# Trades below this USD notional give a price built from a tiny denominator and are
# dropped from the price panel; they are the main source of absurd implied prices.
MIN_TRADE_USD = 50.0
# Days of hourly_reserves sampled for the decimals map. Decimals never change, so a
# spread sample suffices and reading all 2.4 GB to learn a constant is waste.
DECIMALS_SAMPLE = 60


def _day(path: Path) -> str:
    return path.name.split("_")[-1].split(".")[0]


def _f(x: object) -> float:
    try:
        return float(x)  # noqa: TRY300
    except (TypeError, ValueError):
        return 0.0


def one_swaps_day(path: Path) -> dict | None:
    """Median USD price per token, and every (token0, token1) pair that traded."""
    try:
        with gzip.open(path, "rt") as fh:
            rows = [json.loads(line) for line in fh]
    except (OSError, EOFError, json.JSONDecodeError) as exc:
        return {"date": _day(path), "error": f"{type(exc).__name__}: {exc}"[:160]}
    if not rows:
        return None

    px: dict[str, list[float]] = defaultdict(list)
    sym: dict[str, str] = {}
    pairs: dict[tuple[str, str], dict] = {}
    kept = dropped_small = dropped_nonpos = 0

    for r in rows:
        pr = r.get("pair") or {}
        t0, t1 = pr.get("token0") or {}, pr.get("token1") or {}
        a0, a1 = str(t0.get("id") or "").lower(), str(t1.get("id") or "").lower()
        if not a0 or not a1:
            continue
        for a, t in ((a0, t0), (a1, t1)):
            s = t.get("symbol")
            if s and a not in sym:
                sym[a] = s
        key = (a0, a1) if a0 < a1 else (a1, a0)
        p = pairs.setdefault(key, {"n": 0, "usd": 0.0, "sym0": sym.get(key[0]),
                                   "sym1": sym.get(key[1])})
        usd = _f(r.get("amountUSD"))
        p["n"] += 1
        p["usd"] += usd

        if usd < MIN_TRADE_USD:
            dropped_small += 1
            continue
        # amount on each side; a token's traded quantity is its In plus its Out,
        # exactly one of which is nonzero in a well-formed V2 swap
        q0 = _f(r.get("amount0In")) + _f(r.get("amount0Out"))
        q1 = _f(r.get("amount1In")) + _f(r.get("amount1Out"))
        for a, q in ((a0, q0), (a1, q1)):
            if q > 0:
                # each side of the swap is worth the trade's USD value
                px[a].append(usd / q)
                kept += 1
            else:
                dropped_nonpos += 1

    d = _day(path)
    return {
        "date": d,
        "n_swaps": len(rows),
        "price_obs_kept": kept,
        "price_obs_dropped_small": dropped_small,
        "price_obs_dropped_nonpos": dropped_nonpos,
        "_px": [
            {"date": d, "token": a, "symbol": sym.get(a),
             "price_usd": statistics.median(v), "n_obs": len(v)}
            for a, v in px.items()
        ],
        "_pairs": [
            {"date": d, "token0": k[0], "token1": k[1],
             "sym0": v["sym0"], "sym1": v["sym1"],
             "n_swaps": v["n"], "volume_usd": v["usd"]}
            for k, v in pairs.items()
        ],
    }


def one_hourly_day(path: Path) -> dict | None:
    """Harvest the token address to decimals map. Decimals are a contract constant."""
    try:
        with gzip.open(path, "rt") as fh:
            rows = [json.loads(line) for line in fh]
    except (OSError, EOFError, json.JSONDecodeError) as exc:
        return {"date": _day(path), "error": f"{type(exc).__name__}: {exc}"[:160]}
    dec: dict[str, int] = {}
    sym: dict[str, str] = {}
    for r in rows:
        pr = r.get("pair") or {}
        for t in (pr.get("token0") or {}, pr.get("token1") or {}):
            a = str(t.get("id") or "").lower()
            if not a or t.get("decimals") is None:
                continue
            dec[a] = int(t["decimals"])
            if t.get("symbol"):
                sym[a] = t["symbol"]
    return {"date": _day(path), "_dec": [
        {"token": a, "decimals": v, "symbol": sym.get(a)} for a, v in dec.items()]}


def _run(fn, paths: list[Path], workers: int, label: str) -> tuple[list[dict], list[dict]]:
    ok, err = [], []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fn, p): p for p in paths}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r is None:
                continue
            (err if "error" in r else ok).append(r)
            if i % 400 == 0:
                print(f"  {label} {i:,}/{len(paths):,}", flush=True)
    return ok, err


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--until", default=None, help="stop after this YYYYMMDD")
    args = ap.parse_args()

    swaps = sorted(V2.glob("uniswap_v2_swaps_*.jsonl.gz"))
    hourly = sorted(V2.glob("uniswap_v2_hourly_reserves_*.jsonl.gz"))
    if args.until:
        swaps = [p for p in swaps if _day(p) <= args.until]
    if not swaps:
        sys.exit(f"no V2 swaps files under {V2}")
    step = max(1, len(hourly) // DECIMALS_SAMPLE)
    hourly = hourly[::step]
    print(f"V2 swaps days: {len(swaps):,}   hourly days sampled for decimals: "
          f"{len(hourly):,}", flush=True)

    srows, serr = _run(one_swaps_day, swaps, args.workers, "swaps")
    hrows, herr = _run(one_hourly_day, hourly, args.workers, "hourly")
    for name, e in (("swaps", serr), ("hourly", herr)):
        if e:
            print(f"\n{len(e)} {name} day(s) failed to parse:")
            for x in e[:5]:
                print("  ", x["date"], x["error"])

    px = pd.DataFrame([d for r in srows for d in r["_px"]])
    px["date"] = pd.to_datetime(px["date"], format="%Y%m%d")
    px = px.sort_values(["token", "date"]).reset_index(drop=True)

    pairs = pd.DataFrame([d for r in srows for d in r["_pairs"]])
    pairs["date"] = pd.to_datetime(pairs["date"], format="%Y%m%d")
    first = (
        pairs.sort_values("date")
        .groupby(["token0", "token1"], as_index=False)
        .agg(first_trade=("date", "min"), last_trade=("date", "max"),
             days_traded=("date", "nunique"), swaps=("n_swaps", "sum"),
             volume_usd=("volume_usd", "sum"),
             sym0=("sym0", "first"), sym1=("sym1", "first"))
    )

    dec = pd.DataFrame([d for r in hrows for d in r["_dec"]])
    dec = dec.drop_duplicates("token").reset_index(drop=True)

    OUT_PRICE.parent.mkdir(parents=True, exist_ok=True)
    px.to_parquet(OUT_PRICE, index=False)
    dec.to_parquet(OUT_DEC, index=False)
    first.to_parquet(OUT_PAIR, index=False)

    tot_obs = sum(r["price_obs_kept"] for r in srows)
    tot_small = sum(r["price_obs_dropped_small"] for r in srows)
    tot_np = sum(r["price_obs_dropped_nonpos"] for r in srows)
    print(f"\nswaps read: {sum(r['n_swaps'] for r in srows):,}")
    print(f"price observations kept: {tot_obs:,}   "
          f"dropped, trade under ${MIN_TRADE_USD:.0f}: {tot_small:,}   "
          f"dropped, zero token amount: {tot_np:,}")
    print(f"token-days priced: {len(px):,}   distinct tokens: {px.token.nunique():,}")
    print(f"decimals resolved for {len(dec):,} tokens")
    print(f"pairs that ever traded: {len(first):,}   "
          f"{first.first_trade.min().date()} to {first.first_trade.max().date()}")

    weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    n_weth = ((first.token0 == weth) | (first.token1 == weth)).sum()
    print(f"pairs including WETH: {n_weth:,} ({n_weth / len(first):.1%})   "
          f"non-WETH pairs: {len(first) - n_weth:,}")
    print(f"\nwrote {OUT_PRICE.relative_to(ROOT)}, {OUT_DEC.relative_to(ROOT)}, "
          f"{OUT_PAIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

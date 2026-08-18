#!/usr/bin/env python3
"""Uniswap V2 token panel: daily USD prices, decimals, and the arrival date of every pair.

Why this exists. Two questions about the V1-to-V2 architectural discontinuity need V2-side inputs that no existing artefact in this repo supplies.

First, the exchange-to-token crosswalk. The V1 raw fetch (see `src/ddvc/fetch/schemas.py`) requested `exchangeAddress` but never `tokenAddress`, so no direct exchange-to-token map exists. What the V1 daily stream does carry per exchange per day is `tokenPriceUSD` and a token balance printed at the token's own decimal precision. Both are identifying signals against a V2 token panel, so this script builds that panel: a daily median USD price per token, and a token decimals map. Identification is then a price-series match under a decimals constraint, executed in `scripts/analyze/run_v1_forced_vehicle_tests.py`, which reports its resolution rate rather than assuming success.

Second, pair arrival. The sharpest test of voluntary vehicle persistence asks how long ETH stayed the routing intermediary between two tokens AFTER a direct non-ETH pair between them became available. That needs, per unordered token pair, the first date the pair traded on V2.

Availability is dated at FIRST TRADE, not pair creation, because the `swaps` stream is 329 MB against 2.4 GB for `hourly_reserves` and a pair that has never traded is weak evidence of a usable alternative. This dates availability weakly LATE, which shortens any measured persistence window, so it biases against finding persistence rather than manufacturing it. The direction is stated where the result is reported.

Token USD prices come from `amountUSD` divided by the token amount on the same side of the swap, medianed within a token-day. The subgraph's own `amountUSD` is used rather than a reconstruction, so the price panel inherits whatever repricing failures the subgraph has; that is the reason the crosswalk demands a decimals match as well as a price match, and the reason unresolved exchanges are reported as unresolved instead of matched loosely.

Reads   the released canonical Uniswap V2 constant-product state partitions
Writes  data/processed/v2_token_price_daily.parquet
        data/processed/v2_token_decimals.parquet
        data/processed/v2_pair_first_trade.parquet

Run     ./scripts/run scripts/process/build_v2_token_panel.py [--workers N] [--until YYYYMMDD]
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from concurrent.futures import as_completed

import pandas as pd

from ddvc.datasets import (
    PartitionedDataset,
    validate_before_install,
    state_partitions,
)
from ddvc.paths import DATA_DIR, REPO_ROOT, SHARED_RUNTIME_DIR
from ddvc.runtime import bounded_workers, exclusive_job, interruptible_process_pool
from ddvc.state_data import CP_COLUMNS
from ddvc.tables import write_panel

OUT_PRICE = DATA_DIR / "processed" / "v2_token_price_daily.parquet"
OUT_DEC = DATA_DIR / "processed" / "v2_token_decimals.parquet"
OUT_PAIR = DATA_DIR / "processed" / "v2_pair_first_trade.parquet"
LOCK = SHARED_RUNTIME_DIR / "v2-token-panel.lock"
CODE_SOURCES = [
    "scripts/process/build_v2_token_panel.py",
    "src/ddvc/state_data.py",
]

# Trades below this USD notional give a price built from a tiny denominator and are
# dropped from the price panel; they are the main source of absurd implied prices.
MIN_TRADE_USD = 50.0


def _f(x: object) -> float:
    try:
        return float(x)  # noqa: TRY300
    except (TypeError, ValueError):
        return 0.0


def one_swaps_day(day: str, release: PartitionedDataset) -> dict | None:
    """Median USD price per token, and every (token0, token1) pair that traded."""
    state = release.read_day(day)
    swaps = state[state["record_type"].eq("swap")]
    if swaps.empty:
        return None

    px: dict[str, list[float]] = defaultdict(list)
    sym: dict[str, str] = {}
    decimals: dict[str, int] = {}
    pairs: dict[tuple[str, str], dict] = {}
    kept = dropped_small = dropped_nonpos = 0

    snapshots = state[state["record_type"].eq("snapshot")]
    for row in snapshots.itertuples(index=False):
        for token, value in (
            (str(row.token0 or "").lower(), row.decimals0),
            (str(row.token1 or "").lower(), row.decimals1),
        ):
            if not token or pd.isna(value):
                continue
            parsed = int(value)
            if token in decimals and decimals[token] != parsed:
                raise RuntimeError(f"canonical state disagrees on decimals for {token}")
            decimals[token] = parsed

    for row in swaps.itertuples(index=False):
        a0 = str(row.token0 or "").lower()
        a1 = str(row.token1 or "").lower()
        if not a0 or not a1:
            continue
        for a, s in ((a0, row.symbol0), (a1, row.symbol1)):
            if s and a not in sym:
                sym[a] = s
        key = (a0, a1) if a0 < a1 else (a1, a0)
        p = pairs.setdefault(
            key,
            {
                "n": 0,
                "usd": 0.0,
                "sym0": sym.get(key[0]),
                "sym1": sym.get(key[1]),
            },
        )
        usd = _f(row.value_usd)
        p["n"] += 1
        p["usd"] += usd

        if usd < MIN_TRADE_USD:
            dropped_small += 1
            continue
        q0 = abs(_f(row.amount0_delta))
        q1 = abs(_f(row.amount1_delta))
        for a, q in ((a0, q0), (a1, q1)):
            if q > 0:
                # each side of the swap is worth the trade's USD value
                px[a].append(usd / q)
                kept += 1
            else:
                dropped_nonpos += 1

    return {
        "date": day,
        "n_swaps": len(swaps),
        "price_obs_kept": kept,
        "price_obs_dropped_small": dropped_small,
        "price_obs_dropped_nonpos": dropped_nonpos,
        "_px": [
            {"date": day, "token": a, "symbol": sym.get(a),
             "decimals": decimals.get(a), "price_usd": statistics.median(v),
             "n_obs": len(v)}
            for a, v in px.items()
        ],
        "_pairs": [
            {"date": day, "token0": k[0], "token1": k[1],
             "sym0": v["sym0"], "sym1": v["sym1"],
             "n_swaps": v["n"], "volume_usd": v["usd"]}
            for k, v in pairs.items()
        ],
    }


def token_decimals(token_days: pd.DataFrame) -> pd.DataFrame:
    """One conflict-checked decimals row for every canonically priced token."""
    decimals = token_days[["token", "decimals", "symbol"]].dropna(
        subset=["token", "decimals"]
    ).copy()
    decimals["decimals"] = decimals["decimals"].astype(int)
    conflicts = decimals.groupby("token")["decimals"].nunique()
    conflicts = conflicts[conflicts.gt(1)]
    if not conflicts.empty:
        raise RuntimeError(
            f"canonical state disagrees on decimals for {len(conflicts):,} token(s)"
        )
    decimals = decimals.sort_values(["token", "symbol"], na_position="last")
    decimals = decimals.drop_duplicates("token").reset_index(drop=True)
    missing = int(token_days["token"].nunique() - decimals["token"].nunique())
    if missing:
        raise RuntimeError(
            f"canonical snapshots miss decimals for {missing:,} priced token(s)"
        )
    return decimals


def _run(fn, days: list[str], workers: int, label: str, release: PartitionedDataset) -> tuple[list[dict], list[dict]]:
    ok, err = [], []
    with interruptible_process_pool(workers) as pool:
        futs = {
            pool.submit(fn, day, release.select_days((day,))): day
            for day in days
        }
        for i, f in enumerate(as_completed(futs), 1):
            try:
                r = f.result()
            except Exception as exc:
                err.append(
                    {"date": futs[f], "error": f"{type(exc).__name__}: {exc}"[:160]}
                )
                continue
            if r is None:
                continue
            ok.append(r)
            if i % 400 == 0:
                print(f"  {label} {i:,}/{len(days):,}", flush=True)
    return ok, err


def _publish_panels(
    px: pd.DataFrame,
    dec: pd.DataFrame,
    first: pd.DataFrame,
    state_release: PartitionedDataset,
) -> None:
    """Publish independently consumable panels bound to one exact state release."""

    state_inputs = list(state_release.input_paths)
    validator = validate_before_install(state_release)
    release_note = f"released-state identity {state_release.label}"
    outputs = (
        (
            px,
            OUT_PRICE,
            f"daily median token prices from usable canonical Uniswap V2 swaps with at least $50 reported notional; {release_note}",
        ),
        (
            dec,
            OUT_DEC,
            f"conflict-checked token decimals from every usable canonical Uniswap V2 swap pair; {release_note}",
        ),
        (
            first,
            OUT_PAIR,
            f"first and last usable canonical Uniswap V2 swap date per unordered token pair; {release_note}",
        ),
    )
    # Each panel is independently usable and is replaced atomically.
    for frame, output, notes in outputs:
        write_panel(
            frame,
            output,
            code_sources=CODE_SOURCES,
            inputs=state_inputs,
            notes=notes,
            preinstall_validator=validator,
        )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--until", default=None, help="stop after this YYYYMMDD")
    args = ap.parse_args()
    workers = bounded_workers(args.workers)

    state_release = state_partitions("constant_product", "uniswap_v2", CP_COLUMNS)
    swaps = list(state_release.days)
    if args.until:
        swaps = [day for day in swaps if day <= args.until]
    if not swaps:
        print("no released Uniswap V2 state partitions")
        return 1
    print(f"V2 swaps days: {len(swaps):,}", flush=True)

    srows, serr = _run(one_swaps_day, swaps, workers, "swaps", state_release)
    if serr:
        print(f"\n{len(serr)} swap day(s) failed to parse:")
        for error in serr[:5]:
            print("  ", error["date"], error["error"])
        print("refusing partial V2 token panels")
        return 1

    px = pd.DataFrame([d for r in srows for d in r["_px"]])
    px["date"] = pd.to_datetime(px["date"], format="%Y%m%d")
    px = px.sort_values(["token", "date"]).reset_index(drop=True)
    dec = token_decimals(px)
    px = px.drop(columns="decimals")

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

    if args.until is not None:
        print(
            f"bounded construction check complete through {args.until}; canonical outputs unchanged"
        )
        return 0

    state_release.assert_current()
    _publish_panels(px, dec, first, state_release)

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
    print(f"\nwrote {OUT_PRICE.relative_to(REPO_ROOT)}, {OUT_DEC.relative_to(REPO_ROOT)}, "
          f"{OUT_PAIR.relative_to(REPO_ROOT)}")
    state_release.assert_current()
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="V2 token panels"):
        raise SystemExit(main())

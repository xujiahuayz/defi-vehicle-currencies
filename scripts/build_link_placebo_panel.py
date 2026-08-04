#!/usr/bin/env python3
"""Build a placebo panel for LINK (Chainlink) -- a liquid, actively-traded
Ethereum ERC-20 that is explicitly NOT in this repo's 5-token vehicle-candidate
set (VEHICLE_CANDIDATES / VEHICLE_BY_ADDRESS in
src/ddvc/analysis/lp_concentration.py and scripts/run_route_cost_panel.py).

Used by scripts/run_p1_robustness_battery.py, robustness check (i)
(falsification/placebo): if the S~L feedback loop found for the 5 vehicle
candidates is actually a "vehicle-currency" phenomenon and not just "any
liquid token exhibits this because liquidity begets liquidity in any AMM
market," LINK -- which is liquid, has real V3 pools, and is a real
intermediate hop in some routes, but is not treated by the market or by any
routing convention as a vehicle/bridge currency -- should show a muted or
absent version of the relationship.

Builds, by the SAME methodology as the real 5-candidate columns, for every day
in the core sample window (2021-05-05 to 2026-06-30):

  link_liquidity_usd        -- sum of tvlUSD over Uniswap V3 pools where LINK
                                is token0 or token1 (symbol match on the raw
                                daily pool snapshot), with the same
                                MAX_POOL_TVL_USD spam-pool filter used in
                                src/ddvc/analysis/lp_concentration.py. LINK is
                                never split with another candidate since it is
                                the only placebo token being tracked (mirrors
                                the "one-candidate pool gets full TVL" rule).
  log_link_liquidity         = log1p(link_liquidity_usd)          (placebo L)
  link_bridge_share          -- LINK's share of the day's total indirect-route
                                 USD volume, using the exact same route
                                 decomposition (ddvc.metrics._routes over
                                 route_class in {single, coherent}) and the
                                 exact same BridgeShare formula as
                                 scripts/run_empirical_proposition_tests.py::
                                 build_bridge_daily -- just computed for LINK
                                 instead of the 5 vehicle tokens.            (placebo S)

NOT built: an analogous placebo DirectCostAdvantage (D). Doing so honestly
would require re-running the entire multi-year on-chain V2+V3 counterfactual
quote simulation in scripts/run_route_cost_panel.py with LINK added to
VEHICLE_ADDRESSES -- that simulation carries incremental V3 tick-liquidity
state across the whole 2021-05-04..2026-06-30 history (see
_apply_v3_liquidity_events / _update_v3_swap_state), so it cannot be
short-cut to "just LINK, just a few days" the way the L and S measures above
can. That full rebuild was out of scope for this robustness pass. This is
disclosed explicitly, not silently skipped -- the placebo check below is run
on L and S only.

Inputs: data/raw/thegraph/uniswap_v3/uniswap_v3_daily_*.jsonl.gz (pool TVL
snapshots), data/unified/*.parquet (reconstructed route legs).

Output: output/nbc_pipeline/04_evidence/p1/link_placebo_panel.parquet
  columns: date, link_liquidity_usd, log_link_liquidity, link_bridge_share,
           link_indirect_route_denominator_usd
"""
from __future__ import annotations

import gzip
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ddvc.metrics import CLEAN_ROUTE_CLASSES, _routes  # noqa: E402

DATA = ROOT / "data"
OUTDIR = ROOT / "output" / "nbc_pipeline" / "04_evidence" / "p1"
OUT_PATH = OUTDIR / "link_placebo_panel.parquet"

PLACEBO_SYMBOL = "LINK"
MAX_POOL_TVL_USD = 10_000_000_000  # same spam-pool filter as lp_concentration.py

START = "20210505"  # matches the core P1 sample's first date
END = "20260630"    # matches the core P1 sample's last date


def _stamps() -> list[str]:
    files = sorted((DATA / "unified").glob("[0-9]" * 8 + ".parquet"))
    return [f.stem for f in files if START <= f.stem <= END]


def _link_liquidity_usd(stamp: str) -> float:
    path = DATA / "raw" / "thegraph" / "uniswap_v3" / f"uniswap_v3_daily_{stamp}.jsonl.gz"
    if not path.exists():
        return 0.0
    total = 0.0
    with gzip.open(path, "rt") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pool = rec.get("pool") or {}
            sym0 = str((pool.get("token0") or {}).get("symbol") or "")
            sym1 = str((pool.get("token1") or {}).get("symbol") or "")
            if sym0 != PLACEBO_SYMBOL and sym1 != PLACEBO_SYMBOL:
                continue
            try:
                tvl = float(rec.get("tvlUSD", 0) or 0)
            except (TypeError, ValueError):
                continue
            if not (0 < tvl <= MAX_POOL_TVL_USD):
                continue
            total += tvl
    return total


def _link_bridge_day(stamp: str) -> tuple[float, float]:
    """Return (link_volume_usd, indirect_route_denominator_usd) for one day,
    using the identical route decomposition as build_bridge_daily."""
    path = DATA / "unified" / f"{stamp}.parquet"
    if not path.exists():
        return 0.0, 0.0
    legs = pd.read_parquet(
        path,
        columns=[
            "tx_hash", "component_id", "route_class", "token_in_sym", "token_out_sym",
            "amount_usd", "tin_role", "tout_role", "amount_in", "amount_out",
        ],
    )
    routes = _routes(legs[legs["route_class"].isin(CLEAN_ROUTE_CLASSES)])
    indirect = [r for r in routes if r["inter"]]
    denom_vol = sum(float(r["vol"]) for r in indirect)
    link_vol = sum(float(r["vol"]) for r in indirect if PLACEBO_SYMBOL in r["inter"])
    return link_vol, denom_vol


def _one_stamp(stamp: str) -> dict:
    link_liq = _link_liquidity_usd(stamp)
    link_vol, denom_vol = _link_bridge_day(stamp)
    return {
        "date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}",
        "link_liquidity_usd": link_liq,
        "link_bridge_volume_usd": link_vol,
        "link_indirect_route_denominator_usd": denom_vol,
        "link_bridge_share": (link_vol / denom_vol) if denom_vol > 0 else 0.0,
    }


def build(force: bool = False, workers: int = 1) -> pd.DataFrame:
    if OUT_PATH.exists() and not force:
        return pd.read_parquet(OUT_PATH)

    stamps = _stamps()
    rows: list[dict] = [None] * len(stamps)  # type: ignore[list-item]
    t0 = time.time()
    if workers > 1:
        # Each stamp's (liquidity, route-decomposition) computation is a pure
        # function of that day's on-disk files, so this embarrassingly-
        # parallel fan-out over a process pool is safe and produces byte-
        # identical output to the serial loop below (added to keep the
        # ~1,900-day, single-day-at-a-time build tractable in one turn --
        # the serial loop took ~0.4s/day, i.e. ~13min single-threaded).
        import concurrent.futures as cf

        done = 0
        with cf.ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one_stamp, s): i for i, s in enumerate(stamps)}
            for fut in cf.as_completed(futs):
                rows[futs[fut]] = fut.result()
                done += 1
                if done % 200 == 0 or done == len(stamps):
                    print(f"  LINK placebo panel [{done}/{len(stamps)}] ({time.time()-t0:.0f}s elapsed, {workers} workers)", flush=True)
    else:
        for i, stamp in enumerate(stamps, 1):
            rows[i - 1] = _one_stamp(stamp)
            if i % 200 == 0 or i == len(stamps):
                print(f"  LINK placebo panel [{i}/{len(stamps)}] {stamp} ({time.time()-t0:.0f}s elapsed)", flush=True)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    import numpy as np
    df["log_link_liquidity"] = np.log1p(df["link_liquidity_usd"].clip(lower=0))
    df = df.sort_values("date").reset_index(drop=True)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"wrote {len(df):,} rows -> {OUT_PATH}")
    return df


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    df = build(force=args.force, workers=args.workers)
    print(df[["date", "link_liquidity_usd", "log_link_liquidity", "link_bridge_share"]].describe())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

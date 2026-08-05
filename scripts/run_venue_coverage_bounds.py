#!/usr/bin/env python3
"""What is left out of the priced panel, and which way does the omission push the answer?

Three measurements that turn coverage statements into signed bounds.

First, the volume share of each of the seven venues by year, so a missing venue can be
read as a fraction of the market instead of as a name on a list.

Second, the share of Curve's own USD swap volume that sits in pools failing the
StableSwap calibration gate. The count of excluded pools rises across the sample, but a
count is not a bound: twenty tiny crypto-pools and twenty large ones are the same count
and different omissions. The excluded pools' token composition then gives the direction,
because a pool that pairs volatile assets would have served native-asset legs while a
pool that pairs stablecoins would have served stable legs, and excluding it understates
the best available route on exactly those legs.

Third, whether sushiswap_v3 is priceable with machinery that already exists. The venue
is a concentrated-liquidity fork, but what matters is the state the subgraph exposes:
ticks and sqrtPriceX96 make it a v3quote problem, balances and weights make it a
weighted-product problem, and balances without ticks on a concentrated-liquidity venue
makes it neither.

Writes  output/exhibits/venue_volume_by_year.jsonl
        output/exhibits/curve_excluded_volume.jsonl
        output/exhibits/curve_excluded_composition.jsonl
        output/exhibits/sushiswap_v3_schema_probe.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.asset_types import asset_type  # noqa: E402
from ddvc.pricing.stableswap import calibrate_amp  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

RAW = ROOT / "data" / "raw" / "thegraph"
EX = ROOT / "output" / "exhibits"

# The seven venues of the route-cost panel. uniswap_v1 is carried because it is the
# forced-vehicle laboratory of the v1 study and because its volume share is part of the
# bound: a venue too small to move a route cost is a different kind of gap from a venue
# that is merely unpriced.
VENUES = ("uniswap_v1", "uniswap_v2", "uniswap_v3", "uniswap_v4",
          "sushiswap_v2", "sushiswap_v3", "balancer", "curve")

# Field carrying a pool-day's USD swap volume, and the field carrying that pool-day's
# USD value locked, per subgraph schema. The second one is not decoration: it is what
# makes the first one auditable.
VOLUME_FIELD = {
    "uniswap_v2": "dailyVolumeUSD",
    "sushiswap_v2": "dailyVolumeUSD",
    "sushiswap_v3": "dailyVolumeUSD",
    "curve": "dailyVolumeUSD",
    "uniswap_v3": "volumeUSD",
    "uniswap_v4": "volumeUSD",
    "balancer": "swapVolume",
}
TVL_FIELD = {
    "uniswap_v1": "combinedBalanceInUSD",
    "uniswap_v2": "reserveUSD",
    "sushiswap_v2": "reserveUSD",
    "sushiswap_v3": "totalValueLockedUSD",
    "curve": "totalValueLockedUSD",
    "uniswap_v3": "tvlUSD",
    "uniswap_v4": "tvlUSD",
    "balancer": "liquidity",
}

# Plausibility screen on the subgraph's own USD fields, and why one is unavoidable.
# Every USD figure in the raw layer is the subgraph's price oracle applied to token
# amounts, and that oracle fails on thin exotic pools: Curve's vETHETH reports a
# 683,750,272,316,120,064 dollar day against zero value locked, and reusdsfrx reports
# 6.9e22 dollars, which is more money than exists. Summing those unscreened hands the
# whole cross-venue comparison to whichever venue happens to host the worst oracle bug,
# which is what a first pass did: it put Curve at 100% of 2024 volume on the strength of
# one broken pool. So a pool-day enters an aggregate only when its numbers are physically
# possible. The ceilings are three orders of magnitude above anything real, so the screen
# discriminates between data and arithmetic accidents and not between large and small
# pools, and the mass it removes is reported alongside every total it touches.
MAX_POOL_DAY_USD = 5e9        # the largest true pool-day on Ethereum is ~$2e9
MAX_POOL_TVL_USD = 1e10       # no Ethereum pool has ever held this much


def rows(path: Path):
    if not path.exists():
        return
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _f(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v and abs(v) != float("inf") else 0.0


def plausible(vol: float, tvl: float) -> bool:
    return 0.0 < tvl <= MAX_POOL_TVL_USD and 0.0 <= vol <= MAX_POOL_DAY_USD


def day_volume(venue: str, day: str) -> tuple[float, float] | None:
    """(kept, screened) USD swap volume for a venue-day; None when the day is absent.

    Two of the seven subgraphs report volume cumulatively and five report it daily, and
    the difference is invisible in the field names. uniswap_v1's `daily` stream is
    `exchangeHistoricalDatas`, one record per EVENT carrying LIFETIME totals, so reading
    `tradeVolumeEth` as a daily figure counts a pool's entire history once per event and
    turned a venue that had been dead for years into 99.9% of the 2020 market. Its day
    flow is the cumulative field's within-day range. Balancer's `poolSnapshots.swapVolume`
    is lifetime cumulative too, handled above. The five Messari and Uniswap-native
    streams do report a day's flow, and their fields are used directly.
    """
    p = RAW / venue / f"{venue}_daily_{day}.jsonl.gz"
    if not p.exists():
        return None
    kept = screened = 0.0
    if venue == "balancer":
        # Balancer's `poolSnapshots.swapVolume` is also lifetime cumulative, and reading
        # it as a daily figure put the venue at 94% of 2024 volume. Its swaps stream is
        # a true flow and small enough to read, so the day's volume is summed from
        # `valueUSD` and screened against the same pool's snapshot liquidity.
        liq: dict[str, float] = {}
        for r in rows(p):
            pid = ((r.get("pool") or {}).get("id") or "").lower()
            if pid:
                liq[pid] = _f(r.get("liquidity"))
        per_pool: dict[str, float] = defaultdict(float)
        for s in rows(RAW / venue / f"{venue}_swaps_{day}.jsonl.gz"):
            pid = ((s.get("poolId") or {}).get("id") or "").lower()
            per_pool[pid] += _f(s.get("valueUSD"))
        for pid, v in per_pool.items():
            if plausible(v, liq.get(pid, 0.0)):
                kept += v
            else:
                screened += v
        return kept, screened
    if venue == "uniswap_v1":
        lo: dict[str, float] = {}
        hi: dict[str, float] = {}
        tvl: dict[str, float] = {}
        for r in rows(p):
            a = r.get("exchangeAddress") or ""
            c = _f(r.get("tradeVolumeUSD"))
            if not a or c <= 0:
                continue
            lo[a] = min(lo.get(a, c), c)
            hi[a] = max(hi.get(a, c), c)
            tvl[a] = max(tvl.get(a, 0.0), _f(r.get("combinedBalanceInUSD")))
        for a, top in hi.items():
            v = top - lo[a]
            if plausible(v, tvl.get(a, 0.0)):
                kept += v
            else:
                screened += v
        return kept, screened
    vf, tf = VOLUME_FIELD[venue], TVL_FIELD[venue]
    for r in rows(p):
        v = _f(r.get(vf))
        if plausible(v, _f(r.get(tf))):
            kept += v
        else:
            screened += v
    return kept, screened


def sampled_days(step: int) -> list[str]:
    start, end = date(2018, 11, 2), date(2026, 6, 30)
    out, d = [], start
    while d <= end:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=step)
    return out


def job_volume_shares(step: int) -> pd.DataFrame:
    tot: dict[tuple[str, str], float] = defaultdict(float)
    scr: dict[tuple[str, str], float] = defaultdict(float)
    days_seen: dict[tuple[str, str], int] = defaultdict(int)
    days = sampled_days(step)
    print(f"volume shares: {len(days)} sampled days, every {step}th day, "
          f"{days[0]}..{days[-1]}")
    for i, day in enumerate(days):
        for v in VENUES:
            got = day_volume(v, day)
            if got is None:
                continue
            kept, dropped = got
            tot[(day[:4], v)] += kept
            scr[(day[:4], v)] += dropped
            days_seen[(day[:4], v)] += 1
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(days)} days")
    years = sorted({y for y, _ in tot})
    recs = []
    for y in years:
        gross = sum(tot[(y, v)] for v in VENUES)
        for v in VENUES:
            recs.append({"year": y, "venue": v, "usd_volume": tot[(y, v)],
                         "share_pct": 100 * tot[(y, v)] / gross if gross else 0.0,
                         "usd_screened_out": scr[(y, v)],
                         "sampled_days": days_seen[(y, v)]})
    return pd.DataFrame(recs)


def curve_days_with_balances() -> list[str]:
    out = []
    for p in sorted((RAW / "curve").glob("curve_daily_*.jsonl.gz")):
        day = p.name[len("curve_daily_"):-len(".jsonl.gz")]
        for r in rows(p):
            if "inputTokenBalances" in r:
                out.append(day)
            break
    return out


def curve_pool_state(day: str) -> dict[str, dict]:
    pools: dict[str, dict] = {}
    for r in rows(RAW / "curve" / f"curve_daily_{day}.jsonl.gz"):
        p = r.get("pool") or {}
        pid = (p.get("id") or "").lower()
        bals = r.get("inputTokenBalances")
        toks = p.get("inputTokens") or []
        if not pid or not bals or len(bals) != len(toks):
            continue
        try:
            pools[pid] = {
                "symbol": p.get("symbol") or "",
                "tokens": tuple((t.get("id") or "").lower() for t in toks),
                "symbols": tuple((t.get("symbol") or "") for t in toks),
                "decimals": tuple(int(t.get("decimals")) for t in toks),
                "balances": tuple(int(b) for b in bals),
                "daily_volume_usd": _f(r.get("dailyVolumeUSD")),
                "tvl_usd": _f(r.get("totalValueLockedUSD")),
            }
        except (TypeError, ValueError):
            continue
    return pools


# Token classification for the bias argument, and why the project's address registry is
# not enough on its own. `ddvc.asset_types` knows the currencies a route can be
# intermediated THROUGH, which is the right universe for the vehicle test and the wrong
# one for reading a Curve pool's composition. Curve's stable business runs through
# metapools that pair a stablecoin against 3Crv, the LP claim on the DAI/USDC/USDT base
# pool, and through interest-bearing wrappers such as aDAI, yUSDC and sUSDS. Those are
# not vehicle currencies, so they are absent from the registry and land in "other", and
# the first pass at this measurement duly labelled MIM/3Crv, LUSD/3Crv and USDP/3Crv as
# volatile pairs. They are stable-to-stable pools, and reading them as volatile would
# have reversed the sign of the bound. So the registry lookup runs first and a symbol
# pass over stable derivatives runs second.
STABLE_BASES = {
    "DAI", "USDC", "USDT", "TUSD", "SUSD", "BUSD", "GUSD", "USDP", "PAX", "HUSD",
    "USDK", "USDN", "DUSD", "MUSD", "RSV", "LUSD", "MIM", "UST", "USTW", "FRAX",
    "CRVUSD", "USDE", "USDS", "USD1", "PYUSD", "ALUSD", "DOLA", "FEI", "RAI",
    "USDD", "FDUSD", "GHO", "USDL", "USDM", "USDO", "USDX", "USDY", "USDZ", "USDF",
    "USDA", "USDQ", "USDR", "USDV", "DEUSD", "RLUSD", "USR", "SCRVUSD", "FXUSD",
}
# Claims on a basket of the above. A pool pairing one of these against a stablecoin is a
# stable-to-stable pool whatever the LP token's ticker looks like.
STABLE_BASKETS = {
    "3CRV", "CRVFRAX", "CRVUSDUSDC", "CRVUSDUSDT", "FRAXBP", "DOLA3POOL",
    "SUSDFRAXBP", "3POOL", "2CRV", "MIM3LP3CRV", "CRVPLAIN3ANDSUSD",
}
# Wrapper prefixes that leave the underlying currency unchanged: Aave, Compound, Yearn,
# savings vaults, Curve's own cy tokens.
WRAPPERS = ("A", "C", "Y", "S", "CY", "W", "SD", "ST", "V")
NATIVE_SYMBOLS = {
    "ETH", "WETH", "STETH", "WSTETH", "FRXETH", "SFRXETH", "RETH", "CBETH", "ANKRETH",
    "ALETH", "PETH", "OETH", "ETHX", "MSETH", "WBETH", "EETH", "WEETH", "ETH+",
    "SETH", "VETH", "OSETH", "RSETH", "EZETH", "PXETH", "YNETH", "SWETH", "STETH-NG",
}


def token_leg(address: str, symbol: str) -> str:
    """One token's leg: stable, native, or other."""
    t = asset_type(address)
    if t == "stable":
        return "stable"
    if t in ("native", "staked_native"):
        return "native"
    s = (symbol or "").upper().replace("-F", "").replace("_", "")
    if s in NATIVE_SYMBOLS:
        return "native"
    if s in STABLE_BASES or s in STABLE_BASKETS:
        return "stable"
    for w in sorted(WRAPPERS, key=len, reverse=True):
        if s.startswith(w) and s[len(w):] in STABLE_BASES | STABLE_BASKETS:
            return "stable"
    if s.endswith("ETH") and "ETH" != s[:-3]:
        return "native"
    return "other"


def composition(legs: set[str]) -> str:
    """Which leg of the native-versus-stable comparison a pool would have served.

    A pool priced away is a route that was available and went unmeasured, so the label
    has to name the leg, not the chemistry. An all-stable basket would have served the
    stable-vehicle legs. Any pool holding ETH or a liquid-staking derivative would have
    served native legs. Anything else volatile serves the imported-asset legs, which sit
    on the same side of the comparison as native in the sense that they are not the
    stable vehicle under test.
    """
    if legs <= {"stable"}:
        return "stable_leg"
    if "native" in legs:
        return "native_leg"
    return "other_volatile_leg"


def job_curve_excluded(n_days: int, min_swaps: int
                       ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    days = curve_days_with_balances()
    if not days:
        raise SystemExit("no Curve days carry balances")
    step = max(1, len(days) // n_days)
    picked = days[::step][:n_days]
    print(f"\ncurve exclusion: {len(days)} days carry balances, "
          f"measuring {len(picked)}: {picked[0]}..{picked[-1]}")

    day_rows, comp_rows, kept_rows = [], [], []
    for day in picked:
        pools = curve_pool_state(day)
        trades: dict[str, list] = defaultdict(list)
        # A pool-day's volume is taken from the daily snapshot, screened, so that the
        # excluded share is a ratio of two comparably measured quantities.
        vol_usd: dict[str, float] = {}
        gross_day = screened_day = 0.0
        for pid, meta in pools.items():
            v, tvl = meta["daily_volume_usd"], meta["tvl_usd"]
            if plausible(v, tvl):
                vol_usd[pid] = v
                gross_day += v
            else:
                vol_usd[pid] = 0.0
                screened_day += v
        for s in rows(RAW / "curve" / f"curve_swaps_{day}.jsonl.gz"):
            pid = ((s.get("pool") or {}).get("id") or "").lower()
            if pid not in pools:
                continue
            try:
                ti = (s["tokenIn"]["id"] or "").lower()
                to = (s["tokenOut"]["id"] or "").lower()
                ai, ao = int(s["amountIn"]), int(s["amountOut"])
            except (KeyError, TypeError, ValueError):
                continue
            if ai > 0 and ao > 0:
                trades[pid].append((ti, to, ai, ao))

        passed_v = failed_v = untested_v = 0.0
        passed_n = failed_n = untested_n = 0
        for pid, meta in pools.items():
            v = vol_usd.get(pid, 0.0)
            obs = trades.get(pid, [])
            if len(obs) < min_swaps:
                untested_v += v
                untested_n += 1
                continue
            fit = calibrate_amp(meta["balances"], meta["decimals"], meta["tokens"],
                               obs[: len(obs) // 2])
            if fit is None:
                failed_v += v
                failed_n += 1
                legs = {token_leg(a, s)
                        for a, s in zip(meta["tokens"], meta["symbols"])}
                comp_rows.append({
                    "day": day, "pool_id": pid, "pool_symbol": meta["symbol"],
                    "tokens": "|".join(meta["symbols"]),
                    "token_legs": "|".join(sorted(legs)),
                    "leg_served": composition(legs),
                    "usd_volume": v, "n_swaps": len(obs)})
            else:
                passed_v += v
                passed_n += 1
                legs = {token_leg(a, s)
                        for a, s in zip(meta["tokens"], meta["symbols"])}
                kept_rows.append({"day": day, "leg_served": composition(legs),
                                  "usd_volume": v})
        tested_v = passed_v + failed_v
        day_rows.append({
            "day": day, "year": day[:4],
            "pools_passed": passed_n, "pools_failed": failed_n,
            "pools_untested": untested_n,
            "usd_passed": passed_v, "usd_failed": failed_v,
            "usd_untested": untested_v, "usd_all_swaps": gross_day,
            "usd_screened_out": screened_day,
            "excluded_share_of_tested_pct": 100 * failed_v / tested_v if tested_v else 0.0,
            "excluded_share_of_all_pct": 100 * failed_v / gross_day if gross_day else 0.0,
            "untested_share_of_all_pct": (100 * untested_v / gross_day
                                          if gross_day else 0.0)})
        r = day_rows[-1]
        print(f"  {day}: passed {passed_n:>4} pools / ${passed_v:>14,.0f} | "
              f"failed {failed_n:>3} / ${failed_v:>14,.0f} | "
              f"excluded {r['excluded_share_of_tested_pct']:>6.2f}% of tested, "
              f"{r['excluded_share_of_all_pct']:>6.2f}% of all")
    return pd.DataFrame(day_rows), pd.DataFrame(comp_rows), pd.DataFrame(kept_rows)


def job_sushiswap_v3() -> pd.DataFrame:
    v = "sushiswap_v3"
    dailies = sorted((RAW / v).glob(f"{v}_daily_*.jsonl.gz"))
    swaps = sorted((RAW / v).glob(f"{v}_swaps_*.jsonl.gz"))
    nonempty_daily, first_nonempty, last_nonempty = 0, None, None
    have_bal = have_wt = 0
    weights_seen: set[str] = set()
    for p in dailies:
        first = None
        for r in rows(p):
            first = r
            break
        if first is None:
            continue
        nonempty_daily += 1
        day = p.name[len(f"{v}_daily_"):-len(".jsonl.gz")]
        first_nonempty = first_nonempty or day
        last_nonempty = day
        if "inputTokenBalances" in first:
            have_bal += 1
        w = first.get("inputTokenWeights")
        if w is not None:
            have_wt += 1
            weights_seen.add("|".join(str(x)[:8] for x in w))
    swap_fields: set[str] = set()
    swaps_checked = 0
    for p in swaps[::37]:
        for r in rows(p):
            swap_fields |= set(r.keys())
            swaps_checked += 1
            break
    return pd.DataFrame([{
        "venue": v,
        "daily_files": len(dailies),
        "daily_days_nonempty": nonempty_daily,
        "first_nonempty_day": first_nonempty,
        "last_nonempty_day": last_nonempty,
        "days_with_input_token_balances": have_bal,
        "days_with_input_token_weights": have_wt,
        "distinct_weight_vectors_sampled": len(weights_seen),
        "example_weight_vectors": " ; ".join(sorted(weights_seen)[:4]),
        "swap_files_probed": swaps_checked,
        "swap_has_sqrt_price_x96": "sqrtPriceX96" in swap_fields,
        "swap_has_tick": "tick" in swap_fields,
        "swap_fields": "|".join(sorted(swap_fields)),
    }])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--volume-step", type=int, default=7,
                    help="sample every Nth calendar day for the volume table")
    ap.add_argument("--curve-days", type=int, default=16)
    ap.add_argument("--min-swaps", type=int, default=8)
    ap.add_argument("--skip-volume", action="store_true")
    args = ap.parse_args()

    if not args.skip_volume:
        vol = job_volume_shares(args.volume_step)
        write_exhibit(vol, EX / "venue_volume_by_year.jsonl")
        print("\n" + vol.pivot(index="year", columns="venue",
                               values="share_pct").round(2).to_string())

    probe = job_sushiswap_v3()
    write_exhibit(probe, EX / "sushiswap_v3_schema_probe.jsonl")
    print("\nsushiswap_v3 probe")
    for k, x in probe.iloc[0].items():
        print(f"  {k}: {x}")

    days, comp = job_curve_excluded(args.curve_days, args.min_swaps)
    write_exhibit(days, EX / "curve_excluded_volume.jsonl")
    if not comp.empty:
        agg = (comp.groupby("leg_served")
               .agg(pools=("pool_id", "count"), usd_volume=("usd_volume", "sum"))
               .reset_index())
        agg["share_of_excluded_usd_pct"] = 100 * agg["usd_volume"] / agg["usd_volume"].sum()
        write_exhibit(agg, EX / "curve_excluded_composition.jsonl")
        print("\nexcluded-pool composition, pooled over measured days")
        print(agg.round(2).to_string(index=False))
        top = comp.nlargest(12, "usd_volume")[
            ["day", "pool_symbol", "tokens", "leg_served", "usd_volume"]]
        print("\nlargest excluded pool-days")
        print(top.to_string(index=False))
    by_year = (days.groupby("year")
               .agg(days=("day", "count"),
                    usd_failed=("usd_failed", "sum"),
                    usd_passed=("usd_passed", "sum"),
                    usd_all=("usd_all_swaps", "sum"))
               .reset_index())
    by_year["excluded_share_of_tested_pct"] = (
        100 * by_year["usd_failed"] / (by_year["usd_failed"] + by_year["usd_passed"]))
    by_year["excluded_share_of_all_pct"] = (
        100 * by_year["usd_failed"] / by_year["usd_all"])
    print("\ncurve excluded volume by year")
    print(by_year.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
#
# What the screen must NOT do is require the value-locked field to look sane, which a
# first version did by demanding TVL above zero. Two venues fail that test while
# reporting real volume. Curve's subgraph reports zero value locked for pools whose
# tokens its oracle does not price, which in 2026 means most of the newer stablecoins:
# sUSDS/USDT at $17m, USDC/USDT at $9m and PYUSD/crvUSD at $5m were all thrown out. The
# Uniswap v4 subgraph reports NEGATIVE `tvlUSD` on its largest pools, so the deepest
# USDC/USDT pool on the venue went out at $87m. Both losses fall on stable pairs, so the
# tidy-looking version of the screen was quietly deleting the stable side of exactly the
# comparison this document exists to bound. Volume is therefore screened on volume, and
# value locked only rules out the astronomical.
MAX_POOL_DAY_USD = 5e9        # the largest true pool-day on Ethereum is ~$2e9
MAX_POOL_TVL_USD = 1e10       # no Ethereum pool has ever held this much
MAX_SWAP_USD = 5e8            # single swaps above this are oracle output, not trades
# A pool cannot trade a thousand times its own liquidity in a day. The ceiling alone does
# not catch what this does: Uniswap v2 reports a $1,360,770,229 day for WETH/TRI against
# $255 of reserves, and four more meme pairs with four-figure reserves report nine-figure
# days, which together made v2 look larger than v3 in 2025. The rule applies wherever
# liquidity is reported at all, and where it is not, which is Curve's newer stable pools
# at zero and Uniswap v4's largest pools at negative, the volume ceiling stands alone.
MAX_DAILY_TURNOVER = 1_000.0

# The two Messari-schema venues, Curve and sushiswap_v3, need their volume built from
# swaps instead of read from the daily snapshot, for two reasons found by cross-checking
# one against the other. First, `dailyVolumeUSD` counts BOTH legs of a trade while the
# Uniswap-family fields count one, so reading them side by side doubles Curve: 3Crv on
# 2024-04-02 reports $515m against $168m summed from its own swaps, and the ratio sits
# near two on every pool and day checked. Second, the daily field carries the oracle's
# failures whole, while a swap reports the value of both legs and a broken price usually
# breaks one: GHO/USR reports a $456m day whose swaps sum to $8. Taking the SMALLER leg
# of each swap fixes both, and it is conservative by construction, which is the right
# direction for a bound.
MESSARI_VENUES = ("curve", "sushiswap_v3")


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
    if not (0.0 <= vol <= MAX_POOL_DAY_USD and abs(tvl) <= MAX_POOL_TVL_USD):
        return False
    return tvl <= 0.0 or vol <= MAX_DAILY_TURNOVER * tvl


def messari_pool_volume(venue: str, day: str) -> dict[str, float]:
    """Per-pool USD volume for a Messari-schema venue-day, from the smaller swap leg."""
    out: dict[str, float] = defaultdict(float)
    for s in rows(RAW / venue / f"{venue}_swaps_{day}.jsonl.gz"):
        pid = ((s.get("pool") or {}).get("id") or "").lower()
        v = min(_f(s.get("amountInUSD")), _f(s.get("amountOutUSD")))
        if pid and 0.0 <= v <= MAX_SWAP_USD:
            out[pid] += v
    return dict(out)


def day_volume(venue: str, day: str) -> tuple[float, int, int] | None:
    """(kept USD, pool-days kept, pool-days screened); None when the day is absent.

    The screened mass is counted in pool-days and not in dollars, because a dollar total
    over records the oracle got wrong is not a quantity: one 6.9e22 pool-day would
    report the screen as removing 100.0% of everything, which describes the bug and not
    the screen's footprint.

    No two of these subgraphs mean the same thing by volume, and the field names do not
    say so. uniswap_v1's `daily` stream is `exchangeHistoricalDatas`, one record per EVENT
    carrying LIFETIME totals, so reading `tradeVolumeEth` as a daily figure counts a
    pool's entire history once per event and turned a venue that had been dead for years
    into 99.9% of the 2020 market; its day flow is that field's within-day range.
    Balancer's `poolSnapshots.swapVolume` is lifetime cumulative too. Curve's and
    sushiswap_v3's `dailyVolumeUSD` is a daily flow but counts both legs, so it is rebuilt
    from swaps. Only the four Uniswap-family streams can be read as they stand.
    """
    p = RAW / venue / f"{venue}_daily_{day}.jsonl.gz"
    if not p.exists():
        return None
    kept = 0.0
    n_kept = n_screened = 0
    if venue in MESSARI_VENUES:
        tvl_by_pool: dict[str, float] = {}
        for r in rows(p):
            pid = ((r.get("pool") or {}).get("id") or "").lower()
            if pid:
                tvl_by_pool[pid] = _f(r.get("totalValueLockedUSD"))
        for pid, v in messari_pool_volume(venue, day).items():
            if plausible(v, tvl_by_pool.get(pid, 0.0)):
                kept += v
                n_kept += 1
            else:
                n_screened += 1
        return kept, n_kept, n_screened
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
                n_kept += 1
            else:
                n_screened += 1
        return kept, n_kept, n_screened
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
                n_kept += 1
            else:
                n_screened += 1
        return kept, n_kept, n_screened
    vf, tf = VOLUME_FIELD[venue], TVL_FIELD[venue]
    for r in rows(p):
        v = _f(r.get(vf))
        if plausible(v, _f(r.get(tf))):
            kept += v
            n_kept += 1
        else:
            n_screened += 1
    return kept, n_kept, n_screened


def sampled_days(step: int) -> list[str]:
    start, end = date(2018, 11, 2), date(2026, 6, 30)
    out, d = [], start
    while d <= end:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=step)
    return out


def job_volume_shares(step: int) -> pd.DataFrame:
    tot: dict[tuple[str, str], float] = defaultdict(float)
    scr: dict[tuple[str, str], int] = defaultdict(int)
    pool_days: dict[tuple[str, str], int] = defaultdict(int)
    days_seen: dict[tuple[str, str], int] = defaultdict(int)
    days = sampled_days(step)
    print(f"volume shares: {len(days)} sampled days, every {step}th day, "
          f"{days[0]}..{days[-1]}")
    for i, day in enumerate(days):
        for v in VENUES:
            got = day_volume(v, day)
            if got is None:
                continue
            kept, n_kept, n_dropped = got
            tot[(day[:4], v)] += kept
            scr[(day[:4], v)] += n_dropped
            pool_days[(day[:4], v)] += n_kept
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
                         "pool_days_kept": pool_days[(y, v)],
                         "pool_days_screened_out": scr[(y, v)],
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
        # A pool-day's volume is summed from the same swaps the calibration is fitted to,
        # on the smaller-leg basis, so the excluded share is a ratio of two identically
        # measured quantities and neither side can be inflated by the daily field's
        # double counting.
        raw_vol = messari_pool_volume("curve", day)
        vol_usd: dict[str, float] = {}
        gross_day = screened_day = 0.0
        for pid, meta in pools.items():
            v = raw_vol.get(pid, 0.0)
            if plausible(v, meta["tvl_usd"]):
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


def _pairs_on_day(venue: str, day: str) -> set[frozenset[str]]:
    """Token-symbol pairs quotable on a venue-day, for the overlap test."""
    out: set[frozenset[str]] = set()
    for r in rows(RAW / venue / f"{venue}_daily_{day}.jsonl.gz"):
        if venue in ("uniswap_v2", "sushiswap_v2"):
            syms = [(r.get("token0") or {}).get("symbol"),
                    (r.get("token1") or {}).get("symbol")]
        elif venue in ("uniswap_v3", "uniswap_v4"):
            p = r.get("pool") or {}
            syms = [(p.get("token0") or {}).get("symbol"),
                    (p.get("token1") or {}).get("symbol")]
        else:
            syms = [t.get("symbol") for t in ((r.get("pool") or {})
                                              .get("inputTokens") or [])]
        syms = [s.upper() for s in syms if s]
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                out.add(frozenset((syms[i], syms[j])))
    return out


def job_sushiswap_v3_overlap(n_days: int) -> pd.DataFrame:
    """Does sushiswap_v3 reach pairs the priced venues do not?

    Volume share alone cannot settle whether a venue is worth building, because a
    best-of-all-venues route statistic is sensitive to a venue that is SOLE host of a
    pair however small it is. So the test is not size, it is uniqueness.
    """
    priced = ("uniswap_v2", "uniswap_v3", "uniswap_v4", "sushiswap_v2", "curve")
    days = [p.name[len("sushiswap_v3_daily_"):-len(".jsonl.gz")]
            for p in sorted((RAW / "sushiswap_v3").glob("sushiswap_v3_daily_*.jsonl.gz"))]
    days = [d for d in days if d >= "20230405"]
    step = max(1, len(days) // n_days)
    recs = []
    for day in days[::step][:n_days]:
        elsewhere: set[frozenset[str]] = set()
        for v in priced:
            elsewhere |= _pairs_on_day(v, day)
        vol_shared = vol_only = 0.0
        n_shared = n_only = 0
        vol_by_pool = messari_pool_volume("sushiswap_v3", day)
        for r in rows(RAW / "sushiswap_v3" / f"sushiswap_v3_daily_{day}.jsonl.gz"):
            p = r.get("pool") or {}
            syms = [(t.get("symbol") or "").upper()
                    for t in (p.get("inputTokens") or [])]
            v = vol_by_pool.get((p.get("id") or "").lower(), 0.0)
            if len(syms) != 2 or not plausible(v, _f(r.get("totalValueLockedUSD"))):
                continue
            if frozenset(syms) in elsewhere:
                vol_shared += v
                n_shared += 1
            else:
                vol_only += v
                n_only += 1
        tot = vol_shared + vol_only
        recs.append({"day": day, "pools_pair_shared": n_shared,
                     "pools_pair_unique": n_only,
                     "usd_pair_shared": vol_shared, "usd_pair_unique": vol_only,
                     "unique_pair_share_pct": 100 * vol_only / tot if tot else 0.0})
        r0 = recs[-1]
        print(f"  {day}: {n_shared:>3} pools on pairs the priced venues also host "
              f"(${vol_shared:>12,.0f}), {n_only:>3} on pairs they do not "
              f"(${vol_only:>12,.0f}) = {r0['unique_pair_share_pct']:>5.1f}% unique")
    return pd.DataFrame(recs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--volume-step", type=int, default=7,
                    help="sample every Nth calendar day for the volume table")
    ap.add_argument("--curve-days", type=int, default=16)
    ap.add_argument("--min-swaps", type=int, default=8)
    ap.add_argument("--skip-volume", action="store_true")
    ap.add_argument("--overlap-days", type=int, default=12,
                    help="days on which to test sushiswap_v3 pair uniqueness; 0 skips")
    ap.add_argument("--tag", default="",
                    help="suffix for exhibit filenames, for sensitivity runs")
    args = ap.parse_args()
    tag = f"_{args.tag}" if args.tag else ""

    if not args.skip_volume:
        vol = job_volume_shares(args.volume_step)
        write_exhibit(vol, EX / f"venue_volume_by_year{tag}.jsonl")
        print("\n" + vol.pivot(index="year", columns="venue",
                               values="share_pct").round(2).to_string())

    probe = job_sushiswap_v3()
    write_exhibit(probe, EX / f"sushiswap_v3_schema_probe{tag}.jsonl")
    print("\nsushiswap_v3 probe")
    for k, x in probe.iloc[0].items():
        print(f"  {k}: {x}")

    if args.overlap_days:
        print("\nsushiswap_v3 pair uniqueness against the five priced venues")
        ov = job_sushiswap_v3_overlap(args.overlap_days)
        write_exhibit(ov, EX / f"sushiswap_v3_pair_overlap{tag}.jsonl")
        tot = ov["usd_pair_shared"].sum() + ov["usd_pair_unique"].sum()
        print(f"  pooled: {100 * ov['usd_pair_unique'].sum() / tot:.2f}% of "
              f"sushiswap_v3 volume sits on pairs no priced venue hosts that day")

    if not args.curve_days:
        return 0
    days, comp, kept = job_curve_excluded(args.curve_days, args.min_swaps)
    write_exhibit(days, EX / f"curve_excluded_volume{tag}.jsonl")
    if not comp.empty:
        agg = (comp.groupby("leg_served")
               .agg(excluded_pools=("pool_id", "count"),
                    excluded_usd=("usd_volume", "sum"))
               .reset_index())
        agg["share_of_excluded_usd_pct"] = (
            100 * agg["excluded_usd"] / agg["excluded_usd"].sum())
        k = (kept.groupby("leg_served").agg(priced_usd=("usd_volume", "sum"))
             .reset_index()) if not kept.empty else pd.DataFrame(
                 columns=["leg_served", "priced_usd"])
        agg = agg.merge(k, on="leg_served", how="outer").fillna(0.0)
        agg["share_of_priced_usd_pct"] = (
            100 * agg["priced_usd"] / agg["priced_usd"].sum())
        # The bound's sign lives in this column: the share of a leg's Curve volume that
        # the calibration gate throws away, leg by leg.
        agg["excluded_share_within_leg_pct"] = (
            100 * agg["excluded_usd"] / (agg["excluded_usd"] + agg["priced_usd"]))
        write_exhibit(agg, EX / f"curve_excluded_composition{tag}.jsonl")
        print("\nleg composition of Curve volume, priced against excluded, "
              "pooled over measured days")
        print(agg.round(2).to_string(index=False))
        comp["year"] = comp["day"].str[:4]
        kept["year"] = kept["day"].str[:4]
        ex_y = (comp.groupby(["year", "leg_served"])["usd_volume"].sum()
                .unstack(fill_value=0.0))
        kp_y = (kept.groupby(["year", "leg_served"])["usd_volume"].sum()
                .unstack(fill_value=0.0))
        within = (100 * ex_y / (ex_y + kp_y.reindex_like(ex_y).fillna(0.0))).round(2)
        print("\nexcluded share of each leg's Curve volume, by year")
        print(within.to_string())
        write_exhibit(within.reset_index(), EX / f"curve_excluded_by_year_leg{tag}.jsonl")
        top = comp.nlargest(12, "usd_volume")[
            ["day", "pool_symbol", "tokens", "leg_served", "usd_volume"]]
        print("\nlargest excluded pool-days")
        print(top.to_string(index=False))
        # Audit trail for the classifier: any large volume sitting in "other" would mean
        # the leg labels are guesses, so the unclassified tokens are printed by size.
        unk: dict[str, float] = defaultdict(float)
        for _, r in comp.iterrows():
            if "other" in str(r["token_legs"]).split("|"):
                unk[str(r["tokens"])] += float(r["usd_volume"])
        if unk:
            print("\nexcluded pool-days holding a token the classifier calls 'other'")
            for toks, v in sorted(unk.items(), key=lambda kv: -kv[1])[:15]:
                print(f"  ${v:>16,.0f}  {toks}")
            print(f"  total in 'other'-touching pools: ${sum(unk.values()):,.0f} of "
                  f"${comp['usd_volume'].sum():,.0f} excluded")
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

#!/usr/bin/env python3
"""Does the Balancer weighted quoter reproduce realised swaps, and which pools does it fail on?

Three questions, and the third is the one that decides what goes in the panel.

First, is the weighted-geometric-mean implementation right. The v2, v3 and v4 quoters were accepted only after reproducing realised swaps to a median absolute error of 0.0000% and Curve cleared 0.022%, so Balancer has to clear the same bar before its quotes enter the route-cost panel.

Second, does the balance reconstruction hold. Balancer balances arrive as one daily `poolSnapshots.amounts` record, and mixing state measured at different instants is the defect that once made an "hour" compare pools up to 23 hours apart in this project. The reconstruction in `ddvc.pricing.weighted` reads that record as the day's CLOSING state, nets the day's whole swap flow off it to recover the opening state, and replays the flow forward so every trade is quoted against the balances it actually faced. If that reading of the snapshot is wrong the error will show it, and this script prints the two rival readings alongside it so the comparison is on the page instead of in a commit message.

Third, which pools run different maths. Balancer's vault hosts stable, composable-stable, Gyroscope, linear and boosted pools, none of which is a weighted geometric mean. Excluding them on the `poolType` label would be excluding on a name, and the equivalent shortcut on Curve let crypto-pools through an amplification range that merely looked plausible and produced 36% median errors. So every pool is fitted on alternate trades from its day whatever its type says, acceptance is the achieved error on those, and the score is computed only on the trades in between, which no fit ever saw. Exclusions are then reported as a share of VOLUME and attributed to pool types by volume, because a count of excluded pools says nothing about how much of the venue the panel loses.

Writes  output/exhibits/weighted_quoter_validation.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.pricing.weighted import (  # noqa: E402
    MAX_CALIBRATION_ERROR,
    ONE,
    WeightedPool,
    calibrate_fee,
    calibrate_weight_ratio,
    median_quote_error,
    quote_errors,
    quote_exact_input,
    rebuild_pre_trade_balances,
)
from ddvc.tables import write_exhibit  # noqa: E402

RAW = ROOT / "data" / "raw" / "thegraph" / "balancer"
OUT = ROOT / "output" / "exhibits" / "weighted_quoter_validation.jsonl"


def _rows(path: Path):
    if not path.exists():
        return
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def days_with_amounts() -> list[str]:
    """Days whose daily file carries per-token balances.

    The field is requested by the current schema but absent from every file fetched before that
    schema changed, and `skip_existing` kept those files, so presence has to be read off the
    file itself. A raw file records when it was fetched and not which fields were asked for.
    """
    out = []
    for p in sorted(RAW.glob("balancer_daily_*.jsonl.gz")):
        for r in _rows(p):
            if r.get("amounts"):
                out.append(p.name[len("balancer_daily_"):-len(".jsonl.gz")])
            break
    return out


def _raw(amount: str, decimals: int) -> int:
    return int((Decimal(amount) * (10 ** decimals)).to_integral_value())


def load_pools(day: str) -> dict[str, dict]:
    """Pool statics plus the day's closing balances, in RAW integer units."""
    pools: dict[str, dict] = {}
    for r in _rows(RAW / f"balancer_daily_{day}.jsonl.gz"):
        po = r.get("pool") or {}
        pid = (po.get("id") or "").lower()
        toks = po.get("tokens") or []
        order = [str(a).lower() for a in (po.get("tokensList") or [])]
        amounts = r.get("amounts") or []
        if not pid or not toks or len(order) != len(amounts):
            continue
        try:
            addresses = tuple((t.get("address") or "").lower() for t in toks)
            decimals = tuple(int(t["decimals"]) for t in toks)
            weights = tuple(int(Decimal(t["weight"]) * ONE) if t.get("weight") is not None
                            else 0 for t in toks)
            human = dict(zip(order, amounts))
            closing = tuple(_raw(human.get(a, "0"), d)
                            for a, d in zip(addresses, decimals))
            fee = int(Decimal(po.get("swapFee") or "0") * ONE)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        pools[pid] = {
            "tokens": addresses, "decimals": decimals, "weights": weights,
            "closing": closing, "fee": fee,
            "pool_type": po.get("poolType") or "unknown",
        }
    return pools


def load_trades(day: str) -> tuple[dict[str, list], dict[str, float]]:
    """The day's swaps per pool in execution order, with each pool's USD volume.

    Order matters because the reconstruction replays the flow. `block` orders across blocks and
    the decimal log index suffixed to the swap id orders within one block, which is the only
    intra-block ordering the raw layer carries.
    """
    staged: dict[str, list] = defaultdict(list)
    volume: dict[str, float] = defaultdict(float)
    for s in _rows(RAW / f"balancer_swaps_{day}.jsonl.gz"):
        pid = ((s.get("poolId") or {}).get("id") or "").lower()
        if not pid:
            continue
        try:
            usd = float(s.get("valueUSD") or 0)
        except (TypeError, ValueError):
            usd = 0.0
        volume[pid] += max(usd, 0.0)
        try:
            sid = str(s["id"])
            log_index = int(sid[66:]) if len(sid) > 66 else 0
            staged[pid].append((
                int(s["block"]), log_index,
                (s["tokenIn"] or "").lower(), (s["tokenOut"] or "").lower(),
                Decimal(s["tokenAmountIn"]), Decimal(s["tokenAmountOut"]), usd))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
    for v in staged.values():
        v.sort(key=lambda x: (x[0], x[1]))
    return staged, volume


def build_observations(meta: dict, staged: list) -> list | None:
    """One observation per trade, each carrying the balances that trade faced."""
    dec = dict(zip(meta["tokens"], meta["decimals"]))
    trades = []
    for _, _, t_in, t_out, amt_in, amt_out, usd in staged:
        if t_in not in dec or t_out not in dec or t_in == t_out:
            return None
        try:
            trades.append((t_in, t_out, _raw(str(amt_in), dec[t_in]),
                           _raw(str(amt_out), dec[t_out])))
        except ArithmeticError:
            return None
    if any(a <= 0 or b <= 0 for _, _, a, b in trades):
        return None
    path = rebuild_pre_trade_balances(meta["closing"], meta["tokens"], trades)
    if path is None:
        return None
    obs = []
    for balances, (t_in, t_out, amt_in, amt_out) in zip(path, trades):
        pool = WeightedPool(pool_id="rebuilt", tokens=meta["tokens"], balances=balances,
                            decimals=meta["decimals"], weights=meta["weights"],
                            fee=meta["fee"], pool_type=meta["pool_type"])
        obs.append((pool, t_in, t_out, amt_in, amt_out))
    return obs


def static_observations(meta: dict, obs: list, mode: str) -> list:
    """The same trades quoted against ONE balance vector, for the rival snapshot readings.

    `flat` holds the closing snapshot fixed all day, which is what a naive daily-snapshot quoter
    does. `opening` reads the snapshot as the day's first state and replays forward from there,
    which is the other plausible reading of the field.
    """
    if mode == "flat":
        pool = WeightedPool(pool_id="flat", tokens=meta["tokens"], balances=meta["closing"],
                            decimals=meta["decimals"], weights=meta["weights"],
                            fee=meta["fee"], pool_type=meta["pool_type"])
        return [(pool, t_in, t_out, a, b) for _, t_in, t_out, a, b in obs]
    idx = {t: i for i, t in enumerate(meta["tokens"])}
    running = list(meta["closing"])
    out = []
    for _, t_in, t_out, amt_in, amt_out in obs:
        pool = WeightedPool(pool_id="opening", tokens=meta["tokens"],
                            balances=tuple(running), decimals=meta["decimals"],
                            weights=meta["weights"], fee=meta["fee"],
                            pool_type=meta["pool_type"])
        out.append((pool, t_in, t_out, amt_in, amt_out))
        running[idx[t_in]] += amt_in
        running[idx[t_out]] -= amt_out
        if any(b <= 0 for b in running):
            running = list(meta["closing"])
    return out


def _pair(t_in: str, t_out: str) -> tuple[str, str]:
    return (t_in, t_out) if t_in < t_out else (t_out, t_in)


def fit_pool_day(fit_obs: list, gate: float) -> tuple[str, dict, int | None, float] | None:
    """Accept a pool-day on achieved fit error, as (mode, ratio map, fee, fit error).

    Three tiers, each adding at most one free scalar, tried in order of how much they assume.

    Read parameters first, because for a plain weighted pool that never repriced itself the
    reported weights and fee are exact and nothing needs identifying. Then the fee alone, which
    is the parameter most likely to be stale, since the subgraph serves it at the head block and
    a pool's owner can change it. Then the weight ratio per token pair, which is what a
    liquidity-bootstrapping or managed pool needs, since those move weights over time.

    When no tier clears the gate the pool-day is excluded, whatever its `poolType` says. That is
    the whole point: the label is a name and the fit error is a measurement.
    """
    reported = median_quote_error(fit_obs)
    if reported is not None and reported <= gate:
        return "reported", {}, None, reported

    fee_fit = calibrate_fee(fit_obs, max_error=gate)
    if fee_fit is not None:
        return "fee_fitted", {}, fee_fit[0], fee_fit[1]

    by_pair: dict[tuple[str, str], list] = defaultdict(list)
    for o in fit_obs:
        by_pair[_pair(o[1], o[2])].append(o)
    ratios: dict[tuple[str, str], Decimal] = {}
    for (a, b), sub in by_pair.items():
        fit = calibrate_weight_ratio(a, b, sub, max_error=gate)
        if fit is not None:
            ratios[(a, b)] = fit[0]
            ratios[(b, a)] = 1 / fit[0]
    if not ratios:
        return None
    errs = []
    for o in fit_obs:
        r = ratios.get((o[1], o[2]))
        if r is None:
            continue
        errs.extend(quote_errors([o], weight_ratio=r))
    if len(errs) < max(1, len(fit_obs) // 4):
        return None
    errs.sort()
    achieved = errs[len(errs) // 2]
    if achieved > gate:
        return None
    return "weight_fitted", ratios, None, achieved


def score(obs: list, ratios: dict, fee: int | None) -> list[float]:
    errs = []
    for o in obs:
        r = ratios.get((o[1], o[2])) if ratios else None
        if ratios and r is None:
            continue
        q = quote_exact_input(o[0], o[1], o[2], o[3], weight_ratio=r, fee=fee)
        if q is None or o[4] <= 0:
            continue
        errs.append(100 * abs(q - o[4]) / o[4])
    return errs


def evaluate_day(day: str, min_swaps: int, gate: float) -> dict | None:
    """Score one day, returning its exhibit row, or None when nothing on it is scorable."""
    pools = load_pools(day)
    staged, volume = load_trades(day)
    day_volume = sum(volume.values())

    priced = excluded = untested = 0
    vol_priced = vol_excluded = vol_untested = 0.0
    errs: list[float] = []
    flat_errs: list[float] = []
    open_errs: list[float] = []
    modes: dict[str, int] = defaultdict(int)
    excluded_types: dict[str, int] = defaultdict(int)
    priced_types: dict[str, int] = defaultdict(int)
    excluded_vol_types: dict[str, float] = defaultdict(float)
    by_type: dict[str, list[float]] = defaultdict(list)

    for pid, rec in staged.items():
        vol = volume.get(pid, 0.0)
        meta = pools.get(pid)
        if meta is None or len(rec) < min_swaps:
            untested += 1
            vol_untested += vol
            continue
        obs = build_observations(meta, rec)
        if obs is None:
            untested += 1
            vol_untested += vol
            continue
        # Alternate trades between the fitting set and the scoring set instead of cutting
        # the day in half. The two sets then straddle the whole day, so a join or an exit
        # part-way through, which moves balances and is not in this stream, breaks the
        # fit as well as the score and the pool-day is excluded. A first-half fit would
        # pass such a pool-day whenever the break landed after the cut, and it would then
        # contribute a large error to the panel while showing a clean fit.
        fit_obs, held_out = obs[::2], obs[1::2]
        fit = fit_pool_day(fit_obs, gate)
        if fit is None:
            excluded += 1
            vol_excluded += vol
            excluded_types[meta["pool_type"]] += 1
            excluded_vol_types[meta["pool_type"]] += vol
            continue
        mode, ratios, fee, _ = fit
        priced += 1
        vol_priced += vol
        priced_types[meta["pool_type"]] += 1
        modes[mode] += 1
        pool_errs = score(held_out, ratios, fee)
        errs.extend(pool_errs)
        by_type[meta["pool_type"]].extend(pool_errs)
        flat_errs.extend(score(static_observations(meta, held_out, "flat"), ratios, fee))
        open_errs.extend(
            score(static_observations(meta, held_out, "opening"), ratios, fee))

    if not errs:
        return None
    errs.sort()
    flat_errs.sort()
    open_errs.sort()
    tested = priced + excluded
    row = {
        "day": day,
        "pools_priced": priced,
        "pools_excluded": excluded,
        "pools_untested": untested,
        "pools_by_fit_mode": json.dumps(dict(sorted(modes.items())),
                                        sort_keys=True),
        "held_out_trades": len(errs),
        "median_abs_err_pct": errs[len(errs) // 2],
        "p25_abs_err_pct": errs[len(errs) // 4],
        "p75_abs_err_pct": errs[3 * len(errs) // 4],
        "p90_abs_err_pct": errs[min(len(errs) - 1, int(0.90 * len(errs)))],
        "p99_abs_err_pct": errs[min(len(errs) - 1, int(0.99 * len(errs)))],
        "within_1pct": 100 * sum(1 for e in errs if e < 1) / len(errs),
        "within_0_1pct": 100 * sum(1 for e in errs if e < 0.1) / len(errs),
        "median_abs_err_pct_by_pool_type": json.dumps(
            {k: statistics.median(v) for k, v in sorted(by_type.items()) if v},
            sort_keys=True),
        "held_out_trades_by_pool_type": json.dumps(
            {k: len(v) for k, v in sorted(by_type.items())}, sort_keys=True),
        "median_abs_err_pct_flat_snapshot": (
            flat_errs[len(flat_errs) // 2] if flat_errs else None),
        "median_abs_err_pct_opening_snapshot": (
            open_errs[len(open_errs) // 2] if open_errs else None),
        "excluded_vol_share_of_tested": (
            100 * vol_excluded / (vol_priced + vol_excluded)
            if vol_priced + vol_excluded > 0 else None),
        "priced_vol_share_of_day": (
            100 * vol_priced / day_volume if day_volume > 0 else None),
        "untested_vol_share_of_day": (
            100 * vol_untested / day_volume if day_volume > 0 else None),
        "excluded_pool_types": json.dumps(dict(sorted(excluded_types.items())),
                                          sort_keys=True),
        "priced_pool_types": json.dumps(dict(sorted(priced_types.items())),
                                        sort_keys=True),
        # The count of excluded pools says nothing about how much of the venue the panel
        # loses, so the exclusion is attributed to pool types by VOLUME. This is the line
        # that signs the coverage bound.
        "excluded_vol_share_of_day_by_pool_type": json.dumps(
            {k: 100 * v / day_volume for k, v in sorted(excluded_vol_types.items())}
            if day_volume > 0 else {}, sort_keys=True),
    }
    r = row
    fitted = modes["fee_fitted"] + modes["weight_fitted"]
    print(f"  {day}: {priced:>4}/{tested:<4} pools priced ({fitted} on a fitted "
          f"parameter), {untested:>4} untestable | "
          f"{len(errs):>6,} held-out trades | median |err| "
          f"{r['median_abs_err_pct']:>7.4f}% | within 1% {r['within_1pct']:>5.1f}% | "
          f"excluded vol {r['excluded_vol_share_of_tested'] or 0:>5.1f}% of tested")
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--min-swaps", type=int, default=8,
                    help="pool-days with fewer trades cannot be fitted and scored apart")
    ap.add_argument("--gate", type=float, default=MAX_CALIBRATION_ERROR,
                    help="achieved fit error above which a pool-day is excluded")
    args = ap.parse_args()

    days = days_with_amounts()
    if not days:
        print("no re-fetched Balancer days carry per-token balances yet")
        return 1
    # One slot per requested day, evenly spaced over the whole span, and a slot landing on a day
    # nothing can be said about walks forward inside its own slot. A day is scorable only if some
    # pool traded enough times to fit and score apart, and Balancer v2's genesis day carries two
    # swaps in total. Taking the first N days off a denser even grid instead would have covered
    # the sample's first third and called it the sample, which is how a validation ends up silent
    # about the years it never reached.
    slots = [i * len(days) // args.days for i in range(args.days)]
    print(f"{len(days)} Balancer days carry balances; sampling up to {args.days} scorable days "
          f"over {days[0]}..{days[-1]}\n")

    rows = []
    for k, start in enumerate(slots):
        stop = slots[k + 1] if k + 1 < len(slots) else len(days)
        for day in days[start:stop]:
            row = evaluate_day(day, args.min_swaps, args.gate)
            if row is not None:
                rows.append(row)
                break
        else:
            print(f"  slot {k} ({days[start]}..{days[stop - 1]}): no scorable day")

    if not rows:
        return 1
    med = statistics.median([r["median_abs_err_pct"] for r in rows])
    w1 = statistics.median([r["within_1pct"] for r in rows])
    flat = statistics.median([r["median_abs_err_pct_flat_snapshot"] for r in rows
                              if r["median_abs_err_pct_flat_snapshot"] is not None])
    opening = statistics.median([r["median_abs_err_pct_opening_snapshot"] for r in rows
                                 if r["median_abs_err_pct_opening_snapshot"] is not None])
    exc_vol = statistics.median([r["excluded_vol_share_of_tested"] for r in rows
                                 if r["excluded_vol_share_of_tested"] is not None])
    priced_vol = statistics.median([r["priced_vol_share_of_day"] for r in rows
                                    if r["priced_vol_share_of_day"] is not None])
    total_priced = sum(r["pools_priced"] for r in rows)
    total_tested = sum(r["pools_priced"] + r["pools_excluded"] for r in rows)
    total_untested = sum(r["pools_untested"] for r in rows)

    print(f"\nacross days: median of daily median errors {med:.4f}%, "
          f"median within-1% share {w1:.1f}%")
    print(f"pools priced {total_priced:,} of {total_tested:,} testable pool-days, with "
          f"{total_untested:,} pool-days holding too few trades to fit and score apart")
    print(f"excluded volume share of tested volume {exc_vol:.1f}%; priced volume share of "
          f"all Balancer swap volume {priced_vol:.1f}%")
    print(f"rival snapshot readings on the same held-out trades: closing snapshot held flat "
          f"{flat:.4f}%, snapshot read as the opening state {opening:.4f}%")

    excluded_volume: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        for k, v in json.loads(r["excluded_vol_share_of_day_by_pool_type"]).items():
            excluded_volume[k].append(v)
    ranked = sorted(((statistics.median(v), k) for k, v in excluded_volume.items()),
                    reverse=True)
    print("\nexcluded volume by pool type, as a median share of the day's Balancer swap volume:")
    for share, name in ranked:
        print(f"  {name:<24} {share:>6.1f}%")

    print("\nReading. The reconstruction and the invariant are tested together, so a small")
    print("error means both hold. The two rival snapshot readings are scored on the same")
    print("trades, which is what identifies the snapshot instant: a field whose meaning is")
    print("undocumented is settled by which reading reproduces trades. The excluded volume is")
    print("the signed coverage bound, and the ranking above says what would close it: the")
    print("stable family runs the StableSwap invariant with its own amplification coefficient,")
    print("which the current schema now fetches as `Pool.amp`, so those pools are a job for")
    print("ddvc.pricing.stableswap and not for this module.")
    write_exhibit(pd.DataFrame(rows), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


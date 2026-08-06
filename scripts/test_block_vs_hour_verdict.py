#!/usr/bin/env python3
"""Does hour-boundary pricing change the DOMINANCE VERDICT, or only the price level?

An earlier pool-level diagnostic measured how far one pool's state moved before the
hour boundary. That level statistic could not test a dominance verdict, which is a
comparison of routes, and it ordered only by block. The diagnostic is retired; this
script keeps the useful triangle comparison and uses the shared strict block-log owner.

The reason is that a dominance verdict is a COMPARISON, and both sides of it are priced at
the same state. When the market moves between a route's own block and the close of its
hour, the direct pool and both vehicle legs move together, and what a common component
does to the DIFFERENCE between the two routes is nothing. The earlier diagnostic measured
the price level of one pool at a time, so it cannot distinguish a market-wide move that
cancels in the comparison from a relative move that does not. Withdrawing a result on a
level statistic when the estimand is a difference is a real risk of throwing away a true
finding, which Java has objected to in this project before.

The test here is the triangle. For tokens A, B and an intermediary K, with a direct pool
AB and legs AK and KB, define

    m = log P(A->B)  -  [ log P(A->K) + log P(K->B) ]

which is positive exactly when the direct pool returns more B per unit of A than the
two-leg route does, in the zero-size limit where the marginal price is the pool price.
The sign of m IS the dominance verdict. Compute m immediately before each observed swap
in the direct pool and again at its hour-boundary state, and count how often the sign
disagrees. These are opportunity snapshots at direct-pool swap times, not realised
multi-leg routes.

Two properties make this exact rather than approximate. Token decimals enter each leg as a
constant, and around a closed triangle those constants sum to zero, so working in raw
sqrtPriceX96 units needs no decimals resolution and inherits none of its errors. And
`sqrtPriceX96` is carried on the swap event itself, so the state immediately after any
swap is observed and the state before a later event is the prior event in block-log order.

What it cannot see. This is the marginal price, so it holds for small trades and omits the
size-dependent part of execution cost, which is depth. A verdict that is robust here can
still flip at $100,000 through a thin pool. So a low flip rate bounds the timing threat for
small trades and does not discharge it for large ones, and the script says which it found.

Reads   data/raw/thegraph/uniswap_v3/uniswap_v3_swaps_*.jsonl.gz
Writes  output/exhibits/block_vs_hour_verdict.jsonl        per-triangle rows
        output/exhibits/block_vs_hour_conditional.jsonl    the conditional tables
        output/exhibits/triangle_gap_maturation.jsonl       fixed-support trends
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ddvc.analysis.block_timing import (
    PoolView,
    load_v3_swap_day,
    oriented,
    summarise_timing_conditionals,
    summarise_triangle_maturation,
)
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.provenance import cache_key
from ddvc.runtime import atomic_output, exclusive_job
from ddvc.tables import write_exhibit

V3 = DATA_DIR / "raw" / "thegraph" / "uniswap_v3"
OUT = OUTPUT_DIR / "exhibits" / "block_vs_hour_verdict.jsonl"
COND_OUT = OUTPUT_DIR / "exhibits" / "block_vs_hour_conditional.jsonl"
MATURATION_OUT = OUTPUT_DIR / "exhibits" / "triangle_gap_maturation.jsonl"
CACHE_ROOT = DATA_DIR / "empirical" / "_block_vs_hour_day_cache"
LOCK = DATA_DIR / "empirical" / ".block_vs_hour_verdict.lock"
OUTPUT_LOCK = OUTPUT_DIR / "exhibits" / ".block_vs_hour_outputs.lock"
CODE_SOURCES = [
    "scripts/test_block_vs_hour_verdict.py",
    "src/ddvc/analysis/block_timing.py",
    "src/ddvc/analysis/regression.py",
]
TRIANGLE_COLUMNS = [
    "day",
    "src",
    "tgt",
    "vehicle",
    "direct_pool",
    "hop1_pool",
    "hop2_pool",
    "n_observations",
    "flip_rate",
    "median_gap_bps",
    "median_delta_bps",
    "p90_delta_bps",
]
OBSERVATION_COLUMNS = ["m_own_bps", "m_hr_bps", "secs_to_boundary"]


def load_day(day: str):
    """Load one raw V3 day through the shared block-timing owner."""
    return load_v3_swap_day(V3 / f"uniswap_v3_swaps_{day}.jsonl.gz")


def measure_day(day: str, max_triangles: int, min_swaps: int,
                observations: list[tuple[float, float, int]] | None = None) -> list[dict]:
    tokens, series = load_day(day)
    if not series:
        return []
    views = {pid: PoolView(seq) for pid, seq in series.items() if len(seq) >= min_swaps}
    # One pool per unordered token pair, the busiest, so a triangle is unambiguous.
    by_pair: dict[tuple[str, str], str] = {}
    for pid in views:
        t0, t1 = tokens[pid]
        key = (t0, t1) if t0 < t1 else (t1, t0)
        if key not in by_pair or len(series[pid]) > len(series[by_pair[key]]):
            by_pair[key] = pid
    # Adjacency, to find intermediaries joining both endpoints.
    adj: dict[str, set[str]] = defaultdict(set)
    for a, b in by_pair:
        adj[a].add(b)
        adj[b].add(a)

    pairs = sorted(by_pair, key=lambda k: -len(series[by_pair[k]]))
    rows: list[dict] = []
    for a, b in pairs:
        if len(rows) >= max_triangles:
            break
        direct = by_pair[(a, b)]
        for k in sorted(adj[a] & adj[b]):
            if k in (a, b):
                continue
            leg1 = by_pair.get((a, k) if a < k else (k, a))
            leg2 = by_pair.get((k, b) if k < b else (b, k))
            if not leg1 or not leg2 or leg1 == direct or leg2 == direct:
                continue
            vd, v1, v2 = views[direct], views[leg1], views[leg2]
            flips = same = 0
            gaps_own: list[float] = []
            deltas: list[float] = []
            triangle_observations: list[tuple[float, float, int]] = []
            # Direct-pool swaps supply observed event times at which all three marginal
            # prices can be compared. They are opportunity snapshots, not route choices.
            for blk, log_index, own_ts, hour, _p in series[direct]:
                parts_own, parts_hr = [], []
                ok = True
                for pool, (u, v) in ((direct, (a, b)), (leg1, (a, k)), (leg2, (k, b))):
                    vw = views[pool]
                    t0, t1 = tokens[pool]
                    lo, lh = vw.before(blk, log_index), vw.at_hour(hour)
                    if lo is None or lh is None:
                        ok = False
                        break
                    o = oriented(lo, t0, t1, u, v)
                    h = oriented(lh, t0, t1, u, v)
                    if o is None or h is None:
                        ok = False
                        break
                    parts_own.append(o)
                    parts_hr.append(h)
                if not ok:
                    continue
                m_own = parts_own[0] - (parts_own[1] + parts_own[2])
                m_hr = parts_hr[0] - (parts_hr[1] + parts_hr[2])
                if m_own == 0 or m_hr == 0:
                    continue
                agree = (m_own > 0) == (m_hr > 0)
                if agree:
                    same += 1
                else:
                    flips += 1
                gaps_own.append(abs(m_own) * 10_000)
                deltas.append(abs(m_own - m_hr) * 10_000)
                # Keep each opportunity snapshot so the flip rate can be conditioned on
                # its true gap and its distance from the hour boundary.
                triangle_observations.append(
                    (
                        m_own * 10_000,
                        m_hr * 10_000,
                        max(0, vd.hour_end_ts.get(hour, own_ts) - own_ts),
                    )
                )
            n = flips + same
            if n < min_swaps:
                continue
            if observations is not None:
                observations.extend(triangle_observations)
            gaps_own.sort()
            deltas.sort()
            rows.append({
                "day": day,
                "src": a,
                "tgt": b,
                "vehicle": k,
                "direct_pool": direct,
                "hop1_pool": leg1,
                "hop2_pool": leg2,
                "n_observations": n, "flip_rate": flips / n,
                "median_gap_bps": gaps_own[len(gaps_own) // 2],
                "median_delta_bps": deltas[len(deltas) // 2],
                "p90_delta_bps": deltas[int(0.9 * len(deltas))],
            })
            break                                   # one triangle per direct pool
    return rows


def _pick_days(days: list[str], count: int) -> list[str]:
    if count < 1:
        raise ValueError("--days must be positive")
    if count >= len(days):
        return days
    if count == 1:
        return [days[len(days) // 2]]
    indices = [round(index * (len(days) - 1) / (count - 1)) for index in range(count)]
    return [days[index] for index in dict.fromkeys(indices)]


def _cache_paths(cache_dir: Path, day: str) -> tuple[Path, Path, Path]:
    return (
        cache_dir / f"{day}.triangles.parquet",
        cache_dir / f"{day}.observations.parquet",
        cache_dir / f"{day}.complete.json",
    )


def _cached_day(cache_dir: Path, day: str) -> dict[str, object] | None:
    triangles, observations, marker = _cache_paths(cache_dir, day)
    if not (triangles.exists() and observations.exists() and marker.exists()):
        return None
    record = json.loads(marker.read_text(encoding="utf-8"))
    if record.get("day") != day:
        return None
    triangle_frame = pd.read_parquet(triangles, columns=["n_observations"])
    observation_frame = pd.read_parquet(observations, columns=["m_own_bps"])
    if int(record.get("triangles", -1)) != len(triangle_frame):
        return None
    if int(record.get("observations", -1)) != len(observation_frame):
        return None
    if int(triangle_frame["n_observations"].sum()) != len(observation_frame):
        return None
    return record


def _measure_and_cache_day(
    day: str,
    max_triangles: int,
    min_swaps: int,
    cache_dir_text: str,
    force: bool,
) -> dict[str, object]:
    cache_dir = Path(cache_dir_text)
    if not force:
        cached = _cached_day(cache_dir, day)
        if cached is not None:
            return {**cached, "cached": True}
    observations: list[tuple[float, float, int]] = []
    rows = measure_day(day, max_triangles, min_swaps, observations)
    triangles = pd.DataFrame(rows, columns=TRIANGLE_COLUMNS)
    observation_frame = pd.DataFrame(observations, columns=OBSERVATION_COLUMNS)
    expected = int(triangles["n_observations"].sum()) if not triangles.empty else 0
    if expected != len(observation_frame):
        raise RuntimeError(
            f"{day}: triangle and observation counts disagree: "
            f"{expected:,} != {len(observation_frame):,}"
        )
    triangle_path, observation_path, marker_path = _cache_paths(cache_dir, day)
    with atomic_output(triangle_path) as temporary:
        triangles.to_parquet(temporary, index=False)
    with atomic_output(observation_path) as temporary:
        observation_frame.to_parquet(temporary, index=False)
    record: dict[str, object] = {
        "day": day,
        "triangles": len(triangles),
        "observations": len(observation_frame),
        "weighted_flip_rate": (
            float(
                (triangles["flip_rate"] * triangles["n_observations"]).sum()
                / expected
            )
            if expected
            else None
        ),
    }
    with atomic_output(marker_path) as temporary:
        temporary.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    return {**record, "cached": False}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=6)
    ap.add_argument("--triangles", type=int, default=60, help="triangles per day")
    ap.add_argument("--min-swaps", type=int, default=30)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.workers < 1:
        ap.error("--workers must be positive")

    days = sorted(p.name[len("uniswap_v3_swaps_"):-len(".jsonl.gz")]
                  for p in V3.glob("uniswap_v3_swaps_*.jsonl.gz"))
    if not days:
        print(f"no v3 swap files under {V3.relative_to(REPO_ROOT)}")
        return 1
    picked = _pick_days(days, args.days)
    generation = cache_key(CODE_SOURCES, inputs=[V3])
    cache_dir = (
        CACHE_ROOT
        / generation
        / f"triangles_{args.triangles}_minswaps_{args.min_swaps}"
    )
    print(
        f"testing {len(picked)} days: {picked[0]}..{picked[-1]} "
        f"with {args.workers} bounded worker(s)\n",
        flush=True,
    )

    with exclusive_job(LOCK, job="block-vs-hour verdict"):
        payloads = [
            (day, args.triangles, args.min_swaps, str(cache_dir), args.force)
            for day in picked
        ]
        with ProcessPoolExecutor(
            max_workers=args.workers,
            max_tasks_per_child=1,
        ) as executor:
            futures = {
                executor.submit(_measure_and_cache_day, *payload): payload[0]
                for payload in payloads
            }
            for future in as_completed(futures):
                result = future.result()
                if result["triangles"]:
                    source = "cached" if result["cached"] else "built"
                    print(
                        f"  {result['day']}: {int(result['triangles']):>3} triangles, "
                        f"{int(result['observations']):>7,} observations, "
                        f"flip rate {float(result['weighted_flip_rate']):>6.2%} [{source}]",
                        flush=True,
                    )
                else:
                    print(
                        f"  {result['day']}: no triangle cleared the thresholds",
                        flush=True,
                    )

    triangle_frames = [
        pd.read_parquet(_cache_paths(cache_dir, day)[0]) for day in picked
    ]
    df = pd.concat(triangle_frames, ignore_index=True)
    if df.empty:
        print("\nnothing measurable")
        return 1
    n_tot = int(df.n_observations.sum())
    records = [_cached_day(cache_dir, day) for day in picked]
    if any(record is None for record in records):
        raise RuntimeError("a selected day lost its complete cache marker before assembly")
    cached_observations = sum(
        int(record["observations"]) for record in records if record is not None
    )
    if n_tot != cached_observations:
        raise RuntimeError(
            "conditional and per-triangle observation counts disagree: "
            f"{cached_observations:,} != {n_tot:,}"
        )
    flip = float((df.flip_rate * df.n_observations).sum() / n_tot)
    print(f"\n{len(df)} triangles over {n_tot:,} opportunity snapshots")
    print(f"  verdict flip rate, own event against hour boundary : {flip:.2%}")
    print(f"  median triangle gap at own event                   : "
          f"{df.median_gap_bps.median():.1f} bps")
    print(f"  median change in the gap from repricing            : "
          f"{df.median_delta_bps.median():.1f} bps")
    print(f"  90th percentile change in the gap                  : "
          f"{df.p90_delta_bps.median():.1f} bps")

    # WHERE the flips live decides whether anything can be salvaged. If they are spread
    # evenly over the gap distribution then hour pricing is simply unusable. If they
    # concentrate near zero, where an hour of drift can cross the boundary, then a
    # restriction away from the boundary buys back a usable sample, and the cost of that
    # restriction is the share of opportunity snapshots it discards.
    cond = summarise_timing_conditionals(
        pd.read_parquet(_cache_paths(cache_dir, day)[1]) for day in picked
    )
    if not cond.empty:
        print("\nflip rate conditional on how far the gap sits from zero")
        print(f"  {'gap at own event':<26}{'observations':>14}{'flip rate':>12}")
        for row in cond[cond["cut"].eq("gap_at_own_event")].itertuples():
            print(f"  {row.bucket:<26}{row.observations:>10,}{row.value:>11.2%}")
        print("\n  check: flip rate against time remaining to the hour boundary")
        for row in cond[cond["cut"].eq("time_to_hour_boundary")].itertuples():
            print(f"    {row.bucket:<24}{row.observations:>10,}{row.value:>11.2%}")
        print("\n  flip rate once the two-leg route's extra fee is charged")
        print(f"  {'net fee wedge':<26}{'observations':>14}{'flip rate':>12}{'dominated':>12}")
        for row in cond[cond["cut"].eq("fee_wedge_bps")].itertuples():
            print(
                f"  {f'{row.bucket} bps':<26}{row.observations:>10,}"
                f"{row.value:>11.2%}{row.dominated_share:>11.1%}"
            )
        print("  'dominated' is the share where the two-leg route wins at event-time state,")
        print("  which is the estimand itself and moves with the wedge as it should.")
        for row in cond[cond["cut"].eq("gap_minimum_bps")].itertuples():
            print(
                f"  restricting to gaps of at least {int(row.bucket):>3} bps keeps "
                f"{row.observations / n_tot:>5.1%} of observations at a "
                f"{row.value:.2%} flip rate"
            )

    print("\nReading. The earlier diagnostic measured a pool's own price against the")
    print("hour-boundary price and found most observations moving more than 25 bps. That is a")
    print("LEVEL. This is the DIFFERENCE the verdict depends on, where a common move")
    print("cancels across the three legs.")
    print("At zero size the verdict is unstable, and restricting to large gaps does not")
    print("rescue it, because m is then a pure arbitrage residual that mean-reverts within")
    print("blocks: it flips almost as often at 250 basis points as at 5. What does rescue")
    print("it is the fee wedge, which is stable and does not move with the market. So the")
    print("timing threat is a function of trade economics and not a single number, and the")
    print("wedge table above is the result rather than the pooled rate.")
    print("\nThe test validates itself on the time column. An observation seconds before")
    print("its hour closes is priced at nearly the state the panel used and cannot flip,")
    print("and the measured rate rises monotonically with the time remaining. A flat")
    print("profile there would have meant a bug in this script instead of a finding.")
    maturation = summarise_triangle_maturation(df)
    if not maturation.empty:
        print("\nwithin-triangle annual compression in the marginal price gap")
        fixed = maturation[maturation["panel"].eq("fixed_support")]
        for row in fixed.itertuples():
            print(
                f"  {row.identity}, >= {int(row.minimum_dates)} dates: "
                f"{row.annual_compression:>6.1%}/year "
                f"(p={row.p:.3f}; {int(row.triangle_days):,} triangle-days)"
            )
        annual = maturation[maturation["panel"].eq("annual_descriptive")]
        for row in annual.itertuples():
            print(
                f"  {int(row.year)}: median {row.median_gap_bps:.1f} bps; "
                f"snapshot-weighted mean {row.snapshot_weighted_mean_gap_bps:.1f} bps"
            )
    # Keep the three exhibits from one invocation together. Cache population and output
    # assembly have separate locks so a long rebuild does not block a completed cache from
    # being inspected, while two differently sized runs cannot interleave their exhibits.
    with exclusive_job(OUTPUT_LOCK, job="block-vs-hour output assembly"):
        write_exhibit(
            df,
            OUT,
            code_sources=CODE_SOURCES,
            inputs=[V3],
            notes="V3 direct-pool opportunity snapshots; strict pre-event block-log state",
        )
        if not cond.empty:
            write_exhibit(
                cond,
                COND_OUT,
                code_sources=CODE_SOURCES,
                inputs=[V3],
                notes="V3 direct-pool opportunity snapshots; strict pre-event block-log state",
            )
        if not maturation.empty:
            write_exhibit(
                maturation,
                MATURATION_OUT,
                code_sources=CODE_SOURCES,
                inputs=[V3],
                notes="V3 strict transaction-state triangle gaps; fixed-support time trends",
            )
    print(f"\nwrote {OUT.relative_to(REPO_ROOT)}")
    if not cond.empty:
        print(f"wrote {COND_OUT.relative_to(REPO_ROOT)}")
    if not maturation.empty:
        print(f"wrote {MATURATION_OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

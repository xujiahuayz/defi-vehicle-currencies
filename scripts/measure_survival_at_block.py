#!/usr/bin/env python3
"""The survival arms, with dominance judged at each route's own block.

Section 4 of the paper specifies two durations on the same pairs. The RETENTION arm counts
the days an incumbent vehicle keeps the largest routing share on a pair after it stops
being the cheapest way to trade. The DISPLACEMENT arm counts the days a cheaper challenger
takes to take that share. Equal durations are persistence under symmetric frictions;
retention exceeding displacement is hysteresis, and its size in days is the quantity the
currency-inertia literature has never been able to measure.

Both arms need a dominance verdict per pair, per candidate, per day. The route-cost panel
supplies one at the close of each hour, and `scripts/test_block_vs_hour_verdict.py` measured
what that costs: at the fee wedges these routes actually pay, 15% to 25% of verdicts differ
from the verdict at the route's own block. A duration contrast that turns on a few
percentage points between asset types cannot be separated from a misclassification of that
size, which is why the arms are not reported off hour-boundary state.

This computes them at block level instead, on the population where block state is OBSERVED
and needs no reconstruction. Uniswap v3 carries `sqrtPriceX96` on the swap event, so for a
triangle of pools joining a, b and an intermediary k, the sign of

    m = log P(a->b) - [log P(a->k) + log P(k->b)] + wedge

is the dominance verdict at any block, exactly, with token decimals cancelling around the
closed triangle. The wedge is the extra pool fee a two-leg route pays over a direct one,
which is the stable part of the comparison and the part that decides the verdict at
realistic size.

What this is and is not. It is a block-exact measurement on one venue family at the
marginal price, so it omits depth and it omits the venues v3 does not cover. It is the
right robustness counterpart to an hour-level panel estimate over six venues: the two have
opposite weaknesses, and a duration ordering that survives both is not an artefact of
either. Where they disagree, the block-level one is right about timing and the panel is
right about coverage, and the paper reports both.

Reads   data/raw/thegraph/uniswap_v3/uniswap_v3_swaps_*.jsonl.gz
        data/unified/YYYYMMDD.parquet                 realised routing shares
Writes  output/exhibits/survival_at_block.jsonl       the two arms, with censoring
        output/exhibits/survival_at_block_spells.jsonl  every spell, for inspection
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

# Reuse the validated triangle machinery instead of restating it. Its decimals argument and
# its orientation handling are the part most likely to be got wrong twice.
sys.path.insert(0, str(ROOT / "scripts"))
from test_block_vs_hour_verdict import load_day, PoolView, oriented  # noqa: E402

UNIFIED = ROOT / "data" / "unified"
OUT = ROOT / "output" / "exhibits" / "survival_at_block.jsonl"
SPELLS = ROOT / "output" / "exhibits" / "survival_at_block_spells.jsonl"
HAZ_PANEL = ROOT / "output" / "exhibits" / "survival_at_block_panel.jsonl"

# A two-leg route pays two pool fees where a direct route pays one. Uniswap v3's common
# tiers are 5, 30 and 100 basis points, so 30 is the extra burden when all three legs sit
# on the 30bp tier, which is the modal configuration. The sweep in
# test_block_vs_hour_verdict.py shows the verdict is sensitive to this, so it is a
# parameter and the headline is reported across a range of it.
DEFAULT_WEDGE_BPS = 30.0


def dominance_by_day(day: str, wedge_bps: float, min_swaps: int,
                     max_triangles: int) -> dict[tuple[str, str, str], float]:
    """Share of the day's blocks on which routing a->b through k was NOT the cheaper way.

    Keyed by (a, b, k). A value near 1 means the vehicle was dominated all day.
    """
    tokens, series = load_day(day)
    if not series:
        return {}
    views = {pid: PoolView(seq) for pid, seq in series.items() if len(seq) >= min_swaps}
    by_pair: dict[tuple[str, str], str] = {}
    for pid in views:
        t0, t1 = tokens[pid]
        key = (t0, t1) if t0 < t1 else (t1, t0)
        if key not in by_pair or len(series[pid]) > len(series[by_pair[key]]):
            by_pair[key] = pid
    adj: dict[str, set[str]] = defaultdict(set)
    for a, b in by_pair:
        adj[a].add(b)
        adj[b].add(a)

    out: dict[tuple[str, str, str], float] = {}
    wedge = wedge_bps / 10_000.0
    pairs = sorted(by_pair, key=lambda k: -len(series[by_pair[k]]))[:max_triangles]
    for a, b in pairs:
        direct = by_pair[(a, b)]
        for k in sorted(adj[a] & adj[b]):
            if k in (a, b):
                continue
            leg1 = by_pair.get((a, k) if a < k else (k, a))
            leg2 = by_pair.get((k, b) if k < b else (b, k))
            if not leg1 or not leg2 or leg1 == direct or leg2 == direct:
                continue
            dom = tot = 0
            for blk, _ts, _hr, _p in series[direct]:
                parts = []
                for pool, (u, v) in ((direct, (a, b)), (leg1, (a, k)), (leg2, (k, b))):
                    lp = views[pool].at_block(blk)
                    if lp is None:
                        break
                    t0, t1 = tokens[pool]
                    o = oriented(lp, t0, t1, u, v)
                    if o is None:
                        break
                    parts.append(o)
                if len(parts) != 3:
                    continue
                # m > 0 means the DIRECT pool returns more, so the vehicle is dominated.
                m = parts[0] - (parts[1] + parts[2]) + wedge
                tot += 1
                dom += 1 if m > 0 else 0
            if tot >= min_swaps:
                out[(a, b, k)] = dom / tot
    return out


def routing_shares(day: str) -> dict[tuple[str, str, str], float]:
    """Realised share of a->b routing that went through k, from executed routes."""
    p = UNIFIED / f"{day}.parquet"
    if not p.exists():
        return {}
    d = pd.read_parquet(p, columns=["tx_hash", "component_id", "token_in", "token_out",
                                    "amount_usd", "log_index", "route_class"])
    d = d[d.route_class.isin(["single", "coherent"]) & (d.amount_usd > 0)]
    if d.empty:
        return {}
    d = d.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for (_tx, _c), g in d.groupby(["tx_hash", "component_id"], sort=False):
        tin, tout = g.token_in.tolist(), g.token_out.tolist()
        if len(g) < 2 or tin[0] == tout[-1]:
            continue                       # single leg, or a round trip carrying no value
        a, b = tin[0], tout[-1]
        key = (a, b) if a < b else (b, a)
        totals[key] += 1
        for k in {t for t in tout[:-1] if t}:
            counts[(key[0], key[1], k)] += 1
    return {kk: c / totals[(kk[0], kk[1])] for kk, c in counts.items()
            if totals[(kk[0], kk[1])] >= 5}


def turnover_hazard(panel: pd.DataFrame, dominated_at: float) -> list[dict]:
    """How much faster does the role turn over when its holder is dominated?

    THIS IS THE ESTIMAND, and the two-arm version below is descriptive only. The reason is
    a defect in the naive comparison that shows up as soon as it is measured. A retention
    spell ends when ANY challenger takes the lead, while a displacement spell asks whether
    ONE NAMED challenger takes it, so retention is a minimum over the candidate set and
    displacement is a single draw from it. With several candidates on a pair, retention is
    shorter by construction, and the gap widens with the number of candidates instead of
    with any economic force. Measured over sixty days the naive arms give 5.74 days against
    23.90, which is that artefact and not a finding.

    The symmetric question uses ONE event, leadership on a pair changing hands, and
    conditions it on whether the current holder is dominated. Both conditions are evaluated
    on the same pairs, over the same days, with the same event. The comparison is then a
    hazard ratio: how much more likely is the role to move on a day when its holder is
    losing on cost than on a day when it is not.

    Hysteresis is a hazard ratio near one, meaning that losing the cost advantage barely
    raises the chance of losing the role, which is protection a symmetric friction cannot
    produce. A large ratio is the competitive case, where the role follows cost.
    """
    rows: list[dict] = []
    for (a, b), g in panel.groupby(["src", "tgt"], sort=False):
        days = sorted(g.day.unique())
        if len(days) < 5:
            continue
        lead = {d: sub.sort_values("share", ascending=False).iloc[0].vehicle
                for d, sub in g.groupby("day")}
        dom = {(r.day, r.vehicle): r.dominated for r in g.itertuples()}
        n_cand = g.groupby("day").vehicle.nunique()
        for i, d in enumerate(days[:-1]):
            k = lead.get(d)
            if k is None:
                continue
            dv = dom.get((d, k))
            if dv is None:
                continue
            rows.append({
                "src": a, "tgt": b, "day": d, "holder": k,
                "holder_dominated": int(dv >= dominated_at),
                # The event: did the role move to a different asset the next day?
                "turned_over": int(lead.get(days[i + 1]) not in (None, k)),
                # Carried so the ratio can be reported holding the candidate count fixed,
                # since more candidates mean more ways for the role to move.
                "n_candidates": int(n_cand.get(d, 1)),
                "mid_type": classify(k)[1],
            })
    return rows


def spells(panel: pd.DataFrame, dominated_at: float) -> list[dict]:
    """Retention and displacement spells, on the same pairs, with right-censoring.

    Descriptive only. See `turnover_hazard` for why the difference between these two arms
    is contaminated by a minimum-over-candidates artefact and is not the estimand.
    """
    rows: list[dict] = []
    for (a, b), g in panel.groupby(["src", "tgt"], sort=False):
        g = g.sort_values("day")
        days = sorted(g.day.unique())
        if len(days) < 5:
            continue
        # The incumbent on each day is the candidate holding the largest routing share.
        lead = {d: sub.sort_values("share", ascending=False).iloc[0].vehicle
                for d, sub in g.groupby("day")}
        dom = {(r.day, r.vehicle): r.dominated for r in g.itertuples()}
        for k in g.vehicle.unique():
            for i, d in enumerate(days[:-1]):
                was_lead = lead.get(d) == k
                is_dom = dom.get((d, k), 0.0) >= dominated_at
                if was_lead and is_dom and (i == 0 or lead.get(days[i - 1]) != k
                                            or dom.get((days[i - 1], k), 0.0) < dominated_at):
                    # RETENTION: how long does a dominated incumbent keep the lead?
                    n, censored = 0, True
                    for d2 in days[i + 1:]:
                        if lead.get(d2) != k:
                            censored = False
                            break
                        n += 1
                    rows.append({"src": a, "tgt": b, "vehicle": k, "arm": "retention",
                                 "start": d, "days": n, "censored": int(censored)})
                if (not was_lead) and (not is_dom) and dom.get((d, k), 1.0) < dominated_at:
                    prev_dom = dom.get((days[i - 1], k), 1.0) if i else 1.0
                    if prev_dom < dominated_at:
                        continue           # already cheap yesterday, not a fresh edge
                    # DISPLACEMENT: how long does a cheaper challenger take to take over?
                    n, censored = 0, True
                    for d2 in days[i + 1:]:
                        if lead.get(d2) == k:
                            censored = False
                            break
                        n += 1
                    rows.append({"src": a, "tgt": b, "vehicle": k, "arm": "displacement",
                                 "start": d, "days": n, "censored": int(censored)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=None, help="first day, YYYYMMDD")
    ap.add_argument("--days", type=int, default=30, help="consecutive days to measure")
    ap.add_argument("--wedge-bps", type=float, default=DEFAULT_WEDGE_BPS)
    ap.add_argument("--dominated-at", type=float, default=0.5,
                    help="share of the day's blocks dominated before a day counts dominated")
    ap.add_argument("--min-swaps", type=int, default=30)
    ap.add_argument("--triangles", type=int, default=120)
    args = ap.parse_args()

    V3 = ROOT / "data" / "raw" / "thegraph" / "uniswap_v3"
    avail = sorted(p.name[len("uniswap_v3_swaps_"):-len(".jsonl.gz")]
                   for p in V3.glob("uniswap_v3_swaps_*.jsonl.gz"))
    if not avail:
        print("no v3 swap files")
        return 1
    if args.start:
        avail = [d for d in avail if d >= args.start]
    picked = avail[: args.days]
    print(f"measuring {len(picked)} consecutive days {picked[0]}..{picked[-1]} "
          f"at a {args.wedge_bps:.0f} bps fee wedge\n", flush=True)

    recs: list[dict] = []
    for i, day in enumerate(picked, 1):
        dom = dominance_by_day(day, args.wedge_bps, args.min_swaps, args.triangles)
        if not dom:
            print(f"  {day}: no triangle", flush=True)
            continue
        sh = routing_shares(day)
        hit = 0
        for (a, b, k), dshare in dom.items():
            key = (a, b, k) if a < b else (b, a, k)
            s = sh.get(key)
            if s is None:
                continue
            hit += 1
            recs.append({"day": day, "src": key[0], "tgt": key[1], "vehicle": k,
                         "dominated": dshare, "share": s,
                         "mid_type": classify(k)[1]})
        print(f"  {day}: {len(dom):>4} triangles priced, {hit:>4} joined to realised shares",
              flush=True)

    if not recs:
        print("\nnothing joined. The triangles and the realised routes share no pair, which")
        print("would mean the v3 population and the routed population are disjoint.")
        return 1
    panel = pd.DataFrame(recs)
    n_days = panel.day.nunique()
    print(f"\n{len(panel):,} pair-candidate-days over {n_days} days, "
          f"{panel.groupby(['src', 'tgt']).ngroups:,} pairs")

    # THE ESTIMAND FIRST. One event, conditioned two ways, on the same pairs and days.
    haz = pd.DataFrame(turnover_hazard(panel, args.dominated_at))
    if not haz.empty:
        write_exhibit(haz, HAZ_PANEL)
        print(f"\nwrote {HAZ_PANEL.relative_to(ROOT)} for the conditional estimation")
    out = []
    if not haz.empty:
        print(f"\nturnover of the vehicle role, one event conditioned on the holder's cost "
              f"position, {len(haz):,} pair-days")
        print(f"  {'holder':<26}{'pair-days':>11}{'turned over':>13}")
        rate = {}
        for dominated, g in haz.groupby("holder_dominated"):
            lab = "losing on cost" if dominated else "cheapest available"
            rate[int(dominated)] = float(g.turned_over.mean())
            print(f"  {lab:<26}{len(g):>11,}{g.turned_over.mean():>12.2%}")
            out.append({"arm": f"turnover_holder_{'dominated' if dominated else 'cheapest'}",
                        "spells": int(len(g)), "censored_share": float("nan"),
                        "mean_days": float(g.turned_over.mean()),
                        "median_days": float("nan"),
                        "wedge_bps": args.wedge_bps, "days_measured": int(n_days)})
        if 0 in rate and 1 in rate and rate[0] > 0:
            ratio = rate[1] / rate[0]
            print(f"\n  hazard ratio {ratio:.2f}: losing the cost advantage multiplies the "
                  f"daily chance of losing the role by this much")
            out.append({"arm": "turnover_hazard_ratio", "spells": int(len(haz)),
                        "censored_share": float("nan"), "mean_days": ratio,
                        "median_days": float("nan"), "wedge_bps": args.wedge_bps,
                        "days_measured": int(n_days)})
            if ratio < 1.5:
                print("  A ratio near one is the hysteresis reading: cost is losing its grip")
                print("  on who holds the role, which is protection a symmetric friction")
                print("  cannot produce.")
            else:
                print("  The role follows cost closely, which is the competitive reading and")
                print("  leaves little room for an incumbency premium.")
        # Holding the candidate count fixed, since more candidates mean more ways to move.
        print(f"\n  {'candidates on the pair':<26}{'cheapest':>11}{'dominated':>12}")
        for n, g in haz.groupby("n_candidates"):
            if len(g) < 100:
                continue
            a0 = g[g.holder_dominated == 0].turned_over
            a1 = g[g.holder_dominated == 1].turned_over
            if len(a0) < 30 or len(a1) < 30:
                continue
            print(f"  {n:<26}{a0.mean():>10.2%}{a1.mean():>12.2%}")

    rows = spells(panel, args.dominated_at)
    if not rows:
        print("no spell cleared the definition")
        return 1
    sp = pd.DataFrame(rows)
    write_exhibit(sp, SPELLS)
    print("\nThe two arms below are DESCRIPTIVE. A retention spell ends when any challenger")
    print("takes the lead and a displacement spell asks whether one named challenger does,")
    print("so retention is a minimum over the candidate set and displacement a single draw")
    print("from it. Their difference widens with the number of candidates, and the estimand")
    print("above avoids that by conditioning one event two ways.")

    print(f"\n  {'arm':<14}{'spells':>8}{'censored':>10}{'mean days':>11}{'median':>8}")
    for arm, g in sp.groupby("arm"):
        out.append({"arm": arm, "spells": int(len(g)),
                    "censored_share": float(g.censored.mean()),
                    "mean_days": float(g.days.mean()),
                    "median_days": float(g.days.median()),
                    "wedge_bps": args.wedge_bps, "days_measured": int(n_days)})
        r = out[-1]
        print(f"  {arm:<14}{r['spells']:>8,}{r['censored_share']:>9.1%}"
              f"{r['mean_days']:>11.2f}{r['median_days']:>8.1f}")

    ret = next((r for r in out if r["arm"] == "retention"), None)
    dis = next((r for r in out if r["arm"] == "displacement"), None)
    if ret and dis:
        diff = ret["mean_days"] - dis["mean_days"]
        print(f"\n  retention minus displacement: {diff:+.2f} days")
        if diff > 0:
            print("  Retention exceeds displacement, which is the hysteresis ordering. The")
            print("  incumbent holds on longer than a challenger takes to break in, so the")
            print("  system's response depends on the direction of the shock.")
        else:
            print("  Displacement is at least as fast as retention, which is persistence")
            print("  under symmetric frictions and NOT hysteresis. That would reject the")
            print("  asymmetry this paper was written to test, and it is the more")
            print("  interesting result of the two.")
        print("\n  Censoring is reported above and is not ignored: a spell still running at")
        print("  the end of the window enters as censored, and a high censored share means")
        print("  the window is too short for the durations present.")
        out.append({"arm": "DIFFERENCE", "spells": 0, "censored_share": float("nan"),
                    "mean_days": diff, "median_days": float("nan"),
                    "wedge_bps": args.wedge_bps, "days_measured": int(n_days)})
    write_exhibit(pd.DataFrame(out), OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)} and {SPELLS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

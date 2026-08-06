#!/usr/bin/env python3
"""Is the stable numéraire's rise a currency fact or a stableswap-venue artefact?

Node K's sharpest proposal and it threatens this project's lead result directly. The
stable numéraire's rise as an intermediary coincides in time with the rise of venues
running the StableSwap invariant, which exists precisely to make stable-to-stable swaps
cheap. If routing shifts toward stables because a new venue made stable legs cheap, that
is a statement about AMM technology and not about a currency acquiring the vehicle role,
and the paper's headline would be a Curve artefact wearing a monetary-economics label.

The test is cheap because the unified layer already carries `source` per leg. Recompute
the intermediation series on the CONSTANT-PRODUCT SUBSET, meaning Uniswap v2, SushiSwap
v2, Uniswap v3 and Uniswap v4, all of which price the same family of curve and none of
which is specialised for stables. If the stable rise survives there, the transition is
about which asset intermediates and the venue-technology rival is dead. If it vanishes,
the lead result is about Curve.

Reported as three series so the comparison is visible rather than asserted: all venues,
constant-product only, and stableswap venues only. The last is not a control, it is the
thing being separated out, and it should show the strongest stable share by construction.

Reads   data/unified/YYYYMMDD.parquet
Writes  output/exhibits/venue_technology_rival.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit  # noqa: E402

UNIFIED = ROOT / "data" / "unified"
OUT = ROOT / "output" / "exhibits" / "venue_technology_rival.jsonl"

CONSTANT_PRODUCT = {"uniswap_v2", "sushiswap_v2", "uniswap_v3", "uniswap_v4"}
STABLESWAP = {"curve", "balancer"}


def shares_for(day: str, venues: set[str] | None) -> dict[str, float]:
    p = UNIFIED / f"{day}.parquet"
    if not p.exists():
        return {}
    cols = ["tx_hash", "component_id", "token_in", "token_out", "amount_usd",
            "log_index", "route_class", "source"]
    d = pd.read_parquet(p, columns=cols)
    d = d[d.route_class.isin(["single", "coherent"])]
    d = d[(d.amount_usd > 0) & (d.amount_usd < 1e9)]
    if venues is not None:
        # Keep a route only if EVERY leg sits on the venue set, since a route with one
        # leg on Curve is partly a Curve route and would smuggle the rival back in.
        ok = d.groupby(["tx_hash", "component_id"]).source.transform(
            lambda s: s.isin(venues).all())
        d = d[ok]
    if d.empty:
        return {}
    d = d.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    acc: dict[str, float] = {}
    for (_t, _c), g in d.groupby(["tx_hash", "component_id"], sort=False):
        if len(g) < 2:
            continue
        tin, tout = g.token_in.tolist(), g.token_out.tolist()
        if tin[0] == tout[-1]:
            continue
        usd = float(g.amount_usd.max())
        for interior in {t for t in tout[:-1] if t}:
            _sym, typ = classify(interior)
            acc[typ] = acc.get(typ, 0.0) + usd
    tot = sum(acc.values())
    return {k: v / tot for k, v in acc.items()} if tot > 0 else {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stride", type=int, default=90)
    args = ap.parse_args()

    days = sorted(p.stem for p in UNIFIED.glob("[0-9]" * 8 + ".parquet"))[:: args.stride]
    print(f"testing the venue-technology rival on {len(days)} days "
          f"({days[0]}..{days[-1]})\n")

    rows = []
    for i, day in enumerate(days, 1):
        for label, vs in (("all venues", None),
                          ("constant-product only", CONSTANT_PRODUCT),
                          ("stableswap venues only", STABLESWAP)):
            s = shares_for(day, vs)
            if not s:
                continue
            rows.append({"day": day, "basis": label,
                         "native": s.get("native", 0.0), "stable": s.get("stable", 0.0),
                         "imported": s.get("imported", 0.0), "other": s.get("other", 0.0)})
        if i % 5 == 0 or i == len(days):
            print(f"  {i}/{len(days)} {day}", flush=True)

    if not rows:
        print("nothing measured")
        return 1
    p = pd.DataFrame(rows)
    p["year"] = pd.to_datetime(p.day, format="%Y%m%d").dt.year

    for basis in ("all venues", "constant-product only", "stableswap venues only"):
        b = p[p.basis == basis]
        if b.empty:
            continue
        print(f"\n{basis.upper()}: share of intermediation value by asset type")
        print(f"  {'year':>6}{'native':>10}{'stable':>10}{'imported':>10}")
        for yr, g in b.groupby("year"):
            print(f"  {yr:>6}{g.native.mean():>9.1%}{g.stable.mean():>10.1%}"
                  f"{g.imported.mean():>10.1%}")

    cp = p[p.basis == "constant-product only"].groupby("year")[["native", "stable"]].mean()
    if len(cp) >= 2:
        d_stable = cp.stable.iloc[-1] - cp.stable.iloc[0]
        d_native = cp.native.iloc[-1] - cp.native.iloc[0]
        print(f"\n  On constant-product venues ALONE, across the sample:")
        print(f"    stable share moved {d_stable:+.1%}, native share moved {d_native:+.1%}")
        if d_stable > 0.05:
            print("  => the rival is DEAD. The stable rise happens on venues with no")
            print("     stableswap technology, so it is about which asset intermediates.")
        elif d_stable < 0.0:
            print("  => the rival WINS. The stable rise does not exist without stableswap")
            print("     venues, so the lead result is about AMM technology.")
        else:
            print("  => partial. Report both series and attribute the split explicitly.")
    write_exhibit(p, OUT)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

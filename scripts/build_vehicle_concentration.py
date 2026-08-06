#!/usr/bin/env python3
"""Is the vehicle role being SUCCEEDED or FRAGMENTED? Concentration, not just share.

Java's framing, and it separates two things the international currency literature
routinely conflates. A falling incumbent share is consistent with two very different
worlds. Under SUCCESSION one vehicle replaces another, so concentration stays high and
only the leader's identity changes, which is the sterling-to-dollar story. Under
MULTIPOLARITY the role fragments across several assets, so concentration falls while the
incumbent may still lead, which is dominance eroding without displacement. The dollar
against the euro and the renminbi is exactly this question and FX cannot settle it,
because the counterfactual currency network is unobservable.

A Herfindahl-Hirschman index over vehicle shares distinguishes them directly, and the
pair of statistics does the work that neither does alone:

  HHI, the sum of squared shares, falls when the role fragments and holds when it merely
  changes hands. Its reciprocal is the EFFECTIVE NUMBER of vehicles, which is the
  interpretable form: an HHI of 0.5 means two effective vehicles whatever the tail does.

  CR1, the leader's share, together with the leader's IDENTITY. Succession shows a stable
  CR1 with a changing identity. Multipolarity shows a falling CR1 with a stable identity.
  Reporting either alone cannot tell them apart, so both are reported and the leader is
  named in every period.

Computed on a two-by-two, because a share and a centrality are only comparable when they
are weighted the same way. An earlier version compared VOLUME shares against TOPOLOGICAL
betweenness, which is unweighted, so any disagreement between them could have been the
weighting and not the measure. Java caught it. The grid fixes it: volume share against
volume-weighted centrality, and count share against count-weighted centrality, so the
share-versus-centrality contrast is clean within each weighting and the volume-versus-count
contrast is clean within each measure.

Count matters on its own terms here. The vehicle role is about how often traders route
through an asset and not how much value they move, and value weighting is where this data
is most contaminated, since round trips run 12.7% of multi-leg routes by count against
21.7% by value on the median day, and reach 25.9% against 91.3% on the worst day observed. A single large transfer can make an asset look central; a thousand small ones
mean it is.

Reads   data/unified/YYYYMMDD.parquet
        data/processed/vehicle_centrality.parquet
Writes  data/processed/vehicle_concentration.parquet
        output/exhibits/vehicle_concentration.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ddvc.asset_types import classify  # noqa: E402
from ddvc.tables import write_exhibit, write_panel  # noqa: E402

UNIFIED = ROOT / "data" / "unified"
CENTRALITY = ROOT / "data" / "processed" / "vehicle_centrality.parquet"
OUT_PANEL = ROOT / "data" / "processed" / "vehicle_concentration.parquet"
OUT_EXHIBIT = ROOT / "output" / "exhibits" / "vehicle_concentration.jsonl"


def intermediation_shares(day: str, basis: str = "volume") -> pd.Series:
    """Volume, or trade count, routed through each interior token on one day."""
    p = UNIFIED / f"{day}.parquet"
    if not p.exists():
        return pd.Series(dtype=float)
    d = pd.read_parquet(p, columns=["tx_hash", "component_id", "token_in", "token_out",
                                    "amount_usd", "log_index", "route_class"])
    d = d[d.route_class.isin(["single", "coherent"])]
    d = d[(d.amount_usd > 0) & (d.amount_usd < 1e9)]
    if d.empty:
        return pd.Series(dtype=float)
    d = d.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    acc: dict[str, float] = {}
    for (_t, _c), g in d.groupby(["tx_hash", "component_id"], sort=False):
        if len(g) < 2:
            continue
        tin, tout = g.token_in.tolist(), g.token_out.tolist()
        if tin[0] == tout[-1]:
            continue                    # round trip moved no value
        w = float(g.amount_usd.max()) if basis == "volume" else 1.0
        for interior in {t for t in tout[:-1] if t}:
            acc[interior] = acc.get(interior, 0.0) + w
    return pd.Series(acc, dtype=float)


def concentration(shares: pd.Series) -> dict:
    """HHI, effective number, and the leader, from a vector of positive weights."""
    s = shares[shares > 0]
    if s.empty:
        return {}
    w = s / s.sum()
    hhi = float((w ** 2).sum())
    leader = w.idxmax()
    sym, typ = classify(leader)
    return {"hhi": hhi, "effective_vehicles": 1.0 / hhi if hhi > 0 else np.nan,
            "cr1": float(w.max()), "cr3": float(w.nlargest(3).sum()),
            "leader": leader, "leader_symbol": sym, "leader_type": typ,
            "n_vehicles": int(len(w))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stride", type=int, default=30)
    args = ap.parse_args()

    days = sorted(p.stem for p in UNIFIED.glob("[0-9]" * 8 + ".parquet"))[:: args.stride]
    print(f"measuring vehicle concentration on {len(days)} days "
          f"({days[0]}..{days[-1]})\n")

    rows = []
    for i, day in enumerate(days, 1):
        for b in ("volume", "count"):
            s = intermediation_shares(day, basis=b)
            if s.empty:
                continue
            c = concentration(s)
            if c:
                c.update(day=day, basis=f"share_{b}")
                rows.append(c)
        if i % 10 == 0 or i == len(days):
            print(f"  {i}/{len(days)} {day}", flush=True)

    if CENTRALITY.exists():
        cen = pd.read_parquet(CENTRALITY)
        for day, g in cen.groupby("day"):
            for col, lab in (("betweenness_volume", "centrality_volume"),
                             ("betweenness_count", "centrality_count"),
                             ("betweenness_topological", "centrality_topological")):
                if col not in g.columns:
                    continue
                c = concentration(g.set_index("token")[col])
                if c:
                    c.update(day=str(day), basis=lab)
                    rows.append(c)

    if not rows:
        print("nothing measured")
        return 1
    panel = pd.DataFrame(rows)
    panel["date"] = pd.to_datetime(panel.day, format="%Y%m%d")
    panel["year"] = panel.date.dt.year
    write_panel(panel, OUT_PANEL)

    for basis in ("share_volume", "centrality_volume", "share_count",
                  "centrality_count", "centrality_topological"):
        b = panel[panel.basis == basis]
        if b.empty:
            continue
        print(f"\n{basis.upper()} basis, by year")
        print(f"  {'year':>6}{'HHI':>9}{'effective':>11}{'CR1':>9}{'CR3':>9}"
              f"{'leader':>10}{'leader type':>14}")
        for yr, g in b.groupby("year"):
            lead = g.leader_symbol.mode()
            lead = lead.iloc[0] if len(lead) and pd.notna(lead.iloc[0]) else "?"
            ltype = g.leader_type.mode()
            ltype = ltype.iloc[0] if len(ltype) else "?"
            print(f"  {yr:>6}{g.hhi.mean():>9.3f}{g.effective_vehicles.mean():>11.2f}"
                  f"{g.cr1.mean():>9.1%}{g.cr3.mean():>9.1%}{lead:>10}{ltype:>14}")

    print("\n  READ THE GRID IN MATCHED PAIRS. share_volume against centrality_volume,")
    print("  and share_count against centrality_count. Comparing a volume share to an")
    print("  unweighted centrality confounds the weighting with the measure.")
    v = panel[panel.basis == "share_volume"].sort_values("date")
    if len(v) > 4:
        first, last = v.iloc[:max(3, len(v)//10)], v.iloc[-max(3, len(v)//10):]
        d_hhi = last.hhi.mean() - first.hhi.mean()
        d_cr1 = last.cr1.mean() - first.cr1.mean()
        same_leader = (first.leader_symbol.mode().iloc[0]
                       == last.leader_symbol.mode().iloc[0]) \
            if len(first.leader_symbol.mode()) and len(last.leader_symbol.mode()) else False
        print(f"\n  HHI moved {d_hhi:+.3f}, CR1 moved {d_cr1:+.1%}, "
              f"leader {'UNCHANGED' if same_leader else 'CHANGED'}")
        if d_hhi < -0.02 and same_leader:
            print("  => FRAGMENTATION, not succession. The role is spreading across more")
            print("     assets while the same asset still leads, which is dominance")
            print("     eroding without displacement.")
        elif d_hhi > -0.02 and not same_leader:
            print("  => SUCCESSION. Concentration held and the leader changed hands.")
        else:
            print("  => mixed; report both statistics and do not label the regime.")

    write_exhibit(panel.groupby(["year", "basis"], as_index=False)[
        ["hhi", "effective_vehicles", "cr1", "cr3", "n_vehicles"]].mean(), OUT_EXHIBIT)
    print(f"\nwrote {OUT_PANEL.relative_to(ROOT)} and {OUT_EXHIBIT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

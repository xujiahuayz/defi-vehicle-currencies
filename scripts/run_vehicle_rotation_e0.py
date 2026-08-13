#!/usr/bin/env python3
"""E0 exploration of the vehicle-currency rotation, three lenses, reproducible.

PROVISIONAL (workflow §41): reads released route-only D3 exhibits, is a segregated
plausibility check, and promotes nothing until rerun on the released D generation and
passed through E1 and F. Rerun this script after any data refresh.

SNAPSHOT AND DELTA, why the numbers are kept not discarded. The exhibit this writes is a
provenance-stamped snapshot. Running it now on the provisional route-only inputs records a
dated baseline; when node D releases the healed generation, rerunning writes a new stamped
exhibit and the git diff of the two measures how far the finding moved and where. That delta
is the whole point of running the experiment ahead of the data, so the provisional numbers
are stamped and committed, not thrown away. The exhibit is the diffable record; prose stays
thin because prose does not diff, an exhibit does.

THE OBJECT. The vehicle role is intermediary use net of endpoint demand. The excess-use
ratio is an asset's share of intermediary legs over its share of endpoint legs. Above one
means routed through more than held, the signature of a vehicle. The ratio is a quotient of
a routing share over a holding share, so common volume growth, which is what market
maturation and venue migration produce, cancels. Composition is differenced out before any
control is added.

LENS 1, CROSS-SECTION, NOT TIME. In the latest full year the genuine value-vehicles, meaning
excess-use above one on material intermediary dollars, are USDT and USDC. The native asset
sits below one on large dollar volume, so it is held more than routed. High-ratio staking
derivatives and niche units sit on trivial dollars and are noise. Read this as the standing
field of vehicles, not as a trend.

LENS 2, FRAGMENTATION, A DISTRIBUTION FACT. On direct value intermediation share the leader
of the vehicle role loses most of it and the effective number of vehicles rises several
fold. The native asset's single dominance ends and the successor is a stable-led plurality,
not a new hegemon. Caveat kept load-bearing: a falling aggregate Herfindahl cannot by itself
separate genuine per-pair fragmentation from a mosaic of pair-level monopolies, which is the
flaw that retired the earlier betweenness measure. The direct-share measure removes the
circularity but not the aggregation, so genuine-versus-mosaic is a per-cell question for the
state-dependent layer, not a settled finding here.

LENS 3, EVENT STUDIES AROUND MECHANISM INTRODUCTIONS, the identified use of time. DeFi is
rich in discrete events: concentrated liquidity at Uniswap v3 in May 2021, hooks at v4, the
USDC depeg of March 2023, the Terra collapse of May 2022, router and aggregator releases,
and whatever sits under the sustained value crossing dated to 2025Q1. Monotone chronology is
never the finding. Leads and lags around a dated event, with the untreated set as control,
are. These run on the daily panel and are guarded below until node D releases it.

A HONEST NULL WORTH KEEPING. The rotation is strong descriptively and on the daily calendar
panel with HAC standard errors, but a two-way fixed-effect difference-in-differences of the
fiat-stable treatment interacted with a post-2024 indicator on the annual token panel is
underpowered, 18 tokens over 7 years, and returns an insignificant coefficient. The powered
inference is the daily disaggregated panel, not the annual aggregate. The annual DiD is
reported here so its power limit is on the record and not rediscovered later.

Reads   output/exhibits/vehicle_excess_use.jsonl, vehicle_concentration.jsonl
        (guarded) the released daily vehicle panel, when node D publishes it
Writes  output/exhibits/e0_vehicle_rotation_analysis.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from ddvc.tables import write_exhibit

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "output" / "exhibits"
OUT = EX / "e0_vehicle_rotation_analysis.jsonl"
FIAT_STABLE = {"USDT", "USDC", "USD1", "USDS", "PYUSD", "TUSD", "FDUSD", "USDP", "GUSD"}
MATERIAL_USD = 1e8  # ignore sub-$100M-intermediary tokens as cross-sectional noise


def _rows(name: str) -> list[dict]:
    p = EX / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def lens1_cross_section(out: list[dict]) -> None:
    rows = _rows("vehicle_excess_use.jsonl")
    if not rows:
        return
    df = pd.DataFrame([r for r in rows if r.get("level") == "token"
                       and r.get("vehicle_excess_use_ratio") is not None])
    if df.empty:
        return
    df["sym"] = df.get("symbol", df.get("token"))
    year = int(df.year.max())
    cur = df[(df.year == year) & (df.intermediate_usd > MATERIAL_USD)].copy()
    cur = cur.sort_values("vehicle_excess_use_ratio", ascending=False)
    for r in cur.itertuples():
        out.append({"lens": "cross_section", "year": year, "token": r.sym,
                    "value_excess_use": round(r.vehicle_excess_use_ratio, 3),
                    "count_excess_use": round(getattr(r, "vehicle_excess_use_count_ratio", float("nan")), 3),
                    "intermediary_usd": round(r.intermediate_usd, 0),
                    "is_vehicle": bool(r.vehicle_excess_use_ratio > 1)})


def lens2_fragmentation(out: list[dict]) -> None:
    rows = _rows("vehicle_concentration.jsonl")
    for r in rows:
        if str(r.get("basis")) not in ("share_volume", "share_count"):
            continue
        h = r.get("hhi")
        out.append({"lens": "fragmentation", "basis": r.get("basis"), "year": r.get("year"),
                    "hhi": round(h, 4) if h else None,
                    "effective_vehicles": round(1 / h, 2) if h else None,
                    "cr1": round(r.get("cr1"), 4) if r.get("cr1") is not None else None})


def lens_did_annual(out: list[dict]) -> None:
    rows = _rows("vehicle_excess_use.jsonl")
    df = pd.DataFrame([r for r in rows if r.get("level") == "token"
                       and r.get("vehicle_excess_use_ratio") is not None])
    if df.empty:
        return
    df["sym"] = df.get("symbol", df.get("token"))
    df["fiat_stable"] = df.sym.isin(FIAT_STABLE).astype(float)
    df["post"] = (df.year >= 2025).astype(float)
    keep = df.groupby("sym").intermediate_usd.max()
    d = df[df.sym.isin(keep[keep > MATERIAL_USD].index)].copy()
    try:
        import pyfixest as pf
        for outcome in ("vehicle_excess_use_ratio", "vehicle_excess_use_count_ratio"):
            m = pf.feols(f"{outcome} ~ fiat_stable:post | sym + year", data=d, vcov={"CRV1": "sym"})
            row = m.tidy().loc["fiat_stable:post"]
            out.append({"lens": "did_annual_UNDERPOWERED", "outcome": outcome,
                        "coef": round(float(row["Estimate"]), 4), "se": round(float(row["Std. Error"]), 4),
                        "t": round(float(row["t value"]), 2), "p": round(float(row["Pr(>|t|)"]), 3),
                        "n": int(len(d)), "clusters": int(d.sym.nunique()),
                        "note": "annual panel is underpowered; powered inference is the daily calendar panel"})
    except Exception as exc:
        out.append({"lens": "did_annual_UNDERPOWERED", "error": f"{type(exc).__name__}: {str(exc)[:120]}"})


def lens3_event_studies(out: list[dict]) -> None:
    """Guarded: run leads/lags around dated mechanism events on the released daily panel."""
    try:
        from ddvc.data_release import require_node_d_release
        require_node_d_release(routes=True)
    except Exception as exc:
        out.append({"lens": "event_studies", "status": "deferred",
                    "reason": f"daily panel not released ({str(exc)[:80]})",
                    "planned_events": ["uniswap_v3_2021-05-05", "terra_2022-05", "usdc_depeg_2023-03-11",
                                       "uniswap_v4_launch", "router_aggregator_releases", "eth_vehicle_crossing_2025Q1"],
                    "design": "daily leads/lags of stable excess-use around each event, untreated pairs as control, "
                              "cluster-robust; identify the event under the sustained 2025Q1 value crossing"})
        return
    out.append({"lens": "event_studies", "status": "TODO_on_released_daily_panel"})


def main() -> int:
    out: list[dict] = []
    lens1_cross_section(out)
    lens2_fragmentation(out)
    lens_did_annual(out)
    lens3_event_studies(out)
    if not out:
        print("no released exhibits to read")
        return 1
    write_exhibit(pd.DataFrame(out), OUT)
    vehicles = [r for r in out if r.get("lens") == "cross_section" and r.get("is_vehicle")]
    print(f"cross-section vehicles (latest year): {[r['token'] for r in vehicles]}")
    frag = [r for r in out if r.get("lens") == "fragmentation" and r.get("basis") == "share_volume"]
    if frag:
        f0, f1 = frag[0], frag[-1]
        print(f"value fragmentation: effective vehicles {f0['effective_vehicles']} -> {f1['effective_vehicles']}, "
              f"CR1 {f0['cr1']:.1%} -> {f1['cr1']:.1%}")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

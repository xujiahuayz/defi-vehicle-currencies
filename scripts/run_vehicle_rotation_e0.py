#!/usr/bin/env python3
"""E0 exploration of the vehicle-currency rotation, three lenses, reproducible.

PROVISIONAL (workflow §41): reads released route-only D3 exhibits, is a segregated
plausibility check, and promotes nothing until rerun on the released D generation and
passed through E1 and F. Rerun this script after any data refresh.

SNAPSHOT AND DELTA. The exhibit is a provenance-stamped snapshot, but the runner refuses
stale or unstamped inputs. A pre-release fit may guide design privately; it is not committed
as evidence. Once node D publishes the healed generation, rerunning writes the first
admissible baseline, and later generation changes are reviewed as an exact git diff.

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

LENS 3, EVENT STUDIES AROUND MECHANISM INTRODUCTIONS, the identified use of time. Monotone
chronology is never the finding; a dated event with leads, lags and an untreated comparison
is. Two designs run on the daily token panel. First, a difference-in-differences event study
around each named mechanism or stress event: treated tokens are the fiat-reserve stables,
controls are the other material tokens, outcome is log value excess-use, weekly bins over
eight weeks either side with the week before the event as reference, token and calendar-day
fixed effects, standard errors clustered by token. Fewer than twelve token clusters fail
closed instead of manufacturing cluster-robust inference. Named events with overlapping
windows are reported as not separately identified. The post-window mean and an explicit
joint Wald test of all pre-event coefficients are recorded per admissible event. Second, an
agnostic break-date search: the daily log differential between fiat-reserve stablecoins and
native currency excess-use is fit with a single mean
shift over a grid of candidate days, the argmin-SSR day is the estimated break, a level-set
band reports the days whose SSR is within five percent of the minimum, and the distance
from the estimated break to each named event says which introduction, if any, sits under
the sustained 2025Q1 crossing. Proximity remains descriptive and never identifies the
nearby event. The named events, all inside the 2020-05 to 2026-06 sample:
Uniswap v3 concentrated liquidity 2021-05-05, Terra collapse 2022-05-09, the Merge
2022-09-15, FTX failure 2022-11-08, USDC depeg 2023-03-11, UniswapX intent aggregation
2023-07-17, Dencun blobs 2024-03-13, the EU MiCA stablecoin deadline 2024-12-30, Uniswap v4
2025-01-31. Stress events (Terra, FTX, depeg) are expected to show sharp reversible
responses, mechanism introductions persistent ones; the 2022-versus-2025 contrast in lens
2's transient logic is the same test stated eventwise.

A HONEST NULL WORTH KEEPING. The rotation is strong descriptively and on the daily calendar
panel with HAC standard errors, but a two-way fixed-effect difference-in-differences of the
fiat-stable treatment interacted with a post-2024 indicator on the annual token panel is
underpowered, 18 tokens over 7 years, and returns an insignificant coefficient. The daily
disaggregated panel is the intended improvement, but it must still pass the cluster-count,
pre-trend and event-collision gates above. The annual DiD is reported so its power limit is
on the record and not rediscovered later.

Reads   output/exhibits/vehicle_excess_use.jsonl, vehicle_concentration.jsonl,
        data/processed/vehicle_excess_use_daily.parquet (only when provenance-current)
Writes  output/exhibits/e0_vehicle_rotation_analysis.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import STABLE_BACKING
from ddvc.provenance import current_artifacts
from ddvc.tables import write_exhibit

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "output" / "exhibits"
OUT = EX / "e0_vehicle_rotation_analysis.jsonl"
FIAT_STABLE = frozenset(
    symbol for symbol, regime in STABLE_BACKING.items() if regime == "fiat_reserve"
)
MATERIAL_USD = 1e8  # ignore sub-$100M-intermediary tokens as cross-sectional noise
SCRIPT_VERSION = "vehicle_rotation_e0.v2"
EVENT_WINDOW_DAYS = 56
MIN_EVENT_CLUSTERS = 12
ANNUAL_INPUT = EX / "vehicle_excess_use.jsonl"
CONCENTRATION_INPUT = EX / "vehicle_concentration.jsonl"
DAILY_PANEL = ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"


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


EVENTS = {  # date: (name, kind) — kind separates stress (reversible) from mechanism (persistent)
    "2021-05-05": ("uniswap_v3_concentrated_liquidity", "mechanism"),
    "2022-05-09": ("terra_collapse", "stress"),
    "2022-09-15": ("ethereum_merge", "mechanism"),
    "2022-11-08": ("ftx_failure", "stress"),
    "2023-03-11": ("usdc_depeg", "stress"),
    "2023-07-17": ("uniswapx_intent_aggregation", "mechanism"),
    "2024-03-13": ("dencun_blobs", "mechanism"),
    "2024-12-30": ("mica_stablecoin_deadline", "mechanism"),
    "2025-01-31": ("uniswap_v4", "mechanism"),
}
def _daily_panel() -> tuple[pd.DataFrame | None, str | None]:
    if not DAILY_PANEL.exists():
        return None, "daily panel absent on disk"
    cols = ["date", "symbol", "asset_type", "intermediate_usd", "endpoint_usd",
            "vehicle_excess_use_ratio"]
    try:
        with current_artifacts((DAILY_PANEL,), consumer="vehicle-rotation E0"):
            df = pd.read_parquet(DAILY_PANEL, columns=cols)
            df["date"] = pd.to_datetime(df.date)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"daily panel is not a current released artifact ({exc})"
    return df, None


def _fiat_native_differential(df: pd.DataFrame) -> pd.Series:
    """Daily log excess-use gap for fiat-reserve stablecoins versus native money."""
    classified = df.copy()
    classified["comparison_class"] = np.select(
        [classified.symbol.isin(FIAT_STABLE), classified.asset_type.eq("native")],
        ["fiat_reserve", "native"],
        default=None,
    )
    classified = classified[classified.comparison_class.notna()]
    day = classified.groupby(["date", "comparison_class"])[
        ["intermediate_usd", "endpoint_usd"]
    ].sum().reset_index()
    totals = df.groupby("date")[["intermediate_usd", "endpoint_usd"]].sum()
    day = day.join(totals, on="date", rsuffix="_total")
    day["ratio"] = (day.intermediate_usd / day.intermediate_usd_total) / (
        day.endpoint_usd / day.endpoint_usd_total
    )
    wide = day.pivot(index="date", columns="comparison_class", values="ratio")
    required = {"fiat_reserve", "native"}
    if not required.issubset(wide.columns):
        return pd.Series(dtype=float)
    return (
        np.log(wide["fiat_reserve"]) - np.log(wide["native"])
    ).replace([np.inf, -np.inf], np.nan).dropna()


def _break_search(differential: pd.Series) -> dict | None:
    """One-break descriptive diagnostic; it is not causal event attribution."""
    grid = differential.loc["2024-01-01":"2026-03-31"]
    if len(grid) <= 60:
        return None
    values = differential.to_numpy()
    dates = differential.index
    candidates: list[tuple[pd.Timestamp, float]] = []
    for candidate in grid.index[30:-30]:
        cut = dates.searchsorted(candidate)
        ssr = ((values[:cut] - values[:cut].mean()) ** 2).sum()
        ssr += ((values[cut:] - values[cut:].mean()) ** 2).sum()
        candidates.append((candidate, float(ssr)))
    best_date, best_ssr = min(candidates, key=lambda item: item[1])
    null_ssr = float(((values - values.mean()) ** 2).sum())
    band = [date for date, ssr in candidates if ssr <= best_ssr * 1.05]
    cut = dates.searchsorted(best_date)
    return {
        "lens": "break_search_descriptive",
        "series": "log fiat-reserve stable minus log native class excess-use",
        "break_date": str(best_date.date()),
        "pre_mean": round(float(values[:cut].mean()), 3),
        "post_mean": round(float(values[cut:].mean()), 3),
        "ssr_reduction_pct": round(100 * (1 - best_ssr / null_ssr), 1),
        "band_5pct": f"{band[0].date()}..{band[-1].date()}",
        "nearest_events_days": {
            value[0]: int((best_date - pd.Timestamp(date)).days)
            for date, value in EVENTS.items()
            if abs((best_date - pd.Timestamp(date)).days) <= 120
        },
        "interpretation": "descriptive break only; proximity does not identify an event",
    }


def _overlapping_events(date_str: str) -> list[str]:
    focal = pd.Timestamp(date_str)
    return [
        name
        for other_date, (name, _kind) in EVENTS.items()
        if other_date != date_str
        and abs((focal - pd.Timestamp(other_date)).days) < 2 * EVENT_WINDOW_DAYS
    ]


def _joint_pretrend_p(model, coefficient_names: list[str], pre_terms: list[str]) -> float:
    if not pre_terms:
        raise ValueError("event study has no pre-event coefficients to test")
    restriction = np.zeros((len(pre_terms), len(coefficient_names)))
    for row, term in enumerate(pre_terms):
        restriction[row, coefficient_names.index(term)] = 1.0
    result = model.wald_test(R=restriction, distribution="chi2")
    return float(result["pvalue"])


def lens3_event_studies(out: list[dict], df: pd.DataFrame) -> None:
    """DiD leads/lags per named event, plus an agnostic break-date search."""
    break_record = _break_search(_fiat_native_differential(df))
    if break_record is not None:
        out.append(break_record)

    # ---- DiD event studies, treated = fiat-reserve stables, control = other material tokens ----
    keep = df.groupby("symbol").intermediate_usd.max()
    mat = df[df.symbol.isin(keep[keep > MATERIAL_USD].index)].copy()
    mat = mat[np.isfinite(mat.vehicle_excess_use_ratio) & (mat.vehicle_excess_use_ratio > 0)]
    mat["y"] = np.log(mat.vehicle_excess_use_ratio)
    mat["treated"] = mat.symbol.isin(FIAT_STABLE).astype(int)
    try:
        import pyfixest as pf
    except ImportError:
        out.append({"lens": "event_study", "error": "pyfixest unavailable"})
        return
    for date_str, (name, kind) in EVENTS.items():
        overlaps = _overlapping_events(date_str)
        if overlaps:
            out.append({
                "lens": "event_study",
                "event": name,
                "kind": kind,
                "date": date_str,
                "status": "not_separately_identified",
                "reason": f"symmetric event window overlaps: {', '.join(overlaps)}",
            })
            continue
        t0 = pd.Timestamp(date_str)
        win = mat[
            (mat.date >= t0 - pd.Timedelta(days=EVENT_WINDOW_DAYS))
            & (mat.date < t0 + pd.Timedelta(days=EVENT_WINDOW_DAYS))
        ].copy()
        if win.empty or win.treated.nunique() < 2:
            continue
        clusters = int(win.symbol.nunique())
        if clusters < MIN_EVENT_CLUSTERS:
            out.append({
                "lens": "event_study",
                "event": name,
                "kind": kind,
                "date": date_str,
                "status": "underidentified_few_clusters",
                "clusters": clusters,
                "minimum_clusters": MIN_EVENT_CLUSTERS,
            })
            continue
        win["rel_week"] = ((win.date - t0).dt.days // 7).clip(-8, 7)
        try:
            m = pf.feols("y ~ i(rel_week, treated, ref=-1) | symbol + date", data=win,
                         vcov={"CRV1": "symbol"})
            tidy = m.tidy()
            post = tidy[tidy.index.str.contains(r"rel_week::[0-7]\b", regex=True)]
            pre = tidy[tidy.index.str.contains(r"rel_week::-[2-8]", regex=True)]
            coefficient_names = list(m.coef().index)
            pre_joint_p = _joint_pretrend_p(m, coefficient_names, list(pre.index))
            out.append({"lens": "event_study", "event": name, "kind": kind, "date": date_str,
                        "status": "exploratory_crv1",
                        "post_mean_coef": round(float(post["Estimate"].mean()), 4),
                        "post_weeks_sig_5pct": int((post["Pr(>|t|)"] < 0.05).sum()),
                        "pre_mean_coef": round(float(pre["Estimate"].mean()), 4),
                        "pre_joint_p": round(pre_joint_p, 3),
                        "pretrend_pass_10pct": bool(pre_joint_p >= 0.10),
                        "n": int(len(win)), "tokens": int(win.symbol.nunique()),
                        "treated_tokens": int(win[win.treated == 1].symbol.nunique())})
        except Exception as exc:
            out.append({"lens": "event_study", "event": name, "date": date_str,
                        "error": f"{type(exc).__name__}: {str(exc)[:100]}"})


def main() -> int:
    out: list[dict] = []
    base_inputs = (ANNUAL_INPUT, CONCENTRATION_INPUT)
    try:
        with current_artifacts(base_inputs, consumer="vehicle-rotation E0"):
            lens1_cross_section(out)
            lens2_fragmentation(out)
            lens_did_annual(out)
    except RuntimeError as exc:
        print(f"refusing stale E0 inputs: {exc}", file=sys.stderr)
        return 2
    daily, daily_reason = _daily_panel()
    inputs = list(base_inputs)
    if daily is None:
        out.append({"lens": "event_studies", "status": "deferred", "reason": daily_reason})
    else:
        inputs.append(DAILY_PANEL)
        lens3_event_studies(out, daily)
    if not out:
        print("no released exhibits to read")
        return 1
    write_exhibit(
        pd.DataFrame(out),
        OUT,
        code_sources=["scripts/run_vehicle_rotation_e0.py"],
        inputs=inputs,
        notes=f"{SCRIPT_VERSION}; E0 only; no claim promotion before D3/E1/F",
    )
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

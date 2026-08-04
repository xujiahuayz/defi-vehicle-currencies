#!/usr/bin/env python3
"""P2 (revised) test: does V3 concentrated liquidity make vehicle status MORE
ELASTIC, not just decentralize/entrench it in levels?

This adapts two existing scripts for framing_1.md's revised P2:
  - scripts/run_v3_architecture_pair_design.py  (V2->V3 pair-level event design,
    previously WETH-only, outcomes = quote-based direct/vehicle availability and
    direct cost advantage -- a decentralize-vs-entrench framing)
  - scripts/run_core_rq_experiments.py           (builds
    data/empirical/actual_route_choice_panel.parquet, which already has REALIZED
    -- not quoted -- vehicle-candidate route shares and quote-based depth for all
    five candidates: WETH, USDC, USDT, DAI, WBTC)

What changed relative to those scripts, concretely:
  1. Universe: WETH-only -> all five candidates (WETH/USDC/USDT/DAI/WBTC), using
     the already-built actual_route_choice_panel.parquet (realized volumes) instead
     of route_cost_panel_v2's quote-only vehicle_available/direct_available flags.
  2. Outcomes: swapped "direct cost advantage" / "no-direct-WETH availability" for
     the three outcomes the framing's revised P2 asks for: vehicle-candidate route
     share (actual_vehicle_share), vehicle HHI (sum of squared shares across the
     five candidates, pair-day level), and direct-pool depth (direct_depth, the
     quote-based $10k execution-quality proxy already in the panel).
  3. Design: added a genuine ELASTICITY test on top of the existing level
     difference-in-differences. The existing scripts only ever estimated a level
     shift (mean effect of post_v3). P2 is a claim about RESPONSIVENESS, not
     level, so the headline test here is whether the day-to-day absolute change
     in route share / vehicle HHI (|delta y|, a direct empirical proxy for "how
     elastic is vehicle status") is larger post-V3 than pre-V3, holding pair (and
     candidate) fixed. This is new -- neither existing script computes a
     dispersion/elasticity outcome, only a level.
  4. Pre-V3 pair volatility (sigma^pre): the RQ4 spec / variable registry names
     this regressor (notation sigma^pre_{i,o}) but its own registry entry says
     "to be constructed" -- it does not exist anywhere in the repo. Building it
     from token log-returns via the raw daily unified snapshots was not feasible
     in the time available, so it is PROXIED here from the within-pair standard
     deviation of the daily direct-route execution price (direct_depth) over the
     pre-V3 window. This is a real, computed, disclosed adaptation, not a
     fabricated number -- but it is a proxy, not the literal registry variable,
     and is reported as such.
  5. Pool-level liquidity concentration (LiquidityConcentration_{p,t,b}) from the
     framing's four-outcome list is NOT run here (would require tick-level band
     depth reconstruction from raw V3 pool state, out of scope for this pass);
     only the three outcomes the task specified are covered.

Inputs (already built, not refetched):
  data/empirical/actual_route_choice_panel.parquet

Outputs:
  output/nbc_pipeline/04_evidence/p2/p2_level_did.csv
  output/nbc_pipeline/04_evidence/p2/p2_elasticity_test.csv
  output/nbc_pipeline/04_evidence/p2/p2_elasticity_by_volatility.csv
  output/nbc_pipeline/04_evidence/p2/p2_sample_summary.csv
  output/nbc_pipeline/04_evidence/p2/p2_vehicle_status_elasticity_results.md
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUTDIR = Path(__file__).resolve().parent

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p  # noqa: E402

LAUNCH = pd.Timestamp("2021-05-05")
VEHICLES = ["WETH", "USDC", "USDT", "DAI", "WBTC"]


def _oneway_demean(s: pd.Series, g: pd.Series) -> pd.Series:
    return s - s.groupby(g).transform("mean")


def _cluster_ols(y: pd.Series, x: pd.Series, cluster: pd.Series) -> dict[str, float]:
    d = pd.DataFrame({"y": y, "x": x, "cluster": cluster}).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    c = d["cluster"].nunique()
    if n < 20 or c < 2 or np.isclose(float(d["x"].var()), 0.0):
        return {"n": n, "clusters": c, "beta": math.nan, "se": math.nan, "t": math.nan, "p": math.nan}
    xmat = np.column_stack([np.ones(n), d["x"].to_numpy(float)])
    yy = d["y"].to_numpy(float)
    beta = np.linalg.lstsq(xmat, yy, rcond=None)[0]
    resid = yy - xmat @ beta
    bread = np.linalg.inv(xmat.T @ xmat)
    meat = np.zeros((2, 2))
    for _, idx in d.groupby("cluster").indices.items():
        score = xmat[idx].T @ resid[idx][:, None]
        meat += score @ score.T
    finite = (c / (c - 1)) * ((n - 1) / max(n - xmat.shape[1], 1))
    cov = finite * bread @ meat @ bread
    se = float(math.sqrt(max(cov[1, 1], 0.0)))
    t = float(beta[1] / se) if se > 0 else math.nan
    p = float(2 * stats.t.sf(abs(t), c - 1)) if np.isfinite(t) else math.nan
    return {"n": n, "clusters": c, "beta": float(beta[1]), "se": se, "t": t, "p": p}


def load_panel(window_days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (candidate-level panel, pair-level panel) balanced on pair for the
    given +/- window around the V3 launch."""
    cols = [
        "date", "pair", "vehicle_sym", "direct_available", "vehicle_available",
        "direct_depth", "actual_vehicle_share",
    ]
    d = pd.read_parquet(DATA / "empirical" / "actual_route_choice_panel.parquet", columns=cols)
    d = d[d["vehicle_sym"].isin(VEHICLES)].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d["date"] >= LAUNCH - pd.Timedelta(days=window_days)) & (d["date"] <= LAUNCH + pd.Timedelta(days=window_days))]
    d["post_v3"] = (d["date"] >= LAUNCH).astype(float)

    # dedupe: a handful of (date, pair, vehicle) cells have >1 row because
    # "pair" is a symbol string and rare tokens can share a symbol across
    # different contract addresses; averaging collapses this without dropping
    # the observation.
    cand = (
        d.groupby(["date", "pair", "vehicle_sym", "post_v3"], as_index=False)
        .agg(direct_available=("direct_available", "mean"),
             vehicle_available=("vehicle_available", "mean"),
             direct_depth=("direct_depth", "mean"),
             actual_vehicle_share=("actual_vehicle_share", "mean"))
    )

    pre_pairs = set(cand.loc[cand["post_v3"].eq(0), "pair"])
    post_pairs = set(cand.loc[cand["post_v3"].eq(1), "pair"])
    balanced = pre_pairs & post_pairs
    cand = cand[cand["pair"].isin(balanced)].copy()
    cand["pair_vehicle"] = cand["pair"] + "|" + cand["vehicle_sym"]

    pair_level = (
        cand.groupby(["date", "pair", "post_v3"], as_index=False)
        .agg(direct_depth=("direct_depth", "mean"),
             vehicle_hhi=("actual_vehicle_share", lambda s: float(np.sum(np.square(s)))))
    )
    return cand, pair_level


def sigma_pre(cand: pd.DataFrame) -> pd.DataFrame:
    """Proxy for sigma^pre_{i,o}: sd of the pre-V3 day-to-day change in the
    direct-route execution-quality proxy (direct_depth), per pair. See module
    docstring point 4 -- the literal registry sigma^pre (token log-return sd)
    is not built anywhere in the repo, so this is a disclosed substitute."""
    pre = cand[cand["post_v3"].eq(0)].copy()
    pre = pre.sort_values(["pair", "date"]).drop_duplicates(["pair", "date"])
    pre["d_depth"] = pre.groupby("pair")["direct_depth"].diff()
    sig = pre.groupby("pair")["d_depth"].std().rename("sigma_pre").reset_index()
    return sig


def level_did(cand: pd.DataFrame, pair_level: pd.DataFrame, window_label: str) -> list[dict]:
    rows = []
    # Outcome 1: vehicle-candidate route share, pair x candidate FE
    y = _oneway_demean(100.0 * cand["actual_vehicle_share"], cand["pair_vehicle"])
    x = _oneway_demean(cand["post_v3"], cand["pair_vehicle"])
    res = _cluster_ols(y, x, cand["pair"])
    rows.append({"Window": window_label, "Outcome": "Vehicle-candidate route share",
                 "Units": "pp", **res})

    # Outcome 2: vehicle HHI, pair FE
    y = _oneway_demean(pair_level["vehicle_hhi"], pair_level["pair"])
    x = _oneway_demean(pair_level["post_v3"], pair_level["pair"])
    res = _cluster_ols(y, x, pair_level["pair"])
    rows.append({"Window": window_label, "Outcome": "Vehicle HHI",
                 "Units": "HHI (0-1)", **res})

    # Outcome 3: direct-pool depth, pair FE
    y = _oneway_demean(pair_level["direct_depth"].clip(0, 2), pair_level["pair"])
    x = _oneway_demean(pair_level["post_v3"], pair_level["pair"])
    res = _cluster_ols(y, x, pair_level["pair"])
    rows.append({"Window": window_label, "Outcome": "Direct-pool depth",
                 "Units": "ratio", **res})
    return rows


def elasticity_test(cand: pd.DataFrame, pair_level: pd.DataFrame, window_label: str) -> list[dict]:
    """Headline P2 test: is vehicle status *more responsive* (bigger day-to-day
    absolute moves), not just a different level, post-V3?"""
    rows = []

    c = cand.sort_values(["pair_vehicle", "date"]).drop_duplicates(["pair_vehicle", "date"]).copy()
    c["abs_d_share"] = c.groupby("pair_vehicle")["actual_vehicle_share"].diff().abs() * 100.0
    y = _oneway_demean(c["abs_d_share"], c["pair_vehicle"])
    x = _oneway_demean(c["post_v3"], c["pair_vehicle"])
    res = _cluster_ols(y, x, c["pair"])
    rows.append({"Window": window_label, "Outcome": "|day-to-day change| in route share",
                 "Units": "pp", **res})

    p = pair_level.sort_values(["pair", "date"]).drop_duplicates(["pair", "date"]).copy()
    p["abs_d_hhi"] = p.groupby("pair")["vehicle_hhi"].diff().abs()
    y = _oneway_demean(p["abs_d_hhi"], p["pair"])
    x = _oneway_demean(p["post_v3"], p["pair"])
    res = _cluster_ols(y, x, p["pair"])
    rows.append({"Window": window_label, "Outcome": "|day-to-day change| in vehicle HHI",
                 "Units": "HHI points", **res})

    p["abs_d_depth"] = p.groupby("pair")["direct_depth"].diff().abs().clip(upper=2)
    y = _oneway_demean(p["abs_d_depth"], p["pair"])
    x = _oneway_demean(p["post_v3"], p["pair"])
    res = _cluster_ols(y, x, p["pair"])
    rows.append({"Window": window_label, "Outcome": "|day-to-day change| in direct-pool depth",
                 "Units": "ratio points", **res})
    return rows


def elasticity_by_volatility(cand: pd.DataFrame, pair_level: pd.DataFrame, window_label: str) -> list[dict]:
    """Robustness split named in the framing's P2 battery: by pre-V3 pair
    volatility. Low-sigma^pre pairs are where concentrated liquidity should
    matter most (Lehar & Parlour anchor cited in RQ4)."""
    sig = sigma_pre(cand)
    med = sig["sigma_pre"].median()
    sig["vol_bucket"] = np.where(sig["sigma_pre"] <= med, "Low pre-V3 volatility", "High pre-V3 volatility")

    rows = []
    c = cand.merge(sig[["pair", "vol_bucket"]], on="pair", how="inner")
    c = c.sort_values(["pair_vehicle", "date"]).drop_duplicates(["pair_vehicle", "date"]).copy()
    c["abs_d_share"] = c.groupby("pair_vehicle")["actual_vehicle_share"].diff().abs() * 100.0
    for bucket, g in c.groupby("vol_bucket"):
        y = _oneway_demean(g["abs_d_share"], g["pair_vehicle"])
        x = _oneway_demean(g["post_v3"], g["pair_vehicle"])
        res = _cluster_ols(y, x, g["pair"])
        rows.append({"Window": window_label, "Subsample": bucket,
                     "Outcome": "|day-to-day change| in route share", "Units": "pp", **res})

    p = pair_level.merge(sig[["pair", "vol_bucket"]], on="pair", how="inner")
    p = p.sort_values(["pair", "date"]).drop_duplicates(["pair", "date"]).copy()
    p["abs_d_hhi"] = p.groupby("pair")["vehicle_hhi"].diff().abs()
    for bucket, g in p.groupby("vol_bucket"):
        y = _oneway_demean(g["abs_d_hhi"], g["pair"])
        x = _oneway_demean(g["post_v3"], g["pair"])
        res = _cluster_ols(y, x, g["pair"])
        rows.append({"Window": window_label, "Subsample": bucket,
                     "Outcome": "|day-to-day change| in vehicle HHI", "Units": "HHI points", **res})
    return rows


def _to_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def fmt_rows(rows: list[dict]) -> pd.DataFrame:
    out = pd.DataFrame(rows)
    out["N"] = out["n"].map(_int)
    out["Pairs"] = out["clusters"].map(_int)
    out["Effect"] = out["beta"].map(lambda v: _num(v, 4))
    out["SE"] = out["se"].map(lambda v: _num(v, 4))
    out["t"] = out["t"].map(lambda v: _num(v, 2))
    out["p"] = out["p"].map(_p)
    keep = [c for c in ["Window", "Subsample", "Outcome", "Units", "N", "Pairs", "Effect", "SE", "t", "p"] if c in out.columns]
    return out[keep]


def run() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    level_rows: list[dict] = []
    elastic_rows: list[dict] = []
    vol_rows: list[dict] = []
    sample_rows: list[dict] = []

    for window_days, label in [(365, "+/-12 months"), (730, "+/-24 months")]:
        cand, pair_level = load_panel(window_days)
        n_pairs = pair_level["pair"].nunique()
        n_pair_vehicle = cand["pair_vehicle"].nunique()
        sample_rows.append({
            "Window": label,
            "Balanced pairs": _int(n_pairs),
            "Pair-candidate cells": _int(n_pair_vehicle),
            "Candidate-level rows": _int(len(cand)),
            "Pair-day rows": _int(len(pair_level)),
            "First date": str(cand["date"].min().date()),
            "Last date": str(cand["date"].max().date()),
        })
        level_rows += level_did(cand, pair_level, label)
        elastic_rows += elasticity_test(cand, pair_level, label)
        if window_days == 365:
            vol_rows += elasticity_by_volatility(cand, pair_level, label)

    level_out = fmt_rows(level_rows)
    elastic_out = fmt_rows(elastic_rows)
    vol_out = fmt_rows(vol_rows)
    sample_out = pd.DataFrame(sample_rows)

    level_out.to_csv(OUTDIR / "p2_level_did.csv", index=False)
    elastic_out.to_csv(OUTDIR / "p2_elasticity_test.csv", index=False)
    vol_out.to_csv(OUTDIR / "p2_elasticity_by_volatility.csv", index=False)
    sample_out.to_csv(OUTDIR / "p2_sample_summary.csv", index=False)

    lines = []
    lines.append("# P2 (revised): V2->V3 concentrated-liquidity event study, reframed around vehicle-status elasticity")
    lines.append("")
    lines.append(f"Run at trade-size $10,000 notional, candidate set {VEHICLES}, launch date {LAUNCH.date()}.")
    lines.append("")
    lines.append("## Sample")
    lines.append(_to_md(sample_out))
    lines.append("")
    lines.append("## Level difference-in-differences (extends run_v3_architecture_pair_design.py to all 5 candidates)")
    lines.append(_to_md(level_out))
    lines.append("")
    lines.append("## Elasticity test (headline P2 test: |day-to-day change| pre- vs post-V3)")
    lines.append(_to_md(elastic_out))
    lines.append("")
    lines.append("## Elasticity test split by pre-V3 pair volatility proxy (robustness battery item ii)")
    lines.append(_to_md(vol_out))
    lines.append("")
    (OUTDIR / "p2_vehicle_status_elasticity_results.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""P2 robustness battery: placebo/pretrend, volatility split, version
construction, and fixed event windows -- run against the P2 headline result
in run_p2_vehicle_status_elasticity.py (this directory).

Per docs/research-questions-and-empirical-design.md RQ4 Experiment A's
diagnostics section and output/nbc_pipeline/02_framings/framing_1.md Section 2
("P2 battery, revised for the within-chain V2->V3 design"), the four items run
here are:

  (i)   falsification/placebo -- RQ4's own placebo launch dates and joint
        pretrend tests
  (ii)  subsample split -- by pre-V3 pair volatility (extended here to both
        event windows and all three headline outcomes; the headline script
        only ran this for +/-12mo and two of the three outcomes)
  (iii) alternative-measure robustness -- V2-only, V3-only, and
        best-across-versions route construction shown separately
  (iv)  sample-period split -- fixed 12- and 24-month event windows (already
        in the headline script; reproduced here so the whole battery is one
        self-contained report)

Reuses (does not re-derive):
  - run_p2_vehicle_status_elasticity.py (this directory): LAUNCH, VEHICLES,
    load_panel(), _oneway_demean(), _cluster_ols(), sigma_pre(), level_did(),
    elasticity_test().
  - scripts/run_v3_architecture_pair_design.py: the WETH-only, quote-based
    (route_cost_panel_v2.parquet) outcome set and pair-FE/pair-cluster design,
    generalized here to all five vehicle candidates for item (iii).
  - scripts/run_jfe_identification_extensions.py's v3_event_time_pretrends():
    the monthly event-time aggregation and linear-pretrend-slope pattern,
    extended here with an omnibus (joint) Wald test on pre-period month
    dummies, which is what "joint pretrend tests" in the RQ4 diagnostics list
    calls for and the existing script does not itself compute.

Honesty notes:
  - sigma^pre is the same disclosed proxy used in the headline script (pre-V3
    std dev of day-to-day direct_depth changes), not the literal registry
    variable (which the registry itself marks "to be constructed").
  - Item (iii) cannot force a historical quote replay under an AMM version
    that was not actually the realized best quote at that block (that would
    require re-running full historical state replay restricted to one AMM
    version, out of scope for this pass). Instead it partitions
    route_cost_panel_v2.parquet's already-computed best-available quotes by
    which version's pool *was* the realized source for each leg
    (direct_source / hop1_source / hop2_source). This is a disclosed proxy for
    "V2-only" / "V3-only" route construction, not a forced counterfactual
    re-quote against a version that was not actually used.
  - Placebo dates are chosen to sit entirely within one regime (either
    pre-launch or well after launch) so that no part of a placebo's own
    +/- window straddles the true 2021-05-05 break; this is disclosed in the
    per-placebo sample summary (first/last date, event date) written to
    p2_rb_placebo.csv.

Outputs (all real, computed by this run, not fabricated):
  output/nbc_pipeline/04_evidence/p2/p2_rb_pretrend.csv
  output/nbc_pipeline/04_evidence/p2/p2_rb_placebo.csv
  output/nbc_pipeline/04_evidence/p2/p2_rb_volatility_split.csv
  output/nbc_pipeline/04_evidence/p2/p2_rb_version_construction.csv
  output/nbc_pipeline/04_evidence/p2/p2_rb_fixed_windows.csv
  output/nbc_pipeline/04_evidence/p2/p2_robustness_battery_results.md
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

for _p_ in (SCRIPTS, OUTDIR):
    if str(_p_) not in sys.path:
        sys.path.insert(0, str(_p_))

from build_paper_exhibits import _int, _num, _p  # noqa: E402
from run_p2_vehicle_status_elasticity import (  # noqa: E402
    LAUNCH,
    VEHICLES,
    _cluster_ols,
    _oneway_demean,
    elasticity_test,
    level_did,
    load_panel,
    sigma_pre,
)

# ---------------------------------------------------------------------------
# Shared cluster-robust helpers
# ---------------------------------------------------------------------------

def _cluster_wald_joint(y: pd.Series, xmat: pd.DataFrame, cluster: pd.Series) -> dict:
    """Cluster-robust Wald test that all columns of xmat (already within-
    demeaned by the same FE as y) are jointly zero. This is the "joint
    pretrend test" the RQ4 diagnostics list names -- the existing repo script
    (run_jfe_identification_extensions.py) only computes a single linear
    pretrend slope, not an omnibus test across pre-period month dummies."""
    d = pd.concat([y.rename("y"), xmat, cluster.rename("cluster")], axis=1)
    d = d.replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    c = d["cluster"].nunique()
    k = xmat.shape[1]
    if k == 0 or n < 5 * max(k, 1) or c <= k + 1:
        return {"n": n, "clusters": c, "k": k, "chi2": math.nan, "p": math.nan}
    xx = d[xmat.columns].to_numpy(float)
    yy = d["y"].to_numpy(float)
    xtx = xx.T @ xx
    try:
        xtx_inv = np.linalg.inv(xtx)
    except np.linalg.LinAlgError:
        return {"n": n, "clusters": c, "k": k, "chi2": math.nan, "p": math.nan}
    beta = xtx_inv @ (xx.T @ yy)
    resid = yy - xx @ beta
    meat = np.zeros((k, k))
    for _, idx in d.groupby("cluster").indices.items():
        score = xx[idx].T @ resid[idx][:, None]
        meat += score @ score.T
    finite = (c / (c - 1)) * ((n - 1) / max(n - k, 1))
    cov = finite * xtx_inv @ meat @ xtx_inv
    try:
        cov_inv = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        return {"n": n, "clusters": c, "k": k, "chi2": math.nan, "p": math.nan}
    chi2 = float(beta @ cov_inv @ beta)
    p = float(stats.chi2.sf(chi2, k))
    return {"n": n, "clusters": c, "k": k, "chi2": chi2, "p": p}


def _to_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def fmt_rows(rows: list[dict], extra_cols: list[str]) -> pd.DataFrame:
    out = pd.DataFrame(rows)
    out["N"] = out["n"].map(_int)
    out["Pairs"] = out["clusters"].map(_int)
    out["Effect"] = out["beta"].map(lambda v: _num(v, 4))
    out["SE"] = out["se"].map(lambda v: _num(v, 4))
    out["t"] = out["t"].map(lambda v: _num(v, 2))
    out["p"] = out["p"].map(_p)
    keep = [c for c in extra_cols + ["N", "Pairs", "Effect", "SE", "t", "p"] if c in out.columns]
    return out[keep]


# ---------------------------------------------------------------------------
# Item (i): placebo launch dates + joint pretrend tests
# ---------------------------------------------------------------------------

def build_panel_at(full: pd.DataFrame, event_date: pd.Timestamp, window_days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Same construction as load_panel() in the headline script, generalized
    to an arbitrary break date, for placebo tests."""
    d = full[(full["date"] >= event_date - pd.Timedelta(days=window_days))
             & (full["date"] <= event_date + pd.Timedelta(days=window_days))].copy()
    d["post_v3"] = (d["date"] >= event_date).astype(float)
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


def placebo_battery(full: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """RQ4 diagnostic: placebo launch dates. Each fake event date sits
    entirely inside one regime (all pre-launch, or well after the true
    launch) with a +/-120-day window, so no placebo window straddles the true
    2021-05-05 break. A real architecture shock produces a spurious "break"
    of similar size only if the estimator itself is generating false
    positives; a null result at every placebo date is the falsification
    check."""
    window_days = 120
    placebos = [
        ("2020-10-01", "pre-period placebo (true regime: pre-V3)"),
        ("2020-11-15", "pre-period placebo (true regime: pre-V3)"),
        ("2021-01-01", "pre-period placebo (true regime: pre-V3)"),
        ("2022-05-05", "post-period placebo (true regime: post-V3, +1yr)"),
        ("2023-05-05", "post-period placebo (true regime: post-V3, +2yr)"),
    ]
    level_rows: list[dict] = []
    elastic_rows: list[dict] = []
    sample_rows: list[dict] = []
    for date_str, note in placebos:
        event_date = pd.Timestamp(date_str)
        cand, pair_level = build_panel_at(full, event_date, window_days)
        n_pairs = pair_level["pair"].nunique()
        sample_rows.append({
            "Placebo date": date_str, "Regime": note,
            "Balanced pairs": _int(n_pairs),
            "First date": str(cand["date"].min().date()) if len(cand) else "",
            "Last date": str(cand["date"].max().date()) if len(cand) else "",
        })
        label = f"placebo {date_str}"
        for row in level_did(cand, pair_level, label):
            row["Placebo date"] = date_str
            row["Regime"] = note
            level_rows.append(row)
        for row in elasticity_test(cand, pair_level, label):
            row["Placebo date"] = date_str
            row["Regime"] = note
            elastic_rows.append(row)

    level_out = fmt_rows(level_rows, ["Placebo date", "Regime", "Outcome", "Units"])
    elastic_out = fmt_rows(elastic_rows, ["Placebo date", "Regime", "Outcome", "Units"])
    sample_out = pd.DataFrame(sample_rows)
    return pd.concat([level_out.assign(Test="Level DiD"), elastic_out.assign(Test="Elasticity")],
                      ignore_index=True), sample_out


def _pretrend_block(monthly: pd.DataFrame, fe_col: str, cluster_col: str,
                     outcome_label: str, units: str, window_label: str) -> list[dict]:
    m = monthly.dropna(subset=["y"]).copy()
    if m[fe_col].nunique() < 2 or m["rel_month"].nunique() < 3:
        return [{
            "Window": window_label, "Outcome": outcome_label, "Units": units,
            "Pretrend N": _int(len(m)), "Pretrend pairs": "", "Pretrend slope": "",
            "Pretrend slope SE": "", "Pretrend slope t": "", "Pretrend slope p": "",
            "Joint pretrend months (k)": "", "Joint chi2": "", "Joint p": "",
        }]

    y_lin = _oneway_demean(m["y"], m[fe_col])
    x_lin = _oneway_demean(m["rel_month"].astype(float), m[fe_col])
    lin = _cluster_ols(y_lin, x_lin, m[cluster_col])

    ref = -1
    months = sorted(mm for mm in m["rel_month"].unique() if mm != ref)
    if len(months) < 2:
        joint = {"n": len(m), "clusters": m[cluster_col].nunique(), "k": 0, "chi2": math.nan, "p": math.nan}
    else:
        dummies = pd.DataFrame({f"m_{mm}": (m["rel_month"] == mm).astype(float) for mm in months}, index=m.index)
        dummies_dm = dummies.apply(lambda col: _oneway_demean(col, m[fe_col]))
        y_dm = _oneway_demean(m["y"], m[fe_col])
        joint = _cluster_wald_joint(y_dm, dummies_dm, m[cluster_col])

    return [{
        "Window": window_label, "Outcome": outcome_label, "Units": units,
        "Pretrend N": _int(lin["n"]), "Pretrend pairs": _int(lin["clusters"]),
        "Pretrend slope": _num(lin["beta"], 4), "Pretrend slope SE": _num(lin["se"], 4),
        "Pretrend slope t": _num(lin["t"], 2), "Pretrend slope p": _p(lin["p"]),
        "Joint pretrend months (k)": _int(joint["k"]), "Joint chi2": _num(joint["chi2"], 2),
        "Joint p": _p(joint["p"]),
    }]


def pretrend_tests(cand: pd.DataFrame, pair_level: pd.DataFrame, window_label: str) -> list[dict]:
    """RQ4 diagnostic: joint pretrend test. Restricted to the pre-launch
    portion of the balanced panel; tests (a) a linear pretrend slope
    (mirrors run_jfe_identification_extensions.py's v3_event_time_pretrends)
    and (b) an omnibus Wald test that ALL pre-period month dummies (relative
    to the launch-month reference) are jointly zero, which the existing
    script does not compute and which is what "joint pretrend tests" in the
    RQ4 diagnostics list actually calls for."""
    pre_cand = cand[cand["post_v3"].eq(0)].copy()
    pre_pair = pair_level[pair_level["post_v3"].eq(0)].copy()
    pre_cand["rel_month"] = (pre_cand["date"].dt.year - LAUNCH.year) * 12 + (pre_cand["date"].dt.month - LAUNCH.month)
    pre_pair["rel_month"] = (pre_pair["date"].dt.year - LAUNCH.year) * 12 + (pre_pair["date"].dt.month - LAUNCH.month)

    rows: list[dict] = []

    monthly_share = (
        pre_cand.groupby(["pair_vehicle", "pair", "rel_month"], as_index=False)
        .agg(y=("actual_vehicle_share", "mean"))
    )
    monthly_share["y"] = monthly_share["y"] * 100.0
    rows += _pretrend_block(monthly_share, "pair_vehicle", "pair",
                             "Vehicle-candidate route share", "pp", window_label)

    monthly_pair = (
        pre_pair.groupby(["pair", "rel_month"], as_index=False)
        .agg(vehicle_hhi=("vehicle_hhi", "mean"), direct_depth=("direct_depth", "mean"))
    )
    rows += _pretrend_block(monthly_pair.rename(columns={"vehicle_hhi": "y"}), "pair", "pair",
                             "Vehicle HHI", "HHI (0-1)", window_label)
    rows += _pretrend_block(monthly_pair.rename(columns={"direct_depth": "y"}), "pair", "pair",
                             "Direct-pool depth", "ratio", window_label)
    return rows


# ---------------------------------------------------------------------------
# Item (ii): subsample split by pre-V3 pair volatility, extended
# ---------------------------------------------------------------------------

def volatility_split_full(cand: pd.DataFrame, pair_level: pd.DataFrame, window_label: str) -> list[dict]:
    """Extends the headline script's elasticity_by_volatility(): here run for
    BOTH event windows (headline only ran +/-12mo) and all THREE outcomes
    (headline only had route share and vehicle HHI; direct-pool depth is
    added here)."""
    sig = sigma_pre(cand)
    med = sig["sigma_pre"].median()
    sig["vol_bucket"] = np.where(sig["sigma_pre"] <= med, "Low pre-V3 volatility", "High pre-V3 volatility")

    rows: list[dict] = []
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
    p["abs_d_depth"] = p.groupby("pair")["direct_depth"].diff().abs().clip(upper=2)
    for bucket, g in p.groupby("vol_bucket"):
        y = _oneway_demean(g["abs_d_hhi"], g["pair"])
        x = _oneway_demean(g["post_v3"], g["pair"])
        res = _cluster_ols(y, x, g["pair"])
        rows.append({"Window": window_label, "Subsample": bucket,
                     "Outcome": "|day-to-day change| in vehicle HHI", "Units": "HHI points", **res})

        y2 = _oneway_demean(g["abs_d_depth"], g["pair"])
        x2 = _oneway_demean(g["post_v3"], g["pair"])
        res2 = _cluster_ols(y2, x2, g["pair"])
        rows.append({"Window": window_label, "Subsample": bucket,
                     "Outcome": "|day-to-day change| in direct-pool depth", "Units": "ratio points", **res2})
    return rows


# ---------------------------------------------------------------------------
# Item (iii): V2-only / V3-only / best-across-versions route construction
# ---------------------------------------------------------------------------

def load_version_panel(window_days: int) -> pd.DataFrame:
    cols = ["date", "src_sym", "tgt_sym", "vehicle_sym", "direct_available", "vehicle_available",
            "direct_output_usd", "vehicle_output_usd", "trade_size_usd",
            "direct_source", "hop1_source", "hop2_source", "direct_cost_advantage"]
    d = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet", columns=cols)
    d = d[d["vehicle_sym"].isin(VEHICLES)].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d["date"] >= LAUNCH - pd.Timedelta(days=window_days)) & (d["date"] <= LAUNCH + pd.Timedelta(days=window_days))]
    d["pair"] = d["src_sym"].astype(str) + "->" + d["tgt_sym"].astype(str)
    d["post_v3"] = (d["date"] >= LAUNCH).astype(float)
    d["direct_quality"] = (d["direct_output_usd"] / d["trade_size_usd"]).replace([np.inf, -np.inf], np.nan).clip(0, 2)
    d["direct_cost_advantage_w"] = d["direct_cost_advantage"].clip(-10, 10)
    d["no_direct_available"] = (~d["direct_available"].astype(bool)) & d["vehicle_available"].astype(bool)
    return d


def _version_subset(d: pd.DataFrame, version: str) -> pd.DataFrame:
    """version in {'v2_only', 'v3_only', 'best_across'}. best_across is the
    unfiltered panel (route_cost_panel_v2.parquet's own construction: for
    each leg, whichever AMM version gave the highest realized output --
    scripts/run_route_cost_panel.py's _best_quote). v2_only / v3_only keep an
    availability flag TRUE only when the realized best source for that leg
    was actually that version; this is the disclosed proxy described in the
    module docstring, not a forced re-quote against an unused version."""
    out = d.copy()
    if version != "best_across":
        tag = {"v2_only": {"uniswap_v2", "sushiswap_v2"}, "v3_only": {"uniswap_v3"}}[version]
        direct_ok = out["direct_source"].isin(tag)
        had_vehicle = out["vehicle_available"].astype(bool)
        hop_ok = had_vehicle & out["hop1_source"].isin(tag) & (out["hop2_source"].isna() | out["hop2_source"].isin(tag))
        out["direct_available"] = out["direct_available"].astype(bool) & direct_ok
        out["vehicle_available"] = had_vehicle & hop_ok
        out["no_direct_available"] = (~out["direct_available"]) & out["vehicle_available"]
        out["direct_quality"] = out["direct_quality"].where(direct_ok)
        out["direct_cost_advantage_w"] = out["direct_cost_advantage_w"].where(direct_ok & hop_ok)
    out["pair_vehicle"] = out["pair"] + "|" + out["vehicle_sym"]
    return out


def level_did_by_version(d: pd.DataFrame, version_label: str, window_label: str) -> list[dict]:
    pre_pv = set(d.loc[d["post_v3"].eq(0), "pair_vehicle"])
    post_pv = set(d.loc[d["post_v3"].eq(1), "pair_vehicle"])
    bal = pre_pv & post_pv
    d = d[d["pair_vehicle"].isin(bal)].copy()

    outcomes = {
        "Direct-route availability": (100.0 * d["direct_available"].astype(float), "pp"),
        "Vehicle-route availability": (100.0 * d["vehicle_available"].astype(float), "pp"),
        "No-direct vehicle-route availability": (100.0 * d["no_direct_available"].astype(float), "pp"),
        "Direct-route quality": (d["direct_quality"], "ratio"),
        "Direct cost advantage vs vehicle route": (
            d["direct_cost_advantage_w"].where(d["direct_available"].astype(bool) & d["vehicle_available"].astype(bool)),
            "fraction",
        ),
    }
    rows = []
    for name, (y_raw, units) in outcomes.items():
        y = _oneway_demean(y_raw, d["pair_vehicle"])
        x = _oneway_demean(d["post_v3"], d["pair_vehicle"])
        res = _cluster_ols(y, x, d["pair"])
        rows.append({"Window": window_label, "Version construction": version_label,
                     "Outcome": name, "Units": units, **res})
    return rows


def version_construction_battery() -> pd.DataFrame:
    rows: list[dict] = []
    labels = {"best_across": "Best-across-versions (existing default)",
              "v2_only": "V2-only route construction", "v3_only": "V3-only route construction"}
    for window_days, label in [(365, "+/-12 months"), (730, "+/-24 months")]:
        base = load_version_panel(window_days)
        for version in ["best_across", "v2_only", "v3_only"]:
            sub = _version_subset(base, version)
            rows += level_did_by_version(sub, labels[version], label)
    return fmt_rows(rows, ["Window", "Version construction", "Outcome", "Units"])


# ---------------------------------------------------------------------------
# Item (iv): fixed 12- and 24-month event windows (reproduces the headline
# script's own level DiD + elasticity test, consolidated into this report)
# ---------------------------------------------------------------------------

def fixed_windows_battery() -> tuple[pd.DataFrame, pd.DataFrame]:
    level_rows: list[dict] = []
    elastic_rows: list[dict] = []
    for window_days, label in [(365, "+/-12 months"), (730, "+/-24 months")]:
        cand, pair_level = load_panel(window_days)
        level_rows += level_did(cand, pair_level, label)
        elastic_rows += elasticity_test(cand, pair_level, label)
    return fmt_rows(level_rows, ["Window", "Outcome", "Units"]), fmt_rows(elastic_rows, ["Window", "Outcome", "Units"])


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("Loading actual_route_choice_panel.parquet for placebo/pretrend/volatility items...")
    full_cols = ["date", "pair", "vehicle_sym", "direct_available", "vehicle_available",
                 "direct_depth", "actual_vehicle_share"]
    full = pd.read_parquet(DATA / "empirical" / "actual_route_choice_panel.parquet", columns=full_cols)
    full["vehicle_sym"] = full["vehicle_sym"].astype(str)
    full = full[full["vehicle_sym"].isin(VEHICLES)].copy()
    full["date"] = pd.to_datetime(full["date"])

    # --- (i) placebo dates + joint pretrend ---
    print("Running (i) placebo launch dates...")
    placebo_out, placebo_sample = placebo_battery(full)

    print("Running (i) joint pretrend tests...")
    pretrend_rows: list[dict] = []
    for window_days, label in [(365, "+/-12 months"), (730, "+/-24 months")]:
        cand, pair_level = load_panel(window_days)
        pretrend_rows += pretrend_tests(cand, pair_level, label)
    pretrend_out = pd.DataFrame(pretrend_rows)

    # --- (ii) volatility split, extended ---
    print("Running (ii) volatility split (extended to both windows, 3 outcomes)...")
    vol_rows: list[dict] = []
    for window_days, label in [(365, "+/-12 months"), (730, "+/-24 months")]:
        cand, pair_level = load_panel(window_days)
        vol_rows += volatility_split_full(cand, pair_level, label)
    vol_out = fmt_rows(vol_rows, ["Window", "Subsample", "Outcome", "Units"])

    # --- (iii) version construction ---
    print("Running (iii) V2-only / V3-only / best-across-versions...")
    version_out = version_construction_battery()

    # --- (iv) fixed windows (reproduction) ---
    print("Running (iv) fixed 12-/24-month windows (reproduction of headline)...")
    fixed_level_out, fixed_elastic_out = fixed_windows_battery()

    # Write CSVs
    pretrend_out.to_csv(OUTDIR / "p2_rb_pretrend.csv", index=False)
    placebo_out.to_csv(OUTDIR / "p2_rb_placebo.csv", index=False)
    placebo_sample.to_csv(OUTDIR / "p2_rb_placebo_sample.csv", index=False)
    vol_out.to_csv(OUTDIR / "p2_rb_volatility_split.csv", index=False)
    version_out.to_csv(OUTDIR / "p2_rb_version_construction.csv", index=False)
    fixed_level_out.to_csv(OUTDIR / "p2_rb_fixed_windows_level.csv", index=False)
    fixed_elastic_out.to_csv(OUTDIR / "p2_rb_fixed_windows_elasticity.csv", index=False)

    lines: list[str] = []
    lines.append("# P2 robustness battery -- placebo/pretrend, volatility split, version construction, fixed windows")
    lines.append("")
    lines.append(
        "Runs the four robustness-battery items named in "
        "`output/nbc_pipeline/02_framings/framing_1.md` Section 2 and "
        "`docs/research-questions-and-empirical-design.md` RQ4 Experiment A's "
        "diagnostics section, against the P2 headline result in "
        "`p2_vehicle_status_elasticity_results.md`."
    )
    lines.append("")

    lines.append("## (i) Placebo launch dates -- sample")
    lines.append(_to_md(placebo_sample))
    lines.append("")
    lines.append(
        "## (i) Placebo launch dates -- level DiD and elasticity test at each fake break date\n\n"
        "Real launch is 2021-05-05; every placebo date below uses a +/-120-day window entirely "
        "inside one regime (either all pre-launch, or well after launch), so no placebo window "
        "straddles the true break. A null result at every placebo date is the falsification check."
    )
    lines.append(_to_md(placebo_out))
    lines.append("")

    lines.append(
        "## (i) Joint pretrend tests\n\n"
        "Pre-launch portion only. \"Pretrend slope\" is the linear month trend (mirrors "
        "`scripts/run_jfe_identification_extensions.py`'s `v3_event_time_pretrends`); \"Joint "
        "chi2\"/\"Joint p\" is the omnibus cluster-robust Wald test that ALL pre-period month "
        "dummies (relative to the launch-month reference) are jointly zero -- this is what "
        "\"joint pretrend tests\" in the RQ4 diagnostics list calls for and the existing script "
        "does not itself compute."
    )
    lines.append(_to_md(pretrend_out))
    lines.append("")

    lines.append(
        "## (ii) Elasticity test split by pre-V3 pair volatility -- extended to both windows and all three outcomes\n\n"
        "Extends the headline script's volatility split, which only ran +/-12mo and two of the "
        "three outcomes."
    )
    lines.append(_to_md(vol_out))
    lines.append("")

    lines.append(
        "## (iii) V2-only / V3-only / best-across-versions route construction\n\n"
        "Level DiD on the quote-based route_cost_panel_v2.parquet outcomes (the design "
        "`scripts/run_v3_architecture_pair_design.py` uses, generalized here from WETH-only to "
        "all five vehicle candidates). \"Best-across-versions\" is the existing unfiltered panel "
        "(whichever AMM version gave the best realized quote per leg); \"V2-only\"/\"V3-only\" "
        "restrict availability to legs whose realized best source was actually that version -- "
        "see module docstring for why this is a disclosed proxy, not a forced re-quote."
    )
    lines.append(_to_md(version_out))
    lines.append("")

    lines.append(
        "## (iv) Fixed 12- and 24-month event windows -- level DiD (reproduction of headline)"
    )
    lines.append(_to_md(fixed_level_out))
    lines.append("")
    lines.append(
        "## (iv) Fixed 12- and 24-month event windows -- elasticity test (reproduction of headline)"
    )
    lines.append(_to_md(fixed_elastic_out))
    lines.append("")

    (OUTDIR / "p2_robustness_battery_results.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

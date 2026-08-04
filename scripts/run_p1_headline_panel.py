#!/usr/bin/env python3
"""P1 headline panel: candidate-linked liquidity, DirectCostAdvantage, and
indirect-route volume share, for the 5-token candidate set.

Per output/nbc_pipeline/02_framings/framing_1.md Section 2 ("P1's test"), the
headline exhibit links:
  L_{k,t}                (candidate-linked liquidity depth,   column
                           log_vehicle_linked_liquidity = ln(1+L_{k,t}))
  DirectCostAdvantage_{k,t,q}  (column direct_cost_advantage_median, q=$10k)
  VehicleShare_{k,t}      (candidate k's share of day-t indirect-route USD
                           volume, column bridge_share -- this is the
                           token-day-varying operationalization of "indirect-
                           route volume share" registered in
                           src/ddvc/variable_registry.py under notation
                           VehicleShare_{k,t}, and is the exact quantity
                           docs/research-questions-and-empirical-design.md's
                           RQ2 Experiment A calls VehicleShare_{k,t})

Per the shock-scoping report referenced by the task instructions:
  - No IV / event-study design is run here. The one clean candidate exogenous
    supply-side shock found (UNI liquidity-mining launch, 2020-09-18, on the
    four WETH-paired V2 pools) predates this repo's L_{k,t} construction,
    which is hard-coded to Uniswap V3 pool data
    (src/ddvc/analysis/lp_concentration.py) and is only populated from
    2021-05-04 onward. Extending L_{k,t} to V2 is real, non-trivial build
    work that was out of scope for this pass -- it is NOT done here, and no
    IV/break-in-simultaneity result is claimed.
  - What IS run: the pure lead-lag / local-projection panel already spec'd as
    RQ2 Experiment A (docs/research-questions-and-empirical-design.md), using
    the lag_/future_ columns src/ddvc/analysis/observations.py::_add_dynamics
    already builds into data/processed/observations_token_day.parquet. This
    establishes temporal precedence among L, D, S -- NOT a causal break in
    the contemporaneous simultaneity problem the referee flagged in
    framing_1.md. The common-demand-shock confound (new listing, exchange
    integration moving all three at once) is NOT resolved by this design.
    This matches framing_1.md's own language: "predictive feedback, not a
    causal supply elasticity."

System of 3 forward local-projection equations, each regressed on all three
current-period variables (a poor-man's VAR/Granger system) plus token and
date fixed effects, for horizons tau in {1, 7, 14, 30} days:

  Delta_tau S_{k,t+tau} = a_k + d_t + b1 L_{k,t} + b2 D_{k,t} + b3 S_{k,t} + e
  Delta_tau L_{k,t+tau} = a_k + d_t + b1 S_{k,t} + b2 D_{k,t} + b3 L_{k,t} + e
  Delta_tau D_{k,t+tau} = a_k + d_t + b1 L_{k,t} + b2 S_{k,t} + b3 D_{k,t} + e

Inference: (i) date-cluster-robust (repo convention, see
scripts/run_feedback_proposition_tests.py::_cluster_ols_multi), (ii)
Driscoll-Kraay HAC with Bartlett-kernel lag L=max(tau,5) to allow for the
serial correlation the tau-day-ahead construction mechanically induces, and
(iii) a calendar-month block bootstrap (500 reps) as an independent
cross-check, per docs/research-questions-and-empirical-design.md RQ2
Experiment A's stated inference requirement ("Driscoll-Kraay errors and
calendar-month block bootstrap because five candidates are insufficient for
ordinary candidate-cluster asymptotics").

Inputs (already built, not refetched):
  data/processed/observations_token_day.parquet

Outputs:
  output/nbc_pipeline/04_evidence/p1/p1_headline_panel_results.csv
  output/nbc_pipeline/04_evidence/p1/p1_headline_panel_sample.csv
  output/nbc_pipeline/04_evidence/p1/p1_headline_panel_results.md
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTDIR = ROOT / "output" / "nbc_pipeline" / "04_evidence" / "p1"

VEHICLES = ["WETH", "USDC", "USDT", "DAI", "WBTC"]
HORIZONS = [1, 7, 14, 30]
N_BOOT = 500
BOOT_SEED = 20260804

# Core variable columns (see module docstring for notation mapping).
COL_L = "log_vehicle_linked_liquidity"   # L_{k,t} in logs
COL_D = "direct_cost_advantage_median"   # DirectCostAdvantage_{k,t,q=10k}
COL_S = "bridge_share"                   # VehicleShare_{k,t}


def _num(x: float, digits: int = 4) -> str:
    return "" if x is None or not np.isfinite(x) else f"{x:.{digits}f}"


def _int(x: float) -> str:
    return "" if x is None or not np.isfinite(x) else f"{int(round(x)):,}"


def _p(x: float) -> str:
    if x is None or not np.isfinite(x):
        return ""
    if x < 0.001:
        return "<0.001"
    return f"{x:.3f}"


def _to_md(df: pd.DataFrame) -> str:
    """Minimal markdown-table writer -- `tabulate` (pandas' `to_markdown`
    dependency) is not installed in .venv, so this repo's own scripts must
    not rely on it."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def load_core_panel() -> pd.DataFrame:
    df = pd.read_parquet(DATA / "processed" / "observations_token_day.parquet")
    df = df[df["token"].isin(VEHICLES)].copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["token", "date"]).reset_index(drop=True)


def _two_way_demean(frame: pd.DataFrame, col: str) -> pd.Series:
    """Additive token+date fixed-effect residual (single-pass demeaning, the
    same approximation used throughout this repo's estimation scripts, e.g.
    scripts/run_feedback_proposition_tests.py::_demean_two)."""
    s = frame[col]
    return (
        s
        - s.groupby(frame["token"]).transform("mean")
        - s.groupby(frame["date"]).transform("mean")
        + s.mean()
    )


def _build_model_frame(df: pd.DataFrame, horizon: int, base_col: str) -> pd.DataFrame:
    """One equation's estimation sample: forward tau-day change in
    `base_col`'s future_{...}_t{h} column minus its current level, on the
    three current-period regressors L, D, S plus token/date FE residuals.
    Demeaned regressor columns are stored under their short keys (L_dm,
    D_dm, S_dm) regardless of which one is the equation's own outcome, so
    every equation's regressor set can be built the same way."""
    future_col = f"future_{base_col}_t{horizon}"
    need = list(dict.fromkeys(["date", "token", future_col, base_col, COL_L, COL_D, COL_S]))
    sub = df[need].dropna().copy()
    sub["y"] = sub[future_col] - sub[base_col]
    for key, col in REGRESSOR_COL.items():
        sub[f"{key}_dm"] = _two_way_demean(sub, col)
    sub["y_dm"] = _two_way_demean(sub, "y")
    return sub


def _fit_ols(sub: pd.DataFrame, regressors: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.column_stack([np.ones(len(sub))] + [sub[f"{r}_dm"].to_numpy(float) for r in regressors])
    y = sub["y_dm"].to_numpy(float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    return beta, resid, x


def _cluster_by_date_se(sub: pd.DataFrame, regressors: list[str], beta: np.ndarray, resid: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, int]:
    n, k = x.shape
    dates = sub["date"].to_numpy()
    bread = np.linalg.inv(x.T @ x)
    meat = np.zeros((k, k))
    for _, idx in pd.Series(np.arange(n)).groupby(dates).groups.items():
        idx = np.asarray(idx)
        score = x[idx].T @ resid[idx][:, None]
        meat += score @ score.T
    c = pd.Series(dates).nunique()
    finite = (c / max(c - 1, 1)) * ((n - 1) / max(n - k, 1))
    cov = finite * bread @ meat @ bread
    return np.sqrt(np.clip(np.diag(cov), 0.0, None)), c


def _driscoll_kraay_se(sub: pd.DataFrame, regressors: list[str], beta: np.ndarray, resid: np.ndarray, x: np.ndarray, lag: int) -> tuple[np.ndarray, int]:
    """Driscoll & Kraay (1998) HAC standard errors: cross-sectional sums of
    the score by calendar date, then a Bartlett-kernel long-run variance
    across ordered (not necessarily contiguous) calendar dates."""
    n, k = x.shape
    bread = np.linalg.inv(x.T @ x)
    dates = sub["date"].to_numpy()
    order = np.argsort(dates)
    x_o, resid_o, dates_o = x[order], resid[order], dates[order]
    uniq_dates = np.unique(dates_o)
    h_by_t = np.zeros((len(uniq_dates), k))
    date_to_pos = {d: i for i, d in enumerate(uniq_dates)}
    for i in range(n):
        pos = date_to_pos[dates_o[i]]
        h_by_t[pos] += x_o[i] * resid_o[i]
    t_len = len(uniq_dates)
    omega = h_by_t.T @ h_by_t
    for j in range(1, lag + 1):
        if j >= t_len:
            break
        w = 1.0 - j / (lag + 1)
        gamma_j = h_by_t[j:].T @ h_by_t[:-j]
        omega += w * (gamma_j + gamma_j.T)
    cov = bread @ omega @ bread
    c = t_len
    finite = (c / max(c - 1, 1)) * ((n - 1) / max(n - k, 1))
    return np.sqrt(np.clip(finite * np.diag(cov), 0.0, None)), c


def _month_block_bootstrap_se(
    df: pd.DataFrame, horizon: int, outcome_col: str, base_col: str, regressors: list[str], n_boot: int = N_BOOT
) -> np.ndarray:
    future_col = f"future_{base_col}_t{horizon}"
    need = list(dict.fromkeys(["date", "token", future_col, base_col, COL_L, COL_D, COL_S]))
    base = df[need].dropna().copy()
    base["y"] = base[future_col] - base[base_col]
    base["month"] = base["date"].dt.to_period("M")
    months = base["month"].unique()
    outcome_seed_offset = {"S": 0, "L": 1000, "D": 2000}.get(outcome_col, 3000)
    rng = np.random.default_rng(BOOT_SEED + horizon + outcome_seed_offset)
    k = len(regressors) + 1
    draws = np.full((n_boot, k), np.nan)
    for b in range(n_boot):
        sampled = rng.choice(months, size=len(months), replace=True)
        parts = [base[base["month"].eq(m)] for m in sampled]
        boot = pd.concat(parts, ignore_index=True)
        if boot["date"].nunique() < 20 or boot["token"].nunique() < 2:
            continue
        boot["y_dm"] = _two_way_demean(boot, "y")
        for key, col in REGRESSOR_COL.items():
            boot[f"{key}_dm"] = _two_way_demean(boot, col)
        x = np.column_stack([np.ones(len(boot))] + [boot[f"{r}_dm"].to_numpy(float) for r in regressors])
        y = boot["y_dm"].to_numpy(float)
        if np.linalg.matrix_rank(x) < x.shape[1]:
            continue
        beta_b, *_ = np.linalg.lstsq(x, y, rcond=None)
        draws[b] = beta_b
    return np.nanstd(draws, axis=0, ddof=1)


PREDICTED_SIGN = {
    ("S", "L"): "+",  # deeper own liquidity -> more future indirect share through k
    ("S", "D"): "-",  # bigger direct-cost advantage (direct cheaper) -> less indirect reliance on k
    ("S", "S"): None,  # own-lag/AR control, no P1 sign prediction
    ("L", "S"): "+",  # more indirect volume through k -> more LP capital drawn (Krugman feedback closing the loop)
    ("L", "D"): None,  # secondary control, no explicit P1 prediction
    ("L", "L"): None,  # own-lag/AR control
    ("D", "L"): "-",  # deeper own liquidity -> lower price impact -> indirect route cheaper (D falls)
    ("D", "S"): None,  # secondary control, no explicit P1 prediction
    ("D", "D"): None,  # own-lag/AR control
}

# (outcome key, base column for lag/future lookup, list of regressors in the equation)
EQUATION_SPECS = [
    ("S", "bridge_share", ["L", "D", "S"]),
    ("L", "log_vehicle_linked_liquidity", ["S", "D", "L"]),
    ("D", "direct_cost_advantage_median", ["L", "S", "D"]),
]
REGRESSOR_COL = {"L": COL_L, "D": COL_D, "S": COL_S}
OUTCOME_LABEL = {
    "S": "Delta VehicleShare_{k,t+tau} (indirect-route volume share through k)",
    "L": "Delta LogVehicleLiquidity_{k,t+tau} (L_{k,t})",
    "D": "Delta DirectCostAdvantage_{k,t+tau}",
}


def run() -> pd.DataFrame:
    df = load_core_panel()
    core = df.dropna(subset=[COL_L, COL_D, COL_S]).copy()

    sample_rows = [{
        "Sample": "Core (L, D, S all observed)",
        "N rows": len(core),
        "Tokens": core["token"].nunique(),
        "First date": str(core["date"].min().date()),
        "Last date": str(core["date"].max().date()),
    }]
    for tok, g in core.groupby("token"):
        sample_rows.append({
            "Sample": f"  token={tok}", "N rows": len(g), "Tokens": 1,
            "First date": str(g["date"].min().date()), "Last date": str(g["date"].max().date()),
        })
    sample_df = pd.DataFrame(sample_rows)

    rows = []
    for outcome_key, base_col, reg_keys in EQUATION_SPECS:
        for h in HORIZONS:
            sub = _build_model_frame(df, h, base_col)
            regressors = reg_keys  # short keys, e.g. ["L", "D", "S"]; sub has L_dm/D_dm/S_dm columns
            beta, resid, x = _fit_ols(sub, regressors)
            n = len(sub)
            se_cluster, c_dates = _cluster_by_date_se(sub, regressors, beta, resid, x)
            lag = max(h, 5)
            se_dk, c_dk = _driscoll_kraay_se(sub, regressors, beta, resid, x, lag)
            se_boot = _month_block_bootstrap_se(df, h, outcome_key, base_col, regressors)

            for j, reg_key in enumerate(regressors, start=1):
                b = float(beta[j])
                se_c = float(se_cluster[j])
                se_d = float(se_dk[j])
                se_bt = float(se_boot[j]) if np.isfinite(se_boot[j]) else math.nan
                t_dk = b / se_d if se_d > 0 else math.nan
                p_dk = float(2 * stats.t.sf(abs(t_dk), max(c_dk - 1, 1))) if np.isfinite(t_dk) else math.nan
                t_c = b / se_c if se_c > 0 else math.nan
                p_c = float(2 * stats.t.sf(abs(t_c), max(c_dates - 1, 1))) if np.isfinite(t_c) else math.nan
                predicted = PREDICTED_SIGN.get((outcome_key, reg_key))
                actual_sign = "+" if b > 0 else ("-" if b < 0 else "0")
                if predicted is None:
                    sign_match = "n/a (no P1 prior)"
                else:
                    sign_significant = np.isfinite(p_dk) and p_dk < 0.05
                    sign_match = (
                        "MATCH (p<.05, DK)" if (predicted == actual_sign and sign_significant)
                        else (f"sign matches but not sig. (DK p={p_dk:.3f})" if predicted == actual_sign
                              else f"WRONG SIGN (predicted {predicted}, got {actual_sign})")
                    )
                rows.append({
                    "Equation": f"outcome={outcome_key}",
                    "Outcome (full)": OUTCOME_LABEL[outcome_key],
                    "Horizon (days)": h,
                    "Regressor": reg_key,
                    "N": n,
                    "Date clusters": c_dates,
                    "Beta": b,
                    "SE (cluster-by-date)": se_c,
                    "p (cluster-by-date)": p_c,
                    "SE (Driscoll-Kraay)": se_d,
                    "p (Driscoll-Kraay)": p_dk,
                    "SE (month block bootstrap)": se_bt,
                    "Predicted sign (P1)": predicted if predicted is not None else "(no prior)",
                    "Sign check": sign_match,
                })
    results = pd.DataFrame(rows)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(OUTDIR / "p1_headline_panel_results.csv", index=False)
    sample_df.to_csv(OUTDIR / "p1_headline_panel_sample.csv", index=False)

    fmt = results.copy()
    for c in ["Beta", "SE (cluster-by-date)", "SE (Driscoll-Kraay)", "SE (month block bootstrap)"]:
        fmt[c] = fmt[c].map(lambda v: _num(v, 4))
    for c in ["p (cluster-by-date)", "p (Driscoll-Kraay)"]:
        fmt[c] = fmt[c].map(_p)
    fmt["N"] = fmt["N"].map(_int)
    fmt["Date clusters"] = fmt["Date clusters"].map(_int)

    lines = []
    lines.append("# P1 headline panel: L_{k,t}, DirectCostAdvantage_{k,t,q}, VehicleShare_{k,t}")
    lines.append("")
    lines.append(
        "Lead-lag/local-projection system (RQ2 Experiment A operationalization), NOT an IV/event-study "
        "causal design -- the one clean exogenous shock found (UNI liquidity-mining launch, 2020-09-18) "
        "predates this repo's V3-only L_{k,t} construction and would require new V2-equivalent build work "
        "out of scope for this pass. This establishes temporal precedence, not a break in the contemporaneous "
        "simultaneity the referee flagged; the common-demand-shock confound is not resolved."
    )
    lines.append("")
    lines.append("## Sample")
    lines.append(_to_md(sample_df))
    lines.append("")
    lines.append("## Results (all 3 equations x 4 horizons x 3 regressors)")
    lines.append(_to_md(fmt))
    lines.append("")
    (OUTDIR / "p1_headline_panel_results.md").write_text("\n".join(lines) + "\n")

    print("\n".join(lines))
    return results


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Shared estimation helpers for the P1 robustness battery
(scripts/run_p1_robustness_battery.py). Factored out of
scripts/run_p1_headline_panel.py so every robustness check (subsample split,
alternative-measure variant, sample-period split) runs through the exact same
estimator -- same two-way demeaning, same three inference methods
(cluster-by-date, Driscoll-Kraay HAC, calendar-month block bootstrap) -- with
only the input frame and the L/D/S column names varying. This is a library
module (imported, never executed directly); it intentionally has no
__main__ guarded runner.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

HORIZONS = [1, 7, 14, 30]
N_BOOT = 500
BOOT_SEED = 20260804


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


def to_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def format_results_table(results: pd.DataFrame) -> pd.DataFrame:
    fmt = results.copy()
    for c in ["Beta", "SE (cluster-by-date)", "SE (Driscoll-Kraay)", "SE (month block bootstrap)"]:
        if c in fmt.columns:
            fmt[c] = fmt[c].map(lambda v: _num(v, 4))
    for c in ["p (cluster-by-date)", "p (Driscoll-Kraay)"]:
        if c in fmt.columns:
            fmt[c] = fmt[c].map(_p)
    for c in ["N", "Date clusters"]:
        if c in fmt.columns:
            fmt[c] = fmt[c].map(_int)
    return fmt


def two_way_demean(frame: pd.DataFrame, col: str) -> pd.Series:
    """Additive token+date fixed-effect residual (single-pass demeaning, same
    approximation as scripts/run_p1_headline_panel.py::_two_way_demean)."""
    s = frame[col]
    return (
        s
        - s.groupby(frame["token"]).transform("mean")
        - s.groupby(frame["date"]).transform("mean")
        + s.mean()
    )


def build_model_frame(
    df: pd.DataFrame, horizon: int, base_col: str, regressor_cols: dict[str, str]
) -> pd.DataFrame:
    """One equation's estimation sample. `regressor_cols` maps short keys
    (e.g. "L", "D", "S") to the actual column name to use for that role in
    THIS variant of the system (so alternative-measure checks can swap in a
    different depth or DirectCostAdvantage column without touching the
    estimator)."""
    future_col = f"future_{base_col}_t{horizon}"
    need = list(dict.fromkeys(["date", "token", future_col, base_col, *regressor_cols.values()]))
    sub = df[need].dropna().copy()
    sub["y"] = sub[future_col] - sub[base_col]
    for key, col in regressor_cols.items():
        sub[f"{key}_dm"] = two_way_demean(sub, col)
    sub["y_dm"] = two_way_demean(sub, "y")
    return sub


def fit_ols(sub: pd.DataFrame, regressors: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.column_stack([np.ones(len(sub))] + [sub[f"{r}_dm"].to_numpy(float) for r in regressors])
    y = sub["y_dm"].to_numpy(float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    return beta, resid, x


def cluster_by_date_se(sub: pd.DataFrame, x: np.ndarray, resid: np.ndarray) -> tuple[np.ndarray, int]:
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


def driscoll_kraay_se(sub: pd.DataFrame, x: np.ndarray, resid: np.ndarray, lag: int) -> tuple[np.ndarray, int]:
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


def month_block_bootstrap_se(
    df: pd.DataFrame,
    horizon: int,
    outcome_key: str,
    base_col: str,
    regressor_cols: dict[str, str],
    regressors: list[str],
    n_boot: int = N_BOOT,
    seed_offset: int = 0,
) -> np.ndarray:
    future_col = f"future_{base_col}_t{horizon}"
    need = list(dict.fromkeys(["date", "token", future_col, base_col, *regressor_cols.values()]))
    base = df[need].dropna().copy()
    base["y"] = base[future_col] - base[base_col]
    base["month"] = base["date"].dt.to_period("M")
    months = base["month"].unique()
    outcome_seed = {"S": 0, "L": 1000, "D": 2000}.get(outcome_key, 3000)
    rng = np.random.default_rng(BOOT_SEED + horizon + outcome_seed + seed_offset)
    k = len(regressors) + 1
    draws = np.full((n_boot, k), np.nan)
    for b in range(n_boot):
        sampled = rng.choice(months, size=len(months), replace=True)
        parts = [base[base["month"].eq(m)] for m in sampled]
        boot = pd.concat(parts, ignore_index=True)
        if boot["date"].nunique() < 20 or boot["token"].nunique() < 2:
            continue
        boot["y_dm"] = two_way_demean(boot, "y")
        for key, col in regressor_cols.items():
            boot[f"{key}_dm"] = two_way_demean(boot, col)
        x = np.column_stack([np.ones(len(boot))] + [boot[f"{r}_dm"].to_numpy(float) for r in regressors])
        y = boot["y_dm"].to_numpy(float)
        if np.linalg.matrix_rank(x) < x.shape[1]:
            continue
        beta_b, *_ = np.linalg.lstsq(x, y, rcond=None)
        draws[b] = beta_b
    return np.nanstd(draws, axis=0, ddof=1)


EQUATION_SPECS_TEMPLATE = [
    ("S", "S", ["L", "D", "S"]),
    ("L", "L", ["S", "D", "L"]),
    ("D", "D", ["L", "S", "D"]),
]

OUTCOME_LABEL = {
    "S": "Delta VehicleShare_{k,t+tau}",
    "L": "Delta depth_{k,t+tau}",
    "D": "Delta DirectCostAdvantage_{k,t+tau}",
}


def run_system(
    df: pd.DataFrame,
    col_map: dict[str, str],
    *,
    horizons: list[int] = HORIZONS,
    n_boot: int = N_BOOT,
    predicted_sign: dict[tuple[str, str], str | None] | None = None,
    seed_offset: int = 0,
    equation_keys: tuple[str, ...] = ("S", "L", "D"),
) -> pd.DataFrame:
    """Run the 3-equation (or subset) lead-lag system on `df`, using
    col_map={"L": <col>, "D": <col>, "S": <col>} for this variant's L/D/S
    columns. Returns the same long-format results table as
    run_p1_headline_panel.py, generalized to whichever columns were passed."""
    predicted_sign = predicted_sign or {}
    rows = []
    for outcome_key, base_key, reg_keys in EQUATION_SPECS_TEMPLATE:
        if outcome_key not in equation_keys:
            continue
        base_col = col_map[base_key]
        for h in horizons:
            sub = build_model_frame(df, h, base_col, col_map)
            beta, resid, x = fit_ols(sub, reg_keys)
            n = len(sub)
            se_cluster, c_dates = cluster_by_date_se(sub, x, resid)
            lag = max(h, 5)
            se_dk, c_dk = driscoll_kraay_se(sub, x, resid, lag)
            se_boot = (
                month_block_bootstrap_se(df, h, outcome_key, base_col, col_map, reg_keys, n_boot, seed_offset)
                if n_boot > 0
                else np.full(len(reg_keys) + 1, math.nan)
            )
            for j, reg_key in enumerate(reg_keys, start=1):
                b = float(beta[j])
                se_c = float(se_cluster[j])
                se_d = float(se_dk[j])
                se_bt = float(se_boot[j]) if np.isfinite(se_boot[j]) else math.nan
                t_dk = b / se_d if se_d > 0 else math.nan
                p_dk = float(2 * stats.t.sf(abs(t_dk), max(c_dk - 1, 1))) if np.isfinite(t_dk) else math.nan
                t_c = b / se_c if se_c > 0 else math.nan
                p_c = float(2 * stats.t.sf(abs(t_c), max(c_dates - 1, 1))) if np.isfinite(t_c) else math.nan
                predicted = predicted_sign.get((outcome_key, reg_key))
                actual_sign = "+" if b > 0 else ("-" if b < 0 else "0")
                if predicted is None:
                    sign_match = "n/a (no P1 prior)"
                else:
                    sig = np.isfinite(p_dk) and p_dk < 0.05
                    sign_match = (
                        "MATCH (p<.05, DK)" if (predicted == actual_sign and sig)
                        else (f"sign matches but not sig. (DK p={p_dk:.3f})" if predicted == actual_sign
                              else f"WRONG SIGN (predicted {predicted}, got {actual_sign})")
                    )
                rows.append({
                    "Equation": f"outcome={outcome_key}",
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
    return pd.DataFrame(rows)


PREDICTED_SIGN = {
    ("S", "L"): "+",
    ("S", "D"): "-",
    ("S", "S"): None,
    ("L", "S"): "+",
    ("L", "D"): None,
    ("L", "L"): None,
    ("D", "L"): "-",
    ("D", "S"): None,
    ("D", "D"): None,
}

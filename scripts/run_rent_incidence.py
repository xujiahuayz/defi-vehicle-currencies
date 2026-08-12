#!/usr/bin/env python3
"""Withdrawn rent-incidence accounting helpers retained for validated unit tests.

The executable estimator is unavailable until receipt-measured LP-operation gas is certified.

Reads the pool-day panels built by `build_rent_incidence_panel.py`, prices them,
nets gas, groups by the asset roles of the pool's two legs, and tests the
centrality-curse prediction that the most central asset's pools earn the worst
risk-adjusted net return.

Accounting, stated once.

  fee revenue      fee rate times USD volume. 30 basis points on v2; the exact
                   canonical-state tier on v3.
  LVR              external-reference-price realised variance over eight, times
                   contemporaneous pool value. The closed form is admitted only
                   for constant-product pools after the external price path passes.
  gas              exact receipt cost allocated to the pool's mint, burn,
                   collect, and linked rebalance transactions, then summed by day.
  net              fee revenue less LVR less gas.

Pool-price variance remains diagnostic and cannot enter LVR inference. Return
denominators are exact prior-calendar-day deposited capital. For v2 this
is lagged reconstructed reserve capital, valued from a separately validated
anchored-leg price. The contemporaneous pool-value LVR scale is kept separately,
so an LVR return is (current pool value / lagged capital) times realised variance
over eight. V3 capital, LVR, signs, ratios and return inference are absent until
the inventory replay passes custody and LP-ownership reconciliation and a
path-integrated concentrated-liquidity LVR adapter passes independently.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]

from ddvc.asset_types import asset_type
from ddvc.analysis.regression import ClusteredOLSResult, ols_clustered
from ddvc.capital_contracts import RETURN_CAPITAL_VALIDATION_STATUS, capital_contract
from ddvc.capital_validation import (
    ANCHORED_CAPITAL_ROLES,
    CAPITAL_PRICE_SOURCE,
)
from ddvc.liquidity import (
    CAPITAL_COLUMN,
    LVR_SCALE_COLUMN,
    LOCAL_DEPTH_COLUMN,
    MAX_POOL_CAPITAL_USD,
    capital_interpretable,
    capital_scale_label,
    constant_product_lvr_usd,
    lvr_inference_ready,
    require_capital_denominator,
    return_inference_ready,
)
from ddvc.runtime import exclusive_job

LOCK = ROOT / "output" / "empirical" / "rent_incidence" / ".run.lock"

MIN_TVL = 10_000.0
MIN_MONTH_DAYS = 15
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
# A pool price that moves by more than this inside one hour is a rug, a
# rebase or a decimals artefact, not a price. Screening these out REMOVES
# the largest LVR observations, so it works against the finding below
# rather than for it, and the unscreened figure is reported alongside.
MAX_HOURLY_MOVE = 100.0


def _capital_scale_basis(venue: str) -> str:
    if capital_interpretable(venue):
        return capital_contract(venue).capital_measure
    return capital_scale_label(venue)


# ---------------------------------------------------------------------------
# inference
# ---------------------------------------------------------------------------

def wald(beta, V, idx) -> tuple[float, int, float]:
    """Joint Wald test that every coefficient in `idx` is zero."""
    b = beta[idx]
    Vs = V[np.ix_(idx, idx)]
    stat = float(b @ np.linalg.pinv(Vs) @ b)
    q = len(idx)
    # chi-square survival by the regularised upper incomplete gamma
    return stat, q, float(stats.chi2.sf(stat, q))


def _inference_fields(fit: ClusteredOLSResult) -> dict[str, object]:
    counts = fit.cluster_counts or (fit.n_clusters,)
    return {
        "n": fit.n_observations,
        "clusters": fit.n_clusters,
        "pool_clusters": counts[0],
        "month_clusters": counts[1] if len(counts) > 1 else None,
        "covariance": "two_way_pool_month_cr1" if len(counts) > 1 else "one_way_pool_cr1",
    }


def report(
    name,
    y,
    X,
    cols,
    cluster,
    *,
    additional_cluster=None,
    k_absorbed=0,
    focus=None,
):
    fit = ols_clustered(
        y,
        X,
        cluster,
        add_constant=False,
        k_absorbed=k_absorbed,
        additional_clusters=(additional_cluster,) if additional_cluster is not None else (),
    )
    beta, V = fit.beta, fit.covariance
    se, p_values = fit.standard_errors, fit.p_values
    pool_fit = None
    month_fit = None
    if additional_cluster is not None:
        pool_fit = ols_clustered(
            y,
            X,
            cluster,
            add_constant=False,
            k_absorbed=k_absorbed,
        )
        month_fit = ols_clustered(
            y,
            X,
            additional_cluster,
            add_constant=False,
            k_absorbed=k_absorbed,
        )
        if not (
            np.allclose(beta, pool_fit.beta, equal_nan=True)
            and np.allclose(beta, month_fit.beta, equal_nan=True)
        ):
            raise RuntimeError("covariance sensitivities changed the OLS coefficient sample")
    cluster_text = " x ".join(f"{count:,}" for count in fit.cluster_counts)
    print(f"\n{name}   n={fit.n_observations:,}  clusters={cluster_text}")
    print(f"  {'term':<28}{'coef':>12}{'se':>12}{'t':>8}{'p':>8}{'MDE':>12}")
    recs = []
    mde_multiplier = (
        stats.t.ppf(0.975, fit.n_clusters - 1)
        + stats.t.ppf(0.8, fit.n_clusters - 1)
        if fit.n_clusters >= 2
        else np.nan
    )
    for i, c in enumerate(cols):
        if focus is not None and c not in focus:
            continue
        t = fit.t_statistics[i]
        p = p_values[i]
        mde = mde_multiplier * se[i]
        print(f"  {c:<28}{beta[i]:>12.4f}{se[i]:>12.4f}{t:>8.2f}{p:>8.3f}{mde:>12.4f}")
        recs.append(
            {
                "spec": name,
                "term": c,
                "coef": float(beta[i]),
                "se": float(se[i]),
                "t": float(t),
                "p": float(p),
                "mde_80pct": float(mde),
                "se_pool_only": float(pool_fit.standard_errors[i]) if pool_fit else np.nan,
                "p_pool_only": float(pool_fit.p_values[i]) if pool_fit else np.nan,
                "se_month_only": float(month_fit.standard_errors[i]) if month_fit else np.nan,
                "p_month_only": float(month_fit.p_values[i]) if month_fit else np.nan,
                **_inference_fields(fit),
            }
        )
    return beta, V, fit, recs


# ---------------------------------------------------------------------------
# pricing and screening
# ---------------------------------------------------------------------------

def price_and_screen(
    df: pd.DataFrame,
    venue: str,
    min_tvl: float = MIN_TVL,
) -> tuple[pd.DataFrame, list[dict]]:
    """Value, screen and account for one venue's pool-days.

    Validation has already run off a predeclared anchored leg. The repository's token price panel is
    itself derived from pool prices, so a token whose only market is one thin
    pool gets whatever price that pool implies, and multiplying it by that same
    pool's reserves manufactures capital out of nothing: an early cut of this
    table showed the unclassified-pair bucket holding 145 trillion dollars of
    capital-days and a net return of minus 30,000 percent. A constant-product
    pool holds equal value on both legs by construction, so the pool can be
    valued from the leg whose price is separately anchored (a native, staked
    native, stable or imported asset) at twice that leg's value, with the other
    leg's implied price never entering. Pools with no anchored leg are dropped
    and counted, which is the aggressive screen the earlier cut needed.
    """
    steps = []

    def note(label, frame):
        steps.append({"venue": venue, "screen": label, "pool_days": int(len(frame)),
                      "pools": int(frame.pool.nunique()) if len(frame) else 0})
        return frame

    note("0 raw pool-days", df)

    df = df[df.sym0.notna() & df.sym1.notna()
            & (df.sym0.astype(str).str.strip() != "")
            & (df.sym1.astype(str).str.strip() != "")]
    note("1 both legs carry a symbol", df)

    df = df[df.n_ret >= 1]
    note("2 at least one intraday return", df)

    df = df.copy()
    df["type0"] = df.token0.map(asset_type)
    df["type1"] = df.token1.map(asset_type)
    df = df[
        df.type0.isin(ANCHORED_CAPITAL_ROLES)
        | df.type1.isin(ANCHORED_CAPITAL_ROLES)
    ]
    note("3 at least one externally anchored leg", df)

    df = df[df.max_abs_ret <= np.log(MAX_HOURLY_MOVE)]
    note(f"4 no single hour moving the pool price by more than {MAX_HOURLY_MOVE:.0f}x", df)

    if venue == "uniswap_v2":
        df = df[
            df["capital_valid"].fillna(False)
            & df["price_source"].eq(CAPITAL_PRICE_SOURCE)
        ]
        note("5 current deposited capital passes canonical reserve reconciliation", df)
        df = df[
            df["exact_lag_valid"].fillna(False)
            & df["capital_validation_status"].eq(RETURN_CAPITAL_VALIDATION_STATUS)
        ]
        note("6 exact prior-calendar capital also passed canonical reconciliation", df)
        df[LOCAL_DEPTH_COLUMN] = df.reconstructed_capital_usd / 2.0
        df[LVR_SCALE_COLUMN] = df.reconstructed_capital_usd
    else:
        raise ValueError(f"rent incidence has no admitted capital-return path for {venue}")

    df = df[
        np.isfinite(df[CAPITAL_COLUMN])
        & df[CAPITAL_COLUMN].between(min_tvl, MAX_POOL_CAPITAL_USD)
        & np.isfinite(df[LOCAL_DEPTH_COLUMN])
        & df[LOCAL_DEPTH_COLUMN].gt(0)
    ]
    note(f"7 lagged deposited capital at least ${min_tvl:,.0f} and positive local depth", df)
    require_capital_denominator(
        df,
        venue=venue,
        purpose="return" if return_inference_ready(venue) else "descriptive",
    )

    # The old implementation borrowed pooled one-leg swap gas for mint and burn
    # operations. That is not an LP-operation measurement. Keep helper frames gross-only
    # until liquidity events carry their own receipt evidence and allocation contract.
    df["gas_usd"] = np.nan
    df["fees_usd"] = df.fee_rate * df.volume_usd
    if lvr_inference_ready(venue):
        df["lvr_usd"] = constant_product_lvr_usd(df.rv, df[LVR_SCALE_COLUMN])
        df["lvr_usd_4h"] = constant_product_lvr_usd(df.rv_4h, df[LVR_SCALE_COLUMN])
        df["lvr_usd_oc"] = constant_product_lvr_usd(df.rv_oc, df[LVR_SCALE_COLUMN])
    else:
        df[["lvr_usd", "lvr_usd_4h", "lvr_usd_oc"]] = np.nan
    df["net_gross_of_gas_usd"] = df.fees_usd - df.lvr_usd
    df["net_usd"] = df.net_gross_of_gas_usd - df.gas_usd

    for a, b in (("fee_yield", "fees_usd"), ("lvr_rate", "lvr_usd"),
                 ("gas_rate", "gas_usd"), ("net_yield", "net_usd"),
                 ("net_pre_gas_yield", "net_gross_of_gas_usd")):
        df[a] = df[b] / df[CAPITAL_COLUMN]

    df["pool_role"] = [" / ".join(sorted(x)) for x in zip(df.type0, df.type1)]
    df["other_role"] = np.where(df.token0 == WETH, df.type1,
                                np.where(df.token1 == WETH, df.type0, None))
    df["date"] = pd.to_datetime(df.day, format="%Y%m%d")
    df["month"] = df.date.dt.strftime("%Y-%m")
    df["turnover"] = df.volume_usd / df[CAPITAL_COLUMN]
    return df, steps


# ---------------------------------------------------------------------------
# exhibits
# ---------------------------------------------------------------------------

def by_role(df: pd.DataFrame, venue: str, gas_only: bool = True) -> pd.DataFrame:
    d = df[df.gas_usd.notna()] if gas_only else df
    rows = []
    for role, g in d.groupby("pool_role"):
        if len(g) < 500:
            continue
        rows.append({
            "venue": venue, "pool_role": role,
            "pools": int(g.pool.nunique()),
            "token_pairs": int(pd.Series(g.token0 + "_" + g.token1).nunique()),
            "pool_days": int(len(g)),
            "days": int(g.day.nunique()),
            "median_scale_usd": float(g[CAPITAL_COLUMN].median()),
            "scale_days_usd_bn": float(g[CAPITAL_COLUMN].sum() / 1e9),
            "mean_daily_scale_usd_bn": float(g[CAPITAL_COLUMN].sum() / g.day.nunique() / 1e9),
            "scale_share": float(g[CAPITAL_COLUMN].sum() / d[CAPITAL_COLUMN].sum()),
            "pool_day_share": float(len(g) / len(d)),
            # equal-weighted pool-day medians, annualised
            "med_fee_yield_apr": float(g.fee_yield.median() * 365)
            if return_inference_ready(venue) else np.nan,
            "med_lvr_rate_apr": float(g.lvr_rate.median() * 365)
            if return_inference_ready(venue) else np.nan,
            "mean_gas_rate_apr": float(g.gas_rate.mean() * 365)
            if return_inference_ready(venue) else np.nan,
            "share_days_with_lp_event": float(((g.n_mint + g.n_burn) > 0).mean()),
            "med_net_yield_apr": float(g.net_yield.median() * 365)
            if return_inference_ready(venue) else np.nan,
            "share_net_positive": float((g.net_yield > 0).mean())
            if lvr_inference_ready(venue) else np.nan,
            "share_net_positive_pre_gas": float((g.net_pre_gas_yield > 0).mean())
            if lvr_inference_ready(venue) else np.nan,
            # capital-weighted aggregate: total dollars over total capital-days
            "cw_fee_yield_apr": float(g.fees_usd.sum() / g[CAPITAL_COLUMN].sum() * 365)
            if return_inference_ready(venue) else np.nan,
            "cw_lvr_rate_apr": float(g.lvr_usd.sum() / g[CAPITAL_COLUMN].sum() * 365)
            if return_inference_ready(venue) else np.nan,
            "cw_gas_rate_apr": float(g.gas_usd.sum() / g[CAPITAL_COLUMN].sum() * 365)
            if return_inference_ready(venue) else np.nan,
            "cw_net_yield_apr": float(g.net_usd.sum() / g[CAPITAL_COLUMN].sum() * 365)
            if return_inference_ready(venue) else np.nan,
            # Dollar net flow and fee-to-loss ratios also require a valid LVR
            # numerator. They remain missing when a venue lacks that adapter.
            "net_musd": float(g.net_usd.sum() / 1e6)
            if lvr_inference_ready(venue) else np.nan,
            "fee_over_lvr": float(g.fees_usd.sum() / g.lvr_usd.sum())
            if lvr_inference_ready(venue) and g.lvr_usd.sum() > 0 else np.nan,
            "fee_over_lvr_plus_gas": float(
                g.fees_usd.sum() / (g.lvr_usd.sum() + g.gas_usd.sum()))
            if lvr_inference_ready(venue) and (g.lvr_usd.sum() + g.gas_usd.sum()) > 0
            else np.nan,
            "med_pool_day_fee_over_lvr": float(
                (g.fees_usd / g.lvr_usd.replace(0, np.nan)).median())
            if lvr_inference_ready(venue) else np.nan,
            "scale_basis": _capital_scale_basis(venue),
            "capital_interpretable": capital_interpretable(venue),
            "return_inference_ready": return_inference_ready(venue),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values("scale_days_usd_bn", ascending=False)


def by_role_over_time(df: pd.DataFrame, venue: str) -> pd.DataFrame:
    """Keep pooled and annual role incidence under the venue's valid scale."""
    pooled = by_role(df, venue)
    pooled.insert(0, "year", pd.NA)
    pooled.insert(0, "scope", "pooled")
    annual: list[pd.DataFrame] = []
    years = pd.to_datetime(df["date"]).dt.year
    for year, group in df.groupby(years, sort=True):
        table = by_role(group, venue)
        if table.empty:
            continue
        table.insert(0, "year", int(year))
        table.insert(0, "scope", "annual")
        annual.append(table)
    return pd.concat([pooled, *annual], ignore_index=True, sort=False)


def by_size(df: pd.DataFrame, venue: str) -> pd.DataFrame:
    d = df[df.gas_usd.notna()].copy()
    d["size_bin"] = pd.qcut(np.log10(d[CAPITAL_COLUMN]), 10, labels=False, duplicates="drop")
    rows = []
    for b, g in d.groupby("size_bin"):
        rows.append({"venue": venue, "tvl_decile": int(b) + 1,
                     "pools": int(g.pool.nunique()),
            "token_pairs": int(pd.Series(g.token0 + "_" + g.token1).nunique()),
            "pool_days": int(len(g)),
                     "median_tvl_usd": float(g[CAPITAL_COLUMN].median()),
                     "med_fee_yield_apr": float(g.fee_yield.median() * 365),
                     "med_lvr_rate_apr": float(g.lvr_rate.median() * 365),
                     "mean_gas_rate_apr": float(g.gas_rate.mean() * 365),
                     "share_days_with_lp_event": float(((g.n_mint + g.n_burn) > 0).mean()),
                     "gas_rate_apr_given_event": float(
                         g.gas_rate[(g.n_mint + g.n_burn) > 0].median() * 365),
                     "med_net_yield_apr": float(g.net_yield.median() * 365),
                     "share_net_positive": float((g.net_yield > 0).mean())})
    return pd.DataFrame(rows)


def pool_months(df: pd.DataFrame, cent: pd.DataFrame, venue: str) -> pd.DataFrame:
    """Pool-month risk-adjusted net return, with centrality, depth and volatility."""
    d = df[df.gas_usd.notna()].copy()
    c0 = cent.rename(columns={"token": "token0", "betweenness_volume": "c0",
                              "degree": "deg0"})
    c1 = cent.rename(columns={"token": "token1", "betweenness_volume": "c1",
                              "degree": "deg1"})
    d = d.merge(c0[["day", "token0", "c0", "deg0"]], on=["day", "token0"], how="left")
    d = d.merge(c1[["day", "token1", "c1", "deg1"]], on=["day", "token1"], how="left")
    d["c_max"] = d[["c0", "c1"]].max(axis=1)
    d["deg_max"] = d[["deg0", "deg1"]].max(axis=1)
    # centrality of the leg that is NOT the platform's native asset, which is the
    # within-quote-asset comparison
    d["c_other"] = np.where(d.token0 == WETH, d.c1, np.where(d.token1 == WETH, d.c0, np.nan))

    g = d.groupby(["venue", "pool", "month"])
    pm = g.agg(n_days=("net_yield", "size"),
               mean_net=("net_yield", "mean"), sd_net=("net_yield", "std"),
               mean_fee=("fee_yield", "mean"), mean_lvr=("lvr_rate", "mean"),
               mean_gas=("gas_rate", "mean"),
               fees=("fees_usd", "sum"), lvr=("lvr_usd", "sum"),
               lvr4=("lvr_usd_4h", "sum"), gas=("gas_usd", "sum"),
               scale_days=(CAPITAL_COLUMN, "sum"),
               scale=(CAPITAL_COLUMN, "median"),
               local_depth=(LOCAL_DEPTH_COLUMN, "median"), rv=("rv", "mean"),
               turnover=("turnover", "median"),
               c_max=("c_max", "mean"), c_other=("c_other", "mean"),
               deg_max=("deg_max", "mean"),
               pool_role=("pool_role", "first"),
               other_role=("other_role", "first")).reset_index()
    pm = pm[pm.n_days >= MIN_MONTH_DAYS]
    pm["sharpe"] = (
        pm.mean_net / pm.sd_net.replace(0, np.nan)
        if return_inference_ready(venue)
        else np.nan
    )
    pm["net_yield_apr"] = (
        (pm.fees - pm.lvr - pm.gas) / pm.scale_days * 365
        if return_inference_ready(venue)
        else np.nan
    )
    pm["net_yield_apr_w"] = pm.net_yield_apr.clip(*pm.net_yield_apr.quantile([.01, .99]))
    # A bounded outcome, because the APR's own tails are extreme enough that its
    # mean is not a summary of anything: thin pools carry realised variances that
    # put the mean two orders of magnitude from the median.
    pm["net_positive"] = (
        ((pm.fees - pm.lvr - pm.gas) > 0).astype(float)
        if lvr_inference_ready(venue)
        else np.nan
    )
    pm["net_yield_apr_4h"] = (
        (pm.fees - pm.lvr4 - pm.gas) / pm.scale_days * 365
        if return_inference_ready(venue)
        else np.nan
    )
    pm["fee_yield_apr"] = (
        pm.fees / pm.scale_days * 365
        if return_inference_ready(venue)
        else np.nan
    )
    pm["log_fee_over_lvr"] = (
        np.log((pm.fees / pm.lvr).replace([np.inf, -np.inf], np.nan).clip(lower=1e-6))
        if lvr_inference_ready(venue)
        else np.nan
    )
    pm["log_scale"] = np.log(pm.scale)
    pm["log_local_depth"] = np.log(pm.local_depth)
    pm["log_rv"] = np.log(pm.rv.clip(lower=1e-12))
    pm["log_c"] = np.log1p(pm.c_max * 1e4)
    pm["log_c_other"] = np.log1p(pm.c_other * 1e4)
    pm["log_deg"] = np.log1p(pm.deg_max)
    pm["return_inference_ready"] = return_inference_ready(venue)
    if not return_inference_ready(venue):
        pm[[
            "mean_net",
            "sd_net",
            "mean_fee",
            "mean_lvr",
            "mean_gas",
            "sharpe",
            "net_yield_apr",
            "net_yield_apr_w",
            "net_yield_apr_4h",
            "fee_yield_apr",
        ]] = np.nan
    return pm


def robustness_row(
    venue: str,
    label: str,
    frame: pd.DataFrame,
    net_usd: pd.Series,
) -> dict:
    """Report capital returns only where the denominator is deposited reserves."""
    return {
        "venue": venue,
        "arm": label,
        "pool_days": int(len(frame)),
        "pools": int(frame.pool.nunique()),
        "med_net_yield_apr": float((net_usd / frame[CAPITAL_COLUMN]).median() * 365)
        if return_inference_ready(venue) else np.nan,
        "share_net_positive": float((net_usd > 0).mean())
        if lvr_inference_ready(venue) else np.nan,
        "scale_basis": _capital_scale_basis(venue),
    }


def main() -> int:
    raise RuntimeError(
        "rent-incidence estimator withdrawn pending receipt-measured LP-operation gas"
    )

if __name__ == "__main__":
    with exclusive_job(LOCK, job="rent-incidence estimator"):
        raise SystemExit(main())

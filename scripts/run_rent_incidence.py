#!/usr/bin/env python3
"""Does intermediating pay? Fee yield against LVR against net return, by asset role.

Reads the pool-day panels built by `build_rent_incidence_panel.py`, prices them,
nets gas, groups by the asset roles of the pool's two legs, and tests the
centrality-curse prediction that the most central asset's pools earn the worst
risk-adjusted net return.

Accounting, stated once.

  fee revenue      fee rate times USD volume. 30 basis points on v2; the exact
                   canonical-state tier on v3.
  LVR              realised variance over eight, times contemporaneous pool
                   value. This is admitted only for constant-product pools.
  gas              observed mints plus burns, times per-operation gas units,
                   times the day's median gas price, times the ETH price.
  net              fee revenue less LVR less gas.

Return denominators are exact prior-calendar-day deposited capital. For v2 this
is lagged reported reserve value, cross-checked against anchored reserve
valuation. The contemporaneous pool-value LVR scale is kept separately, so an
LVR return is (current pool value / lagged capital) times realised variance over
eight. V3 capital, LVR, signs, ratios and return inference are absent until the
inventory replay and path-integrated concentrated-liquidity LVR both pass.
"""

from __future__ import annotations

import json
from math import erfc, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ddvc.asset_types import asset_type
from ddvc.analysis.regression import ols_clustered
from ddvc.data_release import require_node_d_release
from ddvc.gas import load_daily_gas_prices
from ddvc.liquidity import (
    CAPITAL_COLUMN,
    LVR_SCALE_COLUMN,
    LOCAL_DEPTH_COLUMN,
    MAX_POOL_CAPITAL_USD,
    capital_reconciliation_mask,
    capital_interpretable,
    capital_scale_label,
    constant_product_lvr_usd,
    exact_calendar_lag,
    lvr_inference_ready,
    require_capital_denominator,
    return_inference_ready,
)
from ddvc.provenance import require_current_artifacts, stamp
from ddvc.runtime import exclusive_job
from ddvc.tables import write_exhibit, write_panel

PROC = ROOT / "data" / "processed"
OUT = ROOT / "output" / "empirical" / "rent_incidence"
LOCK = OUT / ".run.lock"
REQUIRED_PANELS = [
    PROC / "daily_gas_price_graph.parquet",
    PROC / "v2_token_price_daily.parquet",
    PROC / "vehicle_centrality_dense.parquet",
    PROC / "rent_incidence_v2_pool_day.parquet",
]
SRC = [
    "scripts/run_rent_incidence.py",
    "scripts/build_rent_incidence_panel.py",
    "src/ddvc/gas.py",
    "src/ddvc/liquidity.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/analysis/regression.py",
    "src/ddvc/tables.py",
]
OUTPUT_PROVENANCE = {"code_sources": SRC, "inputs": REQUIRED_PANELS}

MIN_TVL = 10_000.0
BALANCE_TOL = 3.0          # CPMM holds equal value on both legs; 3x is generous
CAPITAL_RECONCILIATION_TOL = 3.0
MIN_MONTH_DAYS = 15
GAS_UNITS = {"uniswap_v2": 155_000.0, "uniswap_v3": 225_000.0}
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
# A pool price that moves by more than this inside one hour is a rug, a
# rebase or a decimals artefact, not a price. Screening these out REMOVES
# the largest LVR observations, so it works against the finding below
# rather than for it, and the unscreened figure is reported alongside.
MAX_HOURLY_MOVE = 100.0


# ---------------------------------------------------------------------------
# inference
# ---------------------------------------------------------------------------

def pval(t: float) -> float:
    return erfc(abs(t) / sqrt(2)) if np.isfinite(t) else float("nan")


def wald(beta, V, idx) -> tuple[float, int, float]:
    """Joint Wald test that every coefficient in `idx` is zero."""
    b = beta[idx]
    Vs = V[np.ix_(idx, idx)]
    stat = float(b @ np.linalg.pinv(Vs) @ b)
    q = len(idx)
    # chi-square survival by the regularised upper incomplete gamma
    from scipy.stats import chi2
    return stat, q, float(chi2.sf(stat, q))


def report(name, y, X, cols, cluster, k_absorbed=0, focus=None):
    fit = ols_clustered(
        y,
        X,
        cluster,
        add_constant=False,
        k_absorbed=k_absorbed,
    )
    beta, V, g = fit.beta, fit.covariance, fit.n_clusters
    se = np.sqrt(np.maximum(np.diag(V), 0))
    print(f"\n{name}   n={len(y):,}  clusters={g:,}")
    print(f"  {'term':<28}{'coef':>12}{'se':>12}{'t':>8}{'p':>8}{'MDE':>12}")
    recs = []
    for i, c in enumerate(cols):
        if focus is not None and c not in focus:
            continue
        t = beta[i] / se[i] if se[i] > 0 else np.nan
        p = pval(t)
        mde = 2.802 * se[i]
        print(f"  {c:<28}{beta[i]:>12.4f}{se[i]:>12.4f}{t:>8.2f}{p:>8.3f}{mde:>12.4f}")
        recs.append({"spec": name, "term": c, "coef": float(beta[i]),
                     "se": float(se[i]), "t": float(t), "p": float(p),
                     "mde_80pct": float(mde), "n": int(len(y)), "clusters": int(g)})
    return beta, V, g, recs


# ---------------------------------------------------------------------------
# pricing and screening
# ---------------------------------------------------------------------------

def _prices() -> pd.DataFrame:
    """Daily token prices, with a sanity flag on each one.

    The price panel is derived from pool prices, so a thin token inherits
    whatever its own pool implies and occasional values are nonsense: wstETH
    carries a maximum of 346 million dollars in this panel against a median of
    1,891, and that single artefact put 959 billion dollars of phantom capital
    into the staked-native bucket. A price is accepted when it sits within a
    factor of four of the token's own centred 91-day rolling median, and a
    US-dollar stablecoin additionally has to be between half a dollar and two
    dollars. Both are integrity tests on an input, applied before anything is
    computed from it.
    """
    from ddvc.asset_types import NON_USD_STABLE, STABLE

    p = pd.read_parquet(PROC / "v2_token_price_daily.parquet",
                        columns=["date", "token", "symbol", "price_usd"])
    p["day"] = p.date.dt.strftime("%Y%m%d")
    p = p.sort_values(["token", "date"])
    med = (p.groupby("token", sort=False).price_usd
           .transform(lambda x: x.rolling(91, center=True, min_periods=5).median()))
    ok = (p.price_usd > 0) & med.gt(0) & (p.price_usd <= 4 * med) & (p.price_usd >= med / 4)
    usd_stable = {k for k, v in STABLE.items() if v not in NON_USD_STABLE}
    is_us = p.token.isin(usd_stable)
    ok &= ~is_us | (p.price_usd.between(0.5, 2.0))
    p["price_ok"] = ok
    return p[["day", "token", "price_usd", "price_ok"]]


def _gas() -> pd.DataFrame:
    p = _prices()
    g = load_daily_gas_prices(
        PROC / "daily_gas_price_graph.parquet",
        required_dates=p["day"],
    )[["day", "gas_gwei_median"]]
    eth = p[(p.token == WETH) & p.price_ok][["day", "price_usd"]].rename(
        columns={"price_usd": "eth_usd"})
    return g.merge(eth, on="day", how="left")


ANCHORED = ("native", "stable", "imported", "staked_native")


def price_and_screen(df: pd.DataFrame, venue: str, prices: pd.DataFrame,
                     gas: pd.DataFrame, min_tvl: float = MIN_TVL) -> tuple[pd.DataFrame, list[dict]]:
    """Value, screen and account for one venue's pool-days.

    Valuation runs off an ANCHORED leg. The repository's token price panel is
    itself derived from pool prices, so a token whose only market is one thin
    pool gets whatever price that pool implies, and multiplying it by that same
    pool's reserves manufactures capital out of nothing: an early cut of this
    table showed the unclassified-pair bucket holding 145 trillion dollars of
    capital-days and a net return of minus 30,000 percent. A constant-product
    pool holds equal value on both legs by construction, so the pool can be
    valued from the leg whose price is externally anchored (a native, staked
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
    df = df[df.type0.isin(ANCHORED) | df.type1.isin(ANCHORED)]
    note("3 at least one externally anchored leg", df)

    df = df[df.max_abs_ret <= np.log(MAX_HOURLY_MOVE)]
    note(f"4 no single hour moving the pool price by more than {MAX_HOURLY_MOVE:.0f}x", df)

    df = df.merge(prices.rename(columns={"token": "token0", "price_usd": "p0",
                                         "price_ok": "ok0"}),
                  on=["day", "token0"], how="left")
    df = df.merge(prices.rename(columns={"token": "token1", "price_usd": "p1",
                                         "price_ok": "ok1"}),
                  on=["day", "token1"], how="left")
    a0 = df.type0.isin(ANCHORED) & df.p0.gt(0) & np.isfinite(df.p0) & df.ok0.fillna(False)
    a1 = df.type1.isin(ANCHORED) & df.p1.gt(0) & np.isfinite(df.p1) & df.ok1.fillna(False)
    df = df[a0 | a1]
    a0, a1 = a0[df.index], a1[df.index]
    note("5 the anchored leg's price passes the sanity test", df)

    if venue == "uniswap_v2":
        df = df[(df.reserve0 > 0) & (df.reserve1 > 0)]
        a0, a1 = a0[df.index], a1[df.index]
        note("6 positive reserves on both legs", df)
        v0, v1 = df.reserve0 * df.p0, df.reserve1 * df.p1
        both = a0 & a1
        df["balance_log_ratio"] = np.where(both, np.log(v0 / v1), np.nan)
        keep = (~both) | (np.abs(df.balance_log_ratio) <= np.log(BALANCE_TOL))
        df = df[keep]
        a0, a1, v0, v1, both = a0[df.index], a1[df.index], v0[df.index], v1[df.index], both[df.index]
        note(f"7 anchored legs agree within {BALANCE_TOL:.0f}x where both are anchored", df)
        df["reconstructed_capital_usd"] = np.where(
            both, v0 + v1, np.where(a0, 2 * v0, 2 * v1)
        )
        df[LOCAL_DEPTH_COLUMN] = df.reconstructed_capital_usd
        df[LVR_SCALE_COLUMN] = df.reconstructed_capital_usd
        keep = capital_reconciliation_mask(
            df.reported_capital_usd,
            df.reconstructed_capital_usd,
            tolerance=CAPITAL_RECONCILIATION_TOL,
        )
        df = df[keep]
        note(
            f"8 reported reserve capital agrees with independently priced reserves "
            f"within {CAPITAL_RECONCILIATION_TOL:.0f}x",
            df,
        )
        df["_current_capital_reconciled"] = 1.0
        prior_reconciled = exact_calendar_lag(
            df,
            value="_current_capital_reconciled",
        )
        df = df[prior_reconciled.eq(1.0)]
        df["capital_validation_status"] = "reconciled_exact_lag"
        note("9 exact-lag capital also passed reserve reconciliation", df)
    else:
        df = df[df.fee_rate.notna()]
        a0, a1 = a0[df.index], a1[df.index]
        note("6 canonical factory pool with a recovered fee tier", df)
        df = df[(df.liquidity > 0) & df.sqrt_price_x96.gt(0)]
        a0, a1 = a0[df.index], a1[df.index]
        note("7 positive reconstructed active liquidity", df)
        dec = pd.read_parquet(PROC / "v2_token_decimals.parquet")
        dmap = dict(zip(dec.token, dec.decimals))
        from ddvc.pricing.v3pools import ANCHOR_DECIMALS
        dmap.update(ANCHOR_DECIMALS)
        d0, d1 = df.token0.map(dmap), df.token1.map(dmap)
        sp = df.sqrt_price_x96 / (2.0 ** 96)
        # Local virtual reserves of active liquidity, in human units. Their value
        # is a curvature/depth scale and is not deposited capital.
        y1 = df.liquidity * sp / (10.0 ** d1)
        x0 = df.liquidity / sp / (10.0 ** d0)
        use1 = a1 & d1.notna()
        use0 = a0 & d0.notna() & ~use1
        df = df[use0 | use1]
        u0, u1 = use0[df.index], use1[df.index]
        note("8 anchored leg with known decimals", df)
        df[LOCAL_DEPTH_COLUMN] = np.where(
            u1, 2 * y1[df.index] * df.p1, 2 * x0[df.index] * df.p0
        )
        df["reconstructed_capital_usd"] = np.nan
        df[LVR_SCALE_COLUMN] = np.nan
        df["balance_log_ratio"] = np.nan

    df = df[
        np.isfinite(df[CAPITAL_COLUMN])
        & df[CAPITAL_COLUMN].between(min_tvl, MAX_POOL_CAPITAL_USD)
        & np.isfinite(df[LOCAL_DEPTH_COLUMN])
        & df[LOCAL_DEPTH_COLUMN].gt(0)
    ]
    note(f"10 lagged deposited capital at least ${min_tvl:,.0f} and positive local depth", df)
    require_capital_denominator(
        df,
        venue=venue,
        purpose="return" if return_inference_ready(venue) else "descriptive",
    )

    df = df.merge(gas, on="day", how="left")
    df["gas_usd"] = ((df.n_mint + df.n_burn) * GAS_UNITS[venue]
                     * df.gas_gwei_median * 1e-9 * df.eth_usd)
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
            "scale_basis": capital_scale_label(venue),
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
        "scale_basis": capital_scale_label(venue),
    }


def main() -> int:
    require_node_d_release(routes=True, market_state=True)
    require_current_artifacts(REQUIRED_PANELS, consumer="rent-incidence estimator")
    OUT.mkdir(parents=True, exist_ok=True)
    prices, gas = _prices(), _gas()
    cpath = PROC / "vehicle_centrality_dense.parquet"
    cent = pd.read_parquet(cpath, columns=["day", "token", "betweenness_volume", "degree"])
    print(f"centrality from {cpath.name}: {cent.day.nunique()} sampled days, "
          f"{cent.token.nunique():,} tokens")

    frames, all_steps, role_tabs, size_tabs = {}, [], [], []
    for venue, path in (("uniswap_v2", "rent_incidence_v2_pool_day.parquet"),):
        p = PROC / path
        if not p.exists():
            print(f"skip {venue}: {p} absent")
            continue
        raw = pd.read_parquet(p)
        df, steps = price_and_screen(raw, venue, prices, gas)
        all_steps += steps
        frames[venue] = df
        print(f"\n=== {venue}: {len(df):,} screened pool-days, "
              f"{df.pool.nunique():,} pools, {df.day.nunique():,} days")
        for s in steps:
            print(f"   {s['screen']:<52} {s['pool_days']:>12,} pool-days  {s['pools']:>8,} pools")
        role_tabs.append(by_role_over_time(df, venue))
        if return_inference_ready(venue):
            size_tabs.append(by_size(df, venue))

    screens = pd.DataFrame(all_steps)
    write_exhibit(screens, OUT / "screens.jsonl", **OUTPUT_PROVENANCE)

    roles = pd.concat(role_tabs, ignore_index=True)
    print("\n=== Rent incidence by pool asset role (annualised) ===")
    fmt = lambda v: f"{v:,.4f}"
    print(roles[(roles.venue == "uniswap_v2") & roles.scope.eq("pooled")][
        ["pool_role", "pools", "pool_days", "scale_days_usd_bn",
         "med_fee_yield_apr", "med_lvr_rate_apr", "mean_gas_rate_apr",
         "share_days_with_lp_event", "med_net_yield_apr", "share_net_positive",
         "cw_net_yield_apr"]].to_string(index=False, float_format=fmt))
    print("\n=== Invariant-validated rent incidence ===")
    print("(v3 is excluded until event-replayed capital and path-integrated LVR pass)")
    print(roles[roles.scope.eq("pooled")][["venue", "pool_role", "pools", "token_pairs", "pool_days",
                 "net_musd", "fee_over_lvr", "fee_over_lvr_plus_gas",
                 "med_pool_day_fee_over_lvr", "share_net_positive",
                 "share_net_positive_pre_gas"]].to_string(index=False, float_format=fmt))
    write_exhibit(roles, OUT / "rent_by_asset_role.jsonl", **OUTPUT_PROVENANCE)

    sizes = pd.concat(size_tabs, ignore_index=True)
    sizes = sizes[sizes.venue == "uniswap_v2"]
    print("\n=== Net yield by capital decile, v2 only while v3 path-integrated LVR is open ===")
    print(sizes.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
    write_exhibit(sizes, OUT / "rent_by_capital_decile.jsonl", **OUTPUT_PROVENANCE)

    # ---------------- centrality curse ----------------
    pms = []
    for venue, df in frames.items():
        pm = pool_months(df, cent, venue)
        pm["venue"] = venue
        pms.append(pm)
    pm = pd.concat(pms, ignore_index=True)
    pm = pm[np.isfinite(pm.log_scale) & np.isfinite(pm.log_rv)]
    pm = pm[~pm.venue.map(return_inference_ready) | np.isfinite(pm.sharpe)]
    write_panel(pm, PROC / "rent_incidence_pool_month.parquet", **OUTPUT_PROVENANCE)

    regs = []
    print("\n=== Does profitability differ by asset role? Tested, not read off a table ===")
    for venue in sorted(pm.venue.unique()):
        sr = pm[pm.venue == venue].copy()
        cnt = sr.pool_role.value_counts()
        keep = [r_ for r_ in cnt.index if cnt[r_] >= 100]
        sr = sr[sr.pool_role.isin(keep)]
        base = sr.pool_role.value_counts().index[0]
        others = [r_ for r_ in keep if r_ != base]
        if not others:
            continue
        D = np.column_stack([(sr.pool_role == r_).astype(float) for r_ in others])
        mo = pd.get_dummies(sr.month, prefix="m", drop_first=True).astype(float).to_numpy()
        outcomes = [(f"{venue} role differences in the chance a pool-month pays", sr.net_positive)]
        if return_inference_ready(venue):
            outcomes = [
                (f"{venue} role differences in risk-adjusted net return", sr.sharpe),
                (f"{venue} role differences in net return APR", sr.net_yield_apr_w),
                *outcomes,
            ]
        for label, yv in outcomes:
            m = np.isfinite(yv.to_numpy())
            X = np.column_stack([np.ones(len(sr)), D, mo])[m]
            cols = ["const"] + [f"role[{r_}]" for r_ in others] + \
                   [f"m{i}" for i in range(mo.shape[1])]
            beta, V, gsz, r = report(f"{label} (base {base})", yv.to_numpy()[m], X, cols,
                                     sr.pool.to_numpy()[m],
                                     focus=set(cols[:1 + len(others)]))
            regs += r
            stat, q, pv = wald(beta, V, list(range(1, 1 + len(others))))
            print(f"  joint Wald, all role effects zero: chi2({q}) = {stat:.2f}, p = {pv:.3f}")
            regs.append({"spec": f"{label} Wald", "term": "joint", "coef": stat,
                         "se": float("nan"), "t": float("nan"), "p": pv,
                         "mde_80pct": float("nan"), "n": int(m.sum()),
                         "clusters": int(gsz)})

    for venue in sorted(pm.venue.unique()):
        s = pm[(pm.venue == venue) & pm.log_c.notna()].copy()
        if len(s) < 200:
            continue
        mo = pd.get_dummies(s.month, prefix="m", drop_first=True).astype(float).to_numpy()
        cl = s.pool.to_numpy()
        print(f"\n### centrality curse, {venue}: {len(s):,} pool-months, "
              f"{s.pool.nunique():,} pools, {s.month.nunique()} months")
        if return_inference_ready(venue):
            X = np.column_stack([np.ones(len(s)), s.log_c, mo])
            cols = ["const", "log_c"] + [f"m{i}" for i in range(mo.shape[1])]
            _, _, _, r = report(f"{venue} (1) risk-adjusted net return, centrality + month FE",
                                s.sharpe.to_numpy(), X, cols, cl, focus={"log_c"})
            regs += r

        if venue == "uniswap_v3":
            X = np.column_stack(
                [np.ones(len(s)), s.log_c, s.log_scale, s.log_local_depth, s.log_rv, mo]
            )
            cols = ["const", "log_c", "log_capital", "log_local_depth", "log_rv"] + [
                f"m{i}" for i in range(mo.shape[1])
            ]
        else:
            X = np.column_stack([np.ones(len(s)), s.log_c, s.log_scale, s.log_rv, mo])
            cols = ["const", "log_c", "log_capital", "log_rv"] + [
                f"m{i}" for i in range(mo.shape[1])
            ]
        outcomes = (
            [
                ("(5) log fee revenue over LVR", s.log_fee_over_lvr),
                ("(6) chance a pool-month pays", s.net_positive),
            ]
            if lvr_inference_ready(venue)
            else []
        )
        if return_inference_ready(venue):
            outcomes = [
                ("(2) risk-adjusted net return, + depth + volatility", s.sharpe),
                ("(3) net return APR, winsorised at 1 and 99", s.net_yield_apr_w),
                ("(4) fee yield APR", s.fee_yield_apr),
                *outcomes,
            ]
        for label, yv in outcomes:
            m = np.isfinite(yv.to_numpy())
            _, _, _, r = report(f"{venue} {label}", yv.to_numpy()[m], X[m], cols, cl[m],
                                focus={"log_c", "log_capital", "log_local_depth", "log_rv"})
            regs += r

        if return_inference_ready(venue):
            X = np.column_stack([np.ones(len(s)), s.log_deg, s.log_scale, s.log_rv, mo])
            cols = ["const", "log_deg", "log_scale", "log_rv"] + [f"m{i}" for i in range(mo.shape[1])]
            _, _, _, r = report(f"{venue} (7) degree instead of betweenness",
                                s.sharpe.to_numpy(), X, cols, cl, focus={"log_deg"})
            regs += r

        # Within pools quoted against the native asset the quote leg is held
        # fixed, so the surviving cross-sectional variation is the hub status of
        # the OTHER leg. This is where the curse is identified, and the role
        # interaction is tested formally on the same subsample rather than by
        # comparing point estimates across subsamples.
        sw = (
            s[s.log_c_other.notna() & s.other_role.notna()].copy()
            if return_inference_ready(venue)
            else s.iloc[0:0]
        )
        if len(sw) >= 200:
            mow = pd.get_dummies(sw.month, prefix="m", drop_first=True).astype(float).to_numpy()
            Xw = np.column_stack([np.ones(len(sw)), sw.log_c_other, sw.log_scale, sw.log_rv, mow])
            cw = ["const", "log_c_other", "log_scale", "log_rv"] + [f"m{i}" for i in range(mow.shape[1])]
            _, _, _, r = report(f"{venue} (7) native-quoted pools, other leg's centrality",
                                sw.sharpe.to_numpy(), Xw, cw, sw.pool.to_numpy(),
                                focus={"log_c_other", "log_scale", "log_rv"})
            regs += r

            cnt = sw.other_role.value_counts()
            keep = [r_ for r_ in cnt.index if cnt[r_] >= 100]
            si = sw[sw.other_role.isin(keep)].copy()
            base = si.other_role.value_counts().index[0]
            others = [r_ for r_ in keep if r_ != base]
            if others:
                D = np.column_stack([(si.other_role == r_).astype(float) for r_ in others])
                moi = pd.get_dummies(si.month, prefix="m", drop_first=True).astype(float).to_numpy()
                Xi = np.column_stack([np.ones(len(si)), si.log_c_other, si.log_scale,
                                      si.log_rv, D,
                                      D * si.log_c_other.to_numpy()[:, None], moi])
                icols = (["const", "log_c_other", "log_scale", "log_rv"]
                         + [f"role[{r_}]" for r_ in others]
                         + [f"log_c_other x role[{r_}]" for r_ in others])
                nfoc = len(icols)
                icols += [f"m{i}" for i in range(Xi.shape[1] - nfoc)]
                beta, V, gsz, r = report(
                    f"{venue} (8) centrality x other-leg role (base {base})",
                    si.sharpe.to_numpy(), Xi, icols, si.pool.to_numpy(),
                    focus=set(icols[:nfoc]))
                regs += r
                idx = list(range(4 + len(others), 4 + 2 * len(others)))
                stat, q, p = wald(beta, V, idx)
                print(f"  joint Wald, all centrality x role interactions zero: "
                      f"chi2({q}) = {stat:.2f}, p = {p:.3f}; "
                      f"{len(si):,} pool-months, {gsz:,} pools")
                regs.append({"spec": f"{venue} (9) interaction Wald", "term": "joint",
                             "coef": stat, "se": float("nan"), "t": float("nan"),
                             "p": p, "mde_80pct": float("nan"), "n": int(len(si)),
                             "clusters": int(gsz)})

    write_exhibit(
        pd.DataFrame(regs),
        OUT / "centrality_curse_regressions.jsonl",
        **OUTPUT_PROVENANCE,
    )

    # ---------------- robustness ----------------
    rob = []
    for venue, df in frames.items():
        d = df[df.gas_usd.notna()]
        for mult, label in ((0.5, "gas units x0.5"), (1.0, "gas units x1"),
                            (2.0, "gas units x2"), (4.0, "gas units x4")):
            net_usd = d.fees_usd - d.lvr_usd - mult * d.gas_usd
            rob.append(robustness_row(venue, label, d, net_usd))
        scale_name = "lagged capital"
        for thr, label in ((1e5, f"{scale_name} >= $100k"),
                           (1e6, f"{scale_name} >= $1m")):
            g = d[d[CAPITAL_COLUMN] >= thr]
            rob.append(robustness_row(venue, label, g, g.net_usd))
        for col, label in (("lvr_usd_4h", "LVR from 4-hour sampled variance"),
                           ("lvr_usd_oc", "LVR from the open-to-close move only")):
            net_usd = d.fees_usd - d[col] - d.gas_usd
            rob.append(robustness_row(venue, label, d, net_usd))
        g = d[d.turnover <= 10]
        rob.append(robustness_row(
            venue,
            f"daily turnover <= 10x {scale_name}",
            g,
            g.net_usd,
        ))
    robf = pd.DataFrame(rob)
    print("\n=== Robustness ===")
    print(robf.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
    write_exhibit(robf, OUT / "robustness.jsonl", **OUTPUT_PROVENANCE)

    summary = {"min_lagged_capital_usd": MIN_TVL, "balance_tol": BALANCE_TOL,
               "capital_reconciliation_tol": CAPITAL_RECONCILIATION_TOL,
               "min_month_days": MIN_MONTH_DAYS, "gas_units": GAS_UNITS,
               "venues": {v: {"pool_days": int(len(f)), "pools": int(f.pool.nunique()),
                              "days": int(f.day.nunique())} for v, f in frames.items()}}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    stamp(OUT / "summary.json", **OUTPUT_PROVENANCE)
    return 0


if __name__ == "__main__":
    with exclusive_job(LOCK, job="rent-incidence estimator"):
        raise SystemExit(main())

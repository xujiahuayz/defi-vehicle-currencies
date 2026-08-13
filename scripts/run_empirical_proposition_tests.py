#!/usr/bin/env python3
"""First-pass empirical tests for the vehicle-currency propositions.

This script intentionally uses the rebuilt canonical derived layer, not ad-hoc
notebook state:

  * data/unified/YYYYMMDD.parquet for route-level bridge use
  * data/metrics/daily_token_metrics.parquet for betweenness / network measures
  * data/exhibits/lp_capital_concentration.parquet for vehicle-linked LP concentration

It writes compact, paper-facing diagnostics under:

  * data/empirical/
  * output/empirical/

The first pass covers the tests that are identified by the current data layer:
bridge-use measurement, route-cost counterfactuals, liquidity formation,
persistence, stress rotation, and V3 architecture around concentrated liquidity.
V4 physical-transfer virtualization still requires receipt / transfer logs and is
reported as a pending input rather than faked from the route table.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]

from ddvc.analysis.dynamics import exact_daily_log_return, value_at_day_offset
from ddvc.calendar import sample_end_iso
from ddvc.analysis.regression import absorb_fixed_effects
from ddvc.metrics import CLEAN_ROUTE_CLASSES, _routes
from ddvc.paths import DATA_DIR, LP_CAPITAL_CONCENTRATION_PANEL, OUTPUT_DIR


VEHICLES = ("WETH", "USDC", "USDT", "DAI", "WBTC")
STABLES = {"USDC", "USDT", "DAI"}
WETH = "WETH"

OUT_DATA = DATA_DIR / "empirical"
OUT = OUTPUT_DIR / "empirical"


@dataclass
class RegressionResult:
    name: str
    n: int
    beta: float
    se: float
    t: float
    p: float


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        tmp = path.with_suffix(".tmp.parquet")
        df.to_parquet(tmp, index=False)
        tmp.replace(path)
    else:
        df.to_pickle(path)

def _ols_y_on_x(
    y: np.ndarray,
    x: np.ndarray,
    name: str,
    *,
    k_absorbed: int = 0,
) -> RegressionResult:
    ok = np.isfinite(y) & np.isfinite(x)
    y = y[ok].astype(float)
    x = x[ok].astype(float)
    n = len(y)
    if n < 3 or np.isclose(x.var(), 0):
        return RegressionResult(name, n, np.nan, np.nan, np.nan, np.nan)
    xmat = np.column_stack([np.ones(n), x])
    beta = np.linalg.lstsq(xmat, y, rcond=None)[0]
    resid = y - xmat @ beta
    dof = n - xmat.shape[1] - k_absorbed
    sigma2 = float((resid @ resid) / dof) if dof > 0 else np.nan
    cov = sigma2 * np.linalg.inv(xmat.T @ xmat)
    se = float(math.sqrt(cov[1, 1]))
    t = float(beta[1] / se) if se > 0 else np.nan
    p = float(2 * stats.t.sf(abs(t), dof)) if dof > 0 and np.isfinite(t) else np.nan
    return RegressionResult(name, n, float(beta[1]), se, t, p)


def _available_unified(start: str | None, end: str | None) -> list[Path]:
    files = sorted((DATA_DIR / "unified").glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].parquet"))
    if start:
        s = start.replace("-", "")
        files = [f for f in files if f.stem >= s]
    if end:
        e = end.replace("-", "")
        files = [f for f in files if f.stem <= e]
    return files


def _weth_price_from_legs(legs: pd.DataFrame) -> float:
    """Median stablecoin-implied WETH price for one day."""
    rows = []
    cols = ["token_in_sym", "token_out_sym", "amount_in", "amount_out", "amount_usd"]
    d = legs[cols].copy()
    a = d[(d["token_in_sym"] == WETH) & (d["token_out_sym"].isin(STABLES))]
    if not a.empty:
        px = a["amount_out"] / a["amount_in"].replace(0, np.nan)
        rows.append(pd.DataFrame({"price": px, "weight": a["amount_usd"]}))
    b = d[(d["token_out_sym"] == WETH) & (d["token_in_sym"].isin(STABLES))]
    if not b.empty:
        px = b["amount_in"] / b["amount_out"].replace(0, np.nan)
        rows.append(pd.DataFrame({"price": px, "weight": b["amount_usd"]}))
    if not rows:
        return np.nan
    p = pd.concat(rows, ignore_index=True)
    p = p[np.isfinite(p["price"]) & (p["price"] > 0) & (p["price"] < 1_000_000)]
    if p.empty:
        return np.nan
    return float(np.average(p["price"], weights=p["weight"].clip(lower=1e-9)))


def _pair_vehicle_for_day(stamp: str) -> pd.DataFrame:
    """Endpoint-pair x vehicle-family bridge volumes for one day."""
    date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    path = DATA_DIR / "unified" / f"{stamp}.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["date", "pair", "vehicle_group", "volume"])
    legs = pd.read_parquet(
        path,
        columns=[
            "tx_hash", "component_id", "route_class", "token_in_sym", "token_out_sym",
            "amount_usd", "tin_role", "tout_role",
        ],
    )
    routes = _routes(legs[legs["route_class"].isin(CLEAN_ROUTE_CLASSES)])
    rows = []
    for r in routes:
        pair = f"{r['src']}->{r['tgt']}"
        vol = float(r["vol"])
        for m in r["inter"]:
            if m == "WETH":
                group = "WETH"
            elif m in STABLES:
                group = "STABLE"
            elif m == "WBTC":
                group = "WBTC"
            else:
                continue
            rows.append((date, pair, group, vol))
    if not rows:
        return pd.DataFrame(columns=["date", "pair", "vehicle_group", "volume"])
    return (
        pd.DataFrame(rows, columns=["date", "pair", "vehicle_group", "volume"])
        .groupby(["date", "pair", "vehicle_group"], as_index=False)["volume"]
        .sum()
    )


def build_bridge_daily(start: str | None, end: str | None, force: bool = False) -> pd.DataFrame:
    """Construct token-day bridge-use measures from reconstructed routes."""
    out_path = OUT_DATA / "bridge_daily.parquet"
    if out_path.exists() and not force:
        return pd.read_parquet(out_path)

    files = _available_unified(start, end)
    rows = []
    for i, path in enumerate(files, 1):
        date = f"{path.stem[:4]}-{path.stem[4:6]}-{path.stem[6:]}"
        legs = pd.read_parquet(
            path,
            columns=[
                "tx_hash", "component_id", "route_class", "token_in_sym", "token_out_sym",
                "amount_usd", "tin_role", "tout_role", "amount_in", "amount_out",
            ],
        )
        routes = _routes(legs[legs["route_class"].isin(CLEAN_ROUTE_CLASSES)])
        indirect = [r for r in routes if r["inter"]]
        denom_vol = sum(float(r["vol"]) for r in indirect)
        denom_count = len(indirect)
        pair_den = len({(r["src"], r["tgt"]) for r in indirect})

        token_vol = {v: 0.0 for v in VEHICLES}
        token_count = {v: 0 for v in VEHICLES}
        token_pairs: dict[str, set[tuple[str, str]]] = {v: set() for v in VEHICLES}
        main_vehicle: dict[tuple[str, str], dict[str, float]] = {}
        for r in indirect:
            pair = (r["src"], r["tgt"])
            for m in r["inter"]:
                if m not in token_vol:
                    continue
                vol = float(r["vol"])
                token_vol[m] += vol
                token_count[m] += 1
                token_pairs[m].add(pair)
                main_vehicle.setdefault(pair, {})
                main_vehicle[pair][m] = main_vehicle[pair].get(m, 0.0) + vol

        main_pair_count = {v: 0 for v in VEHICLES}
        for vols in main_vehicle.values():
            if vols:
                winner = max(vols, key=vols.get)
                main_pair_count[winner] += 1

        weth_price = _weth_price_from_legs(legs)
        for token in VEHICLES:
            rows.append({
                "date": date,
                "token": token,
                "bridge_volume_usd": token_vol[token],
                "bridge_count": token_count[token],
                "BridgeShare": token_vol[token] / denom_vol if denom_vol > 0 else 0.0,
                "BridgeCountShare": token_count[token] / denom_count if denom_count > 0 else 0.0,
                "PairCoverage": len(token_pairs[token]) / pair_den if pair_den > 0 else 0.0,
                "PairMainVehicleShare": main_pair_count[token] / pair_den if pair_den > 0 else 0.0,
                "indirect_route_volume_usd": denom_vol,
                "indirect_route_count": denom_count,
                "indirect_pair_count": pair_den,
                "weth_price": weth_price,
            })
        if i % 100 == 0 or i == len(files):
            print(f"  bridge daily [{i}/{len(files)}] {date}", flush=True)

    df = pd.DataFrame(rows)
    _write(df, out_path)
    return df


def load_network_metrics() -> pd.DataFrame:
    path = DATA_DIR / "metrics" / "daily_token_metrics.parquet"
    columns = set(pq.read_schema(path).names)
    share_column = "VolShare" if "VolShare" in columns else "VShare"
    df = pd.read_parquet(
        path,
        columns=["date", "token_address", share_column, "BetwCent", "BetwCent_V"],
    )
    return df.rename(columns={"token_address": "token", share_column: "VolShare"})


def load_lp() -> pd.DataFrame:
    path = LP_CAPITAL_CONCENTRATION_PANEL
    df = pd.read_parquet(path)
    return df.rename(columns={"token_symbol": "token"})


def summarize_bridge(bridge: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    m = bridge.merge(metrics, on=["date", "token"], how="left")
    m["year"] = pd.to_datetime(m["date"]).dt.year
    summary = (
        m.groupby(["year", "token"], as_index=False)
        .agg(
            BridgeShare=("BridgeShare", "mean"),
            BetwCent_V=("BetwCent_V", "mean"),
            VolShare=("VolShare", "mean"),
            PairCoverage=("PairCoverage", "mean"),
            PairMainVehicleShare=("PairMainVehicleShare", "mean"),
        )
        .sort_values(["year", "BridgeShare"], ascending=[True, False])
    )
    _write(summary, OUT / "bridge_measure_summary_by_year.pkl")
    return summary


def liquidity_formation_tests(bridge: pd.DataFrame, lp: pd.DataFrame) -> pd.DataFrame:
    d = bridge[["date", "token", "BridgeShare"]].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["token", "date"])
    d["BridgeShare_fwd7"] = value_at_day_offset(d, "BridgeShare", 7)

    l = lp[["date", "token", "lp_capital_share", "total_lp_capital_usd"]].copy()
    l["date"] = pd.to_datetime(l["date"])
    x = d.merge(l, on=["date", "token"], how="inner").dropna()

    rows = []
    rows.append(_ols_y_on_x(
        x["BridgeShare_fwd7"].to_numpy(),
        x["lp_capital_share"].to_numpy(),
        "P2 raw: VehicleShare on lagged LP concentration (7 days)",
    ).__dict__)

    # Within-token version: asks whether a token's own liquidity concentration
    # being above its normal level predicts its later bridge use.
    y = absorb_fixed_effects(x["BridgeShare_fwd7"], x["token"])
    z = absorb_fixed_effects(x["lp_capital_share"], x["token"])
    rows.append(_ols_y_on_x(
        y.to_numpy(),
        z.to_numpy(),
        "P2 within-token: VehicleShare on lagged LP concentration (7 days)",
        k_absorbed=max(int(x["token"].nunique()) - 1, 0),
    ).__dict__)

    out = pd.DataFrame(rows)
    _write(out, OUT / "liquidity_formation_tests.pkl")
    return out


def persistence_tests(bridge: pd.DataFrame) -> pd.DataFrame:
    d = bridge[["date", "token", "BridgeShare"]].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["token", "date"])
    d["lag1"] = value_at_day_offset(d, "BridgeShare", -1)
    d = d.dropna()
    rows = []
    for tok, g in d.groupby("token"):
        rows.append(_ols_y_on_x(g["BridgeShare"].to_numpy(), g["lag1"].to_numpy(), f"P2 stickiness AR(1): {tok}").__dict__)
    out = pd.DataFrame(rows)
    _write(out, OUT / "bridge_stickiness_tests.pkl")
    return out


def stress_tests(bridge: pd.DataFrame) -> pd.DataFrame:
    d = bridge.copy()
    d["date"] = pd.to_datetime(d["date"])
    px = (
        d[["date", "weth_price"]]
        .dropna()
        .drop_duplicates("date")
        .sort_values("date")
    )
    px["weth_ret"] = exact_daily_log_return(px, "weth_price")
    px["downside_stress"] = (-px["weth_ret"]).clip(lower=0)
    z = d.merge(px[["date", "downside_stress"]], on="date", how="left").dropna()

    rows = []
    for tok in ("WETH", "USDC", "USDT", "DAI", "WBTC"):
        g = z[z["token"] == tok]
        rows.append(_ols_y_on_x(g["BridgeShare"].to_numpy(), g["downside_stress"].to_numpy(), f"P3 stress: {tok} BridgeShare").__dict__)
    stable = z[z["token"].isin(["USDC", "USDT"])].groupby("date", as_index=False).agg(
        BridgeShare=("BridgeShare", "sum"),
        downside_stress=("downside_stress", "first"),
    )
    rows.append(_ols_y_on_x(stable["BridgeShare"].to_numpy(), stable["downside_stress"].to_numpy(), "P3 stress: USDC+USDT BridgeShare").__dict__)
    out = pd.DataFrame(rows)
    _write(out, OUT / "stress_rotation_tests.pkl")
    return out


def common_support_stress_tests(
    bridge: pd.DataFrame,
    *,
    force: bool = False,
    n_events: int = 30,
    baseline_days: int = 14,
) -> pd.DataFrame:
    """Event-level WETH-vs-stable route rotation inside common endpoint pairs.

    For each large WETH downside day, compare the pair-level WETH-minus-stable
    bridge share on the event day with the same pair's average gap over the prior
    baseline window. This is a daily common-support version of the high-frequency
    design: endpoint-pair composition is held fixed by differencing within pair.
    """
    out_path = OUT_DATA / "stress_common_support_daily.parquet"
    if out_path.exists() and not force:
        out = pd.read_parquet(out_path)
        _write_common_support_outputs(out)
        return out

    px = (
        bridge[["date", "weth_price"]]
        .dropna()
        .drop_duplicates("date")
        .sort_values("date")
        .copy()
    )
    px["date"] = pd.to_datetime(px["date"])
    px["weth_ret"] = exact_daily_log_return(px, "weth_price")
    # Same-day on-chain price can be noisy in very early/thin days; discard
    # impossible daily moves rather than letting them define stress events.
    px.loc[px["weth_ret"].abs() > 0.5, "weth_ret"] = np.nan
    px["downside_stress"] = (-px["weth_ret"]).clip(lower=0)
    events = (
        px[px["downside_stress"] >= 0.08]
        .nlargest(n_events, "downside_stress")
        .sort_values("date")
        [["date", "downside_stress"]]
    )

    needed: set[str] = set()
    for d in events["date"]:
        for b in range(1, baseline_days + 1):
            needed.add((d - pd.Timedelta(days=b)).strftime("%Y%m%d"))
        needed.add(d.strftime("%Y%m%d"))

    frames = []
    for i, stamp in enumerate(sorted(needed), 1):
        day = _pair_vehicle_for_day(stamp)
        if not day.empty:
            frames.append(day)
        if i % 50 == 0 or i == len(needed):
            print(f"  common-support stress days [{i}/{len(needed)}]", flush=True)
    if not frames:
        out = pd.DataFrame()
        _write(out, out_path)
        return out

    panel = pd.concat(frames, ignore_index=True)
    wide = panel.pivot_table(
        index=["date", "pair"],
        columns="vehicle_group",
        values="volume",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    for c in ("WETH", "STABLE", "WBTC"):
        if c not in wide:
            wide[c] = 0.0
    wide["weth_stable_total"] = wide["WETH"] + wide["STABLE"]
    wide = wide[wide["weth_stable_total"] > 0].copy()
    wide["weth_minus_stable_share"] = (wide["WETH"] - wide["STABLE"]) / wide["weth_stable_total"]
    wide["date"] = pd.to_datetime(wide["date"])

    rows = []
    for ev in events.itertuples(index=False):
        d = pd.Timestamp(ev.date)
        event = wide[wide["date"].eq(d)][["pair", "weth_minus_stable_share", "weth_stable_total"]]
        base = wide[(wide["date"] >= d - pd.Timedelta(days=baseline_days)) & (wide["date"] < d)]
        if event.empty or base.empty:
            continue
        base_pair = (
            base.groupby("pair", as_index=False)
            .agg(
                baseline_gap=("weth_minus_stable_share", "mean"),
                baseline_days=("date", "nunique"),
            )
        )
        comp = event.merge(base_pair, on="pair", how="inner")
        comp = comp[comp["baseline_days"] >= max(3, baseline_days // 3)]
        if comp.empty:
            continue
        comp["effect"] = comp["weth_minus_stable_share"] - comp["baseline_gap"]
        w = comp["weth_stable_total"].clip(lower=1e-9)
        rows.append({
            "event_date": d.strftime("%Y-%m-%d"),
            "downside_stress": float(ev.downside_stress),
            "n_pairs": int(len(comp)),
            "weighted_effect": float(np.average(comp["effect"], weights=w)),
            "mean_effect": float(comp["effect"].mean()),
            "baseline_days": baseline_days,
        })
    out = pd.DataFrame(rows)
    _write(out, out_path)
    _write_common_support_outputs(out)
    return out


def _write_common_support_outputs(out: pd.DataFrame) -> None:
    if out.empty:
        return
    effect = out["weighted_effect"].to_numpy(dtype=float)
    t, p = stats.ttest_1samp(effect, 0.0)
    pd.DataFrame([{
        "name": "P3 common-support event effect",
        "n": int(len(effect)),
        "beta": float(np.mean(effect)),
        "se": float(stats.sem(effect)),
        "t": float(t),
        "p": float(p),
    }]).to_pickle(OUT / "stress_common_support_summary.pkl")
    out.to_pickle(OUT / "stress_common_support_events.pkl")

def v3_architecture_tests(bridge: pd.DataFrame) -> pd.DataFrame:
    d = bridge.copy()
    d["date"] = pd.to_datetime(d["date"])
    # V3 launch, plus a conservative one-year post window because V3 liquidity
    # migration is gradual rather than one block in the full market.
    event = pd.Timestamp("2021-05-05")
    x = d[(d["date"] >= event - pd.Timedelta(days=365)) & (d["date"] <= event + pd.Timedelta(days=365))]
    x = x[x["token"].isin(VEHICLES)].copy()
    x["post_v3"] = (x["date"] >= event).astype(float)
    rows = []
    for tok, g in x.groupby("token"):
        rows.append(_ols_y_on_x(g["BridgeShare"].to_numpy(), g["post_v3"].to_numpy(), f"P4a V3 post: {tok} BridgeShare").__dict__)
    out = pd.DataFrame(rows)
    _write(out, OUT / "v3_architecture_tests.pkl")
    return out


def make_figures(bridge: pd.DataFrame, lp: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)
    b = bridge.copy()
    b["date"] = pd.to_datetime(b["date"])
    fig, ax = plt.subplots(figsize=(10, 5))
    for tok in VEHICLES:
        g = b[b["token"] == tok].sort_values("date")
        ax.plot(g["date"], g["BridgeShare"], label=tok, linewidth=1.2)
    ax.set_title("Bridge share by vehicle token")
    ax.set_ylabel("Share of indirect route volume")
    ax.set_xlabel("Date")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.legend(ncol=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "bridge_share_timeseries.pdf")
    plt.close(fig)

    l = lp[lp["token"].isin(VEHICLES)].copy()
    l["date"] = pd.to_datetime(l["date"])
    fig, ax = plt.subplots(figsize=(10, 5))
    for tok in VEHICLES:
        g = l[l["token"] == tok].sort_values("date")
        ax.plot(g["date"], g["lp_capital_share"], label=tok, linewidth=1.2)
    ax.set_title("LP concentration by vehicle-linked base asset")
    ax.set_ylabel("Share of V3 LP liquidity")
    ax.set_xlabel("Date")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.legend(ncol=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "lp_concentration_vehicle_timeseries.pdf")
    plt.close(fig)


def write_memo(
    summary: pd.DataFrame,
    formation: pd.DataFrame,
    persistence: pd.DataFrame,
    stress: pd.DataFrame,
    v3: pd.DataFrame,
) -> None:
    latest_year = int(summary["year"].max())
    latest = summary[summary["year"] == latest_year].sort_values("BridgeShare", ascending=False).head(5)
    route_cost_path = OUT / "route_cost_panel_v2_summary.pkl"
    route_cost = pd.read_pickle(route_cost_path) if route_cost_path.exists() else pd.DataFrame()

    def fmt_table(df: pd.DataFrame, cols: list[str]) -> str:
        """Small markdown table writer without pandas' optional tabulate dep."""
        view = df[cols].copy()
        for c in view.columns:
            if pd.api.types.is_float_dtype(view[c]):
                view[c] = view[c].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
        header = "| " + " | ".join(cols) + " |"
        sep = "| " + " | ".join(["---"] * len(cols)) + " |"
        rows = [
            "| " + " | ".join(str(v) for v in row) + " |"
            for row in view.itertuples(index=False, name=None)
        ]
        return "\n".join([header, sep, *rows])

    v4_text = fmt_v4_settlement()
    text = f"""# First-pass empirical proposition tests

Generated from the rebuilt DVC data layer through {sample_end_iso()}.

## Measurement

The paper-facing bridge-use measure is `BridgeShare`: for token k on day t, the
USD route volume of indirect routes in which k is an intermediate token divided
by total USD volume of all indirect routes. This is distinct from `VolShare`, which
is total directed token volume and therefore mixes endpoint demand with bridge
use.

Top bridge tokens in {latest_year}:

{fmt_table(latest, ["token", "BridgeShare", "BetwCent_V", "VolShare", "PairCoverage"])}

## Proposition checks

### P1. Direct cost advantage

{fmt_route_cost(route_cost)}

### P2. Liquidity formation and stickiness

These are first-pass association tests, not the final causal liquidity design.
The LP measure is now restricted to pools with a known vehicle candidate on one
side, with bad pool-level TVL outliers removed. The final table should add
date fixed effects, near-price executable liquidity, and LP repositioning.

{fmt_table(formation, ["name", "n", "beta", "se", "t", "p"])}

{fmt_table(persistence, ["name", "n", "beta", "se", "t", "p"])}

### P3. Stress rotation

Stress is measured as the positive part of the daily negative log return of WETH,
using same-day stablecoin-implied WETH prices from swap legs.
This aggregate screen is retained only as a diagnostic; the paper-facing design
is the common-support event check below.

{fmt_table(stress, ["name", "n", "beta", "se", "t", "p"])}

### P4a. Concentrated-liquidity architecture

This first pass is an event-window mean-shift around the Uniswap V3 launch. It is
not yet the final design; the final table should use pair-level direct-route
feasibility and cost measures.

{fmt_table(v3, ["name", "n", "beta", "se", "t", "p"])}

### P4b. V4 settlement implementation

{v4_text}
"""
    path = OUT / "empirical_first_pass.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fmt_route_cost(df: pd.DataFrame) -> str:
    if df.empty:
        return (
            "Not yet run in this empirical pass. Run `./scripts/run scripts/run_route_cost_panel.py` "
            "to build the direct-versus-vehicle route-cost counterfactual panel."
        )
    keep = df[df["vehicle"].eq("WETH")][
        [
            "vehicle", "trade_size_usd", "both_available_rows",
            "vehicle_beats_direct_share", "direct_cost_advantage_median",
            "t_winsor_mean", "p_winsor_mean", "no_direct_vehicle_available_rows",
        ]
    ].copy()
    return (
        "DVC counterfactual using Uniswap V2/SushiSwap V2 constant-product "
        "reserves plus Uniswap V3 exact tick-net quotes reconstructed from raw "
        "mints, burns, and swap-state cutoffs. This is now the P1 route-cost "
        "panel for V2-style pools plus exact-crossing V3. Remaining extensions "
        "are Curve/Balancer/Fluid executable-depth quotes and transaction-time "
        "rather than daily noon/EOD state cutoffs.\n\n" + fmt_table_static(keep)
    )


def fmt_v4_settlement() -> str:
    paired_path = OUT / "v4_settlement_paired.pkl"
    dex_path = OUT / "v4_settlement_dex_summary.pkl"
    if not paired_path.exists() or not dex_path.exists():
        return (
            "Not yet run in this empirical pass. Run "
            "`./scripts/run scripts/run_v4_settlement_identification.py` to match V3/V4 "
            "route units and test ERC-20 transfer incidence from receipts."
        )
    paired = pd.read_pickle(paired_path)
    dex = pd.read_pickle(dex_path)
    if paired.empty:
        return "V4 settlement output exists but is empty."
    p = paired.iloc[0]
    return (
        "DVC receipt-level matched design: coherent multi-hop Uniswap V3 and V4 "
        "route units are matched by week, endpoint pair, and intermediate vehicle "
        "token. The outcome is whether the receipt contains an ERC-20 Transfer log "
        "for the intermediate token. V4 reduces physical intermediary-token "
        f"transfer incidence from {p.v3_mean:.1%} to {p.v4_mean:.1%}, a "
        f"{100 * p['diff']:.1f} pp difference (t={p.t:.2f}, "
        f"{'p<0.001' if p.p < 0.001 else f'p={p.p:.3f}'}). This supports the "
        "architecture proposition, but the right interpretation is virtualization "
        "of settlement, not elimination of vehicle routing.\n\n"
        + fmt_table_static(dex)
    )


def fmt_table_static(df: pd.DataFrame) -> str:
    view = df.copy()
    for c in view.columns:
        if pd.api.types.is_float_dtype(view[c]):
            if c.startswith("p_"):
                view[c] = view[c].map(lambda x: "" if pd.isna(x) else ("<0.001" if x < 0.001 else f"{x:.3f}"))
            else:
                view[c] = view[c].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
    cols = list(view.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = [
        "| " + " | ".join(str(v) for v in row) + " |"
        for row in view.itertuples(index=False, name=None)
    ]
    return "\n".join([header, sep, *rows])


def main() -> None:
    ap = argparse.ArgumentParser(description="Run first-pass DVC empirical proposition tests.")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD inclusive start")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD inclusive end")
    ap.add_argument("--force-bridge", action="store_true", help="rebuild bridge_daily.parquet")
    args = ap.parse_args()

    bridge = build_bridge_daily(args.start, args.end, force=args.force_bridge)
    metrics = load_network_metrics()
    lp = load_lp()

    summary = summarize_bridge(bridge, metrics)
    formation = liquidity_formation_tests(bridge, lp)
    persistence = persistence_tests(bridge)
    stress = stress_tests(bridge)
    common_stress = common_support_stress_tests(bridge)
    v3 = v3_architecture_tests(bridge)
    make_figures(bridge, lp)
    write_memo(summary, formation, persistence, stress, v3)
    if not common_stress.empty:
        with (OUT / "empirical_first_pass.md").open("a", encoding="utf-8") as fh:
            fh.write("\n## P3 Common-Support Stress Event Check\n\n")
            fh.write(
                "Daily event-level common-support design. For each large WETH downside "
                "day, compares WETH-minus-stable bridge share with the same endpoint "
                "pairs' prior 14-day baseline.\n\n"
            )
            fh.write(fmt_common_support(common_stress))
            fh.write("\n")

    print(f"wrote empirical outputs -> {OUT}", flush=True)


def fmt_common_support(df: pd.DataFrame) -> str:
    if df.empty:
        return "No common-support stress events produced.\n"
    effect = df["weighted_effect"].to_numpy()
    t, p = stats.ttest_1samp(effect, 0.0)
    lines = [
        f"- Events: {len(df)}",
        f"- Mean weighted effect: {effect.mean():.4f}",
        f"- t-stat: {float(t):.2f}",
        f"- p-value: {float(p):.4f}",
        "",
        "| event_date | downside_stress | n_pairs | weighted_effect |",
        "| --- | --- | --- | --- |",
    ]
    for r in df.sort_values("downside_stress", ascending=False).head(10).itertuples(index=False):
        lines.append(
            f"| {r.event_date} | {r.downside_stress:.4f} | {int(r.n_pairs)} | {r.weighted_effect:.4f} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()

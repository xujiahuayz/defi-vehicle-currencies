#!/usr/bin/env python3
"""First-pass empirical tests for the vehicle-currency propositions.

This script intentionally uses the rebuilt canonical derived layer, not ad-hoc
notebook state:

  * data/unified/YYYYMMDD.parquet for route-level bridge use
  * data/metrics/daily_token_metrics.parquet for betweenness / network measures
  * data/exhibits/lp_concentration.parquet for vehicle-linked LP concentration

It writes compact, paper-facing diagnostics under:

  * data/empirical/
  * output/empirical/

The first pass covers the tests that are identified by the current data layer:
bridge-use measurement, liquidity formation, persistence, stress rotation, and
V3 architecture around concentrated liquidity. Route-cost counterfactuals and
V4 physical-transfer virtualization require extra quoter / receipt layers and
are reported as pending inputs rather than faked from the route table.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ddvc.metrics import CLEAN_ROUTE_CLASSES, _routes  # noqa: E402
from ddvc.paths import DATA_DIR, OUTPUT_DIR  # noqa: E402


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
        df.to_csv(path, index=False)


def _ols_y_on_x(y: np.ndarray, x: np.ndarray, name: str) -> RegressionResult:
    ok = np.isfinite(y) & np.isfinite(x)
    y = y[ok].astype(float)
    x = x[ok].astype(float)
    n = len(y)
    if n < 3 or np.isclose(x.var(), 0):
        return RegressionResult(name, n, np.nan, np.nan, np.nan, np.nan)
    xmat = np.column_stack([np.ones(n), x])
    beta = np.linalg.lstsq(xmat, y, rcond=None)[0]
    resid = y - xmat @ beta
    dof = n - xmat.shape[1]
    sigma2 = float((resid @ resid) / dof) if dof > 0 else np.nan
    cov = sigma2 * np.linalg.inv(xmat.T @ xmat)
    se = float(math.sqrt(cov[1, 1]))
    t = float(beta[1] / se) if se > 0 else np.nan
    p = float(2 * stats.t.sf(abs(t), dof)) if dof > 0 and np.isfinite(t) else np.nan
    return RegressionResult(name, n, float(beta[1]), se, t, p)


def _demean(values: pd.Series, by: pd.Series) -> pd.Series:
    return values - values.groupby(by).transform("mean")


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
    df = pd.read_parquet(path, columns=["date", "token_address", "VShare", "BetwCent", "BetwCent_V"])
    return df.rename(columns={"token_address": "token"})


def load_lp() -> pd.DataFrame:
    path = DATA_DIR / "exhibits" / "lp_concentration.parquet"
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
            VShare=("VShare", "mean"),
            PairCoverage=("PairCoverage", "mean"),
            PairMainVehicleShare=("PairMainVehicleShare", "mean"),
        )
        .sort_values(["year", "BridgeShare"], ascending=[True, False])
    )
    _write(summary, OUT / "bridge_measure_summary_by_year.csv")
    return summary


def liquidity_formation_tests(bridge: pd.DataFrame, lp: pd.DataFrame) -> pd.DataFrame:
    d = bridge[["date", "token", "BridgeShare"]].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["token", "date"])
    d["BridgeShare_fwd7"] = d.groupby("token")["BridgeShare"].shift(-7)

    l = lp[["date", "token", "lp_concentration_share", "total_lp_liquidity_usd"]].copy()
    l["date"] = pd.to_datetime(l["date"])
    x = d.merge(l, on=["date", "token"], how="inner").dropna()

    rows = []
    rows.append(_ols_y_on_x(
        x["BridgeShare_fwd7"].to_numpy(),
        x["lp_concentration_share"].to_numpy(),
        "P2 raw: future BridgeShare on LP concentration",
    ).__dict__)

    # Within-token version: asks whether a token's own liquidity concentration
    # being above its normal level predicts its later bridge use.
    y = _demean(x["BridgeShare_fwd7"], x["token"])
    z = _demean(x["lp_concentration_share"], x["token"])
    rows.append(_ols_y_on_x(
        y.to_numpy(),
        z.to_numpy(),
        "P2 within-token: future BridgeShare on LP concentration",
    ).__dict__)

    out = pd.DataFrame(rows)
    _write(out, OUT / "liquidity_formation_tests.csv")
    return out


def persistence_tests(bridge: pd.DataFrame) -> pd.DataFrame:
    d = bridge[["date", "token", "BridgeShare"]].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["token", "date"])
    d["lag1"] = d.groupby("token")["BridgeShare"].shift(1)
    d = d.dropna()
    rows = []
    for tok, g in d.groupby("token"):
        rows.append(_ols_y_on_x(g["BridgeShare"].to_numpy(), g["lag1"].to_numpy(), f"P2 stickiness AR(1): {tok}").__dict__)
    out = pd.DataFrame(rows)
    _write(out, OUT / "bridge_stickiness_tests.csv")
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
    px["weth_ret"] = np.log(px["weth_price"]).diff()
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
    _write(out, OUT / "stress_rotation_tests.csv")
    return out


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
    _write(out, OUT / "v3_architecture_tests.csv")
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
        ax.plot(g["date"], g["lp_concentration_share"], label=tok, linewidth=1.2)
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

    text = f"""# First-pass empirical proposition tests

Generated from the rebuilt DVC data layer through 2026-06-30.

## Measurement

The paper-facing bridge-use measure is `BridgeShare`: for token k on day t, the
USD route volume of indirect routes in which k is an intermediate token divided
by total USD volume of all indirect routes. This is distinct from `VShare`, which
is total directed token volume and therefore mixes endpoint demand with bridge
use.

Top bridge tokens in {latest_year}:

{fmt_table(latest, ["token", "BridgeShare", "BetwCent_V", "VShare", "PairCoverage"])}

## Proposition checks

### P2. Liquidity formation and stickiness

{fmt_table(formation, ["name", "n", "beta", "se", "t", "p"])}

{fmt_table(persistence, ["name", "n", "beta", "se", "t", "p"])}

### P3. Stress rotation

Stress is measured as the positive part of the daily negative log return of WETH,
using same-day stablecoin-implied WETH prices from swap legs.

{fmt_table(stress, ["name", "n", "beta", "se", "t", "p"])}

### P4a. Concentrated-liquidity architecture

This first pass is an event-window mean-shift around the Uniswap V3 launch. It is
not yet the final design; the final table should use pair-level direct-route
feasibility and cost measures.

{fmt_table(v3, ["name", "n", "beta", "se", "t", "p"])}

## Not yet identified by this script

P1 route-cost advantage needs the quoter / executable-depth layer: direct route
cost versus best vehicle route cost by endpoint pair and trade-size bucket.

P4b V4 virtualization needs transaction receipt / ERC-20 transfer logs: route
vehicle use can be read from the route table, but physical settlement incidence
requires transfer logs to distinguish virtual from physically moved vehicles.
"""
    path = OUT / "empirical_first_pass.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    v3 = v3_architecture_tests(bridge)
    make_figures(bridge, lp)
    write_memo(summary, formation, persistence, stress, v3)

    print(f"wrote empirical outputs -> {OUT}", flush=True)


if __name__ == "__main__":
    main()

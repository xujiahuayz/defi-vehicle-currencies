#!/usr/bin/env python3
"""Core empirical registry and gap-closing tests for the DVC RQs.

Outputs:
  data/empirical/core_token_day_panel.parquet
  data/empirical/pool_vehicle_liquidity_daily.parquet
  data/empirical/pair_vehicle_actual_daily.parquet
  output/empirical/core_variable_construction.csv
  output/empirical/core_panel_regressions.csv
  output/empirical/persistence_displacement_thresholds.csv
  output/empirical/stress_event_time.csv
  output/empirical/common_liquidity_pool_tests.csv
  output/empirical/core_rq_evidence_registry.md
  output/core_empirical_rq_results.md
  output/tables/table_m08_variable_construction.{csv,tex}
  output/tables/table_m09_core_panel_regressions.{csv,tex}
  output/tables/table_m10_persistence_thresholds.{csv,tex}
  output/tables/table_m11_stress_event_time.{csv,tex}
  output/tables/table_m12_common_liquidity.{csv,tex}
  output/tables/table_m13_actual_route_choice.{csv,tex}
  output/tables/table_m14_lp_allocation_feedback.{csv,tex}
  output/tables/table_m15_pair_challenger_displacement.{csv,tex}
  output/tables/table_m16_v3_dose_response.{csv,tex}
  output/tables/table_m17_v4_route_use_persistence.{csv,tex}
  output/tables/table_m18_common_liquidity_heterogeneity.{csv,tex}
"""
from __future__ import annotations

from collections import defaultdict
import gzip
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_paper_exhibits import _int, _num, _p, _write_table  # noqa: E402


VEHICLES = ["WETH", "USDC", "USDT", "DAI", "WBTC"]
STABLES = {"USDC", "USDT", "DAI"}
VEHICLE_ADDRESSES = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
}
RAW_DAILY_SOURCES = {
    "uniswap_v3": DATA / "raw" / "thegraph" / "uniswap_v3",
    "uniswap_v2": DATA / "raw" / "thegraph" / "uniswap_v2",
    "sushiswap_v2": DATA / "raw" / "thegraph" / "sushiswap_v2",
}
MAX_POOL_LIQUIDITY_USD = 10_000_000_000


def _ensure_dirs() -> None:
    (DATA / "empirical").mkdir(parents=True, exist_ok=True)
    EMP.mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(parents=True, exist_ok=True)


def _twoway_demean(s: pd.Series, a: pd.Series, b: pd.Series) -> pd.Series:
    return s - s.groupby(a).transform("mean") - s.groupby(b).transform("mean") + s.mean()


def _oneway_demean(s: pd.Series, a: pd.Series) -> pd.Series:
    return s - s.groupby(a).transform("mean")


def _cluster_ols(y: pd.Series, xvars: pd.DataFrame, cluster: pd.Series) -> tuple[int, int, dict[str, float]]:
    d = pd.concat([y.rename("y"), xvars, cluster.rename("cluster")], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    n = len(d)
    c = d["cluster"].nunique()
    names = list(xvars.columns)
    empty = {f"{name}_{stat}": math.nan for name in names for stat in ["beta", "se", "t", "p"]}
    if n < 30 or c < 2:
        return n, c, empty
    x = np.column_stack([np.ones(n)] + [d[name].to_numpy(float) for name in names])
    yy = d["y"].to_numpy(float)
    if np.linalg.matrix_rank(x) < x.shape[1]:
        return n, c, empty
    beta = np.linalg.lstsq(x, yy, rcond=None)[0]
    resid = yy - x @ beta
    bread = np.linalg.inv(x.T @ x)
    meat = np.zeros((x.shape[1], x.shape[1]))
    for _, idx in d.groupby("cluster").indices.items():
        score = x[idx].T @ resid[idx][:, None]
        meat += score @ score.T
    finite = (c / (c - 1)) * ((n - 1) / max(n - x.shape[1], 1))
    cov = finite * bread @ meat @ bread
    out: dict[str, float] = {}
    for j, name in enumerate(names, start=1):
        se = float(math.sqrt(max(cov[j, j], 0.0)))
        t = float(beta[j] / se) if se > 0 else math.nan
        p = float(2 * stats.t.sf(abs(t), c - 1)) if np.isfinite(t) else math.nan
        out[f"{name}_beta"] = float(beta[j])
        out[f"{name}_se"] = se
        out[f"{name}_t"] = t
        out[f"{name}_p"] = p
    return n, c, out


def variable_construction_table() -> pd.DataFrame:
    rows = [
        {
            "Variable / proxy": "VehicleShare",
            "Level": "vehicle token x day",
            "Construction": "USD volume of indirect routes where token v is an intermediate divided by total indirect-route USD volume that day.",
            "Source": "data/empirical/bridge_daily.parquet",
            "Used for": "RQ1, RQ2, RQ3, RQ4",
        },
        {
            "Variable / proxy": "RouteCostAdvantage",
            "Level": "endpoint pair x vehicle x day x trade size",
            "Construction": "(vehicle-route exact-quote output USD - direct-route exact-quote output USD) / direct-route output USD; reported in bps as 10000 x advantage. Main core panel uses the median bps across endpoint pairs at $10k.",
            "Source": "data/empirical/route_cost_panel_v2.parquet",
            "Used for": "RQ1, RQ3, RQ5",
        },
        {
            "Variable / proxy": "DirectAvailable",
            "Level": "endpoint pair x day x trade size",
            "Construction": "Indicator that the exact-quote engine finds a direct executable route for the endpoint pair at the standard notional.",
            "Source": "data/empirical/route_cost_panel_v2.parquet",
            "Used for": "RQ1, RQ5",
        },
        {
            "Variable / proxy": "VehicleAvailable",
            "Level": "endpoint pair x vehicle x day x trade size",
            "Construction": "Indicator that both legs through candidate vehicle v are exact-quote executable at the standard notional.",
            "Source": "data/empirical/route_cost_panel_v2.parquet",
            "Used for": "RQ1, RQ5",
        },
        {
            "Variable / proxy": "DirectDepth",
            "Level": "endpoint pair x day x trade size",
            "Construction": "Executable direct-route quality proxy: direct output USD divided by trade size. Thin-direct cells are direct-available cells with output below 90% of notional.",
            "Source": "data/empirical/route_cost_panel_v2.parquet",
            "Used for": "RQ1, RQ5",
        },
        {
            "Variable / proxy": "VehicleLinkedLiquidity",
            "Level": "vehicle token x day",
            "Construction": "USD TVL in Uniswap V3 pools whose vehicle-side/base asset is candidate v, after excluding absurd pool TVL outliers.",
            "Source": "data/exhibits/lp_concentration.parquet",
            "Used for": "RQ2, RQ3, RQ6",
        },
        {
            "Variable / proxy": "LPConcentration",
            "Level": "vehicle token x day",
            "Construction": "VehicleLinkedLiquidity divided by total vehicle-candidate linked liquidity across the vehicle set that day.",
            "Source": "data/exhibits/lp_concentration.parquet",
            "Used for": "RQ2, RQ3",
        },
        {
            "Variable / proxy": "LPRepositioning",
            "Level": "vehicle token x day",
            "Construction": "Daily gross/net V3 mint-burn liquidity movement assigned to candidate vehicle pools; near-price variants use the active/near tick state where available.",
            "Source": "data/empirical/_lp_repositioning_day_cache/",
            "Used for": "RQ2, RQ5",
        },
        {
            "Variable / proxy": "Stress",
            "Level": "day or event day",
            "Construction": "Positive part of negative WETH log return from stablecoin-implied WETH prices; event tables use selected large downside days.",
            "Source": "bridge_daily WETH price; output/tables/table_r21_stress_event_definition.csv",
            "Used for": "RQ4",
        },
        {
            "Variable / proxy": "SettlementTransferIncidence",
            "Level": "matched route unit",
            "Construction": "Indicator that the transaction receipt contains at least one ERC-20 Transfer log matching the intermediate vehicle token.",
            "Source": "data/empirical/v4_settlement_transfer_detail.csv",
            "Used for": "RQ6",
        },
        {
            "Variable / proxy": "NettingExposure",
            "Level": "vehicle token",
            "Construction": "One minus V4 SettlementTransferIncidence for vehicle v in the receipt-audited V4 route-unit sample.",
            "Source": "output/empirical/p4b_netting_exposure_by_vehicle.csv",
            "Used for": "RQ6",
        },
        {
            "Variable / proxy": "VehicleLiquidityFactor",
            "Level": "vehicle token x day",
            "Construction": "Leave-one-out average daily log-liquidity change among other pools linked to the same vehicle; paired with a leave-one-out market liquidity factor.",
            "Source": "constructed from raw daily pool snapshots",
            "Used for": "RQ7",
        },
    ]
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "core_variable_construction.csv", index=False)
    _write_table(
        out,
        "table_m08_variable_construction",
        "Core empirical variables and construction.",
        "tab:variable-construction",
        align="p{0.18\\linewidth}p{0.13\\linewidth}p{0.40\\linewidth}p{0.17\\linewidth}p{0.12\\linewidth}",
        note="This is the variable/proxy registry used before drafting the empirical prose.",
    )
    return out


def route_cost_daily(trade_size: float = 10_000.0) -> pd.DataFrame:
    cols = [
        "date",
        "src",
        "tgt",
        "vehicle_sym",
        "trade_size_usd",
        "direct_available",
        "vehicle_available",
        "direct_output_usd",
        "vehicle_route_advantage",
    ]
    r = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet", columns=cols)
    r = r[r["trade_size_usd"].astype(float).eq(float(trade_size))].copy()
    r["date"] = pd.to_datetime(r["date"])
    r["token"] = r["vehicle_sym"].astype(str)
    r["pair"] = r["src"].astype(str) + "->" + r["tgt"].astype(str)
    r["direct_available"] = r["direct_available"].astype(bool)
    r["vehicle_available"] = r["vehicle_available"].astype(bool)
    r["both_available"] = r["direct_available"] & r["vehicle_available"] & r["vehicle_route_advantage"].notna()
    r["no_direct_vehicle_available"] = (~r["direct_available"]) & r["vehicle_available"]
    r["direct_depth_proxy"] = np.where(r["direct_available"], r["direct_output_usd"].astype(float) / float(trade_size), np.nan)
    r["thin_direct"] = r["direct_available"] & (r["direct_depth_proxy"] < 0.90)
    r["adv_bps"] = 10_000.0 * r["vehicle_route_advantage"].astype(float)
    r["adv_bps_winsor"] = r["adv_bps"].clip(lower=-10_000, upper=10_000)
    grouped = r.groupby(["date", "token"], as_index=False)
    out = grouped.agg(
        quote_rows=("pair", "size"),
        pair_days=("pair", "nunique"),
        direct_available_share=("direct_available", "mean"),
        vehicle_available_share=("vehicle_available", "mean"),
        no_direct_vehicle_available_share=("no_direct_vehicle_available", "mean"),
        both_available_rows=("both_available", "sum"),
        route_cost_advantage_median_bps=("adv_bps", "median"),
        route_cost_advantage_winsor_mean_bps=("adv_bps_winsor", "mean"),
        vehicle_beats_direct_share=("vehicle_route_advantage", lambda x: float((x > 0).mean()) if x.notna().any() else math.nan),
        direct_depth_median=("direct_depth_proxy", "median"),
        thin_direct_share=("thin_direct", "mean"),
    )
    return out


def core_token_day_panel() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet")
    bridge["date"] = pd.to_datetime(bridge["date"])
    bridge = bridge[bridge["token"].isin(VEHICLES)].copy()
    lp = pd.read_parquet(DATA / "exhibits" / "lp_concentration.parquet").rename(columns={"token_symbol": "token"})
    lp["date"] = pd.to_datetime(lp["date"])
    lp = lp[lp["token"].isin(VEHICLES)].copy()
    rc = route_cost_daily(10_000.0)
    d = bridge.merge(
        lp[["date", "token", "total_lp_liquidity_usd", "lp_concentration_share"]],
        on=["date", "token"],
        how="left",
    ).merge(rc, on=["date", "token"], how="left")
    d = d.sort_values(["token", "date"])
    d["log_vehicle_linked_liquidity"] = np.log1p(d["total_lp_liquidity_usd"])
    d["route_cost_advantage_100bp"] = d["route_cost_advantage_median_bps"] / 100.0
    for h in [1, 7, 14, 30]:
        d[f"future_BridgeShare_t{h}"] = d.groupby("token")["BridgeShare"].shift(-h)
        d[f"future_LPConcentration_t{h}"] = d.groupby("token")["lp_concentration_share"].shift(-h)
        d[f"future_log_liquidity_t{h}"] = d.groupby("token")["log_vehicle_linked_liquidity"].shift(-h)
        d[f"delta_BridgeShare_t{h}"] = d[f"future_BridgeShare_t{h}"] - d["BridgeShare"]
    out_path = DATA / "empirical" / "core_token_day_panel.parquet"
    d.to_parquet(out_path, index=False)
    return d


def core_panel_regressions(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    specs = [
        ("RQ1/RQ2/RQ3", "future_BridgeShare_t7", "future VehicleShare, t+7"),
        ("RQ1/RQ2/RQ3", "future_BridgeShare_t30", "future VehicleShare, t+30"),
        ("RQ2", "future_LPConcentration_t7", "future LPConcentration, t+7"),
        ("RQ2", "future_log_liquidity_t7", "future log VehicleLinkedLiquidity, t+7"),
    ]
    x_names = [
        "BridgeShare",
        "route_cost_advantage_100bp",
        "no_direct_vehicle_available_share",
        "direct_available_share",
        "vehicle_available_share",
        "lp_concentration_share",
    ]
    for rq, y_name, label in specs:
        dd = panel.copy()
        y = _twoway_demean(dd[y_name], dd["token"], dd["date"])
        x = pd.DataFrame({name: _twoway_demean(dd[name], dd["token"], dd["date"]) for name in x_names})
        n, clusters, res = _cluster_ols(y, x, dd["date"])
        for name in x_names:
            rows.append(
                {
                    "RQ": rq,
                    "Outcome": label,
                    "Regressor": name,
                    "N": _int(n),
                    "Date clusters": _int(clusters),
                    "Beta": _num(res[f"{name}_beta"], 4),
                    "SE": _num(res[f"{name}_se"], 4),
                    "t": _num(res[f"{name}_t"], 2),
                    "p": _p(res[f"{name}_p"]),
                    "FE / SE": "token FE + date FE; date-clustered SE",
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "core_panel_regressions.csv", index=False)
    _write_table(
        out,
        "table_m09_core_panel_regressions",
        "Core token-day panel regressions for vehicle formation, liquidity, and persistence.",
        "tab:core-panel-regressions",
        note="All variables are residualized by token and date fixed effects. RouteCostAdvantage is median bps divided by 100, so one unit is 100 bps.",
    )
    return out


def persistence_displacement_thresholds(panel: pd.DataFrame) -> pd.DataFrame:
    d = panel.dropna(subset=["BridgeShare", "route_cost_advantage_median_bps", "future_BridgeShare_t30"]).copy()
    idx = d.groupby("date")["BridgeShare"].idxmax()
    inc = d.loc[idx].copy()
    best_alt = (
        d.loc[~d.index.isin(idx)]
        .groupby("date")["route_cost_advantage_median_bps"]
        .max()
        .rename("best_challenger_advantage_bps")
    )
    inc = inc.merge(best_alt, on="date", how="left")
    inc["challenger_minus_incumbent_bps"] = inc["best_challenger_advantage_bps"] - inc["route_cost_advantage_median_bps"]
    inc["future_share_change_pp"] = 100.0 * (inc["future_BridgeShare_t30"] - inc["BridgeShare"])
    bins = [-np.inf, 0, 25, 100, 250, np.inf]
    labels = ["challenger <= incumbent", "0 to 25 bp", "25 to 100 bp", "100 to 250 bp", ">250 bp"]
    inc["Challenger advantage bin"] = pd.cut(inc["challenger_minus_incumbent_bps"], bins=bins, labels=labels)
    rows = []
    for label, g in inc.groupby("Challenger advantage bin", observed=False):
        y = g["future_share_change_pp"].replace([np.inf, -np.inf], np.nan).dropna()
        if len(y) > 1:
            t, p = stats.ttest_1samp(y.to_numpy(float), 0.0, nan_policy="omit")
        else:
            t, p = math.nan, math.nan
        rows.append(
            {
                "Challenger advantage bin": str(label),
                "Incumbent days": _int(len(y)),
                "Mean challenger edge (bp)": _num(g["challenger_minus_incumbent_bps"].mean(), 1),
                "Median challenger edge (bp)": _num(g["challenger_minus_incumbent_bps"].median(), 1),
                "Mean incumbent share change t+30 (pp)": _num(y.mean(), 2),
                "t": _num(t, 2),
                "p": _p(p),
                "Interpretation": "incumbent displacement threshold screen",
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "persistence_displacement_thresholds.csv", index=False)
    _write_table(
        out,
        "table_m10_persistence_thresholds",
        "Incumbent vehicle displacement by challenger route-cost edge.",
        "tab:persistence-thresholds",
        note="Incumbent is the highest-BridgeShare vehicle on day t. Challenger edge is the best non-incumbent median route-cost advantage minus incumbent median advantage at $10k. Outcome is incumbent BridgeShare change over 30 days.",
    )
    return out


def stress_event_time() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet")
    bridge["date"] = pd.to_datetime(bridge["date"])
    wide = bridge.pivot(index="date", columns="token", values="BridgeShare").sort_index()
    wide["stable_share"] = wide[[c for c in STABLES if c in wide.columns]].sum(axis=1)
    wide["weth_minus_stable"] = wide["WETH"] - wide["stable_share"]
    events = pd.read_csv(OUT / "tables" / "table_r21_stress_event_definition.csv")
    events = events[events["Threshold met"].astype(str).str.lower().eq("yes")].head(20)
    event_dates = pd.to_datetime(events["Event date"]).tolist()
    rows = []
    for event_date in event_dates:
        baseline = wide.loc[(wide.index >= event_date - pd.Timedelta(days=28)) & (wide.index <= event_date - pd.Timedelta(days=1))]
        if baseline.empty:
            continue
        base_vals = baseline[["WETH", "stable_share", "weth_minus_stable"]].mean()
        for tau in range(-14, 31):
            day = event_date + pd.Timedelta(days=tau)
            if day not in wide.index:
                continue
            r = wide.loc[day]
            rows.append(
                {
                    "event_date": event_date.date().isoformat(),
                    "event_time": tau,
                    "weth_change_pp": 100.0 * (r["WETH"] - base_vals["WETH"]),
                    "stable_change_pp": 100.0 * (r["stable_share"] - base_vals["stable_share"]),
                    "gap_change_pp": 100.0 * (r["weth_minus_stable"] - base_vals["weth_minus_stable"]),
                }
            )
    ev = pd.DataFrame(rows)
    summary_rows = []
    windows = [("event day", 0, 0), ("post 1 to 7", 1, 7), ("post 8 to 30", 8, 30), ("pre -14 to -1", -14, -1)]
    for label, lo, hi in windows:
        g = ev[(ev["event_time"] >= lo) & (ev["event_time"] <= hi)].groupby("event_date", as_index=False).agg(
            weth_change_pp=("weth_change_pp", "mean"),
            stable_change_pp=("stable_change_pp", "mean"),
            gap_change_pp=("gap_change_pp", "mean"),
        )
        for outcome in ["weth_change_pp", "stable_change_pp", "gap_change_pp"]:
            y = g[outcome].dropna()
            t, p = stats.ttest_1samp(y.to_numpy(float), 0.0, nan_policy="omit") if len(y) > 1 else (math.nan, math.nan)
            summary_rows.append(
                {
                    "Window": label,
                    "Outcome": outcome.replace("_", " "),
                    "Events": _int(len(y)),
                    "Mean effect (pp)": _num(y.mean(), 2),
                    "t": _num(t, 2),
                    "p": _p(p),
                }
            )
    out = pd.DataFrame(summary_rows)
    ev.to_csv(EMP / "stress_event_time_daily.csv", index=False)
    out.to_csv(EMP / "stress_event_time.csv", index=False)
    _write_table(
        out,
        "table_m11_stress_event_time",
        "Stress rotation event-time summary.",
        "tab:stress-event-time",
        note="Effects are relative to each event's prior 28-day baseline. The table separates same-day rotation from post-event persistence.",
    )
    return out


def _daily_files(source: str) -> list[Path]:
    return sorted(RAW_DAILY_SOURCES[source].glob(f"{source}_daily_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].jsonl.gz"))


def _stamp(path: Path) -> str:
    m = re.search(r"_(\d{8})\.jsonl\.gz$", path.name)
    if not m:
        raise ValueError(f"Cannot parse date stamp: {path}")
    return m.group(1)


def _safe_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return math.nan


def _parse_pool_daily_record(source: str, rec: dict, stamp: str) -> list[dict[str, object]]:
    if source == "uniswap_v3":
        pool = rec.get("pool") or {}
        pool_id = str(pool.get("id", "")).lower()
        token0 = pool.get("token0") or {}
        token1 = pool.get("token1") or {}
        liquidity = _safe_float(rec.get("tvlUSD"))
        volume = _safe_float(rec.get("volumeUSD"))
    else:
        pool_id = str(rec.get("pairAddress") or rec.get("id") or "").lower()
        token0 = rec.get("token0") or {}
        token1 = rec.get("token1") or {}
        liquidity = _safe_float(rec.get("reserveUSD"))
        volume = _safe_float(rec.get("dailyVolumeUSD"))
    if not pool_id or not np.isfinite(liquidity) or liquidity <= 0 or liquidity > MAX_POOL_LIQUIDITY_USD:
        return []
    date_iso = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    sides = []
    for tok in [token0, token1]:
        addr = str(tok.get("id", "")).lower()
        symbol = str(tok.get("symbol", ""))
        if addr in VEHICLE_ADDRESSES:
            sides.append((VEHICLE_ADDRESSES[addr], addr, symbol))
    rows = []
    for vehicle, addr, symbol in sides:
        rows.append(
            {
                "date": date_iso,
                "dex": source,
                "pool_id": pool_id,
                "pool_vehicle_id": f"{source}|{pool_id}|{vehicle}",
                "vehicle": vehicle,
                "vehicle_address": addr,
                "vehicle_symbol_raw": symbol,
                "liquidity_usd": liquidity,
                "volume_usd": volume,
            }
        )
    return rows


def build_pool_vehicle_liquidity(force: bool = False) -> pd.DataFrame:
    out_path = DATA / "empirical" / "pool_vehicle_liquidity_daily.parquet"
    if out_path.exists() and not force:
        return pd.read_parquet(out_path)
    rows: list[dict[str, object]] = []
    for source in RAW_DAILY_SOURCES:
        files = _daily_files(source)
        for i, path in enumerate(files, 1):
            stamp = _stamp(path)
            with gzip.open(path, "rt") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rows.extend(_parse_pool_daily_record(source, rec, stamp))
            if i % 250 == 0 or i == len(files):
                print(f"  pool liquidity [{source}] {i}/{len(files)}", flush=True)
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("No vehicle-linked pool daily rows constructed from raw daily files.")
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["pool_vehicle_id", "date"])
    out.to_parquet(out_path, index=False)
    return out


def common_liquidity_tests(pool: pd.DataFrame) -> pd.DataFrame:
    d = pool.copy()
    d = d[d["vehicle"].isin(VEHICLES)].copy()
    d = d.sort_values(["pool_vehicle_id", "date"])
    d["log_liquidity"] = np.log(d["liquidity_usd"].clip(lower=1.0))
    d["dlog_liquidity"] = d.groupby("pool_vehicle_id")["log_liquidity"].diff()
    counts = d.groupby("pool_vehicle_id")["dlog_liquidity"].transform("count")
    d = d[(counts >= 60) & d["dlog_liquidity"].notna()].copy()
    grp_date = d.groupby("date")["dlog_liquidity"]
    d["market_sum"] = grp_date.transform("sum")
    d["market_n"] = grp_date.transform("count")
    grp_vehicle = d.groupby(["date", "vehicle"])["dlog_liquidity"]
    d["vehicle_sum"] = grp_vehicle.transform("sum")
    d["vehicle_n"] = grp_vehicle.transform("count")
    d["market_factor_loo"] = (d["market_sum"] - d["dlog_liquidity"]) / (d["market_n"] - 1)
    d["vehicle_factor_loo"] = (d["vehicle_sum"] - d["dlog_liquidity"]) / (d["vehicle_n"] - 1)
    d = d[(d["market_n"] >= 25) & (d["vehicle_n"] >= 10)].copy()
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "token", "weth_price"])
    weth = bridge[bridge["token"].eq("WETH")][["date", "weth_price"]].copy()
    weth["date"] = pd.to_datetime(weth["date"])
    weth = weth.sort_values("date")
    weth["downside_stress"] = (-np.log(weth["weth_price"] / weth["weth_price"].shift(1))).clip(lower=0)
    weth["stress_dummy"] = (weth["downside_stress"] >= 0.08).astype(float)
    d = d.merge(weth[["date", "stress_dummy"]], on="date", how="left")
    d["stress_dummy"] = d["stress_dummy"].fillna(0.0)
    d["vehicle_factor_x_stress"] = d["vehicle_factor_loo"] * d["stress_dummy"]
    d["post_v3"] = (d["date"] >= pd.Timestamp("2021-05-05")).astype(float)
    d["vehicle_factor_x_post_v3"] = d["vehicle_factor_loo"] * d["post_v3"]
    d.to_parquet(DATA / "empirical" / "common_liquidity_pool_panel.parquet", index=False)
    rows = []
    specs = [
        ("Full sample", ["market_factor_loo", "vehicle_factor_loo"]),
        ("Stress interaction", ["market_factor_loo", "vehicle_factor_loo", "stress_dummy", "vehicle_factor_x_stress"]),
        ("Post-V3 interaction", ["market_factor_loo", "vehicle_factor_loo", "post_v3", "vehicle_factor_x_post_v3"]),
    ]
    for sample, names in specs:
        dd = d.copy()
        y = _oneway_demean(dd["dlog_liquidity"], dd["pool_vehicle_id"])
        x = pd.DataFrame({name: _oneway_demean(dd[name], dd["pool_vehicle_id"]) for name in names})
        n, clusters, res = _cluster_ols(y, x, dd["date"])
        for name in names:
            rows.append(
                {
                    "Sample / specification": sample,
                    "Regressor": name,
                    "N": _int(n),
                    "Date clusters": _int(clusters),
                    "Pools": _int(dd["pool_vehicle_id"].nunique()),
                    "Beta": _num(res[f"{name}_beta"], 4),
                    "SE": _num(res[f"{name}_se"], 4),
                    "t": _num(res[f"{name}_t"], 2),
                    "p": _p(res[f"{name}_p"]),
                    "FE / SE": "pool-vehicle FE; date-clustered SE",
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "common_liquidity_pool_tests.csv", index=False)
    _write_table(
        out,
        "table_m12_common_liquidity",
        "Vehicle-linked commonality in pool liquidity.",
        "tab:common-liquidity",
        note="Dependent variable is daily log liquidity change in vehicle-linked pools. Market and vehicle factors are leave-one-out averages, so the pool's own liquidity change is excluded from its factors.",
    )
    return out


def _unified_files() -> list[Path]:
    return sorted((DATA / "unified").glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].parquet"))


def _routes_from_legs(legs: pd.DataFrame) -> list[tuple[str, str, tuple[str, ...], float]]:
    clean = legs[legs["route_class"].isin(("single", "coherent"))].reset_index(drop=True)
    if clean.empty:
        return []

    tin = clean["token_in_sym"].to_numpy()
    tout = clean["token_out_sym"].to_numpy()
    tin_role = clean["tin_role"].to_numpy()
    tout_role = clean["tout_role"].to_numpy()
    usd = clean["amount_usd"].to_numpy(dtype=float)

    routes: list[tuple[str, str, tuple[str, ...], float]] = []
    for idx in clean.groupby(["tx_hash", "component_id"], sort=False).indices.values():
        role: dict[str, str] = {}
        for i in idx:
            for tok, rl in ((tin[i], tin_role[i]), (tout[i], tout_role[i])):
                if role.get(tok) == "intermediate":
                    continue
                if rl == "intermediate" or tok not in role:
                    role[str(tok)] = str(rl)
        sources = [t for t, rl in role.items() if rl == "source"]
        sinks = [t for t, rl in role.items() if rl == "sink"]
        inter = tuple(t for t, rl in role.items() if rl == "intermediate")
        if not sources or not sinks or not inter:
            continue
        pairs = [(s, t) for s in sources for t in sinks if s != t]
        if not pairs:
            continue
        per_pair_volume = float(usd[idx].sum() / len(idx) / len(pairs))
        for src, tgt in pairs:
            routes.append((src, tgt, inter, per_pair_volume))
    return routes


def build_pair_vehicle_actual_daily(force: bool = False) -> pd.DataFrame:
    out_path = DATA / "empirical" / "pair_vehicle_actual_daily.parquet"
    if out_path.exists() and not force:
        return pd.read_parquet(out_path)

    frames = []
    files = _unified_files()
    for i, path in enumerate(files, 1):
        legs = pd.read_parquet(
            path,
            columns=[
                "tx_hash",
                "component_id",
                "route_class",
                "token_in_sym",
                "token_out_sym",
                "amount_usd",
                "tin_role",
                "tout_role",
            ],
        )
        date = f"{path.stem[:4]}-{path.stem[4:6]}-{path.stem[6:]}"
        acc: defaultdict[tuple[str, str, str], float] = defaultdict(float)
        for src, tgt, inter, volume in _routes_from_legs(legs):
            pair = f"{src}->{tgt}"
            for vehicle in inter:
                if vehicle in VEHICLES:
                    acc[(date, pair, vehicle)] += volume
        if acc:
            frames.append(
                pd.DataFrame(
                    [(date_, pair, vehicle, volume) for (date_, pair, vehicle), volume in acc.items()],
                    columns=["date", "pair", "vehicle", "volume_usd"],
                )
            )
        if i % 250 == 0 or i == len(files):
            print(f"  actual pair-vehicle routes [{i}/{len(files)}] {date}", flush=True)

    out = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["date", "pair", "vehicle", "volume_usd"])
    )
    out.to_parquet(out_path, index=False)
    return out


def _actual_pair_vehicle_shares(actual: pd.DataFrame) -> pd.DataFrame:
    d = actual[actual["vehicle"].isin(VEHICLES)].copy()
    d["date"] = pd.to_datetime(d["date"])
    d["pair_total"] = d.groupby(["date", "pair"])["volume_usd"].transform("sum")
    d = d[d["pair_total"] > 0].copy()
    d["actual_vehicle_share"] = d["volume_usd"] / d["pair_total"]
    d["log_vehicle_volume"] = np.log1p(d["volume_usd"])
    return d


def _route_cost_10k() -> pd.DataFrame:
    cols = [
        "date",
        "src_sym",
        "tgt_sym",
        "vehicle_sym",
        "trade_size_usd",
        "direct_available",
        "vehicle_available",
        "direct_output_usd",
        "vehicle_output_usd",
        "vehicle_route_advantage",
    ]
    r = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet", columns=cols)
    r = r[r["trade_size_usd"].astype(float).eq(10_000.0)].copy()
    r["date"] = pd.to_datetime(r["date"])
    r["pair"] = r["src_sym"].astype(str) + "->" + r["tgt_sym"].astype(str)
    r["vehicle"] = r["vehicle_sym"].astype(str)
    r["route_cost_advantage_100bp"] = (10_000.0 * r["vehicle_route_advantage"].astype(float) / 100.0).clip(-200, 200)
    r["vehicle_available"] = r["vehicle_available"].astype(float)
    r["direct_available"] = r["direct_available"].astype(float)
    r["vehicle_depth"] = (r["vehicle_output_usd"].astype(float) / r["trade_size_usd"].astype(float)).replace(
        [np.inf, -np.inf], np.nan
    ).clip(0, 2)
    r["direct_depth"] = (r["direct_output_usd"].astype(float) / r["trade_size_usd"].astype(float)).replace(
        [np.inf, -np.inf], np.nan
    ).clip(0, 2)
    return r


def actual_route_choice_tests(actual: pd.DataFrame) -> pd.DataFrame:
    shares = _actual_pair_vehicle_shares(actual)
    r = _route_cost_10k()
    d = r.merge(
        shares[["date", "pair", "vehicle", "actual_vehicle_share", "log_vehicle_volume"]],
        on=["date", "pair", "vehicle"],
        how="inner",
    )
    d["pair_date"] = d["pair"] + "|" + d["date"].dt.strftime("%Y-%m-%d")
    d.to_parquet(DATA / "empirical" / "actual_route_choice_panel.parquet", index=False)

    rows = []
    specs = [
        ("Actual vehicle share", 100.0 * d["actual_vehicle_share"], "pp"),
        ("Log actual vehicle volume", d["log_vehicle_volume"], "log points"),
    ]
    x_names = ["route_cost_advantage_100bp", "vehicle_available", "vehicle_depth"]
    for outcome, y_raw, units in specs:
        y = _oneway_demean(y_raw, d["pair_date"])
        x = pd.DataFrame({name: _oneway_demean(d[name], d["pair_date"]) for name in x_names})
        n, clusters, res = _cluster_ols(y, x, d["date"])
        for name in x_names:
            rows.append(
                {
                    "Outcome": outcome,
                    "Regressor": name,
                    "N": _int(n),
                    "Date clusters": _int(clusters),
                    "Beta": _num(res[f"{name}_beta"], 4),
                    "SE": _num(res[f"{name}_se"], 4),
                    "t": _num(res[f"{name}_t"], 2),
                    "p": _p(res[f"{name}_p"]),
                    "Units": units,
                    "FE / SE": "endpoint-pair x date FE; date-clustered SE",
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "actual_route_choice_tests.csv", index=False)
    _write_table(
        out,
        "table_m13_actual_route_choice",
        "Actual pair-vehicle route choice and route economics.",
        "tab:actual-route-choice",
        note="Actual vehicle shares are reconstructed from unified transaction routes. Regressions compare candidate vehicles within the same endpoint pair and date.",
    )
    return out


def lp_allocation_feedback_tests(panel: pd.DataFrame, core: pd.DataFrame) -> pd.DataFrame:
    def _core_row(outcome: str, regressor: str, panel_name: str, units: str) -> dict[str, object]:
        r = core[(core["Outcome"].eq(outcome)) & (core["Regressor"].eq(regressor))].iloc[0]
        return {
            "Panel": panel_name,
            "Outcome": outcome,
            "Regressor": regressor,
            "N": r["N"],
            "Date clusters": r["Date clusters"],
            "Beta": r["Beta"],
            "SE": r["SE"],
            "t": r["t"],
            "p": r["p"],
            "Units": units,
            "FE / SE": r["FE / SE"],
        }

    rows: list[dict[str, object]] = [
        _core_row("future VehicleShare, t+7", "lp_concentration_share", "A. Stock feedback", "share"),
        _core_row("future LPConcentration, t+7", "BridgeShare", "A. Stock feedback", "share"),
        _core_row("future log VehicleLinkedLiquidity, t+7", "BridgeShare", "A. Stock feedback", "log points"),
    ]

    d = panel.sort_values(["token", "date"]).copy()
    d["delta_lp_concentration_t30_pp"] = 100.0 * (
        d.groupby("token")["lp_concentration_share"].shift(-30) - d["lp_concentration_share"]
    )
    d["delta_log_liquidity_t30"] = d.groupby("token")["log_vehicle_linked_liquidity"].shift(-30) - d[
        "log_vehicle_linked_liquidity"
    ]
    x_names = [
        "BridgeShare",
        "route_cost_advantage_100bp",
        "vehicle_available_share",
        "no_direct_vehicle_available_share",
    ]
    specs = [
        ("30-day change in LPConcentration", "delta_lp_concentration_t30_pp", "pp"),
        ("30-day change in log VehicleLinkedLiquidity", "delta_log_liquidity_t30", "log points"),
    ]
    for outcome, y_name, units in specs:
        y = _twoway_demean(d[y_name], d["token"], d["date"])
        x = pd.DataFrame({name: _twoway_demean(d[name], d["token"], d["date"]) for name in x_names})
        n, clusters, res = _cluster_ols(y, x, d["date"])
        for name in x_names:
            rows.append(
                {
                    "Panel": "B. LP stock change",
                    "Outcome": outcome,
                    "Regressor": name,
                    "N": _int(n),
                    "Date clusters": _int(clusters),
                    "Beta": _num(res[f"{name}_beta"], 4),
                    "SE": _num(res[f"{name}_se"], 4),
                    "t": _num(res[f"{name}_t"], 2),
                    "p": _p(res[f"{name}_p"]),
                    "Units": units,
                    "FE / SE": "token FE + date FE; date-clustered SE",
                }
            )

    out = pd.DataFrame(rows)
    out.to_csv(EMP / "lp_allocation_feedback_tests.csv", index=False)
    _write_table(
        out,
        "table_m14_lp_allocation_feedback",
        "Vehicle use and vehicle-linked liquidity allocation.",
        "tab:lp-allocation-feedback",
        note="Panel A reports the unified stock feedback estimates from Table m09. Panel B uses 30-day changes in vehicle-linked liquidity stocks.",
    )
    return out


def pair_challenger_displacement_tests(actual: pd.DataFrame) -> pd.DataFrame:
    shares = _actual_pair_vehicle_shares(actual)
    r = _route_cost_10k()
    d = r.merge(
        shares[["date", "pair", "vehicle", "actual_vehicle_share"]],
        on=["date", "pair", "vehicle"],
        how="inner",
    ).dropna(subset=["actual_vehicle_share", "route_cost_advantage_100bp"])
    idx = d.groupby(["pair", "date"])["actual_vehicle_share"].idxmax()
    inc = d.loc[idx].copy().rename(
        columns={
            "vehicle": "incumbent",
            "actual_vehicle_share": "incumbent_share_t0",
            "route_cost_advantage_100bp": "incumbent_advantage_100bp",
        }
    )
    alt = (
        d.loc[~d.index.isin(idx)]
        .sort_values("route_cost_advantage_100bp")
        .groupby(["pair", "date"])
        .tail(1)[["pair", "date", "vehicle", "route_cost_advantage_100bp", "actual_vehicle_share"]]
        .rename(
            columns={
                "vehicle": "challenger",
                "route_cost_advantage_100bp": "challenger_advantage_100bp",
                "actual_vehicle_share": "challenger_share_t0",
            }
        )
    )
    base = inc.merge(alt, on=["pair", "date"])
    base["challenger_edge_100bp"] = base["challenger_advantage_100bp"] - base["incumbent_advantage_100bp"]
    base["future_date"] = base["date"] + pd.Timedelta(days=30)
    future = shares.rename(
        columns={"date": "future_date", "vehicle": "future_vehicle", "actual_vehicle_share": "future_share"}
    )[["pair", "future_date", "future_vehicle", "future_share"]]
    base = base.merge(
        future,
        left_on=["pair", "future_date", "challenger"],
        right_on=["pair", "future_date", "future_vehicle"],
        how="left",
    ).rename(columns={"future_share": "challenger_share_t30"}).drop(columns=["future_vehicle"])
    base = base.merge(
        future,
        left_on=["pair", "future_date", "incumbent"],
        right_on=["pair", "future_date", "future_vehicle"],
        how="left",
    ).rename(columns={"future_share": "incumbent_share_t30"}).drop(columns=["future_vehicle"])
    base["challenger_share_t30"] = base["challenger_share_t30"].fillna(0.0)
    base["incumbent_share_t30"] = base["incumbent_share_t30"].fillna(0.0)
    base["challenger_delta_t30_pp"] = 100.0 * (base["challenger_share_t30"] - base["challenger_share_t0"])
    base["incumbent_delta_t30_pp"] = 100.0 * (base["incumbent_share_t30"] - base["incumbent_share_t0"])
    base["challenger_beats_incumbent_t30_pp"] = 100.0 * (
        base["challenger_share_t30"] > base["incumbent_share_t30"]
    ).astype(float)
    base.to_parquet(DATA / "empirical" / "pair_challenger_displacement_panel.parquet", index=False)

    rows = []
    for outcome, y_name, units in [
        ("Challenger share change t+30", "challenger_delta_t30_pp", "pp"),
        ("Incumbent share change t+30", "incumbent_delta_t30_pp", "pp"),
        ("Pr(challenger beats incumbent t+30)", "challenger_beats_incumbent_t30_pp", "pp"),
    ]:
        y = _twoway_demean(base[y_name], base["pair"], base["date"])
        x = pd.DataFrame({"challenger_edge_100bp": _twoway_demean(base["challenger_edge_100bp"], base["pair"], base["date"])})
        n, clusters, res = _cluster_ols(y, x, base["date"])
        rows.append(
            {
                "Panel": "A. Pair-level regression",
                "Outcome": outcome,
                "Challenger edge bin": "",
                "N": _int(n),
                "Date clusters": _int(clusters),
                "Mean edge (bp)": "",
                "Mean outcome": "",
                "Beta": _num(res["challenger_edge_100bp_beta"], 4),
                "t": _num(res["challenger_edge_100bp_t"], 2),
                "p": _p(res["challenger_edge_100bp_p"]),
                "Units": f"{units} per 100 bp edge",
            }
        )

    base["edge_bin"] = pd.cut(
        100.0 * base["challenger_edge_100bp"],
        bins=[-np.inf, 0, 25, 100, 250, np.inf],
        labels=["challenger <= incumbent", "0 to 25 bp", "25 to 100 bp", "100 to 250 bp", ">250 bp"],
    )
    bins = base.groupby("edge_bin", observed=False).agg(
        N=("challenger_edge_100bp", "count"),
        edge=("challenger_edge_100bp", "mean"),
        challenger_delta=("challenger_delta_t30_pp", "mean"),
        incumbent_delta=("incumbent_delta_t30_pp", "mean"),
        beat=("challenger_beats_incumbent_t30_pp", "mean"),
    )
    for label, rbin in bins.iterrows():
        rows.append(
            {
                "Panel": "B. Edge-bin means",
                "Outcome": "Challenger / incumbent displacement",
                "Challenger edge bin": str(label),
                "N": _int(rbin["N"]),
                "Date clusters": "",
                "Mean edge (bp)": _num(100.0 * rbin["edge"], 1),
                "Mean outcome": (
                    f"challenger { _num(rbin['challenger_delta'], 2) } pp; "
                    f"incumbent { _num(rbin['incumbent_delta'], 2) } pp; "
                    f"beats { _num(rbin['beat'], 2) }%"
                ),
                "Beta": "",
                "t": "",
                "p": "",
                "Units": "bin means",
            }
        )

    out = pd.DataFrame(rows)
    out.to_csv(EMP / "pair_challenger_displacement_tests.csv", index=False)
    _write_table(
        out,
        "table_m15_pair_challenger_displacement",
        "Actual pair-level challenger displacement by route-cost edge.",
        "tab:pair-challenger-displacement",
        note="The incumbent is the highest actual-share vehicle for the endpoint pair and date. The challenger is the best non-incumbent route-cost candidate at $10k. Edge is challenger minus incumbent route advantage.",
    )
    return out


def v3_dose_response_tests() -> pd.DataFrame:
    launch = pd.Timestamp("2021-05-05")
    d = _route_cost_10k()
    d = d[d["vehicle"].eq("WETH")].copy()
    d = d[(d["date"] >= launch - pd.Timedelta(days=365)) & (d["date"] <= launch + pd.Timedelta(days=365))]
    d["post_v3"] = (d["date"] >= launch).astype(float)
    d["no_direct_weth"] = ((d["direct_available"] < 0.5) & (d["vehicle_available"] > 0.5)).astype(float)
    pre = (
        d[d["post_v3"].eq(0)]
        .groupby("pair", as_index=False)
        .agg(pre_direct_availability=("direct_available", "mean"))
    )
    pre["Pre-V3 direct availability quartile"] = pd.qcut(
        pre["pre_direct_availability"].rank(method="first"),
        4,
        labels=["Q1 weakest", "Q2", "Q3", "Q4 strongest"],
    )
    d = d.merge(pre, on="pair", how="inner")

    rows = []
    outcomes = [
        ("Direct-route availability", "direct_available", 100.0, "pp"),
        ("No-direct WETH availability", "no_direct_weth", 100.0, "pp"),
        ("DirectDepth", "direct_depth", 1.0, "ratio"),
    ]
    for quartile, g in d.groupby("Pre-V3 direct availability quartile", observed=False):
        for outcome, y_col, scale, units in outcomes:
            y = _oneway_demean(scale * g[y_col].astype(float), g["pair"])
            x = pd.DataFrame({"post_v3": _oneway_demean(g["post_v3"], g["pair"])})
            n, clusters, res = _cluster_ols(y, x, g["pair"])
            rows.append(
                {
                    "Pre-V3 direct availability quartile": str(quartile),
                    "Outcome": outcome,
                    "Rows": _int(n),
                    "Pairs": _int(clusters),
                    "Post-V3 effect": _num(res["post_v3_beta"], 2),
                    "SE": _num(res["post_v3_se"], 2),
                    "t": _num(res["post_v3_t"], 2),
                    "p": _p(res["post_v3_p"]),
                    "Units": units,
                    "FE / SE": "endpoint-pair FE; pair-clustered SE",
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "v3_dose_response_tests.csv", index=False)
    _write_table(
        out,
        "table_m16_v3_dose_response",
        "Uniswap V3 architecture dose response by pre-V3 direct-market weakness.",
        "tab:v3-dose-response",
        note="Quartiles are formed from pre-V3 direct-route availability for the same endpoint pairs. Estimates compare one year before and after the May 5, 2021 V3 launch.",
    )
    return out


def v4_route_use_persistence_tests() -> pd.DataFrame:
    d = pd.read_csv(DATA / "empirical" / "v4_settlement_eligible_cells.csv")
    d["week"] = pd.to_datetime(d["week"])
    d["week_label"] = d["week"].dt.strftime("%Y-%m-%d")
    d["vehicle"] = d["vehicle"].astype(str)
    d["log_v3_routes"] = np.log1p(d["routes_uniswap_v3"])
    d["log_v4_routes"] = np.log1p(d["routes_uniswap_v4"])
    d["log_v3_usd"] = np.log1p(d["route_usd_uniswap_v3"])
    d["log_v4_usd"] = np.log1p(d["route_usd_uniswap_v4"])
    d["v4_route_share_pct"] = 100.0 * d["routes_uniswap_v4"] / (d["routes_uniswap_v3"] + d["routes_uniswap_v4"])
    d["v4_volume_share_pct"] = 100.0 * d["route_usd_uniswap_v4"] / (d["route_usd_uniswap_v3"] + d["route_usd_uniswap_v4"])

    rows = []
    specs = [
        ("Log V4 route count", "log_v4_routes", "log_v3_routes", "log V3 route count"),
        ("Log V4 route volume", "log_v4_usd", "log_v3_usd", "log V3 route volume"),
    ]
    for outcome, y_col, x_col, reg_label in specs:
        y = _twoway_demean(d[y_col], d["vehicle"], d["week_label"])
        x = pd.DataFrame({reg_label: _twoway_demean(d[x_col], d["vehicle"], d["week_label"])})
        n, clusters, res = _cluster_ols(y, x, d["week"])
        rows.append(
            {
                "Panel": "A. Matched-cell route-use persistence",
                "Outcome": outcome,
                "Regressor / statistic": reg_label,
                "N": _int(n),
                "Week clusters": _int(clusters),
                "Estimate": _num(res[f"{reg_label}_beta"], 4),
                "SE": _num(res[f"{reg_label}_se"], 4),
                "t": _num(res[f"{reg_label}_t"], 2),
                "p": _p(res[f"{reg_label}_p"]),
                "FE / SE": "vehicle FE + week FE; week-clustered SE",
            }
        )

    for stat_name, value in [
        ("Mean V4 route share within matched cells", d["v4_route_share_pct"].mean()),
        ("Median V4 route share within matched cells", d["v4_route_share_pct"].median()),
        ("Mean V4 volume share within matched cells", d["v4_volume_share_pct"].mean()),
        ("Median V4 volume share within matched cells", d["v4_volume_share_pct"].median()),
    ]:
        rows.append(
            {
                "Panel": "B. Matched-cell V4 use share",
                "Outcome": "V4 share",
                "Regressor / statistic": stat_name,
                "N": _int(len(d)),
                "Week clusters": _int(d["week"].nunique()),
                "Estimate": _num(value, 2),
                "SE": "",
                "t": "",
                "p": "",
                "FE / SE": "descriptive percentage",
            }
        )

    out = pd.DataFrame(rows)
    out.to_csv(EMP / "v4_route_use_persistence_tests.csv", index=False)
    _write_table(
        out,
        "table_m17_v4_route_use_persistence",
        "V4 route-use persistence in matched vehicle-route cells.",
        "tab:v4-route-use-persistence",
        note="Matched cells are week x endpoint pair x intermediate vehicle cells with both V3 and V4 route units in the settlement sample frame.",
    )
    return out


def common_liquidity_heterogeneity_tests() -> pd.DataFrame:
    d = pd.read_parquet(DATA / "empirical" / "common_liquidity_pool_panel.parquet")
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["token", "BridgeShare"])
    vehicle_avg = bridge.groupby("token")["BridgeShare"].mean()
    cutoff = vehicle_avg.median()
    d["high_vehicle_dependence"] = d["vehicle"].map(lambda v: vehicle_avg.get(v, 0.0) >= cutoff)
    mean_pool_liq = d.groupby("pool_vehicle_id")["liquidity_usd"].transform("mean")
    top1_cutoff = mean_pool_liq.quantile(0.99)
    samples = [
        ("High average VehicleShare vehicles", d[d["high_vehicle_dependence"]].copy()),
        ("Low average VehicleShare vehicles", d[~d["high_vehicle_dependence"]].copy()),
        ("Excluding top 1% mean-liquidity pools", d[mean_pool_liq <= top1_cutoff].copy()),
    ]
    rows = []
    for sample, g in samples:
        y = _oneway_demean(g["dlog_liquidity"], g["pool_vehicle_id"])
        x = pd.DataFrame(
            {
                "market_factor_loo": _oneway_demean(g["market_factor_loo"], g["pool_vehicle_id"]),
                "vehicle_factor_loo": _oneway_demean(g["vehicle_factor_loo"], g["pool_vehicle_id"]),
            }
        )
        n, clusters, res = _cluster_ols(y, x, g["date"])
        for name in ["market_factor_loo", "vehicle_factor_loo"]:
            rows.append(
                {
                    "Sample": sample,
                    "Regressor": name,
                    "N": _int(n),
                    "Date clusters": _int(clusters),
                    "Pools": _int(g["pool_vehicle_id"].nunique()),
                    "Beta": _num(res[f"{name}_beta"], 4),
                    "SE": _num(res[f"{name}_se"], 4),
                    "t": _num(res[f"{name}_t"], 2),
                    "p": _p(res[f"{name}_p"]),
                    "FE / SE": "pool-vehicle FE; date-clustered SE",
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(EMP / "common_liquidity_heterogeneity_tests.csv", index=False)
    _write_table(
        out,
        "table_m18_common_liquidity_heterogeneity",
        "Common liquidity heterogeneity by vehicle dependence.",
        "tab:common-liquidity-heterogeneity",
        note="High/low vehicle dependence is based on whether the vehicle token's average BridgeShare is above the vehicle-set median. The top-pool robustness excludes the top 1% of pools by mean liquidity.",
    )
    return out


def build_rq_registry(
    core: pd.DataFrame,
    threshold: pd.DataFrame,
    stress: pd.DataFrame,
    common: pd.DataFrame,
    actual_choice: pd.DataFrame,
    lp_feedback: pd.DataFrame,
    challenger: pd.DataFrame,
    v3_dose: pd.DataFrame,
    v4_persistence: pd.DataFrame,
    common_hetero: pd.DataFrame,
) -> None:
    def _lookup(df: pd.DataFrame, **where: str) -> str:
        g = df.copy()
        for key, val in where.items():
            g = g[g[key].astype(str).eq(val)]
        if g.empty:
            return ""
        r = g.iloc[0]
        return f"beta {r.get('Beta', r.get('Estimate', ''))}, t {r.get('t', '')}, p {r.get('p', '')}"

    def _cell(df: pd.DataFrame, column: str, **where: str) -> str:
        g = df.copy()
        for key, val in where.items():
            g = g[g[key].astype(str).eq(val)]
        if g.empty or column not in g:
            return ""
        return str(g.iloc[0][column])

    def _md_table(df: pd.DataFrame) -> list[str]:
        d = df.fillna("").astype(str)
        d = d.map(lambda x: x.replace("\n", " ").replace("|", "\\|"))
        cols = list(d.columns)
        lines = [
            "| " + " | ".join(cols) + " |",
            "| " + " | ".join(["---"] * len(cols)) + " |",
        ]
        for _, row in d.iterrows():
            lines.append("| " + " | ".join(row[col] for col in cols) + " |")
        return lines

    m04 = pd.read_csv(OUT / "tables" / "table_m04_p3_stress_rotation.csv")
    m05 = pd.read_csv(OUT / "tables" / "table_m05_p4a_v3_opportunity.csv")
    m06 = pd.read_csv(OUT / "tables" / "table_m06_p4b_v4_settlement.csv")

    rq_rows = [
        {
            "RQ": "RQ1. Formation",
            "Empirical answer": "Vehicle use is higher when the candidate vehicle is cheaper/better executable and when vehicle-linked liquidity is larger.",
            "Exact evidence": (
                f"Table m13: route-cost advantage is positive for actual vehicle share ({_lookup(actual_choice, Outcome='Actual vehicle share', Regressor='route_cost_advantage_100bp')}); "
                f"vehicle availability is positive ({_lookup(actual_choice, Outcome='Actual vehicle share', Regressor='vehicle_available')}); vehicle depth is positive ({_lookup(actual_choice, Outcome='Actual vehicle share', Regressor='vehicle_depth')}). "
                f"Table m09: route-cost advantage predicts future VehicleShare ({_lookup(core, Outcome='future VehicleShare, t+7', Regressor='route_cost_advantage_100bp')}); vehicle availability predicts future VehicleShare ({_lookup(core, Outcome='future VehicleShare, t+7', Regressor='vehicle_available_share')})."
            ),
        },
        {
            "RQ": "RQ2. Liquidity provision",
            "Empirical answer": "Vehicle-linked liquidity and vehicle use reinforce each other in stock allocations; short-run stock changes also load on route availability.",
            "Exact evidence": (
                f"Table m09/m14: LPConcentration predicts future VehicleShare ({_lookup(core, Outcome='future VehicleShare, t+7', Regressor='lp_concentration_share')}); "
                f"VehicleShare predicts future LPConcentration ({_lookup(core, Outcome='future LPConcentration, t+7', Regressor='BridgeShare')}) and future log VehicleLinkedLiquidity ({_lookup(core, Outcome='future log VehicleLinkedLiquidity, t+7', Regressor='BridgeShare')}). "
                f"Table m14: vehicle availability predicts the 30-day change in log VehicleLinkedLiquidity ({_lookup(lp_feedback, Panel='B. LP stock change', Outcome='30-day change in log VehicleLinkedLiquidity', Regressor='vehicle_available_share')})."
            ),
        },
        {
            "RQ": "RQ3. Persistence and displacement",
            "Empirical answer": "Vehicle status is persistent, but challenger cost edges predict actual challenger share gains and incumbent losses.",
            "Exact evidence": (
                f"Table m09: current VehicleShare predicts t+30 VehicleShare ({_lookup(core, Outcome='future VehicleShare, t+30', Regressor='BridgeShare')}). "
                f"Table m10: >250 bp challenger edge implies incumbent share change {_cell(threshold, 'Mean incumbent share change t+30 (pp)', **{'Challenger advantage bin': '>250 bp'})} pp, p {_cell(threshold, 'p', **{'Challenger advantage bin': '>250 bp'})}. "
                f"Table m15: challenger edge raises challenger share change ({_lookup(challenger, Panel='A. Pair-level regression', Outcome='Challenger share change t+30')}) and lowers incumbent share change ({_lookup(challenger, Panel='A. Pair-level regression', Outcome='Incumbent share change t+30')})."
            ),
        },
        {
            "RQ": "RQ4. Stress rotation",
            "Empirical answer": "Stress rotates vehicle use away from WETH and toward stable vehicles on common-support stress days; event-time persistence is interpreted with pre-movement caution.",
            "Exact evidence": (
                f"Table m04: WETH-minus-stable change is {_cell(m04, 'Effect', Panel='A. Main decomposed same-day effect', Estimate='WETH-minus-stable change')}, p {_cell(m04, 'p', Panel='A. Main decomposed same-day effect', Estimate='WETH-minus-stable change')}. "
                f"Table m11: event-day gap is {_cell(stress, 'Mean effect (pp)', Window='event day', Outcome='gap change pp')} pp, p {_cell(stress, 'p', Window='event day', Outcome='gap change pp')}; pre-window gap is {_cell(stress, 'Mean effect (pp)', Window='pre -14 to -1', Outcome='gap change pp')} pp, p {_cell(stress, 'p', Window='pre -14 to -1', Outcome='gap change pp')}."
            ),
        },
        {
            "RQ": "RQ5. Architecture",
            "Empirical answer": "Uniswap V3 materially deepens direct-route availability and reduces no-direct WETH dependence, especially outside already-strong direct markets.",
            "Exact evidence": (
                f"Table m05: no-direct WETH availability falls {_cell(m05, 'Post-V3 effect', Outcome='No-direct WETH availability')} pp, p {_cell(m05, 'p', Outcome='No-direct WETH availability')}. "
                f"Table m16: in Q2 pre-V3 direct markets, direct-route availability rises {_cell(v3_dose, 'Post-V3 effect', **{'Pre-V3 direct availability quartile': 'Q2', 'Outcome': 'Direct-route availability'})} pp, p {_cell(v3_dose, 'p', **{'Pre-V3 direct availability quartile': 'Q2', 'Outcome': 'Direct-route availability'})}; no-direct WETH availability falls {_cell(v3_dose, 'Post-V3 effect', **{'Pre-V3 direct availability quartile': 'Q2', 'Outcome': 'No-direct WETH availability'})} pp, p {_cell(v3_dose, 'p', **{'Pre-V3 direct availability quartile': 'Q2', 'Outcome': 'No-direct WETH availability'})}."
            ),
        },
        {
            "RQ": "RQ6. Settlement design",
            "Empirical answer": "V4 reduces physical intermediate-token transfers but vehicle-route demand persists across matched cells, and netting exposure is associated with LP-liquidity response.",
            "Exact evidence": (
                f"Table m06: V4 transfer incidence is {_cell(m06, 'V4', Panel='A. Transfer incidence by route-size bin', **{'Sample / diagnostic': 'All'})} versus V3 {_cell(m06, 'V3', Panel='A. Transfer incidence by route-size bin', **{'Sample / diagnostic': 'All'})}; log LP liquidity response is {_cell(m06, 'Difference / balance', Panel='C. LP response by netting exposure', **{'Sample / diagnostic': 'log LP liquidity'})}. "
                f"Table m17: log V3 route count predicts log V4 route count ({_lookup(v4_persistence, Panel='A. Matched-cell route-use persistence', Outcome='Log V4 route count')}); log V3 route volume predicts log V4 route volume ({_lookup(v4_persistence, Panel='A. Matched-cell route-use persistence', Outcome='Log V4 route volume')})."
            ),
        },
        {
            "RQ": "RQ7. Common liquidity",
            "Empirical answer": "Vehicle-linked pools share a vehicle-specific liquidity component beyond market-wide liquidity; the component is stronger in high-vehicle-dependence samples and survives top-pool exclusion.",
            "Exact evidence": (
                f"Table m12: vehicle factor is positive in the full sample ({_lookup(common, **{'Sample / specification': 'Full sample', 'Regressor': 'vehicle_factor_loo'})}); stress interaction is positive ({_lookup(common, **{'Sample / specification': 'Stress interaction', 'Regressor': 'vehicle_factor_x_stress'})}). "
                f"Table m18: high-dependence vehicle factor is positive ({_lookup(common_hetero, Sample='High average VehicleShare vehicles', Regressor='vehicle_factor_loo')}); low-dependence vehicle factor is not significant ({_lookup(common_hetero, Sample='Low average VehicleShare vehicles', Regressor='vehicle_factor_loo')}); excluding top 1% mean-liquidity pools remains positive ({_lookup(common_hetero, Sample='Excluding top 1% mean-liquidity pools', Regressor='vehicle_factor_loo')})."
            ),
        },
    ]

    registry_lines = [
        "# Core RQ Evidence Registry",
        "",
        "Generated by `scripts/run_core_rq_experiments.py`. This is a core-result registry, not manuscript prose.",
        "",
    ]
    registry_lines.extend(_md_table(pd.DataFrame(rq_rows)))
    (EMP / "core_rq_evidence_registry.md").write_text("\n".join(registry_lines) + "\n", encoding="utf-8")

    table_paths = [
        ("Table m04. Stress rotation", OUT / "tables" / "table_m04_p3_stress_rotation.csv"),
        ("Table m05. V3 opportunity", OUT / "tables" / "table_m05_p4a_v3_opportunity.csv"),
        ("Table m06. V4 settlement", OUT / "tables" / "table_m06_p4b_v4_settlement.csv"),
        ("Table m08. Variable construction", OUT / "tables" / "table_m08_variable_construction.csv"),
        ("Table m09. Core panel regressions", OUT / "tables" / "table_m09_core_panel_regressions.csv"),
        ("Table m10. Persistence thresholds", OUT / "tables" / "table_m10_persistence_thresholds.csv"),
        ("Table m11. Stress event time", OUT / "tables" / "table_m11_stress_event_time.csv"),
        ("Table m12. Common liquidity", OUT / "tables" / "table_m12_common_liquidity.csv"),
        ("Table m13. Actual route choice", OUT / "tables" / "table_m13_actual_route_choice.csv"),
        ("Table m14. LP allocation feedback", OUT / "tables" / "table_m14_lp_allocation_feedback.csv"),
        ("Table m15. Pair challenger displacement", OUT / "tables" / "table_m15_pair_challenger_displacement.csv"),
        ("Table m16. V3 dose response", OUT / "tables" / "table_m16_v3_dose_response.csv"),
        ("Table m17. V4 route-use persistence", OUT / "tables" / "table_m17_v4_route_use_persistence.csv"),
        ("Table m18. Common liquidity heterogeneity", OUT / "tables" / "table_m18_common_liquidity_heterogeneity.csv"),
    ]
    detail_lines = [
        "# Core Empirical RQ Results",
        "",
        "Generated by `scripts/run_core_rq_experiments.py`. Core notes only, not manuscript prose.",
        "",
        "## Research Questions And Answers",
        "",
    ]
    detail_lines.extend(_md_table(pd.DataFrame(rq_rows)))
    detail_lines.append("")
    detail_lines.append("## Displayed Evidence Tables")
    for title, path in table_paths:
        detail_lines.extend(["", f"### {title}", ""])
        detail_lines.extend(_md_table(pd.read_csv(path)))
    (OUT / "core_empirical_rq_results.md").write_text("\n".join(detail_lines) + "\n", encoding="utf-8")


def main() -> int:
    _ensure_dirs()
    variable_construction_table()
    panel = core_token_day_panel()
    core = core_panel_regressions(panel)
    threshold = persistence_displacement_thresholds(panel)
    stress = stress_event_time()
    pool = build_pool_vehicle_liquidity()
    common = common_liquidity_tests(pool)
    actual = build_pair_vehicle_actual_daily()
    actual_choice = actual_route_choice_tests(actual)
    lp_feedback = lp_allocation_feedback_tests(panel, core)
    challenger = pair_challenger_displacement_tests(actual)
    v3_dose = v3_dose_response_tests()
    v4_persistence = v4_route_use_persistence_tests()
    common_hetero = common_liquidity_heterogeneity_tests()
    build_rq_registry(
        core,
        threshold,
        stress,
        common,
        actual_choice,
        lp_feedback,
        challenger,
        v3_dose,
        v4_persistence,
        common_hetero,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

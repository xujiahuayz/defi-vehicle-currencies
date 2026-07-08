#!/usr/bin/env python3
"""Core empirical registry and gap-closing tests for the DVC RQs.

Outputs:
  data/empirical/core_token_day_panel.parquet
  data/empirical/pool_vehicle_liquidity_daily.parquet
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
"""
from __future__ import annotations

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


def build_rq_registry(
    core: pd.DataFrame,
    threshold: pd.DataFrame,
    stress: pd.DataFrame,
    common: pd.DataFrame,
) -> None:
    def _lookup(df: pd.DataFrame, **where: str) -> str:
        g = df.copy()
        for key, val in where.items():
            g = g[g[key].astype(str).eq(val)]
        if g.empty:
            return ""
        r = g.iloc[0]
        return f"beta {r.get('Beta', '')}, t {r.get('t', '')}, p {r.get('p', '')}"

    def _cell(df: pd.DataFrame, column: str, **where: str) -> str:
        g = df.copy()
        for key, val in where.items():
            g = g[g[key].astype(str).eq(val)]
        if g.empty or column not in g:
            return ""
        return str(g.iloc[0][column])

    m04 = pd.read_csv(OUT / "tables" / "table_m04_p3_stress_rotation.csv")
    m05 = pd.read_csv(OUT / "tables" / "table_m05_p4a_v3_opportunity.csv")
    m06 = pd.read_csv(OUT / "tables" / "table_m06_p4b_v4_settlement.csv")

    rq_rows = [
        {
            "RQ": "RQ1 formation",
            "Core answer": "Route-cost advantage, direct availability, vehicle availability, and vehicle-linked liquidity jointly predict future VehicleShare in the token-day panel.",
            "Primary artifact": "Table m09; Table m02 for thin/no-direct route-cost facts; Table m08 for definitions",
            "Current estimate": _lookup(core, Outcome="future VehicleShare, t+7", Regressor="route_cost_advantage_100bp"),
            "Status": "core panel now built; still improve with pair x vehicle x day outcome panel",
        },
        {
            "RQ": "RQ2 liquidity provision",
            "Core answer": "LPConcentration predicts future VehicleShare, and current VehicleShare predicts future LPConcentration/log liquidity.",
            "Primary artifact": "Table m09 plus existing Table m03/Table r32",
            "Current estimate": _lookup(core, Outcome="future VehicleShare, t+7", Regressor="lp_concentration_share"),
            "Status": "reduced-form feedback; next causal upgrade is LP entry/exit or gas/repositioning shock design",
        },
        {
            "RQ": "RQ3 persistence",
            "Core answer": "Lagged VehicleShare remains the dominant predictor; challenger route-cost edges are summarized as a displacement-threshold screen.",
            "Primary artifact": "Table m09 and Table m10",
            "Current estimate": _lookup(core, Outcome="future VehicleShare, t+30", Regressor="BridgeShare"),
            "Status": "threshold screen added; next upgrade is pair-level challenger choice",
        },
        {
            "RQ": "RQ4 stress rotation",
            "Core answer": "WETH share falls and stable-vehicle share rises on common-support stress days. The aggregate event-time table is diagnostic because it also shows pre-event movement.",
            "Primary artifact": "Table m04/Table r18 for same-day common-support; Table m11 as diagnostic event-time check",
            "Current estimate": "Table m04 WETH-minus-stable change -2.96 pp, p=0.018; Table m11 pre-window gap is non-zero",
            "Status": "same-day rotation is core; do not claim clean event-time persistence from Table m11 alone",
        },
        {
            "RQ": "RQ5 architecture",
            "Core answer": "Existing V3 evidence shows direct-route opportunity expansion and reduced no-direct/WETH-only cases; core variables clarify DirectAvailable and DirectDepth proxies.",
            "Primary artifact": "Table m05/Table r14/Table r19; definitions in Table m08",
            "Current estimate": "Table m05: no-direct WETH availability post-V3 -25.81 pp, p<0.001",
            "Status": "needs dose-response by pre-V3 weakness and fee-tier availability",
        },
        {
            "RQ": "RQ6 settlement design",
            "Core answer": "Existing V4 matched receipts show settlement virtualization; LP response by netting exposure is already tabled.",
            "Primary artifact": "Table m06/Table r33; definitions in Table m08",
            "Current estimate": "Table m06: V4 transfer incidence 81.4% vs V3 100%; log LP beta 2.132",
            "Status": "needs route-use persistence around V4, not only transfer incidence",
        },
        {
            "RQ": "RQ7 common liquidity",
            "Core answer": "Pool-level common-liquidity test now constructed from raw daily pool snapshots using leave-one-out vehicle liquidity factors.",
            "Primary artifact": "Table m12",
            "Current estimate": _lookup(common, **{"Sample / specification": "Full sample", "Regressor": "vehicle_factor_loo"}),
            "Status": "new core test added; next upgrade is pair/group split by vehicle-dependence",
        },
    ]
    lines = [
        "# Core RQ Evidence Registry",
        "",
        "Generated by `scripts/run_core_rq_experiments.py`. This is a core-result registry, not manuscript prose.",
        "",
        "| RQ | Core answer | Primary artifact | Current estimate | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in rq_rows:
        lines.append(
            f"| {r['RQ']} | {r['Core answer']} | {r['Primary artifact']} | {r['Current estimate']} | {r['Status']} |"
        )
    lines.append("")
    lines.append("## Newly Built Core Artifacts")
    lines.append("")
    lines.append("- `output/tables/table_m08_variable_construction.csv`: variable/proxy construction.")
    lines.append("- `data/empirical/core_token_day_panel.parquet`: merged VehicleShare, route-cost, direct availability, and LP panel.")
    lines.append("- `output/tables/table_m09_core_panel_regressions.csv`: unified token-day regressions.")
    lines.append("- `output/tables/table_m10_persistence_thresholds.csv`: incumbent displacement-threshold screen.")
    lines.append("- `output/tables/table_m11_stress_event_time.csv`: event-time stress rotation summary.")
    lines.append("- `data/empirical/pool_vehicle_liquidity_daily.parquet`: raw-derived pool-level vehicle-linked liquidity panel.")
    lines.append("- `output/tables/table_m12_common_liquidity.csv`: pool-level common-liquidity test.")
    (EMP / "core_rq_evidence_registry.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    t30_challenger = threshold[threshold["Challenger advantage bin"].astype(str).eq(">250 bp")]
    challenger_note = ""
    if not t30_challenger.empty:
        r = t30_challenger.iloc[0]
        challenger_note = (
            f">250 bp challenger edge: incumbent share change t+30 {r['Mean incumbent share change t+30 (pp)']} pp, "
            f"p {r['p']}."
        )

    detail_lines = [
        "# Core Empirical RQ Results",
        "",
        "Generated by `scripts/run_core_rq_experiments.py`. These are core notes for the empirical spine, not manuscript prose.",
        "",
        "## Variable / Proxy Registry",
        "",
        "- `output/tables/table_m08_variable_construction.csv`: defines `VehicleShare`, `RouteCostAdvantage`, `DirectAvailable`, `DirectDepth`, `VehicleLinkedLiquidity`, `LPConcentration`, `LPRepositioning`, `Stress`, `SettlementTransferIncidence`, `NettingExposure`, and `VehicleLiquidityFactor`.",
        "",
        "## Core RQ Notes",
        "",
        "| RQ | Core answer to carry forward | Main evidence | Gap / next empirical closure |",
        "| --- | --- | --- | --- |",
        (
            "| RQ1 formation | Vehicle use is explained by route economics, route executability, and vehicle-linked liquidity; treat Table m09 as the unified regression and Table m02 as the route-mechanics fact table. "
            f"| Table m09: route-cost advantage predicts future VehicleShare t+7 ({_lookup(core, Outcome='future VehicleShare, t+7', Regressor='route_cost_advantage_100bp')}); vehicle availability ({_lookup(core, Outcome='future VehicleShare, t+7', Regressor='vehicle_available_share')}); LP concentration ({_lookup(core, Outcome='future VehicleShare, t+7', Regressor='lp_concentration_share')}). "
            "| Build pair x vehicle x day outcome panel so DirectAvailable/DirectDepth can be interpreted less mechanically than in the saturated token-day panel. |"
        ),
        (
            "| RQ2 liquidity provision | Vehicle liquidity and route use reinforce each other. "
            f"| Table m09: LPConcentration predicts VehicleShare t+7 ({_lookup(core, Outcome='future VehicleShare, t+7', Regressor='lp_concentration_share')}); VehicleShare predicts future LPConcentration ({_lookup(core, Outcome='future LPConcentration, t+7', Regressor='BridgeShare')}) and future log VehicleLinkedLiquidity ({_lookup(core, Outcome='future log VehicleLinkedLiquidity, t+7', Regressor='BridgeShare')}). Cross-reference Table m03/Table r32. "
            "| Add LP entry/exit or gas/repositioning shock design for a cleaner allocation response. |"
        ),
        (
            "| RQ3 persistence | Vehicle dominance is persistent, but large challenger cost edges are associated with displacement. "
            f"| Table m09: lagged VehicleShare predicts t+30 ({_lookup(core, Outcome='future VehicleShare, t+30', Regressor='BridgeShare')}). Table m10: {challenger_note} "
            "| Upgrade threshold screen to pair-level challenger choice and duration/hazard design. |"
        ),
        (
            "| RQ4 stress rotation | Same-day common-support evidence supports WETH-to-stable rotation in stress; aggregate event-time is only diagnostic because pre-event movement is present. "
            f"| Table m04/Table r18: {_cell(m04, 'Effect', Panel='A. Main decomposed same-day effect', Estimate='WETH-minus-stable change')} gap, p {_cell(m04, 'p', Panel='A. Main decomposed same-day effect', Estimate='WETH-minus-stable change')}. Table m11: event-day gap {_cell(stress, 'Mean effect (pp)', Window='event day', Outcome='gap change pp')} pp, p {_cell(stress, 'p', Window='event day', Outcome='gap change pp')}; pre-window gap {_cell(stress, 'Mean effect (pp)', Window='pre -14 to -1', Outcome='gap change pp')} pp, p {_cell(stress, 'p', Window='pre -14 to -1', Outcome='gap change pp')}. "
            "| Keep common-support same-day estimate as the core result; use Table m11 to motivate caution on persistence. |"
        ),
        (
            "| RQ5 architecture | V3 architecture expands direct-route opportunity and reduces no-direct/WETH-only cases; definitions in Table m08 clarify DirectAvailable and DirectDepth. "
            f"| Table m05: no-direct WETH availability post-V3 {_cell(m05, 'Post-V3 effect', Outcome='No-direct WETH availability')} pp, p {_cell(m05, 'p', Outcome='No-direct WETH availability')}; pretrend p {_cell(m05, 'Pretrend p', Outcome='No-direct WETH availability')}. Cross-reference Table r14/Table r19. "
            "| Add dose response by pre-V3 direct-route weakness, fee-tier arrival, and pair-level route-cost changes. |"
        ),
        (
            "| RQ6 settlement design | V4 virtualizes settlement transfers but does not eliminate vehicle-linked liquidity relevance. "
            f"| Table m06: V4 transfer incidence {_cell(m06, 'V4', Panel='A. Transfer incidence by route-size bin', **{'Sample / diagnostic': 'All'})} versus V3 {_cell(m06, 'V3', Panel='A. Transfer incidence by route-size bin', **{'Sample / diagnostic': 'All'})}; log LP response by netting exposure is `{_cell(m06, 'Difference / balance', Panel='C. LP response by netting exposure', **{'Sample / diagnostic': 'log LP liquidity'})}`. Cross-reference Table r33. "
            "| Add route-use persistence around V4, not only receipt transfer incidence. |"
        ),
        (
            "| RQ7 common liquidity | Vehicle-linked pools share a common liquidity component beyond market-wide liquidity, and the vehicle component strengthens in stress. "
            f"| Table m12: vehicle factor full sample ({_lookup(common, **{'Sample / specification': 'Full sample', 'Regressor': 'vehicle_factor_loo'})}); stress interaction ({_lookup(common, **{'Sample / specification': 'Stress interaction', 'Regressor': 'vehicle_factor_x_stress'})}); post-V3 interaction ({_lookup(common, **{'Sample / specification': 'Post-V3 interaction', 'Regressor': 'vehicle_factor_x_post_v3'})}). "
            "| Split by pair vehicle-dependence and run robustness excluding dominant pools. |"
        ),
        "",
        "## New / Updated Artifacts",
        "",
        "- `output/tables/table_m08_variable_construction.csv`",
        "- `output/tables/table_m09_core_panel_regressions.csv`",
        "- `output/tables/table_m10_persistence_thresholds.csv`",
        "- `output/tables/table_m11_stress_event_time.csv`",
        "- `output/tables/table_m12_common_liquidity.csv`",
        "- `output/empirical/core_rq_evidence_registry.md`",
        "- `data/empirical/core_token_day_panel.parquet`",
        "- `data/empirical/pool_vehicle_liquidity_daily.parquet`",
        "- `data/empirical/common_liquidity_pool_panel.parquet`",
    ]
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
    build_rq_registry(core, threshold, stress, common)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

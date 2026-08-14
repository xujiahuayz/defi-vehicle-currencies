#!/usr/bin/env python3
"""Core empirical registry and gap-closing tests for the DVC RQs.

Outputs:
  data/empirical/core_token_day_panel.parquet
  data/processed/pool_capital_release/current.json (canonical release input)
  data/empirical/pair_vehicle_actual_daily.parquet
  output/empirical/variable_construction.pkl
  output/empirical/core_panel_regressions.pkl
  output/empirical/persistence_thresholds.pkl
  output/empirical/stress_event_time.pkl
  output/empirical/common_pool_capital.pkl
  output/empirical/core_rq_evidence_registry.md
  output/core_empirical_rq_results.md
  output/tables/<descriptive_table_name>.{tex,pdf}
"""
from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.dynamics import (
    CANONICAL_RESPONSE_HORIZONS,
    exact_daily_log_return,
    value_at_day_offset,
)
from ddvc.analysis.lp_concentration import candidate_capital_changes
from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered_named
from ddvc.asset_types import VEHICLE_CANDIDATE_SYMBOLS
from ddvc.capital_contracts import VALID_CAPITAL_STATUSES
from ddvc.capital_release import resolve_capital_release

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

from ddvc.paper_tables import _int, _num, _p, _write_table


VEHICLES = list(VEHICLE_CANDIDATE_SYMBOLS)
STABLES = {"USDC", "USDT", "DAI"}


def _ensure_dirs() -> None:
    (DATA / "empirical").mkdir(parents=True, exist_ok=True)
    EMP.mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(parents=True, exist_ok=True)


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
        "direct_cost_advantage",
    ]
    r = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet", columns=cols)
    r = r[r["trade_size_usd"].astype(float).eq(float(trade_size))].copy()
    r["date"] = pd.to_datetime(r["date"])
    r["token"] = r["vehicle_sym"].astype(str)
    r["pair"] = r["src"].astype(str) + "->" + r["tgt"].astype(str)
    r["direct_available"] = r["direct_available"].astype(bool)
    r["vehicle_available"] = r["vehicle_available"].astype(bool)
    r["both_available"] = (
        r["direct_available"]
        & r["vehicle_available"]
        & r["direct_cost_advantage"].notna()
    )
    r["no_direct_vehicle_available"] = (~r["direct_available"]) & r["vehicle_available"]
    r["direct_quote_quality"] = np.where(r["direct_available"], r["direct_output_usd"].astype(float) / float(trade_size), np.nan)
    r["thin_direct"] = r["direct_available"] & (r["direct_quote_quality"] < 0.90)
    r["direct_cost_advantage_winsor"] = r["direct_cost_advantage"].astype(float).clip(-1, 1)
    grouped = r.groupby(["date", "token"], as_index=False)
    out = grouped.agg(
        quote_rows=("pair", "size"),
        pair_days=("pair", "nunique"),
        direct_available_share=("direct_available", "mean"),
        vehicle_available_share=("vehicle_available", "mean"),
        no_direct_vehicle_available_share=("no_direct_vehicle_available", "mean"),
        both_available_rows=("both_available", "sum"),
        direct_cost_advantage_median=("direct_cost_advantage", "median"),
        direct_cost_advantage_winsor_mean=("direct_cost_advantage_winsor", "mean"),
        vehicle_beats_direct_share=(
            "direct_cost_advantage",
            lambda x: float((x < 0).mean()) if x.notna().any() else math.nan,
        ),
        direct_quote_quality_median=("direct_quote_quality", "median"),
        thin_direct_share=("thin_direct", "mean"),
    )
    return out


def core_token_day_panel() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet")
    bridge["date"] = pd.to_datetime(bridge["date"])
    bridge = bridge[bridge["token"].isin(VEHICLES)].copy()
    rc = route_cost_daily(10_000.0)
    d = bridge.merge(rc, on=["date", "token"], how="left")
    d = d.sort_values(["token", "date"])
    for h in CANONICAL_RESPONSE_HORIZONS:
        d[f"lag_BridgeShare_t{h}"] = value_at_day_offset(d, "BridgeShare", -h)
        d[f"future_BridgeShare_t{h}"] = value_at_day_offset(d, "BridgeShare", h)
        d[f"delta_BridgeShare_t{h}"] = d["BridgeShare"] - d[f"lag_BridgeShare_t{h}"]
    out_path = DATA / "empirical" / "core_token_day_panel.parquet"
    d.to_parquet(out_path, index=False)
    return d


def core_panel_regressions(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    specs = [
        ("RQ1/RQ3", "future_BridgeShare_t7", "VehicleShare", 7),
        ("RQ1/RQ3", "future_BridgeShare_t30", "VehicleShare", 30),
    ]
    x_names = [
        "BridgeShare",
        "direct_cost_advantage_median",
        "no_direct_vehicle_available_share",
        "direct_available_share",
        "vehicle_available_share",
    ]
    for rq, y_name, label, horizon in specs:
        dd = panel.copy()
        y = absorb_fixed_effects(dd[y_name], dd["token"], dd["date"])
        x = pd.DataFrame({name: absorb_fixed_effects(dd[name], dd["token"], dd["date"]) for name in x_names})
        n, clusters, res = ols_clustered_named(y, x, dd["date"], absorbed_groups=(dd["token"], dd["date"]), min_observations=30)
        for name in x_names:
            rows.append(
                {
                    "RQ": rq,
                    "Outcome": label,
                    "Horizon (days)": horizon,
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
    out.to_pickle(EMP / "core_panel_regressions.pkl")
    return out


def persistence_displacement_thresholds(panel: pd.DataFrame) -> pd.DataFrame:
    d = panel.dropna(
        subset=["BridgeShare", "direct_cost_advantage_median", "future_BridgeShare_t30"]
    ).copy()
    idx = d.groupby("date")["BridgeShare"].idxmax()
    inc = d.loc[idx].copy()
    best_alt = (
        d.loc[~d.index.isin(idx)]
        .groupby("date")["direct_cost_advantage_median"]
        .min()
        .rename("best_challenger_direct_cost_advantage")
    )
    inc = inc.merge(best_alt, on="date", how="left")
    inc["challenger_cost_edge"] = (
        inc["direct_cost_advantage_median"]
        - inc["best_challenger_direct_cost_advantage"]
    )
    inc["future_share_change_pp"] = 100.0 * (inc["future_BridgeShare_t30"] - inc["BridgeShare"])
    bins = [-np.inf, 0, 0.0025, 0.01, 0.025, np.inf]
    labels = [
        "challenger <= incumbent",
        "0 to 0.0025",
        "0.0025 to 0.01",
        "0.01 to 0.025",
        ">0.025",
    ]
    inc["Challenger cost-edge bin"] = pd.cut(
        inc["challenger_cost_edge"], bins=bins, labels=labels
    )
    rows = []
    for label, g in inc.groupby("Challenger cost-edge bin", observed=False):
        y = g["future_share_change_pp"].replace([np.inf, -np.inf], np.nan).dropna()
        if len(y) > 1:
            t, p = stats.ttest_1samp(y.to_numpy(float), 0.0, nan_policy="omit")
        else:
            t, p = math.nan, math.nan
        rows.append(
            {
                "Challenger cost-edge bin": str(label),
                "Incumbent days": _int(len(y)),
                "Horizon (days)": 30,
                "Mean challenger cost edge (fraction)": _num(g["challenger_cost_edge"].mean(), 4),
                "Median challenger cost edge (fraction)": _num(g["challenger_cost_edge"].median(), 4),
                "Mean incumbent VehicleShare change (pp)": _num(y.mean(), 2),
                "t": _num(t, 2),
                "p": _p(p),
                "Interpretation": "incumbent displacement threshold screen",
            }
        )
    out = pd.DataFrame(rows)
    out.to_pickle(EMP / "persistence_thresholds.pkl")
    _write_table(
        out,
        "table_m10_persistence_thresholds",
        "Incumbent vehicle displacement by challenger route-cost edge.",
        "tab:persistence-thresholds",
        note="Incumbent is the highest-BridgeShare vehicle on day t. Challenger cost edge is incumbent DirectCostAdvantage minus the minimum non-incumbent DirectCostAdvantage at $10k, so positive values favor the challenger. Outcome is incumbent BridgeShare change over 30 days.",
    )
    return out


def stress_event_time() -> pd.DataFrame:
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet")
    bridge["date"] = pd.to_datetime(bridge["date"])
    wide = bridge.pivot(index="date", columns="token", values="BridgeShare").sort_index()
    wide["stable_share"] = wide[[c for c in STABLES if c in wide.columns]].sum(axis=1)
    wide["weth_minus_stable"] = wide["WETH"] - wide["stable_share"]
    events = pd.read_pickle(EMP / "stress_event_definition.pkl")
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
    ev.to_pickle(EMP / "stress_event_time_daily.pkl")
    out.to_pickle(EMP / "stress_event_time.pkl")
    _write_table(
        out,
        "table_m11_stress_event_time",
        "Stress rotation event-time summary.",
        "tab:stress-event-time",
        note="Effects are relative to each event's prior 28-day baseline. The table separates same-day rotation from post-event persistence.",
    )
    return out


def load_pool_candidate_capital() -> pd.DataFrame:
    """Load the canonical pool-candidate deposited-capital panel, never provider raw."""

    candidate_path = resolve_capital_release().artifacts["candidate"]
    columns = [
        "venue",
        "day",
        "pool",
        "pool_candidate_id",
        "candidate",
        "candidate_address",
        "candidate_symbol_raw",
        "candidate_capital_usd",
        "candidate_capital_usd_lagged",
        "quantity_kind",
        "capital_validation_status",
        "exact_lag_valid",
    ]
    out = pd.read_parquet(candidate_path, columns=columns)
    invalid_kind = set(out["quantity_kind"].dropna().astype(str)) - {"deposited_capital"}
    invalid_status = (
        set(out["capital_validation_status"].dropna().astype(str))
        - VALID_CAPITAL_STATUSES
    )
    capital = pd.to_numeric(out["candidate_capital_usd"], errors="coerce")
    lagged = pd.to_numeric(out["candidate_capital_usd_lagged"], errors="coerce")
    invalid_lag = out["exact_lag_valid"].fillna(False) & ~(
        np.isfinite(lagged) & lagged.gt(0)
    )
    if (
        invalid_kind
        or invalid_status
        or invalid_lag.any()
        or not (np.isfinite(capital) & capital.gt(0)).all()
    ):
        raise ValueError(
            "candidate-capital panel contains an invalid quantity kind, validation status, or value"
        )
    out["date"] = pd.to_datetime(out.pop("day"), format="%Y%m%d", errors="raise")
    out = out.rename(
        columns={
            "venue": "dex",
            "pool": "pool_id",
            "pool_candidate_id": "pool_vehicle_id",
            "candidate": "vehicle",
            "candidate_address": "vehicle_address",
            "candidate_symbol_raw": "vehicle_symbol_raw",
        }
    )
    if out.duplicated(["pool_vehicle_id", "date"]).any():
        raise ValueError("duplicate pool-candidate-day capital rows")
    return out.sort_values(["pool_vehicle_id", "date"]).reset_index(drop=True)


def common_pool_capital_tests(pool: pd.DataFrame) -> pd.DataFrame:
    d = pool.copy()
    d = d[d["vehicle"].isin(VEHICLES)].copy()
    d = d.sort_values(["pool_vehicle_id", "date"])
    d = candidate_capital_changes(d)
    counts = d.groupby("pool_vehicle_id")["dlog_capital"].transform("count")
    d = d[(counts >= 60) & d["dlog_capital"].notna()].copy()
    grp_date = d.groupby("date")["dlog_capital"]
    d["market_sum"] = grp_date.transform("sum")
    d["market_n"] = grp_date.transform("count")
    grp_vehicle = d.groupby(["date", "vehicle"])["dlog_capital"]
    d["vehicle_sum"] = grp_vehicle.transform("sum")
    d["vehicle_n"] = grp_vehicle.transform("count")
    d["market_capital_factor_loo"] = (d["market_sum"] - d["dlog_capital"]) / (d["market_n"] - 1)
    d["vehicle_capital_factor_loo"] = (d["vehicle_sum"] - d["dlog_capital"]) / (d["vehicle_n"] - 1)
    d = d[(d["market_n"] >= 25) & (d["vehicle_n"] >= 10)].copy()
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "token", "weth_price"])
    weth = bridge[bridge["token"].eq("WETH")][["date", "weth_price"]].copy()
    weth["date"] = pd.to_datetime(weth["date"])
    weth = weth.sort_values("date")
    weth["downside_stress"] = (-exact_daily_log_return(weth, "weth_price")).clip(lower=0)
    weth["stress_dummy"] = (
        weth["downside_stress"].ge(0.08).astype(float).where(weth["downside_stress"].notna())
    )
    d = d.merge(weth[["date", "stress_dummy"]], on="date", how="left")
    d["vehicle_capital_factor_x_stress"] = d["vehicle_capital_factor_loo"] * d["stress_dummy"]
    d["post_v3"] = (d["date"] >= pd.Timestamp("2021-05-05")).astype(float)
    d["vehicle_capital_factor_x_post_v3"] = d["vehicle_capital_factor_loo"] * d["post_v3"]
    d.to_parquet(DATA / "empirical" / "common_pool_capital_panel.parquet", index=False)
    rows = []
    specs = [
        ("Full sample", ["market_capital_factor_loo", "vehicle_capital_factor_loo"]),
        ("Stress interaction", ["market_capital_factor_loo", "vehicle_capital_factor_loo", "stress_dummy", "vehicle_capital_factor_x_stress"]),
        ("Post-V3 interaction", ["market_capital_factor_loo", "vehicle_capital_factor_loo", "post_v3", "vehicle_capital_factor_x_post_v3"]),
    ]
    for sample, names in specs:
        dd = d.copy()
        y = absorb_fixed_effects(dd["dlog_capital"], dd["pool_vehicle_id"])
        x = pd.DataFrame({name: absorb_fixed_effects(dd[name], dd["pool_vehicle_id"]) for name in names})
        n, clusters, res = ols_clustered_named(y, x, dd["date"], absorbed_groups=(dd["pool_vehicle_id"],), min_observations=30)
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
    out.to_pickle(EMP / "common_pool_capital.pkl")
    _write_table(
        out,
        "table_m12_common_pool_capital",
        "Vehicle-linked commonality in deposited pool capital.",
        "tab:common-pool-capital",
        note="Dependent variable is the daily log change in deposited capital allocated once across candidate sides. Market and vehicle factors are leave-one-out averages, so the pool's own capital change is excluded from its factors.",
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
        "direct_cost_advantage",
    ]
    r = pd.read_parquet(DATA / "empirical" / "route_cost_panel_v2.parquet", columns=cols)
    r = r[r["trade_size_usd"].astype(float).eq(10_000.0)].copy()
    r["date"] = pd.to_datetime(r["date"])
    r["pair"] = r["src_sym"].astype(str) + "->" + r["tgt_sym"].astype(str)
    r["vehicle"] = r["vehicle_sym"].astype(str)
    r["direct_cost_advantage"] = r["direct_cost_advantage"].astype(float).clip(-2, 2)
    r["vehicle_available"] = r["vehicle_available"].astype(float)
    r["direct_available"] = r["direct_available"].astype(float)
    r["vehicle_quote_quality"] = (r["vehicle_output_usd"].astype(float) / r["trade_size_usd"].astype(float)).replace(
        [np.inf, -np.inf], np.nan
    ).clip(0, 2)
    r["direct_quote_quality"] = (r["direct_output_usd"].astype(float) / r["trade_size_usd"].astype(float)).replace(
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
    x_names = ["direct_cost_advantage", "vehicle_available", "vehicle_quote_quality"]
    for outcome, y_raw, units in specs:
        y = absorb_fixed_effects(y_raw, d["pair_date"])
        x = pd.DataFrame({name: absorb_fixed_effects(d[name], d["pair_date"]) for name in x_names})
        n, clusters, res = ols_clustered_named(y, x, d["date"], absorbed_groups=(d["pair_date"],), min_observations=30)
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
    out.to_pickle(EMP / "actual_route_choice.pkl")
    _write_table(
        out,
        "table_m13_actual_route_choice",
        "Actual pair-candidate indirect-route choice and route economics.",
        "tab:actual-route-choice",
        note="Actual vehicle shares are reconstructed from unified transaction routes. Regressions compare candidate vehicles within the same endpoint pair and date.",
    )
    return out


def pair_challenger_displacement_tests(actual: pd.DataFrame) -> pd.DataFrame:
    shares = _actual_pair_vehicle_shares(actual)
    r = _route_cost_10k()
    d = r.merge(
        shares[["date", "pair", "vehicle", "actual_vehicle_share"]],
        on=["date", "pair", "vehicle"],
        how="inner",
    ).dropna(subset=["actual_vehicle_share", "direct_cost_advantage"])
    idx = d.groupby(["pair", "date"])["actual_vehicle_share"].idxmax()
    inc = d.loc[idx].copy().rename(
        columns={
            "vehicle": "incumbent",
            "actual_vehicle_share": "incumbent_share_t0",
            "direct_cost_advantage": "incumbent_direct_cost_advantage",
        }
    )
    alt = (
        d.loc[~d.index.isin(idx)]
        .sort_values("direct_cost_advantage")
        .groupby(["pair", "date"])
        .head(1)[["pair", "date", "vehicle", "direct_cost_advantage", "actual_vehicle_share"]]
        .rename(
            columns={
                "vehicle": "challenger",
                "direct_cost_advantage": "challenger_direct_cost_advantage",
                "actual_vehicle_share": "challenger_share_t0",
            }
        )
    )
    base = inc.merge(alt, on=["pair", "date"])
    base["challenger_cost_edge"] = (
        base["incumbent_direct_cost_advantage"]
        - base["challenger_direct_cost_advantage"]
    )
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
        ("Challenger VehicleShare change", "challenger_delta_t30_pp", "pp"),
        ("Incumbent VehicleShare change", "incumbent_delta_t30_pp", "pp"),
        ("Challenger exceeds incumbent", "challenger_beats_incumbent_t30_pp", "pp"),
    ]:
        y = absorb_fixed_effects(base[y_name], base["pair"], base["date"])
        x = pd.DataFrame(
            {
                "challenger_cost_edge": absorb_fixed_effects(
                    base["challenger_cost_edge"], base["pair"], base["date"]
                )
            }
        )
        n, clusters, res = ols_clustered_named(y, x, base["date"], absorbed_groups=(base["pair"], base["date"]), min_observations=30)
        rows.append(
            {
                "Panel": "A. Pair-level regression",
                "Outcome": outcome,
                "Horizon (days)": 30,
                "Challenger edge bin": "",
                "N": _int(n),
                "Date clusters": _int(clusters),
                "Mean edge (fraction)": "",
                "Mean outcome": "",
                "Beta": _num(res["challenger_cost_edge_beta"], 4),
                "t": _num(res["challenger_cost_edge_t"], 2),
                "p": _p(res["challenger_cost_edge_p"]),
                "Units": f"{units} per unit fraction",
            }
        )

    base["edge_bin"] = pd.cut(
        base["challenger_cost_edge"],
        bins=[-np.inf, 0, 0.0025, 0.01, 0.025, np.inf],
        labels=[
            "challenger <= incumbent",
            "0 to 0.0025",
            "0.0025 to 0.01",
            "0.01 to 0.025",
            ">0.025",
        ],
    )
    bins = base.groupby("edge_bin", observed=False).agg(
        N=("challenger_cost_edge", "count"),
        edge=("challenger_cost_edge", "mean"),
        challenger_delta=("challenger_delta_t30_pp", "mean"),
        incumbent_delta=("incumbent_delta_t30_pp", "mean"),
        beat=("challenger_beats_incumbent_t30_pp", "mean"),
    )
    for label, rbin in bins.iterrows():
        rows.append(
            {
                "Panel": "B. Edge-bin means",
                "Outcome": "Challenger / incumbent displacement",
                "Horizon (days)": 30,
                "Challenger edge bin": str(label),
                "N": _int(rbin["N"]),
                "Date clusters": "",
                "Mean edge (fraction)": _num(rbin["edge"], 4),
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
    out.to_pickle(EMP / "pair_challenger_displacement.pkl")
    _write_table(
        out,
        "table_m15_pair_challenger_displacement",
        "Actual pair-level challenger displacement by route-cost edge.",
        "tab:pair-challenger-displacement",
        note="The incumbent is the highest actual-share vehicle for the endpoint pair and date. The challenger is the non-incumbent candidate with minimum DirectCostAdvantage at $10k. The cost edge is incumbent minus challenger DirectCostAdvantage, so positive values favor the challenger.",
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
        ("DirectQuoteQuality", "direct_quote_quality", 1.0, "ratio"),
    ]
    for quartile, g in d.groupby("Pre-V3 direct availability quartile", observed=False):
        for outcome, y_col, scale, units in outcomes:
            y = absorb_fixed_effects(scale * g[y_col].astype(float), g["pair"])
            x = pd.DataFrame({"post_v3": absorb_fixed_effects(g["post_v3"], g["pair"])})
            n, clusters, res = ols_clustered_named(y, x, g["pair"], absorbed_groups=(g["pair"],), min_observations=30)
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
    out.to_pickle(EMP / "v3_dose_response.pkl")
    _write_table(
        out,
        "table_m16_v3_dose_response",
        "Uniswap V3 architecture dose response by pre-V3 direct-market weakness.",
        "tab:v3-dose-response",
        note="Quartiles are formed from pre-V3 direct-route availability for the same endpoint pairs. Estimates compare one year before and after the May 5, 2021 V3 launch.",
    )
    return out


def common_pool_capital_heterogeneity_tests() -> pd.DataFrame:
    d = pd.read_parquet(DATA / "empirical" / "common_pool_capital_panel.parquet")
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["token", "BridgeShare"])
    vehicle_avg = bridge.groupby("token")["BridgeShare"].mean()
    cutoff = vehicle_avg.median()
    d["high_vehicle_dependence"] = d["vehicle"].map(lambda v: vehicle_avg.get(v, 0.0) >= cutoff)
    mean_pool_capital = d.groupby("pool_vehicle_id")["candidate_capital_usd"].transform("mean")
    top1_cutoff = mean_pool_capital.quantile(0.99)
    samples = [
        ("High average VehicleShare vehicles", d[d["high_vehicle_dependence"]].copy()),
        ("Low average VehicleShare vehicles", d[~d["high_vehicle_dependence"]].copy()),
        ("Excluding top 1% mean-capital pools", d[mean_pool_capital <= top1_cutoff].copy()),
    ]
    rows = []
    for sample, g in samples:
        y = absorb_fixed_effects(g["dlog_capital"], g["pool_vehicle_id"])
        x = pd.DataFrame(
            {
                "market_capital_factor_loo": absorb_fixed_effects(g["market_capital_factor_loo"], g["pool_vehicle_id"]),
                "vehicle_capital_factor_loo": absorb_fixed_effects(g["vehicle_capital_factor_loo"], g["pool_vehicle_id"]),
            }
        )
        n, clusters, res = ols_clustered_named(y, x, g["date"], absorbed_groups=(g["pool_vehicle_id"],), min_observations=30)
        for name in ["market_capital_factor_loo", "vehicle_capital_factor_loo"]:
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
    out.to_pickle(EMP / "common_pool_capital_heterogeneity.pkl")
    _write_table(
        out,
        "table_m18_common_pool_capital_heterogeneity",
        "Common deposited-capital heterogeneity by vehicle dependence.",
        "tab:common-pool-capital-heterogeneity",
        note="High/low vehicle dependence is based on whether the vehicle token's average BridgeShare is above the vehicle-set median. The top-pool robustness excludes the top 1% of pools by mean deposited capital.",
    )
    return out


def main() -> int:
    _ensure_dirs()
    panel = core_token_day_panel()
    core_panel_regressions(panel)
    persistence_displacement_thresholds(panel)
    stress_event_time()
    pool = load_pool_candidate_capital()
    common_pool_capital_tests(pool)
    actual = build_pair_vehicle_actual_daily()
    actual_route_choice_tests(actual)
    pair_challenger_displacement_tests(actual)
    v3_dose_response_tests()
    common_pool_capital_heterogeneity_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

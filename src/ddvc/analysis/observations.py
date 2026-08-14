"""Utilities for building the canonical wide observations table.

The runnable script lives at scripts/process/build_observations_table.py. This
module holds the importable functions so scripts stay as direct execution
wrappers rather than libraries.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ddvc.analysis.dynamics import (
    CANONICAL_RESPONSE_HORIZONS,
    daily_price_risk_features,
    value_at_day_offset,
)
from ddvc.paths import DATA_DIR
from ddvc.variable_registry import OBSERVATIONS_TABLE_COLUMNS


DEFAULT_VEHICLES = ("WETH", "USDC", "USDT", "DAI", "WBTC")
DEFAULT_TRADE_SIZE = 10_000.0
TRADE_SIZE_SUFFIXES = {
    1_000.0: "q1k",
    10_000.0: "q10k",
    100_000.0: "q100k",
}
STABLES = {"USDC", "USDT", "DAI"}


def _require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Required input is missing: {path}")
    return path


def _as_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def _metric_volume_share_column(path: Path) -> str:
    """Return the current metric column, accepting pre-rename data files."""

    columns = set(pq.read_schema(path).names)
    if "VolShare" in columns:
        return "VolShare"
    if "VShare" in columns:
        return "VShare"
    raise ValueError(f"Metric file has no volume-share column: {path}")


def _read_bridge_daily(data: Path, vehicles: tuple[str, ...]) -> pd.DataFrame:
    bridge = pd.read_parquet(_require(data / "empirical" / "bridge_daily.parquet"))
    bridge = bridge[bridge["token"].isin(vehicles)].copy()
    bridge["date"] = _as_date(bridge["date"])
    bridge = bridge.rename(
        columns={
            "BridgeShare": "bridge_share",
            "BridgeCountShare": "bridge_count_share",
            "PairCoverage": "pair_coverage",
            "PairMainVehicleShare": "pair_main_vehicle_share",
        }
    )
    keep = [
        "date",
        "token",
        "bridge_volume_usd",
        "bridge_count",
        "bridge_share",
        "bridge_count_share",
        "pair_coverage",
        "pair_main_vehicle_share",
        "indirect_route_volume_usd",
        "indirect_route_count",
        "indirect_pair_count",
        "weth_price",
    ]
    return bridge[keep].sort_values(["token", "date"])


def _read_route_denominators(data: Path) -> pd.DataFrame:
    route = pd.read_parquet(_require(data / "empirical" / "route_denominator_daily.parquet")).copy()
    route["date"] = _as_date(route["date"])
    route = route.rename(
        columns={
            "all_route_volume_usd": "daily_all_route_volume_usd",
            "direct_route_volume_usd": "daily_direct_route_volume_usd",
            "indirect_route_volume_usd": "daily_indirect_route_volume_usd",
            "all_route_count": "daily_all_route_count",
            "direct_route_count": "daily_direct_route_count",
            "indirect_route_count": "daily_indirect_route_count",
        }
    )
    keep = [
        "date",
        "daily_all_route_volume_usd",
        "daily_direct_route_volume_usd",
        "daily_indirect_route_volume_usd",
        "daily_all_route_count",
        "daily_direct_route_count",
        "daily_indirect_route_count",
        "direct_route_share",
        "indirect_route_share",
    ]
    return route[keep].sort_values("date")


def _read_metrics(data: Path, vehicles: tuple[str, ...]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    metrics_dir = _require(data / "metrics")
    files = sorted(path for path in metrics_dir.glob("*.parquet") if path.stem.isdigit() and len(path.stem) == 8)
    for i, path in enumerate(files, start=1):
        volume_share_column = _metric_volume_share_column(path)
        day = pd.read_parquet(
            path,
            columns=[
                "token_address",
                "date",
                volume_share_column,
                "EigenCent",
                "BetwCent",
                "BetwCent_V",
            ],
        )
        day = day[day["token_address"].isin(vehicles)].copy()
        if day.empty:
            continue
        day = day.rename(
            columns={
                "token_address": "token",
                volume_share_column: "vol_share",
                "EigenCent": "eigen_centrality",
                "BetwCent": "betweenness_centrality",
                "BetwCent_V": "volume_weighted_betweenness",
            }
        )
        day["date"] = _as_date(day["date"])
        rows.append(day)
        if i % 500 == 0:
            print(f"metrics scan [{i}/{len(files)}] {path.stem}", flush=True)
    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "token",
                "vol_share",
                "eigen_centrality",
                "betweenness_centrality",
                "volume_weighted_betweenness",
            ]
        )
    out = pd.concat(rows, ignore_index=True)
    keep = [
        "date",
        "token",
        "vol_share",
        "eigen_centrality",
        "betweenness_centrality",
        "volume_weighted_betweenness",
    ]
    return out[keep].sort_values(["token", "date"])


def _read_lp_capital(data: Path, vehicles: tuple[str, ...]) -> pd.DataFrame:
    lp = pd.read_parquet(_require(data / "exhibits" / "lp_capital_concentration.parquet")).copy()
    lp = lp.rename(
        columns={
            "token_symbol": "token",
            "total_lp_capital_usd": "vehicle_linked_capital_usd",
        }
    )
    lp = lp[lp["token"].isin(vehicles)].copy()
    lp["date"] = _as_date(lp["date"])
    lp["log_vehicle_linked_capital"] = np.log1p(lp["vehicle_linked_capital_usd"].clip(lower=0))
    keep = [
        "date",
        "token",
        "token_address",
        "is_vehicle_candidate",
        "vehicle_linked_capital_usd",
        "lp_capital_share",
        "log_vehicle_linked_capital",
    ]
    return lp[keep].sort_values(["token", "date"])


def _indirect_beats_direct(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return math.nan
    return float((clean < 0).mean())


def _route_cost_by_size(data: Path, trade_size: float) -> pd.DataFrame:
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
    route = pd.read_parquet(_require(data / "empirical" / "route_cost_panel_v2.parquet"), columns=cols)
    route = route[route["trade_size_usd"].astype(float).eq(float(trade_size))].copy()
    route["date"] = _as_date(route["date"])
    route["token"] = route["vehicle_sym"].astype(str)
    route["pair"] = route["src"].astype(str) + "->" + route["tgt"].astype(str)
    route["direct_available"] = route["direct_available"].astype(bool)
    route["vehicle_available"] = route["vehicle_available"].astype(bool)
    route["both_available"] = (
        route["direct_available"]
        & route["vehicle_available"]
        & route["direct_cost_advantage"].notna()
    )
    route["no_direct_vehicle_available"] = (~route["direct_available"]) & route["vehicle_available"]
    route["direct_quote_quality"] = np.where(
        route["direct_available"],
        pd.to_numeric(route["direct_output_usd"], errors="coerce") / float(trade_size),
        np.nan,
    )
    route["thin_direct"] = route["direct_available"] & route["direct_quote_quality"].lt(0.90)
    route["direct_cost_advantage_winsor"] = pd.to_numeric(
        route["direct_cost_advantage"], errors="coerce"
    ).clip(lower=-1, upper=1)

    grouped = route.groupby(["date", "token"], as_index=False)
    out = grouped.agg(
        quote_rows=("pair", "size"),
        pair_days=("pair", "nunique"),
        direct_available_share=("direct_available", "mean"),
        vehicle_available_share=("vehicle_available", "mean"),
        no_direct_vehicle_available_share=("no_direct_vehicle_available", "mean"),
        both_available_rows=("both_available", "sum"),
        direct_cost_advantage_median=("direct_cost_advantage", "median"),
        direct_cost_advantage_winsor_mean=("direct_cost_advantage_winsor", "mean"),
        vehicle_beats_direct_share=("direct_cost_advantage", _indirect_beats_direct),
        direct_quote_quality_median=("direct_quote_quality", "median"),
        thin_direct_share=("thin_direct", "mean"),
    )
    return out


def _read_route_cost(data: Path, trade_sizes: tuple[float, ...], main_trade_size: float) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for size in trade_sizes:
        size_panel = _route_cost_by_size(data, size)
        suffix = TRADE_SIZE_SUFFIXES.get(float(size), f"q{int(size)}")
        rename = {
            col: f"{col}_{suffix}"
            for col in size_panel.columns
            if col not in {"date", "token"}
        }
        frames.append(size_panel.rename(columns=rename))

    if not frames:
        return pd.DataFrame(columns=["date", "token"])

    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on=["date", "token"], how="outer")

    main_suffix = TRADE_SIZE_SUFFIXES.get(float(main_trade_size), f"q{int(main_trade_size)}")
    for col in [
        "quote_rows",
        "pair_days",
        "direct_available_share",
        "vehicle_available_share",
        "no_direct_vehicle_available_share",
        "both_available_rows",
        "direct_cost_advantage_median",
        "direct_cost_advantage_winsor_mean",
        "vehicle_beats_direct_share",
        "direct_quote_quality_median",
        "thin_direct_share",
    ]:
        source = f"{col}_{main_suffix}"
        if source in out.columns:
            out[col] = out[source]
    return out.sort_values(["token", "date"])


def _add_stress(panel: pd.DataFrame) -> pd.DataFrame:
    weth = (
        panel.loc[panel["token"].eq("WETH"), ["date", "weth_price"]]
        .dropna()
        .drop_duplicates("date")
        .sort_values("date")
    )
    risk = daily_price_risk_features(weth, "weth_price")
    risk["stress_event_8pct"] = risk["stress_event_8pct"].astype("Float64")
    weth = risk.rename(
        columns={"log_return": "weth_log_return", "downside_stress": "stress_downside"}
    )
    return panel.merge(weth[["date", "weth_log_return", "stress_downside", "stress_event_8pct"]], on="date", how="left")


def _add_dynamics(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.sort_values(["token", "date"]).copy()
    dynamic_cols = [
        ("bridge_share", "bridge_share"),
        ("lp_capital_share", "lp_capital_share"),
        ("log_vehicle_linked_capital", "log_vehicle_linked_capital"),
        ("direct_cost_advantage_median", "direct_cost_advantage_median"),
    ]
    for h in CANONICAL_RESPONSE_HORIZONS:
        for base_col, stem in dynamic_cols:
            if base_col not in panel.columns:
                continue
            panel[f"lag_{stem}_t{h}"] = value_at_day_offset(panel, base_col, -h)
            panel[f"future_{stem}_t{h}"] = value_at_day_offset(panel, base_col, h)
        if "bridge_share" in panel.columns:
            panel[f"delta_bridge_share_t{h}"] = panel["bridge_share"] - panel[f"lag_bridge_share_t{h}"]
        if "lp_capital_share" in panel.columns:
            panel[f"delta_lp_capital_share_t{h}"] = (
                panel["lp_capital_share"] - panel[f"lag_lp_capital_share_t{h}"]
            )
    return panel


def build_observations_table(
    data: Path,
    output: Path,
    *,
    vehicles: tuple[str, ...] = DEFAULT_VEHICLES,
    trade_sizes: tuple[float, ...] = tuple(TRADE_SIZE_SUFFIXES),
    main_trade_size: float = DEFAULT_TRADE_SIZE,
) -> pd.DataFrame:
    bridge = _read_bridge_daily(data, vehicles)
    route = _read_route_denominators(data)
    metrics = _read_metrics(data, vehicles)
    lp = _read_lp_capital(data, vehicles)
    route_cost = _read_route_cost(data, trade_sizes, main_trade_size)
    panel = (
        bridge.merge(route, on="date", how="left")
        .merge(metrics, on=["date", "token"], how="left")
        .merge(lp, on=["date", "token"], how="left")
        .merge(route_cost, on=["date", "token"], how="left")
    )
    panel["all_route_bridge_share"] = panel["bridge_volume_usd"] / panel["daily_all_route_volume_usd"]
    panel["token_is_weth"] = panel["token"].eq("WETH").astype(float)
    panel["token_is_stable"] = panel["token"].isin(STABLES).astype(float)
    panel["year"] = panel["date"].dt.year
    panel["month"] = panel["date"].dt.to_period("M").astype(str)
    panel["has_indirect_routes"] = panel["daily_indirect_route_count"].fillna(0).gt(0).astype(float)
    panel["has_lp_observation"] = panel["lp_capital_share"].notna().astype(float)
    panel["has_route_cost_observation"] = panel["quote_rows"].fillna(0).gt(0).astype(float)
    panel = _add_stress(panel)
    panel = _add_dynamics(panel)

    missing_registry_columns = [col for col in OBSERVATIONS_TABLE_COLUMNS if col not in panel.columns]
    if missing_registry_columns:
        raise RuntimeError(f"Observations table is missing registered columns: {missing_registry_columns}")

    panel = panel.sort_values(["date", "token"]).reset_index(drop=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(output, index=False)
    return panel


DEFAULT_OBSERVATIONS_TABLE = DATA_DIR / "processed" / "observations_token_day.parquet"

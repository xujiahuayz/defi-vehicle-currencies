"""Realised vehicle routes and exact-hour matches to executable cost cells."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR

ROUTE_COLUMNS = [
    "tx_hash",
    "component_id",
    "source",
    "token_in",
    "token_out",
    "amount_usd",
    "log_index",
    "route_class",
    "tin_role",
    "tout_role",
    "timestamp_utc",
]
MATCH_KEYS = ["day", "hour", "src", "tgt", "vehicle"]


def cost_panel_days(connection: object, panel_path: Path) -> list[str]:
    """Calendar in a route-cost Parquet, read without materialising the panel."""
    rows = connection.execute(  # type: ignore[attr-defined]
        f"SELECT DISTINCT CAST(date AS DATE) FROM read_parquet('{panel_path.as_posix()}') ORDER BY 1"
    ).fetchall()
    return [row[0].strftime("%Y%m%d") for row in rows]


def read_cost_panel_day(
    connection: object, panel_path: Path, day: str
) -> pd.DataFrame:
    """Read one day's matching columns, relying on Parquet date pushdown."""
    observed = pd.to_datetime(day, format="%Y%m%d").date()
    return connection.execute(  # type: ignore[attr-defined]
        f"""
        SELECT CAST(date AS DATE) AS date, reserve_hour_utc, src, tgt, vehicle,
               trade_size_usd, direct_available, vehicle_available,
               direct_cost_advantage
        FROM read_parquet('{panel_path.as_posix()}')
        WHERE CAST(date AS DATE) = ?
        """,
        [observed],
    ).df()


def extract_realised_routes(legs: pd.DataFrame) -> pd.DataFrame:
    """Return one row per coherent route-intermediary, preserving transaction identity."""
    missing = sorted(set(ROUTE_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"realised routes are missing columns: {', '.join(missing)}")
    d = legs.loc[legs["route_class"].eq("coherent"), ROUTE_COLUMNS].copy()
    if d.empty:
        return pd.DataFrame()
    d = d.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    rows: list[dict[str, object]] = []
    for (tx_hash, component_id), group in d.groupby(
        ["tx_hash", "component_id"], sort=False
    ):
        if len(group) < 2:
            continue
        token_roles = pd.concat(
            [
                group[["token_in", "tin_role"]].rename(
                    columns={"token_in": "token", "tin_role": "role"}
                ),
                group[["token_out", "tout_role"]].rename(
                    columns={"token_out": "token", "tout_role": "role"}
                ),
            ],
            ignore_index=True,
        ).dropna(subset=["token"])
        sources = sorted(set(token_roles.loc[token_roles["role"].eq("source"), "token"]))
        sinks = sorted(set(token_roles.loc[token_roles["role"].eq("sink"), "token"]))
        if len(sources) != 1 or len(sinks) != 1 or sources[0] == sinks[0]:
            continue
        src, tgt = sources[0], sinks[0]
        vehicles = sorted(
            set(token_roles.loc[token_roles["role"].eq("intermediate"), "token"])
            - {src, tgt}
        )
        if not vehicles:
            continue
        timestamps = pd.to_numeric(group["timestamp_utc"], errors="coerce").dropna()
        amounts = pd.to_numeric(group["amount_usd"], errors="coerce").dropna()
        if timestamps.empty or amounts.empty or float(amounts.max()) <= 0:
            continue
        timestamp = int(timestamps.median())
        for vehicle in vehicles:
            route_id = f"{tx_hash}:{component_id}:{vehicle}"
            rows.append(
                {
                    "route_id": route_id,
                    "tx_hash": tx_hash,
                    "component_id": int(component_id),
                    "timestamp_utc": timestamp,
                    "hour": timestamp // 3600 % 24,
                    "src": src,
                    "tgt": tgt,
                    "vehicle": vehicle,
                    "usd": float(amounts.max()),
                    "legs": int(len(group)),
                    "venues": int(group["source"].nunique()),
                    "cross_venue": bool(group["source"].nunique() > 1),
                }
            )
    return pd.DataFrame(rows)


def realised_routes(
    day: str, unified_dir: Path = DATA_DIR / "unified"
) -> pd.DataFrame:
    """Load a UTC day and return its coherent non-cyclic vehicle routes."""
    path = unified_dir / f"{day}.parquet"
    if not path.exists():
        return pd.DataFrame()
    out = extract_realised_routes(pd.read_parquet(path, columns=ROUTE_COLUMNS))
    if not out.empty:
        out.insert(0, "day", day)
    return out


def match_realised_to_cost_panel(
    routes: pd.DataFrame, panel: pd.DataFrame
) -> pd.DataFrame:
    """Match routes to their exact UTC hour and nearest proportional notional."""
    route_required = set(MATCH_KEYS + ["route_id", "usd"])
    panel_required = set(
        [
            "date",
            "reserve_hour_utc",
            "src",
            "tgt",
            "vehicle",
            "trade_size_usd",
            "direct_available",
            "vehicle_available",
            "direct_cost_advantage",
        ]
    )
    missing_routes = sorted(route_required - set(routes.columns))
    missing_panel = sorted(panel_required - set(panel.columns))
    if missing_routes or missing_panel:
        details = []
        if missing_routes:
            details.append(f"routes: {', '.join(missing_routes)}")
        if missing_panel:
            details.append(f"panel: {', '.join(missing_panel)}")
        raise ValueError("matching inputs are missing " + "; ".join(details))
    if routes.empty:
        return routes.copy()

    costs = panel.copy()
    costs["day"] = pd.to_datetime(costs["date"]).dt.strftime("%Y%m%d")
    costs["hour"] = pd.to_numeric(costs["reserve_hour_utc"], errors="raise").astype(int)
    costs["trade_size_usd"] = pd.to_numeric(
        costs["trade_size_usd"], errors="coerce"
    )
    costs = costs[costs["trade_size_usd"].gt(0)].copy()
    cost_key = MATCH_KEYS + ["trade_size_usd"]
    duplicates = costs.duplicated(cost_key, keep=False)
    if duplicates.any():
        sample = costs.loc[duplicates, cost_key].iloc[0].to_dict()
        raise ValueError(f"cost panel has duplicate quote cells: {sample}")

    observed = routes.copy().reset_index(drop=True)
    observed["_route_row"] = observed.index
    observed["usd"] = pd.to_numeric(observed["usd"], errors="coerce")
    candidates = observed.merge(
        costs.drop(columns=["date", "reserve_hour_utc"]),
        on=MATCH_KEYS,
        how="left",
        sort=False,
    )
    candidates["log_size_gap"] = np.where(
        candidates["usd"].gt(0) & candidates["trade_size_usd"].gt(0),
        np.abs(np.log(candidates["trade_size_usd"] / candidates["usd"])),
        np.inf,
    )
    selected = (
        candidates.sort_values(
            ["_route_row", "log_size_gap", "trade_size_usd"], kind="stable"
        )
        .drop_duplicates("_route_row", keep="first")
        .sort_values("_route_row")
        .drop(columns="_route_row")
        .reset_index(drop=True)
    )
    matched = selected["trade_size_usd"].notna()
    direct = selected["direct_available"].fillna(False).astype(bool)
    vehicle = selected["vehicle_available"].fillna(False).astype(bool)
    selected["match_status"] = np.select(
        [
            ~matched,
            matched & ~direct & vehicle,
            matched & direct & vehicle,
            matched & direct & ~vehicle,
        ],
        [
            "no_cost_cell",
            "forced_no_direct",
            "chosen_with_direct",
            "vehicle_quote_unsupported",
        ],
        default="no_quote_support",
    )
    selected["quoted_to_realised_size"] = np.where(
        matched & selected["usd"].gt(0),
        selected["trade_size_usd"] / selected["usd"],
        np.nan,
    )
    selected["dominated"] = pd.NA
    comparable = selected["match_status"].eq("chosen_with_direct")
    selected.loc[comparable, "dominated"] = selected.loc[
        comparable, "direct_cost_advantage"
    ].gt(0)
    return selected

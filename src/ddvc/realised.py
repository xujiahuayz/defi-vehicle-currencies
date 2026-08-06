"""Realised vehicle routes and exact-hour matches to executable cost cells."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import canonical_token
from ddvc.paths import DATA_DIR
from ddvc.prices import PRICE_COLUMNS, day_prices

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
LINEAR_ROUTE_COLUMNS = list(dict.fromkeys([*ROUTE_COLUMNS, *PRICE_COLUMNS]))
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


def read_search_cost_panel_day(
    connection: object, panel_path: Path, day: str
) -> pd.DataFrame:
    """Read one day's vehicle-path frontier for routing-search diagnostics."""
    observed = pd.to_datetime(day, format="%Y%m%d").date()
    return connection.execute(  # type: ignore[attr-defined]
        f"""
        SELECT CAST(date AS DATE) AS date, reserve_hour_utc, src, tgt, vehicle,
               trade_size_usd, vehicle_available, vehicle_output_usd,
               hop1_source, hop2_source
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
    d["token_in"] = d["token_in"].map(lambda value: canonical_token(value) or "")
    d["token_out"] = d["token_out"].map(lambda value: canonical_token(value) or "")
    d = d[d["token_in"].astype(bool) & d["token_out"].astype(bool)]
    if d.empty:
        return pd.DataFrame()
    d = d.sort_values(["tx_hash", "component_id", "log_index"], kind="stable")
    d["_timestamp"] = pd.to_numeric(d["timestamp_utc"], errors="coerce")
    d["_usd"] = pd.to_numeric(d["amount_usd"], errors="coerce")
    component_keys = ["tx_hash", "component_id"]
    components = d.groupby(component_keys, as_index=False).agg(
        legs=("log_index", "size"),
        timestamp_utc=("_timestamp", "median"),
        usd=("_usd", "max"),
        venues=("source", "nunique"),
    )
    components = components[
        components["legs"].ge(2)
        & components["timestamp_utc"].notna()
        & components["usd"].gt(0)
    ]
    if components.empty:
        return pd.DataFrame()

    token_roles = pd.concat(
        [
            d[component_keys + ["token_in", "tin_role"]].rename(
                columns={"token_in": "token", "tin_role": "role"}
            ),
            d[component_keys + ["token_out", "tout_role"]].rename(
                columns={"token_out": "token", "tout_role": "role"}
            ),
        ],
        ignore_index=True,
    ).dropna(subset=["token"])
    token_roles = token_roles.drop_duplicates(component_keys + ["role", "token"])

    def endpoints(role: str, token_name: str, count_name: str) -> pd.DataFrame:
        return token_roles.loc[token_roles["role"].eq(role)].groupby(
            component_keys, as_index=False
        ).agg(**{token_name: ("token", "first"), count_name: ("token", "nunique")})

    components = components.merge(
        endpoints("source", "src", "source_tokens"), on=component_keys, how="inner"
    ).merge(
        endpoints("sink", "tgt", "sink_tokens"), on=component_keys, how="inner"
    )
    components = components[
        components["source_tokens"].eq(1)
        & components["sink_tokens"].eq(1)
        & components["src"].ne(components["tgt"])
    ].drop(columns=["source_tokens", "sink_tokens"])
    vehicles = (
        token_roles.loc[
            token_roles["role"].eq("intermediate"), component_keys + ["token"]
        ]
        .rename(columns={"token": "vehicle"})
        .drop_duplicates()
    )
    out = components.merge(vehicles, on=component_keys, how="inner")
    out = out[out["vehicle"].ne(out["src"]) & out["vehicle"].ne(out["tgt"])]
    if out.empty:
        return pd.DataFrame()
    out = out.sort_values(component_keys + ["vehicle"], kind="stable").reset_index(drop=True)
    out["component_id"] = pd.to_numeric(out["component_id"], errors="raise").astype(int)
    out["timestamp_utc"] = out["timestamp_utc"].astype(int)
    out["hour"] = out["timestamp_utc"].floordiv(3600).mod(24)
    out["usd"] = out["usd"].astype(float)
    out["legs"] = out["legs"].astype(int)
    out["venues"] = out["venues"].astype(int)
    out["cross_venue"] = out["venues"].gt(1)
    out.insert(
        0,
        "route_id",
        out["tx_hash"].astype(str)
        + ":"
        + out["component_id"].astype(str)
        + ":"
        + out["vehicle"].astype(str),
    )
    return out[
        [
            "route_id",
            "tx_hash",
            "component_id",
            "timestamp_utc",
            "hour",
            "src",
            "tgt",
            "vehicle",
            "usd",
            "legs",
            "venues",
            "cross_venue",
        ]
    ]


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


def extract_linear_realised_routes(legs: pd.DataFrame) -> pd.DataFrame:
    """Return exact two-leg routes with realised input/output value and venue reach."""
    missing = sorted(set(LINEAR_ROUTE_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"linear realised routes are missing columns: {', '.join(missing)}")
    routes = extract_realised_routes(legs)
    if routes.empty:
        return pd.DataFrame()
    component_keys = ["tx_hash", "component_id"]
    vehicle_counts = routes.groupby(component_keys)["vehicle"].transform("size")
    routes = routes[routes["legs"].eq(2) & vehicle_counts.eq(1)].copy()
    if routes.empty:
        return pd.DataFrame()

    route_legs = legs.loc[
        legs["route_class"].eq("coherent"), LINEAR_ROUTE_COLUMNS
    ].copy()
    route_legs["token_in"] = route_legs["token_in"].map(
        lambda value: canonical_token(value) or ""
    )
    route_legs["token_out"] = route_legs["token_out"].map(
        lambda value: canonical_token(value) or ""
    )
    route_legs = route_legs[
        route_legs["token_in"].astype(bool) & route_legs["token_out"].astype(bool)
    ].sort_values(component_keys + ["log_index"], kind="stable")
    route_legs = route_legs.merge(
        routes[component_keys].drop_duplicates(), on=component_keys, how="inner"
    )
    first = route_legs.drop_duplicates(component_keys, keep="first").rename(
        columns={
            "source": "realised_hop1_source",
            "token_in": "first_token_in",
            "token_out": "first_token_out",
            "amount_in": "realised_amount_in",
        }
    )
    last = route_legs.drop_duplicates(component_keys, keep="last").rename(
        columns={
            "source": "realised_hop2_source",
            "token_in": "last_token_in",
            "token_out": "last_token_out",
            "amount_out": "realised_amount_out",
        }
    )
    out = routes.merge(
        first[
            component_keys
            + [
                "realised_hop1_source",
                "first_token_in",
                "first_token_out",
                "realised_amount_in",
            ]
        ],
        on=component_keys,
        how="inner",
    ).merge(
        last[
            component_keys
            + [
                "realised_hop2_source",
                "last_token_in",
                "last_token_out",
                "realised_amount_out",
            ]
        ],
        on=component_keys,
        how="inner",
    )
    out = out[
        out["first_token_in"].eq(out["src"])
        & out["first_token_out"].eq(out["vehicle"])
        & out["last_token_in"].eq(out["vehicle"])
        & out["last_token_out"].eq(out["tgt"])
    ].copy()
    price_legs = legs[PRICE_COLUMNS].copy()
    for column in ("token_in", "token_out"):
        price_legs[column] = price_legs[column].map(
            lambda value: canonical_token(value) or ""
        )
    prices = day_prices(price_legs)
    out["src_price_usd"] = out["src"].map(
        {token: value[1] for token, value in prices.items()}
    )
    out["tgt_price_usd"] = out["tgt"].map(
        {token: value[1] for token, value in prices.items()}
    )
    out["realised_amount_in"] = pd.to_numeric(
        out["realised_amount_in"], errors="coerce"
    )
    out["realised_amount_out"] = pd.to_numeric(
        out["realised_amount_out"], errors="coerce"
    )
    out["input_usd"] = out["realised_amount_in"] * out["src_price_usd"]
    out["output_usd"] = out["realised_amount_out"] * out["tgt_price_usd"]
    out = out[out["input_usd"].gt(0) & out["output_usd"].gt(0)].copy()
    first_source = out["realised_hop1_source"].astype(str)
    second_source = out["realised_hop2_source"].astype(str)
    out["venue_set"] = np.where(
        first_source.eq(second_source),
        first_source,
        np.where(
            first_source.lt(second_source),
            first_source + "|" + second_source,
            second_source + "|" + first_source,
        ),
    )
    out["realised_output_rate"] = out["output_usd"] / out["input_usd"]
    out["usd"] = out["input_usd"]
    return out.drop(
        columns=[
            "first_token_in",
            "first_token_out",
            "last_token_in",
            "last_token_out",
            "src_price_usd",
            "tgt_price_usd",
        ]
    ).reset_index(drop=True)


def linear_realised_routes(
    day: str, unified_dir: Path = DATA_DIR / "unified"
) -> pd.DataFrame:
    """Load one day of exact two-leg realised routes for search diagnostics."""
    path = unified_dir / f"{day}.parquet"
    if not path.exists():
        return pd.DataFrame()
    out = extract_linear_realised_routes(
        pd.read_parquet(path, columns=LINEAR_ROUTE_COLUMNS)
    )
    if not out.empty:
        out.insert(0, "day", day)
    return out


def match_within_vehicle_search_efficiency(
    routes: pd.DataFrame, panel: pd.DataFrame
) -> pd.DataFrame:
    """Compare execution with the same-vehicle frontier inside observed venue reach.

    This is a conservative diagnostic of pool and venue search conditional on
    the realised intermediary. It does not test whether another intermediary or
    a direct path would have produced more output.
    """
    route_required = set(
        MATCH_KEYS
        + [
            "route_id",
            "input_usd",
            "output_usd",
            "realised_output_rate",
            "realised_hop1_source",
            "realised_hop2_source",
        ]
    )
    panel_required = set(
        [
            "date",
            "reserve_hour_utc",
            "src",
            "tgt",
            "vehicle",
            "trade_size_usd",
            "vehicle_available",
            "vehicle_output_usd",
            "hop1_source",
            "hop2_source",
        ]
    )
    missing_routes = sorted(route_required - set(routes.columns))
    missing_panel = sorted(panel_required - set(panel.columns))
    if missing_routes or missing_panel:
        detail = []
        if missing_routes:
            detail.append(f"routes: {', '.join(missing_routes)}")
        if missing_panel:
            detail.append(f"panel: {', '.join(missing_panel)}")
        raise ValueError("search matching inputs are missing " + "; ".join(detail))
    if routes.empty:
        return routes.copy()

    costs = panel.copy()
    costs["day"] = pd.to_datetime(costs["date"]).dt.strftime("%Y%m%d")
    costs["hour"] = pd.to_numeric(
        costs["reserve_hour_utc"], errors="raise"
    ).astype(int)
    costs["trade_size_usd"] = pd.to_numeric(
        costs["trade_size_usd"], errors="coerce"
    )
    costs["vehicle_output_usd"] = pd.to_numeric(
        costs["vehicle_output_usd"], errors="coerce"
    )
    costs = costs[costs["trade_size_usd"].gt(0)].copy()
    cost_key = MATCH_KEYS + ["trade_size_usd"]
    duplicates = costs.duplicated(cost_key, keep=False)
    if duplicates.any():
        sample = costs.loc[duplicates, cost_key].iloc[0].to_dict()
        raise ValueError(f"cost panel has duplicate quote cells: {sample}")

    observed = routes.copy().reset_index(drop=True)
    observed["_route_row"] = observed.index
    observed["input_usd"] = pd.to_numeric(observed["input_usd"], errors="coerce")
    quote_columns = [
        "trade_size_usd",
        "vehicle_available",
        "vehicle_output_usd",
        "hop1_source",
        "hop2_source",
    ]
    candidates = observed[["_route_row", *MATCH_KEYS, "input_usd"]].merge(
        costs.drop(columns=["date", "reserve_hour_utc"]),
        on=MATCH_KEYS,
        how="left",
        sort=False,
    )
    candidates = candidates[candidates["trade_size_usd"].notna()]
    candidate_route_rows = set(candidates["_route_row"])
    lower = (
        candidates[candidates["trade_size_usd"].le(candidates["input_usd"])]
        .sort_values(["_route_row", "trade_size_usd"], ascending=[True, False])
        .drop_duplicates("_route_row")
        [["_route_row", *quote_columns]]
        .rename(columns={column: f"lower_{column}" for column in quote_columns})
    )
    upper = (
        candidates[candidates["trade_size_usd"].ge(candidates["input_usd"])]
        .sort_values(["_route_row", "trade_size_usd"], ascending=[True, True])
        .drop_duplicates("_route_row")
        [["_route_row", *quote_columns]]
        .rename(columns={column: f"upper_{column}" for column in quote_columns})
    )
    out = observed.merge(lower, on="_route_row", how="left").merge(
        upper, on="_route_row", how="left"
    )
    has_cost_cell = out["_route_row"].isin(candidate_route_rows)
    bounded = out["lower_trade_size_usd"].notna() & out[
        "upper_trade_size_usd"
    ].notna()
    supported = (
        bounded
        & out["lower_vehicle_available"].fillna(False).astype(bool)
        & out["upper_vehicle_available"].fillna(False).astype(bool)
        & out["lower_vehicle_output_usd"].gt(0)
        & out["upper_vehicle_output_usd"].gt(0)
    )

    def frontier_within_observed_reach(row: pd.Series) -> bool:
        observed_values = [
            row["realised_hop1_source"],
            row["realised_hop2_source"],
        ]
        quoted_values = [
            row[f"{bound}_{hop}_source"]
            for bound in ("lower", "upper")
            for hop in ("hop1", "hop2")
        ]
        if any(pd.isna(value) or not str(value).strip() for value in quoted_values):
            return False
        observed_sources = {str(value) for value in observed_values}
        quoted_sources = {str(value) for value in quoted_values}
        return quoted_sources.issubset(observed_sources)

    within_reach = pd.Series(False, index=out.index)
    within_reach.loc[supported] = out.loc[supported].apply(
        frontier_within_observed_reach, axis=1
    )
    out["search_match_status"] = np.select(
        [
            ~has_cost_cell,
            has_cost_cell & ~bounded,
            bounded & ~supported,
            supported & ~within_reach,
            supported & within_reach,
        ],
        [
            "no_cost_cell",
            "outside_quote_size_grid",
            "vehicle_frontier_unsupported",
            "frontier_outside_observed_venue_reach",
            "within_observed_venue_reach",
        ],
        default="invalid_search_match",
    )
    lower_log = np.log(out["lower_trade_size_usd"])
    upper_log = np.log(out["upper_trade_size_usd"])
    input_log = np.log(out["input_usd"])
    span = upper_log - lower_log
    interpolation_weight = np.where(
        span.abs().gt(1e-12), (input_log - lower_log) / span, 0.0
    )
    lower_rate = out["lower_vehicle_output_usd"] / out["lower_trade_size_usd"]
    upper_rate = out["upper_vehicle_output_usd"] / out["upper_trade_size_usd"]
    out["frontier_output_rate"] = lower_rate + interpolation_weight * (
        upper_rate - lower_rate
    )
    comparable = out["search_match_status"].eq("within_observed_venue_reach")
    out["search_shortfall"] = np.where(
        comparable & out["frontier_output_rate"].gt(0),
        1.0 - out["realised_output_rate"] / out["frontier_output_rate"],
        np.nan,
    )
    out["lower_size_ratio"] = out["lower_trade_size_usd"] / out["input_usd"]
    out["upper_size_ratio"] = out["upper_trade_size_usd"] / out["input_usd"]
    return out.drop(columns="_route_row")


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

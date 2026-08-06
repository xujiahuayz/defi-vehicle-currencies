"""Realised vehicle routes and exact-hour matches to executable cost cells."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ddvc.asset_types import canonical_token
from ddvc.paths import DATA_DIR
from ddvc.prices import PRICE_COLUMNS, day_prices
from ddvc.route_roles import component_eligibility, role_token_values

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
PAIR_MATCH_KEYS = ["day", "hour", "src", "tgt"]


def _same_nullable(left: pd.Series, right: pd.Series) -> pd.Series:
    """Compare path-identity fields while treating two missing values as equal."""
    return left.eq(right) | (left.isna() & right.isna())


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
               trade_size_usd, direct_available, direct_output_usd,
               direct_source, direct_pool, vehicle_available, vehicle_output_usd,
               hop1_source, hop1_pool, hop2_source, hop2_pool
        FROM read_parquet('{panel_path.as_posix()}')
        WHERE CAST(date AS DATE) = ?
        """,
        [observed],
    ).df()


def _normalise_search_costs(panel: pd.DataFrame) -> pd.DataFrame:
    """Normalise shared quote keys and enforce one row per vehicle cost cell."""
    costs = panel.copy()
    costs["day"] = pd.to_datetime(costs["date"]).dt.strftime("%Y%m%d")
    costs["hour"] = pd.to_numeric(
        costs["reserve_hour_utc"], errors="raise"
    ).astype(int)
    for column in (
        "trade_size_usd",
        "direct_output_usd",
        "vehicle_output_usd",
    ):
        if column in costs:
            costs[column] = pd.to_numeric(costs[column], errors="coerce")
    costs = costs[costs["trade_size_usd"].gt(0)].copy()
    cell_key = MATCH_KEYS + ["trade_size_usd"]
    duplicates = costs.duplicated(cell_key, keep=False)
    if duplicates.any():
        sample = costs.loc[duplicates, cell_key].iloc[0].to_dict()
        raise ValueError(f"cost panel has duplicate quote cells: {sample}")
    return costs


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
    d["amount_usd"] = d["_usd"]
    component_keys = ["tx_hash", "component_id"]
    components = d.groupby(component_keys, as_index=False).agg(
        legs=("log_index", "size"),
        timestamp_utc=("_timestamp", "median"),
        venues=("source", "nunique"),
    )
    components = components[
        components["legs"].ge(2)
        & components["timestamp_utc"].notna()
    ]
    if components.empty:
        return pd.DataFrame()

    eligibility = component_eligibility(d, keys=component_keys)
    components = components.merge(
        eligibility.eligible, on=component_keys, how="inner"
    ).drop(columns=["source_tokens", "sink_tokens"])
    vehicles = role_token_values(
        d,
        "intermediate",
        keys=component_keys,
        token_roles=eligibility.token_roles,
    ).rename(
        columns={"token": "vehicle", "amount_usd": "usd"}
    )
    vehicles = vehicles[vehicles["usd"].gt(0)]
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


def extract_linear_realised_routes(
    legs: pd.DataFrame,
    *,
    prices: dict[str, tuple[str, float]] | None = None,
) -> pd.DataFrame:
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
    if prices is None:
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
            "hop1_pool",
            "hop2_source",
            "hop2_pool",
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

    costs = _normalise_search_costs(panel)

    observed = routes.copy().reset_index(drop=True)
    observed["_route_row"] = observed.index
    observed["input_usd"] = pd.to_numeric(observed["input_usd"], errors="coerce")
    quote_columns = [
        "trade_size_usd",
        "vehicle_available",
        "vehicle_output_usd",
        "hop1_source",
        "hop1_pool",
        "hop2_source",
        "hop2_pool",
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
    out["search_frontier_path_switch"] = supported & ~(
        _same_nullable(out["lower_hop1_source"], out["upper_hop1_source"])
        & _same_nullable(out["lower_hop2_source"], out["upper_hop2_source"])
        & _same_nullable(out["lower_hop1_pool"], out["upper_hop1_pool"])
        & _same_nullable(out["lower_hop2_pool"], out["upper_hop2_pool"])
    )
    out["search_match_status"] = np.select(
        [
            ~has_cost_cell,
            has_cost_cell & ~bounded,
            bounded & ~supported,
            supported & ~within_reach,
            supported & within_reach & out["search_frontier_path_switch"],
            supported & within_reach & ~out["search_frontier_path_switch"],
        ],
        [
            "no_cost_cell",
            "outside_quote_size_grid",
            "vehicle_frontier_unsupported",
            "frontier_outside_observed_venue_reach",
            "frontier_switches_between_quote_sizes",
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
    out["interpolated_frontier_output_rate"] = lower_rate + interpolation_weight * (
        upper_rate - lower_rate
    )
    comparable = out["search_match_status"].eq("within_observed_venue_reach")
    out["search_shortfall"] = np.where(
        comparable & out["interpolated_frontier_output_rate"].gt(0),
        1.0
        - out["realised_output_rate"] / out["interpolated_frontier_output_rate"],
        np.nan,
    )
    out["lower_size_ratio"] = out["lower_trade_size_usd"] / out["input_usd"]
    out["upper_size_ratio"] = out["upper_trade_size_usd"] / out["input_usd"]
    return out.drop(columns="_route_row")


def match_observed_reach_path_efficiency(
    routes: pd.DataFrame, panel: pd.DataFrame
) -> pd.DataFrame:
    """Compare execution with the best path on the route's observed venues.

    The frontier includes direct paths and every candidate intermediary in the
    panel. Venue inclusion is observable; executor pool support is not, so this
    remains a venue-reach diagnostic until executor support can be recovered.
    """
    route_required = set(
        PAIR_MATCH_KEYS
        + [
            "route_id",
            "input_usd",
            "output_usd",
            "realised_output_rate",
            "realised_hop1_source",
            "realised_hop2_source",
        ]
    )
    panel_required = {
        "date",
        "reserve_hour_utc",
        "src",
        "tgt",
        "vehicle",
        "trade_size_usd",
        "direct_available",
        "direct_output_usd",
        "direct_source",
        "direct_pool",
        "vehicle_available",
        "vehicle_output_usd",
        "hop1_source",
        "hop1_pool",
        "hop2_source",
        "hop2_pool",
    }
    missing_routes = sorted(route_required - set(routes.columns))
    missing_panel = sorted(panel_required - set(panel.columns))
    if missing_routes or missing_panel:
        detail = []
        if missing_routes:
            detail.append(f"routes: {', '.join(missing_routes)}")
        if missing_panel:
            detail.append(f"panel: {', '.join(missing_panel)}")
        raise ValueError("path matching inputs are missing " + "; ".join(detail))
    if routes.empty:
        return routes.copy()

    costs = _normalise_search_costs(panel)

    pair_size_key = PAIR_MATCH_KEYS + ["trade_size_usd"]
    direct_contract = [
        "direct_available",
        "direct_output_usd",
        "direct_source",
        "direct_pool",
    ]
    direct_variation = costs.groupby(pair_size_key, dropna=False)[
        direct_contract
    ].nunique(dropna=False)
    if not direct_variation.empty and direct_variation.max(axis=1).gt(1).any():
        key = direct_variation.index[direct_variation.max(axis=1).gt(1)][0]
        sample = dict(zip(pair_size_key, key, strict=True))
        raise ValueError(f"direct frontier differs across vehicle rows: {sample}")

    vehicles = costs[
        pair_size_key
        + [
            "vehicle",
            "vehicle_available",
            "vehicle_output_usd",
            "hop1_source",
            "hop1_pool",
            "hop2_source",
            "hop2_pool",
        ]
    ].rename(
        columns={
            "vehicle": "frontier_vehicle",
            "vehicle_available": "path_available",
            "vehicle_output_usd": "path_output_usd",
            "hop1_source": "path_hop1_source",
            "hop1_pool": "path_hop1_pool",
            "hop2_source": "path_hop2_source",
            "hop2_pool": "path_hop2_pool",
        }
    )
    vehicles["frontier_path_type"] = "two_hop"
    direct = costs.drop_duplicates(pair_size_key)[
        pair_size_key + direct_contract
    ].rename(
        columns={
            "direct_available": "path_available",
            "direct_output_usd": "path_output_usd",
            "direct_source": "path_hop1_source",
            "direct_pool": "path_hop1_pool",
        }
    )
    direct["path_hop2_source"] = None
    direct["path_hop2_pool"] = None
    direct["frontier_vehicle"] = None
    direct["frontier_path_type"] = "direct"
    paths = pd.concat([direct, vehicles], ignore_index=True, sort=False)

    observed = routes.copy().reset_index(drop=True)
    observed["_route_row"] = observed.index
    observed["input_usd"] = pd.to_numeric(observed["input_usd"], errors="coerce")
    candidates = observed[
        [
            "_route_row",
            *PAIR_MATCH_KEYS,
            "input_usd",
            "realised_hop1_source",
            "realised_hop2_source",
        ]
    ].merge(paths, on=PAIR_MATCH_KEYS, how="left", sort=False)
    candidates = candidates[candidates["trade_size_usd"].notna()].copy()
    candidate_route_rows = set(candidates["_route_row"])
    first_reached = candidates["realised_hop1_source"].astype(str)
    second_reached = candidates["realised_hop2_source"].astype(str)
    hop1 = candidates["path_hop1_source"]
    hop2 = candidates["path_hop2_source"]
    hop1_reached = hop1.notna() & (
        hop1.astype(str).eq(first_reached) | hop1.astype(str).eq(second_reached)
    )
    hop2_reached = hop2.isna() | (
        hop2.astype(str).eq(first_reached) | hop2.astype(str).eq(second_reached)
    )
    available = (
        candidates["path_available"].fillna(False).astype(bool)
        & candidates["path_output_usd"].gt(0)
    )
    eligible = candidates[available & hop1_reached & hop2_reached].copy()
    eligible["path_output_rate"] = (
        eligible["path_output_usd"] / eligible["trade_size_usd"]
    )
    frontier_columns = [
        "trade_size_usd",
        "path_output_usd",
        "path_output_rate",
        "frontier_path_type",
        "frontier_vehicle",
        "path_hop1_source",
        "path_hop1_pool",
        "path_hop2_source",
        "path_hop2_pool",
    ]
    frontier = (
        eligible.sort_values(
            [
                "_route_row",
                "trade_size_usd",
                "path_output_rate",
                "frontier_path_type",
                "frontier_vehicle",
            ],
            ascending=[True, True, False, True, True],
            kind="stable",
            na_position="first",
        )
        .drop_duplicates(["_route_row", "trade_size_usd"])
    )
    lower = (
        frontier[frontier["trade_size_usd"].le(frontier["input_usd"])]
        .sort_values(["_route_row", "trade_size_usd"], ascending=[True, False])
        .drop_duplicates("_route_row")
        [["_route_row", *frontier_columns]]
        .rename(columns={column: f"lower_{column}" for column in frontier_columns})
    )
    upper = (
        frontier[frontier["trade_size_usd"].ge(frontier["input_usd"])]
        .sort_values(["_route_row", "trade_size_usd"], ascending=[True, True])
        .drop_duplicates("_route_row")
        [["_route_row", *frontier_columns]]
        .rename(columns={column: f"upper_{column}" for column in frontier_columns})
    )
    grid = candidates.groupby("_route_row")["trade_size_usd"].agg(
        grid_min="min",
        grid_max="max",
    )
    out = observed.merge(grid, on="_route_row", how="left").merge(
        lower, on="_route_row", how="left"
    ).merge(upper, on="_route_row", how="left")
    has_cost_cell = out["_route_row"].isin(candidate_route_rows)
    inside_grid = (
        has_cost_cell
        & out["input_usd"].ge(out["grid_min"])
        & out["input_usd"].le(out["grid_max"])
    )
    frontier_bounded = out["lower_trade_size_usd"].notna() & out[
        "upper_trade_size_usd"
    ].notna()
    identity_columns = [
        "frontier_path_type",
        "frontier_vehicle",
        "path_hop1_source",
        "path_hop1_pool",
        "path_hop2_source",
        "path_hop2_pool",
    ]
    same_path = pd.Series(True, index=out.index)
    for column in identity_columns:
        same_path &= _same_nullable(
            out[f"lower_{column}"], out[f"upper_{column}"]
        )
    out["path_frontier_switch"] = frontier_bounded & ~same_path
    out["path_match_status"] = np.select(
        [
            ~has_cost_cell,
            has_cost_cell & ~inside_grid,
            inside_grid & ~frontier_bounded,
            inside_grid & frontier_bounded & out["path_frontier_switch"],
            inside_grid & frontier_bounded & ~out["path_frontier_switch"],
        ],
        [
            "no_cost_cell",
            "outside_quote_size_grid",
            "frontier_unsupported_within_observed_reach",
            "frontier_switches_between_quote_sizes",
            "within_observed_venue_reach",
        ],
        default="invalid_path_match",
    )
    lower_log = np.log(out["lower_trade_size_usd"])
    upper_log = np.log(out["upper_trade_size_usd"])
    input_log = np.log(out["input_usd"])
    span = upper_log - lower_log
    interpolation_weight = np.where(
        span.abs().gt(1e-12), (input_log - lower_log) / span, 0.0
    )
    out["interpolated_path_frontier_output_rate"] = out[
        "lower_path_output_rate"
    ] + interpolation_weight * (
        out["upper_path_output_rate"] - out["lower_path_output_rate"]
    )
    comparable = out["path_match_status"].eq("within_observed_venue_reach")
    out["path_shortfall"] = np.where(
        comparable & out["interpolated_path_frontier_output_rate"].gt(0),
        1.0
        - out["realised_output_rate"]
        / out["interpolated_path_frontier_output_rate"],
        np.nan,
    )
    out["path_lower_size_ratio"] = out["lower_trade_size_usd"] / out["input_usd"]
    out["path_upper_size_ratio"] = out["upper_trade_size_usd"] / out["input_usd"]
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

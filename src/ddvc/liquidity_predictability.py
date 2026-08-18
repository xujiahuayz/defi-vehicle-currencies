"""Construct candidate-day liquidity predictability panels without estimation."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import nullcontext
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.capital_contracts import VALID_CAPITAL_STATUSES
from ddvc.workflow import current_inputs


HORIZONS = (1, 7, 30, 120)
V2_VENUES = ("sushiswap_v2", "uniswap_v2")
V2_VALIDATION_STATUSES = tuple(sorted(VALID_CAPITAL_STATUSES))
V2_QUANTITY_KIND = "deposited_capital"
ROUTE_FAMILY = "topology_valid_non_round_trip_route_use"
V2_FAMILY = "v2_family_deposited_capital_stock"
V3_LAUNCH_DATE = pd.Timestamp("2021-05-05")

ROUTE_COLUMNS = frozenset(
    {
        "date",
        "token",
        "symbol",
        "intermediate_routes",
        "endpoint_routes",
        "intermediate_count_share",
        "vehicle_excess_use_count_ratio",
        "endpoint_supported",
    }
)
CAPITAL_COLUMNS = frozenset(
    {
        "venue",
        "day",
        "pool",
        "pool_candidate_id",
        "candidate",
        "candidate_address",
        "allocation_weight",
        "candidate_capital_usd",
        "quantity_kind",
        "pool_family",
        "invariant_family",
        "state_generation",
        "capital_validation_status",
    }
)
V2_CANDIDATE_DAY_COLUMNS = (
    "origin_date", "candidate_address", "candidate_symbol",
    "route_measurement_family", "route_day_supported",
    "route_candidate_observed", "route_endpoint_supported",
    "intermediary_episode_share", "vehicle_excess_use_count_ratio",
    "intermediate_route_count", "endpoint_route_count",
    "route_all_token_intermediate_count", "route_all_token_endpoint_count",
    "route_share_denominator", "route_support_status",
    "v2_measurement_family", "v2_capital_day_supported",
    "v2_candidate_pool_observed", "v2_deposited_capital_usd",
    "v2_log1p_deposited_capital_usd", "v2_five_candidate_capital_share",
    "v2_candidate_pool_count", "v2_candidate_venue_count",
    "v2_candidate_allocation_row_count", "v2_quantity_kind",
    "v2_capital_validation_status", "v2_capital_state_generation",
    "v2_capital_support_status",
)


def _assert_series_identity(
    actual: pd.Series, expected: pd.Series, message: str
) -> None:
    """Raise one stable semantic error for a recomputed column identity."""

    try:
        pd.testing.assert_series_equal(
            actual.reset_index(drop=True),
            expected.reset_index(drop=True),
            check_names=False,
            check_dtype=False,
            check_exact=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as error:
        raise ValueError(message) from error


def _require_strict_booleans(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if not frame[column].map(lambda value: isinstance(value, (bool, np.bool_))).all():
            raise ValueError(f"{column} is not a complete Boolean support field")


def _sql_path(path: str | Path) -> str:
    return str(Path(path).resolve()).replace("'", "''")


def _sql_values(values: Iterable[str]) -> str:
    return ",".join(f"'{value.replace(chr(39), chr(39) * 2)}'" for value in values)


def _columns(connection: duckdb.DuckDBPyConnection, relation: str) -> set[str]:
    return {str(row[0]) for row in connection.execute(f"DESCRIBE {relation}").fetchall()}


def _require_columns(connection: duckdb.DuckDBPyConnection, relation: str, required: frozenset[str]) -> None:
    missing = sorted(required - _columns(connection, relation))
    if missing:
        raise ValueError(f"{relation} lacks required columns: {missing}")


def _candidate_rows() -> list[tuple[str, str]]:
    rows = sorted((address.lower(), symbol) for address, symbol in VEHICLE_CANDIDATES.items())
    if len(rows) != 5 or len({address for address, _symbol in rows}) != 5 or len({symbol for _address, symbol in rows}) != 5:
        raise RuntimeError("canonical vehicle-candidate identity must contain five unique addresses and symbols")
    return rows


def _raise_on_count(connection: duckdb.DuckDBPyConnection, query: str, message: str) -> None:
    count = int(connection.execute(query).fetchone()[0])
    if count:
        raise ValueError(f"{message}: {count:,} violation(s)")


def _preflight_route(connection: duckdb.DuckDBPyConnection) -> None:
    _require_columns(connection, "route_input", ROUTE_COLUMNS)
    _raise_on_count(
        connection,
        """
        SELECT count(*) FROM route_input r
        JOIN candidate_dim c ON lower(r.token)=c.candidate_address
        WHERE lower(r.token)!=r.token OR r.symbol IS DISTINCT FROM c.candidate_symbol
        """,
        "route input violates exact candidate address or symbol identity",
    )
    _raise_on_count(
        connection,
        """
        SELECT count(*) FROM (
            SELECT cast(date AS DATE), lower(token), count(*) AS n
            FROM route_input
            WHERE lower(token) IN (SELECT candidate_address FROM candidate_dim)
            GROUP BY ALL HAVING n!=1
        )
        """,
        "route input has duplicate candidate-days",
    )
    _raise_on_count(
        connection,
        """
        SELECT count(*) FROM route_input
        WHERE lower(token) IN (SELECT candidate_address FROM candidate_dim)
          AND (
            date IS NULL OR intermediate_routes IS NULL OR intermediate_routes<0
            OR endpoint_routes IS NULL OR endpoint_routes<0
            OR intermediate_count_share IS NULL OR NOT isfinite(intermediate_count_share)
            OR intermediate_count_share<0 OR intermediate_count_share>1
            OR (vehicle_excess_use_count_ratio IS NOT NULL AND (NOT isfinite(vehicle_excess_use_count_ratio) OR vehicle_excess_use_count_ratio<0))
            OR endpoint_supported IS NULL
          )
        """,
        "route input has malformed measurement or support fields",
    )


def _preflight_capital(connection: duckdb.DuckDBPyConnection) -> None:
    _require_columns(connection, "capital_input", CAPITAL_COLUMNS)
    venues = _sql_values(V2_VENUES)
    statuses = _sql_values(V2_VALIDATION_STATUSES)
    _raise_on_count(
        connection,
        f"""
        SELECT count(*) FROM capital_input c
        LEFT JOIN candidate_dim d ON c.candidate_address=d.candidate_address
        WHERE c.venue NOT IN ({venues}) OR c.day IS NULL OR try_strptime(c.day, '%Y%m%d') IS NULL
          OR c.candidate_address IS NULL OR lower(c.candidate_address)!=c.candidate_address
          OR d.candidate_address IS NULL OR c.candidate IS DISTINCT FROM d.candidate_symbol
          OR c.quantity_kind!='{V2_QUANTITY_KIND}'
          OR c.capital_validation_status NOT IN ({statuses})
          OR c.pool_family IS NULL OR c.invariant_family IS NULL OR c.state_generation IS NULL
          OR c.allocation_weight IS NULL OR NOT isfinite(c.allocation_weight) OR c.allocation_weight<=0 OR c.allocation_weight>1
          OR c.candidate_capital_usd IS NULL OR NOT isfinite(c.candidate_capital_usd) OR c.candidate_capital_usd<0
        """,
        "capital input violates venue, identity, quantity, validation, or support contracts",
    )
    _raise_on_count(
        connection,
        """
        SELECT count(*) FROM (
            SELECT venue, day, pool, candidate_address, count(*) AS n
            FROM capital_input GROUP BY ALL HAVING n!=1
        )
        """,
        "capital input has duplicate pool-candidate rows",
    )
    _raise_on_count(
        connection,
        """
        SELECT count(*) FROM (
            SELECT venue, day, pool,
                sum(allocation_weight) AS weight,
                sum(candidate_capital_usd) AS allocated,
                min(candidate_capital_usd/allocation_weight) AS base_min,
                max(candidate_capital_usd/allocation_weight) AS base_max
            FROM capital_input
            GROUP BY ALL
        )
        WHERE abs(weight-1)>1e-10
           OR abs(base_max-base_min)>1e-8*greatest(1, abs(base_max))
           OR abs(allocated-base_max)>1e-8*greatest(1, abs(base_max))
        """,
        "capital allocation does not conserve each pool's deposited capital exactly once",
    )


def _v2_candidate_day_query() -> str:
    """Return the V2-only candidate-day query without inventing a V3 family."""

    return f"""
    WITH bounds AS (
        SELECT min(observed_date) AS first_date, max(observed_date) AS last_date
        FROM (
            SELECT cast(date AS DATE) AS observed_date FROM route_input
            UNION ALL SELECT cast(strptime(day, '%Y%m%d') AS DATE) FROM capital_input
        )
    ),
    calendar AS (
        SELECT cast(day AS DATE) AS origin_date
        FROM bounds, generate_series(first_date, last_date, INTERVAL 1 DAY) AS dates(day)
    ),
    perimeter AS (
        SELECT calendar.origin_date, candidate_dim.candidate_address,
            candidate_dim.candidate_symbol
        FROM calendar CROSS JOIN candidate_dim
    ),
    route_days AS (
        SELECT cast(date AS DATE) AS origin_date,
            sum(intermediate_routes) AS all_token_intermediate_count,
            sum(endpoint_routes) AS all_token_endpoint_count
        FROM route_input GROUP BY 1
    ),
    route AS (
        SELECT cast(r.date AS DATE) AS origin_date, lower(r.token) AS candidate_address,
            r.intermediate_routes, r.endpoint_routes, r.intermediate_count_share,
            r.vehicle_excess_use_count_ratio, r.endpoint_supported
        FROM route_input r JOIN candidate_dim c ON lower(r.token)=c.candidate_address
    ),
    capital_days AS (
        SELECT cast(strptime(day, '%Y%m%d') AS DATE) AS origin_date,
            string_agg(DISTINCT capital_validation_status, '|' ORDER BY capital_validation_status) AS validation_status,
            string_agg(DISTINCT state_generation, '|' ORDER BY state_generation) AS state_generation
        FROM capital_input GROUP BY 1
    ),
    capital AS (
        SELECT cast(strptime(day, '%Y%m%d') AS DATE) AS origin_date, candidate_address,
            sum(candidate_capital_usd) AS deposited_capital_usd,
            count(DISTINCT venue || ':' || pool) AS pool_count,
            count(DISTINCT venue) AS venue_count,
            count(*) AS allocation_row_count
        FROM capital_input GROUP BY 1, 2
    ),
    capital_total AS (
        SELECT cast(strptime(day, '%Y%m%d') AS DATE) AS origin_date,
            sum(candidate_capital_usd) AS five_candidate_capital_usd
        FROM capital_input GROUP BY 1
    )
    SELECT p.origin_date, p.candidate_address, p.candidate_symbol,
        '{ROUTE_FAMILY}' AS route_measurement_family,
        rd.origin_date IS NOT NULL AS route_day_supported,
        r.candidate_address IS NOT NULL AS route_candidate_observed,
        coalesce(r.endpoint_supported, false) AS route_endpoint_supported,
        CASE WHEN rd.origin_date IS NOT NULL THEN coalesce(r.intermediate_count_share, 0.0) END AS intermediary_episode_share,
        r.vehicle_excess_use_count_ratio,
        CASE WHEN rd.origin_date IS NOT NULL THEN coalesce(r.intermediate_routes, 0) END AS intermediate_route_count,
        CASE WHEN rd.origin_date IS NOT NULL THEN coalesce(r.endpoint_routes, 0) END AS endpoint_route_count,
        rd.all_token_intermediate_count AS route_all_token_intermediate_count,
        rd.all_token_endpoint_count AS route_all_token_endpoint_count,
        'all_routed_tokens_on_origin_date' AS route_share_denominator,
        CASE WHEN rd.origin_date IS NULL THEN 'unavailable' WHEN r.candidate_address IS NULL THEN 'supported_zero_intermediation' ELSE 'observed_candidate' END AS route_support_status,
        '{V2_FAMILY}' AS v2_measurement_family,
        cd.origin_date IS NOT NULL AS v2_capital_day_supported,
        c.candidate_address IS NOT NULL AS v2_candidate_pool_observed,
        CASE WHEN cd.origin_date IS NOT NULL THEN coalesce(c.deposited_capital_usd, 0.0) END AS v2_deposited_capital_usd,
        CASE WHEN cd.origin_date IS NOT NULL THEN ln(1.0+coalesce(c.deposited_capital_usd, 0.0)) END AS v2_log1p_deposited_capital_usd,
        CASE WHEN cd.origin_date IS NOT NULL AND ct.five_candidate_capital_usd>0 THEN coalesce(c.deposited_capital_usd, 0.0)/ct.five_candidate_capital_usd END AS v2_five_candidate_capital_share,
        CASE WHEN cd.origin_date IS NOT NULL THEN coalesce(c.pool_count, 0) END AS v2_candidate_pool_count,
        CASE WHEN cd.origin_date IS NOT NULL THEN coalesce(c.venue_count, 0) END AS v2_candidate_venue_count,
        CASE WHEN cd.origin_date IS NOT NULL THEN coalesce(c.allocation_row_count, 0) END AS v2_candidate_allocation_row_count,
        '{V2_QUANTITY_KIND}' AS v2_quantity_kind,
        cd.validation_status AS v2_capital_validation_status,
        cd.state_generation AS v2_capital_state_generation,
        CASE WHEN cd.origin_date IS NULL THEN 'unavailable' WHEN c.candidate_address IS NULL THEN 'supported_zero_capital' ELSE 'observed_candidate_pools' END AS v2_capital_support_status
    FROM perimeter p
    LEFT JOIN route_days rd USING(origin_date)
    LEFT JOIN route r USING(origin_date, candidate_address)
    LEFT JOIN capital_days cd USING(origin_date)
    LEFT JOIN capital c USING(origin_date, candidate_address)
    LEFT JOIN capital_total ct USING(origin_date)
    ORDER BY p.origin_date, p.candidate_address
    """


def validate_v2_candidate_day_panel(panel: pd.DataFrame) -> None:
    """Recompute every route and V2 field consumed by the fitted-model owner."""

    missing = sorted(set(V2_CANDIDATE_DAY_COLUMNS) - set(panel.columns))
    if missing:
        raise ValueError(f"V2 candidate-day panel lacks required columns: {missing}")
    if any(column.startswith("v3_") for column in panel.columns):
        raise ValueError("V2 candidate-day panel contains a V3 measurement family")
    data = panel.loc[:, V2_CANDIDATE_DAY_COLUMNS].copy()
    data["origin_date"] = pd.to_datetime(data["origin_date"], errors="coerce")
    if data["origin_date"].isna().any():
        raise ValueError("V2 candidate-day panel contains an invalid origin date")
    if data.empty or data.duplicated(["origin_date", "candidate_address"]).any():
        raise ValueError("V2 candidate-day panel is empty or has duplicate candidate-days")
    expected = dict(_candidate_rows())
    if (
        set(data["candidate_address"]) != set(expected)
        or not data["candidate_symbol"].eq(
            data["candidate_address"].map(expected)
        ).all()
    ):
        raise ValueError("V2 candidate-day panel does not use the fixed five-address identity")
    expected_addresses = set(expected)
    address_sets = data.groupby("origin_date", sort=False)["candidate_address"].agg(set)
    if not address_sets.map(lambda values: values == expected_addresses).all():
        raise ValueError("V2 candidate-day panel does not contain the exact five addresses each day")
    days = pd.DatetimeIndex(data["origin_date"].drop_duplicates().sort_values())
    if not days.equals(pd.date_range(days.min(), days.max(), freq="D")):
        raise ValueError("V2 candidate-day panel calendar is not consecutive")
    if len(data) != 5 * len(days):
        raise ValueError("V2 candidate-day panel is not the exact five-by-day grid")

    boolean_columns = (
        "route_day_supported", "route_candidate_observed",
        "route_endpoint_supported", "v2_capital_day_supported",
        "v2_candidate_pool_observed",
    )
    _require_strict_booleans(data, boolean_columns)
    if data.groupby("origin_date")["route_day_supported"].nunique().gt(1).any():
        raise ValueError("V2 candidate-day route-day support is not date-global")
    if data.groupby("origin_date")["v2_capital_day_supported"].nunique().gt(1).any():
        raise ValueError("V2 candidate-day capital support is not date-global")
    if not data["route_measurement_family"].eq(ROUTE_FAMILY).all():
        raise ValueError("V2 candidate-day panel changed the route measurement family")
    if not data["route_share_denominator"].eq(
        "all_routed_tokens_on_origin_date"
    ).all():
        raise ValueError("V2 candidate-day panel changed the all-token route denominator")
    if not data["v2_measurement_family"].eq(V2_FAMILY).all():
        raise ValueError("V2 candidate-day panel changed the capital measurement family")
    if not data["v2_quantity_kind"].eq(V2_QUANTITY_KIND).all():
        raise ValueError("V2 candidate-day panel mixed the deposited-capital contract")

    numeric_columns = (
        "intermediary_episode_share", "vehicle_excess_use_count_ratio",
        "intermediate_route_count", "endpoint_route_count",
        "route_all_token_intermediate_count", "route_all_token_endpoint_count",
        "v2_deposited_capital_usd", "v2_log1p_deposited_capital_usd",
        "v2_five_candidate_capital_share", "v2_candidate_pool_count",
        "v2_candidate_venue_count", "v2_candidate_allocation_row_count",
    )
    for column in numeric_columns:
        converted = pd.to_numeric(data[column], errors="coerce")
        if data[column].notna().sum() != converted.notna().sum():
            raise ValueError(f"V2 candidate-day panel has a malformed {column}")
        data[column] = converted

    route_supported = data["route_day_supported"]
    route_observed = data["route_candidate_observed"]
    endpoint_supported = data["route_endpoint_supported"]
    if (route_observed & ~route_supported).any() or (endpoint_supported & ~route_observed).any():
        raise ValueError("V2 candidate-day route support hierarchy is inconsistent")
    route_values = (
        "intermediary_episode_share", "vehicle_excess_use_count_ratio",
        "intermediate_route_count", "endpoint_route_count",
        "route_all_token_intermediate_count", "route_all_token_endpoint_count",
    )
    if data.loc[~route_supported, list(route_values)].notna().any().any():
        raise ValueError("unsupported route dates carry route measurements")
    for column in (
        "intermediary_episode_share", "intermediate_route_count",
        "endpoint_route_count", "route_all_token_intermediate_count",
        "route_all_token_endpoint_count",
    ):
        if data.loc[route_supported, column].isna().any():
            raise ValueError(f"supported route dates omit {column}")
    for column in (
        "route_all_token_intermediate_count", "route_all_token_endpoint_count",
    ):
        if data.loc[route_supported].groupby("origin_date")[column].nunique().ne(1).any():
            raise ValueError(f"V2 all-token route denominator is not date-global: {column}")
    shares = data.loc[route_supported, "intermediary_episode_share"]
    if not shares.between(0, 1).all():
        raise ValueError("V2 intermediary episode share lies outside the unit interval")
    for column in (
        "intermediate_route_count", "endpoint_route_count",
        "route_all_token_intermediate_count", "route_all_token_endpoint_count",
    ):
        values = data.loc[route_supported, column]
        if values.lt(0).any() or values.mod(1).ne(0).any():
            raise ValueError(f"V2 candidate-day panel has an invalid {column}")
    if (
        data.loc[route_supported, "intermediate_route_count"]
        .gt(data.loc[route_supported, "route_all_token_intermediate_count"])
        .any()
        or data.loc[route_supported, "endpoint_route_count"]
        .gt(data.loc[route_supported, "route_all_token_endpoint_count"])
        .any()
    ):
        raise ValueError("V2 candidate route count exceeds its all-token denominator")
    daily_intermediate_total = data["route_all_token_intermediate_count"]
    expected_intermediary_share = pd.Series(0.0, index=data.index).where(
        route_supported
    )
    positive_intermediate_total = route_supported & daily_intermediate_total.gt(0)
    expected_intermediary_share.loc[positive_intermediate_total] = (
        data.loc[positive_intermediate_total, "intermediate_route_count"]
        / daily_intermediate_total.loc[positive_intermediate_total]
    )
    _assert_series_identity(
        data["intermediary_episode_share"], expected_intermediary_share,
        "V2 intermediary episode share disagrees with all-token route counts",
    )
    candidate_share_sums = data.loc[
        route_supported, ["origin_date", "intermediary_episode_share"]
    ].groupby("origin_date")["intermediary_episode_share"].sum()
    if not candidate_share_sums.between(-1e-10, 1.0 + 1e-10).all():
        raise ValueError("V2 five-candidate intermediary shares exceed the all-token total")
    zero_route = route_supported & ~route_observed
    if data.loc[
        zero_route,
        ["intermediary_episode_share", "intermediate_route_count", "endpoint_route_count"],
    ].ne(0).any().any():
        raise ValueError("supported zero-intermediation rows are not exact zeros")
    expected_endpoint = data["endpoint_route_count"].gt(0) & route_observed
    if not np.array_equal(
        endpoint_supported.to_numpy(dtype=bool),
        expected_endpoint.to_numpy(dtype=bool),
    ):
        raise ValueError("route endpoint support disagrees with endpoint route counts")
    ratio = data["vehicle_excess_use_count_ratio"]
    if ratio[endpoint_supported].isna().any() or ratio[endpoint_supported].lt(0).any():
        raise ValueError("endpoint-supported vehicle excess use is missing or negative")
    if ratio[~endpoint_supported].notna().any():
        raise ValueError("endpoint-unsupported rows carry vehicle excess use")
    daily_endpoint_total = data["route_all_token_endpoint_count"]
    endpoint_share = data["endpoint_route_count"] / daily_endpoint_total
    expected_ratio = (expected_intermediary_share / endpoint_share).where(
        endpoint_supported
    ).astype(float)
    _assert_series_identity(
        ratio, expected_ratio,
        "V2 vehicle excess-use ratio disagrees with all-token route-count shares",
    )
    expected_route_status = pd.Series("unavailable", index=data.index)
    expected_route_status.loc[route_supported & ~route_observed] = "supported_zero_intermediation"
    expected_route_status.loc[route_observed] = "observed_candidate"
    _assert_series_identity(
        data["route_support_status"], expected_route_status,
        "V2 route support status disagrees with its support fields",
    )

    capital_supported = data["v2_capital_day_supported"]
    pool_observed = data["v2_candidate_pool_observed"]
    if (pool_observed & ~capital_supported).any():
        raise ValueError("V2 candidate pool is observed on an unsupported capital date")
    capital_values = (
        "v2_deposited_capital_usd", "v2_log1p_deposited_capital_usd",
        "v2_five_candidate_capital_share", "v2_candidate_pool_count",
        "v2_candidate_venue_count", "v2_candidate_allocation_row_count",
    )
    if data.loc[~capital_supported, list(capital_values)].notna().any().any():
        raise ValueError("unsupported V2 dates carry capital values")
    required_capital = [
        "v2_deposited_capital_usd", "v2_log1p_deposited_capital_usd",
        "v2_candidate_pool_count", "v2_candidate_venue_count",
        "v2_candidate_allocation_row_count",
    ]
    if data.loc[capital_supported, required_capital].isna().any().any():
        raise ValueError("supported V2 dates omit a deposited-capital field")
    capital = data["v2_deposited_capital_usd"]
    if capital[capital_supported].lt(0).any():
        raise ValueError("V2 deposited capital is negative")
    expected_log = np.log1p(capital).where(capital_supported)
    _assert_series_identity(
        data["v2_log1p_deposited_capital_usd"], expected_log,
        "V2 log capital disagrees with deposited capital",
    )
    count_columns = (
        "v2_candidate_pool_count", "v2_candidate_venue_count",
        "v2_candidate_allocation_row_count",
    )
    for column in count_columns:
        values = data.loc[capital_supported, column]
        if values.lt(0).any() or values.mod(1).ne(0).any():
            raise ValueError(f"V2 candidate-day panel has an invalid {column}")
    if data.loc[capital_supported, "v2_candidate_venue_count"].gt(len(V2_VENUES)).any():
        raise ValueError("V2 candidate venue count exceeds the admitted family")
    if (
        data.loc[capital_supported, "v2_candidate_pool_count"]
        .gt(data.loc[capital_supported, "v2_candidate_allocation_row_count"])
        .any()
    ):
        raise ValueError("V2 pool count exceeds candidate allocation rows")
    expected_pool_observed = (
        data["v2_candidate_allocation_row_count"].gt(0) & capital_supported
    )
    if not np.array_equal(
        pool_observed.to_numpy(dtype=bool),
        expected_pool_observed.to_numpy(dtype=bool),
    ):
        raise ValueError("V2 candidate-pool support disagrees with allocation rows")
    zero_capital = capital_supported & ~pool_observed
    if data.loc[zero_capital, ["v2_deposited_capital_usd", *count_columns]].ne(0).any().any():
        raise ValueError("supported zero-capital rows are not exact zeros")
    daily_total = capital.where(capital_supported).groupby(data["origin_date"]).transform("sum")
    expected_share = (capital / daily_total).where(capital_supported & daily_total.gt(0))
    _assert_series_identity(
        data["v2_five_candidate_capital_share"], expected_share,
        "V2 five-candidate capital share disagrees with its daily denominator",
    )
    share_sums = data.loc[
        capital_supported & daily_total.gt(0),
        ["origin_date", "v2_five_candidate_capital_share"],
    ].groupby("origin_date")["v2_five_candidate_capital_share"].sum()
    if not np.allclose(share_sums.to_numpy(float), 1.0, rtol=1e-10, atol=1e-10):
        raise ValueError("V2 five-candidate capital shares do not sum to one")
    expected_capital_status = pd.Series("unavailable", index=data.index)
    expected_capital_status.loc[zero_capital] = "supported_zero_capital"
    expected_capital_status.loc[pool_observed] = "observed_candidate_pools"
    _assert_series_identity(
        data["v2_capital_support_status"], expected_capital_status,
        "V2 capital support status disagrees with its support fields",
    )
    for column in ("v2_capital_validation_status", "v2_capital_state_generation"):
        if data.loc[~capital_supported, column].notna().any():
            raise ValueError(f"unsupported V2 dates carry {column}")
        if data.loc[capital_supported, column].isna().any():
            raise ValueError(f"supported V2 dates omit {column}")
        if data.loc[capital_supported].groupby("origin_date")[column].nunique().ne(1).any():
            raise ValueError(f"V2 date disagrees internally on {column}")
    admitted_statuses = set(V2_VALIDATION_STATUSES)
    status_tokens = data.loc[
        capital_supported, "v2_capital_validation_status"
    ].astype(str).str.split("|")
    if not status_tokens.map(lambda values: bool(values) and set(values) <= admitted_statuses).all():
        raise ValueError("V2 capital validation status is outside the admitted contract")
    if data.loc[
        capital_supported, "v2_capital_state_generation"
    ].astype(str).str.strip().eq("").any():
        raise ValueError("V2 capital state generation is blank")


def build_v2_candidate_day_panel(
    route_path: str | Path,
    capital_path: str | Path,
    *,
    verify_inputs: bool = True,
    memory_limit: str = "512MB",
    threads: int = 2,
    temp_directory: str | Path | None = None,
) -> pd.DataFrame:
    """Aggregate current route and V2 releases without requiring or filling V3."""

    inputs = [Path(route_path), Path(capital_path)]
    lease = (
        current_inputs(inputs, consumer="V2 liquidity predictability panel builder")
        if verify_inputs else nullcontext()
    )
    with lease:
        connection = duckdb.connect()
        try:
            connection.execute(f"SET memory_limit='{memory_limit}'")
            connection.execute(f"SET threads={max(1, int(threads))}")
            connection.execute("SET preserve_insertion_order=false")
            if temp_directory is not None:
                directory = Path(temp_directory)
                directory.mkdir(parents=True, exist_ok=True)
                connection.execute(f"SET temp_directory='{_sql_path(directory)}'")
            connection.execute(f"CREATE VIEW route_input AS SELECT * FROM read_parquet('{_sql_path(inputs[0])}')")
            connection.execute(f"CREATE VIEW capital_input AS SELECT * FROM read_parquet('{_sql_path(inputs[1])}')")
            values = ",".join(f"('{address}','{symbol}')" for address, symbol in _candidate_rows())
            connection.execute(
                "CREATE TEMP TABLE candidate_dim(candidate_address VARCHAR, candidate_symbol VARCHAR); "
                f"INSERT INTO candidate_dim VALUES {values}"
            )
            _preflight_route(connection)
            _preflight_capital(connection)
            panel = connection.execute(_v2_candidate_day_query()).df()
        finally:
            connection.close()
    panel["origin_date"] = pd.to_datetime(panel["origin_date"])
    for column in (
        "route_day_supported", "route_candidate_observed", "route_endpoint_supported",
        "v2_capital_day_supported", "v2_candidate_pool_observed",
    ):
        panel[column] = panel[column].astype(bool)
    validate_v2_candidate_day_panel(panel)
    return panel


def build_v2_exact_horizon_panel(
    candidate_day: pd.DataFrame, horizons: Iterable[int] = HORIZONS
) -> pd.DataFrame:
    """Attach exact-date route and V2-stock changes without a V3 dependency."""

    validate_v2_candidate_day_panel(candidate_day)
    horizon_values = tuple(int(value) for value in horizons)
    if not horizon_values or any(value <= 0 for value in horizon_values) or len(set(horizon_values)) != len(horizon_values):
        raise ValueError("horizons must be unique positive calendar-day integers")
    out = _construct_v2_exact_horizon_panel(candidate_day, horizon_values)
    validate_v2_exact_horizon_panel(out, horizon_values)
    return out


def _construct_v2_exact_horizon_panel(
    candidate_day: pd.DataFrame, horizon_values: tuple[int, ...]
) -> pd.DataFrame:
    """Construct exact links after the caller has validated the origin panel."""

    daily = candidate_day.sort_values(["candidate_address", "origin_date"]).reset_index(drop=True)
    origins = daily.merge(pd.DataFrame({"horizon_days": horizon_values}), how="cross")
    origins["target_date"] = origins["origin_date"] + pd.to_timedelta(origins["horizon_days"], unit="D")
    target_sources = (
        "route_day_supported", "intermediary_episode_share",
        "vehicle_excess_use_count_ratio", "v2_capital_day_supported",
        "v2_log1p_deposited_capital_usd", "v2_five_candidate_capital_share",
    )
    targets = daily[["origin_date", "candidate_address", *target_sources]].rename(
        columns={"origin_date": "target_date", **{column: f"target_{column}" for column in target_sources}}
    )
    out = origins.merge(targets, on=["target_date", "candidate_address"], how="left", validate="many_to_one")
    out["route_exact_target_supported"] = out["route_day_supported"] & out["target_route_day_supported"].fillna(False)
    out["v2_exact_target_supported"] = out["v2_capital_day_supported"] & out["target_v2_capital_day_supported"].fillna(False)
    for source in ("intermediary_episode_share", "vehicle_excess_use_count_ratio"):
        out[f"future_{source}_change"] = (
            out[f"target_{source}"] - out[source]
        ).where(out["route_exact_target_supported"])
    for suffix in ("log1p_deposited_capital_usd", "five_candidate_capital_share"):
        source = f"v2_{suffix}"
        out[f"future_{source}_change"] = (
            out[f"target_{source}"] - out[source]
        ).where(out["v2_exact_target_supported"])
    out["horizon_contract"] = "exact_calendar_date_no_row_shift"
    return out.sort_values(
        ["origin_date", "candidate_address", "horizon_days"]
    ).reset_index(drop=True)


def validate_v2_exact_horizon_panel(
    panel: pd.DataFrame, horizons: Iterable[int] = HORIZONS
) -> None:
    """Fail closed when V2 family, identity, or exact-date support drifts."""

    target_sources = (
        "route_day_supported", "intermediary_episode_share",
        "vehicle_excess_use_count_ratio", "v2_capital_day_supported",
        "v2_log1p_deposited_capital_usd", "v2_five_candidate_capital_share",
    )
    derived = {
        "target_date", "horizon_days", "route_exact_target_supported",
        "v2_exact_target_supported", "horizon_contract",
        "future_intermediary_episode_share_change",
        "future_vehicle_excess_use_count_ratio_change",
        "future_v2_log1p_deposited_capital_usd_change",
        "future_v2_five_candidate_capital_share_change",
        *{f"target_{column}" for column in target_sources},
    }
    required = set(V2_CANDIDATE_DAY_COLUMNS) | derived
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"V2 exact-horizon panel lacks required columns: {missing}")
    if any(column.startswith("v3_") for column in panel.columns):
        raise ValueError("V2 exact-horizon panel contains a V3 measurement family")
    horizon_values = tuple(int(value) for value in horizons)
    if (
        not horizon_values
        or any(value <= 0 for value in horizon_values)
        or len(set(horizon_values)) != len(horizon_values)
    ):
        raise ValueError("V2 exact-horizon validator requires unique positive horizons")
    expected_horizons = set(horizon_values)
    if panel.empty or panel.duplicated(["origin_date", "candidate_address", "horizon_days"]).any():
        raise ValueError("V2 exact-horizon panel is empty or duplicated")
    horizon_numeric = pd.to_numeric(panel["horizon_days"], errors="coerce")
    if (
        horizon_numeric.isna().any()
        or horizon_numeric.mod(1).ne(0).any()
        or set(horizon_numeric.astype(int).unique()) != expected_horizons
    ):
        raise ValueError("V2 exact-horizon panel lost a registered horizon")
    data = panel.copy()
    data["origin_date"] = pd.to_datetime(data["origin_date"], errors="coerce")
    data["target_date"] = pd.to_datetime(data["target_date"], errors="coerce")
    data["horizon_days"] = horizon_numeric.astype(int)
    if data[["origin_date", "target_date"]].isna().any().any():
        raise ValueError("V2 exact-horizon panel contains an invalid date")
    keys = ["origin_date", "candidate_address"]
    inconsistent_origins = (
        data.groupby(keys, dropna=False)[list(V2_CANDIDATE_DAY_COLUMNS[2:])]
        .nunique(dropna=False)
        .gt(1)
        .any(axis=1)
    )
    if inconsistent_origins.any():
        raise ValueError("V2 exact-horizon rows disagree on an origin candidate-day")
    candidate_day = (
        data.sort_values([*keys, "horizon_days"])
        .drop_duplicates(keys)
        .loc[:, V2_CANDIDATE_DAY_COLUMNS]
        .reset_index(drop=True)
    )
    validate_v2_candidate_day_panel(candidate_day)
    expected = _construct_v2_exact_horizon_panel(candidate_day, horizon_values)
    actual = data.loc[:, expected.columns].sort_values(
        ["origin_date", "candidate_address", "horizon_days"]
    ).reset_index(drop=True)
    for column in ("target_route_day_supported", "target_v2_capital_day_supported"):
        actual[column] = actual[column].astype("boolean")
        expected[column] = expected[column].astype("boolean")
    try:
        pd.testing.assert_frame_equal(
            actual,
            expected,
            check_dtype=False,
            check_categorical=False,
            check_exact=False,
            rtol=1e-10,
            atol=1e-10,
        )
    except AssertionError as error:
        raise ValueError(
            "V2 exact-horizon panel disagrees with its complete origin-target recomputation"
        ) from error

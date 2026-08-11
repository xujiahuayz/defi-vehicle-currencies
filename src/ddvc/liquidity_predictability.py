"""Construct candidate-day liquidity predictability panels without estimation."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.dynamics import (
    DAILY_VOLATILITY_MIN_RETURNS,
    DAILY_VOLATILITY_WINDOW_DAYS,
    WETH_DOWNSIDE_EVENT_THRESHOLD,
    daily_price_risk_features,
    value_at_day_offset,
)
from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.capital_contracts import VALID_CAPITAL_STATUSES
from ddvc.provenance import require_current_artifacts


HORIZONS = (1, 7, 30, 120)
V2_VENUES = ("sushiswap_v2", "uniswap_v2")
V2_VALIDATION_STATUSES = tuple(sorted(VALID_CAPITAL_STATUSES))
V2_QUANTITY_KIND = "deposited_capital"
V3_NORMALIZATION_STATUS = "dollar_flow_and_within_flow_shares_no_capital_stock"
ROUTE_FAMILY = "topology_valid_non_round_trip_route_use"
V2_FAMILY = "v2_family_deposited_capital_stock"
V3_FAMILY = "uniswap_v3_lp_dollar_flow"
COVARIATE_LAG_DAYS = 1
TOKEN_PRICE_SOURCE = "canonical_repriced_route_legs"
TOKEN_PRICE_VALIDATION_STATUS = "minimum_observations_and_price_consensus_passed"

LOOKAHEAD_SAFE_COVARIATE_COLUMNS = (
    "covariate_observation_cutoff_date",
    "candidate_stress_scale_cutoff_date",
    "covariate_lag_days",
    "covariate_volatility_window_calendar_days",
    "covariate_volatility_min_valid_returns",
    "lag1_candidate_log_return",
    "lag1_candidate_return_supported",
    "lag1_candidate_trailing_30d_volatility",
    "lag1_candidate_volatility_valid_returns",
    "lag1_candidate_volatility_supported",
    "lag1_candidate_pre_shock_30d_volatility",
    "lag1_candidate_pre_shock_volatility_valid_returns",
    "lag1_candidate_pre_shock_volatility_supported",
    "lag1_candidate_downside_stress",
    "lag1_candidate_stress_supported",
    "lag1_weth_log_return",
    "lag1_weth_return_supported",
    "lag1_weth_trailing_30d_volatility",
    "lag1_weth_volatility_valid_returns",
    "lag1_weth_volatility_supported",
    "lag1_weth_downside_stress",
    "lag1_weth_stress_event_8pct",
    "lag1_weth_stress_supported",
    "lag1_route_day_supported",
    "lag1_route_endpoint_supported",
    "lag1_intermediary_episode_share",
    "lag1_vehicle_excess_use_count_ratio",
    "lag1_intermediate_route_count",
    "lag1_endpoint_route_count",
    "lag1_route_total_count",
    "lag1_v2_capital_day_supported",
    "lag1_v2_log1p_deposited_capital_usd",
    "lag1_v2_five_candidate_capital_share",
    "lag1_v3_flow_day_supported",
    "lag1_v3_signed_log1p_net_flow_per_1000",
    "lag1_v3_gross_candidate_flow_share",
)

LAGGED_CONTROL_COLUMNS = {
    "route_day_supported": "lag1_route_day_supported",
    "route_endpoint_supported": "lag1_route_endpoint_supported",
    "intermediary_episode_share": "lag1_intermediary_episode_share",
    "vehicle_excess_use_count_ratio": "lag1_vehicle_excess_use_count_ratio",
    "intermediate_route_count": "lag1_intermediate_route_count",
    "endpoint_route_count": "lag1_endpoint_route_count",
    "v2_capital_day_supported": "lag1_v2_capital_day_supported",
    "v2_log1p_deposited_capital_usd": "lag1_v2_log1p_deposited_capital_usd",
    "v2_five_candidate_capital_share": "lag1_v2_five_candidate_capital_share",
    "v3_flow_day_supported": "lag1_v3_flow_day_supported",
    "v3_signed_log1p_net_flow_per_1000": "lag1_v3_signed_log1p_net_flow_per_1000",
    "v3_gross_candidate_flow_share": "lag1_v3_gross_candidate_flow_share",
}

TOKEN_PRICE_COVARIATE_COLUMNS = frozenset(
    {"day", "token", "symbol", "price_usd", "price_source", "validation_status"}
)

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
FLOW_COLUMNS = frozenset(
    {
        "day",
        "candidate",
        "gross_liquidity_flow_usd",
        "net_liquidity_flow_usd",
        "active_net_liquidity_flow_usd",
        "near_net_liquidity_flow_usd",
        "near_gross_liquidity_flow_usd",
        "event_count",
        "has_liquidity_flow",
        "gross_candidate_flow_share",
        "near_gross_flow_share",
        "flow_normalization_status",
    }
)


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


def _weth_candidate_address() -> str:
    matches = [address for address, symbol in _candidate_rows() if symbol == "WETH"]
    if len(matches) != 1:
        raise RuntimeError("canonical candidates must contain exactly one WETH address")
    return matches[0]


def _price_feature_history(
    token_prices: pd.DataFrame,
    *,
    first_origin_date: pd.Timestamp,
    last_origin_date: pd.Timestamp,
) -> pd.DataFrame:
    missing = sorted(TOKEN_PRICE_COVARIATE_COLUMNS - set(token_prices.columns))
    if missing:
        raise ValueError(f"token-price covariates lack required columns: {missing}")
    identities = dict(_candidate_rows())
    prices = token_prices.copy()
    prices["token"] = prices["token"].astype(str)
    prices = prices.loc[prices["token"].str.lower().isin(identities)].copy()
    raw_days = prices["day"].astype(str)
    prices["price_date"] = pd.to_datetime(raw_days, format="%Y%m%d", errors="coerce")
    invalid = (
        prices["token"].ne(prices["token"].str.lower())
        | prices["price_date"].isna()
        | ~raw_days.str.fullmatch(r"\d{8}")
        | prices["symbol"].ne(prices["token"].map(identities))
        | prices["price_source"].ne(TOKEN_PRICE_SOURCE)
        | prices["validation_status"].ne(TOKEN_PRICE_VALIDATION_STATUS)
    )
    numeric_price = pd.to_numeric(prices["price_usd"], errors="coerce")
    if invalid.any() or (~np.isfinite(numeric_price) | numeric_price.le(0)).any():
        raise ValueError("token-price covariates violate identity, date, source, or value")
    if prices.duplicated(["price_date", "token"]).any():
        raise ValueError("token-price covariates contain duplicate candidate-days")
    prices["price_usd"] = numeric_price

    start = pd.Timestamp(first_origin_date).normalize() - pd.Timedelta(
        days=DAILY_VOLATILITY_WINDOW_DAYS + COVARIATE_LAG_DAYS + 1
    )
    end = pd.Timestamp(last_origin_date).normalize() - pd.Timedelta(
        days=COVARIATE_LAG_DAYS
    )
    index = pd.MultiIndex.from_product(
        [identities, pd.date_range(start, end, freq="D")],
        names=["candidate_address", "price_date"],
    )
    history = (
        prices.rename(columns={"token": "candidate_address"})
        .set_index(["candidate_address", "price_date"])[["price_usd"]]
        .reindex(index)
        .reset_index()
    )
    return daily_price_risk_features(
        history,
        "price_usd",
        entity_columns=("candidate_address",),
        date_column="price_date",
    )


def _lagged_controls(candidate_day: pd.DataFrame) -> pd.DataFrame:
    controls = candidate_day[["origin_date", "candidate_address"]].copy()
    for source, target in LAGGED_CONTROL_COLUMNS.items():
        controls[target] = value_at_day_offset(
            candidate_day,
            source,
            -COVARIATE_LAG_DAYS,
            entity_columns=("candidate_address",),
            date_column="origin_date",
        )
    for column in (
        "lag1_route_day_supported",
        "lag1_route_endpoint_supported",
        "lag1_v2_capital_day_supported",
        "lag1_v3_flow_day_supported",
    ):
        controls[column] = pd.array(controls[column], dtype="boolean")
    for column in ("lag1_intermediate_route_count", "lag1_endpoint_route_count"):
        controls[column] = pd.array(controls[column], dtype="Int64")
    controls["lag1_route_total_count"] = (
        controls["lag1_intermediate_route_count"]
        + controls["lag1_endpoint_route_count"]
    )
    return controls


def _compute_lookahead_safe_daily_covariates(
    candidate_day: pd.DataFrame, token_prices: pd.DataFrame
) -> pd.DataFrame:
    original_columns = tuple(candidate_day.columns)
    base = candidate_day.copy()
    base["origin_date"] = pd.to_datetime(base["origin_date"]).dt.normalize()
    base = base.sort_values(["origin_date", "candidate_address"]).reset_index(drop=True)
    cutoff = base["origin_date"] - pd.Timedelta(days=COVARIATE_LAG_DAYS)
    base["covariate_observation_cutoff_date"] = cutoff
    base["candidate_stress_scale_cutoff_date"] = cutoff - pd.Timedelta(days=1)
    base["covariate_lag_days"] = COVARIATE_LAG_DAYS
    base["covariate_volatility_window_calendar_days"] = DAILY_VOLATILITY_WINDOW_DAYS
    base["covariate_volatility_min_valid_returns"] = DAILY_VOLATILITY_MIN_RETURNS

    history = _price_feature_history(
        token_prices,
        first_origin_date=base["origin_date"].min(),
        last_origin_date=base["origin_date"].max(),
    )
    candidate = history.rename(
        columns={
            "price_date": "covariate_observation_cutoff_date",
            "log_return": "lag1_candidate_log_return",
            "trailing_30d_volatility": "lag1_candidate_trailing_30d_volatility",
            "trailing_volatility_valid_returns": "lag1_candidate_volatility_valid_returns",
            "pre_shock_30d_volatility": "lag1_candidate_pre_shock_30d_volatility",
            "pre_shock_volatility_valid_returns": "lag1_candidate_pre_shock_volatility_valid_returns",
            "standardized_downside_stress": "lag1_candidate_downside_stress",
        }
    )
    candidate_columns = [
        "candidate_address",
        "covariate_observation_cutoff_date",
        "lag1_candidate_log_return",
        "lag1_candidate_trailing_30d_volatility",
        "lag1_candidate_volatility_valid_returns",
        "lag1_candidate_pre_shock_30d_volatility",
        "lag1_candidate_pre_shock_volatility_valid_returns",
        "lag1_candidate_downside_stress",
    ]
    base = base.merge(
        candidate[candidate_columns],
        on=["candidate_address", "covariate_observation_cutoff_date"],
        how="left",
        validate="one_to_one",
    )
    weth = history.loc[history["candidate_address"].eq(_weth_candidate_address())].rename(
        columns={
            "price_date": "covariate_observation_cutoff_date",
            "log_return": "lag1_weth_log_return",
            "trailing_30d_volatility": "lag1_weth_trailing_30d_volatility",
            "trailing_volatility_valid_returns": "lag1_weth_volatility_valid_returns",
            "downside_stress": "lag1_weth_downside_stress",
            "stress_event_8pct": "lag1_weth_stress_event_8pct",
        }
    )
    weth_columns = [
        "covariate_observation_cutoff_date",
        "lag1_weth_log_return",
        "lag1_weth_trailing_30d_volatility",
        "lag1_weth_volatility_valid_returns",
        "lag1_weth_downside_stress",
        "lag1_weth_stress_event_8pct",
    ]
    base = base.merge(
        weth[weth_columns],
        on="covariate_observation_cutoff_date",
        how="left",
        validate="many_to_one",
    )
    for stem in ("candidate", "weth"):
        base[f"lag1_{stem}_return_supported"] = base[f"lag1_{stem}_log_return"].notna()
        base[f"lag1_{stem}_volatility_supported"] = base[f"lag1_{stem}_trailing_30d_volatility"].notna()
        base[f"lag1_{stem}_stress_supported"] = base[f"lag1_{stem}_downside_stress"].notna()
    base["lag1_candidate_pre_shock_volatility_supported"] = base[
        "lag1_candidate_pre_shock_30d_volatility"
    ].notna()
    base = base.merge(
        _lagged_controls(candidate_day),
        on=["origin_date", "candidate_address"],
        how="left",
        validate="one_to_one",
    )
    base = base.sort_values(["origin_date", "candidate_address"]).reset_index(drop=True)
    return base[[*original_columns, *LOOKAHEAD_SAFE_COVARIATE_COLUMNS]]


def validate_lookahead_safe_daily_covariates(
    original: pd.DataFrame, token_prices: pd.DataFrame, transformed: pd.DataFrame
) -> None:
    validate_candidate_day_panel(original)
    original_columns = tuple(original.columns)
    if tuple(transformed.columns) != (
        *original_columns,
        *LOOKAHEAD_SAFE_COVARIATE_COLUMNS,
    ):
        raise ValueError("look-ahead-safe covariates added, removed, or reordered columns")
    if not transformed[list(original_columns)].reset_index(drop=True).equals(
        original[list(original_columns)].reset_index(drop=True)
    ):
        raise ValueError("look-ahead-safe covariates changed an original column")
    ordered = transformed.sort_values(
        ["origin_date", "candidate_address"]
    ).reset_index(drop=True)
    if transformed.empty or not transformed.reset_index(drop=True).equals(ordered):
        raise ValueError("look-ahead-safe covariates are empty or not deterministically ordered")
    cutoff = pd.to_datetime(transformed["origin_date"]) - pd.Timedelta(
        days=COVARIATE_LAG_DAYS
    )
    if not pd.to_datetime(transformed["covariate_observation_cutoff_date"]).equals(
        cutoff
    ) or not pd.to_datetime(transformed["candidate_stress_scale_cutoff_date"]).equals(
        cutoff - pd.Timedelta(days=1)
    ):
        raise ValueError("look-ahead-safe covariate cutoff is not the declared exact lag")
    constants = {
        "covariate_lag_days": COVARIATE_LAG_DAYS,
        "covariate_volatility_window_calendar_days": DAILY_VOLATILITY_WINDOW_DAYS,
        "covariate_volatility_min_valid_returns": DAILY_VOLATILITY_MIN_RETURNS,
    }
    if any(not transformed[column].eq(value).all() for column, value in constants.items()):
        raise ValueError("look-ahead-safe covariate timing contract drifted")
    for stem in ("candidate", "weth"):
        return_supported = transformed[f"lag1_{stem}_log_return"].notna()
        volatility_supported = transformed[
            f"lag1_{stem}_trailing_30d_volatility"
        ].notna()
        stress_supported = transformed[f"lag1_{stem}_downside_stress"].notna()
        if not transformed[f"lag1_{stem}_return_supported"].eq(return_supported).all():
            raise ValueError(f"lagged {stem} return support is inconsistent")
        if not transformed[f"lag1_{stem}_volatility_supported"].eq(
            volatility_supported
        ).all() or (
            volatility_supported
            & transformed[f"lag1_{stem}_volatility_valid_returns"].lt(
                DAILY_VOLATILITY_MIN_RETURNS
            )
        ).any():
            raise ValueError(f"lagged {stem} volatility support is inconsistent")
        if not transformed[f"lag1_{stem}_stress_supported"].eq(stress_supported).all():
            raise ValueError(f"lagged {stem} stress support is inconsistent")
    pre_shock_supported = transformed["lag1_candidate_pre_shock_30d_volatility"].notna()
    if not transformed["lag1_candidate_pre_shock_volatility_supported"].eq(pre_shock_supported).all() or (
        pre_shock_supported
        & transformed["lag1_candidate_pre_shock_volatility_valid_returns"].lt(DAILY_VOLATILITY_MIN_RETURNS)
    ).any():
        raise ValueError("lagged candidate pre-shock volatility support is inconsistent")
    expected_candidate_stress = (
        (-transformed["lag1_candidate_log_return"])
        .clip(lower=0)
        .div(transformed["lag1_candidate_pre_shock_30d_volatility"])
        .where(
            transformed["lag1_candidate_log_return"].notna()
            & transformed["lag1_candidate_pre_shock_30d_volatility"].gt(0)
        )
    )
    try:
        pd.testing.assert_series_equal(
            transformed["lag1_candidate_downside_stress"],
            expected_candidate_stress.rename("lag1_candidate_downside_stress"),
        )
    except AssertionError as error:
        raise ValueError("lagged candidate stress does not use its persisted pre-shock denominator") from error
    route_total = (
        transformed["lag1_intermediate_route_count"].astype("Int64")
        + transformed["lag1_endpoint_route_count"].astype("Int64")
    )
    if not transformed["lag1_route_total_count"].astype("Int64").equals(route_total):
        raise ValueError("lagged route count reconciliation failed")
    support_contracts = {
        "lag1_route_day_supported": (
            "lag1_intermediary_episode_share",
            "lag1_intermediate_route_count",
            "lag1_endpoint_route_count",
            "lag1_route_total_count",
        ),
        "lag1_v2_capital_day_supported": (
            "lag1_v2_log1p_deposited_capital_usd",
            "lag1_v2_five_candidate_capital_share",
        ),
        "lag1_v3_flow_day_supported": (
            "lag1_v3_signed_log1p_net_flow_per_1000",
            "lag1_v3_gross_candidate_flow_share",
        ),
    }
    for support_column, value_columns in support_contracts.items():
        unsupported = ~transformed[support_column].fillna(False)
        if transformed.loc[unsupported, list(value_columns)].notna().any().any():
            raise ValueError(f"{support_column} has values on unsupported dates")
    weth_columns = [column for column in LOOKAHEAD_SAFE_COVARIATE_COLUMNS if column.startswith("lag1_weth_")]
    if transformed.groupby("origin_date", sort=False)[weth_columns].nunique(dropna=False).gt(1).any().any():
        raise ValueError("lagged WETH controls are not global within origin date")
    weth_candidate = transformed.loc[transformed["candidate_address"].eq(_weth_candidate_address())]
    identity_pairs = (
        ("lag1_candidate_log_return", "lag1_weth_log_return"),
        ("lag1_candidate_return_supported", "lag1_weth_return_supported"),
        ("lag1_candidate_trailing_30d_volatility", "lag1_weth_trailing_30d_volatility"),
        ("lag1_candidate_volatility_valid_returns", "lag1_weth_volatility_valid_returns"),
        ("lag1_candidate_volatility_supported", "lag1_weth_volatility_supported"),
    )
    for candidate_column, weth_column in identity_pairs:
        try:
            pd.testing.assert_series_equal(
                weth_candidate[candidate_column].reset_index(drop=True),
                weth_candidate[weth_column].reset_index(drop=True),
                check_names=False,
            )
        except AssertionError as error:
            raise ValueError("WETH candidate and global risk controls disagree") from error
    expected_event = (
        transformed["lag1_weth_downside_stress"]
        .ge(WETH_DOWNSIDE_EVENT_THRESHOLD)
        .where(transformed["lag1_weth_stress_supported"])
        .astype("boolean")
    )
    if not transformed["lag1_weth_stress_event_8pct"].astype("boolean").equals(expected_event):
        raise ValueError("lagged WETH stress event disagrees with the canonical threshold")
    original_sorted = original.sort_values(["origin_date", "candidate_address"]).reset_index(drop=True)
    expected = _compute_lookahead_safe_daily_covariates(original_sorted, token_prices)
    try:
        pd.testing.assert_frame_equal(transformed.reset_index(drop=True), expected)
    except AssertionError as error:
        raise ValueError("look-ahead-safe covariates disagree with canonical recomputation") from error


def attach_lookahead_safe_daily_covariates(
    candidate_day: pd.DataFrame, token_prices: pd.DataFrame
) -> pd.DataFrame:
    """Attach controls observable by the end of the exact prior UTC day.

    Returns use the cutoff date and its exact prior date. Volatility uses the 30
    calendar dates ending at the cutoff with at least 20 valid returns. Candidate
    stress divides the cutoff shock by the same window ending one day earlier.
    Missing dates and startup windows remain unsupported instead of compressing.
    """

    validate_candidate_day_panel(candidate_day)
    collisions = sorted(set(candidate_day) & set(LOOKAHEAD_SAFE_COVARIATE_COLUMNS))
    if collisions:
        raise ValueError(f"candidate-day panel already contains covariates: {collisions}")
    original = candidate_day.sort_values(
        ["origin_date", "candidate_address"]
    ).reset_index(drop=True)
    base = _compute_lookahead_safe_daily_covariates(original, token_prices)
    validate_lookahead_safe_daily_covariates(original, token_prices, base)
    return base


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
        LEFT JOIN candidate_dim c ON lower(r.token)=c.candidate_address
        WHERE r.token IS NULL OR lower(r.token)!=r.token OR c.candidate_address IS NULL OR r.symbol IS DISTINCT FROM c.candidate_symbol
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


def _preflight_flow(connection: duckdb.DuckDBPyConnection) -> None:
    _require_columns(connection, "flow_input", FLOW_COLUMNS)
    numeric = (
        "gross_liquidity_flow_usd",
        "net_liquidity_flow_usd",
        "active_net_liquidity_flow_usd",
        "near_net_liquidity_flow_usd",
        "near_gross_liquidity_flow_usd",
        "event_count",
    )
    malformed_numeric = " OR ".join(f"{column} IS NULL OR NOT isfinite({column})" for column in numeric)
    _raise_on_count(
        connection,
        f"""
        SELECT count(*) FROM flow_input f
        LEFT JOIN candidate_dim d ON f.candidate=d.candidate_symbol
        WHERE d.candidate_address IS NULL OR f.day IS NULL OR try_strptime(f.day, '%Y%m%d') IS NULL
          OR f.flow_normalization_status!='{V3_NORMALIZATION_STATUS}'
          OR {malformed_numeric}
          OR f.gross_liquidity_flow_usd<0 OR f.near_gross_liquidity_flow_usd<0 OR f.event_count<0 OR f.event_count!=floor(f.event_count)
          OR f.has_liquidity_flow IS NULL OR f.has_liquidity_flow!=(f.gross_liquidity_flow_usd>0)
        """,
        "V3 flow input violates identity, dollar-flow, zero-flow, or normalization contracts",
    )
    _raise_on_count(
        connection,
        """
        SELECT count(*) FROM (
            SELECT day, count(*) AS rows, count(DISTINCT candidate) AS candidates
            FROM flow_input GROUP BY day
        ) WHERE rows!=5 OR candidates!=5
        """,
        "V3 flow input does not contain exactly five explicit candidate rows per supported day",
    )
    _raise_on_count(
        connection,
        """
        SELECT count(*) FROM (
            SELECT day, candidate, count(*) AS n FROM flow_input GROUP BY ALL HAVING n!=1
        )
        """,
        "V3 flow input has duplicate candidate-days",
    )
    _raise_on_count(
        connection,
        """
        WITH totals AS (
            SELECT day, sum(gross_liquidity_flow_usd) AS day_gross FROM flow_input GROUP BY day
        )
        SELECT count(*) FROM flow_input f JOIN totals t USING(day)
        WHERE (t.day_gross>0 AND (f.gross_candidate_flow_share IS NULL OR abs(f.gross_candidate_flow_share-f.gross_liquidity_flow_usd/t.day_gross)>1e-10))
           OR (t.day_gross=0 AND f.gross_candidate_flow_share IS NOT NULL)
           OR (f.gross_liquidity_flow_usd>0 AND (f.near_gross_flow_share IS NULL OR abs(f.near_gross_flow_share-f.near_gross_liquidity_flow_usd/f.gross_liquidity_flow_usd)>1e-10))
           OR (f.gross_liquidity_flow_usd=0 AND f.near_gross_flow_share IS NOT NULL)
        """,
        "V3 within-flow shares disagree with their dollar-flow denominators",
    )


def _candidate_day_query() -> str:
    return f"""
    WITH bounds AS (
        SELECT min(observed_date) AS first_date, max(observed_date) AS last_date
        FROM (
            SELECT cast(date AS DATE) AS observed_date FROM route_input
            UNION ALL SELECT cast(strptime(day, '%Y%m%d') AS DATE) FROM capital_input
            UNION ALL SELECT cast(strptime(day, '%Y%m%d') AS DATE) FROM flow_input
        )
    ),
    calendar AS (
        SELECT cast(day AS DATE) AS origin_date
        FROM bounds, generate_series(first_date, last_date, INTERVAL 1 DAY) AS dates(day)
    ),
    perimeter AS (
        SELECT calendar.origin_date, candidate_dim.candidate_address, candidate_dim.candidate_symbol
        FROM calendar CROSS JOIN candidate_dim
    ),
    route_days AS (
        SELECT DISTINCT cast(date AS DATE) AS origin_date FROM route_input
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
    ),
    flow_days AS (
        SELECT cast(strptime(day, '%Y%m%d') AS DATE) AS origin_date,
            sum(gross_liquidity_flow_usd) AS all_candidate_gross_flow_usd
        FROM flow_input GROUP BY 1
    ),
    flow AS (
        SELECT cast(strptime(f.day, '%Y%m%d') AS DATE) AS origin_date, c.candidate_address,
            f.gross_liquidity_flow_usd, f.net_liquidity_flow_usd,
            f.active_net_liquidity_flow_usd, f.near_net_liquidity_flow_usd,
            f.near_gross_liquidity_flow_usd, cast(f.event_count AS BIGINT) AS event_count,
            f.has_liquidity_flow, f.gross_candidate_flow_share, f.near_gross_flow_share
        FROM flow_input f JOIN candidate_dim c ON f.candidate=c.candidate_symbol
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
        CASE WHEN cd.origin_date IS NULL THEN 'unavailable' WHEN c.candidate_address IS NULL THEN 'supported_zero_capital' ELSE 'observed_candidate_pools' END AS v2_capital_support_status,
        '{V3_FAMILY}' AS v3_measurement_family,
        fd.origin_date IS NOT NULL AS v3_flow_day_supported,
        coalesce(f.has_liquidity_flow, false) AS v3_has_liquidity_flow,
        f.gross_liquidity_flow_usd AS v3_gross_flow_usd,
        f.net_liquidity_flow_usd AS v3_net_flow_usd,
        f.active_net_liquidity_flow_usd AS v3_active_net_flow_usd,
        f.near_net_liquidity_flow_usd AS v3_near_net_flow_usd,
        f.near_gross_liquidity_flow_usd AS v3_near_gross_flow_usd,
        f.event_count AS v3_event_count,
        f.gross_candidate_flow_share AS v3_gross_candidate_flow_share,
        f.near_gross_flow_share AS v3_near_gross_within_candidate_flow_share,
        fd.all_candidate_gross_flow_usd AS v3_all_candidate_gross_flow_usd,
        CASE WHEN fd.origin_date IS NOT NULL THEN '{V3_NORMALIZATION_STATUS}' END AS v3_flow_normalization_status,
        CASE WHEN fd.origin_date IS NULL THEN 'unavailable' WHEN f.has_liquidity_flow THEN 'observed_positive_flow' ELSE 'observed_explicit_zero_flow' END AS v3_flow_support_status
    FROM perimeter p
    LEFT JOIN route_days rd USING(origin_date)
    LEFT JOIN route r USING(origin_date, candidate_address)
    LEFT JOIN capital_days cd USING(origin_date)
    LEFT JOIN capital c USING(origin_date, candidate_address)
    LEFT JOIN capital_total ct USING(origin_date)
    LEFT JOIN flow_days fd USING(origin_date)
    LEFT JOIN flow f USING(origin_date, candidate_address)
    ORDER BY p.origin_date, p.candidate_address
    """


def validate_candidate_day_panel(panel: pd.DataFrame) -> None:
    required = {
        "origin_date",
        "candidate_address",
        "candidate_symbol",
        "route_day_supported",
        "intermediary_episode_share",
        "vehicle_excess_use_count_ratio",
        "v2_capital_day_supported",
        "v2_deposited_capital_usd",
        "v2_five_candidate_capital_share",
        "v2_quantity_kind",
        "v3_flow_day_supported",
        "v3_gross_flow_usd",
        "v3_net_flow_usd",
        "v3_flow_normalization_status",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"candidate-day panel lacks required columns: {missing}")
    if panel.empty or panel.duplicated(["origin_date", "candidate_address"]).any():
        raise ValueError("candidate-day panel is empty or has duplicate candidate-days")
    expected = dict(_candidate_rows())
    actual = dict(panel[["candidate_address", "candidate_symbol"]].drop_duplicates().itertuples(index=False, name=None))
    if actual != expected:
        raise ValueError("candidate-day panel does not use the fixed five-address identity")
    per_day = panel.groupby("origin_date")["candidate_address"].nunique()
    if not per_day.eq(5).all():
        raise ValueError("candidate-day panel does not contain all five addresses on every calendar day")
    days = pd.DatetimeIndex(pd.to_datetime(panel["origin_date"].drop_duplicates()).sort_values())
    expected_days = pd.date_range(days.min(), days.max(), freq="D")
    if not days.equals(expected_days):
        raise ValueError("candidate-day panel calendar is not consecutive daily time")
    if not panel["v2_quantity_kind"].eq(V2_QUANTITY_KIND).all():
        raise ValueError("candidate-day panel mixed the V2 deposited-capital quantity contract")
    flow_status = panel.loc[panel["v3_flow_day_supported"], "v3_flow_normalization_status"]
    if not flow_status.eq(V3_NORMALIZATION_STATUS).all():
        raise ValueError("candidate-day panel mixed V3 flow with a capital normalization")
    if panel.loc[~panel["v3_flow_day_supported"], ["v3_gross_flow_usd", "v3_net_flow_usd"]].notna().any().any():
        raise ValueError("missing V3 flow days were converted into observed zeros")
    if panel.loc[panel["v3_flow_support_status"].eq("observed_explicit_zero_flow"), "v3_gross_flow_usd"].ne(0).any():
        raise ValueError("explicit V3 zero-flow support does not carry a zero flow")
    if any("capital" in column for column in panel.columns if column.startswith("v3_")) or any("flow" in column for column in panel.columns if column.startswith("v2_")):
        raise ValueError("V2 capital-stock and V3 dollar-flow namespaces are mixed")


def build_candidate_day_panel(
    route_path: str | Path,
    capital_path: str | Path,
    flow_path: str | Path,
    *,
    verify_inputs: bool = True,
    memory_limit: str = "512MB",
    threads: int = 2,
    temp_directory: str | Path | None = None,
) -> pd.DataFrame:
    """Aggregate the three current releases into one fixed-address daily panel."""

    inputs = [Path(route_path), Path(capital_path), Path(flow_path)]
    if verify_inputs:
        require_current_artifacts(inputs, consumer="liquidity predictability panel builder")
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
        connection.execute(f"CREATE VIEW flow_input AS SELECT * FROM read_parquet('{_sql_path(inputs[2])}')")
        values = ",".join(f"('{address}','{symbol}')" for address, symbol in _candidate_rows())
        connection.execute(f"CREATE TEMP TABLE candidate_dim(candidate_address VARCHAR, candidate_symbol VARCHAR); INSERT INTO candidate_dim VALUES {values}")
        _preflight_route(connection)
        _preflight_capital(connection)
        _preflight_flow(connection)
        panel = connection.execute(_candidate_day_query()).df()
    finally:
        connection.close()
    panel["origin_date"] = pd.to_datetime(panel["origin_date"])
    for column in ("route_day_supported", "route_candidate_observed", "route_endpoint_supported", "v2_capital_day_supported", "v2_candidate_pool_observed", "v3_flow_day_supported", "v3_has_liquidity_flow"):
        panel[column] = panel[column].astype(bool)
    panel["v3_signed_log1p_net_flow_per_1000"] = np.sign(panel["v3_net_flow_usd"]) * np.log1p(panel["v3_net_flow_usd"].abs() / 1000.0)
    panel["v3_signed_log1p_active_net_flow_per_1000"] = np.sign(panel["v3_active_net_flow_usd"]) * np.log1p(panel["v3_active_net_flow_usd"].abs() / 1000.0)
    panel["v3_signed_log1p_near_net_flow_per_1000"] = np.sign(panel["v3_near_net_flow_usd"]) * np.log1p(panel["v3_near_net_flow_usd"].abs() / 1000.0)
    validate_candidate_day_panel(panel)
    return panel


def build_exact_horizon_panel(candidate_day: pd.DataFrame, horizons: Iterable[int] = HORIZONS) -> pd.DataFrame:
    """Attach exact-date targets and complete future V3 flow windows to every origin."""

    validate_candidate_day_panel(candidate_day)
    horizon_values = tuple(int(value) for value in horizons)
    if not horizon_values or any(value <= 0 for value in horizon_values) or len(set(horizon_values)) != len(horizon_values):
        raise ValueError("horizons must be unique positive calendar-day integers")
    daily = candidate_day.copy().sort_values(["candidate_address", "origin_date"]).reset_index(drop=True)
    flow_values = {
        "v3_gross_flow_usd": "v3_prefix_gross_flow_usd",
        "v3_net_flow_usd": "v3_prefix_net_flow_usd",
        "v3_active_net_flow_usd": "v3_prefix_active_net_flow_usd",
        "v3_near_net_flow_usd": "v3_prefix_near_net_flow_usd",
        "v3_near_gross_flow_usd": "v3_prefix_near_gross_flow_usd",
        "v3_all_candidate_gross_flow_usd": "v3_prefix_all_candidate_gross_flow_usd",
    }
    for source, prefix in flow_values.items():
        values = daily[source].where(daily["v3_flow_day_supported"], 0.0).fillna(0.0)
        daily[prefix] = values.groupby(daily["candidate_address"]).cumsum()
    daily["v3_prefix_supported_days"] = daily["v3_flow_day_supported"].astype("int64").groupby(daily["candidate_address"]).cumsum()
    horizon_frame = pd.DataFrame({"horizon_days": horizon_values})
    origins = daily.merge(horizon_frame, how="cross")
    origins["target_date"] = origins["origin_date"] + pd.to_timedelta(origins["horizon_days"], unit="D")
    target_columns = [
        "origin_date",
        "candidate_address",
        "route_day_supported",
        "intermediary_episode_share",
        "vehicle_excess_use_count_ratio",
        "v2_capital_day_supported",
        "v2_deposited_capital_usd",
        "v2_log1p_deposited_capital_usd",
        "v2_five_candidate_capital_share",
        *flow_values.values(),
        "v3_prefix_supported_days",
    ]
    targets = daily[target_columns].rename(columns={column: f"target_{column}" for column in target_columns if column not in {"origin_date", "candidate_address"}}).rename(columns={"origin_date": "target_date"})
    out = origins.merge(targets, on=["target_date", "candidate_address"], how="left", validate="many_to_one")
    out["route_exact_target_supported"] = out["route_day_supported"] & out["target_route_day_supported"].fillna(False)
    out["future_intermediary_episode_share_change"] = (out["target_intermediary_episode_share"] - out["intermediary_episode_share"]).where(out["route_exact_target_supported"])
    out["future_vehicle_excess_use_count_ratio_change"] = (out["target_vehicle_excess_use_count_ratio"] - out["vehicle_excess_use_count_ratio"]).where(out["route_exact_target_supported"])
    out["v2_exact_target_supported"] = out["v2_capital_day_supported"] & out["target_v2_capital_day_supported"].fillna(False)
    out["future_v2_log1p_deposited_capital_change"] = (out["target_v2_log1p_deposited_capital_usd"] - out["v2_log1p_deposited_capital_usd"]).where(out["v2_exact_target_supported"])
    out["future_v2_five_candidate_capital_share_change"] = (out["target_v2_five_candidate_capital_share"] - out["v2_five_candidate_capital_share"]).where(out["v2_exact_target_supported"])
    supported_days = out["target_v3_prefix_supported_days"] - out["v3_prefix_supported_days"]
    out["v3_future_window_supported_days"] = supported_days.astype("Int64")
    out["v3_exact_future_window_supported"] = supported_days.eq(out["horizon_days"])
    cumulative_names = {
        "gross_flow_usd": "gross_flow_usd",
        "net_flow_usd": "net_flow_usd",
        "active_net_flow_usd": "active_net_flow_usd",
        "near_net_flow_usd": "near_net_flow_usd",
        "near_gross_flow_usd": "near_gross_flow_usd",
        "all_candidate_gross_flow_usd": "all_candidate_gross_flow_usd",
    }
    for label, source_label in cumulative_names.items():
        prefix = f"v3_prefix_{source_label}"
        out[f"v3_future_cumulative_{label}"] = (out[f"target_{prefix}"] - out[prefix]).where(out["v3_exact_future_window_supported"])
    net = out["v3_future_cumulative_net_flow_usd"]
    active = out["v3_future_cumulative_active_net_flow_usd"]
    near = out["v3_future_cumulative_near_net_flow_usd"]
    out["v3_future_signed_log1p_net_flow_per_1000"] = np.sign(net) * np.log1p(net.abs() / 1000.0)
    out["v3_future_signed_log1p_active_net_flow_per_1000"] = np.sign(active) * np.log1p(active.abs() / 1000.0)
    out["v3_future_signed_log1p_near_net_flow_per_1000"] = np.sign(near) * np.log1p(near.abs() / 1000.0)
    denominator = out["v3_future_cumulative_all_candidate_gross_flow_usd"]
    candidate_gross = out["v3_future_cumulative_gross_flow_usd"]
    out["v3_future_gross_candidate_flow_share"] = np.where(out["v3_exact_future_window_supported"] & denominator.gt(0), candidate_gross / denominator, np.nan)
    out["v3_future_near_gross_within_candidate_flow_share"] = np.where(out["v3_exact_future_window_supported"] & candidate_gross.gt(0), out["v3_future_cumulative_near_gross_flow_usd"] / candidate_gross, np.nan)
    out["horizon_contract"] = "exact_calendar_date_no_row_shift"
    drop_columns = [column for column in out if column.startswith("v3_prefix_") or column.startswith("target_v3_prefix_")]
    out = out.drop(columns=drop_columns).sort_values(["origin_date", "candidate_address", "horizon_days"]).reset_index(drop=True)
    validate_exact_horizon_panel(out, horizon_values)
    return out


def validate_exact_horizon_panel(panel: pd.DataFrame, horizons: Iterable[int] = HORIZONS) -> None:
    """Fail closed if exact dates, registered horizons, identities, or families drift."""

    expected_horizons = {int(value) for value in horizons}
    required = {
        "origin_date",
        "target_date",
        "candidate_address",
        "candidate_symbol",
        "horizon_days",
        "route_exact_target_supported",
        "v2_exact_target_supported",
        "v3_exact_future_window_supported",
        "horizon_contract",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"exact-horizon panel lacks required columns: {missing}")
    if panel.empty or panel.duplicated(["origin_date", "candidate_address", "horizon_days"]).any():
        raise ValueError("exact-horizon panel is empty or has duplicate candidate-origin-horizon rows")
    if set(panel["horizon_days"].unique()) != expected_horizons:
        raise ValueError("exact-horizon panel lost a registered horizon")
    actual_target = pd.to_datetime(panel["origin_date"]) + pd.to_timedelta(panel["horizon_days"], unit="D")
    if not pd.to_datetime(panel["target_date"]).equals(actual_target):
        raise ValueError("exact-horizon target dates are not origin plus calendar horizon")
    if not panel["horizon_contract"].eq("exact_calendar_date_no_row_shift").all():
        raise ValueError("exact-horizon panel does not declare the no-row-shift contract")
    expected_identity = dict(_candidate_rows())
    actual_identity = dict(panel[["candidate_address", "candidate_symbol"]].drop_duplicates().itertuples(index=False, name=None))
    if actual_identity != expected_identity:
        raise ValueError("exact-horizon panel does not use the fixed five-address identity")
    if any("capital" in column for column in panel.columns if column.startswith("v3_")) or any("flow" in column for column in panel.columns if column.startswith("v2_")):
        raise ValueError("exact-horizon panel mixed V2 capital stocks and V3 dollar flows")


def validate_exact_horizon_covariates(
    candidate_day: pd.DataFrame,
    exact_horizons: pd.DataFrame,
    horizons: Iterable[int] = HORIZONS,
) -> None:
    """Verify every registered horizon preserves its origin-day covariates exactly."""

    validate_exact_horizon_panel(exact_horizons, horizons)
    missing_candidate = sorted(set(LOOKAHEAD_SAFE_COVARIATE_COLUMNS) - set(candidate_day.columns))
    missing_horizon = sorted(set(LOOKAHEAD_SAFE_COVARIATE_COLUMNS) - set(exact_horizons.columns))
    if missing_candidate or missing_horizon:
        raise ValueError(
            f"exact-horizon covariates are incomplete: candidate={missing_candidate}, horizon={missing_horizon}"
        )
    keys = ["origin_date", "candidate_address"]
    expected = exact_horizons[[*keys, "horizon_days"]].merge(
        candidate_day[[*keys, *LOOKAHEAD_SAFE_COVARIATE_COLUMNS]],
        on=keys,
        how="left",
        validate="many_to_one",
    )
    actual = exact_horizons[[*keys, "horizon_days", *LOOKAHEAD_SAFE_COVARIATE_COLUMNS]]
    try:
        pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True))
    except AssertionError as error:
        raise ValueError("exact-horizon panel changed an origin-day covariate") from error

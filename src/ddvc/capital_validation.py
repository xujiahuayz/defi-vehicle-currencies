"""Protocol-specific validation of deposited pool capital.

This module owns validation of accounting capital only. It does not construct
local depth, executable band depth, finite-size quotes, or LVR.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from ddvc.asset_types import (
    IMPORTED,
    NATIVE,
    NON_USD_STABLE,
    STABLE,
    STAKED_NATIVE,
    asset_type,
)
from ddvc.capital_contracts import (
    CAPITAL_SOURCE,
    CURRENT_CAPITAL_VALIDATION_STATUS,
    MAX_POOL_CAPITAL_USD,
)
from ddvc.paths import TOKEN_PRICE_DAILY_PANEL


ANCHORED_CAPITAL_ROLES = frozenset({"native", "staked_native", "stable", "imported"})
ANCHORED_CAPITAL_TOKENS = frozenset(
    address.lower()
    for taxonomy in (NATIVE, STAKED_NATIVE, STABLE, IMPORTED)
    for address in taxonomy
)
USD_STABLE_TOKENS = frozenset(
    address.lower()
    for address, symbol in STABLE.items()
    if symbol not in NON_USD_STABLE
)
PRICE_ROLLING_DAYS = 91
PRICE_MEDIAN_FACTOR = 4.0
USD_STABLE_PRICE_BOUNDS = (0.5, 2.0)
CONSTANT_PRODUCT_BALANCE_TOLERANCE = 3.0
PROVIDER_CAPITAL_SCALE_TARGETS = (1.0, 2.0)
PROVIDER_CAPITAL_SCALE_TOLERANCE = 1.25
CAPITAL_PRICE_SOURCE = "canonical_repriced_route_legs_with_address_time_sanity"


@dataclass(frozen=True)
class CapitalPrice:
    price_usd: float
    source: str
    validation_status: str


@dataclass(frozen=True)
class ConstantProductReserveState:
    reserve0: float | None
    reserve1: float | None
    source: str
    state_timestamp: int | None
    validation_status: str


@dataclass(frozen=True)
class ConstantProductCapitalValidation:
    capital_usd: float | None
    reconstructed_capital_usd: float | None
    reconciliation_ratio: float | None
    balance_value_ratio: float | None
    price_source: str
    validation_status: str
    failure_reason: str | None

    @property
    def valid(self) -> bool:
        return self.capital_usd is not None and self.failure_reason is None


def validated_capital_prices(
    path: Path = TOKEN_PRICE_DAILY_PANEL,
) -> pd.DataFrame:
    """Return sane address-day prices for the small predeclared anchor set."""

    prices = pd.read_parquet(
        path,
        columns=["day", "token", "price_usd", "price_source", "validation_status"],
        filters=[("token", "in", sorted(ANCHORED_CAPITAL_TOKENS))],
    )
    if prices.empty:
        raise RuntimeError("canonical token-price panel has no anchored capital prices")
    prices = prices.sort_values(["token", "day"]).reset_index(drop=True)
    price = pd.to_numeric(prices["price_usd"], errors="coerce")
    median = prices.groupby("token", sort=False)["price_usd"].transform(
        lambda values: values.rolling(
            PRICE_ROLLING_DAYS,
            min_periods=5,
        ).median()
    )
    valid = (
        np.isfinite(price)
        & price.gt(0)
        & np.isfinite(median)
        & median.gt(0)
        & price.between(median / PRICE_MEDIAN_FACTOR, median * PRICE_MEDIAN_FACTOR)
        & prices["price_source"].eq("canonical_repriced_route_legs")
        & prices["validation_status"].eq(
            "minimum_observations_and_price_consensus_passed"
        )
    )
    usd_stable = prices["token"].isin(USD_STABLE_TOKENS)
    valid &= ~usd_stable | price.between(*USD_STABLE_PRICE_BOUNDS)
    result = prices.loc[valid, ["day", "token", "price_usd"]].copy()
    if result.duplicated(["day", "token"]).any():
        raise ValueError("validated capital prices contain duplicate address-day rows")
    result["price_source"] = CAPITAL_PRICE_SOURCE
    result["validation_status"] = "consensus_and_address_time_sanity_passed"
    return result.reset_index(drop=True)


def capital_price_lookup(prices: pd.DataFrame) -> dict[str, dict[str, CapitalPrice]]:
    """Index the small validated anchor-price panel by day and token."""

    required = {"day", "token", "price_usd", "price_source", "validation_status"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"capital-price panel lacks columns: {sorted(missing)}")
    if prices.duplicated(["day", "token"]).any():
        raise ValueError("capital-price panel contains duplicate address-day rows")
    result: dict[str, dict[str, CapitalPrice]] = {}
    for row in prices.itertuples(index=False):
        result.setdefault(str(row.day), {})[str(row.token).lower()] = CapitalPrice(
            price_usd=float(row.price_usd),
            source=str(row.price_source),
            validation_status=str(row.validation_status),
        )
    return result


def _positive_finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) and parsed > 0 else None


def canonical_constant_product_closing_reserves(
    state: pd.DataFrame,
) -> dict[str, ConstantProductReserveState]:
    """Recover each pool's latest state, including later known liquidity events."""

    required = {
        "record_type",
        "pool",
        "period_end",
        "timestamp",
        "block_number",
        "log_index",
        "reserve0",
        "reserve1",
        "amount0_delta",
        "amount1_delta",
        "usable",
    }
    missing = required - set(state.columns)
    if missing:
        raise ValueError(f"constant-product state lacks columns: {sorted(missing)}")
    state = state.copy()
    state["pool"] = state["pool"].astype(str).str.lower()
    snapshots = state[
        state["record_type"].eq("snapshot") & state["usable"].fillna(False)
    ].copy()
    snapshots["period_end"] = pd.to_numeric(snapshots["period_end"], errors="coerce")
    snapshots = snapshots.sort_values(["pool", "period_end"]).groupby(
        "pool", as_index=False
    ).tail(1)
    liquidity = state[
        state["record_type"].eq("liquidity") & state["usable"].fillna(False)
    ].copy()
    liquidity["timestamp"] = pd.to_numeric(liquidity["timestamp"], errors="coerce")
    liquidity = liquidity.sort_values(["pool", "block_number", "log_index"])
    by_pool = {pool: rows for pool, rows in liquidity.groupby("pool", sort=False)}
    result: dict[str, ConstantProductReserveState] = {}
    for snapshot in snapshots.itertuples(index=False):
        pool = str(snapshot.pool).lower()
        try:
            reserve0 = Decimal(str(snapshot.reserve0))
            reserve1 = Decimal(str(snapshot.reserve1))
            period_end = int(snapshot.period_end)
        except (InvalidOperation, TypeError, ValueError):
            continue
        later = by_pool.get(pool)
        latest_timestamp = period_end
        applied = 0
        if later is not None:
            later = later[later["timestamp"].ge(period_end)]
            for event in later.itertuples(index=False):
                try:
                    reserve0 += Decimal(str(event.amount0_delta))
                    reserve1 += Decimal(str(event.amount1_delta))
                    latest_timestamp = max(latest_timestamp, int(event.timestamp))
                    applied += 1
                except (InvalidOperation, TypeError, ValueError):
                    reserve0 = reserve1 = Decimal(-1)
                    break
        valid = reserve0 > 0 and reserve1 > 0
        result[pool] = ConstantProductReserveState(
            reserve0=float(reserve0) if valid else None,
            reserve1=float(reserve1) if valid else None,
            source="canonical_hour_end_state",
            state_timestamp=latest_timestamp,
            validation_status=(
                "latest_snapshot_plus_subsequent_liquidity_events"
                if applied
                else "latest_observed_hour_end_snapshot"
            )
            if valid
            else "quarantined_invalid_closing_reserve_state",
        )
    return result


def pool_day_reserve_state(
    row: Mapping[str, object],
    fallback: ConstantProductReserveState | None,
    *,
    day_end_timestamp: int,
) -> ConstantProductReserveState:
    """Prefer provider closing reserves and use canonical replay when fields are absent."""

    reserve0 = _positive_finite(row.get("reserve0"))
    reserve1 = _positive_finite(row.get("reserve1"))
    if reserve0 is not None and reserve1 is not None:
        return ConstantProductReserveState(
            reserve0=reserve0,
            reserve1=reserve1,
            source="provider_pool_day_closing_reserves",
            state_timestamp=day_end_timestamp,
            validation_status="positive_provider_pool_day_reserves",
        )
    if fallback is not None and fallback.reserve0 is not None and fallback.reserve1 is not None:
        return fallback
    return ConstantProductReserveState(
        reserve0=None,
        reserve1=None,
        source="unavailable_reserve_state",
        state_timestamp=None,
        validation_status="quarantined_missing_reserve_state",
    )


def _failed(reason: str, *, price_source: str = CAPITAL_PRICE_SOURCE) -> ConstantProductCapitalValidation:
    return ConstantProductCapitalValidation(
        capital_usd=None,
        reconstructed_capital_usd=None,
        reconciliation_ratio=None,
        balance_value_ratio=None,
        price_source=price_source,
        validation_status=f"quarantined_{reason}",
        failure_reason=reason,
    )


def validate_constant_product_capital(
    row: Mapping[str, object],
    day_prices: Mapping[str, CapitalPrice],
    *,
    balance_tolerance: float = CONSTANT_PRODUCT_BALANCE_TOLERANCE,
    provider_scale_tolerance: float = PROVIDER_CAPITAL_SCALE_TOLERANCE,
) -> ConstantProductCapitalValidation:
    """Value V2 reserves from an anchored leg and reconcile provider capital."""

    if balance_tolerance <= 1 or provider_scale_tolerance <= 1:
        raise ValueError("capital validation tolerances must exceed one")
    token0 = str(row.get("token0_address") or "").lower()
    token1 = str(row.get("token1_address") or "").lower()
    if not token0 or not token1:
        return _failed("missing_exact_token_identity")
    reserve0 = _positive_finite(row.get("reserve0"))
    reserve1 = _positive_finite(row.get("reserve1"))
    if reserve0 is None or reserve1 is None:
        return _failed("nonpositive_or_missing_reserves")
    reported = _positive_finite(row.get("reported_capital_usd"))
    if reported is None or reported > MAX_POOL_CAPITAL_USD:
        return _failed("nonpositive_or_missing_reported_capital")
    anchored0 = asset_type(token0) in ANCHORED_CAPITAL_ROLES
    anchored1 = asset_type(token1) in ANCHORED_CAPITAL_ROLES
    price0 = day_prices.get(token0) if anchored0 else None
    price1 = day_prices.get(token1) if anchored1 else None
    if price0 is None and price1 is None:
        return _failed("no_valid_anchored_leg_price")
    value0 = reserve0 * price0.price_usd if price0 else None
    value1 = reserve1 * price1.price_usd if price1 else None
    if any(value is not None and not np.isfinite(value) for value in (value0, value1)):
        return _failed("reconstructed_capital_out_of_bounds")
    balance_ratio = None
    if value0 is not None and value1 is not None:
        balance_ratio = value0 / value1
        if not 1 / balance_tolerance <= balance_ratio <= balance_tolerance:
            return ConstantProductCapitalValidation(
                capital_usd=None,
                reconstructed_capital_usd=value0 + value1,
                reconciliation_ratio=(value0 + value1) / reported,
                balance_value_ratio=balance_ratio,
                price_source=CAPITAL_PRICE_SOURCE,
                validation_status="quarantined_anchored_leg_value_disagreement",
                failure_reason="anchored_leg_value_disagreement",
            )
        reconstructed = value0 + value1
    elif value0 is not None:
        reconstructed = 2.0 * value0
    else:
        assert value1 is not None
        reconstructed = 2.0 * value1
    if not np.isfinite(reconstructed) or reconstructed > MAX_POOL_CAPITAL_USD:
        return ConstantProductCapitalValidation(
            capital_usd=None,
            reconstructed_capital_usd=reconstructed,
            reconciliation_ratio=reconstructed / reported,
            balance_value_ratio=balance_ratio,
            price_source=CAPITAL_PRICE_SOURCE,
            validation_status="quarantined_reconstructed_capital_out_of_bounds",
            failure_reason="reconstructed_capital_out_of_bounds",
        )
    reconciliation_ratio = reconstructed / reported
    provider_scale_supported = any(
        target / provider_scale_tolerance
        <= reconciliation_ratio
        <= target * provider_scale_tolerance
        for target in PROVIDER_CAPITAL_SCALE_TARGETS
    )
    if not provider_scale_supported:
        return ConstantProductCapitalValidation(
            capital_usd=None,
            reconstructed_capital_usd=reconstructed,
            reconciliation_ratio=reconciliation_ratio,
            balance_value_ratio=balance_ratio,
            price_source=CAPITAL_PRICE_SOURCE,
            validation_status="quarantined_reported_capital_disagreement",
            failure_reason="reported_capital_disagreement",
        )
    return ConstantProductCapitalValidation(
        capital_usd=reconstructed,
        reconstructed_capital_usd=reconstructed,
        reconciliation_ratio=reconciliation_ratio,
        balance_value_ratio=balance_ratio,
        price_source=CAPITAL_PRICE_SOURCE,
        validation_status=CURRENT_CAPITAL_VALIDATION_STATUS,
        failure_reason=None,
    )

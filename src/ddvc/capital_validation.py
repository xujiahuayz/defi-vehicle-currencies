"""Protocol-specific validation of deposited pool capital.

This module owns validation of accounting capital only. It does not construct
local depth, executable band depth, finite-size quotes, or LVR.
"""

from __future__ import annotations

from dataclasses import dataclass
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
CONSTANT_PRODUCT_BALANCE_TOLERANCE = 1.25
CAPITAL_PRICE_SOURCE = "canonical_repriced_route_legs_with_address_time_sanity"
CAPITAL_PRICE_VALIDATION_STATUS = "consensus_and_address_time_sanity_passed"
MAX_TOKEN_RESERVE = 1.0e50


@dataclass(frozen=True)
class CapitalPrice:
    price_usd: float
    source: str
    validation_status: str

    @property
    def valid(self) -> bool:
        return bool(
            np.isfinite(self.price_usd)
            and self.price_usd > 0
            and self.source == CAPITAL_PRICE_SOURCE
            and self.validation_status == CAPITAL_PRICE_VALIDATION_STATUS
        )


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
    result["validation_status"] = CAPITAL_PRICE_VALIDATION_STATUS
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
) -> ConstantProductCapitalValidation:
    """Value released V2 reserves; provider capital is a diagnostic only."""

    if balance_tolerance <= 1:
        raise ValueError("capital validation tolerance must exceed one")
    token0 = str(row.get("token0_address") or "").lower()
    token1 = str(row.get("token1_address") or "").lower()
    if not token0 or not token1:
        return _failed("missing_exact_token_identity")
    reserve0 = _positive_finite(row.get("reserve0"))
    reserve1 = _positive_finite(row.get("reserve1"))
    if reserve0 is None or reserve1 is None:
        return _failed("nonpositive_or_missing_reserves")
    if reserve0 > MAX_TOKEN_RESERVE or reserve1 > MAX_TOKEN_RESERVE:
        return _failed("reserve_out_of_bounds")
    if row.get("identity_validation_status") != "exact_identity_and_decimals_passed":
        return _failed("identity_or_decimals_not_audited")
    if row.get("token_mechanics_status") == "quarantined_nonstandard_token_mechanics":
        return _failed("nonstandard_token_mechanics")
    reported = _positive_finite(row.get("reported_capital_usd"))
    anchored0 = asset_type(token0) in ANCHORED_CAPITAL_ROLES
    anchored1 = asset_type(token1) in ANCHORED_CAPITAL_ROLES
    observed0 = day_prices.get(token0) if anchored0 else None
    observed1 = day_prices.get(token1) if anchored1 else None
    price0 = observed0 if observed0 is not None and observed0.valid else None
    price1 = observed1 if observed1 is not None and observed1.valid else None
    if (observed0 is not None and price0 is None) or (observed1 is not None and price1 is None):
        return _failed("invalid_anchor_price_contract")
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
                reconciliation_ratio=(value0 + value1) / reported if reported else None,
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
    if not np.isfinite(reconstructed) or reconstructed <= 0 or reconstructed > MAX_POOL_CAPITAL_USD:
        return ConstantProductCapitalValidation(
            capital_usd=None,
            reconstructed_capital_usd=reconstructed,
            reconciliation_ratio=reconstructed / reported if reported else None,
            balance_value_ratio=balance_ratio,
            price_source=CAPITAL_PRICE_SOURCE,
            validation_status="quarantined_reconstructed_capital_out_of_bounds",
            failure_reason="reconstructed_capital_out_of_bounds",
        )
    reconciliation_ratio = reconstructed / reported if reported else None
    return ConstantProductCapitalValidation(
        capital_usd=reconstructed,
        reconstructed_capital_usd=reconstructed,
        reconciliation_ratio=reconciliation_ratio,
        balance_value_ratio=balance_ratio,
        price_source=CAPITAL_PRICE_SOURCE,
        validation_status=CURRENT_CAPITAL_VALIDATION_STATUS,
        failure_reason=None,
    )

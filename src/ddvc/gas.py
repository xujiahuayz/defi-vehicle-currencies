"""Canonical loading and coverage checks for gas-price panels."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd


def load_route_transaction_gas(
    path: Path,
    *,
    required_routes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Load exact receipt gas prices and prove transaction/block coverage."""

    if not path.exists():
        raise FileNotFoundError(f"route transaction gas panel does not exist: {path}")
    panel = pd.read_parquet(path)
    required_columns = {
        "tx_hash",
        "block_number",
        "effective_gas_price_wei",
        "gas_gwei",
        "gas_price_supported",
        "gas_price_support_reason",
        "base_fee_per_gas_wei",
        "base_fee_gwei",
        "base_fee_supported",
        "base_fee_support_reason",
    }
    missing_columns = sorted(required_columns - set(panel.columns))
    if missing_columns:
        raise ValueError(f"route transaction gas panel misses columns: {missing_columns}")
    panel = panel.copy()
    panel["tx_hash"] = panel["tx_hash"].astype(str).str.lower()
    panel["block_number"] = pd.to_numeric(panel["block_number"], errors="raise").astype(
        "int64"
    )
    panel["effective_gas_price_wei"] = pd.to_numeric(
        panel["effective_gas_price_wei"], errors="raise"
    )
    if panel.empty or panel["tx_hash"].duplicated().any():
        raise ValueError("route transaction gas panel is empty or duplicates transactions")
    if panel["effective_gas_price_wei"].isna().any() or panel[
        "effective_gas_price_wei"
    ].lt(0).any():
        raise ValueError("route transaction gas panel has missing or negative prices")
    supported = panel["gas_price_supported"].astype(bool)
    gas_gwei = pd.to_numeric(panel["gas_gwei"], errors="coerce")
    if gas_gwei[supported].isna().any() or not gas_gwei[supported].gt(0).all():
        raise ValueError("supported route transaction gas prices are not positive")
    if gas_gwei[~supported].notna().any():
        raise ValueError("unsupported route transaction gas prices must remain missing")
    base_fee = pd.to_numeric(panel["base_fee_per_gas_wei"], errors="coerce")
    base_supported = panel["base_fee_supported"].astype(bool)
    base_gwei = pd.to_numeric(panel["base_fee_gwei"], errors="coerce")
    if base_fee[base_supported].isna().any() or base_fee[base_supported].lt(0).any():
        raise ValueError("supported same-block base fees are missing or negative")
    if base_fee[~base_supported].notna().any() or base_gwei[~base_supported].notna().any():
        raise ValueError("unsupported same-block base fees must remain missing")
    if base_gwei[base_supported].isna().any() or base_gwei[base_supported].lt(0).any():
        raise ValueError("supported same-block base fees are not nonnegative")
    if required_routes is not None:
        expected = required_routes[["tx", "block"]].rename(
            columns={"tx": "tx_hash", "block": "block_number"}
        )
        expected["tx_hash"] = expected["tx_hash"].astype(str).str.lower()
        expected["block_number"] = pd.to_numeric(
            expected["block_number"], errors="raise"
        ).astype("int64")
        expected = expected.drop_duplicates()
        coverage = expected.merge(
            panel[["tx_hash", "block_number"]],
            on=["tx_hash", "block_number"],
            how="left",
            indicator=True,
            validate="one_to_one",
        )
        missing = int(coverage["_merge"].ne("both").sum())
        if missing:
            raise ValueError(f"route transaction gas panel misses {missing:,} exact routes")
    return panel.sort_values(["block_number", "tx_hash"]).reset_index(drop=True)


def load_daily_gas_prices(
    path: Path,
    *,
    required_dates: Iterable[object] | None = None,
) -> pd.DataFrame:
    """Load one positive, unique gas-price observation per day and check support."""
    if not path.exists():
        raise FileNotFoundError(f"daily gas-price panel does not exist: {path}")
    panel = pd.read_parquet(path)
    if "gas_gwei_median" not in panel:
        raise ValueError("daily gas-price panel is missing gas_gwei_median")
    if "date" in panel:
        dates = pd.to_datetime(panel["date"], errors="raise").dt.normalize()
    elif "day" in panel:
        dates = pd.to_datetime(panel["day"], format="%Y%m%d", errors="raise")
    else:
        raise ValueError("daily gas-price panel is missing date and day")
    panel = panel.copy()
    panel["date"] = dates
    panel["day"] = dates.dt.strftime("%Y%m%d")
    panel["gas_gwei_median"] = pd.to_numeric(
        panel["gas_gwei_median"], errors="raise"
    )
    if panel["date"].duplicated().any():
        raise ValueError("daily gas-price panel has duplicate dates")
    if panel["gas_gwei_median"].isna().any() or not panel[
        "gas_gwei_median"
    ].gt(0).all():
        raise ValueError("daily gas-price panel has missing or non-positive medians")
    if required_dates is not None:
        required = pd.DatetimeIndex(pd.to_datetime(list(required_dates))).normalize()
        missing = required.unique().difference(pd.DatetimeIndex(panel["date"]))
        if len(missing):
            raise ValueError(
                f"daily gas-price panel misses {len(missing):,} required dates "
                f"from {missing.min().date()} to {missing.max().date()}"
            )
    return panel.sort_values("date", kind="stable").reset_index(drop=True)

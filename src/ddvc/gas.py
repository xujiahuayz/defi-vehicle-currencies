"""Canonical loading and coverage checks for the daily gas-price panel."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd


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

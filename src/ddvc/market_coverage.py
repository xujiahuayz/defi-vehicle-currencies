"""Ethereum DEX-volume coverage for the exchange families in the route panel."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping


PANEL_PROTOCOLS = (
    "Uniswap V1",
    "Uniswap V2",
    "Uniswap V3",
    "Uniswap V4",
    "SushiSwap",
    "SushiSwap V3",
    "Curve DEX",
    "Balancer V2",
    "Fluid DEX",
    "Fluid DEX Lite",
)
DISPLAY_YEARS = tuple(range(2020, 2027))
PANEL_END = dt.date(2026, 6, 30)


def annual_market_coverage(
    breakdown: Iterable[object],
    *,
    protocols: Iterable[str] = PANEL_PROTOCOLS,
) -> list[dict[str, object]]:
    """Aggregate DeFiLlama's daily Ethereum series to paper-period coverage.

    The numerator is the volume assigned to the exchange families represented in
    the route panel.  The denominator is all Ethereum DEX volume in the same
    daily breakdown.  The external taxonomy is intentionally kept separate from
    the transaction-level source series used elsewhere in the paper.
    """

    selected_names = set(protocols)
    annual = {
        year: {"selected_usd": 0.0, "ethereum_dex_usd": 0.0, "days": 0}
        for year in DISPLAY_YEARS
    }
    seen_dates: set[dt.date] = set()
    for item in breakdown:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("DeFiLlama breakdown row must be [timestamp, mapping]")
        timestamp, raw_values = item
        if not isinstance(timestamp, (int, float)) or not isinstance(raw_values, Mapping):
            raise ValueError("DeFiLlama breakdown row has an invalid timestamp or mapping")
        date = dt.datetime.fromtimestamp(float(timestamp), tz=dt.timezone.utc).date()
        if date.year not in annual or date > PANEL_END:
            continue
        if date in seen_dates:
            raise ValueError(f"duplicate DeFiLlama date: {date.isoformat()}")
        seen_dates.add(date)
        values: dict[str, float] = {}
        for name, value in raw_values.items():
            if not isinstance(name, str) or not isinstance(value, (int, float)):
                raise ValueError(f"invalid DeFiLlama protocol value on {date.isoformat()}")
            numeric = float(value)
            if numeric < 0:
                raise ValueError(f"negative DeFiLlama volume on {date.isoformat()}")
            values[name] = numeric
        total = sum(values.values())
        if total <= 0:
            continue
        annual[date.year]["selected_usd"] += sum(
            value for name, value in values.items() if name in selected_names
        )
        annual[date.year]["ethereum_dex_usd"] += total
        annual[date.year]["days"] += 1

    rows: list[dict[str, object]] = []
    for year in DISPLAY_YEARS:
        cell = annual[year]
        total = float(cell["ethereum_dex_usd"])
        if total <= 0 or int(cell["days"]) <= 0:
            raise ValueError(f"DeFiLlama coverage lacks positive support in {year}")
        rows.append(
            {
                "year": year,
                "period": "H1" if year == PANEL_END.year else "full_year",
                "days": int(cell["days"]),
                "selected_usd": float(cell["selected_usd"]),
                "ethereum_dex_usd": total,
                "coverage_share": float(cell["selected_usd"]) / total,
            }
        )
    return rows

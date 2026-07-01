"""Source registry for raw market-data fetching.

The registry is intentionally explicit: every source has a genesis date, a
subgraph id, and a schema family. Fetch jobs clamp to each source's genesis so a
"from genesis" run does not waste quota on empty pre-launch days.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class DexSource:
    name: str
    subgraph_id: str
    schema: str
    genesis: dt.date
    notes: str = ""


DEX_SOURCES: dict[str, DexSource] = {
    "curve": DexSource(
        name="curve",
        subgraph_id="3fy93eAT56UJsRCEht8iFhfi6wjHWXtZ9dnnbQmvFopF",
        schema="messari",
        genesis=dt.date(2020, 2, 11),
        notes="Messari DEX schema; explicit tokenIn/tokenOut, n-token pools.",
    ),
    "uniswap_v2": DexSource(
        name="uniswap_v2",
        subgraph_id="EYCKATKGBKLWvSfwvBjzfCBmGwYNdVkduYXVivCsLRFu",
        schema="uniswap_v2",
        genesis=dt.date(2020, 5, 11),
        notes="Canonical V2 constant-product pair schema.",
    ),
    "balancer": DexSource(
        name="balancer",
        subgraph_id="C4ayEZP2yTXRAB8vSaTrgN4m9anTe9Mdm2ViyiAuV9TV",
        schema="balancer",
        genesis=dt.date(2021, 4, 22),
        notes="Balancer bespoke schema; explicit directed swaps and pool snapshots.",
    ),
    "uniswap_v3": DexSource(
        name="uniswap_v3",
        subgraph_id="5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV",
        schema="uniswap_v3",
        genesis=dt.date(2021, 5, 5),
        notes="V3 swaps plus mint/burn liquidity-position events.",
    ),
    "sushiswap_v3": DexSource(
        name="sushiswap_v3",
        subgraph_id="2tGWMrDha4164KkFAfkU3rDCtuxGb4q1emXmFdLLzJ8x",
        schema="messari",
        genesis=dt.date(2023, 4, 5),
        notes="Messari DEX schema for SushiSwap V3.",
    ),
    "uniswap_v4": DexSource(
        name="uniswap_v4",
        subgraph_id="DiYPVdygkfjDWhbxGSqAQxwBKmfKnkWQojqeM2rkLb3G",
        schema="uniswap_v4",
        genesis=dt.date(2025, 1, 24),
        notes="Official Uniswap V4 schema; modifyLiquidities captures LP updates.",
    ),
}


def get_source(name: str) -> DexSource:
    try:
        return DEX_SOURCES[name]
    except KeyError:
        known = ", ".join(sorted(DEX_SOURCES))
        raise KeyError(f"unknown source {name!r}; known sources: {known}") from None


def source_names(selection: list[str] | None) -> list[str]:
    if not selection or selection == ["all"]:
        return sorted(DEX_SOURCES)
    for name in selection:
        get_source(name)
    return selection


def last_complete_month_exclusive(today: dt.date | None = None) -> dt.date:
    """Exclusive end date for a sample through the end of the last full month."""
    today = today or dt.date.today()
    return dt.date(today.year, today.month, 1)


def iter_days(start: dt.date, end_exclusive: dt.date) -> list[dt.date]:
    days: list[dt.date] = []
    cur = start
    while cur < end_exclusive:
        days.append(cur)
        cur += dt.timedelta(days=1)
    return days

"""Source registry for raw market-data fetching.

The registry is intentionally explicit: every source has a backend, a schema
family, and a genesis block where known. Fetch jobs clamp to each source's
genesis date so a "from genesis" run does not waste quota on empty pre-launch
days, while retaining the block as the primary provenance anchor.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class DexSource:
    name: str
    schema: str
    genesis_date_utc: dt.date
    subgraph_id: str = ""
    backend: str = "thegraph"
    genesis_block: int | None = None
    dune_project: str | None = None
    dune_version: str | None = None
    notes: str = ""

    @property
    def genesis(self) -> dt.date:
        return self.genesis_date_utc


DEX_SOURCES: dict[str, DexSource] = {
    "curve": DexSource(
        name="curve",
        schema="messari",
        genesis_date_utc=dt.date(2020, 2, 11),
        subgraph_id="3fy93eAT56UJsRCEht8iFhfi6wjHWXtZ9dnnbQmvFopF",
        genesis_block=9_461_159,
        notes="Messari DEX schema; explicit tokenIn/tokenOut, n-token pools. Genesis is first raw-store swap block.",
    ),
    "uniswap_v1": DexSource(
        name="uniswap_v1",
        schema="dune_dex_trades",
        backend="dune",
        genesis_date_utc=dt.date(2018, 11, 2),
        genesis_block=6_627_917,
        dune_project="uniswap",
        dune_version="1",
        notes="Dune dex.trades source; Uniswap V1 subgraph exists but Dune gives routed swap legs and raw token amounts in the same schema.",
    ),
    "uniswap_v2": DexSource(
        name="uniswap_v2",
        schema="uniswap_v2",
        genesis_date_utc=dt.date(2020, 5, 11),
        subgraph_id="EYCKATKGBKLWvSfwvBjzfCBmGwYNdVkduYXVivCsLRFu",
        genesis_block=10_042_304,
        notes="Canonical V2 constant-product pair schema. Genesis is first raw-store swap block.",
    ),
    "balancer": DexSource(
        name="balancer",
        schema="balancer",
        genesis_date_utc=dt.date(2021, 4, 22),
        subgraph_id="C4ayEZP2yTXRAB8vSaTrgN4m9anTe9Mdm2ViyiAuV9TV",
        genesis_block=12_293_069,
        notes="Balancer bespoke schema; explicit directed swaps and pool snapshots. Genesis is first raw-store swap block.",
    ),
    "uniswap_v3": DexSource(
        name="uniswap_v3",
        schema="uniswap_v3",
        genesis_date_utc=dt.date(2021, 5, 5),
        subgraph_id="5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV",
        genesis_block=12_371_051,
        notes="V3 swaps plus mint/burn liquidity-position events. Genesis is first raw-store swap block.",
    ),
    "sushiswap_v2": DexSource(
        name="sushiswap_v2",
        schema="dune_dex_trades",
        backend="dune",
        genesis_date_utc=dt.date(2020, 8, 28),
        dune_project="sushiswap",
        dune_version="2",
        notes="Dune dex.trades source for SushiSwap cpAMM/V2; Sushi has no separate V1 AMM in this sample frame.",
    ),
    "sushiswap_v3": DexSource(
        name="sushiswap_v3",
        schema="messari",
        genesis_date_utc=dt.date(2023, 4, 5),
        subgraph_id="2tGWMrDha4164KkFAfkU3rDCtuxGb4q1emXmFdLLzJ8x",
        genesis_block=16_984_779,
        notes="Messari DEX schema for SushiSwap V3. Genesis is first raw-store swap block.",
    ),
    "uniswap_v4": DexSource(
        name="uniswap_v4",
        schema="uniswap_v4",
        genesis_date_utc=dt.date(2025, 1, 24),
        subgraph_id="DiYPVdygkfjDWhbxGSqAQxwBKmfKnkWQojqeM2rkLb3G",
        genesis_block=21_696_375,
        notes="Official Uniswap V4 schema; modifyLiquidities captures LP updates. Genesis is first raw-store swap block.",
    ),
    "fluid": DexSource(
        name="fluid",
        schema="dune_dex_trades",
        backend="dune",
        genesis_date_utc=dt.date(2024, 10, 29),
        genesis_block=21_071_249,
        dune_project="fluid",
        notes="Dune dex.trades source; no swap-level Graph subgraph exists on the decentralized network.",
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

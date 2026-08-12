"""Source registry for raw market-data fetching.

The registry is intentionally explicit: every source has a backend, a schema
family, and a genesis block where known. Fetch jobs clamp to each source's
genesis date so a "from genesis" run does not waste quota on empty pre-launch
days, while retaining the block as the primary provenance anchor.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


# Auxiliary current-schema deployment used only to fill immutable pool statics into
# signed v4 swap records from the canonical deployment. Its swap amounts are unsigned,
# so it must never replace the canonical raw stream wholesale.
UNISWAP_V4_STATICS_SUBGRAPH_ID = "8B2wKxnkciCTc5HSgsAojF6vhKn6wxQ1nVecYzMge1hA"


@dataclass(frozen=True)
class DexSource:
    name: str
    schema: str
    genesis_date_utc: dt.date
    subgraph_id: str = ""
    graph_path: str = "subgraphs/id"
    backend: str = "thegraph"
    genesis_block: int | None = None
    factory_address: str | None = None
    factory_deployment_block: int | None = None
    dune_project: str | None = None
    dune_version: str | None = None
    route_normalizer_family: str | None = None
    notes: str = ""

    @property
    def genesis(self) -> dt.date:
        return self.genesis_date_utc


DEX_SOURCES: dict[str, DexSource] = {
    "curve": DexSource(
        name="curve",
        schema="curve",
        genesis_date_utc=dt.date(2020, 2, 11),
        subgraph_id="3fy93eAT56UJsRCEht8iFhfi6wjHWXtZ9dnnbQmvFopF",
        genesis_block=9_461_159,
        route_normalizer_family="messari",
        notes="Messari DEX schema; explicit tokenIn/tokenOut, n-token pools. Genesis is first raw-store swap block.",
    ),
    "uniswap_v1": DexSource(
        name="uniswap_v1",
        schema="uniswap_v1",
        genesis_date_utc=dt.date(2018, 11, 2),
        subgraph_id="ESnjgAG9NjfmHypk4Huu4PVvz55fUwpyrRqHF21thoLJ",
        genesis_block=6_628_280,
        notes="Uniswap V1 subgraph; raw transactions carry token/ETH purchase events against exchange addresses.",
    ),
    "uniswap_v2": DexSource(
        name="uniswap_v2",
        schema="uniswap_v2",
        genesis_date_utc=dt.date(2020, 5, 5),
        subgraph_id="EYCKATKGBKLWvSfwvBjzfCBmGwYNdVkduYXVivCsLRFu",
        genesis_block=10_008_566,
        factory_address="0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f",
        route_normalizer_family="uni_v2",
        notes="Canonical V2 constant-product pair schema. Genesis is first indexed swap block from live Graph audit.",
    ),
    "balancer": DexSource(
        name="balancer",
        schema="balancer",
        genesis_date_utc=dt.date(2021, 4, 22),
        subgraph_id="C4ayEZP2yTXRAB8vSaTrgN4m9anTe9Mdm2ViyiAuV9TV",
        genesis_block=12_293_069,
        route_normalizer_family="balancer",
        notes="Balancer bespoke schema; explicit directed swaps and pool snapshots. Genesis is first raw-store swap block.",
    ),
    "uniswap_v3": DexSource(
        name="uniswap_v3",
        schema="uniswap_v3",
        genesis_date_utc=dt.date(2021, 5, 4),
        subgraph_id="5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV",
        genesis_block=12_369_879,
        factory_deployment_block=12_369_621,
        route_normalizer_family="uni_signed",
        notes="V3 swaps plus mint/burn liquidity-position events. Genesis is the first indexed swap block from the live Graph audit; factory deployment is a separate on-chain perimeter.",
    ),
    "sushiswap_v2": DexSource(
        name="sushiswap_v2",
        schema="sushiswap_v2",
        genesis_date_utc=dt.date(2020, 9, 4),
        subgraph_id="QmaR2nAMF6dCHBL1eFNQ4F5nGpJQs7V11PZobJB2FgQtbt",
        graph_path="deployments/id",
        genesis_block=10_794_365,
        factory_address="0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac",
        route_normalizer_family="uni_v2",
        notes="SushiSwap cpAMM/V2 deployment endpoint; Sushi has no separate V1 AMM in this sample frame.",
    ),
    "sushiswap_v3": DexSource(
        name="sushiswap_v3",
        schema="sushiswap_v3",
        genesis_date_utc=dt.date(2023, 4, 5),
        subgraph_id="2tGWMrDha4164KkFAfkU3rDCtuxGb4q1emXmFdLLzJ8x",
        genesis_block=16_984_779,
        route_normalizer_family="messari",
        notes="Messari DEX schema for SushiSwap V3. Genesis is first raw-store swap block.",
    ),
    "uniswap_v4": DexSource(
        name="uniswap_v4",
        schema="uniswap_v4",
        genesis_date_utc=dt.date(2025, 1, 24),
        subgraph_id="DiYPVdygkfjDWhbxGSqAQxwBKmfKnkWQojqeM2rkLb3G",
        genesis_block=21_696_375,
        route_normalizer_family="uni_signed",
        notes="Signed Uniswap V4 schema; modifyLiquidities captures LP updates. Missing immutable pool statics can be enriched by exact record ID from the auxiliary current-schema deployment.",
    ),
    "fluid": DexSource(
        name="fluid",
        schema="dune_dex_trades",
        backend="dune",
        genesis_date_utc=dt.date(2024, 10, 29),
        genesis_block=21_071_249,
        dune_project="fluid",
        route_normalizer_family="fluid",
        notes="Dune dex.trades source; no swap-level Graph subgraph exists on the decentralized network.",
    ),
}

ROUTE_SOURCE_FAMILIES: dict[str, str] = {
    name: source.route_normalizer_family
    for name, source in DEX_SOURCES.items()
    if source.route_normalizer_family is not None
}
ROUTE_SOURCE_STREAMS: dict[str, str] = {
    name: "swaps" for name in ROUTE_SOURCE_FAMILIES
}
ROUTE_DUNE_SOURCES = frozenset(
    name
    for name in ROUTE_SOURCE_FAMILIES
    if DEX_SOURCES[name].backend == "dune"
)


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

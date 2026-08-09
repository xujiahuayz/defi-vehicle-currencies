#!/usr/bin/env python3
"""Fetch immutable V3 pool statics at the locked sample cutoff.

Legacy pool-day captures retain total capital but often omit token addresses.
Symbols are not identities. This raw-first fetch obtains the complete pool registry
at one historical block, validates every address through CREATE2, and refuses to
publish unless it covers every pool in the locked daily-capital perimeter.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json

from ddvc.fetch.graph import GraphClient, graph_keys, head_block, paginate
from ddvc.fetch.pool_daily import daily_pool_identity_perimeter, pool_identity_values
from ddvc.fetch.raw import write_json, write_jsonl_gz
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.pricing.v3pools import derive_fee_tier
from ddvc.runtime import exclusive_job


VENUE = "uniswap_v3"
SAMPLE_DAY = "20260630"
SAMPLE_BLOCK = 25_433_938
FIELDS = "id feeTier token0 { id symbol decimals } token1 { id symbol decimals }"
RAW_DIRECTORY = DATA_DIR / "raw" / "thegraph"
OUTPUT = RAW_DIRECTORY / VENUE / f"{VENUE}_pool_statics_{SAMPLE_DAY}.jsonl.gz"
METADATA = RAW_DIRECTORY / VENUE / f"{VENUE}_pool_statics_{SAMPLE_DAY}.meta.json"


def validate_rows(
    rows: list[dict[str, object]],
    daily_pools: set[str],
    pools_needing_identity: set[str],
) -> dict[str, int]:
    identities: dict[str, tuple[str, str]] = {}
    for row in rows:
        resolved = pool_identity_values(row)
        if resolved is None:
            raise ValueError("pool-static row lacks an exact pool or ordered token identity")
        pool, identity = resolved
        if pool in identities:
            raise ValueError(f"duplicate pool-static identity: {pool}")
        identities[pool] = (identity.token0_address, identity.token1_address)
        try:
            fee = int(row.get("feeTier") or 0)
        except (TypeError, ValueError):
            fee = 0
        if derive_fee_tier(pool, identity.token0_address, identity.token1_address) != fee:
            raise ValueError(f"pool-static CREATE2 identity or fee mismatch: {pool}")
    missing = pools_needing_identity - set(identities)
    if missing:
        raise ValueError(
            f"pool-static registry misses {len(missing):,}/{len(pools_needing_identity):,} "
            f"sample identity gaps; first={sorted(missing)[0]}"
        )
    return {
        "rows": len(rows),
        "sample_pools": len(daily_pools),
        "sample_pools_needing_identity": len(pools_needing_identity),
        "sample_identity_gaps_resolved": len(pools_needing_identity) - len(missing),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if OUTPUT.exists() and METADATA.exists() and not args.force:
        print(f"pool statics already exist: {OUTPUT.name}")
        return 0
    source = get_source(VENUE)
    daily_files = sorted((RAW_DIRECTORY / VENUE).glob(f"{VENUE}_daily_????????.jsonl.gz"))
    daily_pools, pools_needing_identity = daily_pool_identity_perimeter(
        VENUE,
        daily_files,
    )
    client = GraphClient(source.subgraph_id, graph_keys(), graph_path=source.graph_path)
    provider_head = head_block(client)
    if provider_head is None or provider_head < SAMPLE_BLOCK:
        raise RuntimeError(
            f"provider head {provider_head} does not cover sample block {SAMPLE_BLOCK}"
        )
    def progress(rows: int, _last_id: str) -> None:
        if rows % 10_000 == 0:
            print(f"  pool statics fetched: {rows:,}", flush=True)

    rows = paginate(
        client,
        entity="pools",
        fields=FIELDS,
        base_where={},
        block_number=SAMPLE_BLOCK,
        progress=progress,
    )
    summary = validate_rows(rows, daily_pools, pools_needing_identity)
    write_jsonl_gz(OUTPUT, rows)
    write_json(
        METADATA,
        {
            "source": VENUE,
            "entity": "pools",
            "historical_block": SAMPLE_BLOCK,
            "sample_day": SAMPLE_DAY,
            "provider_head_at_fetch": provider_head,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "fields": FIELDS,
            "validation": "ordered token identities plus canonical V3 CREATE2 fee match",
            **summary,
        },
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    with exclusive_job(
        RAW_MARKET_DATA_LOCK,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        raise SystemExit(main())

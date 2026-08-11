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
import gzip
import json

from ddvc.fetch.graph import GraphClient, graph_keys, head_block, paginate
from ddvc.fetch.pool_daily import (
    UNISWAP_V3_STATIC_FIELDS,
    UNISWAP_V3_STATIC_QUERY_CONTRACT,
    UNISWAP_V3_STATIC_VALIDATION,
    daily_pool_identity_perimeter,
    pool_identity_values,
)
from ddvc.fetch.raw import write_json, write_jsonl_gz
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.pricing.v3pools import derive_fee_tier
from ddvc.provenance import portable_content_sha256
from ddvc.ethereum_logs import file_sha256
from ddvc.artifact_release import file_stat_identity
from ddvc.runtime import exclusive_job


VENUE = "uniswap_v3"
SAMPLE_DAY = "20260630"
SAMPLE_BLOCK = 25_433_938
FIELDS = UNISWAP_V3_STATIC_FIELDS
RAW_DIRECTORY = DATA_DIR / "raw" / "thegraph"
OUTPUT = RAW_DIRECTORY / VENUE / f"{VENUE}_pool_statics_{SAMPLE_DAY}.jsonl.gz"
METADATA = RAW_DIRECTORY / VENUE / f"{VENUE}_pool_statics_{SAMPLE_DAY}.meta.json"


def query_contract() -> dict[str, object]:
    return {**UNISWAP_V3_STATIC_QUERY_CONTRACT, "historical_block": SAMPLE_BLOCK}


def _read_existing_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with gzip.open(OUTPUT, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("pool-static snapshot contains a non-object row")
                rows.append(row)
    return rows


def snapshot_metadata(
    summary: dict[str, int],
    *,
    provider_head: int,
    fetched_at_utc: str,
    recertified_at_utc: str | None = None,
    container_sha256: str | None = None,
    logical_content_sha256: str | None = None,
) -> dict[str, object]:
    metadata = {
        "source": VENUE,
        "entity": "pools",
        "historical_block": SAMPLE_BLOCK,
        "sample_day": SAMPLE_DAY,
        "provider_head_at_fetch": provider_head,
        "fetched_at_utc": fetched_at_utc,
        "fields": FIELDS,
        "query_contract": query_contract(),
        "validation": UNISWAP_V3_STATIC_VALIDATION,
        "container_sha256": container_sha256 or file_sha256(OUTPUT),
        "logical_content_sha256": logical_content_sha256 or portable_content_sha256(OUTPUT),
        **summary,
    }
    if recertified_at_utc is not None:
        metadata["recertified_at_utc"] = recertified_at_utc
    return metadata


def _recertify_existing(
    daily_pools: set[str],
    pools_needing_identity: set[str],
) -> dict[str, int]:
    if not OUTPUT.is_file() or not METADATA.is_file():
        raise RuntimeError("pool-static recertification requires the existing snapshot and metadata")
    prior = json.loads(METADATA.read_text(encoding="utf-8"))
    if (
        not isinstance(prior, dict)
        or prior.get("source") != VENUE
        or prior.get("entity") != "pools"
        or str(prior.get("sample_day")) != SAMPLE_DAY
        or int(prior.get("historical_block", -1)) != SAMPLE_BLOCK
        or prior.get("fields") != FIELDS
        or prior.get("validation") != UNISWAP_V3_STATIC_VALIDATION
    ):
        raise ValueError("legacy pool-static metadata cannot establish the canonical producer contract")
    before_identity = file_stat_identity(OUTPUT)
    container_sha256 = file_sha256(OUTPUT)
    logical_content_sha256 = portable_content_sha256(OUTPUT)
    summary = validate_rows(_read_existing_rows(), daily_pools, pools_needing_identity)
    after_identity = file_stat_identity(OUTPUT)
    if (
        before_identity != after_identity
        or file_sha256(OUTPUT) != container_sha256
        or portable_content_sha256(OUTPUT) != logical_content_sha256
    ):
        raise RuntimeError("pool-static snapshot mutated during recertification")
    now = datetime.now(timezone.utc).isoformat()
    write_json(
        METADATA,
        snapshot_metadata(
            summary,
            provider_head=int(prior["provider_head_at_fetch"]),
            fetched_at_utc=str(prior["fetched_at_utc"]),
            recertified_at_utc=now,
            container_sha256=container_sha256,
            logical_content_sha256=logical_content_sha256,
        ),
    )
    if file_sha256(OUTPUT) != container_sha256 or portable_content_sha256(OUTPUT) != logical_content_sha256:
        raise RuntimeError("pool-static snapshot mutated while installing recertification metadata")
    return summary


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
    parser.add_argument("--recertify-existing", action="store_true")
    args = parser.parse_args()
    if args.force and args.recertify_existing:
        parser.error("--force and --recertify-existing are mutually exclusive")
    daily_files = sorted((RAW_DIRECTORY / VENUE).glob(f"{VENUE}_daily_????????.jsonl.gz"))
    daily_pools, pools_needing_identity = daily_pool_identity_perimeter(
        VENUE,
        daily_files,
    )
    if args.recertify_existing:
        summary = _recertify_existing(daily_pools, pools_needing_identity)
        print(json.dumps(summary, sort_keys=True))
        return 0
    if OUTPUT.exists() and METADATA.exists() and not args.force:
        metadata = json.loads(METADATA.read_text(encoding="utf-8"))
        current = snapshot_metadata(
            validate_rows(_read_existing_rows(), daily_pools, pools_needing_identity),
            provider_head=int(metadata.get("provider_head_at_fetch", -1)),
            fetched_at_utc=str(metadata.get("fetched_at_utc") or ""),
            recertified_at_utc=(str(metadata["recertified_at_utc"]) if metadata.get("recertified_at_utc") else None),
        )
        if metadata != current:
            raise RuntimeError("pool-static metadata requires --recertify-existing")
        print(f"pool statics already exist: {OUTPUT.name}")
        return 0
    source = get_source(VENUE)
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
        snapshot_metadata(
            summary,
            provider_head=provider_head,
            fetched_at_utc=datetime.now(timezone.utc).isoformat(),
        ),
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    with exclusive_job(
        RAW_MARKET_DATA_LOCK,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        raise SystemExit(main())

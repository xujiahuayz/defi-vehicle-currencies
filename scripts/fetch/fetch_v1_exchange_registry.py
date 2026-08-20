#!/usr/bin/env python3
"""Fetch the immutable Uniswap V1 exchange-to-token registry.

The original daily V1 pull retained each exchange address but omitted the token
address.  V1 creates one exchange per ERC-20 token, so this is a single static
lookup rather than another day-by-day market-data stream.

Writes  data/raw/thegraph/uniswap_v1/uniswap_v1_exchange_registry.jsonl.gz
        data/raw/thegraph/uniswap_v1/uniswap_v1_exchange_registry_meta.json

Run     ./scripts/run scripts/fetch/fetch_v1_exchange_registry.py
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import re

from ddvc.fetch.graph import GraphClient, graph_keys, head_block, paginate
from ddvc.fetch.raw import write_json, write_jsonl_gz
from ddvc.fetch.sources import get_source
from ddvc.paths import DATA_DIR, RAW_MARKET_DATA_LOCK
from ddvc.runtime import exclusive_job


VENUE = "uniswap_v1"
FIELDS = "id tokenAddress tokenSymbol"
RAW_DIR = DATA_DIR / "raw" / "thegraph" / VENUE
OUTPUT = RAW_DIR / f"{VENUE}_exchange_registry.jsonl.gz"
METADATA = RAW_DIR / f"{VENUE}_exchange_registry_meta.json"
ADDRESS = re.compile(r"0x[0-9a-f]{40}")


def read_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with gzip.open(OUTPUT, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("V1 exchange registry contains a non-object row")
                rows.append(row)
    return rows


def validate_rows(rows: list[dict[str, object]]) -> dict[str, int]:
    exchanges: set[str] = set()
    tokens: set[str] = set()
    for row in rows:
        exchange = str(row.get("id") or "").lower()
        token = str(row.get("tokenAddress") or "").lower()
        if not ADDRESS.fullmatch(exchange) or not ADDRESS.fullmatch(token):
            raise ValueError("V1 exchange registry contains an invalid address")
        if exchange in exchanges:
            raise ValueError(f"duplicate V1 exchange address: {exchange}")
        if token in tokens:
            raise ValueError(f"duplicate V1 token address: {token}")
        exchanges.add(exchange)
        tokens.add(token)
    if not rows:
        raise ValueError("V1 exchange registry is empty")
    return {"rows": len(rows), "unique_exchanges": len(exchanges), "unique_tokens": len(tokens)}


def main() -> int:
    if OUTPUT.exists():
        summary = validate_rows(read_rows())
        if not METADATA.is_file():
            raise FileNotFoundError(f"registry metadata is missing: {METADATA}")
        print(json.dumps({**summary, "status": "already_present"}, sort_keys=True))
        return 0

    source = get_source(VENUE)
    client = GraphClient(source.subgraph_id, graph_keys(), graph_path=source.graph_path)
    # This legacy subgraph answers entity queries but its surviving indexers reject
    # `_meta`.  The registry is immutable after each exchange is created, so a current
    # complete snapshot is the relevant object and does not need a historical block.
    try:
        block = head_block(client)
    except RuntimeError:
        block = None

    def progress(n: int, _last_id: str) -> None:
        print(f"  V1 exchanges fetched: {n:,}", flush=True)

    rows = paginate(
        client,
        entity="exchanges",
        fields=FIELDS,
        base_where={},
        block_number=block,
        progress=progress,
    )
    summary = validate_rows(rows)
    write_jsonl_gz(OUTPUT, rows)
    write_json(
        METADATA,
        {
            "source": VENUE,
            "subgraph_id": source.subgraph_id,
            "entity": "exchanges",
            "fields": FIELDS.split(),
            "head_block_at_fetch": block,
            "snapshot": "current immutable exchange registry",
            "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            **summary,
        },
    )
    print(json.dumps({**summary, "head_block_at_fetch": block}, sort_keys=True))
    return 0


if __name__ == "__main__":
    with exclusive_job(
        RAW_MARKET_DATA_LOCK,
        job="raw market-data fetch, enrichment, or canonical materialisation",
    ):
        raise SystemExit(main())

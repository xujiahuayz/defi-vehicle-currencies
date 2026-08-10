"""Canonical Ethereum JSON-RPC log storage shared across protocol audits."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.fetch.raw import write_json
from ddvc.quoter import rpc_post
from ddvc.runtime import atomic_output


RAW_LOG_STORAGE_FORMAT = "exact_rpc_log_parquet_v1"
EXACT_LOG_BLOCK_CAP = 50
RAW_LOG_SCHEMA = pa.schema(
    [
        pa.field("address", pa.string(), nullable=False),
        pa.field("block_number", pa.int64(), nullable=False),
        pa.field("block_hash", pa.string(), nullable=False),
        pa.field("transaction_hash", pa.string(), nullable=False),
        pa.field("transaction_index", pa.int64(), nullable=False),
        pa.field("log_index", pa.int64(), nullable=False),
        pa.field("topics", pa.list_(pa.string()), nullable=False),
        pa.field("data", pa.string(), nullable=False),
        pa.field("removed", pa.bool_(), nullable=False),
    ]
)


def block_ranges(start: int, end: int, chunk_size: int) -> list[tuple[int, int]]:
    """Partition an inclusive block perimeter exactly once on aligned boundaries."""

    if start < 0 or end < start or chunk_size <= 0:
        raise ValueError("invalid block-range perimeter")
    ranges: list[tuple[int, int]] = []
    lower = start
    while lower <= end:
        upper = min(((lower // chunk_size) + 1) * chunk_size - 1, end)
        ranges.append((lower, upper))
        lower = upper + 1
    return ranges


def exact_log_block_ranges(
    start: int,
    end: int,
    *,
    aligned: bool = False,
) -> list[tuple[int, int]]:
    """Partition exact-log work under the live provider's deterministic block cap."""

    if start < 0 or end < start:
        raise ValueError("invalid exact-log block perimeter")
    if not aligned:
        return block_ranges(start, end, EXACT_LOG_BLOCK_CAP)
    first = (start // EXACT_LOG_BLOCK_CAP) * EXACT_LOG_BLOCK_CAP
    last = (end // EXACT_LOG_BLOCK_CAP) * EXACT_LOG_BLOCK_CAP
    return [
        (lower, lower + EXACT_LOG_BLOCK_CAP - 1)
        for lower in range(first, last + 1, EXACT_LOG_BLOCK_CAP)
    ]


def rpc_integer(value: object) -> int:
    if isinstance(value, int):
        return value
    text = str(value)
    return int(text, 16) if text.startswith("0x") else int(text)


def canonical_raw_log(log: dict[str, object]) -> dict[str, object]:
    """Retain every field needed to re-decode and identify one exact RPC log."""

    topics = [str(value).lower() for value in log.get("topics") or []]
    record = {
        "address": str(log.get("address") or "").lower(),
        "block_number": rpc_integer(log.get("blockNumber")),
        "block_hash": str(log.get("blockHash") or "").lower(),
        "transaction_hash": str(log.get("transactionHash") or "").lower(),
        "transaction_index": rpc_integer(log.get("transactionIndex")),
        "log_index": rpc_integer(log.get("logIndex")),
        "topics": topics,
        "data": str(log.get("data") or "0x").lower(),
        "removed": bool(log.get("removed", False)),
    }
    if (
        not record["address"]
        or not record["block_hash"]
        or not record["transaction_hash"]
        or not topics
    ):
        raise ValueError("RPC log lacks exact block, transaction, address, or topic identity")
    return record


def fetch_exact_logs(
    *,
    start_block: int,
    end_block: int,
    topics: list[str],
    address: str | None = None,
    rpc_request=rpc_post,
) -> list[dict[str, object]]:
    """Fetch and validate one exact inclusive Ethereum log perimeter."""

    if start_block < 0 or end_block < start_block or not topics:
        raise ValueError("invalid Ethereum log query perimeter")
    normalized_topics = [str(topic).lower() for topic in topics]
    log_filter: dict[str, object] = {
        "fromBlock": hex(start_block),
        "toBlock": hex(end_block),
        "topics": [normalized_topics if len(normalized_topics) > 1 else normalized_topics[0]],
    }
    normalized_address = str(address).lower() if address is not None else None
    if normalized_address is not None:
        log_filter["address"] = normalized_address
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getLogs",
        "params": [log_filter],
    }
    response = rpc_request(
        payload,
        timeout=30,
        retries=1,
        retry_json_errors=True,
    )
    logs = response.get("result") if isinstance(response, dict) else None
    if not isinstance(logs, list):
        raise RuntimeError(
            f"Ethereum log response lacks a result list for {start_block}:{end_block}"
        )
    allowed_topics = set(normalized_topics)
    keys: set[tuple[int, str, int, str]] = set()
    records: list[dict[str, object]] = []
    for log in logs:
        record = canonical_raw_log(log)
        block = int(record["block_number"])
        pool = str(record["address"])
        topic = str(record["topics"][0])
        if not start_block <= block <= end_block:
            raise ValueError("Ethereum log lies outside its requested block range")
        if normalized_address is not None and pool != normalized_address:
            raise ValueError("Ethereum log lies outside its requested address filter")
        if topic not in allowed_topics:
            raise ValueError("Ethereum log lies outside its requested topic filter")
        key = (block, str(record["transaction_hash"]), int(record["log_index"]), pool)
        if key in keys:
            raise ValueError(f"duplicate exact Ethereum log in one chunk: {key}")
        keys.add(key)
        records.append(record)
    return records


def write_exact_log_chunk(
    raw_path: Path,
    marker_path: Path,
    records: list[dict[str, object]],
    marker: dict[str, object],
) -> dict[str, object]:
    """Atomically publish exact logs first and their completeness marker last."""

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(raw_path) as temporary:
        pq.write_table(
            pa.Table.from_pylist(records, schema=RAW_LOG_SCHEMA),
            temporary,
            compression="zstd",
            use_dictionary=True,
        )
    payload = {
        "status": "complete",
        **marker,
        "storage_format": RAW_LOG_STORAGE_FORMAT,
        "raw_logs": len(records),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(marker_path, payload)
    return payload

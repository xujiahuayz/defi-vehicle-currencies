"""Canonical Ethereum JSON-RPC log storage shared across protocol audits."""

from __future__ import annotations

import pyarrow as pa


RAW_LOG_STORAGE_FORMAT = "exact_rpc_log_parquet_v1"
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

"""Canonical Ethereum JSON-RPC log storage shared across protocol audits."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ddvc.fetch.raw import write_json
from ddvc.quoter import (
    RpcCapacityError as ExactLogCapacityError,
    RpcEnvelope,
    RpcSemanticError as ExactLogRpcError,
    rpc_post,
)
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


def coerce_rpc_envelope(response: object) -> RpcEnvelope:
    """Wrap injected test transports in the same evidence shape as live RPC."""

    if isinstance(response, RpcEnvelope) and response.attempts:
        return response
    endpoint = (
        response.endpoint
        if isinstance(response, RpcEnvelope)
        else {"host": "injected", "endpoint_sha256": "0" * 64}
    )
    attempt = {
        "endpoint": endpoint,
        "attempt": 1,
        "classification": "success",
        "http_status": None,
        "rpc_code": None,
        "message": "success",
    }
    payload = response.response if isinstance(response, RpcEnvelope) else response
    return RpcEnvelope(payload, endpoint, (attempt,))


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text.lower())


def frozen_block_rpc_request(block: int, *, rpc_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "eth_getBlockByNumber",
        "params": [hex(block), False],
    }


def validate_frozen_block(
    record: dict[str, object],
    block: int,
    *,
    schema_version: int,
) -> None:
    """Revalidate one persisted exact block-header response and copied identity."""

    if (
        record.get("status") != "complete"
        or int(record.get("schema_version", -1)) != schema_version
        or int(record.get("block_number", -1)) != block
    ):
        raise ValueError("frozen upper-block evidence is stale")
    endpoint = record.get("rpc_endpoint")
    attempts = record.get("rpc_attempts")
    if not isinstance(endpoint, dict) or not is_sha256(endpoint.get("endpoint_sha256")):
        raise ValueError("frozen upper-block evidence lacks a sanitized endpoint identity")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("frozen upper-block evidence lacks RPC attempt history")
    expected_request = frozen_block_rpc_request(block)
    if record.get("rpc_request") != expected_request:
        raise ValueError("frozen upper-block evidence lacks its exact RPC request")
    response = record.get("rpc_response")
    if not isinstance(response, dict) or response.get("id") != 1:
        raise ValueError("frozen upper-block evidence lacks its exact RPC response")
    if record.get("response_sha256") != canonical_json_sha256(response):
        raise ValueError("frozen upper-block response digest disagrees")
    header = response.get("result")
    if not isinstance(header, dict):
        raise ValueError("frozen upper-block RPC response lacks a header")
    observed = {
        "block_number": rpc_integer(header.get("number")),
        "block_hash": str(header.get("hash") or "").lower(),
        "parent_hash": str(header.get("parentHash") or "").lower(),
        "timestamp": rpc_integer(header.get("timestamp")),
    }
    copied = {
        "block_number": int(record["block_number"]),
        "block_hash": str(record["block_hash"]),
        "parent_hash": str(record["parent_hash"]),
        "timestamp": int(record["timestamp"]),
    }
    if observed != copied:
        raise ValueError("frozen upper-block copied fields disagree with the RPC response")
    if not all(
        str(copied[field]).startswith("0x") and len(str(copied[field])) == 66
        for field in ("block_hash", "parent_hash")
    ) or copied["timestamp"] < 1:
        raise ValueError("frozen upper-block evidence lacks an exact header identity")
    if record.get("header_identity_sha256") != canonical_json_sha256(copied):
        raise ValueError("frozen upper-block identity digest disagrees")


def load_or_resolve_frozen_block(
    block: int,
    *,
    path: Path,
    schema_version: int,
    fetch: bool,
    rpc_request=None,
) -> dict[str, object]:
    """Load or atomically persist one exact frozen header with transport evidence."""

    if path.is_file():
        record = json.loads(path.read_text(encoding="utf-8"))
        validate_frozen_block(record, block, schema_version=schema_version)
        return record
    if not fetch:
        raise RuntimeError(f"frozen upper-block evidence is absent for {block}")
    request = frozen_block_rpc_request(block)
    envelope = (
        rpc_post_with_evidence(request)
        if rpc_request is None
        else coerce_rpc_envelope(rpc_request(request, timeout=30, retries=2))
    )
    header = envelope.response.get("result") if isinstance(envelope.response, dict) else None
    if not isinstance(header, dict):
        raise RuntimeError(f"eth_getBlockByNumber lacks an exact result for frozen block {block}")
    record = {
        "status": "complete",
        "schema_version": schema_version,
        "block_number": rpc_integer(header.get("number")),
        "block_hash": str(header.get("hash") or "").lower(),
        "parent_hash": str(header.get("parentHash") or "").lower(),
        "timestamp": rpc_integer(header.get("timestamp")),
        "rpc_request": request,
        "rpc_response": envelope.response,
        "rpc_endpoint": envelope.endpoint,
        "rpc_attempts": list(envelope.attempts),
        "response_sha256": canonical_json_sha256(envelope.response),
    }
    record["header_identity_sha256"] = canonical_json_sha256(
        {
            "block_number": record["block_number"],
            "block_hash": record["block_hash"],
            "parent_hash": record["parent_hash"],
            "timestamp": record["timestamp"],
        }
    )
    validate_frozen_block(record, block, schema_version=schema_version)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    return record


def validate_anchored_log_evidence(
    marker: dict[str, object],
    records: list[dict[str, object]],
    frozen_upper: dict[str, object],
) -> None:
    """Revalidate one canonical log response and its same-endpoint frozen header."""

    validate_frozen_block(
        frozen_upper,
        int(frozen_upper["block_number"]),
        schema_version=int(frozen_upper["schema_version"]),
    )
    endpoint = marker.get("rpc_endpoint")
    attempts = marker.get("rpc_attempts")
    if not isinstance(endpoint, dict) or not is_sha256(endpoint.get("endpoint_sha256")):
        raise ValueError("exact-log evidence lacks a sanitized endpoint identity")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("exact-log evidence lacks RPC attempt history")
    frozen_request = frozen_block_rpc_request(int(frozen_upper["block_number"]), rpc_id=2)
    if marker.get("frozen_upper_request") != frozen_request:
        raise ValueError("exact-log evidence names a different frozen-upper request")
    topics = [str(topic).lower() for topic in marker.get("event_topics") or []]
    log_filter: dict[str, object] = {
        "fromBlock": hex(int(marker["start_block"])),
        "toBlock": hex(int(marker["end_block"])),
        "topics": [topics if len(topics) > 1 else topics[0]],
    }
    address = marker.get("address_filter")
    if address is not None:
        log_filter["address"] = str(address).lower()
    expected_log_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getLogs",
        "params": [log_filter],
    }
    batch_request = marker.get("rpc_request")
    if (
        not isinstance(batch_request, list)
        or len(batch_request) != 2
        or batch_request[0] != expected_log_request
        or batch_request[1] != frozen_request
    ):
        raise ValueError("exact-log evidence lacks its exact two-item request")
    frozen_response = marker.get("frozen_upper_response")
    if not isinstance(frozen_response, dict) or frozen_response.get("id") != 2:
        raise ValueError("exact-log evidence lacks its frozen-upper response")
    header = frozen_response.get("result")
    if not isinstance(header, dict):
        raise ValueError("exact-log evidence lacks a frozen-upper header")
    expected_header = {
        "number": int(frozen_upper["block_number"]),
        "hash": str(frozen_upper["block_hash"]).lower(),
        "parentHash": str(frozen_upper["parent_hash"]).lower(),
        "timestamp": int(frozen_upper["timestamp"]),
    }
    observed_header = {
        "number": rpc_integer(header.get("number")),
        "hash": str(header.get("hash") or "").lower(),
        "parentHash": str(header.get("parentHash") or "").lower(),
        "timestamp": rpc_integer(header.get("timestamp")),
    }
    if observed_header != expected_header:
        raise ValueError("exact-log endpoint disagrees with the frozen upper header")
    if marker.get("frozen_upper_response_sha256") != canonical_json_sha256(frozen_response):
        raise ValueError("exact-log frozen-upper response digest disagrees")
    canonical_response_evidence = {
        "logs": records,
        "frozen_upper_response": frozen_response,
    }
    if marker.get("response_sha256") != canonical_json_sha256(canonical_response_evidence):
        raise ValueError("exact-log canonical response digest disagrees")


def rpc_post_with_evidence(
    payload: dict[str, object] | list[dict[str, object]],
    *,
    timeout: int = 30,
    retries: int = 2,
    retry_delay: float = 0.5,
) -> RpcEnvelope:
    """Call the canonical RPC transport and retain sanitized attempt evidence."""

    envelope = rpc_post(
        payload,
        timeout=timeout,
        retries=retries,
        retry_json_errors=True,
        return_evidence=True,
        classify_capacity=True,
        retry_delay=retry_delay,
    )
    if not isinstance(envelope, RpcEnvelope):
        raise TypeError("evidence RPC transport returned an unwrapped response")
    return envelope


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


def _exact_hex(value: object, *, length: int | None = None) -> bool:
    text = str(value or "").lower()
    if not text.startswith("0x") or (len(text) - 2) % 2:
        return False
    if length is not None and len(text) != length:
        return False
    return all(character in "0123456789abcdef" for character in text[2:])


def validate_canonical_log_records(
    records: list[dict[str, object]],
    *,
    start_block: int,
    end_block: int,
    topics: list[str],
    address: str | None,
) -> list[dict[str, object]]:
    """Revalidate stored canonical rows against the exact query perimeter."""

    allowed_topics = {str(topic).lower() for topic in topics}
    normalized_address = str(address).lower() if address is not None else None
    keys: set[tuple[int, str, int, str]] = set()
    for record in records:
        block = int(record["block_number"])
        pool = str(record["address"]).lower()
        transaction_hash = str(record["transaction_hash"]).lower()
        log_index = int(record["log_index"])
        record_topics = [str(value).lower() for value in record.get("topics") or []]
        if not start_block <= block <= end_block:
            raise ValueError("Ethereum log lies outside its requested block range")
        if normalized_address is not None and pool != normalized_address:
            raise ValueError("Ethereum log lies outside its requested address filter")
        if not record_topics or record_topics[0] not in allowed_topics:
            raise ValueError("Ethereum log lies outside its requested topic filter")
        if not _exact_hex(pool, length=42) or not _exact_hex(record.get("block_hash"), length=66):
            raise ValueError("Ethereum log lacks exact address or block-hash identity")
        if not _exact_hex(transaction_hash, length=66) or int(record["transaction_index"]) < 0 or log_index < 0:
            raise ValueError("Ethereum log lacks exact transaction identity")
        if any(not _exact_hex(topic, length=66) for topic in record_topics) or not _exact_hex(record.get("data")):
            raise ValueError("Ethereum log contains malformed topics or data")
        if bool(record.get("removed")):
            raise ValueError("removed Ethereum log cannot enter an immutable exact chunk")
        key = (block, transaction_hash, log_index, pool)
        if key in keys:
            raise ValueError(f"duplicate exact Ethereum log in one chunk: {key}")
        keys.add(key)
    return records


def _exact_log_payload(
    *,
    start_block: int,
    end_block: int,
    topics: list[str],
    address: str | None,
) -> tuple[dict[str, object], list[str], str | None]:
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
    return (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getLogs",
            "params": [log_filter],
        },
        normalized_topics,
        normalized_address,
    )


def _validated_log_records(
    response: object,
    *,
    start_block: int,
    end_block: int,
    normalized_topics: list[str],
    normalized_address: str | None,
) -> list[dict[str, object]]:
    logs = response.get("result") if isinstance(response, dict) else None
    if not isinstance(logs, list):
        raise ExactLogRpcError(
            f"Ethereum log response lacks a result list for {start_block}:{end_block}"
        )
    records = [canonical_raw_log(log) for log in logs]
    return validate_canonical_log_records(
        records,
        start_block=start_block,
        end_block=end_block,
        topics=normalized_topics,
        address=normalized_address,
    )


def fetch_exact_logs(
    *,
    start_block: int,
    end_block: int,
    topics: list[str],
    address: str | None = None,
    rpc_request=rpc_post,
) -> list[dict[str, object]]:
    """Fetch and validate one exact inclusive Ethereum log perimeter."""

    payload, normalized_topics, normalized_address = _exact_log_payload(
        start_block=start_block,
        end_block=end_block,
        topics=topics,
        address=address,
    )
    response = rpc_request(
        payload,
        timeout=30,
        retries=1,
        retry_json_errors=True,
    )
    return _validated_log_records(
        response,
        start_block=start_block,
        end_block=end_block,
        normalized_topics=normalized_topics,
        normalized_address=normalized_address,
    )


def fetch_exact_logs_with_evidence(
    *,
    start_block: int,
    end_block: int,
    topics: list[str],
    address: str | None = None,
    frozen_upper: dict[str, object],
    rpc_request=None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Fetch exact logs and bind the successful endpoint to the frozen chain view."""

    log_payload, normalized_topics, normalized_address = _exact_log_payload(
        start_block=start_block,
        end_block=end_block,
        topics=topics,
        address=address,
    )
    upper_block = int(frozen_upper["block_number"])
    upper_hash = str(frozen_upper["block_hash"]).lower()
    header_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "eth_getBlockByNumber",
        "params": [hex(upper_block), False],
    }
    payload = [log_payload, header_payload]
    if rpc_request is None:
        envelope = rpc_post_with_evidence(payload)
    else:
        response = rpc_request(payload, timeout=30, retries=2)
        envelope = coerce_rpc_envelope(response)
    if not isinstance(envelope.response, list) or len(envelope.response) != 2:
        raise ExactLogRpcError("anchored Ethereum log response is not an exact two-item batch")
    by_id = {
        item.get("id"): item
        for item in envelope.response
        if isinstance(item, dict) and item.get("id") in {1, 2}
    }
    if set(by_id) != {1, 2}:
        raise ExactLogRpcError("anchored Ethereum log response lacks exact request identities")
    header = by_id[2].get("result")
    if not isinstance(header, dict):
        raise ExactLogRpcError("anchored Ethereum log response lacks the frozen upper header")
    observed_upper = rpc_integer(header.get("number"))
    observed_hash = str(header.get("hash") or "").lower()
    if observed_upper != upper_block or observed_hash != upper_hash:
        raise ExactLogRpcError("Ethereum log endpoint disagrees with the frozen upper block")
    records = _validated_log_records(
        by_id[1],
        start_block=start_block,
        end_block=end_block,
        normalized_topics=normalized_topics,
        normalized_address=normalized_address,
    )
    canonical_response_evidence = {
        "logs": records,
        "frozen_upper_response": by_id[2],
    }
    return records, {
        "request": payload,
        "endpoint": envelope.endpoint,
        "attempts": list(envelope.attempts),
        "response_sha256": hashlib.sha256(
            json.dumps(canonical_response_evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "frozen_upper_request": header_payload,
        "frozen_upper_response": by_id[2],
        "frozen_upper_response_sha256": hashlib.sha256(
            json.dumps(by_id[2], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


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
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
    }
    write_json(marker_path, payload)
    return payload

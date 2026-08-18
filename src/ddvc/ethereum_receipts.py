"""Canonical Ethereum receipt parsing, caching, and deterministic evidence snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from ddvc.fetch.raw import write_jsonl
from ddvc.paths import ETHEREUM_RPC_RAW_ROOT
from ddvc.quoter import (
    coerce_rpc_envelope,
    rpc_post,
    validate_rpc_attempts,
)
from ddvc.runtime import atomic_output


RECEIPT_CACHE = ETHEREUM_RPC_RAW_ROOT / "receipts"


def receipt_payload(tx_hash: str) -> dict[str, object]:
    """Canonical exact-receipt request for one transaction."""

    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getTransactionReceipt",
        "params": [tx_hash.lower()],
    }


def parse_receipt(
    tx_hash: str,
    response: object,
    *,
    expected_block: int | None = None,
    include_logs: bool = False,
) -> dict[str, object] | None:
    """Normalize one successful receipt and enforce supplied transaction identity."""

    if not isinstance(response, dict) or response.get("error"):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    try:
        gas_used = int(str(result["gasUsed"]), 16)
        status = int(str(result.get("status", "0x1")), 16)
        block_number = (
            int(str(result["blockNumber"]), 16)
            if result.get("blockNumber") is not None
            else None
        )
        block_hash = str(result.get("blockHash") or "").lower() or None
        effective_gas_price = (
            int(str(result["effectiveGasPrice"]), 16)
            if result.get("effectiveGasPrice") is not None
            else None
        )
        raw_blob_gas_used = result.get("blobGasUsed")
        raw_blob_gas_price = result.get("blobGasPrice")
        if (raw_blob_gas_used is None) != (raw_blob_gas_price is None):
            return None
        blob_gas_used = (
            int(str(raw_blob_gas_used), 16)
            if raw_blob_gas_used is not None
            else None
        )
        blob_gas_price = (
            int(str(raw_blob_gas_price), 16)
            if raw_blob_gas_price is not None
            else None
        )
    except (KeyError, TypeError, ValueError):
        return None
    normalized_hash = tx_hash.lower()
    returned_hash = str(result.get("transactionHash") or normalized_hash).lower()
    if returned_hash != normalized_hash:
        raise ValueError("Ethereum receipt transaction hash differs from the request")
    if expected_block is not None and block_number != int(expected_block):
        raise ValueError("Ethereum receipt block differs from the route identity")
    if (
        blob_gas_used is not None
        and (blob_gas_used < 0 or blob_gas_price is None or blob_gas_price < 0)
    ):
        return None
    row: dict[str, object] = {
        "tx_hash": normalized_hash,
        "block_number": block_number,
        "block_hash": block_hash,
        "gas_used": gas_used,
        "status": status,
        "tx_to": str(result.get("to") or "").lower() or None,
        "tx_from": str(result.get("from") or "").lower() or None,
        "effective_gas_price_wei": effective_gas_price,
        "blob_gas_used": blob_gas_used,
        "blob_gas_price_wei": blob_gas_price,
    }
    if include_logs:
        raw_logs = result.get("logs")
        if not isinstance(raw_logs, list):
            return None
        logs: list[dict[str, object]] = []
        for raw_log in raw_logs:
            if not isinstance(raw_log, dict):
                return None
            try:
                log_index = int(str(raw_log["logIndex"]), 16)
            except (KeyError, TypeError, ValueError):
                return None
            address = str(raw_log.get("address") or "").lower()
            topics = [str(topic).lower() for topic in raw_log.get("topics") or []]
            data = str(raw_log.get("data") or "").lower()
            if (
                len(address) != 42
                or not address.startswith("0x")
                or log_index < 0
                or not topics
                or any(len(topic) != 66 or not topic.startswith("0x") for topic in topics)
                or not data.startswith("0x")
            ):
                return None
            logs.append(
                {
                    "address": address,
                    "log_index": log_index,
                    "topics": topics,
                    "data": data,
                }
            )
        logs.sort(key=lambda log: int(log["log_index"]))
        if len({int(log["log_index"]) for log in logs}) != len(logs):
            return None
        row["logs"] = logs
    return row


def receipt_is_current(
    row: object,
    tx_hash: str,
    *,
    expected_block: int | None,
    require_block_hash: bool = False,
    require_logs: bool = False,
    require_evidence: bool = False,
) -> bool:
    if not isinstance(row, dict):
        return False
    fields_current = bool(
        row.get("tx_hash") == tx_hash.lower()
        and isinstance(row.get("gas_used"), int)
        and int(row["gas_used"]) > 0
        and row.get("status") in (0, 1)
        and "tx_to" in row
        and (
            (
                row.get("blob_gas_used") is None
                and row.get("blob_gas_price_wei") is None
            )
            or (
                isinstance(row.get("blob_gas_used"), int)
                and int(row["blob_gas_used"]) >= 0
                and isinstance(row.get("blob_gas_price_wei"), int)
                and int(row["blob_gas_price_wei"]) >= 0
            )
        )
        and (
            not require_block_hash
            or (
                isinstance(row.get("block_number"), int)
                and isinstance(row.get("block_hash"), str)
                and str(row["block_hash"]).startswith("0x")
                and len(str(row["block_hash"])) == 66
            )
        )
        and (
            not require_logs
            or receipt_logs_are_current(row.get("logs"))
        )
        and (
            expected_block is None
            or row.get("block_number") == int(expected_block)
        )
    )
    return fields_current and (
        not require_evidence
        or receipt_evidence_is_current(
            row,
            tx_hash,
            expected_block=expected_block,
        )
    )


def receipt_evidence_is_current(
    row: object,
    tx_hash: str,
    *,
    expected_block: int | None,
) -> bool:
    """Reopen one exact RPC response and match every copied receipt field."""

    if not isinstance(row, dict):
        return False
    try:
        endpoint = row.get("rpc_endpoint")
        validate_rpc_attempts(row.get("rpc_attempts"), endpoint)
        request = receipt_payload(tx_hash)
        if row.get("rpc_request") != request:
            return False
        response = row.get("rpc_response")
        if (
            not isinstance(response, dict)
            or response.get("id") != 1
        ):
            return False
        parsed = parse_receipt(
            tx_hash,
            response,
            expected_block=expected_block,
            include_logs="logs" in row,
        )
        if parsed is None:
            return False
    except (TypeError, ValueError):
        return False
    return all(row.get(key) == value for key, value in parsed.items())


def receipt_logs_are_current(logs: object) -> bool:
    """Validate one normalized complete receipt-log perimeter."""

    if not isinstance(logs, list):
        return False
    indices: list[int] = []
    for log in logs:
        if not isinstance(log, dict):
            return False
        try:
            log_index = int(log["log_index"])
        except (KeyError, TypeError, ValueError):
            return False
        address = str(log.get("address") or "")
        topics = log.get("topics")
        data = str(log.get("data") or "")
        if (
            log_index < 0
            or len(address) != 42
            or not address.startswith("0x")
            or not isinstance(topics, list)
            or not topics
            or any(len(str(topic)) != 66 or not str(topic).startswith("0x") for topic in topics)
            or not data.startswith("0x")
        ):
            return False
        indices.append(log_index)
    return len(indices) == len(set(indices))


def fetch_receipt(
    tx_hash: str,
    *,
    cache: Path,
    expected_block: int | None = None,
    require_block_hash: bool = False,
    include_logs: bool = False,
    require_evidence: bool = False,
    rpc_request=rpc_post,
) -> dict[str, object]:
    """Fetch one receipt into a transaction-keyed atomic cache."""

    normalized_hash = tx_hash.lower()
    cached = cache / f"{normalized_hash}.json"
    row = load_cached_receipt(cache, normalized_hash, expected_block=expected_block, require_block_hash=require_block_hash, require_logs=include_logs, require_evidence=require_evidence)
    if row is not None:
        return row
    request = receipt_payload(normalized_hash)
    request_kwargs = {
        "timeout": 20,
        "retries": 2,
        "sleep": 0.02,
        "retry_json_errors": True,
    }
    if rpc_request is rpc_post:
        def validate_response(candidate: object) -> None:
            parsed = parse_receipt(
                normalized_hash,
                candidate,
                expected_block=expected_block,
                include_logs=include_logs,
            )
            if parsed is None or not receipt_is_current(
                parsed,
                normalized_hash,
                expected_block=expected_block,
                require_block_hash=require_block_hash,
                require_logs=include_logs,
            ):
                raise ValueError("receipt response violates its requested identity")

        request_kwargs["response_validator"] = validate_response
        if require_evidence:
            request_kwargs["return_evidence"] = True
    response = rpc_request(request, **request_kwargs)
    envelope = coerce_rpc_envelope(response) if require_evidence else None
    raw_response = envelope.response if envelope is not None else response
    row = parse_receipt(
        normalized_hash,
        raw_response,
        expected_block=expected_block,
        include_logs=include_logs,
    )
    if row is not None and envelope is not None:
        row.update(
            {
                "rpc_request": request,
                "rpc_response": raw_response,
                "rpc_endpoint": envelope.endpoint,
                "rpc_attempts": list(envelope.attempts),
            }
        )
    if row is None or not receipt_is_current(
        row,
        normalized_hash,
        expected_block=expected_block,
        require_block_hash=require_block_hash,
        require_logs=include_logs,
        require_evidence=require_evidence,
    ):
        raise RuntimeError("receipt response is incomplete or violates its requested identity")
    cache.mkdir(parents=True, exist_ok=True)
    with atomic_output(cached) as temporary:
        temporary.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
    return row


def load_cached_receipt(cache: Path, tx_hash: str, *, expected_block: int | None, require_block_hash: bool = False, require_logs: bool = False, require_evidence: bool = False) -> dict[str, object] | None:
    """Reopen one transaction-keyed receipt cache entry without falling through to RPC."""

    normalized_hash = tx_hash.lower()
    cached = cache / f"{normalized_hash}.json"
    if not cached.is_file():
        return None
    try:
        row = json.loads(cached.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return row if receipt_is_current(row, normalized_hash, expected_block=expected_block, require_block_hash=require_block_hash, require_logs=require_logs, require_evidence=require_evidence) else None


def write_receipt_snapshot(
    receipts: Iterable[dict],
    path: Path,
    *,
    require_evidence: bool = False,
    presorted: bool = False,
    order_by_block: bool = False,
) -> Path:
    """Install deterministic receipt evidence, streaming a validated presorted iterable."""

    order_key = (lambda row: (int(row["block_number"]), str(row["tx_hash"]))) if order_by_block else (lambda row: str(row["tx_hash"]))
    ordered = receipts if presorted else sorted(receipts, key=order_key)

    def validated_rows():
        previous: object | None = None
        for row in ordered:
            tx_hash = str(row.get("tx_hash") or "")
            current = (int(row.get("block_number", -1)), tx_hash) if order_by_block else tx_hash
            if not tx_hash or (previous is not None and current <= previous):
                raise ValueError("selected receipt snapshot is duplicated or not strictly ordered")
            if require_evidence and not receipt_is_current(row, tx_hash, expected_block=row.get("block_number"), require_block_hash=True, require_evidence=True):
                raise ValueError("selected receipt snapshot contains unverifiable RPC evidence")
            previous = current
            yield row

    write_jsonl(path, validated_rows())
    return path


def iter_receipt_snapshot(path: Path, *, require_evidence: bool = False, order_by_block: bool = False) -> Iterator[dict]:
    """Stream a deterministic receipt snapshot and reject malformed, stale, or reordered rows."""

    previous: object | None = None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError("receipt snapshot contains malformed JSON") from error
            tx_hash = str(row.get("tx_hash") or "").lower()
            current = receipt_is_current(row, tx_hash, expected_block=row.get("block_number"), require_block_hash=True, require_evidence=require_evidence)
            order_key = (int(row.get("block_number", -1)), tx_hash) if order_by_block else tx_hash
            if not current or (previous is not None and order_key <= previous):
                raise ValueError("receipt snapshot is stale, duplicated, or not strictly ordered")
            previous = order_key
            yield row


def load_receipt_snapshot(
    path: Path,
    *,
    require_evidence: bool = False,
) -> dict[str, dict]:
    """Load valid positive-gas immutable receipts from one evidence snapshot."""

    if not path.exists():
        return {}
    rows: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            tx_hash = str(row.get("tx_hash") or "").lower()
            if (
                tx_hash
                and (
                    receipt_is_current(
                        row,
                        tx_hash,
                        expected_block=row.get("block_number"),
                        require_block_hash=True,
                        require_evidence=True,
                    )
                    if require_evidence
                    else isinstance(row.get("gas_used"), int) and row["gas_used"] > 0
                )
            ):
                rows[tx_hash] = row
    return rows

"""Canonical Ethereum block-header parsing, caching, and evidence snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from ddvc.paths import SHARED_RUNTIME_DIR
from ddvc.quoter import (
    canonical_json_sha256,
    coerce_rpc_envelope,
    rpc_post,
    validate_rpc_attempts,
)
from ddvc.runtime import atomic_output


BLOCK_HEADER_CACHE = SHARED_RUNTIME_DIR / "cache" / "ethereum_block_headers"


def block_header_payload(block_number: int) -> dict[str, object]:
    if int(block_number) < 0:
        raise ValueError("Ethereum block number must be nonnegative")
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": [hex(int(block_number)), False],
    }


def parse_block_header(block_number: int, response: object) -> dict[str, object]:
    """Normalize one exact header, preserving pre-EIP-1559 missing base fees."""

    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError(f"historical Ethereum block {block_number} lacks a header")
    try:
        returned_block = int(str(result["number"]), 16)
        timestamp = int(str(result["timestamp"]), 16)
        base_fee = (
            int(str(result["baseFeePerGas"]), 16)
            if result.get("baseFeePerGas") is not None
            else None
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Ethereum block header has malformed numeric fields") from error
    block_hash = str(result.get("hash") or "").lower()
    parent_hash = str(result.get("parentHash") or "").lower()
    if returned_block != int(block_number):
        raise ValueError(
            f"Ethereum RPC returned block {returned_block} for requested {block_number}"
        )
    if (
        len(block_hash) != 66
        or not block_hash.startswith("0x")
        or len(parent_hash) != 66
        or not parent_hash.startswith("0x")
        or timestamp < 1
        or (base_fee is not None and base_fee < 0)
    ):
        raise ValueError("Ethereum block header lacks a valid chain identity")
    return {
        "block_number": returned_block,
        "block_hash": block_hash,
        "parent_hash": parent_hash,
        "timestamp": timestamp,
        "base_fee_per_gas_wei": base_fee,
    }


def request_block_header(
    block_number: int,
    *,
    rpc_request=rpc_post,
    retries: int = 2,
) -> dict[str, object]:
    request_kwargs = {
        "timeout": 30,
        "retries": retries,
        "retry_json_errors": True,
    }
    if rpc_request is rpc_post:
        request_kwargs["response_validator"] = lambda response: parse_block_header(
            block_number, response
        )
    response = rpc_request(block_header_payload(block_number), **request_kwargs)
    return parse_block_header(block_number, response)


def block_header_is_current(
    row: object,
    block_number: int,
    *,
    require_evidence: bool = False,
) -> bool:
    if not isinstance(row, dict):
        return False
    fields_current = bool(
        row.get("block_number") == int(block_number)
        and isinstance(row.get("timestamp"), int)
        and int(row["timestamp"]) > 0
        and isinstance(row.get("block_hash"), str)
        and len(str(row["block_hash"])) == 66
        and isinstance(row.get("parent_hash"), str)
        and len(str(row["parent_hash"])) == 66
        and (
            row.get("base_fee_per_gas_wei") is None
            or (
                isinstance(row.get("base_fee_per_gas_wei"), int)
                and int(row["base_fee_per_gas_wei"]) >= 0
            )
        )
    )
    return fields_current and (
        not require_evidence
        or block_header_evidence_is_current(row, block_number)
    )


def block_header_evidence_is_current(row: object, block_number: int) -> bool:
    """Reopen one exact header response and match every copied field."""

    if not isinstance(row, dict):
        return False
    try:
        validate_rpc_attempts(row.get("rpc_attempts"), row.get("rpc_endpoint"))
        request = block_header_payload(block_number)
        if row.get("rpc_request") != request:
            return False
        response = row.get("rpc_response")
        if (
            not isinstance(response, dict)
            or response.get("id") != 1
            or row.get("response_sha256") != canonical_json_sha256(response)
        ):
            return False
        parsed = parse_block_header(block_number, response)
    except (RuntimeError, TypeError, ValueError):
        return False
    return all(row.get(key) == value for key, value in parsed.items())


def fetch_block_header(
    block_number: int,
    *,
    cache: Path = BLOCK_HEADER_CACHE,
    require_evidence: bool = False,
    rpc_request=rpc_post,
) -> dict[str, object]:
    """Fetch one block header into an exact-number atomic cache."""

    block = int(block_number)
    cached = cache / f"{block}.json"
    if cached.is_file():
        try:
            row = json.loads(cached.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            row = None
        if block_header_is_current(row, block, require_evidence=require_evidence):
            return row
    if require_evidence:
        request = block_header_payload(block)
        request_kwargs = {
            "timeout": 30,
            "retries": 2,
            "retry_json_errors": True,
        }
        if rpc_request is rpc_post:
            request_kwargs.update(
                {
                    "return_evidence": True,
                    "response_validator": lambda response: parse_block_header(
                        block, response
                    ),
                }
            )
        response = rpc_request(request, **request_kwargs)
        envelope = coerce_rpc_envelope(response)
        row = parse_block_header(block, envelope.response)
        row.update(
            {
                "rpc_request": request,
                "rpc_response": envelope.response,
                "rpc_endpoint": envelope.endpoint,
                "rpc_attempts": list(envelope.attempts),
                "response_sha256": canonical_json_sha256(envelope.response),
            }
        )
        if not block_header_is_current(row, block, require_evidence=True):
            raise RuntimeError("block-header response lacks verifiable RPC evidence")
    else:
        row = request_block_header(block, rpc_request=rpc_request)
    cache.mkdir(parents=True, exist_ok=True)
    with atomic_output(cached) as temporary:
        temporary.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
    return row


def write_block_header_snapshot(
    headers: list[dict],
    path: Path,
    *,
    require_evidence: bool = False,
) -> Path:
    """Install deterministic unique block-header evidence."""

    ordered = sorted(headers, key=lambda row: int(row["block_number"]))
    blocks = [int(row["block_number"]) for row in ordered]
    if len(blocks) != len(set(blocks)):
        raise ValueError("selected block-header snapshot contains duplicate blocks")
    if require_evidence and any(
        not block_header_is_current(
            row,
            int(row.get("block_number", -1)),
            require_evidence=True,
        )
        for row in ordered
    ):
        raise ValueError("selected block-header snapshot contains unverifiable RPC evidence")
    with atomic_output(path) as temporary:
        with temporary.open("w", encoding="utf-8") as handle:
            for row in ordered:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return path

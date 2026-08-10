"""Canonical Ethereum block-header parsing, caching, and evidence snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from ddvc.paths import SHARED_RUNTIME_DIR
from ddvc.quoter import rpc_post
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
) -> dict[str, object]:
    response = rpc_request(
        block_header_payload(block_number),
        timeout=30,
        retries=2,
        retry_json_errors=True,
    )
    return parse_block_header(block_number, response)


def block_header_is_current(row: object, block_number: int) -> bool:
    if not isinstance(row, dict):
        return False
    return bool(
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


def fetch_block_header(
    block_number: int,
    *,
    cache: Path = BLOCK_HEADER_CACHE,
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
        if block_header_is_current(row, block):
            return row
    row = request_block_header(block, rpc_request=rpc_request)
    cache.mkdir(parents=True, exist_ok=True)
    with atomic_output(cached) as temporary:
        temporary.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
    return row


def write_block_header_snapshot(headers: list[dict], path: Path) -> Path:
    """Install deterministic unique block-header evidence."""

    ordered = sorted(headers, key=lambda row: int(row["block_number"]))
    blocks = [int(row["block_number"]) for row in ordered]
    if len(blocks) != len(set(blocks)):
        raise ValueError("selected block-header snapshot contains duplicate blocks")
    with atomic_output(path) as temporary:
        with temporary.open("w", encoding="utf-8") as handle:
            for row in ordered:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return path

"""Canonical Ethereum receipt parsing, caching, and deterministic evidence snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from ddvc.paths import SHARED_RUNTIME_DIR
from ddvc.quoter import rpc_post
from ddvc.runtime import atomic_output


RECEIPT_CACHE = SHARED_RUNTIME_DIR / "cache" / "ethereum_receipts"


def parse_receipt(
    tx_hash: str,
    response: object,
    *,
    expected_block: int | None = None,
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
    except (KeyError, TypeError, ValueError):
        return None
    normalized_hash = tx_hash.lower()
    returned_hash = str(result.get("transactionHash") or normalized_hash).lower()
    if returned_hash != normalized_hash:
        raise ValueError("Ethereum receipt transaction hash differs from the request")
    if expected_block is not None and block_number != int(expected_block):
        raise ValueError("Ethereum receipt block differs from the route identity")
    return {
        "tx_hash": normalized_hash,
        "block_number": block_number,
        "block_hash": block_hash,
        "gas_used": gas_used,
        "status": status,
        "tx_to": str(result.get("to") or "").lower() or None,
        "tx_from": str(result.get("from") or "").lower() or None,
        "effective_gas_price_wei": effective_gas_price,
    }


def receipt_is_current(
    row: object,
    tx_hash: str,
    *,
    expected_block: int | None,
    require_block_hash: bool = False,
) -> bool:
    if not isinstance(row, dict):
        return False
    return bool(
        row.get("tx_hash") == tx_hash.lower()
        and isinstance(row.get("gas_used"), int)
        and int(row["gas_used"]) > 0
        and row.get("status") in (0, 1)
        and "tx_to" in row
        and (
            not require_block_hash
            or (
                isinstance(row.get("block_hash"), str)
                and str(row["block_hash"]).startswith("0x")
                and len(str(row["block_hash"])) == 66
            )
        )
        and (
            expected_block is None
            or row.get("block_number") == int(expected_block)
        )
    )


def fetch_receipt(
    tx_hash: str,
    *,
    cache: Path,
    expected_block: int | None = None,
    require_block_hash: bool = False,
    rpc_request=rpc_post,
) -> dict[str, object]:
    """Fetch one receipt into a transaction-keyed atomic cache."""

    normalized_hash = tx_hash.lower()
    cached = cache / f"{normalized_hash}.json"
    if cached.is_file():
        try:
            row = json.loads(cached.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            row = None
        if receipt_is_current(
            row,
            normalized_hash,
            expected_block=expected_block,
            require_block_hash=require_block_hash,
        ):
            return row
    response = rpc_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getTransactionReceipt",
            "params": [normalized_hash],
        },
        timeout=20,
        retries=2,
        sleep=0.02,
        retry_json_errors=True,
    )
    row = parse_receipt(normalized_hash, response, expected_block=expected_block)
    if row is None or not receipt_is_current(
        row,
        normalized_hash,
        expected_block=expected_block,
        require_block_hash=require_block_hash,
    ):
        raise RuntimeError("receipt response is incomplete or violates its requested identity")
    cache.mkdir(parents=True, exist_ok=True)
    with atomic_output(cached) as temporary:
        temporary.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
    return row


def write_receipt_snapshot(receipts: list[dict], path: Path) -> Path:
    """Install receipt evidence in deterministic transaction order."""

    ordered = sorted(receipts, key=lambda row: str(row["tx_hash"]))
    hashes = [str(row["tx_hash"]) for row in ordered]
    if len(hashes) != len(set(hashes)):
        raise ValueError("selected receipt snapshot contains duplicate transactions")
    with atomic_output(path) as temporary:
        with temporary.open("w", encoding="utf-8") as handle:
            for row in ordered:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def load_receipt_snapshot(path: Path) -> dict[str, dict]:
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
            if tx_hash and isinstance(row.get("gas_used"), int) and row["gas_used"] > 0:
                rows[tx_hash] = row
    return rows

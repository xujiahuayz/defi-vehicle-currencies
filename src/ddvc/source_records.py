"""Stable provider-record semantics shared by ingestion and canonical materialisation.

This module owns source-schema accessors and immutable V4 pool-static rules. It
contains no transport, filesystem, or orchestration code, so changes to fetch
cadence, retries, metadata, or documentation do not invalidate materialised
market-state engines.
"""

from __future__ import annotations

from typing import Any


def transaction_value(row: dict[str, Any], field: str) -> Any:
    """Read transaction data from either nested or scalar Graph schemas."""
    transaction = row.get("transaction")
    if isinstance(transaction, dict):
        return transaction.get(field)
    if field == "id" and isinstance(transaction, str):
        return transaction
    return None


def block_values(rows: list[dict[str, Any]]) -> list[int]:
    """Extract the first valid block number exposed by each provider row."""
    values: list[int] = []
    for row in rows:
        candidates = [
            row.get("block"),
            row.get("blockNumber"),
            transaction_value(row, "blockNumber"),
        ]
        for value in candidates:
            if value is None:
                continue
            try:
                values.append(int(value))
                break
            except (TypeError, ValueError):
                continue
    return values


def block_value(row: dict[str, Any] | None) -> int | None:
    if row is None:
        return None
    values = block_values([row])
    return values[0] if values else None


def timestamp_value(row: dict[str, Any] | None) -> int | None:
    if row is None:
        return None
    candidates = [
        row.get("timestamp"),
        transaction_value(row, "timestamp"),
        row.get("hourStartUnix"),
        row.get("date"),
    ]
    for value in candidates:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def transaction_id(row: dict[str, Any]) -> str | None:
    value = transaction_value(row, "id")
    return str(value) if value else None


def source_event_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Return chain-event content without the provider's mutable entity ID."""
    return {key: value for key, value in row.items() if key != "id"}


def v4_statics_complete(row: dict[str, Any]) -> bool:
    pool = row.get("pool") or {}
    return (
        pool.get("feeTier") is not None
        and pool.get("tickSpacing") is not None
        and pool.get("hooks") is not None
        and (pool.get("token0") or {}).get("decimals") is not None
        and (pool.get("token1") or {}).get("decimals") is not None
    )


V4_DYNAMIC_FEE_FLAG = 1 << 23
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def v4_quote_status(row: dict[str, Any]) -> str:
    """Why a V4 pool is or is not supported by concentrated-liquidity math."""
    if not v4_statics_complete(row):
        return "incomplete_statics"
    pool = row.get("pool") or {}
    try:
        fee = int(pool["feeTier"])
        tick_spacing = int(pool["tickSpacing"])
    except (KeyError, TypeError, ValueError):
        return "invalid_statics"
    hooks = str(pool.get("hooks") or "").lower()
    dynamic = bool(fee & V4_DYNAMIC_FEE_FLAG)
    hooked = hooks != ZERO_ADDRESS
    if dynamic and hooked:
        return "dynamic_fee_and_hooks"
    if dynamic:
        return "dynamic_fee"
    if hooked:
        return "hooks"
    if fee < 0 or fee >= 1_000_000 or tick_spacing <= 0:
        return "invalid_statics"
    return "vanilla_static_fee"


def v4_pool_quote_supported(row: dict[str, Any]) -> bool:
    return v4_quote_status(row) == "vanilla_static_fee"


def merge_v4_statics(row: dict[str, Any], auxiliary: dict[str, Any]) -> None:
    """Merge only immutable V4 pool statics, refusing any identity mismatch."""
    primary_pool = row.get("pool") or {}
    auxiliary_pool = auxiliary.get("pool") or {}
    identities = (
        (row.get("id"), auxiliary.get("id")),
        (primary_pool.get("id"), auxiliary_pool.get("id")),
        ((primary_pool.get("token0") or {}).get("id"), (auxiliary_pool.get("token0") or {}).get("id")),
        ((primary_pool.get("token1") or {}).get("id"), (auxiliary_pool.get("token1") or {}).get("id")),
    )
    if any(
        left is None or right is None or str(left).lower() != str(right).lower()
        for left, right in identities
    ):
        raise RuntimeError(f"v4 static identity mismatch for swap {row.get('id')}")
    primary_pool["feeTier"] = auxiliary_pool.get("feeTier")
    primary_pool["tickSpacing"] = auxiliary_pool.get("tickSpacing")
    primary_pool["hooks"] = auxiliary_pool.get("hooks")
    for token in ("token0", "token1"):
        primary_pool[token]["decimals"] = auxiliary_pool[token].get("decimals")
    if not v4_statics_complete(row):
        raise RuntimeError(f"v4 auxiliary statics incomplete for swap {row.get('id')}")

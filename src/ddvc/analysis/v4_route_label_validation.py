"""Independent Uniswap v4 swap and route-label validation.

PoolManager ``Initialize`` logs own the pool-to-currency mapping and exact
``Swap`` logs own direction, integer amounts, and EVM order.  Provider Swap
rows are the event-level object being tested; the published unified rows are
the route-label object being tested and supply optional display metadata.
Full route-label metrics are deliberately restricted to transactions whose
observed route legs are all Uniswap v4; a v4 event does not certify an
unaudited leg from another venue.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Sequence

import pandas as pd
from eth_abi import decode as abi_decode

from ddvc.analysis.route_reconstruction_validation import transaction_signatures
from ddvc.reconstruct import UNIFIED_COLUMNS
from ddvc.source_records import (
    V4_NATIVE_CURRENCY_DECIMALS,
    ZERO_ADDRESS,
    block_value,
    timestamp_value,
    transaction_id,
)
from ddvc.v4_contract import decode_v4_state_event_identity


def decimal_to_raw(value: object, decimals: object) -> int:
    """Convert a provider decimal amount to its exact signed integer amount."""

    try:
        scale = int(decimals)
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("V4 provider amount or decimals is invalid") from error
    if scale < 0 or scale > 255 or not amount.is_finite():
        raise ValueError("V4 provider amount or decimals is invalid")
    raw = amount.scaleb(scale)
    integral = raw.to_integral_value()
    if raw != integral:
        raise ValueError("V4 provider amount is not an exact raw-token integer")
    return int(integral)


def provider_swap_is_directional(record: Mapping[str, object]) -> bool:
    """Whether a provider Swap carries an economic token direction."""

    try:
        amount0 = Decimal(str(record.get("amount0")))
        amount1 = Decimal(str(record.get("amount1")))
    except InvalidOperation as error:
        raise ValueError("V4 provider swap amount is invalid") from error
    if amount0 * amount1 > 0:
        raise ValueError("V4 provider Swap has same-signed token amounts")
    return amount0 * amount1 < 0


def exact_swap_is_directional(record: Mapping[str, object]) -> bool:
    """Whether an exact Swap carries an economic token direction."""

    data = bytes.fromhex(str(record.get("data") or "0x").removeprefix("0x"))
    if len(data) != 32 * 6:
        raise ValueError("canonical V4 swap event has the wrong ABI data length")
    amount0, amount1, *_ = abi_decode(
        ["int128", "int128", "uint160", "uint128", "int24", "uint24"], data
    )
    if int(amount0) * int(amount1) > 0:
        raise ValueError("canonical V4 Swap has same-signed token amounts")
    return int(amount0) * int(amount1) < 0


def _address(value: object, *, label: str) -> str:
    address = str(value or "").lower()
    if (
        len(address) != 42
        or not address.startswith("0x")
        or any(character not in "0123456789abcdef" for character in address[2:])
    ):
        raise ValueError(f"V4 {label} is not a canonical address")
    return address


def _pool_id(value: object) -> str:
    pool = str(value or "").lower()
    if (
        len(pool) != 66
        or not pool.startswith("0x")
        or any(character not in "0123456789abcdef" for character in pool[2:])
    ):
        raise ValueError("V4 provider pool is not a canonical PoolId")
    return pool


def provider_swap(
    record: Mapping[str, object],
    *,
    token_decimals: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """Normalize one provider row without passing through binary floats."""

    pool = record.get("pool")
    if not isinstance(pool, Mapping):
        raise ValueError("V4 provider swap lacks a pool mapping")
    token0 = pool.get("token0")
    token1 = pool.get("token1")
    if not isinstance(token0, Mapping) or not isinstance(token1, Mapping):
        raise ValueError("V4 provider swap lacks token mappings")
    tx = str(transaction_id(dict(record)) or "").lower()
    if len(tx) != 66 or not tx.startswith("0x"):
        raise ValueError("V4 provider swap lacks a transaction hash")
    try:
        log_index = int(record["logIndex"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("V4 provider swap lacks an exact log index") from error
    token0_address = _address(token0.get("id"), label="token0")
    token1_address = _address(token1.get("id"), label="token1")
    if token0_address >= token1_address:
        raise ValueError("V4 provider pool currencies are not canonically ordered")
    decimals0 = token0.get("decimals")
    decimals1 = token1.get("decimals")
    if decimals0 is None:
        decimals0 = (
            V4_NATIVE_CURRENCY_DECIMALS
            if token0_address == ZERO_ADDRESS
            else (token_decimals or {}).get(token0_address)
        )
    if decimals1 is None:
        decimals1 = (
            V4_NATIVE_CURRENCY_DECIMALS
            if token1_address == ZERO_ADDRESS
            else (token_decimals or {}).get(token1_address)
        )
    amount0_decimal = Decimal(str(record.get("amount0")))
    amount1_decimal = Decimal(str(record.get("amount1")))
    if amount0_decimal * amount1_decimal >= 0:
        raise ValueError("V4 provider swap lacks opposite signed token amounts")
    raw_amount_comparable = decimals0 is not None and decimals1 is not None
    amount0_raw = (
        decimal_to_raw(record.get("amount0"), decimals0)
        if raw_amount_comparable
        else None
    )
    amount1_raw = (
        decimal_to_raw(record.get("amount1"), decimals1)
        if raw_amount_comparable
        else None
    )
    if amount0_decimal > 0:
        token_in, token_out = token0_address, token1_address
        amount_in, amount_out = abs(Decimal(str(record["amount0"]))), abs(
            Decimal(str(record["amount1"]))
        )
    else:
        token_in, token_out = token1_address, token0_address
        amount_in, amount_out = abs(Decimal(str(record["amount1"]))), abs(
            Decimal(str(record["amount0"]))
        )
    return {
        "transaction_hash": tx,
        "block_number": int(block_value(dict(record)) or -1),
        "log_index": log_index,
        "pool": _pool_id(pool.get("id")),
        "token0": token0_address,
        "token1": token1_address,
        "token0_symbol": str(token0.get("symbol") or token0_address[:10]),
        "token1_symbol": str(token1.get("symbol") or token1_address[:10]),
        "token0_decimals": int(decimals0) if decimals0 is not None else None,
        "token1_decimals": int(decimals1) if decimals1 is not None else None,
        "amount0": amount0_raw,
        "amount1": amount1_raw,
        "raw_amount_comparable": raw_amount_comparable,
        "amount_in": amount_in,
        "amount_out": amount_out,
        "token_in": token_in,
        "token_out": token_out,
        "timestamp": int(timestamp_value(dict(record)) or 0),
        "amount_usd": float(record.get("amountUSD") or 0.0),
    }


def initialize_registry(records: Iterable[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    """Decode an exact PoolManager initialization census into PoolKeys."""

    registry: dict[str, dict[str, object]] = {}
    for record in records:
        decoded = decode_v4_state_event_identity(dict(record), "initialize")
        pool = str(decoded["pool"])
        prior = registry.get(pool)
        if prior is not None and prior != decoded:
            raise ValueError(f"V4 PoolId has conflicting Initialize logs: {pool}")
        registry[pool] = decoded
    return registry


def exact_swap(record: Mapping[str, object], pools: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    """Decode one exact Swap and attach currencies from its exact Initialize."""

    decoded = decode_v4_state_event_identity(dict(record), "swap")
    pool = str(decoded["pool"])
    initialized = pools.get(pool)
    if initialized is None:
        raise ValueError(f"V4 Swap lacks an earlier exact Initialize: {pool}")
    if (
        int(initialized["block_number"]),
        int(initialized["transaction_index"]),
        int(initialized["log_index"]),
    ) >= (
        int(decoded["block_number"]),
        int(decoded["transaction_index"]),
        int(decoded["log_index"]),
    ):
        raise ValueError(f"V4 Swap does not follow its exact Initialize: {pool}")
    token0 = str(initialized["currency0"])
    token1 = str(initialized["currency1"])
    # PoolManager BalanceDelta is from the caller's perspective: a negative
    # amount is owed to the pool (input) and a positive amount is owed to the
    # caller (output).  The canonical provider exposes the opposite signs.
    if int(decoded["amount0"]) < 0:
        token_in, token_out = token0, token1
    else:
        token_in, token_out = token1, token0
    return {
        **decoded,
        "token0": token0,
        "token1": token1,
        "token_in": token_in,
        "token_out": token_out,
    }


def _event_key(record: Mapping[str, object]) -> tuple[str, int]:
    return str(record["transaction_hash"]), int(record["log_index"])


def _unique_index(
    records: Sequence[Mapping[str, object]],
) -> dict[tuple[str, int], Mapping[str, object]]:
    index: dict[tuple[str, int], Mapping[str, object]] = {}
    for record in records:
        key = _event_key(record)
        if key in index:
            raise ValueError(f"duplicate V4 transaction/log identity: {key}")
        index[key] = record
    return index


def event_validation_counts(
    provider: Sequence[Mapping[str, object]],
    exact: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Count event, pool, amount, direction, and order agreement."""

    provider_index = _unique_index(provider)
    exact_index = _unique_index(exact)
    criteria = (
        "event_identity",
        "pool_identity",
        "pool_currency_identity",
        "raw_amount_identity",
        "direction_identity",
        "block_identity",
    )
    true = Counter({criterion: 0 for criterion in criteria})
    provider_denominator = Counter({criterion: len(provider) for criterion in criteria})
    provider_denominator["raw_amount_identity"] = sum(
        bool(row.get("raw_amount_comparable")) for row in provider
    )
    mismatch: list[dict[str, object]] = []
    for key in sorted(set(provider_index) | set(exact_index)):
        left = provider_index.get(key)
        right = exact_index.get(key)
        if left is None or right is None:
            details: dict[str, object] = {}
            if left is not None:
                details = {
                    "provider_pool": left["pool"],
                    "provider_direction": f"{left['token_in']}->{left['token_out']}",
                    "provider_block": int(left["block_number"]),
                    "provider_amount0_raw": str(left["amount0"]),
                    "provider_amount1_raw": str(left["amount1"]),
                }
            if right is not None:
                details = {
                    "exact_pool": right["pool"],
                    "exact_direction": f"{right['token_in']}->{right['token_out']}",
                    "exact_block": int(right["block_number"]),
                    "exact_provider_sign_amount0_raw": str(-int(right["amount0"])),
                    "exact_provider_sign_amount1_raw": str(-int(right["amount1"])),
                }
            mismatch.append(
                {
                    "scope": "swap_event",
                    "transaction_hash": key[0],
                    "log_index": key[1],
                    "reason": "chain_only" if left is None else "provider_only",
                    **details,
                }
            )
            continue
        true["event_identity"] += 1
        checks = {
            "pool_identity": left["pool"] == right["pool"],
            "pool_currency_identity": (
                left["token0"], left["token1"]
            ) == (right["token0"], right["token1"]),
            "raw_amount_identity": (
                bool(left.get("raw_amount_comparable"))
                and (int(left["amount0"]), int(left["amount1"]))
                == (-int(right["amount0"]), -int(right["amount1"]))
            ),
            "direction_identity": (
                left["token_in"], left["token_out"]
            ) == (right["token_in"], right["token_out"]),
            "block_identity": int(left["block_number"]) == int(right["block_number"]),
        }
        for criterion, passed in checks.items():
            true[criterion] += int(passed)
        failed = [criterion for criterion, passed in checks.items() if not passed]
        if (
            "raw_amount_identity" in failed
            and not left.get("raw_amount_comparable")
        ):
            failed[failed.index("raw_amount_identity")] = "raw_amount_unavailable"
        if failed:
            raw_details = {}
            if left.get("raw_amount_comparable"):
                provider0, provider1 = int(left["amount0"]), int(left["amount1"])
                exact0, exact1 = -int(right["amount0"]), -int(right["amount1"])
                raw_details = {
                    "provider_amount0_raw": str(provider0),
                    "provider_amount1_raw": str(provider1),
                    "exact_provider_sign_amount0_raw": str(exact0),
                    "exact_provider_sign_amount1_raw": str(exact1),
                    "amount0_raw_difference": str(provider0 - exact0),
                    "amount1_raw_difference": str(provider1 - exact1),
                }
            mismatch.append(
                {
                    "scope": "swap_event",
                    "transaction_hash": key[0],
                    "log_index": key[1],
                    "reason": "|".join(failed),
                    "provider_pool": left["pool"],
                    "exact_pool": right["pool"],
                    "provider_direction": f"{left['token_in']}->{left['token_out']}",
                    "exact_direction": f"{right['token_in']}->{right['token_out']}",
                    **raw_details,
                }
            )
    rows = []
    for criterion in criteria:
        tp = int(true[criterion])
        provider_total = int(provider_denominator[criterion])
        rows.append(
            {
                "dimension": criterion,
                "true_positive": tp,
                "provider_assignments": provider_total,
                "exact_assignments": len(exact),
                "precision": tp / provider_total if provider_total else None,
                "recall": tp / len(exact) if exact else None,
            }
        )
    return rows, mismatch


def _components(legs: Sequence[Mapping[str, object]]) -> list[list[Mapping[str, object]]]:
    parent: dict[str, str] = {}

    def root(token: str) -> str:
        parent.setdefault(token, token)
        while parent[token] != token:
            parent[token] = parent[parent[token]]
            token = parent[token]
        return token

    def union(left: str, right: str) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parent[left_root] = right_root

    for leg in legs:
        union(str(leg["token_in"]), str(leg["token_out"]))
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for leg in legs:
        grouped[root(str(leg["token_in"]))].append(leg)
    return sorted(
        (sorted(group, key=lambda row: int(row["log_index"])) for group in grouped.values()),
        key=lambda group: (int(group[0]["log_index"]), str(group[0]["token_in"])),
    )


def label_frame(
    swaps: Sequence[Mapping[str, object]],
    *,
    metadata: Mapping[tuple[str, int], Mapping[str, object]] | None = None,
) -> pd.DataFrame:
    """Build the minimal canonical frame needed by route-label signatures."""

    by_transaction: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for swap in swaps:
        by_transaction[str(swap["transaction_hash"])].append(swap)
    rows: list[dict[str, object]] = []
    for tx, transaction_swaps in by_transaction.items():
        components = _components(transaction_swaps)
        route_class = (
            "single"
            if len(transaction_swaps) == 1
            else "coherent"
            if len(components) == 1
            else "tricky_independent"
        )
        for component_id, component in enumerate(components):
            for swap in component:
                key = _event_key(swap)
                display = (metadata or {}).get(key, {})
                token_in = str(swap["token_in"])
                token_out = str(swap["token_out"])
                amount_in = (
                    display["amount_in"]
                    if display.get("amount_in") is not None
                    else abs(int(swap.get("amount0") or 1))
                )
                amount_out = (
                    display["amount_out"]
                    if display.get("amount_out") is not None
                    else abs(int(swap.get("amount1") or 1))
                )
                amount_usd = float(display.get("amount_usd") or 1.0)
                rows.append(
                    {
                        "tx_hash": tx,
                        "log_index": int(swap["log_index"]),
                        "source": "uniswap_v4",
                        "token_in": token_in,
                        "token_out": token_out,
                        "token_in_sym": str(display.get("token_in_symbol") or token_in[:10]),
                        "token_out_sym": str(display.get("token_out_symbol") or token_out[:10]),
                        "amount_in": float(amount_in),
                        "amount_out": float(amount_out),
                        "amount_usd": amount_usd,
                        "component_id": component_id,
                        "n_components": len(components),
                        "route_class": route_class,
                        "ambiguous": len(components) > 1,
                        "tin_role": "",
                        "tout_role": "",
                        "timestamp_utc": int(display.get("timestamp") or 1),
                    }
                )
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS)


def _leg_order_signatures(frame: pd.DataFrame) -> dict[str, tuple[tuple, ...]]:
    if frame.empty:
        return {}
    signatures: dict[str, list[tuple]] = defaultdict(list)
    keys = ["tx_hash", "component_id"]
    for (tx, _component), group in frame.groupby(keys, sort=False):
        ordered = group.sort_values("log_index")
        signatures[str(tx)].append(
            tuple(
                zip(
                    ordered["token_in"].astype(str),
                    ordered["token_out"].astype(str),
                    strict=True,
                )
            )
        )
    return {tx: tuple(sorted(values)) for tx, values in signatures.items()}


def route_assignment_signatures(frame: pd.DataFrame, day: str) -> dict[str, dict[str, tuple]]:
    """Reuse canonical route signatures and add exact ordered leg sequences."""

    prepared = frame.copy()
    if not prepared.empty:
        prepared["timestamp_utc"] = int(pd.Timestamp(day, tz="UTC").timestamp()) + 1
    signatures = transaction_signatures(prepared, day)
    leg_order = _leg_order_signatures(prepared)
    for tx in set(signatures) | set(leg_order):
        signatures.setdefault(tx, {})["leg_order"] = leg_order.get(tx, ())
    return signatures


def route_validation_counts(
    provider_frame: pd.DataFrame,
    exact_frame: pd.DataFrame,
    *,
    day: str,
    transactions: set[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Measure assignment precision/recall in observed v4-only transactions."""

    left = route_assignment_signatures(
        provider_frame[provider_frame["tx_hash"].isin(transactions)], day
    )
    right = route_assignment_signatures(
        exact_frame[exact_frame["tx_hash"].isin(transactions)], day
    )
    rows: list[dict[str, object]] = []
    examples: list[dict[str, object]] = []
    for dimension in ("endpoint_pair", "intermediary_identity", "leg_order"):
        provider_labels = Counter(
            (tx, label)
            for tx in transactions
            for label in left.get(tx, {}).get(dimension, ())
        )
        exact_labels = Counter(
            (tx, label)
            for tx in transactions
            for label in right.get(tx, {}).get(dimension, ())
        )
        true_positive = sum((provider_labels & exact_labels).values())
        provider_total = sum(provider_labels.values())
        exact_total = sum(exact_labels.values())
        labeled_transactions = {
            tx
            for tx in transactions
            if left.get(tx, {}).get(dimension, ())
            or right.get(tx, {}).get(dimension, ())
        }
        exact_transactions = sum(
            left.get(tx, {}).get(dimension, ())
            == right.get(tx, {}).get(dimension, ())
            for tx in labeled_transactions
        )
        rows.append(
            {
                "dimension": dimension,
                "true_positive": true_positive,
                "provider_assignments": provider_total,
                "exact_assignments": exact_total,
                "precision": true_positive / provider_total if provider_total else None,
                "recall": true_positive / exact_total if exact_total else None,
                "transactions": len(labeled_transactions),
                "exact_match_transactions": exact_transactions,
                "exact_match_share": (
                    exact_transactions / len(labeled_transactions)
                    if labeled_transactions
                    else None
                ),
            }
        )
        for tx in sorted(transactions):
            provider_value = left.get(tx, {}).get(dimension, ())
            exact_value = right.get(tx, {}).get(dimension, ())
            if provider_value != exact_value:
                examples.append(
                    {
                        "scope": "v4_only_route",
                        "dimension": dimension,
                        "transaction_hash": tx,
                        "provider_label": repr(provider_value),
                        "exact_label": repr(exact_value),
                    }
                )
    return rows, examples


def pooled_metric_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Pool count rows into precision/recall without averaging daily rates."""

    totals: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in rows:
        key = str(row["record_type"]), str(row["dimension"])
        for column in (
            "true_positive",
            "provider_assignments",
            "exact_assignments",
            "transactions",
            "exact_match_transactions",
        ):
            if row.get(column) is not None:
                totals[key][column] += int(row[column])
    result = []
    for (record_type, dimension), count in sorted(totals.items()):
        provider_total = count["provider_assignments"]
        exact_total = count["exact_assignments"]
        transactions = count["transactions"]
        result.append(
            {
                "record_type": f"pooled_{record_type}",
                "dimension": dimension,
                **dict(count),
                "precision": count["true_positive"] / provider_total if provider_total else None,
                "recall": count["true_positive"] / exact_total if exact_total else None,
                "exact_match_share": count["exact_match_transactions"] / transactions if transactions else None,
            }
        )
    return result

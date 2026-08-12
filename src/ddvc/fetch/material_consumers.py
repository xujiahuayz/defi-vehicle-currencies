"""Closed material-consumer contracts for any incremental Graph acquisition."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping


StreamIdentity = tuple[str, str]


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ExistingStreamRequirement:
    """One existing raw stream and the fields a named consumer actually reads."""

    source: str
    stream: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class GraphMaterialConsumerIntent:
    """A closed consumer perimeter; network acquisition requires a code review."""

    reason: str
    existing_streams: tuple[ExistingStreamRequirement, ...]
    allowed_new_streams: frozenset[StreamIdentity]
    max_selected_streams: int
    unresolved_prerequisites: tuple[str, ...] = ()


V2_SWAP_FIELDS = (
    "id",
    "transaction.id",
    "transaction.blockNumber",
    "transaction.timestamp",
    "timestamp",
    "pair.id",
    "pair.token0.id",
    "pair.token1.id",
    "amount0In",
    "amount0Out",
    "amount1In",
    "amount1Out",
    "logIndex",
)
V2_IDENTITY_FIELDS = (
    "id",
    "pair.id",
    "pair.token0.id",
    "pair.token1.id",
)
V3_LIQUIDITY_FIELDS = (
    "id",
    "transaction.id",
    "transaction.blockNumber",
    "transaction.timestamp",
    "timestamp",
    "pool.id",
    "amount",
    "amount0",
    "amount1",
    "tickLower",
    "tickUpper",
    "logIndex",
)
V3_SWAP_FIELDS = (
    "id",
    "transaction.id",
    "transaction.blockNumber",
    "transaction.timestamp",
    "timestamp",
    "pool.id",
    "pool.token0.id",
    "pool.token1.id",
    "amount0",
    "amount1",
    "sqrtPriceX96",
    "tick",
    "logIndex",
)
V4_TARGET_SWAP_FIELDS = tuple(
    field for field in V3_SWAP_FIELDS if field not in {"sqrtPriceX96", "tick"}
)


def _v2_capital_requirements() -> tuple[ExistingStreamRequirement, ...]:
    daily_fields = (
        "id",
        "date",
        "pairAddress",
        "reserveUSD",
        "dailyVolumeUSD",
    )
    return (
        ExistingStreamRequirement(
            "sushiswap_v2",
            "daily",
            (*daily_fields, "token0.id", "token1.id"),
        ),
        ExistingStreamRequirement("uniswap_v2", "daily", daily_fields),
        ExistingStreamRequirement("uniswap_v2", "mints", V2_IDENTITY_FIELDS),
    )


GRAPH_MATERIAL_CONSUMER_INTENTS: Mapping[str, GraphMaterialConsumerIntent] = {
    "v2_end_of_day_deposited_capital": GraphMaterialConsumerIntent(
        reason="materialize V2 end-of-day deposited capital from already installed raw streams",
        existing_streams=_v2_capital_requirements(),
        allowed_new_streams=frozenset(),
        max_selected_streams=0,
        unresolved_prerequisites=(
            "certify the current constant-product state partitions before capital publication",
        ),
    ),
    "exact_transaction_target_and_quote_state_replay": GraphMaterialConsumerIntent(
        reason="certify exact transaction targets and strictly prior quote state from installed Graph streams plus independent chain logs",
        existing_streams=(
            ExistingStreamRequirement("uniswap_v2", "swaps", V2_SWAP_FIELDS),
            ExistingStreamRequirement("sushiswap_v2", "swaps", V2_SWAP_FIELDS),
            ExistingStreamRequirement("uniswap_v3", "swaps", V3_SWAP_FIELDS),
            ExistingStreamRequirement("uniswap_v4", "swaps", V4_TARGET_SWAP_FIELDS),
        ),
        allowed_new_streams=frozenset(),
        max_selected_streams=0,
        unresolved_prerequisites=(
            "bind the exact V2 and V3 event-source release markers on the authoritative data host",
            "bind the exact transaction-target audit and daily release markers after publication",
        ),
    ),
    "v3_pool_inventory_and_liquidity_supply": GraphMaterialConsumerIntent(
        reason="certify V3 pool inventory and liquidity supply from existing event streams and independent chain logs",
        existing_streams=(
            ExistingStreamRequirement("uniswap_v3", "swaps", V3_SWAP_FIELDS),
            ExistingStreamRequirement("uniswap_v3", "mints", V3_LIQUIDITY_FIELDS),
            ExistingStreamRequirement("uniswap_v3", "burns", V3_LIQUIDITY_FIELDS),
        ),
        allowed_new_streams=frozenset(),
        max_selected_streams=0,
        unresolved_prerequisites=(
            "bind the exact V3 event-source and inventory release markers on the authoritative data host",
        ),
    ),
}


UNSUPPORTED_OWNERSHIP_STREAMS = frozenset(
    {
        ("sushiswap_v3", "positionSnapshots"),
        ("sushiswap_v3", "positions"),
        ("uniswap_v3", "positionSnapshots"),
        ("uniswap_v3", "positions"),
    }
)


def validate_material_consumer_registry(
    registry: Mapping[str, GraphMaterialConsumerIntent] | None = None,
) -> None:
    registry = GRAPH_MATERIAL_CONSUMER_INTENTS if registry is None else registry
    for name, intent in registry.items():
        if not name or not intent.reason.strip():
            raise ValueError("Graph material-consumer registry has an unnamed intent")
        if intent.max_selected_streams < 0 or intent.max_selected_streams > len(intent.allowed_new_streams):
            raise ValueError(f"Graph material-consumer scope is inconsistent: {name}")
        forbidden = intent.allowed_new_streams.intersection(UNSUPPORTED_OWNERSHIP_STREAMS)
        if forbidden:
            raise ValueError(f"Graph material-consumer intent admits unsupported ownership: {name}/{sorted(forbidden)}")
        identities = [(item.source, item.stream) for item in intent.existing_streams]
        if len(identities) != len(set(identities)):
            raise ValueError(f"Graph material-consumer intent repeats an existing stream: {name}")
        if any(not item.fields or len(item.fields) != len(set(item.fields)) for item in intent.existing_streams):
            raise ValueError(f"Graph material-consumer intent has an empty or duplicate field perimeter: {name}")
        if len(intent.unresolved_prerequisites) != len(set(intent.unresolved_prerequisites)) or any(
            not prerequisite.strip() for prerequisite in intent.unresolved_prerequisites
        ):
            raise ValueError(f"Graph material-consumer intent has an invalid prerequisite: {name}")


def validate_material_consumer_selection(
    consumer: str,
    selected: set[StreamIdentity],
    *,
    registry: Mapping[str, GraphMaterialConsumerIntent] | None = None,
) -> GraphMaterialConsumerIntent:
    registry = GRAPH_MATERIAL_CONSUMER_INTENTS if registry is None else registry
    validate_material_consumer_registry(registry)
    intent = registry.get(consumer)
    if intent is None:
        raise ValueError(f"unknown Graph material consumer: {consumer}")
    if not selected:
        raise ValueError("Graph acquisition requires at least one selected stream")
    forbidden = selected.intersection(UNSUPPORTED_OWNERSHIP_STREAMS)
    if forbidden:
        raise ValueError(f"Graph acquisition cannot authorize unsupported ownership streams: {sorted(forbidden)}")
    outside = selected.difference(intent.allowed_new_streams)
    if outside:
        raise ValueError(f"Graph acquisition exceeds the named consumer allowlist: {sorted(outside)}")
    if len(selected) > intent.max_selected_streams:
        raise ValueError(f"Graph acquisition exceeds the named consumer maximum scope: {len(selected)} > {intent.max_selected_streams}")
    return intent


def material_consumer_registry_identity(
    registry: Mapping[str, GraphMaterialConsumerIntent] | None = None,
) -> dict[str, object]:
    """Return the canonical closed-registry identity used by release gates."""

    registry = GRAPH_MATERIAL_CONSUMER_INTENTS if registry is None else registry
    validate_material_consumer_registry(registry)
    return {
        name: {
            "materiality_reason": intent.reason,
            "existing_stream_field_perimeter": [
                {
                    "source": requirement.source,
                    "stream": requirement.stream,
                    "fields": list(requirement.fields),
                    "field_perimeter_sha256": _canonical_json_sha256(
                        list(requirement.fields)
                    ),
                }
                for requirement in intent.existing_streams
            ],
            "allowed_new_streams": [
                f"{source}/{stream}"
                for source, stream in sorted(intent.allowed_new_streams)
            ],
            "max_selected_streams": intent.max_selected_streams,
            "unresolved_non_graph_prerequisites": list(
                intent.unresolved_prerequisites
            ),
        }
        for name, intent in sorted(registry.items())
    }


def material_consumer_registry_sha256(
    registry: Mapping[str, GraphMaterialConsumerIntent] | None = None,
) -> str:
    return _canonical_json_sha256(material_consumer_registry_identity(registry))


validate_material_consumer_registry()

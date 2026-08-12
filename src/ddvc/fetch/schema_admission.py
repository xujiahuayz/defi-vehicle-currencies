"""Deterministic admission policy for one-pass Graph raw acquisition."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ddvc.fetch.graphql_selection import render_selection


LEAF_KINDS = frozenset({"SCALAR", "ENUM"})
SOURCE_STREAM_CHILD_ADDITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("balancer", "swaps"): frozenset({"userAddress.id"}),
    ("curve", "daily"): frozenset({"pool.rewardTokens.id"}),
    ("sushiswap_v3", "swaps"): frozenset({"account.id"}),
    ("uniswap_v3", "swaps"): frozenset({"transaction.gasPrice", "transaction.gasUsed"}),
    ("uniswap_v3", "mints"): frozenset(
        {"token0.decimals", "token1.decimals", "transaction.gasPrice", "transaction.gasUsed"}
    ),
    ("uniswap_v3", "burns"): frozenset(
        {"token0.decimals", "token1.decimals", "transaction.gasPrice", "transaction.gasUsed"}
    ),
    ("uniswap_v4", "swaps"): frozenset({"transaction.gasPrice", "transaction.gasUsed"}),
    ("uniswap_v4", "modify_liquidities"): frozenset(
        {"transaction.gasPrice", "transaction.gasUsed"}
    ),
}
SOURCE_STREAM_REMOVALS: dict[tuple[str, str], frozenset[str]] = {
    ("balancer", "daily"): frozenset(
        {
            "pool.amp",
            "pool.swapFee",
            "pool.totalWeight",
            "pool.tokens.balance",
            "pool.tokens.weight",
        }
    )
}


@dataclass(frozen=True)
class VectorOwner:
    """Identity vector that gives one list-valued primitive its economic order."""

    identities: str
    reason: str


# A Graph field can exist in introspection while never being populated by a given
# deployment.  Keep those decisions source-and-stream specific: the same field is
# populated on V2 burns and empty on V2 mints, for example.
SOURCE_STREAM_NULL_QUARANTINE: dict[tuple[str, str], dict[str, str]] = {
    ("balancer", "fxoracles"): {
        "decimals": "always_null_across_bounded_frozen_head_canaries",
    },
    ("balancer", "joins_exits"): {
        "user.*": "provider_nonnull_resolver_failure_use_sender_identity",
    },
    ("balancer", "ampUpdates"): {
        "poolId.protocolIdData.*": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("balancer", "gradualWeightUpdates"): {
        "poolId.latestAmpUpdate.id": "always_null_across_bounded_early_middle_head_canaries",
        "poolId.protocolIdData.*": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("balancer", "managementOperations"): {
        "poolTokenId.circuitBreaker.id": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("balancer", "poolHistoricalLiquidities"): {
        "poolId.protocolIdData.*": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("balancer", "poolTokens"): {
        "circuitBreaker.*": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("balancer", "swapFeeUpdates"): {
        "pool.protocolIdData.*": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("balancer", "tokenPrices"): {
        "poolId.protocolIdData.*": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("balancer", "pools"): {
        "root3Alpha": "always_null_across_bounded_early_middle_head_canaries",
        "tokens.circuitBreaker.id": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("balancer", "priceRateProviders"): {
        "poolId.protocolIdData.*": "always_null_across_bounded_early_middle_head_canaries",
        "token.circuitBreaker.id": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("curve", "financialsDailySnapshots"): {
        "protocolControlledValueUSD": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("sushiswap_v2", "mints"): {
        "feeLiquidity": "always_null_across_bounded_early_middle_head_canaries",
        "feeTo": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("uniswap_v2", "mints"): {
        "feeLiquidity": "always_null_across_bounded_early_middle_head_canaries",
        "feeTo": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("sushiswap_v3", "swaps"): {
        "gasUsed": "always_null_across_bounded_early_middle_head_canaries_use_receipts",
    },
    ("sushiswap_v3", "deposits"): {
        "gasUsed": "always_null_across_bounded_early_middle_head_canaries_use_receipts",
        "pool.liquidityToken.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "pool.rewardTokens.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "position.*": "always_null_relation_across_bounded_early_middle_head_canaries",
    },
    ("sushiswap_v3", "withdraws"): {
        "gasUsed": "always_null_across_bounded_early_middle_head_canaries_use_receipts",
        "pool.liquidityToken.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "pool.rewardTokens.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "position.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "tickLower": "always_null_across_bounded_early_middle_head_canaries_source_position_state",
        "tickUpper": "always_null_across_bounded_early_middle_head_canaries_source_position_state",
    },
    ("sushiswap_v3", "daily"): {
        "rewardTokenEmissionsAmount": "always_null_across_bounded_early_middle_head_canaries",
        "rewardTokenEmissionsUSD": "always_null_across_bounded_early_middle_head_canaries",
        "stakedOutputTokenAmount": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("sushiswap_v3", "dexAmmProtocols"): {
        "protocolControlledValueUSD": "always_null_across_bounded_frozen_head_canaries",
    },
    ("sushiswap_v3", "financialsDailySnapshots"): {
        "protocolControlledValueUSD": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("sushiswap_v3", "liquidityPoolHourlySnapshots"): {
        "pool.liquidityToken.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "pool.rewardTokens.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "rewardTokenEmissionsAmount": "always_null_across_bounded_early_middle_head_canaries",
        "rewardTokenEmissionsUSD": "always_null_across_bounded_early_middle_head_canaries",
        "stakedOutputTokenAmount": "always_null_across_bounded_early_middle_head_canaries",
    },
    ("sushiswap_v3", "liquidityPools"): {
        "liquidityToken.*": "always_null_relation_across_bounded_head_canaries",
        "rewardTokenEmissionsAmount": "always_null_across_bounded_head_canaries",
        "rewardTokenEmissionsUSD": "always_null_across_bounded_head_canaries",
        "rewardTokens.*": "always_null_relation_across_bounded_head_canaries",
        "stakedOutputTokenAmount": "always_null_across_bounded_head_canaries",
    },
    ("sushiswap_v3", "positionSnapshots"): {
        "cumulativeDepositTokenAmounts": "unowned_vector_without_token_order",
        "cumulativeRewardTokenAmounts": "always_null_and_unowned_vector",
        "cumulativeRewardUSD": "always_null_across_bounded_early_middle_head_canaries",
        "cumulativeWithdrawTokenAmounts": "unowned_vector_without_token_order",
        "liquidityTokenType": "always_null_across_bounded_early_middle_head_canaries",
        "position.liquidityToken.*": "always_null_relation_across_bounded_early_middle_head_canaries",
    },
    ("sushiswap_v3", "positions"): {
        "blockNumberClosed": "always_null_right_censored_field",
        "cumulativeRewardUSD": "always_null_right_censored_field",
        "hashClosed": "always_null_right_censored_field",
        "liquidityToken.*": "always_null_relation_across_bounded_head_canaries",
        "pool.liquidityToken.*": "always_null_relation_across_bounded_head_canaries",
        "pool.rewardTokens.*": "always_null_relation_across_bounded_head_canaries",
        "timestampClosed": "always_null_right_censored_field",
    },
    ("sushiswap_v3", "ticks"): {
        "pool.liquidityToken.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "pool.rewardTokens.*": "always_null_relation_across_bounded_early_middle_head_canaries",
    },
    ("sushiswap_v3", "tickDailySnapshots"): {
        "pool.liquidityToken.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "pool.rewardTokens.*": "always_null_relation_across_bounded_early_middle_head_canaries",
    },
    ("sushiswap_v3", "tickHourlySnapshots"): {
        "pool.liquidityToken.*": "always_null_relation_across_bounded_early_middle_head_canaries",
        "pool.rewardTokens.*": "always_null_relation_across_bounded_early_middle_head_canaries",
    },
}


VECTOR_OWNERS: dict[tuple[str, str], dict[str, VectorOwner]] = {
    ("balancer", "daily"): {
        "amounts": VectorOwner("pool.tokens", "pool_token_order"),
        "pool.tokensList": VectorOwner("pool.tokensList", "identity_vector"),
    },
    ("balancer", "joins_exits"): {
        "amounts": VectorOwner("pool.tokensList", "pool_token_order"),
        "pool.tokensList": VectorOwner("pool.tokensList", "identity_vector"),
    },
    ("balancer", "gradualWeightUpdates"): {
        "endWeights": VectorOwner("poolId.tokensList", "pool_token_order"),
        "startWeights": VectorOwner("poolId.tokensList", "pool_token_order"),
        "poolId.tokensList": VectorOwner("poolId.tokensList", "identity_vector"),
    },
    ("balancer", "pools"): {
        "tokensList": VectorOwner("tokensList", "identity_vector"),
    },
    ("balancer", "fxoracles"): {
        "tokens": VectorOwner("tokens", "identity_vector"),
    },
    ("curve", "daily"): {
        **{
            path: VectorOwner("pool.inputTokens", "input_token_order")
            for path in (
                "dailyVolumeByTokenAmount",
                "dailyVolumeByTokenUSD",
                "inputTokenBalances",
                "inputTokenWeights",
            )
        },
        **{
            path: VectorOwner("pool.rewardTokens", "reward_token_order")
            for path in ("rewardTokenEmissionsAmount", "rewardTokenEmissionsUSD")
        },
    },
    ("curve", "deposits"): {
        "inputTokenAmounts": VectorOwner("inputTokens", "input_token_order"),
    },
    ("curve", "withdraws"): {
        "inputTokenAmounts": VectorOwner("inputTokens", "input_token_order"),
    },
    ("curve", "liquidityPoolHourlySnapshots"): {
        **{
            path: VectorOwner("pool.inputTokens", "input_token_order")
            for path in (
                "hourlyVolumeByTokenAmount",
                "hourlyVolumeByTokenUSD",
                "inputTokenBalances",
                "inputTokenWeights",
            )
        },
        **{
            path: VectorOwner("pool.rewardTokens", "reward_token_order")
            for path in ("rewardTokenEmissionsAmount", "rewardTokenEmissionsUSD")
        },
    },
    ("curve", "liquidityPools"): {
        "_inputTokensOrdered": VectorOwner("_inputTokensOrdered", "identity_vector"),
    },
    ("sushiswap_v3", "swaps"): {
        "reserveAmounts": VectorOwner("pool.inputTokens", "input_token_order"),
    },
    ("sushiswap_v3", "daily"): {
        **{
            path: VectorOwner("pool.inputTokens", "input_token_order")
            for path in (
                "cumulativeVolumeByTokenAmount",
                "cumulativeVolumeByTokenUSD",
                "dailyVolumeByTokenAmount",
                "dailyVolumeByTokenUSD",
                "inputTokenBalances",
                "inputTokenBalancesUSD",
                "inputTokenWeights",
                "uncollectedProtocolSideTokenAmounts",
                "uncollectedProtocolSideValuesUSD",
                "uncollectedSupplySideTokenAmounts",
                "uncollectedSupplySideValuesUSD",
            )
        },
    },
    ("sushiswap_v3", "deposits"): {
        "inputTokenAmounts": VectorOwner("inputTokens", "input_token_order"),
        "reserveAmounts": VectorOwner("pool.inputTokens", "input_token_order"),
    },
    ("sushiswap_v3", "withdraws"): {
        "inputTokenAmounts": VectorOwner("inputTokens", "input_token_order"),
        "reserveAmounts": VectorOwner("pool.inputTokens", "input_token_order"),
    },
    ("sushiswap_v3", "liquidityPoolHourlySnapshots"): {
        **{
            path: VectorOwner("pool.inputTokens", "input_token_order")
            for path in (
                "cumulativeVolumeByTokenAmount",
                "cumulativeVolumeByTokenUSD",
                "hourlyVolumeByTokenAmount",
                "hourlyVolumeByTokenUSD",
                "inputTokenBalances",
                "inputTokenBalancesUSD",
                "inputTokenWeights",
                "uncollectedProtocolSideTokenAmounts",
                "uncollectedProtocolSideValuesUSD",
                "uncollectedSupplySideTokenAmounts",
                "uncollectedSupplySideValuesUSD",
            )
        },
    },
    ("sushiswap_v3", "liquidityPools"): {
        **{
            path: VectorOwner("inputTokens", "input_token_order")
            for path in (
                "cumulativeVolumeByTokenAmount",
                "cumulativeVolumeByTokenUSD",
                "inputTokenBalances",
                "inputTokenBalancesUSD",
                "inputTokenWeights",
                "uncollectedProtocolSideTokenAmounts",
                "uncollectedProtocolSideValuesUSD",
                "uncollectedSupplySideTokenAmounts",
                "uncollectedSupplySideValuesUSD",
            )
        },
    },
    ("sushiswap_v3", "positions"): {
        "cumulativeDepositTokenAmounts": VectorOwner("pool.inputTokens", "input_token_order"),
        "cumulativeWithdrawTokenAmounts": VectorOwner("pool.inputTokens", "input_token_order"),
    },
    ("sushiswap_v3", "ticks"): {
        "prices": VectorOwner("pool.inputTokens", "input_token_order"),
    },
}


def null_quarantine_reason(source: str, stream: str, path: str) -> str | None:
    for pattern, reason in SOURCE_STREAM_NULL_QUARANTINE.get((source, stream), {}).items():
        if path == pattern or (pattern.endswith(".*") and path.startswith(pattern[:-1])):
            return reason
    return None


def _root_policy(
    *,
    admit: Mapping[str, set[str]],
    exclude: Mapping[str, set[str]],
) -> dict[str, dict[str, str]]:
    decisions: dict[str, dict[str, str]] = {}
    for mode, names in admit.items():
        for name in names:
            decisions[name] = {"decision": "admit", "mode": mode, "reason": mode}
    for reason, names in exclude.items():
        for name in names:
            if name in decisions:
                raise ValueError(f"Graph root policy classifies {name} twice")
            decisions[name] = {"decision": "exclude", "mode": "none", "reason": reason}
    return decisions


_V2_ROOT_POLICY = _root_policy(
    admit={
        "historical_snapshot_full": {"liquidityPositionSnapshots", "tokenDayDatas"},
        "static_identity": {"pairs", "tokens"},
    },
    exclude={
        "mutable_current_entity": {"liquidityPositions", "users"},
        "duplicate_derivable_index": {"transactions"},
        "duplicate_aggregate_or_external_price": {"bundles", "uniswapDayDatas", "uniswapFactories"},
    },
)


ROOT_POLICIES: dict[str, dict[str, dict[str, str]]] = {
    "balancer": _root_policy(
        admit={
            "historical_event_full": {"ampUpdates", "gradualWeightUpdates", "latestPrices", "managementOperations", "poolHistoricalLiquidities", "swapFeeUpdates", "tokenPrices"},
            "historical_snapshot_full": {"balancerSnapshots", "tokenSnapshots", "tradePairSnapshots"},
            "block_pinned_configuration": {"pools", "poolTokens", "priceRateProviders", "protocolIdDatas", "tokens"},
            "static_identity": {"fxoracles", "poolContracts"},
            "static_or_right_censored_auxiliary": {"tradePairs"},
        },
        exclude={
            "mutable_current_or_reverse_index": {"balancers", "poolShares", "userInternalBalances", "users"},
            "confirmed_empty_at_frozen_cutoff": {"circuitBreakers"},
        },
    ),
    "curve": _root_policy(
        admit={
            "historical_event_full": {"deposits", "withdraws"},
            "historical_snapshot_full": {"financialsDailySnapshots", "liquidityPoolHourlySnapshots", "usageMetricsDailySnapshots", "usageMetricsHourlySnapshots"},
            "static_identity": {"dexAmmProtocols", "liquidityGauges", "liquidityPoolFees", "liquidityPools", "lpTokens", "rewardTokens", "tokens"},
        },
        exclude={
            "identity_only_nonresearch_entity": {"accounts", "activeAccounts"},
            "provider_internal_state": {"circularBuffers"},
            "duplicate_derivable_index": {"events", "protocols"},
        },
    ),
    "sushiswap_v2": _V2_ROOT_POLICY,
    "uniswap_v2": _V2_ROOT_POLICY,
    "sushiswap_v3": _root_policy(
        admit={
            "historical_event_full": {"deposits", "withdraws"},
            "historical_snapshot_full": {"financialsDailySnapshots", "liquidityPoolHourlySnapshots", "positionSnapshots", "tickDailySnapshots", "tickHourlySnapshots", "usageMetricsDailySnapshots", "usageMetricsHourlySnapshots"},
            "static_or_right_censored_auxiliary": {"dexAmmProtocols", "liquidityPoolFees", "liquidityPools", "positions", "tokens"},
            "head_validation_only": {"ticks"},
        },
        exclude={
            "mutable_current_entity": {"accounts"},
            "identity_only_nonresearch_entity": {"activeAccounts"},
            "provider_internal_state": {"helperStores", "liquidityPoolAmounts", "tokenWhitelistSymbols", "tokenWhitelists"},
            "duplicate_derivable_index": {"protocols"},
            "confirmed_empty_at_frozen_cutoff": {"rewardTokens"},
        },
    ),
    "uniswap_v3": _root_policy(
        admit={
            "historical_snapshot_full": {"poolHourDatas", "positionSnapshots", "tickDayDatas", "tokenDayDatas", "tokenHourDatas"},
            "static_identity": {"pools", "tokens"},
            "static_or_right_censored_auxiliary": {"positions"},
        },
        exclude={
            "mutable_current_entity": {"ticks"},
            "duplicate_derivable_index": {"transactions"},
            "duplicate_aggregate_or_external_price": {"bundles", "factories", "uniswapDayDatas"},
            "confirmed_empty_at_frozen_cutoff": {"collects", "flashes", "tickHourDatas"},
        },
    ),
    "uniswap_v4": _root_policy(
        admit={
            "historical_event_full": {"transfers"},
            "historical_snapshot_full": {"poolHourDatas", "tokenDayDatas", "tokenHourDatas"},
            "static_identity": {"pools", "positions", "tokens"},
        },
        exclude={
            "mutable_current_entity": {"ticks"},
            "duplicate_derivable_index": {"transactions"},
            "duplicate_aggregate_or_external_price": {"bundles", "poolManagers", "uniswapDayDatas"},
            "confirmed_empty_at_frozen_cutoff": {"subscribes", "unsubscribes"},
        },
    ),
}

STATIC_DIRECT_FIELDS = frozenset(
    {
        "_inputTokensOrdered",
        "_isMetapool",
        "_registryAddress",
        "address",
        "createTime",
        "createdAtBlockNumber",
        "createdAtTimestamp",
        "createdBlockNumber",
        "createdTimestamp",
        "decimals",
        "factory",
        "feeTier",
        "hooks",
        "id",
        "isBasePoolLpToken",
        "isSingleSided",
        "liquidityTokenType",
        "name",
        "oracleType",
        "poolType",
        "poolTypeVersion",
        "symbol",
        "tickSpacing",
        "tokens",
        "tokensList",
        "type",
    }
)
CHILD_IDENTITY_FIELDS = frozenset(
    {
        "address",
        "blockNumber",
        "decimals",
        "feeTier",
        "hooks",
        "id",
        "name",
        "poolType",
        "poolTypeVersion",
        "symbol",
        "tickSpacing",
        "timestamp",
    }
)
TRANSACTION_CHILD_FIELDS = frozenset(
    {"blockNumber", "gasLimit", "gasPrice", "gasUsed", "hash", "id", "nonce", "timestamp"}
)
BOUNDED_LIST_RELATIONS = frozenset({"inputTokens", "rewardTokens", "tokens"})
SOURCE_NEW_STREAM_CHILD_ADDITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("balancer", "gradualWeightUpdates"): frozenset({"poolId.tokensList"}),
}


def _identity_is_selected(identity_path: str, admitted: set[str]) -> bool:
    return identity_path in admitted or any(
        path.startswith(f"{identity_path}.") for path in admitted
    )


def _validate_vector_ownership(
    source: str,
    stream: str,
    fields: Mapping[str, Mapping[str, Any]],
    admitted: set[str],
) -> list[dict[str, str]]:
    owners = VECTOR_OWNERS.get((source, stream), {})
    admitted_vectors = sorted(
        path for path in admitted if fields.get(path, {}).get("field_list_valued")
    )
    missing = sorted(set(admitted_vectors).difference(owners))
    if missing:
        raise ValueError(
            f"unowned admitted Graph vectors for {source}/{stream}: {', '.join(missing)}"
        )
    records = []
    for values_path in admitted_vectors:
        owner = owners[values_path]
        if not _identity_is_selected(owner.identities, admitted):
            raise ValueError(
                f"Graph vector owner absent for {source}/{stream}/{values_path}: "
                f"{owner.identities}"
            )
        records.append(
            {
                "values_path": values_path,
                "identities_path": owner.identities,
                "reason": owner.reason,
            }
        )
    return records


def adjudicate_new_stream_fields(source: str, entity: Mapping[str, Any]) -> dict[str, Any]:
    """Select a temporally valid superset for one newly admitted root."""

    mode = str(entity.get("mode") or "")
    stream = str(entity.get("entity") or "")
    special_additions = SOURCE_NEW_STREAM_CHILD_ADDITIONS.get(
        (source, stream), frozenset()
    )
    admitted = set()
    decisions = []
    fields_by_path = {
        str(field["path"]): field
        for field in entity.get("fields") or []
        if isinstance(field, Mapping) and isinstance(field.get("path"), str)
    }
    for field in sorted(entity.get("fields") or [], key=lambda item: str(item.get("path") or "")):
        if not isinstance(field, Mapping) or not isinstance(field.get("path"), str):
            continue
        path = str(field["path"])
        parts = path.split(".")
        direct = len(parts) == 1
        leaf = parts[-1]
        quarantine = null_quarantine_reason(source, stream, path)
        if quarantine:
            decision, reason = "exclude", quarantine
        elif path in special_additions:
            decision, reason = "admit", "source_specific_vector_identity_contract"
        elif field.get("deprecated"):
            decision, reason = "exclude", "provider_deprecated"
        elif field.get("kind") == "RELATION_BOUNDARY":
            decision, reason = "exclude", "recursive_relation_boundary"
        elif direct and field.get("kind") in LEAF_KINDS:
            if mode == "static_identity" and leaf not in STATIC_DIRECT_FIELDS:
                decision, reason = "exclude", "mutable_head_state_not_static_identity"
            else:
                decision, reason = "admit", f"{mode}_root_primitive"
        elif field.get("kind") not in LEAF_KINDS:
            decision, reason = "exclude", "nonprimitive_relation"
        elif field.get("ancestor_list_valued") or field.get("field_list_valued"):
            bounded_relation = parts[0] in BOUNDED_LIST_RELATIONS or (
                len(parts) > 2
                and parts[0] == "pool"
                and parts[1] in BOUNDED_LIST_RELATIONS
            )
            nested_reverse = "managements" in parts
            if bounded_relation and not nested_reverse and leaf in CHILD_IDENTITY_FIELDS:
                decision, reason = "admit", "bounded_aligned_token_identity"
            else:
                decision, reason = "exclude", "unbounded_or_reverse_child_relation"
        elif parts[0] == "transaction" and leaf in TRANSACTION_CHILD_FIELDS:
            decision, reason = "admit", "transaction_identity_and_gas"
        elif leaf in CHILD_IDENTITY_FIELDS:
            decision, reason = "admit", "singular_child_identity"
        else:
            decision, reason = "exclude", "mutable_nested_state_without_event_time_semantics"
        if decision == "admit":
            admitted.add(path)
        decisions.append({"path": path, "decision": decision, "reason": reason})
    if "id" not in admitted:
        raise ValueError(f"new Graph stream lacks admitted id: {source}/{entity.get('entity')}")
    vector_owners = _validate_vector_ownership(
        source, stream, fields_by_path, admitted
    )
    return {
        "source": source,
        "entity": entity.get("entity"),
        "entity_type": entity.get("entity_type"),
        "mode": mode,
        "proposed_selected_paths": sorted(admitted),
        "proposed_selection": render_selection(admitted),
        "vector_owners": vector_owners,
        "decisions": decisions,
    }


def build_new_stream_field_manifest(inventory: Mapping[str, Any]) -> dict[str, Any]:
    sources = []
    for source in inventory.get("sources") or []:
        if not isinstance(source, Mapping):
            continue
        source_name = str(source.get("source") or "")
        entities = [
            adjudicate_new_stream_fields(source_name, entity)
            for entity in source.get("entities") or []
        ]
        sources.append({"source": source_name, "status": source.get("status"), "entities": entities})
    return {
        "schema_version": 1,
        "kind": "graph_new_stream_field_admission",
        "inventory_captured_at_utc": inventory.get("captured_at_utc"),
        "summary": {
            "sources": len(sources),
            "new_entities": sum(len(source["entities"]) for source in sources),
            "admitted_paths": sum(
                len(entity["proposed_selected_paths"])
                for source in sources
                for entity in source["entities"]
            ),
        },
        "sources": sources,
    }


def adjudicate_query_roots(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Classify every provider query root, failing if a collection is forgotten."""

    source_name = str(source.get("source") or "")
    active = {str(entity.get("entity")) for entity in source.get("entities") or []}
    policy = ROOT_POLICIES.get(source_name, {})
    decisions = []
    missing = []
    for root in source.get("query_roots") or []:
        if not isinstance(root, Mapping):
            continue
        name = str(root.get("name") or "")
        if name.startswith("_"):
            decision = {"decision": "exclude", "mode": "none", "reason": "provider_metadata"}
        elif not root.get("list_valued"):
            decision = {"decision": "exclude", "mode": "none", "reason": "singular_lookup_not_a_bulk_stream"}
        elif name in active:
            decision = {"decision": "admit", "mode": "active_stream", "reason": "existing_active_stream"}
        elif name in policy:
            decision = policy[name]
        else:
            missing.append(name)
            continue
        decisions.append({"name": name, "type": root.get("type"), "list_valued": bool(root.get("list_valued")), **decision})
    if missing:
        raise ValueError(f"unclassified Graph collection roots for {source_name}: {', '.join(sorted(missing))}")
    return sorted(decisions, key=lambda item: str(item["name"]))


def adjudicate_entity_fields(source: str, entity: Mapping[str, Any]) -> dict[str, Any]:
    """Admit historical primitives and bounded identity; reject unsafe expansion."""

    selected = set(entity.get("selected_paths") or [])
    key = (source, str(entity.get("stream") or ""))
    child_additions = SOURCE_STREAM_CHILD_ADDITIONS.get(key, frozenset())
    removals = SOURCE_STREAM_REMOVALS.get(key, frozenset())
    fields = {
        str(field["path"]): field
        for field in entity.get("fields") or []
        if isinstance(field, Mapping) and isinstance(field.get("path"), str)
    }
    decisions = []
    admitted = set()
    for path, field in sorted(fields.items()):
        direct = "." not in path
        quarantine = null_quarantine_reason(source, str(entity.get("stream") or ""), path)
        if quarantine:
            decision, reason = "exclude", quarantine
        elif path in removals:
            decision, reason = "exclude", "mutable_parent_state_can_leak_query_head_backward"
        elif field.get("deprecated"):
            decision, reason = "exclude", "provider_deprecated"
        elif path in selected:
            decision, reason = "admit", "existing_validated_contract"
        elif direct and field.get("kind") in LEAF_KINDS:
            decision, reason = "admit", "root_historical_primitive"
        elif path in child_additions:
            decision, reason = "admit", "source_specific_bounded_child_contract"
        elif field.get("kind") == "RELATION_BOUNDARY":
            decision, reason = "exclude", "recursive_relation_boundary"
        elif field.get("ancestor_list_valued") or field.get("field_list_valued"):
            decision, reason = "exclude", "unbounded_or_row_multiplying_child_relation"
        else:
            decision, reason = "exclude", "mutable_nested_state_without_event_time_semantics"
        if decision == "admit":
            admitted.add(path)
        decisions.append({"path": path, "decision": decision, "reason": reason})

    absent_selected = sorted(selected - set(fields))
    for path in absent_selected:
        decisions.append(
            {
                "path": path,
                "decision": "invalid_current_contract",
                "reason": "selected_path_absent_or_relation_selected_without_leaf",
            }
        )
    vector_owners = _validate_vector_ownership(
        source, str(entity.get("stream") or ""), fields, admitted
    )
    return {
        "stream": entity.get("stream"),
        "entity": entity.get("entity"),
        "current_selected_paths": sorted(selected),
        "proposed_selected_paths": sorted(admitted),
        "added_paths": sorted(admitted - selected),
        "removed_or_invalid_paths": sorted(selected - admitted),
        "proposed_selection": render_selection(admitted),
        "vector_owners": vector_owners,
        "decisions": sorted(decisions, key=lambda item: (str(item["path"]), str(item["decision"]))),
    }


def build_field_admission_manifest(inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Build a complete active-stream manifest and surface schema-family divergence."""

    sources = []
    by_family: dict[tuple[str, str, str], list[tuple[str, tuple[str, ...]]]] = defaultdict(list)
    for source in inventory.get("sources") or []:
        if not isinstance(source, Mapping):
            continue
        source_name = str(source.get("source") or "")
        schema_family = str(source.get("schema_family") or "")
        entities = [
            adjudicate_entity_fields(source_name, entity)
            for entity in source.get("entities") or []
        ]
        for entity in entities:
            by_family[(schema_family, str(entity["stream"]), str(entity["entity"]))].append(
                (source_name, tuple(entity["proposed_selected_paths"]))
            )
        sources.append(
            {
                "source": source_name,
                "schema_family": schema_family,
                "status": source.get("status"),
                "entities": entities,
                "query_root_decisions": adjudicate_query_roots(source),
            }
        )
    divergences = []
    for (family, stream, entity), variants in sorted(by_family.items()):
        unique = {paths for _, paths in variants}
        if len(unique) > 1:
            divergences.append(
                {
                    "schema_family": family,
                    "stream": stream,
                    "entity": entity,
                    "sources": [name for name, _ in variants],
                    "reason": "live deployments expose different admitted field contracts",
                }
            )
    added = sum(len(entity["added_paths"]) for source in sources for entity in source["entities"])
    invalid = sum(
        len(entity["removed_or_invalid_paths"])
        for source in sources
        for entity in source["entities"]
    )
    query_roots = sum(len(source["query_root_decisions"]) for source in sources)
    collection_roots = sum(
        1
        for source in sources
        for root in source["query_root_decisions"]
        if root["list_valued"]
    )
    admitted_new_roots = sum(
        1
        for source in sources
        for root in source["query_root_decisions"]
        if root["decision"] == "admit" and root["mode"] != "active_stream"
    )
    return {
        "schema_version": 1,
        "kind": "graph_active_stream_field_admission",
        "inventory_captured_at_utc": inventory.get("captured_at_utc"),
        "policy": {
            "admit": [
                "every nondeprecated primitive on the historical root entity",
                "existing validated bounded selections",
                "singular child identity and invariant mechanics",
            ],
            "exclude": [
                "deprecated provider fields",
                "unbounded or row-multiplying child relations",
                "mutable nested current state without event-time semantics",
                "recursive relationship expansion",
            ],
        },
        "summary": {
            "sources": len(sources),
            "active_entities": sum(len(source["entities"]) for source in sources),
            "fields_added": added,
            "invalid_current_paths": invalid,
            "source_specific_schema_splits_required": len(divergences),
            "query_roots_classified": query_roots,
            "collection_roots_classified": collection_roots,
            "new_collection_roots_admitted": admitted_new_roots,
        },
        "source_specific_schema_splits": divergences,
        "sources": sources,
    }

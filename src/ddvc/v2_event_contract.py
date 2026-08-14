"""Stable V2-family event and reconciliation contracts."""

from __future__ import annotations

from eth_utils import keccak


V2_EVENT_VENUES = ("uniswap_v2", "sushiswap_v2")
V2_CORE_EVENTS = ("burn", "mint", "swap")
V2_EVENT_SIGNATURES = {
    "mint": "Mint(address,uint256,uint256)",
    "burn": "Burn(address,uint256,uint256,address)",
    "swap": "Swap(address,uint256,uint256,uint256,uint256,address)",
}
V2_EVENT_TOPICS = {
    name: "0x" + keccak(text=signature).hex()
    for name, signature in V2_EVENT_SIGNATURES.items()
}
V2_EVENT_BY_TOPIC = {topic: name for name, topic in V2_EVENT_TOPICS.items()}
V2_EVENT_SOURCE_SCHEMA_VERSION = 7
V2_POOL_PERIMETER = "all_paircreated_pools_from_registered_mainnet_factories_net_of_materiality_audited_token_pair_exclusions"
V2_RECONCILIATION_SCOPE = "full_utc_day_materiality_admitted_factory_pool_perimeter"
V2_COMPARISON_LEDGER = "released_corrected_provider_ledger"
V2_RECONCILIATION_COUNT_FIELDS = (
    "provider_rows",
    "unique_provider_events",
    "provider_duplicate_rows",
    "exact_events_in_provider_observed_pool_perimeter",
    "exact_events_in_factory_pool_perimeter",
    "matched_events",
    "correction_rows",
    "log_index_repairs",
    "payload_repairs",
    "incomplete_liquidity_repairs",
    "exclusion_rows",
    "reverted_transaction_exclusions",
    "successful_transaction_absence_exclusions",
    "incomplete_liquidity_absence_exclusions",
    "provider_duplicate_exclusions",
    "supplement_rows",
    "canonical_rows",
)
V2_RECONCILIATION_DETAILED_EXCLUSION_FIELDS = (
    "reverted_transaction_exclusions",
    "successful_transaction_absence_exclusions",
    "incomplete_liquidity_absence_exclusions",
    "provider_duplicate_exclusions",
)


def normalize_token_decimals(values: object) -> dict[str, int]:
    """Normalize one token-decimals authority without silent key collisions."""

    if values is None:
        return {}
    try:
        items = values.items()
    except AttributeError as error:
        raise ValueError("audited token decimals must be a mapping") from error
    normalized: dict[str, int] = {}
    original_keys: dict[str, str] = {}
    for raw_token, raw_decimals in items:
        token = str(raw_token or "").lower()
        try:
            decimals = int(raw_decimals)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid audited token decimals: {raw_token}") from error
        if not token or decimals < 0 or decimals > 255:
            raise ValueError(f"invalid audited token decimals: {raw_token}")
        prior = normalized.get(token)
        if prior is not None or token in normalized:
            raise ValueError(
                "audited token decimals contain duplicate case-normalized keys: "
                f"{original_keys[token]} and {raw_token}"
            )
        normalized[token] = decimals
        original_keys[token] = str(raw_token)
    return normalized

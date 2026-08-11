"""Pool-family execution semantics owned independently of capital accounting.

Execution-state materialization must not be invalidated by a change to a TVL,
inventory, or return-denominator rule.  This module is the single owner of pool
families, invariant identities, state generations, and quote readiness used by
the canonical market-state engine.  The richer liquidity registry composes these
execution contracts with separate capital and LVR capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass


CP_STATE_GENERATION = "constant_product_state_v2"
TICK_STATE_GENERATIONS = {
    "uniswap_v3": "uniswap_v3_tick_state_v3_initialize_exact",
    "uniswap_v4": "uniswap_v4_tick_state_v3_poolmanager_exact",
}
MULTI_ASSET_STATE_GENERATIONS = {
    "curve": "curve_multi_asset_state_v2",
    "balancer": "balancer_multi_asset_state_v2",
}
STATE_GENERATIONS = {
    **TICK_STATE_GENERATIONS,
    "uniswap_v2": CP_STATE_GENERATION,
    "sushiswap_v2": CP_STATE_GENERATION,
    **MULTI_ASSET_STATE_GENERATIONS,
}


@dataclass(frozen=True)
class ExecutionContract:
    venue: str
    pool_family: str
    invariant_family: str
    state_generation: str | None = None
    quote_ready: bool = False


def _execution(
    venue: str,
    pool_family: str,
    invariant_family: str,
    *,
    state_generation: str | None = None,
    quote_ready: bool = False,
) -> ExecutionContract:
    return ExecutionContract(
        venue=venue,
        pool_family=pool_family,
        invariant_family=invariant_family,
        state_generation=state_generation,
        quote_ready=quote_ready,
    )


EXECUTION_CONTRACTS = {
    ("uniswap_v1", "full_range_constant_product"): _execution(
        "uniswap_v1", "full_range_constant_product", "full_range_constant_product"
    ),
    ("uniswap_v2", "full_range_constant_product"): _execution(
        "uniswap_v2", "full_range_constant_product", "full_range_constant_product",
        state_generation=CP_STATE_GENERATION, quote_ready=True,
    ),
    ("sushiswap_v2", "full_range_constant_product"): _execution(
        "sushiswap_v2", "full_range_constant_product", "full_range_constant_product",
        state_generation=CP_STATE_GENERATION, quote_ready=True,
    ),
    ("uniswap_v3", "concentrated_liquidity"): _execution(
        "uniswap_v3", "concentrated_liquidity", "concentrated_liquidity",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v3"], quote_ready=True,
    ),
    ("sushiswap_v3", "concentrated_liquidity"): _execution(
        "sushiswap_v3", "concentrated_liquidity", "concentrated_liquidity"
    ),
    ("curve", "stableswap"): _execution(
        "curve", "stableswap", "stableswap",
        state_generation=MULTI_ASSET_STATE_GENERATIONS["curve"],
    ),
    ("curve", "cryptoswap"): _execution(
        "curve", "cryptoswap", "cryptoswap",
        state_generation=MULTI_ASSET_STATE_GENERATIONS["curve"],
    ),
    ("curve", "ng_or_unclassified"): _execution(
        "curve", "ng_or_unclassified", "ng_or_unclassified",
        state_generation=MULTI_ASSET_STATE_GENERATIONS["curve"],
    ),
    ("balancer", "weighted"): _execution(
        "balancer", "weighted", "weighted_geometric_mean",
        state_generation=MULTI_ASSET_STATE_GENERATIONS["balancer"],
    ),
    ("balancer", "stable_or_composable_stable"): _execution(
        "balancer", "stable_or_composable_stable", "stable_or_composable_stable",
        state_generation=MULTI_ASSET_STATE_GENERATIONS["balancer"],
    ),
    ("balancer", "linear_or_boosted"): _execution(
        "balancer", "linear_or_boosted", "linear_target_band",
        state_generation=MULTI_ASSET_STATE_GENERATIONS["balancer"],
    ),
    ("balancer", "gyro_or_custom"): _execution(
        "balancer", "gyro_or_custom", "gyro_or_custom",
        state_generation=MULTI_ASSET_STATE_GENERATIONS["balancer"],
    ),
    ("balancer", "dynamic_weight_or_managed"): _execution(
        "balancer", "dynamic_weight_or_managed", "time_varying_weight_or_managed",
        state_generation=MULTI_ASSET_STATE_GENERATIONS["balancer"],
    ),
    ("balancer", "unclassified"): _execution(
        "balancer", "unclassified", "unclassified",
        state_generation=MULTI_ASSET_STATE_GENERATIONS["balancer"],
    ),
    ("uniswap_v4", "vanilla_concentrated"): _execution(
        "uniswap_v4", "vanilla_concentrated", "concentrated_liquidity_singleton",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v4"], quote_ready=True,
    ),
    ("uniswap_v4", "hooked_or_dynamic_fee"): _execution(
        "uniswap_v4", "hooked_or_dynamic_fee", "hook_defined",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v4"],
    ),
    ("uniswap_v4", "unclassified"): _execution(
        "uniswap_v4", "unclassified", "unclassified",
        state_generation=TICK_STATE_GENERATIONS["uniswap_v4"],
    ),
    ("fluid", "trade_only"): _execution(
        "fluid", "trade_only", "protocol_specific"
    ),
}


def execution_contract(venue: str, pool_family: str) -> ExecutionContract:
    try:
        return EXECUTION_CONTRACTS[(venue, pool_family)]
    except KeyError:
        raise ValueError(
            f"no execution contract for venue={venue!r}, pool_family={pool_family!r}"
        ) from None


def execution_semantics(
    venue: str,
    pool_family: str,
    state_generation: str,
) -> tuple[str, bool]:
    contract = execution_contract(venue, pool_family)
    return (
        contract.invariant_family,
        bool(contract.quote_ready and contract.state_generation == state_generation),
    )

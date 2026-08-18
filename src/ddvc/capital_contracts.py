"""Deposited-capital contracts owned independently of depth, quotes, and LVR."""

from __future__ import annotations

from dataclasses import dataclass


MAX_POOL_CAPITAL_USD = 10_000_000_000.0
CAPITAL_CURRENT_COLUMN = "capital_usd"
CAPITAL_COLUMN = "capital_usd_lagged"
CAPITAL_SOURCE = "validated_hourly_reserve_snapshot"
CP_CAPITAL_STATE_GENERATION = "validated_hourly_reserve_snapshot_v1"
CURRENT_CAPITAL_VALIDATION_STATUS = "exact_state_current"
RETURN_CAPITAL_VALIDATION_STATUS = "exact_state_prior_calendar"
VALID_CAPITAL_STATUSES = frozenset(
    {CURRENT_CAPITAL_VALIDATION_STATUS, RETURN_CAPITAL_VALIDATION_STATUS}
)


@dataclass(frozen=True)
class CapitalContract:
    venue: str
    pool_family: str
    invariant_family: str
    state_generation: str
    capital_measure: str
    capital_sources: tuple[str, ...]
    materializer: str
    validation: str
    admissible_uses: tuple[str, ...]


READY_CAPITAL_CONTRACTS = {
    venue: CapitalContract(
        venue=venue,
        pool_family="full_range_constant_product",
        invariant_family="full_range_constant_product",
        state_generation=CP_CAPITAL_STATE_GENERATION,
        capital_measure=(
            "last admissible hourly reserves valued from a separately validated address-day price anchor"
        ),
        capital_sources=(CAPITAL_SOURCE,),
        materializer="scripts.process.build_pool_capital_panel:main",
        validation=(
            "validated_last_hourly_reserves_with_audited_identity_decimals_"
            "independent_prices_and_exact_prior_calendar_lag"
        ),
        admissible_uses=("descriptive", "return"),
    )
    for venue in ("uniswap_v2", "sushiswap_v2")
}


def capital_contract(venue: str) -> CapitalContract:
    try:
        return READY_CAPITAL_CONTRACTS[venue]
    except KeyError:
        raise ValueError(f"{venue} has no admitted deposited-capital contract") from None


def capital_supported(venue: str) -> bool:
    return venue in READY_CAPITAL_CONTRACTS


def equal_candidate_capital_weights(
    pool_tokens: tuple[str, ...],
    candidates: set[str] | frozenset[str],
) -> dict[str, float]:
    """Allocate one pool's capital once across candidate tokens on its sides."""

    matched = tuple(dict.fromkeys(token for token in pool_tokens if token in candidates))
    if not matched:
        return {}
    weight = 1.0 / len(matched)
    return {token: weight for token in matched}

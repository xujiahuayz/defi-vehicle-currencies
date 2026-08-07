"""Route-level scoring against a strict pre-transaction tick-venue frontier."""

from __future__ import annotations

from dataclasses import dataclass

from ddvc.pricing.tick_frontier import (
    PoolIndex,
    best_tick_leg,
    best_tick_public_path,
    best_tick_vehicle_path,
    quote_tick_path,
)
from ddvc.pricing.tick_state import TickPoolState


@dataclass(frozen=True)
class RealisedTickPath:
    token_in: str
    token_out: str
    vehicle: str
    amount_in: float
    amount_out: float
    venues: tuple[str, str]
    pools: tuple[str, str]


def _gain_bps(frontier: float, realised: float) -> float:
    return 10_000.0 * max(0.0, frontier - realised) / realised


def score_tick_frontier(
    route: RealisedTickPath,
    *,
    vehicles: tuple[str, ...],
    pool_index: PoolIndex,
    states_by_venue: dict[str, dict[str, TickPoolState]],
    ticks_by_venue: dict[str, dict[str, dict[int, int]]],
    max_price_impact: float,
    validation_tolerance: float,
) -> dict[str, object] | None:
    """Validate the chosen path, then score nested routing opportunity sets.

    The realised route is feasible by construction and remains in every frontier,
    even if its own impact exceeds the counterfactual support boundary. That keeps
    every regret weakly non-negative without admitting an unsupported alternative.
    """
    if route.amount_in <= 0 or route.amount_out <= 0:
        return None
    chosen = quote_tick_path(
        route.token_in,
        route.token_out,
        route.vehicle,
        route.amount_in,
        venues=route.venues,
        pools=route.pools,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        max_price_impact=None,
    )
    if chosen is None:
        return None
    validation_error = (chosen.amount_out - route.amount_out) / route.amount_out
    if abs(validation_error) > validation_tolerance:
        return None

    observed_venues = set(route.venues)
    direct_observed = best_tick_leg(
        route.token_in,
        route.token_out,
        route.amount_in,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=observed_venues,
        max_price_impact=max_price_impact,
    )
    direct_public = best_tick_leg(
        route.token_in,
        route.token_out,
        route.amount_in,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=None,
        max_price_impact=max_price_impact,
    )
    same_observed = best_tick_vehicle_path(
        route.token_in,
        route.token_out,
        route.vehicle,
        route.amount_in,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=observed_venues,
        max_price_impact=max_price_impact,
    )
    same_public = best_tick_vehicle_path(
        route.token_in,
        route.token_out,
        route.vehicle,
        route.amount_in,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=None,
        max_price_impact=max_price_impact,
    )
    public = best_tick_public_path(
        route.token_in,
        route.token_out,
        vehicles,
        route.amount_in,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=None,
        max_price_impact=max_price_impact,
    )

    realised = route.amount_out
    same_observed_out = max(realised, same_observed.amount_out if same_observed else 0.0)
    same_public_out = max(realised, same_public.amount_out if same_public else 0.0)
    public_out = max(realised, public.amount_out if public else 0.0)
    if same_public_out + 1e-12 < same_observed_out or public_out + 1e-12 < same_public_out:
        raise AssertionError("nested transaction-state frontiers are not monotone")
    same_observed_winner = (
        same_observed if same_observed is not None and same_observed.amount_out > realised else None
    )
    same_public_winner = (
        same_public if same_public is not None and same_public.amount_out > realised else None
    )
    public_winner = public if public is not None and public.amount_out > realised else None

    return {
        "chosen_quote_out": chosen.amount_out,
        "chosen_validation_error_bps": 10_000.0 * validation_error,
        "chosen_max_price_impact": max(chosen.price_impacts),
        "direct_observed_out": direct_observed.amount_out if direct_observed else None,
        "direct_public_out": direct_public.amount_out if direct_public else None,
        "same_vehicle_observed_out": same_observed_out,
        "same_vehicle_public_out": same_public_out,
        "public_path_out": public_out,
        "within_reach_search_regret_bps": _gain_bps(same_observed_out, realised),
        "public_reach_same_vehicle_regret_bps": _gain_bps(same_public_out, realised),
        "public_path_regret_bps": _gain_bps(public_out, realised),
        "reach_increment_bps": 10_000.0 * (same_public_out - same_observed_out) / realised,
        "path_choice_increment_bps": 10_000.0 * (public_out - same_public_out) / realised,
        "direct_omission_bps": (
            _gain_bps(direct_public.amount_out, realised)
            if direct_public is not None
            else None
        ),
        "same_vehicle_observed_venues": (
            "|".join(same_observed_winner.venues)
            if same_observed_winner is not None
            else "|".join(route.venues)
        ),
        "same_vehicle_observed_pools": (
            "|".join(same_observed_winner.pools)
            if same_observed_winner is not None
            else "|".join(route.pools)
        ),
        "same_vehicle_public_venues": (
            "|".join(same_public_winner.venues)
            if same_public_winner is not None
            else "|".join(route.venues)
        ),
        "same_vehicle_public_pools": (
            "|".join(same_public_winner.pools)
            if same_public_winner is not None
            else "|".join(route.pools)
        ),
        "public_path_vehicle": (
            public_winner.vehicle if public_winner is not None else route.vehicle
        ),
        "public_path_venues": (
            "|".join(public_winner.venues)
            if public_winner is not None
            else "|".join(route.venues)
        ),
        "public_path_pools": (
            "|".join(public_winner.pools)
            if public_winner is not None
            else "|".join(route.pools)
        ),
    }

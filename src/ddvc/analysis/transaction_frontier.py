"""Route-level scoring against a strict pre-transaction path frontier."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from math import isfinite

from ddvc.pricing.path_frontier import (
    LegEnumerator,
    LegQuote,
    PathQuote,
    best_leg,
    best_public_path,
    best_vehicle_path,
)
from ddvc.pricing.tick_frontier import (
    PoolIndex,
    TickQuoteIndexes,
    quote_tick_path,
    tick_leg_quotes,
)
from ddvc.pricing.tick_state import TickPoolState


@dataclass(frozen=True)
class RealisedPath:
    token_in: str
    token_out: str
    vehicle: str
    amount_in: float
    amount_out: float
    venues: tuple[str, str]
    pools: tuple[str, str]


RealisedTickPath = RealisedPath
ChosenPathQuoter = Callable[[RealisedPath], PathQuote | None]


def positive_finite_amount(value: float) -> bool:
    """Whether an amount can enter a relative route-output comparison."""
    return isfinite(value) and value > 0


def chosen_output_error(
    route: RealisedPath,
    chosen: PathQuote | None,
) -> float | None:
    """Relative chosen-route reproduction error, or None off valid support."""
    if chosen is None:
        return None
    if not positive_finite_amount(route.amount_out):
        return None
    if not positive_finite_amount(chosen.amount_out):
        return None
    return (chosen.amount_out - route.amount_out) / route.amount_out


def _gain_bps(frontier: float, realised: float) -> float:
    return 10_000.0 * max(0.0, frontier - realised) / realised


def score_frontier(
    route: RealisedPath,
    *,
    vehicles: tuple[str, ...],
    quote_legs: LegEnumerator,
    quote_chosen: ChosenPathQuoter,
    validation_tolerance: float,
) -> dict[str, object] | None:
    """Validate the chosen path, then score nested routing opportunity sets.

    The realised route is feasible by construction and remains in every frontier,
    even if its own impact exceeds the counterfactual support boundary. That keeps
    every regret weakly non-negative without admitting an unsupported alternative.
    """
    if not positive_finite_amount(route.amount_in):
        return None
    chosen = quote_chosen(route)
    return score_frontier_from_quote(
        route,
        chosen=chosen,
        vehicles=vehicles,
        quote_legs=quote_legs,
        validation_tolerance=validation_tolerance,
    )


def score_frontier_from_quote(
    route: RealisedPath,
    *,
    chosen: PathQuote | None,
    vehicles: tuple[str, ...],
    quote_legs: LegEnumerator,
    validation_tolerance: float,
) -> dict[str, object] | None:
    """Score a frontier from one already-computed chosen-route quote."""
    if not positive_finite_amount(route.amount_in):
        return None
    validation_error = chosen_output_error(route, chosen)
    if validation_error is None:
        return None
    if abs(validation_error) > validation_tolerance:
        return None
    assert chosen is not None

    observed_venues = set(route.venues)

    def within_observed(
        token_in: str, token_out: str, amount_in: float
    ) -> Iterable[LegQuote]:
        return [
            quote
            for quote in quote_legs(token_in, token_out, amount_in)
            if quote.venue in observed_venues
        ]

    direct_observed = best_leg(
        route.token_in,
        route.token_out,
        route.amount_in,
        quote_legs=within_observed,
    )
    direct_public = best_leg(
        route.token_in,
        route.token_out,
        route.amount_in,
        quote_legs=quote_legs,
    )
    same_observed = best_vehicle_path(
        route.token_in,
        route.token_out,
        route.vehicle,
        route.amount_in,
        quote_legs=within_observed,
    )
    same_public = best_vehicle_path(
        route.token_in,
        route.token_out,
        route.vehicle,
        route.amount_in,
        quote_legs=quote_legs,
    )
    public_vehicles = tuple(sorted(set(vehicles) | {route.vehicle}))
    public = best_public_path(
        route.token_in,
        route.token_out,
        public_vehicles,
        route.amount_in,
        quote_legs=quote_legs,
    )

    realised = route.amount_out
    same_observed_out = max(realised, same_observed.amount_out if same_observed else 0.0)
    same_public_out = max(realised, same_public.amount_out if same_public else 0.0)
    public_out = max(realised, public.amount_out if public else 0.0)
    if same_public_out + 1e-12 < same_observed_out or public_out + 1e-12 < same_public_out:
        raise AssertionError("nested transaction-state frontiers are not monotone")
    same_observed_winner = same_observed if (
        same_observed is not None and same_observed.amount_out > realised
    ) else None
    same_public_winner = same_public if (
        same_public is not None and same_public.amount_out > realised
    ) else None
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


def score_tick_frontier(
    route: RealisedPath,
    *,
    vehicles: tuple[str, ...],
    pool_index: PoolIndex,
    states_by_venue: dict[str, dict[str, TickPoolState]],
    ticks_by_venue: dict[str, dict[str, dict[int, int]]],
    max_price_impact: float,
    validation_tolerance: float,
    quote_indexes_by_venue: TickQuoteIndexes | None = None,
) -> dict[str, object] | None:
    """Compatibility adapter for a frontier containing only tick venues."""
    quote_legs = partial(
        tick_leg_quotes,
        pool_index=pool_index,
        states_by_venue=states_by_venue,
        ticks_by_venue=ticks_by_venue,
        allowed_venues=None,
        max_price_impact=max_price_impact,
        quote_indexes_by_venue=quote_indexes_by_venue,
    )

    def quote_chosen(chosen_route: RealisedPath) -> PathQuote | None:
        return quote_tick_path(
            chosen_route.token_in,
            chosen_route.token_out,
            chosen_route.vehicle,
            chosen_route.amount_in,
            venues=chosen_route.venues,
            pools=chosen_route.pools,
            states_by_venue=states_by_venue,
            ticks_by_venue=ticks_by_venue,
            max_price_impact=None,
            quote_indexes_by_venue=quote_indexes_by_venue,
        )

    return score_frontier(
        route,
        vehicles=vehicles,
        quote_legs=quote_legs,
        quote_chosen=quote_chosen,
        validation_tolerance=validation_tolerance,
    )

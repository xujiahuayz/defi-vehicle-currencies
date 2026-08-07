"""Venue-agnostic search over direct and one-vehicle execution paths."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class LegQuote:
    amount_out: float
    venue: str
    pool: str
    price_impact: float


@dataclass(frozen=True)
class PathQuote:
    amount_out: float
    vehicle: str | None
    venues: tuple[str, ...]
    pools: tuple[str, ...]
    price_impacts: tuple[float, ...]


LegEnumerator = Callable[[str, str, float], Iterable[LegQuote]]


def best_leg(
    token_in: str,
    token_out: str,
    amount_in: float,
    *,
    quote_legs: LegEnumerator,
) -> LegQuote | None:
    """Choose the highest-output leg from a deterministically ordered candidate set."""
    best: LegQuote | None = None
    for candidate in quote_legs(token_in, token_out, amount_in):
        if best is None or candidate.amount_out > best.amount_out:
            best = candidate
    return best


def as_direct_path(quote: LegQuote) -> PathQuote:
    return PathQuote(
        amount_out=quote.amount_out,
        vehicle=None,
        venues=(quote.venue,),
        pools=(quote.pool,),
        price_impacts=(quote.price_impact,),
    )


def best_vehicle_path(
    token_in: str,
    token_out: str,
    vehicle: str,
    amount_in: float,
    *,
    quote_legs: LegEnumerator,
) -> PathQuote | None:
    """Return the best sequential two-leg quote through one fixed vehicle.

    Every first-leg candidate is retained until the second leg is quoted. Taking
    only the highest-output first leg is invalid under a finite-size support gate:
    its larger intermediate amount can make every second-leg pool inadmissible
    while a slightly smaller first-leg output still completes the path.
    """
    if vehicle in (token_in, token_out):
        return None
    best: PathQuote | None = None
    for first in quote_legs(token_in, vehicle, amount_in):
        for second in quote_legs(vehicle, token_out, first.amount_out):
            candidate = PathQuote(
                amount_out=second.amount_out,
                vehicle=vehicle,
                venues=(first.venue, second.venue),
                pools=(first.pool, second.pool),
                price_impacts=(first.price_impact, second.price_impact),
            )
            if best is None or candidate.amount_out > best.amount_out:
                best = candidate
    return best


def best_public_path(
    token_in: str,
    token_out: str,
    vehicles: Iterable[str],
    amount_in: float,
    *,
    quote_legs: LegEnumerator,
) -> PathQuote | None:
    """Return the best direct or prespecified one-vehicle path."""
    direct = best_leg(token_in, token_out, amount_in, quote_legs=quote_legs)
    best = as_direct_path(direct) if direct is not None else None
    for vehicle in sorted(set(vehicles)):
        candidate = best_vehicle_path(
            token_in,
            token_out,
            vehicle,
            amount_in,
            quote_legs=quote_legs,
        )
        if candidate is not None and (
            best is None or candidate.amount_out > best.amount_out
        ):
            best = candidate
    return best

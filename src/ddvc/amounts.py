"""Exact token-amount conversions shared by ingestion and pricing code."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def human_to_raw(value: object, decimals: int) -> str | None:
    """Convert a human-unit decimal to an exact base-unit integer string."""
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or decimals < 0:
        return None
    sign, digits, exponent = parsed.as_tuple()
    coefficient = int("".join(str(digit) for digit in digits)) if digits else 0
    power = int(exponent) + decimals
    if power >= 0:
        integer = coefficient * 10**power
    else:
        integer, remainder = divmod(coefficient, 10 ** (-power))
        if remainder:
            return None
    return str(-integer if sign else integer)

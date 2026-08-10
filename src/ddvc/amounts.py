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


def raw_to_human(value: int, decimals: int) -> str:
    """Render an integer base-unit amount as an exact human-unit decimal."""

    if decimals < 0:
        raise ValueError("token decimals cannot be negative")
    parsed = int(value)
    sign = "-" if parsed < 0 else ""
    digits = str(abs(parsed)).rjust(decimals + 1, "0")
    if decimals == 0:
        return sign + digits
    whole, fraction = digits[:-decimals], digits[-decimals:]
    return sign + whole + "." + fraction.rstrip("0") if fraction.rstrip("0") else sign + whole

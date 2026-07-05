"""Constant-product exact-input quotes for V2-style AMM pools."""

from __future__ import annotations


DEFAULT_FEE_BPS = 30


def quote_exact_input_float(
    amount_in: float,
    reserve_in: float,
    reserve_out: float,
    *,
    fee_bps: int = DEFAULT_FEE_BPS,
) -> float:
    """Exact-input constant-product quote in human token units."""
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0.0
    amount_in_with_fee = amount_in * (10_000 - fee_bps) / 10_000
    return amount_in_with_fee * reserve_out / (reserve_in + amount_in_with_fee)

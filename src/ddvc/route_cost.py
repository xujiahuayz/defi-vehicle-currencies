"""Canonical route-cost construction and validation contracts."""

from __future__ import annotations


# Realised input/reserve ratios are 0.0034 at the median, 0.0329 at p90,
# 0.0541 at p95, and 0.1486 at p99 over 932,270 physically admissible swaps.
# The 5% ceiling is the rounded-down p95 support boundary.  It is imposed ex ante
# on each leg, never on the direct-versus-vehicle outcome.  For venue designs
# without a comparable reserve ratio, the same ceiling applies to the leg's own
# price impact against its marginal quote.
SUPPORT_QUANTILE = 0.95
MAX_INPUT_TO_RESERVE = 0.05
MAX_PRICE_IMPACT = 0.05

# A quote panel must contain no more than one observation per economic cell.
QUOTE_CELL_KEYS = (
    "date",
    "reserve_hour_utc",
    "src",
    "tgt",
    "vehicle",
    "trade_size_usd",
)

"""Canonical venue families used in cross-venue robustness checks."""

from __future__ import annotations


# Each venue in this family prices locally on an x*y invariant, including concentrated
# liquidity inside an active tick. Curve is separate. Balancer is also separate because
# the raw source mixes weighted and stable-pool families and cannot be labelled as one.
CONSTANT_PRODUCT_VENUES = frozenset(
    {
        "uniswap_v1",
        "uniswap_v2",
        "sushiswap_v2",
        "sushiswap_v3",
        "uniswap_v3",
        "uniswap_v4",
    }
)

VENUE_ROBUSTNESS_SCOPES: tuple[tuple[str, frozenset[str] | None], ...] = (
    ("all_venues", None),
    ("constant_product_only", CONSTANT_PRODUCT_VENUES),
    ("curve_only", frozenset({"curve"})),
    ("balancer_only", frozenset({"balancer"})),
)

"""Canonical dated public routing-technology releases and calendar regimes."""

from __future__ import annotations

import re

ROUTING_TECHNOLOGY_EVENTS = (
    ("auto_router_v1", "2021-09-16", "https://blog.uniswap.org/auto-router"),
    ("cross_version_auto_router", "2021-12-16", "https://blog.uniswap.org/SuperiorReturnsForLiquidityProviders.pdf"),
    ("universal_router", "2022-11-17", "https://blog.uniswap.org/permit2-and-universal-router"),
)

ROUTING_ERA_NAMES = (
    "pre_auto_router",
    "auto_router_v1",
    "cross_version_router",
    "universal_router_era",
)
ROUTING_ERA_CUTOFFS = tuple(
    (event_date, era, source)
    for (_event, event_date, source), era in zip(
        ROUTING_TECHNOLOGY_EVENTS,
        ROUTING_ERA_NAMES[1:],
        strict=True,
    )
)


def routing_era_for_date(date_text: object) -> str:
    """Classify an ISO calendar date using the canonical public-release cutoffs."""

    value = str(date_text)
    if value < ROUTING_ERA_CUTOFFS[0][0]:
        return ROUTING_ERA_NAMES[0]
    if value < ROUTING_ERA_CUTOFFS[1][0]:
        return ROUTING_ERA_NAMES[1]
    if value < ROUTING_ERA_CUTOFFS[2][0]:
        return ROUTING_ERA_NAMES[2]
    return ROUTING_ERA_NAMES[3]


def routing_era_case_sql(date_column: str = "date") -> str:
    """Render the canonical regime classifier for one trusted SQL identifier."""

    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", date_column) is None:
        raise ValueError("routing-era SQL date column must be one identifier")
    conditions = " ".join(
        f"WHEN {date_column} < '{event_date}' THEN '{prior_era}'"
        for (event_date, _new_era, _source), prior_era in zip(
            ROUTING_ERA_CUTOFFS,
            ROUTING_ERA_NAMES[:-1],
            strict=True,
        )
    )
    return f"CASE {conditions} ELSE '{ROUTING_ERA_NAMES[-1]}' END"

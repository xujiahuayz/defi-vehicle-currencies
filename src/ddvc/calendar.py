"""Canonical sampling calendars shared by empirical instruments."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime


def nearest_day_per_month(
    days: Iterable[str], *, target_day: int = 15
) -> list[str]:
    """One daily audit snapshot per month, nearest target and earlier on ties."""
    if not 1 <= target_day <= 31:
        raise ValueError("target_day must be between 1 and 31")
    parsed = sorted(
        {
            (datetime.strptime(str(day), "%Y%m%d"), str(day))
            for day in days
        }
    )
    by_month: dict[tuple[int, int], list[tuple[datetime, str]]] = {}
    for observed, stamp in parsed:
        by_month.setdefault((observed.year, observed.month), []).append(
            (observed, stamp)
        )
    return [
        min(
            observations,
            key=lambda row: (abs(row[0].day - target_day), row[0]),
        )[1]
        for _month, observations in sorted(by_month.items())
    ]

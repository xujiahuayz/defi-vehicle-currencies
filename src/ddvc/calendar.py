"""Canonical sampling calendars shared by empirical instruments."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta


RESEARCH_SAMPLE_START = "20200211"
RESEARCH_SAMPLE_END = "20260630"


def calendar_days(start: str, end: str) -> list[str]:
    """Every inclusive UTC calendar day between two YYYYMMDD stamps."""
    first = datetime.strptime(str(start).replace("-", ""), "%Y%m%d")
    last = datetime.strptime(str(end).replace("-", ""), "%Y%m%d")
    if first > last:
        raise ValueError("calendar start must not follow end")
    return [
        (first + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range((last - first).days + 1)
    ]


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

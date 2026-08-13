"""Canonical sampling calendars shared by empirical instruments."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone


RESEARCH_SAMPLE_START = "20200211"
RESEARCH_SAMPLE_END = "20260630"
UNISWAP_V3_ERA_START = "20210505"

# V1 predates the research sample: its own genesis, not a second sample end.
V1_GENESIS_START = "20181102"


def day_stamp(day: str | date | datetime) -> str:
    """Normalise any accepted day spelling to a YYYYMMDD stamp."""
    if isinstance(day, datetime):
        return day.strftime("%Y%m%d")
    if isinstance(day, date):
        return day.strftime("%Y%m%d")
    return datetime.strptime(str(day).replace("-", ""), "%Y%m%d").strftime("%Y%m%d")


def day_date(day: str | date | datetime) -> date:
    """The calendar date for any accepted day spelling."""
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    return datetime.strptime(str(day).replace("-", ""), "%Y%m%d").date()


def day_iso(day: str | date | datetime) -> str:
    """The ISO `YYYY-MM-DD` spelling for any accepted day."""
    return day_date(day).isoformat()


def sample_end_date() -> date:
    """Last inclusive day of the research sample."""
    return day_date(RESEARCH_SAMPLE_END)


def sample_end_iso() -> str:
    """Last inclusive day of the research sample, as `YYYY-MM-DD`."""
    return sample_end_date().isoformat()


def sample_end_exclusive_date() -> date:
    """The exclusive upper bound: the day after the sample's last day."""
    return sample_end_date() + timedelta(days=1)


def sample_end_exclusive_iso() -> str:
    """Exclusive upper bound as `YYYY-MM-DD`, for `start <= d < end` filters."""
    return sample_end_exclusive_date().isoformat()


def sample_end_exclusive_stamp() -> str:
    """Exclusive upper bound as a YYYYMMDD stamp."""
    return sample_end_exclusive_date().strftime("%Y%m%d")


def sample_end_utc_exclusive() -> int:
    """Exclusive upper bound as a UTC epoch-second boundary."""
    bound = sample_end_exclusive_date()
    return int(datetime(bound.year, bound.month, bound.day, tzinfo=timezone.utc).timestamp())


def sample_start_date() -> date:
    """First inclusive day of the research sample."""
    return day_date(RESEARCH_SAMPLE_START)


def sample_start_iso() -> str:
    """First inclusive day of the research sample, as `YYYY-MM-DD`."""
    return sample_start_date().isoformat()


def uniswap_v3_era(day: str) -> str:
    """Return the canonical pre/post launch era for one UTC calendar day."""

    normalized = str(day).replace("-", "")
    datetime.strptime(normalized, "%Y%m%d")
    return "pre_uniswap_v3" if normalized < UNISWAP_V3_ERA_START else "post_uniswap_v3"


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

"""Calendar views derived from a released canonical quality ledger."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ddvc.calendar import nearest_day_per_month


def released_route_days(
    quality_panel: str | Path, *, nonempty: bool
) -> list[str]:
    """Return the exact released calendar or its identified non-empty subset."""
    quality = pd.read_parquet(
        quality_panel, columns=["day", "output_rows", "passed"]
    )
    if quality["day"].duplicated().any():
        raise RuntimeError("route quality ledger contains duplicate days")
    if not quality["passed"].all():
        failed = int((~quality["passed"]).sum())
        raise RuntimeError(f"route quality ledger contains {failed:,} failed day(s)")
    if nonempty:
        quality = quality[quality["output_rows"].gt(0)]
    return sorted(quality["day"].astype(str).tolist())


def select_transaction_frontier_audit_days(days: list[str]) -> list[str]:
    """Select the one canonical construction-audit calendar from released days."""

    days = nearest_day_per_month(sorted(set(days)))
    if not days:
        raise RuntimeError("transaction-frontier audit calendar is empty")
    return days


def transaction_frontier_audit_days(quality_panel: str | Path) -> list[str]:
    """Load the released perimeter and return its canonical audit dates."""

    return select_transaction_frontier_audit_days(
        released_route_days(quality_panel, nonempty=True)
    )

"""Canonical V4 pool-static quarantine contract for materialised market state."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from ddvc.paths import DATA_DIR
from ddvc.provenance import require_current_artifacts


V4_STATIC_QUARANTINE_PANEL = (
    DATA_DIR / "processed" / "v4_pool_static_quarantine.parquet"
)
V4_STATIC_QUARANTINE_COLUMNS = [
    "pool",
    "swap_rows",
    "static_variants",
    "first_day",
    "last_day",
]


def audit_v4_pool_static_conflicts(paths: Iterable[str | Path]) -> pd.DataFrame:
    """Find V4 pools whose provider-supplied immutable quote statics drift."""
    import duckdb

    perimeter = sorted(str(Path(path)) for path in paths)
    if not perimeter:
        raise ValueError("V4 static audit requires a nonempty partition perimeter")
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            """
            SELECT
                pool,
                count(*) AS swap_rows,
                count(DISTINCT (
                    token0_raw,
                    token1_raw,
                    decimals0,
                    decimals1,
                    fee_pips,
                    tick_spacing,
                    hooks
                )) AS static_variants,
                min(day) AS first_day,
                max(day) AS last_day
            FROM read_parquet(?, union_by_name=true)
            WHERE
                record_type = 'swap'
                AND usable
                AND token0_raw IS NOT NULL
                AND token1_raw IS NOT NULL
                AND decimals0 IS NOT NULL
                AND decimals1 IS NOT NULL
                AND fee_pips IS NOT NULL
                AND tick_spacing IS NOT NULL
                AND hooks IS NOT NULL
            GROUP BY pool
            HAVING static_variants > 1
            ORDER BY swap_rows DESC, pool
            """,
            [perimeter],
        ).fetchall()
    finally:
        connection.close()
    return pd.DataFrame(rows, columns=V4_STATIC_QUARANTINE_COLUMNS)


def load_v4_static_quarantine(
    path: str | Path = V4_STATIC_QUARANTINE_PANEL,
) -> set[str]:
    """Load the complete pool-level exclusion set released with canonical D2."""
    panel = Path(path)
    require_current_artifacts([panel], consumer="V4 static quarantine")
    frame = pd.read_parquet(panel)
    if list(frame.columns) != V4_STATIC_QUARANTINE_COLUMNS:
        raise RuntimeError("node D V4 static-quarantine schema is stale")
    pools = frame["pool"].astype(str).str.lower()
    if pools.duplicated().any() or pools.eq("").any():
        raise RuntimeError("node D V4 static quarantine contains invalid pool identities")
    return set(pools)

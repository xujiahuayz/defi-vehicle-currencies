"""Out-of-core summary for the route-cost counterfactual panel."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from scipy import stats

from ddvc.runtime import atomic_output


REQUIRED_COLUMNS = {
    "vehicle_sym",
    "trade_size_usd",
    "vehicle_available",
    "direct_available",
    "direct_cost_advantage",
    "realized_bridge_volume_usd",
}


def summarize_route_cost_panel(path: Path) -> pd.DataFrame:
    """Aggregate a large Parquet panel without materialising its rows in pandas."""
    import duckdb
    import pyarrow.parquet as pq

    missing = sorted(REQUIRED_COLUMNS - set(pq.ParquetFile(path).schema.names))
    if missing:
        raise ValueError(f"route-cost summary is missing columns: {', '.join(missing)}")
    connection = duckdb.connect()
    try:
        summary = connection.execute(
            """
            WITH marked AS (
                SELECT vehicle_sym,
                       trade_size_usd,
                       vehicle_available,
                       direct_available,
                       direct_cost_advantage,
                       realized_bridge_volume_usd,
                       vehicle_available AND direct_available
                         AND direct_cost_advantage IS NOT NULL
                         AND isfinite(direct_cost_advantage) AS both_available,
                       least(greatest(direct_cost_advantage, -10.0), 10.0) AS winsor_advantage
                FROM read_parquet(?)
                WHERE vehicle_sym IS NOT NULL AND trade_size_usd IS NOT NULL
            )
            SELECT vehicle_sym AS vehicle,
                   trade_size_usd,
                   count(*) AS rows,
                   avg(CAST(vehicle_available AS DOUBLE)) AS vehicle_available_share,
                   avg(CAST(direct_available AS DOUBLE)) AS direct_available_share,
                   count(*) FILTER (WHERE both_available) AS both_available_rows,
                   avg(CAST(direct_cost_advantage < 0 AS DOUBLE))
                     FILTER (WHERE both_available) AS vehicle_beats_direct_share,
                   quantile_cont(direct_cost_advantage, 0.5)
                     FILTER (WHERE both_available) AS direct_cost_advantage_median,
                   quantile_cont(direct_cost_advantage, 0.25)
                     FILTER (WHERE both_available) AS direct_cost_advantage_p25,
                   quantile_cont(direct_cost_advantage, 0.75)
                     FILTER (WHERE both_available) AS direct_cost_advantage_p75,
                   avg(winsor_advantage)
                     FILTER (WHERE both_available) AS direct_cost_advantage_winsor_mean,
                   stddev_samp(winsor_advantage)
                     FILTER (WHERE both_available) AS direct_cost_advantage_winsor_std,
                   count(*) FILTER (
                     WHERE vehicle_available AND NOT direct_available
                   ) AS no_direct_vehicle_available_rows,
                   coalesce(sum(realized_bridge_volume_usd)
                     FILTER (WHERE vehicle_available), 0.0) AS covered_realized_volume_usd
            FROM marked
            GROUP BY vehicle_sym, trade_size_usd
            ORDER BY trade_size_usd, vehicle_sym
            """,
            [str(path)],
        ).df()
    finally:
        connection.close()
    t_statistics = []
    p_values = []
    for row in summary.itertuples(index=False):
        n = int(row.both_available_rows)
        mean = float(row.direct_cost_advantage_winsor_mean)
        std = float(row.direct_cost_advantage_winsor_std)
        if n > 2 and math.isfinite(std) and std > 0:
            t_statistic = mean / (std / math.sqrt(n))
            p_value = 2 * stats.t.sf(abs(t_statistic), n - 1)
        else:
            t_statistic = p_value = math.nan
        t_statistics.append(t_statistic)
        p_values.append(p_value)
    summary["t_winsor_mean"] = t_statistics
    summary["p_winsor_mean"] = p_values
    return summary.drop(columns=["direct_cost_advantage_winsor_std"])


def write_route_cost_summary(panel_path: Path, summary_path: Path) -> pd.DataFrame:
    """Build and atomically install the canonical route-cost summary."""
    summary = summarize_route_cost_panel(panel_path)
    with atomic_output(summary_path) as temporary:
        summary.to_pickle(temporary)
    return summary

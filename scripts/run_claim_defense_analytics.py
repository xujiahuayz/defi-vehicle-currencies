#!/usr/bin/env python3
"""Additional claim-defense analytics before manuscript drafting.

This script intentionally stays close to already-built panels:
1. stress event-window sensitivity and placebo dates;
2. P1 route-cost decomposition into availability, thin-direct, and common support.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ddvc.analysis.dynamics import exact_daily_log_return

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
OUT = ROOT / "output"
EMP = OUT / "empirical"

from ddvc.paper_tables import _int, _num, _p, _pct, _write_table


ROUTE_COST_REQUIRED_COLUMNS = {
    "date",
    "src",
    "tgt",
    "vehicle_sym",
    "trade_size_usd",
    "direct_output_usd",
    "direct_available",
    "vehicle_available",
    "direct_cost_advantage",
}
ROUTE_COST_MEMORY_LIMIT = "900MB"

ROUTE_COST_DECOMPOSITION_QUERY = """
WITH weth AS NOT MATERIALIZED (
    SELECT date,
           src,
           tgt,
           trade_size_usd,
           direct_output_usd,
           direct_available,
           vehicle_available,
           direct_cost_advantage,
           direct_output_usd / trade_size_usd AS direct_quality
    FROM read_parquet(?)
    WHERE vehicle_sym = 'WETH'
      AND trade_size_usd IS NOT NULL
      AND isfinite(trade_size_usd)
      AND trade_size_usd > 0
),
row_summary AS (
    SELECT trade_size_usd,
           count(*) AS rows,
           avg(CAST(direct_available AS DOUBLE)) AS direct_available_share,
           avg(CAST(vehicle_available AS DOUBLE)) AS vehicle_available_share,
           count(*) FILTER (
               WHERE NOT direct_available AND vehicle_available
           ) AS no_direct_vehicle_available_rows,
           count(*) FILTER (
               WHERE direct_available
                 AND vehicle_available
                 AND direct_cost_advantage IS NOT NULL
                 AND isfinite(direct_cost_advantage)
           ) AS common_support_rows,
           median(direct_cost_advantage) FILTER (
               WHERE direct_available
                 AND vehicle_available
                 AND direct_cost_advantage IS NOT NULL
                 AND isfinite(direct_cost_advantage)
           ) AS common_support_median,
           median(direct_cost_advantage) FILTER (
               WHERE direct_available
                 AND vehicle_available
                 AND direct_cost_advantage IS NOT NULL
                 AND isfinite(direct_cost_advantage)
                 AND direct_output_usd IS NOT NULL
                 AND isfinite(direct_output_usd)
                 AND isfinite(direct_quality)
                 AND direct_quality < 0.90
           ) AS thin_direct_median,
           median(direct_cost_advantage) FILTER (
               WHERE direct_available
                 AND vehicle_available
                 AND direct_cost_advantage IS NOT NULL
                 AND isfinite(direct_cost_advantage)
                 AND direct_output_usd IS NOT NULL
                 AND isfinite(direct_output_usd)
                 AND isfinite(direct_quality)
                 AND direct_quality >= 0.90
           ) AS high_quality_direct_median,
           count(*) FILTER (
               WHERE (direct_output_usd IS NOT NULL AND NOT isfinite(direct_output_usd))
                  OR (direct_cost_advantage IS NOT NULL AND NOT isfinite(direct_cost_advantage))
           ) AS nonfinite_quote_rows,
           count(*) FILTER (
               WHERE direct_available
                 AND direct_output_usd IS NOT NULL
                 AND isfinite(direct_output_usd)
                 AND direct_output_usd <= 0
           ) AS impossible_quote_rows
    FROM weth
    GROUP BY trade_size_usd
),
pair_day AS (
    SELECT trade_size_usd,
           date,
           src,
           tgt,
           avg(direct_cost_advantage) AS pair_day_mean
    FROM weth
    WHERE direct_available
      AND vehicle_available
      AND direct_cost_advantage IS NOT NULL
      AND isfinite(direct_cost_advantage)
    GROUP BY trade_size_usd, date, src, tgt
),
pair_day_clipped AS (
    SELECT trade_size_usd,
           CASE
               WHEN pair_day_mean < -10.0 THEN -10.0
               WHEN pair_day_mean > 10.0 THEN 10.0
               ELSE pair_day_mean
           END AS pair_day_mean_clipped
    FROM pair_day
),
pair_summary AS (
    SELECT trade_size_usd,
           count(*) AS pair_days,
           avg(pair_day_mean_clipped) AS pair_day_mean,
           stddev_samp(pair_day_mean_clipped) AS pair_day_stddev,
           min(pair_day_mean_clipped) AS pair_day_min,
           max(pair_day_mean_clipped) AS pair_day_max
    FROM pair_day_clipped
    GROUP BY trade_size_usd
)
SELECT row_summary.*,
       coalesce(pair_summary.pair_days, 0) AS pair_days,
       pair_summary.pair_day_mean,
       pair_summary.pair_day_stddev,
       pair_summary.pair_day_min,
       pair_summary.pair_day_max
FROM row_summary
LEFT JOIN pair_summary USING (trade_size_usd)
ORDER BY trade_size_usd
"""

ROUTE_COST_TRADE_SIZE_VALIDATION_QUERY = """
SELECT count(*) FILTER (WHERE trade_size_usd IS NULL) AS null_rows,
       count(*) FILTER (
           WHERE trade_size_usd IS NOT NULL AND NOT isfinite(trade_size_usd)
       ) AS nonfinite_rows,
       count(*) FILTER (
           WHERE trade_size_usd IS NOT NULL
             AND isfinite(trade_size_usd)
             AND trade_size_usd <= 0
       ) AS nonpositive_rows
FROM read_parquet(?)
WHERE vehicle_sym = 'WETH'
"""


def _pair_day_ttest(
    *, n: int, mean: float, standard_deviation: float, minimum: float, maximum: float
) -> tuple[float, float]:
    """Return the one-sample pair-day t-test with explicit degenerate semantics.

    Fewer than three observations and an exact all-zero sample are undefined. An exact
    constant nonzero sample has a signed infinite t statistic and a zero p-value. Exact
    minimum/maximum equality identifies constants before floating variance noise can.
    """
    values = (mean, minimum, maximum)
    if n <= 2 or any(not math.isfinite(value) for value in values):
        return math.nan, math.nan
    if minimum == maximum:
        if mean == 0:
            return math.nan, math.nan
        return math.copysign(math.inf, mean), 0.0
    if not math.isfinite(standard_deviation) or standard_deviation <= 0:
        raise ValueError(
            "nonconstant pair-day differences require a positive finite standard deviation"
        )
    statistic = mean / (standard_deviation / math.sqrt(n))
    return statistic, float(2 * stats.t.sf(abs(statistic), n - 1))


def _load_module(name: str, file: str):
    path = SCRIPTS / file
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stress_window_and_placebo() -> pd.DataFrame:
    weekly = _load_module("stress_weekly", "run_stress_weekly_common_support.py")
    empirical = _load_module("dvc_empirical", "run_empirical_proposition_tests.py")
    bridge = pd.read_parquet(DATA / "empirical" / "bridge_daily.parquet", columns=["date", "weth_price"])
    px = bridge.dropna().drop_duplicates("date").sort_values("date").copy()
    px["date"] = pd.to_datetime(px["date"])
    px["weth_ret"] = exact_daily_log_return(px, "weth_price")
    px.loc[px["weth_ret"].abs() > 0.5, "weth_ret"] = np.nan
    px["downside_stress"] = (-px["weth_ret"]).clip(lower=0)

    events = (
        px[px["downside_stress"].ge(0.08)]
        .nlargest(20, "downside_stress")
        [["date", "downside_stress"]]
        .copy()
    )
    placebo = events.copy()
    placebo["date"] = placebo["date"] - pd.Timedelta(days=60)
    placebo = placebo.merge(
        px[["date", "downside_stress"]].rename(columns={"downside_stress": "placebo_stress"}),
        on="date",
        how="inner",
    )
    placebo = placebo[placebo["placebo_stress"].lt(0.02)].head(len(events))

    all_dates: set[str] = set()
    for d in pd.concat([events["date"], placebo["date"]], ignore_index=True):
        for b in range(1, 29):
            all_dates.add(weekly._stamp(d - pd.Timedelta(days=b)))
        for k in range(7):
            all_dates.add(weekly._stamp(d + pd.Timedelta(days=k)))
    panel = weekly._build_panel(all_dates, empirical)

    rows = []
    for sample_name, event_frame in [("stress", events), ("placebo", placebo.rename(columns={"placebo_stress": "downside_stress"}))]:
        for event_days in [1, 2, 3, 7]:
            effects = []
            n_pairs = []
            for ev in event_frame.itertuples(index=False):
                d = pd.Timestamp(ev.date)
                event = weekly._window_gap(panel, d, event_days).rename(
                    columns={"gap": "event_gap", "total": "event_total", "days": "event_days_seen"}
                )
                base = weekly._window_gap(panel, d - pd.Timedelta(days=28), 28).rename(
                    columns={"gap": "baseline_gap", "total": "baseline_total", "days": "baseline_days_seen"}
                )
                comp = event.merge(base, on="pair", how="inner")
                comp = comp[comp["baseline_days_seen"].ge(7)]
                if comp.empty:
                    continue
                comp["effect"] = comp["event_gap"] - comp["baseline_gap"]
                effects.append(float(np.average(comp["effect"], weights=comp["event_total"].clip(lower=1e-9))))
                n_pairs.append(len(comp))
            arr = np.array(effects, dtype=float)
            t, p = stats.ttest_1samp(arr, 0.0) if len(arr) > 2 else (math.nan, math.nan)
            rows.append({
                "Sample": sample_name,
                "Event window": f"{event_days} day" if event_days == 1 else f"{event_days} days",
                "Events": _int(len(arr)),
                "Mean pairs": _int(np.mean(n_pairs) if n_pairs else math.nan),
                "Effect (pp)": _num(100 * arr.mean(), 2) if len(arr) else "",
                "SE (pp)": _num(100 * stats.sem(arr), 2) if len(arr) > 1 else "",
                "t": _num(t, 2),
                "p": _p(p),
                "Negative share (%)": _pct(float(np.mean(arr < 0)) if len(arr) else math.nan),
            })
    out = pd.DataFrame(rows)
    out.to_pickle(EMP / "stress_window_placebo.pkl")
    _write_table(
        out,
        "table_r11_stress_window_placebo",
        "Stress-rotation event-window and placebo checks.",
        "tab:stress-window-placebo",
        note=(
            "Effects are WETH-minus-stable BridgeShare changes within common endpoint-pair "
            "sets relative to the prior 28 days. Placebo dates move each stress event 60 "
            "days earlier and keep only low-stress placebo dates."
        ),
    )
    return out


def route_cost_decomposition(
    panel_path: Path | None = None, *, write_outputs: bool = True
) -> pd.DataFrame:
    import duckdb
    import pyarrow.parquet as pq

    panel_path = panel_path or DATA / "empirical" / "route_cost_panel_v2.parquet"
    missing = sorted(ROUTE_COST_REQUIRED_COLUMNS - set(pq.ParquetFile(panel_path).schema.names))
    if missing:
        raise ValueError(f"route-cost decomposition is missing columns: {', '.join(missing)}")
    connection = duckdb.connect()
    try:
        connection.execute(f"SET memory_limit = '{ROUTE_COST_MEMORY_LIMIT}'")
        connection.execute("SET preserve_insertion_order = false")
        invalid_trade_sizes = connection.execute(
            ROUTE_COST_TRADE_SIZE_VALIDATION_QUERY, [str(panel_path)]
        ).fetchone()
        invalid_names = ("null", "nonfinite", "nonpositive")
        invalid_counts = dict(zip(invalid_names, map(int, invalid_trade_sizes), strict=True))
        if sum(invalid_counts.values()):
            details = ", ".join(
                f"{name}={count}" for name, count in invalid_counts.items()
            )
            raise ValueError(
                "route-cost decomposition requires positive finite WETH "
                f"trade_size_usd values; invalid rows: {details}"
            )
        numeric = connection.execute(
            ROUTE_COST_DECOMPOSITION_QUERY, [str(panel_path)]
        ).to_arrow_table().to_pandas()
    finally:
        connection.close()
    rows = []
    for result in numeric.itertuples(index=False):
        n = int(result.pair_days)
        mean = float(result.pair_day_mean) if pd.notna(result.pair_day_mean) else math.nan
        standard_deviation = (
            float(result.pair_day_stddev)
            if pd.notna(result.pair_day_stddev)
            else math.nan
        )
        minimum = float(result.pair_day_min) if pd.notna(result.pair_day_min) else math.nan
        maximum = float(result.pair_day_max) if pd.notna(result.pair_day_max) else math.nan
        t, p = _pair_day_ttest(
            n=n,
            mean=mean,
            standard_deviation=standard_deviation,
            minimum=minimum,
            maximum=maximum,
        )
        rows.append({
            "Trade size": f"${int(result.trade_size_usd):,}",
            "Rows": _int(result.rows),
            "Direct available (%)": _pct(result.direct_available_share),
            "WETH route available (%)": _pct(result.vehicle_available_share),
            "No-direct, WETH-available rows": _int(result.no_direct_vehicle_available_rows),
            "Common-support rows": _int(result.common_support_rows),
            "Median common-support direct cost advantage (fraction)": _num(
                result.common_support_median, 4
            ),
            "Median thin-direct direct cost advantage (fraction)": _num(
                result.thin_direct_median, 4
            ),
            "Median high-quality-direct cost advantage (fraction)": _num(
                result.high_quality_direct_median, 4
            ),
            "Nonfinite quote rows": _int(result.nonfinite_quote_rows),
            "Impossible quote rows": _int(result.impossible_quote_rows),
            "Pair-day t": _num(t, 2),
            "p": _p(p),
        })
    out = pd.DataFrame(rows)
    if write_outputs:
        out.to_pickle(EMP / "route_cost_decomposition.pkl")
        _write_table(
            out,
            "table_r12_route_cost_decomposition",
            "Direct cost-advantage decomposition against WETH indirect routes.",
            "tab:route-cost-decomposition",
            note=(
                "The table separates route availability, missing-direct-route cases, thin-direct "
                "markets, and common-support price improvement. High-quality direct routes are "
                "rows where direct output is at least 90 percent of notional. Nonfinite and "
                "economically impossible quote rows are reported and excluded from statistics "
                "that require their affected quote fields. Exact constant nonzero pair-day "
                "differences imply an infinite t statistic and zero p-value; exact all-zero "
                "differences leave the t-test undefined."
            ),
        )
    return out


def main() -> int:
    stress_window_and_placebo()
    route_cost_decomposition()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Explore whether vehicle roles are made at market entry.

This is an exploratory mechanism exhibit, not a confirmatory claim. It consumes
the released endpoint-candidate pair-support ledger and asks whether newly
observed ultimate pairs keep the vehicle type they use at birth. The unit is an
ordered ultimate pair. Follow-up windows are complete: a pair enters a horizon
only when the sample end is at least that many days after its first observation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.analysis.regression import ols_clustered
from ddvc.asset_types import classify
from ddvc.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT
from ddvc.runtime import atomic_output


PAIR_SUPPORT = DATA_DIR / "processed/endpoint_candidate_pair_support.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/vehicle_formation_exploration.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/vehicle_formation_support.jsonl"
SAMPLE_END = pd.Timestamp("2026-06-30")
MAIN_ENTRY_YEARS = (2024, 2026)
HORIZONS = (30, 120)
ENTRY_TYPES = ("native_only_entry", "stable_present_entry", "stable_dominant_entry")


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _read_sql(query: str) -> pd.DataFrame:
    connection = duckdb.connect()
    try:
        return connection.execute(query).fetchdf()
    finally:
        connection.close()


def entry_cohorts(pair_support_path: Path = PAIR_SUPPORT) -> pd.DataFrame:
    """Summarise the first observed vehicle choice for every entering pair."""

    path = _sql_path(pair_support_path)
    years = ", ".join(str(year) for year in MAIN_ENTRY_YEARS)
    return _read_sql(
        f"""
        SELECT
            'entry_cohort' AS record_type,
            year(date)::INTEGER AS entry_year,
            count(*)::INTEGER AS pairs,
            sum(primary_choice_route_count)::DOUBLE AS primary_routes,
            sum(stable_choice_route_count)::DOUBLE AS stable_routes,
            sum(native_choice_route_count)::DOUBLE AS native_routes,
            sum(stable_choice_route_count)::DOUBLE
                / nullif(sum(primary_choice_route_count), 0) AS stable_share,
            avg((stable_choice_route_count > native_choice_route_count)::INTEGER)::DOUBLE
                AS stable_dominant_pair_share,
            avg((direct_route_count > 0)::INTEGER)::DOUBLE AS direct_available_share,
            min(date) AS entry_start,
            max(date) AS entry_end
        FROM read_parquet('{path}')
        WHERE pair_entry_on_day
          AND primary_choice_route_count > 0
          AND year(date) IN ({years})
          AND strftime(date, '%m-%d') <= '06-30'
        GROUP BY 1, 2
        ORDER BY 2
        """
    )


def endpoint_class(src: object, tgt: object) -> str:
    """Classify the endpoint pair for the mechanical WETH-eligibility split."""

    src_symbol, src_type = classify(src)
    tgt_symbol, tgt_type = classify(tgt)
    symbols = {src_symbol, tgt_symbol}
    types = {src_type, tgt_type}
    if "WETH" in symbols:
        return "weth_endpoint"
    if "stable" in types:
        return "stable_endpoint"
    if "native" in types:
        return "other_native_endpoint"
    return "other_endpoint"


def entry_endpoint_class_summary(pair_support_path: Path = PAIR_SUPPORT) -> pd.DataFrame:
    """Split entering pairs by endpoint class and add a non-WETH aggregate."""

    path = _sql_path(pair_support_path)
    years = ", ".join(str(year) for year in MAIN_ENTRY_YEARS)
    entries = _read_sql(
        f"""
        SELECT
            date,
            src,
            tgt,
            year(date)::INTEGER AS entry_year,
            primary_choice_route_count::DOUBLE AS primary_routes,
            stable_choice_route_count::DOUBLE AS stable_routes,
            native_choice_route_count::DOUBLE AS native_routes
        FROM read_parquet('{path}')
        WHERE pair_entry_on_day
          AND primary_choice_route_count > 0
          AND year(date) IN ({years})
          AND strftime(date, '%m-%d') <= '06-30'
        """
    )
    entries["endpoint_class"] = [
        endpoint_class(src, tgt) for src, tgt in zip(entries["src"], entries["tgt"])
    ]
    total_by_year = entries.groupby("entry_year")["primary_routes"].sum()
    rows: list[dict[str, object]] = []
    grouped = list(entries.groupby(["entry_year", "endpoint_class"], sort=True))
    non_weth = entries[~entries["endpoint_class"].eq("weth_endpoint")].copy()
    grouped.extend(
        (((int(year), "non_weth_endpoint"), group) for year, group in non_weth.groupby("entry_year", sort=True))
    )
    for (year, class_name), group in grouped:
        primary_routes = float(group["primary_routes"].sum())
        stable_routes = float(group["stable_routes"].sum())
        native_routes = float(group["native_routes"].sum())
        rows.append(
            {
                "record_type": "entry_endpoint_class",
                "entry_year": int(year),
                "endpoint_class": str(class_name),
                "pairs": int(len(group)),
                "primary_routes": primary_routes,
                "stable_routes": stable_routes,
                "native_routes": native_routes,
                "stable_share": stable_routes / primary_routes,
                "stable_dominant_pair_share": float(
                    (group["stable_routes"] > group["native_routes"]).mean()
                ),
                "route_mass_share": primary_routes / float(total_by_year.loc[year]),
                "interpretation": "exploratory_endpoint_class_split_not_causal",
            }
        )
    return pd.DataFrame(rows)


def entry_follow_panel(
    horizon_days: int,
    *,
    pair_support_path: Path = PAIR_SUPPORT,
    sample_end: pd.Timestamp = SAMPLE_END,
) -> pd.DataFrame:
    """Return pair-level follow-up rows for one complete horizon."""

    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    path = _sql_path(pair_support_path)
    years = ", ".join(str(year) for year in MAIN_ENTRY_YEARS)
    sample_end_text = pd.Timestamp(sample_end).strftime("%Y-%m-%d")
    return _read_sql(
        f"""
        WITH entries AS (
            SELECT
                src,
                tgt,
                date AS entry_date,
                year(date)::INTEGER AS entry_year,
                primary_choice_route_count::DOUBLE AS entry_primary_routes,
                stable_choice_route_count::DOUBLE AS entry_stable_routes,
                native_choice_route_count::DOUBLE AS entry_native_routes,
                stable_choice_route_count::DOUBLE
                    / nullif(primary_choice_route_count, 0) AS entry_stable_share,
                CASE
                    WHEN stable_choice_route_count > native_choice_route_count
                        THEN 'stable_dominant_entry'
                    WHEN stable_choice_route_count > 0
                        THEN 'stable_present_entry'
                    ELSE 'native_only_entry'
                END AS entry_type
            FROM read_parquet('{path}')
            WHERE pair_entry_on_day
              AND primary_choice_route_count > 0
              AND year(date) IN ({years})
              AND strftime(date, '%m-%d') <= '06-30'
              AND date + INTERVAL {int(horizon_days)} DAY <= DATE '{sample_end_text}'
        ),
        follow AS (
            SELECT
                e.entry_year,
                e.entry_date,
                e.entry_type,
                e.src,
                e.tgt,
                e.entry_primary_routes,
                e.entry_stable_routes,
                e.entry_native_routes,
                e.entry_stable_share,
                sum(p.primary_choice_route_count)::DOUBLE AS primary_routes,
                sum(p.stable_choice_route_count)::DOUBLE AS stable_routes,
                sum(p.native_choice_route_count)::DOUBLE AS native_routes,
                count(*)::INTEGER AS observed_days
            FROM entries e
            JOIN read_parquet('{path}') p
              ON p.src = e.src
             AND p.tgt = e.tgt
             AND p.date BETWEEN e.entry_date
                            AND e.entry_date + INTERVAL {int(horizon_days)} DAY
            GROUP BY 1,2,3,4,5,6,7,8,9
        )
        SELECT
            {int(horizon_days)}::INTEGER AS horizon_days,
            *,
            stable_routes / nullif(primary_routes, 0) AS stable_share,
            (stable_routes > native_routes)::BOOLEAN AS stable_dominant_followup
        FROM follow
        WHERE primary_routes > 0
        ORDER BY entry_year, entry_type, src, tgt
        """
    )


def persistence_summary(follow: pd.DataFrame) -> pd.DataFrame:
    """Summarise follow-up vehicle use by entry type and cohort."""

    required = {
        "horizon_days",
        "entry_year",
        "entry_type",
        "primary_routes",
        "stable_routes",
        "native_routes",
        "observed_days",
        "stable_dominant_followup",
    }
    missing = sorted(required - set(follow.columns))
    if missing:
        raise ValueError(f"entry follow panel lacks columns: {missing}")
    rows: list[dict[str, object]] = []
    for (horizon, year, entry_type), group in follow.groupby(
        ["horizon_days", "entry_year", "entry_type"], sort=True
    ):
        primary_routes = float(group["primary_routes"].sum())
        if primary_routes <= 0:
            continue
        rows.append(
            {
                "record_type": "entry_persistence",
                "horizon_days": int(horizon),
                "entry_year": int(year),
                "entry_type": str(entry_type),
                "pairs": int(len(group)),
                "primary_routes": primary_routes,
                "stable_routes": float(group["stable_routes"].sum()),
                "native_routes": float(group["native_routes"].sum()),
                "stable_share": float(group["stable_routes"].sum() / primary_routes),
                "stable_dominant_pair_share": float(
                    group["stable_dominant_followup"].astype(float).mean()
                ),
                "mean_observed_days": float(group["observed_days"].mean()),
            }
        )
    return pd.DataFrame(rows)


def persistence_contrasts(follow: pd.DataFrame) -> pd.DataFrame:
    """Estimate the follow-up stable-share gap between stable and native births."""

    rows: list[dict[str, object]] = []
    retained = follow[
        follow["entry_type"].isin(("native_only_entry", "stable_dominant_entry"))
    ].copy()
    retained["stable_dominant_entry"] = retained["entry_type"].eq(
        "stable_dominant_entry"
    ).astype(float)
    for (horizon, year), group in retained.groupby(
        ["horizon_days", "entry_year"], sort=True
    ):
        if group["entry_type"].nunique() != 2:
            continue
        weighted_means = {}
        for entry_type, subgroup in group.groupby("entry_type", sort=False):
            weights = subgroup["primary_routes"].astype(float)
            weighted_means[str(entry_type)] = float(
                np.average(subgroup["stable_share"].astype(float), weights=weights)
            )
        coefficient = (
            weighted_means["stable_dominant_entry"]
            - weighted_means["native_only_entry"]
        )
        fit = ols_clustered(
            group["stable_share"],
            group[["stable_dominant_entry"]],
            group["entry_date"],
            weights=group["primary_routes"],
            min_observations=2,
            min_clusters=2,
        )
        standard_error = float(fit.standard_errors[1])
        rows.append(
            {
                "record_type": "entry_persistence_contrast",
                "horizon_days": int(horizon),
                "entry_year": int(year),
                "coefficient": coefficient,
                "coefficient_pp": 100.0 * coefficient,
                "standard_error": standard_error,
                "standard_error_pp": 100.0 * standard_error,
                "t_statistic": float(fit.t_statistics[1]),
                "p_value": float(fit.p_values[1]),
                "observations": int(fit.n_observations),
                "entry_date_clusters": int(fit.n_clusters),
                "weighted_by": "followup_primary_choice_routes",
                "comparison": "stable_dominant_entry_minus_native_only_entry",
                "covariance_id": "entry_date_cluster_cr1",
                "interpretation": "exploratory_market_birth_persistence_not_causal",
            }
        )
    return pd.DataFrame(rows)


def support_records(
    *,
    pair_support_path: Path,
    result_rows: int,
    support_rows: int,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "record_type": "input",
                "path": str(pair_support_path.relative_to(REPO_ROOT)),
                "role": "released_endpoint_candidate_pair_support",
            },
            {
                "record_type": "sample_contract",
                "entry_years": ",".join(str(year) for year in MAIN_ENTRY_YEARS),
                "entry_window": "jan_01_through_jun_30",
                "sample_end": SAMPLE_END.strftime("%Y-%m-%d"),
                "horizons_days": ",".join(str(horizon) for horizon in HORIZONS),
                "complete_horizon_required": True,
                "unit": "ordered_ultimate_pair",
                "interpretation": "exploratory_market_birth_persistence_not_causal",
            },
            {
                "record_type": "outputs",
                "result_rows": int(result_rows),
                "support_rows": int(support_rows),
            },
        ]
    )


def build_results(pair_support_path: Path = PAIR_SUPPORT) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not pair_support_path.is_file():
        raise FileNotFoundError(pair_support_path)
    cohorts = entry_cohorts(pair_support_path)
    endpoint_classes = entry_endpoint_class_summary(pair_support_path)
    follow_panels = [
        entry_follow_panel(horizon, pair_support_path=pair_support_path)
        for horizon in HORIZONS
    ]
    summaries = [persistence_summary(panel) for panel in follow_panels]
    contrasts = [persistence_contrasts(panel) for panel in follow_panels]
    result = pd.concat(
        [cohorts, endpoint_classes, *summaries, *contrasts],
        ignore_index=True,
        sort=False,
    )
    for column in ("stable_share", "stable_dominant_pair_share"):
        if column in result.columns:
            values = pd.to_numeric(result[column], errors="coerce")
            if ((values < -1e-12) | (values > 1 + 1e-12)).any():
                raise ValueError(f"{column} is outside [0, 1]")
    if not np.isfinite(
        pd.to_numeric(result.get("primary_routes", pd.Series(dtype=float)), errors="coerce")
        .dropna()
        .to_numpy(float)
    ).all():
        raise ValueError("formation results contain nonfinite route mass")
    support = support_records(
        pair_support_path=pair_support_path,
        result_rows=len(result),
        support_rows=3,
    )
    return result, support


def run(
    *,
    pair_support_path: Path = PAIR_SUPPORT,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    result, support = build_results(pair_support_path)
    result_output.parent.mkdir(parents=True, exist_ok=True)
    support_output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output(result_output) as temporary:
        result.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )
    with atomic_output(support_output) as temporary:
        support.to_json(
            temporary,
            orient="records",
            lines=True,
            date_format="iso",
            double_precision=15,
        )
    print(
        f"wrote {len(result):,} formation rows and {len(support):,} support rows"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair-support", type=Path, default=PAIR_SUPPORT)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        pair_support_path=args.pair_support,
        result_output=args.result_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())

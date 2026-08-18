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
CANDIDATE_CHOICES = DATA_DIR / "processed/endpoint_candidate_choices.parquet"
TOKEN_PRICE_DAILY = DATA_DIR / "processed/token_price_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/vehicle_formation_exploration.jsonl"
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/vehicle_formation_support.jsonl"
SAMPLE_END = pd.Timestamp("2026-06-30")
MAIN_ENTRY_YEARS = (2024, 2026)
BASELINE_YEAR = MAIN_ENTRY_YEARS[0]
COMPARISON_YEAR = MAIN_ENTRY_YEARS[1]
HORIZONS = (30, 120)
ENTRY_TYPES = ("native_only_entry", "stable_present_entry", "stable_dominant_entry")
ENTRY_DRIVER_PREDICTORS = (
    "is_2026",
    "stable_endpoint",
    "is_2026_x_stable_endpoint",
    "log_entry_routes",
    "direct_available",
    "direct_share",
    "complex_share",
)
ENTRY_ARCHITECTURE_PREDICTORS = (
    "is_2026",
    "stable_endpoint",
    "is_2026_x_stable_endpoint",
    "log_entry_routes",
    "direct_share",
    "complex_share",
    "is_2026_x_direct_share",
    "is_2026_x_complex_share",
)
ENTRY_SECURE_VOLUME_PREDICTORS = (
    "is_2026",
    "stable_endpoint",
    "is_2026_x_stable_endpoint",
    "log_entry_routes",
    "direct_share",
    "complex_share",
    "is_2026_x_direct_share",
    "is_2026_x_complex_share",
)
ENTRY_ENDPOINT_HISTORY_PREDICTORS = (
    "is_2026",
    "log_entry_routes",
    "direct_share",
    "complex_share",
    "is_2026_x_direct_share",
    "is_2026_x_complex_share",
    "no_prior_price_history_30",
    "log_min_prior_price_obs_30",
    "endpoint_log_price_sd_30",
)


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


def endpoint_claim_class(src: object, tgt: object) -> str:
    """Classify endpoint pairs by the strongest non-WETH claim type present."""

    src_symbol, src_type = classify(src)
    tgt_symbol, tgt_type = classify(tgt)
    symbols = {src_symbol, tgt_symbol}
    types = {src_type, tgt_type}
    if "WETH" in symbols:
        return "weth_endpoint"
    if "stable" in types:
        return "stable_endpoint"
    if "imported" in types:
        return "imported_endpoint"
    if "staked_native" in types:
        return "staked_native_endpoint"
    if "native" in types:
        return "other_native_endpoint"
    return "other_endpoint"


def endpoint_claim_class_summaries(pair_support_path: Path = PAIR_SUPPORT) -> pd.DataFrame:
    """Split active and entering route mass by endpoint claim class."""

    path = _sql_path(pair_support_path)
    years = ", ".join(str(year) for year in MAIN_ENTRY_YEARS)
    panel = _read_sql(
        f"""
        SELECT
            date,
            src,
            tgt,
            year(date)::INTEGER AS year,
            pair_entry_on_day,
            primary_choice_route_count::DOUBLE AS primary_routes,
            stable_choice_route_count::DOUBLE AS stable_routes,
            native_choice_route_count::DOUBLE AS native_routes,
            direct_route_count::DOUBLE AS direct_routes,
            market_route_count::DOUBLE AS market_routes
        FROM read_parquet('{path}')
        WHERE primary_choice_route_count > 0
          AND year(date) IN ({years})
          AND strftime(date, '%m-%d') <= '06-30'
        """
    )
    if panel.empty:
        return pd.DataFrame()
    unique_pairs = panel[["src", "tgt"]].drop_duplicates().copy()
    unique_pairs["endpoint_claim_class"] = [
        endpoint_claim_class(src, tgt)
        for src, tgt in zip(unique_pairs["src"], unique_pairs["tgt"])
    ]
    panel = panel.merge(unique_pairs, on=["src", "tgt"], validate="many_to_one")
    rows: list[dict[str, object]] = []
    for sample_scope, sample in (
        ("active_pair_days", panel),
        ("entry_pair_days", panel[panel["pair_entry_on_day"]].copy()),
    ):
        if sample.empty:
            continue
        year_totals = sample.groupby("year")["primary_routes"].sum()
        grouped = sample.groupby(["year", "endpoint_claim_class"], sort=True)
        for (year, class_name), group in grouped:
            primary_routes = float(group["primary_routes"].sum())
            market_routes = float(group["market_routes"].sum())
            if primary_routes <= 0:
                continue
            rows.append(
                {
                    "record_type": "endpoint_claim_class",
                    "sample_scope": sample_scope,
                    "year": int(year),
                    "endpoint_claim_class": str(class_name),
                    "pairs": int(
                        group[["src", "tgt"]].drop_duplicates().shape[0]
                    ),
                    "pair_days": int(len(group)),
                    "primary_routes": primary_routes,
                    "stable_routes": float(group["stable_routes"].sum()),
                    "native_routes": float(group["native_routes"].sum()),
                    "route_mass_share": primary_routes / float(year_totals.loc[year]),
                    "stable_share": float(group["stable_routes"].sum() / primary_routes),
                    "native_share": float(group["native_routes"].sum() / primary_routes),
                    "direct_route_share": (
                        float(group["direct_routes"].sum() / market_routes)
                        if market_routes > 0
                        else np.nan
                    ),
                    "interpretation": (
                        "exploratory_endpoint_claim_class_split_not_causal"
                    ),
                }
            )
    return pd.DataFrame(rows)


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


def entry_secure_volume_summary(pair_support_path: Path = PAIR_SUPPORT) -> pd.DataFrame:
    """Split non-WETH entrants by whether a stablecoin is already an endpoint.

    This is the entrant analogue of the secure-volume idea in vehicle-currency
    theory: an asset with demand at one side of a corridor has an easier path to
    becoming the intermediary for other trades. WETH endpoints are excluded
    because the native-versus-stable vehicle is mechanically settled there.
    """

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
    non_weth = entries[~entries["endpoint_class"].eq("weth_endpoint")].copy()
    non_weth["secure_volume_class"] = np.where(
        non_weth["endpoint_class"].eq("stable_endpoint"),
        "stable_endpoint",
        "other_non_weth_endpoint",
    )
    total_by_year = non_weth.groupby("entry_year")["primary_routes"].sum()
    rows: list[dict[str, object]] = []
    for (year, class_name), group in non_weth.groupby(
        ["entry_year", "secure_volume_class"], sort=True
    ):
        primary_routes = float(group["primary_routes"].sum())
        stable_routes = float(group["stable_routes"].sum())
        native_routes = float(group["native_routes"].sum())
        rows.append(
            {
                "record_type": "entry_secure_volume_class",
                "entry_year": int(year),
                "secure_volume_class": str(class_name),
                "pairs": int(len(group)),
                "primary_routes": primary_routes,
                "stable_routes": stable_routes,
                "native_routes": native_routes,
                "stable_share": stable_routes / primary_routes,
                "stable_dominant_pair_share": float(
                    (group["stable_routes"] > group["native_routes"]).mean()
                ),
                "route_mass_share": primary_routes / float(total_by_year.loc[year]),
                "interpretation": (
                    "exploratory_secure_volume_entry_split_not_causal"
                ),
            }
        )
    summary = pd.DataFrame(rows)
    gap_rows: list[dict[str, object]] = []
    by_year: dict[int, float] = {}
    for year, group in summary.groupby("entry_year", sort=True):
        stable = group[group["secure_volume_class"].eq("stable_endpoint")]
        other = group[group["secure_volume_class"].eq("other_non_weth_endpoint")]
        if len(stable) == 1 and len(other) == 1:
            gap = float(stable.iloc[0]["stable_share"] - other.iloc[0]["stable_share"])
            by_year[int(year)] = gap
            gap_rows.append(
                {
                    "record_type": "entry_secure_volume_gap",
                    "entry_year": int(year),
                    "stable_endpoint_stable_share": float(
                        stable.iloc[0]["stable_share"]
                    ),
                    "other_non_weth_stable_share": float(
                        other.iloc[0]["stable_share"]
                    ),
                    "stable_share_gap": gap,
                    "interpretation": (
                        "stable_endpoint_minus_other_non_weth_entry_share"
                    ),
                }
            )
    if BASELINE_YEAR in by_year and COMPARISON_YEAR in by_year:
        gap_rows.append(
            {
                "record_type": "entry_secure_volume_gap_change",
                "baseline_year": BASELINE_YEAR,
                "comparison_year": COMPARISON_YEAR,
                "baseline_gap": by_year[BASELINE_YEAR],
                "comparison_gap": by_year[COMPARISON_YEAR],
                "gap_change": by_year[COMPARISON_YEAR] - by_year[BASELINE_YEAR],
                "interpretation": (
                    "descriptive_change_in_stable_endpoint_entry_gap"
                ),
            }
        )
    return pd.concat([summary, pd.DataFrame(gap_rows)], ignore_index=True, sort=False)


def entry_stable_candidate_summary(
    pair_support_path: Path = PAIR_SUPPORT,
    candidate_choices_path: Path = CANDIDATE_CHOICES,
) -> pd.DataFrame:
    """Summarise which stable candidates carry stable-vehicle entry routes."""

    pair_path = _sql_path(pair_support_path)
    choices_path = _sql_path(candidate_choices_path)
    years = ", ".join(str(year) for year in MAIN_ENTRY_YEARS)
    return _read_sql(
        f"""
        WITH entries AS (
            SELECT
                date,
                src,
                tgt,
                year(date)::INTEGER AS entry_year
            FROM read_parquet('{pair_path}')
            WHERE pair_entry_on_day
              AND primary_choice_route_count > 0
              AND year(date) IN ({years})
              AND strftime(date, '%m-%d') <= '06-30'
        ),
        stable_choices AS (
            SELECT
                e.entry_year,
                c.candidate_symbol,
                count(DISTINCT concat(CAST(e.date AS VARCHAR), '|', e.src, '|', e.tgt))::INTEGER
                    AS pair_days,
                sum(c.route_count)::DOUBLE AS candidate_routes,
                sum(c.within_20pct_routes)::DOUBLE AS strict_candidate_routes,
                sum(c.within_20pct_value_usd)::DOUBLE AS strict_candidate_value_usd
            FROM entries e
            JOIN read_parquet('{choices_path}') c
              ON c.date = e.date
             AND c.src = e.src
             AND c.tgt = e.tgt
            WHERE c.candidate_type = 'stable'
              AND c.route_count > 0
            GROUP BY 1, 2
        ),
        totals AS (
            SELECT
                entry_year,
                sum(candidate_routes)::DOUBLE AS stable_entry_routes
            FROM stable_choices
            GROUP BY 1
        )
        SELECT
            'entry_stable_candidate' AS record_type,
            s.entry_year,
            s.candidate_symbol,
            s.pair_days,
            s.candidate_routes,
            s.strict_candidate_routes,
            s.strict_candidate_value_usd,
            t.stable_entry_routes,
            s.candidate_routes / nullif(t.stable_entry_routes, 0) AS stable_entry_route_share,
            'exploratory_stable_entry_candidate_concentration_not_causal' AS interpretation
        FROM stable_choices s
        JOIN totals t USING (entry_year)
        ORDER BY s.entry_year, stable_entry_route_share DESC, s.candidate_symbol
        """
    )


def entry_stable_candidate_persistence(
    horizon_days: int,
    *,
    pair_support_path: Path = PAIR_SUPPORT,
    candidate_choices_path: Path = CANDIDATE_CHOICES,
    sample_end: pd.Timestamp = SAMPLE_END,
) -> pd.DataFrame:
    """Measure whether the stable candidate used at entry keeps the stable role."""

    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    pair_path = _sql_path(pair_support_path)
    choices_path = _sql_path(candidate_choices_path)
    years = ", ".join(str(year) for year in MAIN_ENTRY_YEARS)
    sample_end_text = pd.Timestamp(sample_end).strftime("%Y-%m-%d")
    return _read_sql(
        f"""
        WITH entries AS (
            SELECT
                date AS entry_date,
                src,
                tgt,
                year(date)::INTEGER AS entry_year
            FROM read_parquet('{pair_path}')
            WHERE pair_entry_on_day
              AND primary_choice_route_count > 0
              AND stable_choice_route_count > 0
              AND year(date) IN ({years})
              AND strftime(date, '%m-%d') <= '06-30'
              AND date + INTERVAL {int(horizon_days)} DAY <= DATE '{sample_end_text}'
        ),
        entry_stable AS (
            SELECT
                e.entry_date,
                e.src,
                e.tgt,
                e.entry_year,
                c.candidate_symbol,
                sum(c.route_count)::DOUBLE AS entry_candidate_routes
            FROM entries e
            JOIN read_parquet('{choices_path}') c
              ON c.date = e.entry_date
             AND c.src = e.src
             AND c.tgt = e.tgt
            WHERE c.candidate_type = 'stable'
              AND c.route_count > 0
            GROUP BY 1, 2, 3, 4, 5
        ),
        entry_leaders AS (
            SELECT *
            FROM (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY entry_date, src, tgt
                        ORDER BY entry_candidate_routes DESC, candidate_symbol
                    ) AS rank
                FROM entry_stable
            )
            WHERE rank = 1
        ),
        entry_weight AS (
            SELECT
                entry_year,
                candidate_symbol AS entry_candidate_symbol,
                count(*)::INTEGER AS pairs,
                sum(entry_candidate_routes)::DOUBLE AS entry_candidate_routes
            FROM entry_leaders
            GROUP BY 1, 2
        ),
        followup AS (
            SELECT
                e.entry_year,
                e.candidate_symbol AS entry_candidate_symbol,
                sum(c.route_count)::DOUBLE AS stable_followup_routes,
                sum(
                    CASE
                        WHEN c.candidate_symbol = e.candidate_symbol
                            THEN c.route_count
                        ELSE 0
                    END
                )::DOUBLE AS own_candidate_followup_routes
            FROM entry_leaders e
            JOIN read_parquet('{choices_path}') c
              ON c.src = e.src
             AND c.tgt = e.tgt
             AND c.date BETWEEN e.entry_date
                            AND e.entry_date + INTERVAL {int(horizon_days)} DAY
            WHERE c.candidate_type = 'stable'
              AND c.route_count > 0
            GROUP BY 1, 2
        )
        SELECT
            'entry_stable_candidate_persistence' AS record_type,
            {int(horizon_days)}::INTEGER AS horizon_days,
            f.entry_year,
            f.entry_candidate_symbol,
            e.pairs,
            e.entry_candidate_routes,
            f.stable_followup_routes,
            f.own_candidate_followup_routes,
            f.own_candidate_followup_routes / nullif(f.stable_followup_routes, 0)
                AS own_candidate_followup_share,
            'exploratory_stable_candidate_identity_persistence_not_causal'
                AS interpretation
        FROM followup f
        JOIN entry_weight e USING (entry_year, entry_candidate_symbol)
        WHERE f.stable_followup_routes > 0
        ORDER BY f.entry_year, horizon_days, own_candidate_followup_share DESC,
                 f.entry_candidate_symbol
        """
    )


def entry_driver_panel(pair_support_path: Path = PAIR_SUPPORT) -> pd.DataFrame:
    """Return non-WETH entrant rows used by the birth-driver regression."""

    path = _sql_path(pair_support_path)
    years = ", ".join(str(year) for year in MAIN_ENTRY_YEARS)
    panel = _read_sql(
        f"""
        SELECT
            date,
            src,
            tgt,
            year(date)::INTEGER AS entry_year,
            primary_choice_route_count::DOUBLE AS primary_routes,
            stable_choice_route_count::DOUBLE AS stable_routes,
            native_choice_route_count::DOUBLE AS native_routes,
            direct_route_count::DOUBLE AS direct_routes,
            (
                multiple_intermediary_route_count
                + split_or_join_route_count
                + nonsequential_two_leg_route_count
            )::DOUBLE AS complex_routes,
            market_route_count::DOUBLE AS market_routes
        FROM read_parquet('{path}')
        WHERE pair_entry_on_day
          AND primary_choice_route_count > 0
          AND year(date) IN ({years})
          AND strftime(date, '%m-%d') <= '06-30'
        """
    )
    panel["endpoint_class"] = [
        endpoint_class(src, tgt) for src, tgt in zip(panel["src"], panel["tgt"])
    ]
    panel = panel[~panel["endpoint_class"].eq("weth_endpoint")].copy()
    panel["stable_share"] = panel["stable_routes"] / panel["primary_routes"]
    panel["stable_dominant_entry"] = (
        panel["stable_routes"] > panel["native_routes"]
    ).astype(float)
    panel["is_2026"] = panel["entry_year"].eq(COMPARISON_YEAR).astype(float)
    panel["stable_endpoint"] = panel["endpoint_class"].eq("stable_endpoint").astype(float)
    panel["is_2026_x_stable_endpoint"] = panel["is_2026"] * panel["stable_endpoint"]
    panel["log_entry_routes"] = np.log1p(panel["primary_routes"])
    panel["direct_available"] = panel["direct_routes"].gt(0).astype(float)
    market_routes = panel["market_routes"].replace(0, np.nan)
    panel["direct_share"] = (panel["direct_routes"] / market_routes).fillna(0.0).clip(0.0, 1.0)
    panel["complex_share"] = (panel["complex_routes"] / market_routes).fillna(0.0).clip(0.0, 1.0)
    panel["is_2026_x_direct_share"] = panel["is_2026"] * panel["direct_share"]
    panel["is_2026_x_complex_share"] = panel["is_2026"] * panel["complex_share"]
    return panel


def entry_driver_regressions(panel: pd.DataFrame) -> pd.DataFrame:
    """Fit non-WETH entrant driver screens for stable birth."""

    rows: list[dict[str, object]] = []
    for outcome in ("stable_share", "stable_dominant_entry"):
        required = [outcome, "date", "primary_routes", *ENTRY_DRIVER_PREDICTORS]
        data = panel.loc[:, required].replace([np.inf, -np.inf], np.nan).dropna()
        fit = ols_clustered(
            data[outcome],
            data[list(ENTRY_DRIVER_PREDICTORS)],
            data["date"],
            weights=data["primary_routes"],
            min_observations=1000,
            min_clusters=30,
        )
        for name, beta, se, t_stat, p_value in zip(
            ("constant", *ENTRY_DRIVER_PREDICTORS),
            fit.beta,
            fit.standard_errors,
            fit.t_statistics,
            fit.p_values,
            strict=True,
        ):
            rows.append(
                {
                    "record_type": "entry_driver_regression",
                    "entry_year": None,
                    "endpoint_class": "non_weth_endpoint",
                    "outcome": outcome,
                    "predictor": name,
                    "coefficient": float(beta),
                    "coefficient_pp": 100.0 * float(beta),
                    "standard_error": float(se),
                    "standard_error_pp": 100.0 * float(se),
                    "t_statistic": float(t_stat),
                    "p_value": float(p_value),
                    "observations": int(fit.n_observations),
                    "entry_date_clusters": int(fit.n_clusters),
                    "weighted_by": "entry_primary_choice_routes",
                    "covariance_id": "entry_date_cluster_cr1",
                    "controls": ",".join(ENTRY_DRIVER_PREDICTORS),
                    "interpretation": "exploratory_non_weth_entry_driver_not_causal",
                }
            )
    return pd.DataFrame(rows)


def entry_route_architecture_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Fit 2026-by-route-architecture screens for stable birth."""

    rows: list[dict[str, object]] = []
    for outcome in ("stable_share", "stable_dominant_entry"):
        required = [outcome, "date", "primary_routes", *ENTRY_ARCHITECTURE_PREDICTORS]
        data = panel.loc[:, required].replace([np.inf, -np.inf], np.nan).dropna()
        fit = ols_clustered(
            data[outcome],
            data[list(ENTRY_ARCHITECTURE_PREDICTORS)],
            data["date"],
            weights=data["primary_routes"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        for name, beta, se, t_stat, p_value in zip(
            ("constant", *ENTRY_ARCHITECTURE_PREDICTORS),
            fit.beta,
            fit.standard_errors,
            fit.t_statistics,
            fit.p_values,
            strict=True,
        ):
            rows.append(
                {
                    "record_type": "entry_route_architecture_regression",
                    "entry_year": None,
                    "endpoint_class": "non_weth_endpoint",
                    "outcome": outcome,
                    "predictor": name,
                    "coefficient": float(beta),
                    "coefficient_pp": 100.0 * float(beta),
                    "standard_error": float(se),
                    "standard_error_pp": 100.0 * float(se),
                    "t_statistic": float(t_stat),
                    "p_value": float(p_value),
                    "observations": int(fit.n_observations),
                    "entry_date_clusters": int(fit.n_clusters),
                    "weighted_by": "entry_primary_choice_routes",
                    "covariance_id": "entry_date_cluster_cr1",
                    "controls": ",".join(ENTRY_ARCHITECTURE_PREDICTORS),
                    "interpretation": (
                        "exploratory_2026_route_architecture_driver_not_causal"
                    ),
                }
            )
    return pd.DataFrame(rows)


def entry_secure_volume_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Fit secure-volume screens conditional on entry route architecture."""

    rows: list[dict[str, object]] = []
    for outcome in ("stable_share", "stable_dominant_entry"):
        required = [outcome, "date", "primary_routes", *ENTRY_SECURE_VOLUME_PREDICTORS]
        data = panel.loc[:, required].replace([np.inf, -np.inf], np.nan).dropna()
        fit = ols_clustered(
            data[outcome],
            data[list(ENTRY_SECURE_VOLUME_PREDICTORS)],
            data["date"],
            weights=data["primary_routes"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        for name, beta, se, t_stat, p_value in zip(
            ("constant", *ENTRY_SECURE_VOLUME_PREDICTORS),
            fit.beta,
            fit.standard_errors,
            fit.t_statistics,
            fit.p_values,
            strict=True,
        ):
            rows.append(
                {
                    "record_type": "entry_secure_volume_regression",
                    "entry_year": None,
                    "endpoint_class": "non_weth_endpoint",
                    "outcome": outcome,
                    "predictor": name,
                    "coefficient": float(beta),
                    "coefficient_pp": 100.0 * float(beta),
                    "standard_error": float(se),
                    "standard_error_pp": 100.0 * float(se),
                    "t_statistic": float(t_stat),
                    "p_value": float(p_value),
                    "observations": int(fit.n_observations),
                    "entry_date_clusters": int(fit.n_clusters),
                    "weighted_by": "entry_primary_choice_routes",
                    "covariance_id": "entry_date_cluster_cr1",
                    "controls": ",".join(ENTRY_SECURE_VOLUME_PREDICTORS),
                    "interpretation": (
                        "exploratory_secure_volume_entry_driver_not_causal"
                    ),
                }
            )
    return pd.DataFrame(rows)


def entry_endpoint_history_panel(
    panel: pd.DataFrame,
    token_price_path: Path = TOKEN_PRICE_DAILY,
) -> pd.DataFrame:
    """Attach prior endpoint price-history support to non-WETH entrants.

    The screen asks whether stable vehicles appear disproportionately when a
    new ultimate pair has little recent price history at one endpoint. It uses
    the canonical processed token-price panel only as a history/support measure.
    Price levels are not interpreted, because token decimal conventions differ
    across assets and sources.
    """

    required = {
        "date",
        "src",
        "tgt",
        "entry_year",
        "endpoint_class",
        "primary_routes",
        "stable_share",
        "stable_dominant_entry",
        *ENTRY_ENDPOINT_HISTORY_PREDICTORS[:6],
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"entry driver panel lacks columns for endpoint history: {missing}")
    if not token_price_path.is_file():
        raise FileNotFoundError(token_price_path)
    base = panel.copy()
    base["date"] = pd.to_datetime(base["date"]).dt.normalize()
    base["src_lower"] = base["src"].astype(str).str.lower()
    base["tgt_lower"] = base["tgt"].astype(str).str.lower()
    endpoint_keys = pd.concat(
        [
            base[["date", "src"]].rename(columns={"src": "token"}).assign(side="src"),
            base[["date", "tgt"]].rename(columns={"tgt": "token"}).assign(side="tgt"),
        ],
        ignore_index=True,
    ).drop_duplicates()
    connection = duckdb.connect()
    try:
        connection.register("endpoint_keys", endpoint_keys)
        price_path = _sql_path(token_price_path)
        history = connection.execute(
            f"""
            WITH endpoints AS (
                SELECT DISTINCT
                    CAST(date AS DATE) AS date,
                    lower(token) AS token,
                    side
                FROM endpoint_keys
            ),
            prices AS (
                SELECT
                    strptime(day, '%Y%m%d')::DATE AS price_date,
                    lower(token) AS token,
                    price_usd::DOUBLE AS price_usd,
                    n_observations::DOUBLE AS n_obs
                FROM read_parquet('{price_path}')
                WHERE price_usd > 0
                  AND validation_status = 'minimum_observations_and_price_consensus_passed'
            )
            SELECT
                e.date,
                e.token,
                e.side,
                count(DISTINCT p.price_date)::DOUBLE AS prior_price_days_30,
                coalesce(sum(p.n_obs), 0)::DOUBLE AS prior_price_obs_30,
                coalesce(avg(p.n_obs), 0)::DOUBLE AS mean_price_obs_day_30,
                coalesce(stddev_samp(ln(p.price_usd)), 0)::DOUBLE AS log_price_sd_30
            FROM endpoints e
            LEFT JOIN prices p
              ON p.token = e.token
             AND p.price_date >= e.date - INTERVAL 30 DAY
             AND p.price_date < e.date
            GROUP BY 1, 2, 3
            """
        ).fetchdf()
    finally:
        connection.close()
    source_history = history[history["side"].eq("src")].drop(columns="side").rename(
        columns={
            "token": "src_lower",
            "prior_price_days_30": "src_prior_price_days_30",
            "prior_price_obs_30": "src_prior_price_obs_30",
            "mean_price_obs_day_30": "src_mean_price_obs_day_30",
            "log_price_sd_30": "src_log_price_sd_30",
        }
    )
    target_history = history[history["side"].eq("tgt")].drop(columns="side").rename(
        columns={
            "token": "tgt_lower",
            "prior_price_days_30": "tgt_prior_price_days_30",
            "prior_price_obs_30": "tgt_prior_price_obs_30",
            "mean_price_obs_day_30": "tgt_mean_price_obs_day_30",
            "log_price_sd_30": "tgt_log_price_sd_30",
        }
    )
    out = base.merge(
        source_history,
        on=["date", "src_lower"],
        how="left",
        validate="many_to_one",
    ).merge(
        target_history,
        on=["date", "tgt_lower"],
        how="left",
        validate="many_to_one",
    )
    if len(out) != len(base):
        raise ValueError("endpoint-history merge changed entrant row count")
    for side in ("src", "tgt"):
        for suffix in (
            "prior_price_days_30",
            "prior_price_obs_30",
            "mean_price_obs_day_30",
            "log_price_sd_30",
        ):
            column = f"{side}_{suffix}"
            out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    out["min_prior_price_days_30"] = out[
        ["src_prior_price_days_30", "tgt_prior_price_days_30"]
    ].min(axis=1)
    out["no_prior_price_history_30"] = out["min_prior_price_days_30"].eq(0).astype(float)
    out["log_min_prior_price_obs_30"] = np.log1p(
        out[["src_prior_price_obs_30", "tgt_prior_price_obs_30"]].min(axis=1)
    )
    out["endpoint_log_price_sd_30"] = out[
        ["src_log_price_sd_30", "tgt_log_price_sd_30"]
    ].max(axis=1)
    if out["min_prior_price_days_30"].max() > 30:
        raise ValueError("prior endpoint price-history count exceeds the 30-day window")
    return out


def entry_endpoint_history_summaries(panel: pd.DataFrame) -> pd.DataFrame:
    """Summarise stable birth by endpoint price-history support."""

    sample = panel[panel["endpoint_class"].eq("other_endpoint")].copy()
    if sample.empty:
        raise ValueError("endpoint-history summary has no other-endpoint entrants")
    rows: list[dict[str, object]] = []
    totals = sample.groupby("entry_year")["primary_routes"].sum()
    for (year, no_history), group in sample.groupby(
        ["entry_year", "no_prior_price_history_30"], sort=True
    ):
        primary_routes = float(group["primary_routes"].sum())
        rows.append(
            {
                "record_type": "entry_endpoint_history_summary",
                "sample": "other_endpoint",
                "entry_year": int(year),
                "no_prior_price_history_30": bool(no_history),
                "pairs": int(len(group)),
                "primary_routes": primary_routes,
                "stable_routes": float(group["stable_routes"].sum()),
                "native_routes": float(group["native_routes"].sum()),
                "stable_share": float(group["stable_routes"].sum() / primary_routes),
                "stable_dominant_pair_share": float(
                    group["stable_dominant_entry"].astype(float).mean()
                ),
                "route_mass_share": primary_routes / float(totals.loc[year]),
                "mean_min_prior_price_days_30": float(
                    np.average(
                        group["min_prior_price_days_30"].astype(float),
                        weights=group["primary_routes"].astype(float),
                    )
                ),
                "interpretation": (
                    "exploratory_endpoint_price_history_entry_split_not_causal"
                ),
            }
        )
    return pd.DataFrame(rows)


def entry_endpoint_history_regressions(
    panel: pd.DataFrame,
    *,
    min_observations: int = 1000,
    min_clusters: int = 30,
) -> pd.DataFrame:
    """Fit entrant stable-birth screens using prior endpoint price history."""

    rows: list[dict[str, object]] = []
    sample = panel[panel["endpoint_class"].eq("other_endpoint")].copy()
    if sample.empty:
        raise ValueError("endpoint-history regression has no other-endpoint entrants")
    for outcome in ("stable_share", "stable_dominant_entry"):
        required = [outcome, "date", "primary_routes", *ENTRY_ENDPOINT_HISTORY_PREDICTORS]
        data = sample.loc[:, required].replace([np.inf, -np.inf], np.nan).dropna()
        fit = ols_clustered(
            data[outcome],
            data[list(ENTRY_ENDPOINT_HISTORY_PREDICTORS)],
            data["date"],
            weights=data["primary_routes"],
            min_observations=min_observations,
            min_clusters=min_clusters,
        )
        for name, beta, se, t_stat, p_value in zip(
            ("constant", *ENTRY_ENDPOINT_HISTORY_PREDICTORS),
            fit.beta,
            fit.standard_errors,
            fit.t_statistics,
            fit.p_values,
            strict=True,
        ):
            rows.append(
                {
                    "record_type": "entry_endpoint_history_regression",
                    "sample": "other_endpoint",
                    "entry_year": None,
                    "outcome": outcome,
                    "predictor": name,
                    "coefficient": float(beta),
                    "coefficient_pp": 100.0 * float(beta),
                    "standard_error": float(se),
                    "standard_error_pp": 100.0 * float(se),
                    "t_statistic": float(t_stat),
                    "p_value": float(p_value),
                    "observations": int(fit.n_observations),
                    "entry_date_clusters": int(fit.n_clusters),
                    "weighted_by": "entry_primary_choice_routes",
                    "covariance_id": "entry_date_cluster_cr1",
                    "controls": ",".join(ENTRY_ENDPOINT_HISTORY_PREDICTORS),
                    "interpretation": (
                        "exploratory_endpoint_price_history_entry_driver_not_causal"
                    ),
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


def entry_regime_hysteresis(
    horizon_days: int,
    *,
    pair_support_path: Path = PAIR_SUPPORT,
    sample_end: pd.Timestamp = SAMPLE_END,
) -> pd.DataFrame:
    """Measure whether stable-born entrants ever leave stable-majority status."""

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
                e.entry_type,
                e.src,
                e.tgt,
                count(*)::INTEGER AS active_days,
                sum(
                    (p.stable_choice_route_count > p.native_choice_route_count)::INTEGER
                )::INTEGER AS stable_majority_days,
                sum(
                    (
                        p.native_choice_route_count >= p.stable_choice_route_count
                        AND p.primary_choice_route_count > 0
                    )::INTEGER
                )::INTEGER AS nonstable_majority_days,
                sum(p.primary_choice_route_count)::DOUBLE AS primary_routes,
                sum(p.stable_choice_route_count)::DOUBLE AS stable_routes
            FROM entries e
            JOIN read_parquet('{path}') p
              ON p.src = e.src
             AND p.tgt = e.tgt
             AND p.date BETWEEN e.entry_date
                            AND e.entry_date + INTERVAL {int(horizon_days)} DAY
            WHERE p.primary_choice_route_count > 0
            GROUP BY 1,2,3,4
        )
        SELECT
            'entry_regime_hysteresis' AS record_type,
            {int(horizon_days)}::INTEGER AS horizon_days,
            entry_year,
            entry_type,
            count(*)::INTEGER AS pairs,
            sum((active_days >= 2)::INTEGER)::INTEGER AS pairs_trading_again,
            avg((nonstable_majority_days = 0)::DOUBLE) AS never_left_share_all,
            avg(
                CASE
                    WHEN active_days >= 2
                        THEN (nonstable_majority_days = 0)::DOUBLE
                    ELSE NULL
                END
            ) AS never_left_share_retrade,
            avg(stable_majority_days::DOUBLE / active_days)
                AS mean_stable_majority_day_share,
            sum(stable_routes)::DOUBLE / nullif(sum(primary_routes), 0)
                AS route_stable_share,
            'exploratory_active-day_regime_hysteresis_not_causal'
                AS interpretation
        FROM follow
        GROUP BY 1,2,3,4
        ORDER BY entry_year, horizon_days, entry_type
        """
    )


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
    candidate_choices_path: Path,
    token_price_path: Path,
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
                "record_type": "input",
                "path": str(candidate_choices_path.relative_to(REPO_ROOT)),
                "role": "released_endpoint_candidate_choices",
            },
            {
                "record_type": "input",
                "path": str(token_price_path.relative_to(REPO_ROOT)),
                "role": "canonical_processed_token_price_history",
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


def build_results(
    pair_support_path: Path = PAIR_SUPPORT,
    candidate_choices_path: Path = CANDIDATE_CHOICES,
    token_price_path: Path = TOKEN_PRICE_DAILY,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not pair_support_path.is_file():
        raise FileNotFoundError(pair_support_path)
    if not candidate_choices_path.is_file():
        raise FileNotFoundError(candidate_choices_path)
    if not token_price_path.is_file():
        raise FileNotFoundError(token_price_path)
    cohorts = entry_cohorts(pair_support_path)
    claim_classes = endpoint_claim_class_summaries(pair_support_path)
    endpoint_classes = entry_endpoint_class_summary(pair_support_path)
    secure_volume = entry_secure_volume_summary(pair_support_path)
    stable_candidates = entry_stable_candidate_summary(
        pair_support_path=pair_support_path,
        candidate_choices_path=candidate_choices_path,
    )
    driver_panel = entry_driver_panel(pair_support_path)
    driver_regressions = entry_driver_regressions(driver_panel)
    architecture_regressions = entry_route_architecture_regressions(driver_panel)
    secure_volume_regressions = entry_secure_volume_regressions(driver_panel)
    endpoint_history_panel = entry_endpoint_history_panel(
        driver_panel,
        token_price_path=token_price_path,
    )
    endpoint_history_summaries = entry_endpoint_history_summaries(endpoint_history_panel)
    endpoint_history_regressions = entry_endpoint_history_regressions(
        endpoint_history_panel
    )
    follow_panels = [
        entry_follow_panel(horizon, pair_support_path=pair_support_path)
        for horizon in HORIZONS
    ]
    candidate_persistence = [
        entry_stable_candidate_persistence(
            horizon,
            pair_support_path=pair_support_path,
            candidate_choices_path=candidate_choices_path,
        )
        for horizon in HORIZONS
    ]
    summaries = [persistence_summary(panel) for panel in follow_panels]
    contrasts = [persistence_contrasts(panel) for panel in follow_panels]
    hysteresis = [
        entry_regime_hysteresis(horizon, pair_support_path=pair_support_path)
        for horizon in HORIZONS
    ]
    result = pd.concat(
        [
            cohorts,
            claim_classes,
            endpoint_classes,
            secure_volume,
            stable_candidates,
            *candidate_persistence,
            driver_regressions,
            architecture_regressions,
            secure_volume_regressions,
            endpoint_history_summaries,
            endpoint_history_regressions,
            *summaries,
            *contrasts,
            *hysteresis,
        ],
        ignore_index=True,
        sort=False,
    )
    for column in (
        "stable_share",
        "stable_dominant_pair_share",
        "stable_entry_route_share",
        "own_candidate_followup_share",
    ):
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
        candidate_choices_path=candidate_choices_path,
        token_price_path=token_price_path,
        result_rows=len(result),
        support_rows=5,
    )
    return result, support


def run(
    *,
    pair_support_path: Path = PAIR_SUPPORT,
    candidate_choices_path: Path = CANDIDATE_CHOICES,
    token_price_path: Path = TOKEN_PRICE_DAILY,
    result_output: Path = RESULT_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    result, support = build_results(
        pair_support_path=pair_support_path,
        candidate_choices_path=candidate_choices_path,
        token_price_path=token_price_path,
    )
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
    parser.add_argument("--candidate-choices", type=Path, default=CANDIDATE_CHOICES)
    parser.add_argument("--token-price", type=Path, default=TOKEN_PRICE_DAILY)
    parser.add_argument("--result-output", type=Path, default=RESULT_OUTPUT)
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        pair_support_path=args.pair_support,
        candidate_choices_path=args.candidate_choices,
        token_price_path=args.token_price,
        result_output=args.result_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())

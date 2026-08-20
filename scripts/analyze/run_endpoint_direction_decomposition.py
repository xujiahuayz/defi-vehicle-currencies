#!/usr/bin/env python3
"""Locate stable-vehicle rotation by endpoint-direction class.

The headline rotation pools every ordered endpoint pair. This decomposition
separates endpoint directions that contain a native or stable currency from
all other trading relationships. It uses the same equal-weighted common
January--June calendar as the headline result and remains descriptive.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.asset_types import NATIVE, STABLE
from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.tables import write_exhibit


CHOICES_INPUT = REPO_ROOT / "data/processed/endpoint_candidate_choices.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/endpoint_direction_decomposition.jsonl"
CODE_SOURCES = [
    "scripts/analyze/run_endpoint_direction_decomposition.py",
    "src/ddvc/asset_types.py",
]
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
ENDPOINT_GROUPS = (
    "native_to_native",
    "native_to_stable",
    "stable_to_native",
    "stable_to_stable",
    "other_endpoints",
)
METRICS = {
    "route_count": "count_share",
    "within_20pct_value_usd": "strict_intermediation_value_share",
}


def load_endpoint_direction_cells(path: Path = CHOICES_INPUT) -> pd.DataFrame:
    """Aggregate the released choice panel to endpoint-group daily cells."""

    endpoint_types = pd.DataFrame(
        [
            *(
                {"address": address.lower(), "endpoint_type": "native"}
                for address in NATIVE
            ),
            *(
                {"address": address.lower(), "endpoint_type": "stable"}
                for address in STABLE
            ),
        ]
    )
    with duckdb.connect() as connection:
        connection.register("endpoint_types", endpoint_types)
        escaped = str(path).replace("'", "''")
        return connection.execute(
            f"""
            WITH labelled AS (
                SELECT
                    CAST(c.date AS DATE) AS date,
                    YEAR(c.date)::INTEGER AS year,
                    STRFTIME(c.date, '%m-%d') AS month_day,
                    c.candidate_type,
                    CASE
                        WHEN src_type.endpoint_type = 'native'
                         AND tgt_type.endpoint_type = 'native'
                            THEN 'native_to_native'
                        WHEN src_type.endpoint_type = 'native'
                         AND tgt_type.endpoint_type = 'stable'
                            THEN 'native_to_stable'
                        WHEN src_type.endpoint_type = 'stable'
                         AND tgt_type.endpoint_type = 'native'
                            THEN 'stable_to_native'
                        WHEN src_type.endpoint_type = 'stable'
                         AND tgt_type.endpoint_type = 'stable'
                            THEN 'stable_to_stable'
                        ELSE 'other_endpoints'
                    END AS endpoint_group,
                    c.route_count,
                    c.within_20pct_value_usd
                FROM READ_PARQUET('{escaped}') AS c
                LEFT JOIN endpoint_types AS src_type
                  ON LOWER(c.src) = src_type.address
                LEFT JOIN endpoint_types AS tgt_type
                  ON LOWER(c.tgt) = tgt_type.address
                WHERE YEAR(c.date) IN ({BASELINE_YEAR}, {COMPARISON_YEAR})
                  AND STRFTIME(c.date, '%m-%d') <= '06-30'
                  AND c.candidate_type IN ('native', 'stable')
            )
            SELECT
                date,
                year,
                month_day,
                endpoint_group,
                candidate_type,
                SUM(route_count)::DOUBLE AS route_count,
                SUM(within_20pct_value_usd)::DOUBLE AS within_20pct_value_usd
            FROM labelled
            GROUP BY ALL
            ORDER BY date, endpoint_group, candidate_type
            """
        ).fetchdf()


def endpoint_direction_decomposition(cells: pd.DataFrame) -> pd.DataFrame:
    """Return an exact additive decomposition of the daily stable-share change."""

    required = {
        "date",
        "year",
        "month_day",
        "endpoint_group",
        "candidate_type",
        *METRICS,
    }
    missing = sorted(required - set(cells.columns))
    if missing:
        raise ValueError(f"endpoint-direction cells lack columns: {missing}")
    data = cells.copy()
    data["date"] = pd.to_datetime(data["date"], errors="raise").dt.normalize()
    data["year"] = pd.to_numeric(data["year"], errors="raise").astype(int)
    if not data["year"].isin((BASELINE_YEAR, COMPARISON_YEAR)).all():
        raise ValueError("endpoint-direction cells contain an unexpected year")
    if not data["candidate_type"].isin(("native", "stable")).all():
        raise ValueError("endpoint-direction cells contain an unexpected candidate type")
    if not data["endpoint_group"].isin(ENDPOINT_GROUPS).all():
        raise ValueError("endpoint-direction cells contain an unexpected endpoint group")
    for column in METRICS:
        data[column] = pd.to_numeric(data[column], errors="raise")
        if not np.isfinite(data[column]).all() or data[column].lt(0).any():
            raise ValueError(f"endpoint-direction cells contain invalid {column}")

    calendars = {
        year: set(data.loc[data["year"].eq(year), "month_day"])
        for year in (BASELINE_YEAR, COMPARISON_YEAR)
    }
    common_days = sorted(calendars[BASELINE_YEAR] & calendars[COMPARISON_YEAR])
    if not common_days:
        raise ValueError("endpoint-direction cells have no common calendar days")
    data = data[data["month_day"].isin(common_days)].copy()

    records: list[dict[str, object]] = []
    for value_column, metric in METRICS.items():
        daily_group = (
            data.assign(
                stable_mass=np.where(
                    data["candidate_type"].eq("stable"),
                    data[value_column],
                    0.0,
                )
            )
            .groupby(
                ["date", "year", "month_day", "endpoint_group"],
                as_index=False,
                observed=True,
            )
            .agg(group_mass=(value_column, "sum"), stable_mass=("stable_mass", "sum"))
        )
        daily_total = daily_group.groupby("date", observed=True)["group_mass"].transform(
            "sum"
        )
        if daily_total.le(0).any():
            raise ValueError(f"{metric} contains a nonpositive daily denominator")
        daily_group["mass_share"] = daily_group["group_mass"] / daily_total
        daily_group["stable_contribution"] = daily_group["stable_mass"] / daily_total

        complete_index = pd.MultiIndex.from_product(
            [
                sorted(data["date"].unique()),
                ENDPOINT_GROUPS,
            ],
            names=["date", "endpoint_group"],
        )
        complete = (
            daily_group.set_index(["date", "endpoint_group"])[
                ["year", "mass_share", "stable_contribution"]
            ]
            .reindex(complete_index)
            .reset_index()
        )
        complete["year"] = complete["date"].dt.year.astype(int)
        complete[["mass_share", "stable_contribution"]] = complete[
            ["mass_share", "stable_contribution"]
        ].fillna(0.0)
        means = (
            complete.groupby(["year", "endpoint_group"], observed=True)[
                ["mass_share", "stable_contribution"]
            ]
            .mean()
            .reset_index()
        )
        overall = (
            complete.groupby(["year", "date"], observed=True)["stable_contribution"]
            .sum()
            .groupby("year", observed=True)
            .mean()
            .to_dict()
        )
        overall_change = overall[COMPARISON_YEAR] - overall[BASELINE_YEAR]

        for endpoint_group in ENDPOINT_GROUPS:
            selected = means[means["endpoint_group"].eq(endpoint_group)].set_index(
                "year"
            )
            if set(selected.index) != {BASELINE_YEAR, COMPARISON_YEAR}:
                raise ValueError(f"{metric}/{endpoint_group} lacks an endpoint year")
            mass_base = float(selected.loc[BASELINE_YEAR, "mass_share"])
            mass_end = float(selected.loc[COMPARISON_YEAR, "mass_share"])
            contribution_base = float(
                selected.loc[BASELINE_YEAR, "stable_contribution"]
            )
            contribution_end = float(
                selected.loc[COMPARISON_YEAR, "stable_contribution"]
            )
            change = contribution_end - contribution_base
            records.append(
                {
                    "analysis_status": "exploratory_descriptive",
                    "metric": metric,
                    "endpoint_group": endpoint_group,
                    "baseline_year": BASELINE_YEAR,
                    "comparison_year": COMPARISON_YEAR,
                    "common_calendar_days": len(common_days),
                    "route_mass_share_baseline": mass_base,
                    "route_mass_share_comparison": mass_end,
                    "conditional_stable_share_baseline": (
                        contribution_base / mass_base if mass_base > 0 else None
                    ),
                    "conditional_stable_share_comparison": (
                        contribution_end / mass_end if mass_end > 0 else None
                    ),
                    "stable_share_contribution_baseline": contribution_base,
                    "stable_share_contribution_comparison": contribution_end,
                    "stable_share_contribution_change": change,
                    "share_of_total_stable_change": (
                        change / overall_change if overall_change != 0 else None
                    ),
                    "overall_stable_share_baseline": overall[BASELINE_YEAR],
                    "overall_stable_share_comparison": overall[COMPARISON_YEAR],
                    "overall_stable_share_change": overall_change,
                    "estimand": (
                        "equal-weighted common-calendar contribution of the endpoint "
                        "direction to native-versus-stable intermediary share"
                    ),
                    "interpretation": (
                        "descriptive endpoint-demand composition; endpoint identity may "
                        "restrict vehicle eligibility and trading activity is endogenous"
                    ),
                }
            )

        metric_rows = [row for row in records if row["metric"] == metric]
        for suffix in ("baseline", "comparison"):
            mass_sum = sum(float(row[f"route_mass_share_{suffix}"]) for row in metric_rows)
            contribution_sum = sum(
                float(row[f"stable_share_contribution_{suffix}"])
                for row in metric_rows
            )
            year = BASELINE_YEAR if suffix == "baseline" else COMPARISON_YEAR
            if not np.isclose(mass_sum, 1.0, atol=1e-10):
                raise ValueError(f"{metric}/{year} endpoint mass does not reconcile")
            if not np.isclose(contribution_sum, overall[year], atol=1e-10):
                raise ValueError(f"{metric}/{year} stable contribution does not reconcile")
        if not np.isclose(
            sum(float(row["stable_share_contribution_change"]) for row in metric_rows),
            overall_change,
            atol=1e-10,
        ):
            raise ValueError(f"{metric} contribution changes do not reconcile")

    return pd.DataFrame.from_records(records)


def run_endpoint_direction_decomposition(
    *,
    choices_path: Path = CHOICES_INPUT,
    result_path: Path = RESULT_OUTPUT,
) -> pd.DataFrame:
    cells = load_endpoint_direction_cells(choices_path)
    results = endpoint_direction_decomposition(cells)
    write_exhibit(
        results,
        result_path,
        code_sources=CODE_SOURCES,
        inputs=[choices_path],
        notes=(
            "Exploratory exact decomposition of the matched January-June daily "
            "stable-vehicle share by ordered endpoint-direction class."
        ),
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--choices", type=Path, default=CHOICES_INPUT)
    parser.add_argument("--results", type=Path, default=RESULT_OUTPUT)
    args = parser.parse_args()
    results = run_endpoint_direction_decomposition(
        choices_path=args.choices,
        result_path=args.results,
    )
    print(results.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Test whether disconnected transaction components drive vehicle rotation.

The principal route sample excludes every transaction whose pool events form more
than one disconnected token-flow component.  That rule avoids joining unrelated
calls or inferring an unobserved handoff.  This sensitivity instead treats each
internally well-formed disconnected component as a separate route and asks whether
the 2024--2026 stablecoin rotation changes.

Reads   data/unified/YYYYMMDD.parquet
        data/processed/cross_venue_routing_daily.parquet
        data/processed/intermediation_by_type_daily.parquet
Writes  output/exhibits/disconnected_component_boundary.jsonl
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import pandas as pd

from ddvc.analysis.regression import common_calendar_day_mask, year_endpoint_change
from ddvc.asset_types import classify
from ddvc.datasets import route_partitions, validate_before_install
from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.realised import ROUTE_COLUMNS, extract_realised_routes
from ddvc.runtime import bounded_workers
from ddvc.tables import write_exhibit


UNIFIED = DATA_DIR / "unified"
CLEAN_DAILY = DATA_DIR / "processed/cross_venue_routing_daily.parquet"
COMPOSITION_DAILY = DATA_DIR / "processed/intermediation_by_type_daily.parquet"
RESULT_OUTPUT = OUTPUT_DIR / "exhibits/disconnected_component_boundary.jsonl"
BASELINE_YEAR = 2024
COMPARISON_YEAR = 2026
HAC_LAG = 30
CODE_SOURCES = [
    "scripts/analyze/run_disconnected_component_boundary.py",
    "src/ddvc/realised.py",
    "src/ddvc/route_roles.py",
    "src/ddvc/analysis/regression.py",
]
INPUTS = [
    "data/unified/*.parquet",
    "data/processed/cross_venue_routing_daily.parquet",
    "data/processed/intermediation_by_type_daily.parquet",
]


def component_route_sensitivity(legs: pd.DataFrame) -> pd.DataFrame:
    """Return vehicle episodes after treating each disconnected component as a route."""
    disconnected = legs[
        legs["route_class"].astype(str).str.startswith("tricky_")
    ].copy()
    if disconnected.empty:
        return pd.DataFrame()
    disconnected["route_class"] = "coherent"
    return extract_realised_routes(disconnected, require_positive_value=False)


def one_day(path: Path) -> dict[str, object]:
    """Summarize internally valid two-leg components excluded by the principal rule."""
    legs = pd.read_parquet(path, columns=ROUTE_COLUMNS)
    disconnected = legs[
        legs["route_class"].astype(str).str.startswith("tricky_")
    ]
    component_count = int(
        disconnected[["tx_hash", "component_id"]].drop_duplicates().shape[0]
    )
    routes = component_route_sensitivity(legs)
    if routes.empty:
        routes = pd.DataFrame(columns=["legs", "vehicle", "within_20pct", "usd"])
    routes = routes[routes["legs"].eq(2)].copy()
    routes["asset_type"] = routes["vehicle"].map(lambda value: classify(value)[1])
    out: dict[str, object] = {
        "date": pd.to_datetime(path.stem, format="%Y%m%d"),
        "disconnected_components": component_count,
        "eligible_two_leg_components": int(
            routes[["tx_hash", "component_id"]].drop_duplicates().shape[0]
        )
        if not routes.empty
        else 0,
    }
    for asset_type in ("stable", "native"):
        selected = routes[routes["asset_type"].eq(asset_type)]
        out[f"additional_count_{asset_type}"] = int(len(selected))
        out[f"additional_value_{asset_type}"] = float(
            selected.loc[selected["within_20pct"], "usd"].sum()
        )
    return out


def matched_endpoint_paths(paths: list[Path] | None = None) -> list[Path]:
    paths = paths or sorted(UNIFIED.glob("????????.parquet"))
    paths = [path for path in paths if int(path.stem[:4]) in (BASELINE_YEAR, COMPARISON_YEAR)]
    calendar = pd.DataFrame({"path": paths})
    calendar["date"] = pd.to_datetime(
        calendar["path"].map(lambda path: path.stem), format="%Y%m%d"
    )
    calendar["year"] = calendar["date"].dt.year
    matched = common_calendar_day_mask(
        calendar["date"],
        calendar["year"],
        baseline_year=BASELINE_YEAR,
        comparison_year=COMPARISON_YEAR,
    )
    return calendar.loc[matched, "path"].tolist()


def annual_boundary_summary() -> pd.DataFrame:
    """Measure the disconnected share of reconstructed components by year."""
    clean = pd.read_parquet(CLEAN_DAILY, columns=["date", "routes"])
    clean["year"] = pd.to_datetime(clean["date"]).dt.year
    clean = clean.groupby("year", as_index=False).agg(
        clean_components=("routes", "sum")
    )
    pattern = (UNIFIED / "*.parquet").as_posix().replace("'", "''")
    disconnected = duckdb.connect().execute(
        f"""
        SELECT year(to_timestamp(timestamp_utc)) AS year,
               count(DISTINCT tx_hash) AS disconnected_transactions,
               count(DISTINCT tx_hash || ':' || cast(component_id AS varchar))
                   AS disconnected_components
        FROM read_parquet('{pattern}')
        WHERE route_class LIKE 'tricky_%'
        GROUP BY 1
        ORDER BY 1
        """
    ).df()
    out = clean.merge(disconnected, on="year", how="left").fillna(0)
    out["disconnected_component_share"] = out["disconnected_components"] / (
        out["clean_components"] + out["disconnected_components"]
    )
    out["disconnected_transaction_share"] = out["disconnected_transactions"] / (
        out["clean_components"] + out["disconnected_transactions"]
    )
    out.insert(0, "record_type", "annual_boundary")
    return out


def v4_boundary_summary() -> pd.DataFrame:
    """Compare disconnection rates for components that do and do not touch V4."""
    pattern = (UNIFIED / "*.parquet").as_posix().replace("'", "''")
    out = duckdb.connect().execute(
        f"""
        WITH component AS (
            SELECT year(to_timestamp(timestamp_utc)) AS year,
                   tx_hash,
                   component_id,
                   max(CASE WHEN source = 'uniswap_v4' THEN 1 ELSE 0 END) AS touches_v4,
                   max(CASE WHEN route_class LIKE 'tricky_%' THEN 1 ELSE 0 END)
                       AS disconnected
            FROM read_parquet('{pattern}')
            WHERE year(to_timestamp(timestamp_utc)) IN (2025, 2026)
            GROUP BY 1, 2, 3
        )
        SELECT year,
               cast(touches_v4 AS boolean) AS touches_v4,
               count(*) AS components,
               sum(disconnected) AS disconnected_components,
               avg(disconnected::DOUBLE) AS disconnected_component_share
        FROM component
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).df()
    out.insert(0, "record_type", "v4_boundary")
    return out


def headline_sensitivity(extra: pd.DataFrame) -> pd.DataFrame:
    """Estimate the matched-day rotation with and without component inclusion."""
    columns = [
        "date",
        "cnt_two_leg_stable",
        "cnt_two_leg_native",
        "usd_within_20pct_two_leg_stable",
        "usd_within_20pct_two_leg_native",
    ]
    daily = pd.read_parquet(COMPOSITION_DAILY, columns=columns).merge(
        extra, on="date", how="inner", validate="one_to_one"
    )
    daily["year"] = daily["date"].dt.year
    rows: list[dict[str, object]] = []
    quantities = (
        (
            "episode",
            "all_routes",
            "cnt_two_leg_stable",
            "cnt_two_leg_native",
            "additional_count_stable",
            "additional_count_native",
        ),
        (
            "value",
            "within_20pct",
            "usd_within_20pct_two_leg_stable",
            "usd_within_20pct_two_leg_native",
            "additional_value_stable",
            "additional_value_native",
        ),
    )
    for weighting, support, stable, native, add_stable, add_native in quantities:
        for sample_rule, include in (
            ("principal_connected_routes", False),
            ("internally_valid_component_routes", True),
        ):
            stable_quantity = pd.to_numeric(daily[stable], errors="coerce")
            native_quantity = pd.to_numeric(daily[native], errors="coerce")
            if include:
                stable_quantity = stable_quantity + pd.to_numeric(
                    daily[add_stable], errors="coerce"
                )
                native_quantity = native_quantity + pd.to_numeric(
                    daily[add_native], errors="coerce"
                )
            denominator = stable_quantity + native_quantity
            share = stable_quantity / denominator.where(denominator.gt(0))
            estimate = year_endpoint_change(
                share,
                daily["year"],
                baseline_year=BASELINE_YEAR,
                comparison_year=COMPARISON_YEAR,
                hac_lag=HAC_LAG,
                dates=daily["date"],
            )
            rows.append(
                {
                    "record_type": "headline_sensitivity",
                    "sample_rule": sample_rule,
                    "weighting": weighting,
                    "value_support": support,
                    "baseline_year": BASELINE_YEAR,
                    "comparison_year": COMPARISON_YEAR,
                    "baseline_daily_mean": estimate.baseline_mean,
                    "comparison_daily_mean": estimate.comparison_mean,
                    "change": estimate.change,
                    "hac_standard_error": estimate.standard_error,
                    "t_statistic": estimate.t_statistic,
                    "p_value": estimate.p_value,
                    "days": estimate.n_observations,
                    "hac_lag_days": HAC_LAG,
                    "share_denominator": "native_plus_stable_two_leg_vehicle_episodes",
                }
            )
    return pd.DataFrame(rows)


def _select(frame: pd.DataFrame, record_type: str, **criteria: object) -> pd.Series:
    selected = frame[frame["record_type"].eq(record_type)]
    for column, value in criteria.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one {record_type} row for {criteria}; found {len(selected)}")
    return selected.iloc[0]


def render_values(results: pd.DataFrame) -> str:
    annual_2024 = _select(results, "annual_boundary", year=2024)
    annual_2026 = _select(results, "annual_boundary", year=2026)
    v4_2026 = _select(results, "v4_boundary", year=2026, touches_v4=True)
    other_2026 = _select(results, "v4_boundary", year=2026, touches_v4=False)
    count = _select(
        results,
        "headline_sensitivity",
        sample_rule="internally_valid_component_routes",
        weighting="episode",
    )
    value = _select(
        results,
        "headline_sensitivity",
        sample_rule="internally_valid_component_routes",
        weighting="value",
    )

    def pct(value: object) -> str:
        return f"{100 * float(value):.1f}\\%"

    lines = [
        f"\\newcommand{{\\DisconnectedShareBase}}{{{pct(annual_2024['disconnected_component_share'])}}}",
        f"\\newcommand{{\\DisconnectedShareEnd}}{{{pct(annual_2026['disconnected_component_share'])}}}",
        f"\\newcommand{{\\DisconnectedVFourShareEnd}}{{{pct(v4_2026['disconnected_component_share'])}}}",
        f"\\newcommand{{\\DisconnectedOtherShareEnd}}{{{pct(other_2026['disconnected_component_share'])}}}",
        f"\\newcommand{{\\ComponentRouteCountBase}}{{{pct(count['baseline_daily_mean'])}}}",
        f"\\newcommand{{\\ComponentRouteCountEnd}}{{{pct(count['comparison_daily_mean'])}}}",
        f"\\newcommand{{\\ComponentRouteValueBase}}{{{pct(value['baseline_daily_mean'])}}}",
        f"\\newcommand{{\\ComponentRouteValueEnd}}{{{pct(value['comparison_daily_mean'])}}}",
    ]
    return "\n".join(lines) + "\n"


def render_table(results: pd.DataFrame) -> str:
    annual = {
        year: _select(results, "annual_boundary", year=year)
        for year in (2024, 2025, 2026)
    }
    v4 = {
        (year, touches): _select(
            results, "v4_boundary", year=year, touches_v4=touches
        )
        for year in (2025, 2026)
        for touches in (False, True)
    }
    sensitivity = {
        (rule, weighting): _select(
            results,
            "headline_sensitivity",
            sample_rule=rule,
            weighting=weighting,
        )
        for rule in (
            "principal_connected_routes",
            "internally_valid_component_routes",
        )
        for weighting in ("episode", "value")
    }

    def pct(value: object) -> str:
        return f"{100 * float(value):.1f}\\%"

    def change(row: pd.Series) -> str:
        return f"${100 * float(row['change']):+.1f}$ ({100 * float(row['hac_standard_error']):.2f})"

    lines = [
        r"\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}Xrrr@{}}",
        r"\toprule",
        r"Sample boundary or estimate & 2024 & 2025 & 2026 \\",
        r"\midrule",
        r"\multicolumn{4}{l}{\emph{Panel A. Share of reconstructed components excluded}} \\",
        "All components & "
        + pct(annual[2024]["disconnected_component_share"])
        + " & "
        + pct(annual[2025]["disconnected_component_share"])
        + " & "
        + pct(annual[2026]["disconnected_component_share"])
        + r" \\",
        "Components touching Uniswap v4 &  & "
        + pct(v4[(2025, True)]["disconnected_component_share"])
        + " & "
        + pct(v4[(2026, True)]["disconnected_component_share"])
        + r" \\",
        "Other components &  & "
        + pct(v4[(2025, False)]["disconnected_component_share"])
        + " & "
        + pct(v4[(2026, False)]["disconnected_component_share"])
        + r" \\",
        r"\addlinespace",
        r"\multicolumn{4}{l}{\emph{Panel B. Stablecoin share among native and stable two-leg vehicles}} \\",
        r" & 2024 & 2026 & Change [pp] (s.e.) \\",
    ]
    labels = {
        ("principal_connected_routes", "episode"): "Connected routes, count",
        ("principal_connected_routes", "value"): r"Connected routes, value (20\% agreement)",
        ("internally_valid_component_routes", "episode"): "Each valid component, count",
        ("internally_valid_component_routes", "value"): r"Each valid component, value (20\% agreement)",
    }
    for key in labels:
        row = sensitivity[key]
        lines.append(
            labels[key]
            + " & "
            + pct(row["baseline_daily_mean"])
            + " & "
            + pct(row["comparison_daily_mean"])
            + " & "
            + change(row)
            + r" \\"
        )
    lines.extend([r"\bottomrule", r"\end{tabularx}"])
    return "\n".join(lines) + "\n"


def run(*, workers: int = 4) -> pd.DataFrame:
    release = route_partitions(ROUTE_COLUMNS, nonempty=False)
    paths = matched_endpoint_paths(list(release.paths))
    if not paths:
        raise FileNotFoundError("matched 2024 and 2026 unified route files are absent")
    rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=bounded_workers(workers)) as pool:
        futures = {pool.submit(one_day, path): path for path in paths}
        for index, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            if index % 50 == 0:
                print(f"  component sensitivity {index:,}/{len(paths):,}", flush=True)
    extra = pd.DataFrame(rows).sort_values("date", kind="stable")
    results = pd.concat(
        [annual_boundary_summary(), v4_boundary_summary(), headline_sensitivity(extra)],
        ignore_index=True,
        sort=False,
    )
    write_exhibit(
        results,
        RESULT_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
        notes=(
            "Connected-component sample boundary and a component-as-route sensitivity. "
            "The sensitivity retains only internally well-formed components and does "
            "not infer a broader user instruction or an unobserved handoff."
        ),
        preinstall_validator=validate_before_install(release),
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    results = run(workers=args.workers)
    sensitivity = results[results["record_type"].eq("headline_sensitivity")]
    print(sensitivity.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

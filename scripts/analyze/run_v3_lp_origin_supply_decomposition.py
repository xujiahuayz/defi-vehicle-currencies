#!/usr/bin/env python3
"""Decompose the V3 stable-facing LP-supply rotation across provider origins.

The sample contains Uniswap V3 spokes with exactly one of WETH, DAI, USDC,
and USDT.  Stable-stable and stable-WETH core pools are excluded, so the unit
is an origin supplying a candidate vehicle against a noncandidate endpoint.

For 2024 H1 and 2026 H1, the script aggregates positive-liquidity additions by
decoded transaction origin and decomposes the change in the stable share into
three exact midpoint terms: change within continuing origins, reweighting among
continuing origins, and period-specific origin entry or exit.  The last term is
the sum of the common-support-mass and exclusive-origin-share terms in the
four-part identity used by the route-composition analysis.

Two supply quantities are reported: addition actions and screened
candidate-side USD flow.  Transaction origin is a participation proxy rather
than a beneficial-owner identity.  The flow result is withheld when missing
prices and above-screen observations exceed one percent of addition actions in
any period-by-vehicle cell; zero candidate-side additions remain genuine zero
flow rather than valuation failures.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ddvc.paths import DATA_DIR, OUTPUT_DIR
from ddvc.tables import write_exhibit


ORIGIN_INPUT = DATA_DIR / "processed/v3_lp_add_origin_pool_daily.parquet"
DECOMPOSITION_OUTPUT = (
    OUTPUT_DIR / "exhibits/v3_lp_origin_supply_decomposition.jsonl"
)
SUPPORT_OUTPUT = OUTPUT_DIR / "exhibits/v3_lp_origin_supply_support.jsonl"

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
CANDIDATES = (WETH, DAI, USDC, USDT)

BASELINE_PERIOD = "2024H1"
COMPARISON_PERIOD = "2026H1"
BASELINE_START = pd.Timestamp("2024-01-01")
BASELINE_END = pd.Timestamp("2024-07-01")
COMPARISON_START = pd.Timestamp("2026-01-01")
COMPARISON_END = pd.Timestamp("2026-07-01")
MAX_EXCLUDED_VALUATION_ASSIGNMENT_SHARE = 0.01

CODE_SOURCES = ["scripts/analyze/run_v3_lp_origin_supply_decomposition.py"]
INPUTS = ["data/processed/v3_lp_add_origin_pool_daily.parquet"]
REQUIRED_COLUMNS = {
    "origin_date",
    "origin",
    "candidate_address",
    "paired_token_address",
    "v3_add_action_events",
    "v3_add_flow_priced_assignments",
    "v3_add_flow_screened_assignments",
    "v3_add_flow_missing_price_assignments",
    "v3_add_flow_nonpositive_value_assignments",
    "v3_add_flow_above_screen_assignments",
    "v3_add_flow_usd_screened",
}
METRICS = {
    "lp_add_actions": ("stable_add_actions", "WETH_add_actions"),
    "screened_candidate_side_usd_flow": (
        "stable_add_flow_usd",
        "WETH_add_flow_usd",
    ),
}


def _sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def _candidate_sql_values() -> str:
    return ",".join(f"'{address}'" for address in CANDIDATES)


def load_origin_supply_panel(
    path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return origin-period supply, vehicle-network counts, and valuation support."""

    if not path.is_file():
        raise FileNotFoundError(path)
    connection = duckdb.connect()
    try:
        schema = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{_sql_path(path)}')"
        ).fetchdf()
        observed_columns = set(schema["column_name"].astype(str))
        missing = sorted(REQUIRED_COLUMNS - observed_columns)
        if missing:
            raise ValueError(f"V3 origin-supply input lacks columns: {missing}")

        candidates = _candidate_sql_values()
        sample_sql = f"""
        WITH sample AS (
            SELECT
                CASE
                    WHEN CAST(origin_date AS DATE) >= DATE '{BASELINE_START:%Y-%m-%d}'
                     AND CAST(origin_date AS DATE) < DATE '{BASELINE_END:%Y-%m-%d}'
                        THEN '{BASELINE_PERIOD}'
                    WHEN CAST(origin_date AS DATE) >= DATE '{COMPARISON_START:%Y-%m-%d}'
                     AND CAST(origin_date AS DATE) < DATE '{COMPARISON_END:%Y-%m-%d}'
                        THEN '{COMPARISON_PERIOD}'
                END AS period,
                lower(origin) AS origin,
                lower(paired_token_address) AS endpoint,
                CASE WHEN lower(candidate_address) = '{WETH}'
                     THEN 'WETH' ELSE 'stable' END AS vehicle_type,
                v3_add_action_events::DOUBLE AS add_actions,
                v3_add_flow_priced_assignments::DOUBLE AS priced_assignments,
                v3_add_flow_screened_assignments::DOUBLE AS screened_assignments,
                v3_add_flow_missing_price_assignments::DOUBLE
                    AS missing_price_assignments,
                v3_add_flow_nonpositive_value_assignments::DOUBLE
                    AS nonpositive_assignments,
                v3_add_flow_above_screen_assignments::DOUBLE
                    AS above_screen_assignments,
                v3_add_flow_usd_screened::DOUBLE AS add_flow_usd
            FROM read_parquet('{_sql_path(path)}')
            WHERE (
                    (CAST(origin_date AS DATE) >= DATE '{BASELINE_START:%Y-%m-%d}'
                     AND CAST(origin_date AS DATE) < DATE '{BASELINE_END:%Y-%m-%d}')
                 OR (CAST(origin_date AS DATE) >= DATE '{COMPARISON_START:%Y-%m-%d}'
                     AND CAST(origin_date AS DATE) < DATE '{COMPARISON_END:%Y-%m-%d}')
                  )
              AND lower(candidate_address) IN ({candidates})
              AND lower(paired_token_address) NOT IN ({candidates})
              AND origin <> ''
        )
        """
        origin_panel = connection.execute(
            sample_sql
            + """
            SELECT
                period,
                origin,
                coalesce(sum(add_actions) FILTER (
                    WHERE vehicle_type = 'stable'), 0)::DOUBLE
                    AS stable_add_actions,
                coalesce(sum(add_actions) FILTER (
                    WHERE vehicle_type = 'WETH'), 0)::DOUBLE
                    AS WETH_add_actions,
                coalesce(sum(add_flow_usd) FILTER (
                    WHERE vehicle_type = 'stable'), 0)::DOUBLE
                    AS stable_add_flow_usd,
                coalesce(sum(add_flow_usd) FILTER (
                    WHERE vehicle_type = 'WETH'), 0)::DOUBLE
                    AS WETH_add_flow_usd
            FROM sample
            GROUP BY 1,2
            ORDER BY 1,2
            """
        ).fetchdf()
        network = connection.execute(
            sample_sql
            + """
            , origin_counts AS (
                SELECT period, vehicle_type, count(DISTINCT origin) AS active_origins
                FROM sample
                WHERE add_actions > 0
                GROUP BY 1,2
            ), link_counts AS (
                SELECT period, vehicle_type, count(*) AS origin_endpoint_links
                FROM (
                    SELECT DISTINCT period, vehicle_type, origin, endpoint
                    FROM sample
                    WHERE add_actions > 0
                ) links
                GROUP BY 1,2
            ), totals AS (
                SELECT
                    period,
                    vehicle_type,
                    sum(add_actions)::DOUBLE AS add_actions,
                    sum(add_flow_usd)::DOUBLE AS screened_candidate_side_flow_usd,
                    sum(priced_assignments)::DOUBLE AS priced_assignments,
                    sum(screened_assignments)::DOUBLE AS screened_assignments,
                    sum(missing_price_assignments)::DOUBLE
                        AS missing_price_assignments,
                    sum(nonpositive_assignments)::DOUBLE AS nonpositive_assignments,
                    sum(above_screen_assignments)::DOUBLE
                        AS above_screen_assignments
                FROM sample
                GROUP BY 1,2
            )
            SELECT o.period, o.vehicle_type, o.active_origins,
                   l.origin_endpoint_links, t.* EXCLUDE (period, vehicle_type)
            FROM origin_counts o
            JOIN link_counts l USING (period, vehicle_type)
            JOIN totals t USING (period, vehicle_type)
            ORDER BY o.period, o.vehicle_type
            """
        ).fetchdf()
    finally:
        connection.close()

    if origin_panel.empty:
        raise ValueError("V3 origin-supply sample is empty")
    expected_cells = {
        (BASELINE_PERIOD, "stable"),
        (BASELINE_PERIOD, "WETH"),
        (COMPARISON_PERIOD, "stable"),
        (COMPARISON_PERIOD, "WETH"),
    }
    observed_cells = set(zip(network["period"], network["vehicle_type"]))
    if observed_cells != expected_cells:
        raise ValueError(
            "V3 origin-supply sample lacks a period-by-vehicle cell: "
            f"{sorted(expected_cells - observed_cells)}"
        )
    numeric = [column for columns in METRICS.values() for column in columns]
    values = origin_panel[numeric].apply(pd.to_numeric, errors="coerce")
    if values.isna().any().any() or not np.isfinite(values.to_numpy()).all():
        raise ValueError("V3 origin-supply panel contains nonfinite supply")
    if (values < 0).any().any():
        raise ValueError("V3 origin-supply panel contains negative supply")
    origin_panel[numeric] = values

    overlap_rows: list[dict[str, object]] = []
    for period, sample in origin_panel.groupby("period", sort=True):
        stable = sample["stable_add_actions"].gt(0)
        weth = sample["WETH_add_actions"].gt(0)
        overlap_rows.append(
            {
                "record_type": "origin_vehicle_overlap",
                "period": period,
                "active_origin_proxies": int((stable | weth).sum()),
                "stable_only_origin_proxies": int((stable & ~weth).sum()),
                "WETH_only_origin_proxies": int((weth & ~stable).sum()),
                "both_vehicle_origin_proxies": int((stable & weth).sum()),
            }
        )
    return origin_panel, network, pd.DataFrame(overlap_rows)


def valuation_support(network: pd.DataFrame) -> pd.DataFrame:
    """Validate candidate-side flow accounting and apply the declared gate."""

    support = network.copy()
    for column in (
        "add_actions",
        "priced_assignments",
        "screened_assignments",
        "missing_price_assignments",
        "nonpositive_assignments",
        "above_screen_assignments",
        "screened_candidate_side_flow_usd",
    ):
        support[column] = pd.to_numeric(support[column], errors="coerce")
    numeric = support[
        [
            "add_actions",
            "priced_assignments",
            "screened_assignments",
            "missing_price_assignments",
            "nonpositive_assignments",
            "above_screen_assignments",
            "screened_candidate_side_flow_usd",
        ]
    ]
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("V3 origin-supply support contains nonfinite values")
    if (numeric < 0).any().any():
        raise ValueError("V3 origin-supply support contains negative values")
    assignment_error = support["add_actions"] - (
        support["priced_assignments"]
        + support["nonpositive_assignments"]
        + support["missing_price_assignments"]
    )
    screen_error = support["priced_assignments"] - (
        support["screened_assignments"] + support["above_screen_assignments"]
    )
    if not np.allclose(assignment_error, 0.0, atol=1e-9, rtol=0.0):
        raise ValueError("V3 origin-supply assignment counts do not reconcile")
    if not np.allclose(screen_error, 0.0, atol=1e-9, rtol=0.0):
        raise ValueError("V3 origin-supply valuation-screen counts do not reconcile")
    denominator = support["add_actions"].to_numpy(dtype=float)
    if np.any(denominator <= 0):
        raise ValueError("V3 origin-supply valuation cell has no addition actions")
    support["positive_candidate_side_assignment_share"] = (
        support["screened_assignments"] / support["add_actions"]
    )
    support["missing_price_assignment_share"] = (
        support["missing_price_assignments"] / support["add_actions"]
    )
    support["above_screen_assignment_share"] = (
        support["above_screen_assignments"] / support["add_actions"]
    )
    support["excluded_valuation_assignment_share"] = (
        support["missing_price_assignments"]
        + support["above_screen_assignments"]
    ) / support["add_actions"]
    support["flow_reliable"] = support[
        "excluded_valuation_assignment_share"
    ].le(MAX_EXCLUDED_VALUATION_ASSIGNMENT_SHARE)
    support["record_type"] = "origin_vehicle_network_and_valuation_support"
    support["max_excluded_valuation_assignment_share"] = (
        MAX_EXCLUDED_VALUATION_ASSIGNMENT_SHARE
    )
    support["valuation_rule"] = (
        "missing-price plus above-screen assignments divided by addition actions; "
        "nonpositive candidate-side amounts are zero candidate-side flow"
    )
    if not support["flow_reliable"].all():
        failed = support.loc[
            ~support["flow_reliable"],
            ["period", "vehicle_type", "excluded_valuation_assignment_share"],
        ].to_dict("records")
        raise ValueError(
            "screened V3 candidate-side flow fails the declared valuation gate: "
            f"{failed}"
        )
    return support


def exact_origin_decomposition(
    panel: pd.DataFrame,
    *,
    metric: str,
    stable_column: str,
    WETH_column: str,
    baseline_period: str = BASELINE_PERIOD,
    comparison_period: str = COMPARISON_PERIOD,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the exact midpoint composition identity to transaction origins."""

    required = {"period", "origin", stable_column, WETH_column}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"origin decomposition lacks columns: {missing}")
    data = panel[list(required)].copy()
    unknown_periods = sorted(
        set(data["period"].dropna()) - {baseline_period, comparison_period}
    )
    if unknown_periods:
        raise ValueError(f"origin decomposition has unexpected periods: {unknown_periods}")
    for column in (stable_column, WETH_column):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    values = data[[stable_column, WETH_column]]
    if values.isna().any().any() or not np.isfinite(values.to_numpy()).all():
        raise ValueError("origin decomposition contains nonfinite supply")
    if (values < 0).any().any():
        raise ValueError("origin decomposition contains negative supply")
    data = (
        data.groupby(["period", "origin"], as_index=False)[
            [stable_column, WETH_column]
        ]
        .sum()
    )
    baseline = data.loc[data["period"].eq(baseline_period)].drop(columns="period")
    comparison = data.loc[data["period"].eq(comparison_period)].drop(columns="period")
    merged = baseline.merge(
        comparison,
        on="origin",
        how="outer",
        suffixes=("_baseline", "_comparison"),
        validate="one_to_one",
    ).fillna(0.0)
    stable_baseline = f"{stable_column}_baseline"
    stable_comparison = f"{stable_column}_comparison"
    WETH_baseline = f"{WETH_column}_baseline"
    WETH_comparison = f"{WETH_column}_comparison"
    merged["mass_baseline"] = merged[stable_baseline] + merged[WETH_baseline]
    merged["mass_comparison"] = merged[stable_comparison] + merged[WETH_comparison]
    merged = merged.loc[
        merged["mass_baseline"].gt(0) | merged["mass_comparison"].gt(0)
    ].copy()
    total_baseline = float(merged["mass_baseline"].sum())
    total_comparison = float(merged["mass_comparison"].sum())
    if total_baseline <= 0 or total_comparison <= 0:
        raise ValueError("origin decomposition lacks positive mass in an endpoint period")

    positive_baseline = merged["mass_baseline"].gt(0)
    positive_comparison = merged["mass_comparison"].gt(0)
    merged["origin_membership"] = np.select(
        [positive_baseline & positive_comparison, positive_baseline],
        ["continuing", "baseline_exclusive"],
        default="comparison_exclusive",
    )
    for suffix, stable in (
        ("baseline", stable_baseline),
        ("comparison", stable_comparison),
    ):
        merged[f"stable_share_{suffix}"] = np.divide(
            merged[stable],
            merged[f"mass_{suffix}"],
            out=np.zeros(len(merged), dtype=float),
            where=merged[f"mass_{suffix}"].to_numpy() > 0,
        )

    continuing = merged["origin_membership"].eq("continuing")
    baseline_exclusive = merged["origin_membership"].eq("baseline_exclusive")
    comparison_exclusive = merged["origin_membership"].eq("comparison_exclusive")
    common_mass_baseline = float(merged.loc[continuing, "mass_baseline"].sum())
    common_mass_comparison = float(merged.loc[continuing, "mass_comparison"].sum())
    W_baseline = common_mass_baseline / total_baseline
    W_comparison = common_mass_comparison / total_comparison
    E_baseline = 1.0 - W_baseline
    E_comparison = 1.0 - W_comparison
    merged["q_baseline"] = 0.0
    merged["q_comparison"] = 0.0
    if common_mass_baseline > 0:
        merged.loc[continuing, "q_baseline"] = (
            merged.loc[continuing, "mass_baseline"] / common_mass_baseline
        )
    if common_mass_comparison > 0:
        merged.loc[continuing, "q_comparison"] = (
            merged.loc[continuing, "mass_comparison"] / common_mass_comparison
        )
    S_C_baseline = float(
        (
            merged.loc[continuing, "q_baseline"]
            * merged.loc[continuing, "stable_share_baseline"]
        ).sum()
    )
    S_C_comparison = float(
        (
            merged.loc[continuing, "q_comparison"]
            * merged.loc[continuing, "stable_share_comparison"]
        ).sum()
    )
    baseline_exclusive_mass = float(
        merged.loc[baseline_exclusive, "mass_baseline"].sum()
    )
    comparison_exclusive_mass = float(
        merged.loc[comparison_exclusive, "mass_comparison"].sum()
    )
    S_E_baseline = (
        float(merged.loc[baseline_exclusive, stable_baseline].sum())
        / baseline_exclusive_mass
        if baseline_exclusive_mass > 0
        else 0.0
    )
    S_E_comparison = (
        float(merged.loc[comparison_exclusive, stable_comparison].sum())
        / comparison_exclusive_mass
        if comparison_exclusive_mass > 0
        else 0.0
    )

    W_bar = 0.5 * (W_baseline + W_comparison)
    E_bar = 0.5 * (E_baseline + E_comparison)
    q_bar = 0.5 * (merged["q_baseline"] + merged["q_comparison"])
    s_bar = 0.5 * (
        merged["stable_share_baseline"] + merged["stable_share_comparison"]
    )
    within_continuing = float(
        W_bar
        * (
            q_bar[continuing]
            * (
                merged.loc[continuing, "stable_share_comparison"]
                - merged.loc[continuing, "stable_share_baseline"]
            )
        ).sum()
    )
    continuing_reweighting = float(
        W_bar
        * (
            s_bar[continuing]
            * (
                merged.loc[continuing, "q_comparison"]
                - merged.loc[continuing, "q_baseline"]
            )
        ).sum()
    )
    common_support_mass = float(
        (
            0.5 * (S_C_baseline + S_C_comparison)
            - 0.5 * (S_E_baseline + S_E_comparison)
        )
        * (W_comparison - W_baseline)
    )
    exclusive_origin_share_change = float(
        E_bar * (S_E_comparison - S_E_baseline)
    )
    period_specific_entry_exit = common_support_mass + exclusive_origin_share_change
    baseline_stable_share = float(merged[stable_baseline].sum() / total_baseline)
    comparison_stable_share = float(
        merged[stable_comparison].sum() / total_comparison
    )
    total_change = comparison_stable_share - baseline_stable_share
    identity_error = total_change - (
        within_continuing + continuing_reweighting + period_specific_entry_exit
    )
    if not np.isclose(identity_error, 0.0, atol=1e-12, rtol=0.0):
        raise RuntimeError(
            f"V3 origin-supply decomposition identity failed for {metric}: "
            f"{identity_error}"
        )

    result = pd.DataFrame(
        [
            {
                "record_type": "v3_lp_origin_supply_decomposition",
                "metric": metric,
                "baseline_period": baseline_period,
                "comparison_period": comparison_period,
                "baseline_stable_share": baseline_stable_share,
                "comparison_stable_share": comparison_stable_share,
                "total_change": total_change,
                "within_continuing_origin_change": within_continuing,
                "continuing_origin_reweighting": continuing_reweighting,
                "period_specific_origin_entry_exit": period_specific_entry_exit,
                "common_support_mass_subterm": common_support_mass,
                "exclusive_origin_share_change_subterm": (
                    exclusive_origin_share_change
                ),
                "total_change_pp": 100.0 * total_change,
                "within_continuing_origin_change_pp": 100.0 * within_continuing,
                "continuing_origin_reweighting_pp": 100.0
                * continuing_reweighting,
                "period_specific_origin_entry_exit_pp": 100.0
                * period_specific_entry_exit,
                "identity_error": identity_error,
                "W_baseline": W_baseline,
                "W_comparison": W_comparison,
                "S_C_baseline": S_C_baseline,
                "S_C_comparison": S_C_comparison,
                "S_E_baseline": S_E_baseline,
                "S_E_comparison": S_E_comparison,
                "formula_id": "midpoint_continuing_origin_entry_exit_v1",
                "venue_scope": "Uniswap V3",
                "pool_scope": (
                    "spokes with exactly one WETH/DAI/USDC/USDT candidate side"
                ),
                "identity_rule": (
                    "decoded transaction origin is a participation proxy, not a "
                    "wallet-owner or beneficial-owner identity"
                ),
            }
        ]
    )
    support_rows: list[dict[str, object]] = []
    for membership in (
        "continuing",
        "baseline_exclusive",
        "comparison_exclusive",
    ):
        selected = merged.loc[merged["origin_membership"].eq(membership)]
        support_rows.append(
            {
                "record_type": "decomposition_origin_support",
                "metric": metric,
                "origin_membership": membership,
                "origin_proxies": int(len(selected)),
                "baseline_mass": float(selected["mass_baseline"].sum()),
                "comparison_mass": float(selected["mass_comparison"].sum()),
                "baseline_mass_share": float(
                    selected["mass_baseline"].sum() / total_baseline
                ),
                "comparison_mass_share": float(
                    selected["mass_comparison"].sum() / total_comparison
                ),
            }
        )
    return result, pd.DataFrame(support_rows)


def run(
    *,
    origin_path: Path = ORIGIN_INPUT,
    decomposition_output: Path = DECOMPOSITION_OUTPUT,
    support_output: Path = SUPPORT_OUTPUT,
) -> int:
    panel, network, overlap = load_origin_supply_panel(origin_path)
    network_support = valuation_support(network)
    result_frames: list[pd.DataFrame] = []
    decomposition_support: list[pd.DataFrame] = []
    for metric, (stable_column, WETH_column) in METRICS.items():
        result, support = exact_origin_decomposition(
            panel,
            metric=metric,
            stable_column=stable_column,
            WETH_column=WETH_column,
        )
        result_frames.append(result)
        decomposition_support.append(support)
    results = pd.concat(result_frames, ignore_index=True)
    support = pd.concat(
        [network_support, overlap, *decomposition_support],
        ignore_index=True,
        sort=False,
    )
    write_exhibit(
        results,
        decomposition_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    write_exhibit(
        support,
        support_output,
        code_sources=CODE_SOURCES,
        inputs=INPUTS,
    )
    print(
        f"wrote {len(results):,} V3 origin-supply decompositions and "
        f"{len(support):,} support rows"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin-panel", type=Path, default=ORIGIN_INPUT)
    parser.add_argument(
        "--decomposition-output", type=Path, default=DECOMPOSITION_OUTPUT
    )
    parser.add_argument("--support-output", type=Path, default=SUPPORT_OUTPUT)
    args = parser.parse_args()
    return run(
        origin_path=args.origin_panel,
        decomposition_output=args.decomposition_output,
        support_output=args.support_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())

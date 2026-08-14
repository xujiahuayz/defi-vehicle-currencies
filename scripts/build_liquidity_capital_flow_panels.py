#!/usr/bin/env python3
"""Build registered candidate-day and exact-horizon liquidity panels without fitting models."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.capital_release import CapitalRelease, current_capital_release, resolve_capital_release
from ddvc.liquidity_predictability import (
    HORIZONS,
    attach_lookahead_safe_daily_covariates,
    build_candidate_day_panel,
    build_exact_horizon_panel,
    build_v2_candidate_day_panel,
    build_v2_exact_horizon_panel,
    validate_candidate_day_panel,
    validate_exact_horizon_covariates,
    validate_exact_horizon_panel,
    validate_lookahead_safe_daily_covariates,
    validate_v2_candidate_day_panel,
    validate_v2_exact_horizon_panel,
)
from ddvc.paths import REPO_ROOT, TOKEN_PRICE_DAILY_PANEL
from ddvc.provenance import current_artifacts
from ddvc.tables import write_panel


ROUTE_INPUT = REPO_ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"
FLOW_INPUT = REPO_ROOT / "data" / "processed" / "lp_liquidity_flow_daily_v3.parquet"
PRICE_INPUT = TOKEN_PRICE_DAILY_PANEL
CANDIDATE_DAY_OUTPUT = REPO_ROOT / "data" / "processed" / "liquidity_capital_flow_candidate_day.parquet"
EXACT_HORIZON_OUTPUT = REPO_ROOT / "data" / "processed" / "liquidity_capital_flow_exact_horizons.parquet"
V2_CANDIDATE_DAY_OUTPUT = REPO_ROOT / "data" / "processed" / "liquidity_capital_v2_candidate_day.parquet"
V2_EXACT_HORIZON_OUTPUT = REPO_ROOT / "data" / "processed" / "liquidity_capital_v2_exact_horizons.parquet"
CODE_SOURCES = [
    "scripts/build_liquidity_capital_flow_panels.py",
    "src/ddvc/analysis/dynamics.py",
    "src/ddvc/liquidity_predictability.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/capital_contracts.py",
    "src/ddvc/provenance.py",
    "src/ddvc/tables.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--family", choices=("v2", "joint"), default="v2")
    args = parser.parse_args()
    capital_release = resolve_capital_release()
    with current_capital_release(capital_release):
        return _build(args, capital_release)


def _build(args: argparse.Namespace, capital_release: CapitalRelease) -> int:
    """Build one family while the selected capital release remains current."""

    capital_input = capital_release.artifacts["candidate"]
    if args.family == "v2":
        inputs = [ROUTE_INPUT, *capital_release.lineage_paths]
        with current_artifacts(
            [ROUTE_INPUT], consumer="V2 liquidity panel publication"
        ):
            candidate_day = build_v2_candidate_day_panel(
                ROUTE_INPUT,
                capital_input,
                verify_inputs=False,
                memory_limit=args.memory_limit,
                threads=args.threads,
                temp_directory=REPO_ROOT / "data" / "interim" / "liquidity_predictability_v2_duckdb",
            )

            def validate_v2_candidate_output(path: Path) -> None:
                validate_v2_candidate_day_panel(pd.read_parquet(path))

            def validate_v2_horizon_output(path: Path) -> None:
                validate_v2_exact_horizon_panel(pd.read_parquet(path), HORIZONS)

            write_panel(
                candidate_day,
                V2_CANDIDATE_DAY_OUTPUT,
                code_sources=CODE_SOURCES,
                inputs=inputs,
                notes="independent fixed-five-address V2 deposited-capital candidate-day panel; route shares and vehicle excess-use ratios retain all routed tokens on the origin date as their denominator; no V3 rows, columns, proxy, or missing-family zero fill",
                preinstall_validator=validate_v2_candidate_output,
            )
            with current_artifacts(
                [V2_CANDIDATE_DAY_OUTPUT],
                consumer="V2 exact-horizon publication",
            ):
                installed_candidate_day = pd.read_parquet(V2_CANDIDATE_DAY_OUTPUT)
                validate_v2_candidate_day_panel(installed_candidate_day)
                exact_horizons = build_v2_exact_horizon_panel(
                    installed_candidate_day, HORIZONS
                )
                write_panel(
                    exact_horizons,
                    V2_EXACT_HORIZON_OUTPUT,
                    code_sources=CODE_SOURCES,
                    inputs=[*inputs, V2_CANDIDATE_DAY_OUTPUT],
                    notes="independent V2 deposited-capital exact 1/7/30/120-calendar-day links preserving the all-routed-token route denominator; full calendar primary with pre/post heterogeneity; zero fits",
                    preinstall_validator=validate_v2_horizon_output,
                )
        print(
            f"V2 candidate-day rows={len(candidate_day):,}; exact-horizon rows={len(exact_horizons):,}; "
            f"calendar={candidate_day.origin_date.min().date()}..{candidate_day.origin_date.max().date()}; "
            f"horizons={HORIZONS}; fitted models=0",
            flush=True,
        )
        return 0

    family_inputs = [V2_CANDIDATE_DAY_OUTPUT, V2_EXACT_HORIZON_OUTPUT, FLOW_INPUT]
    inputs = [
        ROUTE_INPUT,
        *capital_release.lineage_paths,
        *family_inputs,
        PRICE_INPUT,
    ]
    with current_artifacts(
        [*family_inputs, PRICE_INPUT],
        consumer="optional joint V2-capital/V3-flow liquidity panel builder",
    ):
        validate_v2_candidate_day_panel(pd.read_parquet(V2_CANDIDATE_DAY_OUTPUT))
        validate_v2_exact_horizon_panel(
            pd.read_parquet(V2_EXACT_HORIZON_OUTPUT), HORIZONS
        )
        base_candidate_day = build_candidate_day_panel(
            ROUTE_INPUT,
            capital_input,
            FLOW_INPUT,
            memory_limit=args.memory_limit,
            threads=args.threads,
            temp_directory=REPO_ROOT / "data" / "interim" / "liquidity_predictability_duckdb",
        )
        token_prices = pd.read_parquet(PRICE_INPUT)
        candidate_day = attach_lookahead_safe_daily_covariates(base_candidate_day, token_prices)
        exact_horizons = build_exact_horizon_panel(candidate_day, HORIZONS)

        def validate_candidate_output(path: Path) -> None:
            frame = pd.read_parquet(path)
            validate_candidate_day_panel(frame)
            validate_lookahead_safe_daily_covariates(base_candidate_day, token_prices, frame)

        def validate_horizon_output(path: Path) -> None:
            frame = pd.read_parquet(path)
            validate_exact_horizon_panel(frame, HORIZONS)
            validate_exact_horizon_covariates(candidate_day, frame, HORIZONS)

        write_panel(
            candidate_day,
            CANDIDATE_DAY_OUTPUT,
            code_sources=CODE_SOURCES,
            inputs=inputs,
            notes="fixed five-address candidate-day construction with exact-prior-day price, risk, route, V2 capital, and V3 flow covariates; trailing and pre-shock volatility distinct; support and observed zeros explicit; zero fits",
            preinstall_validator=validate_candidate_output,
        )
        write_panel(
            exact_horizons,
            EXACT_HORIZON_OUTPUT,
            code_sources=CODE_SOURCES,
            inputs=[*inputs, CANDIDATE_DAY_OUTPUT],
            notes="exact 1/7/30/120 calendar-date links, origin covariates preserved at every horizon, and complete future V3 flow windows; no row shifts and zero fits",
            preinstall_validator=validate_horizon_output,
        )
    print(
        f"candidate-day rows={len(candidate_day):,}; exact-horizon rows={len(exact_horizons):,}; "
        f"calendar={candidate_day.origin_date.min().date()}..{candidate_day.origin_date.max().date()}; "
        f"horizons={HORIZONS}; fitted models=0",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build the paper's V2 candidate-day and exact-horizon capital panels."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.capital_data import POOL_CANDIDATE_CAPITAL_DAILY
from ddvc.liquidity_predictability import (
    HORIZONS,
    build_v2_candidate_day_panel,
    build_v2_exact_horizon_panel,
    validate_v2_candidate_day_panel,
    validate_v2_exact_horizon_panel,
)
from ddvc.paths import REPO_ROOT
from ddvc.workflow import current_inputs
from ddvc.tables import write_panel


# These panels are value-stable but not bit-reproducible. The capital columns are
# DuckDB parallel float sums, so the reduction order varies between runs and the
# installed bytes move even when every input is byte-identical. Measured on two
# consecutive runs off one capital release (2026-08-16): max relative difference
# 3.3e-15 on the candidate-day levels and shares (24 ULP), and 4.5e-10 on the
# horizon change columns, where differencing two near-equal shares amplifies it.
# Nothing at that scale can reach an estimand, a coefficient, or an inference, so
# a byte difference here is not evidence that the panel changed. Read it as
# "rebuilt", not "revised", and compare values before treating it as a finding.
ROUTE_INPUT = REPO_ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"
V2_CANDIDATE_DAY_OUTPUT = REPO_ROOT / "data" / "processed" / "liquidity_capital_v2_candidate_day.parquet"
V2_EXACT_HORIZON_OUTPUT = REPO_ROOT / "data" / "processed" / "liquidity_capital_v2_exact_horizons.parquet"
CODE_SOURCES = [
    "scripts/process/build_liquidity_capital_flow_panels.py",
    "src/ddvc/liquidity_predictability.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/capital_contracts.py",
    "src/ddvc/capital_data.py",
    "src/ddvc/tables.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    return _build(args)


def _build(args: argparse.Namespace) -> int:
    """Build one family from the direct processed capital panel."""

    capital_input = POOL_CANDIDATE_CAPITAL_DAILY
    inputs = [ROUTE_INPUT, capital_input]
    with current_inputs(inputs, consumer="V2 liquidity panel publication"):
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
            notes="fixed-five-address V2 deposited-capital candidate-day panel; route shares and vehicle excess-use ratios retain all routed tokens on the origin date as their denominator",
            preinstall_validator=validate_v2_candidate_output,
        )
        with current_inputs(
            [V2_CANDIDATE_DAY_OUTPUT], consumer="V2 exact-horizon publication"
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
                notes="V2 deposited-capital exact 1/7/30/120-calendar-day links preserving the all-routed-token route denominator",
                preinstall_validator=validate_v2_horizon_output,
            )
    print(
        f"V2 candidate-day rows={len(candidate_day):,}; exact-horizon rows={len(exact_horizons):,}; "
        f"calendar={candidate_day.origin_date.min().date()}..{candidate_day.origin_date.max().date()}; "
        f"horizons={HORIZONS}; fitted models=0",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

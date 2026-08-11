#!/usr/bin/env python3
"""Build registered candidate-day and exact-horizon liquidity panels without fitting models."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.liquidity_predictability import (
    HORIZONS,
    attach_lookahead_safe_daily_covariates,
    build_candidate_day_panel,
    build_exact_horizon_panel,
    validate_candidate_day_panel,
    validate_exact_horizon_covariates,
    validate_exact_horizon_panel,
    validate_lookahead_safe_daily_covariates,
)
from ddvc.paths import REPO_ROOT, TOKEN_PRICE_DAILY_PANEL
from ddvc.provenance import require_current_artifacts
from ddvc.tables import write_panel


ROUTE_INPUT = REPO_ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"
CAPITAL_INPUT = REPO_ROOT / "data" / "processed" / "pool_candidate_capital_daily.parquet"
FLOW_INPUT = REPO_ROOT / "data" / "processed" / "lp_liquidity_flow_daily_v3.parquet"
PRICE_INPUT = TOKEN_PRICE_DAILY_PANEL
CANDIDATE_DAY_OUTPUT = REPO_ROOT / "data" / "processed" / "liquidity_capital_flow_candidate_day.parquet"
EXACT_HORIZON_OUTPUT = REPO_ROOT / "data" / "processed" / "liquidity_capital_flow_exact_horizons.parquet"
CODE_SOURCES = [
    "scripts/build_liquidity_capital_flow_panels.py",
    "src/ddvc/analysis/dynamics.py",
    "src/ddvc/liquidity_predictability.py",
    "src/ddvc/asset_types.py",
    "src/ddvc/capital_contracts.py",
    "src/ddvc/provenance.py",
    "src/ddvc/tables.py",
]
INPUTS = [ROUTE_INPUT, CAPITAL_INPUT, FLOW_INPUT, PRICE_INPUT]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    base_candidate_day = build_candidate_day_panel(
        ROUTE_INPUT,
        CAPITAL_INPUT,
        FLOW_INPUT,
        memory_limit=args.memory_limit,
        threads=args.threads,
        temp_directory=REPO_ROOT / "data" / "interim" / "liquidity_predictability_duckdb",
    )
    require_current_artifacts([PRICE_INPUT], consumer="liquidity covariate builder")
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
        inputs=INPUTS,
        notes="fixed five-address candidate-day construction with exact-prior-day price, risk, route, V2 capital, and V3 flow covariates; trailing and pre-shock volatility distinct; support and observed zeros explicit; zero fits",
        preinstall_validator=validate_candidate_output,
    )
    write_panel(
        exact_horizons,
        EXACT_HORIZON_OUTPUT,
        code_sources=CODE_SOURCES,
        inputs=[*INPUTS, CANDIDATE_DAY_OUTPUT],
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

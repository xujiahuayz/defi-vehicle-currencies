"""Canonical constants shared by routing panel builders and estimators."""

from __future__ import annotations

from ddvc.analysis.dynamics import CANONICAL_RESPONSE_HORIZONS


PRIMARY_YEARS = (2021, 2022, 2023, 2024, 2025)
MIN_PRIMARY_YEAR_CHOSEN_VERIFIED_COVERAGE = 0.80
MAX_PRIMARY_YEAR_CHOSEN_VERIFIED_COVERAGE_SPREAD = 0.10
TRANSITION_YEARS = (2024, 2026)
REPRODUCTION_TOLERANCES_BPS = (1.0, 0.1, 0.01)
TRANSITION_REPRODUCTION_TOLERANCE_BPS = 1.0
HORIZONS_DAYS = CANONICAL_RESPONSE_HORIZONS
MARGINS = (
    "within_reach_search_regret",
    "reach_increment",
    "path_choice_increment",
    "public_path_regret",
)
REGRET_MARGINS_BPS = tuple(f"{margin}_bps" for margin in MARGINS)
REGRET_BIN_COLUMNS = (
    "within_reach_regret_bin",
    "reach_increment_bin",
    "path_choice_increment_bin",
)
REGRET_THRESHOLDS_BPS = (0.01, 1.0, 10.0)
REGRET_BIN_LEVELS = (
    "b1_0_0p01",
    "b2_0p01_1",
    "b3_1_10",
    "b4_above_10",
)

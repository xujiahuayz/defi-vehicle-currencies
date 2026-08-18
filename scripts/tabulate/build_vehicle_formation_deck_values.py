#!/usr/bin/env python3
"""Build presentation macros from the vehicle-formation exploration exhibit."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_presentation_source
from ddvc.runtime import atomic_output


ESTIMATES = OUTPUT_DIR / "exhibits/vehicle_formation_exploration.jsonl"
DECK_VALUES = OUTPUT_DIR / "exhibits/vehicle_formation_deck_values.tex"
CODE_SOURCES = ["scripts/tabulate/build_vehicle_formation_deck_values.py"]


def _pct(value: float, decimals: int = 1) -> str:
    return f"{100 * value:.{decimals}f}\\%"


def _signed_pp(value: float, decimals: int = 1) -> str:
    points = 100 * value
    if abs(points) < 0.5 * 10 ** (-decimals):
        return f"${0:.{decimals}f}$ pp"
    return f"${points:+.{decimals}f}$ pp"


def _unsigned_pp(value: float, decimals: int = 1) -> str:
    return f"${100 * value:.{decimals}f}$ pp"


def _int(value: int | float) -> str:
    return f"{int(value):,}".replace(",", "{,}")


def _one(frame: pd.DataFrame, **selectors: object) -> pd.Series:
    selected = frame.copy()
    for column, value in selectors.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one formation row for {selectors}; found {len(selected)}")
    return selected.iloc[0]


def render_vehicle_formation_deck_values(estimates: pd.DataFrame) -> str:
    required = {"record_type", "entry_year", "stable_share", "primary_routes"}
    missing = sorted(required - set(estimates.columns))
    if missing:
        raise ValueError(f"formation exhibit missing columns: {', '.join(missing)}")
    cohort_2024 = _one(estimates, record_type="entry_cohort", entry_year=2024)
    cohort_2026 = _one(estimates, record_type="entry_cohort", entry_year=2026)
    native_2026_30 = _one(
        estimates,
        record_type="entry_persistence",
        horizon_days=30,
        entry_year=2026,
        entry_type="native_only_entry",
    )
    stable_2026_30 = _one(
        estimates,
        record_type="entry_persistence",
        horizon_days=30,
        entry_year=2026,
        entry_type="stable_dominant_entry",
    )
    contrast_2026_30 = _one(
        estimates,
        record_type="entry_persistence_contrast",
        horizon_days=30,
        entry_year=2026,
    )
    stable_2024_120 = _one(
        estimates,
        record_type="entry_persistence",
        horizon_days=120,
        entry_year=2024,
        entry_type="stable_dominant_entry",
    )
    stable_2026_120 = _one(
        estimates,
        record_type="entry_persistence",
        horizon_days=120,
        entry_year=2026,
        entry_type="stable_dominant_entry",
    )
    contrast_2026_120 = _one(
        estimates,
        record_type="entry_persistence_contrast",
        horizon_days=120,
        entry_year=2026,
    )
    path_share_30 = _one(
        estimates,
        record_type="entry_path_dependence_regression",
        horizon_days=30,
        sample="non_weth_endpoint",
        outcome="stable_share",
        predictor="entry_stable_share",
    )
    path_share_120 = _one(
        estimates,
        record_type="entry_path_dependence_regression",
        horizon_days=120,
        sample="non_weth_endpoint",
        outcome="stable_share",
        predictor="entry_stable_share",
    )
    path_dominant_120 = _one(
        estimates,
        record_type="entry_path_dependence_regression",
        horizon_days=120,
        sample="non_weth_endpoint",
        outcome="stable_dominant_followup",
        predictor="entry_stable_dominant",
    )
    stable_hysteresis_2026_30 = _one(
        estimates,
        record_type="entry_regime_hysteresis",
        horizon_days=30,
        entry_year=2026,
        entry_type="stable_dominant_entry",
    )
    stable_hysteresis_2026_120 = _one(
        estimates,
        record_type="entry_regime_hysteresis",
        horizon_days=120,
        entry_year=2026,
        entry_type="stable_dominant_entry",
    )
    non_weth_2024 = _one(
        estimates,
        record_type="entry_endpoint_class",
        entry_year=2024,
        endpoint_class="non_weth_endpoint",
    )
    non_weth_2026 = _one(
        estimates,
        record_type="entry_endpoint_class",
        entry_year=2026,
        endpoint_class="non_weth_endpoint",
    )
    weth_2026 = _one(
        estimates,
        record_type="entry_endpoint_class",
        entry_year=2026,
        endpoint_class="weth_endpoint",
    )
    usdc_2026_entry = _one(
        estimates,
        record_type="entry_stable_candidate",
        entry_year=2026,
        candidate_symbol="USDC",
    )
    usdt_2026_entry = _one(
        estimates,
        record_type="entry_stable_candidate",
        entry_year=2026,
        candidate_symbol="USDT",
    )
    usdc_2026_own_30 = _one(
        estimates,
        record_type="entry_stable_candidate_persistence",
        horizon_days=30,
        entry_year=2026,
        entry_candidate_symbol="USDC",
    )
    usdt_2026_own_30 = _one(
        estimates,
        record_type="entry_stable_candidate_persistence",
        horizon_days=30,
        entry_year=2026,
        entry_candidate_symbol="USDT",
    )
    usdc_2026_own_120 = _one(
        estimates,
        record_type="entry_stable_candidate_persistence",
        horizon_days=120,
        entry_year=2026,
        entry_candidate_symbol="USDC",
    )
    usdt_2026_own_120 = _one(
        estimates,
        record_type="entry_stable_candidate_persistence",
        horizon_days=120,
        entry_year=2026,
        entry_candidate_symbol="USDT",
    )
    non_weth_year_driver = _one(
        estimates,
        record_type="entry_driver_regression",
        endpoint_class="non_weth_endpoint",
        outcome="stable_share",
        predictor="is_2026",
    )
    non_weth_stable_endpoint_driver = _one(
        estimates,
        record_type="entry_driver_regression",
        endpoint_class="non_weth_endpoint",
        outcome="stable_share",
        predictor="is_2026_x_stable_endpoint",
    )
    route_direct_2026_driver = _one(
        estimates,
        record_type="entry_route_architecture_regression",
        endpoint_class="non_weth_endpoint",
        outcome="stable_share",
        predictor="is_2026_x_direct_share",
    )
    route_complex_2026_driver = _one(
        estimates,
        record_type="entry_route_architecture_regression",
        endpoint_class="non_weth_endpoint",
        outcome="stable_share",
        predictor="is_2026_x_complex_share",
    )
    secure_stable_2026 = _one(
        estimates,
        record_type="entry_secure_volume_class",
        entry_year=2026,
        secure_volume_class="stable_endpoint",
    )
    secure_other_2026 = _one(
        estimates,
        record_type="entry_secure_volume_class",
        entry_year=2026,
        secure_volume_class="other_non_weth_endpoint",
    )
    secure_gap_change = _one(
        estimates,
        record_type="entry_secure_volume_gap_change",
        baseline_year=2024,
        comparison_year=2026,
    )
    secure_volume_driver = _one(
        estimates,
        record_type="entry_secure_volume_regression",
        endpoint_class="non_weth_endpoint",
        outcome="stable_share",
        predictor="is_2026_x_stable_endpoint",
    )
    values = [
        float(cohort_2024["stable_share"]),
        float(cohort_2026["stable_share"]),
        float(native_2026_30["stable_share"]),
        float(stable_2026_30["stable_share"]),
        float(contrast_2026_30["coefficient"]),
        float(contrast_2026_30["standard_error"]),
        float(stable_2024_120["stable_share"]),
        float(stable_2026_120["stable_share"]),
        float(contrast_2026_120["coefficient"]),
        float(contrast_2026_120["standard_error"]),
        float(path_share_30["coefficient_per_10pp_entry_share"]),
        float(path_share_120["coefficient_per_10pp_entry_share"]),
        float(path_dominant_120["coefficient"]),
        float(stable_hysteresis_2026_30["never_left_share_retrade"]),
        float(stable_hysteresis_2026_120["never_left_share_retrade"]),
        float(stable_hysteresis_2026_30["mean_stable_majority_day_share"]),
        float(stable_hysteresis_2026_120["mean_stable_majority_day_share"]),
        float(non_weth_2024["stable_share"]),
        float(non_weth_2026["stable_share"]),
        float(weth_2026["route_mass_share"]),
        float(usdc_2026_entry["stable_entry_route_share"]),
        float(usdt_2026_entry["stable_entry_route_share"]),
        float(usdc_2026_own_30["own_candidate_followup_share"]),
        float(usdt_2026_own_30["own_candidate_followup_share"]),
        float(usdc_2026_own_120["own_candidate_followup_share"]),
        float(usdt_2026_own_120["own_candidate_followup_share"]),
        float(non_weth_year_driver["coefficient"]),
        float(non_weth_stable_endpoint_driver["coefficient"]),
        float(route_direct_2026_driver["coefficient"]),
        float(route_complex_2026_driver["coefficient"]),
        float(secure_stable_2026["stable_share"]),
        float(secure_other_2026["stable_share"]),
        float(secure_stable_2026["route_mass_share"]),
        float(secure_gap_change["gap_change"]),
        float(secure_volume_driver["coefficient"]),
    ]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("formation deck values contain nonfinite cells")
    if not float(non_weth_2026["stable_share"]) > float(non_weth_2024["stable_share"]):
        raise ValueError("non-WETH entry stable share no longer rises")
    if not (
        float(path_share_30["coefficient_per_10pp_entry_share"]) > 0.05
        and float(path_share_120["coefficient_per_10pp_entry_share"]) > 0.05
        and float(path_dominant_120["coefficient"]) > 0.40
        and float(path_share_30["p_value"]) < 0.01
        and float(path_share_120["p_value"]) < 0.01
        and float(path_dominant_120["p_value"]) < 0.01
    ):
        raise ValueError("entry path-dependence screen no longer holds")
    if not (
        float(non_weth_year_driver["coefficient"]) > 0
        and float(non_weth_stable_endpoint_driver["coefficient"]) > 0
    ):
        raise ValueError("non-WETH entry-driver coefficients are no longer positive")
    if not (
        float(route_direct_2026_driver["coefficient"]) > 0
        and float(route_complex_2026_driver["coefficient"]) > 0
        and float(route_direct_2026_driver["p_value"]) < 0.01
        and float(route_complex_2026_driver["p_value"]) < 0.01
    ):
        raise ValueError("2026 route-architecture entry-driver pattern no longer holds")
    if not (
        float(secure_stable_2026["stable_share"])
        > float(secure_other_2026["stable_share"])
        and float(secure_gap_change["gap_change"]) > 0
        and float(secure_volume_driver["coefficient"]) > 0
        and float(secure_volume_driver["p_value"]) < 0.05
    ):
        raise ValueError("stable-endpoint secure-volume entry pattern no longer holds")
    top_two_stable_entry_share = float(usdc_2026_entry["stable_entry_route_share"]) + float(
        usdt_2026_entry["stable_entry_route_share"]
    )
    if not (
        float(usdc_2026_entry["stable_entry_route_share"]) > 0.70
        and top_two_stable_entry_share > 0.99
    ):
        raise ValueError("USDC/USDT no longer dominate 2026 stable-entry routes")
    if not (
        float(usdc_2026_own_30["own_candidate_followup_share"]) > 0.85
        and float(usdt_2026_own_30["own_candidate_followup_share"]) > 0.75
        and float(usdc_2026_own_120["own_candidate_followup_share"]) > 0.85
        and float(usdt_2026_own_120["own_candidate_followup_share"]) > 0.85
    ):
        raise ValueError("USDC/USDT stable-entry candidate identity no longer persists")
    if not (
        float(stable_hysteresis_2026_30["never_left_share_retrade"]) > 0.90
        and float(stable_hysteresis_2026_120["never_left_share_retrade"]) > 0.90
        and float(stable_hysteresis_2026_30["mean_stable_majority_day_share"]) > 0.98
        and float(stable_hysteresis_2026_120["mean_stable_majority_day_share"]) > 0.98
    ):
        raise ValueError("stable-born active-day regime hysteresis no longer holds")
    lines = [
        "% Generated by scripts/tabulate/build_vehicle_formation_deck_values.py; do not edit.",
        f"\\newcommand{{\\FormationEntryStableShareBase}}{{{_pct(float(cohort_2024['stable_share']))}}}",
        f"\\newcommand{{\\FormationEntryStableShareEnd}}{{{_pct(float(cohort_2026['stable_share']))}}}",
        f"\\newcommand{{\\FormationEntryPairsEnd}}{{{_int(cohort_2026['pairs'])}}}",
        f"\\newcommand{{\\FormationThirtyNativeBirthStableShare}}{{{_pct(float(native_2026_30['stable_share']))}}}",
        f"\\newcommand{{\\FormationThirtyStableBirthStableShare}}{{{_pct(float(stable_2026_30['stable_share']))}}}",
        f"\\newcommand{{\\FormationThirtyStableBirthPairs}}{{{_int(stable_2026_30['pairs'])}}}",
        f"\\newcommand{{\\FormationThirtyPersistenceGap}}{{{_signed_pp(float(contrast_2026_30['coefficient']))}}}",
        f"\\newcommand{{\\FormationThirtyPersistenceSE}}{{{_unsigned_pp(float(contrast_2026_30['standard_error']))}}}",
        f"\\newcommand{{\\FormationStableBirthShareOneTwentyBase}}{{{_pct(float(stable_2024_120['stable_share']))}}}",
        f"\\newcommand{{\\FormationStableBirthShareOneTwentyEnd}}{{{_pct(float(stable_2026_120['stable_share']))}}}",
        f"\\newcommand{{\\FormationOneTwentyPersistenceGap}}{{{_signed_pp(float(contrast_2026_120['coefficient']))}}}",
        f"\\newcommand{{\\FormationOneTwentyPersistenceSE}}{{{_unsigned_pp(float(contrast_2026_120['standard_error']))}}}",
        f"\\newcommand{{\\FormationPathDependenceRows}}{{{_int(path_share_30['observations'])}}}",
        f"\\newcommand{{\\FormationPathEntryShareThirtyCoef}}{{{_signed_pp(float(path_share_30['coefficient_per_10pp_entry_share']))}}}",
        f"\\newcommand{{\\FormationPathEntryShareThirtySE}}{{{_unsigned_pp(float(path_share_30['standard_error_per_10pp_entry_share']))}}}",
        f"\\newcommand{{\\FormationPathEntryShareOneTwentyCoef}}{{{_signed_pp(float(path_share_120['coefficient_per_10pp_entry_share']))}}}",
        f"\\newcommand{{\\FormationPathEntryShareOneTwentySE}}{{{_unsigned_pp(float(path_share_120['standard_error_per_10pp_entry_share']))}}}",
        f"\\newcommand{{\\FormationPathDominantOneTwentyCoef}}{{{_signed_pp(float(path_dominant_120['coefficient']))}}}",
        f"\\newcommand{{\\FormationPathDominantOneTwentySE}}{{{_unsigned_pp(float(path_dominant_120['standard_error']))}}}",
        f"\\newcommand{{\\FormationStableHysteresisThirtyRetrade}}{{{_pct(float(stable_hysteresis_2026_30['never_left_share_retrade']))}}}",
        f"\\newcommand{{\\FormationStableHysteresisOneTwentyRetrade}}{{{_pct(float(stable_hysteresis_2026_120['never_left_share_retrade']))}}}",
        f"\\newcommand{{\\FormationStableHysteresisThirtyDayShare}}{{{_pct(float(stable_hysteresis_2026_30['mean_stable_majority_day_share']))}}}",
        f"\\newcommand{{\\FormationStableHysteresisOneTwentyDayShare}}{{{_pct(float(stable_hysteresis_2026_120['mean_stable_majority_day_share']))}}}",
        f"\\newcommand{{\\FormationStableHysteresisThirtyPairs}}{{{_int(stable_hysteresis_2026_30['pairs_trading_again'])}}}",
        f"\\newcommand{{\\FormationStableHysteresisOneTwentyPairs}}{{{_int(stable_hysteresis_2026_120['pairs_trading_again'])}}}",
        f"\\newcommand{{\\FormationNonWethEntryStableShareBase}}{{{_pct(float(non_weth_2024['stable_share']))}}}",
        f"\\newcommand{{\\FormationNonWethEntryStableShareEnd}}{{{_pct(float(non_weth_2026['stable_share']))}}}",
        f"\\newcommand{{\\FormationWethEntryRouteMassEnd}}{{{_pct(float(weth_2026['route_mass_share']))}}}",
        f"\\newcommand{{\\FormationStableEntryUSDCShareEnd}}{{{_pct(float(usdc_2026_entry['stable_entry_route_share']))}}}",
        f"\\newcommand{{\\FormationStableEntryUSDTShareEnd}}{{{_pct(float(usdt_2026_entry['stable_entry_route_share']))}}}",
        f"\\newcommand{{\\FormationStableEntryTopTwoShareEnd}}{{{_pct(top_two_stable_entry_share)}}}",
        f"\\newcommand{{\\FormationUSDCEntryOwnThirty}}{{{_pct(float(usdc_2026_own_30['own_candidate_followup_share']))}}}",
        f"\\newcommand{{\\FormationUSDTEntryOwnThirty}}{{{_pct(float(usdt_2026_own_30['own_candidate_followup_share']))}}}",
        f"\\newcommand{{\\FormationUSDCEntryOwnOneTwenty}}{{{_pct(float(usdc_2026_own_120['own_candidate_followup_share']))}}}",
        f"\\newcommand{{\\FormationUSDTEntryOwnOneTwenty}}{{{_pct(float(usdt_2026_own_120['own_candidate_followup_share']))}}}",
        f"\\newcommand{{\\FormationNonWethYearDriver}}{{{_signed_pp(float(non_weth_year_driver['coefficient']))}}}",
        f"\\newcommand{{\\FormationNonWethYearDriverSE}}{{{_unsigned_pp(float(non_weth_year_driver['standard_error']))}}}",
        f"\\newcommand{{\\FormationNonWethStableEndpointDriver}}{{{_signed_pp(float(non_weth_stable_endpoint_driver['coefficient']))}}}",
        f"\\newcommand{{\\FormationNonWethStableEndpointDriverSE}}{{{_unsigned_pp(float(non_weth_stable_endpoint_driver['standard_error']))}}}",
        f"\\newcommand{{\\FormationRouteArchDirectShareDriver}}{{{_signed_pp(float(route_direct_2026_driver['coefficient']))}}}",
        f"\\newcommand{{\\FormationRouteArchDirectShareDriverSE}}{{{_unsigned_pp(float(route_direct_2026_driver['standard_error']))}}}",
        f"\\newcommand{{\\FormationRouteArchComplexShareDriver}}{{{_signed_pp(float(route_complex_2026_driver['coefficient']))}}}",
        f"\\newcommand{{\\FormationRouteArchComplexShareDriverSE}}{{{_unsigned_pp(float(route_complex_2026_driver['standard_error']))}}}",
        f"\\newcommand{{\\FormationSecureStableEndpointShareEnd}}{{{_pct(float(secure_stable_2026['stable_share']))}}}",
        f"\\newcommand{{\\FormationSecureOtherEndpointShareEnd}}{{{_pct(float(secure_other_2026['stable_share']))}}}",
        f"\\newcommand{{\\FormationSecureStableEndpointMassEnd}}{{{_pct(float(secure_stable_2026['route_mass_share']))}}}",
        f"\\newcommand{{\\FormationSecureGapChange}}{{{_signed_pp(float(secure_gap_change['gap_change']))}}}",
        f"\\newcommand{{\\FormationSecureVolumeDriver}}{{{_signed_pp(float(secure_volume_driver['coefficient']))}}}",
        f"\\newcommand{{\\FormationSecureVolumeDriverSE}}{{{_unsigned_pp(float(secure_volume_driver['standard_error']))}}}",
    ]
    return "\n".join(lines) + "\n"


def run(*, estimates_path: Path = ESTIMATES, output_path: Path = DECK_VALUES) -> int:
    require_presentation_source(estimates_path)
    estimates = pd.read_json(estimates_path, lines=True)
    rendered = render_vehicle_formation_deck_values(estimates)
    with atomic_output(output_path) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimates", type=Path, default=ESTIMATES)
    parser.add_argument("--output", type=Path, default=DECK_VALUES)
    args = parser.parse_args()
    return run(estimates_path=args.estimates, output_path=args.output)


if __name__ == "__main__":
    raise SystemExit(main())

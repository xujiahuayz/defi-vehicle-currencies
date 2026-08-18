#!/usr/bin/env python3
"""Build paper/deck macros from the vehicle-dominance mechanism sweep."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR
from ddvc.presentation import require_presentation_source
from ddvc.runtime import atomic_output


ESTIMATES = OUTPUT_DIR / "exhibits/vehicle_dominance_mechanism_sweep.jsonl"
SUPPORT = OUTPUT_DIR / "exhibits/vehicle_dominance_mechanism_support.jsonl"
DECK_VALUES = OUTPUT_DIR / "exhibits/vehicle_mechanism_sweep_deck_values.tex"


def _single(frame: pd.DataFrame, **conditions: object) -> pd.Series:
    selected = frame
    for column, value in conditions.items():
        selected = selected[selected[column].eq(value)]
    if len(selected) != 1:
        raise ValueError(f"expected one row for {conditions}; found {len(selected)}")
    return selected.iloc[0]


def _integer(value: int) -> str:
    return f"{value:,}".replace(",", "{,}")


def _signed_pp(value: float, decimals: int = 1) -> str:
    if abs(value) < 0.5 * 10 ** (-decimals):
        return f"${0:.{decimals}f}$ pp"
    return f"${value:+.{decimals}f}$ pp"


def _unsigned_pp(value: float, decimals: int = 1) -> str:
    return f"${value:.{decimals}f}$ pp"


def _pct(value: float, decimals: int = 1) -> str:
    return f"{100.0 * value:.{decimals}f}\\%"


def _effect(
    estimates: pd.DataFrame,
    *,
    model_id: str,
    regressor: str,
) -> pd.Series:
    return _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="count_share",
        model_id=model_id,
        regressor=regressor,
    )


def _risk_set_summary(
    estimates: pd.DataFrame,
    *,
    year: int,
    min_total_routes: int = 5,
) -> pd.Series:
    return _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="candidate_route_share",
        model_id="mixed_native_stable_risk_set_summary",
        min_total_routes=min_total_routes,
        year=year,
    )


def _risk_set_effect(
    estimates: pd.DataFrame,
    *,
    regressor: str,
    min_total_routes: int = 5,
) -> pd.Series:
    return _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="candidate_route_share",
        model_id="mixed_native_stable_risk_set_fe",
        min_total_routes=min_total_routes,
        regressor=regressor,
    )


def _hazard_effect(
    estimates: pd.DataFrame,
    *,
    outcome: str,
    regressor: str,
) -> pd.Series:
    return _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="native_only_pair_day_stable_turn_on",
        model_id="stable_turn_on_hazard_fe",
        outcome=outcome,
        regressor=regressor,
    )


def _hazard_decile(estimates: pd.DataFrame, *, regressor: str) -> pd.Series:
    return _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="native_only_pair_day_stable_turn_on",
        model_id="stable_turn_on_hazard_decile",
        outcome="future_stable_turn_on",
        regressor=regressor,
    )


def _hazard_summary(
    estimates: pd.DataFrame,
    *,
    year: int,
    stable_endpoint: bool,
) -> pd.Series:
    return _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="native_only_pair_day_stable_turn_on",
        model_id="stable_turn_on_hazard_summary",
        year=year,
        stable_endpoint=stable_endpoint,
    )


def render_vehicle_mechanism_sweep_deck_values(
    estimates: pd.DataFrame, support: pd.DataFrame
) -> str:
    """Return guarded LaTeX macros for the mechanism-sweep headline."""

    support_row = _single(
        support,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="count_share",
    )
    hazard_support = _single(
        support,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="native_only_pair_day_stable_turn_on",
        model_id="stable_turn_on_hazard",
    )
    turn_on_thin = _effect(
        estimates,
        model_id="turn_on_lpm",
        regressor="baseline_log_market_routes",
    )
    turn_on_direct = _effect(
        estimates,
        model_id="turn_on_lpm",
        regressor="baseline_direct_route_share",
    )
    turn_on_complex = _effect(
        estimates,
        model_id="turn_on_lpm",
        regressor="baseline_complex_route_share",
    )
    turn_on_direct_x_thin = _effect(
        estimates,
        model_id="turn_on_direct_thin_interaction",
        regressor="baseline_direct_x_thin",
    )
    leader_thin = _effect(
        estimates,
        model_id="leader_switch_lpm",
        regressor="baseline_log_market_routes",
    )
    single_stable_persistence = _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="count_share",
        model_id="regime_persistence",
        integration_scope="single_venue",
        baseline_regime="stable_majority",
    )
    single_native_persistence = _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="count_share",
        model_id="regime_persistence",
        integration_scope="single_venue",
        baseline_regime="native_majority",
    )
    cross_stable_persistence = _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="count_share",
        model_id="regime_persistence",
        integration_scope="cross_venue",
        baseline_regime="stable_majority",
    )
    cross_native_persistence = _single(
        estimates,
        claim_status="provisional_exploratory",
        experiment_family="vehicle_dominance_mechanism_sweep",
        metric="count_share",
        model_id="regime_persistence",
        integration_scope="cross_venue",
        baseline_regime="native_majority",
    )
    risk_set_base = _risk_set_summary(estimates, year=2024)
    risk_set_end = _risk_set_summary(estimates, year=2026)
    risk_set_stable_penalty = _risk_set_effect(estimates, regressor="is_stable")
    risk_set_stable_2026 = _risk_set_effect(
        estimates, regressor="is_stable_x_2026"
    )
    hazard_thick = _hazard_decile(estimates, regressor="log_market_routes")
    hazard_age = _hazard_decile(estimates, regressor="pair_age_log")
    hazard_log_market = _hazard_effect(
        estimates,
        outcome="future_stable_turn_on",
        regressor="log_market_routes",
    )
    hazard_pair_age = _hazard_effect(
        estimates,
        outcome="future_stable_turn_on",
        regressor="pair_age_log",
    )
    hazard_plain_2026 = _hazard_summary(
        estimates,
        year=2026,
        stable_endpoint=False,
    )
    hazard_stable_2026 = _hazard_summary(
        estimates,
        year=2026,
        stable_endpoint=True,
    )
    if not (
        float(turn_on_thin["coefficient_pp"]) < 0
        and float(leader_thin["coefficient_pp"]) < 0
        and float(turn_on_direct["coefficient_pp"]) > 0
        and float(turn_on_complex["coefficient_pp"]) > 0
        and float(turn_on_direct_x_thin["coefficient_pp"]) > 0
        and float(single_stable_persistence["coefficient"]) > 0.9
        and float(single_native_persistence["coefficient"]) > 0.9
        and float(cross_stable_persistence["coefficient"]) > 0.9
        and float(cross_native_persistence["coefficient"]) > 0.9
        and float(turn_on_thin["p_value"]) < 0.01
        and float(leader_thin["p_value"]) < 0.01
        and float(turn_on_direct_x_thin["p_value"]) < 0.01
        and float(risk_set_base["stable_route_share"]) < float(
            risk_set_end["stable_route_share"]
        )
        and float(risk_set_end["stable_route_share"]) < 0.5
        and float(risk_set_stable_penalty["coefficient"]) < 0
        and float(risk_set_stable_penalty["p_value"]) < 0.01
        and float(hazard_thick["top_minus_bottom_pp"]) > 10
        and float(hazard_age["top_minus_bottom_pp"]) > 10
        and float(hazard_log_market["coefficient_pp"]) > 0
        and float(hazard_pair_age["coefficient_pp"]) > 0
        and float(hazard_log_market["p_value"]) < 0.01
        and float(hazard_pair_age["p_value"]) < 0.01
        and float(hazard_stable_2026["weighted_turn_on_rate"]) > float(
            hazard_plain_2026["weighted_turn_on_rate"]
        )
    ):
        raise ValueError("vehicle mechanism-sweep headline no longer holds")
    lines = [
        "% Generated by scripts/tabulate/build_vehicle_mechanism_sweep_deck_values.py; do not edit.",
        f"\\newcommand{{\\MechanismScreenRows}}{{{_integer(int(support_row['rows']))}}}",
        f"\\newcommand{{\\MechanismScreenPairs}}{{{_integer(int(support_row['ordered_pairs']))}}}",
        f"\\newcommand{{\\MechanismScreenDays}}{{{_integer(int(support_row['month_days']))}}}",
        f"\\newcommand{{\\MechanismHazardRows}}{{{_integer(int(hazard_support['rows']))}}}",
        f"\\newcommand{{\\MechanismHazardPairs}}{{{_integer(int(hazard_support['ordered_pairs']))}}}",
        f"\\newcommand{{\\MechanismTurnOnThinCoef}}{{{_signed_pp(float(turn_on_thin['coefficient_pp']))}}}",
        f"\\newcommand{{\\MechanismTurnOnThinSE}}{{{_unsigned_pp(float(turn_on_thin['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismTurnOnThinOneSd}}{{{_signed_pp(float(turn_on_thin['one_sd_effect_pp']))}}}",
        f"\\newcommand{{\\MechanismTurnOnDirectCoef}}{{{_signed_pp(float(turn_on_direct['coefficient_pp']))}}}",
        f"\\newcommand{{\\MechanismTurnOnDirectSE}}{{{_unsigned_pp(float(turn_on_direct['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismTurnOnComplexCoef}}{{{_signed_pp(float(turn_on_complex['coefficient_pp']))}}}",
        f"\\newcommand{{\\MechanismTurnOnComplexSE}}{{{_unsigned_pp(float(turn_on_complex['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismTurnOnDirectThinCoef}}{{{_signed_pp(float(turn_on_direct_x_thin['coefficient_pp']))}}}",
        f"\\newcommand{{\\MechanismTurnOnDirectThinSE}}{{{_unsigned_pp(float(turn_on_direct_x_thin['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismLeaderThinCoef}}{{{_signed_pp(float(leader_thin['coefficient_pp']))}}}",
        f"\\newcommand{{\\MechanismLeaderThinSE}}{{{_unsigned_pp(float(leader_thin['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismLeaderThinOneSd}}{{{_signed_pp(float(leader_thin['one_sd_effect_pp']))}}}",
        f"\\newcommand{{\\MechanismSingleStableRegimePersistence}}{{{_pct(float(single_stable_persistence['coefficient']))}}}",
        f"\\newcommand{{\\MechanismSingleStableRegimePersistenceSE}}{{{_unsigned_pp(float(single_stable_persistence['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismSingleNativeRegimePersistence}}{{{_pct(float(single_native_persistence['coefficient']))}}}",
        f"\\newcommand{{\\MechanismSingleNativeRegimePersistenceSE}}{{{_unsigned_pp(float(single_native_persistence['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismCrossStableRegimePersistence}}{{{_pct(float(cross_stable_persistence['coefficient']))}}}",
        f"\\newcommand{{\\MechanismCrossNativeRegimePersistence}}{{{_pct(float(cross_native_persistence['coefficient']))}}}",
        f"\\newcommand{{\\MechanismRiskSetStableRouteShareBase}}{{{_pct(float(risk_set_base['stable_route_share']))}}}",
        f"\\newcommand{{\\MechanismRiskSetStableRouteShareEnd}}{{{_pct(float(risk_set_end['stable_route_share']))}}}",
        f"\\newcommand{{\\MechanismRiskSetStablePenalty}}{{{_signed_pp(float(risk_set_stable_penalty['coefficient_pp']))}}}",
        f"\\newcommand{{\\MechanismRiskSetStablePenaltySE}}{{{_unsigned_pp(float(risk_set_stable_penalty['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismRiskSetStableChange}}{{{_signed_pp(float(risk_set_stable_2026['coefficient_pp']))}}}",
        f"\\newcommand{{\\MechanismRiskSetStableChangeSE}}{{{_unsigned_pp(float(risk_set_stable_2026['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismHazardThickBottom}}{{{_pct(float(hazard_thick['bottom_decile_turn_on_rate']))}}}",
        f"\\newcommand{{\\MechanismHazardThickTop}}{{{_pct(float(hazard_thick['top_decile_turn_on_rate']))}}}",
        f"\\newcommand{{\\MechanismHazardThickGap}}{{{_signed_pp(float(hazard_thick['top_minus_bottom_pp']))}}}",
        f"\\newcommand{{\\MechanismHazardAgeBottom}}{{{_pct(float(hazard_age['bottom_decile_turn_on_rate']))}}}",
        f"\\newcommand{{\\MechanismHazardAgeTop}}{{{_pct(float(hazard_age['top_decile_turn_on_rate']))}}}",
        f"\\newcommand{{\\MechanismHazardAgeGap}}{{{_signed_pp(float(hazard_age['top_minus_bottom_pp']))}}}",
        f"\\newcommand{{\\MechanismHazardLogMarketCoef}}{{{_signed_pp(float(hazard_log_market['coefficient_pp']))}}}",
        f"\\newcommand{{\\MechanismHazardLogMarketSE}}{{{_unsigned_pp(float(hazard_log_market['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismHazardPairAgeCoef}}{{{_signed_pp(float(hazard_pair_age['coefficient_pp']))}}}",
        f"\\newcommand{{\\MechanismHazardPairAgeSE}}{{{_unsigned_pp(float(hazard_pair_age['standard_error_pp']))}}}",
        f"\\newcommand{{\\MechanismHazardPlainEnd}}{{{_pct(float(hazard_plain_2026['weighted_turn_on_rate']))}}}",
        f"\\newcommand{{\\MechanismHazardStableEndpointEnd}}{{{_pct(float(hazard_stable_2026['weighted_turn_on_rate']))}}}",
    ]
    return "\n".join(lines) + "\n"


def run(
    *,
    estimates_path: Path = ESTIMATES,
    support_path: Path = SUPPORT,
    output_path: Path = DECK_VALUES,
) -> int:
    require_presentation_source(estimates_path)
    require_presentation_source(support_path)
    estimates = pd.read_json(estimates_path, lines=True)
    support = pd.read_json(support_path, lines=True)
    rendered = render_vehicle_mechanism_sweep_deck_values(estimates, support)
    with atomic_output(output_path) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--estimates", type=Path, default=ESTIMATES)
    parser.add_argument("--support", type=Path, default=SUPPORT)
    parser.add_argument("--output", type=Path, default=DECK_VALUES)
    args = parser.parse_args()
    return run(
        estimates_path=args.estimates,
        support_path=args.support,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build presentation macros from the current vehicle-pair evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from ddvc.paths import OUTPUT_DIR, REPO_ROOT
from ddvc.provenance import (
    code_fingerprint,
    describe_artifact_payload,
    sidecar_path,
    stamp,
)
from ddvc.runtime import atomic_output


DECOMPOSITION = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_decomposition.jsonl"
FIXED_EFFECTS = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_fixed_effects.jsonl"
USDT_INTEGRATION = OUTPUT_DIR / "exhibits" / "e0_usdt_integration_decomposition.jsonl"
DECK_VALUES = OUTPUT_DIR / "exhibits" / "vehicle_transition_pair_decomposition_deck_values.tex"
CODE_SOURCES = ["scripts/build_vehicle_transition_pair_deck_values.py"]
SCOPES = ("pooled", "single_venue", "cross_venue")
TERMS = (
    "within_common",
    "common_pair_reweighting",
    "common_support_mass",
    "exclusive_pair_contribution",
)
MARKET_INCIDENCE_TERMS = (
    "market_pair_support_bridge",
    "vehicle_role_support_bridge",
    "market_activity_reweighting",
    "vehicle_incidence_reweighting",
    "within_pair_stable_share",
)


def _signed_pp(value: float) -> str:
    points = 100 * value
    if abs(points) < 0.05:
        return "$0.0$ pp"
    return f"${points:+.1f}$ pp"


def _share(value: float) -> str:
    return f"{100 * value:.1f}\\%"


def _unsigned_pp(value: float) -> str:
    return f"${100 * value:.1f}$ pp"


def _raw_pp(value: float) -> str:
    return f"{100 * value:.9f}"


def _raw_pct(value: float) -> str:
    return f"{100 * value:.9f}"


def _scope_rows(decomposition: pd.DataFrame, metric: str) -> dict[str, pd.Series]:
    required = {
        "metric",
        "reporting_scope",
        "baseline_year",
        "comparison_year",
        "common_calendar_end",
        "common_month_days",
        "formula_id",
        "mechanism_status",
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change",
        "support_and_exclusive_joint",
        "identity_error",
        *TERMS,
    }
    missing = sorted(required - set(decomposition.columns))
    if missing:
        raise ValueError(f"pair decomposition missing columns: {', '.join(missing)}")
    rows: dict[str, pd.Series] = {}
    for scope in SCOPES:
        selected = decomposition[
            decomposition["metric"].eq(metric)
            & decomposition["reporting_scope"].eq(scope)
            & decomposition["formula_id"].eq(
                "midpoint_common_exclusive_support_v1"
            )
        ]
        if len(selected) != 1:
            raise ValueError(
                f"pair decomposition requires exactly one {metric}/{scope} row; "
                f"found {len(selected)}"
            )
        row = selected.iloc[0]
        if int(row["baseline_year"]) != 2024 or int(row["comparison_year"]) != 2026:
            raise ValueError("pair decomposition must compare 2024 with 2026")
        if row["common_calendar_end"] != "06-30" or int(row["common_month_days"]) != 181:
            raise ValueError("pair decomposition does not use the locked common calendar")
        if row["formula_id"] != "midpoint_common_exclusive_support_v1":
            raise ValueError("pair decomposition formula differs from the locked identity")
        if row["mechanism_status"] != "descriptive_realised_composition_noncausal":
            raise ValueError("pair decomposition is not labelled as descriptive composition")
        numeric = [
            "baseline_stable_share",
            "comparison_stable_share",
            "total_change",
            "support_and_exclusive_joint",
            "identity_error",
            *TERMS,
        ]
        if not all(math.isfinite(float(row[column])) for column in numeric):
            raise ValueError("pair decomposition contains a non-finite accounting cell")
        if abs(float(row["identity_error"])) > 1e-12:
            raise ValueError("pair decomposition identity error exceeds tolerance")
        joint = float(row["common_support_mass"]) + float(
            row["exclusive_pair_contribution"]
        )
        if not math.isclose(
            float(row["support_and_exclusive_joint"]), joint, abs_tol=1e-12
        ):
            raise ValueError("pair decomposition joint support term does not reconcile")
        total = sum(float(row[column]) for column in TERMS)
        if not math.isclose(float(row["total_change"]), total, abs_tol=1e-12):
            raise ValueError("pair decomposition terms do not sum to the total change")
        if not math.isclose(
            float(row["baseline_stable_share"]) + total,
            float(row["comparison_stable_share"]),
            abs_tol=1e-12,
        ):
            raise ValueError("pair decomposition endpoints do not reconcile")
        rows[scope] = row
    return rows


def _market_incidence_row(decomposition: pd.DataFrame) -> pd.Series:
    required = {
        "metric",
        "reporting_scope",
        "baseline_year",
        "comparison_year",
        "formula_id",
        "mechanism_status",
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change",
        "established_market_baseline_stable_share",
        "established_market_comparison_stable_share",
        "established_market_total_change",
        "common_role_total_change",
        "identity_error",
        *MARKET_INCIDENCE_TERMS,
    }
    missing = sorted(required - set(decomposition.columns))
    if missing:
        raise ValueError(
            f"market-incidence decomposition missing columns: {', '.join(missing)}"
        )
    selected = decomposition[
        decomposition["formula_id"].eq("shapley_market_incidence_stable_bridge_v1")
        & decomposition["metric"].eq("count_share")
        & decomposition["reporting_scope"].eq("pooled")
    ]
    if len(selected) != 1:
        raise ValueError(
            "market-incidence decomposition requires exactly one pooled count row; "
            f"found {len(selected)}"
        )
    row = selected.iloc[0]
    if int(row["baseline_year"]) != 2024 or int(row["comparison_year"]) != 2026:
        raise ValueError("market-incidence decomposition must compare 2024 with 2026")
    if (
        row["mechanism_status"]
        != "descriptive_observed_activity_and_realised_incidence_noncausal"
    ):
        raise ValueError("market-incidence decomposition has a causal mechanism label")
    numeric = [
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change",
        "established_market_baseline_stable_share",
        "established_market_comparison_stable_share",
        "established_market_total_change",
        "common_role_total_change",
        "identity_error",
        *MARKET_INCIDENCE_TERMS,
    ]
    if not all(math.isfinite(float(row[column])) for column in numeric):
        raise ValueError("market-incidence decomposition contains a non-finite cell")
    if abs(float(row["identity_error"])) > 1e-12:
        raise ValueError("market-incidence decomposition identity error exceeds tolerance")
    total = sum(float(row[column]) for column in MARKET_INCIDENCE_TERMS)
    common_role = sum(
        float(row[column])
        for column in (
            "market_activity_reweighting",
            "vehicle_incidence_reweighting",
            "within_pair_stable_share",
        )
    )
    established = float(row["vehicle_role_support_bridge"]) + common_role
    checks = (
        (float(row["total_change"]), total, "total change"),
        (float(row["common_role_total_change"]), common_role, "common-role change"),
        (
            float(row["established_market_total_change"]),
            established,
            "established-market change",
        ),
        (
            float(row["baseline_stable_share"]) + total,
            float(row["comparison_stable_share"]),
            "aggregate endpoints",
        ),
        (
            float(row["established_market_baseline_stable_share"]) + established,
            float(row["established_market_comparison_stable_share"]),
            "established-market endpoints",
        ),
    )
    for left, right, label in checks:
        if not math.isclose(left, right, abs_tol=1e-12):
            raise ValueError(f"market-incidence decomposition does not reconcile {label}")
    return row


def _matched_market_row(fixed_effects: pd.DataFrame, metric: str) -> pd.Series:
    required = {
        "metric",
        "baseline_year",
        "comparison_year",
        "estimator_id",
        "covariance_id",
        "mechanism_status",
        "estimand_scope",
        "coefficient",
        "standard_error",
        "confidence_interval_lower",
        "confidence_interval_upper",
        "p_value_holm",
        "observations",
        "fixed_effect_cells",
        "ordered_pair_clusters",
        "calendar_date_clusters",
    }
    missing = sorted(required - set(fixed_effects.columns))
    if missing:
        raise ValueError(f"pair fixed effects missing columns: {', '.join(missing)}")
    selected = fixed_effects[fixed_effects["metric"].eq(metric)]
    if len(selected) != 1:
        raise ValueError(
            f"pair fixed effects require exactly one {metric} row; "
            f"found {len(selected)}"
        )
    row = selected.iloc[0]
    if int(row["baseline_year"]) != 2024 or int(row["comparison_year"]) != 2026:
        raise ValueError("pair fixed effects must compare 2024 with 2026")
    if (
        row["estimator_id"]
        != "weighted_stable_share_saturated_pair_month_day_scope_fe_v1"
    ):
        raise ValueError("pair fixed effects use an unexpected estimator")
    if row["covariance_id"] != "two_way_ordered_pair_calendar_date_cr1":
        raise ValueError("pair fixed effects use unexpected inference")
    if row["mechanism_status"] != "descriptive_fixed_realised_scope_noncausal":
        raise ValueError("pair fixed effects carry a causal mechanism label")
    if row["estimand_scope"] != "common_pair_month_day_realised_integration_scope":
        raise ValueError("pair fixed effects use an unexpected comparison set")
    numeric = (
        "coefficient",
        "standard_error",
        "confidence_interval_lower",
        "confidence_interval_upper",
        "p_value_holm",
        "observations",
        "fixed_effect_cells",
        "ordered_pair_clusters",
        "calendar_date_clusters",
    )
    if not all(math.isfinite(float(row[column])) for column in numeric):
        raise ValueError("pair fixed effects contain a non-finite result")
    if float(row["standard_error"]) <= 0:
        raise ValueError("pair fixed effects require a positive standard error")
    if not (
        float(row["confidence_interval_lower"])
        <= float(row["coefficient"])
        <= float(row["confidence_interval_upper"])
    ):
        raise ValueError("pair fixed-effects interval excludes its estimate")
    if not 0 <= float(row["p_value_holm"]) <= 1:
        raise ValueError("pair fixed effects contain an invalid adjusted p-value")
    return row


def _usdt_integration_rows(decomposition: pd.DataFrame) -> dict[str, pd.Series]:
    required = {
        "record_type",
        "focal_symbol",
        "comparison_components",
        "baseline_year",
        "comparison_year",
        "weighting",
        "value_support",
        "total_usdt_share_change",
        "within_scope_change",
        "between_scope_composition_change",
        "within_scope_share_of_change",
        "between_scope_share_of_change",
        "identity_residual",
    }
    missing = sorted(required - set(decomposition.columns))
    if missing:
        raise ValueError(f"USDT integration decomposition missing columns: {', '.join(missing)}")
    selected = decomposition[decomposition["record_type"].eq("midpoint_decomposition")]
    rows: dict[str, pd.Series] = {}
    specifications = {
        "count": ("episode", "all_routes"),
        "value": ("value", "within_20pct"),
    }
    for label, (weighting, support) in specifications.items():
        match = selected[
            selected["weighting"].eq(weighting)
            & selected["value_support"].eq(support)
        ]
        if len(match) != 1:
            raise ValueError(
                f"USDT integration decomposition requires exactly one {label} row; "
                f"found {len(match)}"
            )
        row = match.iloc[0]
        if (
            row["focal_symbol"] != "USDT"
            or row["comparison_components"] != "native+USDC+USDT"
            or int(row["baseline_year"]) != 2024
            or int(row["comparison_year"]) != 2026
        ):
            raise ValueError("USDT integration decomposition uses an unexpected scope")
        numeric = (
            "total_usdt_share_change",
            "within_scope_change",
            "between_scope_composition_change",
            "within_scope_share_of_change",
            "between_scope_share_of_change",
            "identity_residual",
        )
        if not all(math.isfinite(float(row[column])) for column in numeric):
            raise ValueError("USDT integration decomposition contains a non-finite value")
        if not math.isclose(
            float(row["within_scope_change"])
            + float(row["between_scope_composition_change"]),
            float(row["total_usdt_share_change"]),
            abs_tol=1e-12,
        ) or not math.isclose(
            float(row["within_scope_share_of_change"])
            + float(row["between_scope_share_of_change"]),
            1.0,
            abs_tol=1e-12,
        ):
            raise ValueError("USDT integration decomposition does not reconcile")
        if abs(float(row["identity_residual"])) > 1e-12:
            raise ValueError("USDT integration decomposition has an identity residual")
        rows[label] = row
    return rows


def render_pair_decomposition_deck_values(
    decomposition: pd.DataFrame,
    fixed_effects: pd.DataFrame,
    usdt_integration: pd.DataFrame,
) -> str:
    """Render empirical cells while keeping evidence identity out of the PDF."""
    count = _scope_rows(decomposition, "count_share")
    value = _scope_rows(decomposition, "strict_intermediation_value_share")
    market = _market_incidence_row(decomposition)
    matched_count = _matched_market_row(fixed_effects, "count_share")
    matched_value = _matched_market_row(
        fixed_effects, "strict_intermediation_value_share"
    )
    usdt = _usdt_integration_rows(usdt_integration)
    pair_activity_total = float(market["market_pair_support_bridge"]) + float(
        market["market_activity_reweighting"]
    )
    vehicle_use_net = float(market["vehicle_incidence_reweighting"]) + float(
        market["vehicle_role_support_bridge"]
    )
    pair_and_vehicle_total = pair_activity_total + vehicle_use_net
    pair_and_vehicle_share = pair_and_vehicle_total / float(market["total_change"])
    if not math.isclose(
        pair_and_vehicle_total + float(market["within_pair_stable_share"]),
        float(market["total_change"]),
        abs_tol=1e-12,
    ):
        raise ValueError("market-incidence display groups do not reconcile")
    pooled = count["pooled"]
    lines = [
        "% Generated by scripts/build_vehicle_transition_pair_deck_values.py; do not edit.",
        f"\\newcommand{{\\PairPooledBase}}{{{_share(float(pooled['baseline_stable_share']))}}}",
        f"\\newcommand{{\\PairPooledEnd}}{{{_share(float(pooled['comparison_stable_share']))}}}",
        f"\\newcommand{{\\PairPooledTotal}}{{{_signed_pp(float(pooled['total_change']))}}}",
        f"\\newcommand{{\\PairPooledReweight}}{{{_signed_pp(float(pooled['common_pair_reweighting']))}}}",
        f"\\newcommand{{\\PairPooledSupportMass}}{{{_signed_pp(float(pooled['common_support_mass']))}}}",
        f"\\newcommand{{\\PairPooledExclusive}}{{{_signed_pp(float(pooled['exclusive_pair_contribution']))}}}",
        f"\\newcommand{{\\PairPooledWithin}}{{{_signed_pp(float(pooled['within_common']))}}}",
        f"\\newcommand{{\\PairPooledBaseRawPct}}{{{_raw_pct(float(pooled['baseline_stable_share']))}}}",
        f"\\newcommand{{\\PairPooledEndRawPct}}{{{_raw_pct(float(pooled['comparison_stable_share']))}}}",
        f"\\newcommand{{\\PairPooledReweightRawPP}}{{{_raw_pp(float(pooled['common_pair_reweighting']))}}}",
        f"\\newcommand{{\\PairPooledSupportMassRawPP}}{{{_raw_pp(float(pooled['common_support_mass']))}}}",
        f"\\newcommand{{\\PairPooledExclusiveRawPP}}{{{_raw_pp(float(pooled['exclusive_pair_contribution']))}}}",
        f"\\newcommand{{\\PairPooledWithinRawPP}}{{{_raw_pp(float(pooled['within_common']))}}}",
    ]
    for scope, suffix in (("single_venue", "Single"), ("cross_venue", "Cross")):
        row = count[scope]
        lines.extend(
            [
                f"\\newcommand{{\\Pair{suffix}Total}}{{{_signed_pp(float(row['total_change']))}}}",
                f"\\newcommand{{\\Pair{suffix}Within}}{{{_signed_pp(float(row['within_common']))}}}",
            ]
        )
    value_pooled = value["pooled"]
    lines.extend(
        [
            f"\\newcommand{{\\PairValueTotal}}{{{_signed_pp(float(value_pooled['total_change']))}}}",
            f"\\newcommand{{\\PairValueWithin}}{{{_signed_pp(float(value_pooled['within_common']))}}}",
            f"\\newcommand{{\\PairValueReweight}}{{{_signed_pp(float(value_pooled['common_pair_reweighting']))}}}",
            f"\\newcommand{{\\PairValueSupportMass}}{{{_signed_pp(float(value_pooled['common_support_mass']))}}}",
            f"\\newcommand{{\\PairValueExclusive}}{{{_signed_pp(float(value_pooled['exclusive_pair_contribution']))}}}",
        ]
    )
    lines.extend(
        [
            f"\\newcommand{{\\MarketBridgeBase}}{{{_share(float(market['baseline_stable_share']))}}}",
            f"\\newcommand{{\\MarketBridgeEnd}}{{{_share(float(market['comparison_stable_share']))}}}",
            f"\\newcommand{{\\MarketBridgeTotal}}{{{_signed_pp(float(market['total_change']))}}}",
            f"\\newcommand{{\\MarketSupportBridge}}{{{_signed_pp(float(market['market_pair_support_bridge']))}}}",
            f"\\newcommand{{\\VehicleRoleSupportBridge}}{{{_signed_pp(float(market['vehicle_role_support_bridge']))}}}",
            f"\\newcommand{{\\MarketActivityReweight}}{{{_signed_pp(float(market['market_activity_reweighting']))}}}",
            f"\\newcommand{{\\VehicleIncidenceReweight}}{{{_signed_pp(float(market['vehicle_incidence_reweighting']))}}}",
            f"\\newcommand{{\\WithinPairStableShare}}{{{_signed_pp(float(market['within_pair_stable_share']))}}}",
            f"\\newcommand{{\\ObservedBothYearsBase}}{{{_share(float(market['established_market_baseline_stable_share']))}}}",
            f"\\newcommand{{\\ObservedBothYearsEnd}}{{{_share(float(market['established_market_comparison_stable_share']))}}}",
            f"\\newcommand{{\\ObservedBothYearsTotal}}{{{_signed_pp(float(market['established_market_total_change']))}}}",
            f"\\newcommand{{\\CommonRoleTotal}}{{{_signed_pp(float(market['common_role_total_change']))}}}",
            f"\\newcommand{{\\PairActivityTotal}}{{{_signed_pp(pair_activity_total)}}}",
            f"\\newcommand{{\\VehicleUseNet}}{{{_signed_pp(vehicle_use_net)}}}",
            f"\\newcommand{{\\PairAndVehicleTotal}}{{{_signed_pp(pair_and_vehicle_total)}}}",
            f"\\newcommand{{\\PairAndVehicleShare}}{{{_share(pair_and_vehicle_share)}}}",
            f"\\newcommand{{\\MarketBridgeBaseRawPct}}{{{_raw_pct(float(market['baseline_stable_share']))}}}",
            f"\\newcommand{{\\MarketSupportBridgeRawPP}}{{{_raw_pp(float(market['market_pair_support_bridge']))}}}",
            f"\\newcommand{{\\VehicleRoleSupportBridgeRawPP}}{{{_raw_pp(float(market['vehicle_role_support_bridge']))}}}",
            f"\\newcommand{{\\MarketActivityReweightRawPP}}{{{_raw_pp(float(market['market_activity_reweighting']))}}}",
            f"\\newcommand{{\\VehicleIncidenceReweightRawPP}}{{{_raw_pp(float(market['vehicle_incidence_reweighting']))}}}",
            f"\\newcommand{{\\WithinPairStableShareRawPP}}{{{_raw_pp(float(market['within_pair_stable_share']))}}}",
            f"\\newcommand{{\\PairActivityTotalRawPP}}{{{_raw_pp(pair_activity_total)}}}",
            f"\\newcommand{{\\VehicleUseNetRawPP}}{{{_raw_pp(vehicle_use_net)}}}",
            f"\\newcommand{{\\PairAndVehicleTotalRawPP}}{{{_raw_pp(pair_and_vehicle_total)}}}",
            f"\\newcommand{{\\MatchedMarketCountChange}}{{{_signed_pp(float(matched_count['coefficient']))}}}",
            f"\\newcommand{{\\MatchedMarketCountSE}}{{{_unsigned_pp(float(matched_count['standard_error']))}}}",
            f"\\newcommand{{\\MatchedMarketCountCILower}}{{{_signed_pp(float(matched_count['confidence_interval_lower']))}}}",
            f"\\newcommand{{\\MatchedMarketCountCIUpper}}{{{_signed_pp(float(matched_count['confidence_interval_upper']))}}}",
            f"\\newcommand{{\\MatchedMarketCountChangeRawPP}}{{{_raw_pp(float(matched_count['coefficient']))}}}",
            f"\\newcommand{{\\MatchedMarketCountCILowerRawPP}}{{{_raw_pp(float(matched_count['confidence_interval_lower']))}}}",
            f"\\newcommand{{\\MatchedMarketCountCIUpperRawPP}}{{{_raw_pp(float(matched_count['confidence_interval_upper']))}}}",
            f"\\newcommand{{\\MatchedMarketValueChange}}{{{_signed_pp(float(matched_value['coefficient']))}}}",
            f"\\newcommand{{\\MatchedMarketValueSE}}{{{_unsigned_pp(float(matched_value['standard_error']))}}}",
            f"\\newcommand{{\\MatchedMarketValueCILower}}{{{_signed_pp(float(matched_value['confidence_interval_lower']))}}}",
            f"\\newcommand{{\\MatchedMarketValueCIUpper}}{{{_signed_pp(float(matched_value['confidence_interval_upper']))}}}",
            f"\\newcommand{{\\USDTVenueMixCountShare}}{{{_share(float(usdt['count']['between_scope_share_of_change']))}}}",
            f"\\newcommand{{\\USDTVenueWithinCountShare}}{{{_share(float(usdt['count']['within_scope_share_of_change']))}}}",
            f"\\newcommand{{\\USDTVenueMixValueShare}}{{{_share(float(usdt['value']['between_scope_share_of_change']))}}}",
            f"\\newcommand{{\\USDTVenueWithinValueShare}}{{{_share(float(usdt['value']['within_scope_share_of_change']))}}}",
        ]
    )
    return "\n".join(lines) + "\n"


def _require_certified_presentation_source(path: Path) -> Path:
    """Verify the committed exhibit boundary without reopening Studio's inputs.

    The data-owning checkout certifies the full upstream perimeter before it
    commits the exhibit and sidecar.  A presentation checkout verifies that
    committed payload/sidecar pair and the producer code, rather than trying to
    rehash the data host's 39 GB lineage.
    """
    provenance_path = sidecar_path(path)
    if not path.is_file() or not provenance_path.is_file():
        raise FileNotFoundError("pair decomposition payload or provenance is missing")
    record = json.loads(provenance_path.read_text(encoding="utf-8"))
    relative = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    if record.get("artefact") != relative:
        raise ValueError("pair decomposition provenance names a different artifact")
    observed_identity = describe_artifact_payload(path, artefact=path)
    if record.get("payload_identity") != observed_identity:
        raise ValueError("pair decomposition payload differs from its certified identity")
    sources = record.get("code_sources")
    if not isinstance(sources, list) or code_fingerprint(sources) != record.get(
        "code_fingerprint"
    ):
        raise ValueError("pair decomposition producer code differs from its certificate")
    if record.get("rows") != observed_identity.get("rows"):
        raise ValueError("pair decomposition row count differs from its certificate")
    return provenance_path


def run(
    *,
    decomposition_path: Path = DECOMPOSITION,
    fixed_effects_path: Path = FIXED_EFFECTS,
    usdt_integration_path: Path = USDT_INTEGRATION,
    output_path: Path = DECK_VALUES,
) -> int:
    provenance_path = _require_certified_presentation_source(decomposition_path)
    fixed_effects_provenance = _require_certified_presentation_source(
        fixed_effects_path
    )
    usdt_integration_provenance = _require_certified_presentation_source(
        usdt_integration_path
    )
    decomposition = pd.read_json(decomposition_path, lines=True)
    fixed_effects = pd.read_json(fixed_effects_path, lines=True)
    usdt_integration = pd.read_json(usdt_integration_path, lines=True)
    rendered = render_pair_decomposition_deck_values(
        decomposition, fixed_effects, usdt_integration
    )
    with atomic_output(output_path) as temporary:
        temporary.write_text(rendered, encoding="utf-8")
    stamp(
        output_path,
        code_sources=CODE_SOURCES,
        inputs=[
            decomposition_path,
            provenance_path,
            fixed_effects_path,
            fixed_effects_provenance,
            usdt_integration_path,
            usdt_integration_provenance,
        ],
        rows=len(decomposition) + len(fixed_effects) + len(usdt_integration),
        notes=(
            "Presentation macros for the exact descriptive pair-composition "
            "accounting and matched-market estimate; evidence status and "
            "identities remain source-only."
        ),
    )
    print(f"wrote {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decomposition", type=Path, default=DECOMPOSITION)
    parser.add_argument("--fixed-effects", type=Path, default=FIXED_EFFECTS)
    parser.add_argument("--usdt-integration", type=Path, default=USDT_INTEGRATION)
    parser.add_argument("--output", type=Path, default=DECK_VALUES)
    args = parser.parse_args()
    return run(
        decomposition_path=args.decomposition,
        fixed_effects_path=args.fixed_effects,
        usdt_integration_path=args.usdt_integration,
        output_path=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""Venue-restriction checks for the registered pair decomposition.

The accounting remains the implementation in
``ddvc.analysis.vehicle_rotation_composition``.  This module only fixes the
endpoint-year calendar, removes named venue sequences, and attaches retained
mass to the canonical pooled decomposition.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from ddvc.analysis.route_reconstruction_validation import AUDITED_VENUES
from ddvc.analysis.vehicle_rotation_composition import (
    BASELINE_YEAR,
    COMPARISON_YEAR,
    METRICS,
    _annual_pair_mass,
    _common_calendar_choices,
    _decompose_metric_scope,
)


ALL_VENUES_ID = "all_venues"
AUDITED_VENUES_ONLY_ID = "audited_venue_families_only"
DECOMPOSITION_FIELDS = (
    "total_change",
    "within_common",
    "common_pair_reweighting",
    "common_support_mass",
    "exclusive_pair_contribution",
)


def venue_sequence_map(sequences: Iterable[object]) -> dict[str, tuple[str, str]]:
    """Return the exact two-leg venue members for each observed sequence."""

    mapping: dict[str, tuple[str, str]] = {}
    for raw_sequence in sequences:
        if not isinstance(raw_sequence, str):
            raise ValueError("venue sequences must be strings")
        members = tuple(raw_sequence.split(">"))
        if len(members) != 2 or any(not member for member in members):
            raise ValueError(f"invalid two-leg venue sequence: {raw_sequence!r}")
        mapping[raw_sequence] = (members[0], members[1])
    if not mapping:
        raise ValueError("venue-exclusion analysis has no venue sequences")
    return mapping


def venue_restrictions(
    sequence_members: dict[str, tuple[str, str]],
) -> list[dict[str, object]]:
    """Build the full, leave-one-family-out, and audited-family restrictions."""

    observed_venues = tuple(
        sorted({venue for members in sequence_members.values() for venue in members})
    )
    all_sequences = tuple(sorted(sequence_members))
    restrictions: list[dict[str, object]] = [
        {
            "variant_id": ALL_VENUES_ID,
            "variant_type": "full_supported_venue_set",
            "allowed_sequences": all_sequences,
            "excluded_venues": (),
            "retained_venues": observed_venues,
        }
    ]
    for venue in observed_venues:
        allowed = tuple(
            sorted(
                sequence
                for sequence, members in sequence_members.items()
                if venue not in members
            )
        )
        retained_venues = tuple(
            sorted(
                {
                    retained
                    for sequence in allowed
                    for retained in sequence_members[sequence]
                }
            )
        )
        restrictions.append(
            {
                "variant_id": f"exclude_{venue}",
                "variant_type": "leave_one_venue_family_out",
                "allowed_sequences": allowed,
                "excluded_venues": (venue,),
                "retained_venues": retained_venues,
            }
        )

    audited_set = frozenset(AUDITED_VENUES)
    audited_sequences = tuple(
        sorted(
            sequence
            for sequence, members in sequence_members.items()
            if set(members).issubset(audited_set)
        )
    )
    if not audited_sequences:
        raise ValueError("venue-exclusion analysis has no audited-family routes")
    retained_audited_venues = tuple(
        sorted(
            {
                venue
                for sequence in audited_sequences
                for venue in sequence_members[sequence]
            }
        )
    )
    restrictions.append(
        {
            "variant_id": AUDITED_VENUES_ONLY_ID,
            "variant_type": "audited_venue_families_only",
            "allowed_sequences": audited_sequences,
            "excluded_venues": tuple(
                venue for venue in observed_venues if venue not in audited_set
            ),
            "retained_venues": retained_audited_venues,
        }
    )
    return restrictions


def _annual_mass(
    annual: pd.DataFrame,
    *,
    baseline_year: int,
    comparison_year: int,
) -> tuple[float, float]:
    masses = annual.groupby("year", sort=True)["denominator"].sum()
    if baseline_year not in masses or comparison_year not in masses:
        raise ValueError("venue restriction lacks positive mass in an endpoint year")
    baseline_mass = float(masses.loc[baseline_year])
    comparison_mass = float(masses.loc[comparison_year])
    if baseline_mass <= 0 or comparison_mass <= 0:
        raise ValueError("venue restriction lacks positive mass in an endpoint year")
    return baseline_mass, comparison_mass


def venue_exclusion_decomposition(
    choices: pd.DataFrame,
    *,
    baseline_year: int = BASELINE_YEAR,
    comparison_year: int = COMPARISON_YEAR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply venue restrictions to the canonical pooled four-term accounting."""

    locked, common_month_days = _common_calendar_choices(
        choices,
        baseline_year=baseline_year,
        comparison_year=comparison_year,
    )
    sequence_members = venue_sequence_map(locked["venue_sequence"].unique())
    restrictions = venue_restrictions(sequence_members)
    observed_venues = tuple(
        sorted({venue for members in sequence_members.values() for venue in members})
    )

    # Collapsing over dates after the common calendar is fixed preserves the
    # exact annual-pair sufficient statistics used by the canonical accounting.
    venue_pair_mass = (
        locked.groupby(
            ["year", "src", "tgt", "candidate_type", "venue_sequence"],
            as_index=False,
            sort=True,
            observed=True,
        )[list(METRICS.values())]
        .sum()
    )
    full_mass: dict[str, tuple[float, float]] = {}
    for metric, metric_column in METRICS.items():
        annual = _annual_pair_mass(
            venue_pair_mass,
            metric_column=metric_column,
            reporting_scope="pooled",
        )
        full_mass[metric] = _annual_mass(
            annual,
            baseline_year=baseline_year,
            comparison_year=comparison_year,
        )

    summary_frames: list[pd.DataFrame] = []
    support_rows: list[dict[str, object]] = []
    for restriction in restrictions:
        allowed_sequences = tuple(restriction["allowed_sequences"])
        selected = venue_pair_mass[
            venue_pair_mass["venue_sequence"].isin(allowed_sequences)
        ]
        raw_selected = locked["venue_sequence"].isin(allowed_sequences)
        if selected.empty:
            raise ValueError(f"venue restriction {restriction['variant_id']} is empty")

        mass_by_metric: dict[str, tuple[float, float]] = {}
        for metric, metric_column in METRICS.items():
            annual = _annual_pair_mass(
                selected,
                metric_column=metric_column,
                reporting_scope="pooled",
            )
            baseline_mass, comparison_mass = _annual_mass(
                annual,
                baseline_year=baseline_year,
                comparison_year=comparison_year,
            )
            mass_by_metric[metric] = (baseline_mass, comparison_mass)
            summary, _decomposition_support, _pair_contributions = (
                _decompose_metric_scope(
                    annual,
                    metric=metric,
                    metric_column=metric_column,
                    reporting_scope="pooled",
                    baseline_year=baseline_year,
                    comparison_year=comparison_year,
                    common_month_days=common_month_days,
                )
            )
            full_baseline_mass, full_comparison_mass = full_mass[metric]
            summary.insert(0, "variant_id", str(restriction["variant_id"]))
            summary.insert(1, "variant_type", str(restriction["variant_type"]))
            summary["excluded_venues"] = "|".join(restriction["excluded_venues"])
            summary["retained_venues"] = "|".join(restriction["retained_venues"])
            summary["baseline_denominator_mass"] = baseline_mass
            summary["comparison_denominator_mass"] = comparison_mass
            summary["baseline_mass_retained_share"] = (
                baseline_mass / full_baseline_mass
            )
            summary["comparison_mass_retained_share"] = (
                comparison_mass / full_comparison_mass
            )
            summary["period_specific_pair_contribution"] = summary[
                "exclusive_pair_contribution"
            ]
            for field in DECOMPOSITION_FIELDS:
                summary[f"{field}_pp"] = 100.0 * summary[field]
            summary["period_specific_pair_contribution_pp"] = 100.0 * summary[
                "period_specific_pair_contribution"
            ]
            summary_frames.append(summary)

        count_mass = mass_by_metric["count_share"]
        value_mass = mass_by_metric["strict_intermediation_value_share"]
        support_rows.append(
            {
                "record_type": "venue_exclusion_support",
                "variant_id": str(restriction["variant_id"]),
                "variant_type": str(restriction["variant_type"]),
                "baseline_year": baseline_year,
                "comparison_year": comparison_year,
                "common_month_days": len(common_month_days),
                "fixed_common_calendar": True,
                "input_choice_rows": len(locked),
                "retained_choice_rows": int(raw_selected.sum()),
                "retained_choice_row_share": float(raw_selected.mean()),
                "observed_venues": "|".join(observed_venues),
                "excluded_venues": "|".join(restriction["excluded_venues"]),
                "retained_venues": "|".join(restriction["retained_venues"]),
                "audited_venues": "|".join(AUDITED_VENUES),
                "audited_scope_note": (
                    "venue_family_restriction_only_not_a_claim_that_every_retained_"
                    "date_was_independently_audited"
                ),
                "baseline_route_count_mass": count_mass[0],
                "comparison_route_count_mass": count_mass[1],
                "baseline_route_count_retained_share": (
                    count_mass[0] / full_mass["count_share"][0]
                ),
                "comparison_route_count_retained_share": (
                    count_mass[1] / full_mass["count_share"][1]
                ),
                "baseline_supported_value_usd": value_mass[0],
                "comparison_supported_value_usd": value_mass[1],
                "baseline_supported_value_retained_share": (
                    value_mass[0]
                    / full_mass["strict_intermediation_value_share"][0]
                ),
                "comparison_supported_value_retained_share": (
                    value_mass[1]
                    / full_mass["strict_intermediation_value_share"][1]
                ),
            }
        )

    results = pd.concat(summary_frames, ignore_index=True, sort=False)
    results = results.sort_values(["variant_id", "metric"], kind="stable").reset_index(
        drop=True
    )
    if not np.allclose(results["identity_error"], 0.0, atol=1e-12, rtol=0.0):
        raise RuntimeError("a venue-exclusion decomposition identity failed")
    support = pd.DataFrame(support_rows).sort_values("variant_id", kind="stable")
    return results, support.reset_index(drop=True)

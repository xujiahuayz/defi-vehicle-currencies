from __future__ import annotations

import pandas as pd
import pytest

from ddvc.analysis.vehicle_rotation_composition import vehicle_rotation_composition
from ddvc.analysis.vehicle_rotation_venue_exclusion import (
    AUDITED_VENUES_ONLY_ID,
    venue_exclusion_decomposition,
    venue_restrictions,
    venue_sequence_map,
)


NATIVE = "0x0000000000000000000000000000000000000001"
STABLE = "0x0000000000000000000000000000000000000002"


def _choice(
    date: str,
    src: str,
    tgt: str,
    candidate_type: str,
    venue_sequence: str,
    route_count: float,
) -> dict[str, object]:
    return {
        "date": pd.Timestamp(date),
        "src": src,
        "tgt": tgt,
        "candidate_address": NATIVE if candidate_type == "native" else STABLE,
        "candidate_type": candidate_type,
        "venue_sequence": venue_sequence,
        "integration_scope": (
            "single_venue"
            if len(set(venue_sequence.split(">"))) == 1
            else "cross_venue"
        ),
        "route_count": route_count,
        "within_20pct_routes": route_count,
        "within_20pct_value_usd": 100.0 * route_count,
    }


def _fixture() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year, stable_v2, stable_fluid in ((2024, 2.0, 1.0), (2026, 8.0, 9.0)):
        date = f"{year}-01-01"
        rows.extend(
            [
                _choice(date, "a", "b", "native", "uniswap_v2>uniswap_v2", 10),
                _choice(
                    date,
                    "a",
                    "b",
                    "stable",
                    "uniswap_v2>uniswap_v2",
                    stable_v2,
                ),
                _choice(date, "c", "d", "native", "fluid>uniswap_v3", 10),
                _choice(
                    date,
                    "c",
                    "d",
                    "stable",
                    "fluid>uniswap_v3",
                    stable_fluid,
                ),
            ]
        )
    return pd.DataFrame(rows)


def test_venue_sequence_map_requires_exactly_two_nonempty_legs() -> None:
    assert venue_sequence_map(["fluid>uniswap_v3"])["fluid>uniswap_v3"] == (
        "fluid",
        "uniswap_v3",
    )
    with pytest.raises(ValueError, match="two-leg"):
        venue_sequence_map(["fluid"])
    with pytest.raises(ValueError, match="two-leg"):
        venue_sequence_map(["fluid>"])


def test_restrictions_use_exact_venue_members_and_define_audited_only() -> None:
    mapping = venue_sequence_map(
        [
            "fluid>uniswap_v3",
            "fluidish>uniswap_v3",
            "uniswap_v2>uniswap_v2",
        ]
    )
    restrictions = {row["variant_id"]: row for row in venue_restrictions(mapping)}
    assert restrictions["exclude_fluid"]["allowed_sequences"] == (
        "fluidish>uniswap_v3",
        "uniswap_v2>uniswap_v2",
    )
    assert restrictions["exclude_uniswap_v3"]["retained_venues"] == (
        "uniswap_v2",
    )
    assert restrictions[AUDITED_VENUES_ONLY_ID]["allowed_sequences"] == (
        "uniswap_v2>uniswap_v2",
    )


def test_full_variant_matches_registered_pooled_decomposition() -> None:
    choices = _fixture()
    expected = vehicle_rotation_composition(
        choices, reporting_scopes=("pooled",)
    )[1].sort_values("metric", kind="stable")
    observed, support = venue_exclusion_decomposition(choices)
    full = observed[observed["variant_id"].eq("all_venues")].sort_values(
        "metric", kind="stable"
    )
    for column in (
        "baseline_stable_share",
        "comparison_stable_share",
        "total_change",
        "within_common",
        "common_pair_reweighting",
        "common_support_mass",
        "exclusive_pair_contribution",
    ):
        assert full[column].to_numpy() == pytest.approx(expected[column].to_numpy())
    assert full["baseline_mass_retained_share"].tolist() == pytest.approx(
        [1.0, 1.0, 1.0]
    )
    assert full["comparison_mass_retained_share"].tolist() == pytest.approx(
        [1.0, 1.0, 1.0]
    )
    audited = observed[
        observed["variant_id"].eq(AUDITED_VENUES_ONLY_ID)
        & observed["metric"].eq("count_share")
    ].iloc[0]
    no_fluid = observed[
        observed["variant_id"].eq("exclude_fluid")
        & observed["metric"].eq("count_share")
    ].iloc[0]
    assert audited["total_change"] == pytest.approx(no_fluid["total_change"])
    assert support["fixed_common_calendar"].all()
    assert set(support["variant_id"]) == {
        "all_venues",
        "exclude_fluid",
        "exclude_uniswap_v2",
        "exclude_uniswap_v3",
        AUDITED_VENUES_ONLY_ID,
    }

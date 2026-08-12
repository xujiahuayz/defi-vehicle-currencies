from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from ddvc.asset_types import NATIVE, STABLE, classify
from ddvc.endpoint_candidate_composition import (
    EVENT_COLLISION,
    INCLUDED,
    EndpointCandidateComposition,
    endpoint_candidate_composition_for_day,
    finalize_endpoint_candidate_composition,
    validate_endpoint_candidate_composition,
)
from ddvc.realised import ROUTE_COLUMNS, extract_realised_routes


SRC = "0x1111111111111111111111111111111111111111"
TGT = "0x2222222222222222222222222222222222222222"
OTHER = "0x3333333333333333333333333333333333333333"
WETH = next(address for address, symbol in NATIVE.items() if symbol == "WETH")
USDC = next(address for address, symbol in STABLE.items() if symbol == "USDC")


def leg(
    tx_hash: str,
    log_index: int,
    token_in: str,
    token_out: str,
    *,
    component_id: int = 0,
    route_class: str = "coherent",
    source: str = "uniswap_v2",
    amount_usd: float = 100.0,
) -> dict[str, object]:
    return {
        "tx_hash": tx_hash,
        "component_id": component_id,
        "route_class": route_class,
        "source": source,
        "token_in": token_in,
        "token_out": token_out,
        "amount_usd": amount_usd,
        "log_index": log_index,
        "tin_role": "source",
        "tout_role": "sink",
        "timestamp_utc": 1_704_153_600,
    }


def sample_legs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            leg("direct", 0, SRC, TGT, route_class="single"),
            leg("weth", 1, SRC, WETH),
            leg("weth", 2, WETH, TGT),
            leg("usdc", 3, SRC, USDC, amount_usd=100),
            leg("usdc", 4, USDC, TGT, source="sushiswap_v2", amount_usd=50),
            leg("other", 5, SRC, OTHER),
            leg("other", 6, OTHER, TGT),
        ]
    )


def test_primary_choice_has_exact_unit_sequences_and_nested_values() -> None:
    bundle = endpoint_candidate_composition_for_day(sample_legs(), "20240102")
    choices = bundle.choices.set_index("candidate_address")
    assert set(choices.index) == {WETH, USDC}
    assert choices["route_count"].eq(1).all()
    assert choices.loc[WETH, "candidate_type"] == "native"
    assert choices.loc[USDC, "candidate_type"] == "stable"
    assert choices.loc[USDC, "backing_regime"] == "fiat_reserve"
    assert choices.loc[WETH, "integration_scope"] == "single_venue"
    assert choices.loc[USDC, "integration_scope"] == "cross_venue"
    assert choices.loc[USDC, "venue_sequence"] == "uniswap_v2>sushiswap_v2"
    assert choices.loc[USDC, "protocol_sequence"] == "uniswap>sushiswap"
    assert choices.loc[WETH, "raw_value_usd"] == pytest.approx(100.0)
    assert choices.loc[WETH, "within_20pct_value_usd"] == pytest.approx(100.0)
    assert choices.loc[USDC, "raw_value_usd"] == pytest.approx(75.0)
    assert choices.loc[USDC, "within_2x_value_usd"] == pytest.approx(75.0)
    assert choices.loc[USDC, "within_20pct_routes"] == 0

    support = bundle.pair_support.iloc[0]
    assert support["market_route_count"] == 4
    assert support["primary_choice_route_count"] == 2
    assert support["direct_route_count"] == 1
    assert support["other_candidate_route_count"] == 1
    assert set(bundle.exclusions["exclusion_reason"]) == {"direct_route", "other_candidate"}
    assert bundle.exclusions["route_count"].sum() + bundle.choices["route_count"].sum() == 4


def test_primary_choice_reconciles_to_canonical_realised_route_owner() -> None:
    legs = sample_legs()
    canonical = extract_realised_routes(
        legs[ROUTE_COLUMNS],
        require_positive_value=False,
    )
    canonical["candidate_type"] = canonical["vehicle"].map(
        lambda address: classify(address)[1]
    )
    canonical = canonical[
        canonical["legs"].eq(2)
        & canonical["candidate_type"].isin(("native", "stable"))
    ]
    choices = endpoint_candidate_composition_for_day(
        legs, "20240102"
    ).choices
    assert choices["route_count"].sum() == len(canonical)
    expected = canonical.groupby("candidate_type")["usd"].sum().sort_index()
    observed = choices.groupby("candidate_type")["raw_value_usd"].sum().sort_index()
    pd.testing.assert_series_equal(observed, expected, check_names=False)


def test_direct_and_other_candidates_are_explicit_exclusions() -> None:
    direct = pd.DataFrame([leg("direct", 0, SRC, TGT, route_class="single")])
    bundle = endpoint_candidate_composition_for_day(direct, "20240102")
    assert bundle.choices.empty
    assert bundle.pair_support.iloc[0]["direct_route_count"] == 1
    assert bundle.exclusions.iloc[0]["exclusion_reason"] == "direct_route"

    other = pd.DataFrame([leg("other", 0, SRC, OTHER), leg("other", 1, OTHER, TGT)])
    bundle = endpoint_candidate_composition_for_day(other, "20240102")
    assert bundle.choices.empty
    assert bundle.pair_support.iloc[0]["other_candidate_route_count"] == 1
    excluded = bundle.exclusions.iloc[0]
    assert excluded["candidate_address"] == OTHER
    assert excluded["candidate_type"] == "other"


def test_unsupported_value_preserves_count_and_zero_supported_value() -> None:
    unsupported = pd.DataFrame(
        [
            leg("weth", 0, SRC, WETH, amount_usd=float("nan")),
            leg("weth", 1, WETH, TGT, amount_usd=float("nan")),
        ]
    )
    choice = endpoint_candidate_composition_for_day(unsupported, "20240102").choices.iloc[0]
    assert choice["route_count"] == 1
    assert choice["raw_value_supported_routes"] == 0
    assert choice["raw_value_usd"] == 0
    assert choice["within_2x_routes"] == 0
    assert choice["within_20pct_routes"] == 0


def test_multi_candidate_route_is_excluded_once() -> None:
    multi = pd.DataFrame(
        [
            leg("multi", 0, SRC, WETH),
            leg("multi", 1, WETH, USDC),
            leg("multi", 2, USDC, TGT),
        ]
    )
    bundle = endpoint_candidate_composition_for_day(multi, "20240102")
    assert bundle.choices.empty
    assert bundle.pair_support.iloc[0]["multiple_intermediary_route_count"] == 1
    assert bundle.exclusions.iloc[0]["exclusion_reason"] == "multiple_intermediaries"
    assert bundle.exclusions.iloc[0]["route_count"] == 1


def test_split_join_and_direct_split_are_not_vehicle_choices() -> None:
    split_around_candidate = pd.DataFrame(
        [
            leg("split", 0, SRC, WETH, amount_usd=50),
            leg("split", 1, SRC, WETH, source="sushiswap_v2", amount_usd=50),
            leg("split", 2, WETH, TGT, amount_usd=100),
        ]
    )
    bundle = endpoint_candidate_composition_for_day(split_around_candidate, "20240102")
    assert bundle.choices.empty
    assert bundle.pair_support.iloc[0]["split_or_join_route_count"] == 1
    assert bundle.exclusions.iloc[0]["exclusion_reason"] == "split_or_join"

    direct_split = pd.DataFrame(
        [
            leg("direct-split", 0, SRC, TGT, amount_usd=50),
            leg("direct-split", 1, SRC, TGT, source="sushiswap_v2", amount_usd=50),
        ]
    )
    bundle = endpoint_candidate_composition_for_day(direct_split, "20240102")
    assert bundle.choices.empty
    assert bundle.pair_support.iloc[0]["direct_split_route_count"] == 1
    assert bundle.exclusions.iloc[0]["exclusion_reason"] == "direct_split"


def test_round_trip_cycle_and_ambiguous_route_class_are_audited() -> None:
    round_trip = pd.DataFrame([leg("cycle", 0, SRC, WETH), leg("cycle", 1, WETH, SRC)])
    bundle = endpoint_candidate_composition_for_day(round_trip, "20240102")
    assert bundle.choices.empty
    assert bundle.pair_support.empty
    assert bundle.exclusions.iloc[0]["exclusion_reason"] == "round_trip"

    ambiguous = pd.DataFrame(
        [
            leg("ambiguous", 0, SRC, WETH, route_class="tricky_bridged"),
            leg("ambiguous", 1, WETH, TGT, route_class="tricky_bridged"),
        ]
    )
    bundle = endpoint_candidate_composition_for_day(ambiguous, "20240102")
    assert bundle.exclusions.iloc[0]["exclusion_reason"] == "ambiguous_route_class"


def test_candidate_identity_and_event_identity_fail_closed() -> None:
    invalid = pd.DataFrame([leg("bad", 0, SRC, "USDC"), leg("bad", 1, "USDC", TGT)])
    with pytest.raises(ValueError, match="invalid token_.* address"):
        endpoint_candidate_composition_for_day(invalid, "20240102")

    duplicate = sample_legs()
    with pytest.raises(ValueError, match="duplicate event identity"):
        endpoint_candidate_composition_for_day(pd.concat([duplicate, duplicate.iloc[[0]]], ignore_index=True), "20240102")

    bundle = endpoint_candidate_composition_for_day(sample_legs(), "20240102")
    tampered = bundle.choices.copy()
    tampered.loc[0, "candidate_type"] = (
        "native" if tampered.loc[0, "candidate_type"] == "stable" else "stable"
    )
    with pytest.raises(ValueError, match="canonical candidate identity"):
        validate_endpoint_candidate_composition(replace(bundle, choices=tampered))


def test_cross_source_coordinate_collision_quarantines_every_affected_component() -> None:
    rows = sample_legs()
    collisions = pd.DataFrame(
        [
            leg("colliding", 10, SRC, WETH, component_id=0, source="uniswap_v2", amount_usd=40),
            leg("colliding", 11, WETH, TGT, component_id=0, source="uniswap_v2", amount_usd=40),
            leg("colliding", 10, SRC, USDC, component_id=1, source="sushiswap_v2", amount_usd=60),
            leg("colliding", 12, USDC, TGT, component_id=1, source="sushiswap_v2", amount_usd=60),
        ]
    )
    bundle = endpoint_candidate_composition_for_day(
        pd.concat([rows, collisions], ignore_index=True),
        "20240102",
    )
    quarantined = bundle.exclusions[
        bundle.exclusions["exclusion_reason"].eq(EVENT_COLLISION)
    ].sort_values("audit_component_id")
    assert len(quarantined) == 2
    assert quarantined["audit_tx_hash"].eq("colliding").all()
    assert quarantined["audit_component_id"].tolist() == [0, 1]
    assert quarantined["collision_event_coordinate_count"].eq(1).all()
    assert quarantined["collision_row_count"].eq(1).all()
    assert quarantined["collision_source_count"].eq(2).all()
    assert quarantined["collision_sources"].eq("sushiswap_v2>uniswap_v2").all()
    assert quarantined["collision_log_indices"].eq("10").all()
    assert quarantined["collision_observed_abs_leg_value_usd_upper_bound"].tolist() == [80, 120]
    assert bundle.choices["route_count"].sum() == 2
    support = bundle.pair_support.iloc[0]
    assert support["day_source_component_count"] == 6
    assert support["day_accounted_component_count"] == 6
    assert support["day_event_collision_component_count"] == 2
    assert support["day_event_collision_observed_abs_leg_value_usd_upper_bound"] == 200
    assert support["source_pair_component_count"] == 6
    assert support["event_collision_component_count"] == 2


def test_choice_support_exposes_transaction_multiplicity_and_conditional_values() -> None:
    routes = pd.DataFrame(
        [
            leg("multi-choice", 0, SRC, WETH, component_id=0, amount_usd=100),
            leg("multi-choice", 1, WETH, TGT, component_id=0, amount_usd=100),
            leg("multi-choice", 2, SRC, WETH, component_id=1, amount_usd=200),
            leg("multi-choice", 3, WETH, TGT, component_id=1, amount_usd=200),
            leg("stable-choice", 4, SRC, USDC, amount_usd=50),
            leg("stable-choice", 5, USDC, TGT, amount_usd=50),
        ]
    )
    support = endpoint_candidate_composition_for_day(routes, "20240102").pair_support.iloc[0]
    assert support["primary_choice_route_count"] == 3
    assert support["native_choice_route_count"] == 2
    assert support["stable_choice_route_count"] == 1
    assert support["native_within_20pct_routes"] == 2
    assert support["stable_within_20pct_routes"] == 1
    assert support["native_within_20pct_value_usd"] == 300
    assert support["stable_within_20pct_value_usd"] == 50
    assert support["primary_choice_transaction_count"] == 2
    assert support["primary_choice_multi_component_transaction_count"] == 1
    assert support["primary_choice_component_excess_count"] == 1
    assert support["duplicate_choice_transaction_candidate_count"] == 1


def test_collision_audit_and_choice_decomposition_fail_closed_on_tamper() -> None:
    rows = pd.concat(
        [
            sample_legs(),
            pd.DataFrame(
                [
                    leg("colliding", 10, SRC, WETH, source="uniswap_v2"),
                    leg("colliding", 10, WETH, TGT, source="sushiswap_v2"),
                ]
            ),
        ],
        ignore_index=True,
    )
    bundle = endpoint_candidate_composition_for_day(rows, "20240102")
    bad_audit = bundle.exclusions.copy()
    collision = bad_audit["exclusion_reason"].eq(EVENT_COLLISION)
    bad_audit.loc[collision, "audit_tx_hash"] = ""
    with pytest.raises(ValueError, match="component-keyed audit evidence"):
        validate_endpoint_candidate_composition(replace(bundle, exclusions=bad_audit))

    bad_support = bundle.pair_support.copy()
    native_count = bad_support.loc[0, "native_choice_route_count"]
    stable_count = bad_support.loc[0, "stable_choice_route_count"]
    native_value = bad_support.loc[0, "native_within_20pct_value_usd"]
    stable_value = bad_support.loc[0, "stable_within_20pct_value_usd"]
    bad_support.loc[0, "native_choice_route_count"] = stable_count
    bad_support.loc[0, "stable_choice_route_count"] = native_count
    bad_support.loc[0, "native_within_20pct_routes"] = stable_count
    bad_support.loc[0, "stable_within_20pct_routes"] = native_count
    bad_support.loc[0, "native_within_20pct_value_usd"] = stable_value
    bad_support.loc[0, "stable_within_20pct_value_usd"] = native_value
    with pytest.raises(ValueError, match="disagrees with native choice"):
        validate_endpoint_candidate_composition(replace(bundle, pair_support=bad_support))

    bad_collision = bundle.pair_support.copy()
    bad_collision.loc[0, "event_collision_component_count"] = 99
    bad_collision.loc[0, "source_pair_component_count"] = (
        bad_collision.loc[0, "market_route_count"] + 99
    )
    bad_collision.loc[
        0, "event_collision_observed_abs_leg_value_usd_upper_bound"
    ] = 999
    with pytest.raises(ValueError, match="disagrees with collision exclusions"):
        validate_endpoint_candidate_composition(
            replace(bundle, pair_support=bad_collision)
        )


def test_transaction_timestamp_must_match_supplied_utc_day() -> None:
    with pytest.raises(ValueError, match="outside supplied UTC day"):
        endpoint_candidate_composition_for_day(sample_legs(), "20240103")


def test_order_and_pair_lifecycle_are_deterministic() -> None:
    first = endpoint_candidate_composition_for_day(sample_legs(), "20240102")
    shuffled = endpoint_candidate_composition_for_day(sample_legs().sample(frac=1, random_state=19), "20240102")
    pd.testing.assert_frame_equal(first.choices, shuffled.choices)
    pd.testing.assert_frame_equal(first.pair_support, shuffled.pair_support)
    pd.testing.assert_frame_equal(first.exclusions, shuffled.exclusions)

    second_legs = sample_legs()
    second_legs["timestamp_utc"] = 1_704_240_000
    second = endpoint_candidate_composition_for_day(second_legs, "20240103")
    forward = finalize_endpoint_candidate_composition([first, second])
    reverse = finalize_endpoint_candidate_composition([second, first])
    pd.testing.assert_frame_equal(forward.choices, reverse.choices)
    pd.testing.assert_frame_equal(forward.pair_support, reverse.pair_support)
    pd.testing.assert_frame_equal(forward.exclusions, reverse.exclusions)
    early = forward.pair_support[forward.pair_support["date"].eq(pd.Timestamp("2024-01-02"))]
    late = forward.pair_support[forward.pair_support["date"].eq(pd.Timestamp("2024-01-03"))]
    assert early["pair_entry_on_day"].all()
    assert late["pair_last_observed_on_day"].all()


def test_venue_sequence_follows_directed_route_when_events_execute_in_reverse() -> None:
    reverse_execution = pd.DataFrame(
        [
            leg("reverse", 0, WETH, TGT, source="uniswap_v3"),
            leg("reverse", 1, SRC, WETH, source="sushiswap_v2"),
        ]
    )
    choice = endpoint_candidate_composition_for_day(
        reverse_execution, "20240102"
    ).choices.iloc[0]
    assert choice["venue_sequence"] == "sushiswap_v2>uniswap_v3"
    assert choice["protocol_sequence"] == "sushiswap>uniswap"
    assert choice["integration_scope"] == "cross_venue"


def test_validation_rejects_non_nested_support_and_accounting_drift() -> None:
    bundle = endpoint_candidate_composition_for_day(sample_legs(), "20240102")
    bad_support = bundle.choices.copy()
    bad_support.loc[0, "within_20pct_routes"] = 2
    with pytest.raises(ValueError, match="not nested"):
        validate_endpoint_candidate_composition(replace(bundle, choices=bad_support))

    bad_pair = bundle.pair_support.copy()
    bad_pair.loc[0, "primary_choice_route_count"] += 1
    with pytest.raises(ValueError, match="does not reconcile"):
        validate_endpoint_candidate_composition(replace(bundle, pair_support=bad_pair))

    bad_exclusion = bundle.exclusions.copy()
    bad_exclusion.loc[0, "exclusion_reason"] = "unregistered"
    with pytest.raises(ValueError, match="unknown reason"):
        validate_endpoint_candidate_composition(replace(bundle, exclusions=bad_exclusion))


def test_validation_rejects_duplicate_exclusions_and_reason_drift() -> None:
    bundle = endpoint_candidate_composition_for_day(sample_legs(), "20240102")
    duplicated = pd.concat([bundle.exclusions, bundle.exclusions.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate composition keys"):
        validate_endpoint_candidate_composition(replace(bundle, exclusions=duplicated))

    drifted = bundle.exclusions.copy()
    direct = drifted["exclusion_reason"].eq("direct_route")
    other = drifted["exclusion_reason"].eq("other_candidate")
    drifted.loc[direct, "route_count"] -= 1
    drifted.loc[other, "route_count"] += 1
    with pytest.raises(ValueError, match="disagree with pair support"):
        validate_endpoint_candidate_composition(replace(bundle, exclusions=drifted))


def test_validation_rejects_infinite_and_non_nested_values() -> None:
    bundle = endpoint_candidate_composition_for_day(sample_legs(), "20240102")
    infinite = bundle.choices.copy()
    infinite.loc[0, "raw_value_usd"] = float("inf")
    with pytest.raises(ValueError, match="invalid raw_value_usd"):
        validate_endpoint_candidate_composition(replace(bundle, choices=infinite))

    non_nested = bundle.choices.copy()
    non_nested.loc[0, "within_2x_value_usd"] = (
        non_nested.loc[0, "raw_value_usd"] + 1
    )
    with pytest.raises(ValueError, match="magnitudes are not nested"):
        validate_endpoint_candidate_composition(replace(bundle, choices=non_nested))

    unsupported = bundle.choices.copy()
    unsupported.loc[0, "within_20pct_routes"] = 0
    unsupported.loc[0, "within_20pct_value_usd"] = 1
    with pytest.raises(ValueError, match="without supported routes"):
        validate_endpoint_candidate_composition(replace(bundle, choices=unsupported))

    positive_support_without_value = bundle.choices.copy()
    positive_support_without_value.loc[
        :, ["raw_value_usd", "within_2x_value_usd", "within_20pct_value_usd"]
    ] = 0
    with pytest.raises(ValueError, match="supported routes without value"):
        validate_endpoint_candidate_composition(
            replace(bundle, choices=positive_support_without_value)
        )

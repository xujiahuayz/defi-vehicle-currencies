from __future__ import annotations

import pandas as pd
import pytest

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.endpoint_candidate_composition import (
    PANEL_KEYS,
    endpoint_candidate_composition_for_day,
    finalize_endpoint_candidate_composition,
    validate_endpoint_candidate_composition,
)
from ddvc.vehicle_extent import compute_vehicle_extent


SRC = "0x1111111111111111111111111111111111111111"
TGT = "0x2222222222222222222222222222222222222222"
OTHER = "0x3333333333333333333333333333333333333333"
WETH = next(address for address, symbol in VEHICLE_CANDIDATES.items() if symbol == "WETH")
USDC = next(address for address, symbol in VEHICLE_CANDIDATES.items() if symbol == "USDC")


def leg(
    tx_hash: str,
    log_index: int,
    token_in: str,
    token_out: str,
    tin_role: str,
    tout_role: str,
    *,
    component_id: int = 0,
    route_class: str = "coherent",
    amount_usd: float = 100.0,
) -> dict[str, object]:
    return {
        "tx_hash": tx_hash,
        "component_id": component_id,
        "route_class": route_class,
        "token_in": token_in,
        "token_out": token_out,
        "tin_role": tin_role,
        "tout_role": tout_role,
        "amount_usd": amount_usd,
        "log_index": log_index,
    }


def sample_legs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            leg("direct", 0, SRC, TGT, "source", "sink", route_class="single"),
            leg("weth", 1, SRC, WETH, "source", "intermediate"),
            leg("weth", 2, WETH, TGT, "intermediate", "sink"),
            leg("usdc", 3, SRC, USDC, "source", "intermediate", amount_usd=100),
            leg("usdc", 4, USDC, TGT, "intermediate", "sink", amount_usd=50),
            leg("other", 5, SRC, OTHER, "source", "intermediate"),
            leg("other", 6, OTHER, TGT, "intermediate", "sink"),
        ]
    )


def test_count_and_strict_value_denominators_are_explicit() -> None:
    panel = endpoint_candidate_composition_for_day(sample_legs(), "20240102").set_index(
        "candidate_symbol"
    )
    assert len(panel) == len(VEHICLE_CANDIDATES)
    assert panel["count_denominator_routes"].eq(4).all()
    assert panel.loc["WETH", "count_numerator_routes"] == 1
    assert panel.loc["WETH", "count_share"] == pytest.approx(0.25)
    assert panel["strict_value_denominator_routes"].eq(3).all()
    assert panel["strict_value_denominator_usd"].eq(300.0).all()
    assert panel.loc["WETH", "strict_value_numerator_usd"] == pytest.approx(100.0)
    assert panel.loc["WETH", "strict_value_share"] == pytest.approx(1 / 3)
    assert panel.loc["USDC", "candidate_strict_value_reason"] == "candidate_has_no_strict_value_route"
    assert panel["count_leader_reason"].eq("tie").all()


def test_direct_only_pair_is_supported_zero_not_missing() -> None:
    direct = pd.DataFrame(
        [leg("direct", 0, SRC, TGT, "source", "sink", route_class="single")]
    )
    panel = endpoint_candidate_composition_for_day(direct, "20240102")
    assert len(panel) == len(VEHICLE_CANDIDATES)
    assert panel["count_supported"].all()
    assert panel["count_numerator_routes"].eq(0).all()
    assert panel["count_share"].eq(0.0).all()
    assert panel["strict_value_supported"].all()
    assert panel["strict_value_share"].eq(0.0).all()
    assert panel["candidate_route_reason"].eq("no_candidate_vehicle_route").all()
    assert panel["count_leader_reason"].eq("no_candidate_vehicle_route").all()


def test_empty_strict_value_support_has_reason_and_no_share() -> None:
    unsupported = pd.DataFrame(
        [
            leg(
                "direct",
                0,
                SRC,
                TGT,
                "source",
                "sink",
                route_class="single",
                amount_usd=float("nan"),
            )
        ]
    )
    panel = endpoint_candidate_composition_for_day(unsupported, "20240102")
    assert (~panel["strict_value_supported"]).all()
    assert panel["strict_value_share"].isna().all()
    assert panel["strict_value_support_reason"].eq(
        "no_strict_value_routes_for_endpoint_pair"
    ).all()
    assert panel["candidate_strict_value_reason"].eq(
        "pair_has_no_strict_value_support"
    ).all()


def test_candidate_endpoint_is_structural_zero_not_missing_support() -> None:
    direct = pd.DataFrame(
        [leg("direct", 0, WETH, TGT, "source", "sink", route_class="single")]
    )
    panel = endpoint_candidate_composition_for_day(direct, "20240102").set_index(
        "candidate_address"
    )
    assert panel.loc[WETH, "count_supported"]
    assert panel.loc[WETH, "count_share"] == 0.0
    assert panel.loc[WETH, "candidate_route_reason"] == "candidate_is_endpoint"
    assert panel.loc[WETH, "candidate_strict_value_reason"] == "candidate_is_endpoint"


def test_duplicate_event_and_duplicate_panel_key_fail_closed() -> None:
    legs = sample_legs()
    with pytest.raises(ValueError, match="duplicate event identity"):
        endpoint_candidate_composition_for_day(
            pd.concat([legs, legs.iloc[[0]]], ignore_index=True), "20240102"
        )
    panel = endpoint_candidate_composition_for_day(legs, "20240102")
    with pytest.raises(ValueError, match="duplicate endpoint-candidate composition key"):
        validate_endpoint_candidate_composition(
            pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
        )


def test_results_are_deterministic_under_input_and_day_completion_order() -> None:
    first = endpoint_candidate_composition_for_day(sample_legs(), "20240102")
    shuffled = endpoint_candidate_composition_for_day(
        sample_legs().sample(frac=1, random_state=19), "20240102"
    )
    pd.testing.assert_frame_equal(first, shuffled)
    second = endpoint_candidate_composition_for_day(sample_legs(), "20240103")
    forward = finalize_endpoint_candidate_composition([first, second])
    reverse = finalize_endpoint_candidate_composition([second, first])
    pd.testing.assert_frame_equal(forward, reverse)
    assert not forward.duplicated(PANEL_KEYS).any()
    assert forward.loc[forward["date"].eq(pd.Timestamp("2024-01-02")), "pair_entry_on_day"].all()
    assert forward.loc[forward["date"].eq(pd.Timestamp("2024-01-03")), "pair_last_observed_on_day"].all()


def test_multi_candidate_route_matches_token_level_vehicle_extent_semantics() -> None:
    multi = pd.DataFrame(
        [
            leg("multi", 0, SRC, WETH, "source", "intermediate"),
            leg("multi", 1, WETH, USDC, "intermediate", "intermediate"),
            leg("multi", 2, USDC, TGT, "intermediate", "sink"),
        ]
    )
    panel = endpoint_candidate_composition_for_day(multi, "20240102").set_index(
        "candidate_address"
    )
    extent = compute_vehicle_extent(multi).set_index("token")
    assert panel.loc[WETH, "count_numerator_routes"] == 1
    assert panel.loc[USDC, "count_numerator_routes"] == 1
    assert panel.loc[WETH, "count_denominator_routes"] == 1
    assert panel.loc[USDC, "count_denominator_routes"] == 1
    assert panel.loc[WETH, "count_share"] == 1.0
    assert panel.loc[USDC, "count_share"] == 1.0
    assert extent.loc[WETH, "intermediate_routes"] == 1
    assert extent.loc[USDC, "intermediate_routes"] == 1

from __future__ import annotations

import pandas as pd
import pytest

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.candidate_pool_contributions import (
    CandidatePoolContributionBundle,
    V2_CAPITAL_FAMILY,
    V3_FLOW_FAMILY,
    candidate_pool_capital_contributions,
    candidate_pool_flow_contributions,
    validate_candidate_pool_contribution_bundle,
)
from ddvc.capital_contracts import CP_CAPITAL_STATE_GENERATION
from ddvc.vehicle_extent import compute_vehicle_extent


SRC = "0x1111111111111111111111111111111111111111"
TGT = "0x2222222222222222222222222222222222222222"
POOL_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
POOL_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
WETH = next(address for address, symbol in VEHICLE_CANDIDATES.items() if symbol == "WETH")
USDC = next(address for address, symbol in VEHICLE_CANDIDATES.items() if symbol == "USDC")


def leg(
    tx: str,
    log: int,
    token_in: str,
    token_out: str,
    tin_role: str,
    tout_role: str,
    *,
    route_class: str = "coherent",
) -> dict[str, object]:
    return {
        "tx_hash": tx,
        "component_id": 0,
        "route_class": route_class,
        "token_in": token_in,
        "token_out": token_out,
        "tin_role": tin_role,
        "tout_role": tout_role,
        "amount_usd": 100.0,
        "log_index": log,
    }


def candidate_capital(pool: str, candidate: str, value: float, weight: float) -> dict[str, object]:
    address = next(address for address, symbol in VEHICLE_CANDIDATES.items() if symbol == candidate)
    return {
        "day": "20240102",
        "venue": "uniswap_v2",
        "pool": pool,
        "candidate": candidate,
        "candidate_address": address,
        "allocation_weight": weight,
        "candidate_capital_usd": value,
        "quantity_kind": "deposited_capital",
        "capital_validation_status": "exact_state_current",
        "state_generation": CP_CAPITAL_STATE_GENERATION,
    }


def direct_route() -> pd.DataFrame:
    return pd.DataFrame([leg("direct", 0, SRC, TGT, "source", "sink", route_class="single")])


def test_shared_pool_is_conserved_once_with_explicit_denominators() -> None:
    pools = pd.DataFrame(
        [
            candidate_capital(POOL_A, "WETH", 500.0, 0.5),
            candidate_capital(POOL_A, "USDC", 500.0, 0.5),
            candidate_capital(POOL_B, "WETH", 800.0, 1.0),
        ]
    )
    bundle = candidate_pool_capital_contributions(
        pools,
        direct_route(),
        "20240102",
        pool_day_supported=True,
        route_day_supported=True,
    )
    contribution = bundle.contributions.set_index(["pool_address", "candidate_symbol"])
    support = bundle.support.set_index("candidate_symbol")
    assert contribution.loc[(POOL_A, "WETH"), "candidate_gross_denominator_usd"] == 1300.0
    assert contribution.loc[(POOL_A, "WETH"), "all_candidate_gross_denominator_usd"] == 1800.0
    assert contribution.loc[(POOL_A, "WETH"), "pool_share_within_candidate"] == pytest.approx(500 / 1300)
    assert contribution.loc[(POOL_A, "USDC"), "pool_share_within_candidate"] == 1.0
    assert support.loc["WETH", "candidate_quantity_share_of_day"] == pytest.approx(1300 / 1800)
    assert support.loc["USDC", "candidate_quantity_share_of_day"] == pytest.approx(500 / 1800)
    assert support["candidate_gross_contribution_usd"].sum() == 1800.0
    assert support["candidate_signed_contribution_usd"].isna().all()
    assert set(bundle.contributions["measurement_family"]) == {V2_CAPITAL_FAMILY}


def test_direct_only_route_is_supported_zero_for_every_candidate() -> None:
    bundle = candidate_pool_capital_contributions(
        pd.DataFrame(),
        direct_route(),
        "20240102",
        pool_day_supported=True,
        route_day_supported=True,
    )
    assert bundle.contributions.empty
    assert bundle.support["pool_support_reason"].eq("supported_zero_pool_quantity").all()
    assert bundle.support["candidate_gross_contribution_usd"].eq(0.0).all()
    assert bundle.support["route_count_denominator"].eq(1).all()
    assert bundle.support["route_count_numerator"].eq(0).all()
    assert bundle.support["route_support_reason"].eq("supported_zero_intermediation").all()


def test_multi_candidate_route_matches_vehicle_extent_semantics() -> None:
    routes = pd.DataFrame(
        [
            leg("multi", 0, SRC, WETH, "source", "intermediate"),
            leg("multi", 1, WETH, USDC, "intermediate", "intermediate"),
            leg("multi", 2, USDC, TGT, "intermediate", "sink"),
        ]
    )
    bundle = candidate_pool_capital_contributions(
        pd.DataFrame(),
        routes,
        "20240102",
        pool_day_supported=True,
        route_day_supported=True,
    )
    support = bundle.support.set_index("candidate_address")
    extent = compute_vehicle_extent(routes).set_index("token")
    assert support.loc[WETH, "route_count_numerator"] == extent.loc[WETH, "intermediate_routes"] == 1
    assert support.loc[USDC, "route_count_numerator"] == extent.loc[USDC, "intermediate_routes"] == 1
    assert support.loc[WETH, "route_count_denominator"] == 1
    assert support.loc[USDC, "route_count_denominator"] == 1


def test_flow_family_keeps_gross_concentration_and_signed_quantity_separate() -> None:
    rows = pd.DataFrame(
        [
            {
                "day": "20240102",
                "venue": "uniswap_v3",
                "pool": POOL_A,
                "tx_hash": "tx1",
                "log_index": 1,
                "candidate": "WETH",
                "candidate_address": WETH,
                "allocation_weight": 0.5,
                "allocated_event_value_usd": 50.0,
                "signed_allocated_event_value_usd": 50.0,
                "event_value_usd": 100.0,
                "event_sign": 1,
                "flow_normalization_status": "dollar_flow_no_capital_stock_denominator",
            },
            {
                "day": "20240102",
                "venue": "uniswap_v3",
                "pool": POOL_A,
                "tx_hash": "tx1",
                "log_index": 1,
                "candidate": "USDC",
                "candidate_address": USDC,
                "allocation_weight": 0.5,
                "allocated_event_value_usd": 50.0,
                "signed_allocated_event_value_usd": 50.0,
                "event_value_usd": 100.0,
                "event_sign": 1,
                "flow_normalization_status": "dollar_flow_no_capital_stock_denominator",
            },
            {
                "day": "20240102",
                "venue": "uniswap_v3",
                "pool": POOL_B,
                "tx_hash": "tx2",
                "log_index": 2,
                "candidate": "WETH",
                "candidate_address": WETH,
                "allocation_weight": 1.0,
                "allocated_event_value_usd": 25.0,
                "signed_allocated_event_value_usd": -25.0,
                "event_value_usd": 25.0,
                "event_sign": -1,
                "flow_normalization_status": "dollar_flow_no_capital_stock_denominator",
            },
        ]
    )
    bundle = candidate_pool_flow_contributions(
        rows,
        direct_route(),
        "20240102",
        pool_day_supported=True,
        route_day_supported=True,
    )
    support = bundle.support.set_index("candidate_symbol")
    assert set(bundle.contributions["measurement_family"]) == {V3_FLOW_FAMILY}
    assert support.loc["WETH", "candidate_gross_contribution_usd"] == 75.0
    assert support.loc["WETH", "candidate_signed_contribution_usd"] == 25.0
    assert support.loc["USDC", "candidate_gross_contribution_usd"] == 50.0
    assert support["candidate_gross_contribution_usd"].sum() == 125.0


def test_duplicates_bad_allocation_and_missing_support_fail_closed() -> None:
    row = candidate_capital(POOL_A, "WETH", 100.0, 1.0)
    with pytest.raises(ValueError, match="duplicate"):
        candidate_pool_capital_contributions(
            pd.DataFrame([row, row]), direct_route(), "20240102", pool_day_supported=True, route_day_supported=True
        )
    bad = pd.DataFrame([candidate_capital(POOL_A, "WETH", 50.0, 0.5)])
    with pytest.raises(ValueError, match="conserve"):
        candidate_pool_capital_contributions(
            bad, direct_route(), "20240102", pool_day_supported=True, route_day_supported=True
        )
    with pytest.raises(ValueError, match="unsupported pool day"):
        candidate_pool_capital_contributions(
            pd.DataFrame([row]), pd.DataFrame(), "20240102", pool_day_supported=False, route_day_supported=False
        )
    unavailable = candidate_pool_capital_contributions(
        pd.DataFrame(), pd.DataFrame(), "20240102", pool_day_supported=False, route_day_supported=False
    ).support
    assert unavailable["pool_support_reason"].eq("unavailable").all()
    assert unavailable["route_support_reason"].eq("unavailable").all()
    assert unavailable["candidate_gross_contribution_usd"].isna().all()


def test_results_are_deterministic_under_pool_and_route_row_order() -> None:
    pools = pd.DataFrame(
        [
            candidate_capital(POOL_A, "WETH", 500.0, 0.5),
            candidate_capital(POOL_A, "USDC", 500.0, 0.5),
            candidate_capital(POOL_B, "WETH", 800.0, 1.0),
        ]
    )
    routes = pd.DataFrame(
        [
            leg("multi", 0, SRC, WETH, "source", "intermediate"),
            leg("multi", 1, WETH, TGT, "intermediate", "sink"),
        ]
    )
    first = candidate_pool_capital_contributions(
        pools, routes, "20240102", pool_day_supported=True, route_day_supported=True
    )
    shuffled = candidate_pool_capital_contributions(
        pools.sample(frac=1, random_state=2),
        routes.sample(frac=1, random_state=3),
        "20240102",
        pool_day_supported=True,
        route_day_supported=True,
    )
    pd.testing.assert_frame_equal(first.contributions, shuffled.contributions)
    pd.testing.assert_frame_equal(first.support, shuffled.support)


def test_tampered_contribution_denominator_fails_add_up_validation() -> None:
    bundle = candidate_pool_capital_contributions(
        pd.DataFrame([candidate_capital(POOL_A, "WETH", 100.0, 1.0)]),
        direct_route(),
        "20240102",
        pool_day_supported=True,
        route_day_supported=True,
    )
    tampered = bundle.contributions.copy()
    tampered.loc[0, "candidate_gross_denominator_usd"] = 101.0
    with pytest.raises(ValueError, match="denominators do not add up"):
        validate_candidate_pool_contribution_bundle(
            CandidatePoolContributionBundle(tampered, bundle.support)
        )

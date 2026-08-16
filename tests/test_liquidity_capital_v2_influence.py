from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ddvc.analysis.liquidity_capital_v2_influence import (
    ATTACK_ID,
    candidate_capital_block,
    candidate_contribution_ledger,
    capital_reconciliation,
    leave_out_units,
    open_candidate_capital,
    pool_contribution_ledger,
    rebuild_candidate_day,
    top_pool_keys,
    within_transform_weight,
)


SCRIPT = Path(__file__).parents[1] / "scripts/run_liquidity_capital_v2_predictability.py"
SPEC = importlib.util.spec_from_file_location("run_liquidity_capital_v2_influence_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

DAYS = pd.date_range("2021-01-01", periods=4, freq="D")
CANDIDATES = ("0xaa", "0xbb")
POOLS = (("uniswap_v2", "0xp1"), ("sushiswap_v2", "0xp2"))


def _allocation_frame() -> pd.DataFrame:
    rows = []
    for day_index, day in enumerate(DAYS):
        for candidate_index, candidate in enumerate(CANDIDATES):
            for pool_index, (venue, pool) in enumerate(POOLS):
                rows.append({
                    "day": day.strftime("%Y%m%d"),
                    "candidate_address": candidate,
                    "venue": venue,
                    "pool": pool,
                    # The first pool carries an order of magnitude more capital,
                    # so the contribution ledger has an unambiguous leader.
                    "candidate_capital_usd": float(
                        (10.0 if pool_index == 0 else 1.0)
                        * (1 + candidate_index)
                        * (day_index + 1)
                    ),
                    "capital_validation_status": "exact_state_current",
                    "state_generation": "fixture",
                })
    return pd.DataFrame(rows)


def _allocation_path(tmp_path: Path) -> Path:
    path = tmp_path / "pool_candidate_capital_daily.parquet"
    _allocation_frame().to_parquet(path, index=False)
    return path


def _released_panel(block: pd.DataFrame) -> pd.DataFrame:
    """Wrap a capital block in the route columns `rebuild_candidate_day` preserves."""

    panel = block.copy()
    panel.insert(2, "candidate_symbol", panel["candidate_address"].str.upper())
    panel.insert(3, "route_day_supported", True)
    panel.insert(4, "route_endpoint_supported", True)
    panel.insert(5, "intermediary_episode_share", 0.25)
    return panel


def _grid() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"origin_date": day, "candidate_address": candidate}
            for day in DAYS
            for candidate in CANDIDATES
        ]
    )


def test_capital_block_reproduces_its_own_release_and_reconciles(tmp_path: Path) -> None:
    connection = open_candidate_capital(_allocation_path(tmp_path))
    try:
        block = candidate_capital_block(connection, _grid())
    finally:
        connection.close()
    assert block["v2_capital_day_supported"].all()
    assert block["v2_candidate_pool_observed"].all()
    # Two pools, two venues, two allocation rows per candidate-day, every day.
    assert set(block["v2_candidate_pool_count"]) == {2.0}
    assert set(block["v2_candidate_venue_count"]) == {2.0}
    np.testing.assert_allclose(
        block.groupby("origin_date")["v2_five_candidate_capital_share"].sum(), 1.0
    )
    released = _released_panel(block)
    rebuilt = rebuild_candidate_day(released, block)
    reconciliation = capital_reconciliation(released, rebuilt)
    assert set(reconciliation["record"]) == {"released_recomputation_reconciliation"}
    assert reconciliation["maximum_relative_difference"].max() == 0.0


def test_reconciliation_refuses_a_capital_column_that_moved(tmp_path: Path) -> None:
    connection = open_candidate_capital(_allocation_path(tmp_path))
    try:
        block = candidate_capital_block(connection, _grid())
    finally:
        connection.close()
    released = _released_panel(block)
    moved = released.copy()
    moved.loc[0, "v2_deposited_capital_usd"] = float(
        moved.loc[0, "v2_deposited_capital_usd"]
    ) * 1.01
    with pytest.raises(ValueError, match="does not reproduce the released panel"):
        capital_reconciliation(moved, released)


def test_excluding_a_pool_removes_only_that_pool_and_renormalises(tmp_path: Path) -> None:
    connection = open_candidate_capital(_allocation_path(tmp_path))
    try:
        ledger = pool_contribution_ledger(connection, top_n=2)
        leader = top_pool_keys(ledger, count=1)[0]
        full = candidate_capital_block(connection, _grid())
        excluded = candidate_capital_block(
            connection, _grid(), excluded_pool_keys=[leader]
        )
    finally:
        connection.close()
    assert leader == "uniswap_v2:0xp1"
    assert excluded["v2_candidate_pool_count"].eq(1.0).all()
    assert excluded["v2_candidate_venue_count"].eq(1.0).all()
    # The excluded pool carried ten of every eleven dollars on every candidate-day.
    np.testing.assert_allclose(
        excluded["v2_deposited_capital_usd"].to_numpy(float),
        full["v2_deposited_capital_usd"].to_numpy(float) / 11.0,
    )
    # Both candidates lose the same proportion, so the share denominator is intact.
    np.testing.assert_allclose(
        excluded["v2_five_candidate_capital_share"].to_numpy(float),
        full["v2_five_candidate_capital_share"].to_numpy(float),
    )
    assert excluded["v2_capital_day_supported"].all()


def test_removing_every_pool_of_a_day_reports_unsupported_not_zero(tmp_path: Path) -> None:
    connection = open_candidate_capital(_allocation_path(tmp_path))
    try:
        block = candidate_capital_block(
            connection,
            _grid(),
            excluded_pool_keys=["uniswap_v2:0xp1", "sushiswap_v2:0xp2"],
        )
    finally:
        connection.close()
    assert not block["v2_capital_day_supported"].any()
    assert block["v2_deposited_capital_usd"].isna().all()
    assert block["v2_capital_support_status"].eq("unavailable").all()


def test_pool_ledger_ranks_by_contribution_and_reports_concentration(tmp_path: Path) -> None:
    connection = open_candidate_capital(_allocation_path(tmp_path))
    try:
        ledger = pool_contribution_ledger(connection, top_n=2)
    finally:
        connection.close()
    summary = ledger[ledger["record"].eq("pool_concentration_summary")].iloc[0]
    contributions = ledger[ledger["record"].eq("pool_contribution")]
    assert int(summary["pools"]) == 2
    assert contributions["rank"].tolist() == [1.0, 2.0]
    np.testing.assert_allclose(contributions["capital_share"].sum(), 1.0)
    np.testing.assert_allclose(summary["top_1_share"], 10.0 / 11.0)
    np.testing.assert_allclose(
        summary["herfindahl_index"], (10 / 11) ** 2 + (1 / 11) ** 2
    )


def test_candidate_ledger_reports_the_capital_share_each_candidate_carries(
    tmp_path: Path,
) -> None:
    connection = open_candidate_capital(_allocation_path(tmp_path))
    try:
        block = candidate_capital_block(connection, _grid())
    finally:
        connection.close()
    ledger = candidate_contribution_ledger(_released_panel(block))
    contributions = ledger[ledger["record"].eq("candidate_contribution")]
    # The second candidate holds twice the first on every pool and day.
    np.testing.assert_allclose(
        contributions.sort_values("candidate_address")["capital_share_of_total"],
        [1 / 3, 2 / 3],
    )
    summary = ledger[ledger["record"].eq("candidate_concentration_summary")].iloc[0]
    np.testing.assert_allclose(summary["top_1_share"], 2 / 3)


def test_within_variance_weights_are_the_pooled_slope_weights() -> None:
    sample = pd.DataFrame({"candidate_address": ["a", "a", "b", "b"]})
    weights = within_transform_weight(sample, pd.Series([1.0, 1.0, 2.0, 2.0]))
    np.testing.assert_allclose(
        weights.sort_values("candidate_address")["predictor_variance_share"], [0.2, 0.8]
    )
    assert weights["observations"].tolist() == [2, 2]


def test_leave_out_perimeter_starts_from_the_recomputed_base(tmp_path: Path) -> None:
    connection = open_candidate_capital(_allocation_path(tmp_path))
    try:
        block = candidate_capital_block(connection, _grid())
    finally:
        connection.close()
    units = leave_out_units(_released_panel(block), ["uniswap_v2:0xp1"])
    assert [unit["leave_out_kind"] for unit in units] == [
        "none", "candidate", "candidate", "pool",
    ]
    assert units[0]["leave_out_unit"] == "recomputed_full_sample"
    assert units[-1]["leave_out_unit"] == "uniswap_v2:0xp1"


def test_leave_one_candidate_fit_accepts_four_and_still_refuses_a_lost_candidate() -> None:
    rows = []
    for day_index, day in enumerate(pd.date_range("2021-01-01", periods=60, freq="D")):
        for candidate in range(4):
            predictor = np.sin(day_index / 7 + candidate) + candidate * day_index / 300
            rows.append({
                "origin_date": day,
                "candidate_address": f"candidate-{candidate}",
                "predictor": predictor,
                "outcome": 0.75 * predictor + candidate + day_index / 10,
            })
    sample = pd.DataFrame(rows)
    primary, two_way = MODULE._fit_fe(
        sample, "outcome", "predictor", expected_candidates=4, with_two_way=False
    )
    np.testing.assert_allclose(primary.beta[0], 0.75, atol=1e-10)
    assert two_way is None
    with pytest.raises(ValueError, match="insufficient candidate-date support"):
        MODULE._fit_fe(sample, "outcome", "predictor")


def test_displacement_flags_a_sign_flip_against_the_recomputed_base() -> None:
    base = []
    for horizon in MODULE.HORIZONS:
        for direction in ("route_to_capital", "capital_to_route"):
            for route_measure in MODULE.ROUTE_MEASURES:
                for capital_measure in MODULE.CAPITAL_MEASURES:
                    base.append({
                        "leave_out_kind": "none",
                        "leave_out_unit": "recomputed_full_sample",
                        "horizon_days": horizon,
                        "primary_horizon": horizon in MODULE.PRIMARY_HORIZONS,
                        "direction": direction,
                        "route_measure": route_measure,
                        "capital_measure": capital_measure,
                        "coefficient": 0.4,
                        "standard_error": 0.1,
                        "p_value": 0.01,
                        "p_value_holm": 0.01,
                    })
    flipped = pd.DataFrame(base).assign(
        leave_out_kind="candidate",
        leave_out_unit="0xaa",
        coefficient=-0.1,
        p_value_holm=0.90,
    )
    displaced = MODULE._influence_displacement(
        pd.concat([pd.DataFrame(base), flipped], ignore_index=True)
    )
    perturbed = displaced[displaced["leave_out_kind"].eq("candidate")]
    assert perturbed["sign_flip"].all()
    np.testing.assert_allclose(perturbed["displacement_in_base_standard_errors"], -5.0)
    assert perturbed["primary_significance_flip"].sum() == 2 * 2 * 2 * len(
        MODULE.PRIMARY_HORIZONS
    )
    assert not displaced[displaced["leave_out_kind"].eq("none")]["sign_flip"].any()


def test_attack_identity_is_the_registered_one() -> None:
    assert ATTACK_ID == "influence_concentration"
    assert MODULE.INFLUENCE_ATTACK_ID == ATTACK_ID

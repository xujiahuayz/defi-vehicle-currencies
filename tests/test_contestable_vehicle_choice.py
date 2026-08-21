from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_contestable_vehicle_choice import (
    MIN_CONSEQUENCE_CELL_PAIRS,
    MIN_CONSEQUENCE_CELL_ROUTES,
    MIN_CONSEQUENCE_LOSS_ROUTES,
    WETH,
    _fit_model,
    attach_v2_bridge_capital,
    attach_incumbency,
    load_lagged_v2_bridge_capital,
    load_first_vehicle_roles,
    output_consequence_rows,
    prepare_frontier,
)


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def _frontier_row(
    route_id: str,
    day: str,
    token_in: str,
    token_out: str,
    *,
    chosen: str,
    gap_bps: float,
    venues: object = "uniswap_v2|sushiswap_v2",
    chosen_price_impact: float = 0.01,
    chosen_vehicle: str | None = None,
) -> dict[str, object]:
    native_out = 100.0
    observed_vehicle = chosen_vehicle or (USDC if chosen == "stable" else WETH)
    return {
        "day": day,
        "route_id": route_id,
        "token_in": token_in,
        "token_out": token_out,
        "chosen_vehicle": observed_vehicle,
        "chosen_vehicle_type": chosen,
        "input_usd": 1_000.0,
        "output_usd": 1_000.0,
        "within_20pct": True,
        "chosen_max_price_impact": chosen_price_impact,
        "vehicle_families_contestable": True,
        "stable_minus_native_bps": gap_bps,
        "native_public_out": native_out,
        "stable_public_out": native_out * (1.0 + gap_bps / 10_000.0),
        "native_public_vehicle": WETH,
        "stable_public_vehicle": USDC,
        "native_public_venues": venues,
        "stable_public_venues": venues,
    }


def test_frontier_uses_pretrade_alternatives_and_measures_output_shortfall() -> None:
    raw = pd.DataFrame(
        [
            _frontier_row(
                "r1",
                "20240215",
                "src-a",
                "tgt-a",
                chosen="native",
                gap_bps=100.0,
                chosen_price_impact=0.50,
            ),
            _frontier_row(
                "r2",
                "20240215",
                "src-b",
                "tgt-b",
                chosen="stable",
                gap_bps=20.0,
                venues=pd.NA,
            ),
            _frontier_row(
                "outside-universe",
                "20240215",
                "src-c",
                "tgt-c",
                chosen="stable",
                gap_bps=20.0,
                chosen_vehicle="0x0000000000000000000000000000000000000001",
            ),
        ]
    )
    panel, support = prepare_frontier(raw)

    assert len(panel) == 2
    first = panel.set_index("route_id").loc["r1"]
    assert bool(first["stable_price_leader"])
    assert not bool(first["chosen_matches_price_leader"])
    assert first["foregone_family_output_bps"] == pytest.approx(100.0)
    assert not bool(first["symmetric_common_support"])
    assert bool(
        panel.set_index("route_id").loc["r2", "symmetric_common_support"]
    )
    assert "foregone_family_output_usd" not in panel
    assert support["contestable_rows"] == 2
    assert support["eligible_classified_vehicle_rows"] == 3
    assert support["eligible_observed_vehicle_rows"] == 2


def test_first_vehicle_role_preserves_ambiguous_initial_day(tmp_path) -> None:
    support = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2024-01-01"),
                "src": "src-a",
                "tgt": "tgt-a",
                "stable_choice_route_count": 8,
                "native_choice_route_count": 2,
                "primary_choice_route_count": 10,
                "pair_first_supported_date": pd.Timestamp("2024-01-01"),
            },
            {
                "date": pd.Timestamp("2024-01-01"),
                "src": "src-c",
                "tgt": "tgt-c",
                "stable_choice_route_count": 8,
                "native_choice_route_count": 0,
                "primary_choice_route_count": 8,
                "pair_first_supported_date": pd.Timestamp("2024-01-01"),
            },
            {
                "date": pd.Timestamp("2024-01-01"),
                "src": "src-b",
                "tgt": "tgt-b",
                "stable_choice_route_count": 5,
                "native_choice_route_count": 5,
                "primary_choice_route_count": 10,
                "pair_first_supported_date": pd.Timestamp("2024-01-01"),
            },
            {
                "date": pd.Timestamp("2024-01-02"),
                "src": "src-b",
                "tgt": "tgt-b",
                "stable_choice_route_count": 9,
                "native_choice_route_count": 1,
                "primary_choice_route_count": 10,
                "pair_first_supported_date": pd.Timestamp("2024-01-01"),
            },
        ]
    )
    path = tmp_path / "pair_support.parquet"
    support.to_parquet(path, index=False)

    roles = load_first_vehicle_roles(path).set_index(["token_in", "token_out"])
    assert roles.loc[("src-a", "tgt-a"), "entry_stable"] == 1.0
    assert bool(roles.loc[("src-a", "tgt-a"), "entry_mixed"])
    assert not bool(roles.loc[("src-a", "tgt-a"), "entry_exclusive"])
    assert bool(roles.loc[("src-b", "tgt-b"), "entry_tie"])
    assert pd.isna(roles.loc[("src-b", "tgt-b"), "entry_stable"])
    assert bool(roles.loc[("src-c", "tgt-c"), "entry_exclusive"])


def test_incumbency_is_strictly_prior_and_maturity_is_separate() -> None:
    raw = pd.DataFrame(
        [
            _frontier_row(
                "entry",
                "20240115",
                "src-a",
                "tgt-a",
                chosen="stable",
                gap_bps=10.0,
            ),
            _frontier_row(
                "early",
                "20240116",
                "src-a",
                "tgt-a",
                chosen="native",
                gap_bps=-10.0,
            ),
            _frontier_row(
                "mature",
                "20240215",
                "src-a",
                "tgt-a",
                chosen="native",
                gap_bps=-10.0,
            ),
            _frontier_row(
                "unmatched",
                "20240215",
                "src-b",
                "tgt-b",
                chosen="stable",
                gap_bps=10.0,
            ),
        ]
    )
    frontier, _ = prepare_frontier(raw)
    roles = pd.DataFrame(
        [
            {
                "token_in": "src-a",
                "token_out": "tgt-a",
                "first_vehicle_date": pd.Timestamp("2024-01-15"),
                "first_market_date": pd.Timestamp("2024-01-01"),
                "entry_stable": 1.0,
                "entry_exclusive": True,
                "entry_mixed": False,
            }
        ]
    )
    result = attach_incumbency(frontier, roles).set_index("route_id")

    assert bool(result.loc["entry", "entry_day_observation"])
    assert not bool(result.loc["entry", "incumbent_known_prior"])
    assert pd.isna(result.loc["entry", "incumbent_retained"])
    assert bool(result.loc["early", "incumbent_known_prior"])
    assert not bool(result.loc["early", "mature_incumbent"])
    assert bool(result.loc["mature", "mature_incumbent"])
    assert bool(result.loc["mature", "mature_exclusive_incumbent"])
    assert result.loc["mature", "pair_age_days"] == 45
    assert result.loc["mature", "incumbent_retained"] == 0.0
    assert result.loc["mature", "challenger_price_leader"] == 1.0
    assert pd.isna(result.loc["unmatched", "incumbent_retained"])


def test_v2_capital_is_prior_day_bottleneck_and_excludes_other_venues(
    tmp_path,
) -> None:
    frontier = pd.DataFrame(
        [
            {
                "day": "20240215",
                "token_in": "src",
                "token_out": "tgt",
                "stable_public_vehicle": USDC,
                "native_public_vehicle": WETH,
                "entry_stable": 1.0,
                "incumbent_known_prior": True,
                "incumbent_output_advantage_100bp": 0.5,
            }
        ]
    )
    rows = []
    for venue, token0, token1, capital in (
        ("uniswap_v2", "src", USDC, 100.0),
        ("sushiswap_v2", USDC, "tgt", 80.0),
        ("uniswap_v2", "src", WETH, 200.0),
        ("sushiswap_v2", WETH, "tgt", 120.0),
        ("curve", "src", USDC, 5_000.0),
    ):
        rows.append(
            {
                "day": "20240215",
                "venue": venue,
                "token0_address": token0,
                "token1_address": token1,
                "capital_usd_lagged": capital,
                "quantity_kind": "deposited_capital",
                "capital_validation_status": "exact_state_prior_calendar",
            }
        )
    path = tmp_path / "pool_capital.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)

    capital = load_lagged_v2_bridge_capital(frontier, path)
    assert capital["stable_v2_bridge_capital_usd"].item() == pytest.approx(80.0)
    assert capital["native_v2_bridge_capital_usd"].item() == pytest.approx(120.0)
    attached = attach_v2_bridge_capital(frontier, capital)
    assert bool(attached["both_v2_bridge_capitals_positive"].item())
    assert attached["incumbent_v2_capital_share"].item() == pytest.approx(0.4)


def test_output_consequence_records_have_exhaustive_splits_and_support_guards(
) -> None:
    rows = []
    for position in range(400):
        block = position // 100
        input_usd = (500.0, 5_000.0, 50_000.0, 500_000.0)[block]
        loss_bps = 10.0 if position % 100 < 50 else 0.0
        if position == 50:
            loss_bps = 1.0
        mature_exclusive = position < 200
        incumbent_known = position < 200 or position >= 300
        pair_age = (
            30.0
            if position < 100
            else 200.0
            if position < 200
            else 500.0
            if position < 300
            else -1.0
            if position < 350
            else np.nan
        )
        both_capitals = position < 300
        stable_capital = (25.0, 100.0, 400.0, 0.0)[block]
        native_capital = 100.0 if both_capitals else 0.0
        rows.append(
            {
                "symmetric_common_support": True,
                "ordered_pair": f"pair-{position % 100}",
                "day": f"2024{position % 12 + 1:02d}15",
                "foregone_family_output_bps": loss_bps,
                "input_usd": input_usd,
                "mature_exclusive_incumbent": mature_exclusive,
                "incumbent_known_prior": incumbent_known,
                "incumbent_retained": (
                    1.0 if position < 100 else 0.0 if position < 200 else np.nan
                ),
                "pair_age_days": pair_age,
                "both_v2_bridge_capitals_positive": both_capitals,
                "stable_v2_bridge_capital_usd": stable_capital,
                "native_v2_bridge_capital_usd": native_capital,
            }
        )

    result = output_consequence_rows(pd.DataFrame(rows))
    overall = result[result["record_type"].eq("family_output_consequence")].iloc[0]
    assert overall["routes"] == 400
    assert overall["lower_output_family_routes"] == 200
    assert overall["lower_output_family_share"] == pytest.approx(0.5)
    assert overall["input_value_weighted_foregone_bps"] == pytest.approx(5.0)
    assert overall["median_foregone_output_bps_if_over_1bp"] == pytest.approx(10.0)
    assert overall["p90_foregone_output_bps_if_over_1bp"] == pytest.approx(10.0)
    assert overall["weighting"] == "observed_route_input_value_usd"
    assert overall["output_difference_rule"] == "strictly_greater_than_threshold"
    assert not bool(overall["dollar_consequence_reported"])
    assert not bool(overall["gas_consequence_reported"])
    assert not bool(overall["causal_interpretation"])

    split = result[result["record_type"].eq("family_output_consequence_split")]
    expected_counts = {
        "incumbency_status": 400,
        "mature_exclusive_route_choice": 200,
        "pair_age": 400,
        "input_size": 400,
        "relative_v2_bridge_capital": 300,
    }
    for dimension, expected in expected_counts.items():
        cells = split[split["split_dimension"].eq(dimension)]
        assert cells["routes"].sum() == expected
        assert cells["cell_route_share"].sum() == pytest.approx(1.0)

    capital = split[
        split["split_dimension"].eq("relative_v2_bridge_capital")
    ].set_index("split_category")
    assert set(capital.index) == {
        "native_over_2x_stable",
        "within_2x",
        "stable_over_2x_native",
    }
    assert (capital["routes"] == 100).all()

    pair_age = split[split["split_dimension"].eq("pair_age")].set_index(
        "split_category"
    )
    thin = pair_age.loc[
        ["before_recorded_pair_entry", "pair_entry_date_unavailable"]
    ]
    assert (thin["routes"] == 50).all()
    assert not thin["cell_meets_minimum_support"].any()
    assert thin["input_value_weighted_foregone_bps"].isna().all()
    assert (result["minimum_cell_routes"] == MIN_CONSEQUENCE_CELL_ROUTES).all()
    assert (
        result["minimum_cell_ordered_pairs"]
        == MIN_CONSEQUENCE_CELL_PAIRS
    ).all()
    assert (
        result["minimum_conditional_loss_routes"]
        == MIN_CONSEQUENCE_LOSS_ROUTES
    ).all()


def test_fixed_effect_model_has_declared_two_way_inference() -> None:
    rng = np.random.default_rng(7)
    rows = []
    for pair in range(25):
        pair_effect = rng.normal(scale=0.2)
        for date in range(25):
            x = rng.normal()
            control = rng.normal()
            rows.append(
                {
                    "ordered_pair": f"pair-{pair}",
                    "day": f"2024-{date + 1:02d}",
                    "outcome": 0.4 * x + 0.1 * control + pair_effect + date / 50,
                    "x": x,
                    "control": control,
                }
            )
    rows.append(
        {
            "ordered_pair": "singleton",
            "day": "2024-01",
            "outcome": 100.0,
            "x": 100.0,
            "control": 100.0,
        }
    )
    result = _fit_model(
        pd.DataFrame(rows),
        model_id="synthetic",
        outcome="outcome",
        predictors=("x", "control"),
        sample="synthetic",
    ).set_index("regressor")

    assert result.loc["x", "coefficient"] == pytest.approx(0.4, abs=1e-8)
    assert result.loc["control", "coefficient"] == pytest.approx(0.1, abs=1e-8)
    assert result.loc["x", "ordered_pair_clusters"] == 25
    assert result.loc["x", "date_clusters"] == 25
    assert result.loc["x", "observations"] == 625
    assert result.loc["x", "complete_case_observations"] == 626
    assert result.loc["x", "singleton_pair_rows_dropped"] == 1
    assert result.loc["x", "covariance"] == (
        "two_way_ordered_pair_calendar_date_cr1"
    )

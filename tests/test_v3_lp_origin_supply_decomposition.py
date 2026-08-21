from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ddvc.tables import read_exhibit
from scripts.analyze.run_v3_lp_origin_supply_decomposition import (
    BASELINE_PERIOD,
    COMPARISON_PERIOD,
    USDC,
    WETH,
    exact_origin_decomposition,
    load_origin_supply_panel,
    run,
    valuation_support,
)


ENDPOINT = "0x00000000000000000000000000000000000000aa"
OTHER_ENDPOINT = "0x00000000000000000000000000000000000000bb"


def _exact_fixture() -> pd.DataFrame:
    # Total stable share rises from 1/4 to 7/10.  The hand-computed midpoint
    # components are 7/40, 7/96, 7/480, and 3/16.
    return pd.DataFrame(
        [
            (BASELINE_PERIOD, "A", 10.0, 30.0),
            (COMPARISON_PERIOD, "A", 10.0, 10.0),
            (BASELINE_PERIOD, "B", 10.0, 10.0),
            (COMPARISON_PERIOD, "B", 45.0, 15.0),
            (BASELINE_PERIOD, "X", 5.0, 35.0),
            (COMPARISON_PERIOD, "Y", 15.0, 5.0),
        ],
        columns=["period", "origin", "stable", "WETH"],
    )


def test_exact_origin_decomposition_reconciles_hand_computed_fixture() -> None:
    result, support = exact_origin_decomposition(
        _exact_fixture(),
        metric="fixture",
        stable_column="stable",
        WETH_column="WETH",
    )
    row = result.iloc[0]
    assert row["baseline_stable_share"] == pytest.approx(1 / 4)
    assert row["comparison_stable_share"] == pytest.approx(7 / 10)
    assert row["within_continuing_origin_change"] == pytest.approx(7 / 40)
    assert row["continuing_origin_reweighting"] == pytest.approx(7 / 96)
    assert row["common_support_mass_subterm"] == pytest.approx(7 / 480)
    assert row["exclusive_origin_share_change_subterm"] == pytest.approx(3 / 16)
    assert row["period_specific_origin_entry_exit"] == pytest.approx(97 / 480)
    assert row["total_change"] == pytest.approx(9 / 20)
    assert abs(row["identity_error"]) <= 1e-12
    counts = support.set_index("origin_membership")["origin_proxies"].to_dict()
    assert counts == {
        "continuing": 2,
        "baseline_exclusive": 1,
        "comparison_exclusive": 1,
    }

    reversed_panel = _exact_fixture().copy()
    reversed_panel["period"] = reversed_panel["period"].map(
        {BASELINE_PERIOD: COMPARISON_PERIOD, COMPARISON_PERIOD: BASELINE_PERIOD}
    )
    reverse, _support = exact_origin_decomposition(
        reversed_panel.sample(frac=1.0, random_state=7),
        metric="fixture",
        stable_column="stable",
        WETH_column="WETH",
    )
    reverse_row = reverse.iloc[0]
    for column in (
        "total_change",
        "within_continuing_origin_change",
        "continuing_origin_reweighting",
        "period_specific_origin_entry_exit",
        "common_support_mass_subterm",
        "exclusive_origin_share_change_subterm",
    ):
        assert reverse_row[column] == pytest.approx(-row[column])


def _input_panel(path: Path) -> None:
    fixture = _exact_fixture()
    period_date = {
        BASELINE_PERIOD: pd.Timestamp("2024-03-01"),
        COMPARISON_PERIOD: pd.Timestamp("2026-03-01"),
    }
    rows: list[dict[str, object]] = []
    for row in fixture.itertuples(index=False):
        for candidate, actions in ((USDC, row.stable), (WETH, row.WETH)):
            if actions <= 0:
                continue
            rows.append(
                {
                    "origin_date": period_date[row.period],
                    "origin": row.origin.lower(),
                    "candidate_address": candidate,
                    "paired_token_address": ENDPOINT,
                    "v3_add_action_events": actions,
                    "v3_add_flow_priced_assignments": actions,
                    "v3_add_flow_screened_assignments": actions,
                    "v3_add_flow_missing_price_assignments": 0.0,
                    "v3_add_flow_nonpositive_value_assignments": 0.0,
                    "v3_add_flow_above_screen_assignments": 0.0,
                    "v3_add_flow_usd_screened": actions,
                }
            )
    # A stable--WETH core row and an out-of-window row must not enter.
    rows.extend(
        [
            {
                "origin_date": pd.Timestamp("2024-03-01"),
                "origin": "core",
                "candidate_address": USDC,
                "paired_token_address": WETH,
                "v3_add_action_events": 999.0,
                "v3_add_flow_priced_assignments": 999.0,
                "v3_add_flow_screened_assignments": 999.0,
                "v3_add_flow_missing_price_assignments": 0.0,
                "v3_add_flow_nonpositive_value_assignments": 0.0,
                "v3_add_flow_above_screen_assignments": 0.0,
                "v3_add_flow_usd_screened": 999.0,
            },
            {
                "origin_date": pd.Timestamp("2025-03-01"),
                "origin": "outside",
                "candidate_address": WETH,
                "paired_token_address": OTHER_ENDPOINT,
                "v3_add_action_events": 999.0,
                "v3_add_flow_priced_assignments": 999.0,
                "v3_add_flow_screened_assignments": 999.0,
                "v3_add_flow_missing_price_assignments": 0.0,
                "v3_add_flow_nonpositive_value_assignments": 0.0,
                "v3_add_flow_above_screen_assignments": 0.0,
                "v3_add_flow_usd_screened": 999.0,
            },
        ]
    )
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_v3_origin_supply_run_filters_core_and_reports_network_support(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "origins.parquet"
    decomposition_path = tmp_path / "decomposition.jsonl"
    support_path = tmp_path / "support.jsonl"
    _input_panel(input_path)

    panel, network, overlap = load_origin_supply_panel(input_path)
    assert set(panel["origin"]) == {"a", "b", "x", "y"}
    assert set(network["active_origins"]) == {3}
    assert set(network["origin_endpoint_links"]) == {3}
    assert set(overlap["active_origin_proxies"]) == {3}
    checked = valuation_support(network)
    assert checked["flow_reliable"].all()
    assert (checked["excluded_valuation_assignment_share"] == 0).all()

    assert (
        run(
            origin_path=input_path,
            decomposition_output=decomposition_path,
            support_output=support_path,
        )
        == 0
    )
    results = read_exhibit(decomposition_path).set_index("metric")
    assert set(results.index) == {
        "lp_add_actions",
        "screened_candidate_side_usd_flow",
    }
    assert results.loc["lp_add_actions", "total_change"] == pytest.approx(9 / 20)
    assert results.loc[
        "screened_candidate_side_usd_flow", "total_change"
    ] == pytest.approx(9 / 20)


def test_valuation_gate_rejects_excess_exclusions() -> None:
    network = pd.DataFrame(
        [
            {
                "period": BASELINE_PERIOD,
                "vehicle_type": "stable",
                "active_origins": 1,
                "origin_endpoint_links": 1,
                "add_actions": 100.0,
                "screened_candidate_side_flow_usd": 98.0,
                "priced_assignments": 100.0,
                "screened_assignments": 98.0,
                "missing_price_assignments": 0.0,
                "nonpositive_assignments": 0.0,
                "above_screen_assignments": 2.0,
            }
        ]
    )
    with pytest.raises(ValueError, match="fails the declared valuation gate"):
        valuation_support(network)

from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.build_contestable_vehicle_choice_values import (
    render_contestable_vehicle_choice_values,
)


def _estimate_rows() -> list[dict[str, object]]:
    return [
        {
            "record_type": "contestable_vehicle_choice_regression",
            "model_id": "stable_choice_price_leader",
            "sample": "contestable_symmetric_common_support",
            "outcome": "chosen_stable",
            "regressor": "stable_price_leader",
            "coefficient_pp": 57.594,
            "standard_error_pp": 2.839,
            "observations": 49_212,
        },
        {
            "record_type": "contestable_vehicle_choice_regression",
            "model_id": "exclusive_incumbent_retention_price_leader",
            "sample": "mature_exclusive_entry_symmetric_common_support",
            "outcome": "incumbent_retained",
            "regressor": "challenger_price_leader",
            "coefficient_pp": -58.081,
            "standard_error_pp": 2.816,
            "observations": 34_439,
        },
        {
            "record_type": "contestable_vehicle_choice_regression",
            "model_id": "exclusive_retention_price_v2_capital",
            "sample": "mature_exclusive_entry_positive_v2_bridge_capital",
            "outcome": "incumbent_retained",
            "regressor": "incumbent_output_advantage_100bp",
            "coefficient_pp": 10.127,
            "standard_error_pp": 0.768,
            "observations": 17_778,
        },
        {
            "record_type": "contestable_vehicle_choice_regression",
            "model_id": "exclusive_retention_price_v2_capital",
            "sample": "mature_exclusive_entry_positive_v2_bridge_capital",
            "outcome": "incumbent_retained",
            "regressor": "incumbent_v2_capital_advantage_10pp",
            "coefficient_pp": 2.774,
            "standard_error_pp": 0.607,
            "observations": 17_778,
        },
    ]


def _support_rows() -> list[dict[str, object]]:
    return [
        {
            "record_type": "incumbent_price_relation_summary",
            "sample": "incumbent_price_leader",
            "routes": 25_621,
            "incumbent_retained_share": 0.93314,
            "lower_output_family_share": None,
            "median_foregone_output_bps_if_over_1bp": None,
            "p90_foregone_output_bps_if_over_1bp": None,
            "input_value_weighted_foregone_bps": None,
        },
        {
            "record_type": "incumbent_price_relation_summary",
            "sample": "challenger_price_leader",
            "routes": 10_663,
            "incumbent_retained_share": 0.27206,
            "lower_output_family_share": None,
            "median_foregone_output_bps_if_over_1bp": None,
            "p90_foregone_output_bps_if_over_1bp": None,
            "input_value_weighted_foregone_bps": None,
        },
        {
            "record_type": "family_output_consequence",
            "sample": "contestable_symmetric_common_support",
            "routes": 52_477,
            "incumbent_retained_share": None,
            "lower_output_family_share": 0.12931,
            "median_foregone_output_bps_if_over_1bp": 27.2358,
            "p90_foregone_output_bps_if_over_1bp": 171.482,
            "input_value_weighted_foregone_bps": 7.4183,
        },
    ]


def test_contestable_choice_values_render_decisive_macros() -> None:
    rendered = render_contestable_vehicle_choice_values(
        pd.DataFrame(_estimate_rows()),
        pd.DataFrame(_support_rows()),
    )

    expected = (
        r"\newcommand{\ContestPriceLeaderEffect}{$+57.59$ pp}",
        r"\newcommand{\ContestPriceLeaderSE}{$2.84$ pp}",
        r"\newcommand{\ContestPriceLeaderN}{49{,}212}",
        r"\newcommand{\ContestChallengerEffect}{$-58.08$ pp}",
        r"\newcommand{\ContestChallengerSE}{$2.82$ pp}",
        r"\newcommand{\ContestChallengerN}{34{,}439}",
        r"\newcommand{\ContestOutputAdvantageHundredBpEffect}{$+10.13$ pp}",
        r"\newcommand{\ContestOutputAdvantageHundredBpSE}{$0.77$ pp}",
        r"\newcommand{\ContestOutputAdvantageHundredBpN}{17{,}778}",
        r"\newcommand{\ContestCapitalAdvantageTenPpEffect}{$+2.77$ pp}",
        r"\newcommand{\ContestCapitalAdvantageTenPpSE}{$0.61$ pp}",
        r"\newcommand{\ContestCapitalAdvantageTenPpN}{17{,}778}",
        r"\newcommand{\ContestIncumbentLeaderRetention}{93.3\%}",
        r"\newcommand{\ContestIncumbentLeaderN}{25{,}621}",
        r"\newcommand{\ContestChallengerLeaderRetention}{27.2\%}",
        r"\newcommand{\ContestChallengerLeaderN}{10{,}663}",
        r"\newcommand{\ContestLowerOutputFamilyShare}{12.9\%}",
        r"\newcommand{\ContestForegoneMedianBps}{27.2 bp}",
        r"\newcommand{\ContestForegonePNinetyBps}{171.5 bp}",
        r"\newcommand{\ContestForegoneInputValueWeightedBps}{7.4 bp}",
    )
    for macro in expected:
        assert macro in rendered
    assert rendered.count(r"\newcommand{") == len(expected)


def test_contestable_choice_values_reject_missing_row() -> None:
    with pytest.raises(ValueError, match="expected one row"):
        render_contestable_vehicle_choice_values(
            pd.DataFrame(_estimate_rows()[:-1]),
            pd.DataFrame(_support_rows()),
        )


def test_contestable_choice_values_reject_changed_direction() -> None:
    estimates = _estimate_rows()
    estimates[1]["coefficient_pp"] = 1.0
    with pytest.raises(ValueError, match="coefficient directions changed"):
        render_contestable_vehicle_choice_values(
            pd.DataFrame(estimates),
            pd.DataFrame(_support_rows()),
        )


def test_contestable_choice_values_reject_invalid_consequence_ordering() -> None:
    support = _support_rows()
    support[2]["p90_foregone_output_bps_if_over_1bp"] = 10.0
    with pytest.raises(ValueError, match="invalid ordering"):
        render_contestable_vehicle_choice_values(
            pd.DataFrame(_estimate_rows()),
            pd.DataFrame(support),
        )

from __future__ import annotations

import pandas as pd
import pytest

from scripts.tabulate.render_first_contestable_vehicle_choice import (
    render_first_contestable_vehicle_choice,
    render_first_contestable_vehicle_choice_values,
)


def _model_rows() -> list[dict[str, object]]:
    common = {
        "record_type": "first_contestable_vehicle_choice_regression",
        "fixed_effects": (
            "calendar_date+source_token+destination_token+observed_route_scope"
        ),
        "covariance": "two_way_ordered_pair_calendar_date_cr1",
        "choice_timing": "first_sampled_exact_contestable_date_after_entry",
        "capital_timing": "exact_prior_calendar_day",
        "entry_value_threshold_usd": 5_000.0,
        "minimum_route_input_usd": 100.0,
        "maximum_leg_price_impact": 0.05,
        "value_agreement_threshold": 0.20,
    }
    specifications = (
        (
            "price_only_all_first_contestable",
            "all_first_sampled_exact_contestable_routes",
            "chosen_stable",
            995,
            580,
            64,
            0.221106,
            0.161963,
            (
                ("stable_output_advantage_100bp", 6.392395, 0.753087, 0.001),
                ("log_input_usd", -2.512694, 1.614009, 0.125),
            ),
        ),
        (
            "r1_entry_retention_price_only",
            "clear_entry_family_first_contestable_positive_capital",
            "entry_vehicle_retained",
            219,
            114,
            27,
            0.849315,
            0.151610,
            (
                (
                    "entry_vehicle_output_advantage_100bp",
                    10.306266,
                    3.934109,
                    0.014,
                ),
                ("log_input_usd", -4.013627, 4.901150, 0.420),
            ),
        ),
        (
            "r3_entry_retention_price_and_capital",
            "clear_entry_family_first_contestable_positive_capital",
            "entry_vehicle_retained",
            219,
            114,
            27,
            0.849315,
            0.151895,
            (
                (
                    "entry_vehicle_output_advantage_100bp",
                    10.203229,
                    4.158186,
                    0.021,
                ),
                (
                    "entry_vehicle_v2_capital_share_10pp",
                    1.853992,
                    4.584395,
                    0.689,
                ),
                ("log_input_usd", -3.905429, 5.007166, 0.442),
            ),
        ),
    )
    rows: list[dict[str, object]] = []
    for (
        model_id,
        sample,
        outcome,
        observations,
        pairs,
        dates,
        dependent_mean,
        within_r_squared,
        regressors,
    ) in specifications:
        for regressor, coefficient, standard_error, p_value in regressors:
            rows.append(
                {
                    **common,
                    "model_id": model_id,
                    "sample": sample,
                    "outcome": outcome,
                    "regressor": regressor,
                    "coefficient_pp": coefficient,
                    "standard_error_pp": standard_error,
                    "p_value": p_value,
                    "observations": observations,
                    "ordered_pairs": pairs,
                    "dates": dates,
                    "ordered_pair_clusters": pairs,
                    "date_clusters": dates,
                    "dependent_mean": dependent_mean,
                    "within_r_squared": within_r_squared,
                }
            )
    # The saturated stable-choice capital model is deliberately outside the
    # displayed ladder.  Its presence in the input must not expose it.
    rows.append(
        {
            **common,
            "model_id": "c3_price_and_capital_common_sample",
            "sample": "first_contestable_positive_both_family_prior_v2_capital",
            "outcome": "chosen_stable",
            "regressor": "stable_v2_capital_share_10pp",
            "coefficient_pp": -99.99,
            "standard_error_pp": 9.99,
            "p_value": 0.001,
            "observations": 220,
            "ordered_pairs": 115,
            "dates": 27,
            "ordered_pair_clusters": 115,
            "date_clusters": 27,
            "dependent_mean": 0.20,
            "within_r_squared": 0.14,
        }
    )
    return rows


def _support_rows() -> list[dict[str, object]]:
    return [
        {
            "record_type": "first_contestable_vehicle_choice_support",
            "sample": "material_entry_cohort",
            "entry_pairs": 118_447,
            "entry_dates": 2_090,
            "pairs_reaching_sampled_contestability": 580,
            "contestability_coverage_share": 580 / 118_447,
            "entry_value_threshold_usd": 5_000.0,
        },
        {
            "record_type": "first_contestable_vehicle_choice_support",
            "sample": "first_sampled_exact_contestable_routes",
            "routes": 995,
            "ordered_pairs": 580,
            "dates": 64,
        },
        {
            "record_type": "first_contestable_vehicle_choice_support",
            "sample": "entry_to_first_sampled_contestability_lag",
            "pairs": 580,
            "median_days": 115.5,
            "p25_days": 21.0,
            "p75_days": 318.5,
            "p90_days": 621.6,
            "within_120_days_share": 0.532759,
        },
        {
            "record_type": "first_contestable_vehicle_choice_support",
            "sample": "entry_vehicle_survival",
            "route_weighted_retention_share": 0.831102,
            "route_weighted_routes": 971,
            "equal_pair_retention_share": 0.843806,
            "equal_pair_pairs": 557,
        },
        {
            "record_type": "first_contestable_vehicle_choice_support",
            "sample": "positive_both_family_prior_v2_capital",
            "routes": 220,
            "ordered_pairs": 115,
            "dates": 27,
        },
    ]


def test_first_contest_table_distinguishes_entry_and_exact_contest() -> None:
    rendered = render_first_contestable_vehicle_choice(
        pd.DataFrame(_model_rows()), pd.DataFrame(_support_rows())
    )

    assert rendered.count(r"\begin{tabularx}{\linewidth}") == 2
    assert "Panel A. From original pair entry to the first sampled exact contest" in rendered
    assert (
        "Original pair-entry cohort & 118,447 pairs & "
        "2,090 entry dates; \\$5,000 minimum"
    ) in rendered
    assert "First sampled exact contest & 580 pairs & 995 routes" in rendered
    assert "Entry pairs reaching a sampled contest & 0.5\\%" in rendered
    assert "Entry-to-contest lag [days] & 115.5 median & 21--318.5" in rendered
    assert "Entry family retained, clear comparisons" in rendered
    assert "83.1\\% of routes & 84.4\\% of pairs" in rendered
    assert "Panel B. Route choice at the first sampled exact contest" in rendered
    assert "Stablecoin current exact-output advantage [per 100 bp]" in rendered
    assert "Entry-family current exact-output advantage [per 100 bp]" in rendered
    assert "Entry-family prior-day V2 weak-leg capital share [per 10 pp]" in rendered
    assert "$+6.39^{***}$" in rendered
    assert "$+10.31^{**}$" in rendered
    assert "$+10.20^{**}$" in rendered
    assert "$+1.85$" in rendered
    assert "Prior-day V2 capital positive for both families & No & Yes & Yes" in rendered
    assert "-99.99" not in rendered
    for forbidden in (
        "candidate",
        "claim",
        "diagnos",
        "pipeline",
        "rather than",
        "screen",
        "workflow",
    ):
        assert forbidden not in rendered.lower()


def test_first_contest_values_share_the_table_rows() -> None:
    rendered = render_first_contestable_vehicle_choice_values(
        pd.DataFrame(_model_rows()), pd.DataFrame(_support_rows())
    )

    expected = (
        r"\newcommand{\FirstContestEntryPairs}{118{,}447}",
        r"\newcommand{\FirstContestEntryValueThreshold}{\$5{,}000}",
        r"\newcommand{\FirstContestPairs}{580}",
        r"\newcommand{\FirstContestCoverage}{0.5\%}",
        r"\newcommand{\FirstContestMedianLagDays}{115.5}",
        r"\newcommand{\FirstContestRouteRetention}{83.1\%}",
        r"\newcommand{\FirstContestPairRetention}{84.4\%}",
        r"\newcommand{\FirstContestStableOutputEffect}{$+6.39$ pp}",
        r"\newcommand{\FirstContestStableOutputSE}{$0.75$ pp}",
        r"\newcommand{\FirstContestRetentionOutputOnlyEffect}{$+10.31$ pp}",
        r"\newcommand{\FirstContestRetentionJointOutputEffect}{$+10.20$ pp}",
        r"\newcommand{\FirstContestRetentionJointCapitalEffect}{$+1.85$ pp}",
        r"\newcommand{\FirstContestRetentionRegressionN}{219}",
        r"\newcommand{\FirstContestRetentionRegressionPairs}{114}",
    )
    for macro in expected:
        assert macro in rendered
    assert "StableChoiceCapital" not in rendered
    assert "-99.99" not in rendered


def test_first_contest_table_rejects_different_retention_samples() -> None:
    rows = _model_rows()
    for row in rows:
        if row["model_id"] == "r3_entry_retention_price_and_capital":
            row["observations"] = 218
    with pytest.raises(ValueError, match="nested retention models use different samples"):
        render_first_contestable_vehicle_choice(
            pd.DataFrame(rows), pd.DataFrame(_support_rows())
        )


def test_first_contest_table_rejects_inconsistent_entry_coverage() -> None:
    support = _support_rows()
    support[0]["contestability_coverage_share"] = 0.5
    with pytest.raises(ValueError, match="coverage is inconsistent"):
        render_first_contestable_vehicle_choice(
            pd.DataFrame(_model_rows()), pd.DataFrame(support)
        )

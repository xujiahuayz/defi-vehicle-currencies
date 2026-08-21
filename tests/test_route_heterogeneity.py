from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analyze.run_route_heterogeneity import (
    endpoint_year_calendar_comparison,
    paired_calendar_comparison,
    render_heterogeneity_deck_values,
    route_heterogeneity_results,
    strict_value_non_weth_composition,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


def panel() -> pd.DataFrame:
    rows = []
    for pair_index in range(8):
        for day in range(1, 7):
            for scope in ("single_venue", "cross_venue"):
                for metric in ("count_share", "matched_strict_count_share"):
                    for year, stable in ((2024, 2 + pair_index % 2), (2026, 6 + pair_index % 2)):
                        native = 10 - stable
                        rows.append(
                            {
                                "metric": metric,
                                "year": year,
                                "date": pd.Timestamp(year, 1, day),
                                "src": f"s{pair_index}",
                                "tgt": f"t{pair_index}",
                                "month_day": f"01-{day:02d}",
                                "integration_scope": scope,
                                "native": native,
                                "stable": stable,
                                "denominator": 10,
                                "stable_share": stable / 10,
                            }
                        )
    return pd.DataFrame(rows)


def heterogeneity_panel() -> pd.DataFrame:
    """A supported matched panel with declared scope and baseline-state variation."""

    rows = []
    for pair_index in range(180):
        baseline_state = pair_index % 3
        weth_endpoint = pair_index % 30 == 0
        for day in range(1, 6):
            for scope in ("single_venue", "cross_venue"):
                baseline_stable = (0, 4, 10)[baseline_state]
                comparison_stable = {
                    (0, "single_venue"): 3,
                    (0, "cross_venue"): 5,
                    (1, "single_venue"): 5,
                    (1, "cross_venue"): 7,
                    (2, "single_venue"): 9,
                    (2, "cross_venue"): 8,
                }[(baseline_state, scope)] + ((day % 3) - 1)
                comparison_stable = min(max(comparison_stable, 0), 10)
                if weth_endpoint:
                    baseline_stable = comparison_stable = 10
                for metric in (
                    "count_share",
                    "matched_strict_count_share",
                    "strict_intermediation_value_share",
                ):
                    denominator = 10 if metric != "strict_intermediation_value_share" else 10.25
                    for year, stable_units in (
                        (2024, baseline_stable),
                        (2026, comparison_stable),
                    ):
                        share = stable_units / 10
                        rows.append(
                            {
                                "metric": metric,
                                "year": year,
                                "date": pd.Timestamp(year, 1, day),
                                "src": WETH if weth_endpoint else f"s{pair_index}",
                                "tgt": f"t{pair_index}",
                                "month_day": f"01-{day:02d}",
                                "integration_scope": scope,
                                "native": denominator * (1 - share),
                                "stable": denominator * share,
                                "denominator": denominator,
                                "stable_share": share,
                            }
                        )
    return pd.DataFrame(rows)


def test_paired_calendar_reports_ordinary_and_hac_t() -> None:
    rows = paired_calendar_comparison(panel(), "count_share", hac_lag=2)
    assert [row["method"] for row in rows] == ["paired_calendar_t", "paired_calendar_hac_t"]
    assert all(np.isclose(row["coefficient"], 0.4) for row in rows)
    assert all("calendar-day ratio of total stable" in row["estimand"] for row in rows)
    assert all("activity_reallocation_across_cells" in row["interpretation"] for row in rows)


def test_heterogeneity_packet_declares_families_and_mechanical_boundary() -> None:
    results = route_heterogeneity_results(heterogeneity_panel())
    estimates = results[results["row_type"].eq("estimate")]
    assessments = results[results["row_type"].eq("assessment")]

    assert len(results) == 66
    assert len(estimates) == 54
    assert len(assessments) == 12
    assert estimates["p_value_holm"].notna().all()
    assert set(
        estimates.loc[
            estimates["analysis_block"].eq("ex_ante_integration_scope"),
            "declaration_status",
        ]
    ) == {"locked_panel_dimension_predeclared_before_estimation"}
    assert set(
        estimates.loc[
            estimates["analysis_block"].eq(
                "appendix_mechanical_baseline_state_bounds"
            ),
            "level",
        ]
    ) == {"zero_stable", "mixed_native_stable", "all_stable"}
    assert estimates.loc[
        estimates["dimension"].eq("baseline_stable_state"),
        "mechanical_boundary",
    ].notna().all()
    identity = assessments[
        assessments["analysis_block"].eq("mechanical_weth_endpoint_identity")
    ]
    assert set(identity["metric"]) == {
        "count_share",
        "matched_strict_count_share",
        "strict_intermediation_value_share",
    }
    assert identity["stable_share_minimum"].eq(1).all()
    assert identity["stable_share_maximum"].eq(1).all()
    assert identity["native_mass_maximum"].eq(0).all()
    weth_estimates = estimates[
        estimates["analysis_block"].eq("weth_endpoint_mechanical_allocation")
    ]
    assert set(weth_estimates["level"]) == {
        "full_matched_panel",
        "exclude_WETH_endpoints",
    }
    assert set(
        weth_estimates[weth_estimates["method"].isin(
            ["paired_calendar_hac_t", "endpoint_year_calendar_hac_t"]
        )]["method"]
    ) == {"paired_calendar_hac_t", "endpoint_year_calendar_hac_t"}
    assert "interpretation_survives" not in results.columns
    attrition = assessments[
        assessments["analysis_block"].eq("major_endpoint_leave_three_support")
    ]
    assert attrition["interpretation"].eq(
        "severe_support_attrition_precludes_robustness_language"
    ).all()


def test_weth_endpoint_identity_violation_is_rejected() -> None:
    data = heterogeneity_panel()
    row = data.index[
        data["metric"].eq("strict_intermediation_value_share")
        & data["src"].eq(WETH)
    ][0]
    data.loc[row, "stable_share"] = 0.9
    data.loc[row, "stable"] = 0.9 * data.loc[row, "denominator"]
    data.loc[row, "native"] = 0.1 * data.loc[row, "denominator"]
    with pytest.raises(RuntimeError, match="mechanical WETH-endpoint intermediary identity"):
        route_heterogeneity_results(data)


def test_heterogeneity_deck_values_carry_sample_boundary() -> None:
    results = route_heterogeneity_results(heterogeneity_panel())
    results.loc[
        results["method"].eq("endpoint_year_calendar_hac_t"), "observations"
    ] = 362
    rendered = render_heterogeneity_deck_values(results)
    assert "% Supporting descriptive analysis" in rendered
    assert "% SAMPLE: exact two-leg native-WETH-versus-stablecoin routes" in rendered
    assert r"\newcommand{\WethCountFullChange}" in rendered
    assert r"\newcommand{\WethCountNoEndpointChange}" in rendered
    assert r"\newcommand{\WethValueFullChange}" in rendered
    assert r"\newcommand{\WethValueNoEndpointChange}" in rendered
    assert r"\newcommand{\WethValueActivityChange}" in rendered
    assert r"\newcommand{\WethValueWithinChange}" in rendered


def test_current_value_covariance_sensitivities_and_midpoint_identity_are_locked() -> None:
    data = pd.read_parquet(
        "output/exhibits/vehicle_transition_pair_panel.parquet"
    )
    value = data[data["metric"].eq("strict_intermediation_value_share")]
    no_weth = value[~value["src"].eq(WETH) & ~value["tgt"].eq(WETH)]

    full_paired = paired_calendar_comparison(
        value, "strict_intermediation_value_share"
    )[1]
    full_endpoint = endpoint_year_calendar_comparison(
        value, "strict_intermediation_value_share"
    )
    no_weth_paired = paired_calendar_comparison(
        no_weth, "strict_intermediation_value_share"
    )[1]
    no_weth_endpoint = endpoint_year_calendar_comparison(
        no_weth, "strict_intermediation_value_share"
    )
    assert np.isclose(full_paired["coefficient"], 0.27196774895523634)
    assert np.isclose(full_paired["standard_error"], 0.010077745023324846)
    assert np.isclose(full_endpoint["standard_error"], 0.019115609378496257)
    assert np.isclose(no_weth_paired["coefficient"], 0.21492301263750363)
    assert np.isclose(no_weth_paired["standard_error"], 0.037879486776266104)
    assert np.isclose(no_weth_endpoint["standard_error"], 0.0489968043345453)

    decomposition = strict_value_non_weth_composition(data)
    primary = decomposition[
        decomposition["method"].eq(
            "endpoint_year_midpoint_kitagawa_calendar_hac"
        )
        & decomposition["hac_lag"].eq(30)
    ].set_index("level")
    assert np.isclose(primary.loc["total_change", "coefficient"], 0.21492301263750313)
    assert np.isclose(
        primary.loc["activity_weight_reallocation", "coefficient"],
        0.23519763598200283,
    )
    assert np.isclose(
        primary.loc["within_group_share_change", "coefficient"],
        -0.020274623344499365,
    )
    assert np.isclose(
        primary.loc["total_change", "coefficient"],
        primary.loc["activity_weight_reallocation", "coefficient"]
        + primary.loc["within_group_share_change", "coefficient"],
        atol=1e-12,
    )
    assert primary["identity_residual_max_abs"].max() < 1e-12

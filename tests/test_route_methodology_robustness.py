from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from scripts.run_route_methodology_robustness import (
    clustered_ecdf_randomisation,
    conventional_ks_rejection,
    endpoint_year_calendar_comparison,
    grouped_binomial_fixed_effects,
    paired_calendar_comparison,
    provisional_snapshot_identity,
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


def test_grouped_binomial_detects_positive_odds_change_without_expansion() -> None:
    result = grouped_binomial_fixed_effects(panel(), "count_share")
    assert result["coefficient"] > 0
    assert result["odds_ratio"] > 1
    assert result["observations"] == 192
    assert result["matched_cells"] == 96
    assert result["separated_cells_excluded"] == 0


def test_paired_calendar_reports_ordinary_and_hac_t() -> None:
    rows = paired_calendar_comparison(panel(), "count_share", hac_lag=2)
    assert [row["method"] for row in rows] == ["paired_calendar_t", "paired_calendar_hac_t"]
    assert all(np.isclose(row["coefficient"], 0.4) for row in rows)
    assert all("calendar-day ratio of total stable" in row["estimand"] for row in rows)
    assert all("activity_reallocation_across_cells" in row["interpretation"] for row in rows)


def test_clustered_ecdf_randomisation_is_reproducible() -> None:
    result, draws = clustered_ecdf_randomisation(
        panel(), "count_share", weighting="symmetric_denominator_mass", replications=19, seed=7
    )
    result_again, draws_again = clustered_ecdf_randomisation(
        panel(), "count_share", weighting="symmetric_denominator_mass", replications=19, seed=7
    )
    assert result["coefficient"] > 0
    assert result["replications"] == 19
    assert result["distribution_weighting"] == "symmetric_denominator_mass"
    pd.testing.assert_frame_equal(draws, draws_again)
    assert result == result_again


def test_conventional_ks_is_recorded_as_rejected_not_authority() -> None:
    result = conventional_ks_rejection(panel(), "count_share")
    assert result["coefficient"] > 0
    assert result["interpretation"] == "rejected_inference_diagnostic_statistic_only"
    assert "cluster sign-randomised" in result["rejection_reason"]


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


def test_heterogeneity_deck_values_carry_generation_and_sample_boundary() -> None:
    results = route_heterogeneity_results(heterogeneity_panel())
    results.loc[
        results["method"].eq("endpoint_year_calendar_hac_t"), "observations"
    ] = 362
    rendered = render_heterogeneity_deck_values(
        results,
        d3_generation="d3-generation",
        endpoint_generation="endpoint-generation",
    )
    assert "% EVIDENCE-STATUS: E0 pending clean J0" in rendered
    assert "% EVIDENCE-D3-GENERATION: d3-generation" in rendered
    assert "% EVIDENCE-ENDPOINT-GENERATION: endpoint-generation" in rendered
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
    assert np.isclose(full_paired["coefficient"], 0.2716630073441233)
    assert np.isclose(full_paired["standard_error"], 0.0100291928267671)
    assert np.isclose(full_endpoint["standard_error"], 0.0191261927779916)
    assert np.isclose(no_weth_paired["coefficient"], 0.2148034489726663)
    assert np.isclose(no_weth_paired["standard_error"], 0.0378514203450401)
    assert np.isclose(no_weth_endpoint["standard_error"], 0.0490210507834651)

    decomposition = strict_value_non_weth_composition(data)
    primary = decomposition[
        decomposition["method"].eq(
            "endpoint_year_midpoint_kitagawa_calendar_hac"
        )
        & decomposition["hac_lag"].eq(30)
    ].set_index("level")
    assert np.isclose(primary.loc["total_change", "coefficient"], 0.2148034489726663)
    assert np.isclose(
        primary.loc["activity_weight_reallocation", "coefficient"],
        0.2352037668438225,
    )
    assert np.isclose(
        primary.loc["within_group_share_change", "coefficient"],
        -0.0204003178711562,
    )
    assert np.isclose(
        primary.loc["total_change", "coefficient"],
        primary.loc["activity_weight_reallocation", "coefficient"]
        + primary.loc["within_group_share_change", "coefficient"],
        atol=1e-12,
    )
    assert primary["identity_residual_max_abs"].max() < 1e-12


def test_provisional_snapshot_accepts_only_release_member_drift(tmp_path, monkeypatch) -> None:
    member = "data/processed/release/generations/g/member.parquet"
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        json.dumps(
            {
                "status": "pass",
                "specification_stage": "design_seed",
                "executable_claim_ids": ["vehicle_transition"],
                "generation": "d3-generation",
                "claim_inputs": [
                    {
                        "input_kind": "release_pointer",
                        "release_generation": "endpoint-generation",
                        "release_artifacts": [{"path": member}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.run_route_methodology_robustness.verify",
        lambda _path: {
            "content_current": True,
            "code_current": True,
            "changed_inputs": [member],
        },
    )
    identity = provisional_snapshot_identity(tmp_path / "panel.parquet", certificate)
    assert identity == {
        "d3_generation": "d3-generation",
        "endpoint_generation": "endpoint-generation",
    }


def test_provisional_snapshot_rejects_out_of_perimeter_drift(tmp_path, monkeypatch) -> None:
    certificate = tmp_path / "certificate.json"
    certificate.write_text(
        json.dumps(
            {
                "status": "pass",
                "specification_stage": "design_seed",
                "executable_claim_ids": ["vehicle_transition"],
                "generation": "d3-generation",
                "claim_inputs": [
                    {
                        "input_kind": "release_pointer",
                        "release_generation": "endpoint-generation",
                        "release_artifacts": [{"path": "member.parquet"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.run_route_methodology_robustness.verify",
        lambda _path: {
            "content_current": True,
            "code_current": True,
            "changed_inputs": ["other.parquet"],
        },
    )
    try:
        provisional_snapshot_identity(tmp_path / "panel.parquet", certificate)
    except RuntimeError as exc:
        assert "out-of-perimeter" in str(exc)
    else:
        raise AssertionError("out-of-perimeter drift was admitted")

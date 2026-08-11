from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from ddvc.analysis.dominance_cost_contract import COMPARATOR_VEHICLES, NATIVE_VEHICLE
from ddvc.analysis.dominance_cost_e0 import (
    FIT_LEDGER,
    LIQUIDITY_MECHANISM_CONTROLS,
    RISK_CONTROLS,
    fit_dominance_cost_e0,
    prepare_analysis_panel,
)
from ddvc.analysis.regression import absorb_fixed_effects, ols_clustered
import ddvc.analysis.dominance_cost_e0 as e0
from scripts import run_dominance_cost_e0 as runner


COMPARATORS = {symbol: address for address, symbol in COMPARATOR_VEHICLES.items()}
CANDIDATES = [(NATIVE_VEHICLE, "WETH"), *sorted((address, symbol) for symbol, address in COMPARATORS.items())]


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2020-01-01", periods=84, freq="MS")
    controls = []
    for day_index, date in enumerate(dates):
        for candidate_index, (address, symbol) in enumerate(CANDIDATES):
            controls.append(
                {
                    "origin_date": date,
                    "candidate_address": address,
                    "candidate_symbol": symbol,
                    "covariate_observation_cutoff_date": date - pd.Timedelta(days=1),
                    "covariate_lag_days": 1,
                    "lag1_candidate_log_return": 0.003 * np.sin((day_index + 1) * (candidate_index + 1)) + 0.00001 * candidate_index * day_index**2,
                    "lag1_candidate_return_supported": not (day_index == 0 and symbol == "DAI"),
                    "lag1_candidate_trailing_30d_volatility": 0.01 + 0.0002 * candidate_index * (day_index + 1) + 0.00001 * day_index**2,
                    "lag1_candidate_volatility_supported": not (day_index == 0 and symbol == "DAI"),
                    "lag1_route_day_supported": not (day_index == 1 and symbol == "USDC"),
                    "lag1_route_endpoint_supported": not (day_index == 1 and symbol == "USDC"),
                    "lag1_intermediary_episode_share": 0.05 + 0.003 * candidate_index + 0.0002 * day_index * (candidate_index + 1),
                    "lag1_vehicle_excess_use_count_ratio": 0.7 + 0.02 * candidate_index + 0.001 * day_index**2 * (candidate_index + 1) + 0.000001 * day_index**3 * (candidate_index + 2) ** 2,
                    "lag1_route_total_count": 50 + 7 * candidate_index + day_index**2 * (candidate_index + 1),
                    "lag1_v2_capital_day_supported": not (day_index == 2 and symbol == "WBTC"),
                    "lag1_v2_log1p_deposited_capital_usd": 8 + 0.1 * candidate_index + 0.002 * day_index**2 * (candidate_index + 1) + 0.0000001 * day_index**4 * (candidate_index + 3) ** 2,
                    "lag1_v2_five_candidate_capital_share": 0.1 + 0.01 * candidate_index + 0.0003 * day_index * candidate_index + 0.0001 * np.sin((day_index + 1) * (candidate_index + 1)),
                    "lag1_v3_flow_day_supported": not (day_index == 2 and symbol == "WBTC"),
                    "lag1_v3_signed_log1p_net_flow_per_1000": (-1) ** candidate_index * (0.2 + 0.01 * day_index * (candidate_index + 1)) + 0.0002 * np.cos((day_index + 2) * (candidate_index + 1)),
                    "lag1_v3_gross_candidate_flow_share": 0.08 + 0.008 * candidate_index + 0.0004 * day_index + 0.00001 * day_index**2 * (candidate_index + 1) + 0.0001 * np.sin((day_index + 3) * (candidate_index + 2)),
                }
            )
    candidate_day = pd.DataFrame(controls)

    pairs = []
    rng = np.random.default_rng(20260812)
    date_shocks = rng.normal(scale=4.0, size=len(dates))
    endpoint_shocks = rng.normal(scale=4.0, size=96)
    date_comparator_shocks = rng.normal(scale=4.0, size=(len(dates), 4))
    endpoint_comparator_shocks = rng.normal(scale=4.0, size=(96, 4))
    symbols = tuple(COMPARATORS)
    for day_index, date in enumerate(dates):
        for endpoint_index in range(24):
            endpoint_identity = (day_index % 4) * 24 + endpoint_index
            src = f"0x{1000 + endpoint_identity:040x}"
            tgt = f"0x{2000 + endpoint_identity:040x}"
            for comparator_index, symbol in enumerate(symbols):
                architecture = (day_index + endpoint_index + comparator_index) % 4
                weth_tick = architecture in (0, 1)
                comparator_tick = architecture in (0, 2)
                notional = (1_000.0, 10_000.0, 100_000.0)[endpoint_index % 3]
                edge = (
                    8.0
                    + 0.4 * comparator_index
                    + 0.06 * day_index * (comparator_index + 1)
                    + 0.03 * endpoint_index**2
                    + 0.2 * architecture
                    + 0.00001 * notional
                    + date_shocks[day_index]
                    + endpoint_shocks[endpoint_identity]
                    + date_comparator_shocks[day_index, comparator_index]
                    + endpoint_comparator_shocks[endpoint_identity, comparator_index]
                    + 0.15 * np.sin((day_index + 1) * (endpoint_index + 2) * (comparator_index + 1))
                    + rng.normal(scale=2.0)
                )
                weth_output = notional * 0.99
                comparator_output = weth_output * (20_000.0 - edge) / (20_000.0 + edge)
                direct_supported = (day_index + endpoint_index + comparator_index) % 7 != 0
                pairs.append(
                    {
                        "date": date.strftime("%Y-%m-%d"),
                        "reserve_hour_utc": endpoint_index % 24,
                        "src": src,
                        "tgt": tgt,
                        "trade_size_usd": notional,
                        "comparator": COMPARATORS[symbol],
                        "comparator_symbol": symbol,
                        "available_candidate_count": 2 + (day_index + endpoint_index) % 4,
                        "weth_hop1_source": "uniswap_v3" if weth_tick else "uniswap_v2",
                        "weth_hop2_source": "uniswap_v2",
                        "comparator_hop1_source": "uniswap_v4" if comparator_tick else "sushiswap_v2",
                        "comparator_hop2_source": "uniswap_v2",
                        "weth_symmetric_output_edge_bps": edge,
                        "weth_output_gain_bps_of_notional": 10_000.0 * (weth_output - comparator_output) / notional,
                        "weth_log_output_ratio": np.log(weth_output) - np.log(comparator_output),
                        "weth_signed_win": 1,
                        "weth_direct_threshold_edge": 1.0 if direct_supported else np.nan,
                    }
                )
    return pd.DataFrame(pairs), candidate_day


def test_exact_seventeen_fit_ledger_has_nested_same_support_and_two_way_inference() -> None:
    pair, controls = _fixture()
    results, support = fit_dominance_cost_e0(pair, controls)
    assert len(FIT_LEDGER) == len(results) == 17
    assert results["spec_id"].tolist() == [spec.spec_id for spec in FIT_LEDGER]
    indexed = results.set_index("spec_id")
    for left, right in (
        ("dc01_risk_support_bridge", "dc02_risk_absorbed_slope_diagnostic"),
        ("dc02_risk_absorbed_slope_diagnostic", "dc03_risk_matched_symmetric"),
        ("dc03_risk_matched_symmetric", "dc04_risk_matched_log"),
        ("dc05_use_support_bridge", "dc06_predetermined_use"),
        ("dc07_mechanism_support_bridge", "dc08_lagged_liquidity_mechanism"),
        ("dc09_heterogeneity_support_bridge", "dc10_architecture_breadth_depeg"),
        ("dc06_predetermined_use", "dc11_log_output_robustness"),
        ("dc06_predetermined_use", "dc12_signed_win_robustness"),
        ("dc06_predetermined_use", "dc13_notional_gain_robustness"),
    ):
        assert indexed.loc[left, "sample_sha256"] == indexed.loc[right, "sample_sha256"]
        assert indexed.loc[left, "n_observations"] == indexed.loc[right, "n_observations"]
    assert set(results["status"]) == {"exploratory_not_admissible"}
    assert set(results["capable_of_e0_closure"]) == {False}
    assert set(results["clustering"]) == {"two_way_date_ordered_endpoint_pair_cr1"}
    assert set(results["inference_owner"]) == {
        "pair_difference_regression_two_way_date_ordered_endpoint_pair_cr1"
    }
    assert "holm_p_values_within_fit_exploratory_only" in results
    assert "holm_p_values_within_fit" not in results
    assert all(min(json.loads(value)) >= 20 for value in results["cluster_counts"])
    assert indexed.loc["dc14_direct_threshold_support", "support_stage"] == "positive_finite_direct_output"
    assert indexed.loc["dc00_full_primary", "estimates_average_weth_edge"]
    assert indexed.loc["dc01_risk_support_bridge", "estimates_average_weth_edge"]
    assert not indexed.loc["dc02_risk_absorbed_slope_diagnostic", "estimates_average_weth_edge"]
    assert indexed.loc["dc03_risk_matched_symmetric", "estimates_average_weth_edge"]
    assert indexed.loc["dc04_risk_matched_log", "estimates_average_weth_edge"]
    assert indexed.loc["dc15_calendar_year_heterogeneity", "sample_sha256"] == indexed.loc["dc00_full_primary", "sample_sha256"]
    assert json.loads(indexed.loc["dc15_calendar_year_heterogeneity", "control_blocks"]) == ["calendar_year", "time_heterogeneity_not_aggregator_attribution"]
    assert set(json.loads(indexed.loc["dc15_calendar_year_heterogeneity", "regressors"])) == {"constant", "calendar_year_2021", "calendar_year_2022", "calendar_year_2023", "calendar_year_2024", "calendar_year_2025", "calendar_year_2026"}
    assert "raw quote-attempt-composition" in indexed.loc["dc15_calendar_year_heterogeneity", "auxiliary_scope"]
    stable_year = indexed.loc["dc16_calendar_year_stable_design_sensitivity"]
    assert json.loads(stable_year["fixed_effects"]) == ["quote_design_cell"]
    assert "not market maturation" in stable_year["auxiliary_scope"]
    stable_support = json.loads(stable_year["fixed_effect_support"])
    assert stable_support["cells_observed_on_multiple_dates"] > 0
    assert stable_support["cells_spanning_multiple_calendar_years"] > 0
    assert stable_support["observations_in_multiple_calendar_year_cells"] > 0
    assert stable_support["share_in_multiple_calendar_year_cells"] > 0
    assert set(stable_support["adjacent_calendar_year_bridge_cell_counts"]) == {f"{year}_{year + 1}" for year in range(2020, 2026)}
    auxiliary = indexed.loc["dc02_risk_absorbed_slope_diagnostic"]
    assert json.loads(auxiliary["fixed_effects"]) == ["date", "quote_design_cell"]
    assert "stable_endpoint_comparator_notional_hour_design" in json.loads(auxiliary["control_blocks"])
    auxiliary_support = json.loads(auxiliary["fixed_effect_support"])
    assert auxiliary_support["cells_observed_on_multiple_dates"] > 0
    assert auxiliary_support["share_in_multiple_date_cells"] == 1.0
    assert auxiliary_support["all_declared_regressors_identified"]
    assert "within-design-cell changes over time" in auxiliary["auxiliary_scope"]
    assert "no_average_weth_edge_coefficient" in indexed.loc["dc02_risk_absorbed_slope_diagnostic", "estimand"]
    assert results["exact_sample_unconditional_mean"].notna().all()
    raw_2020_mean = pair.loc[pd.to_datetime(pair["date"]).dt.year.eq(2020), "weth_symmetric_output_edge_bps"].mean()
    assert indexed.loc["dc15_calendar_year_heterogeneity", "zero_difference_reference_category_profile_estimate"] == pytest.approx(raw_2020_mean)
    assert indexed.loc["dc15_calendar_year_heterogeneity", "zero_difference_reference_category_profile_definition"].startswith("2020 reference-year mean")
    support_rows = support.set_index("sample")["observations"]
    assert support_rows["primary_full"] > support_rows["risk_complete"] > support_rows["use_complete"]
    assert support_rows["use_complete"] > support_rows["mechanism_complete"]
    assert support_rows["direct_complete"] < support_rows["use_complete"]


def test_descriptive_decomposition_reconstructs_each_raw_mean_and_reports_blocks() -> None:
    pair, controls = _fixture()
    results, _support = fit_dominance_cost_e0(pair, controls)
    matched = results.loc[results["estimates_average_weth_edge"]]
    assert np.allclose(
        matched["decomposition_reconstructed_mean"],
        matched["exact_sample_unconditional_mean"],
        rtol=0,
        atol=1e-10,
    )
    assert np.allclose(matched["decomposition_identity_error"], 0, rtol=0, atol=1e-10)
    indexed = results.set_index("spec_id")
    predetermined_blocks = json.loads(indexed.loc["dc06_predetermined_use", "block_contributions_to_raw_mean_gap"])
    assert set(predetermined_blocks) == {"risk", "lagged_use"}
    mechanism_blocks = json.loads(indexed.loc["dc08_lagged_liquidity_mechanism", "block_contributions_to_raw_mean_gap"])
    assert set(mechanism_blocks) == {"risk", "lagged_use", "lagged_liquidity_mechanism"}
    joint_tests = json.loads(indexed.loc["dc08_lagged_liquidity_mechanism", "joint_slope_tests"])
    assert set(joint_tests) == {"all_declared_slopes", "risk", "lagged_use", "lagged_liquidity_mechanism"}
    assert indexed.loc["dc08_lagged_liquidity_mechanism", "decomposition_status"] == "descriptive_not_causal"
    risk = indexed.loc["dc03_risk_matched_symmetric"]
    reference = json.loads(risk["zero_difference_reference_category_profile_inference"])
    adjusted_mean = json.loads(risk["regression_adjusted_mean_at_sample_means_inference"])
    assert adjusted_mean["estimate"] == pytest.approx(risk["exact_sample_unconditional_mean"])
    assert adjusted_mean["standard_error"] > 0
    assert json.loads(risk["raw_mean_inference"]) is None
    raw_owner = indexed.loc["dc01_risk_support_bridge"]
    assert raw_owner["raw_mean_owner"] == "intercept_only_support_bridge"
    assert json.loads(raw_owner["raw_mean_inference"])["estimate"] == pytest.approx(raw_owner["exact_sample_unconditional_mean"])
    assert reference["estimate"] == pytest.approx(risk["zero_difference_reference_category_profile_estimate"])
    assert reference["standard_error"] > 0
    assert reference["confidence_interval_lower"] < reference["estimate"] < reference["confidence_interval_upper"]
    block_inference = json.loads(risk["block_contribution_contrast_inference"])
    block_covariance = np.asarray(json.loads(risk["block_contribution_covariance"]))
    block_labels = json.loads(risk["block_contribution_covariance_labels"])
    assert block_labels == ["risk"]
    assert block_inference["risk"]["estimate"] == pytest.approx(
        json.loads(risk["block_contributions_to_raw_mean_gap"])["risk"]
    )
    assert block_covariance[0, 0] == pytest.approx(block_inference["risk"]["standard_error"] ** 2)
    mechanism = indexed.loc["dc08_lagged_liquidity_mechanism"]
    mechanism_labels = json.loads(mechanism["block_contribution_covariance_labels"])
    mechanism_covariance = np.asarray(json.loads(mechanism["block_contribution_covariance"]))
    mechanism_inference = json.loads(mechanism["block_contribution_contrast_inference"])
    assert mechanism_covariance.shape == (3, 3)
    assert np.allclose(mechanism_covariance, mechanism_covariance.T)
    for position, block in enumerate(mechanism_labels):
        assert mechanism_covariance[position, position] == pytest.approx(
            mechanism_inference[block]["standard_error"] ** 2
        )


def test_centered_first_difference_point_estimate_equals_explicit_member_stack_with_attempt_fixed_effects() -> None:
    pair, controls = _fixture()
    panel = prepare_analysis_panel(pair, controls)
    sample = panel.loc[panel["risk_complete"]].reset_index(drop=True)
    difference_x = sample[list(RISK_CONTROLS)].astype(float)
    difference_means = difference_x.mean()
    difference_x = difference_x - difference_means
    difference_fit = ols_clustered(
        sample["weth_symmetric_output_edge_bps"],
        difference_x,
        sample["date"],
        add_constant=True,
        additional_clusters=(sample["ordered_endpoint_pair"],),
        min_clusters=20,
    )

    n_rows = len(sample)
    stack = pd.DataFrame(
        {
            "outcome": np.concatenate(
                [
                    sample["weth_symmetric_output_edge_bps"].to_numpy(dtype=float) / 2,
                    -sample["weth_symmetric_output_edge_bps"].to_numpy(dtype=float) / 2,
                ]
            ),
            "is_weth": np.concatenate([np.ones(n_rows), np.zeros(n_rows)]),
            "attempt_id": np.concatenate([np.arange(n_rows), np.arange(n_rows)]),
            "date": pd.concat([sample["date"], sample["date"]], ignore_index=True),
            "ordered_endpoint_pair": pd.concat(
                [sample["ordered_endpoint_pair"], sample["ordered_endpoint_pair"]],
                ignore_index=True,
            ),
        }
    )
    for difference_column in RISK_CONTROLS:
        stack[difference_column] = np.concatenate(
            [
                sample[difference_column].to_numpy(dtype=float) - difference_means[difference_column],
                np.zeros(n_rows),
            ]
        )
    stack_x = stack[["is_weth", *RISK_CONTROLS]]
    attempt = stack["attempt_id"]
    stack_fit = ols_clustered(
        absorb_fixed_effects(stack["outcome"], attempt),
        absorb_fixed_effects(stack_x, attempt),
        stack["date"],
        add_constant=False,
        absorbed_groups=(attempt,),
        additional_clusters=(stack["ordered_endpoint_pair"],),
        min_clusters=20,
    )
    assert np.allclose(stack_fit.beta, difference_fit.beta, rtol=0, atol=1e-10)
    assert not np.allclose(stack_fit.covariance, difference_fit.covariance, rtol=1e-8, atol=1e-12)


def test_invalid_declared_coefficient_variance_fails_closed(monkeypatch) -> None:
    pair, _controls = _fixture()
    owner = e0.ols_clustered

    def invalid_variance(*args, **kwargs):
        fitted = owner(*args, **kwargs)
        covariance = fitted.covariance.copy()
        covariance[0, 0] = -1.0
        return replace(fitted, covariance=covariance)

    monkeypatch.setattr(e0, "ols_clustered", invalid_variance)
    with pytest.raises(ValueError, match="non-positive or nonfinite declared coefficient variance"):
        fit_dominance_cost_e0(pair, None, specification_ids=["dc00_full_primary"])


def test_empty_fit_subset_and_unknown_status_fail_closed() -> None:
    pair, controls = _fixture()
    with pytest.raises(ValueError, match="fit subset is invalid"):
        fit_dominance_cost_e0(pair, controls, specification_ids=[])
    with pytest.raises(ValueError, match="fit status is invalid"):
        fit_dominance_cost_e0(pair, controls, status="looks_good")


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("comparator_symbol", "address-symbol mapping"),
        ("architecture_source", "architecture source"),
        ("native_symbol", "address-symbol mapping"),
        ("share_domain", "upper bound"),
    ),
)
def test_input_identity_and_domain_contracts_fail_closed(mutation, message) -> None:
    pair, controls = _fixture()
    if mutation == "comparator_symbol":
        pair["comparator_symbol"] = "USDC"
    elif mutation == "architecture_source":
        pair["weth_hop1_source"] = "unknown_dex"
    elif mutation == "native_symbol":
        controls.loc[controls["candidate_address"].eq(NATIVE_VEHICLE), "candidate_symbol"] = "ETH"
    else:
        controls["lag1_intermediary_episode_share"] = 1.2
    with pytest.raises(ValueError, match=message):
        fit_dominance_cost_e0(pair, controls, specification_ids=["dc03_risk_matched_symmetric"])


def test_mechanisms_never_leak_into_predetermined_or_heterogeneity_baselines() -> None:
    mechanism = set(LIQUIDITY_MECHANISM_CONTROLS)
    for spec in FIT_LEDGER:
        if spec.spec_id != "dc08_lagged_liquidity_mechanism":
            assert mechanism.isdisjoint(spec.controls)
    assert all("lag1_" in column for column in mechanism)


def test_control_panel_must_prove_exact_prior_calendar_day_timing() -> None:
    pair, controls = _fixture()
    controls.loc[0, "covariate_observation_cutoff_date"] = controls.loc[0, "origin_date"]
    with pytest.raises(ValueError, match="exact prior calendar day"):
        fit_dominance_cost_e0(pair, controls)


@pytest.mark.parametrize("bad_hour", [-1.0, 0.5, np.nan, 24.0])
def test_reserve_hour_domain_is_identical_in_full_and_streamed_paths(tmp_path, bad_hour) -> None:
    pair, controls = _fixture()
    pair["reserve_hour_utc"] = pair["reserve_hour_utc"].astype(float)
    pair.loc[0, "reserve_hour_utc"] = bad_hour
    with pytest.raises(ValueError, match="reserve hour"):
        fit_dominance_cost_e0(pair, controls)
    path = tmp_path / "pair.parquet"
    pair.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="reserve hour"):
        e0.fit_unadjusted_parquet(path)


def test_unadjusted_provisional_subset_runs_without_control_panel(tmp_path) -> None:
    pair, _controls = _fixture()
    pair_path = tmp_path / "pair.parquet"
    pair.to_parquet(pair_path, index=False)
    results, support, inputs = runner.run(
        pair_panel_path=pair_path,
        control_path=tmp_path / "missing.parquet",
        provisional_subset="unadjusted",
    )
    assert results["spec_id"].tolist() == ["dc00_full_primary"]
    assert results["status"].tolist() == ["provisional_diagnostic_only"]
    assert support.loc[support["sample"].eq("risk_complete"), "observations"].item() == 0
    assert inputs == [pair_path]


def test_certified_runner_fails_clearly_when_control_panel_is_absent(tmp_path, monkeypatch) -> None:
    pair, _controls = _fixture()
    pair_path = tmp_path / "pair.parquet"
    pair.to_parquet(pair_path, index=False)
    fake_release = SimpleNamespace(artifacts={"panel": pair_path}, lineage_paths=(tmp_path / "current.json", pair_path))
    monkeypatch.setattr(runner, "resolve_dominance_cost_release", lambda _pointer: fake_release)
    with pytest.raises(FileNotFoundError, match="certified-input dominance-cost exploratory sub-ledger requires"):
        runner.run(control_path=tmp_path / "missing.parquet", pointer_path=tmp_path / "current.json", high_memory_full_control=True)


def test_streamed_unadjusted_path_matches_in_memory_fit(tmp_path) -> None:
    pair, _controls = _fixture()
    path = tmp_path / "pair.parquet"
    pair.to_parquet(path, index=False)
    streamed, streamed_support = e0.fit_unadjusted_parquet(path)
    expected, expected_support = fit_dominance_cost_e0(pair, None, specification_ids=["dc00_full_primary"], status="provisional_diagnostic_only")
    for column in ("coefficients", "exact_sample_unconditional_mean", "exact_sample_unconditional_median", "exact_sample_unconditional_standard_deviation", "sample_sha256", "cluster_counts"):
        assert streamed.loc[0, column] == expected.loc[0, column]
    streamed_se = json.loads(streamed.loc[0, "standard_errors"])["constant"]
    expected_se = json.loads(expected.loc[0, "standard_errors"])["constant"]
    assert streamed_se == pytest.approx(expected_se, rel=1e-12, abs=1e-12)
    pd.testing.assert_frame_equal(streamed_support, expected_support)


def test_full_control_runner_fails_closed_without_high_memory_assignment(tmp_path) -> None:
    pair, controls = _fixture()
    pair_path = tmp_path / "pair.parquet"
    controls_path = tmp_path / "controls.parquet"
    pair.to_parquet(pair_path, index=False)
    controls.to_parquet(controls_path, index=False)
    with pytest.raises(RuntimeError, match="48 GiB"):
        runner.run(pair_panel_path=pair_path, control_path=controls_path, provisional_subset="predetermined")


def test_high_memory_runner_projects_pair_schema_and_executes_full_subledger(tmp_path, monkeypatch) -> None:
    pair, controls = _fixture()
    pair["unused_large_payload"] = "x" * 1024
    pair_path = tmp_path / "pair.parquet"
    controls_path = tmp_path / "controls.parquet"
    pair.to_parquet(pair_path, index=False)
    controls.to_parquet(controls_path, index=False)
    owner = runner.pd.read_parquet
    observed_columns = []

    def projected(path, *args, **kwargs):
        if path == pair_path:
            observed_columns.extend(kwargs.get("columns") or [])
            assert "unused_large_payload" not in observed_columns
        return owner(path, *args, **kwargs)

    monkeypatch.setattr(runner.pd, "read_parquet", projected)
    monkeypatch.setattr(runner, "_physical_memory_bytes", lambda: 64 * 1024**3)
    results, _support, _inputs = runner.run(pair_panel_path=pair_path, control_path=controls_path, provisional_subset="all", high_memory_full_control=True)
    assert len(results) == 17
    assert set(observed_columns) == e0.PAIR_REQUIRED_COLUMNS


def test_release_contract_rejects_schema_and_specification_drift(tmp_path) -> None:
    pair, _controls = _fixture()
    path = tmp_path / "pair.parquet"
    pair.to_parquet(path, index=False)
    results, support = e0.fit_unadjusted_parquet(path)
    with pytest.raises(ValueError, match="exact schema"):
        runner._validate_result_contract(results.drop(columns="outcome"), support, expected_status="provisional_diagnostic_only")
    altered = results.copy()
    altered.loc[0, "control_blocks"] = "[]"
    with pytest.raises(ValueError, match="specification contract"):
        runner._validate_result_contract(altered, support, expected_status="provisional_diagnostic_only")


@pytest.mark.parametrize(
    ("target", "column", "value"),
    (
        ("result", "n_dates", -99),
        ("result", "n_ordered_endpoint_pairs", -1),
        ("result", "exact_sample_unconditional_mean", np.nan),
        ("result", "sample_sha256", "bad"),
        ("result", "coefficients", '{"constant": NaN}'),
        ("result", "raw_control_means", '{"bad": NaN}'),
        ("result", "block_contribution_covariance", "[[1.0]]"),
        ("result", "joint_slope_tests", '{"bad": {}}'),
        ("result", "controls_mean_centered", True),
        ("result", "zero_difference_reference_category_profile_definition", "mutated"),
        ("support", "observations", -123),
        ("support", "sample_sha256", "bad"),
    ),
)
def test_release_contract_rejects_adversarial_numeric_and_support_mutations(tmp_path, target, column, value) -> None:
    pair, _controls = _fixture()
    path = tmp_path / "pair.parquet"
    pair.to_parquet(path, index=False)
    results, support = e0.fit_unadjusted_parquet(path)
    if target == "result":
        results.loc[0, column] = value
    else:
        support.loc[support["sample"].eq("primary_full"), column] = value
    with pytest.raises(ValueError):
        runner._validate_result_contract(results, support, expected_status="provisional_diagnostic_only")


def test_release_contract_rejects_cross_field_and_semantic_mutations(tmp_path) -> None:
    pair, _controls = _fixture()
    path = tmp_path / "pair.parquet"
    pair.to_parquet(path, index=False)
    original_results, original_support = e0.fit_unadjusted_parquet(path)

    def rejected(mutator) -> None:
        results = original_results.copy(deep=True)
        support = original_support.copy(deep=True)
        mutator(results, support)
        with pytest.raises(ValueError):
            runner._validate_result_contract(results, support, expected_status="provisional_diagnostic_only")

    rejected(lambda results, _support: results.__setitem__("coefficients", json.dumps({"constant": json.loads(results.loc[0, "coefficients"])["constant"] + 123})))
    rejected(lambda results, _support: results.__setitem__("t_statistics", json.dumps({"constant": 0.123})))
    rejected(lambda results, _support: results.__setitem__("auxiliary_scope", "causal aggregator effect"))
    rejected(lambda results, _support: results.__setitem__("dropped_collinear_design_columns", '["invented_regressor"]'))

    def coordinated_false_dates(results, support) -> None:
        false_dates = int(results.loc[0, "n_dates"]) - 1
        results.loc[0, "n_dates"] = false_dates
        support.loc[support["sample"].isin(["primary_full", "calendar_complete"]), "dates"] = false_dates

    rejected(coordinated_false_dates)


def test_release_contract_rejects_impossible_dc16_fixed_effect_support() -> None:
    pair, controls = _fixture()
    results, support = fit_dominance_cost_e0(pair, controls)
    position = results.index[results["spec_id"].eq("dc16_calendar_year_stable_design_sensitivity")].item()
    fixed_support = json.loads(results.loc[position, "fixed_effect_support"])
    fixed_support["cells_spanning_multiple_calendar_years"] = 999_999
    fixed_support["observations_in_multiple_calendar_year_cells"] = 999_999
    fixed_support["share_in_multiple_calendar_year_cells"] = 1.0
    results.loc[position, "fixed_effect_support"] = json.dumps(fixed_support, sort_keys=True)
    with pytest.raises(ValueError):
        runner._validate_result_contract(results, support, expected_status="exploratory_not_admissible")


def test_release_contract_rejects_joint_df_and_declared_regressor_omission() -> None:
    pair, controls = _fixture()
    original_results, support = fit_dominance_cost_e0(pair, controls)
    position = original_results.index[original_results["spec_id"].eq("dc15_calendar_year_heterogeneity")].item()

    results = original_results.copy(deep=True)
    joint_tests = json.loads(results.loc[position, "joint_slope_tests"])
    joint_tests["all_declared_slopes"]["numerator_df"] -= 1
    joint_tests["all_declared_slopes"]["p_value"] = float(stats.f.sf(joint_tests["all_declared_slopes"]["f_statistic"], joint_tests["all_declared_slopes"]["numerator_df"], joint_tests["all_declared_slopes"]["denominator_df"]))
    results.loc[position, "joint_slope_tests"] = json.dumps(joint_tests, sort_keys=True)
    with pytest.raises(ValueError, match="numerator degrees of freedom"):
        runner._validate_result_contract(results, support, expected_status="exploratory_not_admissible")

    results = original_results.copy(deep=True)
    omitted = "calendar_year_2026"
    regressors = json.loads(results.loc[position, "regressors"])
    regressors.remove(omitted)
    results.loc[position, "regressors"] = json.dumps(regressors)
    results.loc[position, "dropped_collinear_design_columns"] = json.dumps([omitted])
    for field in ("coefficients", "standard_errors", "t_statistics", "p_values", "holm_p_values_within_fit_exploratory_only"):
        mapping = json.loads(results.loc[position, field])
        mapping.pop(omitted)
        results.loc[position, field] = json.dumps(mapping, sort_keys=True)
    with pytest.raises(ValueError, match="specification contract"):
        runner._validate_result_contract(results, support, expected_status="exploratory_not_admissible")


def test_all_seventeen_fits_survive_staged_jsonl_publication_precision(tmp_path) -> None:
    pair, controls = _fixture()
    results, support = fit_dominance_cost_e0(pair, controls)
    release = runner.publish_subledger_release(results, support, inputs=[], provisional=False, pointer_path=tmp_path / "exploratory" / "current.json")
    reopened_results = pd.read_json(release.artifacts["results"], lines=True)
    reopened_support = pd.read_json(release.artifacts["support"], lines=True)
    assert len(reopened_results) == 17
    runner._validate_result_contract(reopened_results, reopened_support, expected_status="exploratory_not_admissible")


def _calendar_fixed_effect_frame(edges: list[tuple[int, int]]) -> pd.DataFrame:
    records = []
    for cell, (left, right) in enumerate(edges):
        for year in (left, right):
            record = {
                "date": pd.Timestamp(year=year, month=1, day=cell + 1),
                "quote_design_cell": f"cell_{cell}",
            }
            record.update({f"calendar_year_{candidate}": float(year == candidate) for candidate in range(2021, 2027)})
            records.append(record)
    return pd.DataFrame(records)


def test_dc16_accepts_connected_full_rank_nonadjacent_bridge_topology() -> None:
    frame = _calendar_fixed_effect_frame([(2020, 2022), (2022, 2024), (2024, 2026), (2026, 2021), (2021, 2023), (2023, 2025)])
    support = e0._fixed_effect_support(frame, FIT_LEDGER[-1])
    assert support["within_fixed_effect_regressor_rank"] == 6
    assert all(count == 0 for count in support["adjacent_calendar_year_bridge_cell_counts"].values())


def test_dc16_rejects_rank_deficient_calendar_design() -> None:
    frame = _calendar_fixed_effect_frame([(year, year) for year in range(2020, 2027)])
    with pytest.raises(ValueError, match="lack identifying support"):
        e0._fixed_effect_support(frame, FIT_LEDGER[-1])


def test_scientific_provenance_owners_are_transitively_bound() -> None:
    assert {"src/ddvc/transaction_targets.py", "src/ddvc/asset_types.py", "src/ddvc/route_cost.py"}.issubset(runner.CODE_SOURCES)


def test_provisional_outputs_publish_as_one_separate_atomic_release(tmp_path) -> None:
    pair, _controls = _fixture()
    pair_path = tmp_path / "pair.parquet"
    pair.to_parquet(pair_path, index=False)
    results, support, inputs = runner.run(
        pair_panel_path=pair_path,
        control_path=tmp_path / "missing.parquet",
        provisional_subset="unadjusted",
    )
    release = runner.publish_subledger_release(
        results,
        support,
        inputs=inputs,
        provisional=True,
        pointer_path=tmp_path / "provisional" / "current.json",
    )
    assert set(release.artifacts) == {"results", "support", "metadata"}
    metadata = json.loads(release.artifacts["metadata"].read_text())
    assert metadata["capable_of_e0_closure"] is False
    assert metadata["status"] == "provisional_diagnostic_only"
    assert metadata["integration_mode"] == "standalone_nonclosing_diagnostic"
    assert metadata["claimed_attack_ids"] == []
    assert metadata["executed_diagnostics"] == {}
    assert "aggregator_attribution" in metadata["unavailable_coverage_gaps"]
    assert "model_ledger" not in json.dumps(metadata)


def test_provisional_release_rejects_nonprovisional_default_pointer(tmp_path) -> None:
    pair, _controls = _fixture()
    results, support = fit_dominance_cost_e0(
        pair,
        None,
        specification_ids=["dc00_full_primary"],
        status="provisional_diagnostic_only",
    )
    with pytest.raises(ValueError, match="cannot share a release pointer"):
        runner.publish_subledger_release(
            results,
            support,
            inputs=[],
            provisional=True,
            pointer_path=runner.EXPLORATORY_OUTPUT_POINTER,
        )

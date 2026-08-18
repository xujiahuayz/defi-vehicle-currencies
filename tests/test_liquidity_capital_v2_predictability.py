from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.liquidity_predictability import (
    ROUTE_FAMILY,
    V2_CANDIDATE_DAY_COLUMNS,
    V2_FAMILY,
    V2_QUANTITY_KIND,
    build_v2_exact_horizon_panel,
)


SCRIPT = Path(__file__).parents[1] / "scripts/analyze/run_liquidity_capital_v2_predictability.py"
SPEC = importlib.util.spec_from_file_location("run_liquidity_capital_v2_predictability_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CANDIDATES = sorted(VEHICLE_CANDIDATES.items())


def _valid_exact_panel() -> pd.DataFrame:
    rows = []
    days = pd.date_range("2020-10-01", "2021-12-31", freq="D")
    for day_index, day in enumerate(days):
        capitals = np.asarray(
            [1000.0 + day_index + 100.0 * index for index in range(5)]
        )
        intermediate_counts = np.asarray(
            [day_index + index + 1 for index in range(5)], dtype=float
        )
        endpoint_counts = np.asarray(
            [day_index + 2 * index + 2 for index in range(5)], dtype=float
        )
        intermediary_shares = intermediate_counts / intermediate_counts.sum()
        endpoint_shares = endpoint_counts / endpoint_counts.sum()
        for candidate, (candidate_address, candidate_symbol) in enumerate(CANDIDATES):
            capital = capitals[candidate]
            rows.append(
                {
                    "origin_date": day,
                    "candidate_address": candidate_address,
                    "candidate_symbol": candidate_symbol,
                    "route_measurement_family": ROUTE_FAMILY,
                    "route_day_supported": True,
                    "route_candidate_observed": True,
                    "route_endpoint_supported": True,
                    "intermediary_episode_share": intermediary_shares[candidate],
                    "vehicle_excess_use_count_ratio": (
                        intermediary_shares[candidate] / endpoint_shares[candidate]
                    ),
                    "intermediate_route_count": int(intermediate_counts[candidate]),
                    "endpoint_route_count": int(endpoint_counts[candidate]),
                    "route_all_token_intermediate_count": int(intermediate_counts.sum()),
                    "route_all_token_endpoint_count": int(endpoint_counts.sum()),
                    "route_share_denominator": "all_routed_tokens_on_origin_date",
                    "route_support_status": "observed_candidate",
                    "v2_measurement_family": V2_FAMILY,
                    "v2_capital_day_supported": True,
                    "v2_candidate_pool_observed": True,
                    "v2_deposited_capital_usd": capital,
                    "v2_log1p_deposited_capital_usd": np.log1p(capital),
                    "v2_five_candidate_capital_share": capital / capitals.sum(),
                    "v2_candidate_pool_count": 1,
                    "v2_candidate_venue_count": 1,
                    "v2_candidate_allocation_row_count": 1,
                    "v2_quantity_kind": V2_QUANTITY_KIND,
                    "v2_capital_validation_status": "exact_state_current",
                    "v2_capital_state_generation": "fixture_v2",
                    "v2_capital_support_status": "observed_candidate_pools",
                }
            )
    return build_v2_exact_horizon_panel(pd.DataFrame(rows))




def test_two_way_fixed_effect_fit_recovers_within_candidate_date_signal() -> None:
    rows = []
    for day_index, day in enumerate(pd.date_range("2021-01-01", periods=60, freq="D")):
        for candidate, (candidate_address, candidate_symbol) in enumerate(CANDIDATES):
            predictor = np.sin(day_index / 7 + candidate) + candidate * day_index / 300
            rows.append(
                {
                    "origin_date": day,
                    "candidate_address": f"candidate-{candidate}",
                    "predictor": predictor,
                    "outcome": 0.75 * predictor + candidate + day_index / 10,
                }
            )
    primary, two_way = MODULE._fit_fe(pd.DataFrame(rows), "outcome", "predictor")
    np.testing.assert_allclose(primary.beta[0], 0.75, atol=1e-10)
    assert np.isfinite(primary.standard_errors[0])
    assert np.isfinite(two_way.standard_errors[0])


def test_calendar_score_hac_keeps_missing_dates_as_zero_scores() -> None:
    covariance = MODULE._calendar_score_hac_covariance(
        np.ones((2, 1)),
        np.array([1.0, 2.0]),
        pd.Series(pd.to_datetime(["2021-01-01", "2021-01-03"])),
        lag_days=1,
        scale=1.0,
    )
    assert covariance[0, 0] == pytest.approx(1.25)


def test_runner_fails_closed_when_declared_inputs_are_missing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(MODULE, "CANDIDATE_DAY_INPUT", tmp_path / "candidate.parquet")
    monkeypatch.setattr(MODULE, "EXACT_HORIZON_INPUT", tmp_path / "horizons.parquet")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--bootstrap-repetitions", "20"])
    assert MODULE.main() == 2
    assert "INPUT BLOCKED" in capsys.readouterr().out


def test_registered_grid_reports_primary_holm_and_support(monkeypatch) -> None:
    panel = _valid_exact_panel()

    def fake_fit(sample, outcome, predictor):
        del outcome, predictor
        fit = SimpleNamespace(
            beta=np.array([0.5]),
            standard_errors=np.array([0.1]),
            t_statistics=np.array([5.0]),
            p_values=np.array([0.001]),
            n_observations=len(sample),
            n_clusters=sample["origin_date"].nunique(),
        )
        return fit, fit

    monkeypatch.setattr(MODULE, "_fit_fe", fake_fit)
    monkeypatch.setattr(
        MODULE, "_month_block_bootstrap", lambda *args, **kwargs: (0.2, 0.03, 20)
    )
    estimates, support = MODULE.estimate_v2_predictability(
        panel, bootstrap_repetitions=20
    )
    assert len(estimates) == len(support) == 96
    assert estimates["spec_id"].is_unique
    assert estimates.loc[estimates["primary_horizon"], "p_value_holm"].notna().all()
    assert estimates.loc[~estimates["primary_horizon"], "p_value_holm"].isna().all()
    assert set(support["measurement_family"]) == {"v2_family_deposited_capital_stock"}
    assert estimates.loc[
        estimates["perimeter"].eq("full_v2_calendar"), "claim_decision_pass"
    ].all()
    assert estimates.loc[
        ~estimates["perimeter"].eq("full_v2_calendar"), "claim_decision_pass"
    ].isna().all()
    assert estimates.loc[
        estimates["adjudication_primary"], "analysis_role"
    ].eq("primary_adjudication").all()
    assert estimates.loc[
        estimates["perimeter"].eq("full_v2_calendar")
        & ~estimates["primary_horizon"],
        "analysis_role",
    ].eq("long_horizon_sensitivity").all()
    assert estimates.loc[
        ~estimates["perimeter"].eq("full_v2_calendar"), "analysis_role"
    ].eq("calendar_heterogeneity_only").all()

    primary_failed = estimates.copy()
    full = primary_failed["perimeter"].eq("full_v2_calendar")
    primary_failed.loc[full, "coefficient"] = -0.1
    primary_failed.loc[full, ["p_value", "p_value_holm"]] = 0.5
    readjudicated = MODULE._attach_full_calendar_decision(primary_failed)
    assert not readjudicated.loc[full, "claim_decision_pass"].any()
    assert readjudicated.loc[~full, "claim_decision_pass"].isna().all()

from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.liquidity_predictability import (
    LOOKAHEAD_SAFE_COVARIATE_COLUMNS,
    V2_FAMILY,
    V3_FAMILY,
    attach_lookahead_safe_daily_covariates,
    build_candidate_day_panel,
    build_exact_horizon_panel,
    validate_exact_horizon_covariates,
    validate_lookahead_safe_daily_covariates,
)


CANDIDATES = sorted((address, symbol) for address, symbol in VEHICLE_CANDIDATES.items())


def _write_inputs(root: Path) -> tuple[Path, Path, Path]:
    days = pd.date_range("2020-01-25", "2020-06-02", freq="D")
    route_rows = []
    for index, day in enumerate(days):
        if day == pd.Timestamp("2020-02-15"):
            continue
        for candidate_index, (address, symbol) in enumerate(CANDIDATES):
            if day == pd.Timestamp("2020-02-10") and candidate_index == 0:
                continue
            endpoint = candidate_index != 0
            route_rows.append(
                {
                    "date": day,
                    "token": address,
                    "symbol": symbol,
                    "intermediate_routes": index + candidate_index,
                    "endpoint_routes": index + 1 if endpoint else 0,
                    "intermediate_count_share": (candidate_index + 1) / 20,
                    "vehicle_excess_use_count_ratio": (candidate_index + 1) / 2 if endpoint else np.nan,
                    "endpoint_supported": endpoint,
                }
            )
    capital_rows = []
    for index, day in enumerate(days[2:]):
        if day == pd.Timestamp("2020-02-16"):
            continue
        for candidate_index, (address, symbol) in enumerate(CANDIDATES):
            if day == pd.Timestamp("2020-02-17") and candidate_index == 0:
                continue
            pool = f"0x{index:038x}{candidate_index:02x}"
            capital_rows.append(
                {
                    "venue": "uniswap_v2" if candidate_index % 2 else "sushiswap_v2",
                    "day": day.strftime("%Y%m%d"),
                    "pool": pool,
                    "pool_candidate_id": f"{pool}:{address}",
                    "candidate": symbol,
                    "candidate_address": address,
                    "allocation_weight": 1.0,
                    "candidate_capital_usd": float(1000 + index + candidate_index),
                    "quantity_kind": "deposited_capital",
                    "pool_family": "full_range_constant_product",
                    "invariant_family": "full_range_constant_product",
                    "state_generation": "fixture_v2",
                    "capital_validation_status": "exact_state_current",
                }
            )
    flow_rows = []
    for index, day in enumerate(days[4:]):
        values = [0.0 if index == 0 and candidate_index == 0 else float(10 + candidate_index) for candidate_index in range(5)]
        day_total = sum(values)
        for (address, symbol), gross in zip(CANDIDATES, values, strict=True):
            del address
            flow_rows.append(
                {
                    "day": day.strftime("%Y%m%d"),
                    "candidate": symbol,
                    "gross_liquidity_flow_usd": gross,
                    "net_liquidity_flow_usd": gross / 2,
                    "active_net_liquidity_flow_usd": gross / 3,
                    "near_net_liquidity_flow_usd": gross / 4,
                    "near_gross_liquidity_flow_usd": gross / 2,
                    "event_count": float(gross > 0),
                    "has_liquidity_flow": gross > 0,
                    "gross_candidate_flow_share": gross / day_total if day_total else np.nan,
                    "near_gross_flow_share": 0.5 if gross > 0 else np.nan,
                    "flow_normalization_status": "dollar_flow_and_within_flow_shares_no_capital_stock",
                }
            )
    paths = root / "route.parquet", root / "capital.parquet", root / "flow.parquet"
    pd.DataFrame(route_rows).to_parquet(paths[0], index=False)
    pd.DataFrame(capital_rows).to_parquet(paths[1], index=False)
    pd.DataFrame(flow_rows).to_parquet(paths[2], index=False)
    return paths


def _build(root: Path) -> pd.DataFrame:
    return build_candidate_day_panel(*_write_inputs(root), verify_inputs=False, memory_limit="256MB", threads=1, temp_directory=root / "tmp")


def _token_prices(
    *, start: str = "2019-12-01", end: str = "2020-06-02"
) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D")
    rows = []
    for candidate_index, (address, symbol) in enumerate(CANDIDATES):
        for day_index, day in enumerate(days):
            price = (100.0 + candidate_index) * np.exp(
                0.001 * day_index
                + 0.01 * np.sin(day_index / 3.0 + candidate_index)
            )
            rows.append(
                {
                    "day": day.strftime("%Y%m%d"),
                    "token": address,
                    "symbol": symbol,
                    "price_usd": price,
                    "n_observations": 3,
                    "n_consensus": 3,
                    "consensus_share": 1.0,
                    "gross_weight_usd": 1000.0,
                    "consensus_weight_usd": 1000.0,
                    "price_source": "canonical_repriced_route_legs",
                    "validation_status": "minimum_observations_and_price_consensus_passed",
                }
            )
    return pd.DataFrame(rows)


def test_candidate_day_keeps_stock_and_flow_families_separate(tmp_path: Path) -> None:
    panel = _build(tmp_path)
    assert panel["v2_measurement_family"].eq(V2_FAMILY).all()
    assert panel["v3_measurement_family"].eq(V3_FAMILY).all()
    assert not any("capital" in column for column in panel if column.startswith("v3_"))
    assert not any("flow" in column for column in panel if column.startswith("v2_"))
    assert panel["v2_quantity_kind"].eq("deposited_capital").all()
    assert panel.loc[panel["v3_flow_day_supported"], "v3_flow_normalization_status"].eq("dollar_flow_and_within_flow_shares_no_capital_stock").all()


def test_exact_calendar_links_cross_leap_day_and_month_boundary(tmp_path: Path) -> None:
    exact = build_exact_horizon_panel(_build(tmp_path))
    address = CANDIDATES[0][0]
    leap = exact[(exact["origin_date"].eq("2020-02-28")) & (exact["candidate_address"].eq(address)) & (exact["horizon_days"].eq(1))].iloc[0]
    month = exact[(exact["origin_date"].eq("2020-01-31")) & (exact["candidate_address"].eq(address)) & (exact["horizon_days"].eq(30))].iloc[0]
    assert leap["target_date"] == pd.Timestamp("2020-02-29")
    assert month["target_date"] == pd.Timestamp("2020-03-01")
    assert leap["horizon_contract"] == "exact_calendar_date_no_row_shift"


def test_zero_and_missing_support_are_distinct(tmp_path: Path) -> None:
    panel = _build(tmp_path)
    address = CANDIDATES[0][0]
    missing_flow = panel[(panel["origin_date"].eq("2020-01-27")) & (panel["candidate_address"].eq(address))].iloc[0]
    zero_flow = panel[(panel["origin_date"].eq("2020-01-29")) & (panel["candidate_address"].eq(address))].iloc[0]
    missing_capital = panel[(panel["origin_date"].eq("2020-02-16")) & (panel["candidate_address"].eq(address))].iloc[0]
    zero_capital = panel[(panel["origin_date"].eq("2020-02-17")) & (panel["candidate_address"].eq(address))].iloc[0]
    assert not missing_flow["v3_flow_day_supported"] and pd.isna(missing_flow["v3_gross_flow_usd"])
    assert zero_flow["v3_flow_day_supported"] and zero_flow["v3_gross_flow_usd"] == 0
    assert zero_flow["v3_flow_support_status"] == "observed_explicit_zero_flow"
    assert not missing_capital["v2_capital_day_supported"] and pd.isna(missing_capital["v2_deposited_capital_usd"])
    assert zero_capital["v2_capital_day_supported"] and zero_capital["v2_deposited_capital_usd"] == 0
    assert zero_capital["v2_capital_support_status"] == "supported_zero_capital"


def test_pool_allocation_must_conserve_without_double_counting(tmp_path: Path) -> None:
    route, capital, flow = _write_inputs(tmp_path)
    frame = pd.read_parquet(capital)
    day = frame.iloc[0]["day"]
    pool = frame.iloc[0]["pool"]
    first = frame.iloc[0].copy()
    second = frame.iloc[1].copy()
    first["allocation_weight"] = 0.5
    first["candidate_capital_usd"] = 70.0
    second["day"] = day
    second["venue"] = first["venue"]
    second["pool"] = pool
    second["pool_candidate_id"] = f"{pool}:{second['candidate_address']}"
    second["allocation_weight"] = 0.5
    second["candidate_capital_usd"] = 30.0
    frame = frame.iloc[2:].copy()
    frame = pd.concat([frame, pd.DataFrame([first, second])], ignore_index=True)
    frame.to_parquet(capital, index=False)
    with pytest.raises(ValueError, match="conserve"):
        build_candidate_day_panel(route, capital, flow, verify_inputs=False, memory_limit="256MB", threads=1, temp_directory=tmp_path / "tmp")


def test_fixed_five_address_identity_fails_closed_on_symbol(tmp_path: Path) -> None:
    route, capital, flow = _write_inputs(tmp_path)
    frame = pd.read_parquet(route)
    frame.loc[0, "symbol"] = "NOT_THE_CANONICAL_ASSET"
    frame.to_parquet(route, index=False)
    with pytest.raises(ValueError, match="identity"):
        build_candidate_day_panel(route, capital, flow, verify_inputs=False, memory_limit="256MB", threads=1, temp_directory=tmp_path / "tmp")


def test_fixed_five_address_identity_fails_closed_on_extra_token(tmp_path: Path) -> None:
    route, capital, flow = _write_inputs(tmp_path)
    frame = pd.read_parquet(route)
    extra = frame.iloc[0].copy()
    extra["token"] = "0x0000000000000000000000000000000000000001"
    extra["symbol"] = "EXTRA"
    pd.concat([frame, pd.DataFrame([extra])], ignore_index=True).to_parquet(route, index=False)
    with pytest.raises(ValueError, match="identity"):
        build_candidate_day_panel(route, capital, flow, verify_inputs=False, memory_limit="256MB", threads=1, temp_directory=tmp_path / "tmp")


def test_exact_windows_require_every_calendar_day_and_do_not_row_shift(tmp_path: Path) -> None:
    panel = _build(tmp_path)
    exact = build_exact_horizon_panel(panel)
    address = CANDIDATES[0][0]
    supported = exact[(exact["origin_date"].eq("2020-02-28")) & (exact["candidate_address"].eq(address)) & (exact["horizon_days"].eq(1))].iloc[0]
    assert supported["v3_exact_future_window_supported"]
    assert supported["v3_future_window_supported_days"] == 1
    assert supported["v3_future_cumulative_gross_flow_usd"] == 10.0
    missing_target = exact[(exact["origin_date"].eq("2020-06-02")) & (exact["candidate_address"].eq(address)) & (exact["horizon_days"].eq(1))].iloc[0]
    assert not missing_target["route_exact_target_supported"]
    assert pd.isna(missing_target["future_intermediary_episode_share_change"])


def test_builder_requires_current_provenance_by_default(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    with pytest.raises(RuntimeError, match="requires current analysis inputs"):
        build_candidate_day_panel(*paths, memory_limit="256MB", threads=1, temp_directory=tmp_path / "tmp")


def test_lookahead_safe_covariates_add_exact_columns_and_order_deterministically(
    tmp_path: Path,
) -> None:
    candidate_day = _build(tmp_path)
    prices = _token_prices()
    transformed = attach_lookahead_safe_daily_covariates(candidate_day, prices)
    shuffled = attach_lookahead_safe_daily_covariates(
        candidate_day.sample(frac=1.0, random_state=11),
        prices.sample(frac=1.0, random_state=12),
    )
    assert tuple(transformed.columns) == (
        *candidate_day.columns,
        *LOOKAHEAD_SAFE_COVARIATE_COLUMNS,
    )
    pd.testing.assert_frame_equal(transformed, shuffled)
    expected_cutoff = transformed["origin_date"] - pd.Timedelta(days=1)
    pd.testing.assert_series_equal(
        transformed["covariate_observation_cutoff_date"],
        expected_cutoff.rename("covariate_observation_cutoff_date"),
    )
    assert transformed["covariate_lag_days"].eq(1).all()
    assert transformed["covariate_volatility_window_calendar_days"].eq(30).all()
    assert transformed["covariate_volatility_min_valid_returns"].eq(20).all()


def test_lookahead_safe_covariates_reject_added_removed_or_changed_columns(
    tmp_path: Path,
) -> None:
    original = _build(tmp_path).sort_values(
        ["origin_date", "candidate_address"]
    ).reset_index(drop=True)
    transformed = attach_lookahead_safe_daily_covariates(
        original, _token_prices()
    )
    with pytest.raises(ValueError, match="added, removed, or reordered"):
        validate_lookahead_safe_daily_covariates(
            original, _token_prices(), transformed.drop(columns="lag1_candidate_log_return")
        )
    changed = transformed.copy()
    changed.loc[0, "candidate_symbol"] = "CHANGED"
    with pytest.raises(ValueError, match="changed an original column"):
        validate_lookahead_safe_daily_covariates(original, _token_prices(), changed)


def test_price_perturbation_cannot_affect_same_or_earlier_origin_dates(
    tmp_path: Path,
) -> None:
    candidate_day = _build(tmp_path)
    prices = _token_prices()
    shock_date = pd.Timestamp("2020-03-01")
    weth_address = next(
        address for address, symbol in CANDIDATES if symbol == "WETH"
    )
    perturbed = prices.copy()
    shock = perturbed["day"].eq(shock_date.strftime("%Y%m%d")) & perturbed[
        "token"
    ].eq(weth_address)
    perturbed.loc[shock, "price_usd"] *= 2.0
    baseline = attach_lookahead_safe_daily_covariates(candidate_day, prices)
    changed = attach_lookahead_safe_daily_covariates(candidate_day, perturbed)
    comparison_columns = [
        "origin_date",
        "candidate_address",
        *LOOKAHEAD_SAFE_COVARIATE_COLUMNS,
    ]
    same_or_earlier = baseline["origin_date"].le(shock_date)
    pd.testing.assert_frame_equal(
        baseline.loc[same_or_earlier, comparison_columns].reset_index(drop=True),
        changed.loc[same_or_earlier, comparison_columns].reset_index(drop=True),
    )
    next_day = baseline["origin_date"].eq(shock_date + pd.Timedelta(days=1))
    assert not baseline.loc[next_day, "lag1_weth_log_return"].equals(
        changed.loc[next_day, "lag1_weth_log_return"]
    )


def test_candidate_day_perturbation_cannot_affect_same_or_earlier_covariates(
    tmp_path: Path,
) -> None:
    candidate_day = _build(tmp_path)
    prices = _token_prices()
    shock_date = pd.Timestamp("2020-03-01")
    address = CANDIDATES[0][0]
    perturbed = candidate_day.copy()
    shock = perturbed["origin_date"].eq(shock_date) & perturbed[
        "candidate_address"
    ].eq(address)
    perturbed.loc[shock, "intermediate_route_count"] += 1000
    perturbed.loc[shock, "v2_log1p_deposited_capital_usd"] += 1.0
    perturbed.loc[shock, "v3_signed_log1p_net_flow_per_1000"] += 1.0
    baseline = attach_lookahead_safe_daily_covariates(candidate_day, prices)
    changed = attach_lookahead_safe_daily_covariates(perturbed, prices)
    covariates = [
        "origin_date",
        "candidate_address",
        *LOOKAHEAD_SAFE_COVARIATE_COLUMNS,
    ]
    same_or_earlier = baseline["origin_date"].le(shock_date)
    pd.testing.assert_frame_equal(
        baseline.loc[same_or_earlier, covariates].reset_index(drop=True),
        changed.loc[same_or_earlier, covariates].reset_index(drop=True),
    )
    next_day = (
        baseline["origin_date"].eq(shock_date + pd.Timedelta(days=1))
        & baseline["candidate_address"].eq(address)
    )
    assert baseline.loc[next_day, "lag1_intermediate_route_count"].iloc[0] + 1000 == changed.loc[
        next_day, "lag1_intermediate_route_count"
    ].iloc[0]


def test_price_gaps_remain_missing_and_are_not_compressed_in_returns_or_windows(
    tmp_path: Path,
) -> None:
    candidate_day = _build(tmp_path)
    prices = _token_prices()
    address = CANDIDATES[0][0]
    missing_price_date = "20200210"
    gapped = prices.loc[
        ~(
            prices["token"].eq(address)
            & prices["day"].eq(missing_price_date)
        )
    ].copy()
    baseline = attach_lookahead_safe_daily_covariates(candidate_day, prices)
    transformed = attach_lookahead_safe_daily_covariates(candidate_day, gapped)
    missing_cutoff = transformed[
        transformed["origin_date"].eq("2020-02-11")
        & transformed["candidate_address"].eq(address)
    ].iloc[0]
    next_cutoff = transformed[
        transformed["origin_date"].eq("2020-02-12")
        & transformed["candidate_address"].eq(address)
    ].iloc[0]
    assert not missing_cutoff["lag1_candidate_return_supported"]
    assert not next_cutoff["lag1_candidate_return_supported"]
    baseline_count = baseline.loc[
        baseline["origin_date"].eq("2020-02-12")
        & baseline["candidate_address"].eq(address),
        "lag1_candidate_volatility_valid_returns",
    ].iloc[0]
    assert next_cutoff["lag1_candidate_volatility_valid_returns"] == baseline_count - 2


def test_volatility_startup_requires_twenty_valid_calendar_day_returns(
    tmp_path: Path,
) -> None:
    candidate_day = _build(tmp_path)
    transformed = attach_lookahead_safe_daily_covariates(
        candidate_day, _token_prices(start="2020-01-25")
    )
    address = CANDIDATES[0][0]
    early = transformed[
        transformed["origin_date"].eq("2020-02-10")
        & transformed["candidate_address"].eq(address)
    ].iloc[0]
    supported = transformed[
        transformed["origin_date"].eq("2020-02-16")
        & transformed["candidate_address"].eq(address)
    ].iloc[0]
    assert early["lag1_candidate_volatility_valid_returns"] < 20
    assert not early["lag1_candidate_volatility_supported"]
    assert supported["lag1_candidate_volatility_valid_returns"] >= 20
    assert supported["lag1_candidate_volatility_supported"]


def test_lagged_route_and_liquidity_controls_use_exact_calendar_dates(
    tmp_path: Path,
) -> None:
    transformed = attach_lookahead_safe_daily_covariates(
        _build(tmp_path), _token_prices()
    )
    address = CANDIDATES[0][0]
    after_missing_route_day = transformed[
        transformed["origin_date"].eq("2020-02-16")
        & transformed["candidate_address"].eq(address)
    ].iloc[0]
    assert not after_missing_route_day["lag1_route_day_supported"]
    assert pd.isna(after_missing_route_day["lag1_intermediate_route_count"])
    assert pd.isna(after_missing_route_day["lag1_route_total_count"])


def test_lagged_v2_and_v3_gaps_remain_unsupported(tmp_path: Path) -> None:
    transformed = attach_lookahead_safe_daily_covariates(_build(tmp_path), _token_prices())
    address = CANDIDATES[0][0]
    after_missing_v2 = transformed.loc[
        transformed["origin_date"].eq("2020-02-17")
        & transformed["candidate_address"].eq(address)
    ].iloc[0]
    before_v3_start = transformed.loc[
        transformed["origin_date"].eq("2020-01-29")
        & transformed["candidate_address"].eq(address)
    ].iloc[0]
    assert not after_missing_v2["lag1_v2_capital_day_supported"]
    assert pd.isna(after_missing_v2["lag1_v2_log1p_deposited_capital_usd"])
    assert pd.isna(after_missing_v2["lag1_v2_five_candidate_capital_share"])
    assert not before_v3_start["lag1_v3_flow_day_supported"]
    assert pd.isna(before_v3_start["lag1_v3_signed_log1p_net_flow_per_1000"])
    assert pd.isna(before_v3_start["lag1_v3_gross_candidate_flow_share"])


def test_candidate_stress_persists_and_uses_pre_shock_denominator(tmp_path: Path) -> None:
    prices = _token_prices()
    transformed = attach_lookahead_safe_daily_covariates(_build(tmp_path), prices)
    row = transformed.loc[transformed["lag1_candidate_downside_stress"].gt(0)].iloc[0]
    address = row["candidate_address"]
    cutoff = row["covariate_observation_cutoff_date"]
    series = prices.loc[prices["token"].eq(address), ["day", "price_usd"]].copy()
    series["date"] = pd.to_datetime(series["day"], format="%Y%m%d")
    series = series.sort_values("date")
    series["return"] = np.log(series["price_usd"] / series["price_usd"].shift(1))
    pre_shock = series.loc[
        series["date"].between(cutoff - pd.Timedelta(days=30), cutoff - pd.Timedelta(days=1)),
        "return",
    ]
    trailing = series.loc[
        series["date"].between(cutoff - pd.Timedelta(days=29), cutoff),
        "return",
    ]
    assert len(pre_shock) == 30
    assert len(trailing) == 30
    assert row["lag1_candidate_pre_shock_volatility_valid_returns"] == 30
    assert row["lag1_candidate_volatility_valid_returns"] == 30
    assert row["lag1_candidate_pre_shock_30d_volatility"] == pytest.approx(pre_shock.std(ddof=1))
    assert row["lag1_candidate_trailing_30d_volatility"] == pytest.approx(trailing.std(ddof=1))
    assert row["lag1_candidate_downside_stress"] == pytest.approx(
        max(-row["lag1_candidate_log_return"], 0)
        / row["lag1_candidate_pre_shock_30d_volatility"]
    )


@pytest.mark.parametrize(
    "column",
    [
        "lag1_candidate_log_return",
        "lag1_candidate_trailing_30d_volatility",
        "lag1_candidate_pre_shock_30d_volatility",
        "lag1_candidate_downside_stress",
        "lag1_weth_downside_stress",
        "lag1_weth_stress_event_8pct",
        "lag1_route_total_count",
        "lag1_v2_log1p_deposited_capital_usd",
        "lag1_v3_signed_log1p_net_flow_per_1000",
    ],
)
def test_covariate_validator_rejects_numerical_corruption(
    tmp_path: Path, column: str
) -> None:
    original = _build(tmp_path).sort_values(["origin_date", "candidate_address"]).reset_index(drop=True)
    prices = _token_prices()
    corrupted = attach_lookahead_safe_daily_covariates(original, prices)
    index = corrupted.index[corrupted[column].notna()][-1]
    if column == "lag1_weth_stress_event_8pct":
        corrupted.loc[index, column] = not bool(corrupted.loc[index, column])
    else:
        corrupted.loc[index, column] = corrupted.loc[index, column] + 1
    with pytest.raises(ValueError):
        validate_lookahead_safe_daily_covariates(original, prices, corrupted)


@pytest.mark.parametrize("defect", ["zero", "infinite", "source", "status", "duplicate"])
def test_token_price_input_fails_closed_on_invalid_rows(
    tmp_path: Path, defect: str
) -> None:
    prices = _token_prices()
    if defect == "zero":
        prices.loc[0, "price_usd"] = 0.0
    elif defect == "infinite":
        prices.loc[0, "price_usd"] = np.inf
    elif defect == "source":
        prices.loc[0, "price_source"] = "unregistered"
    elif defect == "status":
        prices.loc[0, "validation_status"] = "unvalidated"
    else:
        prices = pd.concat([prices, prices.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError):
        attach_lookahead_safe_daily_covariates(_build(tmp_path), prices)


def test_exact_horizon_builder_preserves_origin_covariates(tmp_path: Path) -> None:
    candidate_day = attach_lookahead_safe_daily_covariates(
        _build(tmp_path), _token_prices()
    )
    exact = build_exact_horizon_panel(candidate_day)
    assert set(LOOKAHEAD_SAFE_COVARIATE_COLUMNS).issubset(exact.columns)
    assert exact["covariate_observation_cutoff_date"].eq(
        exact["origin_date"] - pd.Timedelta(days=1)
    ).all()
    validate_exact_horizon_covariates(candidate_day, exact)
    corrupted = exact.copy()
    corrupted.loc[0, "lag1_candidate_log_return"] += 1
    with pytest.raises(ValueError, match="changed an origin-day covariate"):
        validate_exact_horizon_covariates(candidate_day, corrupted)


def test_registered_builder_wires_price_input_provenance_and_validators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = Path(__file__).parents[1] / "scripts" / "build_liquidity_capital_flow_panels.py"
    spec = importlib.util.spec_from_file_location("build_liquidity_capital_flow_panels_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = _build(tmp_path)
    price_path = tmp_path / "token_price_daily.parquet"
    _token_prices().to_parquet(price_path, index=False)
    candidate_output = tmp_path / "candidate.parquet"
    horizon_output = tmp_path / "horizons.parquet"
    capital_input = tmp_path / "capital.parquet"
    capital_pointer = tmp_path / "capital-current.json"
    monkeypatch.setattr(module, "ROUTE_INPUT", tmp_path / "route.parquet")
    monkeypatch.setattr(module, "FLOW_INPUT", tmp_path / "flow.parquet")
    monkeypatch.setattr(module, "PRICE_INPUT", price_path)
    monkeypatch.setattr(module, "CANDIDATE_DAY_OUTPUT", candidate_output)
    monkeypatch.setattr(module, "EXACT_HORIZON_OUTPUT", horizon_output)
    class CapitalRelease:
        artifacts = {"candidate": capital_input}
        lineage_paths = (capital_pointer, capital_input)

    monkeypatch.setattr(module, "resolve_capital_release", lambda: CapitalRelease())
    monkeypatch.setattr(module, "build_candidate_day_panel", lambda *args, **kwargs: base)
    required = []
    def current_artifacts(paths: list[Path], **kwargs: object):
        required.extend(paths)
        return nullcontext()

    monkeypatch.setattr(module, "current_artifacts", current_artifacts)
    writes = []

    def write_panel(frame: pd.DataFrame, path: Path, **kwargs: object) -> None:
        frame.to_parquet(path, index=False)
        kwargs["preinstall_validator"](path)
        writes.append((path, tuple(kwargs["inputs"])))

    monkeypatch.setattr(module, "write_panel", write_panel)
    monkeypatch.setattr(sys, "argv", [str(script)])
    assert module.main() == 0
    assert required == [price_path]
    assert "src/ddvc/analysis/dynamics.py" in module.CODE_SOURCES
    assert len(writes) == 2
    assert all(price_path in inputs for _path, inputs in writes)
    assert all(capital_pointer in inputs for _path, inputs in writes)
    written_candidate = pd.read_parquet(candidate_output)
    written_horizons = pd.read_parquet(horizon_output)
    assert set(LOOKAHEAD_SAFE_COVARIATE_COLUMNS).issubset(written_candidate)
    assert set(written_horizons["horizon_days"]) == {1, 7, 30, 120}


def test_construction_module_contains_no_estimator_or_fit_call() -> None:
    source = (Path(__file__).parents[1] / "src" / "ddvc" / "liquidity_predictability.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "statsmodels" not in lowered
    assert "linearmodels" not in lowered
    assert ".fit(" not in lowered

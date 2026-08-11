from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.liquidity_predictability import V2_FAMILY, V3_FAMILY, build_candidate_day_panel, build_exact_horizon_panel


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
                    "capital_validation_status": "reconciled_current",
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


def test_construction_module_contains_no_estimator_or_fit_call() -> None:
    source = (Path(__file__).parents[1] / "src" / "ddvc" / "liquidity_predictability.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "statsmodels" not in lowered
    assert "linearmodels" not in lowered
    assert ".fit(" not in lowered

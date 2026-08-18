from __future__ import annotations

import argparse
import importlib.util
from contextlib import nullcontext
from pathlib import Path

import pandas as pd
import pytest

from ddvc.asset_types import VEHICLE_CANDIDATES
from ddvc.liquidity_predictability import (
    HORIZONS,
    V2_CANDIDATE_DAY_COLUMNS,
    build_v2_candidate_day_panel,
    build_v2_exact_horizon_panel,
    validate_v2_candidate_day_panel,
    validate_v2_exact_horizon_panel,
)


CANDIDATES = sorted(
    (address.lower(), symbol) for address, symbol in VEHICLE_CANDIDATES.items()
)


def _write_inputs(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    route_rows: list[dict[str, object]] = []
    capital_rows: list[dict[str, object]] = []
    days = pd.date_range("2024-01-01", periods=8, freq="D")
    for day_index, day in enumerate(days):
        intermediate = [day_index + candidate_index + 1 for candidate_index in range(5)]
        endpoints = [day_index + 2 for _candidate_index in range(5)]
        intermediate_total = sum(intermediate)
        endpoint_total = sum(endpoints)
        for candidate_index, (address, symbol) in enumerate(CANDIDATES):
            route_rows.append(
                {
                    "date": day,
                    "token": address,
                    "symbol": symbol,
                    "intermediate_routes": intermediate[candidate_index],
                    "endpoint_routes": endpoints[candidate_index],
                    "intermediate_count_share": (
                        intermediate[candidate_index] / intermediate_total
                    ),
                    "vehicle_excess_use_count_ratio": (
                        (intermediate[candidate_index] / intermediate_total)
                        / (endpoints[candidate_index] / endpoint_total)
                    ),
                    "endpoint_supported": True,
                }
            )
            pool = f"0x{day_index:037x}{candidate_index:03x}"
            capital_rows.append(
                {
                    "venue": "uniswap_v2" if candidate_index % 2 else "sushiswap_v2",
                    "day": day.strftime("%Y%m%d"),
                    "pool": pool,
                    "pool_candidate_id": f"{pool}:{address}",
                    "candidate": symbol,
                    "candidate_address": address,
                    "allocation_weight": 1.0,
                    "candidate_capital_usd": float(1_000 + 10 * day_index + candidate_index),
                    "quantity_kind": "deposited_capital",
                    "pool_family": "full_range_constant_product",
                    "invariant_family": "full_range_constant_product",
                    "state_generation": "fixture_v2",
                    "capital_validation_status": "exact_state_current",
                }
            )
    route_path = root / "route.parquet"
    capital_path = root / "capital.parquet"
    pd.DataFrame(route_rows).to_parquet(route_path, index=False)
    pd.DataFrame(capital_rows).to_parquet(capital_path, index=False)
    return route_path, capital_path


def _build(root: Path) -> pd.DataFrame:
    route, capital = _write_inputs(root)
    return build_v2_candidate_day_panel(
        route,
        capital,
        verify_inputs=False,
        memory_limit="256MB",
        threads=1,
        temp_directory=root / "duckdb",
    )


def test_v2_candidate_day_panel_has_one_direct_family(tmp_path: Path) -> None:
    panel = _build(tmp_path)
    assert tuple(panel.columns) == V2_CANDIDATE_DAY_COLUMNS
    assert set(panel["candidate_address"]) == {address for address, _ in CANDIDATES}
    assert panel["route_measurement_family"].nunique() == 1
    assert panel["v2_measurement_family"].nunique() == 1
    assert not any(column.startswith("v3_") for column in panel)
    assert panel["v2_capital_day_supported"].all()
    validate_v2_candidate_day_panel(panel)


def test_candidate_day_validator_recomputes_route_and_capital_shares(
    tmp_path: Path,
) -> None:
    panel = _build(tmp_path)
    broken_route = panel.copy()
    broken_route.loc[0, "intermediary_episode_share"] += 0.01
    with pytest.raises(ValueError, match="intermediary episode share"):
        validate_v2_candidate_day_panel(broken_route)

    broken_capital = panel.copy()
    broken_capital.loc[0, "v2_five_candidate_capital_share"] += 0.01
    with pytest.raises(ValueError, match="capital share"):
        validate_v2_candidate_day_panel(broken_capital)


def test_exact_horizons_use_calendar_dates_and_preserve_origin(
    tmp_path: Path,
) -> None:
    candidate_day = _build(tmp_path)
    exact = build_v2_exact_horizon_panel(candidate_day, horizons=(1, 3))
    assert set(exact["horizon_days"]) == {1, 3}
    assert (
        exact["target_date"]
        == exact["origin_date"] + pd.to_timedelta(exact["horizon_days"], unit="D")
    ).all()
    assert exact["horizon_contract"].eq("exact_calendar_date_no_row_shift").all()
    assert not any(column.startswith("v3_") for column in exact)
    validate_v2_exact_horizon_panel(exact, horizons=(1, 3))


def test_exact_horizon_validator_rejects_a_row_shift(tmp_path: Path) -> None:
    exact = build_v2_exact_horizon_panel(_build(tmp_path), horizons=(1,))
    supported = exact["route_exact_target_supported"]
    assert supported.any()
    broken = exact.copy()
    index = broken.index[supported][0]
    broken.loc[index, "future_intermediary_episode_share_change"] += 0.1
    with pytest.raises(ValueError, match="origin-target recomputation"):
        validate_v2_exact_horizon_panel(broken, horizons=(1,))


def test_processed_panel_builder_writes_only_v2_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = (
        Path(__file__).parents[1]
        / "scripts"
        / "process"
        / "build_liquidity_capital_flow_panels.py"
    )
    spec = importlib.util.spec_from_file_location("v2_panel_builder_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    route, capital = _write_inputs(tmp_path)
    candidate = _build(tmp_path / "second")
    exact = build_v2_exact_horizon_panel(candidate)
    candidate_output = tmp_path / "candidate.parquet"
    exact_output = tmp_path / "exact.parquet"

    monkeypatch.setattr(module, "ROUTE_INPUT", route)
    monkeypatch.setattr(module, "POOL_CANDIDATE_CAPITAL_DAILY", capital)
    monkeypatch.setattr(module, "V2_CANDIDATE_DAY_OUTPUT", candidate_output)
    monkeypatch.setattr(module, "V2_EXACT_HORIZON_OUTPUT", exact_output)
    monkeypatch.setattr(
        module, "build_v2_candidate_day_panel", lambda *args, **kwargs: candidate
    )
    monkeypatch.setattr(
        module, "build_v2_exact_horizon_panel", lambda *args, **kwargs: exact
    )
    monkeypatch.setattr(module, "current_inputs", lambda *args, **kwargs: nullcontext())

    writes: list[Path] = []

    def write_panel(frame: pd.DataFrame, path: Path, **kwargs: object) -> None:
        frame.to_parquet(path, index=False)
        kwargs["preinstall_validator"](path)
        writes.append(path)

    monkeypatch.setattr(module, "write_panel", write_panel)
    args = argparse.Namespace(memory_limit="256MB", threads=1)
    assert module._build(args) == 0
    assert writes == [candidate_output, exact_output]


def test_construction_module_contains_no_estimator_or_retired_joint_builder() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "ddvc" / "liquidity_predictability.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "statsmodels" not in lowered
    assert "linearmodels" not in lowered
    assert ".fit(" not in lowered
    assert "def build_candidate_day_panel(" not in source
    assert "def build_exact_horizon_panel(" not in source

from __future__ import annotations

import pandas as pd
import pytest

from scripts.analyze.run_route_gas_economics import (
    annual_route_class_summaries,
    endpoint_hurdle_change,
    extra_hop_hurdles,
    prepared_gas_panel,
)


def _gas_row(
    date: str,
    *,
    tx_hash: str,
    year: int,
    mid_type: str,
    gas_used: int,
    notional: float = 1_000.0,
    gas_price_gwei: float = 10.0,
) -> dict[str, object]:
    return {
        "date": pd.Timestamp(date),
        "year": year,
        "tx_hash": tx_hash,
        "legs": 1 if mid_type == "direct" else 2,
        "mid_type": mid_type,
        "gas_vehicle": mid_type,
        "route_notional_usd": notional,
        "effective_gas_price_wei": int(gas_price_gwei * 1e9),
        "gas_used": gas_used,
        "status": 1,
    }


def test_prepared_gas_panel_attaches_weth_price_and_costs() -> None:
    gas = pd.DataFrame(
        [
            _gas_row("2024-01-01", tx_hash="0x1", year=2024, mid_type="direct", gas_used=100_000),
            _gas_row("2024-01-01", tx_hash="0x2", year=2024, mid_type="stable", gas_used=250_000),
        ]
    )
    prices = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "price_usd": [2_000.0]})
    panel = prepared_gas_panel(gas, prices)
    stable = panel[panel["route_class"].eq("stable_vehicle")].iloc[0]
    assert stable["gas_price_gwei"] == pytest.approx(10.0)
    assert stable["gas_cost_usd"] == pytest.approx(5.0)
    assert stable["gas_cost_bps"] == pytest.approx(50.0)


def test_extra_hop_hurdle_uses_year_median_prices() -> None:
    rows = []
    for year, date, gas_price in [(2024, "2024-01-01", 10.0), (2026, "2026-01-01", 1.0)]:
        rows.extend(
            [
                _gas_row(date, tx_hash=f"0xd{year}", year=year, mid_type="direct", gas_used=100_000, gas_price_gwei=gas_price),
                _gas_row(date, tx_hash=f"0xs{year}", year=year, mid_type="stable", gas_used=300_000, gas_price_gwei=gas_price),
            ]
        )
    prices = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2026-01-01")],
            "price_usd": [2_000.0, 1_000.0],
        }
    )
    panel = prepared_gas_panel(pd.DataFrame(rows), prices)
    annual = annual_route_class_summaries(panel)
    assert {"annual_route_class_gas"} == set(annual["record_type"])
    hurdles = extra_hop_hurdles(panel)
    base = hurdles[hurdles["year"].eq(2024)].iloc[0]
    end = hurdles[hurdles["year"].eq(2026)].iloc[0]
    assert base["extra_gas_units"] == pytest.approx(200_000)
    assert base["extra_gas_cost_usd_at_year_medians"] == pytest.approx(4.0)
    assert base["notional_for_extra_gas_1bp_usd"] == pytest.approx(40_000.0)
    change = endpoint_hurdle_change(hurdles)
    assert change.iloc[0]["one_bp_notional_ratio"] == pytest.approx(
        end["notional_for_extra_gas_1bp_usd"] / base["notional_for_extra_gas_1bp_usd"]
    )

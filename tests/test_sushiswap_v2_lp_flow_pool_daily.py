from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.process.build_sushiswap_v2_lp_flow_pool_daily import (
    load_raw_sushiswap_v2_lp_flows,
    run,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
POOL = "0x00000000000000000000000000000000000000aa"


def _timestamp(day: str) -> str:
    return str(int(pd.Timestamp(day, tz="UTC").timestamp()))


def _prices(path: Path) -> None:
    rows = []
    for day in pd.date_range("2025-01-01", "2025-01-06", freq="D"):
        rows.extend(
            [
                {
                    "day": day.strftime("%Y%m%d"),
                    "token": WETH,
                    "symbol": "WETH",
                    "price_usd": 2_000.0,
                    "price_source": "canonical_repriced_route_legs",
                    "validation_status": "minimum_observations_and_price_consensus_passed",
                },
                {
                    "day": day.strftime("%Y%m%d"),
                    "token": USDC,
                    "symbol": "USDC",
                    "price_usd": 1.0,
                    "price_source": "canonical_repriced_route_legs",
                    "validation_status": "minimum_observations_and_price_consensus_passed",
                },
            ]
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _registry() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pool": POOL,
                "token0_address": WETH,
                "token0_symbol": "WETH",
                "token1_address": USDC,
                "token1_symbol": "USDC",
            }
        ]
    )


def _event(event_id: str, *, needs_complete: bool = False) -> dict[str, object]:
    day = "2025-01-05"
    return {
        "amount0": "0.5",
        "amount1": "1000",
        "amountUSD": "999999",
        "id": event_id,
        "liquidity": "5",
        "logIndex": "7",
        "needsComplete": needs_complete,
        "pair": {
            "id": POOL,
            "token0": {"id": WETH, "symbol": "WETH"},
            "token1": {"id": USDC, "symbol": "USDC"},
        },
        "sender": "0x0000000000000000000000000000000000000def",
        "to": "0x0000000000000000000000000000000000000123",
        "timestamp": _timestamp(day),
        "transaction": {
            "id": f"0x{event_id:0>64}",
            "timestamp": _timestamp(day),
        },
    }


def _write_events(
    path: Path,
    mints: list[dict[str, object]],
    burns: list[dict[str, object]],
) -> None:
    for kind, rows in (("mints", mints), ("burns", burns)):
        target = path / f"sushiswap_v2_{kind}_20250105.jsonl.gz"
        with gzip.open(target, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")


def _write_daily(path: Path, day: str, volume: str) -> None:
    target = path / f"sushiswap_v2_daily_{day.replace('-', '')}.jsonl.gz"
    row = {
        "date": int(pd.Timestamp(day, tz="UTC").timestamp()),
        "pairAddress": POOL,
        "dailyVolumeUSD": volume,
        "reserveUSD": "100000",
        "token0": {"id": WETH, "symbol": "WETH"},
        "token1": {"id": USDC, "symbol": "USDC"},
    }
    with gzip.open(target, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def _capital(path: Path) -> None:
    rows = []
    for day, reserve0, reserve1, capital, lagged, exact_lag in (
        ("20250104", 10.0, 20.0, 40_000.0, None, False),
        ("20250105", 12.0, 24.0, 48_000.0, 40_000.0, True),
    ):
        rows.append(
            {
                "venue": "sushiswap_v2",
                "day": day,
                "pool": POOL,
                "token0_address": WETH,
                "token0_symbol": "WETH",
                "token1_address": USDC,
                "token1_symbol": "USDC",
                "reserve0": reserve0,
                "reserve1": reserve1,
                "capital_usd": capital,
                "capital_usd_lagged": lagged,
                "capital_valid": True,
                "exact_lag_valid": exact_lag,
                "capital_source": "reconstructed_constant_product_reserves",
                "price_source": "canonical_repriced_route_legs_with_address_time_sanity",
                "capital_validation_status": "audited_exact_reserve_capital",
                "identity_validation_status": "exact_identity_and_decimals_passed",
                "token_mechanics_status": "standard_token_mechanics",
                "failure_reason": None,
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_sushiswap_loader_retains_needs_complete_burn(tmp_path: Path) -> None:
    events = tmp_path / "events"
    events.mkdir()
    prices = tmp_path / "prices.parquet"
    _prices(prices)
    _write_events(events, [], [_event("1", needs_complete=True)])
    flows, support = load_raw_sushiswap_v2_lp_flows(
        event_dir=events,
        pool_registry=_registry(),
        price_path=prices,
    )
    row = flows.iloc[0]
    assert row["v2_remove_lp_flow_usd"] == pytest.approx(2_000.0)
    assert row["v2_remove_liquidity"] == pytest.approx(5.0)
    assert row["v2_needs_complete_remove_liquidity"] == pytest.approx(5.0)
    assert row["v2_needs_complete_events"] == 1
    assert row["v2_remove_events_valued"] == 1
    assert support["needs_complete_events"] == 1


def test_sushiswap_run_keeps_eventless_day_and_25bp_fee(tmp_path: Path) -> None:
    events = tmp_path / "events"
    events.mkdir()
    prices = tmp_path / "prices.parquet"
    capital = tmp_path / "capital.parquet"
    output = tmp_path / "flows.parquet"
    support = tmp_path / "support.jsonl"
    _prices(prices)
    _capital(capital)
    _write_daily(events, "2025-01-04", "1000")
    _write_daily(events, "2025-01-05", "2000")
    _write_events(events, [_event("2")], [])
    assert run(
        output_path=output,
        support_path=support,
        event_dir=events,
        capital_path=capital,
        price_path=prices,
    ) == 0
    panel = pd.read_parquet(output).sort_values("origin_date").reset_index(drop=True)
    assert panel["venue"].eq("sushiswap_v2").all()
    assert panel.loc[0, "v2_gross_lp_flow_usd"] == 0
    assert panel.loc[0, "v2_fee_opportunity_usd"] == pytest.approx(2.5)
    assert panel.loc[1, "v2_add_lp_flow_usd"] == pytest.approx(2_000.0)
    assert panel.loc[1, "v2_fee_opportunity_usd"] == pytest.approx(5.0)
    assert panel.loc[1, "v2_lagged_capital_usd"] == pytest.approx(40_000.0)
    assert panel.loc[1, "v2_exact_lag_valid"]

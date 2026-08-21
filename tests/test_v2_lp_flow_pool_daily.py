from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.process.build_v2_lp_flow_pool_daily import (
    load_raw_v2_pool_day_calendar,
    load_raw_uniswap_v2_lp_flows,
    run,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
OTHER = "0x0000000000000000000000000000000000000001"
POOL_A = "0x00000000000000000000000000000000000000aa"
POOL_B = "0x00000000000000000000000000000000000000bb"


def _timestamp(day: str) -> str:
    return str(int(pd.Timestamp(day, tz="UTC").timestamp()))


def _write_prices(path: Path) -> None:
    rows: list[dict[str, object]] = []
    for day in pd.date_range("2025-01-01", "2025-01-06", freq="D"):
        for token, symbol, price in (
            (WETH, "WETH", 2_000.0),
            (USDC, "USDC", 1.0),
        ):
            rows.append(
                {
                    "day": day.strftime("%Y%m%d"),
                    "token": token,
                    "symbol": symbol,
                    "price_usd": price,
                    "n_observations": 5,
                    "n_consensus": 5,
                    "consensus_share": 1.0,
                    "gross_weight_usd": 1_000.0,
                    "consensus_weight_usd": 1_000.0,
                    "price_source": "canonical_repriced_route_legs",
                    "validation_status": (
                        "minimum_observations_and_price_consensus_passed"
                    ),
                }
            )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _registry() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pool": POOL_A,
                "token0_address": WETH,
                "token0_symbol": "WETH",
                "token1_address": USDC,
                "token1_symbol": "USDC",
            },
            {
                "pool": POOL_B,
                "token0_address": USDC,
                "token0_symbol": "USDC",
                "token1_address": OTHER,
                "token1_symbol": "OTHER",
            },
        ]
    )


def _event(
    *,
    pool: str,
    token0: str,
    token1: str,
    amount0: str,
    amount1: str,
    liquidity: object,
    event_id: str,
    day: str = "2025-01-05",
    needs_complete: bool = False,
) -> dict[str, object]:
    return {
        "amount0": amount0,
        "amount1": amount1,
        "amountUSD": "999999",
        "id": event_id,
        "liquidity": liquidity,
        "logIndex": "7",
        "needsComplete": needs_complete,
        "origin": "0x0000000000000000000000000000000000000abc",
        "pair": {
            "id": pool,
            "token0": {"id": token0, "symbol": "TOKEN0"},
            "token1": {"id": token1, "symbol": "TOKEN1"},
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
    event_dir: Path,
    *,
    day: str,
    mints: list[dict[str, object]],
    burns: list[dict[str, object]],
) -> None:
    for stem, rows in (("mints", mints), ("burns", burns)):
        path = event_dir / f"uniswap_v2_{stem}_{day.replace('-', '')}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")


def _write_daily(
    event_dir: Path,
    *,
    day: str,
    pool: str,
    volume: str,
) -> None:
    path = event_dir / f"uniswap_v2_daily_{day.replace('-', '')}.jsonl.gz"
    row = {
        "id": f"{pool}-{day}",
        "date": int(pd.Timestamp(day, tz="UTC").timestamp()),
        "dailyVolumeUSD": volume,
        "reserveUSD": "100000",
        "pairAddress": pool,
        "token0": {"symbol": "WETH"},
        "token1": {"symbol": "USDC"},
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def _write_capital(path: Path) -> None:
    rows = []
    for day, reserve0, reserve1, capital, lagged, exact_lag in (
        ("20250104", 10.0, 20.0, 40_000.0, None, False),
        ("20250105", 12.0, 24.0, 48_000.0, 40_000.0, True),
    ):
        rows.append(
            {
                "venue": "uniswap_v2",
                "day": day,
                "pool": POOL_A,
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
                "price_source": (
                    "canonical_repriced_route_legs_with_address_time_sanity"
                ),
                "capital_validation_status": "audited_exact_reserve_capital",
                "identity_validation_status": "exact_identity_and_decimals_passed",
                "token_mechanics_status": "standard_token_mechanics",
                "failure_reason": None,
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_v2_lp_flow_loader_keeps_true_flows_and_liquidity_separate(
    tmp_path: Path,
) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    price_path = tmp_path / "prices.parquet"
    _write_prices(price_path)
    _write_events(
        event_dir,
        day="2025-01-05",
        mints=[
            _event(
                pool=POOL_A,
                token0=WETH,
                token1=USDC,
                amount0="1",
                amount1="2000",
                liquidity="10",
                event_id="1",
            ),
            _event(
                pool=POOL_A,
                token0=WETH,
                token1=USDC,
                amount0="2",
                amount1="4000",
                liquidity="3",
                event_id="2",
                needs_complete=True,
            ),
            _event(
                pool=POOL_B,
                token0=USDC,
                token1=OTHER,
                amount0="100",
                amount1="50",
                liquidity="2",
                event_id="3",
            ),
        ],
        burns=[
            _event(
                pool=POOL_A,
                token0=WETH,
                token1=USDC,
                amount0="0.5",
                amount1="1000",
                liquidity="5",
                event_id="4",
            )
        ],
    )

    flows, support = load_raw_uniswap_v2_lp_flows(
        event_dir=event_dir,
        pool_registry=_registry(),
        price_path=price_path,
    )

    pool_a = flows[flows["pool"].eq(POOL_A)].iloc[0]
    pool_b = flows[flows["pool"].eq(POOL_B)].iloc[0]
    assert pool_a["v2_add_lp_flow_usd"] == pytest.approx(12_000.0)
    assert pool_a["v2_remove_lp_flow_usd"] == pytest.approx(2_000.0)
    assert pool_a["v2_gross_lp_flow_usd"] == pytest.approx(14_000.0)
    assert pool_a["v2_net_add_lp_flow_usd"] == pytest.approx(10_000.0)
    assert pool_a["v2_add_liquidity"] == pytest.approx(13.0)
    assert pool_a["v2_remove_liquidity"] == pytest.approx(5.0)
    assert pool_a["v2_net_add_liquidity"] == pytest.approx(8.0)
    assert pool_a["v2_needs_complete_add_liquidity"] == pytest.approx(3.0)
    assert pool_a["v2_needs_complete_remove_liquidity"] == 0
    assert (
        pool_a["v2_liquidity_support_status"]
        == "raw_liquidity_contains_needs_complete_source_flag"
    )
    assert pool_a["v2_needs_complete_events"] == 1
    assert pool_a["v2_flow_valuation_status"] == "all_eligible_events_two_sided_canonical"
    assert pool_b["v2_add_lp_flow_usd"] == 0
    assert pool_b["v2_add_token0_flow_usd_priced"] == pytest.approx(100.0)
    assert pool_b["v2_one_price_events"] == 1
    assert support["full_price_events"] == 3
    assert support["one_price_events"] == 1
    assert support["needs_complete_events"] == 1
    assert support["valid_liquidity_events"] == 4


def test_v2_lp_flow_run_retains_eventless_volume_days_and_capital_state(
    tmp_path: Path,
) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    price_path = tmp_path / "prices.parquet"
    capital_path = tmp_path / "capital.parquet"
    output = tmp_path / "flows.parquet"
    support = tmp_path / "support.jsonl"
    _write_prices(price_path)
    _write_capital(capital_path)
    _write_daily(event_dir, day="2025-01-04", pool=POOL_A, volume="1000")
    _write_daily(event_dir, day="2025-01-05", pool=POOL_A, volume="2000")
    _write_events(
        event_dir,
        day="2025-01-05",
        mints=[
            _event(
                pool=POOL_A,
                token0=WETH,
                token1=USDC,
                amount0="1",
                amount1="2000",
                liquidity="10",
                event_id="5",
            )
        ],
        burns=[],
    )

    assert (
        run(
            output_path=output,
            support_path=support,
            event_dir=event_dir,
            capital_path=capital_path,
            price_path=price_path,
        )
        == 0
    )
    panel = pd.read_parquet(output).sort_values("origin_date").reset_index(drop=True)
    assert len(panel) == 2
    assert panel["venue"].eq("uniswap_v2").all()
    assert panel.loc[0, "v2_volume_usd"] == pytest.approx(1_000.0)
    assert panel.loc[0, "v2_fee_opportunity_usd"] == pytest.approx(3.0)
    assert panel.loc[0, "v2_gross_lp_flow_usd"] == 0
    assert panel.loc[0, "v2_flow_valuation_status"] == "no_lp_events"
    assert panel.loc[1, "v2_volume_usd"] == pytest.approx(2_000.0)
    assert panel.loc[1, "v2_fee_opportunity_usd"] == pytest.approx(6.0)
    assert panel.loc[1, "v2_add_lp_flow_usd"] == pytest.approx(4_000.0)
    assert panel.loc[1, "v2_lagged_capital_usd"] == pytest.approx(40_000.0)
    assert panel.loc[1, "v2_lagged_sqrt_k"] == pytest.approx((10.0 * 20.0) ** 0.5)
    assert panel.loc[1, "v2_exact_lag_valid"]
    assert "eventless_pool_days" in support.read_text()


def test_v2_lp_fee_rate_changes_on_first_complete_post_activation_day(
    tmp_path: Path,
) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    _write_daily(event_dir, day="2025-12-27", pool=POOL_A, volume="1000")
    _write_daily(event_dir, day="2025-12-28", pool=POOL_A, volume="1000")

    calendar, _support = load_raw_v2_pool_day_calendar(event_dir)
    rates = calendar.set_index("origin_date")["v2_lp_fee_rate"]
    fees = calendar.set_index("origin_date")["v2_fee_opportunity_usd"]

    assert rates.loc[pd.Timestamp("2025-12-27")] == pytest.approx(0.003)
    assert rates.loc[pd.Timestamp("2025-12-28")] == pytest.approx(0.0025)
    assert fees.loc[pd.Timestamp("2025-12-27")] == pytest.approx(3.0)
    assert fees.loc[pd.Timestamp("2025-12-28")] == pytest.approx(2.5)


def test_v2_lp_flow_loader_retains_needs_complete_burn_amounts(
    tmp_path: Path,
) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    price_path = tmp_path / "prices.parquet"
    _write_prices(price_path)
    _write_events(
        event_dir,
        day="2025-01-05",
        mints=[],
        burns=[
            _event(
                pool=POOL_A,
                token0=WETH,
                token1=USDC,
                amount0="0.5",
                amount1="1000",
                liquidity="5",
                event_id="7",
                needs_complete=True,
            )
        ],
    )

    flows, support = load_raw_uniswap_v2_lp_flows(
        event_dir=event_dir,
        pool_registry=_registry(),
        price_path=price_path,
    )

    row = flows.iloc[0]
    assert row["v2_remove_lp_flow_usd"] == pytest.approx(2_000.0)
    assert row["v2_remove_liquidity"] == pytest.approx(5.0)
    assert row["v2_needs_complete_remove_liquidity"] == pytest.approx(5.0)
    assert row["v2_remove_events_valued"] == 1
    assert row["v2_needs_complete_events"] == 1
    assert row["v2_full_price_event_share"] == pytest.approx(1.0)
    assert row["v2_flow_valuation_status"] == "all_eligible_events_two_sided_canonical"
    assert support["full_price_events"] == 1
    assert support["needs_complete_events"] == 1


def test_v2_lp_flow_loader_counts_missing_liquidity(tmp_path: Path) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    price_path = tmp_path / "prices.parquet"
    _write_prices(price_path)
    _write_events(
        event_dir,
        day="2025-01-05",
        mints=[
            _event(
                pool=POOL_A,
                token0=WETH,
                token1=USDC,
                amount0="1",
                amount1="2000",
                liquidity=None,
                event_id="6",
            )
        ],
        burns=[],
    )
    flows, support = load_raw_uniswap_v2_lp_flows(
        event_dir=event_dir,
        pool_registry=_registry(),
        price_path=price_path,
    )
    assert flows.iloc[0]["v2_add_lp_flow_usd"] == pytest.approx(4_000.0)
    assert flows.iloc[0]["v2_add_liquidity"] == 0
    assert flows.iloc[0]["v2_missing_invalid_liquidity_events"] == 1
    assert support["missing_invalid_liquidity_events"] == 1

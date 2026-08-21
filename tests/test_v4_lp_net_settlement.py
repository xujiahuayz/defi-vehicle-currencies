from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from scripts.analyze.run_v4_lp_net_settlement import (
    CONTROLS,
    build_horizon_panel,
    fit_net_settlement_models,
)
from scripts.process.build_v4_lp_net_settlement_weekly import (
    NATIVE_ETH_ADDRESS,
    WETH_ADDRESS,
    aggregate_provider_pool_week,
    build_day_transactions,
)


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
POOL = "0x" + "ab" * 32
ORIGIN = "0x" + "11" * 20
SENDER = "0x" + "22" * 20


def _event(
    transaction: str,
    *,
    liquidity: float,
    amount0: float,
    amount1: float,
    log_index: int,
    tick_lower: int = -100,
    tick_upper: int = 100,
) -> dict[str, object]:
    timestamp = int(pd.Timestamp("2025-01-08T12:00:00Z").timestamp())
    return {
        "id": f"{transaction}-{log_index}",
        "transaction": {"id": transaction, "timestamp": str(timestamp)},
        "timestamp": str(timestamp),
        "pool": {
            "id": POOL,
            "token0": {"id": NATIVE_ETH_ADDRESS, "symbol": "ETH"},
            "token1": {"id": USDC, "symbol": "USDC"},
        },
        "origin": ORIGIN,
        "sender": SENDER,
        "amount": str(liquidity),
        "amount0": str(amount0),
        "amount1": str(amount1),
        "tickLower": str(tick_lower),
        "tickUpper": str(tick_upper),
        "logIndex": str(log_index),
    }


def _write_gzip_json(path, rows: list[dict[str, object]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_transaction_netting_and_weekly_lp_supply_are_kept_separate(tmp_path) -> None:
    transaction_one = "0x" + "01" * 32
    transaction_two = "0x" + "02" * 32
    modify_path = tmp_path / "uniswap_v4_modify_liquidities_20250108.jsonl.gz"
    swap_path = tmp_path / "uniswap_v4_swaps_20250108.jsonl.gz"
    _write_gzip_json(
        modify_path,
        [
            _event(
                transaction_one,
                liquidity=-10,
                amount0=-10,
                amount1=-20,
                log_index=1,
            ),
            _event(
                transaction_one,
                liquidity=7,
                amount0=7,
                amount1=14,
                log_index=2,
                tick_lower=-50,
                tick_upper=50,
            ),
            _event(
                transaction_two,
                liquidity=2,
                amount0=2,
                amount1=4,
                log_index=3,
            ),
        ],
    )
    swap = _event(
        transaction_one,
        liquidity=0,
        amount0=3,
        amount1=6,
        log_index=4,
    )
    swap.pop("amount")
    swap.pop("tickLower")
    swap.pop("tickUpper")
    _write_gzip_json(swap_path, [swap])
    prices = {
        ("20250108", WETH_ADDRESS): 2.0,
        ("20250108", USDC): 1.0,
    }

    transactions, support = build_day_transactions(
        modify_path, swap_path, prices=prices
    )
    assert support["provider_pool_transaction_rows"] == 2
    first = transactions.set_index("transaction_id").loc[transaction_one]
    assert first["reposition_tx"] == 1
    assert first["gross_obligation_count"] == 6
    assert first["net_obligation_count"] == 0
    assert first["settlement_count_reduction_share"] == 1.0
    assert first["amount_netting_value_share"] == 1.0
    assert first["lp_tx_has_netting"] == 1

    weekly = aggregate_provider_pool_week(transactions)
    row = weekly.iloc[0]
    assert row["lp_tx_count"] == 2
    assert row["netting_tx_share"] == 0.5
    assert row["settlement_count_reduction_share"] == 0.75
    assert row["add_lp_flow_usd"] == 36.0
    assert row["remove_lp_flow_usd"] == 40.0
    assert row["net_add_lp_flow_usd"] == -4.0
    assert row["reposition_tx_count"] == 1
    assert row["first_observed_participation_proxy"] == 1
    assert row["last_observed_participation_proxy"] == 1


def _weekly_row(
    provider: str,
    pool: str,
    week: str,
    *,
    add: float,
    remove: float,
    txs: int = 1,
    netting: float = 0.2,
    last: int = 0,
) -> dict[str, object]:
    gross = add + remove
    return {
        "week_start": pd.Timestamp(week),
        "origin": provider,
        "pool": pool,
        "provider_pool_id": f"{provider}|{pool}",
        "lp_tx_count": txs,
        "netting_tx_share": netting,
        "settlement_count_reduction_share": 0.5 * netting,
        "amount_netting_value_share": 0.25 * netting,
        "settlement_value_coverage_share": 1.0,
        "gross_lp_flow_usd": gross,
        "add_lp_flow_usd": add,
        "remove_lp_flow_usd": remove,
        "net_add_flow_balance": (add - remove) / (gross + 1.0),
        "supply_side_assignments": 2 * txs,
        "valued_supply_side_assignments": 2 * txs,
        "reposition_tx_count": int(txs > 1),
        "reposition_tx_share": float(txs > 1) / txs,
        "add_log_tick_width_sum": np.log(200.0) if add > 0 else 0.0,
        "add_range_observations": int(add > 0),
        "last_observed_participation_proxy": last,
    }


def test_horizon_panel_uses_only_subsequent_weeks_and_labels_inactivity() -> None:
    rows = [
        _weekly_row("provider-a", "pool-a", "2025-01-06", add=10, remove=2),
        _weekly_row("provider-a", "pool-a", "2025-01-13", add=20, remove=3),
        _weekly_row("provider-a", "pool-a", "2025-01-20", add=30, remove=4),
        _weekly_row("provider-a", "pool-a", "2025-01-27", add=40, remove=5),
        _weekly_row("provider-a", "pool-a", "2025-02-03", add=50, remove=6, last=1),
        _weekly_row("provider-b", "pool-b", "2025-01-06", add=5, remove=1, last=1),
    ]
    panel = build_horizon_panel(pd.DataFrame(rows), horizon_weeks=2)
    first = panel[
        panel["provider_pool_id"].eq("provider-a|pool-a")
        & panel["week_start"].eq(pd.Timestamp("2025-01-06"))
    ].iloc[0]
    assert first["future_log1p_add_lp_flow_usd"] == np.log1p(50.0)
    assert first["future_log1p_remove_lp_flow_usd"] == np.log1p(7.0)
    assert first["future_active"] == 1
    inactive = panel[panel["provider_pool_id"].eq("provider-b|pool-b")].iloc[0]
    assert inactive["future_active"] == 0
    assert inactive["future_inactivity_persistence_proxy"] == 1


def test_net_settlement_regression_absorbs_provider_pool_and_week() -> None:
    rng = np.random.default_rng(117)
    rows: list[dict[str, object]] = []
    for provider_index in range(30):
        provider_pool = f"provider-{provider_index}|pool-{provider_index % 5}"
        provider_effect = 0.03 * provider_index
        for week_index, week in enumerate(pd.date_range("2025-01-06", periods=12, freq="7D")):
            netting = 0.05 + 0.02 * ((provider_index + 3 * week_index) % 11)
            controls = {
                "log1p_current_gross_lp_flow_usd": 2.0 + 0.01 * provider_index,
                "log1p_current_lp_txs": 0.7 + 0.01 * (week_index % 4),
                "current_net_add_flow_balance": 0.1 * np.sin(provider_index + week_index),
                "current_reposition_tx_share": 0.05 * ((provider_index + week_index) % 3),
            }
            outcome = (
                1.5 * netting
                + provider_effect
                + 0.02 * week_index
                + 0.05 * controls["current_net_add_flow_balance"]
                + rng.normal(0.0, 0.01)
            )
            rows.append(
                {
                    "week_start": week,
                    "horizon_weeks": 4,
                    "provider_pool_id": provider_pool,
                    "current_settlement_value_coverage_share": 1.0,
                    "future_lp_flow_value_coverage_share": 1.0,
                    "netting_tx_share": netting,
                    "future_log1p_add_lp_flow_usd": outcome,
                    **controls,
                }
            )
    results = fit_net_settlement_models(
        pd.DataFrame(rows),
        predictors=("netting_tx_share",),
        outcomes=("future_log1p_add_lp_flow_usd",),
        controls=CONTROLS,
        min_observations=100,
        min_clusters=20,
    )
    result = results.iloc[0]
    assert result["record_type"] == "v4_lp_net_settlement_regression"
    assert np.isfinite(result["coefficient"])
    assert result["coefficient"] > 0
    assert result["provider_pool_clusters"] == 30

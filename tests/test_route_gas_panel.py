from __future__ import annotations

import numpy as np
import pandas as pd

from ddvc.route_gas import (
    RouteGasEstimator,
    deterministic_route_sample,
    route_gas_rows,
)


WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
TOKEN = "0x1111111111111111111111111111111111111111"


def _two_leg(tx: str, source1: str = "uniswap_v2", source2: str = "uniswap_v3") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "tx_hash": tx,
                "component_id": 0,
                "n_components": 1,
                "source": source1,
                "token_in": TOKEN,
                "token_out": WETH,
                "amount_usd": 1_000.0,
                "log_index": 1,
                "route_class": "coherent",
                "tin_role": "source",
                "tout_role": "intermediate",
            },
            {
                "tx_hash": tx,
                "component_id": 0,
                "n_components": 1,
                "source": source2,
                "token_in": WETH,
                "token_out": USDC,
                "amount_usd": 990.0,
                "log_index": 2,
                "route_class": "coherent",
                "tin_role": "intermediate",
                "tout_role": "sink",
            },
        ]
    )


def test_route_gas_rows_preserve_ordered_venues_and_intermediary() -> None:
    rows = route_gas_rows(_two_leg("0x" + "1" * 64), "20240115")
    assert len(rows) == 1
    row = rows.iloc[0]
    assert row["venue_sequence"] == "uniswap_v2>uniswap_v3"
    assert row["mid"] == WETH
    assert row["mid_type"] == "native"
    assert row["route_notional_usd"] == 990.0


def test_route_sample_uses_existing_transaction_identity_without_extra_hash() -> None:
    parts = []
    for digit in "321":
        parts.append(route_gas_rows(_two_leg("0x" + digit * 64), "20240115"))
    sample = deterministic_route_sample(pd.concat(parts), per_cell=2)
    assert sample["tx_hash"].tolist() == ["0x" + "1" * 64, "0x" + "2" * 64]


def test_route_gas_estimator_uses_router_and_ordered_venue_cells() -> None:
    rows = []
    for index in range(600):
        router = "0x" + ("a" if index < 300 else "b") * 40
        venue = "uniswap_v2>uniswap_v3" if index % 2 == 0 else "uniswap_v3>uniswap_v2"
        base = 180_000 if router.endswith("a" * 40) else 260_000
        rows.append(
            {
                "tx_hash": f"0x{index:064x}",
                "year": 2024,
                "legs": 2,
                "venue_sequence": venue,
                "tx_to": router,
                "gas_used": base + (index % 7) * 1_000,
            }
        )
    estimator = RouteGasEstimator(pd.DataFrame(rows))
    request = pd.DataFrame(
        [
            {
                "year": 2024,
                "legs": 2,
                "venue_sequence": "uniswap_v2|uniswap_v3",
                "tx_to": "0x" + "a" * 40,
            },
            {
                "year": 2024,
                "legs": 2,
                "venue_sequence": "uniswap_v2|uniswap_v3",
                "tx_to": "0x" + "b" * 40,
            },
        ]
    )
    prediction = estimator.predict(request)
    assert prediction.median[0] < prediction.median[1]
    assert np.all(prediction.p25 <= prediction.median)
    assert np.all(prediction.median <= prediction.p75)
    assert set(prediction.support) == {"year_router_ordered_venues"}

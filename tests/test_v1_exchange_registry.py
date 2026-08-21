from __future__ import annotations

import pandas as pd
import pytest

from scripts.fetch.fetch_v1_exchange_registry import validate_rows
from scripts.process.build_v1_exchange_token_crosswalk import build_crosswalk
from scripts.process.build_v1_route_case import attach_token_identities


EXCHANGE_A = "0x" + "1" * 40
EXCHANGE_B = "0x" + "2" * 40
TOKEN_A = "0x" + "a" * 40
TOKEN_B = "0x" + "b" * 40


def test_v1_exchange_registry_requires_one_exchange_per_token() -> None:
    rows = [
        {"id": EXCHANGE_A, "tokenAddress": TOKEN_A, "tokenSymbol": "AAA"},
        {"id": EXCHANGE_B, "tokenAddress": TOKEN_B, "tokenSymbol": "BBB"},
    ]
    assert validate_rows(rows) == {
        "rows": 2,
        "unique_exchanges": 2,
        "unique_tokens": 2,
    }
    with pytest.raises(ValueError, match="duplicate V1 token"):
        validate_rows([rows[0], {**rows[1], "tokenAddress": TOKEN_A}])


def test_exact_crosswalk_covers_every_observed_exchange() -> None:
    registry = pd.DataFrame(
        {
            "exchange": [EXCHANGE_A, EXCHANGE_B],
            "token": [TOKEN_A, TOKEN_B],
            "symbol": ["AAA", "BBB"],
        }
    )
    exchange_day = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-05-01", "2020-06-01"]),
            "exchange": [EXCHANGE_A, EXCHANGE_B],
            "n_pair": [1, 1],
            "n_t2t": [0, 0],
        }
    )
    crosswalk, summary = build_crosswalk(registry, exchange_day)
    assert summary["observed_exchanges_resolved"] == 2
    assert crosswalk.set_index("exchange").loc[EXCHANGE_A, "v1_era"]
    assert not crosswalk.set_index("exchange").loc[EXCHANGE_B, "v1_era"]
    assert crosswalk.resolved.all()


def test_exact_crosswalk_refuses_partial_registry() -> None:
    registry = pd.DataFrame(
        {"exchange": [EXCHANGE_A], "token": [TOKEN_A], "symbol": ["AAA"]}
    )
    exchange_day = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-05-01", "2020-05-01"]),
            "exchange": [EXCHANGE_A, EXCHANGE_B],
            "n_pair": [1, 1],
            "n_t2t": [0, 0],
        }
    )
    with pytest.raises(ValueError, match="registry misses 1/2 observed exchanges"):
        build_crosswalk(registry, exchange_day)


def test_registered_v1_route_uses_exact_crosswalk_identities() -> None:
    case = {
        "legs": [
            {"exchange": EXCHANGE_A, "role": "token_to_eth"},
            {"exchange": EXCHANGE_B.upper(), "role": "eth_to_token"},
        ]
    }
    crosswalk = pd.DataFrame(
        {
            "exchange": [EXCHANGE_A, EXCHANGE_B],
            "token": [TOKEN_A, TOKEN_B],
            "symbol": ["AAA", "BBB"],
            "resolved": [True, True],
        }
    )

    resolved = attach_token_identities(case, crosswalk)

    assert [(leg["token"], leg["symbol"]) for leg in resolved["legs"]] == [
        (TOKEN_A, "AAA"),
        (TOKEN_B, "BBB"),
    ]

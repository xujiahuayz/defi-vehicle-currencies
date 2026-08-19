from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ddvc.route_replay import (
    build_route_replay_manifest,
    render_route_replay_deck_values,
)


ROOT = Path(__file__).resolve().parents[1]


def _legs() -> pd.DataFrame:
    common = {
        "tx_hash": "0xabc",
        "component_id": 0,
        "route_class": "coherent",
        "timestamp_utc": 1_768_003_200,
    }
    return pd.DataFrame([
        {
            **common,
            "log_index": 7,
            "source": "fluid",
            "token_in": "0x0000000000000000000000000000000000000001",
            "token_out": "0x0000000000000000000000000000000000000002",
            "token_in_sym": "USDC",
            "token_out_sym": "USDT",
            "tin_role": "source",
            "tout_role": "intermediate",
            "amount_in": 100_000.0,
            "amount_out": 99_990.0,
            "amount_usd": 100_000.0,
        },
        {
            **common,
            "log_index": 11,
            "source": "uniswap_v4",
            "token_in": "0x0000000000000000000000000000000000000002",
            "token_out": "0x0000000000000000000000000000000000000003",
            "token_in_sym": "USDT",
            "token_out_sym": "USDe",
            "tin_role": "intermediate",
            "tout_role": "sink",
            "amount_in": 99_990.0,
            "amount_out": 100_040.0,
            "amount_usd": 99_990.0,
        },
    ])


def test_manifest_preserves_authentic_transaction_and_route_order() -> None:
    manifest = build_route_replay_manifest(
        _legs(), day="20260110", tx_hash="0xABC", component_id=0
    )

    assert manifest["tx_hash"] == "0xabc"
    assert manifest["route"]["source"] == "USDC"
    assert manifest["route"]["vehicle"] == "USDT"
    assert manifest["route"]["target"] == "USDe"
    assert [leg["venue"] for leg in manifest["route"]["legs"]] == ["fluid", "uniswap_v4"]


def test_manifest_rejects_a_missing_second_leg() -> None:
    with pytest.raises(ValueError, match="exactly one coherent two-leg"):
        build_route_replay_manifest(
            _legs().iloc[:1],
            day="20260110",
            tx_hash="0xabc",
            component_id=0,
        )


def test_deck_labels_are_generated_from_the_route_manifest() -> None:
    manifest = build_route_replay_manifest(
        _legs(), day="20260110", tx_hash="0xabc", component_id=0
    )

    values = render_route_replay_deck_values(manifest)

    assert r"\RouteReplayInputAmount}{100,000}" in values
    assert r"\RouteReplayVehicleAmount}{99,990}" in values
    assert r"\RouteReplayOutputAmount}{100,040}" in values
    assert r"\RouteReplayValue}{100,000}" in values

    source = (ROOT / "deck" / "sections" / "01-identification.tex").read_text(
        encoding="utf-8"
    )
    assert source.count("assets/observed_route_blockscout.png") == 3
    assert "maker supplies the USDC used by the Fluid leg" in source

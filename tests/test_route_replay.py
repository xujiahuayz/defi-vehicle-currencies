from __future__ import annotations

import pandas as pd
import pytest

from ddvc.route_replay import (
    build_route_replay_manifest,
    render_route_replay_html,
    render_route_replay_pdf,
)


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
        _legs(), day="20260110", tx_hash="0xABC", component_id=0, partition_sha256="f" * 64
    )

    assert manifest["tx_hash"] == "0xabc"
    assert manifest["partition_sha256"] == "f" * 64
    assert manifest["route"]["source"] == "USDC"
    assert manifest["route"]["vehicle"] == "USDT"
    assert manifest["route"]["target"] == "USDe"
    assert [leg["venue"] for leg in manifest["route"]["legs"]] == ["fluid", "uniswap_v4"]


def test_replay_is_selectable_progressive_and_print_complete() -> None:
    manifest = build_route_replay_manifest(
        _legs(), day="20260110", tx_hash="0xabc", component_id=0, partition_sha256="f" * 64
    )
    page = render_route_replay_html(manifest)

    assert 'data-step="1"' in page and 'data-step="2"' in page
    assert "Reveal next leg" in page
    assert "@media print" in page
    assert "partition_sha256" not in page
    assert "Fluid" in page and "Uniswap V4" in page


def test_manifest_rejects_a_missing_second_leg() -> None:
    with pytest.raises(ValueError, match="exactly one coherent two-leg"):
        build_route_replay_manifest(
            _legs().iloc[:1],
            day="20260110",
            tx_hash="0xabc",
            component_id=0,
            partition_sha256="f" * 64,
        )


def test_static_replay_is_a_vector_pdf(tmp_path) -> None:
    manifest = build_route_replay_manifest(
        _legs(), day="20260110", tx_hash="0xabc", component_id=0, partition_sha256="f" * 64
    )
    output = tmp_path / "route.pdf"
    render_route_replay_pdf(manifest, output)
    assert output.read_bytes().startswith(b"%PDF")
    assert output.stat().st_size > 1_000

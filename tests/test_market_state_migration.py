from __future__ import annotations

import gzip
import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import pytest

from ddvc.artifact_release import file_sha256
from ddvc.market_state_release import MarketStateReleaseEntry, panel_content_identity
from ddvc.state_data import (
    FAMILY_PRODUCER_FINGERPRINTS,
    FAMILY_STREAMS,
    SCHEMA_VERSION as STATE_SCHEMA_VERSION,
    STATE_ROOT,
    StatePartitionQuality,
    bind_state_partition_output,
    normalise_cp_partition,
    normalise_multi_asset_partition,
)
from scripts.build_market_state import (
    build_family,
    migrate_v1_partition,
    preflight_event_order_generations,
    rekey_current_partition,
    rekey_source_current,
    validate_migration_sample,
    validate_rekey_sample,
)


def test_event_order_preflight_reports_every_stale_generation() -> None:
    def inspect(_raw: Path, venue: str, day: str):
        if day in {"20250101", "20250103"}:
            raise ValueError(f"stale {venue}/{day}")
        return None

    with patch(
        "scripts.build_market_state.load_event_order_generation_metadata",
        side_effect=inspect,
    ), pytest.raises(RuntimeError, match="2 invalid generation") as error:
        preflight_event_order_generations(
            [
                ("uniswap_v3", "20250101"),
                ("uniswap_v3", "20250102"),
                ("uniswap_v2", "20250103"),
                ("curve", "20250104"),
            ]
        )
    assert "uniswap_v3/20250101" in str(error.value)
    assert "uniswap_v2/20250103" in str(error.value)


def write_streams(
    raw: Path,
    family: str,
    venue: str,
    day: str,
    payloads: dict[str, list[dict]],
) -> None:
    for stream, _kind, _sign in FAMILY_STREAMS[family][venue]:
        path = raw / venue / f"{venue}_{stream}_{day}.jsonl.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt") as handle:
            for row in payloads.get(stream, []):
                handle.write(json.dumps(row) + "\n")


def write_v1_source(source: Path, family: str, venue: str, day: str, frame, quality) -> None:
    path = source / family / venue / f"{day}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = frame.drop(
        columns=[
            "pool_family",
            "invariant_family",
            "state_generation",
            "quote_unsupported_reason",
        ]
    ).copy()
    if family == "multi_asset":
        legacy = legacy.rename(columns={"provider_pool_type": "pool_type"})
    legacy["schema_version"] = 1
    legacy.to_parquet(path, index=False)
    marker = asdict(quality)
    marker["schema_version"] = 1
    path.with_suffix(".quality.json").write_text(json.dumps(marker))


def write_v2_source(source: Path, family: str, venue: str, day: str, frame, quality) -> Path:
    path = source / family / venue / f"{day}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    quality = bind_state_partition_output(quality, path)
    path.with_suffix(".quality.json").write_text(json.dumps(asdict(quality)))
    return path


def test_schema_current_rekey_hardlinks_only_after_raw_exact_validation(tmp_path) -> None:
    raw, source, target = tmp_path / "raw", tmp_path / "source", tmp_path / "target"
    day = "20250101"
    pair = {
        "id": "pool",
        "token0": {"id": "0xa", "symbol": "A", "decimals": 18},
        "token1": {"id": "0xb", "symbol": "B", "decimals": 6},
    }
    write_streams(
        raw,
        "constant_product",
        "sushiswap_v2",
        day,
        {
            "hourly_reserves": [{
                "id": "snapshot", "hourStartUnix": 0, "reserve0": "100",
                "reserve1": "200", "pair": pair,
            }],
            "swaps": [],
        },
    )
    frame, quality = normalise_cp_partition(raw, "sushiswap_v2", day)
    source_path = write_v2_source(
        source, "constant_product", "sushiswap_v2", day, frame, quality
    )
    with patch("scripts.build_market_state.RAW", raw):
        rekey_current_partition(
            source, "constant_product", "sushiswap_v2", day, target
        )
        validate_rekey_sample(
            "constant_product", "sushiswap_v2", day, target
        )
    target_path = target / "constant_product" / "sushiswap_v2" / f"{day}.parquet"
    assert source_path.stat().st_ino == target_path.stat().st_ino


def test_released_rekey_uses_marker_and_stat_identity_without_rereading_panel_bytes(tmp_path) -> None:
    raw, source, target = tmp_path / "raw", tmp_path / "source", tmp_path / "target"
    day = "20250101"
    pair = {
        "id": "pool",
        "token0": {"id": "0xa", "symbol": "A", "decimals": 18},
        "token1": {"id": "0xb", "symbol": "B", "decimals": 6},
    }
    write_streams(
        raw,
        "constant_product",
        "sushiswap_v2",
        day,
        {
            "hourly_reserves": [{"id": "snapshot", "hourStartUnix": 0, "reserve0": "100", "reserve1": "200", "pair": pair}],
            "swaps": [],
        },
    )
    frame, quality = normalise_cp_partition(raw, "sushiswap_v2", day)
    panel = write_v2_source(source, "constant_product", "sushiswap_v2", day, frame, quality)
    marker = panel.with_suffix(".quality.json")
    bound = json.loads(marker.read_text(encoding="utf-8"))
    entry = MarketStateReleaseEntry(
        family="constant_product",
        venue="sushiswap_v2",
        day=day,
        panel_relative=f"constant_product/sushiswap_v2/{day}.parquet",
        marker_relative=f"constant_product/sushiswap_v2/{day}.quality.json",
        input_fingerprint=bound["input_fingerprint"],
        producer_fingerprint=bound["producer_fingerprint"],
        output_bytes=bound["output_bytes"],
        output_sha256=bound["output_sha256"],
        marker_sha256=file_sha256(marker),
        panel_stat_identity=panel_content_identity(panel),
    )
    with (
        patch("scripts.build_market_state.RAW", raw),
        patch("scripts.build_market_state.state_partition_output_is_current", side_effect=AssertionError("full panel hash should not run")),
    ):
        rekey_current_partition(source, "constant_product", "sushiswap_v2", day, target, entry)
        rekey_current_partition(source, "constant_product", "sushiswap_v2", day, tmp_path / "retry", entry)
    assert panel.stat().st_ino == (target / entry.panel_relative).stat().st_ino
    assert panel_content_identity(panel) == entry.panel_stat_identity


def test_rekey_refuses_a_marker_when_any_current_required_stream_is_missing(tmp_path) -> None:
    raw, source = tmp_path / "raw", tmp_path / "source"
    day = "20250101"
    panel = source / "constant_product" / "sushiswap_v2" / f"{day}.parquet"
    panel.parent.mkdir(parents=True)
    panel.touch()
    panel.with_suffix(".quality.json").write_text(
        json.dumps(
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "passed": True,
                "input_fingerprint": "old",
            }
        )
    )
    with patch("scripts.build_market_state.RAW", raw):
        assert not rekey_source_current(
            source,
            "constant_product",
            "sushiswap_v2",
            day,
        )
        with pytest.raises(FileNotFoundError, match="required raw stream"):
            rekey_current_partition(
                source,
                "constant_product",
                "sushiswap_v2",
                day,
                tmp_path / "target",
            )


def test_v1_migration_matches_fresh_raw_normalization_for_cp_and_multi_asset(tmp_path) -> None:
    raw, source, target = tmp_path / "raw", tmp_path / "source", tmp_path / "target"
    day = "20250101"
    pair = {
        "id": "pool",
        "token0": {"id": "0xa", "symbol": "A", "decimals": 18},
        "token1": {"id": "0xb", "symbol": "B", "decimals": 6},
    }
    write_streams(
        raw,
        "constant_product",
        "sushiswap_v2",
        day,
        {
            "hourly_reserves": [{
                "id": "snapshot",
                "hourStartUnix": 0,
                "reserve0": "100",
                "reserve1": "200",
                "pair": pair,
            }],
            "swaps": [{
                "id": "swap",
                "transaction": {"id": "tx", "blockNumber": "10", "timestamp": "100"},
                "timestamp": "100",
                "logIndex": "4",
                "amount0In": "1",
                "amount0Out": "0",
                "amount1In": "0",
                "amount1Out": "2",
                "pair": pair,
            }],
        },
    )
    cp_frame, cp_quality = normalise_cp_partition(raw, "sushiswap_v2", day)
    write_v1_source(source, "constant_product", "sushiswap_v2", day, cp_frame, cp_quality)

    curve_pool = {
        "id": "curve-pool",
        "symbol": "provider-symbol-not-an-invariant",
        "inputTokens": [
            {"id": "0xa", "symbol": "A", "decimals": 18},
            {"id": "0xb", "symbol": "B", "decimals": 6},
        ],
    }
    write_streams(
        raw,
        "multi_asset",
        "curve",
        day,
        {
            "daily": [{
                "id": "state",
                "timestamp": "100",
                "inputTokenBalances": ["1000", "2000"],
                "pool": curve_pool,
            }],
            "swaps": [{
                "id": "swap",
                "hash": "tx",
                "blockNumber": "10",
                "logIndex": 4,
                "timestamp": "99",
                "pool": curve_pool,
                "tokenIn": {"id": "0xa"},
                "tokenOut": {"id": "0xb"},
                "amountIn": "10",
                "amountOut": "9",
            }],
        },
    )
    multi_frame, multi_quality = normalise_multi_asset_partition(raw, "curve", day)
    write_v1_source(source, "multi_asset", "curve", day, multi_frame, multi_quality)

    with patch("scripts.build_market_state.RAW", raw):
        migrate_v1_partition(
            source,
            "constant_product",
            "sushiswap_v2",
            day,
            target,
        )
        validate_migration_sample(
            "constant_product",
            "sushiswap_v2",
            day,
            target,
        )
        migrate_v1_partition(source, "multi_asset", "curve", day, target)
        validate_migration_sample("multi_asset", "curve", day, target)


def test_cached_migration_partition_is_revalidated_after_restart(tmp_path) -> None:
    source = tmp_path / "source"
    day = "20250101"
    source_day = source / "constant_product" / "sushiswap_v2" / f"{day}.parquet"
    source_day.parent.mkdir(parents=True)
    source_day.touch()
    source_day.with_suffix(".quality.json").touch()
    quality = StatePartitionQuality(
        schema_version=STATE_SCHEMA_VERSION,
        family="constant_product",
        venue="sushiswap_v2",
        day=day,
        producer_fingerprint=FAMILY_PRODUCER_FINGERPRINTS["constant_product"],
        input_fingerprint="fingerprint",
        raw_rows=0,
        canonical_rows=0,
        snapshot_rows=0,
        swap_rows=0,
        liquidity_rows=0,
        initialization_rows=0,
        usable_rows=0,
        missing_order=0,
        missing_identity=0,
        missing_required_streams=0,
        duplicate_events=0,
        conflicting_events=0,
        invalid_swap_sign=0,
        invalid_state=0,
        unsupported_state=0,
        zero_swap_amounts=0,
        missing_quote_statics=0,
        quote_supported_swaps=0,
        output_bytes=0,
        output_sha256="",
        passed=True,
    )
    with (
        patch("scripts.build_market_state.selected_days", return_value=[day]),
        patch("scripts.build_market_state.read_cp_quality", return_value=quality),
        patch("scripts.build_market_state.validate_migration_sample") as validate,
    ):
        rows = build_family(
            "constant_product",
            ["sushiswap_v2"],
            start=day,
            end=day,
            workers=1,
            force=False,
            migrate_from=source,
        )
    assert len(rows) == 1
    validate.assert_called_once_with("constant_product", "sushiswap_v2", day, STATE_ROOT)

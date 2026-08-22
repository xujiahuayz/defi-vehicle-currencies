from __future__ import annotations

import json
from pathlib import Path

from ddvc.ethereum_logs import RAW_LOG_STORAGE_FORMAT
from ddvc.v4_contract import (
    UNISWAP_V4_INITIALIZE_TOPIC,
    UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC,
    UNISWAP_V4_POOL_MANAGER_ADDRESS,
    UNISWAP_V4_SWAP_TOPIC,
)
from scripts.fetch.fetch_v4_route_label_logs import (
    EXISTING_GENERATION,
    OWNED_GENERATION,
    expected_ranges,
    missing_ranges,
)


def completed(root: Path, lower: int, upper: int, *, existing: bool) -> None:
    stem = f"blocks_{lower}_{upper}"
    (root / f"{stem}.parquet").write_bytes(b"parquet")
    suffix = ".meta.json" if existing else ".complete.json"
    (root / f"{stem}{suffix}").write_text(
        json.dumps(
            {
                "status": "complete",
                "generation": EXISTING_GENERATION if existing else OWNED_GENERATION,
                "start_block": lower,
                "end_block": upper,
                "event_topics": (
                    [
                        UNISWAP_V4_INITIALIZE_TOPIC,
                        UNISWAP_V4_MODIFY_LIQUIDITY_TOPIC,
                        UNISWAP_V4_SWAP_TOPIC,
                    ]
                    if existing
                    else [UNISWAP_V4_INITIALIZE_TOPIC, UNISWAP_V4_SWAP_TOPIC]
                ),
                "address_filter": UNISWAP_V4_POOL_MANAGER_ADDRESS,
                "storage_format": RAW_LOG_STORAGE_FORMAT,
            }
        ),
        encoding="utf-8",
    )


def test_expected_ranges_align_and_stop_at_requested_upper() -> None:
    assert expected_ranges(15_001, 35_010) == [
        (10_000, 19_999),
        (20_000, 29_999),
        (30_000, 35_010),
    ]


def test_missing_ranges_combine_read_only_census_and_owned_chunks(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    owned = tmp_path / "owned"
    existing.mkdir()
    owned.mkdir()
    completed(existing, 10_000, 19_999, existing=True)
    completed(owned, 20_000, 29_999, existing=False)
    assert missing_ranges(
        15_001,
        35_010,
        existing_root=existing,
        output_root=owned,
    ) == [(30_000, 35_010)]


def test_payload_without_completion_marker_is_not_coverage(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    owned = tmp_path / "owned"
    existing.mkdir()
    owned.mkdir()
    (owned / "blocks_10000_19999.parquet").write_bytes(b"partial")
    assert missing_ranges(
        10_000,
        19_999,
        existing_root=existing,
        output_root=owned,
    ) == [(10_000, 19_999)]


def test_owned_marker_with_wrong_event_scope_is_not_coverage(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    owned = tmp_path / "owned"
    existing.mkdir()
    owned.mkdir()
    completed(owned, 10_000, 19_999, existing=False)
    marker = owned / "blocks_10000_19999.complete.json"
    record = json.loads(marker.read_text(encoding="utf-8"))
    record["event_topics"] = [UNISWAP_V4_SWAP_TOPIC]
    marker.write_text(json.dumps(record), encoding="utf-8")
    assert missing_ranges(
        10_000,
        19_999,
        existing_root=existing,
        output_root=owned,
    ) == [(10_000, 19_999)]

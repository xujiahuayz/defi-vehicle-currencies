from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ddvc.artifact_release import file_sha256
from ddvc.market_state_release import (
    family_pointer_path,
    market_state_gc_candidates,
    panel_content_identity,
    publish_market_state_family_release,
    resolve_market_state_family_release,
)
from ddvc.state_data import FAMILY_CODE_SOURCES, FAMILY_PRODUCER_FINGERPRINTS


def _release_constant_product(root: Path, engine: str = "engine_prior"):
    state_root = root / engine
    panel = state_root / "constant_product" / "uniswap_v2" / "20250101.parquet"
    panel.parent.mkdir(parents=True)
    panel.write_bytes(b"canonical-partition")
    marker = panel.with_suffix(".quality.json")
    record = {
        "family": "constant_product",
        "venue": "uniswap_v2",
        "day": "20250101",
        "producer_fingerprint": FAMILY_PRODUCER_FINGERPRINTS["constant_product"],
        "input_fingerprint": "a" * 64,
        "output_bytes": panel.stat().st_size,
        "output_sha256": file_sha256(panel),
        "passed": True,
    }
    marker.write_text(json.dumps(record), encoding="utf-8")
    ledger = root / "quality" / "constant_product.parquet"
    ledger.parent.mkdir()
    pd.DataFrame([record]).to_parquet(ledger, index=False)
    pointer = family_pointer_path("constant_product", root=root / "releases")
    release = publish_market_state_family_release(
        pd.DataFrame([record]),
        family="constant_product",
        ledger_path=ledger,
        state_root=state_root,
        pointer_path=pointer,
    )
    return release, panel


def test_family_release_pointer_binds_exact_partition_and_local_reuse_identity(tmp_path) -> None:
    release, panel = _release_constant_product(tmp_path)
    reopened = resolve_market_state_family_release(
        "constant_product", pointer_path=release.pointer_path
    )
    entry = reopened.entries[("uniswap_v2", "20250101")]
    assert reopened.generation_id == release.generation_id
    assert entry.output_sha256 == file_sha256(panel)
    assert entry.panel_stat_identity == panel_content_identity(panel)
    assert not list((tmp_path / "releases").rglob("*.parquet"))


def test_tick_only_dependencies_do_not_fork_other_family_producers() -> None:
    assert "src/ddvc/tick_state_events.py" in FAMILY_CODE_SOURCES["tick"]
    assert "src/ddvc/tick_state_events.py" not in FAMILY_CODE_SOURCES["constant_product"]
    assert "src/ddvc/tick_state_events.py" not in FAMILY_CODE_SOURCES["multi_asset"]


def test_gc_retains_target_current_and_pinned_engines(tmp_path) -> None:
    _release_constant_product(tmp_path)
    target = tmp_path / "engine_target"
    pinned = tmp_path / "engine_pinned"
    stale = tmp_path / "engine_stale"
    for path in (target, pinned, stale):
        path.mkdir()
        (path / "data").write_bytes(path.name.encode())
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({"engines": [pinned.name]}), encoding="utf-8")
    assert market_state_gc_candidates(
        root=tmp_path,
        target_root=target,
        pins_path=pins,
    ) == (stale,)

from __future__ import annotations

import gzip
import json
import threading
from pathlib import Path

import pytest

from ddvc.fetch.material_consumers import (
    ExistingStreamRequirement,
    GraphMaterialConsumerIntent,
    material_consumer_registry_sha256,
)
from ddvc.fetch.raw import installed_source_day_paths
from ddvc.fetch.thin_consumer_audit import (
    RawPartition,
    build_thin_consumer_audit,
    publish_thin_consumer_audit,
    resolve_thin_consumer_audit,
    validate_thin_consumer_audit_envelope,
)
from ddvc.provenance import portable_content_sha256
from ddvc.runtime import exclusive_job
from scripts.stage_graph_acquisition import certify_installed_no_fetch
from source_day_fixtures import install_source_day_metadata


def intent(*fields: str) -> dict[str, GraphMaterialConsumerIntent]:
    return {
        "consumer": GraphMaterialConsumerIntent(
            reason="existing source is sufficient",
            existing_streams=(
                ExistingStreamRequirement("uniswap_v2", "swaps", fields),
            ),
            allowed_new_streams=frozenset(),
            max_selected_streams=0,
        )
    }


def prelaunch_identity(audit_path: Path, intents) -> dict[str, object]:
    return {
        "thin_consumer_audit_sha256": portable_content_sha256(audit_path),
        "consumer_registry_sha256": material_consumer_registry_sha256(intents),
    }


def source_day_audit(
    tmp_path: Path, monkeypatch
) -> tuple[Path, Path, Path, dict[str, GraphMaterialConsumerIntent]]:
    data_root = tmp_path / "data"
    partition = RawPartition("uniswap_v2", "swaps", "20200101")
    raw_path, _marker = installed_source_day_paths(
        partition.source,
        partition.stream,
        __import__("datetime").date(2020, 1, 1),
        data_root=data_root,
    )
    raw_path.parent.mkdir(parents=True)
    with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "swap-1", "transaction": {"id": "tx-1"}}) + "\n")
    install_source_day_metadata(
        data_root / "raw" / "thegraph",
        partition.source,
        (partition.stream,),
        partition.day,
    )
    monkeypatch.setattr(
        "ddvc.fetch.thin_consumer_audit.required_partitions",
        lambda source, streams: (partition,),
    )
    intents = intent("id", "transaction.id")
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(
        json.dumps(
            build_thin_consumer_audit(data_root=data_root, intents=intents),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return audit_path, data_root, raw_path, intents


def test_thin_consumer_audit_reopens_source_day_files(tmp_path: Path, monkeypatch) -> None:
    audit_path, _data_root, _raw_path, intents = source_day_audit(tmp_path, monkeypatch)
    payload = validate_thin_consumer_audit_envelope(audit_path, intents=intents)["audit"]
    marker = payload["source_release_markers"][0]
    assert marker["identity_policy"] == "source-day-file-timestamp-v1"
    assert marker["selected_rows"] == 1
    assert marker["selected_partitions"] == 1


def test_thin_consumer_audit_rejects_field_outside_fetch_schema(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="field perimeter exceeds"):
        build_thin_consumer_audit(
            data_root=tmp_path,
            intents=intent("id", "field_that_no_schema_selects"),
        )


def test_resolver_rejects_absent_or_changed_source_day(tmp_path: Path, monkeypatch) -> None:
    audit_path, data_root, raw_path, intents = source_day_audit(tmp_path, monkeypatch)
    raw_path.write_bytes(raw_path.read_bytes() + b"mutation")
    with pytest.raises(ValueError, match="disagrees with live"):
        certify_installed_no_fetch(
            thin_audit=audit_path,
            data_root=data_root,
            prelaunch=prelaunch_identity(audit_path, intents),
            intents=intents,
        )
    raw_path.unlink()
    with pytest.raises(Exception, match="uncommitted"):
        resolve_thin_consumer_audit(audit_path, data_root=data_root, intents=intents)


def test_resolver_rejects_registry_drift(tmp_path: Path, monkeypatch) -> None:
    audit_path, data_root, _raw_path, intents = source_day_audit(tmp_path, monkeypatch)
    current = intents["consumer"]
    drifted = {
        "consumer": GraphMaterialConsumerIntent(
            reason="changed materiality reason",
            existing_streams=current.existing_streams,
            allowed_new_streams=current.allowed_new_streams,
            max_selected_streams=current.max_selected_streams,
        )
    }
    with pytest.raises(ValueError, match="stale consumer registry identity"):
        resolve_thin_consumer_audit(audit_path, data_root=data_root, intents=drifted)


def test_publisher_holds_raw_mutation_lease_through_install(tmp_path: Path, monkeypatch) -> None:
    _audit_path, data_root, raw_path, intents = source_day_audit(tmp_path, monkeypatch)
    output = tmp_path / "published-audit.json"
    mutation_lock = tmp_path / "raw-mutation.lock"
    entered_writer = threading.Event()
    release_writer = threading.Event()
    publisher_errors: list[BaseException] = []
    from ddvc.fetch import thin_consumer_audit

    original_writer = thin_consumer_audit._write_thin_consumer_audit_unlocked

    def paused_writer(*args, **kwargs):
        entered_writer.set()
        assert release_writer.wait(timeout=10)
        return original_writer(*args, **kwargs)

    monkeypatch.setattr(thin_consumer_audit, "_write_thin_consumer_audit_unlocked", paused_writer)

    def publish() -> None:
        try:
            publish_thin_consumer_audit(
                output,
                data_root=data_root,
                intents=intents,
                mutation_lock=mutation_lock,
            )
        except BaseException as error:
            publisher_errors.append(error)

    publisher = threading.Thread(target=publish)
    publisher.start()
    assert entered_writer.wait(timeout=10)
    with pytest.raises(RuntimeError, match="already running"):
        with exclusive_job(mutation_lock, job="raw market-data fetch or enrichment"):
            raw_path.write_bytes(raw_path.read_bytes() + b"forbidden mutation")
    release_writer.set()
    publisher.join(timeout=10)
    assert not publisher.is_alive()
    assert not publisher_errors

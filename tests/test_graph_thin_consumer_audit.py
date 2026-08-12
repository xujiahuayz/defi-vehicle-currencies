from __future__ import annotations

import datetime as dt
import gzip
import json
import threading
from pathlib import Path

import pytest

from ddvc.fetch.material_consumers import ExistingStreamRequirement, GraphMaterialConsumerIntent, material_consumer_registry_sha256
from ddvc.fetch.raw import installed_source_day_paths
from ddvc.fetch.thin_consumer_audit import build_thin_consumer_audit, resolve_thin_consumer_audit, validate_thin_consumer_audit_envelope
from ddvc.provenance import portable_content_sha256
from ddvc.raw_certification import RawPartition, _scan_partition, write_local_scan_certificate
from ddvc.runtime import exclusive_job
from scripts.stage_graph_acquisition import certify_installed_no_fetch


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


def test_thin_consumer_audit_is_generated_from_exact_source_authority(tmp_path: Path, monkeypatch) -> None:
    certificate_root = tmp_path / "certificates"
    certificate_root.mkdir()
    certificate = certificate_root / "uniswap_v2_local_certificate.json"
    certificate.write_text("{}\n", encoding="utf-8")
    partition = RawPartition("uniswap_v2", "swaps", "20200101")
    monkeypatch.setattr(
        "ddvc.fetch.thin_consumer_audit.required_partitions",
        lambda source, streams: (partition,),
    )

    def load_marker(path, *, data_root, partitions):
        assert path == certificate
        assert tuple(partitions) == (partition,)
        return (
            [
                {
                    "source": partition.source,
                    "stream": partition.stream,
                    "day": partition.day,
                    "rows": 7,
                }
            ],
            {
                "policy": "installed-required-raw-local-certificate-v1",
                "certificate_sha256": "a" * 64,
                "partition_ledger_sha256": "b" * 64,
                "selected_partition_count": 1,
                "selected_partition_identity_sha256": "c" * 64,
            },
        )

    monkeypatch.setattr(
        "ddvc.raw_certification.load_certified_partition_ledger",
        load_marker,
    )
    result = build_thin_consumer_audit(
        data_root=tmp_path,
        certificate_root=certificate_root,
        intents=intent("id", "transaction.id"),
    )
    assert result["authorized_graph_acquisition"] == {"streams": [], "stream_count": 0}
    assert result["consumers"][0]["new_graph_acquisition_required"] is False
    assert result["consumers"][0]["existing_stream_field_perimeter"][0]["fields"] == ["id", "transaction.id"]
    marker = result["source_release_markers"][0]
    assert marker["selected_partition_identity_sha256"] == "c" * 64
    assert marker["selected_rows"] == 7
    assert marker["certificate_file_sha256"] != marker["certificate_sha256"]


def test_thin_consumer_audit_rejects_field_outside_certified_perimeter(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="field perimeter exceeds"):
        build_thin_consumer_audit(
            data_root=tmp_path,
            certificate_root=tmp_path,
            intents=intent("id", "field_that_no_contract_certifies"),
        )


def certified_audit(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path, Path, dict[str, GraphMaterialConsumerIntent]]:
    data_root = tmp_path / "data"
    certificate_root = tmp_path / "certificates"
    certificate_root.mkdir()
    partition = RawPartition("uniswap_v2", "swaps", "20200101")
    raw_path, _metadata_path = installed_source_day_paths(
        partition.source,
        partition.stream,
        dt.datetime.strptime(partition.day, "%Y%m%d").date(),
        data_root=data_root,
    )
    raw_path.parent.mkdir(parents=True)
    row = {
        "id": "swap-1",
        "transaction": {"id": "tx-1", "blockNumber": "1", "timestamp": "1577836800"},
        "timestamp": "1577836800",
        "pair": {"id": "pair-1", "token0": {"id": "token-0"}, "token1": {"id": "token-1"}},
        "amount0In": "1",
        "amount0Out": "0",
        "amount1In": "0",
        "amount1Out": "1",
        "amountUSD": "1",
        "logIndex": "1",
    }
    with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    certificate = certificate_root / "uniswap_v2_local_certificate.json"
    write_local_scan_certificate(certificate, [_scan_partition(str(data_root), partition)], expected_partitions=[partition])
    monkeypatch.setattr("ddvc.fetch.thin_consumer_audit.required_partitions", lambda source, streams: (partition,))
    intents = intent("id", "transaction.id")
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(build_thin_consumer_audit(data_root=data_root, certificate_root=certificate_root, intents=intents), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit_path, data_root, certificate_root, raw_path, intents


def test_thin_consumer_resolver_rejects_absent_certified_raw(tmp_path: Path, monkeypatch) -> None:
    audit_path, data_root, certificate_root, raw_path, intents = certified_audit(tmp_path, monkeypatch)
    raw_path.unlink()
    with pytest.raises(ValueError, match="certified raw partition is missing"):
        certify_installed_no_fetch(thin_audit=audit_path, data_root=data_root, certificate_root=certificate_root, prelaunch=prelaunch_identity(audit_path, intents), intents=intents)


def test_thin_consumer_resolver_rejects_mutated_certified_raw(tmp_path: Path, monkeypatch) -> None:
    audit_path, data_root, certificate_root, raw_path, intents = certified_audit(tmp_path, monkeypatch)
    raw_path.write_bytes(raw_path.read_bytes() + b"mutation")
    with pytest.raises(ValueError, match="changed after scan"):
        certify_installed_no_fetch(thin_audit=audit_path, data_root=data_root, certificate_root=certificate_root, prelaunch=prelaunch_identity(audit_path, intents), intents=intents)


def test_thin_consumer_resolver_rejects_missing_certificate(tmp_path: Path, monkeypatch) -> None:
    audit_path, data_root, certificate_root, _raw_path, intents = certified_audit(tmp_path, monkeypatch)
    (certificate_root / "uniswap_v2_local_certificate.json").unlink()
    with pytest.raises(ValueError, match="local scan certificate"):
        certify_installed_no_fetch(thin_audit=audit_path, data_root=data_root, certificate_root=certificate_root, prelaunch=prelaunch_identity(audit_path, intents), intents=intents)


def test_thin_consumer_resolver_rejects_registry_drift(tmp_path: Path, monkeypatch) -> None:
    audit_path, data_root, certificate_root, _raw_path, intents = certified_audit(tmp_path, monkeypatch)
    drifted = intent("id", "transaction.id")
    current = drifted["consumer"]
    drifted["consumer"] = GraphMaterialConsumerIntent(reason="changed materiality reason", existing_streams=current.existing_streams, allowed_new_streams=current.allowed_new_streams, max_selected_streams=current.max_selected_streams)
    with pytest.raises(ValueError, match="stale consumer registry identity"):
        certify_installed_no_fetch(thin_audit=audit_path, data_root=data_root, certificate_root=certificate_root, prelaunch=prelaunch_identity(audit_path, intents), intents=drifted)


def test_thin_consumer_envelope_rejects_authorization_drift(tmp_path: Path, monkeypatch) -> None:
    audit_path, _data_root, _certificate_root, _raw_path, intents = certified_audit(tmp_path, monkeypatch)
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    payload["authorized_graph_acquisition"] = {
        "streams": ["uniswap_v3/swaps"],
        "stream_count": 1,
    }
    audit_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="stale acquisition authorization"):
        validate_thin_consumer_audit_envelope(audit_path, intents=intents)


def test_resolver_holds_raw_mutation_lease_across_source_reopen(tmp_path: Path, monkeypatch) -> None:
    audit_path, data_root, certificate_root, raw_path, intents = certified_audit(tmp_path, monkeypatch)
    mutation_lock = tmp_path / "raw-mutation.lock"
    entered_loader = threading.Event()
    release_loader = threading.Event()
    resolver_errors: list[BaseException] = []
    from ddvc import raw_certification

    original_loader = raw_certification.load_certified_partition_ledger

    def paused_loader(*args, **kwargs):
        entered_loader.set()
        assert release_loader.wait(timeout=10)
        return original_loader(*args, **kwargs)

    monkeypatch.setattr(raw_certification, "load_certified_partition_ledger", paused_loader)

    def resolve() -> None:
        try:
            resolve_thin_consumer_audit(
                audit_path,
                data_root=data_root,
                certificate_root=certificate_root,
                intents=intents,
                mutation_lock=mutation_lock,
            )
        except BaseException as error:
            resolver_errors.append(error)

    resolver = threading.Thread(target=resolve)
    resolver.start()
    assert entered_loader.wait(timeout=10)
    with pytest.raises(RuntimeError, match="already running"):
        with exclusive_job(mutation_lock, job="raw market-data fetch or enrichment"):
            raw_path.write_bytes(raw_path.read_bytes() + b"forbidden mutation")
    release_loader.set()
    resolver.join(timeout=10)
    assert not resolver.is_alive()
    assert not resolver_errors

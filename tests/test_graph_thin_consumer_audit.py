from __future__ import annotations

from pathlib import Path

import pytest

from ddvc.fetch.material_consumers import ExistingStreamRequirement, GraphMaterialConsumerIntent
from ddvc.raw_certification import RawPartition
from scripts.build_graph_thin_consumer_audit import build_audit


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


def test_thin_consumer_audit_is_generated_from_exact_source_authority(tmp_path: Path, monkeypatch) -> None:
    certificate_root = tmp_path / "certificates"
    certificate_root.mkdir()
    certificate = certificate_root / "uniswap_v2_local_certificate.json"
    certificate.write_text("{}\n", encoding="utf-8")
    partition = RawPartition("uniswap_v2", "swaps", "20200101")
    monkeypatch.setattr(
        "scripts.build_graph_thin_consumer_audit._required_partitions",
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
        "scripts.build_graph_thin_consumer_audit.load_certified_partition_ledger",
        load_marker,
    )
    result = build_audit(
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
        build_audit(
            data_root=tmp_path,
            certificate_root=tmp_path,
            intents=intent("id", "field_that_no_contract_certifies"),
        )

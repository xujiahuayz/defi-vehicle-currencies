from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path

import pytest
from datetime import datetime, timezone

from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.acquisition import source_contract_sha256, validate_freeze, validate_prelaunch_inputs, vector_alignment_failures, vector_alignment_results
from ddvc.fetch.acquisition_release import AcquisitionTask, _write_task_payloads, acquisition_cutoff, acquisition_tasks, publish_graph_acquisition, resolve_graph_acquisition
from ddvc.fetch.schemas import EntitySpec, acquisition_schema, get_schema
from ddvc.fetch.graph import iter_paginate
from ddvc.paths import REPO_ROOT


def sample_end_boundary() -> dict:
    start = int(datetime.strptime(RESEARCH_SAMPLE_END, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp())
    end = start + 86_400
    blocks = (20_000_001, 20_000_002, 20_000_003, 20_000_004)
    hashes = {block: "0x" + str(index) * 64 for index, block in enumerate(blocks, 1)}
    timestamps = dict(zip(blocks, (start - 1, start, end - 1, end), strict=True))
    evidence = []
    for index, block in enumerate(blocks):
        evidence.append(
            {
                "request": {"method": "eth_getBlockByNumber", "params": [hex(block), False]},
                "response": {
                    "number": hex(block),
                    "hash": hashes[block],
                    "parentHash": hashes[blocks[index - 1]] if index else "0x" + "0" * 64,
                    "timestamp": hex(timestamps[block]),
                },
            }
        )
    return {
        "day": RESEARCH_SAMPLE_END,
        "start_timestamp": start,
        "end_timestamp": end,
        "start_block": blocks[1],
        "start_block_timestamp": start,
        "end_block": blocks[2],
        "end_block_timestamp": end - 1,
        "before_start_block": blocks[0],
        "before_start_block_timestamp": start - 1,
        "after_end_block": blocks[3],
        "after_end_block_timestamp": end,
        "rpc_evidence": evidence,
    }


def test_source_specific_schema_contracts_are_distinct() -> None:
    assert get_schema("curve").name == "curve"
    assert get_schema("sushiswap_v3").name == "sushiswap_v3"
    assert get_schema("sushiswap_v2").name == "sushiswap_v2"


def test_frozen_acquisition_schema_materialises_fetch_modes(tmp_path) -> None:
    active = tmp_path / "active.json"
    new = tmp_path / "new.json"
    active.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source": "uniswap_v3",
                        "status": "available",
                        "entities": [
                            {
                                "stream": "swaps",
                                "entity": "swaps",
                                "proposed_selected_paths": ["id", "timestamp"],
                                "proposed_selection": "id timestamp",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    new.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source": "uniswap_v3",
                        "status": "available",
                        "entities": [
                            {
                                "entity": "pools",
                                "mode": "static_identity",
                                "proposed_selected_paths": ["id"],
                                "proposed_selection": "id",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    schema = acquisition_schema("uniswap_v3", active_manifest=active, new_manifest=new)
    assert [(entity.stream, entity.fetch_mode) for entity in schema.entities] == [
        ("swaps", "day_partitioned"),
        ("pools", "static_snapshot"),
    ]


def test_vector_alignment_counts_missing_identity_as_failure() -> None:
    owners = [{"values_path": "amounts", "identities_path": "pool.tokens", "reason": "pool_token_order"}]
    results = vector_alignment_results(
        [
            {"amounts": [1, 2], "pool": {"tokens": [{"id": "a"}, {"id": "b"}]}},
            {"amounts": [1], "pool": {"tokens": None}},
            {"amounts": None, "pool": {"tokens": []}},
        ],
        owners,
    )
    assert results["amounts~pool.tokens"] == {"compared_rows": 2, "failure_rows": 1}


def test_vector_alignment_excludes_self_comparisons_and_keeps_exact_failures() -> None:
    owners = [
        {"values_path": "tokens", "identities_path": "tokens", "reason": "identity_vector"},
        {"values_path": "amounts", "identities_path": "tokens", "reason": "pool_token_order"},
    ]
    row = {"tokens": ["a"], "amounts": [1, 2]}
    assert vector_alignment_results([row], owners) == {
        "amounts~tokens": {"compared_rows": 1, "failure_rows": 1}
    }
    assert vector_alignment_failures(row, owners) == [
        {
            "values_path": "amounts",
            "identities_path": "tokens",
            "values_length": 2,
            "identities_length": 1,
            "reason": "pool_token_order",
        }
    ]


def test_graph_paginator_yields_before_collecting_the_generation() -> None:
    class Client:
        sleep_seconds = 0

        def __init__(self) -> None:
            self.calls = 0

        def query(self, query, variables):
            self.calls += 1
            return {"swaps": ([{"id": "a"}, {"id": "b"}] if self.calls == 1 else [])}

    client = Client()
    rows = iter_paginate(client, entity="swaps", fields="id", base_where={}, page_size=2)
    assert client.calls == 0
    assert next(rows) == {"id": "a"}
    assert client.calls == 1
    assert list(rows) == [{"id": "b"}]
    assert client.calls == 2


def test_non_temporal_cutoff_uses_sample_end_block_when_no_creation_field() -> None:
    task = AcquisitionTask(
        source="uniswap_v3",
        entity=EntitySpec("pools", "pools", "id token0 { id }", fetch_mode="static_snapshot"),
        sample_end_block=123,
        provider_head_block=456,
        vector_owners=(),
    )
    assert acquisition_cutoff(task) == ({}, 123)


def test_temporal_cutoff_uses_explicit_filter_at_provider_head() -> None:
    task = AcquisitionTask(
        source="uniswap_v3",
        entity=EntitySpec("swaps", "swaps", "id timestamp", fetch_mode="day_partitioned"),
        sample_end_block=123,
        provider_head_block=456,
        vector_owners=(),
    )
    where, block = acquisition_cutoff(task)
    assert where == {"timestamp_lte": str(int(datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc).timestamp()))}
    assert block == 456


def test_live_manifests_materialise_exactly_93_tasks() -> None:
    tasks = acquisition_tasks(
        active_manifest=REPO_ROOT / "docs" / "graph-field-admission.json",
        new_manifest=REPO_ROOT / "docs" / "graph-new-stream-field-admission.json",
        sample_end_blocks={name: 30_000_000 for name in ("balancer", "curve", "sushiswap_v2", "sushiswap_v3", "uniswap_v2", "uniswap_v3", "uniswap_v4")},
    )
    assert len(tasks) == 93


def test_staging_quarantines_vector_mismatch_before_clean_payload(tmp_path: Path, monkeypatch) -> None:
    task = AcquisitionTask(
        source="uniswap_v3",
        entity=EntitySpec("snapshots", "snapshots", "id timestamp amounts tokens", fetch_mode="global_historical"),
        sample_end_block=123,
        provider_head_block=456,
        vector_owners=({"values_path": "amounts", "identities_path": "tokens", "reason": "pool_token_order"},),
    )
    monkeypatch.setattr("ddvc.fetch.acquisition_release.graph_keys", lambda: ["key"])
    monkeypatch.setattr("ddvc.fetch.acquisition_release.GraphClient", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        "ddvc.fetch.acquisition_release.iter_graph_entity_rows",
        lambda *args, **kwargs: [
            {"id": "clean", "amounts": [1], "tokens": ["a"]},
            {"id": "bad", "amounts": [1, 2], "tokens": ["a"]},
        ],
    )
    clean = tmp_path / "clean.jsonl.gz"
    quarantine = tmp_path / "quarantine.jsonl.gz"
    assert _write_task_payloads(task, clean_path=clean, quarantine_path=quarantine, max_pages_per_chunk=1) == {"clean_rows": 1, "quarantine_rows": 1}
    with gzip.open(clean, "rt", encoding="utf-8") as handle:
        assert [json.loads(line)["id"] for line in handle] == ["clean"]
    with gzip.open(quarantine, "rt", encoding="utf-8") as handle:
        evidence = json.loads(next(handle))
    assert evidence["row"]["id"] == "bad"
    assert evidence["alignment_failures"][0]["identities_length"] == 1


def test_failed_selected_stream_stage_never_publishes_pointer(tmp_path: Path, monkeypatch) -> None:
    task = AcquisitionTask(
        source="uniswap_v3",
        entity=EntitySpec("snapshots", "snapshots", "id", fetch_mode="global_historical"),
        sample_end_block=123,
        provider_head_block=456,
        vector_owners=(),
    )
    monkeypatch.setattr("ddvc.fetch.acquisition_release._write_task_payloads", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider failed")))
    pointer = tmp_path / "current.json"
    with pytest.raises(RuntimeError, match="provider failed"):
        publish_graph_acquisition(
            pointer_path=pointer,
            tasks=(task,),
            inputs=[],
            code_sources=[],
            selection_reason="exact target replay lacks one material state stream",
        )
    assert not pointer.exists()


def test_selected_canary_only_generation_publishes_marker_last_and_reopens(tmp_path: Path) -> None:
    tasks = tuple(
        AcquisitionTask(
            source="uniswap_v3",
            entity=EntitySpec(f"validation_{index}", "validations", "id", fetch_mode="head_validation_only"),
            sample_end_block=123,
            provider_head_block=456,
            vector_owners=(),
        )
        for index in range(2)
    )
    pointer = tmp_path / "current.json"
    publish_graph_acquisition(pointer_path=pointer, tasks=tasks, inputs=[], code_sources=[], selection_reason="bounded canary-only consumer check")
    assert pointer.is_file()
    assert len(resolve_graph_acquisition(pointer)["streams"]) == 2


def test_acquisition_requires_a_selected_stream_and_materiality_reason(tmp_path: Path) -> None:
    task = AcquisitionTask(
        source="uniswap_v3",
        entity=EntitySpec("validation", "validations", "id", fetch_mode="head_validation_only"),
        sample_end_block=123,
        provider_head_block=456,
        vector_owners=(),
    )
    with pytest.raises(ValueError, match="at least one selected task"):
        publish_graph_acquisition(
            pointer_path=tmp_path / "none.json",
            tasks=(),
            inputs=[],
            code_sources=[],
            selection_reason="material field",
        )
    with pytest.raises(ValueError, match="named materiality reason"):
        publish_graph_acquisition(
            pointer_path=tmp_path / "unnamed.json",
            tasks=(task,),
            inputs=[],
            code_sources=[],
            selection_reason="",
        )


def test_freeze_validation_fails_on_manifest_drift(tmp_path) -> None:
    inventory = tmp_path / "inventory.json"
    active = tmp_path / "active.json"
    new = tmp_path / "new.json"
    for path, value in ((inventory, "inventory"), (active, "active"), (new, "new")):
        path.write_text(value, encoding="utf-8")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    freeze = {
        "schema_inventory_sha256": digest(inventory),
        "active_manifest_sha256": digest(active),
        "new_manifest_sha256": digest(new),
        "research_sample_end": RESEARCH_SAMPLE_END,
        "sample_end_boundary": sample_end_boundary(),
        "sources": [
            {
                "source": "uniswap_v3",
                "head_block": 30_000_000,
                "sample_end_block": 20_000_003,
                "source_contract_sha256": source_contract_sha256("uniswap_v3"),
            }
        ],
    }
    assert validate_freeze(
        freeze,
        inventory=inventory,
        active_manifest=active,
        new_manifest=new,
        expected_sources={"uniswap_v3"},
    ) == {"uniswap_v3": 20_000_003}
    active.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="stale active_manifest_sha256"):
        validate_freeze(
            freeze,
            inventory=inventory,
            active_manifest=active,
            new_manifest=new,
            expected_sources={"uniswap_v3"},
        )


def test_prelaunch_recomputes_hashes_and_accepts_explicit_provider_quarantine(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    active = tmp_path / "active.json"
    new = tmp_path / "new.json"
    for path, value in ((inventory, "inventory"), (active, "active"), (new, "new")):
        path.write_text(value, encoding="utf-8")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(
        json.dumps(
            {
                "schema_inventory_sha256": digest(inventory),
                "active_manifest_sha256": digest(active),
                "new_manifest_sha256": digest(new),
                "research_sample_end": RESEARCH_SAMPLE_END,
                "sample_end_boundary": sample_end_boundary(),
                "sources": [
                    {
                        "source": "uniswap_v3",
                        "head_block": 30_000_000,
                        "sample_end_block": 20_000_003,
                        "source_contract_sha256": source_contract_sha256("uniswap_v3"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.jsonl.gz"
    evidence.write_bytes(b"evidence")
    canary_path = tmp_path / "canary.json"
    canary_path.write_text(
        json.dumps(
            {
                "freeze_sha256": digest(freeze_path),
                "schema_inventory_sha256": digest(inventory),
                "active_manifest_sha256": digest(active),
                "new_manifest_sha256": digest(new),
                "pre_quarantine_evidence": {"path": str(evidence), "sha256": digest(evidence)},
                "sources": [
                    {
                        "source": "uniswap_v3",
                        "streams": [
                            {
                                "stream": "tokens",
                                "quality_action": "provider_archive_unavailable_quarantined",
                                "summary": {"failed_samples": 2, "alignment_failure_rows": 0},
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    current_canary = tmp_path / "current-canary.json"
    root_population = tmp_path / "root-population.json"
    shared_identity = {
        "freeze_sha256": digest(freeze_path),
        "schema_inventory_sha256": digest(inventory),
        "active_manifest_sha256": digest(active),
        "new_manifest_sha256": digest(new),
    }
    current_canary.write_text(json.dumps(shared_identity), encoding="utf-8")
    root_population.write_text(json.dumps({**shared_identity, "summary": {"errors": 0}}), encoding="utf-8")
    forecast = tmp_path / "forecast.json"
    forecast.write_text(
        json.dumps(
            {
                "inputs": {
                    "freeze_sha256": digest(freeze_path),
                    "final_canary_sha256": digest(canary_path),
                    "current_canary_sha256": digest(current_canary),
                    "root_population_sha256": digest(root_population),
                },
                "launch_decision": "inventory_validated_consumer_selection_required",
            }
        ),
        encoding="utf-8",
    )
    assert validate_prelaunch_inputs(
        freeze_path=freeze_path,
        inventory_path=inventory,
        active_manifest_path=active,
        new_manifest_path=new,
        canary_path=canary_path,
        canary_evidence_path=evidence,
        current_canary_path=current_canary,
        root_population_path=root_population,
        forecast_path=forecast,
    )["stream_count"] == 1
    active.write_text("drift", encoding="utf-8")
    with pytest.raises(ValueError, match="stale active_manifest_sha256"):
        validate_prelaunch_inputs(
            freeze_path=freeze_path,
            inventory_path=inventory,
            active_manifest_path=active,
            new_manifest_path=new,
            canary_path=canary_path,
            canary_evidence_path=evidence,
            current_canary_path=current_canary,
            root_population_path=root_population,
            forecast_path=forecast,
        )

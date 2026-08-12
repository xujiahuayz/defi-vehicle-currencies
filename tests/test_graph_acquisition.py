from __future__ import annotations

import hashlib
import gzip
import json
import threading
from pathlib import Path

import pytest
from datetime import datetime, timezone

from ddvc.calendar import RESEARCH_SAMPLE_END
from ddvc.fetch.acquisition import _validate_canary_evidence, source_contract_sha256, validate_freeze, validate_prelaunch_inputs, vector_alignment_failures, vector_alignment_results
from ddvc.fetch.acquisition_release import AcquisitionTask, _install_content_addressed, _write_task_payloads, acquisition_cutoff, acquisition_tasks, publish_graph_acquisition, resolve_graph_acquisition
from ddvc.fetch.material_consumers import GRAPH_MATERIAL_CONSUMER_INTENTS, ExistingStreamRequirement, GraphMaterialConsumerIntent, UNSUPPORTED_OWNERSHIP_STREAMS, graph_acquisition_authorization, material_consumer_registry_sha256, validate_material_consumer_registry, validate_material_consumer_selection
from ddvc.fetch.schemas import EntitySpec, acquisition_schema, get_schema
from ddvc.fetch.graph import iter_paginate
from ddvc.paths import REPO_ROOT
from ddvc.runtime import exclusive_job
from scripts import build_graph_acquisition_forecast


def allow_intent(*streams: tuple[str, str]) -> dict[str, GraphMaterialConsumerIntent]:
    return {
        "test_consumer": GraphMaterialConsumerIntent(
            reason="test-only material missing stream",
            existing_streams=(
                ExistingStreamRequirement("uniswap_v3", "swaps", ("id",)),
            ),
            allowed_new_streams=frozenset(streams),
            max_selected_streams=len(streams),
        )
    }


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


def test_forecast_holds_raw_mutation_lease_through_publication(tmp_path: Path, monkeypatch) -> None:
    mutation_lock = tmp_path / "raw-mutation.lock"
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def paused_build(_args):
        entered.set()
        assert release.wait(timeout=10)
        return 0

    monkeypatch.setattr(
        build_graph_acquisition_forecast,
        "RAW_MARKET_DATA_LOCK",
        mutation_lock,
    )
    monkeypatch.setattr(
        build_graph_acquisition_forecast,
        "_parse_args",
        lambda: object(),
    )
    monkeypatch.setattr(
        build_graph_acquisition_forecast,
        "_build_and_publish_forecast",
        paused_build,
    )

    def build() -> None:
        try:
            build_graph_acquisition_forecast.main()
        except BaseException as error:
            errors.append(error)

    builder = threading.Thread(target=build)
    builder.start()
    assert entered.wait(timeout=10)
    with pytest.raises(RuntimeError, match="already running"):
        with exclusive_job(mutation_lock, job="synthetic raw writer"):
            raise AssertionError("raw writer entered during forecast publication")
    release.set()
    builder.join(timeout=10)
    assert not builder.is_alive()
    assert not errors


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
    assert results["amounts~pool.tokens"] == {"compared_rows": 3, "failure_rows": 2}


def test_vector_alignment_validates_self_identity_vectors_and_keeps_exact_failures() -> None:
    owners = [
        {"values_path": "tokens", "identities_path": "tokens", "reason": "identity_vector"},
        {"values_path": "amounts", "identities_path": "tokens", "reason": "pool_token_order"},
    ]
    row = {"tokens": ["a"], "amounts": [1, 2]}
    assert vector_alignment_results([row], owners) == {
        "tokens~tokens": {"compared_rows": 1, "failure_rows": 0},
        "amounts~tokens": {"compared_rows": 1, "failure_rows": 1}
    }
    assert vector_alignment_failures(row, owners) == [
        {
            "values_path": "amounts",
            "identities_path": "tokens",
            "values_length": 2,
            "identities_length": 1,
            "reason": "pool_token_order",
            "failure": "length_mismatch",
        }
    ]


@pytest.mark.parametrize(
    ("row", "failure"),
    [
        ({"amounts": None, "tokens": ["a"]}, "missing_or_empty_values"),
        ({"amounts": [], "tokens": []}, "missing_or_empty_values"),
        ({"amounts": [None], "tokens": ["a"]}, "malformed_values"),
        ({"amounts": ["NaN"], "tokens": ["a"]}, "malformed_values"),
        ({"amounts": ["not-a-number"], "tokens": ["a"]}, "malformed_values"),
        ({"amounts": ["1"], "tokens": [{"id": None}]}, "malformed_identities"),
        ({"amounts": ["1"], "tokens": []}, "missing_or_empty_identities"),
    ],
)
def test_vector_alignment_rejects_missing_empty_or_malformed_items(row, failure) -> None:
    owners = [{"values_path": "amounts", "identities_path": "tokens", "reason": "pool_token_order"}]
    assert vector_alignment_failures(row, owners)[0]["failure"] == failure


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
        canary_path=REPO_ROOT / "docs" / "graph-query-canaries-final.json",
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
    monkeypatch.setattr(
        "ddvc.fetch.material_consumers.GRAPH_MATERIAL_CONSUMER_INTENTS",
        allow_intent(("uniswap_v3", "snapshots")),
    )
    monkeypatch.setattr("ddvc.fetch.acquisition_release._write_task_payloads", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider failed")))
    pointer = tmp_path / "current.json"
    with pytest.raises(RuntimeError, match="provider failed"):
        publish_graph_acquisition(
            pointer_path=pointer,
            tasks=(task,),
            inputs=[],
            code_sources=[],
            material_consumer="test_consumer",
        )
    assert not pointer.exists()
    assert not list((tmp_path / "payloads").rglob("*.jsonl.gz"))


def test_selected_canary_only_generation_publishes_marker_last_and_reopens(tmp_path: Path, monkeypatch) -> None:
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
    monkeypatch.setattr(
        "ddvc.fetch.material_consumers.GRAPH_MATERIAL_CONSUMER_INTENTS",
        allow_intent(*((task.source, task.entity.stream) for task in tasks)),
    )
    pointer = tmp_path / "current.json"
    publish_graph_acquisition(pointer_path=pointer, tasks=tasks, inputs=[], code_sources=[], material_consumer="test_consumer")
    assert pointer.is_file()
    assert len(resolve_graph_acquisition(pointer)["streams"]) == 2


def test_acquisition_requires_a_selected_stream_and_closed_consumer(tmp_path: Path, monkeypatch) -> None:
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
            material_consumer="test_consumer",
        )
    monkeypatch.setattr(
        "ddvc.fetch.material_consumers.GRAPH_MATERIAL_CONSUMER_INTENTS",
        allow_intent(("uniswap_v3", "validation")),
    )
    with pytest.raises(ValueError, match="unknown Graph material consumer"):
        publish_graph_acquisition(
            pointer_path=tmp_path / "unnamed.json",
            tasks=(task,),
            inputs=[],
            code_sources=[],
            material_consumer="not_registered",
        )


def test_material_consumer_registry_rejects_broad_and_ownership_scope() -> None:
    all_streams = {
        (source["source"], stream["stream"])
        for source in json.loads((REPO_ROOT / "docs" / "graph-query-canaries-final.json").read_text())["sources"]
        for stream in source["streams"]
    }
    with pytest.raises(ValueError, match="exceeds the named consumer allowlist"):
        validate_material_consumer_selection(
            "v2_end_of_day_deposited_capital",
            all_streams.difference(UNSUPPORTED_OWNERSHIP_STREAMS),
        )
    forbidden = next(iter(UNSUPPORTED_OWNERSHIP_STREAMS))
    invalid = allow_intent(forbidden)
    with pytest.raises(ValueError, match="unsupported ownership"):
        validate_material_consumer_registry(invalid)


def test_exact_quote_state_consumer_requires_v3_swap_replay_state() -> None:
    requirements = {
        (requirement.source, requirement.stream): set(requirement.fields)
        for requirement in GRAPH_MATERIAL_CONSUMER_INTENTS[
            "exact_transaction_target_and_quote_state_replay"
        ].existing_streams
    }
    assert {"sqrtPriceX96", "tick"}.issubset(requirements[("uniswap_v3", "swaps")])
    assert {"sqrtPriceX96", "tick"}.isdisjoint(requirements[("uniswap_v4", "swaps")])


def test_publisher_independently_rejects_scope_outside_named_consumer(tmp_path: Path, monkeypatch) -> None:
    allowed = AcquisitionTask(
        source="uniswap_v3",
        entity=EntitySpec("allowed", "allowed", "id", fetch_mode="head_validation_only"),
        sample_end_block=123,
        provider_head_block=456,
        vector_owners=(),
    )
    extra = AcquisitionTask(
        source="uniswap_v3",
        entity=EntitySpec("extra", "extra", "id", fetch_mode="head_validation_only"),
        sample_end_block=123,
        provider_head_block=456,
        vector_owners=(),
    )
    monkeypatch.setattr(
        "ddvc.fetch.material_consumers.GRAPH_MATERIAL_CONSUMER_INTENTS",
        allow_intent(("uniswap_v3", "allowed")),
    )
    with pytest.raises(ValueError, match="exceeds the named consumer allowlist"):
        publish_graph_acquisition(
            pointer_path=tmp_path / "current.json",
            tasks=(allowed, extra),
            inputs=[],
            code_sources=[],
            material_consumer="test_consumer",
        )
    assert not (tmp_path / "current.json").exists()


def test_content_address_install_deduplicates_identical_staged_names(tmp_path: Path) -> None:
    first = tmp_path / ".candidate.jsonl.gz.first.tmp"
    second = tmp_path / ".candidate.jsonl.gz.second.tmp"
    first.write_bytes(b"identical")
    second.write_bytes(b"identical")
    target1, created1 = _install_content_addressed(first, tmp_path / "payloads", semantic_suffix=".jsonl.gz")
    target2, created2 = _install_content_addressed(second, tmp_path / "payloads", semantic_suffix=".jsonl.gz")
    assert target1 == target2
    assert target1.name == f"{hashlib.sha256(b'identical').hexdigest()}.jsonl.gz"
    assert created1 and not created2
    assert list((tmp_path / "payloads").iterdir()) == [target1]


def test_later_stage_failure_removes_all_transaction_staging_and_payloads(tmp_path: Path, monkeypatch) -> None:
    tasks = tuple(
        AcquisitionTask(
            source="uniswap_v3",
            entity=EntitySpec(name, name, "id", fetch_mode="global_historical"),
            sample_end_block=123,
            provider_head_block=456,
            vector_owners=(),
        )
        for name in ("first", "second")
    )
    monkeypatch.setattr(
        "ddvc.fetch.material_consumers.GRAPH_MATERIAL_CONSUMER_INTENTS",
        allow_intent(*((task.source, task.entity.stream) for task in tasks)),
    )

    def write_then_fail(task, *, clean_path, quarantine_path, max_pages_per_chunk):
        if task.entity.stream == "second":
            raise RuntimeError("later failure")
        clean_path.write_bytes(b"clean")
        quarantine_path.write_bytes(b"quarantine")
        return {"clean_rows": 1, "quarantine_rows": 0}

    monkeypatch.setattr("ddvc.fetch.acquisition_release._write_task_payloads", write_then_fail)
    pointer = tmp_path / "current.json"
    with pytest.raises(RuntimeError, match="later failure"):
        publish_graph_acquisition(
            pointer_path=pointer,
            tasks=tasks,
            inputs=[],
            code_sources=[],
            material_consumer="test_consumer",
            workers=1,
        )
    assert not pointer.exists()
    assert not list(tmp_path.glob(".graph-acquisition-stage-*"))
    assert not list((tmp_path / "payloads").rglob("*.jsonl.gz"))


def test_pointer_publication_failure_restores_pointer_and_removes_new_generation(tmp_path: Path, monkeypatch) -> None:
    task = AcquisitionTask(
        source="uniswap_v3",
        entity=EntitySpec("allowed", "allowed", "id", fetch_mode="head_validation_only"),
        sample_end_block=123,
        provider_head_block=456,
        vector_owners=(),
    )
    monkeypatch.setattr(
        "ddvc.fetch.material_consumers.GRAPH_MATERIAL_CONSUMER_INTENTS",
        allow_intent((task.source, task.entity.stream)),
    )
    pointer = tmp_path / "current.json"
    from ddvc.artifact_release import publish_artifact_release as real_publish

    def fail_pointer(**kwargs):
        def writer(path, payload):
            path.write_text(json.dumps(payload), encoding="utf-8")
            raise RuntimeError("pointer publication")

        return real_publish(**kwargs, write_pointer=writer)

    monkeypatch.setattr(
        "ddvc.fetch.acquisition_release.publish_artifact_release",
        fail_pointer,
    )
    with pytest.raises(RuntimeError, match="pointer publication"):
        publish_graph_acquisition(
            pointer_path=pointer,
            tasks=(task,),
            inputs=[],
            code_sources=[],
            material_consumer="test_consumer",
        )
    assert not pointer.exists()
    assert not list((tmp_path / "generations").glob("*"))
    assert not list(tmp_path.glob(".graph-acquisition-stage-*"))


def test_acquisition_tasks_require_exact_canary_identity_and_action(tmp_path: Path) -> None:
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
        json.dumps({"sources": [{"source": "uniswap_v3", "status": "available", "entities": []}]}),
        encoding="utf-8",
    )
    canary = tmp_path / "canary.json"
    canary.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source": "uniswap_v3",
                        "streams": [{"stream": "different", "quality_action": "admit"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="perimeters differ"):
        acquisition_tasks(
            active_manifest=active,
            new_manifest=new,
            sample_end_blocks={"uniswap_v3": 123},
            canary_path=canary,
        )
    canary.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source": "uniswap_v3",
                        "streams": [{"stream": "swaps", "quality_action": None}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid quality actions"):
        acquisition_tasks(
            active_manifest=active,
            new_manifest=new,
            sample_end_blocks={"uniswap_v3": 123},
            canary_path=canary,
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
    with gzip.open(evidence, "wt", encoding="utf-8"):
        pass
    canary_path = tmp_path / "canary.json"
    canary_path.write_text(
        json.dumps(
            {
                "freeze_sha256": digest(freeze_path),
                "schema_inventory_sha256": digest(inventory),
                "active_manifest_sha256": digest(active),
                "new_manifest_sha256": digest(new),
                    "quarantine_failure_evidence": {
                        "path": str(evidence.resolve()),
                        "sha256": digest(evidence),
                        "rows": 0,
                        "sampled_rows": 0,
                },
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
    current_evidence = tmp_path / "current-evidence.jsonl.gz"
    with gzip.open(current_evidence, "wt", encoding="utf-8"):
        pass
    root_population = tmp_path / "root-population.json"
    shared_identity = {
        "freeze_sha256": digest(freeze_path),
        "schema_inventory_sha256": digest(inventory),
        "active_manifest_sha256": digest(active),
        "new_manifest_sha256": digest(new),
    }
    current_canary.write_text(
        json.dumps(
            {
                **shared_identity,
                    "quarantine_failure_evidence": {
                        "path": str(current_evidence.resolve()),
                        "sha256": digest(current_evidence),
                        "rows": 0,
                        "sampled_rows": 0,
                },
                "sources": [],
            }
        ),
        encoding="utf-8",
    )
    root_population.write_text(json.dumps({**shared_identity, "summary": {"errors": 0}}), encoding="utf-8")
    thin_audit = tmp_path / "thin-audit.json"
    thin_audit.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "kind": "graph_thin_consumer_materiality_audit",
                "research_sample_end": RESEARCH_SAMPLE_END,
                "consumer_registry_sha256": material_consumer_registry_sha256(),
                "authorized_graph_acquisition": graph_acquisition_authorization(),
            }
        ),
        encoding="utf-8",
    )
    forecast = tmp_path / "forecast.json"
    forecast.write_text(
        json.dumps(
            {
                "inputs": {
                    "freeze_sha256": digest(freeze_path),
                    "final_canary_sha256": digest(canary_path),
                    "current_canary_sha256": digest(current_canary),
                    "root_population_sha256": digest(root_population),
                    "thin_consumer_audit_sha256": digest(thin_audit),
                    "consumer_registry_sha256": material_consumer_registry_sha256(),
                },
                "forecast": {
                    "authorized_fetch": {
                        **graph_acquisition_authorization(),
                        "bytes": 0,
                        "graph_calls": 0,
                    }
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
        current_canary_evidence_path=current_evidence,
        root_population_path=root_population,
        forecast_path=forecast,
        thin_audit_path=thin_audit,
    )["stream_count"] == 1
    forecast_payload = json.loads(forecast.read_text(encoding="utf-8"))
    forecast_payload["forecast"]["authorized_fetch"]["streams"] = ["uniswap_v3/swaps"]
    forecast.write_text(json.dumps(forecast_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="stale acquisition authorization"):
        validate_prelaunch_inputs(
            freeze_path=freeze_path,
            inventory_path=inventory,
            active_manifest_path=active,
            new_manifest_path=new,
            canary_path=canary_path,
            canary_evidence_path=evidence,
            current_canary_path=current_canary,
            current_canary_evidence_path=current_evidence,
            root_population_path=root_population,
            forecast_path=forecast,
            thin_audit_path=thin_audit,
        )
    forecast_payload["forecast"]["authorized_fetch"] = {
        **graph_acquisition_authorization(),
        "bytes": 0,
        "graph_calls": 0,
    }
    forecast.write_text(json.dumps(forecast_payload), encoding="utf-8")
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
            current_canary_evidence_path=current_evidence,
            root_population_path=root_population,
            forecast_path=forecast,
            thin_audit_path=thin_audit,
        )


def test_canary_failure_evidence_recomputes_the_recorded_vector_failure(tmp_path: Path) -> None:
    evidence = tmp_path / "failures.jsonl.gz"
    owner = {
        "values_path": "amounts",
        "identities_path": "tokens",
        "reason": "ordered amount vector",
    }
    row = {"amounts": [1, 2], "tokens": [{"id": "token"}]}
    failure = vector_alignment_failures(row, [owner])
    record = {
        "sample_key": "source/stream/head/100",
        "source": "source",
        "stream": "stream",
        "epoch": "head",
        "requested_rows": 100,
        "row_index": 3,
        "row": row,
        "alignment_failures": failure,
    }
    with gzip.open(evidence, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    canary = {
        "quarantine_failure_evidence": {
            "path": str(evidence.resolve()),
            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "rows": 1,
            "sampled_rows": 4,
        },
        "sources": [
            {
                "source": "source",
                "streams": [
                    {
                        "stream": "stream",
                        "vector_owners": [owner],
                        "samples": [
                            {
                                "status": "ok",
                                "epoch": "head",
                                "requested_rows": 100,
                                "returned_rows": 4,
                                "alignment_failure_row_indices": [3],
                                "quarantine_failure_evidence_key": "source/stream/head/100",
                                "quarantine_failure_evidence_rows": 1,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    _validate_canary_evidence(canary, evidence, label="test")
    record["row_index"] = 2
    with gzip.open(evidence, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    canary["quarantine_failure_evidence"]["sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="non-failure row"):
        _validate_canary_evidence(canary, evidence, label="test")
    record["row_index"] = 3
    record["alignment_failures"] = [{"failure": "fabricated"}]
    with gzip.open(evidence, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    canary["quarantine_failure_evidence"]["sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="non-failure row"):
        _validate_canary_evidence(canary, evidence, label="test")

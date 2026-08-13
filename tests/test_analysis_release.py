from __future__ import annotations

import json
import shutil
import tempfile
import threading
from pathlib import Path

import pandas as pd
import pytest

import ddvc.analysis_release as analysis_release
import ddvc.artifact_release as artifact_release
import ddvc.endpoint_candidate_composition_release as endpoint_release_module
from ddvc.analysis_release import (
    ANALYSIS_RELEASE_FILENAMES,
    ANALYSIS_RELEASE_POINTER_KIND,
    ANALYSIS_RELEASE_POINTER_SCHEMA_VERSION,
    publish_analysis_release,
    resolve_analysis_release,
    resolve_current_analysis_release,
)
from ddvc.artifact_release import file_sha256, resolve_artifact_release
from ddvc.asset_types import NATIVE, STABLE
from ddvc.endpoint_candidate_composition import (
    ROUTE_INPUT_COLUMNS,
    endpoint_candidate_composition_for_day,
)
from ddvc.endpoint_candidate_composition_release import (
    ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_RELATIVE,
    current_endpoint_candidate_composition_release,
    publish_endpoint_candidate_composition_release,
)
from ddvc.model_registry import canonical_hash, generation_id
from ddvc.paths import REPO_ROOT
from ddvc.provenance import sidecar_path, stamp
from ddvc.runtime import atomic_output


SRC = "0x1111111111111111111111111111111111111111"
TGT = "0x2222222222222222222222222222222222222222"
WETH = next(address for address, symbol in NATIVE.items() if symbol == "WETH")
USDC = next(address for address, symbol in STABLE.items() if symbol == "USDC")


class _BindingValidator:
    def __init__(self, paths: list[Path]):
        self.paths = paths

    def __call__(self, _path: Path) -> None:
        return None

    def validate_prepared_stamp(self, prepared: bytes) -> bytes:
        record = json.loads(prepared)
        record["released_input_bindings"] = [
            {"path": str(path.resolve()), "sha256": file_sha256(path)}
            for path in self.paths
        ]
        return (json.dumps(record, indent=1, sort_keys=True) + "\n").encode()


def _workspace():
    return tempfile.TemporaryDirectory(prefix="d3-release-test-", dir=REPO_ROOT)


def _cleanup_manifest_mirror(directory: Path) -> None:
    relative = directory.relative_to(REPO_ROOT)
    shutil.rmtree(REPO_ROOT / "data" / "manifests" / relative, ignore_errors=True)


def _write_specification(path: Path, inputs: list[str]) -> None:
    payload = {
        "schema_version": 1,
        "stage": "design_seed",
        "claims": [
            {"id": "lead", "status": "candidate_primary", "execution_gate": "open", "inputs": inputs},
            {
                "id": "companion",
                "status": "candidate_companion",
                "execution_gate": "blocked_external_reference_variance",
                "inputs": ["data/raw/blocked-provider.json"],
            },
            {"id": "withheld", "status": "withheld"},
            {"id": "support", "status": "supporting"},
            {"id": "old", "status": "retired", "inputs": ["data/raw/ignored.json"]},
        ],
    }
    payload["lock_hash"] = canonical_hash(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _released_inputs(directory: Path) -> tuple[Path, Path]:
    first = directory / "first.parquet"
    second = directory / "second.json"
    pd.DataFrame({"day": ["20260101", "20260102"], "value": [1.0, 2.0]}).to_parquet(first, index=False)
    second.write_text(json.dumps({"status": "pass", "rows": 2}), encoding="utf-8")
    for path in (first, second):
        stamp(path, code_sources=["tests/test_analysis_release.py"], inputs=[])
    return first, second


def _publish_endpoint_release(directory: Path):
    upstream = [directory / "route-a.bin", directory / "route-b.bin"]
    for index, path in enumerate(upstream):
        path.write_bytes(f"certified-route-{index}".encode())
    frame = pd.DataFrame(
        [
            {
                "tx_hash": transaction,
                "component_id": 0,
                "route_class": "coherent",
                "source": source,
                "token_in": token_in,
                "token_out": token_out,
                "amount_usd": 100.0,
                "log_index": log_index,
                "tin_role": "source",
                "tout_role": "sink",
                "timestamp_utc": 1_704_153_600,
            }
            for transaction, source, token_in, token_out, log_index in (
                ("native", "uniswap_v2", SRC, WETH, 0),
                ("native", "uniswap_v2", WETH, TGT, 1),
                ("stable", "sushiswap_v2", SRC, USDC, 2),
                ("stable", "sushiswap_v2", USDC, TGT, 3),
            )
        ]
    )[ROUTE_INPUT_COLUMNS]
    tables = endpoint_candidate_composition_for_day(frame, "20240102")
    pointer = directory / ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_RELATIVE
    release = publish_endpoint_candidate_composition_release(
        writers={
            name: (
                lambda target, table=getattr(tables, name): table.to_parquet(
                    target, index=False
                )
            )
            for name in ("choices", "choice_audit", "pair_support", "exclusions")
        },
        row_counts={
            name: len(getattr(tables, name))
            for name in ("choices", "choice_audit", "pair_support", "exclusions")
        },
        code_sources=["tests/test_analysis_release.py"],
        inputs=[upstream[0]],
        notes="real typed endpoint release for D3 fast-resolution tests",
        preinstall_validator=_BindingValidator(upstream),
        pointer_path=pointer,
    )
    return release, upstream


def _publish_typed_analysis_release(directory: Path):
    endpoint, upstream = _publish_endpoint_release(directory)
    specification = directory / "specification.json"
    _write_specification(
        specification, [ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_RELATIVE]
    )
    pointer = directory / "analysis" / "current.json"
    release = publish_analysis_release(
        root=directory,
        specification_path=specification.relative_to(directory),
        pointer_path=pointer.relative_to(directory),
    )
    return endpoint, upstream, specification, pointer, release


def test_d3_release_reopens_exact_union_and_publishes_pointer_last() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, second = _released_inputs(directory)
            specification = directory / "specification.json"
            inputs = [first.relative_to(REPO_ROOT).as_posix(), second.relative_to(REPO_ROOT).as_posix()]
            _write_specification(specification, inputs)
            pointer = directory / "release" / "current.json"
            release = publish_analysis_release(
                specification_path=specification.relative_to(REPO_ROOT),
                pointer_path=pointer.relative_to(REPO_ROOT),
            )
            assert release.pointer_path == pointer
            assert release.certificate["claim_input_count"] == 2
            assert release.certificate["executable_claim_ids"] == ["lead"]
            assert release.certificate["excluded_claim_count"] == 4
            assert release.certificate["excluded_claims"] == [
                {
                    "claim_id": "companion",
                    "status": "candidate_companion",
                    "execution_gate": "blocked_external_reference_variance",
                    "exclusion_reason": "execution_gate_not_open",
                },
                {
                    "claim_id": "old",
                    "status": "retired",
                    "execution_gate": None,
                    "exclusion_reason": "status_not_executable_at_design_seed",
                },
                {
                    "claim_id": "support",
                    "status": "supporting",
                    "execution_gate": None,
                    "exclusion_reason": "status_not_executable_at_design_seed",
                },
                {
                    "claim_id": "withheld",
                    "status": "withheld",
                    "execution_gate": None,
                    "exclusion_reason": "status_not_executable_at_design_seed",
                },
            ]
            assert release.certificate["generation"] == generation_id(release.certificate)
            assert [record["path"] for record in release.certificate["claim_inputs"]] == sorted(inputs)
            assert all(record["provenance_sha256"] for record in release.certificate["claim_inputs"])
            reopened = resolve_current_analysis_release(pointer_path=pointer.relative_to(REPO_ROOT))
            assert reopened.generation == release.generation
            direct = resolve_analysis_release(certificate_path=release.certificate_path.relative_to(REPO_ROOT))
            assert direct.certificate == release.certificate
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_release_fails_only_when_an_execution_open_claim_is_incomplete() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            specification = directory / "specification.json"
            _write_specification(specification, [])
            with pytest.raises(ValueError, match="execution-open claim has no analysis inputs: lead"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_rejects_a_stage_claim_with_no_explicit_execution_gate() -> None:
    payload = {
        "schema_version": 1,
        "stage": "design_seed",
        "claims": [{"id": "lead", "status": "candidate_primary", "inputs": ["data/processed/input.parquet"]}],
    }
    with pytest.raises(ValueError, match="must explicitly declare its execution gate: lead"):
        analysis_release._active_claim_input_perimeter(payload)


def test_real_specification_excludes_closed_and_non_stage_claims_from_d3() -> None:
    specification = json.loads((REPO_ROOT / "docs/specification-lock.json").read_text(encoding="utf-8"))
    assert analysis_release._validate_specification_identity(specification) == specification["lock_hash"]
    stage_statuses = {
        "candidate_primary",
        "candidate_foundation",
        "candidate_mechanism",
        "candidate_companion",
    }
    stage_claims = [claim for claim in specification["claims"] if claim["status"] in stage_statuses]
    assert all(claim.get("execution_gate") for claim in stage_claims)
    perimeter = analysis_release._active_claim_input_perimeter(specification)
    expected_executable = tuple(
        sorted(claim["id"] for claim in stage_claims if claim["execution_gate"] == "open")
    )
    assert perimeter.executable_claim_ids == expected_executable
    assert {
        "direct_cost_dominance",
        "routing_maturation_rival",
        "vehicle_transition",
    }.issubset(perimeter.executable_claim_ids)
    expected_excluded = {
        claim["id"]: {
            "claim_id": claim["id"],
            "status": claim["status"],
            "execution_gate": claim.get("execution_gate"),
            "exclusion_reason": (
                "execution_gate_not_open"
                if claim["status"] in stage_statuses
                else "status_not_executable_at_design_seed"
            ),
        }
        for claim in specification["claims"]
        if claim["id"] not in expected_executable
    }
    assert {record["claim_id"]: record for record in perimeter.excluded_claims} == expected_excluded
    executable_paths = set(perimeter.paths)
    for claim in specification["claims"]:
        if claim["id"] in expected_excluded:
            assert executable_paths.isdisjoint(claim.get("inputs", []))


def test_d3_release_rejects_raw_missing_and_stale_claim_inputs() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, _second = _released_inputs(directory)
            specification = directory / "specification.json"
            _write_specification(specification, ["data/raw/provider.json"])
            with pytest.raises(ValueError, match="raw provider input"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
                )
            missing = directory / "missing.parquet"
            _write_specification(specification, [missing.relative_to(REPO_ROOT).as_posix()])
            with pytest.raises(FileNotFoundError, match="claim input is absent"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
                )
            _write_specification(specification, [first.relative_to(REPO_ROOT).as_posix()])
            first.write_bytes(first.read_bytes() + b"tamper")
            with pytest.raises(RuntimeError, match="claim input.*current"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_reader_rejects_input_and_provenance_tampering_after_release() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, second = _released_inputs(directory)
            specification = directory / "specification.json"
            _write_specification(
                specification,
                [first.relative_to(REPO_ROOT).as_posix(), second.relative_to(REPO_ROOT).as_posix()],
            )
            release = publish_analysis_release(
                specification_path=specification.relative_to(REPO_ROOT),
                pointer_path=(directory / "release/current.json").relative_to(REPO_ROOT),
            )
            provenance = json.loads(sidecar_path(first).read_text(encoding="utf-8"))
            provenance["artefact"] = "different.parquet"
            sidecar_path(first).write_text(json.dumps(provenance), encoding="utf-8")
            with pytest.raises((RuntimeError, ValueError), match="current|provenance"):
                resolve_analysis_release(certificate_path=release.certificate_path.relative_to(REPO_ROOT))
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_reader_preserves_documentation_only_source_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, _second = _released_inputs(directory)
            specification = directory / "specification.json"
            _write_specification(
                specification, [first.relative_to(REPO_ROOT).as_posix()]
            )
            release = publish_analysis_release(
                specification_path=specification.relative_to(REPO_ROOT),
                pointer_path=(directory / "release/current.json").relative_to(
                    REPO_ROOT
                ),
            )
            monkeypatch.setattr(
                analysis_release,
                "code_fingerprint",
                lambda _sources: "f" * 64,
            )
            reopened = resolve_analysis_release(
                certificate_path=release.certificate_path.relative_to(REPO_ROOT)
            )
            assert reopened.generation == release.generation
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_pointer_crash_preserves_the_previous_release(monkeypatch: pytest.MonkeyPatch) -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, second = _released_inputs(directory)
            specification = directory / "specification.json"
            _write_specification(specification, [first.relative_to(REPO_ROOT).as_posix()])
            pointer = directory / "release/current.json"
            first_release = publish_analysis_release(
                specification_path=specification.relative_to(REPO_ROOT),
                pointer_path=pointer.relative_to(REPO_ROOT),
            )
            pointer_before = pointer.read_bytes()
            _write_specification(
                specification,
                [first.relative_to(REPO_ROOT).as_posix(), second.relative_to(REPO_ROOT).as_posix()],
            )

            def crash_before_pointer(*_args, **_kwargs):
                raise RuntimeError("injected D3 pointer crash")

            monkeypatch.setattr(analysis_release, "write_json", crash_before_pointer)
            with pytest.raises(RuntimeError, match="injected D3 pointer crash"):
                publish_analysis_release(
                    specification_path=specification.relative_to(REPO_ROOT),
                    pointer_path=pointer.relative_to(REPO_ROOT),
                )
            assert pointer.read_bytes() == pointer_before
            selected = resolve_artifact_release(
                pointer,
                kind=ANALYSIS_RELEASE_POINTER_KIND,
                schema_version=ANALYSIS_RELEASE_POINTER_SCHEMA_VERSION,
                filenames=ANALYSIS_RELEASE_FILENAMES,
                require_current_provenance=False,
            )
            assert selected.artifacts["certificate"] == first_release.certificate_path
        finally:
            _cleanup_manifest_mirror(directory)


def test_d3_publication_leases_ordinary_inputs_through_pointer_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            first, _second = _released_inputs(directory)
            specification = directory / "specification.json"
            _write_specification(
                specification, [first.relative_to(REPO_ROOT).as_posix()]
            )
            attempted = threading.Event()
            completed = threading.Event()
            real_publish = analysis_release.publish_artifact_release

            def checked_publish(**kwargs):
                def replace_input() -> None:
                    attempted.set()
                    with atomic_output(first) as temporary:
                        temporary.write_bytes(b"replacement")
                    completed.set()

                thread = threading.Thread(target=replace_input)
                thread.start()
                assert attempted.wait(timeout=1)
                assert not completed.wait(timeout=0.05)
                result = real_publish(**kwargs)
                assert not completed.wait(timeout=0.05)
                thread.join(timeout=2)
                return result

            monkeypatch.setattr(
                analysis_release, "publish_artifact_release", checked_publish
            )
            publish_analysis_release(
                specification_path=specification.relative_to(REPO_ROOT),
                pointer_path=(directory / "release/current.json").relative_to(
                    REPO_ROOT
                ),
            )
            assert completed.wait(timeout=2)
        finally:
            _cleanup_manifest_mirror(directory)


@pytest.mark.parametrize(
    "mutation", ["pointer", "member", "sidecar", "upstream", "specification"]
)
def test_fast_direct_and_current_resolvers_reject_post_publication_tampering(
    mutation: str,
) -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            endpoint, upstream, specification, analysis_pointer, release = (
                _publish_typed_analysis_release(directory)
            )
            if mutation == "pointer":
                endpoint.pointer_path.write_bytes(
                    endpoint.pointer_path.read_bytes() + b" "
                )
            elif mutation == "member":
                endpoint.artifacts["choices"].write_bytes(
                    endpoint.artifacts["choices"].read_bytes() + b"tamper"
                )
            elif mutation == "sidecar":
                provenance_path = sidecar_path(endpoint.artifacts["choices"])
                provenance = json.loads(provenance_path.read_text())
                provenance["notes"] = "tampered after publication"
                provenance_path.write_text(json.dumps(provenance) + "\n")
                pointer = json.loads(endpoint.pointer_path.read_text())
                pointer["artifacts"]["choices"]["provenance_sha256"] = file_sha256(
                    provenance_path
                )
                endpoint.pointer_path.write_text(json.dumps(pointer) + "\n")
            elif mutation == "upstream":
                upstream[0].write_bytes(b"different certified route")
            else:
                payload = json.loads(specification.read_text())
                payload["paper_scope"] = "changed after D3 publication"
                payload["lock_hash"] = canonical_hash(
                    {key: value for key, value in payload.items() if key != "lock_hash"}
                )
                specification.write_text(json.dumps(payload))
            operations = (
                lambda: resolve_analysis_release(
                    certificate_path=release.certificate_path.relative_to(directory),
                    root=directory,
                ),
                lambda: resolve_current_analysis_release(
                    pointer_path=analysis_pointer.relative_to(directory),
                    root=directory,
                ),
            )
            for operation in operations:
                with pytest.raises(
                    (FileNotFoundError, RuntimeError, TypeError, ValueError)
                ):
                    operation()
        finally:
            _cleanup_manifest_mirror(directory)


def test_fast_resolvers_validate_semantics_once_per_audit_and_hash_bindings_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path
    semantic_calls = 0
    real_semantic = endpoint_release_module.validate_endpoint_candidate_composition_paths

    def counted_semantic(paths):
        nonlocal semantic_calls
        semantic_calls += 1
        return real_semantic(paths)

    monkeypatch.setattr(
        endpoint_release_module,
        "validate_endpoint_candidate_composition_paths",
        counted_semantic,
    )
    endpoint, upstream = _publish_endpoint_release(directory)
    assert semantic_calls == 1
    specification = directory / "specification.json"
    _write_specification(
        specification, [ENDPOINT_CANDIDATE_COMPOSITION_RELEASE_RELATIVE]
    )
    analysis_pointer = directory / "analysis/current.json"
    release = publish_analysis_release(
        root=directory,
        specification_path=specification.relative_to(directory),
        pointer_path=analysis_pointer.relative_to(directory),
    )
    assert semantic_calls == 1

    real_hash = artifact_release.file_sha256
    counts: dict[Path, int] = {}

    def counted_hash(path: Path) -> str:
        resolved = Path(path).resolve()
        counts[resolved] = counts.get(resolved, 0) + 1
        return real_hash(Path(path))

    monkeypatch.setattr(artifact_release, "file_sha256", counted_hash)
    semantic_calls = 0
    resolve_analysis_release(
        certificate_path=release.certificate_path.relative_to(directory),
        root=directory,
    )
    assert semantic_calls == 0
    assert {counts[path.resolve()] for path in upstream} == {1}

    counts.clear()
    resolve_current_analysis_release(
        pointer_path=analysis_pointer.relative_to(directory),
        root=directory,
    )
    assert semantic_calls == 0
    assert {counts[path.resolve()] for path in upstream} == {1}
    assert endpoint.bundle.semantic_receipt is not None


def test_endpoint_consumer_lease_blocks_every_lineage_switch(tmp_path: Path) -> None:
    endpoint, upstream = _publish_endpoint_release(tmp_path)
    receipt = endpoint.bundle.semantic_receipt
    assert receipt is not None
    targets = (
        endpoint.pointer_path,
        endpoint.artifacts["choices"],
        sidecar_path(endpoint.artifacts["choices"]),
        upstream[0],
    )
    started = [threading.Event() for _target in targets]
    completed = [threading.Event() for _target in targets]

    def replace(index: int, target: Path) -> None:
        started[index].set()
        with atomic_output(target) as temporary:
            temporary.write_bytes(b"replacement")
        completed[index].set()

    with current_endpoint_candidate_composition_release(
        endpoint.pointer_path,
        expected_semantic_receipt=receipt,
    ) as leased:
        assert leased.generation_id == endpoint.generation_id
        threads = [
            threading.Thread(target=replace, args=(index, target))
            for index, target in enumerate(targets)
        ]
        for thread in threads:
            thread.start()
        assert all(event.wait(timeout=1) for event in started)
        assert not any(event.wait(timeout=0.05) for event in completed)

    for thread in threads:
        thread.join(timeout=2)
    assert all(event.is_set() for event in completed)


def test_endpoint_consumer_rechecks_uncoordinated_member_replacement(
    tmp_path: Path,
) -> None:
    endpoint, _upstream = _publish_endpoint_release(tmp_path)
    receipt = endpoint.bundle.semantic_receipt
    assert receipt is not None
    target = endpoint.artifacts["choices"]
    original = target.read_bytes()
    try:
        with pytest.raises(RuntimeError, match="lineage changed"):
            with current_endpoint_candidate_composition_release(
                endpoint.pointer_path,
                expected_semantic_receipt=receipt,
            ):
                target.write_bytes(original + b"uncoordinated mutation")
    finally:
        target.write_bytes(original)


def test_endpoint_consumer_rejects_valid_pointer_switch_after_d3_binding(
    tmp_path: Path,
) -> None:
    endpoint, upstream = _publish_endpoint_release(tmp_path)
    receipt = endpoint.bundle.semantic_receipt
    assert receipt is not None
    rows = {
        name: pd.read_parquet(path) for name, path in endpoint.artifacts.items()
    }
    replacement = publish_endpoint_candidate_composition_release(
        writers={
            name: (lambda target, table=table: table.to_parquet(target, index=False))
            for name, table in rows.items()
        },
        row_counts={name: len(table) for name, table in rows.items()},
        code_sources=["tests/test_analysis_release.py"],
        inputs=[upstream[0]],
        notes="different valid generation after D3 binding",
        preinstall_validator=_BindingValidator(upstream),
        pointer_path=endpoint.pointer_path,
    )
    assert replacement.generation_id != endpoint.generation_id
    with pytest.raises(ValueError, match="receipt"):
        with current_endpoint_candidate_composition_release(
            endpoint.pointer_path,
            expected_semantic_receipt=receipt,
        ):
            pass

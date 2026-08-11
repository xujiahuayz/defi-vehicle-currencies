from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

import ddvc.exploration as exploration
from ddvc.analysis_release import publish_analysis_release
from ddvc.exploration import close_exploration, execute_exploration_plan, resolve_exploration_release
from ddvc.model_registry import canonical_hash, model_run_id, validate_artifact_spec_ids
from ddvc.paths import REPO_ROOT
from ddvc.provenance import sidecar_path, stamp
from scripts.audit_findings_freeze import validate_model_ledger


def _workspace():
    return tempfile.TemporaryDirectory(prefix="e0-release-test-", dir=REPO_ROOT)


def _cleanup_manifest_mirror(directory: Path) -> None:
    relative = directory.relative_to(REPO_ROOT)
    shutil.rmtree(REPO_ROOT / "data" / "manifests" / relative, ignore_errors=True)


def _legacy_family() -> dict:
    return {
        "id": "legacy",
        "claim_id": "legacy",
        "estimator": "OLS",
        "fixed_effects": "none",
        "inference": "robust",
        "substantive_specifications": 1,
        "diagnostic_specifications": 0,
        "resampling_refits": 0,
        "status": "retired",
        "artifacts": [],
        "note": "historical",
    }


def _write_ledger(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "current_analysis_generation": None,
                "exploration": {
                    "status": "not_started",
                    "d3_generation": None,
                    "d3_certificate": None,
                    "generation": None,
                    "certificate": None,
                    "started_at": None,
                    "completed_at": None,
                },
                "legacy_families": [_legacy_family()],
                "runs": [],
            }
        ),
        encoding="utf-8",
    )


def _d3_release(directory: Path):
    input_path = directory / "analysis.parquet"
    pd.DataFrame({"day": ["20260101", "20260102"], "dominance": [0.2, 0.3]}).to_parquet(input_path, index=False)
    stamp(input_path, code_sources=["tests/test_exploration.py"], inputs=[])
    specification = directory / "specification.json"
    payload = {
        "schema_version": 1,
        "stage": "design_seed",
        "claims": [
            {
                "id": "seed",
                "status": "candidate_primary",
                "execution_gate": "open",
                "inputs": [input_path.relative_to(REPO_ROOT).as_posix()],
            }
        ],
    }
    payload["lock_hash"] = canonical_hash(payload)
    specification.write_text(json.dumps(payload), encoding="utf-8")
    return publish_analysis_release(
        specification_path=specification.relative_to(REPO_ROOT),
        pointer_path=(directory / "d3/current.json").relative_to(REPO_ROOT),
    )


def _write_plan(directory: Path, d3_generation: str, *, artifact: Path, families: int = 1) -> Path:
    runner = REPO_ROOT / "scripts" / "run_core_rq_experiments.py"
    family_records = []
    for index in range(families):
        output = artifact if index == 0 else artifact.with_name(f"result-{index}.jsonl")
        family_records.append(
            {
                "family_id": f"open-search-{index}",
                "claim_id": f"unregistered-question-{index}",
                "question": "Which data-supported mechanism or rival explanation is publication-worthy?",
                "search_dimensions": ["distribution", "heterogeneity", "mechanism", "rival_explanation"],
                "runner": runner.relative_to(REPO_ROOT).as_posix(),
                "arguments": ["--output", output.relative_to(REPO_ROOT).as_posix()],
                "engine_sources": [],
                "estimator": "exploratory OLS family",
                "fixed_effects": "open candidate set",
                "inference": "diagnostic until E1 registration",
                "artifacts": [
                    {
                        "path": output.relative_to(REPO_ROOT).as_posix(),
                        "role": "result",
                        "spec_ids": [f"open-fit-{index}"],
                    }
                ],
                "note": "Open-minded E0 family; no exploratory estimate is admissible evidence.",
            }
        )
    plan = directory / "plan.json"
    plan.write_text(
        json.dumps({"schema_version": 1, "d3_generation": d3_generation, "families": family_records}),
        encoding="utf-8",
    )
    return plan


def _successful_runner(command: list[str], _cwd: Path, env: dict[str, str]) -> int:
    output = REPO_ROOT / command[command.index("--output") + 1]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('{"spec_id":"open-fit-0","estimate":0.25}\n', encoding="utf-8")
    runner = Path(command[2]).relative_to(REPO_ROOT).as_posix()
    stamp(output, code_sources=[runner], inputs=[REPO_ROOT / env["DDVC_D3_CERTIFICATE"]])
    return 0


def _triage(run_id: str, *, outcome: str = "promote") -> dict:
    decision = {
        "decision_id": f"triage-{run_id[:12]}",
        "run_id": run_id,
        "outcome": outcome,
        "rationale": "The result is economically material and survives the exploratory attack, but it requires a new test.",
        "assessment": {
            "novelty": "new continuous dominance mechanism",
            "economic_magnitude": "large enough to matter",
            "robustness": "stable across the declared exploratory family",
            "identification_credibility": "candidate only until a distinct attack set",
            "centrality_to_vehicle_dominance": "directly concerns the degree of vehicleness",
            "jfe_fit": "potential headline after confirmation",
        },
    }
    if outcome == "promote":
        decision.update({"proposed_claim_id": "promoted-dominance-mechanism", "required_reopen_nodes": ["C", "E1"]})
    elif outcome == "retain_auxiliary":
        decision["companion_role"] = "support diagnostic"
    elif outcome == "park_next_paper":
        decision["proposed_question"] = "Does the same mechanism operate outside vehicle-currency markets?"
    else:
        decision["rejection_reason"] = "The pattern is fragile or economically uninformative."
    return {"schema_version": 1, "decisions": [decision]}


def test_e0_logs_before_fit_then_closes_exact_run_and_triage_algebra() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            artifact = directory / "result.jsonl"
            plan = _write_plan(directory, d3.generation, artifact=artifact)
            run_ids = execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )
            assert len(run_ids) == 1
            in_progress = json.loads(ledger.read_text(encoding="utf-8"))
            run = in_progress["runs"][0]
            assert run["lifecycle"] == "executed"
            assert run["lane"] == "exploratory"
            assert run["disposition"] == "not_assessed"
            assert run["run_id"] == model_run_id(run)
            assert run["plan_path"] == plan.relative_to(REPO_ROOT).as_posix()
            assert run["runner"] == "scripts/run_core_rq_experiments.py"
            assert run["arguments"] == ["--output", artifact.relative_to(REPO_ROOT).as_posix()]
            assert run["question"].startswith("Which data-supported mechanism")
            assert run["search_dimensions"] == [
                "distribution",
                "heterogeneity",
                "mechanism",
                "rival_explanation",
            ]
            assert run["declared_artifacts"] == [
                {
                    "path": artifact.relative_to(REPO_ROOT).as_posix(),
                    "role": "result",
                    "spec_ids": ["open-fit-0"],
                }
            ]
            assert in_progress["exploration"]["status"] == "in_progress"
            triage = directory / "triage.json"
            triage.write_text(json.dumps(_triage(run_ids[0])), encoding="utf-8")
            release = close_exploration(
                triage.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                lock_path=directory / "close.lock",
            )
            completed = json.loads(ledger.read_text(encoding="utf-8"))
            assert completed["exploration"]["status"] == "complete"
            assert completed["exploration"]["certificate"] == release.certificate_path.relative_to(REPO_ROOT).as_posix()
            assert release.certificate["exploratory_run_ids"] == run_ids
            assert release.certificate["triage_decisions"][0]["outcome"] == "promote"
            assert release.certificate["generation"] == completed["exploration"]["generation"]
            passed, detail = validate_model_ledger(
                completed,
                claim_ids=set(),
                root=REPO_ROOT,
            )
            assert passed, detail
            assert resolve_exploration_release(
                certificate_path=release.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
            ).generation == release.generation
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_missing_or_invalid_triage_never_publishes_a_certificate() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(directory, d3.generation, artifact=directory / "result.jsonl")
            run_id = execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )[0]
            triage = directory / "triage.json"
            triage.write_text(json.dumps({"schema_version": 1, "decisions": []}), encoding="utf-8")
            pointer = directory / "e0/current.json"
            with pytest.raises(ValueError, match="triage perimeter"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=pointer.relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
            assert not pointer.exists()
            assert json.loads(ledger.read_text(encoding="utf-8"))["exploration"]["status"] == "in_progress"
            invalid = _triage(run_id)
            invalid["decisions"][0]["outcome"] = "headline"
            triage.write_text(json.dumps(invalid), encoding="utf-8")
            with pytest.raises(ValueError, match="outcome"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=pointer.relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
            assert not pointer.exists()
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_failed_or_unchanged_fit_is_logged_but_cannot_close() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            artifact = directory / "result.jsonl"
            artifact.write_text('{"stale":true}\n', encoding="utf-8")
            stamp(artifact, code_sources=["scripts/run_core_rq_experiments.py"], inputs=[])
            plan = _write_plan(directory, d3.generation, artifact=artifact)

            def unchanged(_command, _cwd, _env):
                return 0

            with pytest.raises(RuntimeError, match="unchanged artifact"):
                execute_exploration_plan(
                    plan.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    lock_path=directory / "run.lock",
                    command_runner=unchanged,
                )
            failed = json.loads(ledger.read_text(encoding="utf-8"))["runs"][0]
            assert failed["lifecycle"] == "retired"
            assert failed["disposition"] == "rejected"
            triage = directory / "triage.json"
            triage.write_text(json.dumps({"schema_version": 1, "decisions": []}), encoding="utf-8")
            with pytest.raises(RuntimeError, match="without an executed fitted family"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_rejects_a_fit_not_provenance_bound_to_the_d3_release() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            artifact = directory / "result.jsonl"
            plan = _write_plan(directory, d3.generation, artifact=artifact)

            def unbound_runner(command, _cwd, _env):
                artifact.write_text('{"estimate":0.4}\n', encoding="utf-8")
                stamp(artifact, code_sources=[Path(command[2]).relative_to(REPO_ROOT).as_posix()], inputs=[])
                return 0

            with pytest.raises(ValueError, match="not bound to the D3 certificate"):
                execute_exploration_plan(
                    plan.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    lock_path=directory / "run.lock",
                    command_runner=unbound_runner,
                )
            failed = json.loads(ledger.read_text(encoding="utf-8"))["runs"][0]
            assert failed["lifecycle"] == "retired"
            assert failed["disposition"] == "rejected"
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_requires_explicit_rejection_for_each_retired_execution() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(directory, d3.generation, artifact=directory / "result.jsonl", families=2)

            def first_succeeds_second_fails(command, cwd, env):
                if command[command.index("--output") + 1].endswith("result-1.jsonl"):
                    return 3
                return _successful_runner(command, cwd, env)

            with pytest.raises(RuntimeError, match="exit=3"):
                execute_exploration_plan(
                    plan.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    lock_path=directory / "run.lock",
                    command_runner=first_succeeds_second_fails,
                )
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            executed_id = next(run["run_id"] for run in payload["runs"] if run["lifecycle"] == "executed")
            retired_id = next(run["run_id"] for run in payload["runs"] if run["lifecycle"] == "retired")
            triage = directory / "triage.json"
            triage.write_text(json.dumps(_triage(executed_id)), encoding="utf-8")
            with pytest.raises(ValueError, match="triage perimeter"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
            complete_triage = _triage(executed_id)
            complete_triage["decisions"].append(_triage(retired_id, outcome="reject")["decisions"][0])
            triage.write_text(json.dumps(complete_triage), encoding="utf-8")
            release = close_exploration(
                triage.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                lock_path=directory / "close.lock",
            )
            assert release.certificate["exploratory_run_ids"] == [executed_id]
            assert release.certificate["retired_run_ids"] == [retired_id]
            assert release.certificate["retired_run_decisions"][0]["outcome"] == "reject"
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_pointer_crash_keeps_ledger_open_and_is_resumable(monkeypatch: pytest.MonkeyPatch) -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(directory, d3.generation, artifact=directory / "result.jsonl")
            run_id = execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )[0]
            triage = directory / "triage.json"
            triage.write_text(json.dumps(_triage(run_id, outcome="retain_auxiliary")), encoding="utf-8")
            pointer = directory / "e0/current.json"

            def crash_before_pointer(*_args, **_kwargs):
                raise RuntimeError("injected E0 pointer crash")

            original_write = exploration.write_json
            monkeypatch.setattr(exploration, "write_json", crash_before_pointer)
            with pytest.raises(RuntimeError, match="injected E0 pointer crash"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=pointer.relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
            assert json.loads(ledger.read_text(encoding="utf-8"))["exploration"]["status"] == "in_progress"
            assert not pointer.exists()
            monkeypatch.setattr(exploration, "write_json", original_write)
            release = close_exploration(
                triage.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                pointer_path=pointer.relative_to(REPO_ROOT),
                lock_path=directory / "close.lock",
            )
            assert release.certificate["triage_decisions"][0]["outcome"] == "retain_auxiliary"
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_reader_rejects_post_certificate_run_record_tampering() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(directory, d3.generation, artifact=directory / "result.jsonl")
            run_id = execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )[0]
            triage = directory / "triage.json"
            triage.write_text(json.dumps(_triage(run_id, outcome="park_next_paper")), encoding="utf-8")
            release = close_exploration(
                triage.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                lock_path=directory / "close.lock",
            )
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            payload["runs"][0]["note"] = "silently reframed after exploration"
            ledger.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(ValueError, match="run identity|plan identity|does not reproduce"):
                resolve_exploration_release(
                    certificate_path=release.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_rejects_unknown_lifecycle_instead_of_omitting_the_run() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(directory, d3.generation, artifact=directory / "result.jsonl")
            run_id = execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )[0]
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            payload["runs"][0]["lifecycle"] = "silently_skipped"
            ledger.write_text(json.dumps(payload), encoding="utf-8")
            triage = directory / "triage.json"
            triage.write_text(json.dumps(_triage(run_id)), encoding="utf-8")
            with pytest.raises(RuntimeError, match="non-terminal exploratory lifecycles"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_rejects_declared_spec_ids_that_differ_from_fitted_contents() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(directory, d3.generation, artifact=directory / "result.jsonl")

            def mismatched_runner(command: list[str], _cwd: Path, env: dict[str, str]) -> int:
                output = REPO_ROOT / command[command.index("--output") + 1]
                output.write_text('{"spec_id":"undeclared-fit","estimate":0.25}\n', encoding="utf-8")
                runner = Path(command[2]).relative_to(REPO_ROOT).as_posix()
                stamp(output, code_sources=[runner], inputs=[REPO_ROOT / env["DDVC_D3_CERTIFICATE"]])
                return 0

            with pytest.raises(ValueError, match="declared spec_ids do not match"):
                execute_exploration_plan(
                    plan.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    lock_path=directory / "run.lock",
                    command_runner=mismatched_runner,
                )
            retired = json.loads(ledger.read_text(encoding="utf-8"))["runs"][0]
            assert retired["lifecycle"] == "retired"
            assert retired["disposition"] == "rejected"
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_support_artifact_cannot_declare_fitted_coverage() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(directory, d3.generation, artifact=directory / "support.jsonl")
            payload = json.loads(plan.read_text(encoding="utf-8"))
            payload["families"][0]["artifacts"][0]["role"] = "support"
            plan.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(ValueError, match="support artifact claims fitted coverage"):
                execute_exploration_plan(
                    plan.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    lock_path=directory / "run.lock",
                    command_runner=_successful_runner,
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_structured_artifact_spec_ids_cover_json_jsonl_parquet_and_support() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        json_path = directory / "fit.json"
        jsonl_path = directory / "fit.jsonl"
        parquet_path = directory / "fit.parquet"
        support_path = directory / "support.json"
        json_path.write_text(json.dumps({"fits": [{"spec_id": "json-fit"}]}), encoding="utf-8")
        jsonl_path.write_text('{"spec_id":"jsonl-fit"}\n', encoding="utf-8")
        pd.DataFrame({"spec_id": ["parquet-fit"], "estimate": [0.1]}).to_parquet(parquet_path, index=False)
        support_path.write_text(json.dumps({"coverage": 0.95}), encoding="utf-8")
        assert validate_artifact_spec_ids(json_path, role="result", declared=["json-fit"]) == {"json-fit"}
        assert validate_artifact_spec_ids(jsonl_path, role="diagnostic", declared=["jsonl-fit"]) == {"jsonl-fit"}
        assert validate_artifact_spec_ids(parquet_path, role="resampling", declared=["parquet-fit"]) == {"parquet-fit"}
        assert validate_artifact_spec_ids(support_path, role="support", declared=[]) == set()
        support_path.write_text(json.dumps({"spec_id": "hidden-fit"}), encoding="utf-8")
        with pytest.raises(ValueError, match="support artifact contains fitted"):
            validate_artifact_spec_ids(support_path, role="support", declared=[])


def test_e0_identity_reuse_compares_the_complete_planned_record() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(directory, d3.generation, artifact=directory / "result.jsonl")
            execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            payload["runs"][0]["question"] = "A different question hidden behind the same stored run id"
            ledger.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(RuntimeError, match="different complete plan"):
                execute_exploration_plan(
                    plan.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    lock_path=directory / "run.lock",
                    command_runner=_successful_runner,
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_completed_e0_reclose_validates_before_any_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(directory, d3.generation, artifact=directory / "result.jsonl")
            run_id = execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )[0]
            triage = directory / "triage.json"
            triage.write_text(json.dumps(_triage(run_id)), encoding="utf-8")
            pointer = directory / "e0/current.json"
            release = close_exploration(
                triage.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                pointer_path=pointer.relative_to(REPO_ROOT),
                lock_path=directory / "close.lock",
            )
            pointer_before = pointer.read_bytes()

            def forbidden_publish(*_args, **_kwargs):
                raise AssertionError("completed re-close attempted publication")

            monkeypatch.setattr(exploration, "_publish_exploration_certificate", forbidden_publish)
            assert close_exploration(
                triage.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                pointer_path=pointer.relative_to(REPO_ROOT),
                lock_path=directory / "close.lock",
            ).generation == release.generation
            changed = _triage(run_id)
            changed["decisions"][0]["rationale"] += " Changed after closure."
            triage.write_text(json.dumps(changed), encoding="utf-8")
            with pytest.raises(RuntimeError, match="completed E0"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=pointer.relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
            assert pointer.read_bytes() == pointer_before
        finally:
            _cleanup_manifest_mirror(directory)

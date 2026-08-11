from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

import ddvc.exploration as exploration
from ddvc.analysis_release import publish_analysis_release
from ddvc.exploration import EXPLORATION_PLAN_SCHEMA_VERSION, close_exploration, execute_exploration_plan as _execute_exploration_plan, resolve_exploration_release
from ddvc.model_artifacts import attach_spec_ids, model_artifact_context, write_model_exhibit
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
                "search_dimension_spec_ids": {
                    dimension: [f"open-fit-{index}"]
                    for dimension in ("distribution", "heterogeneity", "mechanism", "rival_explanation")
                },
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
    template = directory / "plan-template.json"
    template.write_text(
        json.dumps(
            {
                "schema_version": EXPLORATION_PLAN_SCHEMA_VERSION,
                "kind": "e0_exploration_plan_template",
                "families": [
                    {
                        key: family[key]
                        for key in ("family_id", "claim_id", "question", "search_dimensions")
                    }
                    for family in family_records
                ],
            }
        ),
        encoding="utf-8",
    )
    plan.write_text(
        json.dumps({"schema_version": EXPLORATION_PLAN_SCHEMA_VERSION, "d3_generation": d3_generation, "families": family_records}),
        encoding="utf-8",
    )
    return plan


def execute_exploration_plan(plan_path, **kwargs):
    plan = REPO_ROOT / plan_path
    template = plan.with_name("plan-template.json")
    return _execute_exploration_plan(
        plan_path,
        template_path=template.relative_to(REPO_ROOT),
        **kwargs,
    )


def _successful_runner(command: list[str], _cwd: Path, env: dict[str, str]) -> int:
    output = REPO_ROOT / command[command.index("--output") + 1]
    output.parent.mkdir(parents=True, exist_ok=True)
    index = int(output.stem.rsplit("-", 1)[1]) if output.stem.startswith("result-") else 0
    output.write_text(
        json.dumps({"spec_id": f"open-fit-{index}", "estimate": 0.25}) + "\n",
        encoding="utf-8",
    )
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
            assert run["search_dimension_spec_ids"] == {
                dimension: ["open-fit-0"]
                for dimension in run["search_dimensions"]
            }
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


def test_e0_rejects_an_executable_plan_below_the_template_perimeter() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(
                directory,
                d3.generation,
                artifact=directory / "result.jsonl",
                families=2,
            )
            payload = json.loads(plan.read_text(encoding="utf-8"))
            payload["families"] = payload["families"][:1]
            plan.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(ValueError, match="canonical family perimeter"):
                execute_exploration_plan(
                    plan.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    lock_path=directory / "run.lock",
                    command_runner=_successful_runner,
                )
            assert json.loads(ledger.read_text(encoding="utf-8"))["runs"] == []
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_rejects_precoverage_plan_schema_without_a_compatibility_path() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(
                directory,
                d3.generation,
                artifact=directory / "result.jsonl",
            )
            payload = json.loads(plan.read_text(encoding="utf-8"))
            payload["schema_version"] = 1
            plan.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(ValueError, match="plan schema is not current"):
                execute_exploration_plan(
                    plan.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    lock_path=directory / "run.lock",
                    command_runner=_successful_runner,
                )
            assert json.loads(ledger.read_text(encoding="utf-8"))["runs"] == []
        finally:
            _cleanup_manifest_mirror(directory)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("missing_dimension", "search-dimension coverage is not exact"),
        ("empty_dimension", "lacks exact fitted coverage"),
        ("support_only", "cites non-fitted specification ids"),
    ],
)
def test_e0_rejects_incomplete_or_nonfitted_search_dimension_coverage(
    failure: str,
    message: str,
) -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(
                directory,
                d3.generation,
                artifact=directory / "result.jsonl",
            )
            payload = json.loads(plan.read_text(encoding="utf-8"))
            family = payload["families"][0]
            dimension = family["search_dimensions"][0]
            if failure == "missing_dimension":
                family["search_dimension_spec_ids"].pop(dimension)
            elif failure == "empty_dimension":
                family["search_dimension_spec_ids"][dimension] = []
            else:
                family["artifacts"].append(
                    {
                        "path": (directory / "support.jsonl").relative_to(REPO_ROOT).as_posix(),
                        "role": "support",
                        "spec_ids": [],
                    }
                )
                family["search_dimension_spec_ids"][dimension] = ["support-only"]
            plan.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(ValueError, match=message):
                execute_exploration_plan(
                    plan.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    lock_path=directory / "run.lock",
                    command_runner=_successful_runner,
                )
            assert json.loads(ledger.read_text(encoding="utf-8"))["runs"] == []
        finally:
            _cleanup_manifest_mirror(directory)


def test_canonical_e0_template_covers_seed_families_and_open_discovery() -> None:
    template = json.loads(
        (REPO_ROOT / "docs" / "e0-exploration-plan.template.json").read_text(
            encoding="utf-8"
        )
    )
    assert template["schema_version"] == EXPLORATION_PLAN_SCHEMA_VERSION == 2
    assert [family["family_id"] for family in template["families"]] == [
        "vehicle_transition_e0",
        "routing_maturation_e0",
        "direct_cost_dominance_e0",
        "liquidity_allocation_e0",
        "open_question_anomaly_e0",
    ]
    assert template["families"][-1]["claim_id"] == "open_question"
    assert "open_question" in template["families"][-1]["search_dimensions"]


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


def test_e0_requires_explicit_rejection_for_a_repaired_execution_attempt() -> None:
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
            corrected_ids = execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )
            assert executed_id in corrected_ids
            assert len(corrected_ids) == 2
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            corrected = next(
                run
                for run in payload["runs"]
                if run["family_id"] == "open-search-1" and run["lifecycle"] == "executed"
            )
            assert corrected["attempt"] == 2
            assert corrected["retry_of_run_id"] == retired_id
            triage = directory / "triage.json"
            incomplete_triage = _triage(executed_id)
            incomplete_triage["decisions"].append(
                _triage(corrected["run_id"], outcome="retain_auxiliary")["decisions"][0]
            )
            triage.write_text(json.dumps(incomplete_triage), encoding="utf-8")
            with pytest.raises(ValueError, match="triage perimeter"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
            complete_triage = incomplete_triage
            complete_triage["decisions"].append(_triage(retired_id, outcome="reject")["decisions"][0])
            triage.write_text(json.dumps(complete_triage), encoding="utf-8")
            release = close_exploration(
                triage.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                lock_path=directory / "close.lock",
            )
            assert set(release.certificate["exploratory_run_ids"]) == set(corrected_ids)
            assert release.certificate["retired_run_ids"] == [retired_id]
            assert release.certificate["retired_run_decisions"][0]["outcome"] == "reject"
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_cannot_close_after_a_terminal_family_disappears() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(
                directory,
                d3.generation,
                artifact=directory / "result.jsonl",
                families=2,
            )
            run_ids = execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            payload["runs"] = [payload["runs"][0]]
            ledger.write_text(json.dumps(payload), encoding="utf-8")
            triage = directory / "triage.json"
            triage.write_text(json.dumps(_triage(run_ids[0])), encoding="utf-8")
            with pytest.raises(RuntimeError, match="canonical family perimeter"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
        finally:
            _cleanup_manifest_mirror(directory)


def test_e0_operational_failures_never_satisfy_the_executed_family_perimeter() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            ledger = directory / "model-ledger.json"
            _write_ledger(ledger)
            plan = _write_plan(
                directory,
                d3.generation,
                artifact=directory / "result.jsonl",
                families=5,
            )
            run_ids = execute_exploration_plan(
                plan.relative_to(REPO_ROOT),
                d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                ledger_path=ledger.relative_to(REPO_ROOT),
                lock_path=directory / "run.lock",
                command_runner=_successful_runner,
            )
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            for run in payload["runs"][1:]:
                run["lifecycle"] = "retired"
                run["disposition"] = "rejected"
                run["artifacts"] = []
                run["execution_note"] = "Runner exited with status 3; no fitted artifact is admitted."
            ledger.write_text(json.dumps(payload), encoding="utf-8")
            triage_payload = _triage(run_ids[0], outcome="retain_auxiliary")
            triage_payload["decisions"].extend(
                _triage(run_id, outcome="reject")["decisions"][0]
                for run_id in run_ids[1:]
            )
            triage = directory / "triage.json"
            triage.write_text(json.dumps(triage_payload), encoding="utf-8")
            with pytest.raises(RuntimeError, match="executed runs do not close"):
                close_exploration(
                    triage.relative_to(REPO_ROOT),
                    d3_certificate_path=d3.certificate_path.relative_to(REPO_ROOT),
                    ledger_path=ledger.relative_to(REPO_ROOT),
                    pointer_path=(directory / "e0/current.json").relative_to(REPO_ROOT),
                    lock_path=directory / "close.lock",
                )
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


def test_model_artifact_adapter_binds_spec_ids_and_exact_d3_certificate() -> None:
    with _workspace() as raw_directory:
        directory = Path(raw_directory)
        try:
            d3 = _d3_release(directory)
            context = model_artifact_context(
                environment={
                    "DDVC_D3_CERTIFICATE": d3.certificate_path.relative_to(REPO_ROOT).as_posix(),
                    "DDVC_D3_GENERATION": d3.generation,
                }
            )
            frame = attach_spec_ids(
                pd.DataFrame(
                    {
                        "family": ["routing", "routing"],
                        "spec": ["primary", "alternative"],
                        "estimate": [0.1, 0.2],
                    }
                ),
                prefix="routing-e0",
                columns=("family", "spec"),
            )
            output = directory / "model.jsonl"
            write_model_exhibit(
                frame,
                output,
                role="result",
                context=context,
                code_sources=["tests/test_exploration.py"],
                inputs=[],
                notes="adapter contract test",
            )
            assert validate_artifact_spec_ids(
                output,
                role="result",
                declared=["routing-e0.routing.primary", "routing-e0.routing.alternative"],
            ) == {"routing-e0.routing.primary", "routing-e0.routing.alternative"}
            provenance = json.loads(sidecar_path(output).read_text(encoding="utf-8"))
            assert d3.certificate_path.relative_to(REPO_ROOT).as_posix() in {
                record["path"] for record in provenance["inputs"]
            }
            with pytest.raises(ValueError, match="disagrees with its certificate"):
                model_artifact_context(
                    environment={
                        "DDVC_D3_CERTIFICATE": d3.certificate_path.relative_to(REPO_ROOT).as_posix(),
                        "DDVC_D3_GENERATION": "0" * 64,
                    }
                )
            with pytest.raises(ValueError, match="support artifact cannot contain spec_id"):
                write_model_exhibit(
                    frame,
                    directory / "support.jsonl",
                    role="support",
                    context=context,
                    code_sources=["tests/test_exploration.py"],
                    inputs=[],
                    notes="invalid support",
                )
        finally:
            _cleanup_manifest_mirror(directory)


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

#!/usr/bin/env python3
"""Earn the git-native E1 lock from a validated seed and completed E0 run."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ddvc.analysis_release import resolve_analysis_release
from ddvc.exploration import close_exploration, execute_exploration_plan
from ddvc.model_registry import artifact_fitted_spec_ids, canonical_hash
from ddvc.paths import REPO_ROOT
from ddvc.provenance import portable_content_sha256
from scripts.audit_findings_freeze import validate_specification_lock


SPECIFICATION = Path("docs/specification-lock.json")
PLAN = Path("docs/e0-exploration-plan.json")
TEMPLATE = Path("docs/e0-exploration-plan.template.json")
TRIAGE = Path("docs/e0-exploration-triage.json")
LEDGER = Path("docs/model-ledger.json")
E0_POINTER = Path("data/processed/e0_exploration_release/current.json")
D3_POINTER = Path("data/processed/d3_analysis_release/current.json")

VEHICLE_ARTIFACTS = (
    ("output/exhibits/e0_vehicle_transition_smoke_estimates.jsonl", "result"),
    ("output/exhibits/e0_vehicle_transition_smoke_support.jsonl", "support"),
    ("output/exhibits/e0_vehicle_transition_backing_regime_estimates.jsonl", "result"),
    ("output/exhibits/e0_vehicle_transition_backing_regime_support.jsonl", "support"),
    ("output/exhibits/e0_vehicle_transition_fixed_opportunity_estimates.jsonl", "result"),
    ("output/exhibits/e0_vehicle_transition_fixed_opportunity_support.jsonl", "support"),
    ("output/exhibits/vehicle_transition_pair_panel.parquet", "support"),
    ("output/exhibits/vehicle_transition_pair_contributions.parquet", "support"),
    ("output/exhibits/vehicle_transition_pair_decomposition.jsonl", "result"),
    ("output/exhibits/vehicle_transition_pair_support.jsonl", "support"),
    ("output/exhibits/vehicle_transition_pair_fixed_effects.jsonl", "result"),
)
LIQUIDITY_ARTIFACTS = (
    ("output/exhibits/liquidity_capital_v2_predictability.jsonl", "result"),
    ("output/exhibits/liquidity_capital_v2_support.jsonl", "support"),
    ("output/exhibits/e0_liquidity_capital_v2_influence_estimates.jsonl", "result"),
    ("output/exhibits/e0_liquidity_capital_v2_influence_support.jsonl", "support"),
    ("output/exhibits/e0_liquidity_capital_v2_quantity_contract.jsonl", "support"),
    ("output/exhibits/e0_liquidity_capital_v2_attack_disposition.jsonl", "support"),
)
OPEN_QUESTION_ARTIFACTS = (
    ("output/exhibits/e0_open_question_anomaly_diagnostics.jsonl", "diagnostic"),
    ("output/exhibits/e0_open_question_anomaly_support.jsonl", "support"),
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON owner is not an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_design_seed(seed: dict[str, Any]) -> None:
    """Apply the freeze audit's exact validator before any machine stamp."""

    if seed.get("stage") != "design_seed" or seed.get("locked_at") is not None:
        raise ValueError("E1 owner requires an unlocked design_seed")
    passed, detail = validate_specification_lock(seed)
    if not passed:
        raise ValueError(f"design seed failed the findings-freeze validator: {detail}")


def _d3_certificate(root: Path) -> Path:
    pointer = _read_json(root / D3_POINTER)
    generation = str(pointer.get("generation_id") or "")
    if not generation:
        raise ValueError("D3 pointer has no generation identity")
    path = root / D3_POINTER.parent / "generations" / generation / "certificate.json"
    if not path.is_file():
        raise FileNotFoundError(f"D3 certificate is absent: {path}")
    return path


def _spec_ids(root: Path, relative: str) -> list[str]:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(f"planned fitted artifact is absent: {relative}")
    identifiers = sorted(artifact_fitted_spec_ids(path))
    if not identifiers:
        raise ValueError(f"planned fitted artifact has no specification ids: {relative}")
    return identifiers


def _artifact_contracts(root: Path, values: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "role": role,
            "spec_ids": _spec_ids(root, path) if role != "support" else [],
        }
        for path, role in values
    ]


def build_exploration_plan(seed: dict[str, Any], d3_generation: str, *, root: Path) -> dict[str, Any]:
    """Build the exact three-family plan from the canonical template and fitted IDs."""

    template = _read_json(root / TEMPLATE)
    executable = {
        family["family_id"]: family
        for family in template["families"]
        if family.get("execution_status") == "executable"
    }
    if set(executable) != {
        "vehicle_transition_e0",
        "liquidity_capital_v2_e0",
        "open_question_anomaly_e0",
    }:
        raise ValueError(f"unexpected E0 executable perimeter: {sorted(executable)}")

    vehicle_artifacts = _artifact_contracts(root, VEHICLE_ARTIFACTS)
    liquidity_artifacts = _artifact_contracts(root, LIQUIDITY_ARTIFACTS[:-1]) + [
        {"path": LIQUIDITY_ARTIFACTS[-1][0], "role": "support", "spec_ids": []}
    ]
    open_specs = [
        "open-question-anomaly-e0." + attack_id.replace("_", "-")
        for attack_id in executable["open_question_anomaly_e0"]["required_attack_ids"]
    ]
    open_artifacts = [
        {"path": OPEN_QUESTION_ARTIFACTS[0][0], "role": "diagnostic", "spec_ids": open_specs},
        {"path": OPEN_QUESTION_ARTIFACTS[1][0], "role": "support", "spec_ids": []},
    ]
    vehicle_specs = {record["path"]: record["spec_ids"] for record in vehicle_artifacts}
    liquidity_specs = {record["path"]: record["spec_ids"] for record in liquidity_artifacts}
    smoke = vehicle_specs[VEHICLE_ARTIFACTS[0][0]]
    backing = vehicle_specs[VEHICLE_ARTIFACTS[2][0]]
    fixed = vehicle_specs[VEHICLE_ARTIFACTS[4][0]]
    decomposition = vehicle_specs[VEHICLE_ARTIFACTS[8][0]]
    pair_fixed = vehicle_specs[VEHICLE_ARTIFACTS[10][0]]
    predictability = liquidity_specs[LIQUIDITY_ARTIFACTS[0][0]]
    influence = liquidity_specs[LIQUIDITY_ARTIFACTS[2][0]]
    open_by_attack = {
        spec_id.rsplit(".", 1)[-1].replace("-", "_"): spec_id
        for spec_id in open_specs
    }

    vehicle_template = executable["vehicle_transition_e0"]
    liquidity_template = executable["liquidity_capital_v2_e0"]
    open_template = executable["open_question_anomaly_e0"]
    families = [
        {
            "family_id": "vehicle_transition_e0",
            "claim_id": vehicle_template["claim_id"],
            "question": vehicle_template["question"],
            "search_dimensions": vehicle_template["search_dimensions"],
            "search_dimension_spec_ids": {
                "distribution": smoke,
                "support": fixed,
                "functional_form": smoke,
                "heterogeneity": backing,
                "rival_explanation": [*pair_fixed, *decomposition],
            },
            "required_attack_ids": vehicle_template["required_attack_ids"],
            "attack_evidence": {
                "dominance_measure_triangulation": {"artifact_path": VEHICLE_ARTIFACTS[0][0], "spec_ids": smoke},
                "routing_strata_separation": {"artifact_path": VEHICLE_ARTIFACTS[0][0], "spec_ids": smoke},
                "dated_backing_regimes": {"artifact_path": VEHICLE_ARTIFACTS[2][0], "spec_ids": backing},
                "fixed_opportunity_conditioning": {"artifact_path": VEHICLE_ARTIFACTS[5][0]},
                "support_uncertainty_ledger": {"artifact_path": VEHICLE_ARTIFACTS[1][0]},
                "within_pair_composition_decomposition": {"artifact_path": VEHICLE_ARTIFACTS[8][0], "spec_ids": decomposition},
            },
            "runner": "scripts/run_vehicle_transition_exploration.py",
            "arguments": [],
            "engine_sources": [],
            "estimator": "daily HAC share contrasts, fixed-opportunity cohorts, pair-cell WLS, and exact descriptive decompositions",
            "fixed_effects": "none for daily contrasts; saturated pair-month-day-integration cells for the fixed-market estimate",
            "inference": "30-day calendar HAC or two-way ordered-pair and date CR1 as declared by component",
            "artifacts": vehicle_artifacts,
            "note": "Complete E0 vehicle-transition family; state-frontier dimensions remain explicit unsupported rows, never fitted claims.",
        },
        {
            "family_id": "liquidity_capital_v2_e0",
            "claim_id": liquidity_template["claim_id"],
            "question": liquidity_template["question"],
            "search_dimensions": liquidity_template["search_dimensions"],
            "search_dimension_spec_ids": {
                "distribution": predictability,
                "support": predictability,
                "functional_form": predictability,
                "heterogeneity": influence,
                "mechanism": predictability,
                "rival_explanation": influence,
            },
            "required_attack_ids": liquidity_template["required_attack_ids"],
            "attack_evidence": {
                "absolute_share_sign_stability": {"artifact_path": LIQUIDITY_ARTIFACTS[0][0], "spec_ids": predictability},
                "bidirectional_exact_horizons": {"artifact_path": LIQUIDITY_ARTIFACTS[0][0], "spec_ids": predictability},
                "common_shock_price_risk_placebos": {"artifact_path": LIQUIDITY_ARTIFACTS[5][0]},
                "influence_concentration": {"artifact_path": LIQUIDITY_ARTIFACTS[2][0], "spec_ids": influence},
                "multiplicity_support_ledger": {"artifact_path": LIQUIDITY_ARTIFACTS[0][0], "spec_ids": predictability},
                "stress_heterogeneity": {"artifact_path": LIQUIDITY_ARTIFACTS[5][0]},
                "v2_calendar_perimeter_subsamples": {"artifact_path": LIQUIDITY_ARTIFACTS[0][0], "spec_ids": predictability},
                "v2_stock_v3_flow_separation": {"artifact_path": LIQUIDITY_ARTIFACTS[4][0]},
            },
            "runner": "scripts/run_liquidity_capital_v2_predictability.py",
            "arguments": ["--bootstrap-repetitions", "199", "--top-pool-count", "5"],
            "engine_sources": [],
            "estimator": "bidirectional exact-calendar candidate-day fixed-effect panels and leave-one-unit influence refits",
            "fixed_effects": "candidate and origin-date fixed effects in the primary full-calendar specifications",
            "inference": "30-day calendar score HAC, month-block bootstrap, and limited two-way clustered sensitivity",
            "artifacts": liquidity_artifacts,
            "note": "V2 deposited-capital stock family; price-risk and stress attacks are recorded as blocked by the current claim-input perimeter.",
        },
        {
            "family_id": "open_question_anomaly_e0",
            "claim_id": open_template["claim_id"],
            "question": open_template["question"],
            "search_dimensions": open_template["search_dimensions"],
            "search_dimension_spec_ids": {
                dimension: open_specs for dimension in open_template["search_dimensions"]
            },
            "required_attack_ids": open_template["required_attack_ids"],
            "attack_evidence": {
                attack_id: {
                    "artifact_path": OPEN_QUESTION_ARTIFACTS[0][0],
                    "spec_ids": [open_by_attack[attack_id]],
                }
                for attack_id in open_template["required_attack_ids"]
            },
            "runner": "scripts/run_open_question_anomaly_e0.py",
            "arguments": [],
            "engine_sources": [],
            "estimator": "bounded descriptive diagnostics over the released route-only panels",
            "fixed_effects": "not applicable; no causal or confirmatory coefficient is fitted",
            "inference": "diagnostic magnitudes only",
            "artifacts": open_artifacts,
            "note": "Open discovery is retained as a diagnostic and creates no unregistered paper claim.",
        },
    ]
    return {
        "schema_version": 4,
        "kind": "e0_exploration_plan",
        "d3_generation": d3_generation,
        "families": families,
    }


def _triage(run_ids: list[str], *, retired_run_ids: list[str] | None = None) -> dict[str, Any]:
    decisions = []
    for run_id in sorted(run_ids):
        decisions.append(
            {
                "decision_id": f"retain-{run_id[:16]}",
                "run_id": run_id,
                "outcome": "retain_auxiliary",
                "companion_role": "design-seed evidence used to register a distinct confirmatory plan",
                "rationale": (
                    "The E0 family maps support, alternatives, and unresolved attacks but does not become "
                    "admissible evidence; E1 retains it as design evidence and requires a distinct F run."
                ),
                "assessment": {
                    "novelty": "The family addresses a predeclared vehicle-dominance or liquidity mechanism claim.",
                    "economic_magnitude": "Magnitude is preserved in the fitted artifacts and is not selected in triage.",
                    "robustness": "Every canonical attack has fitted evidence or an explicit unsupported disposition.",
                    "identification_credibility": "The evidence is descriptive or predictive and carries its stated fixed-effect boundary.",
                    "centrality_to_vehicle_dominance": "The family is directly attached to one execution-open claim.",
                    "jfe_fit": "The retained packet separates a primary specification, alternatives, rivals, and support limits.",
                },
            }
        )
    for run_id in sorted(retired_run_ids or []):
        decisions.append(
            {
                "decision_id": f"reject-{run_id[:16]}",
                "run_id": run_id,
                "outcome": "reject",
                "rejection_reason": "engineering_execution_failed_before_any_fitted_artifact_was_admitted",
                "rationale": (
                    "The first execution failed while importing the composed runner, before fitting or admitting "
                    "an artifact. The ledger preserves that failed attempt and the successful retry separately."
                ),
                "assessment": {
                    "novelty": "No scientific result was produced by this retired engineering attempt.",
                    "economic_magnitude": "No fitted artifact was admitted, so the attempt carries zero evidentiary weight.",
                    "robustness": "The successful retry executes the unchanged registered engine and full attack perimeter.",
                    "identification_credibility": "The import failure occurred before estimation and cannot identify a claim.",
                    "centrality_to_vehicle_dominance": "The runner targets a central claim, but this failed attempt contributes no evidence.",
                    "jfe_fit": "A pre-estimation engineering failure is rejected rather than reported as a research result.",
                },
            }
        )
    return {"schema_version": 1, "decisions": decisions}


def _coverage_leaves(value: object, path: str) -> list[tuple[str, object]]:
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in _coverage_leaves(child, f"{path}/{key}")]
    if isinstance(value, list):
        return [item for index, child in enumerate(value) for item in _coverage_leaves(child, f"{path}/{index}")]
    return [(path, value)]


def _registered_plan(claim: dict[str, Any]) -> list[dict[str, Any]]:
    leaves = _coverage_leaves(claim.get("mandatory_alternatives") or {}, "mandatory_alternatives")
    specifications: list[dict[str, Any]] = []
    for index, (check_id, choice) in enumerate(leaves):
        specifications.append(
            {
                "spec_id": f"{claim['id']}-registered-{index + 1:02d}",
                "kind": "primary" if index == 0 else "alternative",
                "parameters": {"registered_choice": choice, "check_id": check_id},
                "covers": [check_id],
            }
        )
    specifications.append(
        {
            "spec_id": f"{claim['id']}-registered-falsifier",
            "kind": "falsifier",
            "parameters": {"falsifier": claim["falsifier"]},
            "covers": ["falsifier"],
        }
    )
    return specifications


def build_confirmatory_lock(
    seed: dict[str, Any],
    *,
    seed_file_sha256: str,
    d3_generation: str,
    d3_certificate: str,
    exploration_generation: str,
    exploration_certificate: str,
) -> dict[str, Any]:
    payload = copy.deepcopy(seed)
    payload["design_seed_identity"] = {
        "lock_hash": seed["lock_hash"],
        "file_sha256": seed_file_sha256,
    }
    payload["adjudications"] = [
        {
            "id": "vehicle_use_weighting",
            "decision": "episode_count_primary_value_secondary",
            "reason": (
                "The estimand is the frequency of intermediary choice and topology is complete, while dollar "
                "support is type-dependent. Lehar and Parlour separately report transaction counts and volume, "
                "and show that dollar volume requires an explicit cross-market price construction."
            ),
            "citations": [
                {"source_key": "LeharParlour2024Uniswap", "location": "Section III and Table I, journal pp. 335-338"},
                {"source_key": "LeharParlour2024Uniswap", "location": "Appendix C, journal pp. 365-367"},
            ],
        },
        {
            "id": "liquidity_rent_confirmatory_perimeter",
            "decision": "withhold_until_external_intraday_reference_prices",
            "reason": (
                "The saved LVR contract requires an independent external price path; own-pool variance cannot "
                "identify LVR. The required exact address-resolved intraday panel is absent, so finishability "
                "demotes this claim instead of waiting or substituting a proxy."
            ),
            "citations": [
                {"source_key": "MilionisMoallemiRoughgardenZhang2022LVR", "location": "LVR definition and external-market price process, Sections 2-3"},
                {"source_key": "LeharParlour2024Uniswap", "location": "Section IV.B, Figure 12, journal pp. 348-350"},
            ],
        },
    ]
    payload.update(
        {
            "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stage": "confirmatory",
            "analytical_choices_status": "registered_after_exploration",
            "d3_generation": d3_generation,
            "d3_certificate": d3_certificate,
            "exploration_generation": exploration_generation,
            "exploration_certificate": exploration_certificate,
        }
    )
    status_map = {
        "candidate_primary": "registered_primary",
        "candidate_foundation": "registered_foundation",
        "candidate_mechanism": "registered_mechanism",
        "candidate_companion": "registered_companion",
    }
    for claim in payload["claims"]:
        if claim["id"] == "liquidity_rent_incidence":
            claim["status"] = "withheld"
            claim["withheld_reason"] = "external_intraday_reference_price_panel_absent_at_E0_close"
            continue
        claim["status"] = status_map.get(claim["status"], claim["status"])
        if claim.get("execution_gate") == "open":
            specifications = _registered_plan(claim)
            claim["registered_specifications"] = specifications
            claim["plan_hash"] = canonical_hash(specifications)
    payload["lock_hash"] = canonical_hash({key: value for key, value in payload.items() if key != "lock_hash"})
    passed, detail = validate_specification_lock(payload, require_confirmatory=True)
    if not passed:
        raise ValueError(f"machine-issued confirmatory lock failed validation: {detail}")
    return payload


def main() -> int:
    root = REPO_ROOT
    specification_path = root / SPECIFICATION
    seed = _read_json(specification_path)
    validate_design_seed(seed)
    seed_file_sha256 = portable_content_sha256(specification_path)
    d3_path = _d3_certificate(root)
    d3 = resolve_analysis_release(certificate_path=d3_path.relative_to(root), root=root)
    plan = build_exploration_plan(seed, d3.generation, root=root)
    _write_json(root / PLAN, plan)
    run_ids = execute_exploration_plan(
        PLAN,
        d3_certificate_path=d3_path.relative_to(root),
        root=root,
        ledger_path=LEDGER,
        template_path=TEMPLATE,
        specification_path=SPECIFICATION,
    )
    model_ledger = _read_json(root / LEDGER)
    retired_run_ids = [
        str(run["run_id"])
        for run in model_ledger.get("runs", [])
        if run.get("lifecycle") == "retired"
    ]
    _write_json(root / TRIAGE, _triage(run_ids, retired_run_ids=retired_run_ids))
    exploration = close_exploration(
        TRIAGE,
        d3_certificate_path=d3_path.relative_to(root),
        root=root,
        ledger_path=LEDGER,
        pointer_path=E0_POINTER,
    )
    locked = build_confirmatory_lock(
        seed,
        seed_file_sha256=seed_file_sha256,
        d3_generation=d3.generation,
        d3_certificate=d3_path.relative_to(root).as_posix(),
        exploration_generation=exploration.generation,
        exploration_certificate=exploration.certificate_path.relative_to(root).as_posix(),
    )
    _write_json(specification_path, locked)
    print(
        json.dumps(
            {
                "status": "confirmatory",
                "d3_generation": d3.generation,
                "exploration_generation": exploration.generation,
                "lock_hash": locked["lock_hash"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

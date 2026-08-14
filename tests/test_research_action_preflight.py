import json
from pathlib import Path
import sys

import pytest

from scripts.research_action_preflight import (
    ACTION_SECTIONS,
    checklist_sections,
    checklist_hash,
    checklist_item_ids,
    closure_invalidation_identity,
    closure_report_template,
    frontmatter,
    main,
    prose_gate,
    regression_checks,
    verify_closure_report,
)


def test_frontmatter_reads_live_graph_fields(tmp_path: Path) -> None:
    path = tmp_path / "freeze.md"
    path.write_text("---\nfreeze_status: red\nprose_node: closed\n---\nbody\n")
    assert frontmatter(path) == {"freeze_status": "red", "prose_node": "closed"}


def test_frontmatter_requires_closed_header(tmp_path: Path) -> None:
    path = tmp_path / "freeze.md"
    path.write_text("---\nfreeze_status: red\n")
    with pytest.raises(ValueError, match="unterminated"):
        frontmatter(path)


def test_every_graph_stage_has_a_separate_checklist() -> None:
    sections = checklist_sections()
    required = {
        "Universal closure envelope",
        "O. Operations and supervision",
        "A. Venue and talk benchmark",
        "B. Domain literature",
        "C. Estimand and measurement",
        "K. Ideation",
        "D1. Purpose-bound input contract",
        "D2. Certification and material repair",
        "D3. Analysis panel",
        "J0. Purpose-bound data release",
        "E0. Exploration and mechanism search",
        "E1. Claim-specific lock",
        "F. Registered empirics",
        "J1. Finding admission",
        "G. Scientific interpretation and paper spine",
        "P0. Working-paper prose",
        "P1. Final integrative paper edit",
        "H. Live deck",
        "I. Independent challenge",
        "J2-paper. Paper certificate",
        "J2-deck. Deck certificate",
        "J3. Submission freeze",
        "R. Repository and reproducibility",
    }
    assert required <= set(sections)
    assert all(sections[name] for name in required)


def test_node_specific_preflight_does_not_close_adjacent_nodes() -> None:
    e0 = " ".join(regression_checks("analysis", "E0")).lower()
    assert "universal closure envelope" not in e0
    assert "explicitly: ols/wls" in e0
    assert "freeze one claim" not in e0
    assert "run the e1 primary" not in e0
    assert "finding admission" not in e0


def test_action_routes_cover_point_of_use_literature() -> None:
    for action in ("analysis", "deck", "prose"):
        assert "B. Domain literature" in ACTION_SECTIONS[action]
    assert "A. Venue and talk benchmark" in ACTION_SECTIONS["deck"]
    assert "A. Venue and talk benchmark" in ACTION_SECTIONS["prose"]


def test_universal_envelope_requires_evidence_review_and_invalidation() -> None:
    checks = " ".join(regression_checks("analysis", "C")).lower()
    assert "requirement ids" in checks
    assert "pass" in checks and "not_applicable" in checks
    assert "scientific reason accepted" in checks
    assert "builder and reviewer are distinct" in checks
    assert "reopens the package automatically" in checks
    assert "compatible interjections" in checks


def test_data_preflight_is_purpose_bound_and_materiality_bounded() -> None:
    d1 = " ".join(regression_checks("data", "D1")).lower()
    d2 = " ".join(regression_checks("data", "D2")).lower()
    assert "smallest sufficient panel" in d1
    assert "unspecified future k ideas" in d1
    assert "materiality stop rule" in d1
    assert "diffuse immaterial dirt" in d2
    assert "fixed-date mechanism test" in d2


def test_e0_names_every_requested_method_family() -> None:
    checks = " ".join(regression_checks("analysis", "E0")).lower()
    for phrase in ("ols/wls", "panel fixed effects", "logit/binomial", "ppml", "cloglog", "cox", "did/event study", "t comparisons", "ks/distribution"):
        assert phrase in checks


def test_p0_requires_raw_jfe_whole_paper_rhythm_analogy_and_editorial_rules() -> None:
    checks = " ".join(regression_checks("prose", "P0")).lower()
    for phrase in (
        "raw jfe passage",
        "complete manuscript",
        "every section and subsection",
        "natural sentence and paragraph-length variation",
        "finance-calibrated analogies",
        "100-word abstract",
        "harmonized amm notation",
        "transaction links",
        "mathematical minus signs",
        "conclusion synthesizes",
    ):
        assert phrase in checks
    assert "local repair never closes p0" in checks


def test_h_requires_backlog_authentic_case_no_mp4_notes_and_full_review() -> None:
    checks = " ".join(regression_checks("deck", "H")).lower()
    for phrase in (
        "persistent visual backlog",
        "authentic, correctly ordered route case",
        "never embed a synthetic slide animation as mp4",
        "interpretation stays in visible slide prose",
        "changed-page and whole-deck projection review",
    ):
        assert phrase in checks


def test_operations_encodes_runtime_and_eta_requirements() -> None:
    checks = " ".join(regression_checks("operations", "O")).lower()
    for phrase in (
        "without launching a second token-consuming executor",
        "does not fall back to qwen or opus",
        "does not depend on tailscale",
        "duplicate supervisors",
        "throughput-based eta",
    ):
        assert phrase in checks


def test_repository_has_its_own_closure_node() -> None:
    checks = " ".join(regression_checks("repository", "R")).lower()
    for phrase in ("human/agent consumers", "map each manuscript table", "legacy", "hard-wrap", "clean equivalent boundary"):
        assert phrase in checks


def test_tiered_prose_gate_preserves_blocked_coefficient_boundary() -> None:
    allowed, message = prose_gate({"prose_node": "tiered"})
    assert allowed
    assert "certified route-only facts" in message
    assert "exact-state coefficient" in message


def test_closed_prose_gate_still_blocks_paper_mutation() -> None:
    allowed, message = prose_gate({"prose_node": "closed"})
    assert not allowed
    assert "leave paper/ unchanged" in message


def completed_report(action: str = "analysis", node: str = "E0") -> dict:
    report = closure_report_template(action, node)
    report.update(
        {
            "package_id": "pkg-e0-001",
            "requirement_ids": ["REQ-001", "REQ-019"],
            "owner": "builder",
            "immutable_inputs": [{"path": "output/panel.parquet", "sha256": "a" * 64}],
            "upstream_generation": "j0-generation-42",
            "predecessor_certificate": {
                "path": "output/j0-certificate.json",
                "sha256": "b" * 64,
            },
            "outputs": [{"path": "output/exploration.json", "sha256": "c" * 64}],
            "allowed_claim": "Explore route composition without admitting a paper finding.",
            "tests": [
                {
                    "command": "pytest tests/test_exploration.py",
                    "result": "pass",
                    "evidence": "12 tests passed",
                }
            ],
            "stop_rule": "Stop after the strongest objection is recorded.",
            "downstream_join": "E1",
            "reviewer": "reviewer",
        }
    )
    for item in report["items"]:
        item["status"] = "pass"
        item["evidence"] = f"evidence/{item['id']}.json"
    report["invalidation_identity"] = closure_invalidation_identity(report)
    return report


def test_closure_template_uses_live_checklist_ids_without_copying_prose() -> None:
    report = closure_report_template("analysis", "E0")
    assert report["checklist_hash"] == checklist_hash("analysis", "E0")
    assert [item["id"] for item in report["items"]] == list(
        checklist_item_ids("analysis", "E0")
    )
    assert all("text" not in item and "rule" not in item for item in report["items"])


def test_completed_closure_report_passes_current_node_contract() -> None:
    assert verify_closure_report(completed_report(), "analysis", "E0") == ()


def test_closure_report_fails_closed_on_missing_item_and_evidence() -> None:
    report = completed_report()
    missing = report["items"].pop()
    report["items"][0]["evidence"] = ""
    report["invalidation_identity"] = closure_invalidation_identity(report)
    errors = " ".join(verify_closure_report(report, "analysis", "E0"))
    assert missing["id"] in errors
    assert "evidence is required" in errors


def test_not_applicable_requires_scientific_reason_and_evidence() -> None:
    report = completed_report()
    report["items"][0].update(
        status="not_applicable", evidence="review/e0.md", not_applicable_reason=""
    )
    report["invalidation_identity"] = closure_invalidation_identity(report)
    errors = " ".join(verify_closure_report(report, "analysis", "E0"))
    assert "not_applicable_reason is required" in errors


def test_closure_report_detects_stale_checklist_and_invalidation_identity() -> None:
    report = completed_report()
    report["checklist_hash"] = "d" * 64
    errors = " ".join(verify_closure_report(report, "analysis", "E0"))
    assert "checklist_hash is stale" in errors
    assert "invalidation_identity is stale" in errors


def test_closure_report_rejects_owner_as_reviewer_and_failed_test() -> None:
    report = completed_report()
    report["reviewer"] = report["owner"]
    report["tests"][0]["result"] = "fail"
    report["invalidation_identity"] = closure_invalidation_identity(report)
    errors = " ".join(verify_closure_report(report, "analysis", "E0"))
    assert "reviewer must be distinct from owner" in errors
    assert "result must be pass" in errors


def test_cli_emits_and_verifies_node_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "e0-closure.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "research_action_preflight.py",
            "analysis",
            "--node",
            "E0",
            "--emit-report-template",
            str(report_path),
        ],
    )
    assert main() == 0
    assert json.loads(report_path.read_text())["node"] == "E0"

    report = completed_report()
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "research_action_preflight.py",
            "analysis",
            "--node",
            "E0",
            "--verify-report",
            str(report_path),
        ],
    )
    assert main() == 0
    assert "closes E0" in capsys.readouterr().out

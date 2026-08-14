#!/usr/bin/env python3
"""Route a research action through the live graph before files are mutated."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "docs" / "findings-freeze.md"
CHECKLIST = ROOT / "docs" / "research-node-checklists.md"


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path} has no frontmatter")
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return values
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    raise ValueError(f"{path} has unterminated frontmatter")


ROUTES = {
    "operations": "Apply the durable supervision, observability, sync and ETA checklist.",
    "literature": "Apply the venue or domain source checklist to one named use.",
    "data": "Apply the purpose-bound data checklist to the named estimand.",
    "analysis": "Apply the design, exploration and empirics checklists to the current J0 release.",
    "deck": "Apply the deck checklist and the persistent visual backlog to the current J1 packets.",
    "prose": "Apply the paper checklist to the complete manuscript and current J1 packets.",
    "review": "Apply one independent challenge or submission-freeze checklist to a frozen object.",
    "repository": "Apply the repository ownership, consumer and reproducibility checklist.",
}

ACTION_SECTIONS = {
    "operations": ("O. Operations and supervision",),
    "literature": ("A. Venue and talk benchmark", "B. Domain literature"),
    "data": ("D1. Purpose-bound input contract", "D2. Certification and material repair", "D3. Analysis panel", "J0. Purpose-bound data release"),
    "analysis": ("B. Domain literature", "C. Estimand and measurement", "K. Ideation", "E0. Exploration and mechanism search", "E1. Claim-specific lock", "F. Registered empirics", "J1. Finding admission"),
    "deck": ("A. Venue and talk benchmark", "B. Domain literature", "G. Scientific interpretation and paper spine", "H. Live deck", "J2-deck. Deck certificate"),
    "prose": ("A. Venue and talk benchmark", "B. Domain literature", "G. Scientific interpretation and paper spine", "P0. Working-paper prose", "P1. Final integrative paper edit", "J2-paper. Paper certificate"),
    "review": ("I. Independent challenge", "J3. Submission freeze"),
    "repository": ("R. Repository and reproducibility",),
}

COMMON_SECTIONS = ("Universal closure envelope",)
REPORT_SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def checklist_sections(path: Path = CHECKLIST) -> dict[str, tuple[str, ...]]:
    """Read the canonical node checklist without copying its rules into code."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current and line.startswith("- "):
            sections[current].append(line[2:].strip())
    return {name: tuple(items) for name, items in sections.items()}


def prose_gate(state: dict[str, str]) -> tuple[bool, str]:
    """Return the live prose permission without collapsing evidence tiers."""
    node = state.get("prose_node", "closed").lower()
    if node == "open":
        return True, "ALLOWED: prose node P is open"
    if node == "tiered":
        return True, (
            "ALLOWED-TIERED: write publication-standard prose for the question, "
            "setting, mechanisms, and certified route-only facts. Keep final cost, "
            "turnover, persistence, LP-return, and other exact-state coefficient "
            "sentences out until their own evidence locks."
        )
    return False, (
        "BLOCKED: prose node P is closed. Develop the economic argument in "
        "docs/paper-spine.md and leave paper/ unchanged. Do not perform term "
        "substitution or create a second style memo."
    )


def regression_checks(action: str, node: str | None = None) -> tuple[str, ...]:
    sections = checklist_sections()
    if node is None:
        selected = ACTION_SECTIONS[action]
    else:
        matches = tuple(name for name in ACTION_SECTIONS[action] if name.split(".", 1)[0].lower() == node.lower())
        if len(matches) != 1:
            raise ValueError(f"node {node} is not a unique member of action {action}")
        selected = matches
    names = (*COMMON_SECTIONS, *selected)
    missing = [name for name in names if name not in sections]
    if missing:
        raise ValueError(f"canonical node checklist lacks sections: {', '.join(missing)}")
    return tuple(item for name in names for item in sections[name])


def selected_sections(action: str, node: str) -> tuple[str, ...]:
    """Return the universal envelope and one exact graph node."""
    matches = tuple(
        name
        for name in ACTION_SECTIONS[action]
        if name.split(".", 1)[0].lower() == node.lower()
    )
    if len(matches) != 1:
        raise ValueError(f"node {node} is not a unique member of action {action}")
    return (*COMMON_SECTIONS, *matches)


def _section_id(section: str) -> str:
    prefix = section.split(".", 1)[0].lower()
    return re.sub(r"[^a-z0-9]+", "-", prefix).strip("-")


def checklist_item_ids(action: str, node: str) -> tuple[str, ...]:
    """Derive stable local IDs without copying checklist prose into reports."""
    sections = checklist_sections()
    names = selected_sections(action, node)
    missing = [name for name in names if name not in sections]
    if missing:
        raise ValueError(f"canonical node checklist lacks sections: {', '.join(missing)}")
    return tuple(
        f"{_section_id(name)}:{index:02d}"
        for name in names
        for index, _item in enumerate(sections[name], start=1)
    )


def checklist_hash(action: str, node: str) -> str:
    """Hash the exact current source rules selected for one node."""
    sections = checklist_sections()
    payload = [
        {"section": name, "items": list(sections[name])}
        for name in selected_sections(action, node)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def closure_report_template(action: str, node: str) -> dict[str, Any]:
    """Build a fillable closure report tied to the live canonical checklist."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "package_id": "",
        "action": action,
        "node": node,
        "requirement_ids": [],
        "owner": "",
        "immutable_inputs": [{"path": "", "sha256": ""}],
        "upstream_generation": "",
        "predecessor_certificate": {"path": "", "sha256": ""},
        "outputs": [{"path": "", "sha256": ""}],
        "allowed_claim": "",
        "tests": [{"command": "", "result": "", "evidence": ""}],
        "stop_rule": "",
        "downstream_join": "",
        "reviewer": "",
        "checklist_hash": checklist_hash(action, node),
        "invalidation_identity": "",
        "items": [
            {
                "id": item_id,
                "status": "",
                "evidence": "",
                "not_applicable_reason": "",
            }
            for item_id in checklist_item_ids(action, node)
        ],
    }


def closure_invalidation_identity(report: dict[str, Any]) -> str:
    """Bind every field whose change must reopen an accepted package."""
    fields = {
        "action": report.get("action"),
        "node": report.get("node"),
        "requirement_ids": report.get("requirement_ids"),
        "immutable_inputs": report.get("immutable_inputs"),
        "upstream_generation": report.get("upstream_generation"),
        "predecessor_certificate": report.get("predecessor_certificate"),
        "outputs": report.get("outputs"),
        "allowed_claim": report.get("allowed_claim"),
        "checklist_hash": report.get("checklist_hash"),
    }
    encoded = json.dumps(
        fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_hashed_paths(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{field} must be a non-empty list")
        return
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{field}[{index}] must be an object")
            continue
        if not _nonempty_string(item.get("path")):
            errors.append(f"{field}[{index}].path is required")
        if not isinstance(item.get("sha256"), str) or not SHA256_RE.fullmatch(item["sha256"]):
            errors.append(f"{field}[{index}].sha256 must be a lowercase SHA-256")


def verify_closure_report(
    report: dict[str, Any], action: str, node: str
) -> tuple[str, ...]:
    """Return every reason a closure report fails the current node contract."""
    errors: list[str] = []
    required_strings = (
        "package_id",
        "owner",
        "upstream_generation",
        "allowed_claim",
        "stop_rule",
        "downstream_join",
        "reviewer",
    )
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {REPORT_SCHEMA_VERSION}")
    if report.get("action") != action:
        errors.append(f"action must be {action}")
    if report.get("node") != node:
        errors.append(f"node must be {node}")
    for field in required_strings:
        if not _nonempty_string(report.get(field)):
            errors.append(f"{field} is required")
    if report.get("owner") == report.get("reviewer") and _nonempty_string(report.get("owner")):
        errors.append("reviewer must be distinct from owner")

    requirement_ids = report.get("requirement_ids")
    if (
        not isinstance(requirement_ids, list)
        or not requirement_ids
        or any(not _nonempty_string(item) for item in requirement_ids)
        or len(requirement_ids) != len(set(requirement_ids))
    ):
        errors.append("requirement_ids must be a non-empty list of unique strings")

    _validate_hashed_paths(report.get("immutable_inputs"), "immutable_inputs", errors)
    _validate_hashed_paths(report.get("outputs"), "outputs", errors)
    predecessor = report.get("predecessor_certificate")
    if not isinstance(predecessor, dict):
        errors.append("predecessor_certificate must be an object")
    else:
        if not _nonempty_string(predecessor.get("path")):
            errors.append("predecessor_certificate.path is required")
        if not isinstance(predecessor.get("sha256"), str) or not SHA256_RE.fullmatch(predecessor["sha256"]):
            errors.append("predecessor_certificate.sha256 must be a lowercase SHA-256")

    tests = report.get("tests")
    if not isinstance(tests, list) or not tests:
        errors.append("tests must be a non-empty list")
    else:
        for index, test in enumerate(tests):
            if not isinstance(test, dict):
                errors.append(f"tests[{index}] must be an object")
                continue
            if not _nonempty_string(test.get("command")):
                errors.append(f"tests[{index}].command is required")
            if test.get("result") != "pass":
                errors.append(f"tests[{index}].result must be pass")
            if not _nonempty_string(test.get("evidence")):
                errors.append(f"tests[{index}].evidence is required")

    current_hash = checklist_hash(action, node)
    if report.get("checklist_hash") != current_hash:
        errors.append("checklist_hash is stale")

    expected_ids = checklist_item_ids(action, node)
    items = report.get("items")
    if not isinstance(items, list):
        errors.append("items must be a list")
    else:
        actual_ids = [item.get("id") for item in items if isinstance(item, dict)]
        if len(items) != len(actual_ids):
            errors.append("every checklist item must be an object")
        if len(actual_ids) != len(set(actual_ids)):
            errors.append("checklist item IDs must be unique")
        missing = [item_id for item_id in expected_ids if item_id not in actual_ids]
        extra = [item_id for item_id in actual_ids if item_id not in expected_ids]
        if missing:
            errors.append(f"missing checklist items: {', '.join(missing)}")
        if extra:
            errors.append(f"stale or foreign checklist items: {', '.join(extra)}")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            item_id = item.get("id", f"index {index}")
            status = item.get("status")
            if status not in {"pass", "not_applicable"}:
                errors.append(f"{item_id}.status must be pass or not_applicable")
            if not _nonempty_string(item.get("evidence")):
                errors.append(f"{item_id}.evidence is required")
            reason = item.get("not_applicable_reason")
            if status == "not_applicable" and not _nonempty_string(reason):
                errors.append(f"{item_id}.not_applicable_reason is required")

    expected_identity = closure_invalidation_identity(report)
    if report.get("invalidation_identity") != expected_identity:
        errors.append(
            "invalidation_identity is stale; expected " + expected_identity
        )
    return tuple(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=sorted(ROUTES))
    parser.add_argument("--node", help="one exact node ID within the selected action, for example E0 or P0")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--emit-report-template",
        metavar="PATH",
        help="write a node closure JSON template; use - for stdout",
    )
    operation.add_argument(
        "--verify-report",
        metavar="PATH",
        help="verify a completed node closure JSON report",
    )
    operation.add_argument(
        "--print-invalidation-identity",
        metavar="PATH",
        help="print the invalidation identity for a filled report",
    )
    args = parser.parse_args()
    if (
        args.emit_report_template
        or args.verify_report
        or args.print_invalidation_identity
    ):
        if not args.node:
            parser.error("a report operation requires --node")
        if args.emit_report_template:
            payload = json.dumps(
                closure_report_template(args.action, args.node),
                indent=2,
                ensure_ascii=False,
            ) + "\n"
            if args.emit_report_template == "-":
                print(payload, end="")
            else:
                Path(args.emit_report_template).write_text(payload, encoding="utf-8")
            return 0
        report_path = Path(args.verify_report or args.print_invalidation_identity)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if args.print_invalidation_identity:
            print(closure_invalidation_identity(report))
            return 0
        errors = verify_closure_report(report, args.action, args.node)
        if errors:
            print("BLOCKED: closure report failed")
            for error in errors:
                print(f"- {error}")
            return 2
        print(f"PASS: {report['package_id']} closes {args.node}")
        return 0

    state = frontmatter(FREEZE)
    print(f"freeze={state.get('freeze_status', '?')}")
    for stream in ("operations", "data", "methods", "paper", "deck", "review"):
        print(f"{stream}={state.get(f'{stream}_stream', '?')}")
    print(f"meeting={state.get('meeting_edge', '?')}")
    print(ROUTES[args.action])
    print("PRIOR-CORRECTION REGRESSION CHECK:")
    for check in regression_checks(args.action, args.node):
        print(f"- {check}")
    if args.action == "prose":
        allowed, message = prose_gate(state)
        print(message)
        if not allowed:
            return 2
    print(f"ALLOWED: {args.action} action is inside the current graph boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

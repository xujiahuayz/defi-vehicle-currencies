"""Canonical admission policy for the curated research-source corpus."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


ADMITTED_DECISIONS = frozenset(
    {"include_scholarly", "include_exception", "include_primary_technical"}
)
DECISION_PUBLICATION_CLASSES = {
    "include_scholarly": frozenset({"peer_reviewed_finance_economics"}),
    "include_exception": frozenset(
        {
            "peer_reviewed_adjacent",
            "published_adjacent_editorial",
            "institutional_working_paper",
            "working_paper",
        }
    ),
    "include_primary_technical": frozenset({"primary_technical"}),
}
REQUIRED_FIELDS = frozenset(
    {
        "key",
        "title",
        "decision",
        "publication_class",
        "publication_status",
        "author_field_credibility",
        "scholarly_uptake",
        "finance_relevance",
        "evidence_role",
        "boundary",
        "technical_integrity",
        "rationale",
        "supporting_source_version",
        "finance_native",
        "reviewed_at",
    }
)


def _records_by_key(records: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    by_key: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    if not isinstance(records, list):
        return by_key, duplicates
    for record in records:
        if not isinstance(record, dict) or not str(record.get("key") or "").strip():
            continue
        key = str(record["key"])
        if key in by_key:
            duplicates.append(key)
        by_key[key] = record
    return by_key, sorted(set(duplicates))


def load_source_admission(path: Path) -> dict[str, Any]:
    """Load the admission ledger, returning an invalid empty object on failure."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def validate_source_admission(
    keys: Iterable[str],
    ledger: dict[str, Any],
) -> tuple[bool, str]:
    """Require an explicit, complete, affirmative decision for every source key."""
    required = set(keys)
    admitted_records, admitted_duplicates = _records_by_key(
        ledger.get("admitted_records", []) if isinstance(ledger, dict) else []
    )
    rejected_records, rejected_duplicates = _records_by_key(
        ledger.get("rejected_or_retired_candidates", [])
        if isinstance(ledger, dict)
        else []
    )
    cross_registered = sorted(set(admitted_records) & set(rejected_records))
    rejected_incomplete = sorted(
        key
        for key, record in rejected_records.items()
        if record.get("decision") != "exclude"
        or not isinstance(record.get("red_flags"), list)
        or not record["red_flags"]
        or not str(record.get("reentry_condition") or "").strip()
    )
    missing = sorted(required - set(admitted_records) - set(rejected_records))
    incomplete = sorted(
        key
        for key in required & set(admitted_records)
        if REQUIRED_FIELDS - set(admitted_records[key])
        or any(
            admitted_records[key].get(field) is None
            or (
                not isinstance(admitted_records[key].get(field), bool)
                and not str(admitted_records[key].get(field) or "").strip()
            )
            for field in REQUIRED_FIELDS
        )
    )
    rejected = sorted(
        (required & set(rejected_records))
        | {
            key
            for key in required & set(admitted_records)
            if admitted_records[key].get("decision") not in ADMITTED_DECISIONS
        }
    )
    incompatible = sorted(
        key
        for key in required & set(admitted_records)
        if admitted_records[key].get("decision") in ADMITTED_DECISIONS
        and admitted_records[key].get("publication_class")
        not in DECISION_PUBLICATION_CLASSES[admitted_records[key]["decision"]]
    )
    passed = bool(
        ledger.get("schema_version") == "1.0.0"
        and not missing
        and not incomplete
        and not rejected
        and not incompatible
        and not admitted_duplicates
        and not rejected_duplicates
        and not cross_registered
        and not rejected_incomplete
    )
    admitted = len(required) - len(
        set(missing) | set(incomplete) | set(rejected) | set(incompatible)
    )
    return passed, (
        f"sources={len(required)}; admitted={admitted}; missing={missing or 'none'}; "
        f"incomplete={incomplete or 'none'}; rejected={rejected or 'none'}; "
        f"incompatible={incompatible or 'none'}; duplicates="
        f"{sorted(set(admitted_duplicates) | set(rejected_duplicates)) or 'none'}; "
        f"cross_registered={cross_registered or 'none'}; "
        f"rejected_incomplete={rejected_incomplete or 'none'}"
    )


def require_source_admission(keys: Iterable[str], ledger: dict[str, Any]) -> None:
    """Stop acquisition before network or filesystem work if admission is unresolved."""
    passed, detail = validate_source_admission(keys, ledger)
    if not passed:
        raise ValueError(f"source admission failed: {detail}")

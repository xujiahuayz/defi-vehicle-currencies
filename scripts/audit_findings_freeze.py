#!/usr/bin/env python3
"""Audit whether the project may leave findings work and enter prose refinement."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
from ddvc.asset_types import TYPES
from ddvc.analysis.transaction_frontier import (
    MIN_CHOSEN_REPRODUCTION,
    chosen_reproduction_share,
)
from ddvc.calendar import RESEARCH_SAMPLE_END, RESEARCH_SAMPLE_START, calendar_days
from ddvc.fetch.sources import get_source
from ddvc.provenance import sidecar_path, verify
from ddvc.reconstruct import DEX_FAMILY, UNIFIED_QUALITY_PANEL
from ddvc.route_roles import VALUE_SUPPORT_COLUMNS
from ddvc.state_data import FAMILY_STREAMS
from ddvc.venue_corpus import JFE_VENUE_CARDS, JFE_VENUE_SOURCE_KEYS

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
EXTENT = ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"
INTERMEDIATION = ROOT / "data" / "processed" / "intermediation_by_type_daily.parquet"
CROSS_VENUE = ROOT / "data" / "processed" / "cross_venue_routing_daily.parquet"
TRANSACTION_FRONTIER = ROOT / "data" / "processed" / "transaction_state_frontier_audit.parquet"
TRANSACTION_FRONTIER_REJECTIONS = ROOT / "data" / "processed" / "transaction_state_frontier_audit_rejections.parquet"
TRANSACTION_FRONTIER_SUPPORT = ROOT / "output" / "exhibits" / "transaction_state_frontier_audit_support.jsonl"
V4 = ROOT / "data" / "raw" / "thegraph" / "uniswap_v4"
REFRESH = ROOT / "scripts" / "refresh_panel_dependents.py"
STATE = ROOT / "docs" / "findings-freeze.md"
SPECIFICATION_LOCK = ROOT / "docs" / "specification-lock.json"
MODEL_LEDGER = ROOT / "docs" / "model-ledger.json"
LITERATURE_AUDIT = ROOT / "docs" / "literature-audit.md"
LITERATURE_BIB = ROOT / "literature" / "vehicle-currencies.bib"
LITERATURE_SOURCES = ROOT / "literature" / "pdf-sources.json"
LITERATURE_TEXT = ROOT / "literature" / "text"
LITERATURE_SOURCE_NOTES = ROOT / "literature" / "source-notes"
MARKET_STATE_QUALITY = ROOT / "data" / "processed" / "market_state_quality.parquet"
CANONICAL_EMPIRICAL_CONSUMERS = (
    "scripts/build_transaction_state_frontier.py",
    "scripts/build_counterfactual_dominance.py",
    "scripts/build_rent_incidence_panel.py",
    "scripts/validate_curve_quoter.py",
    "scripts/validate_weighted_quoter.py",
    "scripts/run_balancer_weighted_quote_extension.py",
    "src/ddvc/pricing/tick_replay.py",
    "src/ddvc/pricing/v2_replay.py",
)
RAW_PROVIDER_PATTERNS = (
    "data/raw/thegraph",
    '"raw" / "thegraph"',
    "from ddvc.fetch.raw import",
    "import ddvc.fetch.raw",
    "gzip.open(",
    "raw_stream_path(",
)
PAPER_SECTIONS = ROOT / "paper" / "sections"
LITERATURE_CARD_REQUIRED_FIELDS = frozenset(
    {
        "status",
        "roles",
        "source",
        "source key",
        "version",
        "companions",
        "uses",
        "scientific",
        "structure",
        "depth",
        "breadth",
        "optics",
        "locations",
        "implication",
        "first reader",
        "independent",
    }
)
LITERATURE_CARD_PLACEHOLDERS = frozenset({"", "todo", "tbd", "n/a"})
LITERATURE_CARD_EVIDENCE_FIELDS = frozenset(
    {
        "source",
        "source key",
        "version",
        "companions",
        "uses",
        "scientific",
        "structure",
        "depth",
        "breadth",
        "optics",
        "locations",
        "implication",
        "first reader",
    }
)
GRAPH_FIELDS = ("active_node", "parent_loop", "next_edge", "prose_node")
LOCKED_CLAIM_STATUSES = {
    "enter_fgh_primary",
    "enter_fgh_foundation",
    "enter_fgh_mechanism",
    "enter_fgh_companion",
}
MODEL_LEDGER_STATUSES = {"admissible", "diagnostic", "withheld", "retired"}


def _manifest(path: Path) -> dict:
    sidecar = sidecar_path(path)
    return json.loads(sidecar.read_text()) if sidecar.exists() else {}


def _nonempty_v4_days() -> set[str]:
    days: set[str] = set()
    prefix = "uniswap_v4_swaps_"
    suffix = ".jsonl.gz"
    for path in V4.glob(f"{prefix}*{suffix}"):
        with gzip.open(path, "rb") as handle:
            if handle.read(1):
                days.add(path.name[len(prefix):-len(suffix)])
    return days


def parse_state_frontmatter(text: str) -> dict[str, str]:
    """Read the scalar workflow state from the document's leading frontmatter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        name, separator, value = line.partition(":")
        if separator and name.strip():
            fields[name.strip()] = value.strip()
    return {}


def _state_fields() -> dict[str, str]:
    return parse_state_frontmatter(STATE.read_text()) if STATE.exists() else {}


def cited_bibliography_keys(paths: list[Path]) -> set[str]:
    """Extract every bibliography key used by the manuscript's cite commands."""
    keys: set[str] = set()
    for path in paths:
        for group in re.findall(r"\\cite\w*\{([^}]+)\}", path.read_text()):
            keys.update(key.strip() for key in group.split(",") if key.strip())
    return keys


def parse_literature_cards(text: str) -> dict[str, dict[str, str]]:
    """Parse mechanically auditable fields from level-three paper cards."""
    matches = list(re.finditer(r"^###\s+(\S+)\s*$", text, flags=re.MULTILINE))
    cards: dict[str, dict[str, str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fields: dict[str, str] = {}
        for line in text[match.end():end].splitlines():
            field = re.match(r"^-\s+([^:]+):\s*(.+?)\s*$", line)
            if field:
                fields[field.group(1).strip().lower()] = field.group(2).strip()
        cards[match.group(1)] = fields
    return cards


def complete_literature_card(fields: dict[str, str]) -> bool:
    """Reject cards that omit an evidence axis or leave a placeholder behind."""
    fields_present = all(
        fields.get(field, "").strip().lower() not in LITERATURE_CARD_PLACEHOLDERS
        for field in LITERATURE_CARD_REQUIRED_FIELDS
    )
    evidence_written = all(
        fields.get(field, "").strip().lower() != "pending"
        for field in LITERATURE_CARD_EVIDENCE_FIELDS
    )
    return fields_present and evidence_written


def published_venue_version(fields: dict[str, str]) -> bool:
    """A published venue cannot be calibrated from a pre-publication layout."""
    return fields.get("version", "").strip().lower().startswith("published ")


def companion_source_keys(fields: dict[str, str]) -> set[str]:
    """Read canonical companion bibliography keys from the card disposition."""
    return set(re.findall(r"`([^`]+)`", fields.get("companions", "")))


def literature_source_key(fields: dict[str, str]) -> str:
    """Resolve scientific and venue cards to one canonical main-paper source set."""
    return fields.get("source key", "").strip()


def materialized_companion_sources() -> dict[str, bool]:
    """Report whether each registered source key has durable extracted text or a source note."""
    bib_keys = set(re.findall(r"@\w+\s*\{\s*([^,\s]+)", LITERATURE_BIB.read_text()))
    try:
        source_keys = set(json.loads(LITERATURE_SOURCES.read_text()).get("sources", {}))
    except (json.JSONDecodeError, OSError):
        source_keys = set()
    return {
        key: source_materialized(
            key,
            bib_keys=bib_keys,
            source_keys=source_keys,
            text_root=LITERATURE_TEXT,
            note_root=LITERATURE_SOURCE_NOTES,
        )
        for key in bib_keys | source_keys
    }


def source_materialized(
    key: str,
    *,
    bib_keys: set[str],
    source_keys: set[str],
    text_root: Path,
    note_root: Path,
) -> bool:
    """Require an exact-key durable artifact; a prefix-sharing companion is insufficient."""
    return bool(
        key in bib_keys
        and key in source_keys
        and (
            any(text_root.glob(f"*-{key}-*.txt"))
            or any(note_root.glob(f"*-{key}.md"))
        )
    )


def literature_source_sets() -> dict[str, dict]:
    """Load the auditable discovery record for each required paper source set."""
    try:
        source_sets = json.loads(LITERATURE_SOURCES.read_text()).get("source_sets", {})
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        str(key): value
        for key, value in source_sets.items()
        if isinstance(value, dict)
    }


def card_source_text(fields: dict[str, str]) -> str | None:
    """Resolve a card's saved PDF to its tracked page-delimited extract."""
    source = fields.get("source", "").strip()
    if not source.startswith("literature/papers/") or not source.endswith(".pdf"):
        return None
    path = LITERATURE_TEXT / f"{Path(source).stem}.txt"
    return path.read_text(errors="replace") if path.exists() else None


def companion_sources_closed(
    fields: dict[str, str],
    *,
    materialized: dict[str, bool] | None = None,
    source_text: str | None = None,
    source_set: dict | None = None,
) -> bool:
    """Require explicit disposition and, at the live gate, materialized full source-set evidence."""
    if materialized is not None and source_text is None:
        return False
    if source_set is not None:
        main_key = source_set.get("main")
        if main_key != literature_source_key(fields):
            return False
        if not materialized or not source_set_record_closed(source_set, materialized):
            return False
        recorded_companions = source_set.get("companions")
        if not isinstance(recorded_companions, list) or any(not isinstance(key, str) for key in recorded_companions):
            return False
        if set(recorded_companions) != companion_source_keys(fields):
            return False
    disposition = fields.get("companions", "").strip().lower()
    if disposition.startswith("complete:"):
        if materialized is None:
            return True
        keys = companion_source_keys(fields)
        return bool(keys) and all(materialized.get(key, False) for key in keys)
    if disposition.startswith("none:"):
        if source_text is None:
            return True
        return not re.search(
            r"\b(?:online|internet|web)\s+appendix\b"
            r"|\b(?:the|in\s+the)\s+supplementary\s+material\b"
            r"|\bsupplementary\s+(?:material|data)\s+associated\s+with\s+this\s+(?:article|paper)\b"
            r"|\bdata\s+appendix\b"
            r"|\bseparate(?:ly)?\s+(?:hosted\s+)?supplement(?:ary|al)?\b",
            source_text,
            flags=re.IGNORECASE,
        )
    return False


def source_set_record_closed(
    source_set: dict,
    materialized: dict[str, bool],
    *,
    root: Path = ROOT,
) -> bool:
    """Validate discovery coverage and durable artifacts independently of prose cards."""
    checks = source_set.get("checks", {})
    companions = source_set.get("companions")
    main_key = source_set.get("main")
    article = checks.get("article") if isinstance(checks, dict) else None
    article_path = (root / article).resolve() if isinstance(article, str) else None
    text_root = (root / "literature" / "text").resolve()
    tracked_article = bool(
        article_path
        and article_path.is_relative_to(text_root)
        and article_path.is_file()
    )
    return bool(
        source_set.get("status") == "complete"
        and isinstance(main_key, str)
        and isinstance(checks, dict)
        and all(checks.get(kind) for kind in ("article", "publisher_or_doi", "author_or_repository"))
        and isinstance(companions, list)
        and all(isinstance(key, str) for key in companions)
        and (tracked_article or materialized.get(main_key, False))
        and all(materialized.get(key, False) for key in companions)
        and non_text_dispositions_closed(source_set, root=root)
    )


def non_text_dispositions_closed(
    source_set: dict,
    *,
    root: Path = ROOT,
) -> bool:
    """Bind every declared code/data URL to an inspected durable disposition."""
    sources = source_set.get("non_text_companions", [])
    dispositions = source_set.get("non_text_dispositions", [])
    if not isinstance(sources, list) or any(not isinstance(url, str) for url in sources):
        return False
    if not sources:
        return dispositions in (None, [])
    if (
        not isinstance(dispositions, list)
        or not dispositions
        or len(sources) != len(set(sources))
    ):
        return False

    source_note_root = (root / "literature" / "source-notes").resolve()
    paper_root = (root / "literature" / "papers").resolve()
    covered: list[str] = []
    for disposition in dispositions:
        if not isinstance(disposition, dict):
            return False
        disposition_sources = disposition.get("sources")
        if (
            not isinstance(disposition_sources, list)
            or not disposition_sources
            or any(not isinstance(url, str) for url in disposition_sources)
        ):
            return False
        covered.extend(disposition_sources)

        note = disposition.get("note")
        note_path = (root / note).resolve() if isinstance(note, str) else None
        if not (
            note_path
            and note_path.is_relative_to(source_note_root)
            and note_path.suffix == ".md"
            and note_path.is_file()
        ):
            return False

        status = disposition.get("status")
        if status == "materialized":
            artifact = disposition.get("artifact")
            artifact_path = (root / artifact).resolve() if isinstance(artifact, str) else None
            expected_bytes = disposition.get("bytes")
            if not (
                artifact_path
                and artifact_path.is_relative_to(paper_root)
                and artifact_path.is_file()
                and isinstance(expected_bytes, int)
                and expected_bytes > 0
                and artifact_path.stat().st_size == expected_bytes
                and re.fullmatch(r"[0-9a-f]{64}", str(disposition.get("sha256", "")))
                and file_sha256(artifact_path) == disposition.get("sha256")
            ):
                return False
        elif status == "unavailable":
            if not str(disposition.get("reason", "")).strip():
                return False
        else:
            return False

    return bool(
        len(covered) == len(set(covered))
        and set(covered) == set(sources)
    )


def file_sha256(path: Path) -> str:
    """Hash a package without loading a potentially large research dataset into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_literature_audit(
    text: str,
    cited_keys: set[str],
    venue_cards: set[str],
    *,
    verify_source_sets: bool = False,
) -> tuple[bool, str]:
    """Require individual full-text cards before findings may freeze."""
    frontmatter = parse_state_frontmatter(text)
    cards = parse_literature_cards(text)
    required_cards = cited_keys | venue_cards
    materialized = materialized_companion_sources() if verify_source_sets else None
    source_sets = literature_source_sets() if verify_source_sets else {}
    required_source_keys = cited_keys | {
        JFE_VENUE_SOURCE_KEYS[key]
        for key in venue_cards
        if key in JFE_VENUE_SOURCE_KEYS
    }
    closed_source_sets = {
        key
        for key in required_source_keys
        if key in source_sets
        and materialized is not None
        and source_set_record_closed(source_sets[key], materialized)
    }
    complete_cards = {
        key
        for key in required_cards
        if key in cards
        and complete_literature_card(cards[key])
        and (
            not verify_source_sets
            or literature_source_key(cards[key]) in source_sets
        )
        and companion_sources_closed(
            cards[key],
            materialized=materialized,
            source_text=card_source_text(cards[key]) if verify_source_sets else None,
            source_set=(
                source_sets.get(literature_source_key(cards[key]))
                if verify_source_sets
                else None
            ),
        )
    }
    verified_citations = {
        key
        for key in cited_keys
        if cards.get(key, {}).get("status")
        in {"claim-verified", "independently-re-read"}
    }
    read_venues = {
        key
        for key in venue_cards
        if cards.get(key, {}).get("status")
        in {"full-text-read", "claim-verified", "independently-re-read"}
        and published_venue_version(cards[key])
    }
    central = {
        key
        for key, fields in cards.items()
        if "central" in {
            role.strip() for role in fields.get("roles", "").split(",")
        }
    }
    independent = {
        key for key in central if cards[key].get("independent") == "complete"
    }
    passed = bool(
        frontmatter.get("status") == "complete"
        and (not verify_source_sets or closed_source_sets == required_source_keys)
        and complete_cards == required_cards
        and verified_citations == cited_keys
        and read_venues == venue_cards
        and independent == central
    )
    return passed, (
        f"status={frontmatter.get('status') or 'missing'}; "
        f"source-sets={len(closed_source_sets)}/{len(required_source_keys)}; "
        f"five-axis-cards={len(complete_cards)}/{len(required_cards)}; "
        f"cited={len(verified_citations)}/{len(cited_keys)}; "
        f"venue={len(read_venues)}/{len(venue_cards)}; "
        f"independent={len(independent)}/{len(central)}"
    )


def graph_status(fields: dict[str, str]) -> str:
    """One-line status contract for terminal, chat and automated logs."""
    return (
        f"active={fields.get('active_node') or 'missing'}; "
        f"parent={fields.get('parent_loop') or 'missing'}; "
        f"next={fields.get('next_edge') or 'missing'}; "
        f"prose={fields.get('prose_node') or 'missing'}"
    )


def validate_canonical_consumer_boundary(
    paths: tuple[str, ...] | None = None,
) -> tuple[bool, str]:
    """Keep active estimators and quote consumers behind the node-D data boundary."""
    if paths is None:
        paths = registered_empirical_consumers()
    violations: list[str] = []
    missing: list[str] = []
    for relative in paths:
        path = ROOT / relative
        if not path.exists():
            missing.append(relative)
            continue
        source = path.read_text(encoding="utf-8")
        matched = [pattern for pattern in RAW_PROVIDER_PATTERNS if pattern in source]
        if matched:
            violations.append(f"{relative}:{','.join(matched)}")
    passed = not violations and not missing
    return passed, (
        f"consumers={len(paths)}; violations={violations or 'none'}; "
        f"missing={missing or 'none'}"
    )


def _artifact_producer(relative: str) -> str | None:
    manifest = sidecar_path(ROOT / relative)
    if not manifest.exists():
        return None
    try:
        producer = json.loads(manifest.read_text(encoding="utf-8")).get("script")
    except (json.JSONDecodeError, OSError):
        return None
    return str(producer) if producer else None


def registered_empirical_consumers() -> tuple[str, ...]:
    """Resolve active claim/model producers from their registered artifacts."""
    consumers = set(CANONICAL_EMPIRICAL_CONSUMERS)
    try:
        specification = json.loads(SPECIFICATION_LOCK.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        specification = {}
    for claim in specification.get("claims", []):
        if not isinstance(claim, dict) or str(claim.get("status", "")).startswith("retired"):
            continue
        for artifact in claim.get("outputs", []):
            producer = _artifact_producer(str(artifact))
            if producer:
                consumers.add(producer)
    try:
        ledger = json.loads(MODEL_LEDGER.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        ledger = {}
    for family in ledger.get("families", []):
        if not isinstance(family, dict) or family.get("status") == "retired":
            continue
        for artifact in family.get("artifacts", []):
            producer = _artifact_producer(str(artifact))
            if producer:
                consumers.add(producer)
    return tuple(sorted(consumers))


def expected_market_state_keys(
    start: str = RESEARCH_SAMPLE_START,
    end: str = RESEARCH_SAMPLE_END,
) -> set[tuple[str, str, str]]:
    """Exact family-venue-day perimeter required by the node-D gate."""
    keys: set[tuple[str, str, str]] = set()
    for family, venues in FAMILY_STREAMS.items():
        for venue in venues:
            lower = max(start, get_source(venue).genesis.strftime("%Y%m%d"))
            keys.update((family, venue, day) for day in calendar_days(lower, end))
    return keys


def expected_unified_route_venue_days(
    start: str = RESEARCH_SAMPLE_START,
    end: str = RESEARCH_SAMPLE_END,
) -> int:
    """Exact routed-venue perimeter, independent of observed source files."""
    return sum(
        len(calendar_days(max(start, get_source(venue).genesis.strftime("%Y%m%d")), end))
        for venue in DEX_FAMILY
    )


def validate_unified_route_layer(
    quality: pd.DataFrame,
    *,
    provenance_status: str,
) -> tuple[bool, str]:
    """Require every calendar day and every launched routed venue before analysis."""
    expected_days = set(calendar_days(RESEARCH_SAMPLE_START, RESEARCH_SAMPLE_END))
    observed_rows = quality.get("day", pd.Series(dtype=str)).astype(str).tolist()
    observed_days = set(observed_rows)
    duplicate_days = len(observed_rows) - len(observed_days)
    missing_days = expected_days - observed_days
    unexpected_days = observed_days - expected_days
    required = {
        "day",
        "expected_sources",
        "missing_sources",
        "conflicting_events",
        "malformed_rows",
        "passed",
    }
    missing_columns = sorted(required - set(quality.columns))
    expected_venue_days = expected_unified_route_venue_days()
    observed_venue_days = int(
        pd.to_numeric(quality.get("expected_sources", pd.Series(dtype=float)), errors="coerce").sum()
    )
    failed = int((~quality.get("passed", pd.Series(dtype=bool)).astype(bool)).sum())
    missing_sources = int(
        pd.to_numeric(quality.get("missing_sources", pd.Series(dtype=float)), errors="coerce").sum()
    )
    conflicts = int(
        pd.to_numeric(quality.get("conflicting_events", pd.Series(dtype=float)), errors="coerce").sum()
    )
    malformed = int(
        pd.to_numeric(quality.get("malformed_rows", pd.Series(dtype=float)), errors="coerce").sum()
    )
    passed = bool(
        not missing_columns
        and len(quality) == len(expected_days)
        and not missing_days
        and not unexpected_days
        and duplicate_days == 0
        and observed_venue_days == expected_venue_days
        and failed == 0
        and missing_sources == 0
        and conflicts == 0
        and malformed == 0
        and provenance_status == "ok"
    )
    return passed, (
        f"calendar_days={len(quality):,}/{len(expected_days):,}; "
        f"venue_days={observed_venue_days:,}/{expected_venue_days:,}; failed={failed:,}; "
        f"missing_sources={missing_sources:,}; conflicts={conflicts:,}; malformed={malformed:,}; "
        f"missing_days={len(missing_days):,}; unexpected_days={len(unexpected_days):,}; "
        f"duplicate_days={duplicate_days:,}; missing_columns={missing_columns or 'none'}; "
        f"provenance={provenance_status}"
    )


def validate_specification_lock(payload: dict) -> tuple[bool, str]:
    """Validate the canonical hash and minimum decision contract for node E."""
    declared_hash = str(payload.get("lock_hash") or "")
    hash_payload = {key: value for key, value in payload.items() if key != "lock_hash"}
    actual_hash = hashlib.sha256(
        json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    claims = payload.get("claims") or []
    ids = [str(claim.get("id") or "") for claim in claims if isinstance(claim, dict)]
    locked_claims = [
        claim
        for claim in claims
        if isinstance(claim, dict) and claim.get("status") in LOCKED_CLAIM_STATUSES
    ]
    required = {
        "id",
        "status",
        "role",
        "estimand",
        "sample",
        "unit",
        "dependent_variable",
        "transformation",
        "outlier_treatment",
        "inference",
        "mandatory_alternatives",
        "falsifier",
        "admissible_interpretation",
        "forbidden_interpretation",
        "inputs",
        "outputs",
    }
    incomplete = [
        str(claim.get("id") or "missing")
        for claim in locked_claims
        if required - set(claim)
    ]
    global_rules = payload.get("global_rules") or {}
    required_semantic_rules = {
        "vehicle_status",
        "vehicle_dominance",
        "cost_domination",
        "abstract_question",
    }
    missing_semantic_rules = sorted(
        key for key in required_semantic_rules if not str(global_rules.get(key) or "").strip()
    )
    passed = bool(
        payload.get("schema_version") == 1
        and declared_hash == actual_hash
        and len(ids) == len(claims)
        and len(ids) == len(set(ids))
        and len(locked_claims) >= 3
        and not incomplete
        and not missing_semantic_rules
    )
    detail = (
        f"hash={'ok' if declared_hash == actual_hash else 'mismatch'}; "
        f"claims={len(claims)}; locked={len(locked_claims)}; "
        f"incomplete={incomplete or 'none'}; "
        f"missing_semantic_rules={missing_semantic_rules or 'none'}"
    )
    return passed, detail


def validate_claim_input_layer(
    payload: dict,
    *,
    root: Path = ROOT,
    verifier=verify,
) -> tuple[bool, str]:
    """Require every registered non-retired claim input to be canonical and current."""
    inputs = sorted(
        {
            str(relative)
            for claim in payload.get("claims", [])
            if isinstance(claim, dict)
            and not str(claim.get("status", "")).startswith("retired")
            for relative in claim.get("inputs", [])
        }
    )
    raw_inputs = [relative for relative in inputs if relative.startswith("data/raw/")]
    missing = [relative for relative in inputs if not (root / relative).exists()]
    statuses = {
        relative: verifier(root / relative).get("status")
        for relative in inputs
        if relative not in missing and relative not in raw_inputs
    }
    stale = {relative: status for relative, status in statuses.items() if status != "ok"}
    passed = bool(inputs and not raw_inputs and not missing and not stale)
    return passed, (
        f"inputs={len(inputs)}; current={sum(status == 'ok' for status in statuses.values())}; "
        f"raw={raw_inputs or 'none'}; missing={missing or 'none'}; stale={stale or 'none'}"
    )
def validate_model_ledger(
    payload: dict,
    *,
    claim_ids: set[str],
) -> tuple[bool, str]:
    """Validate the one family-level count of executed empirical models."""
    families = payload.get("families") or []
    required = {
        "id",
        "claim_id",
        "estimator",
        "fixed_effects",
        "inference",
        "substantive_specifications",
        "diagnostic_specifications",
        "resampling_refits",
        "status",
        "artifacts",
        "note",
    }
    ids = [str(family.get("id") or "") for family in families if isinstance(family, dict)]
    incomplete = [
        str(family.get("id") or "missing")
        for family in families
        if not isinstance(family, dict) or required - set(family)
    ]
    invalid_status = [
        str(family.get("id") or "missing")
        for family in families
        if isinstance(family, dict)
        and family.get("status") not in MODEL_LEDGER_STATUSES
    ]
    invalid_counts = [
        str(family.get("id") or "missing")
        for family in families
        if isinstance(family, dict)
        and any(
            not isinstance(family.get(field), int) or family.get(field, -1) < 0
            for field in (
                "substantive_specifications",
                "diagnostic_specifications",
                "resampling_refits",
            )
        )
    ]
    unknown_live_claims = [
        str(family.get("id") or "missing")
        for family in families
        if isinstance(family, dict)
        and family.get("status") != "retired"
        and family.get("claim_id") not in claim_ids
    ]
    missing_artifacts = [
        artifact
        for family in families
        if isinstance(family, dict)
        for artifact in family.get("artifacts", [])
        if not (ROOT / str(artifact)).exists()
    ]
    reported = sum(
        int(family.get("substantive_specifications", 0))
        + int(family.get("diagnostic_specifications", 0))
        for family in families
        if isinstance(family, dict)
    )
    refits = sum(
        int(family.get("resampling_refits", 0))
        for family in families
        if isinstance(family, dict)
    )
    statuses = {
        status: sum(
            int(family.get("substantive_specifications", 0))
            + int(family.get("diagnostic_specifications", 0))
            for family in families
            if isinstance(family, dict) and family.get("status") == status
        )
        for status in sorted(MODEL_LEDGER_STATUSES)
    }
    passed = bool(
        payload.get("schema_version") == 1
        and ids
        and len(ids) == len(families)
        and len(ids) == len(set(ids))
        and not incomplete
        and not invalid_status
        and not invalid_counts
        and not unknown_live_claims
        and not missing_artifacts
    )
    detail = (
        f"families={len(families)}; reported={reported:,}; refits={refits:,}; "
        f"status={statuses}; incomplete={incomplete or 'none'}; "
        f"unknown_live_claims={unknown_live_claims or 'none'}; "
        f"missing_artifacts={missing_artifacts or 'none'}"
    )
    return passed, detail


def transaction_frontier_support_checks(
    support: pd.DataFrame,
    *,
    panel_rows: int,
    rejection_rows: int,
) -> list[tuple[str, bool, str]]:
    """Validate the fixed-calendar frontier funnel and chosen-output reproduction."""
    required = {
        "day",
        "scored_routes",
        "rejected_routes",
        "exact_venue_two_leg_routes",
        "invalid_realised_input",
        "invalid_realised_output",
        "invalid_chosen_output",
        "within_20pct_chosen_quote_available",
        "within_20pct_chosen_output_mismatch",
    }
    missing = sorted(required - set(support.columns))
    if missing:
        return [("transaction frontier support schema", False, f"missing={missing}")]
    days = sorted(support["day"].astype(str).unique())
    scored = int(pd.to_numeric(support["scored_routes"], errors="coerce").sum())
    rejected = int(pd.to_numeric(support["rejected_routes"], errors="coerce").sum())
    exact = int(
        pd.to_numeric(support["exact_venue_two_leg_routes"], errors="coerce").sum()
    )
    available = int(
        pd.to_numeric(
            support["within_20pct_chosen_quote_available"], errors="coerce"
        ).sum()
    )
    mismatches = int(
        pd.to_numeric(
            support["within_20pct_chosen_output_mismatch"], errors="coerce"
        ).sum()
    )
    reproduction = chosen_reproduction_share(available, mismatches)
    return [
        (
            "transaction frontier row contract",
            scored == panel_rows and rejected == rejection_rows and scored + rejected == exact,
            f"scored panel={panel_rows:,}; support={scored:,}; "
            f"rejections={rejection_rows:,}; support={rejected:,}; exact={exact:,}",
        ),
        (
            "transaction frontier chosen-output validation",
            reproduction >= MIN_CHOSEN_REPRODUCTION,
            f"coherent={available:,}; mismatches={mismatches:,}; pass={reproduction:.2%}",
        ),
        (
            "transaction frontier audit-day coverage",
            len(days) == 77 and days[0] == "20200214" and days[-1] == "20260615",
            f"days={len(days)}; range={days[0] if days else 'none'}..{days[-1] if days else 'none'}",
        ),
    ]


def route_measurement_invariants(
    intermediation: pd.DataFrame,
    cross_venue: pd.DataFrame,
    vehicle_daily: pd.DataFrame,
) -> list[tuple[str, bool, str]]:
    """Cross-family identities that must hold before route findings can freeze."""
    merged = intermediation.merge(
        cross_venue,
        on="date",
        how="outer",
        validate="one_to_one",
        indicator=True,
        suffixes=("_type", "_routing"),
    ).merge(
        vehicle_daily,
        on="date",
        how="outer",
        validate="one_to_one",
        indicator="_vehicle_merge",
    )

    def exact(left: pd.Series, right: pd.Series) -> bool:
        return bool(
            np.array_equal(
                pd.to_numeric(left, errors="coerce").to_numpy(),
                pd.to_numeric(right, errors="coerce").to_numpy(),
                equal_nan=True,
            )
        )

    def close(left: pd.Series, right: pd.Series) -> bool:
        return bool(
            np.allclose(
                pd.to_numeric(left, errors="coerce"),
                pd.to_numeric(right, errors="coerce"),
                rtol=1e-9,
                atol=1e-6,
                equal_nan=True,
            )
        )

    results: list[tuple[str, bool, str]] = []
    calendar_ok = bool(
        merged["_merge"].eq("both").all()
        and merged["_vehicle_merge"].eq("both").all()
    )
    results.append(
        ("route measurement calendars reconcile", calendar_ok, f"days={len(merged):,}")
    )
    route_identity = exact(
        merged["routes_intermediated"], merged["intermediated_routes"]
    )
    results.append(
        (
            "intermediated route counts reconcile",
            route_identity,
            f"routes={merged['routes_intermediated'].sum():,.0f}",
        )
    )
    split_identity = exact(
        merged["economic_multileg_routes"],
        merged["intermediated_routes"] + merged["direct_split_routes"],
    )
    sequence_identity = exact(
        merged["intermediated_routes"],
        merged["pure_sequential_routes"] + merged["mixed_indirect_routes"],
    )
    results.append(
        (
            "routing topology partitions reconcile",
            split_identity and sequence_identity,
            "multileg=intermediated+direct_split; intermediated=sequential+mixed",
        )
    )
    type_episode_total = sum(
        (merged[f"cnt_{asset_type}"] for asset_type in TYPES),
        start=pd.Series(0, index=merged.index, dtype="int64"),
    )
    episode_identity = exact(merged["episodes"], type_episode_total) and exact(
        merged["episodes"], merged["vehicle_intermediate_routes"]
    )
    results.append(
        (
            "intermediary episode counts reconcile",
            episode_identity,
            f"episodes={merged['episodes'].sum():,.0f}",
        )
    )
    value_columns = {
        "all_routes": "usd",
        **{support: f"usd_{support}" for support in VALUE_SUPPORT_COLUMNS},
    }
    values_ok = True
    details = []
    for support, prefix in value_columns.items():
        type_total = sum(
            (merged[f"{prefix}_{asset_type}"] for asset_type in TYPES),
            start=pd.Series(0.0, index=merged.index),
        )
        vehicle_column = (
            "vehicle_intermediate_usd"
            if support == "all_routes"
            else f"vehicle_intermediate_usd_{support}"
        )
        matched = close(type_total, merged[vehicle_column])
        values_ok &= matched
        details.append(f"{support}={'ok' if matched else 'mismatch'}")
    nested = bool(
        merged["vehicle_intermediate_usd_within_20pct"].le(
            merged["vehicle_intermediate_usd_within_2x"] + 1e-6
        ).all()
        and merged["vehicle_intermediate_usd_within_2x"].le(
            merged["vehicle_intermediate_usd"] + 1e-6
        ).all()
        and merged["intermediated_usd_within_20pct"].le(
            merged["intermediated_usd_within_2x"] + 1e-6
        ).all()
        and merged["intermediated_usd_within_2x"].le(
            merged["intermediated_usd"] + 1e-6
        ).all()
    )
    results.append(
        (
            "intermediary values reconcile and support nests",
            values_ok and nested,
            "; ".join(details) + f"; nested={'ok' if nested else 'fail'}",
        )
    )
    return results


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    state = _state_fields()

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append((name, passed, detail))

    missing_graph_fields = [name for name in GRAPH_FIELDS if not state.get(name)]
    record(
        "workflow graph state",
        not missing_graph_fields,
        graph_status(state),
    )
    boundary_passed, boundary_detail = validate_canonical_consumer_boundary()
    record("node D raw-provider boundary", boundary_passed, boundary_detail)

    if MARKET_STATE_QUALITY.exists():
        quality = pd.read_parquet(MARKET_STATE_QUALITY)
        required_quality_columns = {
            "family",
            "venue",
            "day",
            "passed",
            "missing_required_streams",
            "conflicting_events",
        }
        missing_quality_columns = sorted(required_quality_columns - set(quality.columns))
        expected_keys = expected_market_state_keys()
        observed_key_rows = list(
            quality.reindex(columns=["family", "venue", "day"])
            .astype(str)
            .itertuples(index=False, name=None)
        )
        observed_keys = set(observed_key_rows)
        duplicate_keys = len(observed_key_rows) - len(observed_keys)
        missing_keys = expected_keys - observed_keys
        unexpected_keys = observed_keys - expected_keys
        expected_venues = {venue for _family, venue, _day in expected_keys}
        observed_venues = set(quality.get("venue", pd.Series(dtype=str)).astype(str))
        passed = bool(
            not missing_quality_columns
            and not quality.empty
            and not missing_keys
            and not unexpected_keys
            and duplicate_keys == 0
            and observed_venues == expected_venues
            and quality.get("passed", pd.Series(dtype=bool)).astype(bool).all()
            and pd.to_numeric(
                quality.get("missing_required_streams", pd.Series(dtype=float)),
                errors="coerce",
            ).sum() == 0
            and pd.to_numeric(
                quality.get("conflicting_events", pd.Series(dtype=float)),
                errors="coerce",
            ).sum() == 0
            and verify(MARKET_STATE_QUALITY).get("status") == "ok"
        )
        record(
            "node D full-calendar market-state gate",
            passed,
            f"partitions={len(quality):,}/{len(expected_keys):,}; venues={sorted(observed_venues)}; "
            f"failed={int((~quality.get('passed', pd.Series(dtype=bool)).astype(bool)).sum()):,}; "
            f"missing_days={len(missing_keys):,}; unexpected_days={len(unexpected_keys):,}; "
            f"duplicate_days={duplicate_keys:,}; "
            f"missing_columns={missing_quality_columns or 'none'}; "
            f"provenance={verify(MARKET_STATE_QUALITY).get('status')}",
        )
    else:
        record(
            "node D full-calendar market-state gate",
            False,
            str(MARKET_STATE_QUALITY.relative_to(ROOT)),
        )
    if UNIFIED_QUALITY_PANEL.exists():
        route_quality = pd.read_parquet(UNIFIED_QUALITY_PANEL)
        route_provenance = str(verify(UNIFIED_QUALITY_PANEL).get("status"))
        route_passed, route_detail = validate_unified_route_layer(
            route_quality,
            provenance_status=route_provenance,
        )
        record("node D full-calendar directed-route gate", route_passed, route_detail)
    else:
        record(
            "node D full-calendar directed-route gate",
            False,
            str(UNIFIED_QUALITY_PANEL.relative_to(ROOT)),
        )
    lock_claim_ids: set[str] = set()
    if SPECIFICATION_LOCK.exists():
        try:
            lock_payload = json.loads(SPECIFICATION_LOCK.read_text())
            lock_passed, lock_detail = validate_specification_lock(lock_payload)
            lock_claim_ids = {
                str(claim.get("id"))
                for claim in lock_payload.get("claims", [])
                if isinstance(claim, dict) and claim.get("id")
            }
            input_passed, input_detail = validate_claim_input_layer(lock_payload)
        except (json.JSONDecodeError, OSError) as exc:
            lock_passed, lock_detail = False, type(exc).__name__
            input_passed, input_detail = False, type(exc).__name__
        record("node E specification lock", lock_passed, lock_detail)
        record("node D claim-input provenance gate", input_passed, input_detail)
    else:
        record(
            "node E specification lock",
            False,
            str(SPECIFICATION_LOCK.relative_to(ROOT)),
        )
        record(
            "node D claim-input provenance gate",
            False,
            str(SPECIFICATION_LOCK.relative_to(ROOT)),
        )

    if MODEL_LEDGER.exists():
        try:
            model_payload = json.loads(MODEL_LEDGER.read_text())
            model_passed, model_detail = validate_model_ledger(
                model_payload,
                claim_ids=lock_claim_ids,
            )
        except (json.JSONDecodeError, OSError) as exc:
            model_passed, model_detail = False, type(exc).__name__
        record("empirical model ledger", model_passed, model_detail)
    else:
        record("empirical model ledger", False, str(MODEL_LEDGER.relative_to(ROOT)))

    if LITERATURE_AUDIT.exists():
        cited = cited_bibliography_keys(sorted(PAPER_SECTIONS.glob("*.tex")))
        literature_passed, literature_detail = validate_literature_audit(
            LITERATURE_AUDIT.read_text(), cited, JFE_VENUE_CARDS, verify_source_sets=True
        )
        record("node B full-text literature ledger", literature_passed, literature_detail)
    else:
        record(
            "node B full-text literature ledger",
            False,
            str(LITERATURE_AUDIT.relative_to(ROOT)),
        )

    if PANEL.exists():
        meta = pq.ParquetFile(PANEL).metadata
        panel_manifest = _manifest(PANEL)
        record(
            "panel manifest row contract",
            panel_manifest.get("rows") == meta.num_rows,
            f"parquet={meta.num_rows:,}; manifest={panel_manifest.get('rows')}",
        )
        verdict = verify(PANEL)
        record(
            "panel provenance current",
            verdict.get("status") == "ok" and bool(panel_manifest.get("inputs")),
            f"status={verdict.get('status')}; inputs={len(panel_manifest.get('inputs') or [])}",
        )
        con = duckdb.connect()
        summary = con.execute(
            f"""
            SELECT count(DISTINCT date), min(date), max(date)
            FROM read_parquet('{PANEL.as_posix()}')
            """
        ).fetchone()
        v4_days = {
            str(row[0]).replace("-", "")
            for row in con.execute(
                f"""
                SELECT DISTINCT date
                FROM read_parquet('{PANEL.as_posix()}')
                WHERE direct_source='uniswap_v4'
                   OR hop1_source='uniswap_v4'
                   OR hop2_source='uniswap_v4'
                """
            ).fetchall()
        }
        con.close()
        record(
            "panel time coverage",
            int(summary[0]) >= 2_238 and str(summary[2]) == "2026-06-30",
            f"days={summary[0]:,}; range={summary[1]}..{summary[2]}",
        )
        raw_v4 = _nonempty_v4_days()
        overlap = len(v4_days & raw_v4)
        coverage = overlap / len(raw_v4) if raw_v4 else 0.0
        record(
            "v4 historical pricing coverage",
            coverage >= 0.90,
            f"priced={overlap:,}; nonempty raw days={len(raw_v4):,}; share={coverage:.1%}",
        )
    else:
        record("route-cost panel exists", False, str(PANEL.relative_to(ROOT)))

    if (
        TRANSACTION_FRONTIER.exists()
        and TRANSACTION_FRONTIER_REJECTIONS.exists()
        and TRANSACTION_FRONTIER_SUPPORT.exists()
    ):
        frontier_rows = pq.ParquetFile(TRANSACTION_FRONTIER).metadata.num_rows
        frontier_rejection_rows = pq.ParquetFile(
            TRANSACTION_FRONTIER_REJECTIONS
        ).metadata.num_rows
        frontier_verdicts = {
            TRANSACTION_FRONTIER.name: verify(TRANSACTION_FRONTIER).get("status"),
            TRANSACTION_FRONTIER_REJECTIONS.name: verify(
                TRANSACTION_FRONTIER_REJECTIONS
            ).get("status"),
            TRANSACTION_FRONTIER_SUPPORT.name: verify(
                TRANSACTION_FRONTIER_SUPPORT
            ).get("status"),
        }
        record(
            "transaction frontier provenance current",
            all(status == "ok" for status in frontier_verdicts.values()),
            "; ".join(
                f"{name}={status}" for name, status in frontier_verdicts.items()
            ),
        )
        frontier_support = pd.read_json(TRANSACTION_FRONTIER_SUPPORT, lines=True)
        for name, passed, detail in transaction_frontier_support_checks(
            frontier_support,
            panel_rows=frontier_rows,
            rejection_rows=frontier_rejection_rows,
        ):
            record(name, passed, detail)
    else:
        missing_frontier = [
            str(path.relative_to(ROOT))
            for path in (
                TRANSACTION_FRONTIER,
                TRANSACTION_FRONTIER_REJECTIONS,
                TRANSACTION_FRONTIER_SUPPORT,
            )
            if not path.exists()
        ]
        record(
            "transaction frontier exists",
            False,
            f"missing={missing_frontier}",
        )

    if EXTENT.exists():
        con = duckdb.connect()
        extent_days = con.execute(
            f"SELECT count(DISTINCT date) FROM read_parquet('{EXTENT.as_posix()}')"
        ).fetchone()[0]
        vehicle_daily = con.execute(
            f"""
            SELECT
                date,
                sum(intermediate_routes) AS vehicle_intermediate_routes,
                sum(intermediate_usd) AS vehicle_intermediate_usd,
                sum(intermediate_usd_within_2x) AS vehicle_intermediate_usd_within_2x,
                sum(intermediate_usd_within_20pct) AS vehicle_intermediate_usd_within_20pct
            FROM read_parquet('{EXTENT.as_posix()}')
            GROUP BY date
            ORDER BY date
            """
        ).df()
        con.close()
        record(
            "vehicle dominance full sample",
            extent_days == 2_277 and verify(EXTENT).get("status") == "ok",
            f"days={extent_days:,}; provenance={verify(EXTENT).get('status')}",
        )
    else:
        record("vehicle extent exists", False, str(EXTENT.relative_to(ROOT)))

    if EXTENT.exists() and INTERMEDIATION.exists() and CROSS_VENUE.exists():
        route_verdicts = {
            path.name: verify(path).get("status")
            for path in (INTERMEDIATION, CROSS_VENUE)
        }
        record(
            "route measurement provenance current",
            all(status == "ok" for status in route_verdicts.values()),
            "; ".join(
                f"{name}={status}" for name, status in route_verdicts.items()
            ),
        )
        intermediation = pd.read_parquet(INTERMEDIATION)
        cross_venue = pd.read_parquet(CROSS_VENUE)
        for name, passed, detail in route_measurement_invariants(
            intermediation,
            cross_venue,
            vehicle_daily,
        ):
            record(name, passed, detail)
    else:
        missing_route_panels = [
            str(path.relative_to(ROOT))
            for path in (INTERMEDIATION, CROSS_VENUE)
            if not path.exists()
        ]
        record(
            "route measurement panels exist",
            False,
            f"missing={missing_route_panels}",
        )

    refresh = REFRESH.read_text() if REFRESH.exists() else ""
    retired = [
        name
        for name in (
            "measure_realised_dominance.py",
            "run_dominance_specification_curve.py",
            "run_vehicle_dominance_hdfe.py",
            "run_survival_after_dominance.py",
            "run_displacement_asymmetry.py",
            "run_jfe_construct_validity_checks.py",
            "build_paper_exhibits.py",
        )
        if name in refresh
    ]
    record(
        "refresh graph excludes retired estimands",
        not retired,
        f"retired={retired or 'none'}; "
        "only validated diagnostics may run",
    )

    stable_passes = int(state.get("stable_passes") or 0)
    record(
        "two unchanged findings passes",
        stable_passes >= 2,
        f"stable_passes={stable_passes}",
    )

    print(f"GRAPH  {graph_status(state)}\n")
    width = max(len(name) for name, _passed, _detail in checks)
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {name:<{width}}  {detail}")
    failures = [name for name, passed, _detail in checks if not passed]
    print(
        f"\nfreeze gate: {'PASS' if not failures else 'RED'} "
        f"({len(failures)} blocking check(s))"
    )
    if failures:
        print("blocking: " + "; ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

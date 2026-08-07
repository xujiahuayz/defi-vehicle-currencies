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
from ddvc.provenance import sidecar_path, verify
from ddvc.route_roles import VALUE_SUPPORT_COLUMNS

PANEL = ROOT / "data" / "empirical" / "route_cost_panel_v2.parquet"
EXTENT = ROOT / "data" / "processed" / "vehicle_excess_use_daily.parquet"
INTERMEDIATION = ROOT / "data" / "processed" / "intermediation_by_type_daily.parquet"
CROSS_VENUE = ROOT / "data" / "processed" / "cross_venue_routing_daily.parquet"
V4 = ROOT / "data" / "raw" / "thegraph" / "uniswap_v4"
REFRESH = ROOT / "scripts" / "refresh_panel_dependents.py"
STATE = ROOT / "docs" / "findings-freeze.md"
SPECIFICATION_LOCK = ROOT / "docs" / "specification-lock.json"
LITERATURE_AUDIT = ROOT / "docs" / "literature-audit.md"
PAPER_SECTIONS = ROOT / "paper" / "sections"
LITERATURE_CARD_REQUIRED_FIELDS = frozenset(
    {
        "status",
        "roles",
        "source",
        "version",
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
        "version",
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
JFE_VENUE_CARDS = {
    "venue:bolton-kacperczyk-carbon",
    "venue:carletti-banks-patient-lenders",
    "venue:chang-ripples-into-waves",
    "venue:cong-li-wang-token-platform",
    "venue:diamond-hu-rajan-liquidity-pledgeability",
    "venue:eren-malamud-dominant-currency-debt",
    "venue:graham-corporate-culture",
    "venue:hajda-nikolov-product-market",
    "venue:hinzen-bitcoin-adoption",
    "venue:huang-constrained-liquidity-fx",
    "venue:li-ye-zheng-refusing-best-price",
    "venue:makarov-schoar-crypto-arbitrage",
    "venue:mayer-financing-breakthroughs",
    "venue:pastor-sustainable-investing",
}
GRAPH_FIELDS = ("active_node", "parent_loop", "next_edge", "prose_node")
LOCKED_CLAIM_STATUSES = {
    "enter_fgh_primary",
    "enter_fgh_foundation",
    "enter_fgh_mechanism",
    "enter_fgh_companion",
}


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


def validate_literature_audit(
    text: str,
    cited_keys: set[str],
    venue_cards: set[str],
) -> tuple[bool, str]:
    """Require individual full-text cards before findings may freeze."""
    frontmatter = parse_state_frontmatter(text)
    cards = parse_literature_cards(text)
    required_cards = cited_keys | venue_cards
    complete_cards = {
        key
        for key in required_cards
        if key in cards and complete_literature_card(cards[key])
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
        and complete_cards == required_cards
        and verified_citations == cited_keys
        and read_venues == venue_cards
        and independent == central
    )
    return passed, (
        f"status={frontmatter.get('status') or 'missing'}; "
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
    if SPECIFICATION_LOCK.exists():
        try:
            lock_payload = json.loads(SPECIFICATION_LOCK.read_text())
            lock_passed, lock_detail = validate_specification_lock(lock_payload)
        except (json.JSONDecodeError, OSError) as exc:
            lock_passed, lock_detail = False, type(exc).__name__
        record("node E specification lock", lock_passed, lock_detail)
    else:
        record(
            "node E specification lock",
            False,
            str(SPECIFICATION_LOCK.relative_to(ROOT)),
        )

    if LITERATURE_AUDIT.exists():
        cited = cited_bibliography_keys(sorted(PAPER_SECTIONS.glob("*.tex")))
        literature_passed, literature_detail = validate_literature_audit(
            LITERATURE_AUDIT.read_text(), cited, JFE_VENUE_CARDS
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

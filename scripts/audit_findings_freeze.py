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
from ddvc.asset_types import TYPES, VEHICLE_CANDIDATES
from ddvc.analysis.transaction_frontier import (
    MAX_CHOSEN_REPRODUCTION_ERROR_BPS,
    chosen_quote_coverage_share,
    chosen_reproduction_share,
)
from ddvc.analysis.dynamics import CANONICAL_RESPONSE_HORIZONS
from ddvc.calendar import (
    RESEARCH_SAMPLE_END,
    RESEARCH_SAMPLE_START,
    calendar_days,
    sample_end_iso,
)
from ddvc.capital_contracts import (
    CAPITAL_CURRENT_COLUMN,
    CAPITAL_SOURCE,
    CP_CAPITAL_STATE_GENERATION,
    VALID_CAPITAL_STATUSES,
)
from ddvc.capital_release import CapitalRelease, resolve_capital_release
from ddvc.cp_state_stream import certified_cp_event_stream, certified_cp_state_stream
from ddvc.fetch.sources import DEX_SOURCES, get_source
from ddvc.frontier_release import resolve_frontier_release
from ddvc.liquidity import (
    CAPITAL_COLUMN,
    LIQUIDITY_CONTRACTS,
    require_contract_coverage,
    resolve_materializer,
)
from ddvc.literature_admission import load_source_admission, validate_source_admission
from ddvc.provenance import portable_content_sha256, sidecar_path, verify
from ddvc.prices import load_canonical_token_prices
from ddvc.model_registry import (
    DESIGN_SEED_CLAIM_STATUSES,
    LEGACY_MODEL_STATUSES,
    MODEL_RUN_ARTIFACT_ROLES,
    MODEL_RUN_DISPOSITIONS,
    MODEL_RUN_LANES,
    MODEL_RUN_LIFECYCLES,
    REGISTERED_CLAIM_STATUSES,
    canonical_hash,
    claim_execution_perimeter,
    exploratory_plan_identity,
    generation_id,
    model_run_id,
    validate_artifact_spec_ids,
    validate_registered_plan,
)
from ddvc.reconstruct import DEX_FAMILY, UNIFIED_QUALITY_PANEL
from ddvc.data_release import require_route_release, released_state_partitions
from ddvc.d3_stage_registry import d3_release_postcondition
from ddvc.route_cost import MAIN_ROUTE_COST_SPEC, QUOTE_CELL_KEYS
from ddvc.route_roles import VALUE_SUPPORT_COLUMNS
from ddvc.state_data import (
    CP_COLUMNS,
    FAMILY_STREAMS,
    RAW_ROOT,
    STATE_GENERATIONS,
    pool_semantics,
)
from ddvc.venue_corpus import JFE_VENUE_CARDS, JFE_VENUE_SOURCE_KEYS
from ddvc.release_calendar import transaction_frontier_audit_days
from ddvc.v2_event_completeness import (
    read_v2_event_source_certificate,
    read_v2_event_source_release,
    resolve_v2_event_source_release,
    validate_v2_event_source_certificate,
    validate_v2_event_source_evidence_bundle,
)
from ddvc.v3_event_completeness import (
    read_v3_event_source_release,
    resolve_v3_event_source_release,
    validate_v3_event_source_certificate,
    validate_v3_event_source_evidence_bundle,
    v3_audit_days,
)
from ddvc.v3_inventory_calendar import inventory_calendar_days
from ddvc.paths import (
    LITERATURE_SOURCE_ADMISSION,
    LP_LIQUIDITY_FLOW_CANDIDATES,
    LP_LIQUIDITY_FLOW_DAILY,
    LP_LIQUIDITY_FLOW_EVENTS,
    LP_LIQUIDITY_FLOW_REJECTIONS,
    TOKEN_PRICE_DAILY_PANEL,
    literature_papers_dir,
)

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
LITERATURE_USE_CONTRACTS = ROOT / "literature" / "use-contracts.json"
LITERATURE_TEXT = ROOT / "literature" / "text"
LITERATURE_SOURCE_NOTES = ROOT / "literature" / "source-notes"
MARKET_STATE_QUALITY = ROOT / "data" / "processed" / "market_state_quality.parquet"
V3_INVENTORY_CALENDAR = ROOT / "data" / "processed" / "v3_inventory_day_calendar.parquet"
V3_INVENTORY_DAY_CUTS = ROOT / "data" / "raw" / "ethereum" / "uniswap_v3_inventory_day_cuts"
CEX_REFERENCE_SUPPORT = ROOT / "data" / "processed" / "cex_reference_support.parquet"
WITHDRAWN_ROUTE_GAS_SCRIPTS = (
    "scripts/test_gap_arbitrage_bound.py",
    "scripts/measure_dominance_windows.py",
    "scripts/run_rent_incidence.py",
)
WITHDRAWN_ROUTE_GAS_ARTIFACTS = (
    "data/interim/gas_days",
    "data/interim/gas_price_graph",
    "data/manifests/data/processed/daily_gas_eth.parquet.prov.json",
    "data/manifests/data/processed/daily_gas_price_graph.parquet.prov.json",
    "data/manifests/output/exhibits/daily_gas_eth.jsonl.prov.json",
    "data/manifests/output/exhibits/daily_gas_price_graph.jsonl.prov.json",
    "data/processed/daily_gas_eth.parquet",
    "data/processed/daily_gas_price_graph.parquet",
    "output/exhibits/daily_gas_eth" + "." + "csv",
    "output/exhibits/daily_gas_eth.jsonl",
    "output/exhibits/daily_gas_price_graph.jsonl",
    "output/exhibits/gap_arbitrage_bound.jsonl",
    "output/exhibits/dominance_windows_screened.jsonl",
)
ROUTE_GAS_AUDIT_ONLY_DOCS = (
    # The round-one review is an immutable criticism ledger: it quotes the retired
    # constants in order to document why they were rejected, never as live evidence.
    "docs/review-node-i-round1.md",
)
WITHDRAWN_ROUTE_GAS_REFERENCES = (
    "build_daily_gas_and_eth",
    "daily_gas_eth",
    "daily_gas_price_graph",
    "fetch_daily_gas_price_graph",
    "gas_price_graph",
    "gas_days",
    "output/exhibits/gap_arbitrage_bound.jsonl",
    "output/exhibits/dominance_windows_screened.jsonl",
)
RETIRED_ROUTE_GAS_CODE_MARKERS = (
    "GAS_BY_LEGS",
    "GAS_PER_EXTRA_HOP",
    "def gas_units(",
    "def gas_cost_bps(",
    "def all_in_direct_advantage_bps(",
)
RETIRED_ROUTE_GAS_CODE_PATTERNS = (
    re.compile(r"\beth_usd\s*=\s*2_?500(?:\.0)?\b", re.IGNORECASE),
    re.compile(r"\bgas_(?:price_)?gwei\s*=\s*13\.67\b", re.IGNORECASE),
    re.compile(r"\b(?:gas|hop)[^\n]{0,100}\b(?:74_096|154_604|228_701|319_906)\b", re.IGNORECASE),
    re.compile(r"\b13\.67e-9\b", re.IGNORECASE),
)
RETIRED_ROUTE_GAS_PUBLICATION_PATTERNS = (
    re.compile(r"\b(?:13\.67|13\.7)\s+gwei\b", re.IGNORECASE),
    re.compile(r"\b(?:gas|hop|receipt)[^\n]{0,160}\b(?:74,096|154,604|228,701|319,906)\b", re.IGNORECASE),
    re.compile(r"\b(?:74,096|154,604|228,701|319,906)\b[^\n]{0,160}\b(?:gas|hop|receipt)\b", re.IGNORECASE),
    re.compile(r"\b(?:gas|ETH price|converted at)[^\n]{0,120}(?:\\?\$2,500)\b", re.IGNORECASE),
)
CANONICAL_EMPIRICAL_CONSUMERS = (
    "scripts/build_intermediation_by_type.py",
    "scripts/build_transaction_state_frontier.py",
    "scripts/build_counterfactual_dominance.py",
    "scripts/build_rent_incidence_panel.py",
    "scripts/build_lp_liquidity_flow_panel.py",
    "scripts/build_token_price_panel.py",
    "scripts/run_core_rq_experiments.py",
    "scripts/run_rent_incidence.py",
    "scripts/test_block_vs_hour_verdict.py",
    "scripts/validate_curve_quoter.py",
    "scripts/validate_weighted_quoter.py",
    "scripts/run_balancer_weighted_quote_extension.py",
    "src/ddvc/pricing/tick_replay.py",
    "src/ddvc/pricing/v2_replay.py",
    "src/ddvc/analysis/lp_concentration.py",
    "src/ddvc/analysis/lp_liquidity_flow.py",
)


def retired_route_gas_release_checks(
    root: Path = ROOT,
) -> list[tuple[str, bool, str]]:
    """Reject retired route-gas clocks at executable and publication boundaries."""

    executable_violations: list[str] = []
    refresh_path = root / "scripts" / "refresh_panel_dependents.py"
    refresh_source = refresh_path.read_text(encoding="utf-8") if refresh_path.exists() else ""
    for relative in WITHDRAWN_ROUTE_GAS_SCRIPTS:
        path = root / relative
        source = path.read_text(encoding="utf-8") if path.exists() else ""
        if relative.rsplit("/", 1)[-1] in refresh_source:
            executable_violations.append(f"refresh:{relative}")
        if "raise RuntimeError" not in source or "withdraw" not in source.lower():
            executable_violations.append(f"not-fail-closed:{relative}")

    code_violations: list[str] = []
    for directory in (root / "scripts", root / "src"):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.py")):
            if path == root / "scripts" / "audit_findings_freeze.py":
                continue
            source = path.read_text(encoding="utf-8")
            if path == root / "src" / "ddvc" / "cpquote.py":
                for marker in RETIRED_ROUTE_GAS_CODE_MARKERS:
                    if marker in source:
                        code_violations.append(f"{path.relative_to(root)}:{marker}")
            for pattern in RETIRED_ROUTE_GAS_CODE_PATTERNS:
                if pattern.search(source):
                    code_violations.append(
                        f"{path.relative_to(root)}:{pattern.pattern}"
                    )
            for marker in WITHDRAWN_ROUTE_GAS_REFERENCES:
                if marker in source:
                    code_violations.append(f"{path.relative_to(root)}:{marker}")

    excluded_docs = {root / relative for relative in ROUTE_GAS_AUDIT_ONLY_DOCS}
    publication_paths = [
        *(sorted((root / "paper" / "sections").glob("*.tex")) if (root / "paper" / "sections").exists() else []),
        *(sorted((root / "deck" / "sections").glob("*.tex")) if (root / "deck" / "sections").exists() else []),
        *(
            sorted(
                path
                for pattern in ("*.md", "*.json")
                for path in (root / "docs").rglob(pattern)
                if path not in excluded_docs
            )
            if (root / "docs").exists()
            else []
        ),
    ]
    publication_violations: list[str] = []
    for path in publication_paths:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        for marker in WITHDRAWN_ROUTE_GAS_REFERENCES:
            if marker in source:
                publication_violations.append(f"{path.relative_to(root)}:{marker}")
        for pattern in RETIRED_ROUTE_GAS_PUBLICATION_PATTERNS:
            if pattern.search(source):
                publication_violations.append(f"{path.relative_to(root)}:{pattern.pattern}")

    existing_artifacts = [
        relative for relative in WITHDRAWN_ROUTE_GAS_ARTIFACTS if (root / relative).exists()
    ]
    return [
        (
            "retired route-gas executables fail closed",
            not executable_violations,
            f"violations={executable_violations or 'none'}",
        ),
        (
            "retired route-gas constants absent from code",
            not code_violations,
            f"violations={code_violations or 'none'}",
        ),
        (
            "withdrawn route-gas evidence absent from publication surfaces",
            not publication_violations,
            f"violations={publication_violations or 'none'}",
        ),
        (
            "withdrawn route-gas artifacts absent",
            not existing_artifacts,
            f"artifacts={existing_artifacts or 'none'}",
        ),
    ]
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
LITERATURE_FINDING_SELLING_MARKERS = (
    "## Finding-selling calibration",
    "Literal evidence/design",
    "Strongest headline",
    "Adjacent qualification",
    "Auxiliary evidence",
    "Residual stretch",
    "Reusable move",
)
RENT_V2_PANEL = ROOT / "data" / "processed" / "rent_incidence_v2_pool_day.parquet"
GRAPH_FIELDS = ("active_node", "parent_loop", "next_edge", "prose_node")
CAPITAL_CONTRACT_COLUMNS = (
    "venue",
    "pool_family",
    "invariant_family",
    "state_generation",
    "quantity_kind",
    "capital_source",
)
VEHICLE_TRANSITION_E1_COMPONENTS = (
    "within_common",
    "common_pair_reweighting",
    "common_support_mass",
    "exclusive_pair_contribution",
)
VEHICLE_TRANSITION_MARKET_INCIDENCE_COMPONENTS = (
    "market_pair_support_bridge",
    "vehicle_role_support_bridge",
    "market_activity_reweighting",
    "vehicle_incidence_reweighting",
    "within_pair_stable_share",
)
EXPECTED_VEHICLE_TRANSITION_E1_DESIGN_HASH = "d4f9215fdda57f70d6cf5924a844bc77d420bcf99675888d578f23c4ff6c0cda"


def _manifest(path: Path) -> dict:
    sidecar = sidecar_path(path)
    return json.loads(sidecar.read_text()) if sidecar.exists() else {}


def vehicle_transition_e1_design_errors(claim: dict) -> list[str]:
    """Validate the seeded pair-panel and exact-decomposition contract."""

    errors: list[str] = []
    design = claim.get("e1_design")
    expected_members = {
        "pair_panel",
        "pair_decomposition",
        "market_incidence_decomposition",
    }
    if not isinstance(design, dict) or set(design) != expected_members:
        return [
            "e1_design must contain exactly pair_panel, pair_decomposition, "
            "and market_incidence_decomposition"
        ]
    actual_design_hash = canonical_hash(design)
    if claim.get("e1_design_hash") != actual_design_hash:
        errors.append("e1_design_hash")
    if actual_design_hash != EXPECTED_VEHICLE_TRANSITION_E1_DESIGN_HASH:
        errors.append("unreviewed e1_design_hash")
    panel = design.get("pair_panel")
    decomposition = design.get("pair_decomposition")
    market_incidence = design.get("market_incidence_decomposition")
    if (
        not isinstance(panel, dict)
        or not isinstance(decomposition, dict)
        or not isinstance(market_incidence, dict)
    ):
        return ["e1_design members must be objects"]
    panel_required = {"id", "comparison_years", "cell_keys", "common_support_keys", "candidate_types", "primary_measures", "stable_share_formula", "estimator_id", "fixed_effects", "fixed_effect_cell_keys", "clusters", "coefficient", "effective_cell_weight", "multiplicity"}
    decomposition_required = {"id", "target_id", "role_id", "comparison_years", "calendar_support", "calendar_aggregation_id", "integration_scope_aggregation_id", "pair_membership_id", "pair_universe", "common_pair_definition", "exclusive_pair_definition", "candidate_types", "measure_ids", "components", "identity", "formula_id", "formula", "identity_absolute_tolerance", "zero_exclusive_mass_rule", "denominator_scope", "forbidden_denominator", "reporting"}
    missing_panel = sorted(panel_required - set(panel))
    missing_decomposition = sorted(decomposition_required - set(decomposition))
    if missing_panel:
        errors.append(f"pair_panel missing={missing_panel}")
    if missing_decomposition:
        errors.append(f"pair_decomposition missing={missing_decomposition}")
    if panel.get("candidate_types") != ["native", "stable"]:
        errors.append("pair_panel candidate_types")
    measures = panel.get("primary_measures")
    measure_rows = measures if isinstance(measures, list) else []
    measure_ids = [
        str(row.get("id") or "")
        for row in measure_rows
        if isinstance(row, dict)
    ]
    incomplete_measures = [
        str(row.get("id") or "missing")
        for row in measure_rows
        if not isinstance(row, dict)
        or not {"id", "source_column", "support", "weight"}.issubset(row)
        or any(not str(row.get(field) or "").strip() for field in ("id", "source_column", "support", "weight"))
    ]
    if len(measure_rows) != 3 or len(measure_ids) != 3 or len(set(measure_ids)) != 3 or incomplete_measures:
        errors.append("pair_panel primary_measures")
    if panel.get("fixed_effects") != ["ordered_endpoint_pair_x_month_day_x_integration_scope"]:
        errors.append("pair_panel fixed_effects")
    if panel.get("fixed_effect_cell_keys") != panel.get("common_support_keys"):
        errors.append("pair_panel fixed_effect_cell_keys")
    if panel.get("clusters") != ["ordered_endpoint_pair", "calendar_date"]:
        errors.append("pair_panel clusters")
    multiplicity = panel.get("multiplicity")
    if not isinstance(multiplicity, dict) or multiplicity.get("method") != "Holm" or multiplicity.get("family") != measure_ids:
        errors.append("pair_panel multiplicity")
    if decomposition.get("comparison_years") != panel.get("comparison_years"):
        errors.append("pair_decomposition comparison_years")
    if decomposition.get("candidate_types") != panel.get("candidate_types"):
        errors.append("pair_decomposition candidate_types")
    if decomposition.get("measure_ids") != measure_ids:
        errors.append("pair_decomposition measure_ids")
    if tuple(decomposition.get("components") or ()) != VEHICLE_TRANSITION_E1_COMPONENTS:
        errors.append("pair_decomposition components")
    identity = str(decomposition.get("identity") or "")
    identity_terms = [term.strip() for term in identity.partition("=")[2].split("+")]
    if not identity.startswith("delta_total =") or identity_terms != list(VEHICLE_TRANSITION_E1_COMPONENTS):
        errors.append("pair_decomposition identity")
    tolerance = decomposition.get("identity_absolute_tolerance")
    if not isinstance(tolerance, (float, int)) or not 0 < float(tolerance) <= 1e-6:
        errors.append("pair_decomposition identity_absolute_tolerance")
    denominator = str(decomposition.get("denominator_scope") or "")
    forbidden_denominator = str(decomposition.get("forbidden_denominator") or "")
    if not denominator or not forbidden_denominator or denominator == forbidden_denominator:
        errors.append("pair_decomposition denominator boundary")
    formula = str(decomposition.get("formula") or "")
    if not all(f"{component} =" in formula for component in VEHICLE_TRANSITION_E1_COMPONENTS):
        errors.append("pair_decomposition formula")
    market_required = {
        "id",
        "target_id",
        "role_id",
        "comparison_years",
        "calendar_support",
        "pair_universe",
        "market_activity",
        "vehicle_incidence",
        "stable_share",
        "support_classification",
        "common_role_definition",
        "components",
        "identity",
        "formula_id",
        "formula",
        "identity_absolute_tolerance",
        "measure_ids",
        "forbidden_interpretations",
        "reporting",
    }
    missing_market = sorted(market_required - set(market_incidence))
    if missing_market:
        errors.append(f"market_incidence_decomposition missing={missing_market}")
    if market_incidence.get("comparison_years") != panel.get("comparison_years"):
        errors.append("market_incidence_decomposition comparison_years")
    if market_incidence.get("measure_ids") != ["count_share"]:
        errors.append("market_incidence_decomposition measure_ids")
    if tuple(market_incidence.get("components") or ()) != (
        VEHICLE_TRANSITION_MARKET_INCIDENCE_COMPONENTS
    ):
        errors.append("market_incidence_decomposition components")
    market_identity = str(market_incidence.get("identity") or "")
    market_identity_terms = [
        term.strip() for term in market_identity.partition("=")[2].split("+")
    ]
    if (
        not market_identity.startswith("delta_total =")
        or market_identity_terms
        != list(VEHICLE_TRANSITION_MARKET_INCIDENCE_COMPONENTS)
    ):
        errors.append("market_incidence_decomposition identity")
    market_formula = str(market_incidence.get("formula") or "")
    if not all(
        term in market_formula
        for term in ("all six permutations", "F(M,I,s)", "positive M")
    ):
        errors.append("market_incidence_decomposition formula")
    market_forbidden = str(market_incidence.get("forbidden_interpretations") or "")
    if not all(
        term in market_forbidden
        for term in ("architecture", "opportunity", "demand", "preference", "search")
    ):
        errors.append("market_incidence_decomposition interpretation boundary")
    return errors


def v3_inventory_calendar_checks(
    calendar_path: Path = V3_INVENTORY_CALENDAR,
    raw_root: Path = V3_INVENTORY_DAY_CUTS,
    *,
    expected_days: list[str] | None = None,
) -> list[tuple[str, bool, str]]:
    """Audit exact UTC cuts against persisted RPC evidence and the raw-source calendar."""

    if not calendar_path.is_file() or not raw_root.is_dir():
        return [
            (
                "node D V3 inventory calendar exists",
                False,
                f"calendar={calendar_path.is_file()}; raw_root={raw_root.is_dir()}",
            )
        ]
    provenance_status = verify(calendar_path).get("status")
    results = [
        (
            "node D V3 inventory calendar provenance",
            provenance_status == "ok",
            f"provenance={provenance_status}",
        )
    ]
    frame = pd.read_parquet(calendar_path)
    required = {
        "day",
        "target_timestamp",
        "day_end_block",
        "day_end_block_timestamp",
        "next_block",
        "next_block_timestamp",
        "initial_lower_bracket",
        "resolved_upper_bracket",
    }
    missing = sorted(required - set(frame.columns))
    results.append(
        (
            "node D V3 inventory calendar schema",
            not missing,
            f"missing_columns={missing or 'none'}",
        )
    )
    if missing:
        return results

    expected = expected_days or inventory_calendar_days()
    days = frame["day"].astype(str).tolist()
    duplicate_days = len(days) - len(set(days))
    results.append(
        (
            "node D V3 inventory calendar perimeter",
            days == expected and not duplicate_days,
            f"rows={len(days):,}/{len(expected):,}; duplicates={duplicate_days:,}; "
            f"range={days[0] if days else 'none'}..{days[-1] if days else 'none'}",
        )
    )
    if not days or duplicate_days or days != expected:
        return results

    raw_paths = sorted(raw_root.glob("*.json"))
    unexpected = sorted(
        path.name for path in raw_root.iterdir() if path.is_file() and path.suffix != ".json"
    )
    records: list[dict[str, object]] = []
    parse_failures: list[str] = []
    for path in raw_paths:
        try:
            record = json.loads(path.read_text())
            if str(record.get("day")) != path.stem:
                raise ValueError("filename/day mismatch")
            records.append(record)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            parse_failures.append(path.name)
    raw_days = [str(record.get("day")) for record in records]
    complete = sum(record.get("status") == "complete" for record in records)
    results.append(
        (
            "node D V3 inventory raw-cut coverage",
            raw_days == expected
            and complete == len(records)
            and not parse_failures
            and not unexpected,
            f"cuts={len(records):,}/{len(expected):,}; parse_failures={len(parse_failures):,}; "
            f"complete={complete:,}; unexpected_files={len(unexpected):,}",
        )
    )
    if (
        raw_days != expected
        or complete != len(records)
        or parse_failures
        or unexpected
    ):
        return results

    integer_columns = [
        "target_timestamp",
        "day_end_block",
        "day_end_block_timestamp",
        "next_block",
        "next_block_timestamp",
        "initial_lower_bracket",
        "resolved_upper_bracket",
    ]
    raw_frame = pd.DataFrame.from_records(records).sort_values("day").reset_index(drop=True)
    observed = frame[["day", *integer_columns]].sort_values("day").reset_index(drop=True)
    for column in integer_columns:
        raw_frame[column] = pd.to_numeric(raw_frame[column], errors="coerce").astype("Int64")
        observed[column] = pd.to_numeric(observed[column], errors="coerce").astype("Int64")
    raw_frame["day"] = raw_frame["day"].astype(str)
    observed["day"] = observed["day"].astype(str)
    results.append(
        (
            "node D V3 inventory raw-to-panel identity",
            observed.equals(raw_frame[["day", *integer_columns]]),
            f"rows={len(observed):,}; exact_columns={len(integer_columns) + 1}",
        )
    )

    target = observed["target_timestamp"].astype("int64")
    end_timestamp = observed["day_end_block_timestamp"].astype("int64")
    next_timestamp = observed["next_block_timestamp"].astype("int64")
    end_block = observed["day_end_block"].astype("int64")
    next_block = observed["next_block"].astype("int64")
    expected_target = (
        pd.to_datetime(observed["day"], format="%Y%m%d", utc=True) + pd.Timedelta(days=1)
    ).map(lambda value: int(value.timestamp()))
    strict = bool(
        np.array_equal(target.to_numpy(), expected_target.to_numpy())
        and (end_timestamp < target).all()
        and (target <= next_timestamp).all()
        and (next_block == end_block + 1).all()
        and (observed["initial_lower_bracket"].astype("int64") <= end_block).all()
        and (end_block < observed["resolved_upper_bracket"].astype("int64")).all()
        and end_block.is_monotonic_increasing
        and end_block.is_unique
    )
    results.append(
        (
            "node D V3 inventory exact UTC-cut contract",
            strict,
            f"before_midnight={int((target - end_timestamp).min())}.."
            f"{int((target - end_timestamp).max())}s; after_midnight="
            f"{int((next_timestamp - target).min())}..{int((next_timestamp - target).max())}s",
        )
    )

    bad_evidence = 0
    evidence_counts: list[int] = []
    for record in records:
        evidence = record.get("rpc_evidence")
        if not isinstance(evidence, list):
            bad_evidence += 1
            continue
        evidence_counts.append(len(evidence))
        requested: set[int] = set()
        returned: set[int] = set()
        responses: dict[int, dict[str, object]] = {}
        evidence_bad = False
        for item in evidence:
            request = item.get("request") if isinstance(item, dict) else None
            response = item.get("response") if isinstance(item, dict) else None
            try:
                if request.get("method") != "eth_getBlockByNumber":
                    raise ValueError("wrong method")
                requested_block = int(str(request["params"][0]), 16)
                returned_block = int(str(response["number"]), 16)
                int(str(response["timestamp"]), 16)
                if requested_block != returned_block or not response.get("hash") or not response.get("parentHash"):
                    raise ValueError("incomplete response identity")
                requested.add(requested_block)
                returned.add(returned_block)
                responses[returned_block] = response
            except (AttributeError, KeyError, TypeError, ValueError):
                evidence_bad = True
                break
        end = int(record["day_end_block"])
        following = int(record["next_block"])
        required_blocks = {
            end,
            following,
            int(record["initial_lower_bracket"]),
            int(record["resolved_upper_bracket"]),
        }
        if (
            requested != returned
            or not required_blocks.issubset(requested)
            or len(requested) != len(evidence)
            or int(str(responses.get(end, {}).get("timestamp")), 16)
            != int(record["day_end_block_timestamp"])
            or int(str(responses.get(following, {}).get("timestamp")), 16)
            != int(record["next_block_timestamp"])
            or responses.get(following, {}).get("parentHash") != responses.get(end, {}).get("hash")
        ):
            evidence_bad = True
        if evidence_bad:
            bad_evidence += 1
    evidence_ok = bool(
        len(evidence_counts) == len(records)
        and evidence_counts
        and min(evidence_counts) >= 2
        and max(evidence_counts) <= 64
        and not bad_evidence
    )
    results.append(
        (
            "node D V3 inventory RPC evidence",
            evidence_ok,
            f"cuts={len(evidence_counts):,}/{len(records):,}; calls_per_cut="
            f"{min(evidence_counts) if evidence_counts else 0}.."
            f"{max(evidence_counts) if evidence_counts else 0}; bad={bad_evidence:,}",
        )
    )
    return results


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


def literature_card_for_requirement(
    cards: dict[str, dict[str, str]], key: str
) -> dict[str, str]:
    """Reuse one complete card when a cited paper is also a venue exemplar.

    Card headings describe the role under review, while the Source key owns paper
    identity. Requiring a second copy of the same five-axis read when a venue exemplar
    later becomes cited creates two independently drifting summaries of one source.
    """
    if key in cards:
        return cards[key]
    matches = [
        fields
        for fields in cards.values()
        if literature_source_key(fields) == key
    ]
    return matches[0] if len(matches) == 1 else {}


def literature_corpus_index(root: Path = ROOT) -> dict[str, dict]:
    """Load the tracked checksum contract for the ignored local PDF corpus."""
    path = root / "literature" / "text" / "_index.jsonl"
    records: dict[str, dict] = {}
    if not path.is_file():
        return records
    for line in path.read_text(errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        stem = str(record.get("stem") or "") if isinstance(record, dict) else ""
        if stem:
            records[stem] = record
    return records


def indexed_pdf_materialized(stem: str, *, paper_root: Path, index: dict[str, dict]) -> bool:
    """Verify one ignored PDF against the tracked index record for its exact stem."""
    record = index.get(stem, {})
    pdf = paper_root / f"{stem}.pdf"
    expected_hash = record.get("pdf_sha256") if isinstance(record, dict) else None
    return bool(
        pdf.is_file()
        and isinstance(expected_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected_hash)
        and file_sha256(pdf) == expected_hash
    )


def source_note_type(key: str, *, note_root: Path) -> str | None:
    """Read the explicit materialization type from one exact-key source note."""
    notes = list(note_root.glob(f"*-{key}.md"))
    if len(notes) != 1:
        return None
    match = re.search(
        r"^source_type:\s*(.+?)\s*$",
        notes[0].read_text(errors="replace"),
        flags=re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip().lower() if match else None


def materialized_companion_sources(root: Path = ROOT) -> dict[str, bool]:
    """Report exact-key artifacts backed by the local checksum-verified PDF corpus."""
    bib_path = root / "literature" / "vehicle-currencies.bib"
    sources_path = root / "literature" / "pdf-sources.json"
    text_root = root / "literature" / "text"
    note_root = root / "literature" / "source-notes"
    paper_root = literature_papers_dir(root)
    bib_keys = set(re.findall(r"@\w+\s*\{\s*([^,\s]+)", bib_path.read_text()))
    try:
        source_keys = set(json.loads(sources_path.read_text()).get("sources", {}))
    except (json.JSONDecodeError, OSError):
        source_keys = set()
    index = literature_corpus_index(root)
    return {
        key: source_materialized(
            key,
            bib_keys=bib_keys,
            source_keys=source_keys,
            text_root=text_root,
            note_root=note_root,
            paper_root=paper_root,
            index=index,
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
    paper_root: Path | None = None,
    index: dict[str, dict] | None = None,
) -> bool:
    """Require an exact-key durable source, never an extract standing in for its PDF."""
    if key not in bib_keys or key not in source_keys:
        return False
    extracts = list(text_root.glob(f"*-{key}-*.txt"))
    if extracts:
        if paper_root is None or index is None:
            return False
        for extract in extracts:
            if indexed_pdf_materialized(extract.stem, paper_root=paper_root, index=index):
                return True
        return False
    return source_note_type(key, note_root=note_root) == "publisher-native-html"


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


def card_source_evidence_text(fields: dict[str, str]) -> str | None:
    """Resolve a card's PDF extract or primary-technical source note."""
    source = fields.get("source", "").strip()
    if source.startswith("literature/papers/") and source.endswith(".pdf"):
        path = LITERATURE_TEXT / f"{Path(source).stem}.txt"
        return path.read_text(errors="replace") if path.exists() else None
    if source.startswith("literature/source-notes/") and source.endswith(".md"):
        path = ROOT / source
        return path.read_text(errors="replace") if path.is_file() else None
    return None


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
        main_closed = (
            source_set_main_artifact_closed(source_set, materialized)
            if source_set is not None
            else materialized.get(literature_source_key(fields), False)
        )
        return bool(keys) and all(
            source_set_companion_closed(
                key,
                main_key=literature_source_key(fields),
                materialized=materialized,
                main_artifact_closed=main_closed,
            )
            for key in keys
        )
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


def source_set_companion_closed(
    key: str,
    *,
    main_key: str,
    materialized: dict[str, bool],
    main_artifact_closed: bool | None = None,
    root: Path = ROOT,
) -> bool:
    """Allow only a verified artifact or an explicitly embedded appendix in the verified main PDF."""
    if materialized.get(key, False):
        return True
    main_closed = materialized.get(main_key, False) if main_artifact_closed is None else main_artifact_closed
    return (
        source_note_type(key, note_root=root / "literature" / "source-notes") == "embedded-in-main"
        and main_closed
    )


def source_set_main_artifact_closed(
    source_set: dict,
    materialized: dict[str, bool],
    *,
    root: Path = ROOT,
) -> bool:
    """Verify the exact article extract against its indexed local PDF and checksum."""
    checks = source_set.get("checks", {})
    article = checks.get("article") if isinstance(checks, dict) else None
    article_path = (root / article).resolve() if isinstance(article, str) else None
    text_root = (root / "literature" / "text").resolve()
    if article_path and article_path.is_relative_to(text_root) and article_path.is_file():
        return indexed_pdf_materialized(
            article_path.stem,
            paper_root=literature_papers_dir(root),
            index=literature_corpus_index(root),
        )
    main_key = source_set.get("main")
    return isinstance(main_key, str) and materialized.get(main_key, False)


def source_set_companion_disposition_resolved(
    key: str,
    materialized: dict[str, bool],
    *,
    root: Path = ROOT,
) -> bool:
    """Distinguish a missing appendix from one explicitly embedded in the main PDF."""
    if materialized.get(key, False):
        return True
    return source_note_type(
        key,
        note_root=root / "literature" / "source-notes",
    ) in {"embedded-in-main", "publisher-native-html"}


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
    main_closed = source_set_main_artifact_closed(source_set, materialized, root=root)
    return bool(
        source_set.get("status") == "complete"
        and isinstance(main_key, str)
        and isinstance(checks, dict)
        and all(checks.get(kind) for kind in ("article", "publisher_or_doi", "author_or_repository"))
        and isinstance(companions, list)
        and all(isinstance(key, str) for key in companions)
        and main_closed
        and all(
            source_set_companion_closed(
                key,
                main_key=main_key,
                materialized=materialized,
                main_artifact_closed=main_closed,
                root=root,
            )
            for key in companions
        )
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
    paper_root = literature_papers_dir(root).resolve()
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
            artifact_path = (
                paper_root / Path(artifact).name
                if isinstance(artifact, str) and artifact.startswith("literature/papers/")
                else (root / artifact).resolve()
                if isinstance(artifact, str)
                else None
            )
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


def load_literature_use_contracts(path: Path = LITERATURE_USE_CONTRACTS) -> dict:
    """Load the one canonical policy for citation-use and vocabulary boundaries."""
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def validate_literature_use_contracts(policy: dict) -> tuple[bool, str]:
    """Fail closed when the policy weakens the method/vocabulary asymmetry or is malformed."""
    claim_rules = policy.get("claim_use_contracts")
    vocabulary_rules = policy.get("vocabulary_contracts")
    if not isinstance(claim_rules, list) or not isinstance(vocabulary_rules, list):
        return False, "claim_use_contracts and vocabulary_contracts must be lists"
    ids: list[str] = []
    invalid: list[str] = []
    for rule in claim_rules:
        required = {
            "id",
            "source_key",
            "evidence_field",
            "evidence_pattern",
            "prohibited_pattern",
            "reason",
        }
        rule_id = str(rule.get("id") or "missing-id") if isinstance(rule, dict) else "missing-id"
        ids.append(rule_id)
        if not isinstance(rule, dict) or any(not str(rule.get(field) or "").strip() for field in required):
            invalid.append(rule_id)
            continue
        try:
            re.compile(str(rule["evidence_pattern"]), flags=re.IGNORECASE | re.DOTALL)
            re.compile(str(rule["prohibited_pattern"]), flags=re.IGNORECASE | re.DOTALL)
        except re.error:
            invalid.append(rule_id)
    for rule in vocabulary_rules:
        required = {"id", "term", "publication_classes", "minimum_documents", "reason"}
        rule_id = str(rule.get("id") or "missing-id") if isinstance(rule, dict) else "missing-id"
        ids.append(rule_id)
        if (
            not isinstance(rule, dict)
            or any(field not in rule for field in required)
            or not str(rule.get("term") or "").strip()
            or not isinstance(rule.get("publication_classes"), list)
            or not rule["publication_classes"]
            or any(not isinstance(value, str) or not value for value in rule["publication_classes"])
            or not isinstance(rule.get("minimum_documents"), int)
            or rule["minimum_documents"] < 1
            or not str(rule.get("reason") or "").strip()
        ):
            invalid.append(rule_id)
    duplicates = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
    passed = bool(
        policy.get("schema_version") == 1
        and policy.get("method_absence_rule")
        == "absence_never_prohibits_without_explicit_source_prohibition"
        and policy.get("vocabulary_absence_rule") == "configured_absence_prohibits"
        and not invalid
        and not duplicates
    )
    return passed, f"invalid={sorted(set(invalid)) or 'none'}; duplicates={duplicates or 'none'}"


def manuscript_citation_contexts(paths: list[Path], source_key: str) -> list[tuple[Path, str]]:
    """Return paragraph-level TeX contexts that actually cite one source key."""
    contexts: list[tuple[Path, str]] = []
    for path in paths:
        for block in re.split(r"\n\s*\n", path.read_text(errors="replace")):
            groups = re.findall(r"\\cite\w*\{([^}]+)\}", block)
            keys = {
                key.strip()
                for group in groups
                for key in group.split(",")
                if key.strip()
            }
            if source_key in keys:
                contexts.append((path, block))
    return contexts


def literature_use_contract_violations(
    policy: dict,
    *,
    cards: dict[str, dict[str, str]],
    manuscript_paths: list[Path],
    admission_ledger: dict,
    text_root: Path = LITERATURE_TEXT,
) -> tuple[list[str], list[str]]:
    """Apply explicit claim boundaries and configured vocabulary-absence rules."""
    claim_violations: list[str] = []
    vocabulary_violations: list[str] = []
    for rule in policy.get("claim_use_contracts", []):
        rule_id = str(rule["id"])
        source_key = str(rule["source_key"])
        evidence = cards.get(source_key, {}).get(str(rule["evidence_field"]), "")
        if not re.search(str(rule["evidence_pattern"]), evidence, flags=re.IGNORECASE | re.DOTALL):
            claim_violations.append(f"{rule_id}:evidence-card-drift")
        for path, context in manuscript_citation_contexts(manuscript_paths, source_key):
            if re.search(str(rule["prohibited_pattern"]), context, flags=re.IGNORECASE | re.DOTALL):
                claim_violations.append(f"{rule_id}:{path.name}")
                break

    manuscript = "\n".join(path.read_text(errors="replace") for path in manuscript_paths)
    admitted = admission_ledger.get("admitted_records", []) if isinstance(admission_ledger, dict) else []
    for rule in policy.get("vocabulary_contracts", []):
        term = str(rule["term"])
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags=re.IGNORECASE)
        paper_uses = len(pattern.findall(manuscript))
        if not paper_uses:
            continue
        classes = set(rule["publication_classes"])
        corpus_keys = {
            str(record.get("key"))
            for record in admitted
            if isinstance(record, dict)
            and record.get("publication_class") in classes
            and str(record.get("key") or "")
        }
        documents: dict[str, str] = {}
        for key in corpus_keys:
            extracts = list(text_root.glob(f"*-{key}-*.txt"))
            if extracts:
                documents[key] = "\n".join(path.read_text(errors="replace") for path in extracts)
        if len(documents) < int(rule["minimum_documents"]):
            vocabulary_violations.append(
                f"{rule['id']}:corpus-coverage={len(documents)}/{rule['minimum_documents']}"
            )
            continue
        corpus_hits = sum(bool(pattern.search(text)) for text in documents.values())
        if corpus_hits == 0:
            vocabulary_violations.append(
                f"{rule['id']}:paper={paper_uses},corpus=0/{len(documents)}"
            )
    return claim_violations, vocabulary_violations


def unresolved_source_set_artifacts(
    source_set: dict,
    materialized: dict[str, bool],
    *,
    root: Path = ROOT,
) -> list[str]:
    """Name missing main/companion artifacts so a failed literature gate is actionable."""
    main_key = str(source_set.get("main") or "")
    missing = [] if source_set_main_artifact_closed(source_set, materialized, root=root) else [main_key]
    companions = source_set.get("companions", [])
    if isinstance(companions, list):
        missing.extend(
            key
            for key in companions
            if isinstance(key, str)
            and not source_set_companion_disposition_resolved(key, materialized, root=root)
        )
    return missing


def validate_literature_audit(
    text: str,
    cited_keys: set[str],
    venue_cards: set[str],
    *,
    verify_source_sets: bool = False,
    manuscript_paths: list[Path] | None = None,
    use_contracts: dict | None = None,
    admission_ledger: dict | None = None,
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
        if (fields := literature_card_for_requirement(cards, key))
        and complete_literature_card(fields)
        and (
            not verify_source_sets
            or literature_source_key(fields) in source_sets
        )
        and companion_sources_closed(
            fields,
            materialized=materialized,
            source_text=card_source_evidence_text(fields) if verify_source_sets else None,
            source_set=(
                source_sets.get(literature_source_key(fields))
                if verify_source_sets
                else None
            ),
        )
    }
    verified_citations = {
        key
        for key in cited_keys
        if literature_card_for_requirement(cards, key).get("status")
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
    claim_violations: list[str] = []
    vocabulary_violations: list[str] = []
    finding_selling_complete = all(
        marker in text for marker in LITERATURE_FINDING_SELLING_MARKERS
    )
    policy_valid = True
    policy_detail = "not-configured"
    if use_contracts is not None:
        policy_valid, policy_detail = validate_literature_use_contracts(use_contracts)
        if policy_valid and manuscript_paths is not None and admission_ledger is not None:
            claim_violations, vocabulary_violations = literature_use_contract_violations(
                use_contracts,
                cards=cards,
                manuscript_paths=manuscript_paths,
                admission_ledger=admission_ledger,
            )
        elif policy_valid:
            policy_valid = False
            policy_detail = "manuscript_paths and admission_ledger are required"
    missing_artifacts: list[str] = []
    overclosed_cards: list[str] = []
    if verify_source_sets and materialized is not None:
        for key in sorted(required_source_keys):
            source_set = source_sets.get(key)
            if source_set:
                missing_artifacts.extend(unresolved_source_set_artifacts(source_set, materialized))
        for card_key in sorted(required_cards):
            fields = cards.get(card_key, {})
            source_set = source_sets.get(literature_source_key(fields))
            if (
                fields.get("companions", "").strip().lower().startswith("complete:")
                and source_set
                and any(
                    companion in missing_artifacts
                    for companion in source_set.get("companions", [])
                    if isinstance(companion, str)
                )
            ):
                overclosed_cards.append(card_key)
    passed = bool(
        frontmatter.get("status") == "complete"
        and (not verify_source_sets or closed_source_sets == required_source_keys)
        and complete_cards == required_cards
        and verified_citations == cited_keys
        and read_venues == venue_cards
        and independent == central
        and finding_selling_complete
        and policy_valid
        and not claim_violations
        and not vocabulary_violations
    )
    return passed, (
        f"status={frontmatter.get('status') or 'missing'}; "
        f"source-sets={len(closed_source_sets)}/{len(required_source_keys)}; "
        f"five-axis-cards={len(complete_cards)}/{len(required_cards)}; "
        f"cited={len(verified_citations)}/{len(cited_keys)}; "
        f"venue={len(read_venues)}/{len(venue_cards)}; "
        f"independent={len(independent)}/{len(central)}; "
        f"finding-selling={'complete' if finding_selling_complete else 'incomplete'}; "
        f"policy={policy_detail if not policy_valid else 'valid'}; "
        f"claim-use={claim_violations or 'none'}; "
        f"vocabulary={vocabulary_violations or 'none'}; "
        f"missing-artifacts={sorted(set(missing_artifacts)) or 'none'}; "
        f"overclosed={overclosed_cards or 'none'}"
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
        try:
            paths = registered_empirical_consumers()
        except ValueError as error:
            return False, f"claim execution policy invalid: {error}"
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


def validate_liquidity_contracts() -> tuple[bool, str]:
    """Require one coherent capital/depth/LVR contract for every canonical venue."""

    try:
        require_contract_coverage(set(DEX_SOURCES))
    except ValueError as exc:
        return False, str(exc)
    invalid: list[str] = []
    for (venue, family), contract in LIQUIDITY_CONTRACTS.items():
        label = f"{venue}/{family}"
        if not contract.invariant_family or not contract.capital_measure:
            invalid.append(f"{label}:missing meaning")
        if contract.venue != venue or contract.pool_family != family:
            invalid.append(f"{label}:registry key differs from contract identity")
        if contract.capital_ready and not contract.capital_sources:
            invalid.append(f"{label}:ready capital lacks permitted provenance")
        if any(
            marker in source.lower()
            for source in contract.capital_sources
            for marker in ("virtual", "local_depth", "band_depth")
        ):
            invalid.append(f"{label}:capital provenance names a depth quantity")
        for capability in contract.capabilities:
            if capability.ready and not (
                capability.state_generation
                and capability.materializer
                and capability.validation
                and capability.admissible_uses
            ):
                invalid.append(
                    f"{label}:{capability.quantity_kind} lacks state, materializer, validation, or admitted use"
                )
            if capability.ready and capability.materializer:
                try:
                    resolve_materializer(capability.materializer)
                except (ImportError, ValueError) as exc:
                    invalid.append(
                        f"{label}:{capability.quantity_kind} has no callable materializer ({exc})"
                    )
        if contract.band_depth_adapter is not None and contract.quote_adapter is None:
            invalid.append(f"{label}:band depth lacks an exact-quote adapter")
        if contract.lvr_adapter is not None and contract.local_depth_adapter is None:
            invalid.append(f"{label}:LVR lacks an invariant-local depth adapter")
        if contract.return_inference_ready and (
            not contract.capital_ready or contract.lvr_adapter is None
        ):
            invalid.append(f"{label}:return model lacks capital or LVR")
    venues = {venue for venue, _family in LIQUIDITY_CONTRACTS}
    return not invalid, (
        f"venues={len(venues)}/{len(DEX_SOURCES)}; families={len(LIQUIDITY_CONTRACTS)}; "
        f"capital-ready={sum(c.capital_ready for c in LIQUIDITY_CONTRACTS.values())}; "
        f"quote-ready={sum(c.quote_adapter is not None for c in LIQUIDITY_CONTRACTS.values())}; "
        f"band-depth-ready={sum(c.band_depth_adapter is not None for c in LIQUIDITY_CONTRACTS.values())}; "
        f"return-ready={sum(c.return_inference_ready for c in LIQUIDITY_CONTRACTS.values())}; "
        f"invalid={invalid or 'none'}"
    )


def validate_quote_state_contract_rows(rows: pd.DataFrame) -> tuple[bool, str]:
    """Bind canonical state family, invariant, generation, and quote admission."""

    required = {
        "venue",
        "pool_family",
        "invariant_family",
        "state_generation",
        "quote_supported",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        return False, f"missing_columns={missing}"
    invalid: list[str] = []
    observed = rows[list(required)].drop_duplicates()
    for row in observed.itertuples(index=False):
        venue = str(row.venue)
        family = str(row.pool_family)
        invariant = str(row.invariant_family)
        generation = str(row.state_generation)
        label = f"{venue}/{family}/{generation}"
        contract = LIQUIDITY_CONTRACTS.get((venue, family))
        if contract is None:
            invalid.append(f"{label}:unregistered family")
            continue
        if invariant != contract.invariant_family:
            invalid.append(f"{label}:invariant mismatch")
        if generation != STATE_GENERATIONS.get(venue):
            invalid.append(f"{label}:state generation mismatch")
        if bool(row.quote_supported) and not pool_semantics(
            venue, family, generation
        )[1]:
            invalid.append(f"{label}:unsupported quote admitted")
    return not invalid, (
        f"state-contracts={len(observed)}; invalid={invalid or 'none'}"
    )


def quote_state_artifact_check() -> tuple[bool, str]:
    """Read distinct state contracts across every materialized family partition."""

    missing: list[str] = []
    contracts: list[pd.DataFrame] = []
    for family, venues in FAMILY_STREAMS.items():
        for venue in venues:
            try:
                release = released_state_partitions(
                    family,
                    venue,
                    ("venue", "pool_family", "invariant_family", "state_generation", "quote_supported"),
                    include_quarantined=True,
                )
                contracts.append(
                    pd.concat(
                        [release.read_day(day).drop_duplicates() for day in release.days],
                        ignore_index=True,
                    ).drop_duplicates()
                )
                release.assert_current()
            except (OSError, RuntimeError, ValueError) as exc:
                missing.append(f"{family}/{venue}:{type(exc).__name__}")
    if missing:
        return False, f"missing_or_invalid={missing}"
    rows = pd.concat(contracts, ignore_index=True) if contracts else pd.DataFrame()
    return validate_quote_state_contract_rows(rows)


def active_claim_requires_wide_state(payload: dict) -> bool:
    """Gate the optional wide state cache only when an executable claim names it."""

    inputs = executable_claim_inputs(payload)
    return any(
        path == "data/processed/market_state_quality.parquet"
        or path.startswith("data/processed/market_state/")
        for path in inputs
    )


def executable_claim_inputs(payload: dict) -> frozenset[str]:
    """Return the exact artifact perimeter of claims executable at this stage."""

    perimeter = claim_execution_perimeter(payload)
    return frozenset(
        str(path)
        for claim in perimeter.executable_claims
        for path in claim.get("inputs", [])
    )


def active_claim_requires_any(payload: dict, paths: tuple[str, ...]) -> bool:
    """Decide whether one diagnostic family can affect an executable claim."""

    return bool(executable_claim_inputs(payload).intersection(paths))


def validate_capital_contract_rows(rows: pd.DataFrame) -> tuple[bool, str]:
    """Bind every materialized capital row family/generation/source to the registry."""

    missing = sorted(set(CAPITAL_CONTRACT_COLUMNS) - set(rows.columns))
    if missing:
        return False, f"missing_columns={missing}"
    actual = {
        tuple(str(value) for value in row)
        for row in rows[list(CAPITAL_CONTRACT_COLUMNS)].drop_duplicates().itertuples(
            index=False,
            name=None,
        )
    }
    expected = {
        (
            contract.venue,
            contract.pool_family,
            contract.invariant_family,
            str(contract.capability("deposited_capital").state_generation),
            "deposited_capital",
            source,
        )
        for contract in LIQUIDITY_CONTRACTS.values()
        if contract.capital_ready
        for source in contract.capital_sources
    }
    missing_contracts = sorted(expected - actual)
    unsupported = sorted(actual - expected)
    return not missing_contracts and not unsupported, (
        f"observed={len(actual)}; expected={len(expected)}; "
        f"missing={missing_contracts or 'none'}; unsupported={unsupported or 'none'}"
    )


def capital_artifact_checks(
    capital_release: CapitalRelease | None = None,
) -> list[tuple[str, bool, str]]:
    """Audit capital identities, exact lags, allocation conservation, and quarantine."""

    try:
        selected = capital_release or resolve_capital_release()
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return [("node D capital release current", False, f"{type(exc).__name__}: {exc}")]
    pool_path = selected.artifacts["pool"]
    candidate_path = selected.artifacts["candidate"]
    rejection_path = selected.artifacts["rejection"]
    overlap_path = selected.artifacts["overlap"]
    artifacts = (pool_path, candidate_path, rejection_path, overlap_path)
    missing = [path.name for path in artifacts if not path.is_file()]
    if missing:
        return [("node D capital artifacts current", False, f"missing={missing}")]
    provenance = {path.name: verify(path).get("status") for path in artifacts}
    results: list[tuple[str, bool, str]] = [
        (
            "node D capital release current",
            True,
            f"generation={selected.generation_id}; artifacts={len(selected.artifacts)}",
        ),
        (
            "node D capital artifacts current",
            all(status == "ok" for status in provenance.values()),
            f"provenance={provenance}",
        )
    ]
    required = {
        pool_path: {
            *CAPITAL_CONTRACT_COLUMNS,
            "day",
            "pool",
            "reported_capital_usd",
            "reported_capital_source",
            "reconstructed_capital_usd",
            CAPITAL_CURRENT_COLUMN,
            CAPITAL_COLUMN,
            "capital_reconciliation_ratio",
            "balance_value_ratio",
            "reserve_source",
            "reserve_state_timestamp",
            "reserve_validation_status",
            "identity_validation_status",
            "token_mechanics_status",
            "provider_overlap_status",
            "provider_reconciliation_status",
            "token_mechanics_status",
            "price_source",
            "capital_validation_status",
            "failure_reason",
            "capital_valid",
            "exact_lag_valid",
            "token0_address",
            "token1_address",
        },
        candidate_path: {
            *CAPITAL_CONTRACT_COLUMNS,
            "day",
            "pool",
            "candidate",
            "allocation_weight",
            "candidate_capital_usd",
            "candidate_capital_usd_lagged",
            "provider_overlap_status",
            "provider_reconciliation_status",
            "price_source",
            "capital_validation_status",
            "exact_lag_valid",
        },
        rejection_path: {
            "venue",
            "day",
            "pool",
            "token0_address",
            "token1_address",
            "reported_capital_usd",
            "reported_capital_source",
            "reconstructed_capital_usd",
            "capital_reconciliation_ratio",
            "balance_value_ratio",
            "reserve_source",
            "reserve_state_timestamp",
            "reserve_validation_status",
            "identity_validation_status",
            "token_mechanics_status",
            "provider_overlap_status",
            "provider_reconciliation_status",
            "capital_source",
            "price_source",
            "quantity_kind",
            "pool_family",
            "invariant_family",
            "state_generation",
            "capital_validation_status",
            "failure_reason",
        },
    }
    missing_columns = {
        path.name: sorted(columns - set(pq.ParquetFile(path).schema_arrow.names))
        for path, columns in required.items()
        if columns - set(pq.ParquetFile(path).schema_arrow.names)
    }
    results.append(
        (
            "node D capital schemas",
            not missing_columns,
            f"missing_columns={missing_columns or 'none'}",
        )
    )
    if missing_columns:
        return results
    try:
        overlap = pd.read_json(overlap_path, lines=True)
        overlap_required = {
            "venue",
            "era",
            "candidate",
            "provider_overlap_row_share",
            "provider_overlap_capital_share",
            "provider_disagreement_row_share",
            "provider_disagreement_capital_share",
            "materiality_status",
        }
        overlap_missing = sorted(overlap_required - set(overlap.columns))
        share_columns = [column for column in overlap_required if column.endswith("_share")]
        shares_valid = all(
            pd.to_numeric(overlap[column], errors="coerce").dropna().between(0, 1).all()
            for column in share_columns
            if column in overlap
        )
        overlap_valid = bool(
            not overlap.empty
            and not overlap_missing
            and not overlap.duplicated(["venue", "era", "candidate"]).any()
            and shares_valid
            and overlap["materiality_status"].notna().all()
        )
    except (OSError, TypeError, ValueError):
        overlap_missing, overlap_valid = ["unreadable"], False
    results.append(
        (
            "node D provider-capital overlap and support diagnostics",
            overlap_valid,
            f"rows={len(overlap) if 'overlap' in locals() else 0}; missing_columns={overlap_missing or 'none'}",
        )
    )

    con = duckdb.connect()
    con.execute("SET memory_limit='1500MB'")
    con.execute("SET threads=2")
    con.execute(f"SET temp_directory='{(ROOT / 'data' / 'processed' / '_duckdb_tmp').as_posix()}'")
    pool = f"read_parquet('{pool_path.as_posix()}')"
    candidate = f"read_parquet('{candidate_path.as_posix()}')"
    rejection = f"read_parquet('{rejection_path.as_posix()}')"
    valid_statuses = ",".join(f"'{status}'" for status in sorted(VALID_CAPITAL_STATUSES))
    try:
        contract_rows = con.execute(
            f"SELECT DISTINCT {','.join(CAPITAL_CONTRACT_COLUMNS)} FROM {pool}"
        ).df()
        contract_passed, contract_detail = validate_capital_contract_rows(contract_rows)
        results.append(("node D capital family contracts", contract_passed, contract_detail))

        pool_core = con.execute(
            f"""
            SELECT
                count(*) AS rows,
                count(DISTINCT (venue, day, pool)) AS unique_rows,
                count(*) FILTER (
                    WHERE capital_valid != coalesce(
                        isfinite(capital_usd)
                        AND capital_usd > 0
                        AND capital_validation_status IN ({valid_statuses}),
                        false
                    )
                ) AS validity_mismatch,
                count(*) FILTER (
                    WHERE (capital_validation_status IN ({valid_statuses})) != capital_valid
                ) AS status_mismatch,
                count(*) FILTER (
                    WHERE exact_lag_valid AND (
                        capital_usd_lagged IS NULL OR NOT isfinite(capital_usd_lagged)
                    )
                ) AS valid_lag_missing,
                count(*) FILTER (
                    WHERE NOT exact_lag_valid AND capital_usd_lagged IS NOT NULL
                ) AS invalid_lag_payload
            FROM {pool}
            """
        ).fetchone()
        pool_passed = bool(
            pool_core[0] == pool_core[1]
            and not any(pool_core[index] for index in range(2, 6))
        )
        results.append(
            (
                "node D capital row contract",
                pool_passed,
                f"rows={pool_core[0]:,}; unique={pool_core[1]:,}; "
                f"validity_mismatch={pool_core[2]:,}; status_mismatch={pool_core[3]:,}; "
                f"valid_lag_missing={pool_core[4]:,}; invalid_lag_payload={pool_core[5]:,}",
            )
        )

        lag_core = con.execute(
            f"""
            WITH ordered AS (
                SELECT *,
                    lag(day) OVER (PARTITION BY venue, pool ORDER BY day) AS prior_day,
                    lag(capital_usd) OVER (
                        PARTITION BY venue, pool ORDER BY day
                    ) AS prior_capital,
                    lag(capital_valid) OVER (
                        PARTITION BY venue, pool ORDER BY day
                    ) AS prior_valid
                FROM {pool}
            )
            SELECT
                count(*) FILTER (
                    WHERE exact_lag_valid != coalesce(
                        capital_valid AND prior_valid
                        AND strptime(day, '%Y%m%d') =
                            strptime(prior_day, '%Y%m%d') + INTERVAL 1 DAY,
                        false
                    )
                ) AS flag_mismatch,
                count(*) FILTER (
                    WHERE exact_lag_valid AND abs(capital_usd_lagged-prior_capital) >
                        greatest(1e-8, abs(prior_capital)*1e-12)
                ) AS value_mismatch
            FROM ordered
            """
        ).fetchone()
        results.append(
            (
                "node D capital exact-lag identity",
                not lag_core[0] and not lag_core[1],
                f"flag_mismatch={lag_core[0]:,}; value_mismatch={lag_core[1]:,}",
            )
        )

        allocation = con.execute(
            f"""
            WITH allocated AS (
                SELECT venue, day, pool,
                    sum(allocation_weight) AS weight,
                    sum(candidate_capital_usd) AS capital,
                    sum(candidate_capital_usd_lagged) AS lagged,
                    count(*) AS candidate_rows
                FROM {candidate}
                GROUP BY venue, day, pool
            ), joined AS (
                SELECT a.*, p.capital_usd, p.capital_usd_lagged,
                    p.exact_lag_valid
                FROM allocated a
                JOIN {pool} p USING (venue, day, pool)
            )
            SELECT
                count(*) AS pools,
                count(*) FILTER (WHERE abs(weight-1)>1e-12) AS weight_fail,
                count(*) FILTER (
                    WHERE abs(capital-capital_usd) >
                        greatest(1e-8, abs(capital_usd)*1e-12)
                ) AS capital_fail,
                count(*) FILTER (
                    WHERE exact_lag_valid AND abs(lagged-capital_usd_lagged) >
                        greatest(1e-8, abs(capital_usd_lagged)*1e-12)
                ) AS lagged_fail,
                count(*) FILTER (
                    WHERE NOT exact_lag_valid AND lagged IS NOT NULL
                ) AS invalid_lag_payload
            FROM joined
            """
        ).fetchone()
        results.append(
            (
                "node D candidate-capital conservation",
                not any(allocation[index] for index in range(1, 5)),
                f"pool_days={allocation[0]:,}; weight_fail={allocation[1]:,}; "
                f"capital_fail={allocation[2]:,}; lagged_fail={allocation[3]:,}; "
                f"invalid_lag_payload={allocation[4]:,}",
            )
        )

        rejected = con.execute(
            f"""
            WITH expected AS (
                SELECT venue, day, pool, reported_capital_usd
                FROM {pool}
                WHERE NOT capital_valid
            ), actual AS (SELECT * FROM {rejection})
            SELECT
                (SELECT count(*) FROM expected) AS expected,
                (SELECT count(*) FROM actual) AS actual,
                (SELECT count(*) FROM expected e LEFT JOIN actual r
                    USING (venue, day, pool) WHERE r.pool IS NULL) AS missing,
                (SELECT count(*) FROM actual r LEFT JOIN expected e
                    USING (venue, day, pool) WHERE e.pool IS NULL) AS extra,
                (SELECT coalesce(sum(reported_capital_usd), 0) FROM actual) AS capital
            """
        ).fetchone()
        results.append(
            (
                "node D capital rejection ledger",
                rejected[0] == rejected[1] and not rejected[2] and not rejected[3],
                f"rows={rejected[1]:,}/{rejected[0]:,}; missing={rejected[2]:,}; "
                f"extra={rejected[3]:,}; capital_usd={rejected[4]:,.2f}",
            )
        )

        reserve_streams = {}
        for venue in ("uniswap_v2", "sushiswap_v2"):
            reserve_streams[venue] = certified_cp_state_stream(
                venue,
                calendar_days(
                    max(RESEARCH_SAMPLE_START, get_source(venue).genesis.strftime("%Y%m%d")),
                    RESEARCH_SAMPLE_END,
                ),
                raw_root=RAW_ROOT,
            )
        coverage = con.execute(
            f"""
            SELECT
                (SELECT count(*) FROM {pool} WHERE reserve_source!='certified_hourly_reserve_snapshot'),
                (SELECT count(*) FROM {pool} WHERE capital_source!='{CAPITAL_SOURCE}'),
                (SELECT count(*) FROM {pool} WHERE failure_reason LIKE '%reported_capital%')
            """
        ).fetchone()
        manifest_support = {
            (str((shard.get("spec") or {}).get("venue")), str(record.get("day"))): record
            for shard in selected.manifest.get("shards") or []
            for record in shard.get("daily_support") or []
        }
        expected_support = {
            (venue, day)
            for venue, stream in reserve_streams.items()
            for day in stream.days
        }
        support_mismatch = expected_support.symmetric_difference(manifest_support)
        results.append(
            (
                "node D capital certified-reserve perimeter and source ownership",
                not any(coverage) and not support_mismatch,
                f"support_mismatch={len(support_mismatch):,}; "
                f"bad_reserve_source={coverage[0]:,}; bad_capital_source={coverage[1]:,}; "
                f"provider_eligibility_failures={coverage[2]:,}",
            )
        )
        manifest_releases = selected.manifest.get("certified_reserve_stream") or {}
        release_identity_mismatch = [
            venue
            for venue, reserve_stream in reserve_streams.items()
            if (manifest_releases.get(venue) or {}).get("content_identity_sha256")
            != reserve_stream.content_identity_sha256
        ]
        results.append(
            (
                "node D capital certified-reserve identities",
                not release_identity_mismatch,
                f"mismatch={release_identity_mismatch or 'none'}",
            )
        )
    except (duckdb.Error, OSError, ValueError) as exc:
        results.append(("node D capital artifact audit", False, f"{type(exc).__name__}: {exc}"))
    finally:
        con.close()
    return results


def token_price_artifact_checks() -> list[tuple[str, bool, str]]:
    """Audit the canonical address-day price owner before downstream valuation."""

    if not TOKEN_PRICE_DAILY_PANEL.exists():
        return [("node D token-price artifact", False, "missing canonical panel")]
    try:
        prices = load_canonical_token_prices(TOKEN_PRICE_DAILY_PANEL)
    except (OSError, RuntimeError, ValueError) as exc:
        return [("node D token-price canonical release", False, f"{type(exc).__name__}: {exc}")]
    candidates = prices.loc[prices["token"].isin(VEHICLE_CANDIDATES)]
    return [
        (
            "node D token-price canonical release",
            True,
            f"rows={len(prices):,}; candidate_rows={len(candidates):,}; candidate_days={candidates['day'].nunique():,}; content_sha256={prices.attrs['content_sha256']}",
        )
    ]


def cex_reference_support_checks(
    path: Path = CEX_REFERENCE_SUPPORT,
    *,
    expected_rows: int = 43,
    expected_sample_rows: int = 4_113,
) -> list[tuple[str, bool, str]]:
    """Audit the positive-only, exact-address external-price support perimeter."""

    if not path.is_file():
        return [("node D CEX positive-support registry", False, "missing canonical panel")]
    required = {
        "token_address", "token_symbol", "dex_pool", "binance_symbol",
        "binance_base_asset", "binance_quote_asset", "source_dex_creation_at",
        "binance_sample_first_at", "binance_sample_last_at", "binance_sample_rows",
        "support_definition", "source_publication",
    }
    columns = set(pq.ParquetFile(path).schema_arrow.names)
    missing = sorted(required - columns)
    results = [
        (
            "node D CEX positive-support provenance and schema",
            verify(path).get("status") == "ok" and not missing,
            f"provenance={verify(path).get('status')}; missing_columns={missing or 'none'}",
        )
    ]
    if missing:
        return results
    frame = pd.read_parquet(path)
    address_ok = frame["token_address"].astype(str).str.fullmatch(r"0x[0-9a-f]{40}")
    semantics_ok = frame["support_definition"].eq(
        "positive_observed_uniswap_binance_reference_support"
    )
    first = pd.to_datetime(frame["binance_sample_first_at"], errors="coerce")
    last = pd.to_datetime(frame["binance_sample_last_at"], errors="coerce")
    sample_rows = pd.to_numeric(frame["binance_sample_rows"], errors="coerce")
    passed = bool(
        len(frame) == expected_rows
        and frame["token_address"].nunique() == expected_rows
        and frame["binance_symbol"].nunique() == expected_rows
        and frame["dex_pool"].nunique() == expected_rows
        and address_ok.all()
        and semantics_ok.all()
        and first.notna().all()
        and last.notna().all()
        and first.le(last).all()
        and sample_rows.gt(0).all()
        and int(sample_rows.sum()) == expected_sample_rows
        and not frame["binance_symbol"].isin({"BONDETH", "PROSETH"}).any()
    )
    results.append(
        (
            "node D CEX positive-support identity and bounds",
            passed,
            f"rows={len(frame):,}/{expected_rows:,}; addresses={frame['token_address'].nunique():,}; "
            f"pairs={frame['binance_symbol'].nunique():,}; sample_rows={int(sample_rows.sum()):,}/"
            f"{expected_sample_rows:,}; range={first.min()}..{last.max()}",
        )
    )
    return results


def _route_cost_partition_invariants(path: Path) -> tuple[int, int, int, int]:
    """Check date-separable panel invariants without grouping the full release."""

    parquet = pq.ParquetFile(path)
    date_index = parquet.schema_arrow.names.index("date")
    intervals: list[tuple[object, object, int, int]] = []
    for row_group in range(parquet.num_row_groups):
        metadata = parquet.metadata.row_group(row_group)
        statistics = metadata.column(date_index).statistics
        if statistics is None or not statistics.has_min_max:
            raise ValueError(
                "route-cost date statistics are required for the exact bounded-memory audit"
            )
        minimum = statistics.min
        maximum = statistics.max
        if isinstance(minimum, bytes):
            minimum = minimum.decode()
        if isinstance(maximum, bytes):
            maximum = maximum.decode()
        intervals.append((minimum, maximum, row_group, metadata.num_rows))

    # Any row groups whose date ranges overlap must be checked together.  The
    # resulting components are independent because date belongs to every key
    # used below.  Adjacent components may therefore be batched for I/O without
    # changing the full-panel GROUP BY result.
    components: list[list[tuple[int, int]]] = []
    component_maximum: object | None = None
    for minimum, maximum, row_group, rows in sorted(intervals):
        if components and component_maximum is not None and minimum <= component_maximum:
            components[-1].append((row_group, rows))
            component_maximum = max(component_maximum, maximum)
        else:
            components.append([(row_group, rows)])
            component_maximum = maximum

    batches: list[list[int]] = []
    batch_rows = 0
    for component in components:
        component_rows = sum(rows for _row_group, rows in component)
        if batches and batch_rows + component_rows > 100_000:
            batch_rows = 0
        if not batches or batch_rows == 0:
            batches.append([])
        batches[-1].extend(row_group for row_group, _rows in component)
        batch_rows += component_rows

    audit_columns = list(
        dict.fromkeys(
            [
                *QUOTE_CELL_KEYS,
                "direct_output_usd",
                "direct_source",
                "direct_pool",
                "realized_bridge_volume_usd",
                "n_realized_routes",
            ]
        )
    )
    totals = [0, 0, 0, 0]
    con = duckdb.connect()
    con.execute("SET memory_limit='256MB'")
    con.execute("SET threads=1")
    con.execute("SET preserve_insertion_order=false")
    con.execute(
        f"SET temp_directory='{(ROOT / 'data' / 'processed' / '_duckdb_tmp').as_posix()}'"
    )
    try:
        for row_groups in batches:
            table = parquet.read_row_groups(row_groups, columns=audit_columns)
            con.register("route_cost_partition", table)
            duplicates = con.execute(
                """
                WITH by_date AS (
                    SELECT date, count(*) AS rows,
                        count(DISTINCT (
                            reserve_hour_utc, src, tgt, vehicle, trade_size_usd
                        )) AS unique_rows
                    FROM route_cost_partition
                    GROUP BY date
                )
                SELECT coalesce(sum(rows - unique_rows), 0),
                    count(*) FILTER (WHERE rows!=unique_rows)
                FROM by_date
                """
            ).fetchone()
            direct_cells = con.execute(
                """
                WITH direct_cells AS (
                    SELECT date, reserve_hour_utc, src, tgt, trade_size_usd,
                        count(DISTINCT direct_output_usd) AS outputs,
                        count(DISTINCT direct_source) AS sources,
                        count(DISTINCT direct_pool) AS pools
                    FROM route_cost_partition
                    GROUP BY date, reserve_hour_utc, src, tgt, trade_size_usd
                )
                SELECT count(*) FROM direct_cells
                WHERE outputs>1 OR sources>1 OR pools>1
                """
            ).fetchone()
            realized_cells = con.execute(
                """
                WITH realized_cells AS (
                    SELECT date, reserve_hour_utc, src, tgt,
                        count(DISTINCT realized_bridge_volume_usd) AS volumes,
                        count(DISTINCT n_realized_routes) AS routes
                    FROM route_cost_partition
                    GROUP BY date, reserve_hour_utc, src, tgt
                )
                SELECT count(*) FROM realized_cells WHERE volumes>1 OR routes>1
                """
            ).fetchone()
            values = (*duplicates, direct_cells[0], realized_cells[0])
            totals = [total + int(value) for total, value in zip(totals, values)]
            con.unregister("route_cost_partition")
    finally:
        con.close()
    return totals[0], totals[1], totals[2], totals[3]


def route_cost_panel_checks(
    path: Path = PANEL,
) -> list[tuple[str, bool, str]]:
    """Audit the release-grade route-cost panel's economic-cell semantics."""

    if not path.is_file():
        return [("node D route-cost panel", False, "missing canonical panel")]
    required = {
        *QUOTE_CELL_KEYS,
        "method",
        "direct_available",
        "vehicle_available",
        "direct_output_usd",
        "vehicle_output_usd",
        "direct_cost_advantage",
        "direct_source",
        "direct_pool",
        "hop1_source",
        "hop1_pool",
        "hop2_source",
        "hop2_pool",
        "realized_bridge_volume_usd",
        "n_realized_routes",
    }
    columns = set(pq.ParquetFile(path).schema_arrow.names)
    missing = sorted(required - columns)
    provenance = verify(path).get("status")
    results = [
        (
            "node D route-cost provenance and schema",
            provenance == "ok" and not missing,
            f"provenance={provenance}; missing_columns={missing or 'none'}",
        )
    ]
    if missing:
        return results

    admitted_sources = sorted(
        {
            venue
            for (venue, _family), contract in LIQUIDITY_CONTRACTS.items()
            if contract.capability("quote_quality").ready
            and contract.capability("executable_band_depth").ready
        }
    )
    candidates = sorted(VEHICLE_CANDIDATES)
    expected_hours = list(MAIN_ROUTE_COST_SPEC.hours_utc)
    expected_sizes = list(MAIN_ROUTE_COST_SPEC.trade_sizes_usd)
    con = duckdb.connect()
    # Keep the full-panel read-only scans below the grind executor's resident-
    # memory ceiling.  The higher setting exceeded the process allowance before
    # the bounded uniqueness and invariance checks could run.
    con.execute("SET memory_limit='512MB'")
    con.execute("SET threads=1")
    con.execute("SET preserve_insertion_order=false")
    con.execute(
        f"SET temp_directory='{(ROOT / 'data' / 'processed' / '_duckdb_tmp').as_posix()}'"
    )
    try:
        core = con.execute(
            """
            WITH panel AS (
                SELECT *,
                    direct_available AND vehicle_available AS common_support,
                    (direct_output_usd - vehicle_output_usd) / direct_output_usd
                        AS reconstructed_advantage
                FROM read_parquet(?)
            )
            SELECT count(*) AS rows,
                count(*) FILTER (WHERE method!='v2_cp_plus_v3_exact_tick') AS bad_method,
                count(*) FILTER (
                    WHERE src=tgt OR vehicle=src OR vehicle=tgt OR vehicle NOT IN (SELECT unnest(?))
                ) AS bad_identity,
                count(*) FILTER (
                    WHERE direct_output_usd < 0 OR vehicle_output_usd < 0
                       OR NOT isfinite(direct_output_usd) OR NOT isfinite(vehicle_output_usd)
                ) AS bad_output,
                count(*) FILTER (
                    WHERE direct_available IS DISTINCT FROM (direct_output_usd > 0)
                       OR vehicle_available IS DISTINCT FROM (vehicle_output_usd > 0)
                ) AS bad_availability,
                count(*) FILTER (
                    WHERE (common_support AND (
                              NOT isfinite(direct_cost_advantage)
                              OR abs(direct_cost_advantage - reconstructed_advantage)
                                 > 1e-12 * greatest(1.0, abs(reconstructed_advantage))
                          ))
                       OR (NOT common_support AND isfinite(direct_cost_advantage))
                ) AS bad_cost,
                count(*) FILTER (
                    WHERE direct_available IS DISTINCT FROM (
                              direct_source IS NOT NULL AND direct_pool IS NOT NULL
                          )
                       OR vehicle_available IS DISTINCT FROM (
                              hop1_source IS NOT NULL AND hop1_pool IS NOT NULL
                              AND hop2_source IS NOT NULL AND hop2_pool IS NOT NULL
                          )
                ) AS bad_path_lineage,
                count(*) FILTER (
                    WHERE (direct_source IS NOT NULL AND direct_source NOT IN (SELECT unnest(?)))
                       OR (hop1_source IS NOT NULL AND hop1_source NOT IN (SELECT unnest(?)))
                       OR (hop2_source IS NOT NULL AND hop2_source NOT IN (SELECT unnest(?)))
                ) AS bad_source,
                count(*) FILTER (
                    WHERE realized_bridge_volume_usd < 0
                       OR NOT isfinite(realized_bridge_volume_usd)
                       OR n_realized_routes <= 0
                ) AS bad_realized_support
            FROM panel
            """,
            [str(path), candidates, admitted_sources, admitted_sources, admitted_sources],
        ).fetchone()
        results.append(
            (
                "node D route-cost row semantics",
                bool(core[0]) and not any(core[index] for index in range(1, 9)),
                f"rows={core[0]:,}; method={core[1]:,}; identity={core[2]:,}; "
                f"output={core[3]:,}; availability={core[4]:,}; cost={core[5]:,}; "
                f"path_lineage={core[6]:,}; source={core[7]:,}; "
                f"realized_support={core[8]:,}",
            )
        )

        scope = con.execute(
            """
            SELECT list_sort(list(DISTINCT reserve_hour_utc)),
                list_sort(list(DISTINCT trade_size_usd)),
                count(DISTINCT date), min(date), max(date)
            FROM read_parquet(?)
            """,
            [str(path)],
        ).fetchone()
        observed_hours = [int(value) for value in scope[0]]
        observed_sizes = [float(value) for value in scope[1]]
        results.append(
            (
                "node D route-cost declared scope",
                observed_hours == expected_hours and observed_sizes == expected_sizes,
                f"hours={observed_hours}; sizes={observed_sizes}; days={scope[2]:,}; "
                f"range={scope[3]}..{scope[4]}",
            )
        )

        con.close()
        con = None
        duplicates_and_invariance = _route_cost_partition_invariants(path)
        duplicates = duplicates_and_invariance[:2]
        results.append(
            (
                "node D route-cost unique economic cells",
                not duplicates[0] and not duplicates[1],
                f"duplicate_rows={duplicates[0]:,}; affected_dates={duplicates[1]:,}",
            )
        )

        invariance = duplicates_and_invariance[2:]
        results.append(
            (
                "node D route-cost repeated-input invariance",
                not invariance[0] and not invariance[1],
                f"direct_cells={invariance[0]:,}; realized_cells={invariance[1]:,}",
            )
        )
    except (duckdb.Error, OSError, ValueError) as exc:
        results.append(("node D route-cost semantic audit", False, f"{type(exc).__name__}: {exc}"))
    finally:
        if con is not None:
            con.close()
    return results


def rent_incidence_artifact_checks(
    rent_path: Path = RENT_V2_PANEL,
    capital_release: CapitalRelease | None = None,
) -> list[tuple[str, bool, str]]:
    """Audit the construction-only V2 rent panel before any screen or estimator."""

    try:
        selected_capital = capital_release or resolve_capital_release()
        capital_path = selected_capital.artifacts["pool"]
        reserve_authority = selected_capital.manifest["certified_reserve_stream"]["uniswap_v2"]
        event_stream = certified_cp_event_stream(
            "uniswap_v2",
            [str(partition["day"]) for partition in reserve_authority["partitions"]],
            raw_root=RAW_ROOT,
        )
        event_stream.assert_current()
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return [("node D V2 rent construction", False, f"purpose-bound source: {type(exc).__name__}: {exc}")]
    if not rent_path.is_file() or not capital_path.is_file():
        missing = [path.name for path in (rent_path, capital_path) if not path.is_file()]
        return [("node D V2 rent construction", False, f"missing={missing}")]
    provenance = verify(rent_path).get("status")
    required = {
        "venue",
        "day",
        "pool",
        "n_hours",
        "n_ret",
        "volume_usd",
        "reserve0",
        "reserve1",
        "rv",
        "rv_4h",
        "rv_oc",
        "max_abs_ret",
        "reported_capital_usd",
        "reported_capital_source",
        "reconstructed_capital_usd",
        CAPITAL_CURRENT_COLUMN,
        CAPITAL_COLUMN,
        "capital_reconciliation_ratio",
        "balance_value_ratio",
        "reserve_source",
        "reserve_state_timestamp",
        "reserve_validation_status",
        "capital_source",
        "price_source",
        "quantity_kind",
        "pool_family",
        "invariant_family",
        "state_generation",
        "capital_validation_status",
        "failure_reason",
        "capital_valid",
        "exact_lag_valid",
    }
    missing_columns = sorted(required - set(pq.ParquetFile(rent_path).schema_arrow.names))
    results = [
        (
            "node D V2 rent purpose-bound event source",
            True,
            f"days={len(event_stream.days):,}; identity={event_stream.content_identity_sha256}",
        ),
        (
            "node D V2 rent construction provenance and schema",
            provenance == "ok" and not missing_columns,
            f"provenance={provenance}; missing_columns={missing_columns or 'none'}",
        )
    ]
    if missing_columns:
        return results
    con = duckdb.connect()
    con.execute("SET memory_limit='1500MB'")
    con.execute("SET threads=2")
    try:
        core = con.execute(
            f"""
            SELECT count(*) AS row_count,
                count(DISTINCT (venue, day, pool)) AS unique_count,
                count(*) FILTER (WHERE venue!='uniswap_v2'
                    OR pool_family!='full_range_constant_product'
                    OR invariant_family!='full_range_constant_product'
                    OR state_generation!='{CP_CAPITAL_STATE_GENERATION}'
                    OR quantity_kind!='deposited_capital') AS contract_mismatch,
                count(*) FILTER (WHERE n_hours<1 OR n_ret!=greatest(n_hours-1,0)
                    OR volume_usd<0 OR reserve0<=0 OR reserve1<=0 OR rv<0
                    OR rv_4h<0 OR rv_oc<0 OR max_abs_ret<0) AS value_mismatch,
                count(*) FILTER (WHERE exact_lag_valid !=
                    (capital_usd_lagged IS NOT NULL)) AS lag_mismatch,
                count(*) FILTER (WHERE capital_validation_status=
                    'missing_pool_day_capital') AS missing_capital,
                count(*) FILTER (WHERE capital_validation_status=
                    'missing_pool_day_capital' AND (
                        reported_capital_source!='unavailable_missing_provider_pool_day'
                        OR reserve_source!='unavailable_missing_provider_pool_day'
                        OR reserve_validation_status!='unavailable_missing_provider_pool_day'
                        OR capital_source!='{CAPITAL_SOURCE}'
                        OR price_source!='unavailable_missing_provider_pool_day'
                        OR capital_valid
                        OR exact_lag_valid OR capital_usd_lagged IS NOT NULL
                        OR reported_capital_usd IS NOT NULL
                        OR capital_usd IS NOT NULL)) AS bad_missing,
                count(*) FILTER (WHERE capital_source IS NULL OR reserve_source IS NULL
                    OR reserve_validation_status IS NULL OR quantity_kind IS NULL
                    OR pool_family IS NULL OR invariant_family IS NULL
                    OR state_generation IS NULL OR capital_validation_status IS NULL
                    OR exact_lag_valid IS NULL) AS null_semantics
            FROM read_parquet(?)
            """,
            [str(rent_path)],
        ).fetchone()
        results.append(
            (
                "node D V2 rent construction row contract",
                bool(core[0] == core[1] and not any(core[index] for index in (2, 3, 4, 6, 7))),
                f"rows={core[0]:,}; unique={core[1]:,}; contract={core[2]:,}; "
                f"values={core[3]:,}; lag={core[4]:,}; missing_capital={core[5]:,}; "
                f"bad_missing={core[6]:,}; null_semantics={core[7]:,}",
            )
        )
        joined = con.execute(
            """
            SELECT count(*) FILTER (WHERE c.pool IS NOT NULL AND (
                    r.reported_capital_usd IS DISTINCT FROM c.reported_capital_usd
                    OR r.reported_capital_source IS DISTINCT FROM
                        c.reported_capital_source
                    OR r.reconstructed_capital_usd IS DISTINCT FROM
                        c.reconstructed_capital_usd
                    OR r.capital_usd IS DISTINCT FROM c.capital_usd
                    OR r.capital_usd_lagged IS DISTINCT FROM c.capital_usd_lagged
                    OR r.capital_reconciliation_ratio IS DISTINCT FROM
                        c.capital_reconciliation_ratio
                    OR r.balance_value_ratio IS DISTINCT FROM c.balance_value_ratio
                    OR r.reserve_source IS DISTINCT FROM c.reserve_source
                    OR r.reserve_state_timestamp IS DISTINCT FROM c.reserve_state_timestamp
                    OR r.reserve_validation_status IS DISTINCT FROM
                        c.reserve_validation_status
                    OR r.capital_source IS DISTINCT FROM c.capital_source
                    OR r.price_source IS DISTINCT FROM c.price_source
                    OR r.failure_reason IS DISTINCT FROM c.failure_reason
                    OR r.capital_valid IS DISTINCT FROM c.capital_valid
                    OR r.exact_lag_valid IS DISTINCT FROM c.exact_lag_valid
                    OR r.capital_validation_status IS DISTINCT FROM
                        c.capital_validation_status)) AS matched_mismatch,
                count(*) FILTER (WHERE c.pool IS NULL) AS missing_join,
                count(*) FILTER (WHERE c.pool IS NULL AND
                    r.capital_validation_status!='missing_pool_day_capital')
                    AS unlabeled_missing
            FROM read_parquet(?) r
            LEFT JOIN read_parquet(?) c USING (venue, day, pool)
            """,
            [str(rent_path), str(capital_path)],
        ).fetchone()
        results.append(
            (
                "node D V2 rent construction capital lineage",
                bool(joined[0] == 0 and joined[1] == core[5] and joined[2] == 0),
                f"matched_mismatch={joined[0]:,}; missing_join={joined[1]:,}; "
                f"unlabeled_missing={joined[2]:,}",
            )
        )
    finally:
        con.close()
    return results


def lp_liquidity_flow_artifact_checks() -> list[tuple[str, bool, str]]:
    """Audit causal tick use, allocation conservation, and proxy-free flow scaling."""

    artifacts = (
        LP_LIQUIDITY_FLOW_EVENTS,
        LP_LIQUIDITY_FLOW_CANDIDATES,
        LP_LIQUIDITY_FLOW_DAILY,
        LP_LIQUIDITY_FLOW_REJECTIONS,
    )
    missing = [path.name for path in artifacts if not path.exists()]
    if missing:
        return [("node D LP liquidity-flow artifacts", False, f"missing={missing}")]
    provenance = {path.name: verify(path).get("status") for path in artifacts}
    results = [
        (
            "node D LP liquidity-flow provenance",
            all(status == "ok" for status in provenance.values()),
            f"provenance={provenance}",
        )
    ]
    required = {
        LP_LIQUIDITY_FLOW_EVENTS: {
            "venue", "day", "tx_hash", "log_index", "pool", "pool_family",
            "invariant_family", "state_generation", "event_sign", "event_value_usd",
            "signed_event_value_usd", "tick_before", "tick_state_age_seconds",
            "amount0", "amount1", "price0_usd", "price1_usd",
            "price_anchor_token", "price_anchor_usd", "sqrt_price_x96_before",
            "tick_lower", "tick_upper", "tick_spacing", "range_width_spacings",
            "range_active_before", "range_near_active_before",
        },
        LP_LIQUIDITY_FLOW_CANDIDATES: {
            "venue", "day", "tx_hash", "log_index", "pool", "candidate",
            "event_sign", "allocation_weight", "allocated_event_value_usd",
            "signed_allocated_event_value_usd", "flow_normalization_status",
        },
        LP_LIQUIDITY_FLOW_DAILY: {
            "day", "candidate", "gross_liquidity_flow_usd", "net_liquidity_flow_usd",
            "active_net_liquidity_flow_usd", "near_net_liquidity_flow_usd",
            "near_gross_liquidity_flow_usd", "event_count", "has_liquidity_flow",
            "gross_candidate_flow_share", "net_flow_pressure",
            "active_net_flow_pressure", "near_net_flow_pressure",
            "near_gross_flow_share", "flow_normalization_status",
        },
        LP_LIQUIDITY_FLOW_REJECTIONS: {
            "venue", "day", "tx_hash", "log_index", "pool", "failure_reason",
        },
    }
    missing_columns = {
        path.name: sorted(columns - set(pq.ParquetFile(path).schema_arrow.names))
        for path, columns in required.items()
        if columns - set(pq.ParquetFile(path).schema_arrow.names)
    }
    results.append(
        (
            "node D LP liquidity-flow schemas",
            not missing_columns,
            f"missing_columns={missing_columns or 'none'}",
        )
    )
    if missing_columns:
        return results
    con = duckdb.connect()
    event = f"read_parquet('{LP_LIQUIDITY_FLOW_EVENTS.as_posix()}')"
    candidate = f"read_parquet('{LP_LIQUIDITY_FLOW_CANDIDATES.as_posix()}')"
    daily = f"read_parquet('{LP_LIQUIDITY_FLOW_DAILY.as_posix()}')"
    rejection = f"read_parquet('{LP_LIQUIDITY_FLOW_REJECTIONS.as_posix()}')"
    try:
        core = con.execute(
            f"""
            SELECT count(*) AS rows,
                count(DISTINCT (venue, day, tx_hash, log_index)) AS unique_rows,
                count(*) FILTER (WHERE venue!='uniswap_v3'
                    OR pool_family!='concentrated_liquidity'
                    OR invariant_family!='concentrated_liquidity'
                    OR state_generation!='{STATE_GENERATIONS["uniswap_v3"]}') AS family_mismatch,
                count(*) FILTER (WHERE tick_state_age_seconds < 0) AS noncausal,
                count(*) FILTER (WHERE range_active_before !=
                    (tick_lower <= tick_before AND tick_before < tick_upper)) AS active_mismatch,
                count(*) FILTER (WHERE range_near_active_before !=
                    (range_active_before AND range_width_spacings <= 20)) AS near_mismatch,
                count(*) FILTER (WHERE abs(signed_event_value_usd
                    - event_sign * event_value_usd) > 1e-8) AS sign_mismatch,
                count(*) FILTER (WHERE abs(event_value_usd
                    - amount0 * price0_usd - amount1 * price1_usd)
                    > greatest(1e-6, event_value_usd * 1e-10)) AS value_mismatch,
                count(*) FILTER (WHERE price_anchor_token NOT IN (token0, token1)
                    OR price_anchor_usd <= 0
                    OR event_value_source!='candidate_day_price_anchor_plus_exact_prior_v3_sqrt_price')
                    AS valuation_lineage_mismatch
            FROM {event}
            """
        ).fetchone()
        results.append(
            (
                "node D LP event causal contract",
                bool(core[0] == core[1] and not any(core[index] for index in range(2, 9))),
                f"rows={core[0]:,}; unique={core[1]:,}; family={core[2]:,}; "
                f"noncausal={core[3]:,}; active={core[4]:,}; near={core[5]:,}; "
                f"sign={core[6]:,}; value={core[7]:,}; lineage={core[8]:,}",
            )
        )
        allocation = con.execute(
            f"""
            SELECT count(*) AS rows,
                count(DISTINCT (venue, day, tx_hash, log_index, candidate)) AS unique_rows,
                count(*) FILTER (WHERE allocation_weight <= 0 OR allocation_weight > 1
                    OR allocated_event_value_usd <= 0
                    OR flow_normalization_status!='dollar_flow_no_capital_stock_denominator')
                    AS invalid_allocation,
                count(*) FILTER (WHERE abs(signed_allocated_event_value_usd
                    - event_sign * allocated_event_value_usd) > 1e-8) AS sign_mismatch
            FROM {candidate}
            """
        ).fetchone()
        conservation = con.execute(
            f"""
            WITH allocated AS (
                SELECT venue, day, tx_hash, log_index,
                    sum(allocated_event_value_usd) AS allocated
                FROM {candidate}
                GROUP BY venue, day, tx_hash, log_index
            )
            SELECT count(*) AS events,
                count(*) FILTER (WHERE abs(a.allocated - e.event_value_usd)
                    > greatest(1e-6, e.event_value_usd * 1e-10)) AS mismatch
            FROM allocated a
            JOIN {event} e USING (venue, day, tx_hash, log_index)
            """
        ).fetchone()
        unresolved = con.execute(
            f"""
            SELECT count(*)
            FROM {event} e
            LEFT JOIN (SELECT DISTINCT venue, day, tx_hash, log_index FROM {candidate}) c
                USING (venue, day, tx_hash, log_index)
            LEFT JOIN (SELECT DISTINCT venue, day, tx_hash, log_index FROM {rejection}) r
                USING (venue, day, tx_hash, log_index)
            WHERE c.tx_hash IS NULL AND r.tx_hash IS NULL
            """
        ).fetchone()[0]
        rejection_contract = con.execute(
            f"""
            SELECT count(*) AS rows,
                count(*) FILTER (WHERE failure_reason IS NULL OR failure_reason NOT IN (
                    'no_prior_swap_tick',
                    'invalid_tick_range',
                    'missing_liquidity_delta',
                    'zero_liquidity_delta',
                    'zero_liquidity_burn_no_capital_flow',
                    'invalid_token_amounts',
                    'noncausal_tick_timestamp',
                    'missing_exact_tick_valuation_state',
                    'missing_candidate_day_price_anchor',
                    'invalid_tick_implied_event_value',
                    'missing_or_implausible_event_value_usd',
                    'no_candidate_pool_side'
                )) AS unknown_reason,
                count(*) FILTER (WHERE failure_reason='zero_liquidity_burn_no_capital_flow'
                    AND source_stream!='burns') AS mislabeled_zero_burn,
                count(*) FILTER (WHERE failure_reason='zero_liquidity_burn_no_capital_flow')
                    AS zero_burn_rows,
                count(*) FILTER (WHERE failure_reason IN (
                    'invalid_tick_range', 'missing_liquidity_delta', 'zero_liquidity_delta'
                )) AS malformed_rows
            FROM {rejection}
            """
        ).fetchone()
        daily_core = con.execute(
            f"""
            WITH active_days AS (
                SELECT day, sum(gross_candidate_flow_share) AS share
                FROM {daily}
                WHERE gross_candidate_flow_share IS NOT NULL
                GROUP BY day
            )
            SELECT
                (SELECT count(*) FROM {daily}) AS rows,
                (SELECT count(DISTINCT (day, candidate)) FROM {daily}) AS unique_rows,
                (SELECT count(*) FROM {daily} WHERE gross_liquidity_flow_usd < 0
                    OR abs(net_liquidity_flow_usd) > gross_liquidity_flow_usd + 1e-8
                    OR flow_normalization_status!='dollar_flow_and_within_flow_shares_no_capital_stock')
                    AS invalid_flow,
                (SELECT count(*) FROM {daily} WHERE has_liquidity_flow AND (
                    abs(net_flow_pressure - net_liquidity_flow_usd / gross_liquidity_flow_usd) > 1e-10
                    OR abs(near_gross_flow_share - near_gross_liquidity_flow_usd / gross_liquidity_flow_usd) > 1e-10))
                    AS pressure_mismatch,
                (SELECT count(*) FROM {daily} WHERE NOT has_liquidity_flow AND (
                    net_flow_pressure IS NOT NULL OR near_gross_flow_share IS NOT NULL))
                    AS zero_flow_payload,
                (SELECT count(*) FROM active_days WHERE abs(share - 1) > 1e-10)
                    AS day_share_mismatch
            """
        ).fetchone()
        results.append(
            (
                "node D LP candidate allocation contract",
                bool(
                    allocation[0] == allocation[1]
                    and allocation[2] == 0
                    and allocation[3] == 0
                    and conservation[1] == 0
                    and unresolved == 0
                    and rejection_contract[1] == 0
                    and rejection_contract[2] == 0
                    and daily_core[0] == daily_core[1]
                    and not any(daily_core[index] for index in range(2, 6))
                ),
                f"rows={allocation[0]:,}; unique={allocation[1]:,}; "
                f"invalid_allocation={allocation[2]:,}; sign={allocation[3]:,}; "
                f"conserved_events={conservation[0]:,}; conservation_mismatch={conservation[1]:,}; "
                f"unresolved_events={unresolved:,}; candidate_days={daily_core[0]:,}; "
                f"daily_unique={daily_core[1]:,}; daily_invalid={daily_core[2]:,}; "
                f"pressure={daily_core[3]:,}; zero_flow={daily_core[4]:,}; "
                f"day_share={daily_core[5]:,}; rejection_rows={rejection_contract[0]:,}; "
                f"unknown_rejections={rejection_contract[1]:,}; "
                f"mislabeled_zero_burn={rejection_contract[2]:,}; "
                f"zero_burn_bookkeeping={rejection_contract[3]:,}; "
                f"malformed_rejections={rejection_contract[4]:,}",
            )
        )
    finally:
        con.close()
    return results


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
    perimeter = claim_execution_perimeter(specification)
    for claim in perimeter.executable_claims:
        for artifact in claim.get("outputs", []):
            producer = _artifact_producer(str(artifact))
            if producer:
                consumers.add(producer)
    try:
        ledger = json.loads(MODEL_LEDGER.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        ledger = {}
    for family in ledger.get("legacy_families", []):
        if not isinstance(family, dict) or family.get("status") == "retired":
            continue
        for artifact in family.get("artifacts", []):
            producer = _artifact_producer(str(artifact))
            if producer:
                consumers.add(producer)
    for run in ledger.get("runs", []):
        if not isinstance(run, dict) or run.get("lifecycle") == "retired":
            continue
        for artifact in run.get("artifacts", []):
            if not isinstance(artifact, dict):
                continue
            producer = _artifact_producer(str(artifact.get("path") or ""))
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


def validate_released_route_partitions(
    release_validator=require_route_release,
) -> tuple[bool, str]:
    """Run the same exact partition contract required by route-panel owners."""

    try:
        release_validator()
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as error:
        return False, str(error)
    return True, "ok"


def validate_specification_lock(
    payload: dict,
    *,
    require_confirmatory: bool = False,
) -> tuple[bool, str]:
    """Validate a design seed or the post-exploration node-E1 lock."""
    declared_hash = str(payload.get("lock_hash") or "")
    hash_payload = {key: value for key, value in payload.items() if key != "lock_hash"}
    actual_hash = hashlib.sha256(
        json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    claims = payload.get("claims") or []
    ids = [str(claim.get("id") or "") for claim in claims if isinstance(claim, dict)]
    stage = str(payload.get("stage") or "")
    stage_claim_statuses = (
        REGISTERED_CLAIM_STATUSES
        if stage == "confirmatory"
        else DESIGN_SEED_CLAIM_STATUSES
    )
    stage_claims = [
        claim
        for claim in claims
        if isinstance(claim, dict) and claim.get("status") in stage_claim_statuses
    ]
    try:
        execution_perimeter = claim_execution_perimeter(payload)
        execution_policy_error = ""
        executable_stage_claims = list(execution_perimeter.executable_claims)
    except ValueError as error:
        execution_policy_error = str(error)
        executable_stage_claims = []
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
        for claim in executable_stage_claims
        if required - set(claim)
    ]
    global_rules = payload.get("global_rules") or {}
    required_semantic_rules = {
        "audit_sampling",
        "vehicle_status",
        "vehicle_dominance",
        "cost_domination",
        "abstract_question",
        "dynamic_horizons",
    }
    missing_semantic_rules = sorted(
        key for key in required_semantic_rules if not str(global_rules.get(key) or "").strip()
    )
    dynamic_rule = str(global_rules.get("dynamic_horizons") or "").lower()
    dynamic_numbers = tuple(
        int(value) for value in re.findall(r"\b\d+\b", dynamic_rule)
    )
    dynamic_rule_valid = bool(
        dynamic_numbers == CANONICAL_RESPONSE_HORIZONS
        and "exact calendar" in dynamic_rule
        and "row shifts are not substitutes" in dynamic_rule
    )
    sampling_rule = str(global_rules.get("audit_sampling") or "").lower()
    sampling_rule_valid = bool(
        "validation" in sampling_rule
        and "not define a monthly estimand" in sampling_rule
    )
    invalid_horizon_claims: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("id") or "missing")
        if "response_horizon_days" in claim and tuple(claim["response_horizon_days"]) != CANONICAL_RESPONSE_HORIZONS:
            invalid_horizon_claims.append(claim_id)
        alternatives = claim.get("mandatory_alternatives")
        if (
            isinstance(alternatives, dict)
            and "response_horizon_days" in alternatives
            and tuple(alternatives["response_horizon_days"]) != CANONICAL_RESPONSE_HORIZONS
        ):
            invalid_horizon_claims.append(claim_id)
    invalid_horizon_claims = sorted(set(invalid_horizon_claims))
    stage_valid = stage in {"design_seed", "confirmatory"}
    analytical_choices_status = str(payload.get("analytical_choices_status") or "")
    expected_choices_status = (
        "registered_after_exploration"
        if stage == "confirmatory"
        else "provisional_design_seed"
    )
    choices_status_valid = analytical_choices_status == expected_choices_status
    invalid_stage_statuses = sorted(
        str(claim.get("id") or "missing")
        for claim in claims
        if isinstance(claim, dict)
        and claim.get("status") in DESIGN_SEED_CLAIM_STATUSES | REGISTERED_CLAIM_STATUSES
        and claim.get("status") not in stage_claim_statuses
    )
    primary_status = (
        "registered_primary" if stage == "confirmatory" else "candidate_primary"
    )
    has_primary = any(
        claim.get("status") == primary_status
        for claim in executable_stage_claims
    )
    d3_generation = str(payload.get("d3_generation") or "")
    d3_certificate = str(payload.get("d3_certificate") or "")
    exploration_generation = str(payload.get("exploration_generation") or "")
    exploration_certificate = str(payload.get("exploration_certificate") or "")
    locked_at = str(payload.get("locked_at") or "")
    confirmatory_ready = bool(
        stage == "confirmatory"
        and locked_at.strip()
        and d3_generation.strip()
        and d3_certificate.strip()
        and exploration_generation.strip()
        and exploration_certificate.strip()
        and choices_status_valid
        and not invalid_stage_statuses
        and not execution_policy_error
    )
    registered_plan_errors: dict[str, str] = {}
    if stage == "confirmatory":
        for claim in executable_stage_claims:
            claim_id = str(claim.get("id") or "missing")
            plan_passed, plan_detail = validate_registered_plan(claim)
            if not plan_passed:
                registered_plan_errors[claim_id] = plan_detail
    transition_design_errors: list[str] = []
    transition_claims = [
        claim
        for claim in claims
        if isinstance(claim, dict) and claim.get("id") == "vehicle_transition"
    ]
    if transition_claims:
        transition_design_errors.extend(
            vehicle_transition_e1_design_errors(transition_claims[0])
        )
    passed = bool(
        payload.get("schema_version") == 1
        and declared_hash == actual_hash
        and len(ids) == len(claims)
        and len(ids) == len(set(ids))
        and bool(executable_stage_claims)
        and has_primary
        and not incomplete
        and not invalid_stage_statuses
        and not execution_policy_error
        and not missing_semantic_rules
        and dynamic_rule_valid
        and sampling_rule_valid
        and not invalid_horizon_claims
        and stage_valid
        and choices_status_valid
        and not registered_plan_errors
        and not transition_design_errors
        and (not require_confirmatory or confirmatory_ready)
    )
    detail = (
        f"hash={'ok' if declared_hash == actual_hash else 'mismatch'}; "
        f"claims={len(claims)}; stage_claims={len(stage_claims)}; "
        f"incomplete={incomplete or 'none'}; "
        f"invalid_stage_statuses={invalid_stage_statuses or 'none'}; "
        f"execution_policy={execution_policy_error or 'valid'}; "
        f"primary={'ok' if has_primary else 'missing'}; "
        f"missing_semantic_rules={missing_semantic_rules or 'none'}; "
        f"dynamic_rule={'ok' if dynamic_rule_valid else 'invalid'}; "
        f"audit_sampling={'ok' if sampling_rule_valid else 'invalid'}; "
        f"invalid_horizons={invalid_horizon_claims or 'none'}; "
        f"stage={stage or 'missing'}; "
        f"choices_status={analytical_choices_status or 'missing'}; "
        f"locked_at={locked_at or 'missing'}; "
        f"d3_generation={d3_generation or 'missing'}; "
        f"d3_certificate={d3_certificate or 'missing'}; "
        f"exploration_generation={exploration_generation or 'missing'}; "
        f"exploration_certificate={exploration_certificate or 'missing'}; "
        f"registered_plan_errors={registered_plan_errors or 'none'}; "
        f"transition_design_errors={transition_design_errors or 'none'}"
    )
    return passed, detail


def validate_claim_input_layer(
    payload: dict,
    *,
    root: Path = ROOT,
    verifier=verify,
) -> tuple[bool, str]:
    """Require every execution-open claim input to be canonical and current."""
    try:
        perimeter = claim_execution_perimeter(payload)
    except ValueError as error:
        return False, f"claim execution policy invalid: {error}"
    inputs = sorted(
        {
            str(relative)
            for claim in perimeter.executable_claims
            for relative in claim.get("inputs", [])
        }
    )
    raw_inputs = [relative for relative in inputs if relative.startswith("data/raw/")]
    missing = [relative for relative in inputs if not (root / relative).exists()]
    statuses: dict[str, object] = {}
    for relative in inputs:
        if relative in missing or relative in raw_inputs:
            continue
        postcondition = d3_release_postcondition(relative)
        if postcondition is None:
            statuses[relative] = verifier(root / relative).get("status")
            continue
        try:
            if postcondition.receipt_backed_lease is not None:
                with postcondition.receipt_backed_lease(root / relative):
                    pass
            else:
                postcondition.resolver(root / relative)
            statuses[relative] = "ok"
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as error:
            statuses[relative] = f"typed_release_{type(error).__name__}"
    stale = {relative: status for relative, status in statuses.items() if status != "ok"}
    passed = bool(inputs and not raw_inputs and not missing and not stale)
    return passed, (
        f"inputs={len(inputs)}; current={sum(status == 'ok' for status in statuses.values())}; "
        f"raw={raw_inputs or 'none'}; missing={missing or 'none'}; stale={stale or 'none'}"
    )


def confirmatory_promotion_errors(
    runs: list[dict],
    e0_certificate: dict,
) -> tuple[dict[str, list[str]], list[str]]:
    """Bind each exploratory promotion to its exact E0 decision and a distinct confirmation."""
    errors: dict[str, list[str]] = {}
    certificate_errors: list[str] = []
    decisions = [
        decision
        for decision in e0_certificate.get("triage_decisions", [])
        if isinstance(decision, dict)
    ]
    decision_ids = [str(decision.get("decision_id") or "") for decision in decisions]
    if not all(decision_ids) or len(decision_ids) != len(set(decision_ids)):
        certificate_errors.append("e0_decision_identity")
    decisions_by_id = {
        str(decision["decision_id"]): decision
        for decision in decisions
        if str(decision.get("decision_id") or "")
    }
    recorded_exploratory_runs = {
        str(run_id) for run_id in e0_certificate.get("exploratory_run_ids", [])
    }
    runs_by_id = {str(run.get("run_id") or ""): run for run in runs}

    def add(run_id: str, error: str) -> None:
        errors.setdefault(run_id, []).append(error)
        errors[run_id] = sorted(set(errors[run_id]))

    for run in runs:
        if run.get("lane") != "confirmatory" or run.get("selection_origin") != "exploratory_discovery":
            continue
        run_id = str(run.get("run_id") or run.get("family_id") or "missing")
        source_run_id = str(run.get("promoted_from_run_id") or "")
        source = runs_by_id.get(source_run_id)
        decision = decisions_by_id.get(str(run.get("decision_id") or ""))
        if (
            source is None
            or source_run_id not in recorded_exploratory_runs
            or source.get("lane") != "exploratory"
            or source.get("lifecycle") != "executed"
        ):
            add(run_id, "promotion_source_certificate")
            continue
        required_nodes = decision.get("required_reopen_nodes") if decision is not None else None
        if (
            decision is None
            or decision.get("run_id") != source_run_id
            or decision.get("outcome") != "promote"
            or decision.get("proposed_claim_id") != run.get("claim_id")
            or not isinstance(required_nodes, list)
            or "E1" not in required_nodes
        ):
            add(run_id, "promotion_decision")
        if run.get("plan_hash") == source.get("plan_hash"):
            add(run_id, "confirmation_plan_not_distinct")
        source_artifacts = [artifact for artifact in source.get("artifacts", []) if isinstance(artifact, dict)]
        confirmation_artifacts = [artifact for artifact in run.get("artifacts", []) if isinstance(artifact, dict)]
        source_paths = {str(artifact.get("path") or "") for artifact in source_artifacts}
        confirmation_paths = {str(artifact.get("path") or "") for artifact in confirmation_artifacts}
        source_hashes = {str(artifact.get("sha256") or "") for artifact in source_artifacts}
        confirmation_hashes = {str(artifact.get("sha256") or "") for artifact in confirmation_artifacts}
        if source_paths & confirmation_paths:
            add(run_id, "confirmation_artifact_path_not_distinct")
        if (source_hashes - {""}) & (confirmation_hashes - {""}):
            add(run_id, "confirmation_artifact_content_not_distinct")
    return errors, certificate_errors


def validate_model_ledger(
    payload: dict,
    *,
    claim_ids: set[str],
    lock_payload: dict | None = None,
    require_confirmatory: bool = False,
    root: Path = ROOT,
    verifier=verify,
    verify_artifacts: bool = True,
    verify_certificates: bool = True,
) -> tuple[bool, str]:
    """Validate immutable run records, promotion history, and attack coverage."""
    lock_payload = lock_payload or {}
    legacy_families = payload.get("legacy_families") or []
    runs = payload.get("runs") or []
    exploration = payload.get("exploration") or {}
    current_generation = str(payload.get("current_analysis_generation") or "")

    legacy_required = {
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
    legacy_ids = [
        str(family.get("id") or "")
        for family in legacy_families
        if isinstance(family, dict)
    ]
    legacy_incomplete = [
        str(family.get("id") or "missing")
        for family in legacy_families
        if not isinstance(family, dict) or legacy_required - set(family)
    ]
    legacy_invalid = [
        str(family.get("id") or "missing")
        for family in legacy_families
        if isinstance(family, dict)
        and (
            family.get("status") not in LEGACY_MODEL_STATUSES
            or any(
                not isinstance(family.get(field), int) or family.get(field, -1) < 0
                for field in (
                    "substantive_specifications",
                    "diagnostic_specifications",
                    "resampling_refits",
                )
            )
        )
    ]

    exploration_status = str(exploration.get("status") or "")
    exploration_valid = exploration_status in {"not_started", "in_progress", "complete"}
    exploration_d3 = str(exploration.get("d3_generation") or "")
    exploration_d3_certificate = str(exploration.get("d3_certificate") or "")
    exploration_generation = str(exploration.get("generation") or "")
    exploration_certificate = str(exploration.get("certificate") or "")
    if exploration_status == "not_started":
        exploration_valid = bool(
            exploration_valid
            and not current_generation
            and not exploration_d3
            and not exploration_d3_certificate
            and not exploration_generation
            and not exploration_certificate
            and not runs
        )
    elif exploration_status == "in_progress":
        exploration_valid = bool(
            exploration_valid
            and current_generation
            and exploration_d3 == current_generation
            and exploration_d3_certificate
            and not exploration_generation
            and not exploration_certificate
        )
    elif exploration_status == "complete":
        exploration_valid = bool(
            exploration_valid
            and current_generation
            and exploration_d3 == current_generation
            and exploration_d3_certificate
            and exploration_generation
            and exploration_certificate
        )

    run_required = {
        "family_id",
        "run_id",
        "claim_id",
        "lane",
        "lifecycle",
        "disposition",
        "selection_origin",
        "promoted_from_run_id",
        "decision_id",
        "d3_generation",
        "exploration_generation",
        "lock_hash",
        "plan_hash",
        "engine_hash",
        "estimator",
        "fixed_effects",
        "inference",
        "artifacts",
        "note",
    }
    run_ids = [
        str(run.get("run_id") or "") for run in runs if isinstance(run, dict)
    ]
    incomplete_runs = [
        str(run.get("run_id") or run.get("family_id") or "missing")
        for run in runs
        if not isinstance(run, dict) or run_required - set(run)
    ]
    invalid_runs: dict[str, list[str]] = {}
    artifact_owners: dict[str, str] = {}
    reused_artifacts: list[str] = []
    exploratory_run_ids = {
        str(run.get("run_id") or "")
        for run in runs
        if isinstance(run, dict)
        and run.get("lane") == "exploratory"
        and run.get("lifecycle") == "executed"
    }
    try:
        registered_perimeter = claim_execution_perimeter(lock_payload)
        registered_claims = {
            str(claim["id"]): claim
            for claim in registered_perimeter.executable_claims
            if claim.get("status") in REGISTERED_CLAIM_STATUSES
        }
    except ValueError:
        registered_claims = {}
    admissible_claims: set[str] = set()

    for run in runs:
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("run_id") or run.get("family_id") or "missing")
        errors: list[str] = []
        lane = str(run.get("lane") or "")
        lifecycle = str(run.get("lifecycle") or "")
        disposition = str(run.get("disposition") or "")
        if lane not in MODEL_RUN_LANES:
            errors.append("lane")
        if lifecycle not in MODEL_RUN_LIFECYCLES:
            errors.append("lifecycle")
        if disposition not in MODEL_RUN_DISPOSITIONS:
            errors.append("disposition")
        if run.get("run_id") != model_run_id(run):
            errors.append("run_id")
        if str(run.get("d3_generation") or "") != current_generation:
            errors.append("d3_generation")
        artifacts = run.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append("artifacts")
            artifacts = []
        executed_specification_ids: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict) or not {
                "path",
                "role",
                "sha256",
                "provenance_path",
                "spec_ids",
            }.issubset(artifact):
                errors.append("artifact_contract")
                continue
            artifact_path = str(artifact.get("path") or "")
            artifact_relative = Path(artifact_path)
            provenance_relative = Path(str(artifact.get("provenance_path") or ""))
            artifact_hash = str(artifact.get("sha256") or "")
            artifact_spec_ids = artifact.get("spec_ids")
            if (
                not artifact_path
                or artifact_relative.is_absolute()
                or ".." in artifact_relative.parts
                or not provenance_relative.parts
                or provenance_relative.is_absolute()
                or ".." in provenance_relative.parts
                or not re.fullmatch(r"[0-9a-f]{64}", artifact_hash)
                or not isinstance(artifact_spec_ids, list)
                or not all(
                    isinstance(specification_id, str) and specification_id
                    for specification_id in artifact_spec_ids or []
                )
            ):
                errors.append("artifact_contract")
            if artifact.get("role") not in MODEL_RUN_ARTIFACT_ROLES:
                errors.append("artifact_role")
            if artifact.get("role") == "support" and artifact_spec_ids:
                errors.append("support_claims_fitted_coverage")
            if artifact.get("role") != "support" and not artifact_spec_ids:
                errors.append("fitted_artifact_without_spec_ids")
            if artifact_path in artifact_owners and artifact_owners[artifact_path] != run_id:
                reused_artifacts.append(artifact_path)
            artifact_owners[artifact_path] = run_id
            if verify_artifacts:
                resolved_artifact = root / artifact_path
                resolved_provenance = root / str(artifact.get("provenance_path") or "")
                expected_provenance = sidecar_path(resolved_artifact)
                if not resolved_artifact.is_file():
                    errors.append("artifact_missing")
                elif artifact.get("sha256") != portable_content_sha256(resolved_artifact):
                    errors.append("artifact_hash")
                if resolved_provenance != expected_provenance:
                    errors.append("provenance_path")
                if not resolved_provenance.is_file():
                    errors.append("provenance_missing")
                elif verifier(resolved_artifact).get("status") != "ok":
                    errors.append("provenance_stale")
                if resolved_artifact.is_file():
                    try:
                        actual_spec_ids = validate_artifact_spec_ids(
                            resolved_artifact,
                            role=str(artifact.get("role") or ""),
                            declared=artifact_spec_ids,
                        )
                    except (OSError, TypeError, ValueError):
                        errors.append("artifact_spec_ids")
                    else:
                        executed_specification_ids.update(actual_spec_ids)
            elif artifact.get("role") in {"result", "falsifier", "diagnostic", "resampling"}:
                executed_specification_ids.update(str(specification_id) for specification_id in artifact_spec_ids or [])
        if lifecycle == "executed" and not artifacts:
            errors.append("executed_without_artifacts")
        if lane == "exploratory":
            if run.get("plan_hash") != canonical_hash(exploratory_plan_identity(run)):
                errors.append("exploratory_plan_identity")
            declared_artifacts = run.get("declared_artifacts")
            realized_contract = [
                {
                    "path": artifact.get("path"),
                    "role": artifact.get("role"),
                    "spec_ids": artifact.get("spec_ids"),
                }
                for artifact in artifacts
                if isinstance(artifact, dict)
            ]
            if not isinstance(declared_artifacts, list) or realized_contract != declared_artifacts:
                errors.append("exploratory_artifact_plan")
            if run.get("lock_hash") is not None or run.get("exploration_generation") is not None:
                errors.append("exploratory_generation_binding")
            if disposition == "admissible":
                errors.append("exploratory_admissible")
            if any(
                run.get(field) is not None
                for field in (
                    "selection_origin",
                    "promoted_from_run_id",
                    "decision_id",
                )
            ):
                errors.append("exploratory_selection_history")
        elif lane == "confirmatory":
            claim_id = str(run.get("claim_id") or "")
            claim = registered_claims.get(claim_id)
            if claim is None:
                errors.append("unregistered_claim")
            else:
                if run.get("plan_hash") != claim.get("plan_hash"):
                    errors.append("plan_hash")
                registered_ids = {
                    str(specification.get("spec_id") or "")
                    for specification in claim.get("registered_specifications", [])
                    if isinstance(specification, dict)
                }
                if lifecycle == "executed" and executed_specification_ids != registered_ids:
                    errors.append("specification_coverage")
            if lock_payload.get("stage") != "confirmatory":
                errors.append("confirmatory_without_lock")
            if run.get("lock_hash") != lock_payload.get("lock_hash"):
                errors.append("lock_hash")
            if run.get("d3_generation") != lock_payload.get("d3_generation"):
                errors.append("lock_d3_generation")
            if run.get("exploration_generation") != lock_payload.get("exploration_generation"):
                errors.append("lock_exploration_generation")
            if not run.get("decision_id"):
                errors.append("decision_id")
            selection_origin = run.get("selection_origin")
            if selection_origin == "exploratory_discovery":
                source_run_id = str(run.get("promoted_from_run_id") or "")
                if source_run_id not in exploratory_run_ids or source_run_id == run_id:
                    errors.append("promotion_source")
            elif selection_origin == "design_seed":
                if run.get("promoted_from_run_id") is not None:
                    errors.append("design_seed_promotion_source")
            else:
                errors.append("selection_origin")
            if disposition == "admissible" and (lifecycle != "executed" or errors):
                errors.append("inadmissible_execution_state")
        if errors:
            invalid_runs[run_id] = sorted(set(errors))

    certificate_errors: list[str] = []

    def load_certificate(relative: str, kind: str) -> dict:
        relative_path = Path(relative)
        if (
            not relative
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            certificate_errors.append(f"{kind}_path")
            return {}
        path = root / relative_path
        if not path.is_file():
            certificate_errors.append(f"{kind}_missing")
            return {}
        try:
            certificate = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            certificate_errors.append(f"{kind}_invalid_json")
            return {}
        if verifier(path).get("status") != "ok":
            certificate_errors.append(f"{kind}_provenance")
        if certificate.get("kind") != kind:
            certificate_errors.append(f"{kind}_kind")
        if certificate.get("generation") != generation_id(certificate):
            certificate_errors.append(f"{kind}_generation")
        return certificate

    if exploration_status in {"in_progress", "complete"} and verify_certificates:
        d3_certificate = load_certificate(
            exploration_d3_certificate,
            "d3_analysis_release",
        )
        if d3_certificate.get("generation") != current_generation:
            certificate_errors.append("d3_analysis_release_binding")
    e0_certificate: dict = {}
    if exploration_status == "complete" and verify_certificates:
        e0_certificate = load_certificate(
            exploration_certificate,
            "e0_exploration",
        )
        if e0_certificate.get("generation") != exploration_generation:
            certificate_errors.append("e0_exploration_binding")
        if e0_certificate.get("d3_generation") != current_generation:
            certificate_errors.append("e0_exploration_d3")
        recorded_exploratory_runs = {
            str(run_id) for run_id in e0_certificate.get("exploratory_run_ids", [])
        }
        if recorded_exploratory_runs != exploratory_run_ids:
            certificate_errors.append("e0_exploratory_run_perimeter")
        triage_run_ids = {
            str(decision.get("run_id") or "")
            for decision in e0_certificate.get("triage_decisions", [])
            if isinstance(decision, dict)
        }
        if triage_run_ids != exploratory_run_ids:
            certificate_errors.append("e0_triage_perimeter")

        exploratory_records = {
            str(record.get("run_id") or ""): str(record.get("record_sha256") or "")
            for record in e0_certificate.get("exploratory_run_records", [])
            if isinstance(record, dict)
        }
        current_exploratory_records = {
            str(run.get("run_id") or ""): canonical_hash(run)
            for run in runs
            if isinstance(run, dict)
            and run.get("lane") == "exploratory"
            and run.get("lifecycle") == "executed"
        }
        if exploratory_records != current_exploratory_records:
            certificate_errors.append("e0_exploratory_run_records")

        promotion_errors, promotion_certificate_errors = confirmatory_promotion_errors(runs, e0_certificate)
        certificate_errors.extend(promotion_certificate_errors)
        for run_id, errors in promotion_errors.items():
            invalid_runs[run_id] = sorted(set([*invalid_runs.get(run_id, []), *errors]))

    admissible_claims = {
        str(run.get("claim_id") or "")
        for run in runs
        if isinstance(run, dict)
        and run.get("lane") == "confirmatory"
        and run.get("lifecycle") == "executed"
        and run.get("disposition") == "admissible"
        and str(run.get("run_id") or "") not in invalid_runs
    }

    missing_claim_evidence = sorted(claim_ids - admissible_claims)
    confirmatory_context_valid = bool(
        lock_payload.get("stage") == "confirmatory"
        and exploration_status == "complete"
        and current_generation == str(lock_payload.get("d3_generation") or "")
        and exploration_d3_certificate
        == str(lock_payload.get("d3_certificate") or "")
        and exploration_generation
        == str(lock_payload.get("exploration_generation") or "")
        and exploration_certificate
        == str(lock_payload.get("exploration_certificate") or "")
        and not certificate_errors
    )
    passed = bool(
        payload.get("schema_version") == 2
        and legacy_ids
        and len(legacy_ids) == len(legacy_families)
        and len(legacy_ids) == len(set(legacy_ids))
        and not legacy_incomplete
        and not legacy_invalid
        and len(run_ids) == len(runs)
        and len(run_ids) == len(set(run_ids))
        and not incomplete_runs
        and not invalid_runs
        and not reused_artifacts
        and not certificate_errors
        and exploration_valid
        and (
            not require_confirmatory
            or (confirmatory_context_valid and not missing_claim_evidence)
        )
    )
    return passed, (
        f"legacy_families={len(legacy_families)}; current_runs={len(runs)}; "
        f"exploration={exploration_status or 'missing'}; "
        f"current_generation={current_generation or 'missing'}; "
        f"legacy_incomplete={legacy_incomplete or 'none'}; "
        f"legacy_invalid={legacy_invalid or 'none'}; "
        f"incomplete_runs={incomplete_runs or 'none'}; "
        f"invalid_runs={invalid_runs or 'none'}; "
        f"reused_artifacts={sorted(set(reused_artifacts)) or 'none'}; "
        f"certificate_errors={sorted(set(certificate_errors)) or 'none'}; "
        f"confirmatory_context={'ok' if confirmatory_context_valid else 'invalid'}; "
        f"missing_claim_evidence={missing_claim_evidence or 'none'}"
    )


def v2_event_source_certificate_checks(
    summary_path: Path | None = None,
    exceptions_path: Path | None = None,
    certificate_path: Path | None = None,
    quality_path: Path = UNIFIED_QUALITY_PANEL,
) -> list[tuple[str, bool, str]]:
    """Require current, exact, zero-exception V2 event-source evidence."""

    explicit = (summary_path, exceptions_path, certificate_path)
    if any(path is not None for path in explicit) and not all(path is not None for path in explicit):
        return [("node D V2 event-source certificate exists", False, "explicit reads require all three artifact paths")]
    try:
        if all(path is None for path in explicit):
            release = resolve_v2_event_source_release()
            artifacts = release.artifact_paths
        else:
            release = None
            artifacts = tuple(Path(path) for path in explicit if path is not None)
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as error:
        return [("node D V2 event-source certificate exists", False, str(error))]
    missing = [path.name for path in artifacts if not path.is_file()]
    if missing:
        return [("node D V2 event-source certificate exists", False, f"missing={missing}")]
    try:
        provenance = {path.name: verify(path).get("status") for path in artifacts}
    except (OSError, TypeError, ValueError) as error:
        provenance = {"invalid": str(error)}
    checks = [
        (
            "node D V2 event-source provenance current",
            all(status == "ok" for status in provenance.values()),
            f"provenance={provenance}",
        )
    ]
    certificate: dict[str, object] | None = None
    summary: pd.DataFrame | None = None
    try:
        expected_days = transaction_frontier_audit_days(quality_path)
        if release is not None:
            summary, exceptions, certificate = read_v2_event_source_release(release)
        else:
            summary, exceptions, certificate = read_v2_event_source_certificate(
                *artifacts
            )
        days, raw_events = validate_v2_event_source_certificate(
            summary,
            exceptions,
            certificate,
            expected_days,
        )
        passed, detail = True, f"audit_dates={days}; raw_events={raw_events:,}; exceptions=0"
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as error:
        passed, detail = False, str(error)
    checks.append(("node D V2 event-source exact comparisons", passed, detail))
    try:
        if certificate is None:
            raise ValueError("V2 event-source certificate is unavailable for evidence validation")
        pairs, leaves = validate_v2_event_source_evidence_bundle(
            certificate,
            summary=summary,
        )
        evidence_passed = True
        evidence_detail = f"factory_pairs={pairs:,}; factory_leaves={leaves:,}; cited_artifacts=reopened"
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as error:
        evidence_passed, evidence_detail = False, str(error)
    checks.append(("node D V2 event-source cited evidence", evidence_passed, evidence_detail))
    return checks


def v3_event_source_certificate_checks(
    summary_path: Path | None = None,
    exceptions_path: Path | None = None,
    quarantine_path: Path | None = None,
    certificate_path: Path | None = None,
    quality_path: Path = UNIFIED_QUALITY_PANEL,
) -> list[tuple[str, bool, str]]:
    """Require current, exact, zero-exception V3 event-source evidence."""

    explicit = (summary_path, exceptions_path, quarantine_path, certificate_path)
    if any(path is not None for path in explicit) and not all(
        path is not None for path in explicit
    ):
        return [
            (
                "node D V3 event-source certificate exists",
                False,
                "explicit reads require all four artifact paths",
            )
        ]
    try:
        if all(path is None for path in explicit):
            release = resolve_v3_event_source_release()
            artifacts = release.artifact_paths
            summary, exceptions, quarantine, certificate = read_v3_event_source_release(
                release
            )
        else:
            artifacts = tuple(Path(path) for path in explicit if path is not None)
            summary = pd.read_parquet(Path(summary_path))
            exceptions = pd.read_parquet(Path(exceptions_path))
            quarantine = pd.read_parquet(Path(quarantine_path))
            certificate = json.loads(Path(certificate_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as error:
        return [("node D V3 event-source certificate exists", False, str(error))]
    missing = [path.name for path in artifacts if not path.is_file()]
    if missing:
        return [
            ("node D V3 event-source certificate exists", False, f"missing={missing}")
        ]
    try:
        provenance = {path.name: verify(path).get("status") for path in artifacts}
    except (OSError, TypeError, ValueError) as error:
        provenance = {"invalid": str(error)}
    checks = [
        (
            "node D V3 event-source provenance current",
            all(status == "ok" for status in provenance.values()),
            f"provenance={provenance}",
        )
    ]
    try:
        expected_days = v3_audit_days(quality_path)
        days, exact_events = validate_v3_event_source_certificate(
            summary,
            exceptions,
            quarantine,
            certificate,
            expected_days,
        )
        passed = True
        detail = (
            f"audit_dates={days}; exact_events={exact_events:,}; exceptions=0; "
            f"pools={certificate['pool_count']:,}"
        )
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as error:
        passed, detail = False, str(error)
    checks.append(("node D V3 event-source exact comparisons", passed, detail))
    try:
        pools, events = validate_v3_event_source_evidence_bundle(
            certificate,
            summary=summary,
            quarantine=quarantine,
        )
        evidence_passed = True
        evidence_detail = (
            f"factory_pools={pools:,}; exact_events={events:,}; cited_artifacts=reopened"
        )
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as error:
        evidence_passed, evidence_detail = False, str(error)
    checks.append(
        ("node D V3 event-source cited evidence", evidence_passed, evidence_detail)
    )
    return checks


def transaction_frontier_support_checks(
    support: pd.DataFrame,
    *,
    panel_rows: int,
    rejection_rows: int,
    prefix: str = "transaction frontier",
    coverage_label: str = "audit-day",
    expected_days: int = 77,
    first_day: str = "20200214",
    last_day: str = "20260615",
) -> list[tuple[str, bool, str]]:
    """Validate one frontier's fixed calendar, funnel and chosen-output reproduction."""
    required = {
        "day",
        "scored_routes",
        "rejected_routes",
        "exact_venue_two_leg_routes",
        "invalid_realised_input",
        "invalid_realised_output",
        "invalid_chosen_output",
        "within_20pct_chosen_quote_eligible_routes",
        "within_20pct_chosen_quote_available",
        "within_20pct_chosen_output_mismatch",
        "chosen_validation_tolerance_bps",
    }
    missing = sorted(required - set(support.columns))
    if missing:
        return [(f"{prefix} support schema", False, f"missing={missing}")]
    days = sorted(support["day"].astype(str).unique())
    scored = int(pd.to_numeric(support["scored_routes"], errors="coerce").sum())
    rejected = int(pd.to_numeric(support["rejected_routes"], errors="coerce").sum())
    exact = int(
        pd.to_numeric(support["exact_venue_two_leg_routes"], errors="coerce").sum()
    )
    eligible = int(
        pd.to_numeric(
            support["within_20pct_chosen_quote_eligible_routes"], errors="coerce"
        ).sum()
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
    quote_coverage = chosen_quote_coverage_share(eligible, available)
    verified_coverage = chosen_quote_coverage_share(eligible, available - mismatches)
    reproduction = chosen_reproduction_share(available, mismatches)
    tolerance = pd.to_numeric(
        support["chosen_validation_tolerance_bps"], errors="coerce"
    )
    return [
        (
            f"{prefix} row contract",
            scored == panel_rows and rejected == rejection_rows and scored + rejected == exact,
            f"scored panel={panel_rows:,}; support={scored:,}; "
            f"rejections={rejection_rows:,}; support={rejected:,}; exact={exact:,}",
        ),
        (
            f"{prefix} chosen-state support",
            eligible >= available >= mismatches,
            f"eligible={eligible:,}; quoted={available:,}; state_coverage={quote_coverage:.2%}; "
            f"verified={available - mismatches:,}; verified_coverage={verified_coverage:.2%}",
        ),
        (
            f"{prefix} chosen-output validation",
            tolerance.notna().all()
            and tolerance.eq(MAX_CHOSEN_REPRODUCTION_ERROR_BPS).all(),
            f"coherent={available:,}; mismatches={mismatches:,}; pass={reproduction:.2%}; "
            f"tolerance_bps={sorted(tolerance.dropna().unique().tolist())}",
        ),
        (
            f"{prefix} {coverage_label} coverage",
            len(days) == expected_days
            and bool(days)
            and days[0] == first_day
            and days[-1] == last_day,
            f"days={len(days)}; range={days[0] if days else 'none'}..{days[-1] if days else 'none'}",
        ),
    ]


def transaction_frontier_artifact_checks(
    panel: Path,
    rejections: Path,
    support: Path,
    *,
    prefix: str,
    coverage_label: str,
    expected_days: int,
    first_day: str,
    last_day: str,
) -> list[tuple[str, bool, str]]:
    """Require all three published artifacts, current provenance and reconciled counts."""
    artifacts = (panel, rejections, support)
    missing = [str(path.relative_to(ROOT)) for path in artifacts if not path.exists()]
    if missing:
        return [(f"{prefix} exists", False, f"missing={missing}")]
    verdicts = {path.name: verify(path).get("status") for path in artifacts}
    checks = [
        (
            f"{prefix} provenance current",
            all(status == "ok" for status in verdicts.values()),
            "; ".join(f"{name}={status}" for name, status in verdicts.items()),
        )
    ]
    support_frame = (
        pd.read_json(support, lines=True)
        if support.suffix == ".jsonl"
        else pd.read_parquet(support)
    )
    checks.extend(
        transaction_frontier_support_checks(
            support_frame,
            panel_rows=pq.ParquetFile(panel).metadata.num_rows,
            rejection_rows=pq.ParquetFile(rejections).metadata.num_rows,
            prefix=prefix,
            coverage_label=coverage_label,
            expected_days=expected_days,
            first_day=first_day,
            last_day=last_day,
        )
    )
    return checks


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

    def zero(series: pd.Series, *, atol: float = 0.0) -> pd.Series:
        numeric = pd.to_numeric(series, errors="coerce").fillna(0)
        return numeric.abs().le(atol) if atol else numeric.eq(0)

    type_episode_total = sum(
        (merged[f"cnt_{asset_type}"] for asset_type in TYPES),
        start=pd.Series(0, index=merged.index, dtype="int64"),
    )
    type_value_totals = {
        prefix: sum(
            (merged[f"{prefix}_{asset_type}"] for asset_type in TYPES),
            start=pd.Series(0.0, index=merged.index),
        )
        for prefix in ("usd", *(f"usd_{support}" for support in VALUE_SUPPORT_COLUMNS))
    }
    vehicle_columns = [
        "vehicle_intermediate_routes",
        "vehicle_intermediate_usd",
        *(f"vehicle_intermediate_usd_{support}" for support in VALUE_SUPPORT_COLUMNS),
    ]
    missing_vehicle = merged["_vehicle_merge"].eq("left_only")
    structurally_empty = (
        zero(merged["routes_intermediated"])
        & zero(merged["intermediated_routes"])
        & zero(merged["episodes"])
        & zero(type_episode_total)
        & zero(merged["intermediated_usd"], atol=1e-6)
        & zero(merged["intermediated_usd_within_2x"], atol=1e-6)
        & zero(merged["intermediated_usd_within_20pct"], atol=1e-6)
        & zero(type_value_totals["usd"], atol=1e-6)
        & zero(type_value_totals["usd_within_2x"], atol=1e-6)
        & zero(type_value_totals["usd_within_20pct"], atol=1e-6)
    )
    permitted_empty_vehicle = missing_vehicle & structurally_empty
    merged.loc[permitted_empty_vehicle, vehicle_columns] = 0

    results: list[tuple[str, bool, str]] = []
    calendar_ok = bool(
        merged["_merge"].eq("both").all()
        and (merged["_vehicle_merge"].eq("both") | permitted_empty_vehicle).all()
    )
    results.append(
        (
            "route measurement calendars reconcile",
            calendar_ok,
            f"days={len(merged):,}; structurally_empty_vehicle_days={int(permitted_empty_vehicle.sum()):,}",
        )
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
        type_total = type_value_totals[prefix]
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
    try:
        early_lock_payload = json.loads(SPECIFICATION_LOCK.read_text())
        wide_state_required = active_claim_requires_wide_state(early_lock_payload)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        early_lock_payload = {}
        wide_state_required = False

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append((name, passed, detail))

    def executable_inputs_require(paths: tuple[str, ...]) -> bool:
        if not early_lock_payload:
            return False
        return active_claim_requires_any(early_lock_payload, paths)

    missing_graph_fields = [name for name in GRAPH_FIELDS if not state.get(name)]
    record(
        "workflow graph state",
        not missing_graph_fields,
        graph_status(state),
    )
    boundary_passed, boundary_detail = validate_canonical_consumer_boundary()
    record("node D raw-provider boundary", boundary_passed, boundary_detail)
    liquidity_passed, liquidity_detail = validate_liquidity_contracts()
    record("cross-protocol liquidity semantics", liquidity_passed, liquidity_detail)
    if wide_state_required:
        quote_state_passed, quote_state_detail = quote_state_artifact_check()
        record("node D quote-state family contracts", quote_state_passed, quote_state_detail)
    else:
        record(
            "node D quote-state family contracts",
            True,
            "not required by the executable claim-input perimeter",
        )

    def run_claim_bound_checks(
        label: str,
        required_inputs: tuple[str, ...],
        checker,
    ) -> None:
        if executable_inputs_require(required_inputs):
            for name, passed, detail in checker():
                record(name, passed, detail)
        else:
            record(label, True, "not required by the executable claim-input perimeter")

    run_claim_bound_checks(
        "capital release artifacts",
        ("data/processed/pool_capital_release/current.json",),
        capital_artifact_checks,
    )
    run_claim_bound_checks(
        "token-price artifacts",
        ("data/processed/token_price_daily.parquet",),
        token_price_artifact_checks,
    )
    run_claim_bound_checks(
        "CEX reference-support artifacts",
        ("data/processed/cex_reference_support.parquet",),
        cex_reference_support_checks,
    )
    lp_inputs = (
        "data/processed/lp_liquidity_flow_events_v3.parquet",
        "data/processed/lp_liquidity_flow_candidates_v3.parquet",
        "data/processed/lp_liquidity_flow_daily_v3.parquet",
        "data/processed/lp_liquidity_flow_rejections_v3.parquet",
        "data/processed/liquidity_capital_flow_candidate_day.parquet",
        "data/processed/liquidity_capital_flow_exact_horizons.parquet",
    )
    run_claim_bound_checks(
        "LP liquidity-flow artifacts",
        lp_inputs,
        lp_liquidity_flow_artifact_checks,
    )
    run_claim_bound_checks(
        "rent-incidence artifacts",
        (
            "data/processed/rent_incidence_v2_pool_day.parquet",
            "data/processed/lp_transaction_gas.parquet",
            "data/processed/external_reference_price_intraday.parquet",
        ),
        rent_incidence_artifact_checks,
    )
    run_claim_bound_checks(
        "V3 inventory calendar",
        lp_inputs,
        v3_inventory_calendar_checks,
    )
    route_inputs = (
        "data/processed/counterfactual_dominance.parquet",
        "data/processed/counterfactual_dominance_gross.parquet",
        "data/processed/route_gas_units.parquet",
        "data/processed/route_transaction_gas.parquet",
        "data/processed/routing_maturation_cell_day.parquet",
        "data/processed/routing_transition_cells.parquet",
        "data/processed/routing_maturation_exact_horizons.parquet",
    )
    run_claim_bound_checks(
        "V2 event-source certificate",
        route_inputs,
        v2_event_source_certificate_checks,
    )
    run_claim_bound_checks(
        "V3 event-source certificate",
        (*route_inputs, *lp_inputs),
        v3_event_source_certificate_checks,
    )
    run_claim_bound_checks(
        "retired route-gas releases",
        (
            "data/processed/route_gas_units.parquet",
            "data/processed/route_transaction_gas.parquet",
        ),
        retired_route_gas_release_checks,
    )

    if wide_state_required and MARKET_STATE_QUALITY.exists():
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
    elif wide_state_required:
        record(
            "node D full-calendar market-state gate",
            False,
            str(MARKET_STATE_QUALITY.relative_to(ROOT)),
        )
    else:
        record(
            "node D full-calendar market-state gate",
            True,
            "not required by the executable claim-input perimeter",
        )
    if UNIFIED_QUALITY_PANEL.exists():
        route_quality = pd.read_parquet(UNIFIED_QUALITY_PANEL)
        route_provenance = str(verify(UNIFIED_QUALITY_PANEL).get("status"))
        route_passed, route_detail = validate_unified_route_layer(
            route_quality,
            provenance_status=route_provenance,
        )
        partition_passed, partition_detail = validate_released_route_partitions()
        record(
            "node D full-calendar directed-route gate",
            route_passed and partition_passed,
            f"{route_detail}; partition_release={partition_detail}",
        )
    else:
        record(
            "node D full-calendar directed-route gate",
            False,
            str(UNIFIED_QUALITY_PANEL.relative_to(ROOT)),
        )
    lock_claim_ids: set[str] = set()
    lock_payload: dict = {}
    if SPECIFICATION_LOCK.exists():
        try:
            lock_payload = json.loads(SPECIFICATION_LOCK.read_text())
            lock_passed, lock_detail = validate_specification_lock(
                lock_payload,
                require_confirmatory=True,
            )
            execution_perimeter = claim_execution_perimeter(lock_payload)
            lock_claim_ids = {
                str(claim["id"])
                for claim in execution_perimeter.executable_claims
                if claim.get("status") in REGISTERED_CLAIM_STATUSES
            }
            input_passed, input_detail = validate_claim_input_layer(lock_payload)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            lock_passed, lock_detail = False, type(exc).__name__
            input_passed, input_detail = False, type(exc).__name__
        record("node E1 specification lock", lock_passed, lock_detail)
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
                lock_payload=lock_payload,
                require_confirmatory=True,
            )
        except (json.JSONDecodeError, OSError) as exc:
            model_passed, model_detail = False, type(exc).__name__
        record("empirical model ledger", model_passed, model_detail)
    else:
        record("empirical model ledger", False, str(MODEL_LEDGER.relative_to(ROOT)))

    if LITERATURE_AUDIT.exists():
        cited = cited_bibliography_keys(sorted(PAPER_SECTIONS.glob("*.tex")))
        admission = load_source_admission(LITERATURE_SOURCE_ADMISSION)
        admission_passed, admission_detail = validate_source_admission(cited, admission)
        record("node B source-admission gate", admission_passed, admission_detail)
        literature_passed, literature_detail = validate_literature_audit(
            LITERATURE_AUDIT.read_text(),
            cited,
            JFE_VENUE_CARDS,
            verify_source_sets=True,
            manuscript_paths=sorted(PAPER_SECTIONS.glob("*.tex")),
            use_contracts=load_literature_use_contracts(),
            admission_ledger=admission,
        )
        record("node B full-text literature ledger", literature_passed, literature_detail)
    else:
        record("node B source-admission gate", False, "literature audit missing")
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
        for name, passed, detail in route_cost_panel_checks(PANEL):
            record(name, passed, detail)
        notes = str(panel_manifest.get("notes") or "")
        argv = [str(value) for value in panel_manifest.get("argv") or []]
        record(
            "panel release scope explicit",
            "scope=main_v1" in notes and "--main-spec" in argv,
            f"main_spec={'--main-spec' in argv}; scope={notes.split(';', 1)[0] or 'missing'}",
        )
        con = duckdb.connect()
        summary = con.execute(
            f"""
            SELECT count(DISTINCT date), min(date), max(date),
                count(DISTINCT reserve_hour_utc), min(reserve_hour_utc),
                max(reserve_hour_utc)
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
            int(summary[0]) >= 2_238
            and str(summary[2]) == sample_end_iso()
            and int(summary[3]) == 24
            and int(summary[4]) == 0
            and int(summary[5]) == 23,
            f"days={summary[0]:,}; range={summary[1]}..{summary[2]}; "
            f"hours={summary[3]} ({summary[4]}..{summary[5]})",
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

    if executable_inputs_require(route_inputs):
        for name, passed, detail in transaction_frontier_artifact_checks(
            TRANSACTION_FRONTIER,
            TRANSACTION_FRONTIER_REJECTIONS,
            TRANSACTION_FRONTIER_SUPPORT,
            prefix="transaction frontier",
            coverage_label="audit-day",
            expected_days=77,
            first_day="20200214",
            last_day="20260615",
        ):
            record(name, passed, detail)

        try:
            frontier_release = resolve_frontier_release()
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
            record("transaction frontier daily release", False, str(error))
        else:
            record(
                "transaction frontier daily release",
                True,
                f"generation={frontier_release.generation_id}",
            )
            for name, passed, detail in transaction_frontier_artifact_checks(
                frontier_release.artifacts["panel"],
                frontier_release.artifacts["rejections"],
                frontier_release.artifacts["support"],
                prefix="transaction frontier daily",
                coverage_label="calendar",
                expected_days=len(calendar_days(RESEARCH_SAMPLE_START, RESEARCH_SAMPLE_END)),
                first_day=RESEARCH_SAMPLE_START,
                last_day=RESEARCH_SAMPLE_END,
            ):
                record(name, passed, detail)
            frontier_release.assert_current()
    else:
        record(
            "transaction frontier artifacts",
            True,
            "not required by the executable claim-input perimeter",
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
            *WITHDRAWN_ROUTE_GAS_SCRIPTS,
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

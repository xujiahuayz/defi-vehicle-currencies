"""Canonical ownership registry for every executable D3 claim input."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ddvc.analysis.dominance_cost_release import DOMINANCE_COST_RELEASE_RELATIVE
from ddvc.model_registry import claim_execution_perimeter


OwnershipStatus = Literal["built", "external_prerequisite"]


@dataclass(frozen=True)
class D3BuildStage:
    """One ordered D3 materialization stage and all artifacts it owns."""

    script: str
    arguments: tuple[str, ...]
    purpose: str
    outputs: tuple[str, ...]


@dataclass(frozen=True)
class D3ExternalPrerequisite:
    """One D3 input produced by a separately controlled expensive owner."""

    path: str
    owner: str
    purpose: str


@dataclass(frozen=True)
class D3InputOwnership:
    """The unique owner and status of one executable specification input."""

    path: str
    status: OwnershipStatus
    owner: str


D3_BUILD_STAGES = (
    D3BuildStage(
        "build_dominance_cost_panel.py",
        ("--threads", "1", "--memory-limit", "2GB"),
        "pairwise WETH-versus-comparator route-cost outcomes with an outcome-specific zero-retention support ledger",
        (
            DOMINANCE_COST_RELEASE_RELATIVE,
        ),
    ),
    D3BuildStage(
        "build_routing_maturation_panel.py",
        ("--threads", "1", "--memory-limit", "1GB"),
        "estimator-ready recurrent cell-days, conditioned transition cells, and exact-calendar routing links",
        (
            "data/processed/routing_maturation_cell_day.parquet",
            "data/processed/routing_transition_cells.parquet",
            "data/processed/routing_maturation_exact_horizons.parquet",
        ),
    ),
    D3BuildStage(
        "process/build_cex_reference_support.py",
        (),
        "published exact-address positive CEX-reference support for the rent bound",
        ("data/processed/cex_reference_support.parquet",),
    ),
    D3BuildStage(
        "build_ethereum_day_calendar.py",
        ("--workers", "4"),
        "exact chain-wide UTC-day block bounds for DEX-independent sampling",
        ("data/processed/ethereum_utc_day_calendar.parquet",),
    ),
    D3BuildStage(
        "process/build_route_gas_units.py",
        ("--workers", "8", "--panel-only"),
        "receipt-measured route gas by topology, venue, and vehicle",
        ("data/processed/route_gas_units.parquet",),
    ),
    D3BuildStage(
        "build_intermediation_by_type.py",
        ("--workers", "8", "--panel-only"),
        "one-vehicle route counts and value support by asset type",
        ("data/processed/intermediation_by_type_daily.parquet",),
    ),
    D3BuildStage(
        "build_cross_venue_routing_series.py",
        ("--workers", "8", "--panel-only"),
        "routing integration, splitting, and complexity margins",
        ("data/processed/cross_venue_routing_daily.parquet",),
    ),
    D3BuildStage(
        "build_vehicle_excess_use.py",
        ("--workers", "8", "--panel-only"),
        "continuous vehicle dominance normalized by endpoint demand",
        ("data/processed/vehicle_excess_use_daily.parquet",),
    ),
    D3BuildStage(
        "build_vehicle_swap_style.py",
        ("--workers", "8", "--panel-only"),
        "matched-support count/value dominance by observable route morphology, complexity, integration, and capped notional",
        ("data/processed/vehicle_swap_style_daily.parquet",),
    ),
    D3BuildStage(
        "build_vehicle_centrality.py",
        (
            "--stride",
            "24",
            "--jobs",
            "4",
            "--out",
            "data/processed/vehicle_centrality_dense.parquet",
            "--panel-only",
        ),
        "metric-sensitive topology companion",
        ("data/processed/vehicle_centrality_dense.parquet",),
    ),
    D3BuildStage(
        "build_token_price_panel.py",
        ("--workers", "2"),
        "canonical address-day USD prices used by liquidity and route valuation",
        ("data/processed/token_price_daily.parquet",),
    ),
    D3BuildStage(
        "build_pool_capital_panel.py",
        (),
        "only protocol-admitted deposited capital and exact candidate allocation; V3 provider TVL is excluded",
        (
            "data/processed/pool_capital_daily.parquet",
            "data/processed/pool_candidate_capital_daily.parquet",
            "data/processed/pool_capital_rejections.parquet",
        ),
    ),
    D3BuildStage(
        "build_rent_incidence_panel.py",
        ("v2",),
        "constant-product liquidity-provider rent inputs; V3 is withheld pending custody, ownership, and path-LVR reconciliation",
        ("data/processed/rent_incidence_v2_pool_day.parquet",),
    ),
    D3BuildStage(
        "build_lp_liquidity_flow_panel.py",
        (),
        "causal V3 LP dollar-flow inputs without an unvalidated capital-stock proxy",
        (
            "data/processed/lp_liquidity_flow_events_v3.parquet",
            "data/processed/lp_liquidity_flow_candidates_v3.parquet",
            "data/processed/lp_liquidity_flow_rejections_v3.parquet",
            "data/processed/lp_liquidity_flow_daily_v3.parquet",
        ),
    ),
    D3BuildStage(
        "build_liquidity_capital_flow_panels.py",
        ("--threads", "1", "--memory-limit", "1GB"),
        "candidate-day and exact-calendar-horizon liquidity-allocation inputs",
        (
            "data/processed/liquidity_capital_flow_candidate_day.parquet",
            "data/processed/liquidity_capital_flow_exact_horizons.parquet",
        ),
    ),
    D3BuildStage(
        "build_counterfactual_dominance.py",
        ("--stage", "gross", "--workers", "4"),
        "gross exact-state route counterfactual released before any gas-price dependency",
        ("data/processed/counterfactual_dominance_gross.parquet",),
    ),
    D3BuildStage(
        "process/build_route_transaction_gas.py",
        ("--workers", "8"),
        "exact realised-transaction effective gas price joined by transaction and block",
        ("data/processed/route_transaction_gas.parquet",),
    ),
    D3BuildStage(
        "build_counterfactual_dominance.py",
        ("--stage", "final", "--panel-only"),
        "gas-adjusted exact-state route counterfactual with common transaction gas price across alternatives",
        ("data/processed/counterfactual_dominance.parquet",),
    ),
)


D3_EXTERNAL_PREREQUISITES = (
    D3ExternalPrerequisite(
        "data/empirical/route_cost_panel_v2.parquet",
        "scripts/run_route_cost_panel.py",
        "full locked route-cost generation built by its separately controlled expensive owner",
    ),
)


def executable_claim_inputs(specification: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the exact deduplicated input perimeter for execution-open claims."""

    perimeter = claim_execution_perimeter(specification)
    paths = {
        str(path)
        for claim in perimeter.executable_claims
        for path in claim.get("inputs", [])
    }
    return tuple(sorted(paths))


def d3_input_ownership(
    specification: Mapping[str, Any],
    *,
    stages: Iterable[D3BuildStage] = D3_BUILD_STAGES,
    external_prerequisites: Iterable[
        D3ExternalPrerequisite
    ] = D3_EXTERNAL_PREREQUISITES,
) -> tuple[D3InputOwnership, ...]:
    """Require one unique registered owner for every executable D3 input."""

    candidates: dict[str, list[D3InputOwnership]] = defaultdict(list)
    for stage in stages:
        for path in stage.outputs:
            candidates[path].append(D3InputOwnership(path, "built", stage.script))
    external_paths: set[str] = set()
    for prerequisite in external_prerequisites:
        if prerequisite.path in external_paths:
            raise ValueError(
                f"D3 external prerequisite is registered more than once: {prerequisite.path}"
            )
        external_paths.add(prerequisite.path)
        candidates[prerequisite.path].append(
            D3InputOwnership(
                prerequisite.path,
                "external_prerequisite",
                prerequisite.owner,
            )
        )

    required = executable_claim_inputs(specification)
    missing = [path for path in required if path not in candidates]
    duplicates = [path for path in required if len(candidates[path]) != 1]
    stale_external = sorted(external_paths - set(required))
    if missing or duplicates or stale_external:
        raise ValueError(
            "D3 input ownership does not equal the executable specification perimeter: "
            f"missing={missing or 'none'}; duplicate={duplicates or 'none'}; "
            f"stale_external={stale_external or 'none'}"
        )
    return tuple(candidates[path][0] for path in required)

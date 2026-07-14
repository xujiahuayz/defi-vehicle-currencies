"""Canonical variable registry for paper-facing DVC analysis panels.

The registry is the single source for variable notation, calculation language,
and the columns expected in the wide observations table. Table renderers and
processing scripts should import this file rather than duplicating definitions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VariableSpec:
    """A paper variable and its implementation in the observations table."""

    group: str
    name: str
    column: str
    notation: str
    unit: str
    construction: str
    source: str
    used_for: str
    in_observations_table: bool = True
    include_in_summary: bool = False
    summary_panel: str | None = None
    summary_label: str | None = None
    summary_scale: float = 1.0
    summary_level: str = "token-day"


VARIABLE_SPECS: tuple[VariableSpec, ...] = (
    VariableSpec(
        group="Panel A. Vehicle-use measures",
        name="Bridge share",
        column="bridge_share",
        notation=r"$\mathrm{BridgeShare}_{k,t}$",
        unit="candidate vehicle token x day",
        construction=(
            "USD volume of indirect routes whose intermediate token is k divided by "
            "total indirect-route USD volume on day t."
        ),
        source="data/empirical/bridge_daily.parquet",
        used_for="Main vehicle-use outcome; measurement and persistence tests.",
        include_in_summary=True,
        summary_panel="Panel B. Vehicle-use measures, token-day",
        summary_label="BridgeShare (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel A. Vehicle-use measures",
        name="All-route bridge share",
        column="all_route_bridge_share",
        notation=r"$\mathrm{AllRouteBridgeShare}_{k,t}$",
        unit="candidate vehicle token x day",
        construction=(
            "USD volume of routes whose intermediate token is k divided by total "
            "route USD volume on day t."
        ),
        source="bridge_daily plus route_denominator_daily",
        used_for="Economic-scope denominator robustness.",
        include_in_summary=True,
        summary_panel="Panel B. Vehicle-use measures, token-day",
        summary_label="All-route bridge share (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel A. Vehicle-use measures",
        name="Bridge count share",
        column="bridge_count_share",
        notation=r"$\mathrm{BridgeCountShare}_{k,t}$",
        unit="candidate vehicle token x day",
        construction=(
            "Number of indirect route units whose intermediate token is k divided "
            "by total indirect route-unit count on day t."
        ),
        source="data/empirical/bridge_daily.parquet",
        used_for="Count-weighted measurement robustness.",
        include_in_summary=True,
        summary_panel="Panel B. Vehicle-use measures, token-day",
        summary_label="Bridge count share (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel A. Vehicle-use measures",
        name="Pair coverage",
        column="pair_coverage",
        notation=r"$\mathrm{PairCoverage}_{k,t}$",
        unit="candidate vehicle token x day",
        construction=(
            "Share of active endpoint pairs on day t for which k appears as an "
            "intermediate token in at least one indirect route."
        ),
        source="data/empirical/bridge_daily.parquet",
        used_for="Extensive-margin vehicle coverage.",
        include_in_summary=True,
        summary_panel="Panel B. Vehicle-use measures, token-day",
        summary_label="Pair coverage (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel A. Vehicle-use measures",
        name="Main-vehicle pair share",
        column="pair_main_vehicle_share",
        notation=r"$\mathrm{MainVehiclePairShare}_{k,t}$",
        unit="candidate vehicle token x day",
        construction=(
            "Share of active endpoint pairs for which k is the largest intermediate "
            "vehicle by realized indirect-route USD volume on day t."
        ),
        source="data/empirical/bridge_daily.parquet",
        used_for="Pair-level dominance and robustness.",
        include_in_summary=True,
        summary_panel="Panel B. Vehicle-use measures, token-day",
        summary_label="Main-vehicle pair share (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel A. Vehicle-use measures",
        name="Bridge volume",
        column="bridge_volume_usd",
        notation=r"$\mathrm{BridgeVolume}_{k,t}$",
        unit="USD, candidate vehicle token x day",
        construction="USD volume of indirect routes whose intermediate token is k on day t.",
        source="data/empirical/bridge_daily.parquet",
        used_for="Economic magnitude and weighting.",
        include_in_summary=True,
        summary_panel="Panel B. Vehicle-use measures, token-day",
        summary_label="Bridge volume ($mn)",
        summary_scale=1.0 / 1_000_000.0,
    ),
    VariableSpec(
        group="Panel B. Network and route-denominator controls",
        name="Raw token volume share",
        column="vshare",
        notation=r"$\mathrm{VShare}_{k,t}$",
        unit="candidate vehicle token x day",
        construction=(
            "Token k's total in-route plus out-route USD volume divided by total "
            "token volume in the daily route network."
        ),
        source="data/metrics/<date>.parquet",
        used_for="Exploratory contrast with bridge-only measures.",
    ),
    VariableSpec(
        group="Panel B. Network and route-denominator controls",
        name="Route betweenness",
        column="betweenness_centrality",
        notation=r"$\mathrm{Betweenness}_{k,t}$",
        unit="candidate vehicle token x day",
        construction="Daily route-network betweenness centrality for token k.",
        source="data/metrics/<date>.parquet",
        used_for="Network-theoretic vehicle proxy.",
        include_in_summary=True,
        summary_panel="Panel B. Vehicle-use measures, token-day",
        summary_label="Route betweenness",
    ),
    VariableSpec(
        group="Panel B. Network and route-denominator controls",
        name="Volume-weighted betweenness",
        column="volume_weighted_betweenness",
        notation=r"$\mathrm{Betweenness}^{V}_{k,t}$",
        unit="candidate vehicle token x day",
        construction="Daily USD-volume-weighted route betweenness centrality for token k.",
        source="data/metrics/<date>.parquet",
        used_for="Network-theoretic robustness.",
    ),
    VariableSpec(
        group="Panel B. Network and route-denominator controls",
        name="All-route volume",
        column="daily_all_route_volume_usd",
        notation=r"$\mathrm{AllRouteVolume}_{t}$",
        unit="day",
        construction="Total USD route volume across direct and indirect route units on day t.",
        source="data/empirical/route_denominator_daily.parquet",
        used_for="Daily market-size control and summary statistics.",
        include_in_summary=True,
        summary_panel="Panel A. Daily route activity",
        summary_label="Total route volume ($bn)",
        summary_scale=1.0 / 1_000_000_000.0,
        summary_level="day",
    ),
    VariableSpec(
        group="Panel B. Network and route-denominator controls",
        name="Indirect-route volume",
        column="daily_indirect_route_volume_usd",
        notation=r"$\mathrm{IndirectRouteVolume}_{t}$",
        unit="day",
        construction="Total USD volume in indirect route units on day t.",
        source="data/empirical/route_denominator_daily.parquet",
        used_for="BridgeShare denominator and scope.",
        include_in_summary=True,
        summary_panel="Panel A. Daily route activity",
        summary_label="Indirect route volume ($bn)",
        summary_scale=1.0 / 1_000_000_000.0,
        summary_level="day",
    ),
    VariableSpec(
        group="Panel B. Network and route-denominator controls",
        name="Indirect-route share",
        column="indirect_route_share",
        notation=r"$\mathrm{IndirectRouteShare}_{t}$",
        unit="day",
        construction="Indirect-route USD volume divided by total route USD volume on day t.",
        source="data/empirical/route_denominator_daily.parquet",
        used_for="Overall importance of routed exchange.",
        include_in_summary=True,
        summary_panel="Panel A. Daily route activity",
        summary_label="Indirect route share (%)",
        summary_scale=100.0,
        summary_level="day",
    ),
    VariableSpec(
        group="Panel C. Liquidity measures",
        name="Vehicle-linked liquidity",
        column="vehicle_linked_liquidity_usd",
        notation=r"$\mathrm{VehicleLiquidity}_{k,t}$",
        unit="USD, candidate vehicle token x day",
        construction=(
            "USD TVL in Uniswap V3 pools linked to candidate vehicle k after "
            "filtering subgraph TVL outliers."
        ),
        source="data/exhibits/lp_concentration.parquet",
        used_for="Liquidity concentration, persistence, and stickiness tests.",
        include_in_summary=True,
        summary_panel="Panel C. Liquidity and route-cost opportunity",
        summary_label="Vehicle-linked LP liquidity ($bn)",
        summary_scale=1.0 / 1_000_000_000.0,
    ),
    VariableSpec(
        group="Panel C. Liquidity measures",
        name="LP concentration",
        column="lp_concentration",
        notation=r"$\mathrm{LPConc}_{k,t}$",
        unit="candidate vehicle token x day",
        construction=(
            "Vehicle-linked liquidity for k divided by total vehicle-linked "
            "liquidity across the candidate vehicle set on day t."
        ),
        source="data/exhibits/lp_concentration.parquet",
        used_for="Liquidity persistence and predictability regressions.",
        include_in_summary=True,
        summary_panel="Panel C. Liquidity and route-cost opportunity",
        summary_label="LP concentration (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel C. Liquidity measures",
        name="Log vehicle-linked liquidity",
        column="log_vehicle_linked_liquidity",
        notation=r"$\log(1+\mathrm{VehicleLiquidity}_{k,t})$",
        unit="candidate vehicle token x day",
        construction="Natural log of one plus vehicle-linked liquidity in USD.",
        source="data/exhibits/lp_concentration.parquet",
        used_for="Liquidity-level regressions.",
    ),
    VariableSpec(
        group="Panel D. Route-cost opportunity measures",
        name="Direct available share",
        column="direct_available_share",
        notation=r"$\Pr(D_{ijqt})$",
        unit="candidate vehicle token x day",
        construction=(
            "Share of endpoint-pair quote rows for which the direct route is "
            "executable at the main trade size."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Direct-market completeness and architecture tests.",
        include_in_summary=True,
        summary_panel="Panel C. Liquidity and route-cost opportunity",
        summary_label="Direct route available (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel D. Route-cost opportunity measures",
        name="Vehicle-route available share",
        column="vehicle_available_share",
        notation=r"$\Pr(V_{ijkqt})$",
        unit="candidate vehicle token x day",
        construction=(
            "Share of endpoint-pair quote rows for which both legs through k are "
            "executable at the main trade size."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Vehicle-route feasibility.",
        include_in_summary=True,
        summary_panel="Panel C. Liquidity and route-cost opportunity",
        summary_label="Vehicle route available (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel D. Route-cost opportunity measures",
        name="No-direct but vehicle available",
        column="no_direct_vehicle_available_share",
        notation=r"$\Pr(\neg D_{ijqt},V_{ijkqt})$",
        unit="candidate vehicle token x day",
        construction=(
            "Share of endpoint-pair quote rows with no executable direct route but "
            "an executable route through k."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Availability and thin-direct-market protection.",
        include_in_summary=True,
        summary_panel="Panel C. Liquidity and route-cost opportunity",
        summary_label="No-direct vehicle route (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel D. Route-cost opportunity measures",
        name="Route-cost advantage",
        column="route_cost_advantage_median_bps",
        notation=r"$\Delta \mathrm{Cost}_{ijkqt}$",
        unit="basis points, candidate vehicle token x day",
        construction=(
            "Median, across common-support quote rows, of 10,000 times "
            "the vehicle-route output advantage over the direct route."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Common-support execution-cost tests.",
        include_in_summary=True,
        summary_panel="Panel C. Liquidity and route-cost opportunity",
        summary_label="Vehicle advantage (bp)",
    ),
    VariableSpec(
        group="Panel D. Route-cost opportunity measures",
        name="Vehicle beats direct",
        column="vehicle_beats_direct_share",
        notation=r"$\Pr(\Delta \mathrm{Cost}_{ijkqt}>0)$",
        unit="candidate vehicle token x day",
        construction=(
            "Share of common-support quote rows for which the vehicle route gives "
            "higher output than the direct route."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Execution-cost heterogeneity.",
        include_in_summary=True,
        summary_panel="Panel C. Liquidity and route-cost opportunity",
        summary_label="Vehicle beats direct route (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel D. Route-cost opportunity measures",
        name="Thin-direct share",
        column="thin_direct_share",
        notation=r"$\Pr(T_{ijqt})$",
        unit="candidate vehicle token x day",
        construction=(
            "Share of quote rows with an executable direct route whose direct output "
            "is below 90 percent of notional."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Thin-direct protection.",
        include_in_summary=True,
        summary_panel="Panel C. Liquidity and route-cost opportunity",
        summary_label="Thin direct route share (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel E. Stress and dynamic variables",
        name="Downside WETH stress",
        column="stress_downside",
        notation=r"$\mathrm{Stress}_{t}$",
        unit="day",
        construction="Positive part of the negative daily log return in the WETH price.",
        source="data/empirical/bridge_daily.parquet",
        used_for="Stress-rotation tests and controls.",
        include_in_summary=True,
        summary_panel="Panel A. Daily route activity",
        summary_label="Downside WETH stress (%)",
        summary_scale=100.0,
        summary_level="day",
    ),
    VariableSpec(
        group="Panel E. Stress and dynamic variables",
        name="Eight percent stress event",
        column="stress_event_8pct",
        notation=r"$1\{\mathrm{Stress}_{t}\ge 0.08\}$",
        unit="day",
        construction="Indicator that downside WETH stress is at least 8 percent on day t.",
        source="constructed from WETH price in bridge_daily",
        used_for="Main daily stress-event design.",
    ),
    VariableSpec(
        group="Panel E. Stress and dynamic variables",
        name="Future bridge share, seven days",
        column="future_bridge_share_t7",
        notation=r"$\mathrm{BridgeShare}_{k,t+7}$",
        unit="candidate vehicle token x day",
        construction="BridgeShare for token k seven calendar days after t.",
        source="constructed from observations table",
        used_for="Dynamic predictability regressions.",
    ),
    VariableSpec(
        group="Panel E. Stress and dynamic variables",
        name="Change in bridge share, seven days",
        column="delta_bridge_share_t7",
        notation=r"$\Delta_{7}\mathrm{BridgeShare}_{k,t}$",
        unit="candidate vehicle token x day",
        construction="BridgeShare at t+7 minus BridgeShare at t.",
        source="constructed from observations table",
        used_for="Persistence and displacement tests.",
    ),
    VariableSpec(
        group="Panel F. V4 settlement implementation measures",
        name="Settlement transfer incidence",
        column="settlement_transfer_incidence",
        notation=r"$\Pr(\mathrm{Transfer}_{k,r}=1)$",
        unit="candidate vehicle token x week",
        construction=(
            "Mean receipt-level indicator that a matched route unit contains an "
            "ERC-20 Transfer log for the intermediate vehicle token."
        ),
        source="data/empirical/v4_settlement_transfer_detail.csv",
        used_for="V4 settlement virtualization and netting tests.",
        include_in_summary=True,
        summary_panel="Panel D. Settlement-transfer sample",
        summary_label="Intermediary transfer incidence (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Panel F. V4 settlement implementation measures",
        name="Settlement receipt count",
        column="settlement_receipt_count",
        notation=r"$N^{\mathrm{receipt}}_{k,t}$",
        unit="candidate vehicle token x week",
        construction="Number of receipt-audited matched route units for vehicle k in week t.",
        source="data/empirical/v4_settlement_transfer_detail.csv",
        used_for="Settlement-sample size and weights.",
        include_in_summary=True,
        summary_panel="Panel D. Settlement-transfer sample",
        summary_label="Receipt observations",
    ),
)


OBSERVATIONS_TABLE_COLUMNS: tuple[str, ...] = tuple(
    spec.column for spec in VARIABLE_SPECS if spec.in_observations_table
)

SUMMARY_SPECS: tuple[VariableSpec, ...] = tuple(
    spec for spec in VARIABLE_SPECS if spec.include_in_summary
)


def specs_by_group() -> dict[str, tuple[VariableSpec, ...]]:
    """Return variable specs grouped in display order."""

    grouped: dict[str, list[VariableSpec]] = {}
    for spec in VARIABLE_SPECS:
        grouped.setdefault(spec.group, []).append(spec)
    return {group: tuple(specs) for group, specs in grouped.items()}

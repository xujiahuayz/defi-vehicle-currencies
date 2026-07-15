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
    formula: str
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


@dataclass(frozen=True)
class NotationDefinition:
    """Meaning and measurement unit of a symbol used in paper notation."""

    notation: str
    unit: str
    definition: str


NOTATION_DEFINITIONS: tuple[NotationDefinition, ...] = (
    NotationDefinition(
        notation=r"$i,\ j$",
        unit="Token",
        definition=r"Input (sold) and output (bought) endpoint tokens; the ordered pair is $i\to j$.",
    ),
    NotationDefinition(
        notation=r"$k$",
        unit="Token",
        definition=r"Candidate vehicle token used as the route intermediate; $k\notin\{i,j\}$.",
    ),
    NotationDefinition(
        notation=r"$t,\ w$",
        unit="UTC day / UTC week",
        definition=r"$t$ indexes calendar days; $w$ indexes calendar weeks in settlement variables.",
    ),
    NotationDefinition(
        notation=r"$q$",
        unit="USD",
        definition=r"Input quote notional. Un-suffixed route-cost columns use $q=\$10{,}000$.",
    ),
    NotationDefinition(
        notation=r"$r$",
        unit="Route unit",
        definition=r"Receipt-audited coherent multihop route unit indexed by $r$.",
    ),
    NotationDefinition(
        notation=r"$\mathcal{P}_{k,t,q}$",
        unit="Set of token pairs",
        definition=r"Ordered endpoint pairs eligible for $k$ and quoted on day $t$ at notional $q$.",
    ),
    NotationDefinition(
        notation=(
            r"$\mathcal{D}_{k,t,q},\ \mathcal{V}_{k,t,q},\ \mathcal{C}_{k,t,q},\ "
            r"\mathcal{T}_{k,t,q},\ \mathcal{W}_{k,t,q}$"
        ),
        unit="Sets of token pairs",
        definition=(
            r"Subsets of $\mathcal P_{k,t,q}$ with a direct route ($\mathcal D$), a route via $k$ "
            r"($\mathcal V$), both routes ($\mathcal C=\mathcal D\cap\mathcal V$), a thin direct "
            r"route ($\mathcal T$), or a vehicle-route cost advantage ($\mathcal W$)."
        ),
    ),
    NotationDefinition(
        notation=r"$D_{i,j,q,t},\ V_{i,j,k,q,t},\ T_{i,j,q,t}$",
        unit="Indicator (0/1)",
        definition=(
            r"Indicators for direct-route availability ($D$), route-through-$k$ availability ($V$), "
            r"and an executable direct route returning less than $0.9q$ ($T$)."
        ),
    ),
    NotationDefinition(
        notation=r"$O^{D}_{i,j,q,t},\ O^{V}_{i,j,k,q,t}$",
        unit="USD",
        definition=r"Quoted output values; superscripts $D$ and $V$ denote direct and vehicle routes.",
    ),
    NotationDefinition(
        notation=r"$\Delta C_{i,j,k,q,t}$",
        unit="Basis points",
        definition=(
            r"$10{,}000\,(O^{V}_{i,j,k,q,t}-O^{D}_{i,j,q,t})/O^{D}_{i,j,q,t}$ on "
            r"$\mathcal C_{k,t,q}$."
        ),
    ),
    NotationDefinition(
        notation=r"$\mathcal{R}_{k,w}$",
        unit="Set of route units",
        definition=r"Receipt-audited matched route units using vehicle $k$ in UTC week $w$.",
    ),
    NotationDefinition(
        notation=r"$\mathcal{R}^{\mathrm{transfer}}_{k,w}$",
        unit="Set of route units",
        definition=r"Members of $\mathcal R_{k,w}$ whose receipt logs a transfer of vehicle $k$.",
    ),
    NotationDefinition(
        notation=r"$|\mathcal{A}|,\ \mathbf{1}\{\cdot\}$",
        unit="Count / indicator (0/1)",
        definition=r"Cardinality of set $\mathcal A$ and an indicator equal to one when its condition is true.",
    ),
    NotationDefinition(
        notation=r"$\mathrm{Betweenness}^{\mathrm{vol}},\ \Delta_{7}$",
        unit="USD weighting / 7 days",
        definition=r"Superscript $\mathrm{vol}$ denotes USD weighting; $\Delta_7 X_t=X_{t+7}-X_t$.",
    ),
)


VARIABLE_SPECS: tuple[VariableSpec, ...] = (
    VariableSpec(
        group="Vehicle-use measures",
        name="Vehicle share",
        column="bridge_share",
        notation=r"$\mathrm{VehicleShare}_{k,t}$",
        formula=r"$\displaystyle\frac{B_{k,t}}{B_t}$",
        unit="Fraction (0--1)",
        construction=(
            r"$B_{k,t}$ is indirect-route USD volume through $k$; $B_t$ is total "
            r"indirect-route USD volume on day $t$."
        ),
        source="data/empirical/bridge_daily.parquet",
        used_for="Main vehicle-use outcome; measurement and persistence tests.",
        include_in_summary=True,
        summary_panel="Vehicle-use measures, token-day",
        summary_label="Vehicle share (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="All-route vehicle share",
        column="all_route_bridge_share",
        notation=r"$\mathrm{AllRouteVehicleShare}_{k,t}$",
        formula=r"$\displaystyle\frac{B_{k,t}}{A_t}$",
        unit="Fraction (0--1)",
        construction=(
            r"$B_{k,t}$ is indirect-route USD volume through $k$; $A_t$ is total "
            r"direct plus indirect route USD volume on day $t$."
        ),
        source="bridge_daily plus route_denominator_daily",
        used_for="Economic-scope denominator robustness.",
        include_in_summary=True,
        summary_panel="Vehicle-use measures, token-day",
        summary_label="All-route vehicle share (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Vehicle count share",
        column="bridge_count_share",
        notation=r"$\mathrm{VehicleCountShare}_{k,t}$",
        formula=r"$\displaystyle\frac{N^{B}_{k,t}}{N^{B}_{t}}$",
        unit="Fraction (0--1)",
        construction=(
            r"$N^{B}_{k,t}$ counts indirect route units through $k$; $N^{B}_{t}$ counts "
            r"all indirect route units on day $t$."
        ),
        source="data/empirical/bridge_daily.parquet",
        used_for="Count-weighted measurement robustness.",
        include_in_summary=True,
        summary_panel="Vehicle-use measures, token-day",
        summary_label="Vehicle count share (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Pair coverage",
        column="pair_coverage",
        notation=r"$\mathrm{PairCoverage}_{k,t}$",
        formula=r"$\displaystyle\frac{|\mathcal A^{k}_{t}|}{|\mathcal A_t|}$",
        unit="Fraction (0--1)",
        construction=(
            r"$\mathcal A_t$ is the set of active endpoint pairs; $\mathcal A^k_t$ contains "
            r"pairs using $k$ in at least one indirect route on day $t$."
        ),
        source="data/empirical/bridge_daily.parquet",
        used_for="Extensive-margin vehicle coverage.",
        include_in_summary=True,
        summary_panel="Vehicle-use measures, token-day",
        summary_label="Pair coverage (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Main-vehicle pair share",
        column="pair_main_vehicle_share",
        notation=r"$\mathrm{MainVehiclePairShare}_{k,t}$",
        formula=r"$\displaystyle\frac{|\mathcal M^{k}_{t}|}{|\mathcal A_t|}$",
        unit="Fraction (0--1)",
        construction=(
            r"$\mathcal M^k_t\subseteq\mathcal A_t$ contains pairs for which $k$ has the "
            r"largest realized indirect-route USD volume on day $t$."
        ),
        source="data/empirical/bridge_daily.parquet",
        used_for="Pair-level dominance and robustness.",
        include_in_summary=True,
        summary_panel="Vehicle-use measures, token-day",
        summary_label="Main-vehicle pair share (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Vehicle volume",
        column="bridge_volume_usd",
        notation=r"$\mathrm{VehicleVolume}_{k,t}$",
        formula=r"$B_{k,t}$",
        unit="USD",
        construction=r"Sum of realized USD volume over indirect routes using vehicle $k$ on day $t$.",
        source="data/empirical/bridge_daily.parquet",
        used_for="Economic magnitude and weighting.",
        include_in_summary=True,
        summary_panel="Vehicle-use measures, token-day",
        summary_label="Vehicle volume ($mn)",
        summary_scale=1.0 / 1_000_000.0,
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="Raw token volume share",
        column="vshare",
        notation=r"$\mathrm{VShare}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{V^{\mathrm{in}}_{k,t}+V^{\mathrm{out}}_{k,t}}"
            r"{\sum_{\ell}(V^{\mathrm{in}}_{\ell,t}+V^{\mathrm{out}}_{\ell,t})}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"$V^{\mathrm{in}}_{k,t}$ and $V^{\mathrm{out}}_{k,t}$ are inbound and outbound "
            r"route-leg USD volumes for $k$; $\ell$ indexes every token in the day-$t$ network."
        ),
        source="data/metrics/<date>.parquet",
        used_for="Exploratory contrast with bridge-only measures.",
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="Route betweenness",
        column="betweenness_centrality",
        notation=r"$\mathrm{Betweenness}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{N^{\mathrm{mid}}_{k,t}}"
            r"{N^{\mathrm{route}}_t-N^{\mathrm{src}}_{k,t}-N^{\mathrm{sink}}_{k,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of day-$t$ intent routes on which $k$ is intermediate, excluding routes "
            r"where $k$ is the source or sink. Superscripts identify each route role."
        ),
        source="data/metrics/<date>.parquet",
        used_for="Network-theoretic vehicle proxy.",
        include_in_summary=True,
        summary_panel="Vehicle-use measures, token-day",
        summary_label="Route betweenness",
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="Volume-weighted betweenness",
        column="volume_weighted_betweenness",
        notation=r"$\mathrm{Betweenness}^{\mathrm{vol}}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{V^{\mathrm{mid}}_{k,t}}"
            r"{V^{\mathrm{route}}_t-V^{\mathrm{src}}_{k,t}-V^{\mathrm{sink}}_{k,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"USD-volume analogue of $\mathrm{Betweenness}_{k,t}$; each $V$ term is the "
            r"day-$t$ route volume assigned to the indicated role."
        ),
        source="data/metrics/<date>.parquet",
        used_for="Network-theoretic robustness.",
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="All-route volume",
        column="daily_all_route_volume_usd",
        notation=r"$\mathrm{AllRouteVolume}_{t}$",
        formula=r"$\mathrm{DirectRouteVolume}_t+\mathrm{IndirectRouteVolume}_t$",
        unit="USD",
        construction=r"Total realized USD volume across direct and indirect route units on day $t$.",
        source="data/empirical/route_denominator_daily.parquet",
        used_for="Daily market-size control and summary statistics.",
        include_in_summary=True,
        summary_panel="Daily route activity",
        summary_label="Total route volume ($bn)",
        summary_scale=1.0 / 1_000_000_000.0,
        summary_level="day",
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="Indirect-route volume",
        column="daily_indirect_route_volume_usd",
        notation=r"$\mathrm{IndirectRouteVolume}_{t}$",
        formula=r"$B_t$",
        unit="USD",
        construction=r"$B_t$ is total realized USD volume across indirect route units on day $t$.",
        source="data/empirical/route_denominator_daily.parquet",
        used_for="VehicleShare denominator and scope.",
        include_in_summary=True,
        summary_panel="Daily route activity",
        summary_label="Indirect route volume ($bn)",
        summary_scale=1.0 / 1_000_000_000.0,
        summary_level="day",
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="Indirect-route share",
        column="indirect_route_share",
        notation=r"$\mathrm{IndirectRouteShare}_{t}$",
        formula=r"$\displaystyle\frac{B_t}{A_t}$",
        unit="Fraction (0--1)",
        construction=r"$B_t$ is indirect-route USD volume and $A_t$ is all-route USD volume on day $t$.",
        source="data/empirical/route_denominator_daily.parquet",
        used_for="Overall importance of routed exchange.",
        include_in_summary=True,
        summary_panel="Daily route activity",
        summary_label="Indirect route share (%)",
        summary_scale=100.0,
        summary_level="day",
    ),
    VariableSpec(
        group="Liquidity measures",
        name="Vehicle-linked liquidity",
        column="vehicle_linked_liquidity_usd",
        notation=r"$\mathrm{VehicleLiquidity}_{k,t}$",
        formula=r"$L_{k,t}=\displaystyle\sum_{p\in\mathcal L_{k,t}}\mathrm{TVL}_{p,t}$",
        unit="USD",
        construction=(
            r"$\mathcal L_{k,t}$ is the set of eligible Uniswap V3 pools linked to $k$; "
            r"$p$ indexes pools after filtering subgraph TVL outliers."
        ),
        source="data/exhibits/lp_concentration.parquet",
        used_for="Liquidity concentration, persistence, and stickiness tests.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Vehicle-linked LP liquidity ($bn)",
        summary_scale=1.0 / 1_000_000_000.0,
    ),
    VariableSpec(
        group="Liquidity measures",
        name="LP concentration",
        column="lp_concentration",
        notation=r"$\mathrm{LPConc}_{k,t}$",
        formula=r"$\displaystyle\frac{L_{k,t}}{\sum_{\ell\in\mathcal K}L_{\ell,t}}$",
        unit="Fraction (0--1)",
        construction=(
            r"$\mathcal K$ is the candidate-vehicle set; $L_{k,t}$ is vehicle-linked "
            r"liquidity for $k$ on day $t$."
        ),
        source="data/exhibits/lp_concentration.parquet",
        used_for="Liquidity persistence and predictability regressions.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="LP concentration (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Liquidity measures",
        name="Log vehicle-linked liquidity",
        column="log_vehicle_linked_liquidity",
        notation=r"$\mathrm{LogVehicleLiquidity}_{k,t}$",
        formula=r"$\ln(1+L_{k,t})$",
        unit="Natural-log points",
        construction=r"Natural log of one plus $L_{k,t}$ measured in USD.",
        source="data/exhibits/lp_concentration.parquet",
        used_for="Liquidity-level regressions.",
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Direct available share",
        column="direct_available_share",
        notation=r"$\mathrm{DirectAvailable}_{k,t,q}$",
        formula=r"$\displaystyle\frac{|\mathcal D_{k,t,q}|}{|\mathcal P_{k,t,q}|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pairs in $\mathcal P_{k,t,q}$ with $D_{i,j,q,t}=1$. "
            r"The un-suffixed data column fixes $q=\$10{,}000$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Direct-market completeness and architecture tests.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Direct route available (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Vehicle-route available share",
        column="vehicle_available_share",
        notation=r"$\mathrm{VehicleAvailable}_{k,t,q}$",
        formula=r"$\displaystyle\frac{|\mathcal V_{k,t,q}|}{|\mathcal P_{k,t,q}|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pairs in $\mathcal P_{k,t,q}$ with $V_{i,j,k,q,t}=1$, so both "
            r"legs through $k$ are executable."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Vehicle-route feasibility.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Vehicle route available (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="No-direct but vehicle available",
        column="no_direct_vehicle_available_share",
        notation=r"$\mathrm{NoDirectVehicleAvailable}_{k,t,q}$",
        formula=(
            r"$\displaystyle\frac{|\mathcal V_{k,t,q}\setminus\mathcal D_{k,t,q}|}"
            r"{|\mathcal P_{k,t,q}|}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pairs with $D_{i,j,q,t}=0$ and $V_{i,j,k,q,t}=1$: no executable "
            r"direct route but an executable route through $k$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Availability and thin-direct-market protection.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="No-direct vehicle route (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Direct depth",
        column="direct_depth_median",
        notation=r"$\mathrm{DirectDepth}_{k,t,q}$",
        formula=r"$\displaystyle\mathrm{median}_{\mathcal D_{k,t,q}}\left(O^D_{i,j,q,t}/q\right)$",
        unit="Output USD per input USD",
        construction=(
            r"Median direct-route output ratio $O^D_{i,j,q,t}/q$ over executable-direct "
            r"pairs $(i,j)\in\mathcal D_{k,t,q}$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Direct-market quality and thin-direct-market tests.",
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Route-cost advantage",
        column="route_cost_advantage_median_bps",
        notation=r"$\mathrm{RouteCostAdvantage}_{k,t,q}$",
        formula=r"$\displaystyle\mathrm{median}_{\mathcal C_{k,t,q}}\Delta C_{i,j,k,q,t}$",
        unit="Basis points",
        construction=(
            r"Median $\Delta C_{i,j,k,q,t}$ over common-support pairs "
            r"$(i,j)\in\mathcal C_{k,t,q}$; positive values favor the route through $k$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Common-support execution-cost tests.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Vehicle advantage (bp)",
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Vehicle beats direct",
        column="vehicle_beats_direct_share",
        notation=r"$\mathrm{VehicleBeatsDirect}_{k,t,q}$",
        formula=r"$\displaystyle\frac{|\mathcal W_{k,t,q}|}{|\mathcal C_{k,t,q}|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of $(i,j)\in\mathcal C_{k,t,q}$ for which "
            r"$\Delta C_{i,j,k,q,t}>0$, equivalently $O^V_{i,j,k,q,t}>O^D_{i,j,q,t}$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Execution-cost heterogeneity.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Vehicle beats direct route (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Thin-direct share",
        column="thin_direct_share",
        notation=r"$\mathrm{ThinDirectShare}_{k,t,q}$",
        formula=r"$\displaystyle\frac{|\mathcal T_{k,t,q}|}{|\mathcal P_{k,t,q}|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pairs with $D_{i,j,q,t}=1$ and $O^D_{i,j,q,t}/q<0.9$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Thin-direct protection.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Thin direct route share (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Stress and dynamic variables",
        name="Downside WETH stress",
        column="stress_downside",
        notation=r"$\mathrm{Stress}_{t}$",
        formula=r"$\max\{-R^{\mathrm{WETH}}_t,0\}$",
        unit="Daily log-return fraction",
        construction=r"$R^{\mathrm{WETH}}_t$ is the day-$t$ WETH log return; only downside moves enter.",
        source="data/empirical/bridge_daily.parquet",
        used_for="Stress-rotation tests and controls.",
        include_in_summary=True,
        summary_panel="Daily route activity",
        summary_label="Downside WETH stress (%)",
        summary_scale=100.0,
        summary_level="day",
    ),
    VariableSpec(
        group="Stress and dynamic variables",
        name="Eight percent stress event",
        column="stress_event_8pct",
        notation=r"$\mathrm{StressEvent}_{t}$",
        formula=r"$\mathbf 1\{\mathrm{Stress}_{t}\ge 0.08\}$",
        unit="Indicator (0/1)",
        construction=r"Equals one when $\mathrm{Stress}_t$ is at least $0.08$ on day $t$.",
        source="constructed from WETH price in bridge_daily",
        used_for="Main daily stress-event design.",
    ),
    VariableSpec(
        group="Stress and dynamic variables",
        name="Future vehicle share, seven days",
        column="future_bridge_share_t7",
        notation=r"$\mathrm{FutureVehicleShare}^{(7)}_{k,t}$",
        formula=r"$\mathrm{VehicleShare}_{k,t+7}$",
        unit="Fraction (0--1)",
        construction=r"Vehicle share for token $k$ seven calendar days after day $t$.",
        source="constructed from observations table",
        used_for="Dynamic predictability regressions.",
    ),
    VariableSpec(
        group="Stress and dynamic variables",
        name="Change in vehicle share, seven days",
        column="delta_bridge_share_t7",
        notation=r"$\Delta_{7}\mathrm{VehicleShare}_{k,t}$",
        formula=r"$\mathrm{VehicleShare}_{k,t+7}-\mathrm{VehicleShare}_{k,t}$",
        unit="Fraction points",
        construction=r"Seven-day forward change for vehicle $k$, measured from day $t$.",
        source="constructed from observations table",
        used_for="Persistence and displacement tests.",
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="Settlement transfer incidence",
        column="settlement_transfer_incidence",
        notation=r"$\mathrm{TransferIncidence}_{k,w}$",
        formula=(
            r"$\displaystyle\frac{|\mathcal R^{\mathrm{transfer}}_{k,w}|}"
            r"{|\mathcal R_{k,w}|}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of receipt-audited route units $r\in\mathcal R_{k,w}$ containing "
            r"an ERC-20 $\mathrm{Transfer}$ log for intermediate vehicle $k$."
        ),
        source="data/empirical/v4_settlement_transfer_detail.parquet",
        used_for="V4 settlement virtualization and netting tests.",
        include_in_summary=True,
        summary_panel="Settlement-transfer sample",
        summary_label="Intermediary transfer incidence (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="Settlement receipt count",
        column="settlement_receipt_count",
        notation=r"$\mathrm{ReceiptCount}_{k,w}$",
        formula=r"$|\mathcal R_{k,w}|$",
        unit="Route-unit count",
        construction=r"Number of receipt-audited matched route units for vehicle $k$ in UTC week $w$.",
        source="data/empirical/v4_settlement_transfer_detail.parquet",
        used_for="Settlement-sample size and weights.",
        include_in_summary=True,
        summary_panel="Settlement-transfer sample",
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

"""Canonical variable registry for paper-facing DVC analysis panels.

The registry is the single source for variable notation, calculation language,
and the columns expected in the wide observations table. Table renderers and
processing scripts should import this file rather than duplicating definitions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VariableSpec:
    """A paper variable and its implementation in the observations table.

    Formula contains a calculation only; primitive measured quantities leave it blank.
    """

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

    group: str
    notation: str
    unit: str
    definition: str


NOTATION_DEFINITIONS: tuple[NotationDefinition, ...] = (
    NotationDefinition(
        group="Indices",
        notation=r"$i,\ j$",
        unit="Token",
        definition=r"Input (sold) and output (bought) endpoint tokens; the ordered pair is $i\to j$.",
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$k$",
        unit="Token",
        definition=r"Candidate vehicle token used as the route intermediate; $k\notin\{i,j\}$.",
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$\ell,\ p$",
        unit="Token / pool",
        definition=r"$\ell$ indexes tokens in cross-token sums; $p$ indexes liquidity pools.",
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$t,\ w$",
        unit="UTC day / UTC week",
        definition=r"$t$ indexes calendar days; $w$ indexes calendar weeks in settlement variables.",
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$q$",
        unit="USD",
        definition=r"Input quote notional. Un-suffixed route-cost columns use $q=\$10{,}000$.",
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$r$",
        unit="Route unit",
        definition=(
            r"Reconstructed source-to-sink route unit. A coherent $i\to k\to j$ component "
            r"contributes one $r$ regardless of its number of legs; a split or join contributes "
            r"one $r$ per reconstructed source-sink pair."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$\mathrm{Vol}_t,\ \mathrm{DVol}_t$",
        unit="USD",
        definition=(
            r"$\mathrm{Vol}_t$ is total realized USD volume across all direct and indirect route units "
            r"on day $t$. $\mathrm{DVol}_t$ restricts it to direct routes, so "
            r"$0\le\mathrm{DVol}_t\le\mathrm{Vol}_t$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$\mathrm{IVol}_t,\ \mathrm{IVol}_{k,t}$",
        unit="USD",
        definition=(
            r"$\mathrm{IVol}_t$ restricts $\mathrm{Vol}_t$ to indirect routes, so "
            r"$0\le\mathrm{IVol}_t\le\mathrm{Vol}_t$. $\mathrm{IVol}_{k,t}$ further restricts "
            r"that volume to routes using vehicle $k$, so "
            r"$0\le\mathrm{IVol}_{k,t}\le\mathrm{IVol}_t$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=(
            r"$N_t,\ N^{\mathrm{src}}_{k,t},\ "
            r"N^{\mathrm{sink}}_{k,t}$"
        ),
        unit="Route-unit count",
        definition=(
            r"$N_t$ counts all reconstructed route units $r$ on day $t$, not their individual legs. "
            r"$N^{\mathrm{src}}_{k,t}$ and $N^{\mathrm{sink}}_{k,t}$ restrict that count "
            r"to source and sink roles for $k$; each lies between $0$ and "
            r"$N_t$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$N^I_t,\ N^I_{k,t}$",
        unit="Route-unit count",
        definition=(
            r"$N^I_t$ restricts $N_t$ to route units with at least one intermediate token. "
            r"$N^I_{k,t}$ further restricts that count to units with intermediate $k$, so "
            r"$0\le N^I_{k,t}\le N^I_t\le N_t$; "
            r"superscript $I$ denotes indirect routes."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$\mathcal A_t,\ \mathcal A^k_t,\ \mathcal M^k_t$",
        unit="Sets of token pairs",
        definition=(
            r"$\mathcal A_t$ is the set of endpoint pairs active in indirect routes on day "
            r"$t$. $\mathcal A^k_t$ restricts it to pairs using $k$, and $\mathcal M^k_t$ "
            r"further restricts it to pairs for which $k$ has the largest candidate-vehicle "
            r"volume; $\mathcal M^k_t\subseteq\mathcal A^k_t\subseteq\mathcal A_t$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$\mathrm{Vol}^{\mathrm{in}}_{k,t},\ \mathrm{Vol}^{\mathrm{out}}_{k,t}$",
        unit="USD",
        definition=(
            r"$\mathrm{Vol}^{\mathrm{in}}_{k,t}$ and "
            r"$\mathrm{Vol}^{\mathrm{out}}_{k,t}$ are inbound and outbound route-leg "
            r"volumes assigned to token $k$ on day $t$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=(
            r"$\mathrm{Vol}^{\mathrm{src}}_{k,t},\ "
            r"\mathrm{Vol}^{\mathrm{sink}}_{k,t}$"
        ),
        unit="USD",
        definition=(
            r"Source- and sink-role restrictions of $\mathrm{Vol}_t$ for token $k$: "
            r"$0\le\mathrm{Vol}^{\mathrm{src}}_{k,t}\le\mathrm{Vol}_t$ and "
            r"$0\le\mathrm{Vol}^{\mathrm{sink}}_{k,t}\le\mathrm{Vol}_t$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$\mathcal K$",
        unit="Set of tokens",
        definition=(
            r"Prespecified candidate set $\{\mathrm{WETH},\mathrm{USDC},\mathrm{USDT},"
            r"\mathrm{DAI},\mathrm{WBTC}\}$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$\mathcal L_{k,t},\ m_p$",
        unit="Set of pools / token count",
        definition=(
            r"$\mathcal L_{k,t}$ contains Uniswap V3 daily-snapshot pools with candidate $k$ "
            r"on one side, exact token contracts identified in the persisted V3 swap archive, "
            r"and $0<\mathrm{TVL}_{p,t}\le 10$ billion USD. $m_p$ is the number of pool tokens "
            r"in $\mathcal K$, so $m_p\in\{1,2\}$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$\mathrm{TVL}_{p,t},\ L_{k,t}$",
        unit="USD",
        definition=(
            r"$\mathrm{TVL}_{p,t}$ is pool $p$'s day-$t$ USD TVL from the V3 daily snapshot. "
            r"$L_{k,t}=\sum_{p\in\mathcal L_{k,t}}\mathrm{TVL}_{p,t}/m_p$; a one-candidate "
            r"pool contributes all TVL to that candidate and a two-candidate pool contributes "
            r"one half to each."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$R^{\mathrm{WETH}}_t$",
        unit="Daily log-return fraction",
        definition=r"Day-$t$ log return of the WETH price used to construct downside stress.",
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$\mathcal{P}_{k,t,q}$",
        unit="Set of token pairs",
        definition=r"Ordered endpoint pairs eligible for $k$ and quoted on day $t$ at notional $q$.",
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=(
            r"$\mathcal{D}_{k,t,q},\ \mathcal{I}_{k,t,q},\ \mathcal{C}_{k,t,q},\ "
            r"\mathcal{T}_{k,t,q},\ \mathcal{W}_{k,t,q}$"
        ),
        unit="Sets of token pairs",
        definition=(
            r"$\mathcal D_{k,t,q}\subseteq\mathcal P_{k,t,q}$ and "
            r"$\mathcal I_{k,t,q}\subseteq\mathcal P_{k,t,q}$ restrict the broad pair set "
            r"to pairs with a direct route or a route via $k$. "
            r"$\mathcal C_{k,t,q}=\mathcal D_{k,t,q}\cap\mathcal I_{k,t,q}$, "
            r"$\mathcal T_{k,t,q}\subseteq\mathcal D_{k,t,q}$ is the thin-direct subset, and "
            r"$\mathcal W_{k,t,q}\subseteq\mathcal C_{k,t,q}$ has an indirect-route cost advantage."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$D_{i,j,q,t},\ I_{i,j,k,q,t},\ T_{i,j,q,t}$",
        unit="Indicator (0/1)",
        definition=(
            r"Indicators for direct-route availability ($D$), indirect-route-through-$k$ availability ($I$), "
            r"and an executable direct route returning less than $0.9q$ ($T$)."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$O^{D}_{i,j,q,t},\ O^{I}_{i,j,k,q,t}$",
        unit="USD",
        definition=r"Quoted output values; superscripts $D$ and $I$ denote direct and indirect routes.",
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$\Delta C_{i,j,k,q,t}$",
        unit="Basis points",
        definition=(
            r"$10{,}000\,(O^{I}_{i,j,k,q,t}-O^{D}_{i,j,q,t})/O^{D}_{i,j,q,t}$ on "
            r"$\mathcal C_{k,t,q}$."
        ),
    ),
    NotationDefinition(
        group="Settlement objects and operators",
        notation=r"$\mathcal{R}_{k,w}$",
        unit="Set of route units",
        definition=r"Receipt-audited matched route units using vehicle $k$ in UTC week $w$.",
    ),
    NotationDefinition(
        group="Settlement objects and operators",
        notation=r"$\mathcal{R}^{\mathrm{transfer}}_{k,w}$",
        unit="Set of route units",
        definition=(
            r"Members whose receipt logs a transfer of vehicle $k$; "
            r"$\mathcal R^{\mathrm{transfer}}_{k,w}\subseteq\mathcal R_{k,w}$."
        ),
    ),
    NotationDefinition(
        group="Settlement objects and operators",
        notation=r"$|\mathcal{S}|,\ \mathbf{1}_{\{\cdot\}}$",
        unit="Count / indicator (0/1)",
        definition=(
            r"Cardinality of any finite set $\mathcal S$ and an indicator equal to one when its "
            r"subscripted condition is true."
        ),
    ),
    NotationDefinition(
        group="Settlement objects and operators",
        notation=r"$\Delta_{7}$",
        unit="7 days",
        definition=(
            r"Seven-day forward change in any daily variable $X_t$: "
            r"$\Delta_7 X_t=X_{t+7}-X_t$."
        ),
    ),
)


VARIABLE_SPECS: tuple[VariableSpec, ...] = (
    VariableSpec(
        group="Vehicle-use measures",
        name="Vehicle share",
        column="bridge_share",
        notation=r"$\mathrm{VehicleShare}_{k,t}$",
        formula=r"$\displaystyle\frac{\mathrm{IVol}_{k,t}}{\mathrm{IVol}_t}$",
        unit="Fraction (0--1)",
        construction=r"Fraction of day-$t$ indirect-route USD volume routed through $k$.",
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
        formula=r"$\displaystyle\frac{\mathrm{IVol}_{k,t}}{\mathrm{Vol}_t}$",
        unit="Fraction (0--1)",
        construction=r"Fraction of day-$t$ all-route USD volume routed indirectly through $k$.",
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
        formula=r"$\displaystyle\frac{N^{I}_{k,t}}{N^{I}_{t}}$",
        unit="Fraction (0--1)",
        construction=r"Fraction of day-$t$ indirect route units that use $k$.",
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
        construction=r"Fraction of active indirect-route endpoint pairs that use $k$.",
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
            r"Fraction of active indirect-route endpoint pairs for which $k$ has the largest "
            r"candidate-vehicle volume."
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
        notation=r"$\mathrm{IVol}_{k,t}$",
        formula="",
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
        column="vol_share",
        notation=r"$\mathrm{VolShare}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{Vol}^{\mathrm{in}}_{k,t}+\mathrm{Vol}^{\mathrm{out}}_{k,t}}"
            r"{\sum_{\ell}(\mathrm{Vol}^{\mathrm{in}}_{\ell,t}+\mathrm{Vol}^{\mathrm{out}}_{\ell,t})}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"$\mathrm{Vol}^{\mathrm{in}}_{k,t}$ and $\mathrm{Vol}^{\mathrm{out}}_{k,t}$ "
            r"are inbound and outbound route-leg USD volumes for $k$; $\ell$ indexes every "
            r"token in the day-$t$ network."
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
            r"$\displaystyle\frac{N^{I}_{k,t}}"
            r"{N_t-N^{\mathrm{src}}_{k,t}-N^{\mathrm{sink}}_{k,t}}$"
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
            r"$\displaystyle\frac{\mathrm{IVol}_{k,t}}"
            r"{\mathrm{Vol}_t-\mathrm{Vol}^{\mathrm{src}}_{k,t}"
            r"-\mathrm{Vol}^{\mathrm{sink}}_{k,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"USD-volume analogue of $\mathrm{Betweenness}_{k,t}$ using the same route "
            r"universe and source/sink exclusions."
        ),
        source="data/metrics/<date>.parquet",
        used_for="Network-theoretic robustness.",
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="All-route volume",
        column="daily_all_route_volume_usd",
        notation=r"$\mathrm{Vol}_t$",
        formula=r"$\mathrm{DVol}_t+\mathrm{IVol}_t$",
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
        notation=r"$\mathrm{IVol}_t$",
        formula="",
        unit="USD",
        construction=r"Total realized USD volume across indirect route units on day $t$.",
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
        formula=r"$\displaystyle\frac{\mathrm{IVol}_t}{\mathrm{Vol}_t}$",
        unit="Fraction (0--1)",
        construction=r"Fraction of day-$t$ all-route USD volume executed through indirect routes.",
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
        notation=r"$L_{k,t}$",
        formula=r"$\displaystyle\sum_{p\in\mathcal L_{k,t}}\frac{\mathrm{TVL}_{p,t}}{m_p}$",
        unit="USD",
        construction=(
            r"Candidate $k$'s allocated share of valid Uniswap V3 pool TVL: full TVL when $k$ "
            r"is the pool's only candidate token and one half when both pool tokens are candidates."
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
        construction=r"Candidate $k$'s share of total vehicle-linked liquidity on day $t$.",
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
        name="Indirect-route available share",
        column="vehicle_available_share",
        notation=r"$\mathrm{IndirectAvailable}_{k,t,q}$",
        formula=r"$\displaystyle\frac{|\mathcal I_{k,t,q}|}{|\mathcal P_{k,t,q}|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pairs in $\mathcal P_{k,t,q}$ with $I_{i,j,k,q,t}=1$, so both "
            r"legs through $k$ are executable."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Indirect-route feasibility.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Indirect route available (%)",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Indirect-only available share",
        column="no_direct_vehicle_available_share",
        notation=r"$\mathrm{IndirectOnlyAvailable}_{k,t,q}$",
        formula=(
            r"$\displaystyle\frac{|\mathcal I_{k,t,q}\setminus\mathcal D_{k,t,q}|}"
            r"{|\mathcal P_{k,t,q}|}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pairs with $D_{i,j,q,t}=0$ and $I_{i,j,k,q,t}=1$: no executable "
            r"direct route but an executable route through $k$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Availability and thin-direct-market protection.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Indirect-only route available (%)",
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
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Direct depth (% of input)",
        summary_scale=100.0,
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
        summary_label="Indirect-route advantage (bp)",
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Indirect route beats direct",
        column="vehicle_beats_direct_share",
        notation=r"$\mathrm{IndirectBeatsDirect}_{k,t,q}$",
        formula=r"$\displaystyle\frac{|\mathcal W_{k,t,q}|}{|\mathcal C_{k,t,q}|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of $(i,j)\in\mathcal C_{k,t,q}$ for which "
            r"$\Delta C_{i,j,k,q,t}>0$, equivalently $O^I_{i,j,k,q,t}>O^D_{i,j,q,t}$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Execution-cost heterogeneity.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_label="Indirect route beats direct (%)",
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
            r"Fraction of pairs with an executable direct quote but "
            r"$O^D_{i,j,q,t}/q<0.9$. This is a quote-quality proxy, not a direct measure "
            r"of pool liquidity depth."
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
        construction=r"Positive part of the negative day-$t$ WETH log return.",
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
        formula=r"$\mathbf{1}_{\{\mathrm{Stress}_{t}\ge 0.08\}}$",
        unit="Indicator (0/1)",
        construction=r"Equals one when $\mathrm{Stress}_t$ is at least $0.08$ on day $t$.",
        source="constructed from WETH price in bridge_daily",
        used_for="Main daily stress-event design.",
    ),
    VariableSpec(
        group="Stress and dynamic variables",
        name="Future vehicle share, seven days",
        column="future_bridge_share_t7",
        notation=r"$\mathrm{VehicleShare}_{k,t+7}$",
        formula="",
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

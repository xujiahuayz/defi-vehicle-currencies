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
    summary_unit: str | None = None
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
        notation=r"$i,\ o$",
        unit="Token",
        definition=(
            r"Input (sold) and output (bought) endpoint tokens, respectively; "
            r"$(i,o)$ is an ordered input--output pair and the direct route is $i\to o$."
        ),
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$k$",
        unit="Token",
        definition=r"Candidate vehicle token used as the route intermediate; $k\notin\{i,o\}$.",
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$h$",
        unit="Token",
        definition=(
            r"Candidate vehicle token used as a challenger to incumbent $k$; "
            r"$h\in\mathcal K\setminus\{i,o,k\}$."
        ),
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$\ell,\ p,\ p'$",
        unit="Token / pool",
        definition=(
            r"$\ell$ indexes tokens in cross-token sums; $p$ indexes a focal liquidity pool; "
            r"$p'$ indexes another pool in leave-one-out sums."
        ),
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$t,\ u,\ w$",
        unit="UTC day / UTC week",
        definition=(
            r"$t$ indexes a focal calendar day; $u$ indexes another calendar day in a "
            r"time-window sum; $w$ indexes calendar weeks in settlement variables."
        ),
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$\tau$",
        unit="Days",
        definition=(
            r"Positive calendar-day horizon selected ex ante for each dynamic specification."
        ),
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$d,\ \mu$",
        unit="Calendar days / calendar months",
        definition=(
            r"$d$ is calendar-day event time relative to a candidate-specific shock; "
            r"$\mu$ is calendar-month event time relative to an architecture activation date. "
            r"Event time zero contains the event or activation date."
        ),
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$g$",
        unit="Settlement comparison cell",
        definition=(
            r"Settlement comparison cell defined by ordered pair $(i,o)$, vehicle $k$, "
            r"UTC week $w$, and a prespecified route-size bin."
        ),
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
            r"Reconstructed input-to-output route unit. A coherent $i\to k\to o$ component "
            r"contributes one $r$ regardless of its number of legs; a split or join contributes "
            r"one $r$ per reconstructed input--output pair."
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
            r"$\mathrm{Vol}_{i,o,t},\ \mathrm{IVol}_{i,o,t},\ "
            r"\mathrm{IVol}_{i,o,k,t}$"
        ),
        unit="USD",
        definition=(
            r"$\mathrm{Vol}_{i,o,t}$ is realized route-unit volume for ordered pair $(i,o)$ "
            r"on day $t$. $\mathrm{IVol}_{i,o,t}$ restricts it to indirect routes, and "
            r"$\mathrm{IVol}_{i,o,k,t}$ further restricts it to routes through $k$, so "
            r"$0\le\mathrm{IVol}_{i,o,k,t}\le\mathrm{IVol}_{i,o,t}"
            r"\le\mathrm{Vol}_{i,o,t}$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=(
            r"$N_t,\ N^{\mathrm{in}}_{k,t},\ "
            r"N^{\mathrm{out}}_{k,t}$"
        ),
        unit="Route-unit count",
        definition=(
            r"$N_t$ counts all reconstructed route units $r$ on day $t$, not their individual legs. "
            r"$N^{\mathrm{in}}_{k,t}$ and $N^{\mathrm{out}}_{k,t}$ restrict that count "
            r"to routes with $k$ as the input or output endpoint, respectively; each lies between $0$ and "
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
        notation=(
            r"$\mathrm{LegVol}^{\mathrm{in}}_{k,t},\ "
            r"\mathrm{LegVol}^{\mathrm{out}}_{k,t}$"
        ),
        unit="USD",
        definition=(
            r"$\mathrm{LegVol}^{\mathrm{in}}_{k,t}$ and "
            r"$\mathrm{LegVol}^{\mathrm{out}}_{k,t}$ are route-leg USD volumes for "
            r"which $k$ is the leg's input or output token, respectively, on day $t$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=(
            r"$\mathrm{Vol}^{\mathrm{in}}_{k,t},\ "
            r"\mathrm{Vol}^{\mathrm{out}}_{k,t}$"
        ),
        unit="USD",
        definition=(
            r"Input- and output-endpoint restrictions of $\mathrm{Vol}_t$ for token $k$: "
            r"$0\le\mathrm{Vol}^{\mathrm{in}}_{k,t}\le\mathrm{Vol}_t$ and "
            r"$0\le\mathrm{Vol}^{\mathrm{out}}_{k,t}\le\mathrm{Vol}_t$."
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
        notation=r"$\mathcal L_t,\ \mathcal L_{k,t},\ m_p$",
        unit="Set of pools / token count",
        definition=(
            r"$\mathcal L_t$ contains valid Uniswap V3 daily-snapshot pools with exact token "
            r"contracts identified in the persisted V3 swap archive and "
            r"$0<\mathrm{TVL}_{p,t}\le 10$ billion USD. "
            r"$\mathcal L_{k,t}\subseteq\mathcal L_t$ restricts that set to pools with "
            r"candidate $k$ on one side. $m_p$ is the number of pool tokens in $\mathcal K$, "
            r"so $m_p\in\{1,2\}$."
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
        group="Candidate-shock objects",
        notation=r"$P_{k,t}$",
        unit="USD per token",
        definition=r"Day-$t$ USD price of candidate token $k$.",
    ),
    NotationDefinition(
        group="Candidate-shock objects",
        notation=r"$R_{k,t}$",
        unit="Daily log-return fraction",
        definition=r"Candidate return $R_{k,t}=\ln(P_{k,t}/P_{k,t-1})$.",
    ),
    NotationDefinition(
        group="Candidate-shock objects",
        notation=r"$\sigma^{(30)}_{k,t-1}$",
        unit="Daily log-return standard deviation",
        definition=(
            r"Sample standard deviation of $R_{k,u}$ over the 30 calendar days ending at "
            r"$t-1$, requiring at least 20 valid daily returns."
        ),
    ),
    NotationDefinition(
        group="Persistence and displacement objects",
        notation=r"$k^\star_{i,o,t},\ h^\star_{i,o,q,t}$",
        unit="Token",
        definition=(
            r"$k^\star_{i,o,t}$ is the incumbent vehicle with the largest mean "
            r"$\mathrm{VehicleShare}_{i,o,k,u}$ over the 30 calendar days ending at $t-1$. "
            r"$h^\star_{i,o,q,t}$ is the executable nonincumbent candidate with the largest "
            r"$O^I_{i,o,h,q,t}$ on day $t$."
        ),
    ),
    NotationDefinition(
        group="Architecture objects",
        notation=(
            r"$t^{\mathrm{V3}}_0,\ \mathcal T^{\mathrm{V3}}_{\mathrm{pre}},\ "
            r"\mathcal P^{\mathrm{V3}}_q$"
        ),
        unit="UTC day / set of UTC days / set of token pairs",
        definition=(
            r"$t^{\mathrm{V3}}_0$ is the Uniswap V3 activation date, 5 May 2021. "
            r"$\mathcal T^{\mathrm{V3}}_{\mathrm{pre}}$ is the fixed 180-calendar-day window "
            r"ending at $t^{\mathrm{V3}}_0-1$. $\mathcal P^{\mathrm{V3}}_q$ is the fixed "
            r"architecture-analysis universe of ordered pairs with positive realized route "
            r"volume on at least 30 days in that pre-period; every member is quoted at $q$ "
            r"throughout the event window, independent of post-V3 activity."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$\mathcal{P}_{k,t,q}$",
        unit="Set of token pairs",
        definition=(
            r"Quote-universe pairs for candidate $k$: distinct ordered input--output pairs "
            r"among day $t$'s 200 largest clean reconstructed pairs by realized USD volume, "
            r"where clean means route class \texttt{single} or \texttt{coherent}, "
            r"$k\notin\{i,o\}$, and each of $i$, $o$, and $k$ has a valid day-price "
            r"estimate. A valid estimate requires at least three finite token-side "
            r"USD-per-token observations in $(0,\$1{,}000{,}000)$ and equals their "
            r"realized-USD-volume-weighted median. Each pair is submitted to the direct "
            r"and via-$k$ quote engines at input $q$; membership does not require either "
            r"quote to execute."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$\mathcal{D}_{k,t,q},\ \mathcal{I}_{k,t,q}$",
        unit="Sets of token pairs",
        definition=(
            r"$\mathcal D_{k,t,q}\subseteq\mathcal P_{k,t,q}$ and "
            r"$\mathcal I_{k,t,q}\subseteq\mathcal P_{k,t,q}$ restrict the broad pair set "
            r"to pairs with an executable direct route or an executable indirect route via $k$."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$\mathcal{C}_{k,t,q}$",
        unit="Set of token pairs",
        definition=(
            r"Common-support pairs for candidate $k$, day $t$, and notional $q$: "
            r"$\mathcal C_{k,t,q}=\mathcal D_{k,t,q}\cap\mathcal I_{k,t,q}$, so both the "
            r"direct and indirect routes are executable."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$\mathcal{T}_{k,t,q},\ \mathcal{W}_{k,t,q}$",
        unit="Sets of token pairs",
        definition=(
            r"$\mathcal T_{k,t,q}\subseteq\mathcal D_{k,t,q}$ is the thin-direct subset. "
            r"$\mathcal W_{k,t,q}\subseteq\mathcal C_{k,t,q}$ contains common-support pairs "
            r"for which the indirect route beats the direct route, equivalently "
            r"$\Delta C^D_{i,o,k,q,t}<0$."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$D_{i,o,q,t},\ I_{i,o,k,q,t},\ T_{i,o,q,t}$",
        unit="Indicator (0/1)",
        definition=(
            r"Indicators for direct-route availability ($D$), indirect-route-through-$k$ availability ($I$), "
            r"and an executable direct route returning less than $0.9q$ ($T$)."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$O^{D}_{i,o,q,t},\ O^{I}_{i,o,k,q,t}$",
        unit="USD",
        definition=r"Quoted output values; superscripts $D$ and $I$ denote direct and indirect routes.",
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$\Delta C^D_{i,o,k,q,t}$",
        unit="Fraction",
        definition=(
            r"Pair-level direct cost advantage "
            r"$(O^{D}_{i,o,q,t}-O^{I}_{i,o,k,q,t})/O^{D}_{i,o,q,t}$ on "
            r"$\mathcal C_{k,t,q}$; positive values favor the direct route."
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
        notation=r"$\mathcal R^3_g,\ \mathcal R^4_g$",
        unit="Sets of route units",
        definition=(
            r"Receipt-audited route units in settlement comparison cell $g$ executed on "
            r"Uniswap V3 and V4, respectively. A matched cell has both sets nonempty."
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
        group="Dynamic operators",
        notation=r"$\Delta_{\tau}$",
        unit="",
        definition=(
            r"Change in a daily variable over the $\tau$ days ending at $t$: "
            r"$\Delta_\tau X_t=X_t-X_{t-\tau}$."
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
        summary_unit="Percent",
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
        summary_unit="Percent",
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
        summary_unit="Percent",
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
        summary_unit="Percent",
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
        summary_unit="Percent",
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
        summary_unit="USD millions",
        summary_scale=1.0 / 1_000_000.0,
    ),
    VariableSpec(
        group="Pair-level route-choice measures",
        name="Pair-level vehicle share",
        column="actual_vehicle_share",
        notation=r"$\mathrm{VehicleShare}_{i,o,k,t}$",
        formula=r"$\displaystyle\frac{\mathrm{IVol}_{i,o,k,t}}{\mathrm{IVol}_{i,o,t}}$",
        unit="Fraction (0--1)",
        construction=(
            r"Candidate $k$'s share of realized indirect-route USD volume for ordered pair "
            r"$(i,o)$ on day $t$, defined when $\mathrm{IVol}_{i,o,t}>0$."
        ),
        source="data/empirical/pair_vehicle_actual_daily.parquet",
        used_for="RQ1 candidate selection and RQ3 persistence/displacement designs.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Pair-level route-choice measures",
        name="Pair-level indirect-route share",
        column="pair_indirect_route_share",
        notation=r"$\mathrm{IndirectRouteShare}_{i,o,t}$",
        formula=r"$\displaystyle\frac{\mathrm{IVol}_{i,o,t}}{\mathrm{Vol}_{i,o,t}}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of realized route-unit USD volume for ordered pair $(i,o)$ executed "
            r"through an indirect route on day $t$, defined when $\mathrm{Vol}_{i,o,t}>0$."
        ),
        source="to be constructed from the unified route panel before estimation",
        used_for="RQ1 vehicle reliance and RQ4 execution-architecture designs.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="Raw token volume share",
        column="vol_share",
        notation=r"$\mathrm{VolShare}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{LegVol}^{\mathrm{in}}_{k,t}+\mathrm{LegVol}^{\mathrm{out}}_{k,t}}"
            r"{\sum_{\ell}(\mathrm{LegVol}^{\mathrm{in}}_{\ell,t}+\mathrm{LegVol}^{\mathrm{out}}_{\ell,t})}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"$\mathrm{LegVol}^{\mathrm{in}}_{k,t}$ and $\mathrm{LegVol}^{\mathrm{out}}_{k,t}$ "
            r"are input-side and output-side route-leg USD volumes for $k$; $\ell$ indexes every "
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
            r"{N_t-N^{\mathrm{in}}_{k,t}-N^{\mathrm{out}}_{k,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of day-$t$ intent routes on which $k$ is intermediate, excluding routes "
            r"where $k$ is the input or output endpoint. Superscripts identify each route role."
        ),
        source="data/metrics/<date>.parquet",
        used_for="Network-theoretic vehicle proxy.",
        include_in_summary=True,
        summary_panel="Vehicle-use measures, token-day",
        summary_unit="Fraction (0--1)",
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="Volume-weighted betweenness",
        column="volume_weighted_betweenness",
        notation=r"$\mathrm{Betweenness}^{\mathrm{vol}}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{IVol}_{k,t}}"
            r"{\mathrm{Vol}_t-\mathrm{Vol}^{\mathrm{in}}_{k,t}"
            r"-\mathrm{Vol}^{\mathrm{out}}_{k,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"USD-volume analogue of $\mathrm{Betweenness}_{k,t}$ using the same route "
            r"universe and input/output-endpoint exclusions."
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
        summary_unit="USD billions",
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
        summary_unit="USD billions",
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
        summary_unit="Percent",
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
        summary_unit="USD billions",
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
        summary_unit="Percent",
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
        group="Liquidity commonality measures",
        name="Leave-one-out vehicle liquidity factor",
        column="vehicle_factor_loo",
        notation=r"$\mathrm{VehicleLiquidityFactor}_{p,k,t}$",
        formula=(
            r"$\displaystyle\frac{\sum_{p'\in\mathcal L_{k,t}\setminus\{p\}}"
            r"\Delta_1\ln(\mathrm{TVL}_{p',t})}"
            r"{|\mathcal L_{k,t}\setminus\{p\}|}$"
        ),
        unit="Daily log-change points",
        construction=(
            r"Leave-one-out mean daily log TVL change among other valid pools linked to "
            r"candidate $k$; requires at least three other pools."
        ),
        source="data/empirical/common_liquidity_pool_panel.parquet",
        used_for="RQ2 common-liquidity mechanism test.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Liquidity commonality measures",
        name="Leave-one-out market liquidity factor",
        column="market_factor_loo",
        notation=r"$\mathrm{MarketLiquidityFactor}_{p,t}$",
        formula=(
            r"$\displaystyle\frac{\sum_{p'\in\mathcal L_t\setminus\{p\}}"
            r"\Delta_1\ln(\mathrm{TVL}_{p',t})}"
            r"{|\mathcal L_t\setminus\{p\}|}$"
        ),
        unit="Daily log-change points",
        construction=(
            r"Leave-one-out mean daily log TVL change across all other valid pools in "
            r"$\mathcal L_t$; market-wide control for the vehicle factor."
        ),
        source="data/empirical/common_liquidity_pool_panel.parquet",
        used_for="RQ2 common-liquidity mechanism test.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Any indirect route available",
        column="any_indirect_available",
        notation=r"$\mathrm{AnyIndirectAvailable}_{i,o,q,t}$",
        formula=(
            r"$\mathbf{1}_{\{\sum_{k\in\mathcal K\setminus\{i,o\}}"
            r"I_{i,o,k,q,t}>0\}}$"
        ),
        unit="Indicator (0/1)",
        construction=(
            r"Equals one when at least one candidate in $\mathcal K\setminus\{i,o\}$ "
            r"provides an executable indirect route for pair $(i,o)$ at input notional $q$."
        ),
        source="to be constructed from data/empirical/route_cost_panel_v2.parquet",
        used_for="RQ1 extensive-margin vehicle reliance.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-level direct depth",
        column="pair_direct_depth",
        notation=r"$\mathrm{DirectDepth}_{i,o,q,t}$",
        formula=r"$\displaystyle\frac{O^D_{i,o,q,t}}{q}$",
        unit="Output USD per input USD",
        construction=(
            r"Direct-route output ratio for cells with $D_{i,o,q,t}=1$; undefined when "
            r"the direct route is not executable."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="RQ1 direct-route quality and RQ4 architecture outcomes.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-candidate indirect depth",
        column="pair_indirect_depth",
        notation=r"$\mathrm{IndirectDepth}_{i,o,k,q,t}$",
        formula=r"$\displaystyle\frac{O^I_{i,o,k,q,t}}{q}$",
        unit="Output USD per input USD",
        construction=(
            r"Indirect-route output ratio through candidate $k$ for "
            r"$(i,o)\in\mathcal I_{k,t,q}$; undefined when that route is not executable."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="RQ1 candidate selection and RQ2 liquidity-route mechanism tests.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Direct available share",
        column="direct_available_share",
        notation=r"$\mathrm{DirectAvailable}_{k,t,q}$",
        formula=r"$\displaystyle\frac{|\mathcal D_{k,t,q}|}{|\mathcal P_{k,t,q}|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pairs in $\mathcal P_{k,t,q}$ with $D_{i,o,q,t}=1$. "
            r"The un-suffixed data column fixes $q=\$10{,}000$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Direct-market completeness and architecture tests.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_unit="Percent",
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
            r"Fraction of pairs in $\mathcal P_{k,t,q}$ with $I_{i,o,k,q,t}=1$, so both "
            r"legs through $k$ are executable."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Indirect-route feasibility.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_unit="Percent",
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
            r"Fraction of pairs with $D_{i,o,q,t}=0$ and $I_{i,o,k,q,t}=1$: no executable "
            r"direct route but an executable route through $k$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Availability and thin-direct-market protection.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_unit="Percent",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Direct depth",
        column="direct_depth_median",
        notation=r"$\mathrm{DirectDepth}_{k,t,q}$",
        formula=r"$\displaystyle\mathrm{median}_{\mathcal D_{k,t,q}}\left(O^D_{i,o,q,t}/q\right)$",
        unit="Output USD per input USD",
        construction=(
            r"Median direct-route output ratio $O^D_{i,o,q,t}/q$ over executable-direct "
            r"pairs $(i,o)\in\mathcal D_{k,t,q}$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Direct-market quality and thin-direct-market tests.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_unit="Percent of input",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Direct cost advantage",
        column="direct_cost_advantage_median",
        notation=r"$\mathrm{DirectCostAdvantage}_{k,t,q}$",
        formula=r"$\displaystyle\mathrm{median}_{\mathcal C_{k,t,q}}\Delta C^D_{i,o,k,q,t}$",
        unit="Fraction",
        construction=(
            r"Median $\Delta C^D_{i,o,k,q,t}$ over common-support pairs "
            r"$(i,o)\in\mathcal C_{k,t,q}$; positive values favor the direct route and "
            r"negative values favor the indirect route through $k$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Common-support execution-cost tests.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_unit="Fraction",
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Indirect route beats direct",
        column="vehicle_beats_direct_share",
        notation=r"$\mathrm{IndirectBeatsDirect}_{k,t,q}$",
        formula=r"$\displaystyle\frac{|\mathcal W_{k,t,q}|}{|\mathcal C_{k,t,q}|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of $(i,o)\in\mathcal C_{k,t,q}$ for which "
            r"$\Delta C^D_{i,o,k,q,t}<0$, equivalently $O^I_{i,o,k,q,t}>O^D_{i,o,q,t}$."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Execution-cost heterogeneity.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_unit="Percent",
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
            r"$O^D_{i,o,q,t}/q<0.9$. This is a quote-quality proxy, not a direct measure "
            r"of pool liquidity depth."
        ),
        source="data/empirical/route_cost_panel_v2.parquet",
        used_for="Thin-direct protection.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_unit="Percent",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="Stress and dynamic variables",
        name="Candidate downside stress",
        column="candidate_downside_stress",
        notation=r"$\mathrm{CandidateStress}_{k,t}$",
        formula=r"$\displaystyle\max\left\{-\frac{R_{k,t}}{\sigma^{(30)}_{k,t-1}},0\right\}$",
        unit="Trailing-volatility standard deviations",
        construction=(
            r"Candidate-specific adverse return shock scaled by trailing volatility. The "
            r"measure captures crashes for volatile candidates and downward depegs for stable candidates."
        ),
        source="to be constructed from candidate-token day prices before estimation",
        used_for="RQ3 candidate-specific stress rotation and event-time designs.",
        in_observations_table=False,
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
        summary_unit="Percent",
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
        name="Change in vehicle share",
        column="delta_bridge_share_t7",
        notation=r"$\Delta_{\tau}\mathrm{VehicleShare}_{k,t}$",
        formula=r"$\mathrm{VehicleShare}_{k,t}-\mathrm{VehicleShare}_{k,t-\tau}$",
        unit="Fraction points",
        construction=(
            r"$\tau$-day change for vehicle $k$ ending on day $t$. The displayed data column "
            r"is the $\tau=7$ instance; the observations table also constructs "
            r"$\tau\in\{1,14,30\}$."
        ),
        source="constructed from observations table",
        used_for="Persistence and displacement tests.",
    ),
    VariableSpec(
        group="Persistence and displacement measures",
        name="Incumbent vehicle indicator",
        column="incumbent_vehicle",
        notation=r"$\mathrm{Incumbent}_{i,o,k,t}$",
        formula=r"$\mathbf{1}_{\{k=k^\star_{i,o,t}\}}$",
        unit="Indicator (0/1)",
        construction=(
            r"Equals one when candidate $k$ is the trailing-30-day incumbent for ordered pair "
            r"$(i,o)$; the ranking window ends at $t-1$."
        ),
        source="to be constructed from pair-level vehicle shares before estimation",
        used_for="RQ3 persistence and candidate-shock interactions.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Persistence and displacement measures",
        name="Challenger cost edge",
        column="challenger_cost_edge",
        notation=r"$\mathrm{ChallengerCostEdge}_{i,o,q,t}$",
        formula=(
            r"$\displaystyle\frac{O^I_{i,o,h^\star,q,t}-O^I_{i,o,k^\star,q,t}}"
            r"{O^I_{i,o,k^\star,q,t}}$"
        ),
        unit="Fraction",
        construction=(
            r"Quoted-output advantage of the best executable challenger over the incumbent "
            r"vehicle at input notional $q$; positive values favor the challenger."
        ),
        source="to be constructed from pair-level shares and the route-cost panel",
        used_for="RQ3 incumbent-displacement and switching-threshold designs.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Persistence and displacement measures",
        name="Vehicle switch indicator",
        column="vehicle_switch",
        notation=r"$\mathrm{VehicleSwitch}_{i,o,q,t,\tau}$",
        formula=(
            r"$\displaystyle\mathbf{1}_{\left\{\begin{array}{c}"
            r"\mathrm{VehicleShare}_{i,o,h^\star,t+\tau}\\"
            r"{}>\mathrm{VehicleShare}_{i,o,k^\star,t+\tau}"
            r"\end{array}\right\}}$"
        ),
        unit="Indicator (0/1)",
        construction=(
            r"Equals one when the day-$t$ best challenger has a larger pair-level vehicle "
            r"share than the day-$t$ incumbent at exact calendar horizon $t+\tau$."
        ),
        source="to be constructed from pair-level vehicle shares before estimation",
        used_for="RQ3 displacement probability at 7-, 30-, and 90-day horizons.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Execution-architecture measures",
        name="Pre-V3 direct-market constraint",
        column="pre_v3_direct_constraint",
        notation=r"$\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}$",
        formula=(
            r"$\displaystyle 1-\frac{\sum_{u\in\mathcal T^{\mathrm{V3}}_{\mathrm{pre}}}"
            r"D_{i,o,q,u}}{|\mathcal T^{\mathrm{V3}}_{\mathrm{pre}}|}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of the fixed 180-day pre-V3 window in which pair $(i,o)$ lacks an "
            r"executable direct route at notional $q$; higher values mean a more constrained "
            r"pre-architecture direct market."
        ),
        source="to be constructed from the route-cost panel before estimation",
        used_for="RQ4 continuous-treatment architecture event study.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Execution-architecture measures",
        name="Post-V3 indicator",
        column="post_v3",
        notation=r"$\mathrm{PostV3}_{t}$",
        formula=r"$\mathbf{1}_{\{t\ge t^{\mathrm{V3}}_0\}}$",
        unit="Indicator (0/1)",
        construction=r"Equals one on and after the Uniswap V3 activation date.",
        source="constructed from calendar date",
        used_for="RQ4 architecture difference-in-differences and event-time designs.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="Intermediate-token transfer indicator",
        column="has_matching_transfer",
        notation=r"$\mathrm{Transfer}_{r,k}$",
        formula=r"$\mathbf{1}_{\{r\in\mathcal R^{\mathrm{transfer}}_{k,w}\}}$",
        unit="Indicator (0/1)",
        construction=(
            r"Equals one when route unit $r$'s transaction receipt contains an ERC-20 "
            r"$\mathrm{Transfer}$ log matching intermediate vehicle $k$."
        ),
        source="data/empirical/v4_settlement_transfer_detail.parquet",
        used_for="RQ5 matched route-level settlement comparison.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="V4 route indicator",
        column="v4_route",
        notation=r"$\mathrm{V4}_{r}$",
        formula=r"$\mathbf{1}_{\{r\in\mathcal R^4_g\}}$",
        unit="Indicator (0/1)",
        construction=r"Equals one when matched route unit $r$ executes on Uniswap V4.",
        source="data/empirical/v4_settlement_transfer_detail.parquet",
        used_for="RQ5 settlement-architecture treatment indicator.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="V4 route share",
        column="v4_route_share",
        notation=r"$\mathrm{V4RouteShare}_{g}$",
        formula=r"$\displaystyle\frac{|\mathcal R^4_g|}{|\mathcal R^3_g|+|\mathcal R^4_g|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of receipt-audited route units in comparison cell $g$ executed on V4; "
            r"reported alongside transfer incidence to distinguish route use from token movement."
        ),
        source="to be constructed from the matched V3/V4 settlement panel",
        used_for="RQ5 economic-route-use persistence diagnostic.",
        in_observations_table=False,
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
        summary_unit="Percent",
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
        summary_unit="Route-unit count",
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

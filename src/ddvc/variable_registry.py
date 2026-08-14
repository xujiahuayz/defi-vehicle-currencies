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
        notation=r"$x$",
        unit="Token",
        definition=r"Generic token index used where a quantity applies to any endpoint or candidate token.",
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
        notation=r"$a,\ a'$",
        unit="LP address",
        definition=(
            r"$a$ indexes a focal liquidity-provider address or resolved position controller; "
            r"$a'$ indexes another provider in within-pool sums."
        ),
    ),
    NotationDefinition(
        group="Indices",
        notation=r"$b$",
        unit="Fraction",
        definition=(
            r"Symmetric price-band half-width used to measure concentrated liquidity around "
            r"the current reference price; $b=0.02$ is primary."
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
            r"$\mathcal L_t$ contains pools from protocols whose deposited-capital contract "
            r"is admitted, with exact token contracts and $0<\mathrm{Capital}_{p,t}\le 10$ billion USD. "
            r"$\mathcal L_{k,t}\subseteq\mathcal L_t$ restricts that set to pools with "
            r"candidate $k$ on one side. $m_p$ is the number of pool tokens in $\mathcal K$, "
            r"so $m_p\in\{1,2\}$."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$\mathrm{Capital}_{p,t},\ C_{k,t}$",
        unit="USD",
        definition=(
            r"$\mathrm{Capital}_{p,t}$ is pool $p$'s validated day-$t$ accounting capital under "
            r"its protocol contract. $C_{k,t}=\sum_{p\in\mathcal L_{k,t}}\mathrm{Capital}_{p,t}/m_p$; "
            r"a one-candidate pool contributes all capital to that candidate and a two-candidate pool contributes "
            r"one half to each."
        ),
    ),
    NotationDefinition(
        group="Route and liquidity aggregates",
        notation=r"$\mathrm{PoolVol}_{p,t},\ \mathrm{SpokeIVol}_{p,k,t}$",
        unit="USD",
        definition=(
            r"$\mathrm{PoolVol}_{p,t}$ is total realized swap volume in pool $p$ on day $t$. "
            r"$\mathrm{SpokeIVol}_{p,k,t}$ restricts it to pool legs belonging to reconstructed "
            r"indirect routes that use $k$ as the intermediate, so "
            r"$0\le\mathrm{SpokeIVol}_{p,k,t}\le\mathrm{PoolVol}_{p,t}$."
        ),
    ),
    NotationDefinition(
        group="LP portfolio objects",
        notation=r"$L_{a,p,t}$",
        unit="USD",
        definition=(
            r"End-of-day USD value of active liquidity supplied by provider $a$ to pool $p$, "
            r"marked at the day-$t$ reference prices."
        ),
    ),
    NotationDefinition(
        group="LP portfolio objects",
        notation=r"$w_{a,p,t}$",
        unit="Fraction (0--1)",
        definition=(
            r"Provider $a$'s share of active capital in pool $p$ on day $t$: "
            r"$w_{a,p,t}=L_{a,p,t}/\sum_{a'}L_{a',p,t}$."
        ),
    ),
    NotationDefinition(
        group="LP portfolio objects",
        notation=r"$F^{\mathrm{LP}}_{a,p,t}$",
        unit="USD per day",
        definition=(
            r"Day-$t$ liquidity deposits by $a$ into $p$ minus withdrawals, valued at "
            r"transaction-time USD prices and excluding fee collections."
        ),
    ),
    NotationDefinition(
        group="LP portfolio objects",
        notation=r"$\mathrm{Fee}_{a,p,t},\ G^{\mathrm{LP}}_{a,p,t}$",
        unit="USD",
        definition=(
            r"Swap fees accrued to provider $a$ in pool $p$ during day $t$, and USD gas "
            r"spent by $a$ on that position's mint, burn, collect, and rebalance transactions."
        ),
    ),
    NotationDefinition(
        group="LP portfolio objects",
        notation=r"$V^{\mathrm{LP}}_{a,p,t},\ V^{\mathrm{RB}}_{a,p,t}$",
        unit="USD",
        definition=(
            r"End-of-day values of the day-$t$ opening LP inventory and its self-financing "
            r"rebalanced benchmark, respectively, both excluding day-$t$ fees, flows, and gas."
        ),
    ),
    NotationDefinition(
        group="LP portfolio objects",
        notation=r"$R^{\mathrm{LP}}_{a,p,t},\ R^{\mathrm{other}}_{a,-p,t}$",
        unit="Daily return fraction",
        definition=(
            r"$R^{\mathrm{LP}}_{a,p,t}=(V^{\mathrm{LP}}_{a,p,t}-L_{a,p,t-1})/L_{a,p,t-1}$ "
            r"is the position's fee-, flow-, and gas-excluded return. "
            r"$R^{\mathrm{other}}_{a,-p,t}$ is the lag-capital-weighted mean of that return "
            r"across $a$'s pools other than $p$."
        ),
    ),
    NotationDefinition(
        group="LP portfolio objects",
        notation=r"$\omega_{a,x,-p,t}$",
        unit="Fraction (0--1)",
        definition=(
            r"Share of provider $a$'s marked LP inventory outside focal pool $p$ exposed to "
            r"token $x$, excluding both tokens in $p$ and normalized to sum to one across the "
            r"remaining tokens."
        ),
    ),
    NotationDefinition(
        group="LP portfolio objects",
        notation=r"$\mathrm{BandDepth}_{p,t,b}$",
        unit="USD",
        definition=(
            r"Average across trade directions of the input USD notional executable in pool $p$ "
            r"before its marginal price exits the symmetric $b$ band around the day-$t$ "
            r"reference price."
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
        notation=r"$P_{x,t},\ P_{k,t}$",
        unit="USD per token",
        definition=(
            r"$P_{x,t}$ is the day-$t$ USD price of any token $x$. $P_{k,t}$ restricts "
            r"that price to candidate $k\in\mathcal K$."
        ),
    ),
    NotationDefinition(
        group="Candidate-shock objects",
        notation=r"$R_{x,t},\ R_{k,t}$",
        unit="Daily log-return fraction",
        definition=(
            r"$R_{x,t}=\ln(P_{x,t}/P_{x,t-1})$ is the day-$t$ return of any token $x$. "
            r"$R_{k,t}$ restricts it to candidate $k\in\mathcal K$."
        ),
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
        group="Architecture objects",
        notation=r"$R_{i,o,t},\ \sigma^{\mathrm{pre}}_{i,o}$",
        unit="Daily log-return fraction / daily log-return standard deviation",
        definition=(
            r"$R_{i,o,t}=\ln[(P_{i,t}/P_{o,t})/(P_{i,t-1}/P_{o,t-1})]$ is the ordered "
            r"endpoint-pair return. $\sigma^{\mathrm{pre}}_{i,o}$ is its sample standard "
            r"deviation over $\mathcal T^{\mathrm{V3}}_{\mathrm{pre}}$."
        ),
    ),
    NotationDefinition(
        group="Persistence and displacement objects",
        notation=r"$k^\star_{i,o,t},\ h^\star_{i,o,q,t}$",
        unit="Token",
        definition=(
            r"$k^\star_{i,o,t}$ is the incumbent vehicle with the largest mean "
            r"$\mathrm{VehicleShare}_{i,o,k,u}$ over the 30 calendar days ending at $t-1$. "
            r"$h^\star_{i,o,q,t}$ is the executable nonincumbent candidate with the smallest "
            r"all-in indirect cost $C^I_{i,o,h,q,t}$ on day $t$."
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
        group="Architecture objects",
        notation=(
            r"$t^{\mathrm{V4}}_0,\ \mathcal T^{\mathrm{V4}}_{\mathrm{pre}},\ "
            r"\mathcal T^{\mathrm{V4}}_{i,o,\mathrm{pre}}$"
        ),
        unit="UTC day / sets of UTC days",
        definition=(
            r"$t^{\mathrm{V4}}_0$ is the Ethereum V4 activation date established from the "
            r"canonical deployment metadata before extraction. "
            r"$\mathcal T^{\mathrm{V4}}_{\mathrm{pre}}$ is the fixed 180-calendar-day window "
            r"ending at $t^{\mathrm{V4}}_0-1$. "
            r"$\mathcal T^{\mathrm{V4}}_{i,o,\mathrm{pre}}\subseteq"
            r"\mathcal T^{\mathrm{V4}}_{\mathrm{pre}}$ restricts that window to days with "
            r"$\mathrm{Vol}_{i,o,t}>0$."
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
            r"USD-per-token observations in $(0,\$1{,}000{,}000)$, at least 75 percent "
            r"of observations within a fivefold band around their ordinary median, and "
            r"equals the realized-USD-volume-weighted median inside that consensus band. "
            r"Each pair is submitted to the direct "
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
        notation=r"$O^{D,\mathrm{fee}}_{i,o,q,t},\ O^{I,\mathrm{fee}}_{i,o,k,q,t}$",
        unit="USD",
        definition=(
            r"Counterfactual direct and indirect output values when each pool remains at its "
            r"pre-quote marginal price but charges its historical swap fee; these retain fee "
            r"loss and suppress price impact."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$G^{D}_{i,o,q,t},\ G^{I}_{i,o,k,q,t}$",
        unit="USD",
        definition=(
            r"Historical gas expenditure for the quoted direct and indirect routes, "
            r"respectively, using route-specific gas usage and the day-$t$ gas-token USD price."
        ),
    ),
    NotationDefinition(
        group="Route-cost quote objects",
        notation=r"$C^{D}_{i,o,q,t},\ C^{I}_{i,o,k,q,t}$",
        unit="Fraction",
        definition=(
            r"All-in execution-cost fractions for the direct and indirect alternatives, "
            r"including quoted pool fees and price impact plus historical gas expenditure."
        ),
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
        group="Route-cost quote objects",
        notation=r"$\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$",
        unit="Fraction",
        definition=(
            r"All-in direct cost advantage $C^{I}_{i,o,k,q,t}-C^{D}_{i,o,q,t}$ on "
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
        notation=r"$M_{r,k},\ \mathrm{GrossLegVol}_{r,k}$",
        unit="USD",
        definition=(
            r"$M_{r,k}$ is the sum of absolute, route-attributed ERC-20 transfers of intermediate "
            r"$k$ between distinct nonzero addresses in route unit $r$, valued in USD. "
            r"$\mathrm{GrossLegVol}_{r,k}$ is the corresponding gross USD notional of $k$ entering "
            r"or leaving the route's pools across both vehicle legs."
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
        name="Intermediate-use share",
        column="intermediate_share",
        notation=r"$\mathrm{IShare}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{IVol}_{k,t}}"
            r"{\sum_{j:\mathrm{Type}(j)\ne\mathrm{other}}\mathrm{IVol}_{j,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Token $k$'s share of clean, non-cyclic route value carried as an "
            r"intermediary; a repeated appearance of $k$ inside one reconstructed "
            r"component is counted once. Primary shares use the prespecified currency "
            r"types and exclude the residual unclassified-contract bucket."
        ),
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Numerator of vehicle dominance and of its normalized excess-use measure.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Endpoint-demand share",
        column="endpoint_share",
        notation=r"$\mathrm{EShare}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{EVol}_{k,t}}"
            r"{\sum_{j:\mathrm{Type}(j)\ne\mathrm{other}}\mathrm{EVol}_{j,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Token $k$'s share of source-or-sink value across all clean, non-cyclic "
            r"routes, including direct routes so the benchmark does not condition "
            r"on intermediation. Primary shares use the same prespecified currency types."
        ),
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Fundamental endpoint-demand benchmark for normalized vehicle dominance.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Vehicle excess-use ratio",
        column="vehicle_excess_use_ratio",
        notation=r"$\mathrm{ExcessUse}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{IShare}_{k,t}}"
            r"{\mathrm{EShare}_{k,t}}$"
        ),
        unit="Ratio",
        construction=(
            r"Intermediate-use share divided by endpoint-demand share on the same clean, "
            r"non-cyclic route universe; undefined when endpoint demand is zero."
        ),
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for=(
            "Economic-weight dimension of vehicle dominance; values above one indicate "
            "use beyond endpoint demand on the stated value-support perimeter."
        ),
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Intermediate-use count share",
        column="intermediate_count_share",
        notation=r"$\mathrm{IShare}^{N}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{N^{I}_{k,t}}"
            r"{\sum_{j:\mathrm{Type}(j)\ne\mathrm{other}}N^{I}_{j,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Token $k$'s share of clean, non-cyclic route components in which it is an "
            r"intermediary; one component-token appearance is counted once."
        ),
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Count-weighted vehicle-dominance measure.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Endpoint-demand count share",
        column="endpoint_count_share",
        notation=r"$\mathrm{EShare}^{N}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{N^{E}_{k,t}}"
            r"{\sum_{j:\mathrm{Type}(j)\ne\mathrm{other}}N^{E}_{j,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Token $k$'s share of source-or-sink appearances across all clean, "
            r"non-cyclic route components, including direct routes."
        ),
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Count-weighted endpoint-demand benchmark.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Vehicle excess-use count ratio",
        column="vehicle_excess_use_count_ratio",
        notation=r"$\mathrm{ExcessUse}^{N}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{IShare}^{N}_{k,t}}"
            r"{\mathrm{EShare}^{N}_{k,t}}$"
        ),
        unit="Ratio",
        construction=(
            r"Count-share analogue of vehicle excess use on the same clean, non-cyclic "
            r"route universe; undefined when endpoint count is zero."
        ),
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Frequency dimension of vehicle dominance with full topology support.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Strict-support intermediate-use count share",
        column="intermediate_count_share_within_20pct",
        notation=r"$\mathrm{IShare}^{N,20}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{N^{I,20}_{k,t}}"
            r"{\sum_{j:\mathrm{Type}(j)\ne\mathrm{other}}N^{I,20}_{j,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Count share on the exact route components used by the strict-value measure: "
            r"source, sink and every intermediary reconcile within 20 percent."
        ),
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Separating value weighting from strict-support sample selection.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Strict-support endpoint-demand count share",
        column="endpoint_count_share_within_20pct",
        notation=r"$\mathrm{EShare}^{N,20}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{N^{E,20}_{k,t}}"
            r"{\sum_{j:\mathrm{Type}(j)\ne\mathrm{other}}N^{E,20}_{j,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=r"Endpoint count share on the same 20-percent value-coherence support.",
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Matched-support endpoint-demand benchmark for count-versus-value decomposition.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Strict-support vehicle excess-use count ratio",
        column="vehicle_excess_use_count_ratio_within_20pct",
        notation=r"$\mathrm{ExcessUse}^{N,20}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{IShare}^{N,20}_{k,t}}"
            r"{\mathrm{EShare}^{N,20}_{k,t}}$"
        ),
        unit="Ratio",
        construction=r"Matched-support count excess use; undefined when strict-support endpoint count is zero.",
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Matched-support frequency benchmark for the strict-value dominance measure.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Strict-value intermediate-use share",
        column="intermediate_share_within_20pct",
        notation=r"$\mathrm{IShare}^{V,20}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{IVol}^{20}_{k,t}}"
            r"{\sum_{j:\mathrm{Type}(j)\ne\mathrm{other}}\mathrm{IVol}^{20}_{j,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=r"Intermediary value share where source, sink and every intermediary reconcile within 20 percent.",
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Strict-value dimension of vehicle dominance.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Strict-value endpoint-demand share",
        column="endpoint_share_within_20pct",
        notation=r"$\mathrm{EShare}^{V,20}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{EVol}^{20}_{k,t}}"
            r"{\sum_{j:\mathrm{Type}(j)\ne\mathrm{other}}\mathrm{EVol}^{20}_{j,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=r"Endpoint value share on the same 20-percent value-coherence support.",
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Strict-value endpoint-demand benchmark.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Vehicle-use measures",
        name="Strict-value vehicle excess-use ratio",
        column="vehicle_excess_use_ratio_within_20pct",
        notation=r"$\mathrm{ExcessUse}^{V,20}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{IShare}^{V,20}_{k,t}}"
            r"{\mathrm{EShare}^{V,20}_{k,t}}$"
        ),
        unit="Ratio",
        construction=r"Strict-value intermediary share divided by strict-value endpoint share on identical support.",
        source="data/processed/vehicle_excess_use_daily.parquet",
        used_for="Economic-value dimension of vehicle dominance.",
        in_observations_table=False,
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
        used_for="Pair-level vehicle dominance and robustness.",
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
        group="Pair-level route-choice measures",
        name="Pair-level candidate vehicle coverage",
        column="pair_candidate_vehicle_coverage",
        notation=r"$\mathrm{Coverage}^{\mathcal K}_{i,o,t}$",
        formula=(
            r"$\displaystyle\sum_{k\in\mathcal K\setminus\{i,o\}}"
            r"\mathrm{VehicleShare}_{i,o,k,t}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Share of pair $(i,o)$'s realized indirect-route volume routed through a candidate "
            r"in $\mathcal K\setminus\{i,o\}$; defined when total pair indirect volume is positive."
        ),
        source="to be constructed from pair-level vehicle shares before estimation",
        used_for="RQ4 candidate-set coverage diagnostic for pair-level vehicle concentration.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Pair-level route-choice measures",
        name="Pair-level vehicle concentration",
        column="pair_vehicle_hhi",
        notation=r"$\mathrm{VehicleHHI}_{i,o,t}$",
        formula=(
            r"$\displaystyle\sum_{k\in\mathcal K\setminus\{i,o\}}\left("
            r"\frac{\mathrm{VehicleShare}_{i,o,k,t}}"
            r"{\mathrm{Coverage}^{\mathcal K}_{i,o,t}}"
            r"\right)^2$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Herfindahl concentration among candidates in $\mathcal K\setminus\{i,o\}$ for "
            r"ordered pair $(i,o)$ on day $t$, after renormalizing their shares to sum to one; "
            r"defined when candidate-routed indirect volume is positive."
        ),
        source="to be constructed from pair-level vehicle shares before estimation",
        used_for="RQ3 dominance and RQ4 decentralization-versus-entrenchment tests.",
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
        name="Intent-route intermediary incidence",
        column="betweenness_centrality",
        notation=r"$\mathrm{RouteIncidence}^{N}_{k,t}$",
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
        used_for=(
            "Historical realized-route diagnostic; this is intermediary incidence, not "
            "graph-theoretic shortest-path betweenness and not a primary dominance measure."
        ),
        include_in_summary=True,
        summary_panel="Vehicle-use measures, token-day",
        summary_unit="Fraction (0--1)",
    ),
    VariableSpec(
        group="Network and route-denominator controls",
        name="Value-weighted intent-route intermediary incidence",
        column="volume_weighted_betweenness",
        notation=r"$\mathrm{RouteIncidence}^{V}_{k,t}$",
        formula=(
            r"$\displaystyle\frac{\mathrm{IVol}_{k,t}}"
            r"{\mathrm{Vol}_t-\mathrm{Vol}^{\mathrm{in}}_{k,t}"
            r"-\mathrm{Vol}^{\mathrm{out}}_{k,t}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"USD-volume analogue of $\mathrm{RouteIncidence}^{N}_{k,t}$ using the same route "
            r"universe and input/output-endpoint exclusions."
        ),
        source="data/metrics/<date>.parquet",
        used_for=(
            "Historical realized-route diagnostic; distinct from graph-theoretic "
            "value-weighted betweenness."
        ),
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
        group="LP capital measures",
        name="Vehicle-linked deposited capital",
        column="vehicle_linked_capital_usd",
        notation=r"$C_{k,t}$",
        formula=r"$\displaystyle\sum_{p\in\mathcal L_{k,t}}\frac{\mathrm{Capital}_{p,t}}{m_p}$",
        unit="USD",
        construction=(
            r"Candidate $k$'s allocated share of validated deposited capital reconstructed from the "
            r"released exact constant-product closing reserves, audited token identity and decimals, "
            r"and independent address-day prices. Allocation is full when $k$ is the pool's only "
            r"candidate token and one half when both pool tokens are candidates. Provider-reported "
            r"TVL or reserveUSD is an overlap diagnostic and never owns the measure or row eligibility."
        ),
        source="data/exhibits/lp_capital_concentration.parquet",
        used_for="LP-capital allocation, persistence, and stickiness tests.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_unit="USD billions",
        summary_scale=1.0 / 1_000_000_000.0,
    ),
    VariableSpec(
        group="LP capital measures",
        name="LP capital share",
        column="lp_capital_share",
        notation=r"$\mathrm{LPCapitalShare}_{k,t}$",
        formula=r"$\displaystyle\frac{C_{k,t}}{\sum_{\ell\in\mathcal K}C_{\ell,t}}$",
        unit="Fraction (0--1)",
        construction=r"Candidate $k$'s share of total candidate-linked deposited capital on day $t$.",
        source="data/exhibits/lp_capital_concentration.parquet",
        used_for="LP-capital persistence and predictability regressions.",
        include_in_summary=True,
        summary_panel="Liquidity and route-cost opportunity",
        summary_unit="Percent",
        summary_scale=100.0,
    ),
    VariableSpec(
        group="LP capital measures",
        name="Log vehicle-linked deposited capital",
        column="log_vehicle_linked_capital",
        notation=r"$\mathrm{LogVehicleCapital}_{k,t}$",
        formula=r"$\ln(1+C_{k,t})$",
        unit="Natural-log points",
        construction=r"Natural log of one plus $C_{k,t}$ measured in USD.",
        source="data/exhibits/lp_capital_concentration.parquet",
        used_for="LP-capital-level regressions.",
    ),
    VariableSpec(
        group="LP capital commonality measures",
        name="Leave-one-out vehicle capital factor",
        column="vehicle_capital_factor_loo",
        notation=r"$\mathrm{VehicleCapitalFactor}_{p,k,t}$",
        formula=(
            r"$\displaystyle\frac{\sum_{p'\in\mathcal L_{k,t}\setminus\{p\}}"
            r"\Delta_1\ln(\mathrm{Capital}_{p',t})}"
            r"{|\mathcal L_{k,t}\setminus\{p\}|}$"
        ),
        unit="Daily log-change points",
        construction=(
            r"Leave-one-out mean daily log deposited-capital change among other valid pools linked to "
            r"candidate $k$; requires at least three other pools."
        ),
        source="data/empirical/common_pool_capital_panel.parquet",
        used_for="RQ2 common-capital mechanism test.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital commonality measures",
        name="Leave-one-out market capital factor",
        column="market_capital_factor_loo",
        notation=r"$\mathrm{MarketCapitalFactor}_{p,t}$",
        formula=(
            r"$\displaystyle\frac{\sum_{p'\in\mathcal L_t\setminus\{p\}}"
            r"\Delta_1\ln(\mathrm{Capital}_{p',t})}"
            r"{|\mathcal L_t\setminus\{p\}|}$"
        ),
        unit="Daily log-change points",
        construction=(
            r"Leave-one-out mean daily log deposited-capital change across all other valid pools in "
            r"$\mathcal L_t$; market-wide control for the vehicle factor."
        ),
        source="data/empirical/common_pool_capital_panel.parquet",
        used_for="RQ2 common-capital mechanism test.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Liquidity commonality measures",
        name="Pool vehicle-route share",
        column="pool_vehicle_route_share",
        notation=r"$\mathrm{VehicleRouteShare}_{p,k,t}$",
        formula=r"$\displaystyle\frac{\mathrm{SpokeIVol}_{p,k,t}}{\mathrm{PoolVol}_{p,t}}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pool $p$'s day-$t$ realized swap volume contributed by legs of "
            r"indirect routes using $k$ as the intermediate; defined for positive pool volume."
        ),
        source="to be constructed from the reconstructed route-leg and pool-volume panels",
        used_for="RQ2 pool-level vehicle demand and LP rent-incidence tests.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="LP active capital",
        column="lp_active_capital_usd",
        notation=r"$L_{a,p,t}$",
        formula="",
        unit="USD",
        construction=(
            r"End-of-day active liquidity controlled by address $a$ in pool $p$, reconstructed "
            r"from position events and marked at day-$t$ reference prices. Contract-managed "
            r"positions are assigned to a controller only where the event trail permits look-through."
        ),
        source="to be constructed from V3/V4 position events, pool states, and transaction receipts",
        used_for="RQ2 LP supply, balance-sheet transmission, and rent-incidence tests.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="LP capital share",
        column="lp_pool_capital_share",
        notation=r"$w_{a,p,t}$",
        formula=r"$\displaystyle\frac{L_{a,p,t}}{\sum_{a'}L_{a',p,t}}$",
        unit="Fraction (0--1)",
        construction=r"Provider $a$'s share of reconstructed active capital in pool $p$ on day $t$.",
        source="to be constructed from LP active capital",
        used_for="RQ2 provider overlap and pool exposure weights.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="LP net flow",
        column="lp_net_flow_usd",
        notation=r"$F^{\mathrm{LP}}_{a,p,t}$",
        formula="",
        unit="USD per day",
        construction=(
            r"Transaction-time USD value of day-$t$ mint deposits less burn withdrawals for "
            r"provider $a$ in pool $p$, with fee collections excluded."
        ),
        source="to be constructed from V3/V4 liquidity events and transaction-time token prices",
        used_for="RQ2 liquidity-supply response and RQ4/RQ5 architecture response.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="LP fee yield",
        column="lp_fee_yield",
        notation=r"$\mathrm{LPFeeYield}_{a,p,t}$",
        formula=r"$\displaystyle\frac{\mathrm{Fee}_{a,p,t}}{L_{a,p,t-1}}$",
        unit="Daily fraction",
        construction=(
            r"Day-$t$ fees accrued to the position divided by lagged active capital; defined "
            r"only for positive lagged capital."
        ),
        source="to be constructed from swap fees, position ranges, and lagged LP active capital",
        used_for="RQ2 gross LP rent incidence and RQ4/RQ5 architecture response.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="Loss versus rebalancing",
        column="lp_lvr",
        notation=r"$\mathrm{LVR}_{a,p,t}$",
        formula=(
            r"$\displaystyle\frac{V^{\mathrm{RB}}_{a,p,t}-V^{\mathrm{LP}}_{a,p,t}}"
            r"{L_{a,p,t-1}}$"
        ),
        unit="Daily fraction",
        construction=(
            r"Underperformance of the opening LP inventory relative to its self-financing "
            r"rebalanced benchmark, before fees, flows, and gas; defined for positive lagged capital."
        ),
        source="to be constructed from V3/V4 position states and intraday reference-price paths",
        used_for="RQ2 adverse-selection cost and net-rent decomposition.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="LP net return",
        column="lp_net_return",
        notation=r"$\mathrm{LPNetReturn}_{a,p,t}$",
        formula=(
            r"$\displaystyle\mathrm{LPFeeYield}_{a,p,t}-\mathrm{LVR}_{a,p,t}"
            r"-\frac{G^{\mathrm{LP}}_{a,p,t}}{L_{a,p,t-1}}$"
        ),
        unit="Daily fraction",
        construction=(
            r"Fee yield less loss versus rebalancing and position-management gas cost, all "
            r"scaled by lagged active capital."
        ),
        source="to be constructed from LP fee yield, loss versus rebalancing, and transaction gas",
        used_for="RQ2 net LP rent incidence and RQ4/RQ5 architecture response.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="Other-pool LP portfolio return",
        column="lp_other_pool_return",
        notation=r"$R^{\mathrm{other}}_{a,-p,t}$",
        formula=(
            r"$\displaystyle\frac{\sum_{p'\ne p}L_{a,p',t-1}R^{\mathrm{LP}}_{a,p',t}}"
            r"{\sum_{p'\ne p}L_{a,p',t-1}}$"
        ),
        unit="Daily return fraction",
        construction=(
            r"Lag-capital-weighted, fee-, flow-, and gas-excluded return on provider $a$'s "
            r"positions outside focal pool $p$; defined when outside lagged capital is positive."
        ),
        source="to be constructed from the address-pool LP position panel",
        used_for="RQ2 within-pool balance-sheet transmission experiment.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="Predicted other-pool LP shock",
        column="lp_predicted_other_pool_shock",
        notation=r"$Z^{\mathrm{other}}_{a,-p,t}$",
        formula=r"$\displaystyle\sum_{x\notin p}\omega_{a,x,-p,t-1}R_{x,t}$",
        unit="Daily return fraction",
        construction=(
            r"Shift-share return shock formed from provider $a$'s lagged outside-pool token "
            r"exposures and independent day-$t$ token returns, excluding both focal-pool tokens."
        ),
        source="to be constructed from lagged LP inventories and an independent token-price panel",
        used_for="RQ2 predetermined-exposure balance-sheet transmission experiment.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="Pool LP wealth shock",
        column="pool_lp_wealth_shock",
        notation=r"$\mathrm{LPWealthShock}_{p,t}$",
        formula=r"$\displaystyle\sum_a w_{a,p,t-1}Z^{\mathrm{other}}_{a,-p,t}$",
        unit="Daily return fraction",
        construction=(
            r"Lagged-capital-share-weighted predicted outside-pool shock of the providers "
            r"supplying pool $p$ before day-$t$ flows."
        ),
        source="to be constructed from LP capital shares and predicted other-pool shocks",
        used_for="RQ2 pool-level propagation of LP balance-sheet shocks.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="LP capital and return measures",
        name="LP provider overlap",
        column="lp_provider_overlap",
        notation=r"$\mathrm{LPOverlap}_{p,p',t}$",
        formula=r"$\displaystyle\sum_a\min\{w_{a,p,t},w_{a,p',t}\}$",
        unit="Fraction (0--1)",
        construction=(
            r"Common active-capital share attributable to the same resolved providers in pools "
            r"$p$ and $p'$; zero means no overlap and one means identical provider weights."
        ),
        source="to be constructed from LP capital shares",
        used_for="RQ2 separation of shared-provider supply from vehicle-network demand.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Routing-search efficiency measures",
        name="Chosen-path reproduction error",
        column="chosen_validation_error_bps",
        notation=r"$\mathrm{ChosenError}_{r}$",
        formula=r"$10^4(O^{\mathrm{chosen}}_r-O^{\mathrm{real}}_r)/O^{\mathrm{real}}_r$",
        unit="Basis points",
        construction=(
            r"Signed difference between the exact pre-transaction quote of realised route $r$ "
            r"and its observed token output. The construction sample requires an absolute error "
            r"of at most one basis point; 0.1- and 0.01-basis-point subsets are prespecified."
        ),
        source="data/processed/transaction_state_frontier_daily_release/current.json",
        used_for="Exact-state construction validation and nested routing-efficiency support.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Routing-search efficiency measures",
        name="Chosen-leg maximum reproduction error",
        column="chosen_validation_max_abs_error_bps",
        notation=r"$\lvert\mathrm{ChosenError}^{\max}_{r}\rvert$",
        formula=r"$\max\{\lvert e^{(1)}_r\rvert,\lvert e^{(2)}_r\rvert,\lvert e^{(1\circ2)}_r\rvert\}$",
        unit="Basis points",
        construction=(
            r"Maximum absolute error across the first realised leg, the second realised leg "
            r"quoted at its observed input, and their composed path. The construction sample "
            r"requires this measure to be at most one basis point; 0.1- and "
            r"0.01-basis-point subsets are prespecified."
        ),
        source="data/processed/transaction_state_frontier_daily_release/current.json",
        used_for="Exact-state construction validation and nested routing-efficiency support.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Routing-search efficiency measures",
        name="Within-reach routing-search regret",
        column="within_reach_search_regret_bps",
        notation=r"$\mathrm{Regret}^{\mathrm{reach}}_{r}$",
        formula=(
            r"$10^4[\max\{O^{\mathrm{real}}_r,O^{k,\mathcal V_r}_r\}"
            r"-O^{\mathrm{real}}_r]/O^{\mathrm{real}}_r$"
        ),
        unit="Basis points",
        construction=(
            r"Output gain from the best path through the realised vehicle $k$ using only the "
            r"venues observed on route $r$, relative to realised output at the same pre-transaction state."
        ),
        source="data/processed/transaction_state_frontier_daily_release/current.json",
        used_for="Routing search quality while holding venue reach and intermediary fixed.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Routing-search efficiency measures",
        name="Public-reach increment",
        column="reach_increment_bps",
        notation=r"$\mathrm{ReachIncrement}_{r}$",
        formula=(
            r"$10^4[\max\{O^{\mathrm{real}}_r,O^{k,\mathcal V}_r\}"
            r"-\max\{O^{\mathrm{real}}_r,O^{k,\mathcal V_r}_r\}]"
            r"/O^{\mathrm{real}}_r$"
        ),
        unit="Basis points",
        construction=(
            r"Additional output from expanding the same-vehicle search from route $r$'s observed "
            r"venues $\mathcal V_r$ to the admitted public venue set $\mathcal V$."
        ),
        source="data/processed/transaction_state_frontier_daily_release/current.json",
        used_for="Opportunity-set expansion separated from within-reach search.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Routing-search efficiency measures",
        name="Intermediary and path-choice increment",
        column="path_choice_increment_bps",
        notation=r"$\mathrm{PathChoiceIncrement}_{r}$",
        formula=(
            r"$10^4[\max\{O^{\mathrm{real}}_r,O^{\mathrm{public}}_r\}"
            r"-\max\{O^{\mathrm{real}}_r,O^{k,\mathcal V}_r\}]"
            r"/O^{\mathrm{real}}_r$"
        ),
        unit="Basis points",
        construction=(
            r"Additional output from allowing the admitted public frontier to change the "
            r"intermediary or choose a direct path after public venue reach is already available."
        ),
        source="data/processed/transaction_state_frontier_daily_release/current.json",
        used_for="Intermediary/path choice separated from search and venue reach.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Routing-search efficiency measures",
        name="Public-path routing regret",
        column="public_path_regret_bps",
        notation=r"$\mathrm{Regret}^{\mathrm{public}}_{r}$",
        formula=(
            r"$\mathrm{Regret}^{\mathrm{reach}}_{r}+\mathrm{ReachIncrement}_{r}"
            r"+\mathrm{PathChoiceIncrement}_{r}$"
        ),
        unit="Basis points",
        construction=(
            r"Total nonnegative output shortfall against the best admitted direct or two-leg "
            r"public path at the same pre-transaction state."
        ),
        source="data/processed/transaction_state_frontier_daily_release/current.json",
        used_for="Overall realised-to-public-frontier routing efficiency.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Routing-search efficiency measures",
        name="Direct-path omission",
        column="direct_omission_bps",
        notation=r"$\mathrm{DirectOmission}_{r}$",
        formula=(
            r"$10^4[\max\{O^{\mathrm{real}}_r,O^{D,\mathcal V}_r\}"
            r"-O^{\mathrm{real}}_r]/O^{\mathrm{real}}_r$"
        ),
        unit="Basis points",
        construction=(
            r"Output gain from the best admitted public direct path relative to the realised "
            r"indirect route; undefined when no direct path is executable."
        ),
        source="data/processed/transaction_state_frontier_daily_release/current.json",
        used_for="Direct-route omission as a separate extensive routing margin.",
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
        name="Pair-level direct quote quality",
        column="pair_direct_quote_quality",
        notation=r"$\mathrm{DirectQuoteQuality}_{i,o,q,t}$",
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
        name="Pair-candidate indirect quote quality",
        column="pair_indirect_quote_quality",
        notation=r"$\mathrm{IndirectQuoteQuality}_{i,o,k,q,t}$",
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
        name="Pair-level direct fee cost",
        column="pair_direct_fee_cost",
        notation=r"$C^{D,\mathrm{fee}}_{i,o,q,t}$",
        formula=r"$\displaystyle 1-\frac{O^{D,\mathrm{fee}}_{i,o,q,t}}{q}$",
        unit="Fraction",
        construction=(
            r"Direct-route loss attributable to historical pool fees when price impact is "
            r"suppressed at the pre-quote marginal price."
        ),
        source="to be constructed by historical no-impact quote replay with actual fees",
        used_for="RQ1 all-in route-cost decomposition.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-level direct price-impact cost",
        column="pair_direct_price_impact_cost",
        notation=r"$C^{D,\mathrm{impact}}_{i,o,q,t}$",
        formula=(
            r"$\displaystyle\frac{O^{D,\mathrm{fee}}_{i,o,q,t}-O^{D}_{i,o,q,t}}{q}$"
        ),
        unit="Fraction",
        construction=(
            r"Additional direct-route output loss caused by moving through the realized "
            r"liquidity curve, after holding the fee-only output fixed."
        ),
        source="to be constructed from actual and no-impact direct quote replay",
        used_for="RQ1 convex-price-impact mechanism test.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-level direct gas cost",
        column="pair_direct_gas_cost",
        notation=r"$C^{D,\mathrm{gas}}_{i,o,q,t}$",
        formula=r"$\displaystyle\frac{G^{D}_{i,o,q,t}}{q}$",
        unit="Fraction",
        construction=r"Historical direct-route gas expenditure as a fraction of input USD notional.",
        source="to be constructed from route gas usage, gas price, and gas-token USD price",
        used_for="RQ1 fixed-cost decomposition and RQ5 user-cost incidence.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-candidate indirect fee cost",
        column="pair_indirect_fee_cost",
        notation=r"$C^{I,\mathrm{fee}}_{i,o,k,q,t}$",
        formula=r"$\displaystyle 1-\frac{O^{I,\mathrm{fee}}_{i,o,k,q,t}}{q}$",
        unit="Fraction",
        construction=(
            r"Two-leg indirect-route loss attributable to both pools' historical fees when "
            r"price impact is suppressed at each pre-quote marginal price."
        ),
        source="to be constructed by historical two-leg no-impact quote replay with actual fees",
        used_for="RQ1 second-fee-leg mechanism test.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-candidate indirect price-impact cost",
        column="pair_indirect_price_impact_cost",
        notation=r"$C^{I,\mathrm{impact}}_{i,o,k,q,t}$",
        formula=(
            r"$\displaystyle\frac{O^{I,\mathrm{fee}}_{i,o,k,q,t}-O^{I}_{i,o,k,q,t}}{q}$"
        ),
        unit="Fraction",
        construction=(
            r"Additional two-leg indirect-route output loss caused by moving through both "
            r"realized liquidity curves, after holding fee-only output fixed."
        ),
        source="to be constructed from actual and no-impact indirect quote replay",
        used_for="RQ1 vehicle-spoke price-impact mechanism test.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-candidate indirect gas cost",
        column="pair_indirect_gas_cost",
        notation=r"$C^{I,\mathrm{gas}}_{i,o,k,q,t}$",
        formula=r"$\displaystyle\frac{G^{I}_{i,o,k,q,t}}{q}$",
        unit="Fraction",
        construction=r"Historical two-leg indirect-route gas expenditure as a fraction of input USD notional.",
        source="to be constructed from route gas usage, gas price, and gas-token USD price",
        used_for="RQ1 fixed-cost decomposition and RQ5 settlement-saving incidence.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-level all-in direct cost",
        column="pair_all_in_direct_cost",
        notation=r"$C^{D}_{i,o,q,t}$",
        formula=r"$\displaystyle 1-\frac{O^{D}_{i,o,q,t}}{q}+\frac{G^{D}_{i,o,q,t}}{q}$",
        unit="Fraction",
        construction=(
            r"Direct quote-output loss, which includes pool fees and price impact, plus historical "
            r"route gas as a fraction of input notional. Fee, price-impact, and gas contributions "
            r"are retained separately and sum to this measure."
        ),
        source="to be constructed by historical quote replay and route-specific gas accounting",
        used_for="RQ1 route-cost decomposition and RQ3 current-economics controls.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-candidate all-in indirect cost",
        column="pair_all_in_indirect_cost",
        notation=r"$C^{I}_{i,o,k,q,t}$",
        formula=r"$\displaystyle 1-\frac{O^{I}_{i,o,k,q,t}}{q}+\frac{G^{I}_{i,o,k,q,t}}{q}$",
        unit="Fraction",
        construction=(
            r"Indirect quote-output loss across both legs, which includes both pools' fees and "
            r"price impact, plus historical route gas as a fraction of input notional. Fee, "
            r"price-impact, and gas contributions are retained separately and sum to this measure."
        ),
        source="to be constructed by historical quote replay and route-specific gas accounting",
        used_for="RQ1 trade-size route comparison and RQ3 challenger economics.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Route-cost opportunity measures",
        name="Pair-candidate all-in direct cost advantage",
        column="pair_all_in_direct_cost_advantage",
        notation=r"$\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$",
        formula=r"$C^{I}_{i,o,k,q,t}-C^{D}_{i,o,q,t}$",
        unit="Fraction",
        construction=(
            r"Indirect all-in cost minus direct all-in cost on common support; positive values "
            r"favor direct execution and negative values favor indirect execution."
        ),
        source="to be constructed from pair-level direct and indirect all-in costs",
        used_for="RQ1 economic route choice and RQ3 hysteresis conditional on current economics.",
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
        name="Direct quote quality",
        column="direct_quote_quality_median",
        notation=r"$\mathrm{DirectQuoteQuality}_{k,t,q}$",
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
        name="Candidate-day median all-in direct cost advantage",
        column="all_in_direct_cost_advantage_median",
        notation=r"$\mathrm{AllInDirectCostAdvantage}_{k,t,q}$",
        formula=(
            r"$\displaystyle\mathrm{median}_{\mathcal C_{k,t,q}}"
            r"\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$"
        ),
        unit="Fraction",
        construction=(
            r"Median pair-level all-in direct cost advantage over common-support pairs; "
            r"positive values favor direct execution after gas."
        ),
        source="to be constructed from pair-level all-in direct cost advantages",
        used_for="RQ2 candidate-day feedback controls and all-in-cost robustness.",
        in_observations_table=False,
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
            r"$\tau\in\{1,7,30,120\}$ by exact calendar date."
        ),
        source="constructed from observations table",
        used_for="Persistence and displacement tests.",
    ),
    VariableSpec(
        group="Reference-price support",
        name="Observed CEX reference support",
        column="cex_reference_supported",
        notation=r"$\mathrm{CEXRef}_{x,t}$",
        formula=(
            r"$\mathbf{1}_{\{x\in\mathcal K^{\mathrm{CEX}},\ "
            r"t\in[t_x^{\mathrm{first}},t_x^{\mathrm{last}}]\}}$"
        ),
        unit="Indicator (0/1)",
        construction=(
            r"Equals one only for an exact token address in the published 43-pair "
            r"Uniswap--Binance comparison and between that pair's first and last "
            r"observations in the package's 1-in-10,000 minute sample. Absence is "
            r"unsupported and never means that the token was unlisted."
        ),
        source="data/processed/cex_reference_support.parquet",
        used_for="Positive-support CEX-reference bound on liquidity-rent estimates.",
        in_observations_table=False,
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
        formula=r"$C^I_{i,o,k^\star,q,t}-C^I_{i,o,h^\star,q,t}$",
        unit="Fraction",
        construction=(
            r"All-in cost advantage of the best executable challenger over the incumbent "
            r"vehicle at input notional $q$; positive values favor the challenger."
        ),
        source="to be constructed from pair-level shares and pair-candidate all-in route costs",
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
        used_for="RQ3 displacement probability at the exact calendar-day horizons registered in the empirical design.",
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
        name="Pre-V3 pair volatility",
        column="pre_v3_pair_volatility",
        notation=r"$\sigma^{\mathrm{pre}}_{i,o}$",
        formula=r"$\displaystyle\mathrm{sd}_{u\in\mathcal T^{\mathrm{V3}}_{\mathrm{pre}}}(R_{i,o,u})$",
        unit="Daily log-return standard deviation",
        construction=(
            r"Sample standard deviation of the ordered endpoint-pair log return over the fixed "
            r"180-day pre-V3 window; computed only from information dated before V3 activation."
        ),
        source="to be constructed from endpoint-token reference prices before estimation",
        used_for="RQ4 test of whether concentrated liquidity disproportionately favors stable pairs.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Execution-architecture measures",
        name="Pool band-depth capital efficiency",
        column="pool_band_depth_capital_efficiency",
        notation=r"$\eta^{\mathrm{Band}}_{p,t,b,d}$",
        formula=r"$\displaystyle\frac{\mathrm{BandDepth}_{p,t,b,d}}{C_{p,t}}$",
        unit="USD directional band depth per USD validated deposited capital",
        construction=(
            r"Fee-inclusive executable dollar depth in direction $d$ inside the symmetric "
            r"$b$ price band divided by contemporaneous validated deposited capital. The "
            r"primary band is $b=0.02$; $b\in\{0.01,0.10\}$ is retained for robustness. "
            r"The row retains direction, band, invariant family and state generation."
        ),
        source="withheld until a protocol-family band-depth adapter and validated capital stock both pass",
        used_for="RQ4 capital-efficiency and network-concentration mechanism tests.",
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
        group="Execution-architecture measures",
        name="V4 route indicator",
        column="v4_route",
        notation=r"$\mathrm{V4}_{r}$",
        formula=r"$\mathbf{1}_{\{r\in\mathcal R^4_g\}}$",
        unit="Indicator (0/1)",
        construction=r"Equals one when matched route unit $r$ executes on Uniswap V4.",
        source="data/empirical/v4_settlement_route_units.parquet",
        used_for="Architecture-state adoption, exit and reversal diagnostics.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="Execution-architecture measures",
        name="V4 route share",
        column="v4_route_share",
        notation=r"$\mathrm{V4RouteShare}_{g}$",
        formula=r"$\displaystyle\frac{|\mathcal R^4_g|}{|\mathcal R^3_g|+|\mathcal R^4_g|}$",
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pure V3/V4 route units in ordered endpoint-pair, vehicle and week "
            r"cell $g$ that execute on V4. Mixed-source components are excluded before assignment."
        ),
        source="data/processed/architecture_state_weekly.parquet",
        used_for="Architecture-state adoption, exit and reversal diagnostics.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="Pre-V4 pair indirect-route share",
        column="pre_v4_pair_indirect_route_share",
        notation=r"$\mathrm{PreV4IndirectShare}_{i,o}$",
        formula=(
            r"$\displaystyle\frac{\sum_{u\in\mathcal T^{\mathrm{V4}}_{i,o,\mathrm{pre}}}"
            r"\mathrm{IndirectRouteShare}_{i,o,u}}"
            r"{|\mathcal T^{\mathrm{V4}}_{i,o,\mathrm{pre}}|}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Mean pair-level indirect-route share over pair $(i,o)$'s positive-volume days in "
            r"the fixed 180-day pre-V4 window, requiring at least 30 such days."
        ),
        source="to be constructed from the pre-V4 pair route panel",
        used_for="RQ5 predetermined pair-level exposure to settlement netting.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="Post-V4 indicator",
        column="post_v4",
        notation=r"$\mathrm{PostV4}_{t}$",
        formula=r"$\mathbf{1}_{\{t\ge t^{\mathrm{V4}}_0\}}$",
        unit="Indicator (0/1)",
        construction=r"Equals one on and after the Ethereum V4 activation date.",
        source="constructed from the activation date verified against deployment metadata",
        used_for="RQ5 pair- and pool-level differential event studies.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="Physical vehicle-token movement",
        column="physical_vehicle_movement_usd",
        notation=r"$M_{r,k}$",
        formula="",
        unit="USD",
        construction=(
            r"Sum of absolute, route-attributed ERC-20 transfers of intermediate token $k$ "
            r"between distinct nonzero addresses in route unit $r$, with duplicate logs removed "
            r"and each amount valued at the transaction-time reference price."
        ),
        source="to be constructed from receipt-audited route units and ERC-20 transfer logs",
        used_for="RQ5 gross-to-net settlement comparison.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="Physical settlement intensity",
        column="physical_settlement_intensity",
        notation=r"$\mathrm{SettlementIntensity}_{r,k}$",
        formula=r"$\displaystyle\frac{M_{r,k}}{\mathrm{GrossLegVol}_{r,k}}$",
        unit="USD transferred per gross vehicle-leg USD",
        construction=(
            r"Physical intermediate-token movement per unit of gross intermediate-token notional "
            r"across the two economic route legs; defined for positive gross vehicle-leg volume."
        ),
        source="to be constructed from receipt-audited movement and reconstructed route legs",
        used_for="RQ5 intensive-margin settlement netting and accounting validation.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="Vehicle capital turnover",
        column="vehicle_capital_turnover",
        notation=r"$\mathrm{VehicleTurnover}_{k,t}$",
        formula=r"$\displaystyle\frac{\mathrm{IVol}_{k,t}}{C_{k,t}}$",
        unit="USD vehicle volume per USD deposited capital per day",
        construction=(
            r"Realized indirect-route volume through candidate $k$ divided by its allocated "
            r"vehicle-linked deposited capital, defined for positive $C_{k,t}$."
        ),
        source="to be constructed from route volume and vehicle-linked deposited capital",
        used_for="RQ5 test of whether net settlement changes required capital per unit of vehicle use.",
        in_observations_table=False,
    ),
    VariableSpec(
        group="V4 settlement implementation measures",
        name="Pre-V4 pool vehicle-route exposure",
        column="pre_v4_pool_vehicle_route_exposure",
        notation=r"$\mathrm{VehicleRouteExposure}^{\mathrm{pre}}_{p,k}$",
        formula=(
            r"$\displaystyle\frac{\sum_{u\in\mathcal T^{\mathrm{V4}}_{\mathrm{pre}}}"
            r"\mathrm{SpokeIVol}_{p,k,u}}"
            r"{\sum_{u\in\mathcal T^{\mathrm{V4}}_{\mathrm{pre}}}\mathrm{PoolVol}_{p,u}}$"
        ),
        unit="Fraction (0--1)",
        construction=(
            r"Fraction of pool $p$'s realized swap volume in the fixed 180-day pre-V4 window "
            r"attributable to legs of indirect routes using $k$ as the intermediate; defined "
            r"for positive pre-period pool volume."
        ),
        source="to be constructed from the pre-V4 reconstructed route-leg and pool panels",
        used_for="RQ5 predetermined LP-capital exposure and RQ2 vehicle-spoke heterogeneity.",
        in_observations_table=False,
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

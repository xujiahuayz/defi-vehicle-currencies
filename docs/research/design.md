# Research questions and empirical design

This note explains the current paper design. The executable definitions are in
[`../specifications/confirmatory.json`](../specifications/confirmatory.json), and
the current numerical results are in [`../findings/`](../findings/README.md).
Ideas that are not in those two places are future work, not unfinished parts of
the present paper.

## Current expansion agenda

The executable gate is green for the two registered baseline families, but the
research target is now stronger than measurement. The open mode is parallel:
keep a presentable paper and deck, send versioned review snapshots when useful,
and continue mechanism search, input building, experiments, and comment response
at the same time. A weak, merely measurable, or literature-incremental result
loops back to more search; it does not stop the paper and slides from being
rebuilt.

## Resolve before caveating

For every central result, list the serious alternative explanations, measurement
limits, and interpretive steps. Then classify each one by whether the repository
can observe its implication.

1. A missing field, stale fetch, incomplete crosswalk, or rebuildable historical
   input is a data task. Fetch or reconstruct it, rerun every dependent result,
   and remove the obsolete caveat.
2. A testable interpretation becomes a focused empirical design. Use the most
   direct object available: exact route repricing for price alternatives,
   decomposition for accounting margins, transition matrices for switching,
   event time for sequencing, and regression only when conditioning or variation
   is the question.
3. A result replaces the interpretation when the test discriminates among the
   alternatives. If the test leaves several explanations observationally
   equivalent, state that remaining set precisely.
4. Retain a limitation only when it concerns identification, user or provider
   intent absent from the chain, unavailable external data, or an extension whose
   cost and scope are disproportionate to the paper's contribution.

This loop is recursive. A new result can expose another resolvable boundary; the
paper, deck, tables, figures, and speaking notes are rebuilt after the boundary
is closed.

### Current result-resolution map

| Main evidence | Question that can be settled with current or fetchable data | Direct check | Residual boundary |
|---|---|---|---|
| Executed pool routes | Did missing V1 token identities truncate the route panel, or do disconnected calls drive the rotation? | Re-fetch the exact V1 exchange registry, rebuild the common panel, and compare the principal connected-transaction rule with separately reconstructed components. | A pool-event component identifies the executed on-chain route. User instructions, executor inventory, and off-pool transfers remain unobserved. |
| Aggregate stablecoin rotation | Is the endpoint comparison a selected window, and is the near-zero within-pair term hiding gross switching? | Report positive and negative pair contributions separately and apply the identical decomposition to every adjacent January--June year pair. | The accounting locates the margin of change; it does not assign an external cause to pair entry, exit, or trading reallocation. |
| Vehicle use after pair entry | Does the first vehicle merely predict later use, or does persistence survive an observable challenger? | Report transition and majority-state persistence, condition on continuous stablecoin-versus-WETH depth, and compare the chosen vehicle with the exact pretrade price leader when the panels overlap. | Trader and liquidity-provider intent are absent from the chain, so behavior and expectations remain observationally equivalent after measured price and depth are held fixed. |
| Persistent bridge support and first use | Is support only a binary availability indicator, and what happens to capital around first use? | Measure the continuous bottleneck-depth ratio, the adoption gradient, pre- and post-use capital paths, and new-pool versus continuing-pool capital. | First use and deposited capital are equilibrium outcomes; without external variation the sequence does not identify a liquidity-supply effect. |
| Exact route prices | Would the realised route change after opening more venues, another vehicle, or the direct path? | Reprice the same input at pretrade state through nested opportunity sets and report route-level transitions. | Candidate-specific gas, private order flow, and venues without reconstructable historical state remain outside the exact all-in comparison. |

The adjacent-year decomposition is part of the vehicle-transition rebuild. The
entry-price comparison runs only after the V1-inclusive exact-price and entry
panels have both been rebuilt; it is omitted rather than filled with stale
numbers before that join exists.

Priority experiments:

1. Making of vehicle dominance: estimate which asset, market, and route features
   predict vehicle adoption, dominance intensity, leader switches, entry, exit,
   reversals, and persistence. Preferred designs condition on the same endpoint
   pair and date when feasible, so the comparison is among candidate vehicles in
   the same trading opportunity.
2. Liquidity-provision behavior: separate capital stocks from liquidity-supply
   flows, provider entry/exit, withdrawals, reallocation across vehicles, and
   V3/V4 route or netting behavior where the required inputs exist.
3. Mechanism distinction: compare route cost, executable depth, venue coverage,
   route redundancy, candidate centrality, pool age, and capital concentration
   as competing explanations. Correlations are admissible when causal evidence
   is not defensible, but each result must state the unit, conditioning set,
   strongest rival, and economic magnitude.
4. Framing: motivate the paper with concrete traditional-finance analogies, such
   as a dealer or treasurer routing a thin currency pair through a liquid vehicle
   currency because direct execution is expensive or unavailable. The analogy is
   motivation only; it should not substitute for the DEX evidence.

Draft rule: provisional results may enter the paper and deck if they are clearly
labelled and rebuildable enough for review. Claim-status upgrades are separate:
a result becomes headline evidence only if it is economically material, survives
a serious rival explanation, clarifies the contribution relative to the
literature, and can be rebuilt from declared inputs. If those conditions are not
met, the workflow loops back to mechanism search and additional experiments
while the current draft remains presentable.

The current V4 participation extension distinguishes transaction origins active
in the preceding 180 days from origins first active after the measurement date.
It excludes zero-liquidity updates in the primary sample and separates days
1--30 from days 31--120. Transaction origin is a participation proxy, not a
verified LP-position owner. The registered comparison asks whether internal
same-asset routing is followed first by more actions from incumbent origins and
later by origins absent from the prior window. The family uses the existing
vehicle and date effects, origin-day controls, date clustering, and Holm
adjustment across the three accounting proxies and four timing outcomes.

The state-dependent extension uses lagged 30-day mean realised WETH volatility
from one-minute prices. It interacts that state with internal same-asset routing,
allows every vehicle and origin-day control its own volatility slope, and keeps
vehicle and date effects. The registered outcomes are actions by 180-day
incumbent origins during days 1 to 30 and first-active origins during days 31 to
120. A seven-day state, zero-liquidity updates, a 90-day prior window, and
leave-one-vehicle-out estimates are sensitivities. This test distinguishes
persistent risk-bearing conditions from an architecture-only account without
calling volatility an exogenous provider constraint.

The protocol comparison constructs internal same-asset routing identically from
V3 and V4 swap legs, pairs the same vehicle and calendar day, and measures future
participation from nonzero V3 mint/burn and V4 modify-liquidity actions. The
primary 180-day-history sample runs from 23 July 2025 through 2 March 2026. On
that mature common calendar, neither the level difference in routing slopes nor
the V4-minus-V3 difference in their persistent-volatility interactions survives
the two-outcome Holm correction. A pooled 90-day-history sample produces large
differences, but neither its early nor mature calendar segment reproduces that
pooled estimate. The protocol-specific interpretation is therefore withheld:
the V4 result describes participation under its singleton architecture, while
common trading demand and risk-bearing conditions remain viable explanations.

## Question and contribution

The paper asks what makes a vehicle currency dominant and how that dominance
changes. Decentralized exchange is the empirical setting because a transaction
records the assets and pools used along its route. It lets us observe a currency
role that conventional pair-level turnover data usually leave latent.

The main contribution is a distinction between two margins:

1. substitution within an endpoint pair, where traders change the intermediary;
2. composition across endpoint pairs, where activity reallocates toward pairs
   that already use one intermediary more heavily.

For `A → B → C`, `(A,C)` is the ordered **endpoint pair**, `A → B` and
`B → C` are the two **legs**, and the full connected sequence is the **route**.
One pool swap supplies one leg; it is not the routed exchange by itself.

## Measurement

An asset has vehicle status on a route when it is an intermediary rather than an
ultimate endpoint. Vehicle dominance is the degree of that use. The paper reports
both the intermediary share and excess use relative to the asset's endpoint share.
Cost domination is a separate direct-versus-indirect execution comparison.

Route counts are primary because topology is observed more broadly than reliable
dollar value. Value-weighted results are secondary and require source,
intermediary, and destination valuations to agree within 20 percent. Raw values,
coverage, and a wider twofold agreement band remain diagnostics. Canonical
endpoint round trips are excluded from economic-exchange denominators.

The economic unit is a contract-identified token claim grouped by vehicle role,
not a consolidated unit of account. ETH and WETH are combined only after route
reconstruction because wrapping represents the same settlement asset one for
one. Dollar-pegged tokens remain distinct claims because issuer, redemption,
risk, and leg-level pool liquidity differ; stable-group results therefore measure a
family of stable-token vehicles, while token-level results retain issuer
competition.

## Confirmatory family 1: Vehicle-role rotation

The first family compares the stablecoin share of native-plus-stable
intermediaries in 2024 and 2026 on common January-to-June dates.

- Unit: pair-day by observed integration scope. As defined above, every pair is
  ordered by token flow.
- Main coefficient: the 2026 indicator with pair × month-day × scope
  fixed effects.
- Weights: the applicable native-plus-stable route mass.
- Inference: two-way clustering by pair and date, with Holm adjustment
  across the three registered count/value measures.
- Interpretation: descriptive within-market substitution. Calendar time is not a treatment,
  and realised cross-venue routing is not assigned integration.

The aggregate change is then decomposed into within-common-pair substitution,
reweighting across continuing pairs, common-support mass, and entry/exit-pair
composition. The terms must add exactly to the pooled change. This decomposition
is the paper's central empirical result. Its within-pair component is a net
quantity: gross movements toward stable and native intermediaries remain visible
because cancellation is economically different from an absence of switching.

Supporting evidence separates native, fiat-backed, crypto-backed, and hybrid
intermediaries; decomposes USDT excess use; and reports single-venue versus
cross-venue routes and route-complexity cells. These splits test rival composition
stories but do not turn the design causal.

## Confirmatory family 2: V2 deposited-capital predictability

The second family asks whether vehicle use and deposited capital predict one
another within the Uniswap V2 and SushiSwap V2 constant-product family.

- Unit: candidate token address × origin calendar day.
- Candidates: WETH, WBTC, DAI, USDC, and USDT, identified by address.
- Inputs: the all-route vehicle-use panel and candidate-attributed deposited
  capital constructed from validated pool reserves.
- Horizons: exact 1, 7, 30, and 120 calendar days; missing dates remain missing.
- Fixed effects: candidate and origin date.
- Interpretation: predictive association, not causal feedback.

The registered claim requires a positive reciprocal pattern at multiple primary
horizons after multiple-testing adjustment and no contradictory long-horizon
reversal. The paper reports the result at that decision rule rather than selecting
the most favorable coefficient.

Deposited capital is the externally valued capital assigned once across linked
candidates. It is not candidate inventory, marginal depth, executable depth,
quote quality, liquidity-provider profit, or rent.

## Supporting routing analyses and architecture context

The Uniswap V1-to-V2 architecture change supplies institutional evidence. V1
mechanically forced token-to-token routed exchanges through ETH; V2 allowed direct
ERC20 pool pairs. V1 therefore demonstrates forced vehicle status, while continued
WETH pairing after V2 is descriptive evidence about persistence after the mandate
was withdrawn. It does not identify the later stablecoin transition.

Routing-technology windows, cross-venue routing, route complexity, quote-support
bounds, and venue-coverage bounds discipline alternative explanations. Public
release dates are descriptive windows because executor identity does not reveal
who authored a route and market composition changes at the same time.

## Exact pre-transaction vehicle frontier

The monthly exact-price comparison asks whether the realised intermediary
survives a broader public opportunity set. The calendar is the fifteenth day of
each month from June 2020 through June 2026. The unit is a coherent two-leg route
executed on Uniswap V2, SushiSwap V2, or Uniswap V3. Source, destination, input
amount, and pre-transaction state remain fixed, and the observed route must
reproduce realised output within one basis point.

The comparison widens the price set in three nested stages: the same vehicle in
the venue families used by the realised route, the same vehicle across all three
exact venues, and any of WETH, USDC, USDT, DAI, WBTC, the realised noncandidate
vehicle, or a direct path across those venues. The main sample requires leg
values to agree within 20 percent, at least $100 of input, and no more than 5
percent own-price impact on every realised or hypothetical leg. A vehicle change
requires more than one basis point of additional gross output.

Among 777,651 common-support routes, 6.6 percent find a better same-vehicle path
inside the used venue families, 44.4 percent do so after all three exact venues
open, and 46.4 percent improve after the vehicle set and direct path also open.
The full set lowers stablecoin vehicle share by 1.16 percentage points
route-weighted and 2.09 percentage points input-value weighted. The distinction
is descriptive: venue choice responds much more than vehicle identity to the
expanded price set. The comparison is gross of gas, omits private order flow and
other venue families, and does not identify why an available pool was omitted.
Ninety-eight standard-invariant quotes imply more than twice realised output;
they are excluded from magnitude summaries, and removing them leaves the
reported shares unchanged at one decimal place.

## Boundaries

- Architecture availability, adoption, leg-level venue formation, pair entry,
  substitution, and reversal are different objects.
- Counts and values answer different questions and are never silently pooled.
- Unsupported values stay visible through coverage rather than being imputed.
- Symbols label assets; contract addresses establish identity.
- Causal language requires treatment timing, balance, pretrends, exclusion, and
  placebos appropriate to the claimed mechanism.
- Route-minus-capital gaps mechanically reuse origin capital share when the
  outcome is a future-minus-origin share or rank. Those rows diagnose
  convergence and do not identify provider reallocation without separate origin
  share controls or a residualised-gap design.
- Withheld all-in direct-cost, rent-incidence, joint V2/V3 flow, and hysteresis branches
  are outside the current paper unless they receive a new specification and a
  complete producer-to-deliverable path.

# Research questions and empirical design

This note explains the current paper design. The executable definitions are in
[`../specifications/confirmatory.json`](../specifications/confirmatory.json), and
the current numerical results are in [`../findings/`](../findings/README.md).
Ideas that are not in those two places are future work, not unfinished parts of
the present paper.

## JFE depth revision

The paper is an empirical market-structure paper enabled by a new measurement,
not a measurement paper. Route reconstruction must earn the economic object and
the pair decomposition must establish the central fact. Both should be compact.
The empirical middle then asks the harder questions: which vehicle is present
when a pair first appears, how long that initial allocation persists, when a
rival bridge becomes genuinely contestable, how current prices and prior
two-leg depth divide route flow, and what retaining an incumbent costs.

This ordering follows the published-JFE pattern documented in
[`../../literature/audit.md`](../../literature/audit.md): the measured object is
made auditable early, while the body is devoted to conditioned estimates,
mechanism-discriminating comparisons, economic magnitude, and the strongest
rivals. Focus comes from making every exhibit answer the next question, not
from demoting all formal analysis.

The revision follows one connected graph and convergence loop:

```text
compact route measurement and exact-chain validation
  -> aggregate rotation and exact pair lifecycle decomposition
  -> pre-entry price and depth select the first vehicle
  -> first vehicle at pair entry predicts later vehicle use
  -> prior-information bridge formation and relative two-leg depth
  -> stablecoin and WETH paths feasible at the same pretrade state
  -> price-rank crossings reveal when incumbents yield
  -> current output and prior weak-leg depth jointly divide route flow
  -> all-in execution cost and network-risk consequences
  -> rival explanation or unresolved implication
       -> directly observable: test it and rebuild the chain
       -> unobservable or disproportionate: state the remaining boundary
  -> rebuild paper -> deck -> speaking notes -> paper until they agree
```

This is focus by hierarchy. A result belongs in the main text when it advances
the chain or changes the interpretation of a result already there. Technical
derivations, protocol-specific construction, exact-chain validation details,
alternative samples, additional horizons, and local robustness checks belong in
the appendix. A disconnected coefficient belongs in neither place merely
because it is statistically significant; its code and output can remain
available for a later paper.

### Main-text evidence

1. **Measurement and validation.** Define pair, leg, route, path, vehicle, and
   dominance once. Keep one compact panel table. Exact-chain correction results
   should appear as one concise validation line in the data section and a
   technical appendix table unless they materially change pair or vehicle
   assignment.
2. **Central fact and lifecycle.** Keep one all-route rotation figure and one
   exact pair-composition table. The table separates net switching within
   continuing pairs, reweighting across continuing pairs, first-observed pair
   entry, reactivation, vehicle-role turnover, and pair exit. Gross entry must
   remain distinct from the net period-specific-pair term.
3. **Persistence after entry.** Measure days 1--30 and 31--120 separately, remove
   the entry day from every outcome, report later trading explicitly, and show
   pair- and activity-weighted estimates. Entry identity is descriptive state
   dependence until prices and challenger depth enter the comparison.
4. **Liquidity formation.** Date usable bridge formation only with information
   available before the event. Retain adoption at 30 and 120 days, continuous
   relative weak-leg depth, and later route allocation. The capital path around
   first use and future-persistence definitions belong in the appendix as timing
   and robustness evidence.
5. **Contestable vehicle choice.** On routes for which stablecoin and WETH paths
   are both feasible at the same input, state, and public venue set, estimate
   retention first as a function of current exact-output advantage and then add
   prior weak-leg capital on the identical sample. Use a conventional column
   ladder with pair and date effects and pair/date clustered inference. Add
   price-rank crossings to show how retention changes when a challenger becomes
   both cheaper and deep enough to carry the observed trade.
6. **Financial consequence.** For each contestable route, measure gross output
   relative to the feasible rival family. Report route and input-value weights,
   pair age, conditional shortfall quantiles, and transparent gas and venue
   bounds. This converts persistence into an economically scaled outcome.
7. **Risk transmission, conditional on evidence.** Promote an issuer shock only
   if a pair-level exposure design has credible pretrends, comparison support,
   and restrictions for dust, round trips, and automated flow. The existing
   aggregate USDC episode does not clear that bar by itself.

The current bridge-choice estimates and exact-price comparison already warrant
the fifth step. The prior-information event contains 1,618 bridges; adoption
reaches 38.3% within 30 days and 47.0% within 120 days, and relative depth
predicts subsequent allocation. On the same 17,778 contestable routes, the
price coefficient changes from 10.56 pp to 10.13 pp when capital enters, while
a 10 pp lagged capital-share advantage adds 2.77 pp. These are central
estimates. The missing economic link is dynamic: how quickly an incumbent yields
after the challenger crosses the exact-output ranking at different depth levels.

### Experiment order and promotion gates

| Order | Analysis | Required inputs | Main-text gate | Current disposition |
|---|---|---|---|---|
| 1 | Exact-chain route sensitivity | Existing reconciliation ledgers and reconstructed audited dates | Report how chain corrections change pair, vehicle, topology, and headline shares | Running on Studio; technical appendix unless conclusions move |
| 2 | Pair lifecycle accounting | Existing all-history pair support and 2024/2026 decomposition | Entry, reactivation, role turnover, and exit add exactly to the period-specific term | Passed; gross first-observed entry belongs in the central decomposition |
| 3 | Correct post-entry persistence | Existing entry and route panels | Entry day excluded; later trading explicit; stable across pair and activity weights | Passed; main text |
| 4 | Prior-information bridge formation | Existing route-share and capital panels | Event date uses only lagged information; adoption timing and continuous depth reported | Passed; main text |
| 5 | Exact first-vehicle choice | Exact pretrade prices, prior weak-leg capital, and material entrants | Both paths feasible at entry; price and depth estimated separately and together | Next Studio build; closes the entry-selection gap |
| 6 | Price-rank crossings and incumbent response | Existing monthly exact-price and capital panels | Event dated without future information; challenger depth stratified; reverse crossings and placebo dates | Next Studio estimate; highest return per unit of compute |
| 7 | Same-sample price and capital choice | Existing exact-price, bridge-depth, and entry panels | Identical opportunity sample; interpretable magnitudes; pair/date effects | Passed; main text |
| 8 | Dynamic route-use and bridge-depth relation | Existing route-share and capital panels | No mechanical coupling; initial states, time-reversed benchmarks, and alternative horizons pass | Appendix boundary because time reversal also predicts outcomes |
| 9 | Cost of retaining the incumbent | Exact-price panel and a reproducible receipt-gas panel | Same-size rival path; route- and value-weighted magnitude; gas bounds | Gross comparison passed; build the missing gas producer before the final consequence table |
| 10 | LP returns and bridge formation | Prior fees, relative-price risk, capital, and material-token prices | Net-return proxy predicts later capital beyond initial depth and demand | Gated Studio extension; otherwise divergence loss remains an interpretation |
| 11 | USDC shock exposure | Existing routes, prices, and capital; targeted refetch only if a field is missing | Pair-level exposure, pretrends, comparison group, and flow restrictions | Gated; run only if the comparison design clears the stated bar |
| 12 | Executable network centrality | Exact-state monthly graph, price/depth/gas edge costs, material tokens | Predicts first vehicle or later route use beyond degree and unweighted betweenness | Gated extension; raw betweenness alone stays supporting evidence |

The first LP-risk pass finds that lower prior endpoint--vehicle relative-price
risk predicts deeper full-range constant-product bridge capital. It does not
explain the stablecoin rotation: stablecoin bridges have higher median relative
volatility than WETH bridges in the comparable pair-month sample. This result
can bound the divergence-loss interpretation in the appendix; it does not earn
a main-text mechanism slot unless a later design adds provider returns or
exogenous supply variation.

Every promoted regression must identify its unit, risk set, variation,
conditioning set, weighting, fixed effects, clustering, economic magnitude, and
strongest rival explanation. A conventional table places specifications in
columns and reports sample size, effects, and fit; a collection of unrelated
one-coefficient rows is not a substitute.

### Appendix rule

An appendix exhibit must be consumed by a named main-text result through one of
four roles: derivation, measurement validation, alternative sample, or
robustness. The route-boundary checks, quoter validation, coverage, adjacent-year
decompositions, endpoint restrictions, and venue/pricing-family checks meet this
rule. The V3/V4 participation and flash-accounting tables do not support the
present chain closely enough; preserve their scripts and outputs outside the
manuscript for a possible separate study rather than using the appendix as a
result archive.

## Resolve before caveating

For every central result, list serious alternative explanations, measurement
limits, and interpretive steps. A missing field, stale fetch, incomplete
crosswalk, or rebuildable historical input is a data task. A testable
interpretation becomes a focused analysis using the most direct object available:
exact repricing for price alternatives, decomposition for accounting margins,
transition matrices for switching, event time for sequencing, and regression
when conditioning or variation is the question. Retain a limitation only when
identification, unobserved intent, unavailable external data, or disproportionate
scope prevents a useful test.

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

The direct stablecoin-versus-WETH comparison quotes the best path in each family
independently. At least 120 days after pair entry, the entry vehicle carries
93.4% of routes when its path leads by more than one basis point and 22.4% across
8,807 routes in 1,311 pairs when the other family leads. Pair-day weighting gives
94.6% and 24.5%. This split shows that current public price leadership strongly
conditions persistence associated with the first vehicle. Gas, private order
flow, omitted venues, and behavior remain possible sources of the residual.

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

# Research questions and empirical design

This note explains the current paper design. The executable definitions are in
[`../specifications/confirmatory.json`](../specifications/confirmatory.json), and
the current numerical results are in [`../findings/`](../findings/README.md).
Ideas that are not in those two places are future work, not unfinished parts of
the present paper.

## JFE depth revision

The paper now needs a deeper economic spine, not a longer inventory of results.
Route reconstruction and the aggregate decomposition remain essential because
they establish the empirical object and the central fact. Their presentation,
however, should be compact enough to leave the main body for the questions that
follow: which vehicle wins a contestable route, why an established vehicle
persists, how liquidity responds, and what the persistence costs or protects.

The revision follows one connected loop:

```text
aggregate rotation and pair composition
  -> routes on which stablecoins and WETH are both feasible
  -> current price and weak-leg depth determine vehicle choice
  -> entry state versus persistence after entry
  -> subsequent route use and bridge capital
  -> execution-cost and risk consequences
  -> rival explanation or unresolved implication
       -> directly observable: test it and rebuild the chain
       -> unobservable or disproportionate: state the remaining boundary
  -> rebuild paper -> deck -> speaking notes -> paper until they agree
```

This is focus by hierarchy rather than deletion. A result belongs in the main
text when it advances the chain. Technical derivations, validation, alternative
samples, and robustness checks belong in the appendix. An unrelated significant
coefficient belongs in neither place; its code and output can remain available
for a later paper.

### Main-text evidence

1. **Central fact.** Keep one all-route rotation figure and one compact exact
   pair-composition table. Fold the current before/after share table into these
   exhibits. Report gross movements in both directions so the near-zero net
   within-pair term is not mistaken for an absence of switching.
2. **Contestable vehicle choice.** On routes for which stablecoin and WETH paths
   are both feasible at the same input, state, and public venue set, estimate
   stablecoin choice as a function of the stablecoin path's output advantage,
   relative weak-leg depth, the vehicle used at pair entry, and their
   interactions. Use a conventional column ladder with pair and date effects,
   trade-size and venue-access controls, and pair/date clustered inference.
3. **Persistence after entry.** Rebuild the current entry regressions because the
   existing outcome includes the entry day. Measure days 1--30 and 31--120
   separately, require and report later trading, show pair- and activity-weighted
   estimates, and ask whether entry identity still predicts use once the rival
   route becomes comparably deep and cheaper.
4. **Liquidity formation.** Retain the continuous weak-leg-depth relation and
   pool-capital path. Strengthen the bidirectional route-use/depth forecasts with
   bridge and date effects, flexible initial states, exact horizons,
   time-reversed benchmarks, and alternative weights. Describe these as
   equilibrium relations unless a design supplies external variation.
5. **Financial consequence.** For each contestable route, measure the gross
   output lost or gained relative to the feasible rival vehicle. Report economic
   magnitudes by pair age, incumbent identity, trade size, and challenger depth,
   with transparent gas bounds. This gives persistence a financial consequence.
6. **Risk transmission, conditional on evidence.** Use the March 2023 USDC shock
   only if a pair-level exposure design has credible pre-trends and survives
   restrictions for dust, round trips, and automated flow. Otherwise retain the
   aggregate episode as motivation or omit it.

The current bridge-choice estimates and exact-price comparison already warrant
the second step. A vehicle with the deepest weak leg carries most route mass,
and incumbent retention changes sharply with contemporaneous price leadership.
The joint price--depth--incumbency model is therefore the first new central
estimate; it does not require another raw-data fetch.

### Experiment order and promotion gates

| Order | Analysis | Required inputs | Main-text gate | Current disposition |
|---|---|---|---|---|
| 1 | Correct post-entry persistence | Existing entry and route panels | Entry day excluded; later trading explicit; stable across pair and activity weights | Passed; main text |
| 2 | Joint price, depth, and incumbency choice | Existing exact-price, bridge-depth, and entry panels on Studio | Same opportunity and pre-trade state; interpretable magnitudes; pair/date effects | Passed; main text |
| 3 | Dynamic route-use and bridge-depth relation | Existing route-share and capital panels | No mechanical coupling; initial states, time-reversed benchmarks, and alternative horizons pass | Corrected; appendix boundary because time reversal also predicts outcomes |
| 4 | Cost of retaining the incumbent | Existing exact-price panel | Same-size rival path; route- and value-weighted economic magnitude; gas bounds | Passed gross-of-gas comparison; main text with gas boundary |
| 5 | USDC shock exposure | Existing routes, prices, and capital; targeted refetch only if a field is missing | Pair-level exposure, pre-trends, comparison group, and flow restrictions | Gated; run only if the comparison design clears the stated bar |
| 6 | LP risk and supply | Existing prices, volumes, fees, and capital if coverage aligns | Within-opportunity divergence-risk or volatility measure adds information beyond demand and fees | Completed; appendix because risk locates depth but does not explain the aggregate rotation |

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

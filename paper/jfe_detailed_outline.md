# JFE Detailed Outline - The Making of Vehicle Currencies

Target title: **The Making of Vehicle Currencies: Evidence from DeFi**

Purpose: restructure the paper around a JFE-compatible architecture after checking
the downloaded vehicle-currency, liquidity, DeFi, and stablecoin-run literature,
with particular weight on the JFE papers in the corpus:

- Eren and Malamud (2022), *Journal of Financial Economics*, "Dominant Currency Debt"
- Makarov and Schoar (2020), *Journal of Financial Economics*, "Trading and Arbitrage in Cryptocurrency Markets"
- Chordia, Roll, and Subrahmanyam (2000), *Journal of Financial Economics*, "Commonality in Liquidity"

The JFE lesson is structural: a compact 5-8 section paper, a long economic
introduction, related literature integrated in the introduction, a model or
framework before the tests, results grouped by economic mechanism rather than by
script output, and self-contained captions. The current DDC draft has the raw
material, but its results section is too long and mixes main findings,
identification checks, diagnostics, returns, depeg, V4, and support material under
one top-level heading. The revised structure below turns the paper into a
vehicle-currency formation and stickiness paper.

## Core Claim

DeFi reveals how vehicle currencies form, persist, and sometimes lose share
because every routed trade records the source asset, destination asset,
intermediate vehicle, route cost, and settlement implementation. Vehicle dominance
is sticky because liquidity and routing externalities concentrate execution around
an incumbent. It changes in three ways:

1. **Gradual change** as pair liquidity and route opportunity migrate across base
   assets.
2. **Stress-state rotation** when risk makes the inherited vehicle less attractive
   and safer stable assets become better routes.
3. **Architecture shocks** when protocol design changes the feasible route set or
   the gross settlement movement required by a route.

This claim fits the downloaded literature: Krugman (1980) supplies the cheapest
route/vehicle idea; Dowd and Greenaway (1993) supply network externalities and
switching costs; Gopinath and Stein (2021), Gopinath et al. (2020), Amiti et al.
(2022), Mukhin (2022), Eren and Malamud (2022), and Somogyi (2026) supply the
dominant-currency and vehicle-currency comparison; Chordia et al. (2000),
Pastor and Stambaugh (2003), Brunnermeier and Pedersen (2009), and Baele et al.
(2020) supply liquidity commonality and flight-to-safety discipline; Makarov and
Schoar (2020, 2022), Schar (2021), Daian et al. (2020), and Lehar and Parlour
(2024) anchor the crypto/DEX setting; Catalini et al. (2022), Lyons et al. (2023),
Gorton and Zhang (2023), Anadu et al. (2023), Liu et al. (2023), and Uhlig (2022)
discipline the stablecoin safety shock.

## Main Paper Structure

### 1. Introduction

**Goal:** make the paper legible to a JFE reader before the data machinery appears.
The introduction should be long, thesis-first, and result-sequential. No standalone
top-level literature review.

#### 1.1 Motivation: vehicle currencies are liquidity institutions

Open with the core economic problem: traders often exchange A for C through B
because B is the cheaper, deeper, more widely paired route. In FX, the dollar is
the canonical vehicle. In DeFi, the same role is visible transaction by transaction.

#### 1.2 Identification problem in fiat markets

Explain why fiat vehicle-currency formation is hard to study: route choice is
opaque, transitions are rare, the incumbent is sticky, and market architecture does
not change on an observable block.

#### 1.3 DeFi laboratory

State the laboratory clearly: many assets compete, AMM liquidity is observable,
routes are public, and protocol architecture changes create dated shocks to the
route technology.

#### 1.4 Findings in order

Use prose "First, Second, Third" signposting:

- First, vehicle use is concentrated and persistent, consistent with thick-market
  and network-externality forces.
- Second, stress rotates route choice away from the risky inherited vehicle, WETH,
  toward safer stable assets within common source-destination opportunities.
- Third, architecture changes alter vehicle use and settlement implementation: V3
  changes pairwise depth and route feasibility; V4 lets a route token remain in the
  path while gross ERC-20 movement is netted away.

#### 1.5 Contribution

Frame the contribution as identification of vehicle-currency formation and
stickiness, not a broad ranking of "dominant currencies" across all monetary roles.
The broad literature analogy is retained, but the empirical claim is scoped to
vehicle routes, endpoint settlement pressure, and settlement implementation in
DEXs.

#### 1.6 Related literature integrated in the introduction

Keep three prose paragraphs:

- Dominant and vehicle currencies: Krugman; Dowd and Greenaway; Gopinath et al.;
  Gopinath and Stein; Amiti et al.; Mukhin; Eren and Malamud; Somogyi.
- Liquidity, commonality, and flight to safety: Chordia et al.; Pastor and
  Stambaugh; Brunnermeier and Pedersen; Baele et al.
- DeFi, AMMs, arbitrage, and stablecoins: Makarov and Schoar; Schar; Lehar and
  Parlour; Daian et al.; Catalini et al.; Lyons et al.; Gorton and Zhang; Anadu et
  al.; Liu et al.; Uhlig.

#### 1.7 Roadmap

Roadmap should mirror the final section order exactly.

### 2. Institutional Setting, Data, and Measurement

**Goal:** give enough route, venue, and measurement detail for trust, while moving
diagnostics to the appendix.

#### 2.1 AMM routes and the vehicle-currency role

Define direct routes, multi-hop routes, split routes, and loop routes. A token is a
vehicle only when it is an intermediate, not the source or destination. This section
should cite Krugman (1980), Somogyi (2026), Daian et al. (2020), Makarov and
Schoar (2022), and Lehar and Parlour (2024).

#### 2.2 Raw swap and route reconstruction

Describe raw swap records, transaction hash grouping, log-index ordering, route
components, stablecoin-anchored repricing, and artifact filters. Keep the full
validation battery in the appendix, but state the central reliability checks.

#### 2.3 Measurement universes

Separate the full route-measurement network from the coefficient-bearing samples.
This responds directly to prior referee confusion about sample accounting.

#### 2.4 Vehicle, endpoint, and settlement-implementation measures

Define:

- vehicle share: share of routes using token B as a pure intermediate;
- route betweenness: centrality of token B in the route network;
- endpoint share: share of route endpoints held by a token;
- settlement implementation: whether an intermediate token emits a gross ERC-20
  transfer or is internally netted.

#### 2.5 Descriptive vehicle dominance and persistence

Move concentration and lead-lag evidence out of a generic measurement section and
into the economic question: WETH is the inherited vehicle; stablecoins become
increasingly important route assets; vehicle shares are persistent.

### 3. Framework: Liquidity, Network Externalities, and Architecture

**Goal:** model or conceptual framework before tests, as JFE expects. This section
should discipline the results and replace the old "framework for routing
architecture" if it reads like a late rationalization.

#### 3.1 Route choice with liquidity and price impact

A router chooses the path that maximizes output net of pool fees and price impact.
The vehicle role belongs to the token that makes indirect exchange cheaper than
direct exchange. This maps directly to Krugman (1980), Somogyi (2026), and the AMM
literature.

#### 3.2 Thick markets, network externalities, and switching costs

Liquidity supplied against the incumbent deepens its pairs, lowering future route
costs and creating persistence. Dowd and Greenaway (1993) give the switching-cost
and network-externality logic. Chordia et al. (2000) and Brunnermeier and Pedersen
(2009) justify why liquidity can move together under stress.

#### 3.3 Stress shocks

Stress changes the risk and balance-sheet value of candidate vehicles. Prediction:
when the inherited vehicle is risky, downside stress reduces its vehicle share
within common route opportunities and raises safe-token intermediation.

#### 3.4 Reserve shocks

A reserve impairment changes endpoint safety. Prediction: a stablecoin depeg
causes route-endpoint flow out of the impaired token and creates persistent
endpoint pressure, but does not mechanically imply tipping to a single substitute
when several substitutes can clear.

#### 3.5 Architecture shocks

Protocol design changes route feasibility and settlement implementation. Prediction:
V3-style concentrated liquidity changes the cost of using direct versus vehicle
routes; V4-style internal netting separates route appearance from gross settlement
movement.

#### 3.6 Proposition summary

Use three propositions, not long H1/H1a/H2 notation:

- **Proposition 1: Vehicle liquidity and stickiness.** Vehicle share is persistent
  and concentrated because liquidity supplied against a base asset lowers future
  route costs.
- **Proposition 2: Stress-state vehicle rotation.** Downside stress reduces use of
  a risky incumbent vehicle relative to safer substitutes within common route
  opportunities.
- **Proposition 3: Architecture and settlement implementation.** Architecture
  changes can alter the mapping from route use to gross token movement, allowing a
  token to remain a route unit while physical settlement is netted.

### 4. Formation and Stickiness of the Vehicle Role

**Goal:** make "making" and "stickiness" the first empirical object, before stress
events.

#### 4.1 Baseline vehicle concentration

Show that route intermediation is highly concentrated relative to endpoint use and
that WETH starts as the inherited Ethereum vehicle.

#### 4.2 Gradual change in vehicle use

Document the secular movement from WETH-only intermediation toward stablecoin route
assets. This section should distinguish gradual liquidity migration from sudden
stress rotation.

#### 4.3 Persistence and inertia

Estimate persistence in vehicle share or route betweenness: transition matrices,
AR persistence, half-life, or share recovery after shocks. Tie this directly to
Dowd and Greenaway (switching costs/network externalities) and the currency-inertia
literature.

#### 4.4 Liquidity supply against the vehicle

Use pool depth or paired-liquidity concentration to show that liquidity is provided
against the vehicle. This is the missing "vehicle route much better than direct
route" foundation: vehicle status should be visible not only in executed routes but
in the liquidity graph that makes those routes cheap.

### 5. Stress-State Vehicle Rotation

**Goal:** make the WETH-to-stable rotation the central identification section.
This section should absorb what is now spread across many results subsections.

#### 5.1 Daily severity design

Use the full daily panel: WETH gap against the stable layer falls monotonically with
ETH downside severity. Keep WBTC as placebo.

#### 5.2 Hourly event anatomy

Use named stress windows as anatomy, not as the sole source of identification.
Show sign consistency across episodes, leave-one-out stability, and risk-on
placebos.

#### 5.3 Common-support route opportunities

Place the common-support design immediately after the dose response. This is the
referee-facing identification fix: same source-destination pair, both WETH and
non-WETH opportunities observed before the shock, baseline-normalized WETH share.

#### 5.4 Executed route costs

Use the V3 executed route-cost opportunity test to show the rotation is not simply
composition, route length, or fee-tier drift.

#### 5.5 Road-not-taken counterfactual

Present the quoter and counterfactual validation after the common-support and
executed-cost evidence. The road-not-taken result should be interpreted as the
price/cost consequence of vehicle rotation under stress, not as a separate paper
inside the paper.

#### 5.6 Recovery and stickiness after stress

Close the section by showing whether WETH share mean-reverts after stress. This
connects the stress design back to "stickiness" rather than leaving it as an event
study.

### 6. Reserve Credibility and Settlement Endpoint Flight

**Goal:** keep the USDC depeg because it is strong and finance-relevant, but scope
it as endpoint settlement safety, not as the whole paper's main vehicle result.

#### 6.1 The USDC/SVB depeg as reserve-safety shock

Explain the exogenous trigger, the within-event reversal, and the on-chain price
measurement from USDC/USDT ticks.

#### 6.2 Endpoint flow out of the impaired settlement token

Report hourly net flow out of USDC into substitute stablecoins during the widening
phase and the normal-times/block-placebo comparison.

#### 6.3 Persistence of endpoint pressure

Cumulate route-endpoint flow into route-implied endpoint pressure. Be explicit that
this is not wallet holdings. This responds to prior reviewer concerns.

#### 6.4 Substitution rather than automatic tipping

Use the settlement-substitution table to show that flow disperses across several
substitutes. This is economically useful because it disciplines the
strategic-complementarity/tipping claim.

#### 6.5 Cross-sectional safety in busts

If the determinant/return evidence is retained, place the safe-token bust
association here as supporting evidence for reserve credibility and safety demand,
not as a separate "determinants" paper.

### 7. Architecture Shocks and Settlement Implementation

**Goal:** integrate V3/V4 as architecture evidence rather than a late add-on.

#### 7.1 V2 to V3: concentrated liquidity and route feasibility

If the data support it, use V3 launch/concentrated liquidity as the architecture
shock that changes pairwise depth and therefore the need for vehicle routes. This
is the cleanest match to "gradual versus sudden/architectural change." If the
analysis is not yet built, state it as the natural extension and keep V4 as the
implemented architecture result.

#### 7.2 V4 flash accounting and route-token settlement

Present the matched endpoint-pair-week-intermediate design. The key first stage:
holding the route unit fixed, V4 sharply reduces gross ERC-20 transfer incidence
for the intermediate token.

#### 7.3 Route composition around V4

Keep V4 route-composition changes as descriptive diagnostics unless stronger
identification is built. Do not overclaim pool creation or hook design as
randomized.

#### 7.4 Settlement netting under stress

Report netting shares and stress patterns as descriptive. The identified claim is
the matched receipt wedge, not a causal stress coefficient.

### 8. Pricing Implications and Conclusion

**Goal:** end with the finance implication and a concise conclusion. JFE needs a
"why prices/finance readers care" payoff, but this should not reopen a separate
asset-pricing paper.

#### 8.1 Convenience yield of vehicle/liquidity services

Keep the conditional return-sort result if it remains robust: dominance services
are valuable in states where route liquidity is scarce, so high-dominance tokens
earn lower subsequent returns in boom/scarcity states. Present unconditional factor
pricing as a diagnostic in the appendix.

#### 8.2 What DeFi teaches about vehicle currencies

State the general lesson: vehicle currencies are liquidity institutions whose
dominance persists through network externalities, rotates under stress, and is
reshaped by architecture.

#### 8.3 Limits and external validity

One tight paragraph: crypto assets are not sovereign currencies; the claim is not
that DeFi is the global dollar system. The contribution is that DeFi reveals the
route-level mechanisms that fiat markets usually hide.

#### 8.4 Conclusion

Short, no new results. Return to the title: how a vehicle currency is made, why it
sticks, and what changes it.

## Main Exhibit Spine

Keep the main paper exhibit count tight. Heavy validation, alternative
specifications, determinant batteries, return diagnostics, and venue-composition
details belong in the online appendix.

### Figure 1. Routed exchange and monetary roles in an AMM network

Brief caption: The figure illustrates direct, indirect, split, and loop routes in
AMM-based DEXs. A token is counted as a vehicle only when it is an intermediate,
not the source or destination. The same transaction identifies vehicle use,
endpoint settlement flow, and, where receipts are available, gross versus net
settlement implementation.

### Table 1. Measurement and estimation universes

Brief caption: The table separates the full reconstructed route network from the
coefficient-bearing samples used in the vehicle-rotation, depeg, architecture, and
pricing tests. This prevents readers from confusing network-measurement tokens
with regression cross-sectional units.

### Figure 2. Vehicle-currency concentration and gradual change

Brief caption: Weekly vehicle-route shares for WETH, USDC, USDT, and other major
tokens. The figure documents the inherited WETH vehicle role, the rise of
stablecoin route assets, and the difference between gradual liquidity migration
and sharp stress episodes.

### Table 2. Persistence and concentration of vehicle use

Brief caption: Persistence, concentration, and transition measures for vehicle
shares. The table reports concentration of route intermediation, persistence of
token vehicle shares, and recovery/half-life statistics after stress episodes.

### Figure 3. Liquidity supplied against vehicle assets

Brief caption: Pair-liquidity concentration by base asset. The figure shows that
liquidity is disproportionately provided against vehicle assets, which makes
indirect routes through the vehicle cheaper than thin direct routes.

### Table 3. Daily vehicle-rotation dose response

Brief caption: Daily fixed-effects estimates of WETH vehicle-share or betweenness
loss as ETH downside severity rises. WBTC is included as a placebo and the stable
layer as the safe substitute benchmark.

### Table 4. Common-support WETH route rotation

Brief caption: Baseline-normalized route-share changes within source-destination
pair-episodes that used both WETH and non-WETH intermediaries before the stress
anchor. The coefficient identifies WETH losing share relative to observed
substitute intermediaries within the same route opportunity set.

### Table 5. Executed route costs and road-not-taken validation

Brief caption: Route-cost and quoter-validation evidence for the vehicle rotation.
The table reports executed V3 route-cost controls, reproduction accuracy for
observed swaps, and filtered road-not-taken premiums showing the cost consequence
of routing away from the inherited vehicle under stress.

### Figure 4. Stress anatomy and recovery of WETH vehicle share

Brief caption: Event-time WETH vehicle share around stress episodes, with
pre-anchor normalization and post-event recovery. The figure shows the rotation
timing and whether the incumbent returns to baseline after stress.

### Figure 5. The USDC depeg as settlement endpoint shock

Brief caption: USDC's on-chain price during the March 2023 SVB depeg and hourly
net route-endpoint flow into or out of USDC. Negative bars record flight from the
impaired stablecoin; the price line supplies the within-event shock timing.

### Table 6. Persistence and dispersion of endpoint flight

Brief caption: Cumulative route-endpoint pressure out of USDC and substitution
shares across stablecoin recipients. The table distinguishes persistent route
pressure from wallet holdings and shows that flow disperses across several
substitutes rather than tipping automatically to one stablecoin.

### Table 7. V4 matched settlement-implementation first stage

Brief caption: Matched route-unit cells by endpoint pair, week, and intermediate
token compare V3 and V4. The table reports gross-exposure nettable share and the
incidence of matching ERC-20 transfer receipts, showing that V4 sharply reduces
physical intermediate-token movement for the same route unit.

### Table 8. Settlement netting on V4

Brief caption: Token-level netted shares for clean V4 routes, with adoption and
stress diagnostics. The table is descriptive; the causal architecture claim is the
matched V3/V4 receipt wedge in Table 7.

### Table 9. State-dependent convenience yield

Brief caption: Conditional return sorts by vehicle or dominance measures. The
table reports whether tokens with stronger route-liquidity services earn lower
subsequent returns in states where the service is scarce; unconditional factor
tests move to the appendix.

## Appendix Placement

Move the following out of the main paper unless a referee specifically needs them
for the central claim:

- DEX venue composition and long sample-construction diagnostics.
- Full route-reconstruction validation and raw conservation checks.
- Alternative stress thresholds and all per-episode tables beyond the sign-pattern
  summary.
- Long determinant robustness batteries.
- Unconditional factor-pricing diagnostics.
- Money-market, Compound/Aave, collateral, and lending-access diagnostics.
- V4 route-composition rows that are descriptive rather than identified.
- Heatmaps, lead-lag cross-autocorrelations, and auxiliary concentration figures.

## Implementation Notes for the Manuscript

1. Retitle from "Dominant Currencies" to "Vehicle Currencies" unless the paper
   adds broader sovereign-style evidence. "Dominant" still belongs in the
   literature framing, not the empirical title.
2. Collapse the old one-piece Results section into mechanism sections: formation
   and stickiness, stress rotation, reserve credibility, architecture, and pricing.
3. Avoid a top-level "Literature Review." Keep the literature in the introduction
   and in short local paragraphs where a mechanism is introduced.
4. Replace long H1/H1a notation with three propositions inside the framework.
5. Make every main exhibit caption standalone: sample, unit, variable, treatment,
   and interpretation in the caption.
6. Keep model/framework before empirical tests. JFE will punish a model that reads
   like a post-hoc audit.
7. Scope every broad claim to the margin identified: route vehicle, endpoint
   pressure, or settlement implementation.

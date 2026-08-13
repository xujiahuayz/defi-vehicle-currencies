# Paper spine: The Making of Dominant Vehicle Currencies: Evidence from DeFi

This file is the content memo for node G. It fixes the economic jobs, claim order, exhibit jobs, and open comparisons before publication prose is rewritten. It is not a draft to be polished sentence by sentence. The later rewrite reads the closest raw published JFE passages named in `docs/research-workflow.md`; corpus cards only locate those passages.

The current lead is the rotation of continuous vehicle use from the native platform asset toward stable numeraire assets. Cost dominance, liquidity allocation, routing search, persistence, and hysteresis are possible explanations or extensions. None defines the lead outcome. Calendar year locates the rotation in the sample. It does not identify the market design, technology, or balance-sheet feature that caused it.

## 1. Section architecture and argument order

The architecture is fact first and mechanism second. Makarov and Schoar move from measured dispersion to the market segmentation that can sustain it. Huang et al. introduce their model after the empirical facts it rationalises. Bolton and Kacperczyk organise the interpretation around rival mechanisms whose predictions are tested in sequence. Those raw passages license the ordering below; they do not supply a verbal template.

```
1. Introduction
2. Institutional setting, measurement, and data
   2.1 Decentralised exchange routes
   2.2 Definitions
   2.3 Route reconstruction and support
   2.4 Sample and validation
3. Rotation in vehicle use
   3.1 Aggregate count and value paths
   3.2 Endpoint-pair composition
   3.3 Endpoint demand and excess use
   3.4 Candidate and backing-design decomposition
4. Time, market design, and opportunity sets
   4.1 Venue integration and route complexity
   4.2 Protocol architecture entry, exit, and reversal
   4.3 Fixed opportunity-cell comparisons
5. Rival accounts of the rotation
   5.1 Routing technology and fragmented reach
   5.2 Liquidity placement
   5.3 Holding costs and backing design
   5.4 Software defaults and architectural mandates
   5.5 What survives
6. Persistence and reversal
   6.1 Incumbent retention after a state reversal
   6.2 Challenger displacement after a favourable state arrives
   6.3 Persistence, symmetric frictions, and hysteresis
7. Conclusion
```

Section 3 establishes the economic fact before assigning a mechanism. Section 4 asks whether designs prevalent at a date account for that fact and whether the relation reverses when exposure or feasible states reverse. Section 5 runs the remaining explanations as a horse race. Section 6 enters the paper only with comparable retention and displacement arms on one fixed risk set. Until then it remains a registered extension with no headline estimate.

## 2. Claims by section, with evidentiary status

`EXISTS` means a current generated exhibit or finding packet reports the object. `PENDING` means the specification is fixed here but the result cannot enter prose. An existing descriptive result may remain pending for a causal interpretation.

### 2.1 Section 1, Introduction

| Claim job | Evidence | Status | Interpretation boundary |
|---|---|---|---|
| Vehicle status is a route role, while dominance is the continuous extent of intermediary use. | Route definitions and vehicle-share exhibits. | EXISTS | The paper studies degree and composition, not the existence of one bridging route. |
| The intermediating asset rotates from native toward stable assets over the sample. | Quarterly and annual vehicle-share exhibits. | EXISTS | Calendar time describes the path. |
| The path contains an earlier stable-value lead, a reversal, and a renewed lead. | Quarterly strict-support value series. | EXISTS | A monotone trend is rejected descriptively. |
| The 2024 to 2026 aggregate rotation is allocated mainly to pair representation, admitted route-component activity, and realised vehicle incidence; stable-for-native substitution on common-role pairs is small. | `vehicle_transition_pair_decomposition.jsonl`. | EXISTS | The five factors form an exact descriptive Shapley allocation, not architecture, demand, preference, or opportunity effects. |
| USDT accounts for most of the 2024 to 2026 change within the stablecoin category. | Candidate excess-use and share-gap exhibits. | EXISTS | USDC and stablecoin backing designs remain separate. |
| Endpoint demand alone cannot account for the USDT movement. | Intermediary-minus-endpoint share-gap change, Holm value `(0.000)`, count `(0.015)`. | EXISTS | Endpoint netting removes proportional endpoint growth, not every composition change. |
| The economic question is which coordination, market-design, and balance-sheet mechanisms can produce this rotation. | Rival map in Sections 4 and 5. | EXISTS | No mechanism is assigned in the opening paragraph. |

### 2.2 Section 2, Institutional setting, measurement, and data

| Claim job | Evidence | Status | Interpretation boundary |
|---|---|---|---|
| A coherent directed swap component is one route unit. | Certified directed-route release. | EXISTS | Multi-leg and intermediated are separate classifications. |
| Sequential intermediation is separated from direct splitting and canonical endpoint round trips. | Route-quality and intermediation exhibits. | EXISTS | Round trips do not enter the endpoint-conversion denominator. |
| Count and value measure frequency and economic size on parallel support perimeters. | Intermediation-by-type panel. | EXISTS | Value uses the stated source-intermediary-sink amount-coherence restriction. |
| Endpoint use supplies the demand benchmark for excess vehicle use. | Vehicle excess-use producer. | EXISTS | The share gap is the primary inferential outcome. |
| The route release spans 2,332 calendar partitions, including typed empty days. | Current route-quality ledger. | EXISTS | Nonempty-day counts describe activity, not missing calendar support. |
| Eight routed venues enter topology, while exact counterfactual pricing has its own narrower state perimeter. | Release and state-support ledgers. | EXISTS | Topology coverage does not imply quote-state coverage. |
| Missing support is reported by count, value, time, venue, entity, and mechanism cell. | Coverage and provenance exhibits. | EXISTS | An immaterial random gap does not stop an observational result. |
| Exact-state panels admit a defect only after its economic exposure is bounded. | Materiality workflow and support ledger. | PENDING | Engineering completeness is not itself a paper result. |

### 2.3 Section 3, Rotation in vehicle use

| Claim job | Evidence | Status | Interpretation boundary |
|---|---|---|---|
| Stable share rises sharply from 2024 to 2026 by count and strict-support value. | `intermediation_by_type.jsonl`. | EXISTS | This is an endpoint-year comparison on common calendar support. |
| Native value share rebounds in 2023 and 2024 before falling again. | Quarterly vehicle-share figure. | EXISTS | The reversal is visible and remains part of the lead figure. |
| Stable value leads from 2025-Q1, while count leadership is later and not yet sustained. | Quarterly vehicle-share figure. | EXISTS | Frequency and economic dominance are separate margins. |
| Pair representation, admitted route-component activity, and realised vehicle incidence account for 94.9% of the pooled count increase. | Pair-composition decomposition, support, and panel. | EXISTS | A pair observed in one endpoint year is not necessarily a newly created or exited market. |
| The stable-share factor on common-role pairs is small by count, and stable share within continuing pairs barely changes in the separate supported-value identity. | Pair-composition decomposition. | EXISTS | Both results are exact descriptive accounting, not fixed-opportunity causal estimates. |
| Value rotation is driven primarily by changes in activity weights among continuing pairs, with a material year-specific-pair contribution. | Pair-composition decomposition. | EXISTS | Supported value is conditional on the 20% value-coherence perimeter. |
| Stable assets have excess intermediary use in 2026 while native assets fall below parity. | `vehicle_excess_use.jsonl`. | EXISTS | Ratios are reported only where endpoint support is positive. |
| USDC begins above excess-use parity and changes little. | Candidate transition figure. | EXISTS | USDC does not explain the transition slope. |
| USDT crosses parity on strict-support value and rises by count. | Candidate transition figure and transition inference. | EXISTS | The share gap carries inference; the ratio translates intensity. |
| Fiat-reserve stables carry most supported stable intermediary value. | Backing decomposition. | EXISTS | Concentration identifies a mechanism candidate, not a balance-sheet effect. |
| On-chain-collateralised and synthetic stables do not share the same magnitude. | Backing decomposition. | EXISTS | The paper avoids a homogeneous stablecoin mechanism. |

### 2.4 Section 4, Time, market design, and opportunity sets

| Claim job | Evidence | Status | Interpretation boundary |
|---|---|---|---|
| Stable share rises inside both single-venue and cross-venue route strata. | Pair-composition and integration rival exhibits. | EXISTS | Endpoint-pair composition and changes in activity weights account for the increases in both strata; stable share changes little within continuing pairs. |
| The 2024 to 2026 rise is larger across venues than within one venue. | Pair-composition and integration interaction exhibits. | EXISTS | Cross-venue value rotation relies more on year-specific pairs; the comparison does not fix opportunity. |
| Stable rotation appears within observed integration-by-complexity count cells. | Complexity rival exhibit. | EXISTS | Broad strata do not hold endpoint pairs, search quality, or feasible paths fixed. |
| Cross-venue reach expands while true intermediation contracts on balanced support. | Cross-venue routing exhibits. | EXISTS | The two margins move separately. |
| Falling intermediation does not reject routing maturation. | Joint reading of reach and intermediation. | EXISTS | Better search can find direct routes and activate dispersed stable liquidity. |
| Realised architecture entry and exit provide no isolated within-cell substitution event in the current audit. | Architecture transition support exhibit. | EXISTS | The null concerns support for the design, not the existence of architecture change. |
| A design effect requires independently measured availability or exact cost and depth states. | Registered fixed-cell design. | PENDING | Realised use of a design is endogenous exposure. |
| Time and design are separated within endpoint-pair, candidate, venue-reach, route-design, notional, and support cells. | Fixed-cell vehicle-rotation specification. | PENDING | Composition that enters or exits between years cannot identify the within-cell change. |
| Reversal is tested when a design or economic state disappears, weakens, or returns. | Reversal specification. | PENDING | A launch date alone cannot identify persistence or hysteresis. |

### 2.5 Section 5, Rival accounts of the rotation

| Account | Discriminating prediction | Evidence | Status |
|---|---|---|---|
| Routing technology and fragmented reach | Stable use rises within a fixed feasible set or after search efficiency is held fixed; direct-route discovery and stable-liquidity activation are reported separately. | Integration and complexity results; exact frontier pending. | PENDING |
| Liquidity placement | Candidate depth or capital leads later vehicle use within a fixed endpoint opportunity set. | Capital and direction-specific depth panels. | PENDING |
| Holding costs and backing design | The transition differs with volatility, depeg, redemption, or reserve design after opportunity is held fixed, with signs reversing under candidate-specific stress. | Backing decomposition exists; reversal tests pending. | PENDING |
| Software defaults and mandates | Role changes align with software reach or mandate changes and remain local to the affected software population. | V1 mandate withdrawal and architecture support audits. | EXISTS |
| Coordination persistence | Incumbent use responds less to an adverse state reversal than challenger use responds to a favourable state arrival. | Comparable retention and displacement arms. | PENDING |
| Horse-race conclusion | Each surviving account has one magnitude, one uncertainty statement, and one remaining interpretation boundary. | Table 5. | PENDING |

### 2.6 Section 6, Persistence and reversal

| Claim job | Evidence | Status | Interpretation boundary |
|---|---|---|---|
| Persistence is positive retention after the favourable state weakens or reverses. | Fixed pair-candidate retention arm. | PENDING | Duration alone is consistent with symmetric slow adjustment. |
| Displacement measures challenger adoption after a favourable state arrives. | Fixed pair-candidate displacement arm. | PENDING | Entry and retention use the same state and risk set. |
| Hysteresis is an asymmetry between the two response functions. | Joint retention-displacement test. | PENDING | No claim is made from one arm. |
| Cost-state reversal is priced at exact transaction state and realised size. | Transaction-state frontier. | PENDING | Hour or day state cannot license a route-level mechanism claim. |
| Architecture reversal distinguishes exposure loss from vehicle-role loss. | Availability and exact-state reversal panel. | PENDING | Design exit does not necessarily remove the vehicle role or feasible design. |

### 2.7 Section 7, Conclusion

| Claim job | Evidence | Status | Interpretation boundary |
|---|---|---|---|
| Restate the rotation, candidate margin, and non-monotone path. | Section 3 admitted exhibits. | EXISTS | No chronology-to-causality upgrade. |
| State which composition accounts fail as complete explanations. | Section 4 admitted exhibits. | EXISTS | Partial mechanisms can remain viable. |
| State which mechanism tests survive and report nulls. | Section 5 horse race. | PENDING | The conclusion follows the strength of each design. |
| State persistence or hysteresis only if both arms clear. | Section 6 joint test. | PENDING | Otherwise the paper closes on rotation and its mechanism bounds. |

## 3. Definitions for Section 2.2

**Definition 1, route unit.** A route is one directed economic swap component within a transaction, from source token to sink token, after direct splits and sequential legs have been joined by causal order.

**Definition 2, intermediary.** Token $k$ is an intermediary on route $r:i\rightarrow k\rightarrow o$ when $k$ is neither endpoint and the directed legs form a sequential conversion from $i$ to $o$.

**Definition 3, vehicle status.** Candidate $k$ has vehicle status on a route when it is the observed intermediary. Status is binary at route level.

**Definition 4, vehicle dominance.** Vehicle dominance is a candidate's continuous share of intermediary use within a stated candidate and route perimeter.

**Definition 5, count share.** Count share gives every admitted route one unit of weight and measures the frequency with which a candidate carries the intermediary role.

**Definition 6, value share.** Value share weights admitted routes by comparable dollar value on the stated source-intermediary-sink support perimeter.

**Definition 7, endpoint demand.** Endpoint demand is a candidate's share of route endpoints on the same route, candidate, time, and support perimeter used for intermediary use.

**Definition 8, excess use.** The share gap is intermediary share minus endpoint share. The excess-use ratio is intermediary share divided by endpoint share when endpoint share is positive. The gap is primary for inference; the ratio reports relative intensity.

**Definition 9, integration scope.** A sequential route is single venue when both legs use the same venue and cross venue when the two legs use different venues.

**Definition 10, opportunity cell.** An opportunity cell fixes ordered endpoints, candidate identity, observed venue reach, route design, notional bin, value-support status, and the registered search-efficiency state.

**Definition 11, rotation.** Rotation is a change in the degree or composition of vehicle use across comparable periods or states. It does not require permanent replacement.

**Definition 12, persistence.** Persistence is retention of vehicle use after the state that favoured the incumbent weakens or reverses, measured on a fixed risk set.

**Definition 13, hysteresis.** Hysteresis is a weaker response to an adverse reversal for an incumbent than the response to a favourable state arrival for a challenger, measured with comparable retention and displacement arms.

## 4. Table and figure jobs

### Table 1. Sample, route classifications, and support

Rows report the route calendar, venue perimeter, route classes, candidate perimeter, count support, raw value, strict-support value, and exclusions by economic weight and concentration. It separates topology coverage from exact-state coverage.

### Table 2. Aggregate vehicle use

Panels report annual and selected quarterly count and strict-support value shares by asset type, together with the native-minus-stable change, calendar-HAC uncertainty, and common-day support.

### Table 3. Endpoint-normalised candidate use

Panels report intermediary share, endpoint share, share gap, and excess-use ratio for USDC and USDT in 2024 and 2026. The transition test is the change in the share gap. Ratios are translations and never replace the gap.

### Table 4. Endpoint-pair accounting and opportunity-set tests

The first panel reports the exact five-factor 2024--2026 count allocation across pair representation, vehicle-role support, admitted route-component activity, realised vehicle incidence, and the stable-share factor. The second retains the separate four-term supported-value accounting across continuing and year-specific endpoint pairs. Later panels move from broad venue-reach and complexity strata to the full opportunity cell, separating observed activity from architecture availability, exposure, and state reversals.

### Table 5. Rival mechanisms

Rows are routing technology, liquidity placement, holding and backing design, defaults and mandates, and coordination persistence. Columns are the separating prediction, estimate, economic magnitude, uncertainty, support, and conclusion.

### Table 6. Persistence and reversal

This table is absent until both retention and displacement arms are supported. If admitted, it reports response functions and a joint asymmetry test on one fixed pair-candidate risk set.

### Figures

1. One authentic directed transaction trace and the route unit it creates.
2. Quarterly count and value shares by asset type on common calendar support.
3. USDC and USDT 2024 to 2026 excess-use dumbbells around parity.
4. Endpoint-pair ribbon showing pair representation, admitted route-component activity, realised vehicle incidence, vehicle-role support, and the stable-share factor.
5. Fixed-opportunity decomposition of feasible activity, realised vehicle incidence, and stable share when the required cells are released.
6. Retention and displacement response functions, included only when both are admissible.

## 5. Named rival mechanisms

### 5.1 Routing technology and fragmented reach

Routing technology changes two margins with opposite predictions. It can discover direct liquidity and reduce intermediation, or connect fragmented spoke liquidity and make a stable intermediary more useful. The evidence therefore reports intermediation incidence separately from the composition of remaining intermediary routes. The mechanism survives only if stable use remains after feasible paths, observed reach, complexity, and search efficiency are held fixed.

### 5.2 Liquidity placement

Vehicle use can follow capital and executable depth, while capital can also follow expected routing demand. The separating evidence is timing within a fixed endpoint opportunity set: independently valued deposited capital and direction-specific executable depth must lead later vehicle use for liquidity supply to explain the rotation. Contemporaneous capital is a mechanism outcome and cannot enter as a routine control.

### 5.3 Holding costs and backing design

Lower volatility or redemption risk can make a stable intermediary attractive when it must be held between legs. A common stablecoin coefficient cannot test that account because fiat-reserve, on-chain-collateralised, and synthetic claims have different balance sheets. Candidate-specific stress and design changes supply the required sign reversals. Current fiat-reserve concentration motivates the test and does not identify it.

### 5.4 Software defaults and architectural mandates

Software reach and protocol architecture can coordinate routing without a change in monetary demand. The V1 to V2 mandate withdrawal provides one bounded null, while later architecture entry and exit remain selected exposure events. A convincing test holds the feasible set fixed, measures availability independently of realised use, and asks whether an effect is local to software populations whose reach changed.

### 5.5 What survives

The section closes by ranking accounts on completed separating tests. A null is reported with the same prominence as a positive result. A partial account may remain viable after it fails as a complete explanation. The final paragraph states the narrowest economic conclusion licensed by the strongest surviving comparison and names the next unresolved mechanism only when it motivates Section 6.

## What G needs from F

1. Preserve the current certified endpoint-pair accounting and its exact count/value identities in every downstream refresh.
2. Separate admitted pair-ledger activity, realised vehicle-route incidence, and stable choice on pairs observed in both endpoint years before attributing pair representation to opportunity or demand.
3. Run the full fixed-opportunity rotation design on ordered endpoint, candidate, venue reach, route design, notional, support, and search-efficiency state when those inputs are released.
4. Test dated architecture and software changes as measured exposures, with independent availability and reversal where the data support it.
5. Complete the exact transaction-state frontier before any cost-dominance or routing-efficiency mechanism enters the paper.
6. Build independently valued capital and direction-specific executable depth before testing the liquidity-placement sequence.
7. Produce retention and displacement on one risk set, or keep Section 6 free of an estimated hysteresis claim.
8. Rerun every promoted exhibit on one generation and complete two unchanged F-G passes before prose node P opens.

## What G needs from H

1. Keep pages 10 to 12 generated from the current route exhibits: annual paths, candidate dumbbells, and the endpoint-pair accounting ribbon.
2. Build the authentic transaction trace and its local replay from one admitted transaction, with a complete static PDF state.
3. Replace the two-architecture sketch with a V1 to V4 architecture sequence using verified institutional facts.
4. Add the sample funnel, protocol-state matrix, opportunity-set network, capital-depth cross-section, and exact-horizon diagram as their inputs become admissible.
5. Keep evidence status, source paths, and commit identities in comments and manifests; the rendered deck remains ready to present.
6. After every touch, run the semantic diff, focused producer tests, local compile, audience-language audit, full contact sheet, and changed-page inspection.

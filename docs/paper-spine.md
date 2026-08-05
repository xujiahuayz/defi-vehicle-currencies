# Paper spine: The Making of Dominant Vehicle Currencies: Evidence from DeFi

Node G output, 2026-08-06. Supersedes `paper/jfe_detailed_outline.md`, which targeted the pre-decision title, carried seven research questions against the design document's five, planned nine top-level sections, and stated four numbered propositions in the introduction. All four of those conflict with settled decisions or with the venue invariants measured below, and the superseded file is deleted in the same commit under the standing rule in `docs/research-workflow.md` section 0.

Lane, title, and the two-axis treatment of vehicle status are settled and are not reopened here. What this file decides is the section architecture, the claim inventory with its evidentiary status, the table shells, the definitions text, and the horse race. Everything marked PENDING names the specification that would produce it.

---

## 1. Section architecture, and the venue evidence for each choice

### 1.1 How the invariants below were measured

Nine published papers were read first-hand from `literature/papers/`, selected by confirming the journal from the PDF's own first page instead of from any list in this repository. Seven carry a *Journal of Financial Economics* imprint on the article page (Chordia, Roll and Subrahmanyam 2000; Coughenour and Saad 2004; Anand and Venkataraman 2016; Clark-Joseph, Ye and Zi 2017, published version; Makarov and Schoar 2020; Li, Wang and Ye 2021; Eren and Malamud 2022). Two more are JFE articles whose local copies predate or omit the modern article header. Amihud and Mendelson 1980 carries the volume imprint for Journal of Financial Economics 8 (1980), pages 31 to 53, on its own first page, with the journal name partly corrupted by the scan. Hendershott and Menkveld 2014 is an accepted manuscript with no imprint at all, and its inclusion rests on the publication record and not on anything visible in the file, which is stated here so a reader can discount it. Dropping it leaves eight papers and moves no count below by more than one unit. Structure was extracted by parsing every numbered heading and counting distinct table and figure references, with each abstract read in full and no summary of any paper consulted at any point.

The sample splits five pure empirical, two pure theory, two model-plus-data. That reproduces the bimodality node A reported from a different corpus, and among the two model-plus-data papers exactly one leads with theory, which reproduces node A's one-of-three. Hendershott and Menkveld put the empirics in section 2 under the title "Empirical identification of price pressure" and the model in section 3 under "A simple dynamic inventory control model to interpret", which is the facts-first configuration this paper would adopt if a model ever became necessary.

### 1.2 The invariants, with counts

| Invariant | Count in the nine papers read | Architectural consequence here |
|---|---|---|
| Conclusion is the last top-level section | 9 of 9 | Section 6 is the Conclusion |
| No standalone literature-review section | 9 of 9 | Differentiation sits in the introduction, one closing sentence per strand |
| No standalone identification or empirical-strategy section | 0 of 7 papers with data have one | No such section. Estimating equations appear inside the results subsection that uses them |
| No standalone robustness section | 0 of 9 | Robustness is a subsection of the result it defends (2.4, 3.4, 4.4, 5.5) or a footnote |
| Institutional setting or data is the section immediately after the introduction | 5 of 7 papers with data | Section 2 |
| Rival mechanism named in a section or subsection title | 3 of 7 papers with data, 4 titles | Section 5 and its subsections |
| Top-level section count | 4, 5, 5, 6, 6, 7, 7, 8, 9; median 6 | Six |
| Subsection nesting depth | Two levels in 6 of 9; three levels in 3 of 9 | Two levels everywhere |
| Abstract word count | 97, 99, 99, 102, 103, 103, 110; median 102 | Target 100, hard band 96 to 106 |
| Abstract contains a quantitative result | 1 of 7 | At most one magnitude, and only if it carries the whole argument |
| Abstract contains a t-statistic, sample size, or sample period | 0 of 7 | None |
| Tables in a paper with data | 4, 6, 7, 8, 9, 10, 12; median 8 | Eight main tables |
| Figures in a paper with data | 0, 2, 2, 4, 5, 7, 11; median 4 | Four main figures |
| Introduction as a share of body pages | 7%, 9%, 12%, 12%, 14%, 15%, 23%; median 12% | 12% of body, roughly 5.5 manuscript pages |

Two node A claims do not survive first-hand re-derivation on this sample and are corrected here. First, node A recorded that none of the fourteen exemplars has five top-level sections. Amihud and Mendelson have five and Hendershott and Menkveld have five, both JFE. The binding constraint is the plus-or-minus-two band around six, and a five-section paper is a live option. Second, node A recorded roughly seven figures for an empirical paper. The median in this sample is four, and Makarov and Schoar at eleven is the single outlier that pulls any mean upward. Four main figures against eight main tables is the calibrated target, and a paper carrying seven figures would sit at the top of the observed distribution with nothing gained.

One invariant deserves emphasis because it changes where our defensive material goes. Not one of the seven papers with data has a section titled robustness, identification, or empirical strategy. Coughenour and Saad place a specification check at 4.3, inside the results section it defends. Clark-Joseph, Ye and Zi place placebo tests at 3.2 and robustness checks at 4.2, each inside the section whose result is at risk. Anand and Venkataraman carry four robustness statements in footnotes. The architectural rule that follows is that a defence travels with the claim it defends, and a reader who doubts a number finds the answer on the same page.

### 1.3 The architecture

```
1. Introduction                                       ~5.5 manuscript pages, 12% of body
2. Institutional setting, definitions, and data
   2.1 What a route is, and who chooses it
   2.2 Definitions
   2.3 The route panel and how it was reconstructed
   2.4 Screens, filters, and what they remove
3. The transition in which asset intermediates        LEAD RESULT
   3.1 Which asset type carries the vehicle role
   3.2 Large trades moved first
   3.3 The feasible set that architecture fixes
   3.4 Measurement robustness and the unclassified residual
4. Pricing the road not taken
   4.1 The same-state cost frontier
   4.2 Cost-dominance windows
   4.3 Gas as a fixed cost
   4.4 Composition or asset role
5. Four rival accounts of the transition              THE HORSE RACE
   5.1 Thick-market cost advantage
   5.2 The cost of holding the intermediary
   5.3 Liquidity supply as the state variable
   5.4 Software defaults and the road already taken
   5.5 What survives
6. Conclusion
```

Why the horse race gets its own section instead of a subsection. Node A recorded the named-rival horse race as the craft pattern that substitutes for formal hypotheses in no-model empirical JFE papers, and my sample locates it at both levels: Clark-Joseph, Ye and Zi give it a whole section at 4 ("Distinguishing a DMM effect from a general NYSE effect") and a second at 6 ("Why do DMMs matter to the extent that they do?"), while Eren and Malamud give it a subsection at 3.4 ("Exchange-rate expectations or convenience yield"). A paper whose lead result is a description needs the rival accounts to carry the mechanism weight, which argues for the section-level treatment.

Why measurement rivals do not appear in section 5. Repricing artefacts, wash trading, taxonomy coverage and venue composition are threats to the measurement, and they are dispatched at 2.4, 3.4 and 4.4, alongside the numbers they threaten. Section 5 is reserved for accounts that would each be economically interesting if true.

---

## 2. Claims by section, with evidentiary status

Status is EXISTS when a `docs/finding-*.md` file in this repository reports the number, and PENDING when node F has not produced it. The mechanicalness column applies section 4's screen from the workflow: a claim is mechanical when its sign is fixed by construction, and a mechanical claim may support but may not lead.

### 2.1 Section 1, Introduction

The introduction narrates the whole argument in prose carrying no notation and previews every finding. Each literature strand closes with one differentiation sentence. It states no numbered proposition and lists no hypotheses, per 0 of 9 in the read sample.

| Claim the introduction must make | Supporting result | Status | Mechanical |
|---|---|---|---|
| The vehicle-currency question is about the extent to which one asset captures an intermediation role, and the role is continuous where the literature treats it as a label | Definitional, discharged at 2.2 | EXISTS | n/a |
| On-chain routing records the intermediate asset directly, which FX data do not | Institutional, `docs/router-identification-feasibility.md` on the route fields | EXISTS | n/a |
| The vehicle role migrated from the native platform asset to the stable numeraire inside six years, and the migration is observable in both directions | `docs/finding-intermediation-transition.md`, native 73.0% to 14.8% value-weighted, stable 21.2% to 50.1% | EXISTS | No |
| Large trades made the migration roughly four years before small trades | Same, value crossover 2022-Q1 sustained from 2022-Q4, count crossover only 2026-H1 | EXISTS | No |
| The state in which an incumbent holds the role while being strictly cost-dominated is observable on-chain and common | `docs/finding-cost-dominance-measured.md`, 17.9% of intermediated routes dominated gross of gas and 30.0% all-in | EXISTS | No |
| Whether the incumbent's apparent cost advantage is a property of its role or of which trades it carries is unresolved on the single-venue panel and is settled on the multi-venue panel | Same, pair-by-day fixed effects +0.094 (0.269) with 96.2% of the panel not contributing | EXISTS for the null; PENDING for the resolution | No |
| Removing a hard architectural mandate to use the native asset did not reduce native-asset pairing | `docs/finding-v1-forced-vehicle.md` section 3, new-pair WETH share 84.1% in 2020 rising to 97.9% in 2026 | EXISTS | No |
| Studying one venue becomes progressively wrong across the sample | `docs/router-identification-feasibility.md` cross-venue series, 1.2% to 61.1% count-weighted | EXISTS | Partly |
| No prior work connects DEX routing to the vehicle-currency question | `docs/research-workflow.md` section 4.0, four-lane prior-art sweep returning zero | EXISTS | n/a |

The introduction may not claim to resolve the inertia identification problem until section 4's all-in multi-venue frontier lands. That constraint was fixed in advance in `docs/finding-cost-dominance-not-yet-established.md` and it still binds on the leading claim of section 5.3.

### 2.2 Section 2, Institutional setting, definitions, and data

| Claim | Supporting result | Status | Mechanical |
|---|---|---|---|
| A route unit is the economic object, and one coherent multi-leg component is one route unit regardless of leg count | Registry definition of $r$ | EXISTS | n/a |
| Routing is executed by deterministic graph optimisers, which removes quote-time habit as a channel and relocates incumbency to state variables | `docs/research-workflow.md` section 4.0 | EXISTS | n/a |
| The executor is identifiable from the calling contract and the routing author is only partly recoverable | `docs/router-identification-feasibility.md`, 241 distinct senders on 74,323 swaps, `sender == origin` in 0 rows, executor population fragmenting to 397 senders by late 2025 with a hand registry covering 11.8% | EXISTS | No |
| The quoting engine reproduces executed swaps | Validation on record, 1,550 of 1,655 swaps within 1%, median absolute error 0.00 bp; `output/exhibits/v4_quoter_validation.jsonl` for the concentrated-liquidity extension | EXISTS for the two-hop single-venue quoter; PENDING for a published validation table on the multi-venue panel | n/a |
| Round-trip routes are atomic arbitrage or wash trading and are excluded | `docs/router-identification-feasibility.md`, 25.6% of multi-leg routes by count and 90.5% by value on the day inspected, and 0 of 18 post-2022 quarters invert after the filter | EXISTS | No |
| The reconstruction advantage is engineering difficulty and not private data | `docs/research-workflow.md` section 2, corrected from the retracted data-moat reading | EXISTS | n/a |

### 2.3 Section 3, The transition in which asset intermediates

| Claim | Supporting result | Status | Mechanical |
|---|---|---|---|
| The native share of intermediation falls and the stable share rises across the sample | Transition finding, count and value-weighted tables, 2,240 days | EXISTS | No |
| The value-weighted crossover arrives 2022-Q1 and is sustained from 2022-Q4 | Same | EXISTS | No |
| The count-weighted crossover appears only in 2026-H1 and cannot be called sustained | Same, sample ends 2026-06-30 | EXISTS | No |
| The series is not monotone; the native share rises in 2021 and again in 2023 | Same | EXISTS | No |
| The crossover survives folding staked-native derivatives into native | Same, native plus staked 33.7% against stable 36.4% in 2026 | EXISTS | No |
| The imported store of value grows from a rounding error to a material intermediary | Same, 0.2% to 5.8% of episodes and 1.3% to 9.9% of value | EXISTS | No |
| Architecture sets the feasible set within which allocation happens | V1 finding sections 1 and 3, forced routing 8.60% of V1 swaps, V2 WETH-pool share 95% to 98% by count | EXISTS | Yes, and therefore may not lead |
| Intermediated routing fragmented across venues while concentrating in a few assets | Cross-venue series, 1.2% to 61.1% count-weighted and 11.1% to 89.1% value-weighted | EXISTS | Partly |
| The unclassified residual is a real category and no type claim extends beyond the classified set | Transition finding, `other` at 24.2% of 2026 episodes across 9,283 distinct intermediary tokens | EXISTS | n/a |
| The transition is present venue by venue and is not the death of one venue | Same series recomputed with a venue dimension | PENDING | No |
| The transition survives the turnover-spike, volume-spike and arbitrage-cycle screens on top of the round-trip filter | `docs/research-workflow.md` section 4.2 names the screens as unapplied | PENDING | No |

### 2.4 Section 4, Pricing the road not taken

| Claim | Supporting result | Status | Mechanical |
|---|---|---|---|
| Comparing realised execution rates cannot detect an execution-cost difference on a volatile pair | Negative finding, median absolute gap 775 bps on volatile pairs against 23 bps on stable-to-stable, a factor of 34, on 16,586 cells | EXISTS | No |
| Cost-dominance windows exist and are common | Measured finding, 17.9% of 103,857 intermediated routes dominated gross of gas, 30.0% all-in, 186 days | EXISTS on v2-family venues and two-leg routes | No |
| Dominance incidence rises with a second hop's gas exactly where a fixed cost must bite | Same, $100 to $1k routes move from 17.0% to 39.1% while routes above $100k do not move at all | EXISTS | No |
| The extra hop costs 74,096 gas units, measured from receipts | Same, median gasUsed 154,604 for one leg against 228,701 for two | EXISTS | No |
| Larger trades are less likely to be dominated within a pair-day | Same, log notional -0.042 (0.000) | EXISTS | No |
| The pooled native cost advantage does not survive holding the trade fixed | Same, pooled -0.049 (0.008) against pair-by-day fixed effects +0.094 (0.269) | EXISTS | No |
| The pair-by-day design on one venue cannot resolve the sign, and calling it a null asserted an absence the data could not support | Same, 703 of 22,991 pair-day cells and 3,865 of 102,845 routes identify, standard error 0.085, minimum detectable effect near 24 percentage points | EXISTS | n/a |
| Quoting every candidate for every pair-day removes the coincidence the single-venue estimator waits on, and settles the sign | Multi-venue panel, native coefficient -0.383 (0.000) on 45,630 identifying cells and 944 pair clusters, against a minimum detectable effect of 0.104, cross-checked in R's fixest to 3.55e-07 | EXISTS, `docs/finding-native-intermediation-advantage.md` | No, screen passed |
| Holding the pair, the time window and the trade size fixed, the native-intermediated route is the harder one to beat | Same, and the head-to-head against the stable numeraire alone gives -0.368 (0.000) on 44,601 cells | EXISTS | No |
| The incumbent's routing advantage is largest for retail-sized trades and smallest where price impact dominates | Same, -0.4115 at $1,000, -0.4113 at $10,000, -0.3218 at $100,000 | EXISTS gross of gas; PENDING all-in and on a finer grid | No |
| Dominance windows exist on an all-in basis with a per-day gas price and a per-day gas-token price | Measured finding uses a flat 25.8 gwei and $2,500 per unit across 2020 to 2026, which is wrong in both directions at different times | PENDING | No |
| The 2021-Q3 collapse in the native routing advantage is not a migration of the best native routes to a venue the counterfactual cannot see | Measured finding states the confound and names the extension that would settle it | PENDING | No |
| Vehicle routes above $100k are dominated at the highest rate of any size bin and gas cannot explain it | Measured finding, 33.5% gross and all-in on 847 routes | EXISTS as an anomaly; PENDING for its explanation | No |

### 2.5 Section 5, Four rival accounts of the transition

Claims here are the horse race and are set out in full in section 5 of this file. Every one of them is PENDING, which is the paper's current structural problem and the subject of the last two sections of this document.

### 2.6 Section 6, Conclusion

| Claim | Supporting result | Status |
|---|---|---|
| A dominance transition that took the sterling-to-dollar literature decades is observable inside six years with the road not taken priced | Sections 3 and 4 jointly | Partly EXISTS |
| The vehicle role is a continuous share and the binary label discards the object of interest | Definitional, 2.2 | EXISTS |
| Which rival account survives, stated as a finding including the null | Section 5.5 | PENDING |

The conclusion reports the null on whichever rivals fail, per the standing rule that reporting a null is mandatory and belongs in results. It contains no limitations opener and no reconciliation against this repository's own earlier plans.

---

## 3. Table shells

Notation is the registry in `src/ddvc/variable_registry.py`. Cells read PENDING where node F has not delivered; no number appears that is not already in a `docs/finding-*.md` file. One registry gap is recorded at the end of this section.

### Table 1. Sample construction and coverage

Rows are filters in application order; columns record what each filter costs. Sample restriction: every venue in the unified layer, 2020-02-11 to 2026-06-30.

| Filter | Route units $r$ | Share kept | $\mathrm{Vol}_t$ summed, USD | Share kept |
|---|---|---|---|---|
| All reconstructed route units | 364,324,757 | 1.000 | PENDING | 1.000 |
| Route units with at least one intermediate, $N^I_t$ | PENDING | PENDING | PENDING | PENDING |
| Economic intermediation, first input token differing from last output token | PENDING | PENDING | PENDING | PENDING |
| Round trips excluded | PENDING | PENDING | PENDING | PENDING |
| Turnover-spike and volume-spike screens applied | PENDING | PENDING | PENDING | PENDING |
| Arbitrage-cycle detection applied | PENDING | PENDING | PENDING | PENDING |
| Intermediary token classified into a type in $\{$native, staked native, stable, imported$\}$ | PENDING | PENDING | PENDING | PENDING |

Memo rows, from `docs/router-identification-feasibility.md`: 471,616,631 swap legs reduce to 364,324,757 route units across 2,277 days; venues active rise from 3 in 2020 to 8 in 2025 and 2026; the round-trip share of multi-leg routes runs 9.6% to 20.5% by year.

### Table 2. Summary statistics

Panels follow `SUMMARY_SPECS` in the registry. Columns are mean, median, standard deviation, 5th percentile, 95th percentile, N. Sample restriction: token-day for panels A and C, day for panel B, candidate-week for panel D.

| Panel | Rows |
|---|---|
| A. Vehicle-use measures, token-day | $\mathrm{VehicleShare}_{k,t}$, $\mathrm{AllRouteVehicleShare}_{k,t}$, $\mathrm{VehicleCountShare}_{k,t}$, $\mathrm{PairCoverage}_{k,t}$, $\mathrm{MainVehiclePairShare}_{k,t}$, $\mathrm{IVol}_{k,t}$, $\mathrm{Betweenness}_{k,t}$ |
| B. Daily route activity | $\mathrm{Vol}_t$, $\mathrm{IVol}_t$, $\mathrm{IndirectRouteShare}_t$, $\mathrm{Stress}_t$ |
| C. Liquidity and route-cost opportunity | $L_{k,t}$, $\mathrm{LPConc}_{k,t}$, $\mathrm{DirectAvailable}_{k,t,q}$, $\mathrm{IndirectAvailable}_{k,t,q}$, $\mathrm{IndirectOnlyAvailable}_{k,t,q}$, $\mathrm{DirectDepth}_{k,t,q}$, $\mathrm{DirectCostAdvantage}_{k,t,q}$, $\mathrm{IndirectBeatsDirect}_{k,t,q}$, $\mathrm{ThinDirectShare}_{k,t,q}$ |
| D. Settlement-transfer sample | $\mathrm{TransferIncidence}_{k,w}$, $\mathrm{ReceiptCount}_{k,w}$ |

Every cell is PENDING. Panel C must be reported at $q=\$10{,}000$ in the body with $q\in\{\$1{,}000,\$100{,}000\}$ in an internal appendix, per the cross-RQ design rule. $L_{k,t}$ and $\mathrm{LPConc}_{k,t}$ are currently Uniswap-V3-only quantities and must be rebuilt on the unified layer before they enter this table, per `docs/retired-single-venue-round.md`.

### Table 3. Which asset type carries the vehicle role

The paper's lead exhibit. Rows are calendar years; column blocks are count-weighted and value-weighted type shares. Sample restriction: economically intermediated route units on the unified layer with the round-trip filter applied and the intermediary token classified, 2020-05-06 to 2026-06-30, 2,240 days.

| Year | $\mathrm{TypeCountShare}^{\mathrm{native}}_t$ | $^{\mathrm{staked}}$ | $^{\mathrm{stable}}$ | $^{\mathrm{imported}}$ | $^{\mathrm{other}}$ | $\mathrm{TypeShare}^{\mathrm{native}}_t$ | $^{\mathrm{staked}}$ | $^{\mathrm{stable}}$ | $^{\mathrm{imported}}$ | $^{\mathrm{other}}$ |
|---|---|---|---|---|---|---|---|---|---|---|
| 2020 | 68.7 | 0.0 | 26.8 | 0.2 | 4.3 | 73.0 | 0.0 | 21.2 | 1.3 | 4.5 |
| 2021 | 72.4 | 0.0 | 21.3 | 2.0 | 4.3 | PENDING | PENDING | PENDING | PENDING | PENDING |
| 2022 | 62.9 | 0.2 | 25.6 | 1.3 | 10.1 | 24.3 | 0.3 | 46.2 | 4.3 | 24.9 |
| 2023 | 71.3 | 0.3 | 13.9 | 0.9 | 13.7 | PENDING | PENDING | PENDING | PENDING | PENDING |
| 2024 | 66.0 | 0.9 | 14.1 | 1.3 | 17.7 | 36.0 | 6.7 | 29.5 | 3.6 | 24.2 |
| 2025 | 45.1 | 1.1 | 28.9 | 4.1 | 20.7 | PENDING | PENDING | PENDING | PENDING | PENDING |
| 2026 | 32.9 | 0.8 | 36.4 | 5.8 | 24.2 | 14.8 | 1.5 | 50.1 | 9.9 | 23.7 |

Panel B, robustness, one row each with the 2026 count-weighted native and stable shares as columns: staked native folded into native (33.7 against 36.4, EXISTS); expanded classified set with a documented tail cutoff (PENDING); venue-by-venue recomputation (PENDING); post-screen sample (PENDING); quarterly crossover dates for both weightings (PENDING).

Registry gap, and it blocks this table. The registry has no symbol for an asset-type share. $\mathcal K$ is the five-ticker candidate set and the lead result is measured over the five-type taxonomy in `src/ddvc/asset_types.py` across 9,283 observed intermediary tokens. The paper's headline quantity therefore has no registered notation. Node F must add $\mathcal K^{\theta}$ for the token set of type $\theta\in\{$native, staked_native, stable, imported, other$\}$, with $\mathrm{TypeShare}^{\theta}_t=\sum_{k\in\mathcal K^{\theta}}\mathrm{IVol}_{k,t}/\mathrm{IVol}_t$ and $\mathrm{TypeCountShare}^{\theta}_t=\sum_{k\in\mathcal K^{\theta}}N^I_{k,t}/N^I_t$, both defined over the full observed intermediary population and not over $\mathcal K$. Until that lands, table 3 uses symbols that do not exist, which violates the registry's role as single source.

### Table 4. Route availability and the feasible set

Rows are candidates in $\mathcal K$; column blocks are the three notionals. Sample restriction: $\mathcal P_{k,t,q}$, the day's 200 largest clean reconstructed pairs with $k\notin\{i,o\}$ and a valid day price for each of $i$, $o$ and $k$, on 2,238 days from 2020-05-14 to 2026-06-23, across uniswap_v2, sushiswap_v2, uniswap_v3 and uniswap_v4.

| Candidate $k$ | $\mathrm{DirectAvailable}_{k,t,q}$ | $\mathrm{IndirectAvailable}_{k,t,q}$ | $\mathrm{IndirectOnlyAvailable}_{k,t,q}$ | $\mathrm{ThinDirectShare}_{k,t,q}$ | $|\mathcal C_{k,t,q}|$ per day |
|---|---|---|---|---|---|
| WETH | PENDING | PENDING | PENDING | PENDING | PENDING |
| USDC | PENDING | PENDING | PENDING | PENDING | PENDING |
| USDT | PENDING | PENDING | PENDING | PENDING | PENDING |
| DAI | PENDING | PENDING | PENDING | PENDING | PENDING |
| WBTC | PENDING | PENDING | PENDING | PENDING | PENDING |

Memo line, verified first-hand against the panel on ten row groups spread across the file: 26.97% of quoted rows have both a direct and an indirect route executable, which matches the 30.04M common-support rows in the panel header. Availability is an architectural quantity whose sign is fixed by construction, which places this table in the supporting layer and never in the lead.

### Table 5. The same-state cost frontier and dominance incidence

Panel A rows are intermediary asset types; columns are dominance incidence and the median cost gap, gross of gas and all-in. Sample restriction: intermediated two-leg routes with an executable direct alternative priced at identical reconstructed pre-trade pool state, absolute gap at most 10,000 bps, notional between $100 and $50m.

| Intermediary type | Routes | Dominated, gross | Median gap, gross, bps | Dominated, all-in | Median gap, all-in, bps |
|---|---|---|---|---|---|
| Native | 19,339 | 13.2 | -2,459 | PENDING | PENDING |
| Stable | 33,037 | 16.8 | -492 | PENDING | PENDING |
| Other | 48,441 | 18.7 | -171 | PENDING | PENDING |
| Imported | 2,028 | 23.1 | -123 | PENDING | PENDING |
| All | 102,845 | 17.9 | PENDING | 30.0 | PENDING |

Panel B rows are notional bins; columns are dominance incidence gross and all-in. Same restriction.

| Notional | Routes | Dominated, gross | Dominated, all-in |
|---|---|---|---|
| $100 to $1k | 50,283 | 17.0 | 39.1 |
| $1k to $10k | 42,051 | 18.9 | 22.2 |
| $10k to $100k | 10,674 | 17.0 | 17.3 |
| Above $100k | 847 | 33.5 | 33.5 |

Panel C is the cost decomposition and every cell is PENDING. Rows are $C^{D,\mathrm{fee}}_{i,o,q,t}$, $C^{D,\mathrm{impact}}_{i,o,q,t}$, $C^{D,\mathrm{gas}}_{i,o,q,t}$, $C^{D}_{i,o,q,t}$, $C^{I,\mathrm{fee}}_{i,o,k,q,t}$, $C^{I,\mathrm{impact}}_{i,o,k,q,t}$, $C^{I,\mathrm{gas}}_{i,o,k,q,t}$, $C^{I}_{i,o,k,q,t}$, $\Delta C^{D}_{i,o,k,q,t}$, $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$. Columns are the three notionals crossed with median and mean, reported together because a few per cent of trades drive the entire mean. The fee, impact and gas contributions must sum back to all-in cost within a stated numerical tolerance, and the tolerance is reported in the table note.

Panels A and B carry a flat 25.8 gwei gas price and a flat $2,500 gas-token price across the whole span, which the source document names as its first refinement. The published version of this table requires the per-day gas price from `data/processed/daily_gas_price_graph.parquet` (1,883 days) and a per-day gas-token price, and the all-in columns stay PENDING until then. The gross columns do not depend on either and are reported as measured.

### Table 6. Route choice on all-in cost

Rows are coefficients; columns are specifications. Sample restriction: common support $\mathcal C_{k,t,q}$ at $q=\$10{,}000$, with the other two notionals in an internal appendix. Every cell is PENDING.

| Coefficient | (1) Pooled | (2) + $\ln q$ | (3) + year | (4) Pair-date FE | (5) Pair-date FE, cross-venue panel |
|---|---|---|---|---|---|
| $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$ on $\mathrm{IndirectRouteShare}_{i,o,t+1}$ | PENDING | PENDING | PENDING | PENDING | PENDING |
| $\mathrm{DirectDepth}_{i,o,q,t}$ | PENDING | PENDING | PENDING | PENDING | PENDING |
| $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$ on $\mathrm{VehicleShare}_{i,o,k,t+1}$ | PENDING | PENDING | PENDING | PENDING | PENDING |
| $\mathrm{LPConc}_{k,t}$ | PENDING | PENDING | PENDING | PENDING | PENDING |
| Native-type indicator | -0.049 (0.008) | -0.051 (0.008) | -0.049 (0.008) | +0.094 (0.269) | -0.383 (0.000) |
| Standard error | PENDING | PENDING | PENDING | 0.085 | 0.037 |
| Cells identifying | | | | 703 of 22,991 | 45,630 of 170,047 |
| Rows | 102,845 | 102,845 | 102,845 | 3,865 | 11,248,255 |
| Minimum detectable effect, percentage points | | | | 24 | 10.4 |
| Clusters | 3,654 pairs | 3,654 | 3,654 | 158 | 944 pairs |

Column (5) is the specification the paper needs and the single most valuable thing node F can deliver. Columns (1) to (4) are the single-venue two-leg v2-only estimates already on record; they are retained in the table because a reader will ask why the multi-venue panel was necessary and the answer is the 96.2% of the v2 panel that contributes nothing to column (4). Every column reports coefficient, standard error, 95% interval, $p$-value, N, fixed effects, clustering, and an economically scaled effect, per the cross-RQ design rule.

### Table 7. Persistence and displacement

Panel A, persistence conditional on current economics. Rows are coefficients, columns are $\tau\in\{7,30,90\}$. Sample restriction: common-support pair-candidate-days with pair-date fixed effects, two-way clustering by pair-candidate and date. Every cell is PENDING.

| Coefficient | $\tau=7$ | $\tau=30$ | $\tau=90$ |
|---|---|---|---|
| $\rho_\tau$ on $\mathrm{VehicleShare}_{i,o,k,t}$ | PENDING | PENDING | PENDING |
| $\beta_\tau$ on $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$ | PENDING | PENDING | PENDING |
| $\gamma_\tau$ on $\mathrm{LPConc}_{k,t}$ | PENDING | PENDING | PENDING |
| $\chi_\tau$ on $\mathrm{CandidateStress}_{k,t}$ | PENDING | PENDING | PENDING |

Panel B, displacement. Rows are fixed $\mathrm{ChallengerCostEdge}_{i,o,q,t}$ bins with knots at 0, 25, 50, 100 and 200 basis points, fixed before estimation. Columns are $\mathrm{VehicleSwitch}_{i,o,q,t,\tau}$ at the three horizons and the incumbent's share change. Every cell is PENDING. A mirror-sample column estimates whether a displaced incumbent needs a larger edge to return than the challenger needed to win, which is the asymmetry that separates hysteresis from persistence.

Panel C is the persistence result the paper already owns and cannot use as identification. Rows are weeks since a live direct pool first existed for a pair; the column is the median per-pair share of trade count still routed through the native asset, with the trailing-28-day liveness condition applied.

| Weeks since a live direct pool existed | Median native-routed share of count |
|---|---|
| 0 | 0.456 |
| 1 | 0.638 |
| 2 to 3 | 0.746 |
| 4 to 7 | 0.600 |
| 8 to 12 | 0.333 |
| 13 to 25 | 0.321 |
| 26 to 51 | 0.200 |
| 52 and beyond | 0.078 |

Sample restriction for panel C: 2,222 Uniswap V2 pairs with a direct pool, at least 20 trades, and at least one native-routed trade, median trade notional between $100 and $50m, both tokens in the V2 decimals map. The table note states that calendar year explains more of this profile than horizon does, that the panel is 1,308 other-plus-stable and 807 other-plus-other pairs by endpoint type, and that a thin new direct pool can make native routing cost-optimal at every instant. Panel C is descriptive in the paper and is labelled as such.

### Table 8. The horse race

Rows are the four rival accounts of section 5; columns are the discriminating prediction, the sign the account requires, the estimate, and the verdict. Every estimate cell is PENDING. This is the table the paper is organised around and it is the table with the least support today.

| Account | Discriminating prediction | Required sign | Estimate | Verdict |
|---|---|---|---|---|
| Thick-market cost advantage | $C^I_{i,o,k,q,t}$ for stable candidates crosses below the native candidate's at the share-crossover date, and $\beta_K<0$ under pair-date fixed effects | $\beta_K<0$; cost crossover leads or coincides with the share crossover | Native indicator -0.383 (0.000) holding pair, window and size fixed; cost crossover PENDING | Supported on the level, PENDING on the timing |
| Cost of holding the intermediary | The value-weighted crossover precedes the count-weighted crossover, the native cost advantage weakens with notional, and $\chi_\tau$ on $\mathrm{CandidateStress}_{k,t}$ is negative for the native candidate and positive for stable candidates | Value crossover earlier; native advantage falling in $q$; $\chi_\tau$ sign flip by type | 2022-Q1 against 2026-H1, EXISTS; -0.4115 at \$1,000 falling to -0.3218 at \$100,000, EXISTS; $\chi_\tau$ PENDING | Supported on two of three predictions |
| Liquidity supply as the state variable | $\mathrm{LPConc}_{k,t}$ predicts $\mathrm{VehicleShare}_{i,o,k,t+\tau}$ after conditioning on contemporaneous $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$, and $\rho_\tau>0$ under pair-date fixed effects | $\gamma_\tau>0$ and $\rho_\tau>0$ | PENDING | PENDING |
| Software defaults | Migration arrives as a step at routing-software and template release dates, does not appear on venues whose software did not change, and native pairing rises after the mandate is withdrawn | Step timing; no cross-venue spillover; V1-to-V2 null | V1-to-V2 null EXISTS and favours this account; step timing and spillover PENDING | Partly supported |

Two accounts currently have partial support and both of those partial supports point in opposite directions, which is the whole reason the section exists.

### Figures

| Figure | Content | Status |
|---|---|---|
| 1 | $\mathrm{TypeCountShare}^{\theta}_t$ and $\mathrm{TypeShare}^{\theta}_t$ for the four classified types, monthly, 2020 to 2026, with both crossover dates marked | EXISTS as data, PENDING as an exhibit |
| 2 | Median $C^{I}_{i,o,k,q,t}$ by candidate type against $\mathrm{TypeShare}^{\theta}_t$ on the same time axis, $q=\$10{,}000$ | PENDING, and this is the exhibit the paper most needs |
| 3 | Dominance incidence against notional, gross and all-in, by intermediary type | Partly EXISTS from table 5 panels A and B |
| 4 | Specification curve for the leading claim of section 5.5, with the joint inference test | PENDING |

Four figures against eight tables matches the measured median of the read sample. Node A's figure count of roughly seven is not supported on this sample and is not adopted.

---

## 4. Section 2.2, Definitions, written out

The paper's object is not whether an asset is used as an intermediary. Vehicle status in that sense is binary and one bridging swap satisfies it, which makes the label uninformative about anything a reader cares about. What the paper measures is the extent to which one asset captures the intermediation role, and dominance is treated throughout as a continuous share on an axis separate from status. The literature's categorical usage compresses a distribution into a label, and making the distribution explicit is part of the contribution.

**Definition 1, route unit.** A route unit $r$ is a reconstructed input-to-output execution inside one transaction. A coherent $i\to k\to o$ component contributes one route unit whatever its number of legs, and a split or a join contributes one route unit for each reconstructed input-output pair. Counting legs would weight a route by how many pools a router happened to touch, which is a property of the router.

**Definition 2, direct and indirect routes.** For an ordered endpoint pair $(i,o)$, the direct route is the single-hop execution $i\to o$. An indirect route passes through at least one intermediate token. The indirect route through candidate $k$ is $i\to k\to o$ with $k\notin\{i,o\}$.

**Definition 3, vehicle use.** Token $k$ is used as a vehicle in route unit $r$ when $k$ is an intermediate of $r$. The day-$t$ vehicle share of $k$ is $\mathrm{VehicleShare}_{k,t}=\mathrm{IVol}_{k,t}/\mathrm{IVol}_t$, the fraction of indirect-route USD volume passing through $k$. Its count-weighted counterpart is $\mathrm{VehicleCountShare}_{k,t}=N^I_{k,t}/N^I_t$, and its all-route counterpart $\mathrm{AllRouteVehicleShare}_{k,t}=\mathrm{IVol}_{k,t}/\mathrm{Vol}_t$ carries direct volume in the denominator so the economic scope of routed exchange stays visible. USD-weighted shares are primary and count shares are the reported robustness, with the exception noted at 3.1, where the count-weighted series is primary because value weighting is more exposed to inflation by wash trading.

**Definition 4, dominance.** Dominance is the concentration of the vehicle role, measured at two levels. At market level it is the vehicle share itself, together with the extensive-margin measures $\mathrm{PairCoverage}_{k,t}=|\mathcal A^k_t|/|\mathcal A_t|$ and $\mathrm{MainVehiclePairShare}_{k,t}=|\mathcal M^k_t|/|\mathcal A_t|$, the fraction of active endpoint pairs that use $k$ at all and the fraction for which $k$ carries the largest candidate volume. At pair level it is $\mathrm{VehicleHHI}_{i,o,t}$, the Herfindahl concentration of candidate shares after renormalisation, always reported with $\mathrm{Coverage}^{\mathcal K}_{i,o,t}$ so that routing moving outside the candidate set cannot present itself as concentration inside it.

**Definition 5, asset types.** The claim is about currency types and tickers appear only as proxies. A *native platform asset* is the platform's own settlement asset, carrying the thickest incumbent pairing network and high volatility, whose traditional counterpart is the incumbent international currency whose role rests on thick-market externalities. A *stable numeraire* is a low-volatility unit of account, whose counterpart is the managed or pegged stable unit. An *imported store of value* is a non-native asset brought on-platform in wrapped form, including tokenised gold, whose counterpart is gold or a foreign reserve asset. A *staked native derivative* holds the native asset's exposure in a different instrument, and it is held apart from the native type because whether it counts as the same currency is a specification choice and not a fact; the paper reports both treatments. Every other intermediary token is *other*, which is a real category and not a residual to be explained away: it carries 24.2% of 2026 intermediation episodes across a tail of 9,283 observed intermediary tokens, and no type claim in the paper extends beyond the classified set.

**Definition 6, candidate set.** $\mathcal K=\{\mathrm{WETH},\mathrm{USDC},\mathrm{USDT},\mathrm{DAI},\mathrm{WBTC}\}$ is the prespecified set used wherever a counterfactual must be quoted for every candidate, because quoting requires a pool universe and a price for each candidate on each day. The type shares of definition 5 are measured over the whole observed intermediary population and not over $\mathcal K$, and the two must never be conflated: $\mathcal K$ is the quoting universe and the taxonomy is the measurement universe.

**Definition 7, all-in route cost.** For notional $q$ at reconstructed pre-trade state, the direct all-in cost is $C^{D}_{i,o,q,t}=1-O^{D}_{i,o,q,t}/q+G^{D}_{i,o,q,t}/q$ and the indirect all-in cost through $k$ is $C^{I}_{i,o,k,q,t}=1-O^{I}_{i,o,k,q,t}/q+G^{I}_{i,o,k,q,t}/q$, where $O$ is quoted output value and $G$ is route gas expenditure at the day's gas price and gas-token price. Each decomposes into a fee contribution, a price-impact contribution and a gas contribution that sum back to the total within a stated tolerance. Quote-output cost and all-in cost are separate objects and are never substituted for one another: $\Delta C^{D}_{i,o,k,q,t}=(O^D-O^I)/O^D$ excludes gas, and $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}=C^{I}-C^{D}$ includes it. Positive values of either favour the direct route.

**Definition 8, cost-dominance window.** A cell $(i,o,k,q,t)$ is a cost-dominance window when the indirect route through $k$ carries realised routing while $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}>0$, meaning the direct route was strictly cheaper on an executable all-in basis and was declined. The window is the state the FX literature cannot observe, because there an incumbent's cost advantage is a consequence of its incumbency and the counterfactual price of the road not taken is unavailable.

**Definition 9, common support.** $\mathcal C_{k,t,q}=\mathcal D_{k,t,q}\cap\mathcal I_{k,t,q}$ is the set of pairs for which both the direct and the indirect route through $k$ execute at notional $q$. Cost comparisons are made only on common support. Pairs off common support are retained as availability outcomes and are never deleted, because whether an alternative exists at all is the architectural margin of section 3.3.

**Definition 10, depth.** Realised all-in cost at a fixed notional grid is the primary depth measure. Marginal-price displacement, $\mathrm{BandDepth}_{p,t,b}$ and $\mathrm{LiquidityConcentration}_{p,t,b}$, is a secondary structural descriptor of a single pool. The two stand in a design-dependent relation, and no sum of per-pool depth numbers is used, because the economically correct aggregation across heterogeneous pools is the joint split optimisation.

**Definition 11, incumbent and challenger.** The incumbent vehicle $k^\star_{i,o,t}$ has the largest mean $\mathrm{VehicleShare}_{i,o,k,u}$ over the 30 calendar days ending at $t-1$, using only information dated before $t$. The challenger $h^\star_{i,o,q,t}$ is the executable non-incumbent candidate with the smallest $C^I_{i,o,h,q,t}$ on day $t$. The challenger's edge is $\mathrm{ChallengerCostEdge}_{i,o,q,t}=C^I_{i,o,k^\star,q,t}-C^I_{i,o,h^\star,q,t}$, positive when the challenger is cheaper.

**Definition 12, what routing agency is and is not.** Route selection is executed by smart-order routers that are deterministic graph optimisers over current pool state, which removes trader habit as a quote-time channel. Preferring an incumbent intermediary when a cheaper direct route exists therefore cannot be read as inertia. Incumbency in this paper operates through state variables that update slowly, being liquidity-provider capital allocation, where providers face switching costs, gas costs and attention limits, and aggregator integration scope, which is a business decision on a business cadence. A router choosing the native asset because its pools are deepest is optimal at that instant, and the reason those pools are deepest may still be historical incumbency.

---

## 5. Named rival mechanisms: the horse race on the leading claim

**The leading claim, stated in the form the rivals have to beat.** Across 2020 to 2026 the intermediation role migrated from the native platform asset to the stable numeraire, with the native share falling from 73.0% to 14.8% of intermediated value and the stable share rising from 21.2% to 50.1%, and the migration arrived in value roughly four years before it arrived in count.

Four accounts could produce that pattern. Each is stated with the empirical fact that separates it from the others, per the craft pattern node A extracted from the no-model empirical exemplars. Following Bolton and Kacperczyk's practice of rejecting one of their own, the fourth account is the one this paper's own V1 evidence currently favours, and it is reported that way.

### 5.1 Thick-market cost advantage

The role sits with whichever asset is cheapest to route through at the moment, and the migration is the stable numeraire's route cost falling below the native asset's as its pools deepened. This is Krugman's mechanism with the unobservable FX cost schedule replaced by an exact same-state counterfactual.

What separates it: the timing of the cost crossover against the timing of the share crossover, on the same days and the same pairs. If the account holds, median $C^{I}_{i,o,k,q,t}$ for stable candidates crosses below the native candidate's at or before the share crossover, and the route-choice coefficient $\beta_K$ on $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$ is negative under pair-date fixed effects. If the cost crossover lags the share crossover, this account is refuted and the causality runs from use to depth.

What refutes it as the whole story: contemporaneous cost cannot be the only thing selecting the intermediary when 17.9% of intermediated routes were already dominated gross of gas and 30.0% all-in. That measurement is on record and it bounds this account before any regression runs.

Status: supported on the level, PENDING on the timing. Commit 0a4da17 settles the level: holding the pair, the time window and the trade size fixed, the native-intermediated route is 38.3 percentage points less likely to be beaten by a direct pool, with a cluster-robust standard error of 0.037 (0.000) on 45,630 identifying cells and 944 pair clusters, and the estimate is nearly four times its minimum detectable effect of 0.104. Native intermediation winning because its pools are deeper is the thick-market externality of the vehicle-currency literature arriving as a measured coefficient. What the level cannot do is explain the migration, because a mechanism that favours the native asset throughout the sample cannot by itself produce a role moving away from it. The timing test is what carries that weight, and figure 2 is the exhibit. Nothing in the repository currently puts cost and share on one time axis.

The level result also carries the finding that makes this account partial in a productive way. The advantage runs -0.4115 at a $1,000 trade, -0.4113 at $10,000 and -0.3218 at $100,000, so it weakens as notional grows. A pure depth mechanism has to strengthen with notional, because a thin pool fails worse as size grows, and the profile does the reverse. Section 5.2 takes that profile as its hinge.

### 5.2 The cost of holding the intermediary

Because an intermediate asset is held for the duration of the hop, the cost of the intermediary's own volatility scales with notional, and a large trade has more reason to route through a low-volatility unit. The migration is then a reallocation by trade size and the aggregate crossover is its composition.

What separates it, and this is the only rival with a prediction already on the record that was not fitted after the fact: the mechanism requires the value-weighted crossover to arrive before the count-weighted one. Measured, the value crossover is 2022-Q1 and sustained from 2022-Q4 while the count crossover appears only in 2026-H1. The ordering matches.

The second discriminating test is the size profile of the incumbent's cost advantage, and it is the hinge on which this section now turns. If the mechanism holds, the native asset's advantage as an intermediary has to weaken as notional grows, because the cost of holding a volatile intermediary scales with the amount held. Measured on the multi-venue panel, the native coefficient runs -0.4115 at a $1,000 trade, -0.4113 at $10,000 and -0.3218 at $100,000. A depth mechanism predicts the opposite slope, because a thin pool fails worse as size grows. The two panels now say the same thing from opposite directions: the role migrated first at the notionals where the incumbent's advantage is weakest, and the value crossover leading the count crossover by four years is what that looks like in realised routing.

The third discriminating test is stress. If the intermediary's own risk is what is being priced, $\mathrm{CandidateStress}_{k,t}$ should push share away from the stressed candidate, negatively for the native asset under its own drawdowns and positively for stable candidates under a native drawdown, with the sign reversing for a stable candidate's own downward depeg. A placebo assigning the shock after the outcome window must be null.

Status: supported on two of three predictions and the strongest account in the race. The count-value ordering EXISTS and the size profile EXISTS gross of gas. Three things would settle it. The size profile re-estimated on the all-in outcome, because the current profile mixes a depth channel with a fixed-cost channel and gas hits small trades hardest. The same profile on a notional grid finer than three points, because a monotone-mechanism claim needs more than three. And the transition crossover dated by trade-size bin, which converts a pattern observed across two documents into one exhibit. The stress coefficients are PENDING and the March 2023 depeg is the episode that identifies the reversal.

### 5.3 Liquidity supply as the state variable

Pools are deepest where they have historically been deepest, because providers face switching costs, gas costs and attention limits, and route cost inherits that history. The migration is then a slow reallocation of provider capital, with routing following mechanically and instantaneously at every instant.

What separates it: $\mathrm{LPConc}_{k,t}$ predicting $\mathrm{VehicleShare}_{i,o,k,t+\tau}$ after conditioning on contemporaneous $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$, together with $\rho_\tau>0$ under pair-date fixed effects. Conditioning on current all-in cost is what distinguishes this from account 5.1, and the distinction is the whole reason the all-in frontier has to be built.

What this account may not be tested with: a lagged dependent variable plus fundamentals controls. That is the specification the FX literature itself shows cannot separate switching costs from a serially correlated unobserved fundamental, and running it would reproduce the interpretive error this paper claims to overcome. The lagged coefficient re-enters only alongside contemporaneous all-in cost and the dominance windows.

Status: PENDING, and doubly so. $L_{k,t}$ and $\mathrm{LPConc}_{k,t}$ are currently Uniswap-V3-only quantities and must be rebuilt on the unified layer before they can enter any specification.

### 5.4 Software defaults and the road already taken

Routing software and pool-creation templates default to the native asset, and the migration is a change in defaults with no allocative content. A single implementation choice inside one frontend can generate both a pairing pattern and a routing pattern with no economics behind either.

What separates it, in three independent ways. First, timing: a default change is a step at a release date, and an allocative reallocation is a drift. Second, venue scope: a default inside one venue's software cannot move routing on venues whose software did not change, which makes cross-venue spillover the discriminating design. Third, the mandate withdrawal: when Uniswap V1's architectural requirement to route through the native asset was removed by V2, native-asset pairing did not retreat, and the share of newly created pairs including the native asset rose from 84.1% in 2020 to 99.0% in 2023 and 97.9% in 2026.

This is the account the paper's own evidence currently favours, and it is reported as such. The V1 finding is a null on the architectural hypothesis measured over 477,633 pairs, of which 97.1% include the native asset, and the honest reading is that convention and tooling would produce the pattern as well as optimisation would. The token-level version of the same test reaches a bounded null: on 247 V1 exchanges, forced-routing intensity carries a coefficient of +0.276 on exit speed with a robust standard error of 0.307, randomisation inference at (0.355), a hazard-model coefficient of +0.026 with a cluster-robust standard error of 0.431, and measured power of 98.4% against a halving of survival time. An effect the mandate hypothesis needs would have been visible and it was not.

Status: partly supported, and the support runs against the paper's more interesting reading. The step-timing test and the cross-venue spillover design are PENDING, and they are how this account is beaten if it can be beaten.

### 5.5 What survives

The section closes with a specification curve on the leading claim, curated to defensible specifications with a joint inference test, and a dashboard showing which analytical choices move the result. The three mandatory-to-vary choices are the dependent variable (value against count weighting), the transformation (level, log, share), and the outlier treatment (the notional band and the absolute-gap cap), following the measured result that discretion over ten routine choices lets a researcher report over 70% of randomly generated variables as significant.

The verdict paragraph states which accounts survive and which do not, including the nulls, and it states them as findings. If two accounts survive jointly the paper says so; the section's purpose is to close off the accounts that do not survive, and a horse race that ends in a tie between two mechanisms is a result.

---

## What G needs from F

Ordered by how much narrative weight is blocked, with the specification that would produce each. Items F1 and F2 were added after commit 0a4da17 landed the multi-venue dominance estimate during this drafting pass, and both concern that estimate.

**F1. CLOSED during this drafting pass. The non-mechanicalness screen, and it passes.** G asked for the enumeration screen and `docs/finding-native-intermediation-advantage.md` delivers it. Dropping the imported asset entirely, which is the most likely thin candidate, leaves the native asset beating the stable numeraire head to head by 36.8 percentage points on 9,805,608 rows and 44,601 cells with a standard error of 0.0376 (0.000). Restricting to economically live routes where the direct route's advantage lies within 5% either way gives -0.3986 with a standard error of 0.0351 (0.000). The result is an asset-role effect and section 5.1 promotes it accordingly.

**F2. CLOSED. The findings document exists** at `docs/finding-native-intermediation-advantage.md`, and it supersedes the composition reading in `docs/finding-cost-dominance-measured.md` explicitly. Every status in this file that read "delivered in commit 0a4da17" now cites that document. One item from the original request is still open and moves to F3: the outcome is a binary on quoted output gross of gas, and the treatment of the 355 panel days lacking a gas price is undetermined.

**F2a. NEW, and it is now the most consequential open item. Frame the size profile, which G answers here.** F asks whether the size heterogeneity leads or supports. It supports, and it becomes the hinge of section 5.2. The reason is that it joins the paper's two halves for the first time. The native asset's routing advantage runs -0.4115 at a $1,000 trade, -0.4113 at $10,000 and -0.3218 at $100,000, so incumbency pays most for retail-sized trades and least where price impact dominates. The transition finding independently reports that the stable numeraire overtook the native asset in value roughly four years before it overtook in count. Those two facts are the same fact seen from two panels: the role migrated first exactly at the notionals where the incumbent's cost advantage is weakest. G needs three things to state it. First, the size profile re-estimated on the all-in outcome, because gas hits small trades hardest and the advantage is already largest there, and F's own note predicts sharpening without reversal. Second, the coefficient estimated on a finer notional grid than three points, because a mechanism claim on a monotone profile needs more than three. Third, the crossover date by trade-size bin from the transition panel, so the ordering can be shown as a joint pattern instead of asserted across two documents. That third item is the one exhibit that would let the paper claim a mechanism for the transition, and it displaces figure 2 as the highest-value deliverable.

**F2b. NEW. The feasible-set crossover the deck carries has no findings document.** `docs/deck-outline.md` slide 10 reports quoted two-hop availability of 86.0% in 2021 falling to 50.4% in 2026 for the native asset against 33.4% rising to 57.8% for the stable numeraire, with the crossover annotated at 2025-Q4 and moving to 2025-Q3 under a native-ETH endpoint alternative. No `docs/finding-*.md` file carries those numbers, and table 4 of this spine is the shell they belong in. Either F writes them up with the coverage bound signed, or the slide loses its grounding line.

**F3. All-in cost on the multi-venue panel, per-day gas and per-day gas-token price.** Join `data/empirical/route_cost_panel_v2.parquet` (123,765,615 rows, 2,238 days, 2020-05-14 to 2026-06-23, five candidates, three notionals, four venues, method `v2_cp_plus_v3_exact_tick`) to `data/processed/daily_gas_price_graph.parquet` (1,883 days, `gas_gwei_median`) and a per-day gas-token USD price, using the receipt-measured gas topology (154,604 units for one leg, 228,701 for two, 74,096 for the extra hop). Deliver $C^{D}_{i,o,q,t}$, $C^{I}_{i,o,k,q,t}$, $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}$ and the fee, impact and gas decomposition with the summation tolerance stated. The panel currently carries `direct_cost_advantage`, which is the quote-output measure $\Delta C^{D}_{i,o,k,q,t}$ and not the all-in one. This blocks table 5 panel C, table 6, table 7 panels A and B, table 8 rows 1 and 3, and figure 2. The 1,883-day gas coverage against the panel's 2,238 days leaves 355 days without a gas price, and F must state how those days are handled instead of dropping them silently.

**F4. Figure 2, cost and share on one time axis.** Median $C^{I}_{i,o,k,q,t}$ by candidate type against $\mathrm{TypeShare}^{\theta}_t$, monthly, $q=\$10{,}000$, on common support $\mathcal C_{k,t,q}$. This is the single exhibit that converts the paper from a description of a transition into a statement about what made it, and no artefact in the repository currently joins the two panels. The transition is measured on 2,240 days of the unified layer and the cost on 186 sampled days of the v2-only counterfactual, with different venue coverage, which means the join needs the multi-venue panel from F3 and not the existing counterfactual.

**F5. The pair-date fixed-effects route-choice coefficient on the multi-venue panel.** Table 6 column (5). The single-venue estimate is uninformative by construction, because within one venue a pair-day rarely sees both a native and a non-native intermediary actually used, which left 703 of 22,991 pair-day cells and 3,865 of 102,845 routes identifying, 158 clusters, a standard error of 0.085 and a minimum detectable effect near 24 percentage points against a point estimate of +0.094 (0.269). The multi-venue panel quotes all five candidates for every pair-day by construction, which removes the coincidence. Report the minimum detectable effect alongside the coefficient in both cases.

**Delivered, 2026-08-06, `docs/finding-native-intermediation-advantage.md`.** F produced this estimate while G was drafting, which is the cluster working as specified. `scripts/run_vehicle_dominance_hdfe.py` estimates $\mathbf{1}_{\{\Delta C^{D}_{i,o,k,q,t}>0\}}$ on a native-type indicator absorbing a pair-by-window-by-size cell effect, clustered by pair, and reports the minimum detectable effect beside every coefficient. On the seven-day window the native coefficient is -0.383 with a cluster-robust standard error of 0.037 (0.000), on 45,630 identifying cells of 170,047, 944 pair clusters and 11,248,255 rows, against a minimum detectable effect of 0.104. The control-window ladder runs 1 to 120 days and moves the coefficient by 0.0022 against a median standard error of 0.037. An independent re-estimation in R's fixest agrees to 3.55e-07 on the headline specification.

This overturns two readings G had encoded from the v2-only panel and both are corrected above and below. The single-venue design gave -0.049 (0.008) pooled flipping to +0.094 (0.269) under pair-day effects, which was read first as a composition effect and later as leaning toward the incumbent being the worse intermediary. Both readings were artefacts of 703 identifying cells of 22,991 and a minimum detectable effect near 24 percentage points. The multi-venue panel raises identifying cells by a factor of 252 and the sign is settled in the direction the thick-market account of section 5.1 requires.

The non-mechanicalness screen has since run and the effect survives it. Dropping the imported asset, which is the thinnest candidate, leaves the native asset beating the stable numeraire head to head by 36.8 percentage points on 9,805,608 rows with a standard error of 0.0376 (0.000), and restricting to routes whose direct advantage lies within 5% either way gives -0.3986 (0.000). Two limits keep the estimate out of the lead. The outcome is a binary on quoted output at reconstructed state, which describes the cost surface a router faced and not what a router chose. And the specification is gross of gas, so the size profile below mixes a depth channel with a fixed-cost channel that has not been separated.

**F6. Registry symbols for asset-type shares.** Add $\mathcal K^{\theta}$, $\mathrm{TypeShare}^{\theta}_t$ and $\mathrm{TypeCountShare}^{\theta}_t$ to `src/ddvc/variable_registry.py` with $\theta$ over the five types in `src/ddvc/asset_types.py`, measured over the observed intermediary population and not over $\mathcal K$. The paper's lead table has no registered notation today, which breaks the registry's role as single source and breaks the rule that table shells use registry symbols.

**F7. Value-weighted type shares for the missing years.** Table 3's value-weighted block reports 2020, 2022, 2024 and 2026 in the findings document and omits 2021, 2023 and 2025. Fill them, and report the quarterly crossover dates for both weightings so the paper can state the two crossovers with dates instead of with year labels.

**F8. The transition recomputed venue by venue, and after the wash screens.** The transition is currently measured on the pooled unified layer with only the round-trip filter applied. The turnover-spike, volume-spike, arbitrage-cycle and organic-versus-MEV screens named in the workflow's section 4.2 are unapplied, and the venue dimension is absent. Both are needed to dispatch the measurement rival at 3.4, and the venue split is needed because Uniswap V2 became a legacy venue after May 2021 and a pooled series cannot rule out venue composition on its own.

**F9. The V3 extension that settles the 2021-Q3 collapse.** The native routing advantage falls from +20.4 to +0.4 percentage points in one quarter immediately after the V3 launch, and the composition alternative is that the best native-intermediated routes migrated to V3 first while the counterfactual saw only v2. The multi-venue panel already prices uniswap_v3 and uniswap_v4 with exact tick state, which is the extension the findings document names as unavailable. Re-run the quarterly dominance series on that panel and the confound is either dispatched or confirmed.

**F10. Stress coefficients by candidate type.** $\chi_\tau$ on $\mathrm{CandidateStress}_{k,t}$ for native against stable candidates, with the March 2023 depeg as the episode that identifies the sign reversal, and the post-outcome placebo. This is the second discriminating test for account 5.2, the only rival with a prediction already passing.

**F11. Cross-venue spillover from the V3 architecture change.** The design that discriminates account 5.4, because software defaults inside one venue cannot move routing on venues whose software did not change. The workflow records that any V3-launch event study inherits the Jan-to-May 2021 volatility confound and that a control group sharing the macro episode is the fix. Fixed universe $\mathcal P^{\mathrm{V3}}_q$, continuous treatments $\mathrm{DirectConstraint}^{\mathrm{pre}}_{i,o,q}$ and $\sigma^{\mathrm{pre}}_{i,o}$, with the caveat that $\sigma^{\mathrm{pre}}_{i,o}$ is named in the registry and was never constructed.

**F12. Liquidity measures rebuilt on the unified layer.** $L_{k,t}$, $\mathrm{LPConc}_{k,t}$ and $\mathrm{LogVehicleLiquidity}_{k,t}$ are Uniswap-V3-only quantities today. Account 5.3 cannot be tested and table 2 panel C cannot be published until they are rebuilt. This also unblocks the September 2020 liquidity-mining launch as a candidate supply shock, which is unusable while liquidity is measured on V3 alone.

**F13. Explanation or retirement of the above-$100k anomaly.** Routes above $100k are dominated at 33.5% gross and all-in, the highest rate of any size bin, on 847 routes, and gas cannot explain it at that notional. Candidates to test are split routing across venues the v2-only counterfactual cannot see, MEV protection, and router suboptimality. Either the anomaly gets an explanation and enters section 4.3, or it is reported as an unexplained cell with its size stated.

**F14. Cleanup that the gates require.** `output/empirical/` still holds roughly fifty pickled result objects and `output/tables/` roughly twenty TeX and PDF exhibits from the round retired in `docs/retired-single-venue-round.md`, which states that every scripted output from that round is deleted and not archived. They are not deleted. Anything F promotes must be regenerated on the unified layer; everything else goes, in the same commit, per the standing supersede rule.

## What G needs from H

`docs/deck-outline.md` appeared during this drafting pass, targeting the Nanyang Blockchain Conference on 21 to 22 August 2026, with 18 main slides and 23 appendix slides. Four of its main slides are RESERVED against results that do not exist, each carrying an explicit cut rule. Reading it against this spine exposes four gaps and one direct conflict.

**H1. The deck's slide 13 is now buildable and the spine says so.** Slide 13 is RESERVED for whether the asset type matters once the trade is held fixed, with a cut rule that removes it if the sign stays unresolved. The sign is resolved. `docs/finding-native-intermediation-advantage.md` gives -0.3834 with a cluster-robust standard error of 0.0372 (0.000) on 177,106 identifying cells and 944 pair clusters, against a minimum detectable effect of 0.104, and the enumeration screen passes. H builds the coefficient plot the slide specifies and adds the notional split, because the size profile is the part that carries a mechanism.

**H2. The deck's slide 10 carries numbers with no findings document, and the spine cannot cite it.** Slide 10 reports quoted two-hop availability crossing at 2025-Q4, with the native candidate falling from 86.0% to 50.4% and the stable candidate rising from 33.4% to 57.8%. Table 4 of this spine is the shell for exactly those quantities and it is entirely PENDING. A slide grounded on a parquet file is grounded; a paper table needs a written-up measurement with the venue-coverage bound signed. This is item F2b.

**H3. The deck orders the argument architecture-first and the paper orders it transition-first.** Slides 2 through 8 are institutional and definitional, slide 9 is which asset type intermediates, and slide 10 is the feasible set. The paper puts the transition at section 3 and the architecture layer at 3.3 inside it. Both orderings are defensible for their medium, and the divergence is worth recording because Java's reserved call on which results lead is still open. Section 4.1 of the workflow says the transition leads. Section 8's item 3 gives a different inclination, and its numbering refers to a candidate list that section 4.1 replaced, which makes it stale where it reads as contradictory. G has built to section 4.1's ordering and flags the discrepancy for Java.

**H4. The deck's cut rule on slide 14 is stricter than the spine's and the spine adopts it.** Slide 14 will be cut unless cost-dominance windows are dated on an all-in basis with per-day gas, on the stated ground that a window dated on gross quotes is not a window a trader faced. That is a better rule than the spine had. Section 4.2 currently reports the gross incidence of 17.9% as a headline with the all-in 30.0% beside it, and both rest on a flat gas price across six years. G adopts the deck's rule: the gross figure describes the quote surface and the all-in figure is the only one the paper may call a window. F3 is what unblocks it.

**H5. Nothing in the deck's four RESERVED slides asks for a result the spine has not asked F for, and one spine item has no slide.** Slides 14, 15 and 16 map to F3, F11 and F12 of the list above. Running the mapping in the other direction leaves the size profile of the native advantage with no slide at all, which is the item G has just promoted to the hinge of section 5.2. H needs a slide for it, and the natural form is the coefficient plot of slide 13 split by notional with the transition's value and count crossover dates annotated on the same figure.

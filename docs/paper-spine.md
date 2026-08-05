# Paper spine: The Making of Dominant Vehicle Currencies: Evidence from DeFi

Node G output, rewritten 2026-08-06 after `docs/review-node-i-round1.md` withheld approval on the estimand and not on its execution. The previous version of this file was built around the level comparison, that native intermediation is harder to beat conditional on the trade. That estimand is retired as a lead result and survives only as a validation exhibit in section 2. What replaces it is the survival question: how long the vehicle role outlives the moment it stops being the cheapest route, priced in dollars foregone and days of delay, with the return-edge against displacement-edge asymmetry separating hysteresis from persistence.

Three of this file's own errors were confirmed in that review and are corrected throughout, so a reader comparing versions can see what moved. The trade-size gradient that the old section 5.2 called "the hinge on which this section now turns" does not exist: the interaction of the native indicator with log size, formally tested for the first time in `output/exhibits/dominance_specification_curve.jsonl`, is +0.0023 with a standard error of 0.0209 (0.914), so the three-point profile the old file read as a monotone mechanism was three draws from a flat line. The old headline mixed two specifications, pairing the seven-day window's coefficient of -0.3834 and standard error of 0.0372 with the one-day window's identifying count of 177,106; the seven-day window identifies from 45,630 cells. And the old defence against quote collapse restricted the sample on absolute cost advantage, which is a monotone function of the binary outcome, so it selected on the dependent variable and cannot discharge anything.

Two results landed from nodes D and E while this file was being written and both are folded in below. The realised-dominance headline was reweighted from the raw matched mean of 41.3% to 27.2% on the population's candidate composition, because the matched sample is inverted on exactly the dimension that drives the rate, and 41.3% is retained only as the raw matched mean answering a narrower question. And `docs/node-e-screen-persistence.md` screened the persistence result for mechanicalness before it was written up, passing it on the definitional threat and naming hour-boundary pricing as the dangerous open one. Measuring that threat confirmed it: `output/exhibits/repricing_at_block.jsonl` puts the median share of routes mispriced by more than 25 basis points at 86.2% across the busiest pools, against route-cost differences of tens of basis points. The persistence result is therefore WITHDRAWN in this file pending block-level pricing, and section 4 is written as an estimand with a specification and no admissible measurement. That is the honest state of the paper today and the file says so in every row it touches.

Lane, title, and the two-axis treatment of vehicle status are settled and are not reopened here. What this file decides is the section architecture, the claim inventory with its evidentiary status, the table shells, the definitions text, and the horse race. Everything marked PENDING names the specification that would produce it. Anything requiring the full-sample rebuild now running, 2,277 days across six venues, is marked PENDING even where a four-day or eight-day version of the number already exists, and the distinction is stated in the row.

---

## 1. Section architecture, and the venue evidence for each choice

### 1.1 How the invariants below were measured, and what changed in the measurement

Nine published papers were read first-hand, selected by confirming the journal from the PDF's own first page instead of from any list in this repository. Seven carry a *Journal of Financial Economics* imprint on the article page (Chordia, Roll and Subrahmanyam 2000; Coughenour and Saad 2004; Anand and Venkataraman 2016; Clark-Joseph, Ye and Zi 2017, published version; Makarov and Schoar 2020; Li, Wang and Ye 2021; Eren and Malamud 2022). Amihud and Mendelson 1980 carries the volume imprint for Journal of Financial Economics 8 (1980), pages 31 to 53, on its own first page. Hendershott and Menkveld 2014 is an accepted manuscript with no imprint at all, and its inclusion rests on the publication record and not on anything visible in the file, which is stated here so a reader can discount it.

The corpus is now extracted to plain text at `literature/text/*.txt`, 53 papers over 1,974 pages, so every count below was re-derived by parsing numbered headings out of the text files instead of by opening PDFs. That re-derivation overturns two counts this file previously reported as zero, and Java's independent measurement was right in both cases.

**A standalone identification section exists, 1 of 8.** Hendershott and Menkveld's section 2 is titled "Empirical identification of price pressure and inventory dynamics" at line 277 of the extract, and it is a top-level section carrying the word in its title. The previous version of this file recorded 0 of 7 and reached that count by reading the section as an empirics section, which it also is. A referee scanning a table of contents sees the word.

**A standalone robustness heading exists, 1 of 8.** Clark-Joseph, Ye and Zi carry "4.2. Robustness checks" at line 819. The previous count of 0 of 9 was a count of top-level sections, where it is still correct, and the two counts describe different objects. The one that binds architecture is the heading count, because a dedicated numbered heading is what a reader navigates by. The correction narrows the invariant instead of overturning it: the robustness heading sits inside section 4, which is the section whose result it defends, so the defence still travels with the claim.

**A top-level defence of the measured object exists, 1 of 8, and it decides the question Node I raised.** Makarov and Schoar's section 8, "Discussion of arbitrages and constraints", opens at line 1923 of a 2,134-line extract and is the penultimate section before their conclusion. Its content is why their measured price deviations are real given the frictions that sustain them, from bitcoin settlement latency and multi-day fiat transfer to the absence of short selling on the exchanges trading at the largest premium. It defends the object and not a result. Node I argued that this licenses a standalone executability section here and the evidence supports the argument, with one qualification the argument did not carry: the pattern is 1 of 8, so it is a licensed option and not a norm, and it earns its place only if the object is contested. This paper's object is a counterfactual quote for a route nobody executed, and the review established that a large fraction of the measured gaps were arbitrage that would have been taken. The object is contested. Section 6 exists, and it sits where Makarov and Schoar put theirs.

### 1.2 The invariants, with counts

| Invariant | Count in the nine papers read | Architectural consequence here |
|---|---|---|
| Conclusion is the last top-level section | 9 of 9 | Section 7 is the Conclusion |
| No standalone literature-review section | 9 of 9 | Differentiation sits in the introduction, one closing sentence per strand |
| Standalone identification section, top level | 1 of 8 with data (Hendershott and Menkveld section 2) | Corrected from 0. Not adopted here: our identification is an object problem and goes to section 6 |
| Standalone robustness heading, any level | 1 of 8 with data (Clark-Joseph, Ye and Zi 4.2), 0 of 8 at top level | Robustness is a subsection of the result it defends (3.4, 4.4) and never a top-level section |
| Standalone defence of the measured object, top level | 1 of 8 with data (Makarov and Schoar section 8) | Section 6, positioned before the conclusion as theirs is |
| Institutional setting or data is the section immediately after the introduction | 5 of 7 papers with data | Section 2 |
| Rival mechanism named in a section or subsection title | 3 of 7 papers with data, 4 titles | Section 5 and its subsections |
| Top-level section count | 4, 5, 5, 6, 6, 7, 7, 8, 9; median 6 | Seven, matching Clark-Joseph and Li, Wang and Ye |
| Subsection nesting depth | Two levels in 6 of 9; three levels in 3 of 9 | Two levels everywhere |
| Abstract word count | 97, 99, 99, 102, 103, 103, 110; median 102 | Target 100, hard band 96 to 106 |
| Abstract contains a quantitative result | 1 of 7 | At most one magnitude, and only if it carries the whole argument |
| Abstract contains a t-statistic, sample size, or sample period | 0 of 7 | None |
| Tables in a paper with data | 4, 6, 7, 8, 9, 10, 12; median 8 | Seven main tables, and the count is an output |
| Figures in a paper with data | 0, 2, 2, 4, 5, 7, 11; median 4 | Four main figures |
| Introduction as a share of body pages | 7%, 9%, 12%, 12%, 14%, 15%, 23%; median 12% | 12% of body, roughly 5.5 manuscript pages |

Node I rejected the eight-table target as a design constraint, on the ground that shells whose cells read PENDING are a plan wearing the costume of an architecture, and the rejection is accepted. The table count below is seven because seven tables have a stated source specification, and it moves when the results move. The exhibit count stays in the invariant table as a calibration check on the finished paper and is no longer used to size the shell inventory.

### 1.3 The architecture

```
1. Introduction                                       ~5.5 manuscript pages, 12% of body
2. Institutional setting, definitions, and data
   2.1 What a route is, and who chooses it
   2.2 Definitions
   2.3 The route panel and how it was reconstructed
   2.4 The support screen, derived from where the quoters were validated
   2.5 Validation: level costs across intermediary types
3. Incumbents holding the role while dominated       LEAD RESULT
   3.1 Dominance on realised routes
   3.2 Which asset type is dominated, and how that changed
   3.3 The matched sample, and what matching costs
   3.4 Measurement robustness
4. How long the role survives                        THE ESTIMAND
   4.1 Routing share retained under dominance
   4.2 The price of survival, in dollars and in days
   4.3 Return edge against displacement edge
   4.4 Robustness of the survival profile
5. Rival accounts of survival                        THE HORSE RACE
   5.1 Liquidity supply as the slow state variable
   5.2 Aggregator integration scope
   5.3 The cost of holding the intermediary
   5.4 Software defaults and the road already taken
   5.5 What survives
6. Are the measured gaps real?                       DEFENCE OF THE OBJECT
   6.1 Where the quoters are validated, and where they are not
   6.2 Whether the router faced the state the panel prices
   6.3 What an unexploited gap implies, and the arbitrage bound
   6.4 Venue coverage, signed
7. Conclusion
```

Why section 3 leads with dominance on realised routes and no longer with the transition. The transition in which asset intermediates is a description, and the old file placed it first because it was the paper's largest measured object. Under the survival estimand the transition is the setting in which survival is measured and not the finding, so it moves into section 3 as the time axis along which dominance and survival are read. What leads is the state itself: a vehicle carrying realised routing while a direct pool at the same reconstructed state would have paid more. That is the state `docs/research-workflow.md` section 4.0 names as the FX literature's decisive gap, and this repository can now report it on routes that happened.

Why section 4 gets the estimand and section 5 keeps the horse race. Section 4 measures the duration and its price. Section 5 asks what produces a duration of that length, and the four accounts are the ones that would each be economically interesting if true. Measurement rivals do not appear in section 5; they are dispatched at 2.4, 3.4, 4.4 and in section 6 alongside the numbers they threaten, per the invariant that survived the correction above.

Why section 6 is top level and not a subsection. Per 1.1, because the object is contested and because Makarov and Schoar establish the position for exactly this case. Its content is the support screen's derivation, the block-against-hour timing question of whether the router faced the state the panel prices, the arbitrage bound on the gaps that survive the screen, and the signed venue-coverage bound. None of that defends a coefficient. All of it defends whether the gap is a thing that existed.

---

## 2. Claims by section, with evidentiary status

Status is EXISTS when an exhibit in `output/exhibits/` or a `docs/finding-*.md` file reports the number, and PENDING otherwise. PENDING (rebuild) marks anything that exists at small sample today and needs the full-sample rebuild across 2,277 days and six venues before it can be reported, which is most of section 4. The mechanicalness column applies the workflow's section 4 screen: a claim is mechanical when its sign is fixed by construction, and a mechanical claim may support but may not lead.

### 2.1 Section 1, Introduction

The introduction narrates the whole argument in prose carrying no notation and previews every finding. Each literature strand closes with one differentiation sentence. It states no numbered proposition and lists no hypotheses, per 0 of 9 in the read sample.

| Claim the introduction must make | Supporting result | Status | Mechanical |
|---|---|---|---|
| The FX inertia literature cannot observe an incumbent holding the vehicle role while strictly cost-dominated, because there an incumbent's cost advantage is a consequence of its incumbency | `docs/research-workflow.md` section 4.0, and the four-lane prior-art sweep returning zero | EXISTS | n/a |
| On-chain that state is observable on routes that executed, and it is common: 27.2% of realised multi-leg routing was strictly dominated by an available direct pool at the state it executed in | `docs/finding-dominance-and-persistence.md` and `output/exhibits/realised_dominance.jsonl`, matched type-specific rates reweighted to the realised population's candidate composition, covering 79.0% of realised routing, from 1,762 matched routes of 90,705 across four days | EXISTS at four days; PENDING (rebuild) at full sample | No |
| Dominance incidence differs sharply by intermediary type, at native 23.7%, stable 45.4% and imported 61.4% | Same, and the ordering is what the thick-network definition of the native type implies, so it is reported as description and not as a finding, per 2.5 | EXISTS at four days at hour-boundary state; PENDING recomputation at block-level state and PENDING (rebuild) | Partly |
| The frequency is affected in magnitude by the timing correction and not in kind, because a frequency is a statement about a state and does not require the router to have had a choice | `docs/node-e-screen-persistence.md` and the commit that measured the threat | EXISTS as a design argument, and it is what keeps section 3 standing while section 4 does not | n/a |
| The role survives dominance instead of ending with it, keeping roughly half to two thirds of its routing share | `output/exhibits/survival_after_dominance.jsonl`, native mean share 68.6% undominated against 39.4% dominated, stable 43.4% against 28.2%, imported 6.1% against 2.8% | WITHDRAWN. Measured at four days on 223 pair-candidate observations and not separable from hour-boundary staleness per 6.2. Reinstated by F1 | No |
| Survival has a price, and it is money: 83.1 million dollars routed through dominated vehicles across four days | Same exhibit, summing the dominated rows at 4.18m imported, 9.13m native, 69.74m stable | WITHDRAWN with the retention ratios it is conditioned on; the dollar total is a sum over routes classified dominated at hour-boundary state | No |
| Survival has a length in days, and the length is what the inertia literature has always wanted | `scripts/run_displacement_asymmetry.py` | PENDING. The script exists and refuses to report: 4 consecutive priced days available against 20 required | No |
| Whether the incumbent holds on longer than a challenger takes to break in separates hysteresis from persistence | Same script, both arms defined on the same quantity | PENDING (rebuild) | No |
| The vehicle role migrated from the native platform asset to the stable numeraire inside six years, in both directions | `docs/finding-intermediation-transition.md`, native 73.0% to 14.8% value-weighted, stable 21.2% to 50.1% | EXISTS | No |
| Removing a hard architectural mandate to use the native asset did not reduce native-asset pairing | `docs/finding-v1-forced-vehicle.md` section 3, new-pair WETH share 84.1% in 2020 rising to 97.9% in 2026 | EXISTS | No |
| Studying one venue becomes progressively wrong across the sample | `docs/router-identification-feasibility.md` cross-venue series, 1.2% to 61.1% count-weighted | EXISTS | Partly |

The introduction may not describe the native asset as cheaper to route through as a finding. Per Node I section 5 and accepted here, the native platform asset is defined in `docs/research-workflow.md` section 3 as the asset with the thickest incumbent pairing network, so a result that the thickest-network asset is the cheapest route restates the maintained assumption of Krugman (1980) and of the literature this paper cites. The level comparison appears in section 2.5 as evidence that the quoting engine reproduces a known ordering, which is what a validation exhibit is for.

### 2.2 Section 2, Institutional setting, definitions, and data

| Claim | Supporting result | Status | Mechanical |
|---|---|---|---|
| A route unit is the economic object, and one coherent multi-leg component is one route unit regardless of leg count | Registry definition of $r$ | EXISTS | n/a |
| Routing is executed by deterministic graph optimisers, which removes quote-time habit as a channel and relocates incumbency to state variables | `docs/research-workflow.md` section 4.0 | EXISTS | n/a |
| Round-trip routes are atomic arbitrage or wash trading and are excluded before anything is measured | `docs/router-identification-feasibility.md`, 25.6% of multi-leg routes by count and 90.5% by value on the day inspected | EXISTS | No |
| Six venues are priced and each quoter was accepted against realised swaps | `docs/venue-coverage-bounds.md`, v2 and sushiswap_v2 on constant product, v3 and v4 on exact tick state, Curve on a per-pool-day calibrated amplification coefficient at 0.022% median error, Balancer on the weighted geometric mean at 0.0000% median error on backward-rolled balances | EXISTS for the quoters; PENDING for Balancer's integration into the route panel | n/a |
| sushiswap_v3 is excluded and the exclusion is a decision with a number behind it | Same, 0.016% of priced-venue volume pooled and 4.1% of its volume on pairs no priced venue hosts | EXISTS | n/a |
| The panel refuses to quote a leg whose own price impact exceeds 5% of the trade, and the threshold is derived from where the quoters were validated | `output/exhibits/quoter_support_bounds.jsonl`, 932,270 validated swaps across eight sampled days, pooled median size-to-depth 0.34%, p90 3.3%, p99 14.9% | EXISTS | n/a |
| The screen removes 70% to 86% of quotable routes and cuts median gaps from thousands of basis points to tens | `scripts/measure_dominance_windows.py` and `output/exhibits/gap_arbitrage_bound.jsonl`, post-screen median gap 31 bps at $1,000, 34 bps at $10,000 and 21 bps at $100,000, against a pre-screen median of 4,655 bps at $100,000 | EXISTS | n/a |
| The executor is identifiable from the calling contract and the routing author is only partly recoverable | `docs/router-identification-feasibility.md`, 241 distinct senders on 74,323 swaps, executor population fragmenting to 397 senders by late 2025 with a hand registry covering 11.8% | EXISTS | No |
| The reconstruction advantage is engineering difficulty and not private data | `docs/research-workflow.md` section 2, corrected from the retracted data-moat reading | EXISTS | n/a |

**2.5, the level comparison as validation.** This is where the retired estimand lives, and the framing is that a quoting engine which reproduces a ranking the literature already assumes is a quoting engine behaving as expected. On the screened panel with a pair-by-window-by-size fixed effect the native indicator on the continuous gap is -25.3 basis points with a standard error of 11.4 (0.037), on 732 routes in 274 cells. The binary version of the same specification is -0.043 (0.543) and is not reported as a result. The retired -0.383 on the unscreened binary does not appear in the paper at all, for the reason in Node I ground 1: a shift in the probability that one quoted number exceeds another, at a threshold the design absorbs, has no mapping to basis points without the density at the threshold, and this repository owns the continuous object. The subsection states in one sentence that the ordering matches what the thick-network definition implies and that the paper takes no credit for it.

### 2.3 Section 3, Incumbents holding the role while dominated

| Claim | Supporting result | Status | Mechanical |
|---|---|---|---|
| On routing that actually executed, 27.2% was strictly dominated by an available direct pool at the same reconstructed state, population-weighted and covering 79.0% of realised routing | `output/exhibits/realised_dominance.jsonl` REWEIGHTED row, from 1,762 matched routes over four days | EXISTS at four days; PENDING (rebuild) | No |
| The raw matched mean is 41.3% and it is not the population figure, because matching is inverted on candidate type | Same, daily matched rates 49.5%, 38.0%, 39.2%, 37.9%, against a matched composition of 64.1% stable where the population is 67.7% native | EXISTS | n/a |
| Weighted by value the matched incidence runs 33.5% to 46.7% across the four days | Same, `value_weighted` field, and no population reweighting of the value figure exists | EXISTS at four days; PENDING for the reweighted value figure | No |
| 27.2% lands close to the 30.0% all-in figure the retired v2-only analysis reported, by a path that reuses none of that computation | `docs/finding-dominance-and-persistence.md` | EXISTS, and it is reported as a convergence and not as a confirmation, since both could share an error in the underlying quoting | n/a |
| Enumerating every candidate a router could have chosen returns 70.1% gross and 80.3% all-in, and it answers a different question | `output/exhibits/dominance_windows_screened.jsonl`, 1,839 enumerated routes post-screen | EXISTS | Partly, and it is reported as the enumeration bound and never as the incidence |
| The realised figure and the enumerated figure differ because most enumerated two-hop routes are ones nobody took, and holding the role means being used | `scripts/measure_realised_dominance.py` header | EXISTS as a design statement | n/a |
| The retired 17.9% was a v2-only, unscreened, enumerated figure and is superseded in all three respects | `docs/finding-cost-dominance-measured.md`, now superseded | EXISTS as a correction | n/a |
| Post-screen enumerated dominance by type runs native 62.0%, stable 69.1%, imported 85.0% gross | `output/exhibits/dominance_windows_screened.jsonl`, 347, 1,212 and 280 routes | EXISTS | Partly |
| Dominance incidence on realised routes by intermediary type, at native 23.7%, stable 45.4% and imported 61.4% | `scripts/characterise_matched_sample.py` and `scripts/measure_realised_dominance.py`, the same rates that carry the reweighting | EXISTS at four days; PENDING (rebuild) for the year dimension | Partly |
| The vehicle role migrated from native to stable across the sample, and the migration is the time axis dominance is read against | `docs/finding-intermediation-transition.md`, 2,240 days | EXISTS | No |
| The value-weighted crossover arrives 2022-Q1 and is sustained from 2022-Q4; the count-weighted crossover appears only in 2026-H1 | Same | EXISTS | No |
| The matched sample is not the realised population, and the direction of the difference is measured | `output/exhibits/matched_sample_characterisation.jsonl`, matched median trade $11,594 against $866 unmatched, native share 26.5% against 67.7%, stable 64.1% against 10.3%, `other` 0.0% against 21.3% | EXISTS, and it is the paper's largest disclosed limitation | n/a |
| The transition is present venue by venue and is not the death of one venue | Same series recomputed with a venue dimension | PENDING | No |
| The transition survives the turnover-spike, volume-spike, arbitrage-cycle and organic-versus-MEV screens on top of the round-trip filter | `docs/research-workflow.md` section 4.2 names the screens as unapplied | PENDING | No |

The matched-sample row is the one that decides whether section 3 can lead, and it is the reason the headline is 27.2% and not 41.3%. Matching a realised route to a counterfactual quote requires the panel to carry that pair, that candidate and that state, and only 1.9% of realised multi-leg routes clear it, on 71 pairs against 17,851. The survivors are 13 times larger at the median and are 64.1% stable-intermediated where the realised population is 67.7% native-intermediated, with the entire `other` category absent. Because dominance rates differ by a factor of two and a half across candidate types, quoting the raw matched mean as a population figure would be a statement about large trades on busy pairs through stablecoins. Reweighting the matched type-specific rates to the population's composition gives 27.2% and covers 79.0% of realised routing, and the residual 21.0% is `other` and staked-native routing for which no matched rate exists. Section 3.3 reports the reweighting arithmetic in full so a reader can redo it, and states what the reweighting cannot fix: nothing conditional on trade size generalises, because the panel prices three fixed notionals and matched trades are an order of magnitude larger than the population's.

### 2.4 Section 4, How long the role survives

| Claim | Supporting result | Status | Mechanical |
|---|---|---|---|
| A dominated vehicle keeps a large share of its routing instead of losing it | `output/exhibits/survival_after_dominance.jsonl` | WITHDRAWN pending F1, measured at four days | No |
| Native retains 39.4% mean routing share while dominated against 68.6% while not, a retention ratio of 0.57 | Same, 25 dominated and 23 undominated pair-candidate observations | WITHDRAWN pending F1 | No |
| Stable retains 28.2% against 43.4%, a ratio of 0.65 | Same, 98 dominated and 53 undominated observations | WITHDRAWN pending F1 | No |
| Imported retains 2.8% against 6.1%, a ratio of 0.45, on 20 dominated observations | Same | WITHDRAWN pending F1, and too thin to report as a type contrast in any case | No |
| The retention ratio does not order by incumbency, since stable retains more of its share than native does | Same | WITHDRAWN pending F1, and it is the finding that would falsify a simple incumbency story if it survives repricing | No |
| 83.1 million dollars of routing passed through dominated vehicles across four days | Same, dominated USD rows | WITHDRAWN pending F1, because the classification it sums over is the one under repair | No |
| Dollars foregone, meaning the money the dominated routing gave up against the direct alternative | Not the same object as dollars routed. Specification: the matched realised routes' USD notional multiplied by the realised gap in basis points, summed | PENDING. This is the Makarov and Schoar magnitude and nothing in the repository computes it yet | No |
| Days a dominated incumbent holds the role before turnover | `scripts/run_displacement_asymmetry.py`, retention arm | PENDING. The script refuses at 4 consecutive priced days against 20 required, and the refusal is on record in `output/exhibits/displacement_asymmetry.jsonl` | No |
| Days a challenger with an edge takes to become the incumbent | Same script, displacement arm | PENDING (rebuild) | No |
| Retention duration exceeds displacement duration, which is hysteresis; equality is persistence under symmetric frictions | Same script, the two arms compared on the same pairs | PENDING (rebuild), and this is the single claim the paper is being written to make | No |
| The survival profile is not an artefact of the fixed-size notional grid | Specification: re-run both arms at $1,000, $10,000 and $100,000 and report whether the duration ordering is common across the grid | PENDING (rebuild) | No |
| The survival profile is not an artefact of the support screen | Specification: re-run at a 2% and a 10% price-impact ceiling and report the retention ratios at each | PENDING (rebuild) | No |

Section 4 currently has no admissible measurement and the reason is measured, not suspected. `docs/node-e-screen-persistence.md` named hour-boundary pricing as the dangerous threat to persistence, and `output/exhibits/repricing_at_block.jsonl` confirms it at 86.2% of routes mispriced by more than 25 basis points at the median pool. A route that was cheapest when the router quoted and dominated by the time the hour closed records as dominated when the router could not have avoided it, so a retention ratio computed on that classification cannot be separated from staleness. Every retention ratio in this section is WITHDRAWN until F1 reprices realised routes at their own block, and the rows below are retained with their numbers so the reinstated version can be compared against them.

One thing survives the withdrawal and it is the design argument, which is why section 4 keeps its place in the architecture. The comparison is against the same vehicle's share when not dominated and not against zero, so a story in which routing shares are merely sticky predicts no differential at all, and the definitional screen is the one screen the result passes on its own construction. Whether the differential is 68.6% against 39.4% or something else is what F1 decides.

Even reinstated, the result will not license the word hysteresis, which needs the displacement arm, and will not license a causal reading, which needs the objective-mismatch bound of section 6.2.

Every duration in this section is PENDING and the reason is stated so it is not mistaken for a gap in effort. A duration cannot be measured on a cross-section, both arms need runs of consecutive priced days, and the priced panel holds four. The rebuild across 2,277 days is what supplies them. What EXISTS today is the cross-sectional half of the estimand, that share survives dominance, at four days and 223 pair-candidate observations, and that half is enough to establish the phenomenon and not enough to price it.

### 2.5 Section 5, Rival accounts of survival

Claims here are the horse race and are set out in full in section 5 of this file. All four are PENDING, and unlike the previous version of this spine that is now a schedule and not a structural problem, because the rebuild that produces section 4 produces the inputs to three of the four.

### 2.6 Section 6, Are the measured gaps real?

| Claim | Supporting result | Status |
|---|---|---|
| Each quoter was accepted against realised swaps, and every one of those validations draws from trades whose pool was deep enough to serve them | `scripts/measure_quoter_support.py` header, with the per-venue median errors in `docs/venue-coverage-bounds.md` | EXISTS |
| The validation population's size-to-depth distribution is measured, and the panel's support bound is derived from it | `output/exhibits/quoter_support_bounds.jsonl`, pooled median 0.34%, p90 3.3%, p99 14.9%, on 932,270 swaps | EXISTS |
| The screen is ex ante on the pool and not a filter on the gap, so it does not repeat the selection-on-the-dependent-variable error | Same header, and Node I objection 5 | EXISTS as a design property |
| A router quotes at a block and the panel prices at an hour boundary, so a route cheapest at quote time and dominated by the hour's close records as dominated when the router could not have avoided it | `docs/node-e-screen-persistence.md` threat 1 | EXISTS as a stated threat, and the measurement below confirms it instead of bounding it |
| The threat is live at the median pool: 86.2% of routes are mispriced by more than 25 basis points and the median deviation is 1.166%, against route-cost differences of tens of basis points | `output/exhibits/repricing_at_block.jsonl`, `scripts/reprice_realised_at_block.py`, 40 pools | EXISTS, and it is why every retention ratio in section 4 is withdrawn |
| The error concentrates where validation did not look, which is why it was invisible earlier | Same. USDC/WETH at the 5-basis-point tier shows a 0.085% median deviation with 16.5% of routes past the threshold and WETH/USDT shows 0.012% and 13.5%, while volatile pools run 1.8% to 4.9% median deviation with 89% to 97% past it | EXISTS |
| Re-pricing each realised route at its own block closes the threat, and the fix is a separation and not another rebuild | Same. The counterfactual panel is a cost surface sampled at intervals and stays hourly; the realised-route analysis moves to block-level state, which the data supports because v3 and v4 carry `sqrtPriceX96` and `tick` on every swap and the constant-product family unwinds backward from the stored end-of-hour reserve at 0.0000% median error | PENDING, and it is F1 |
| The timing threat bears on persistence and not on the dominance frequency, because a frequency is a statement about a state and does not require the router to have had a choice | Same | EXISTS as a design argument |
| The router optimises something other than quoted output, weighing MEV exposure, failure probability and private orderflow alongside gas | Same, threat 3. Gas is handled by the all-in comparison; the rest are not observable here | PENDING for a bound on what fraction of persisting volume each could explain, and it is the strongest referee objection to the persistence claim |
| Post-screen, the median gap is 31 bps at $1,000, 34 bps at $10,000 and 21 bps at $100,000 | `output/exhibits/gap_arbitrage_bound.jsonl` | EXISTS |
| A residual share of post-screen gaps still exceeds three pool fees plus three-hop gas, at 13.6% at $1,000, 38.5% at $10,000 and 22.0% at $100,000 | Same, `share_above_threshold` against thresholds of 169, 71 and 61 bps | EXISTS, and it is reported as an unresolved upper bound on measurement error |
| Whether an atomic cycle appears in the same block for the gaps above threshold | Specification: join the flagged cells to same-block swap sequences and report the share with a closing cycle | PENDING, and it is what would split arbitrage that was taken from quoter error |
| Venue coverage gaps push the native-versus-stable comparison against the native asset in every year, so the comparison is a floor | `docs/venue-coverage-bounds.md`, Curve's gate removing 65.2% of native-leg volume against 21.1% of stable-leg volume, the gap at least 33 percentage points in every year | EXISTS |
| Balancer is the largest venue with a built quoter and no route-cost integration, at 3.9% of panel volume pooled and 8.8% at its 2023 peak | Same | EXISTS |
| Closing the Curve gate by pricing crypto-pools on the CryptoSwap invariant widens the native advantage instead of narrowing it | Same, stated as a falsifiable prediction | PENDING |

### 2.7 Section 7, Conclusion

| Claim | Supporting result | Status |
|---|---|---|
| An incumbent vehicle keeps the role after it stops being the cheapest route, and the on-chain record prices what that costs | Sections 3 and 4 jointly | PENDING. Section 3 stands at hour-boundary state and section 4 is withdrawn pending F1, so the paper's own headline sentence is not currently supported |
| Whether the persistence is hysteresis or symmetric friction, stated as a finding including the null | Section 4.3 | PENDING (rebuild) |
| A dominance transition that took the sterling-to-dollar literature decades is observable inside six years with the road not taken priced | Section 3 | EXISTS, subject to recomputation at block-level state |
| Which rival account survives, stated as a finding including the null | Section 5.5 | PENDING |

The conclusion reports the null on whichever rivals fail, per the standing rule that reporting a null is mandatory and belongs in results. It contains no limitations opener and no reconciliation against this repository's own earlier plans.

---

## 3. Table shells

Notation is the registry in `src/ddvc/variable_registry.py`. No number appears that is not already in an exhibit or a findings document. Seven shells, and the count is an output of what has a stated source specification.

### Table 1. Sample construction and coverage

Rows are filters in application order; columns record what each filter costs. Sample restriction: every priced venue in the unified layer, 2020-02-11 to 2026-06-30.

| Filter | Route units $r$ | Share kept | $\mathrm{Vol}_t$ summed, USD | Share kept |
|---|---|---|---|---|
| All reconstructed route units | 364,324,757 | 1.000 | PENDING | 1.000 |
| Route units with at least one intermediate, $N^I_t$ | PENDING | PENDING | PENDING | PENDING |
| Economic intermediation, first input token differing from last output token | PENDING | PENDING | PENDING | PENDING |
| Round trips excluded | PENDING | PENDING | PENDING | PENDING |
| Turnover-spike and volume-spike screens applied | PENDING | PENDING | PENDING | PENDING |
| Arbitrage-cycle detection applied | PENDING | PENDING | PENDING | PENDING |
| Intermediary token classified into a type | PENDING | PENDING | PENDING | PENDING |
| Support screen applied, price impact per leg at most 5% | PENDING | PENDING | PENDING | PENDING |
| Matched to a counterfactual direct quote at the same state | PENDING | PENDING | PENDING | PENDING |

The last two rows are new and they are the expensive ones. On the four measured days the support screen removes 70% to 86% of quotable routes and the counterfactual match retains 1,762 of 90,705 realised multi-leg routes, which is 1.9%. Memo rows from `docs/router-identification-feasibility.md`: 471,616,631 swap legs reduce to 364,324,757 route units across 2,277 days, and venues active rise from 3 in 2020 to 8 in 2025 and 2026.

### Table 2. The matched sample against the realised population

The table that makes the paper's selection legible, and it exists in full today. Rows are attributes; columns are matched, unmatched, and the ratio. Source `output/exhibits/matched_sample_characterisation.jsonl`.

| Attribute | Matched | Unmatched | Ratio |
|---|---|---|---|
| Median trade, USD | 11,594 | 866 | 13.40 |
| Mean trade, USD | 87,941 | 4,559 | 19.29 |
| 90th percentile trade, USD | 208,204 | 6,454 | 32.26 |
| Share native | 0.265 | 0.677 | 0.39 |
| Share stable | 0.641 | 0.103 | 6.20 |
| Share imported | 0.094 | 0.005 | 17.23 |
| Share staked native | 0.000 | 0.002 | 0.00 |
| Share other | 0.000 | 0.213 | 0.00 |
| Routes per pair | 25.03 | 4.98 | 5.02 |

The note states what the ratios do to the headline. Matching selects toward large stable-intermediated routing on well-covered pairs, and the `other` category, which carries 24.2% of 2026 intermediation episodes across 9,283 distinct tokens, is entirely absent. Every incidence and every retention ratio in sections 3 and 4 is conditional on this sample, and the rebuild is what widens it.

### Table 3. Dominance on realised routes

The paper's lead exhibit. Panel A rows are days in the current sample and will be years after the rebuild; columns are matched routes, dominance incidence by count, and by value. Source `output/exhibits/realised_dominance.jsonl`.

| Day | Realised multi-leg routes | Matched | Dominated, count | Dominated, value |
|---|---|---|---|---|
| 2023-06-01 | 24,847 | 475 | 49.5 | 46.7 |
| 2023-06-02 | 23,959 | 598 | 38.0 | 33.5 |
| 2023-06-03 | 21,108 | 306 | 39.2 | 37.9 |
| 2023-06-04 | 20,791 | 383 | 37.9 | 38.6 |
| Raw matched mean | 90,705 | 1,762 | 41.3 | PENDING |
| **Population-weighted** | 90,705 | 1,762 | **27.2** | PENDING |

The headline row is the reweighted one and the table note says why in one sentence: the matched mean describes the sample that matched, the population weighting describes realised routing, and the two differ by 14 percentage points because matching is inverted on candidate type. Panel B is the type split that carries the reweighting.

| Intermediary type | Dominance rate on realised routes | Share of realised routing |
|---|---|---|
| Native | 23.7 | 67.7 |
| Stable | 45.4 | 10.3 |
| Imported | 61.4 | 0.5 |
| Other and staked native | no matched rate | 21.5 |
| Covered, weighted | 27.2 | 79.0 |

The note on panel B carries the constraint from 2.5. Native routing is dominated least, which is the ordering the definition of a thick-network incumbent already implies, so the row is reported as description and the paper takes no credit for it. What the panel is for is the reweighting and the coverage figure. Panel C is the enumeration bound, from `output/exhibits/dominance_windows_screened.jsonl`, reported so a reader can see the two questions apart.

| Enumerated scope | Routes | Dominated, gross | Dominated, all-in |
|---|---|---|---|
| Native | 347 | 62.0 | 67.1 |
| Stable | 1,212 | 69.1 | 81.4 |
| Imported | 280 | 85.0 | 92.1 |
| All | 1,839 | 70.1 | 80.3 |
| At $1,000 | 804 | 67.4 | 85.2 |
| At $10,000 | 631 | 74.6 | 80.8 |
| At $100,000 | 404 | 68.6 | 69.8 |

The note distinguishes the panels in one sentence. Panel A asks how often a vehicle carrying realised routing was worse than the direct alternative, which is the state the FX literature cannot observe. Panel C asks how often any enumerated two-hop route through a candidate would have been worse, which is a property of the route universe and includes routes nobody would take. Neither figure may be quoted as the other and the retired 17.9% was neither, being a v2-only unscreened enumeration.

### Table 4. Survival of the role under dominance

The estimand's exhibit, and every cell in it is WITHDRAWN pending F1. Panel A is the cross-sectional retention as measured at hour-boundary state, printed here so the reinstated version can be compared against it and clearly marked so no downstream document lifts it. Rows are intermediary types; columns are mean and median routing share when not dominated and when dominated, the retention ratio, observations, and dollars routed.

| Type | Mean share, not dominated | Mean share, dominated | Retention ratio | Obs, not dominated | Obs, dominated | USD routed while dominated |
|---|---|---|---|---|---|---|
| Native | 0.686 | 0.394 | 0.57 | 23 | 25 | 9,132,313 |
| Stable | 0.434 | 0.282 | 0.65 | 53 | 98 | 69,743,192 |
| Imported | 0.061 | 0.028 | 0.45 | 4 | 20 | 4,181,839 |
| All | PENDING | PENDING | PENDING | 80 | 143 | 83,057,344 |

Panel B is the duration table and every cell is PENDING, from `scripts/run_displacement_asymmetry.py`. Rows are the retention arm and the displacement arm; columns are the median duration in days, the interquartile range, the number of spells, and the difference between arms with its standard error. The script currently writes a refusal, that 4 consecutive priced days are available against 20 required, and the refusal stands until the rebuild lands.

Panel C is the price of survival and is PENDING. Rows are intermediary types; columns are dollars routed while dominated, the median realised gap in basis points, and dollars foregone, meaning notional multiplied by gap summed over dominated realised routes. The middle and right columns are the Makarov and Schoar magnitude and nothing computes them yet. Dollars routed and dollars foregone are separate objects and the table note says so, because 83.1 million dollars passing through a dominated vehicle at a median gap of tens of basis points is a foregone figure in the low hundreds of thousands, and conflating them would overstate the result by three orders of magnitude.

### Table 5. Rival accounts of survival

Rows are the four accounts of section 5; columns are the discriminating prediction, the required sign, the estimate, and the verdict. Every estimate cell is PENDING and the schedule is the rebuild.

| Account | Discriminating prediction | Required sign | Estimate | Verdict |
|---|---|---|---|---|
| Liquidity supply as the slow state variable | Retention duration is increasing in $\mathrm{LPConc}_{k,t}$ after conditioning on the contemporaneous gap, and provider capital moves after routing does | $\gamma>0$ on duration; capital lags routing | PENDING | PENDING |
| Aggregator integration scope | Retention duration is longer on pairs whose cheaper alternative sits on a venue fewer aggregators had integrated at the time | Duration decreasing in integration breadth | PENDING | PENDING |
| Cost of holding the intermediary | Retention duration is shorter for a volatile incumbent under its own stress, and $\mathrm{CandidateStress}_{k,t}$ shortens native spells while lengthening stable ones | Sign flip by type; post-outcome placebo null | PENDING | PENDING |
| Software defaults | Duration falls as a step at routing-software release dates, does not move on venues whose software did not change, and native pairing does not retreat when the V1 mandate is withdrawn | Step timing; no cross-venue spillover; V1-to-V2 null | V1-to-V2 null EXISTS and favours this account | Partly supported |

The fourth account is the one this paper's own evidence currently favours and it is reported that way, following the practice of rejecting one's own preferred account first. Two accounts pointing in opposite directions is the reason the section exists.

### Table 6. Level costs across intermediary types, validation

Demoted from the previous version's table 6, and it now reports the continuous object on the screened panel. Source `output/exhibits/dominance_specification_curve.jsonl`.

| Specification | Native coefficient | Standard error | $p$ | Groups | N |
|---|---|---|---|---|---|
| Pooled, binary outcome | -0.101 | 0.070 | (0.150) | 0 | 1,839 |
| Pooled, plus log size | -0.102 | 0.069 | (0.145) | 0 | 1,839 |
| Pair fixed effect, binary | -0.063 | 0.070 | (0.381) | 23 | 812 |
| Pair by window by size, binary | -0.043 | 0.069 | (0.543) | 274 | 732 |
| Pair by window by size, gap in basis points | -25.26 | 11.38 | (0.037) | 274 | 732 |
| Routes touching a tick venue, binary | -0.047 | 0.070 | (0.510) | 269 | 719 |
| Native interacted with log size | +0.0023 | 0.0209 | (0.914) | 274 | 732 |

The last row is the correction the previous version of this file most needed. The trade-size gradient it treated as the hinge of a mechanism is a flat line when the interaction is estimated instead of read off three separate subsamples, and no document in this repository may describe the native advantage as weakening with size. The basis-point row is the only line in the table with a $p$ below 0.05 and it is reported as validation, not as a finding, per 2.5.

### Table 7. Venue coverage and the signed bound

Rows are the seven venues; columns are pooled volume share, priced or not, and the direction the omission pushes the native-versus-stable comparison. Every cell EXISTS in `docs/venue-coverage-bounds.md`. The table's note carries the sign in one sentence: every remaining gap understates the native side, so any native-versus-stable comparison in the paper is a floor and not a point.

### Figures

| Figure | Content | Status |
|---|---|---|
| 1 | $\mathrm{TypeCountShare}^{\theta}_t$ and $\mathrm{TypeShare}^{\theta}_t$ for the four classified types, monthly, 2020 to 2026, with both crossover dates marked | EXISTS as data, PENDING as an exhibit |
| 2 | Dominance incidence on realised routes, monthly, by intermediary type, against the type share on the same axis | PENDING (rebuild), and this is the exhibit that joins the transition to the estimand |
| 3 | The two survival curves, retention and displacement, on the same pairs, with the gap between them shaded as the incumbency premium in days | PENDING on F1 and then on the rebuild, and it is the paper's single most important figure |
| 4 | Specification curve for the retention-duration estimate with the joint inference test | PENDING (rebuild) |

Figure 3 is what the paper is for. If the two curves lie on top of each other the finding is symmetric friction and the paper reports it as a null, which is publishable under this project's standing rule and is the honest outcome if that is what the data say.

---

## 4. Section 2.2, Definitions, written out

The paper's object is not whether an asset is used as an intermediary. Vehicle status in that sense is binary and one bridging swap satisfies it, which makes the label uninformative about anything a reader cares about. What the paper measures is how long one asset holds an intermediation role after the economics stop supporting it, and dominance is treated throughout as a continuous share on an axis separate from status.

**Definition 1, route unit.** A route unit $r$ is a reconstructed input-to-output execution inside one transaction. A coherent $i\to k\to o$ component contributes one route unit whatever its number of legs, and a split or a join contributes one route unit for each reconstructed input-output pair. Counting legs would weight a route by how many pools a router happened to touch, which is a property of the router.

**Definition 2, direct and indirect routes.** For an ordered endpoint pair $(i,o)$, the direct route is the single-hop execution $i\to o$. An indirect route passes through at least one intermediate token. The indirect route through candidate $k$ is $i\to k\to o$ with $k\notin\{i,o\}$.

**Definition 3, vehicle use.** Token $k$ is used as a vehicle in route unit $r$ when $k$ is an intermediate of $r$. The day-$t$ vehicle share of $k$ is $\mathrm{VehicleShare}_{k,t}=\mathrm{IVol}_{k,t}/\mathrm{IVol}_t$. Its count-weighted counterpart is $\mathrm{VehicleCountShare}_{k,t}=N^I_{k,t}/N^I_t$, and its all-route counterpart $\mathrm{AllRouteVehicleShare}_{k,t}=\mathrm{IVol}_{k,t}/\mathrm{Vol}_t$ carries direct volume in the denominator so the economic scope of routed exchange stays visible.

**Definition 4, dominance, and the distinction the paper turns on.** A realised route unit $r$ through candidate $k$ is *dominated* when the best available direct route for the same ordered pair, priced at the same reconstructed pre-trade state, would have returned more than $r$ did. Dominance is therefore a property of a route someone took. A candidate $k$ is *enumerably dominated* for a cell $(i,o,q,t)$ when the best direct quote exceeds the best two-leg quote through $k$, whether or not anyone routed through $k$. The first is the state the FX literature cannot observe, because holding the role means being used. The second is a property of the route universe and is reported as a bound. The paper never substitutes one for the other, and the previous 17.9% figure was the second measured on one venue family without a support screen.

**Definition 5, asset types.** The claim is about currency types and tickers appear only as proxies. A *native platform asset* is the platform's own settlement asset, carrying the thickest incumbent pairing network and high volatility, whose traditional counterpart is the incumbent international currency whose role rests on thick-market externalities. A *stable numeraire* is a low-volatility unit of account. An *imported store of value* is a non-native asset brought on-platform in wrapped form, including tokenised gold. A *staked native derivative* holds the native asset's exposure in a different instrument, and it is held apart from the native type because whether it counts as the same currency is a specification choice; the paper reports both treatments. Every other intermediary token is *other*, which is a real category carrying 24.2% of 2026 intermediation episodes across 9,283 observed intermediary tokens, and which is entirely absent from the matched sample per table 2. Because the native type is defined by having the thickest pairing network, the paper may not report as a finding that the native asset is the cheapest route, and section 2.5 states that constraint where the level comparison appears.

**Definition 6, candidate set.** $\mathcal K=\{\mathrm{WETH},\mathrm{USDC},\mathrm{USDT},\mathrm{DAI},\mathrm{WBTC}\}$ is the prespecified set used wherever a counterfactual must be quoted for every candidate. The type shares of definition 5 are measured over the whole observed intermediary population and not over $\mathcal K$: $\mathcal K$ is the quoting universe and the taxonomy is the measurement universe.

**Definition 7, all-in route cost.** For notional $q$ at reconstructed pre-trade state, the direct all-in cost is $C^{D}_{i,o,q,t}=1-O^{D}_{i,o,q,t}/q+G^{D}_{i,o,q,t}/q$ and the indirect all-in cost through $k$ is $C^{I}_{i,o,k,q,t}=1-O^{I}_{i,o,k,q,t}/q+G^{I}_{i,o,k,q,t}/q$, where $O$ is quoted output value and $G$ is route gas expenditure at the day's gas price and gas-token price. Quote-output cost and all-in cost are separate objects and are never substituted: $\Delta C^{D}_{i,o,k,q,t}=(O^D-O^I)/O^D$ excludes gas and $\Delta C^{D,\mathrm{all}}_{i,o,k,q,t}=C^{I}-C^{D}$ includes it. Positive values of either favour the direct route. Gas must enter as a candidate-specific and venue-specific term and not as a per-hop constant, because a cost common to every candidate inside a group is absorbed by the group fixed effect and cannot move a coefficient at all.

**Definition 8, the support screen.** The panel declines to quote any leg whose own price impact at notional $q$ exceeds 5% of the trade. The threshold is derived and not chosen: the quoters were each accepted against realised swaps, and the size-to-depth distribution of that validation population has a pooled median of 0.34%, a 90th percentile of 3.3% and a 99th percentile of 14.9% across 932,270 swaps on eight sampled days, so 5% sits between the 90th and 99th percentiles of the region where the quoter has measured error. The screen is ex ante on the pool state, so it conditions on nothing downstream of the outcome. This is what replaces the retired trim on absolute cost advantage, which conditioned on a monotone function of the binary outcome and could not defend anything.

**Definition 9, common support.** $\mathcal C_{k,t,q}=\mathcal D_{k,t,q}\cap\mathcal I_{k,t,q}$ is the set of pairs for which both routes execute at notional $q$ and both clear the support screen. Cost comparisons are made only on common support. Pairs off common support are retained as availability outcomes and are never deleted.

**Definition 10, incumbent and challenger.** The incumbent vehicle $k^\star_{i,o,t}$ has the largest mean $\mathrm{VehicleShare}_{i,o,k,u}$ over the 30 calendar days ending at $t-1$, using only information dated before $t$. The challenger $h^\star_{i,o,q,t}$ is the executable non-incumbent candidate with the smallest $C^I_{i,o,h,q,t}$ on day $t$. The challenger's edge is $\mathrm{ChallengerCostEdge}_{i,o,q,t}=C^I_{i,o,k^\star,q,t}-C^I_{i,o,h^\star,q,t}$, positive when the challenger is cheaper.

**Definition 11, retention and displacement spells.** A *retention spell* opens on the first day an incumbent becomes dominated on a pair and closes on the first day it is no longer the incumbent, and its length in days is the survival quantity. A *displacement spell* opens on the first day a non-incumbent candidate holds an edge, meaning routing through it beats the direct pool while the incumbent's route does not, and closes on the first day it becomes the incumbent. Both are defined on the same pairs and the same share quantity so the two durations are comparable. *Persistence* is the finding that retention spells have positive length. *Hysteresis* is the finding that retention spells exceed displacement spells, and the difference between the two medians is the incumbency premium measured in days. Neither duration is reported alone, because persistence on its own is consistent with slow information and with switching frictions that apply equally in both directions.

**Definition 12, what routing agency is and is not.** Route selection is executed by smart-order routers that are deterministic graph optimisers over current pool state, which removes trader habit as a quote-time channel. Preferring an incumbent intermediary when a cheaper direct route exists therefore cannot be read as trader inertia, and the survival estimand is not a claim about habit. Incumbency in this paper operates through state variables that update slowly, being liquidity-provider capital allocation, where providers face switching costs and attention limits, and aggregator integration scope, which is a business decision on a business cadence. A router choosing the native asset because its pools are deepest is optimal at that instant, and the reason those pools are deepest may still be historical incumbency. This is why the survival estimand is the right one for this instrument: the duration of a dominated role is a statement about how fast those state variables move, and the definition of a thick-network incumbent says nothing about their speed.

---

## 5. Named rival mechanisms: the horse race on survival

**The leading claim, stated in the form the rivals have to beat.** A vehicle that stops being the cheapest route keeps a substantial part of its routing share, and it keeps it for a measurable number of days. The magnitude in that sentence carries no number until F1 lands, because the four-day figures of roughly half to two thirds are withdrawn and the rivals have to beat whatever the repriced version says. Four accounts could produce a duration of that length, and each is stated with the empirical fact that separates it from the others. Following the practice of rejecting one of one's own first, the fourth account is the one this paper's own V1 evidence currently favours and it is reported that way.

The horse race is now about duration and no longer about the level, and that is the substantive consequence of the estimand change. The old section 5.1, thick-market cost advantage, is gone from the race entirely. It explained why the native asset was cheap, which the definition already supplies, and Node I established that confirming it is not a contribution. Its empirical content moves to section 2.5 as validation. What the surviving four accounts have to explain is why routing does not leave the moment the cost advantage does.

### 5.1 Liquidity supply as the slow state variable

Routing follows depth instantaneously, and depth follows provider capital, which moves slowly because providers face switching costs and attention limits. The role survives dominance for exactly as long as it takes capital to reallocate, and the duration is a measurement of provider stickiness with no behavioural content on the trading side at all.

What separates it: the duration should be increasing in $\mathrm{LPConc}_{k,t}$ after conditioning on the contemporaneous gap, and provider capital should move after routing does and not before. If capital leads routing, the account is refuted and the causality runs the other way.

What this account may not be tested with: a lagged dependent variable plus fundamentals controls. That is the specification the FX literature itself shows cannot separate switching costs from a serially correlated unobserved fundamental, and running it would reproduce the interpretive error this paper claims to overcome.

Status: PENDING, and doubly so. $L_{k,t}$ and $\mathrm{LPConc}_{k,t}$ are Uniswap-V3-only quantities today and must be rebuilt on the unified layer before they enter any specification.

### 5.2 Aggregator integration scope

A cheaper route that no aggregator has integrated is a route no trader can take, so the role survives dominance for as long as it takes the routing infrastructure to see the alternative. This is a supply-side friction on the routing layer and it is distinct from 5.1 because it involves no capital movement.

What separates it: retention duration should be longer on pairs whose cheaper alternative sits on a venue that fewer aggregators had integrated at the time, and the duration should collapse at integration dates that are observable from calling-contract populations. `docs/router-identification-feasibility.md` records the executor population fragmenting from 241 to 397 senders with a hand registry covering 11.8%, which is the constraint on how sharply this can be measured.

Status: PENDING, and it is the newest account in the race. It was implicit in the old file's definition 12 and was never given a discriminating test.

### 5.3 The cost of holding the intermediary

Because an intermediate asset is held for the duration of the hop, the cost of the intermediary's own volatility scales with the amount held, so a volatile incumbent should be abandoned faster under its own stress than a stable one is.

What separates it: $\mathrm{CandidateStress}_{k,t}$ should shorten retention spells for the native candidate under its own drawdowns and lengthen them for stable candidates under a native drawdown, with the sign reversing for a stable candidate's own downward depeg, and a placebo assigning the shock after the outcome window must be null. The March 2023 depeg is the episode that identifies the reversal.

What this account has lost since the previous version of this file. It rested on two supports there and one of them is void. The size gradient in the native cost advantage, which the old 5.2 called its hinge, does not exist: the interaction is +0.0023 (0.914) per table 6. The surviving support is the count-value ordering, that the value-weighted crossover arrives 2022-Q1 while the count-weighted crossover appears only in 2026-H1, and that ordering is what the mechanism predicts. One prediction on the record is a weaker position than the old file described, and the retention-duration test is now the account's main chance.

Status: PENDING on all duration predictions. The count-value ordering EXISTS and is one prediction, not two.

### 5.4 Software defaults and the road already taken

Routing software and pool-creation templates default to the incumbent, and the survival duration is the release cadence of that software with no allocative content behind it.

What separates it, in four ways. Timing: a default change is a step at a release date and an allocative reallocation is a drift. Venue scope: a default inside one venue's software cannot move routing on venues whose software did not change, which makes cross-venue spillover the discriminating design. Mandate withdrawal: when Uniswap V1's architectural requirement to route through the native asset was removed by V2, native-asset pairing did not retreat, and the share of newly created pairs including the native asset rose from 84.1% in 2020 to 99.0% in 2023 and 97.9% in 2026. Duration heterogeneity: if defaults drive survival, retention spells should be common across pairs served by the same software and should vary across software populations.

This is the account the paper's own evidence currently favours. The V1 finding is a null on the architectural hypothesis measured over 477,633 pairs, of which 97.1% include the native asset. The token-level version reaches a bounded null: on 247 V1 exchanges, forced-routing intensity carries a coefficient of +0.276 on exit speed with a robust standard error of 0.307, randomisation inference at (0.355), a hazard-model coefficient of +0.026 with a cluster-robust standard error of 0.431, and measured power of 98.4% against a halving of survival time. An effect the mandate hypothesis needs would have been visible and it was not.

Status: partly supported, and the support runs against the paper's more interesting reading. The step-timing test, the cross-venue spillover design and the duration-heterogeneity test are PENDING, and they are how this account is beaten if it can be beaten.

### 5.5 What survives

The section closes with a specification curve on the retention-duration estimate, curated to defensible specifications with a joint inference test, and a dashboard showing which analytical choices move the result. The mandatory-to-vary choices are the support-screen threshold, the incumbency window, the notional grid point, and the outlier treatment, following the measured result that discretion over ten routine choices lets a researcher report over 70% of randomly generated variables as significant.

The verdict paragraph states which accounts survive and which do not, including the nulls, and it states them as findings. A horse race that ends in a tie between two mechanisms is a result, and a race in which the retention and displacement curves coincide is a null on hysteresis that the paper reports in the abstract.

---

## What G needs from F

Ordered by how much narrative weight is blocked, with the specification that would produce each. The list is shorter than the previous version's and it is shorter because the estimand change retired six items outright.

**RETIRED, and F should stop work on them if any is in flight.** The old size-profile item, framing the size profile as the hinge of a mechanism, is void: the interaction is +0.0023 (0.914). The old pair-date route-choice coefficient on the multi-venue panel, is demoted to table 6 and needs no further work beyond what `dominance_specification_curve.jsonl` already carries. The old V3 extension settling the 2021-Q3 collapse in the native routing advantage, is retired with the level estimand it served. The old item explaining the above-$100k dominance anomaly, was measured on the unscreened v2-only panel and does not survive the screen. The old non-mechanicalness screen and the old headline both rest on a specification the paper no longer reports.

**F1. Re-price realised routes at their own block, which is the only item that reinstates section 4.** The threat is measured and confirmed, not suspected: `output/exhibits/repricing_at_block.jsonl` puts the median deviation between a swap's own immediately-prior state and the hour-boundary state at 1.166% across 40 busy pools, with 86.2% of routes mispriced by more than 25 basis points at the median pool, against route-cost differences of tens of basis points. The split explains why it went unnoticed, since the deep stable pairs the quoters were validated on are fine at 0.085% and 0.012% median deviation while volatile pools run 1.8% to 4.9%. Specification, and the shape of it matters: this is a separation and not another full rebuild. The counterfactual panel is a cost surface sampled at regular intervals and stays hourly. The realised-route analysis moves to block-level state, taking the last swap in the pool at or before the route's block for v3 and v4 from `sqrtPriceX96` and `tick`, and unwinding the constant-product family backward from the stored end-of-hour reserve, which this project has already validated at 0.0000% median error. Deliver the verdict-flip rate between hour pricing and block pricing as its own exhibit, because that rate is the size of the correction and a reader will ask for it. Until this lands, table 4 is withdrawn and section 4 has a specification and no measurement.

**F2. The full-sample rebuild, and the two arms it unblocks.** This is the only item that matters and it is running. 2,277 days across six priced venues with the support screen applied. What G needs out of it, in order: `measure_realised_dominance.py` run across the full panel with the `mid_type` split retained, which fills table 3 panels A and B and figure 2; `run_survival_after_dominance.py` on the same, which fills table 4 panel A with a sample larger than 223 pair-candidate observations; and `run_displacement_asymmetry.py`, which currently refuses at 4 consecutive priced days against 20 required and which fills table 4 panel B and figure 3. Nothing in section 4 leaves PENDING without this.

**F3. Dollars foregone, which is not dollars routed.** The repository has 83.1 million dollars routed through dominated vehicles across four days and nothing that multiplies a dominated realised route's notional by its realised gap. Specification: on the matched realised routes, compute $q_r \times \Delta C^{D}_{r}$ for every dominated $r$, sum by intermediary type and by year, and report the median gap alongside so a reader can reconstruct the arithmetic. This is the Makarov and Schoar magnitude and it is what an editor recognises as a number. Table 4 panel C is the shell and it is the highest-value hour of work on this list once F1 and F2 have landed.

**F4. Balancer integrated into the route-cost panel.** The quoter is built and validated at 0.0000% median error on backward-rolled balances, and Balancer is 3.9% of panel volume pooled and 8.8% at its 2023 peak, which makes it the largest coverage gain available. `docs/venue-coverage-bounds.md` records the integration as pending and the venue as absent from both sides of the comparison.

**F5. The same-block cycle check on gaps above the arbitrage threshold.** Post-screen, 13.6% of gaps at $1,000, 38.5% at $10,000 and 22.0% at $100,000 still exceed three pool fees plus three-hop gas. Join those cells to the same-block swap sequence and report the share where a closing cycle appears. A cycle means arbitrage that was taken and the gap was real; no cycle means the gap is quoter error or an unmodelled constraint. This is the one test that splits the two, and section 6.3 cannot be written without it.

**F6. Per-day gas and per-day gas-token price, candidate-specific and venue-specific.** Join the panel to `data/processed/daily_gas_price_graph.parquet` (1,883 days) and a per-day gas-token USD price, with gas measured per candidate and per venue and not as the flat 74,096-unit per-hop constant. A Curve stableswap leg and a tick-crossing concentrated-liquidity leg do not cost the same gas as a constant-product leg, and a constant common to candidates inside a group is absorbed by the group fixed effect. The 1,883-day coverage against 2,277 panel days leaves 394 days without a gas price and F must state how those are handled instead of dropping them silently.

**F7. The matched-sample bound, narrowed.** Table 2 shows matching retains 1.9% of realised multi-leg routes and selects hard toward large stable-intermediated routing. Report what the rebuild does to that ratio, and if it stays near 2%, report the dominance incidence separately for the pairs the panel covers well and the pairs it barely covers, so a reader can see whether the 27.2% moves with coverage. Coverage is 79.0% of realised routing today and the uncovered 21.0% is `other` and staked-native routing, for which no matched rate exists at all. This is the paper's largest hole on the frequency side, as F1 is on the persistence side.

**F8. Registry symbols for asset-type shares and for the survival quantities.** Add $\mathcal K^{\theta}$, $\mathrm{TypeShare}^{\theta}_t$ and $\mathrm{TypeCountShare}^{\theta}_t$ over the five types in `src/ddvc/asset_types.py`, and add the retention-spell and displacement-spell durations of definition 11 with the incumbency window as a parameter. Table 4 currently uses quantities with no registered notation, which breaks the registry's role as single source.

**F9. Value-weighted type shares for the missing years, with quarterly crossover dates.** Table 3's setting panel reports 2020, 2022, 2024 and 2026 and omits 2021, 2023 and 2025. Fill them and report the quarterly crossover dates for both weightings.

**F10. The transition recomputed venue by venue and after the wash screens.** The turnover-spike, volume-spike, arbitrage-cycle and organic-versus-MEV screens named in workflow section 4.2 are unapplied and the venue dimension is absent. Both are needed for 3.4.

**F11. Liquidity measures rebuilt on the unified layer.** $L_{k,t}$, $\mathrm{LPConc}_{k,t}$ and $\mathrm{LogVehicleLiquidity}_{k,t}$ are Uniswap-V3-only today. Account 5.1 cannot be tested until they are rebuilt.

**F12. Aggregator integration dates, as far as the executor registry supports.** Account 5.2 needs the date each venue became reachable through each major aggregator. The hand registry covers 11.8% of the executor population, so F should report what fraction of routing volume the covered executors carry before anyone builds a test on it, because a design resting on 11.8% of contracts and 80% of volume is viable and one resting on 11.8% of both is not.

**F13. Cleanup that the gates require.** `output/empirical/` still holds roughly fifty pickled result objects and `output/tables/` roughly twenty exhibits from the round retired in `docs/retired-single-venue-round.md`, which states that every scripted output from that round is deleted and not archived. They are not deleted. Anything F promotes must be regenerated on the unified layer with the support screen applied; everything else goes, in the same commit.

## What G needs from H

`docs/deck-outline.md` targets the Nanyang Blockchain Conference on 21 to 22 August 2026 with 18 main slides and 23 appendix slides, and it was built against the retired estimand. The rewrite below is not optional, because four of its slides now advertise a result the paper does not report.

**H1. Slide 13 is cut and not built.** The previous version of this file told H that slide 13 was buildable because the sign of the native-type effect was resolved. That instruction is withdrawn. The coefficient it named, -0.3834 with a standard error of 0.0372 on 177,106 identifying cells, is the mixed-specification number: the seven-day window gives -0.3834 and 0.0372 on 45,630 identifying cells, and 177,106 belongs to the one-day window whose coefficient is -0.3837. The slide's own cut rule fires for a different reason than it anticipated, which is that the estimand is retired and not that the sign is unresolved. What replaces it is one validation slide carrying the -25.3 basis points (0.037) with the note that the ordering is what the definition of a thick-network asset implies.

**H2. Slide 12's size story is cut.** The old H5 asked H for a slide splitting the coefficient by notional with the crossover dates annotated, on the ground that the size profile was the hinge joining the paper's two halves. The gradient does not exist. Any slide whose read is "the signature of a fixed cost" from a three-point profile has to go, and the deck should carry the interaction estimate of +0.0023 (0.914) in the appendix as the reason it went, because a speaker who has quietly dropped a claim will be asked about it.

**H3. The deck needs a new spine slide and it is the survival curve, and until F1 lands the deck may not show a retention number at all.** Figure 3 of this file, the retention and displacement curves on the same pairs with the gap shaded, is the deck's centre once F1 and the rebuild land. The four-day retention ratios are withdrawn per section 4 and may not appear on a slide, in an appendix, or in a spoken caveat, because 86.2% of routes are mispriced by more than 25 basis points at hour-boundary state and the conference is on 21 to 22 August. Until then the deck's centre is the realised-dominance incidence at 27.2% population-weighted, with the matched-sample ratios from table 2 on the same slide and not in an appendix, because a headline incidence measured on 1.9% of realised routes that skew 13 times larger at the median cannot be presented without its selection alongside it. The raw matched mean of 41.3% may not appear as the headline anywhere in the deck, and if it appears at all it is labelled as the sample mean before reweighting.

**H4. Slide 11's gas arrow is wrong in a way the rewrite makes worse.** The slide specifies a dashed arrow labelled "add 74,096 units" attaching to the vehicle lane only. A per-hop constant common to every candidate is absorbed by the group fixed effect in any within-cell design and moves nothing, per Node I objection 6 and definition 7 above. The arrow should carry a candidate-specific and venue-specific gas term or it should be removed, and F5 is what supplies it.

**H5. Slide 14's cut rule is adopted and generalised.** Slide 14 will be cut unless dominance windows are dated on an all-in basis, on the stated ground that a window dated on gross quotes is not a window a trader faced. G adopts it and extends it: no incidence figure enters the deck or the paper without the support screen applied, because the pre-screen figures carried median gaps of thousands of basis points and the retired 17.9% is the example of what that produces.

**H6. A16's disclosed-and-unbounded filter now has a bound and the slide should carry it.** A16 discloses that the notional band removes 36.9% of pair-days and correlates with the outcome, then stops. Table 2 of this file is the bound, and it is a harder number than the disclosure: matching selects 13 times larger at the median with the entire `other` category absent. Disclosing a filter and then reporting its selection is a stronger position than disclosing it and stopping.

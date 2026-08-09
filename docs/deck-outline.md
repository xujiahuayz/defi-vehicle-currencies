# Conference deck outline: Nanyang Blockchain Conference, NTU Singapore, 21-22 August 2026

Slot: 30 minutes including Q&A, so roughly 20 minutes of speaking. Main deck 17 slides, of which cover and references consume seconds, leaving 15 slides carrying content at about 80 seconds each. Appendix 29 slides, unpresented, reached by number when a question lands. Paper title, settled 2026-08-06: "The Making of Dominant Vehicle Currencies: Evidence from DeFi".

The deck is built on the survival estimand. The question the talk asks and answers is how long the vehicle role survives once the asset carrying it stops being the cheapest route, priced in dollars foregone and in days of delay, with the asymmetry between the edge a challenger needs to displace an incumbent and the edge a displaced incumbent needs to return separating hysteresis from persistence. Deck order follows the paper architecture in `docs/paper-spine.md` section 1.3, whose section 3 leads on the state itself, section 4 carries the survival estimand, and section 6 defends the measured object as a numbered section. One divergence is recorded and held: the paper reads the migration in which asset intermediates as the time axis inside section 3, and the deck puts it before the state on slide 7, because an audience needs the setting before it can be told what happens inside the setting.

The level comparison between asset types appears in the appendix as a validation exhibit at about -25.3 basis points on the continuous gap (0.037). The retired binary version at -0.383, which was measuring quote collapse, and the retired size gradient, whose interaction with log size reads +0.0023 (0.914), appear only as the appendix line that says why they went.

Every slide is tagged **[BUILDABLE]** where every number and every axis on it can be rendered from artefacts in this repository today, and **[NEEDS REBUILD]** where the slide waits on the full-sample six-venue panel now running. Four priced days, 2023-06-01 to 2023-06-04, carry the results at cross-section, which is enough for the frequency, the share retention and the dollar total, and not enough for a duration. A slide tagged NEEDS REBUILD is cut from the running deck if its result has not landed, and it is never shipped with a placeholder number.

Two boundaries hold on every slide. Slide text is phrases and short clauses with a 40-word body budget, on appendix slides as hard as on core slides. Measurement belongs on slides and the organisation of the work does not, so quoter validation, gas receipts, support screens and coverage bounds are all admissible while anything describing how the analysis was assembled is not.

Figure assets live under `output/figures/deck/` as one file per slide. Diagrams live as tabs in a single `output/figures/deck/diagrams.drawio` with a transparent page background, exported on build. Asset-type colours are fixed once on slide 6 and every later chart inherits them.

---

## Main deck

### 1. Cover [BUILDABLE]

- Title: The Making of Dominant Vehicle Currencies
- Subtitle: Evidence from DeFi
- Speaker, affiliation, venue, date
- Pagination off

**Visual.** Full-bleed background with the tonal brand mask composited into the image file itself. No chart.

---

### 2. The state the data never contain [BUILDABLE]

- An incumbent's cost advantage is a consequence of its incumbency
- Sterling to dollar: the road not taken has no price
- Needed: a currency holding the role while strictly beaten
- On-chain the beaten route is quotable at the same state

**Visual.** `deck/identification_gap.svg`, drawio tab `identification_gap`. Two side-by-side panels in identical geometry. Left panel, labelled with the FX setting, shows an ordered pair of endpoint currencies joined by a solid arrow through a vehicle vertex, and a direct edge drawn as a dashed grey line ending in a question mark, with a hatched box over the price label. Right panel, same graph, same vertex positions, with the direct edge solid and carrying a price, and a bracket between the two paths labelled with the gap in basis points. The reader should see that the two panels differ in exactly one element, the price on the road not taken, and that the whole design turns on recovering it. No legend strip; the hatched box is annotated in place.

**Citations.** Krugman (1980) for the vehicle role resting on the lowest-cost route through the exchange structure; Flandreau and Jobst (2009) for persistence measured without strong lock-in; Eichengreen and Flandreau on inertia in the sterling-to-dollar turnover; Somogyi (2026) for dollar dominance measured as a share of FX trading.

**Grounding.** `docs/review-node-i-round1.md` section 4 states the capability and names the estimand it is for.

---

### 3. A vehicle currency written into the contract [BUILDABLE]

- Uniswap V1: one exchange contract per ERC20, ETH on the other side
- Token-to-token: no pool exists, so the protocol hops through ETH
- 217,003 forced routes, 8.60% of 2,522,120 V1 swap transactions
- 87.4% of forced routes report exactly equal ETH legs

**Visual.** `deck/v1_star_topology.svg`, drawio tab `v1_mandate`. A star graph: ETH as the single hub vertex, eight token vertices on the rim, every rim vertex joined to the hub and to nothing else. One highlighted two-leg path token A to ETH to token B, both legs labelled with the same ETH amount. The reader should see that no rim-to-rim edge exists, so the hop is a property of the graph and not of a choice, with the equal-legs signature annotated on the highlighted path.

**Citations.** Uniswap V1 protocol documentation for the one-exchange-per-token rule. Kiyotaki and Wright (1989) is not used here because its media emerge through bilateral acceptance rather than a contract-imposed star graph.

**Grounding.** `docs/finding-v1-forced-vehicle.md` section 1 and the numerical correction at the end.

---

### 4. The mandate goes, the pairing climbs [BUILDABLE]

- V2 live 2020-05-05, arbitrary ERC20 pairs allowed
- Constraint withdrawn, outcome unmoved
- 97.1% of 477,633 pairs ever traded on V2 hold WETH
- New-pair WETH share 84.1% in 2020, 99.0% by 2023, 97.9% in 2026

**Visual.** `deck/pairing_null.svg`. Two stacked panels sharing an x axis of calendar year 2020 to 2026, with a vertical rule at 2020-05-05 labelled with the architecture change and nothing else. Upper panel, y axis the WETH share of newly created pairs in percent on an 80 to 100 scale, one line with a marker per cohort year at 84.1, 92.9, 96.5, 99.0, 98.0, 98.1, 97.9. Lower panel, y axis the share of single-leg V2 trades executing on a WETH pool in percent on a 75 to 100 scale, two series, count-weighted and value-weighted. The read is that the vertical rule marks the removal of the constraint, neither series bends at it, and the supply of new pools converges toward the asset the constraint had mandated. A null exhibited as a picture with the event date visible so the audience can check the absence themselves.

**Citations.** Uniswap V2 whitepaper for arbitrary-pair support; Dowd and Greenaway (1993) for switching costs and network externalities.

**Caveats the speaker states aloud.** Uniswap V2 only, and V2 became a legacy venue after V3 arrived in May 2021, so this describes the venue that lost the mandate. Launch-template convention would produce the same pattern that optimisation would, and this exhibit cannot separate the two.

**Grounding.** `docs/finding-v1-forced-vehicle.md` sections 3 and 7.

---

### 5. Four architectures of one role [BUILDABLE]

- V1: ETH mandated by code
- V2: any pair allowed, ETH wrapped as WETH
- V3: liquidity concentrated into ticks
- V4: native ETH restored as a pool asset, no wrapping
- Mandated, then chosen and wrapped, then chosen and unwrapped

**Visual.** `deck/architecture_progression.svg`, drawio tab `architecture_arc`. Four panels left to right on one horizontal timeline with launch dates beneath. Panel one is the V1 star. Panel two is a dense graph with WETH as the highest-degree vertex and a small wrapping badge on it. Panel three is the same graph with pool edges drawn as narrow bands instead of lines, showing range concentration. Panel four is the same graph with the WETH vertex relabelled to native ETH and the wrapping badge gone. Vertex shape and fill stay identical across panels so only the labelled change moves, and the wrapping badge is the one shape that appears and then disappears.

**Citations.** Adams, Zinsmeister and Robinson (2021) for concentrated liquidity; Uniswap v4 documentation for native-asset pools; Lehar and Parlour (2024) for AMM liquidity provision.

---

### 6. Types before tickers [BUILDABLE]

- Native platform asset, thick pairing network, high volatility. Proxies WETH and native ETH
- Stablecoin, targeting a fiat peg with backing and redemption varying by design. Proxies USDC, USDT, DAI
- Imported store of value, wrapped in. Proxies WBTC, tokenised gold
- Staked native derivative, same exposure, separate instrument
- Traditional-finance counterpart named for each

**Visual.** `deck/asset_types.svg`, drawio tab `asset_taxonomy`. Four cards in a 2x2 grid, one per type, each carrying the type name in bold, the ticker proxies in monospace, and the traditional-finance counterpart in italic on a hairline-separated lower band. Card fill is the one colour used for that type in every other chart in the deck, so the type-to-colour mapping is established here once and carried by consistency thereafter. Staked native appears as a hairline-bordered inset on the native card, signalling that whether it is the same currency is a specification choice.

**Citations.** Gopinath and Stein (2021) for the incumbent international currency; Gorton and Zhang (2023) for reserve-backed par design and run exposure; Catalini, de Gortari and Shah (2022) and Lyons and Viswanath-Natraj (2023) for heterogeneous backing and peg-restoration mechanisms; Amiti, Itskhoki and Konings (2022) for invoicing-currency choice.

**Grounding.** `src/ddvc/asset_types.py`.

---

### 7. The role moves, and it takes six years [BUILDABLE]

- Native share of intermediated value 73.0% in 2020, 14.8% in 2026
- Stable share 21.2% to 50.1%
- Value crossover 2022-Q1, sustained from 2022-Q4
- Count crossover only in the final two quarters
- Imported store of value 1.3% to 9.9% of intermediated value

**Visual.** `deck/intermediation_transition.svg`. Two panels sharing an x axis of calendar time 2020 to 2026 at quarterly resolution. Upper panel count-weighted, lower panel value-weighted, y axis in both the share of intermediation episodes in percent from 0 to 80, one line per asset type in the slide 6 colours. Each panel's crossover marked with a small open circle and a date label. The read is one transition happening twice at two dates four years apart, with the value-weighted one sustained and the count-weighted one arriving at the sample edge. This is the time axis every later slide is read against, and it is what makes duration the question, because a role that eventually moves is a role whose survival time is finite and measurable.

**Citations.** Gopinath and Stein (2021) for a dominant currency being made; Somogyi (2026) for the FX analogue measured as a share; Chen and Duffie (2021) for fragmentation.

**Caveats the speaker states aloud.** The count-weighted crossover sits at the sample edge and cannot be called sustained. The unclassified residual reaches 24.2% of 2026 episodes across 9,283 distinct intermediary tokens, and no type claim extends past the classified set. Folding staked native into native leaves the count crossover intact at 33.7% against 36.4%.

**Grounding.** `docs/finding-intermediation-transition.md`.

---

### 8. What the panel contains [BUILDABLE, mandatory data slide]

- 2,277 daily files, 2020-02-11 to 2026-06-30, 471.6M swap legs, 364.3M route units
- Six venues priced: uniswap v2, v3, v4, sushiswap v2, curve, balancer
- 2,238 quoted days, 24 hourly pool states per day, 19,343 endpoint tokens
- Five vehicle candidates at $1k, $10k, $100k
- Venues active 3 in 2020, 8 in 2025

**Visual.** `deck/data_overview.svg`, two elements side by side. Left, four stat tiles reading 364.3M route units, 2,277 days, 19,343 endpoint tokens, 6 venues priced, each with a small-caps label beneath. Right, a stacked area chart, x axis calendar time 2020 to 2026 at yearly resolution, y axis each venue's share of panel volume summing to 100%, seven bands with the six priced venues in the deck's venue colours and the one unpriced venue hatched. Measured shares: uniswap v3 rising 0.0 to 66.8 to 49.4, uniswap v2 falling 77.5 to 2.4, curve holding 11.4 to 13.5 throughout, uniswap v4 entering at 22.1 in 2025 and 34.2 in 2026, balancer peaking at 8.8 in 2023, sushiswap v2 falling 11.1 to 0.1, sushiswap v3 never above 0.2. The read is that the venue carrying the market turns over twice inside the sample and the hatched band stays negligible, so a single-venue study drifts progressively away from the market and this one does not.

**Citations.** Makarov and Schoar (2022) for institutional architecture and Schär (2021) for a dated 2020 exchange-design taxonomy. The current venue landscape comes from the project's inventory.

**Caveats the speaker states aloud.** The quoted pair universe is the 200 most heavily bridged ordered pairs per day, which is a hub-and-long-tail panel and not a census, and pairs enter on the intensity of the behaviour under study. Concentrated-liquidity pricing begins 2021-05-04 with V3.

**Grounding.** `docs/venue-coverage-bounds.md`; `docs/router-identification-feasibility.md`; `data/empirical/route_cost_panel_v2.parquet`.

---

### 9. Pricing the road not taken [BUILDABLE]

- Both routes quoted at one reconstructed pool state
- Price movement cannot enter the comparison
- Constant product, tick traversal, StableSwap, weighted geometric mean
- Gas priced per leg from receipts, by venue and by candidate

**Visual.** `deck/counterfactual_design.svg`, drawio tab `counterfactual`. Two horizontal lanes issuing from a single state box labelled with the hour's reconstructed reserves, ticks and balances. Upper lane, one solid arrow labelled "quote direct i to o" into an output box. Lower lane, two solid arrows labelled "quote i to k" and "quote k to o" into a second output box. One gas box sits below and sends a dashed arrow to every leg arrow in both lanes, each dashed arrow labelled with that leg's own venue-specific gas draw, so the diagram shows a per-leg cost that differs across candidates and not one constant attached to the vehicle lane. A single bracket between the two output boxes labelled with the gap in basis points. The reader should see one state feeding both lanes, which is what removes price movement, and should see the gas term varying with which pools the route touches.

**Citations.** Angeris, Chitra, Evans and Boyd for gas-aware optimal routing being mixed-integer convex, so a shortfall against an optimum is measurable; Barbon and Ranaldo for total cost as slippage plus fee plus gas over notional; Xu, Paruch, Cousaert and Feng for design-specific slippage.

**Grounding.** `src/ddvc/pricing/`; `scripts/run_route_cost_panel.py`.

---

### 10. Quoting only where the quoter was validated [BUILDABLE]

- Every quoter validated on swaps that executed
- Realised trade size at 0.34% of the input reserve at the median, 3.3% at the 90th percentile
- Screen refuses any leg whose own price impact exceeds 5%
- Median gap at $100k falls from 4,655 to 20.8 basis points
- 70% to 86% of quotable routes removed

**Visual.** `deck/support_screen.svg`. Two panels sharing a log x axis of the gap in basis points from 1 to 100,000. Upper panel, the distribution of the same-state gap before the screen, plotted as a filled density with the median marked at 4,655 basis points at the $100k notional and a shaded region beyond the atomic-arbitrage threshold. Lower panel, the same distribution after the screen, median at 20.8 basis points, same axes and same shading. A small inset in the lower panel plots the empirical distribution of realised trade size as a fraction of the input reserve, x axis on a log scale, with a vertical rule at the 5% cap sitting near the 95th percentile at 0.0541. The read is that the unscreened panel was quoting trades no pool could absorb, and that the surviving gaps are the order of magnitude of the effects being measured.

**Citations.** Makarov and Schoar (2020) for what a defensible measured deviation looks like and for the frictions that have to sustain one; Daian et al. (2020) for why an unconstrained same-block cycle is exposed to atomic competitive capture; Milionis, Moallemi, Roughgarden and Zhang (2023) for the loss-versus-rebalancing benchmark. The project's measured gas, state-latency and execution bounds carry the economic verdict.

**Caveats the speaker states aloud.** The screen is ex ante on each leg's own impact and never on the gap, so it does not condition on the outcome. A material minority of surviving gaps at $10k still imply a cycle that pays, 38.5% at that notional, and the surviving sample is characterised on the next slide before any frequency is read off it.

**Grounding.** `output/exhibits/quoter_support_bounds.jsonl`; `output/exhibits/gap_arbitrage_bound.jsonl`.

---

### 11. Dominated at the state they executed in [BUILDABLE, and the deck's centre until slide 15 lands]

- 27.2% of realised multi-leg routing strictly beaten by a direct pool at its own state
- Population-weighted, covering 79.0% of realised routing
- Native 23.7%, stable 45.4%, imported 61.4%
- Matched sample carries 1.9% of realised routes, median trade $11,594 against $866
- The role held while strictly cost-dominated, observed

**Visual, the deck's strongest exhibit.** `deck/realised_dominance.svg`, two panels on one row with the left panel given two thirds of the width.

Left panel, a Marimekko. X axis is the share of realised multi-leg routing, 0 to 100%, with column width set by that share: native 66.9%, stable 11.4%, imported 0.7%, and a final column of 21.0% for the routing the matched panel does not cover. Y axis is dominance incidence, 0 to 100%. Each covered column is filled to its measured incidence, native to 23.7, stable to 45.4, imported to 61.4, in the slide 6 type colours, with the space above each fill in a light neutral. The uncovered column is hatched across its full height and labelled with the coverage gap. Filled area across the three covered columns is 27.2% of the whole plotting area and that equality is printed once inside the panel. The reader should see the headline emerge as an area, should see that the type carrying most of the routing is the type least often beaten, and should see the coverage gap drawn on the same axes as the claim instead of stated beside it.

Right panel, the magnitude. X axis is the direct pool's advantage over the route the trader actually took, in basis points, on a symmetric log scale from -10,000 through 0 to +10,000, with the sign convention printed under each half as "vehicle route was cheaper" on the left and "direct pool was cheaper" on the right. Y axis is count of matched realised routes, 1,762 in total, as a filled histogram with one vertical rule at zero. Mass to the right of zero filled in the accent colour and mass to the left in a light neutral, the shaded share annotated in place at 41.3% as the raw matched mean, and the median of the shaded region printed in basis points. The reader should see that the state has a size and not only a frequency, and should see the raw matched mean standing well above the population-weighted headline in the left panel, which is the selection made visible.

**Citations.** Krugman (1980) and Flandreau and Jobst (2009) for the identification limit this addresses; Makarov and Schoar (2020) for reporting the magnitude alongside the frequency.

**Caveats the speaker states aloud.** 1,762 of 90,705 realised multi-leg routes on those days matched a priced counterfactual, because the panel prices 200 pairs at three fixed notionals, so the matched set is 64.5% stable-intermediated where the population is 66.9% native-intermediated, and it covers 71 pairs against 17,851. The raw matched mean of 41.3% inverts on candidate type against the population, and it is shown for that reason. Enumerating every candidate a router could have chosen answers a different question and returns 70.1% gross and 80.3% all-in. Round trips are excluded, since a route whose first input equals its last output moved no value. Remaining venue gaps would make the direct alternative better, so the incidence is a floor.

**Grounding.** `docs/finding-dominance-and-persistence.md`; `output/exhibits/realised_dominance.jsonl`; `output/exhibits/dominance_windows_screened.jsonl`.

---

### 12. The role does not leave [BUILDABLE]

- Being beaten costs a vehicle share, and does not cost it the role
- Native 68.6% of its pair's multi-leg volume when cheapest, 39.4% when beaten
- Stable 43.4% to 28.2%
- Imported 6.1% to 2.8%
- Roughly half to two thirds retained on every type

**Visual.** `deck/persistence_slope.svg`. A slope chart. X axis carries two positions, labelled "vehicle was cheapest" and "a direct pool was cheaper", with generous horizontal separation. Y axis is the vehicle's mean share of its pair's multi-leg volume in percent from 0 to 75. Three lines in the slide 6 type colours, native from 68.6 to 39.4, stable from 43.4 to 28.2, imported from 6.1 to 2.8, each line endpoint carrying its value and its observation count as a small annotation. A faint reference line drawn from each left endpoint to zero on the right shows where full cost minimisation would land the series. The read is three lines that fall and none that reaches the reference, so routing responds to the price and does not obey it. Median shares behave the same way and are annotated as hairline markers beside each mean.

**Citations.** Flandreau and Jobst (2009) for persistence measured without strong lock-in; Dowd and Greenaway (1993) for switching costs consistent with a partial response but not identified by it; Krugman (1980) for the conditional multiple-equilibrium structure that makes the residual share an object of interest.

**Caveats the speaker states aloud.** 223 pair-day-vehicle observations across four days, which supports a cross-section and not a duration. The imported type rests on 4 undominated observations and its level is read as a direction only. Routers quote at a block and the panel prices at an hour boundary, and intra-day state movement on the deepest pool runs at a median 0.345% against gaps of tens of basis points, so part of the measured dominance is a state a router could not have seen; this is the open threat to persistence and it does not touch the frequency on slide 11, which is a statement about a state. The word hysteresis is not used here, because a partial response is equally consistent with slow information and with symmetric switching frictions, and the test that separates them is on slide 15.

**Grounding.** `output/exhibits/survival_after_dominance.jsonl`.

---

### 13. Eighty-three million dollars through a beaten vehicle [BUILDABLE]

- $83.1m of realised multi-leg volume through vehicles a direct pool beat, four days
- $69.7m of it through stablecoins
- $9.1m native, $4.2m imported
- More value through beaten vehicles than through cheapest ones

**Visual.** `deck/dollars_foregone.svg`. Two stacked bars side by side, x axis carrying the two states, "vehicle was cheapest" and "a direct pool was cheaper", y axis USD millions of realised multi-leg volume from 0 to 90. Left bar totals 73.2 and splits into stable 58.7, native 12.2, imported 2.3. Right bar totals 83.1 and splits into stable 69.7, native 9.1, imported 4.2. Segment fills are the slide 6 type colours, segment values printed in-bar, bar totals printed above, and a hairline bracket between the bar tops carrying the difference. A narrow strip below the bars, on the same vertical scale and therefore almost flat, holds the shortfall itself, being the gap in basis points applied to the volume that carried it. The read is that the taller bar is the one where a cheaper route sat available and was declined, and that the money left on the table is a small fraction of the money exposed to the choice.

**Citations.** Makarov and Schoar (2020) for money left on the table as the reported quantity; Barbon and Ranaldo for total trader cost including validator gas.

**Caveats the speaker states aloud.** Four days and the matched sample of slide 11, so this is a rate and not a cumulative total for the sample. Dollars routed through a dominated vehicle and dollars foregone are separate objects and the slide keeps them apart: $83.1m passing through at a median gap of tens of basis points is a foregone figure in the low hundreds of thousands, and reading the exposure as the loss overstates the result by three orders of magnitude. The shortfall strip renders once the gap-weighted total lands, and the slide ships without it until then.

**Grounding.** `docs/finding-dominance-and-persistence.md`; `output/exhibits/survival_after_dominance.jsonl`.

---

### 14. Days of delay [NEEDS REBUILD]

**Claim this slide must support.** Once a vehicle stops being the cheapest route on a pair, the number of days it keeps the majority of that pair's multi-leg volume has a measurable distribution, with a median in days, and that distribution is the object the inertia literature has wanted and never had. The cross-section on slides 12 and 13 establishes that survival is positive; this slide gives it a length.

**Figure to build once the result exists.** `deck/survival_curve.svg`. Kaplan-Meier survival curves, x axis days since the vehicle first became dominated on that pair from 0 to 90, y axis the share of pair-vehicle spells in which the vehicle still carries the largest share of that pair's multi-leg volume, 0 to 1, one curve per asset type in the slide 6 colours with a shaded confidence band per curve. A horizontal rule at 0.5 with each curve's median survival dropped to the x axis and labelled in days. Censoring ticks drawn on each curve. The read must be a median measured in days with a visible separation between types, or an overlap reported as an overlap.

**What it waits on.** A consecutive run of at least 20 priced days against the 4 that exist, so a spell can start and end inside the sample. The full-sample six-venue panel supplies it.

**Cut rule.** Cut if the run of priced days cannot support a spell length, and slide 12 stands alone as a cross-sectional retention. A survival curve fitted on four days is not shipped under any framing.

**Grounding when built.** `output/exhibits/displacement_asymmetry.jsonl` records the day requirement as 20 against 4 available.

---

### 15. The edge to win against the edge to return [NEEDS REBUILD]

**Claim this slide must support.** A displaced incumbent needs a larger cost edge to retake the role than the challenger needed to take it, which is hysteresis, and if the two curves lie on top of each other the finding is symmetric friction and is reported as a null. This is the asymmetry that no FX dataset can test, because it requires the counterfactual price on both sides of the switch, and it is the paper's single most important figure.

**Figure to build once the result exists.** `deck/edge_asymmetry.svg`, the deck's rendering of spine figure 3. One panel, x axis days from the moment the cost edge opens, 0 to 90, y axis the share of pair-vehicle spells in which the role has not yet turned over, 0 to 1. Two survival curves estimated on the same pairs, the retention arm for an incumbent holding the role while dominated and the displacement arm for a challenger holding a cost edge over an incumbent that still leads, each with a confidence band, drawn in two distinguishable line styles. The area between them shaded and labelled as the incumbency premium in days, with the horizontal distance between the two median crossings bracketed at the 0.5 rule and printed. The read must be whether the retention curve sits above the displacement curve and by how many days at the median, or whether the two overlap.

**What it waits on.** Both arms on the same pairs, which needs the date on which a challenger's edge opens on a pair the incumbent still holds. The three-point notional grid dates that coarsely, and the same consecutive run of priced days as slide 14 is required.

**Cut rule.** Cut unless both arms are measured on the same pairs, since curves estimated on different pair populations compare two samples and not two directions. An overlap is a result and ships as one.

---

### 16. Recap [BUILDABLE shell, two lines conditional]

- A vehicle role mandated by code, withdrawn, and never surrendered
- The role migrates by value four years before it migrates by count
- 27.2% of realised routing held the role while a direct pool beat it
- Being beaten costs a vehicle roughly a third of its share and not the role
- Two lines reserved for the duration and the asymmetry that slides 14 and 15 deliver

**Visual.** No chart. Five hairline-separated rows in the outcomes-table pattern, each row a bold head and a short gloss, in the order the body covered them. The two conditional rows render only when their slides ship, and the slide is laid out for both heights.

---

### 17. References [BUILDABLE]

- Two columns of author-year entries, cited works only
- Data and code availability line at the foot

**Visual.** None. Scoped font reduction to 22px.

---

## Appendix, held for Q&A

Not presented. Reached by number when a question lands. Every slide keeps the phrase discipline and the body budget.

### A1. Status is binary, dominance is a share [BUILDABLE]

- One bridging swap confers vehicle status
- Extent of capture is what varies
- Two axes: whether an asset intermediates, and how much of the role it holds
- Continuous share is the object measured here

**Visual.** `deck/appendix_status_vs_dominance.svg`, drawio tab `two_axes`. A plane with the horizontal axis running zero to one as the share of intermediation episodes an asset carries and the vertical axis a binary strip marking whether the asset intermediates at all. Four labelled positions plotted, at no intermediation, at a 2% share, at 35% and at 80%. The reader should see the binary axis saturating immediately while the share axis carries all the variation.

### A2. What is priced against what [BUILDABLE]

- One reconstructed state per pool-hour
- Direct route and every candidate vehicle route quoted from that state
- Gap in basis points is the road taken against the road not taken
- Realised amounts embed sandwich losses, simulated quotes do not

**Visual.** `deck/appendix_state_reconstruction.svg`, drawio tab `state_recon`. Timeline of one hour with swap events as ticks, an end-of-hour reserve box on the right, and a backward arrow labelled "unwind swaps" reaching the pre-trade state box on the left. The reader should see that the pre-trade state is derived and not assumed.

### A3. Constant-product quoting, and its validation [BUILDABLE]

- v2-family pools priced from unwound hourly reserves
- Median absolute error 0.0000% against realised swaps
- 95.2% of quotes within 0.01%
- Pool-hours failing reserve continuity dropped, roughly 3.2%

**Visual.** `deck/appendix_v2_validation.svg`. Histogram, x axis absolute quote error in percent on a log scale from 1e-6 to 1e0, y axis count of validated swaps, median marked. The read is that the mass sits below the axis resolution of any economic quantity in the paper.

### A4. Concentrated liquidity, and why direction matters [BUILDABLE]

- Active liquidity accumulated from every mint and burn since pool inception
- Quote traverses initialized ticks, piecewise on price
- Errors reported by direction and by whether a tick was crossed
- A pooled error statistic hides a directional fault

**Visual.** `deck/appendix_tick_traversal.svg`, drawio tab `tick_traversal`. Price axis horizontal with initialized ticks as vertical hairlines, liquidity depth as a step function above it, and a solid arrow showing a quote consuming depth across three ticks. Two arrows drawn, one each direction, in the same style, so the symmetry of the object and the asymmetry of the failure mode are both visible.

### A5. Concentrated-liquidity validation, all four cells [BUILDABLE]

- Consecutive swaps in one pool give the pre-trade state
- v3: median absolute error 0.0000%, 100% within 1%, all four direction-by-crossing cells
- v4: 4,218 realised swaps on three dates, median absolute error 0.0000%, 100% within 1%, all four direction-by-crossing cells
- supported v4 pools span static fee tiers 0, 7, 8, 100, 500, 10,000 and 20,000; hook-bearing and dynamic-fee pools are outside the vanilla-quoter contract and measured as excluded support

**Visual.** `deck/appendix_tick_validation.svg`. A 2x2 small-multiple of error distributions, rows the swap direction and columns whether an initialized tick was crossed, each cell a box plot on a shared log x axis of absolute error in percent. The read is four cells at the same location, which is the point of splitting them.

### A6. What a pooled error statistic concealed [BUILDABLE]

- Upward tick-crossing quotes were low by a median 62.6%
- Every other cell read exact
- A directional fault biases one side of every route comparison
- Reporting by cell is the check that catches it

**Visual.** `deck/appendix_directional_fault.svg`. Paired bar chart, four bars for the pre-correction cells and four for the post-correction cells, y axis median absolute error in percent on a log scale. The read is one bar out of eight standing three orders of magnitude above the others, then all eight level.

### A7. StableSwap quoting, with the amplification coefficient identified from trades [BUILDABLE]

- Curve pools priced on the StableSwap invariant, A fitted per pool-day on the first half of the day's trades
- Held-out median absolute error 0.033% across four sampled days
- 98.9% to 100% of held-out quotes within 1%
- Pools whose fit misses by more than 1% excluded and not approximated

**Visual.** `deck/appendix_curve_validation.svg`. Four small-multiple panels, one per validation day, x axis absolute held-out quote error in percent on a log scale, y axis count, median marked in each and the 1% acceptance threshold drawn as a vertical rule. The read is four independent days landing at the same median with the threshold far to the right of the mass.

**Grounding.** `output/exhibits/curve_quoter_validation.jsonl`.

### A8. Weighted-pool quoting, at hourly balances [BUILDABLE]

- Balancer weighted pools priced on the weighted geometric mean
- Median absolute error 0.0000% on held-out trades, 100% within 1%
- Daily snapshot held flat across the day costs a median 1.7% of quote error
- Hourly state recovered by netting the day's flow off the closing balance

**Visual.** `deck/appendix_balancer_validation.svg`. A dumbbell chart, y axis the twelve sampled validation days, x axis median absolute quote error in percent on a log scale from 1e-10 to 1e1, two markers per row joined by a line, one for the hourly-state quote and one for the flat daily snapshot. The read is two clouds separated by nine orders of magnitude, which is what makes hourly state load-bearing here and not on Curve.

**Grounding.** `output/exhibits/weighted_quoter_validation.jsonl`.

### A9. Pool statics recovered from identities [BUILDABLE]

- Fee tier from the CREATE2 address identity, 100.0% of pools in every era tested
- Decimals from the sqrtPriceX96-against-amounts identity, median error 0.0002
- Decimals coverage 99.95% of volume
- Pools resolving to neither are excluded

**Visual.** None needed. Two stat tiles and a four-row hairline list.

### A10. Gas measured from receipts [BLOCKED ON ROUTE-GAS SAMPLE]

- The pooled one-, two- and three-leg constants are fallbacks, not final evidence
- The live instrument samples exact single-component transactions by year, topology, exact venue sequence and intermediary identity
- Report medians and interquartile ranges only after the full support distribution fixes the fallback hierarchy
- Executor addresses are heterogeneity diagnostics and do not identify the route author
- Direction-asymmetric: one direction deducts from output, the other shrinks the input budget

**Visual.** `deck/appendix_gas_hops.svg`. Two horizontal bars, y axis the route topology at one leg and two legs, x axis median gas units from 0 to 250,000, with the difference bracketed and labelled. The read is the size of the handicap the vehicle route carries before any price effect.

### A11. The cost regime moves by three orders of magnitude [PRICE SERIES BUILDABLE; ALL-IN BPS BLOCKED]

- Daily median from every transaction in three spanning full blocks, all 2,277 project days
- Annual medians 84.00 gwei in 2021 and 0.13 gwei in 2026
- 32.84 gwei before 2024-03-13 and 1.35 gwei after
- Notional-scaled all-in basis points wait for the completed route-gas and gas-token-price join

**Visual.** `deck/appendix_gas_regime.svg`. Upper panel, x axis calendar time 2020-02 to 2026-06, y axis median gas price in gwei on a log scale from 0.03 to 500, the daily median as a thin line with the interquartile band as a light ribbon behind it, and a vertical rule at 2024-03-13 labelled with the blob-fee change. Lower panel on the same x axis, added only after the route-gas join, is a heat strip of the extra route cost in basis points by notional bucket on a sequential ramp. The read is that a vehicle route's gas handicap is not a constant of the technology and swings by three orders of magnitude inside the sample.

**Citations.** Caparros, Chaudhary and Klein (2024) for gas and liquidity concentration; Barbon and Ranaldo for validator gas dominating trader cost.

### A12. Why gas is in the outcome and not in the controls [BUILDABLE]

- Gas enters the quoted cost of each route topology directly
- Gas also drives liquidity-provider repositioning, which drives depth
- A variable on the causal path cannot be netted out by including it
- Measured in the outcome, absent from the right-hand side

**Visual.** `deck/appendix_gas_causal_path.svg`, drawio tab `gas_path`. A small directed graph, gas price vertex with solid arrows to route cost and to repositioning, repositioning with a solid arrow to pool depth, pool depth with a solid arrow to route cost. Every arrow verb-labelled, and the route-cost vertex drawn in the outcome fill so its role is visible from the shape. The reader should see gas sitting upstream of both the treatment and the outcome, and should see it entering the outcome as a measured term.

### A13. Asset types and their traditional-finance counterparts [BUILDABLE]

- Native platform asset: the incumbent international currency resting on thick-market externalities
- Stablecoin: targets a fiat peg; backing and redemption vary by design
- Imported store of value: gold or a foreign reserve asset
- Staked native derivative: same exposure, different instrument
- Other: the classified set ends and no type claim is made past it

**Visual.** `deck/appendix_taxonomy_map.svg`, drawio tab `taxonomy_map`. Two columns of cards, left the DeFi type with its ticker proxies, right the traditional-finance counterpart, joined by one labelled solid arrow per row. Card fill matches the type colours used throughout.

### A14. Coverage of the taxonomy, and the tail [BUILDABLE]

- Selected by measuring intermediation over 57 stratified days
- 2,149,718 episodes, 9,283 distinct intermediary tokens
- Six head tokens carry 81.7% of episodes
- Corrected classification places native ETH at the zero address in the native type

**Visual.** `deck/appendix_taxonomy_coverage.svg`. Cumulative-coverage curve, x axis intermediary tokens ranked by episode count on a log scale, y axis cumulative share of episodes from 0 to 100%, with the 81.7% level marked at rank six. The read is a steep head and a long tail that no cutoff can absorb quietly.

### A15. The specification alternative a referee will ask for [BUILDABLE]

- Staked native folded into native, the registered alternative
- 2026 count-weighted crossover survives: native plus staked 33.7% against stable 36.4%
- Whether the derivative is the same currency is a choice
- Both readings reported

**Visual.** `deck/appendix_staked_alternative.svg`. Dumbbell chart, y axis the year, x axis the native share in percent, two markers per row for the two definitions joined by a line, with the stable share drawn as a vertical reference. The read is that the crossover survives the alternative.

### A16. Where the routes come from [BUILDABLE]

- 2,277 daily files, 2020-02-11 to 2026-06-30, roughly 215k swap legs per day
- Eight venues: uniswap v1 to v4, sushiswap v2 and v3, curve, balancer, fluid
- Multi-leg routes reconstructed inside one transaction across venues
- Cross-venue share of clean economic multi-leg routes 1.4% in 2020 to 58.7% in 2026; full-market incidence falls 19.5% to 16.6% from 2022 to 2026. Inside the balanced five-venue perimeter it falls to 10.3%, but route coverage also falls to 69.8%, so that larger change is a support-exit decomposition

**Visual.** `deck/appendix_route_reconstruction.svg`, drawio tab `route_recon`. One transaction box containing three pool boxes on two different venues, solid arrows carrying the token flow through them, one dashed arrow from the transaction receipt box to a gas annotation. The reader should see that the unit of observation is the reconstructed route and not the swap leg.

### A17. How a realised route is matched to its counterfactual [BUILDABLE]

- Interior token identified from the reconstructed multi-leg route
- Same ordered pair, same hour state, nearest notional on the quoted grid
- 1,762 of roughly 90,700 realised multi-leg routes matched on four days
- Matched set is selected toward heavily bridged pairs and near-grid sizes

**Visual.** `deck/appendix_match_diagram.svg`, drawio tab `realised_match`. A realised route box on the left carrying its endpoint pair, interior token, hour and notional, four hairline arrows to the four match keys drawn as small boxes in the centre, and one solid arrow into a panel-row box on the right carrying the quoted direct and vehicle outputs. Keys that must match exactly drawn as solid arrows and the notional key, which snaps to the nearest grid point, drawn as a dashed arrow with its tolerance labelled. The reader should see which single key is approximate and therefore where the matched set's selection comes from.

### A18. What matching costs, measured [BUILDABLE]

- Matching retains 1.9% of realised multi-leg routes
- Median trade $11,594 matched against $866 unmatched, 90th percentile $208,204 against $6,454
- Matched routing 64.5% stable-intermediated, population 66.9% native-intermediated
- 71 pairs covered against 17,851, and the `other` category absent

**Visual.** `deck/appendix_matched_selection.svg`. A dumbbell chart, y axis the selection dimensions of median trade size, 90th-percentile trade size, native share, stable share, imported share, other share and routes per pair, x axis the matched-to-unmatched ratio on a log scale from 0.01 to 100 with a vertical rule at parity. Two markers per row joined by a line, one for the matched sample and one for the unmatched, and the ratio printed at the right of each row. The read is a fan of rows spreading in both directions from parity, with trade size and the stable share far to one side and the native and other shares far to the other, so the audience sees which way the matched frequency is pulled and by how much.

**Grounding.** `docs/paper-spine.md` table 2; `docs/finding-dominance-and-persistence.md`.

### A19. Screens applied before any estimate [BUILDABLE]

- Round-trip exclusion mandatory: median day 12.7% of multi-leg routes by count, 21.7% by value, reaching 25.9% and 91.3% on 2025-12-06, the most extreme day observed
- Support screen on each leg's own price impact at 5%, removing 70% to 86% of quotable routes
- Mispriced tokens filtered: absolute gap at most 10,000 bps, notional $100 to $50m, keeping 99.0%
- Notional band removes 36.9% of pair-days, correlates with the outcome, and its selection is measured on A18 at 13 times the median trade size

**Visual.** `deck/appendix_screens_waterfall.svg`. Waterfall chart, x axis the screens in application order, y axis routes surviving, each bar annotated with the share kept. The read is which screen is binding and by how much.

### A20. Coverage bounds, signed [BUILDABLE]

- Venue omission understates the best alternative, so dominance incidence is a lower bound
- Curve's calibration gate removes 65.2% of its native-leg volume against 21.1% of its stable-leg volume
- The native-against-stable gap holds in every year, at least 33 points and reaching 54 in 2023
- sushiswap v3 at 0.016% of priced volume and 4.1% pair-unique, excluded and not approximated

**Visual.** `deck/appendix_coverage_bounds.svg`. Two panels. Upper, Gantt-style coverage bars, y axis the venue, x axis calendar time 2020 to 2026, one bar per venue for the period in which its pools are priced drawn against a lighter bar for the period in which its flow exists. Lower, a diverging bar chart, y axis calendar year, x axis the excluded share of Curve volume in percent, two bars per year for the native leg and the stable leg in the slide 6 type colours. The read is that every remaining gap pushes the comparison in one direction, and that the direction is signed year by year.

**Grounding.** `docs/venue-coverage-bounds.md`.

### A21. The level comparison, kept as a validation exhibit [BUILDABLE]

- Native-intermediated routes about 25.3 basis points cheaper on the continuous gap (0.037)
- Pair-by-window-by-size cell effects, clustered by pair, 732 routes in 274 cells
- Binary version of the same comparison reads -0.043 (0.543)
- Native interacted with log size reads +0.0023 (0.914), which is why no size claim is made anywhere

**Visual.** `deck/appendix_specification_curve.svg`. A specification curve. Upper panel, y axis the coefficient with 95% intervals and a horizontal zero rule, x axis the specifications ordered by design dimension, points coloured by whether the outcome is the continuous gap in basis points or the binary indicator, with the two outcomes on separate y scales drawn as two stacked upper panels so the units are never mixed. Lower panel, the analytical-choice dashboard, rows the design dimensions of fixed-effect structure, outcome definition, venue set and candidate count, marks showing which choice each specification made. The read is that the sign is stable and the significance lives in the continuous outcome, and that the size interaction sits on zero.

**Citations.** Simonsohn, Simmons and Nelson for the specification curve and its joint inference test.

**Grounding.** `output/exhibits/dominance_specification_curve.jsonl`.

### A22. Four ways the persistence result could be mechanical [BUILDABLE]

- Measured against the same vehicle's undominated share, and not against zero
- Block-against-hour staleness open, intra-day movement at a median 0.345%
- Venue gaps leave a router with no cheaper pool to see, bounded and signed
- Quoted output is not the router's whole objective, and MEV exposure is unobserved here

**Visual.** `deck/appendix_persistence_threats.svg`, drawio tab `persistence_threats`. Four threat boxes in a column, each with a solid arrow into a verdict box on the right reading closed, open or bounded, and each arrow labelled with the quantity that decides it. The open threat's box and arrow drawn in the deck's alert fill so the one unresolved item is visible from the shape and not from reading. The reader should see which threats are discharged and which one is carried into the paper as a stated limit.

**Grounding.** `docs/node-e-screen-persistence.md`.

### A23. Why realised trades cannot answer this [BUILDABLE]

- Daily-median comparison on realised rates, 16,586 cells across 5,656 pairs
- Median absolute gap 691 bps, only 3.6% of cells within 10 bps
- Stable-to-stable pairs 23 bps against volatile pairs 775 bps
- Intraday price movement swamps execution cost 34 to 1 on 97% of the sample

**Visual.** `deck/appendix_price_movement_swamp.svg`. Two overlaid density curves, x axis absolute rate gap in basis points on a log scale, y axis density, one curve for stable-to-stable pairs and one for volatile pairs, with the 10 bp execution-cost band shaded. The read is one curve inside the band and one two orders of magnitude outside it, which is why same-state quoting is required.

### A24. Identifying a forced route in V1 [BUILDABLE]

- V1 keys its transaction entity on transaction hash plus exchange address
- A token-to-token trade lands as two rows sharing one hash
- One row carries the ETH-purchase array, the other the token-purchase array
- Rows carrying both arrays are single-pool round trips, 0.52% of entity rows

**Visual.** `deck/appendix_v1_signature.svg`, drawio tab `v1_signature`. Two row boxes side by side sharing a bracketed transaction hash above them, each row's populated event array highlighted and the empty one greyed, with a solid arrow between them labelled with the equal ETH amount. A separate single box to the right shows the both-arrays case labelled as a round trip. The reader should see why a single-row test would recover none of the forced routes.

### A25. Composition of V1 flow [BUILDABLE]

Last-resort table, five rows, three columns, used because the shares are the point and no plot beats them at five categories.

| trade class | transactions | share |
|---|---|---|
| ETH to token | 1,203,360 | 47.71% |
| token to ETH | 1,075,970 | 42.66% |
| token to token, forced via ETH | 217,003 | 8.60% |
| round trip in one exchange | 12,051 | 0.48% |
| three or more exchanges | 13,736 | 0.54% |

- 2,522,120 swap transactions, 2,798 days, 2018-11-02 to 2026-06-30
- Liquidity provision and withdrawal excluded from the denominator, 2.19% of rows

### A26. Why the V1 event study fails [BUILDABLE]

- Token-to-token needs two live exchanges, ETH-paired needs one
- Feasible pairs fall with the square of the live count
- Excess over the thinning benchmark sits between 0.83 and 1.07 throughout
- Treatment and confound are the same event

**Visual.** `deck/appendix_v1_thinning.svg`. Two lines on one panel, x axis calendar month 2020-03 to 2021-06, y axis indexed to 2020-05 at 1.0, one line the ratio of forced to ETH-paired flow and one the live-exchange count, with the excess plotted as a bar series beneath at a 0.8 to 1.1 scale. The read is two lines that fall together, so the differential has nothing left to explain.

### A27. The token-level test, and the bound it establishes [BUILDABLE]

- 247 V1 exchanges, outcome dated on the exchange's own ETH-paired flow
- Forced-route intensity +0.276, robust se 0.307, t +0.90
- Randomisation inference (0.355) over 5,000 draws, hazard ratio 1.004 per standard deviation
- Power against a halving of survival time 98.4%, so a large effect would have been seen
- Power against a 25% shortening 42%, so that range is out of reach

**Visual.** `deck/appendix_v1_power.svg`. Power curve, x axis the true survival-time ratio between the 95th and 5th percentile of intensity from 0.25 to 0.90, y axis power at 5% with correct sign from 0 to 100%, with the 80% pre-stated criterion drawn as a horizontal rule and the four measured points marked. The read is where the design can see and where it cannot, which turns a null into a bound.

### A28. Voluntary vehicle routing after a direct pool exists [BUILDABLE]

- 2,222 V2 pairs with a direct pool, 20 or more trades, and some ETH-routed trade
- Before the direct pool: 444,651 ETH-routed trades and 0 direct
- Median pair sends 32% through ETH at three to six months, 20% at six to twelve
- Without a liveness filter the same series reads 99%, which dead pools produce
- Cohort and calendar dominate horizon, so the profile is descriptive

**Visual.** `deck/appendix_persistence_decay.svg`. Two lines on one panel, x axis weeks since the direct pool first traded on a log scale, y axis median per-pair ETH-routed share of trade count from 0 to 100%, one line with no liveness condition and one requiring a direct trade in the trailing 28 days. The read is two lines that diverge to opposite conclusions, which is what makes the filter load-bearing.

### A29. Extended references [BUILDABLE]

- Full author-year list including works cited only in the appendix
- Data sources with their coverage dates
- Code entry points for every number quoted
- Panel and validation artefacts named by file

---

## What H needs from G

The spine rebuild answered the two structural questions the previous version of this file asked, and both answers are already built in above: section 3 leads on the state, and section 6 defends the measured object as a numbered section, so slide 10 stays in the core deck. Four items remain, and none of them is a wording question.

**1. The four rival accounts of survival, verbatim, as running labels.** Spine section 5 now races liquidity supply as the slow state variable, aggregator integration scope, the cost of holding the intermediary, and software defaults. The deck needs those four in G's exact words, because they become the recurring annotation on slides 12 through 15 and the audience must hear in the talk the same labels a referee reads in the paper. Until they land, slides 12 and 15 carry a mechanism-free description and the recap has no line naming which account survives.

**2. Whether the deck may open on the migration when the paper does not.** The paper reads the migration as the time axis inside section 3 and leads on the state. The deck puts the migration on slide 7, ahead of the state on slide 11, because a listener cannot be told what happens inside a setting before being given the setting. If G rules that the deck must follow the paper's order, slide 7 moves to sit after slide 13 as the axis the survival results are read against, which reorders five slides and changes what the recap's second row says. This is recorded as a divergence and held open for one decision.

**3. The headline figure the paper will print, since two are live.** `docs/finding-dominance-and-persistence.md` reports 27.2% population-weighted covering 79.0% of realised routing, and spine table 3 panel A still prints the raw matched pooled mean of 41.3% with the value column PENDING. Slide 11 carries both, with 27.2% as the headline and 41.3% shown as the selection made visible, which is the only presentation that satisfies spine H3 and the finding document at once. If G settles on one number, the slide keeps both and the emphasis moves; if G retires the matched mean from the paper, the right panel of the figure loses its annotation and the histogram stays.

**4. Bibliography entries the deck cites and `literature/vehicle-currencies.bib` does not carry.** Eight works are cited on slides above and absent from the bib: Barbon and Ranaldo on total trader cost; Angeris, Chitra, Evans and Boyd on gas-aware routing as a mixed-integer convex problem; Xu, Paruch, Cousaert and Feng on design-specific slippage; Eichengreen and Flandreau on sterling-to-dollar inertia; Simonsohn, Simmons and Nelson on the specification curve and its joint inference test; and the Uniswap V1, V2 and v4 protocol references for the architectural arc. Slides 2, 3, 4, 5, 9 and 13 and appendix slides A11 and A21 carry inline citations to these, and the references slide cannot render without them. Full author, year, venue and DOI for each, from G, since G owns the reference list.

**5. Confirmation that the deck adds no claim of its own.** Slides 2, 10, 11, 12 and 13 assert things a paper section must also assert: that the unobservable state is the price on the road not taken and not the routing choice, that the support screen is a property of where the quoters were validated and therefore ex ante on the leg, that the population-weighted incidence and the raw matched mean are two numbers with two readings, that a partial share response is neither hysteresis nor persistence until the asymmetry is measured, and that dollars routed through a dominated vehicle and dollars foregone differ by three orders of magnitude. If any of those has no G section, either G gains the section or the slide loses the claim.

## What H needs from F

**1. A consecutive run of priced days long enough to hold a spell, which slides 14 and 15 exist to carry.** `output/exhibits/displacement_asymmetry.jsonl` states the requirement as 20 consecutive days against the 4 that exist and returns `insufficient_days` for both arms. Slide 14 needs, per pair-vehicle spell, the day the vehicle first became dominated, the day it stopped carrying the largest share of that pair's multi-leg volume, and a censoring indicator for spells still open at the end of the run. Slide 15 needs the same spells with the mirror arm, in which a challenger holding a cost edge over an incumbent that still leads is followed on the same pairs. Without both arms on the same pairs slide 15 is cut, slide 14 ships alone, and the deck has no centre once the audience asks how long the role lasts.

**2. Dollars foregone, which slide 13 has a strip reserved for and cannot fill.** Slide 13 reports $83.1m of realised multi-leg volume through vehicles a direct pool beat. The economic quantity is the shortfall itself, being the gap in basis points applied to the notional that carried it, summed over dominated realised routes and reported with its median and its distribution. Spine table 4 panel C is the shell and nothing computes it. This is the Makarov and Schoar magnitude and it is the difference between a slide about exposure and a slide about loss.

**3. The 27.2% recomputed on the full sample, with an interval and a time profile.** The headline rests on four days in June 2023, which is one gas regime, one venue mix and one month. Slide 11 needs the population-weighted incidence across the priced span reported by year, so the audience can see whether the state is common throughout or concentrated in one regime, and it needs a standard error or an interval so the number is not read as exact. The reweighting also needs its coverage recomputed, since the 21.0% uncovered column on the left panel is a four-day figure.

**4. Dominance incidence by intermediary type on realised routes, over time.** Spine table 3 panel B is PENDING and spine figure 2 is the exhibit that joins the migration to the estimand. Slide 7 and slide 11 currently sit on two different panels with no line connecting them, and the join is the single thing that would let the talk say why the role moved instead of only that it moved and that it lingered.

**5. Endpoint tokens canonicalised in the route-cost panel, which selects on the paper's own asset.** Pool token addresses pass through `canonical_token` with `unify_wrapped` set, so native ETH at the zero address resolves to WETH, while the endpoint `src` and `tgt` columns keep the raw address. Every panel row whose endpoint pair contains the zero address therefore has `direct_available` and `vehicle_available` both false, measured at 0.000 on every day inspected against 0.843 and 0.453 for other pairs on the same day. That is 6.3% of rows in 2025 and 12.6% in 2026, and it deletes exactly the pairs the native-asset question is about. Slide 8's coverage figures, slide 11's uncovered column and every survival result on a native-endpoint pair need the panel rebuilt with endpoints canonicalised on the same rule as pool tokens.

**6. Uniswap v4 priced across its full observed history.** Exact-ID statics enrichment now covers all 523 raw calendar files from 2025-01-24 to 2026-06-30, including 522 positive-swap days. The vanilla static-fee quoter supports 84.0% of swaps and 99.0% of reported value pooled, and strict early/mid/late validation reproduces all 4,218 sampled realised swaps within 1%. v4 is 22.1% of panel volume in 2025 and 34.2% in 2026 by the coverage measurement, so a survival result on 2025 or 2026 pairs priced without it is measuring a market with a third of its depth removed. The architectural arc on slide 5 ends on v4, and a floor audience will ask what v4 does to the survival curve first.

**7. Balancer's excluded pool families, with the exclusion's direction signed.** The weighted quoter is wired in and validated, and the families it declines are large on the days they trade: AaveLinear and ERC4626Linear reach 58.8% and 63.7% of a day's excluded Balancer volume, and ComposableStable reaches 83.3% on another. Those are stable-side families, so their exclusion runs opposite to the Curve gate's native-side exclusion, and the two have never been netted. Slide A20 signs the Curve gate year by year and states the panel's bound as one-directional, and slide 11's floor caveat rests on that statement. It is not currently safe, and it needs the Balancer exclusion measured on the same leg split before either ships.

**8. Per-leg gas by venue and by candidate, which slide 9's diagram now advertises.** The diagram shows a gas draw attaching to every leg and differing across candidates, because a per-hop constant common to all candidates is absorbed by any within-cell design and moves nothing. A Curve StableSwap leg, a tick-crossing concentrated-liquidity leg and a constant-product leg do not cost the same gas, and the receipt-measured 154,604 and 228,701 unit medians are pooled over all of them. Slide 9 draws the term the deck claims to price, and A10 currently reports the pooled version, so either the per-venue medians land or the diagram reverts to one lane and A10 says so.

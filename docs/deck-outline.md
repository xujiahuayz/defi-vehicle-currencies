# Conference deck outline: Nanyang Blockchain Conference, NTU Singapore, 21-22 August 2026

Slot: 30 minutes including Q&A, so roughly 20 minutes of speaking. Main deck 18 slides at about one slide per minute, cover and references consuming seconds. Appendix 25 slides, unpresented, held for Q&A. Paper title, settled 2026-08-06: "The Making of Dominant Vehicle Currencies: Evidence from DeFi". Deck order follows the title's word order, so the making of the role comes first, dominance as a measured share second, and the DeFi evidence third.

Every slide below is tagged **FOUNDATION** or **RESERVED**. Foundation slides rest on measurements already in this repository and can be rendered today. Reserved slides carry a title and the claim they must support; they ship only once that claim has a measured result behind it, and an unpopulated reserved slide is cut from the running deck instead of shipped as a placeholder.

Two boundaries hold across every slide. Slide text is phrases and short clauses, never a full sentence, and the 40-word body budget binds on appendix slides as hard as on core slides. Measurement belongs on slides and the way the work was organised does not, so quoter validation, gas receipts, screens and coverage bounds are all admissible while anything about how the analysis was assembled is not.

Figure assets live under `output/figures/deck/` as one file per slide, and all diagrams live as tabs in a single `output/figures/deck/diagrams.drawio` with transparent page background, exported on build.

---

## Main deck

### 1. Cover [FOUNDATION]

- Title: The Making of Dominant Vehicle Currencies
- Subtitle: Evidence from DeFi
- Speaker, affiliation, venue, date
- Pagination off

**Visual.** Full-bleed background with the tonal brand mask composited into the image file itself. No chart.

---

### 2. A vehicle currency written into the contract [FOUNDATION]

- Uniswap V1: one exchange contract per ERC20, ETH on the other side
- Token-to-token: no pool exists, so the protocol hops through ETH
- 217,003 forced routes, 8.60% of V1 swap transactions
- 87.4% of forced routes report exactly equal ETH legs

**Visual.** `deck/v1_star_topology.svg`, drawio tab `v1_mandate`. A star graph: ETH as the single hub vertex, eight token vertices on the rim, every rim vertex joined to the hub and to nothing else. One highlighted two-leg path token A to ETH to token B, both legs labelled with the same ETH amount. The reader should see that no rim-to-rim edge exists, so the hop is a property of the graph and not of a choice. Verification of the equal-legs signature is the annotation on the highlighted path.

**Citations.** Uniswap V1 protocol documentation for the one-exchange-per-token rule; Krugman (1980) for the vehicle-currency object; Kiyotaki and Wright (1989) for why a medium of exchange concentrates.

**Grounding.** `docs/finding-v1-forced-vehicle.md` sections 1 and the numerical correction at the end.

---

### 3. The mandate goes, the pairing climbs [FOUNDATION]

- V2 live 2020-05-05, arbitrary ERC20 pairs allowed
- Constraint withdrawn, outcome unmoved
- 97.1% of 477,633 pairs ever traded on V2 hold WETH
- New-pair WETH share 84.1% in 2020, 99.0% by 2023

**Visual, and the deck's strongest exhibit.** `deck/pairing_null.svg`, two stacked panels sharing an x axis of calendar year 2020 to 2026, with a vertical rule at 2020-05-05 labelled with the architecture change and nothing else. Upper panel, y axis is the WETH share of newly created pairs in percent on a 80 to 100 scale, plotted as a line with a marker per cohort year, values 84.1, 92.9, 96.5, 99.0, 98.0, 98.1, 97.9. Lower panel, y axis is the share of single-leg V2 trades executing on a WETH pool in percent on a 75 to 100 scale, two series, count-weighted and value-weighted. The read is that the vertical rule marks the removal of the constraint and neither series bends at it, and the supply of new pools converges toward the asset the constraint had mandated. A null exhibited as a picture, with the event date visible so the audience can check the absence themselves.

**Citations.** Uniswap V2 whitepaper for arbitrary-pair support; Flandreau and Jobst (2009) for persistence without strong lock-in; Dowd and Greenaway (1993) for switching costs and network externalities.

**Caveats the speaker states aloud.** Uniswap V2 only, and V2 became a legacy venue after V3 arrived in May 2021, so this describes the venue that lost the mandate and says nothing about the native asset elsewhere. Launch-template convention would produce the same pattern as optimisation would, and this exhibit cannot separate the two.

**Grounding.** `docs/finding-v1-forced-vehicle.md` sections 3 and 7.

---

### 4. Four architectures of one role [FOUNDATION]

- V1: ETH mandated by code
- V2: any pair allowed, ETH wrapped as WETH
- V3: liquidity concentrated into ticks
- V4: native ETH restored as a pool asset, no wrapping
- Mandated, then chosen and wrapped, then chosen and unwrapped

**Visual.** `deck/architecture_progression.svg`, drawio tab `architecture_arc`. Four panels left to right on one horizontal timeline with the launch dates beneath. Panel one is the V1 star. Panel two is a complete-ish graph with WETH still the highest-degree vertex, a small wrapping badge on the WETH vertex. Panel three is the same graph with pool edges drawn as narrow bands instead of lines, showing range concentration. Panel four is the same graph with the WETH vertex relabelled to native ETH and the wrapping badge removed. Vertex shape and fill stay identical across panels so only the labelled change moves; the wrapping badge is the one shape that appears and then disappears.

**Citations.** Adams, Zinsmeister and Robinson (2021) for concentrated liquidity; Uniswap v4 documentation for native-asset pools; Lehar and Parlour (2024) for AMM liquidity provision.

---

### 5. Status is binary, dominance is a share [FOUNDATION]

- One bridging swap confers vehicle status
- Extent of capture is what varies
- Two axes: whether an asset intermediates, and how much of the role it holds
- Continuous share is the object measured here

**Visual.** `deck/status_vs_dominance.svg`, drawio tab `two_axes`. A plane with the horizontal axis running from zero to one as the share of intermediation episodes an asset carries, and the vertical axis a binary strip marking whether the asset intermediates at all. Four labelled positions plotted, one for an asset that never intermediates, one for an asset with status and a 2% share, one at a 35% share, one at an 80% share. The reader should see that the binary axis saturates immediately while the share axis carries all the variation, so a categorical vehicle label discards the quantity of interest. Two clean axes, no 2x2 implying the axes are exclusive.

**Citations.** Krugman (1980) and Gopinath et al. (2020) for the categorical usage in the currency literature; Somogyi (2026) for dollar dominance measured as a share in FX trading.

**Grounding.** `docs/research-workflow.md` section 3.

---

### 6. Types before tickers [FOUNDATION]

- Native platform asset, thick pairing network, high volatility. Proxy WETH and native ETH
- Stable numeraire, unit of account. Proxies USDC, USDT, DAI
- Imported store of value, wrapped in. Proxies WBTC, tokenised gold
- Staked native derivative, same exposure, separate instrument
- Traditional-finance counterpart named for each

**Visual.** `deck/asset_types.svg`, drawio tab `asset_taxonomy`. Four cards in a 2x2 grid, one per type, each card carrying the type name in bold, the ticker proxies in monospace, and the traditional-finance counterpart in italic on a hairline-separated lower band. Card fill is the one colour used for that type in every other chart in the deck, so the type-to-colour mapping is established here once and carried by consistency thereafter. Staked native appears as a hairline-bordered inset on the native card, signalling that whether it is the same currency is a specification choice.

**Citations.** Gopinath and Stein (2021) for the incumbent international currency; Gorton and Zhang (2023) and Lyons and Viswanath-Natraj (2023) for the stable unit; Amiti, Itskhoki and Konings (2022) for invoicing-currency choice.

**Grounding.** `src/ddvc/asset_types.py`; `docs/research-workflow.md` section 3.

---

### 7. What the panel contains [FOUNDATION, mandatory slide]

- 123.8M quoted route comparisons, 2,238 days, 2020-05-14 to 2026-06-30
- 24 hourly pool states per day on 2,234 days
- 30.0M comparisons with a direct and a vehicle route both quoted
- 19,343 endpoint tokens, 41,836 ordered pairs, 5 vehicle candidates, $1k / $10k / $100k
- Four venues quoted: uniswap v2, v3, v4, sushiswap v2

**Visual.** `deck/data_overview.svg`, two elements side by side. Left, five stat tiles reading 123.8M, 2,238, 30.0M, 19,343, $2.46tn, each with a small-caps label beneath. Right, a stacked area chart, x axis calendar time 2020 to 2026 at monthly resolution, y axis the share of best direct legs won by each venue summing to 100%, four bands in the deck's venue colours. The read is that the venue carrying the cheapest direct route turns over completely twice, uniswap v2 at 88.7% in 2020, uniswap v3 at 86.4% by 2025, and uniswap v4 taking 51.5% of best direct legs on the 30 days where v4 is priced. A shaded vertical band marks that 30-day window so the audience sees the coverage limit on the same axes as the claim.

**Citations.** Makarov and Schoar (2022) and Schär (2021) for the venue landscape.

**Caveats the speaker states aloud.** Pair universe is the 200 most heavily bridged ordered pairs per day, so this is a hub-and-long-tail panel and not a census. Concentrated-liquidity pricing begins 2021-05-04 with V3, and v4 pricing covers June 2026 only.

**Grounding.** `data/empirical/route_cost_panel_v2.parquet`; `scripts/run_route_cost_panel.py`.

---

### 8. The cost regime moves by three orders of magnitude [FOUNDATION]

- Per-transaction gas price, exact, 1,883 days
- Annual medians 70.51 gwei in 2021 to 0.12 gwei in 2026
- 28.37 gwei before 2024-03-13, 1.11 gwei after
- Fixed per-hop cost, so the vehicle route's penalty moves with it

**Visual.** `deck/gas_regime.svg`. One panel, x axis calendar time 2021-05 to 2026-06, y axis median gas price in gwei on a log scale from 0.03 to 500, the daily median as a thin line with the interquartile band as a light ribbon behind it. A vertical rule at 2024-03-13 labelled with the blob-fee change. A right-hand secondary annotation gives the extra gas of a second hop translated into basis points at each of the three notionals, 478 bp on $100 and 0.5 bp on $100,000. The read is that a two-hop route's handicap is not a constant of the technology and swings by three orders of magnitude inside the sample, so any statement about which route is cheaper is a statement about a date.

**Citations.** Caparros, Chaudhary and Klein (2024) for gas and liquidity concentration; Barbon and Ranaldo for validator gas dominating trader cost.

**Grounding.** `data/processed/daily_gas_price_graph.parquet`; `docs/finding-cost-dominance-measured.md`.

---

### 9. Which type of asset intermediates [FOUNDATION]

- Native share of intermediation episodes 68.7% in 2020, 32.9% in 2026
- Stable share 26.8% to 36.4% count-weighted
- Value-weighted crossover 2022-Q1, sustained from 2022-Q4
- Count-weighted crossover only in the final two quarters
- Imported store of value 0.2% to 5.8% of episodes

**Visual.** `deck/intermediation_transition.svg`, two panels sharing an x axis of calendar time 2020 to 2026. Upper panel count-weighted, lower panel value-weighted, y axis in both the share of intermediation episodes in percent from 0 to 80, one line per asset type in the type colours fixed on slide 6. Crossover points marked with a small open circle on each panel. The read is that the same transition happens twice at two different dates, four years apart, and the value-weighted one is the one that is sustained.

**Citations.** Gopinath and Stein (2021) for a dominant currency being made; Somogyi (2026) for the FX analogue measured as a share; Chen and Duffie (2021) for fragmentation.

**Caveats the speaker states aloud.** Count-weighted crossover sits at the very end of the sample, so it cannot be called sustained. The unclassified residual reaches 24.2% of episodes across 9,283 distinct intermediary tokens, and no type claim is made beyond the classified set. Folding staked-native into native leaves the crossover intact at 33.7% against 36.4%.

**Grounding.** `docs/finding-intermediation-transition.md`.

---

### 10. The feasible set flips before the flow does [FOUNDATION]

- Quoted two-hop availability by vehicle candidate, hourly state
- WETH availability 86.0% in 2021, 50.4% in 2026
- USDC 33.4% to 57.8%, overtaking WETH from 2025-Q4
- Availability sets the choice set, and allocative choice picks inside it

**Visual.** `deck/vehicle_availability.svg`. One panel, x axis calendar quarter 2020-Q2 to 2026-Q2, y axis the share of pair-hours in which a two-hop route through that candidate can be quoted, 0 to 100%, five lines in the type colours from slide 6. Crossing point of USDC over WETH annotated at 2025-Q4. A second thin panel beneath, same x axis, plots the share of panel rows whose endpoint pair the quoting layer can price at all, so the coverage decline is visible directly under the series it could bias. The read is that the route the router is allowed to take changes composition before any claim about which route it prefers.

**Citations.** Chen and Duffie (2021) for fragmentation; Adams, Zinsmeister and Robinson (2021) for why concentrated liquidity makes availability state-dependent.

**Caveats the speaker states aloud.** This is the feasible-set layer and it leads nothing. The crossover quarter moves from 2025-Q3 to 2025-Q4 depending on whether pairs with a native-ETH endpoint are kept, and on the 30 days where v4 is priced the WETH-to-USDC gap narrows from 7.7 to 2.3 percentage points, so the magnitude is coverage-dependent and the sign is not.

**Grounding.** `data/empirical/route_cost_panel_v2.parquet`.

---

### 11. Pricing the road not taken [FOUNDATION]

- Both routes quoted at one reconstructed pool state
- Price movement cannot enter the comparison
- Constant product for v2-family, tick traversal for v3 and v4
- Gas added per route topology from receipts

**Visual.** `deck/counterfactual_design.svg`, drawio tab `counterfactual`. Two horizontal lanes issuing from a single state box labelled with the hour's reconstructed reserves and ticks. Upper lane, one solid arrow labelled "quote direct i to o" into an output box. Lower lane, two solid arrows labelled "quote i to k" and "quote k to o" into a second output box, with a dashed arrow from a gas box labelled "add 74,096 units" joining the lower lane only. A single bracket between the two output boxes labelled with the gap in basis points. The reader should see that one state feeds both lanes, which is what removes price movement, and that the gas asymmetry attaches to exactly one lane.

**Citations.** Angeris, Chitra, Evans and Boyd for gas-aware optimal routing being mixed-integer convex, so a shortfall against an optimum is measurable; Barbon and Ranaldo for total cost as slippage plus fee plus gas over notional; Xu, Paruch, Cousaert and Feng for design-specific slippage.

**Grounding.** `src/ddvc/cpquote.py`; `src/ddvc/pricing/v3quote.py`; `scripts/build_counterfactual_dominance.py`.

---

### 12. Cost-dominance windows are common [FOUNDATION]

- 103,857 intermediated two-leg routes with a direct alternative
- 17.9% dominated gross of gas, 30.0% all-in
- $100 to $1k trades: 17.0% gross, 39.1% all-in
- Above $100k: 33.5% gross, 33.5% all-in
- The state the FX literature cannot observe is observable here

**Visual.** `deck/dominance_windows.svg`. A slope chart, x axis carrying two positions labelled gross of gas and all-in, y axis the share of routes dominated in percent from 0 to 45, one line per trade-size bucket in a sequential ramp from small to large. The read is that the smallest bucket rises steeply from 17.0 to 39.1 while the largest bucket is flat at 33.5, which is the signature of a fixed cost, and that dominance is common in every bucket at every measurement.

**Citations.** Krugman (1980) and Flandreau and Jobst (2009) for the identification limit this addresses; Milionis, Moallemi and Roughgarden (2023) for AMM liquidity economics.

**Caveats the speaker states aloud.** Dominance incidence is a lower bound on venue coverage since the alternative is understated, and an upper bound on gas since some measured dominance disappears all-in. Marginal frequency needs no controls, and it does not license a claim about which asset type is the better intermediary.

**Grounding.** `docs/finding-cost-dominance-measured.md`.

---

### 13. RESERVED: does the asset type matter once the trade is held fixed

**Claim this slide must support.** Conditional on the same ordered pair at the same hour and the same notional, whether the intermediary is the native asset changes the probability that the route was cost-dominated, with a coefficient whose sign is identified. The existing pooled estimate of -0.049 (0.008) is confounded by composition, and the existing pair-by-day fixed-effects estimate of +0.094 (0.269) has a minimum detectable effect near 24 percentage points on 158 clusters, so 96.2% of that panel contributes nothing. The multi-venue panel quotes every vehicle candidate for every pair-hour by construction, which removes the coincidence the within-pair estimator waits on.

**Figure to build once the result exists.** A coefficient plot, y axis the specification from pooled through pair-hour fixed effects, x axis the native coefficient in percentage points with 95% intervals and a vertical zero rule. The read must be whether the interval crosses zero and whether it narrows enough to exclude the effect size the incumbency story needs.

**Cut rule.** If the sign stays unresolved, the slide is cut and slide 12 stands alone as a marginal frequency.

---

### 14. RESERVED: how fast routing migrates when a window opens

**Claim this slide must support.** When an incumbent route becomes strictly cost-dominated on an executable all-in basis, routed share moves toward the cheaper route at a measurable speed, and that speed is the quantity the inertia literature cannot observe. Candidate windows are gas-regime shifts, fee-tier introductions, protocol-version migrations, and the March 2023 depeg.

**Figure to build once the result exists.** Event-time panel, x axis days from window opening at negative 30 to positive 90, y axis the incumbent's share of routed volume for that pair, mean with a confidence ribbon, one line per window class. The read must be whether the response has a visible onset and a half-life measurable in days.

**Cut rule.** Cut unless the windows are dated on an all-in basis with per-day gas, since a window dated on gross quotes is not a window a trader faced.

---

### 15. RESERVED: spillover to venues that did not change

**Claim this slide must support.** An architecture change on one venue moves the vehicle share on venues that did not change, which is non-mechanical and shares any macro episode with the treated venue. This is the cleanest identification the setting offers.

**Figure to build once the result exists.** Before-and-after panels, left the treated venue and right the untreated venues, x axis calendar month around the activation date, y axis vehicle share by asset type. The read must be a movement on the right panel that a common shock cannot produce alone.

**Cut rule.** Cut if the untreated venues cannot be shown to be untreated, since a router splitting across both makes the control a treated unit.

---

### 16. RESERVED: where incumbency can live at all

**Claim this slide must support.** Routing is executed by deterministic graph optimisers, so a preference for the incumbent when a cheaper route existed is not evidence of habit. Incumbency operates through a state variable, so it must be found in liquidity-provider capital allocation, where switching costs, gas and attention limits bind on a slower cadence.

**Figure to build once the result exists.** Two panels, upper the quote-time cost gap between incumbent and challenger routes for a pair, lower the incumbent pool's share of that pair's active capital, on one shared calendar axis. The read must be that the lower series moves on a slower cadence than the upper one, which locates the stickiness in capital and not in quote-time choice.

**Cut rule.** Cut if the capital measure is not rebuilt across venues, since a single-venue capital share is a different quantity.

---

### 17. Recap [FOUNDATION shell, one line reserved]

- A vehicle role mandated by code, then withdrawn, then never surrendered
- Vehicle status is trivially satisfied and dominance is the share that varies
- Which type intermediates flips by value four years before it flips by count
- The state the FX literature cannot observe is observable and common here
- One line reserved for the identified result slide 13 or 14 delivers

**Visual.** No chart. Five hairline-separated rows in the outcomes-table pattern, each row a bold head and a short gloss, in the order the body covered them.

---

### 18. References [FOUNDATION]

- Two columns of author-year entries, cited works only
- Data and code availability line at the foot

**Visual.** None. Scoped font reduction to 22px.

---

## Appendix, held for Q&A

Not presented. Reached by number when a question lands. Every slide keeps the phrase discipline and the body budget.

### A1. What is priced against what [FOUNDATION]

- One reconstructed state per pool-hour
- Direct route and every candidate vehicle route quoted from that state
- Gap in basis points is the road taken against the road not taken
- Realised amounts embed sandwich losses, simulated quotes do not

**Visual.** `deck/appendix_state_reconstruction.svg`, drawio tab `state_recon`. Timeline of one hour with swap events as ticks, an end-of-hour reserve box on the right, and a backward arrow labelled "unwind swaps" reaching the pre-trade state box on the left. The reader should see that the pre-trade state is derived and not assumed.

### A2. Constant-product quoting, and its validation [FOUNDATION]

- v2-family pools priced from unwound hourly reserves
- Median absolute error 0.0000% against realised swaps
- 95.2% of quotes within 0.01%
- Pool-hours failing reserve continuity dropped, roughly 3.2%

**Visual.** `deck/appendix_v2_validation.svg`. Histogram, x axis absolute quote error in percent on a log scale from 1e-6 to 1e0, y axis count of validated swaps, with the median marked. The read is that the mass sits below the axis resolution of any economic quantity in the paper.

### A3. Concentrated liquidity, and why direction matters [FOUNDATION]

- Active liquidity accumulated from every mint and burn since pool inception
- Quote traverses initialized ticks, piecewise on price
- Errors reported by direction and by whether a tick was crossed
- A pooled error statistic hides a directional fault

**Visual.** `deck/appendix_tick_traversal.svg`, drawio tab `tick_traversal`. Price axis horizontal with initialized ticks as vertical hairlines, liquidity depth as a step function above it, and a solid arrow showing a quote consuming depth across three ticks. Two arrows drawn, one each direction, in the same style, so the symmetry of the object and the asymmetry of the failure mode are distinguishable.

### A4. Concentrated-liquidity validation, all four cells [FOUNDATION]

- Consecutive swaps in one pool give the pre-trade state
- v3: median absolute error 0.0000%, 100% within 1%, all four direction-by-crossing cells
- v4: 1,200 realised swaps, median absolute error 0.0000%, 100% within 1%, all four cells
- v4 pools span fee tiers 0, 7, 100 and 500, so hook-driven fees price correctly

**Visual.** `deck/appendix_tick_validation.svg`. A 2x2 small-multiple of error distributions, rows the swap direction and columns whether an initialized tick was crossed, each cell a box plot on a shared log x axis of absolute error in percent. The read is four cells at the same location, which is the point of splitting them.

### A5. What a pooled error statistic concealed [FOUNDATION]

- Upward tick-crossing quotes were low by a median 62.6%
- Every other cell read exact
- A directional fault biases one side of every route comparison
- Reporting by cell is the check that catches it

**Visual.** `deck/appendix_directional_fault.svg`. Paired bar chart, four bars for the pre-correction cells and four for the post-correction cells, y axis median absolute error in percent on a log scale. The read is one bar out of eight standing three orders of magnitude above the others, then all eight level.

### A6. Pool statics recovered from identities [FOUNDATION]

- Fee tier from the CREATE2 address identity, 100.0% of pools in every era tested
- Decimals from the sqrtPriceX96-against-amounts identity, median error 0.0002
- Decimals coverage 99.95% of volume
- Pools resolving to neither are excluded

**Visual.** None needed. Two stat tiles and a four-row hairline list.

### A7. Gas measured from receipts [FOUNDATION]

- Median gasUsed 154,604 for one leg
- Median gasUsed 228,701 for two legs
- Extra hop 74,096 units
- Direction-asymmetric: one direction deducts from output, the other shrinks the input budget

**Visual.** `deck/appendix_gas_hops.svg`. Two horizontal bars, y axis the route topology at one leg and two legs, x axis median gas units from 0 to 250,000, with the difference bracketed and labelled. The read is the size of the handicap the vehicle route carries before any price effect.

### A8. Gas translated into cost [FOUNDATION]

- 74,096 units at the day's median gas price and the day's ETH price
- 478 bp of a $100 notional, 0.5 bp of a $100,000 notional
- 70.51 gwei median in 2021, 0.12 gwei in 2026
- Flat gas and flat ETH price would misstate both ends of the sample

**Visual.** `deck/appendix_gas_in_bp.svg`. Heat map, x axis calendar year 2021 to 2026, y axis notional bucket, cell value the extra hop's cost in basis points on a sequential ramp with the values printed in-cell. The read is that the same physical hop costs three orders of magnitude more in one corner than the other.

### A9. Why gas is not a control [FOUNDATION]

- Gas drives whether the vehicle route is optimal
- Gas drives liquidity-provider repositioning
- Repositioning is highest in the deepest pools
- A variable on the causal path cannot be netted out by including it

**Visual.** `deck/appendix_gas_causal_path.svg`, drawio tab `gas_path`. A small directed graph, gas price vertex with solid arrows to route choice and to repositioning, repositioning with a solid arrow to pool depth, pool depth with a solid arrow to route choice. Every arrow verb-labelled. The reader should see that gas sits upstream of both the treatment and the outcome, which is the definition of the problem.

### A10. Asset types and their traditional-finance counterparts [FOUNDATION]

- Native platform asset: the incumbent international currency resting on thick-market externalities
- Stable numeraire: the managed or pegged stable unit
- Imported store of value: gold or a foreign reserve asset
- Staked native derivative: same exposure, different instrument
- Other: the classified set ends and no type claim is made past it

**Visual.** `deck/appendix_taxonomy_map.svg`, drawio tab `taxonomy_map`. Two columns of cards, left the DeFi type with its ticker proxies, right the traditional-finance counterpart, joined by one labelled solid arrow per row. Card fill matches the type colours used throughout.

### A11. Coverage of the taxonomy, and the tail [FOUNDATION]

- Selected by measuring intermediation over 57 stratified days
- 2,149,718 episodes, 9,283 distinct intermediary tokens
- Six head tokens carry 81.7% of episodes
- Native ETH at the zero address was once misfiled, 19.8% of the residual in 2026 samples

**Visual.** `deck/appendix_taxonomy_coverage.svg`. Cumulative-coverage curve, x axis intermediary tokens ranked by episode count on a log scale, y axis cumulative share of episodes from 0 to 100%, with the 81.7% level marked at rank six. The read is a steep head and a long tail that no cutoff can absorb quietly.

### A12. The specification alternative a referee will ask for [FOUNDATION]

- Staked native folded into native, the registered alternative
- 2026 count-weighted crossover survives: native plus staked 33.7% against stable 36.4%
- Whether the derivative is the same currency is a choice
- Both readings reported

**Visual.** `deck/appendix_staked_alternative.svg`. Dumbbell chart, y axis the year, x axis the native share in percent, two markers per row for the two definitions joined by a line, with the stable share drawn as a vertical reference. The read is that the crossover survives the alternative.

### A13. Where the routes come from [FOUNDATION]

- 2,277 daily files, 2020-02-11 to 2026-06-30, roughly 215k swap legs per day
- Eight venues: uniswap v1 to v4, sushiswap v2 and v3, curve, balancer, fluid
- Multi-leg routes reconstructed inside one transaction across venues
- Cross-venue share of multi-leg routes 11.7% in 2021 to 49.8% in 2025

**Visual.** `deck/appendix_route_reconstruction.svg`, drawio tab `route_recon`. One transaction box containing three pool boxes on two different venues, solid arrows carrying the token flow through them, one dashed arrow from the transaction receipt box to a gas annotation. The reader should see that the unit of observation is the reconstructed route and not the swap leg.

### A14. How the quoted panel is built [FOUNDATION]

- 200 most heavily bridged ordered pairs per day
- Five vehicle candidates, three notionals, 24 hourly states
- Best direct pool against best two-hop path at the same state
- 30.0M of 123.8M comparisons have both sides quotable

**Visual.** `deck/appendix_panel_cells.svg`. A nested-rectangle area diagram sized to the cell counts, outer rectangle all comparisons, inner rectangle the both-quotable subset, with counts printed. The read is the fraction of the panel that supports a comparison at all.

### A15. Coverage bounds, signed [FOUNDATION]

- Venue omission understates the best alternative, so dominance incidence is a lower bound
- Gross-of-gas quotes overstate it, so the all-in figure is the binding one
- Concentrated-liquidity pricing starts 2021-05-04
- v4 pricing covers June 2026 only, 30 days of 546 with v4 flow

**Visual.** `deck/appendix_coverage_bounds.svg`. Gantt-style coverage bars, y axis the venue, x axis calendar time 2020 to 2026, one bar per venue for the period in which its pools are priced, drawn against a lighter bar for the period in which its flow exists. The read is the gap between flow and pricing, per venue, with the v4 gap the largest.

### A16. Screens applied before any estimate [FOUNDATION]

- Round-trip exclusion mandatory: 25.6% of multi-leg routes by count, 90.5% by value on the day inspected
- Mispriced tokens filtered: absolute gap at most 10,000 bps, notional $100 to $50m, keeping 99.0%
- Notional band removes 36.9% of pair-days and correlates with the outcome
- Sandwiched trades flagged, submission channel not used as a control

**Visual.** `deck/appendix_screens_waterfall.svg`. Waterfall chart, x axis the screens in application order, y axis routes surviving, each bar annotated with the share kept. The read is which screen is binding and by how much.

### A17. Identifying a forced route in V1 [FOUNDATION]

- V1 keys its transaction entity on transaction hash plus exchange address
- A token-to-token trade lands as two rows sharing one hash
- One row carries the ETH-purchase array, the other the token-purchase array
- Rows carrying both arrays are single-pool round trips, 0.52% of entity rows

**Visual.** `deck/appendix_v1_signature.svg`, drawio tab `v1_signature`. Two row boxes side by side sharing a bracketed transaction hash above them, each row's populated event array highlighted and the empty one greyed, with a solid arrow between them labelled with the equal ETH amount. A separate single box to the right shows the both-arrays case labelled as a round trip. The reader should see why a single-row test would recover none of the forced routes.

### A18. Composition of V1 flow [FOUNDATION]

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

### A19. Why the V1 event study fails [FOUNDATION]

- Token-to-token needs two live exchanges, ETH-paired needs one
- Feasible pairs fall with the square of the live count
- Excess over the thinning benchmark sits between 0.83 and 1.07 throughout
- Treatment and confound are the same event

**Visual.** `deck/appendix_v1_thinning.svg`. Two lines on one panel, x axis calendar month 2020-03 to 2021-06, y axis indexed to 2020-05 at 1.0, one line the ratio of forced to ETH-paired flow and one line the live-exchange count, with the excess plotted as a bar series beneath at a 0.8 to 1.1 scale. The read is two lines that fall together, so the differential has nothing left to explain.

### A20. The token-level test, and the bound it establishes [FOUNDATION]

- 247 V1 exchanges, outcome dated on the exchange's own ETH-paired flow
- Forced-route intensity +0.276, robust se 0.307, t +0.90
- Randomisation inference (0.355) over 5,000 draws, hazard ratio 1.004 per standard deviation
- Power against a halving of survival time 98.4%, so a large effect would have been seen
- Power against a 25% shortening 42%, so that range is out of reach

**Visual.** `deck/appendix_v1_power.svg`. Power curve, x axis the true survival-time ratio between the 95th and 5th percentile of intensity from 0.25 to 0.90, y axis power at 5% with correct sign from 0 to 100%, with the 80% pre-stated criterion drawn as a horizontal rule and the four measured points marked. The read is where the design can see and where it cannot, which turns a null into a bound.

### A21. Voluntary vehicle routing after a direct pool exists [FOUNDATION]

- 2,222 V2 pairs with a direct pool, 20 or more trades, and some ETH-routed trade
- Before the direct pool: 444,651 ETH-routed trades and 0 direct
- Median pair sends 32% through ETH at three to six months, 20% at six to twelve
- Without a liveness filter the same series reads 99%, which dead pools produce
- Cohort and calendar dominate horizon, so the profile is not identified

**Visual.** `deck/appendix_persistence_decay.svg`. Two lines on one panel, x axis weeks since the direct pool first traded on a log scale, y axis median per-pair ETH-routed share of trade count from 0 to 100%, one line with no liveness condition and one requiring a direct trade in the trailing 28 days. The read is two lines that diverge to opposite conclusions, which is what makes the filter load-bearing.

### A22. Cost dominance under controls [FOUNDATION]

Last-resort table, five rows, three columns.

| specification | native coefficient | p |
|---|---|---|
| pooled | -0.049 | (0.008) |
| plus log notional | -0.051 | (0.008) |
| plus year effects | -0.049 | (0.008) |
| pair-by-day fixed effects | +0.094 | (0.269) |
| pair-by-day, gap in bps | +186 | (0.078) |

- Larger trades less often dominated within a pair-day, log notional -0.042 (0.000)
- 3,654 pair clusters in the pooled specifications

### A23. Why the within-pair estimate cannot settle the sign [FOUNDATION]

- 703 identifying pair-day cells of 22,991
- 3,865 routes of 102,845, so 96.2% contributes nothing
- 158 clusters, standard error 0.085, minimum detectable effect near 24 percentage points
- A pair-day rarely sees a native and a non-native intermediary both used on one venue

**Visual.** `deck/appendix_within_pair_power.svg`. Nested-rectangle area diagram, outer rectangle all routes in the panel and inner rectangle the identifying subset, sized to scale with counts printed, and a minimum-detectable-effect bar drawn to the same horizontal scale as the estimate. The read is a sliver identifying the coefficient and an interval far wider than the effect in question.

### A24. Why realised trades cannot answer this [FOUNDATION]

- Daily-median comparison on realised rates, 16,586 cells across 5,656 pairs
- Median absolute gap 691 bps, only 3.6% of cells within 10 bps
- Stable-to-stable pairs 23 bps against volatile pairs 775 bps
- Intraday price movement swamps execution cost 34 to 1 on 97% of the sample

**Visual.** `deck/appendix_price_movement_swamp.svg`. Two overlaid density curves, x axis absolute rate gap in basis points on a log scale, y axis density, one curve for stable-to-stable pairs and one for volatile pairs, with the 10 bp execution-cost band shaded. The read is one curve inside the band and one two orders of magnitude outside it, which is why same-state quoting is required.

### A25. Extended references [FOUNDATION]

- Full author-year list including works cited only in the appendix
- Data sources with their coverage dates
- Code entry points for every number quoted
- Panel and validation artefacts named by file

---

## What H needs from G

The spine is G's to set and the deck cannot converge without four decisions from it. Each one changes slide ordering or slide existence, and none of them is a wording question.

**1. Which result leads, and whether the intermediation transition leads or supports.** Section 4.1 of `docs/research-workflow.md` ranks the intermediation transition first, while section 8 item 3 states a revised inclination putting cross-venue spillover first. Those two lists disagree, and section 8's numbering refers to a superseded list, since it calls result (1) "cross-aggregator routing choice" where 4.1's (1) is the intermediation transition, and it calls (2) "incumbency in liquidity supply" where 4.1's (2) is cost-dominance windows. Section 4.0 separately retires cross-aggregator routing choice, since the entry contract identifies the executor and not the aggregator, with the executor population fragmenting to 397 senders and a hand registry reaching 11.8% of swaps. So section 8 item 3 needs either a rewrite against 4.1's numbering or an explicit statement that 4.1 supersedes it. Until then slide 9's position in the arc is a guess, and slides 13 through 16 cannot be ordered.

**2. The named rival mechanisms, verbatim, as running labels.** Section 1 identifies the horse race as the craft pattern that replaces formal hypotheses in no-model empirical JFE papers, with Bolton and Kacperczyk italicising three competing hypotheses in the introduction and using them as running labels through the results. The deck needs those labels in G's exact words, because they become the recurring annotation on slides 12 through 16 and the audience must hear the same words in the talk that a referee reads in the paper.

**3. Which objections are dispatched in the body and therefore need a core slide.** Section 1 records that objections are named and dispatched in numbered subsections and that an appendix does not discharge them. The appendix here holds A19, A23 and A24, each of which discharges an objection. If G dispatches any of those in a numbered subsection, its slide is promoted out of the appendix into the core deck, which pushes the core count past 18 and forces slide 10 out. G's list of body-dispatched objections decides that.

**4. Bibliography entries the deck cites and `literature/vehicle-currencies.bib` does not carry.** Nine works are cited on slides above and absent from the bib: Barbon and Ranaldo on total cost; Angeris, Chitra, Evans and Boyd on gas-aware routing as a mixed-integer convex problem; Xu, Paruch, Cousaert and Feng on design-specific slippage; Cartea, Drissi and Monga on gas-netted liquidity-provider return; Chu, Dowling and Li (2026, JIMF) on impermanent-loss pricing; Uniswap V1, V2 and v4 protocol references for the architectural arc; Eichengreen and Chinn and Frankel for the inertia strand; Yuan (2005) on benchmark securities, which section 4.1 already leans on for the centrality-curse prediction. Slides 2, 3, 4, 8, 11 and 12 carry inline citations to these, and the references slide cannot render without them. Full author, year, venue and DOI for each, from G, since G owns the reference list.

**5. Confirmation that the deck adds no claim of its own.** The convergence condition in section 6 requires every slide to map to a G section. Slides 5, 6, 10, 11 and 12 currently assert things a paper section must also assert, in particular that vehicle status and dominance are separate axes, that the availability layer sets the feasible set without leading, and that dominance incidence is bounded below by venue coverage and above by gas treatment. If any of those has no G section, either G gains the section or the slide loses the claim.

## What H needs from F

Four measurement items block reserved slides, and two data defects block foundation slides that are otherwise ready.

**1. The multi-venue within-pair-hour estimate, which slide 13 exists to carry.** The pair-by-day design on the v2-only panel identifies from 703 cells of 22,991 with a minimum detectable effect near 24 percentage points, so it can neither confirm a native advantage nor exclude a substantial native disadvantage. `data/empirical/route_cost_panel_v2.parquet` quotes every vehicle candidate for every pair-hour by construction, which removes the coincidence the estimator waits on. Slide 13 needs the coefficient on native intermediation with the pair-by-hour fixed effect, its cluster count, its standard error, and the minimum detectable effect that standard error implies, so the slide can state what the design can and cannot see instead of stating a point estimate alone.

**2. All-in dominance on per-day gas and per-day ETH price.** `docs/finding-cost-dominance-measured.md` computes its all-in figures at a flat 25.8 gwei and ETH at $2,500 across the whole 2020 to 2026 span, which is wrong in both directions at different times, because annual median gas runs 70.51 gwei in 2021 and 0.12 gwei in 2026, and the blob-fee change alone moves the median from 28.37 to 1.11 gwei. `data/processed/daily_gas_price_graph.parquet` holds the exact per-transaction series for 1,883 days. Slide 12's all-in column and slide 14's window dating both need the per-day version, because a window dated on flat gas is not a window a trader faced.

**3. Window dating, for slide 14.** Slide 14 needs windows defined as intervals in which the incumbent route is cost-dominated all-in for a given pair and notional, with an opening date, a closing date, and the incumbent's routed share through the window. Candidate window classes named in section 4.0 are gas-regime shifts, fee-tier introductions, protocol-version migrations, and the March 2023 depeg. Without dated intervals there is no event time and therefore no figure.

**4. Cross-venue capital allocation, for slide 16.** The liquidity measures in `src/ddvc/analysis/lp_concentration.py` read `data/raw/thegraph/uniswap_v3/` only, so every quantity built on them is a Uniswap-V3-only quantity. Slide 16 locates incumbency in capital allocation, which requires the incumbent pool's share of a pair's active capital measured across venues on the same axis as the quote-time cost gap.

**5. Endpoint tokens are not canonicalised in the route-cost panel, and it selects on the paper's own asset.** Pool token addresses pass through `canonical_token` with `unify_wrapped` set, so native ETH at the zero address resolves to WETH, while the endpoint `src` and `tgt` columns keep the raw address. Every panel row whose endpoint pair contains the zero address therefore has `direct_available` and `vehicle_available` both false, measured at 0.000 on every day inspected, against 0.843 and 0.453 for other pairs on the same day. That is 6.3% of rows in 2025 and 12.6% in 2026, and it deletes exactly the pairs the native-asset question is about. Slide 7's coverage figures and slide 10's availability series both need the panel rebuilt with endpoints canonicalised on the same rule as pool tokens. The crossover on slide 10 survives either way, moving between 2025-Q3 and 2025-Q4, so this changes magnitudes and coverage and does not change the sign.

**6. Uniswap v4 is priced on 30 days of the 546 for which its flow exists.** Raw v4 files cover 2025-01-01 to 2026-06-30, and v4 legs appear in the panel only from 2026-06-01. The bias is measurable and it runs against the native asset, because on the 30 days where v4 prices, WETH two-hop availability is 65.8% against 45.2% on 2026 days where it does not, and USDC is 68.1% against 52.9%, so adding v4 lifts WETH by 20.6 percentage points and USDC by 15.2. On those same days v4 wins 51.5% of best direct legs and 57.8% of first hops. Slide 7's venue composition, slide 10's crossover magnitude, and any all-in dominance figure covering 2025 onward all need v4 priced across its full 546 days. This is the single largest coverage gap in the panel and it is the one a referee will find first, because the architectural arc on slide 4 ends on v4 and the evidence for v4 currently rests on one month.

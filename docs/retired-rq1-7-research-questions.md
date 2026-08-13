# Retired RQ1–7 research-questions memo

**Status:** Retired design record. This July RQ1–7 framing is preserved for history, but it is not a current agent route, estimator specification, findings record, or deliverable source. Current execution follows `docs/specification-lock.json`, `docs/findings-freeze.md`, and `docs/research-workflow.md`.

Generated 2026-07-08. Purpose: settle research questions before model, propositions, outline, or evidence hierarchy.

Update 2026-07-08: the workflow moved to empirical-first. The companion historical design is preserved in [`docs/retired-rq1-7-empirical-design.md`](retired-rq1-7-empirical-design.md).

## Ground Rule

Keep the research question short. Put mechanism, model object, proposition, and evidence below it.

Definition is not a proposition. "A vehicle currency is an asset used as an intermediate in exchange between two other assets" is setup. A proposition must say when that role emerges, persists, rotates, or changes with liquidity provision or market architecture.

DeFi is the empirical laboratory, not the claim boundary. The paper should speak to general vehicle-currency and market-design mechanisms.

## Candidate Core RQs

### RQ1. Under what market conditions does one asset become the vehicle?

This is the main formation question.

What it should absorb:
- Transaction-cost and price-impact conditions.
- Direct market incompleteness.
- Economies of market size.
- Strategic routing through the lower-cost intermediate.

Likely model object:
- Direct route cost versus indirect route cost through a candidate vehicle.
- Route availability, depth, price impact, and fee cost.

Possible proposition later:
- A candidate asset becomes the vehicle when routing through it has lower expected execution cost or higher feasible depth than direct exchange, especially when transaction costs decline with market size.

Evidence later:
- DeFi route reconstruction.
- Direct versus indirect route availability.
- Route-cost comparisons by trade size and market depth.

### RQ2. How does liquidity provision make a vehicle?

This is the central liquidity-provision question.

What it should absorb:
- LPs choose where to allocate capital.
- Vehicle-linked pools may become deeper because they are where route demand concentrates.
- Deeper vehicle-linked liquidity can then make future routing through the vehicle cheaper.
- Liquidity supply can be complementary across LPs and venues.

Likely model object:
- LP payoff from providing liquidity to vehicle-linked pools.
- Trader route choice as a function of vehicle-linked liquidity.
- Feedback from route demand to LP allocation.

Possible proposition later:
- Vehicle-linked liquidity and vehicle-route demand reinforce one another.

Evidence later:
- LP concentration around candidate vehicles.
- Predictive relation between vehicle-route demand and future LP liquidity.
- Route cost response to vehicle-linked liquidity.

### RQ3. Why does vehicle status persist?

This is the stickiness question.

What it should absorb:
- Network effects.
- Switching costs.
- Path dependence.
- Liquidity-route feedback.

Likely model object:
- Dynamic state variable for vehicle-linked liquidity or route share.
- Switching cost or coordination friction.
- Multiple equilibria or hysteresis.

Possible proposition later:
- Once vehicle status is established, a competing vehicle must offer a sufficiently large cost or safety advantage to displace it.

Evidence later:
- Persistence and half-life of vehicle shares.
- Post-shock mean reversion versus persistent shift.
- Slow secular replacement or coexistence of vehicle assets.

### RQ4. When does vehicle status switch?

This is the rotation question.

What it should absorb:
- Risk or credibility shocks to the incumbent vehicle.
- Flight to safer or more liquid substitutes.
- Temporary rotation versus regime change.

Likely model object:
- Vehicle risk or credibility cost in the indirect-route cost function.
- Substitute vehicle safety or settlement reliability.

Possible proposition later:
- A negative shock to the incumbent vehicle reduces its route share relative to safer substitutes inside the same route opportunity set.

Evidence later:
- Stress-event route shares.
- Common-support route opportunities.
- Stable asset substitutes and persistence after the shock.

### RQ5. How does market architecture change vehicle formation?

This is the architecture question.

What it should absorb:
- Direct-market deepening.
- Concentrated liquidity.
- Fee-tier design.
- Gas/repositioning costs.
- LP control over ranges.
- Multi-pool fragmentation or specialization.

Likely model object:
- Architecture parameter that changes direct depth or vehicle-linked LP cost.
- LP repositioning cost and active liquidity concentration.
- Direct-route feasibility versus vehicle-route feasibility.

Possible proposition later:
- Architecture that deepens direct pairwise markets weakens vehicle reliance, while architecture that lowers vehicle-linked LP costs can strengthen vehicle formation.

Evidence later:
- Architecture-change event studies.
- Direct route feasibility around market-design changes.
- LP liquidity concentration around candidate vehicles before and after design changes.

### RQ6. How does settlement design change vehicle use?

This is the netting/settlement question. It should not be demoted by default. It is part of architecture when it changes the cost of using or supporting a vehicle.

What it should absorb:
- Physical movement through the vehicle versus virtual/netted settlement.
- Settlement frictions and inventory movement.
- Whether a vehicle can remain economically central even when physical transfer falls.

Likely model object:
- Settlement friction or netting parameter.
- LP operating cost or inventory movement cost.
- Route intermediation versus physical settlement movement.

Possible proposition later:
- Settlement netting can preserve the vehicle route role while lowering physical intermediary-token movement, and may increase vehicle-linked liquidity if it reduces LP or settlement costs.

Evidence later:
- Matched route units across settlement architectures.
- Transfer-log incidence.
- LP liquidity response to netting exposure.

Need one more literature check:
- Add top-tier clearing/netting/settlement-design papers. The current corpus supports architecture and arbitrage design, but the external TradFi netting anchor is thinner than for liquidity provision.

### RQ7. Does a vehicle create common liquidity across markets?

This is the common-liquidity question.

What it should absorb:
- A vehicle links otherwise separate markets.
- Shared LP capital, shared inventory risk, and common route demand can create liquidity co-movement.
- Market architecture can strengthen cross-market liquidity spillovers.

Likely model object:
- Common vehicle-linked liquidity factor.
- Pool/pair liquidity beta to aggregate vehicle-linked liquidity.
- Stronger commonality during stress or after architecture connects markets.

Possible proposition later:
- Markets linked by the same vehicle asset have stronger liquidity co-movement, especially when architecture lowers multi-market routing or LP repositioning costs.

Evidence later:
- Liquidity commonality across vehicle-linked pools.
- Down-market commonality.
- Change in commonality around architecture changes.

## Recommended Settlement Set

If we want a paper-level RQ set that is broad but still clean:

1. Under what market conditions does one asset become the vehicle?
2. How does liquidity provision make a vehicle?
3. Why does vehicle status persist?
4. How does market architecture change vehicle formation?
5. How does settlement design change vehicle use?

RQ4 stress rotation and RQ7 common liquidity can be either core subquestions or evidence sections, depending on what the model can carry cleanly.

## Source Snippet Bank

Exact snippets are intentionally short. Line numbers refer to the local `pdftotext` extraction in `/tmp/dvc_pdf_text/`; PDFs are under `literature/papers/`.

### Krugman 1980, vehicle currencies and transaction costs

PDF: `literature/papers/1980-Krugman1980VehicleCurrencies-vehicle-currencies-and-the-structure-of-international-exchange.pdf`

Snippet: "transaction costs ... decreasing in the volume of transactions" (text lines 425-427).

Use: RQ1 formation. This is mechanism inspiration, not a definition.

### Somogyi 2026, dollar dominance in FX trading

PDF: `literature/papers/2026-Somogyi2026DollarDominanceFX-dollar-dominance-in-fx-trading.pdf`

Snippet: "low-price-impact advantage" (text line 46).

Use: RQ1 formation. The clean TradFi analog is vehicle status through lower price impact.

### Dowd and Greenaway 1993, network externalities and switching costs

PDF: `literature/papers/1993-DowdGreenaway1993CurrencyCompetition-currency-competition-network-externalities-and-switching-costs-towards-an-altern.pdf`

Snippet: "network effects" and "switching costs" (text lines 36 and 44-46).

Use: RQ3 persistence. This supports stickiness, not a crypto-specific narrowing.

### Mukhin 2022, equilibrium international price system

PDF: `literature/papers/2022-Mukhin2022InternationalPriceSystem-an-equilibrium-model-of-the-international-price-system.pdf`

Snippet: "strategic complementarities ... path dependence" (text lines 87-89).

Use: RQ3 persistence. The broader idea is coordination and hysteresis in currency choice.

### Bessembinder, Hao, and Zheng 2020, liquidity provision contracts

PDF: `literature/papers/2020-BessembinderHaoZheng2020Contracts-liquidity-provision-contracts-and-market-quality-evidence-from-the-new-york-stoc.pdf`

Snippet: "strategic complementarity" in "liquidity provision" (text lines 429-430).

Use: RQ2 liquidity provision. This gives a high-level TradFi anchor for LP complementarity.

### Anand and Venkataraman 2016, market-making fragility

PDF: `literature/papers/2016-AnandVenkataraman2016MarketMaking-market-conditions-fragility-and-the-economics-of-market-making.pdf`

Snippet: "endogenous liquidity provision" (text line 67).

Use: RQ2 and RQ4. It documents endogenous provider participation that falls with low volume and one-sided order flow but rises with volatility; this is a heterogeneity boundary, not a generic stress or identification result.

### Uniswap v3 whitepaper, concentrated liquidity

PDF: `literature/papers/2021-AdamsZinsmeisterRobinson2021UniswapV3-whitepaper-uniswap-v3-core.pdf`

Snippet: "more control over the price ranges" (text lines 25-27).

Use: RQ5 architecture. Architecture changes the LP decision space.

### Klein, Kozhan, Viswanath-Natraj, and Wang 2026, informed LP

PDF: `literature/papers/2026-KleinKozhanViswanathNatrajWang2026InformedLP-working-paper-informed-liquidity-provision-on-decentralized-exchanges.pdf`

Snippet: "passive into a potentially strategic activity" (text lines 773-774).

Use: RQ5 architecture. V3 changes LP behavior, not just measurement.

### Caparros, Chaudhary, and Klein 2024, scaling and liquidity concentration

PDF: `literature/papers/2024-CaparrosChaudharyKlein2024BlockchainScaling-working-paper-blockchain-scaling-and-liquidity-concentration-on-decentralized-exchanges.pdf`

Snippet: "higher liquidity concentration translates into lower slippage" (text lines 101-103).

Use: RQ2 and RQ5. LP repositioning cost affects concentration and trader execution cost.

### Lehar and Parlour 2024, Uniswap AMM

PDF: `literature/papers/2024-LeharParlour2024Uniswap-decentralized-exchange-the-uniswap-automated-market-maker.pdf`

Snippet: "the size of the pool adjusts" (text lines 156-159).

Use: RQ2. AMM liquidity provision can equilibrate through pool size rather than quoted price.

### Lyons and Viswanath-Natraj 2023, stablecoin stability

PDF: `literature/papers/2023-LyonsViswanathNatraj2023Stablecoins-what-keeps-stablecoins-stable.pdf`

Snippet: "arbitrage design stabilizes the price" (text lines 30-31).

Use: RQ6 architecture/settlement design by analogy. Design controls access and frictions.

### Anadu et al. 2023, stablecoin runs and flights to safety

PDF: `literature/papers/2023-AnaduEtAl2023StablecoinRuns-working-paper-runs-and-flights-to-safety-are-stablecoins-the-new-money-market-funds.pdf`

Snippet: "safer stablecoins experience net inflows" (text lines 1489-1491).

Use: RQ4 stress rotation. The broader point is safety-based rotation under stress.

### Chordia, Roll, and Subrahmanyam 2000, commonality in liquidity

PDF: `literature/papers/2000-ChordiaRollSubrahmanyam2000Commonality-commonality-in-liquidity.pdf`

Snippet: "liquidity could be expected to exhibit similar co-movement" (text lines 93-94).

Use: RQ7 common liquidity. A shared vehicle may create common liquidity movement.

### Klein and Song 2021, commonality and MTF architecture

PDF: `literature/papers/2021-KleinSong2021CommonalityIntraday-accepted-commonality-in-intraday-liquidity-and-multilateral-trading-facilities-evidence-f.pdf`

Snippet: "connects European markets in a single network" (text lines 103-106).

Use: RQ7 and RQ5. Market architecture can strengthen cross-market liquidity spillovers.

## Immediate Next Work

1. Decide whether RQ6 is a standalone core RQ or a subcase of RQ5.
2. Add a targeted clearing/netting/settlement literature mini-sweep for RQ6.
3. Once RQs are selected, write the model primitives for only those RQs.
4. Only after model primitives are clear, draft propositions.
5. Only after propositions are clear, map DeFi evidence and TradFi anecdotes.

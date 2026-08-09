# Node K, round 1: proposals nobody asked for

Node K output, 2026-08-06. This node exists because the graph had no generator. Every other node either builds what is specified or attacks what is built, and the two best ideas of the last long session, betweenness centrality for the vehicle role and a Herfindahl index to separate succession from fragmentation, both came from the project owner. This file proposes candidates the graph did not ask for, screened against the non-mechanicalness rule in `docs/research-workflow.md` section 4 and against the constraints that are already known to bind.

Each accepted candidate names its estimand, its identification and the variation that carries it, what would falsify it, which existing result it displaces or supports, its single biggest threat, and the files and streams it reads. The rejected list follows, with reasons, because a proposal node that reports only its hits is not reporting its screen.

Two sources were worked. The first is data affordances, meaning what the raw and unified layers can measure that nothing in this repository measures. The second is literature concepts the corpus formalises that this project has not operationalised. Four of the eight accepted candidates came from the first, three from the second, and one from the collision of both.

---

## A correction to the brief, stated first because it changes what several candidates can promise

The brief describes the raw layer as holding per-transaction gas price. It does not. No swap, mint, burn or join stream under `data/raw/thegraph/` carries `gasPrice`, `effectiveGasPrice` or `gasUsed`; the fields present are `blockNumber`, `timestamp`, `logIndex` and the amount columns. Gas in this repository comes from two places, and both are coarse. `data/processed/daily_gas_eth.parquet` holds twelve rows, built by `scripts/build_daily_gas_and_eth.py` from three JSON-RPC receipts per sampled day with a base-fee fallback, and `data/processed/daily_gas_price_graph.parquet` holds 1,883 daily medians. Node I's section 7 requirement, that the gas term be candidate-specific and venue-specific because a constant common to candidates is absorbed by the group fixed effect, is therefore unmet by every artefact in the repository and cannot be met without a receipt fetch that nothing has budgeted. Every candidate below is designed so that gas enters as a level and never as the identifying variation, and the two that would need a candidate-specific gas term say so.

---

## Accepted candidates, ranked by expected contribution against cost

### K1. The arbitrageur's numéraire, as an inertia-free benchmark for the vehicle role

This project discards a potentially informative population. Canonical endpoint round trips run 12.7% of multi-leg routes by count and 21.7% by value on the median day of 79 sampled, and every panel excludes them because they lie outside endpoint-to-endpoint conversion. They may contain cyclic arbitrage and other self-returning activity, but neither the endpoint rule nor the cited evidence proves the agents are habit-free. A useful test would identify repeated searchers, compare their route and base-asset choices with the acyclic population, absorb searcher effects and condition on state-dependent profitability. A weaker persistence profile would support the proposed benchmark. Turning the excluded population into a separately validated measuring instrument is the proposal.

**Estimand.** Two objects on a common denominator. The wedge, meaning the difference at each date between the vehicle share of cyclic flow and the vehicle share of acyclic flow, by asset type. And the lead, meaning the number of days by which the cyclic series turns before the acyclic series turns, estimated as the lag maximising cross-correlation and separately as the horizon profile of a local projection of the acyclic share on lags of the cyclic share with pair fixed effects.

**Identification, and the variation that carries it.** Within day and within ordered pair, cyclic and acyclic routes face the same pool state, the same gas price, the same venue set and the same fee schedule. The only thing that differs between them is the agent. So a wedge between their intermediary mixes cannot be a cost difference and must be an agent difference, which is what inertia means. The time-series variation is carried by the several dozen dates on which relative candidate cost moves sharply, and the estimate is the delay between the two populations reacting to the same move.

**Falsification.** Zero wedge and zero lead. If arbitrage flow and ordinary flow switch intermediary at the same date and in the same proportion, then nothing beyond contemporaneous cost drives ordinary routing, section 4.0's judgement that routing is not a site of habit is confirmed on direct evidence, and the paper must locate incumbency entirely in the state variables that K4 and K5 address.

**What it displaces or supports.** It supplies, without touching the counterfactual quoter, the object that the retired lagged-share persistence design and the withdrawn transaction-state persistence result were both reaching for. That matters because it is immune to the constraint that kills those: the 62.8% of validated actual routes moving more than 30 basis points before hour end cannot contaminate a comparison between two populations of realised trades. It supports `docs/finding-intermediation-transition.md` by dating the transition twice on the same data and reading the gap as a magnitude.

**Biggest threat.** A searcher's base asset is chosen for funding reasons and not for DEX routing cost. Flash-loan depth on the lending venues, and inventory the bot already holds, both push toward WETH and USDC for reasons that have nothing to do with the routing question. Mitigation is to split cycles by whether the transaction contains legs outside the DEX venue set, which `n_components` and unmatched role assignments in the unified layer expose, and to report the wedge on self-funded cycles separately. If the wedge survives only on the funded subset, the finding is about lending markets and must be reported as such.

**Files and streams.** `data/unified/*.parquet` for `tx_hash`, `component_id`, `n_components`, `route_class`, `tin_role`, `tout_role` and `source`; `data/processed/intermediation_by_type_daily.parquet` as the acyclic comparator already built; `src/ddvc/asset_types.py` for the type map. Cost is medium: one pass over 2,277 daily files with a cycle detector on the component graph.

---

### K2. Somogyi's three conditions, tested where his latent variable is observed

Somogyi (*Management Science*, published online 2026-04-07, in the corpus at `literature/text/2026-Somogyi2026DollarDominanceFX-dollar-dominance-in-fx-trading.txt`) is the closest live competitor to this paper's question and the corpus already holds it. His model derives conditions for dominance and his text states them at lines 196 to 200 and 1564 to 1569: dollar pairs exhibit C1 larger average fundamental trading demands, C2 more volatile fundamental trading demands, and C3 less volatile currency returns than nondollar pairs. He then draws the conclusion this paper has to answer, at line 200, that dominance in his model is not a co-ordination result. His empirical work rests on inferring the vehicle component from a triangular volume identity, reaching 13% of dollar-pair volume, and his own decomposition attributes roughly 5.3% of the time-series variation in dominance to C1 and up to 3.1% jointly to C2 and C3, leaving above ninety per cent unexplained. Here the vehicle component is not inferred. It is read off `tin_role` and `tout_role` leg by leg.

**Estimand.** Within a token triplet on a day, the elasticity of the candidate's vehicle share to the level of fundamental demand in its pairs, to the volatility of that demand, and to the candidate's own return volatility, plus the residual share of variation in vehicle share once all of those are absorbed. The residual is the quantity Somogyi cannot compute and this project can.

**Identification, and the variation that carries it.** The decomposition into fundamental and vehicle volume is measured and not modelled, because a source-to-sink leg and a source-to-intermediate leg are separately labelled in the unified layer. Variation comes from the several thousand triplets alive on a typical day and from time within a triplet. The decisive variation is a fact about this market that FX does not contain: the incumbent vehicle here, the native platform asset, violates C3 by construction, since it is the most volatile of the five candidates, while the challenger satisfies C3 throughout the sample. Somogyi's conditions therefore predict the stable numéraire should have held the role from the first day, and it did not.

**Falsification.** If C1 to C3 explain the on-chain vehicle share and its migration as well as they explain FX dominance or better, then coordination is unnecessary to read this data, Krugman's structure is surplus, and the paper's framing loses its motive. The result would still be publishable and it would be a different paper. The alternative outcome is that the conditions first favour the stable numéraire many months before the routing crossover, and the length of that lag is the coordination friction stated in months.

**What it displaces or supports.** It engages the newest and most directly competing published work in the corpus on its own model's terms, and it converts that paper's identification weakness into this paper's comparative advantage. Section 4.0 records that nothing in the literature connects DEX routing to the vehicle-currency question, so the introduction currently has no differentiation sentence against the FX side. This buys one.

**Biggest threat.** Return volatility for long-tail tokens is measured from DEX prices generated by the routing being explained, so C3 becomes endogenous to the outcome. Mitigation is to measure volatility only for the candidate vehicles, all five of which have deep independent pricing, and never for the endpoint tokens. A second threat is that a triplet in FX is a closed object with three currencies and a triplet here is a construct over thousands of tokens, so the mapping from Somogyi's proposition to a regression specification needs writing down carefully before anything is estimated.

**Files and streams.** `data/unified/*.parquet` role columns; `data/processed/observations_token_day.parquet` for pair coverage and bridge shares; `data/processed/v2_token_price_daily.parquet` for candidate returns; `data/processed/vehicle_centrality_dense.parquet` for the triplet frame. Cost is low to medium, since the fundamental and vehicle volume split is a group-by over existing columns.

---

### K3. Was the transition a trend or a staircase

The lead result reports annual shares. `docs/finding-intermediation-transition.md` prints the native and stable intermediation shares by year, and the daily panel behind it, `data/processed/intermediation_by_type_daily.parquet`, has 2,240 rows and has never been read at event frequency. An annual table cannot distinguish a smooth network-externality migration from a punctuated one, and those are different economics. Node I's objection 4 is that the paper is about time while its estimates have no time dimension. That objection was aimed at the retired level comparison. It applies with equal force to the result that survived.

**Estimand.** The fraction of the six-year native-to-stable migration in intermediation share that accrues inside a small set of dated stress windows, and the reversion fraction measured at 30, 90 and 180 days after each window closes. Both are shares of the total migration, so both are in the units the result is already reported in.

**Identification, and the variation that carries it.** The windows are dated by events exogenous to any single token pair's routing decision: the March 2020 liquidation cascade, the May 2021 drawdown, the May 2022 algorithmic-stablecoin failure, the November 2022 offshore exchange collapse, and the March 2023 banking episode that broke the peg of the largest stable candidate. Within-pair before-and-after with the pair set frozen at pre-window membership, against a comparison set of pairs already intermediated by a stable candidate before the window opened. The ratchet is the reversion coefficient.

**Falsification, and the sharp version of it.** A smooth trend with full reversion after every window says the migration is gradual and the crisis reading is wrong. Near-zero reversion says the role moves by punctuated reallocation, which no FX sample contains enough dated stress to observe. The decisive window is March 2023, because it is a flight away from the challenger and not toward it. If the stable intermediation share ratchets up through the depeg of the stable numéraire itself, no risk-aversion account of the transition survives and the mechanism must be transactional. If it falls and stays down, the transition is a risk story and the vehicle-currency framing is the wrong frame for it.

**What it displaces or supports.** It re-reads the paper's lead result at the frequency the result's own claim requires, and it is the cheapest available answer to node I's objection 4 applied to a result that is not retired.

**Biggest threat.** Every one of those windows is also a gas-price shock and a volume shock, so route composition moves for reasons the design does not want. Holding the pair set fixed at pre-window membership handles entry and exit, and the gas path has to be plotted alongside every window so a reader can see whether the ratchet coincides with a gas regime change. The March 2023 window is the one where this threat is weakest, which is a further reason to lead with it.

**Files and streams.** `data/processed/intermediation_by_type_daily.parquet`; `data/unified/*.parquet` for the pair-level version; `data/processed/daily_gas_eth.parquet` and `data/processed/daily_gas_price_graph.parquet` for the gas path; `data/processed/cross_venue_routing_daily.parquet` for the composition check. Cost is the lowest of any candidate here. The aggregate version runs against a parquet that already exists.

---

### K4. The pool-creation margin, where habit can actually live

Section 4.0 establishes that routing is executed by deterministic graph optimisers and therefore cannot carry inertia, then names two places incumbency can live: LP capital allocation and aggregator integration scope. It misses the one that is fully observable, discrete, and made by a human exactly once per token. When a new token's first pool is created, someone chooses what to pair it with, and that choice fixes the token's routing topology for the rest of its life. `docs/finding-v1-forced-vehicle.md` already reports the fact that makes this margin interesting, that the native-asset share of newly created pairs rose from 84% in 2020 to 98% by 2023 after the protocol mandate forcing that pairing was withdrawn. That fact currently sits inside a negative result as an unexplained aside.

**Estimand.** In a conditional logit over candidate pairing assets at the moment of first pool creation, the coefficient on the candidate's installed pairing degree, holding the candidate's contemporaneous depth and the contemporaneous routing cost through it fixed. Degree and depth are separately measured in `data/processed/vehicle_centrality_dense.parquet` as `degree` and `strength_usd`, so the network-externality channel and the pure depth channel are not collinear by construction.

**Identification, and the variation that carries it.** Launch cohorts. Tokens created in different weeks face different relative depth and different relative installed base among the candidates, and gas regimes plus the V3 fee-tier introduction move the cost of a candidate leg without moving its installed base inside a short window. The comparison is within launch week and across tokens.

**Falsification.** An installed-base coefficient indistinguishable from zero once cost and depth are held fixed. That says the network externality operates only through contemporaneous depth, that Krugman's coordination channel has no support at the single margin where it should be most visible, and that the whole vehicle-currency reading of this market rests on a depth ranking.

**What it displaces or supports.** It supplies the mechanism `docs/paper-spine.md` section 5 is missing and that node I's third desk-reject ground names as absent, and it is a mechanism that survives the routing-is-not-habit correction intact because it operates on a decision made once at human cadence. It also converts the V1 finding's unexplained aside into a measured object, which upgrades a negative result.

**Biggest threat.** Deployer tooling and launchpads hard-code the native asset as the pairing default, so the coefficient may be measuring a software default and not a choice. This is not fatal, since a default that nobody overrides is a switching cost and is the aggregator-integration channel wearing different clothes, but it changes the interpretation completely and it has to be measured and not argued. The test is to cluster on deployer address and report the coefficient within deployer, where the same deployer launched tokens on both sides of a cost move.

**Files and streams.** `data/processed/v2_pair_first_trade.parquet`; the `*_daily` streams under `data/raw/thegraph/uniswap_v2`, `uniswap_v3` and `uniswap_v4` for pool first appearance across venues; `data/unified/*.parquet` for contemporaneous leg cost; `data/processed/vehicle_centrality_dense.parquet` for degree and strength. Cost is medium.

---

### K5. LP capital hysteresis, estimated at the address level, in basis points

Section 4.0 names LP capital allocation as a home for incumbency. The old concentration reader and aggregate `run_lp_repositioning_tests.py` proxy were subsequently retired; the canonical replacement measures deposited capital separately from causal dollar supply flows. Neither replacement yet identifies provider wallets. That identity remains constructible: every V3 mint and burn carries `origin`, the externally owned account that sent the transaction, and every V4 modify-liquidity record carries both `origin` and `sender`. An LP-address by pool by day panel is directly constructible over 1,884 V3 days and 546 V4 days.

**Estimand.** The net-return edge, in annualised basis points, required to pull an LP's capital out of a native-paired pool, set against the edge required to pull it back in, measured on the same addresses and the same pools. The difference between the two thresholds is the switching cost in economic units, which is the kind of magnitude node I's first desk-reject ground says the project keeps failing to report.

**Identification, and the variation that carries it.** Within LP and within day, across the pools that LP already occupies. The LP fixed effect absorbs attention, gas budget, capital scale and sophistication, so the only thing moving is the cross-pool return differential. That differential is realised fees minus loss-versus-rebalancing minus gas. The current V2 and V3 pool-day rent panels contain the required components; the former monthly aggregate was deleted after its producer changed and must be regenerated from those current daily inputs before this candidate enters F.

**Falsification.** Symmetric thresholds. If it takes the same edge to move capital out as to move it back, LP capital is not sticky, and section 4.0's list of legitimate homes for incumbency is empty. That is a publishable null and it forces the paper onto pure architecture, which section 4.0 already says may not lead.

**What it displaces or supports.** It is the mechanism layer beneath both the transition and the rent-incidence node, and it is the only asymmetry test available in this project that never touches the counterfactual quoter and therefore does not inherit the support bound or the measured transaction-to-hour movement. Everything else in the repository that speaks to hysteresis is downstream of a quote for a route nobody took.

**Biggest threat.** The identity key differs by venue and one of the obvious keys is wrong. On V3, `owner` is the NonfungiblePositionManager contract on the great majority of mints, so a panel keyed on `owner` measures the position manager and not the provider; `origin` is the correct key. On V2 there is no `origin` at all: mints carry `sender`, which is the router, and `to`, which is the recipient of the LP token, while burns carry `sender` and `to` with reversed meaning. So the V2 arm and the V3 arm are keyed on different objects and are not comparable without an explicit crosswalk and a stated bound on what fraction of positions each key recovers. This has to be settled and reported before any threshold is estimated, and if it cannot be settled the candidate reduces to V3 and V4 only, which still spans the transition.

**Files and streams.** `data/raw/thegraph/uniswap_v3/uniswap_v3_mints_*` and `uniswap_v3_burns_*`; `data/raw/thegraph/uniswap_v4/uniswap_v4_modify_liquidities_*`; `data/raw/thegraph/uniswap_v2/uniswap_v2_mints_*` and `uniswap_v2_burns_*` if the key crosswalk holds; the current V2 and V3 rent-incidence pool-day panels, followed by a newly provenance-stamped monthly aggregation owned by the F runner. Cost is the highest here, because it means an address-level panel over roughly 4,700 daily files.

---

### K6. Vehicle dependence as a liquidity-risk exposure

Chordia, Roll and Subrahmanyam on commonality, and Klein and Song on commonality after multilateral trading facility entry, are both in the corpus, and the workflow cites Klein and Song only as a template for the spillover node's event study. The economic content of that strand has not been operationalised anywhere in this project. The vehicle role is currently measured entirely as a benefit, meaning cheaper routing and thicker networks. Its risk side has no measurement: a token whose routing depends on a hub inherits the hub's liquidity shocks whether or not anything happened to the token.

**Estimand.** The coefficient on the interaction of a hub liquidity shock with predetermined vehicle dependence, in a token-day panel whose outcome is the token's own realised execution cost. Read as an elasticity, it prices the insurance a token buys by pairing away from the hub, and it is the welfare counterpart to the centrality curse the rent-incidence node predicts on the LP side.

**Identification, and the variation that carries it.** Hub-side liquidity shocks that are not about the dependent token, specifically large single-address withdrawals from native-paired pools identified from the V3 burn stream by `origin` and `amount`, and the repositioning-suppressing gas spikes that hit hub pools hardest because hub pools reposition most. Dependence is measured in a pre-period and is therefore predetermined. Because dependence varies across tokens within a day, day fixed effects are available and the market-wide component of any shock is absorbed.

**Falsification.** No differential. High-dependence and low-dependence tokens absorb hub liquidity shocks equally, which says routing through a hub carries no risk premium and the network externality is free. That is a clean null and it strengthens the pure-cost reading of the vehicle role.

**What it displaces or supports.** It supplies a reason the migration to the stable numéraire could be efficient and not fashionable, which is the interpretive gap the transition result currently leaves open. Paired with the rent-incidence node's centrality curse, it says the hub is costly at both ends of the market, on the provider side and on the taker side, which is a stronger and more surprising joint statement than either alone.

**Biggest threat.** Hub liquidity shocks coincide with market-wide risk-off, and high-dependence tokens are also the highest-beta tokens, so the interaction picks up beta. Day fixed effects handle the common component but not the differential loading, so a token-level beta estimated outside the shock windows has to enter as an interacted control, and the result has to be shown to survive it.

**Files and streams.** `data/raw/thegraph/uniswap_v3/uniswap_v3_burns_*` for withdrawal shocks; `data/unified/*.parquet` for realised execution cost and dependence; `data/processed/observations_token_day.parquet`; `data/processed/vehicle_centrality_dense.parquet`. Cost is medium.

---

### K7. The venue-technology rival explanation for the lead result

The strongest rival explanation for the paper's headline has not been stated anywhere in this repository, and a referee who knows this market will raise it in the first paragraph of their report. The stable numéraire's rise as an intermediary coincides with the rise of venues running a stableswap invariant, which makes stable-to-stable legs almost free and exists for no other asset class. If the transition is a venue-technology event, the vehicle-currency reading of it is wrong, and the paper's lead result is a Curve result wearing a monetary label.

**Estimand.** The share of the measured rise in the stable intermediation share attributable to the arrival and growth of stableswap-invariant venues, decomposed within venue and between venue, and the same series recomputed on the constant-product venue subset only.

**Identification, and the variation that carries it.** The unified layer carries `source` on every leg, so the identical series can be rebuilt on the constant-product subset, meaning Uniswap V2, Sushiswap V2 and the Balancer weighted family, where no invariant advantage for stable assets exists. The test has a sign prediction the technology story must make. An intermediated route through a stable candidate consists of volatile-to-stable legs, which a stableswap invariant does not serve, so the technology account predicts the rise should be concentrated in stable-to-stable legs and absent from the intermediation series proper.

**Falsification.** If the stable intermediation share rises at the same rate on the constant-product subset, the technology explanation is dead and the monetary reading stands on stronger ground than it does now. If it does not rise there at all, the lead result is a venue-composition artefact and the framing has to change.

**What it displaces or supports.** It either hardens or destroys `docs/finding-intermediation-transition.md`, which is the result the paper leads with and the one everything else is arranged around. No other candidate here can change so much for so little work.

**Biggest threat.** Venue choice is itself endogenous to the cost of the leg, so restricting to the constant-product subset conditions on an outcome. The restricted series alone is therefore not sufficient and has to be reported alongside a decomposition of the aggregate change into a within-venue component and a between-venue component, so the reader sees how much of the movement is composition across venues and how much is behaviour inside them.

**Files and streams.** `data/unified/*.parquet` for `source` and the role columns; `scripts/build_intermediation_by_type.py` as the base to fork; `data/processed/intermediation_by_type_daily.parquet` as the comparator. Cost is hours.

---

### K8. Pair graduation, and whether it reverses

Krugman's structure distinguishes partial- and total-indirect regimes through cost inequalities, but routed volume varies with the payment imbalance inside the partial regime. It therefore supplies a categorical regime precedent without ruling out gradients in observed vehicle use. Conditional multiplicity motivates testing asymmetric entry and exit, but the published article gives no formal transition dynamics and does not itself imply that a switch is harder to undo than to make. This project has the pair panel to date both events and has never dated either. `data/processed/v2_pair_routing_daily.parquet` holds 12.8 million rows keyed on ordered pair, day and route kind.

**Estimand.** The hazard of graduation, meaning the day an ordered pair's direct route first captures the majority of its own flow, as a function of the pair's own volume, set against the hazard of reversion back to majority-intermediated routing evaluated at the same own-volume level. The gap between the two hazards at equal volume is the pair-level incumbency premium, and it is measured in a running variable that has nothing to do with a counterfactual quote.

**Identification, and the variation that carries it.** Graduation and reversion are dated events on one running variable, so the comparison is between two hazards at the same point on it and never between two levels. Variation comes from the tens of thousands of pairs that cross the threshold in both directions across six years.

**Falsification.** Symmetric hazards. That refutes multiple equilibria at the pair level and says direct-versus-vehicle routing is a smooth function of own volume, which is the single-equilibrium reading Flandreau and Jobst reach for currencies and which section 4.3 flags as the closest prior claim this paper would have to beat.

**What it displaces or supports.** It is the pair-level analogue of the retired persistence design, built on an asymmetry instead of a lagged dependent variable, so it escapes the Chinn-Frankel critique that retired the original. It is adjacent to `scripts/run_displacement_asymmetry.py`, and the difference has to be stated so the two do not collide: that script compares one vehicle candidate against another on a cost edge, and this compares direct routing against intermediated routing on a volume threshold. If they turn out to be the same object under two names, this one is the redundant one and should be dropped.

**Biggest threat.** Graduation is partly the mechanical consequence of a direct pool being created and funded, in which case the estimand is pool creation and the candidate collapses into K4. The hazard must condition on a direct pool existing with a size floor throughout the window, and the fraction of graduations that coincide with pool creation must be reported before anything else in the design is believed.

**Files and streams.** `data/processed/v2_pair_routing_daily.parquet`; `data/unified/*.parquet` for the multi-venue version, since the existing panel is V2-only and section 2 forbids leaving it that way; `data/processed/v2_pair_first_trade.parquet` for the pool-creation control. Cost is medium.

---

## Rejected, with reasons

These were generated and killed. The list is here because the screen is the useful part.

**Mechanical AMM price-impact slope, not a Kyle lambda.** In Kyle, lambda is the equilibrium slope of conditional liquidation value with respect to aggregate informed-plus-noise order flow. In a constant-product pool, local price impact is mechanically determined by reserves, fee and trade size; an OLS coefficient is only a local linear approximation to a nonlinear invariant. It therefore adds no independent identifying variation and is rejected. Kyle supplies no permanent-versus-transitory decomposition for K6, which concerns vehicle dependence on hub-liquidity shocks.

**The Amihud illiquidity ratio by token.** Same defect in a different notation. Absolute return over volume in an automated market maker is the reciprocal of depth up to a design-specific constant, so the measure is a re-expression of pool size and carries no information that `strength_usd` does not already carry.

**Gas price and the number of hops in a route.** Higher gas mechanically penalises the extra hop, so the effect of gas on intermediated share has a guaranteed sign. The part that is not guaranteed is whether the retreat reverses when gas normalises, and that hysteresis question is better identified on the dated windows in K3 than on a gas series that is itself a daily median from three receipts.

**Router and aggregator identity as an explanatory variable.** Ruled out by the stated hard constraint and by `docs/router-identification-feasibility.md`. The entry contract identifies the executor and not the frontend, the executor population fragments to 397 senders by late 2025, and a hand registry captures 11.8% of swaps. Any coefficient on router identity would be estimated on a non-random eighth of the data and would be attacked on exactly that ground.

**Three-hop and split-route counterfactual cost surfaces.** Rejected because they compound the binding constraint. With 62.8% of validated actual two-leg routes moving more than 30 basis points before hour end, a third leg adds another stale state, and nothing should be added on top of the quoter before transaction-state counterfactual pricing exists. Proposing more counterfactual surface area now would enlarge the unvalidated object.

**Survival of the vehicle role after cost-dominance opens, with the retention-against-displacement asymmetry.** Not mine and already running. It is node I's section 4 proposal and it has two scripts, `scripts/run_survival_after_dominance.py` and `scripts/run_displacement_asymmetry.py`. Listed so the omission does not read as ignorance.

**Hasbrouck information shares between the vehicle path and the direct path.** Killed on two counts. Atomic arbitrage equalises prices inside a block, so the measured lead would be decided by transaction ordering within a block and by which pool a searcher touched first, which is the outcome of a gas auction and not price discovery. And Klein, Kozhan, Viswanath-Natraj and Wang (2026, in the corpus) already occupy the DEX price-discovery position, finding permanent price impact from liquidity provision in the ETH-USDC low-fee pool. Reconsider only with block-ordered data and a design that conditions on arbitrage arrival.

**Trader-level switching behaviour keyed on the `origin` account.** The account chooses a frontend and not a route, the frontend is not recoverable per the constraint above, and a large share of distinct origins are bot-operated. A switching coefficient at this level would be the composition of an unobserved router's upgrade schedule with a trader's choice, and neither part would be separately identified.

**Concentrated liquidity as the cause of the transition, measured as depth-per-dollar by asset role before and after V3.** A good question owned by another node. The cross-venue spillover node already holds the V3 and V4 launch windows, and running a second independent design on the same event across two nodes creates a multiple-comparison problem that neither node would see. The right disposition is to hand depth-per-dollar by asset role to that node as an additional outcome.

**A Herfindahl of liquidity providers within a pool.** The effective-number-of-vehicles panel is already building and a provider-side concentration index would report the same shape one layer down without a separate estimand. K5 keeps the provider layer and replaces the index with a threshold in basis points, which is a magnitude a referee can hold.

**A convenience yield on the vehicle asset, measured as a price premium.** There is no on-chain price of the vehicle that is independent of the pools whose routing is the outcome, so the regressor would be a function of the dependent variable. This is the same defect node I identified in the five-per-cent trim, arriving from a different direction.

---

## What this list assumes, stated so it can be attacked

Every candidate above is designed to be estimable without the counterfactual quoter, or to use it only as a level and never as identifying variation. That is a judgement about where this project's risk sits, and it could be wrong. If the off-support error bound comes back tight, the quoter becomes the best instrument in the repository and several rejected candidates come back. If it comes back loose, K1, K3, K5 and K8 are the only lines of work in this project that survive it, and that concentration is the reason they are ranked where they are.

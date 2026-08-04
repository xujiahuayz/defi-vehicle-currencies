# Node B — domain literature closed, with a prior-art verdict that changed the plan

Four independent lanes (prior art on the cross-aggregator test; inertia and hysteresis in currency dominance; LVR and rent incidence; router and aggregator microstructure), then a reconciliation pass that was asked to flag contradictions with the workflow. It found seven.

---

## Reconciled synthesis

## 1. NOVELTY VERDICT — cross-aggregator routing test

**Already done, as written. The planned second headline result does not survive in its stated form.**

The paper is **Weiye Xi & Ciamac C. Moallemi, "Quantifying Sub-Optimality in Routing for Automated Market Makers," arXiv 2607.20762 (22 Jul 2026).** It executes all three steps that §4.0 and §4.1(1) claim as the design's sharpest contribution:

- **Router identification from the entry contract** — "labels are assigned by destination contract address," across Universal Router, CoWSwap, 1inch v4, 1inch v5, Odos v2.
- **Cross-router comparison** — 2.98M WETH-USDC swaps, blocks 19.5M–23.0M, $120.42bn input, against three reproducible optimality benchmarks; per-router medians and dispersion reported (CoWSwap tightest, Universal Router / Odos widest).
- **The residual attributed to router architecture** — in print: "differences across routers … are consistent with institutional features, e.g., solver-mediated batch auctions and private order flow in CoW Protocol."

That is §4.1(1) verbatim, on a larger sample, with benchmarks we would have to match. A referee finds it in one search. Secondary redundancy: **Bachu, Wan & Moallemi (arXiv 2405.00537, 2024)** owns the interface-level version (4–5 bps price improvement, decomposed into routing / gas / priority fee); **Ruiyang Zhang (arXiv 2607.21955, 2026)** owns aggregator market structure via CoW's CIP-74 as a governance-dated natural experiment — a cleaner design than any cross-section, and it occupies §4.0's "aggregator integration scope" slot directly.

**What is left, and it is the actual topic.** Xi & Moallemi exclude by assumption exactly our object: "we restrict attention to a simplified same-token setting … we do not allow trading through other intermediate tokens when routing," single pair, L1 only, no multi-hop — and they name multi-hop extension as future work. Also untouched: matched-trade same-block head-to-head between two routers (they measure each router against a counterfactual optimum, never against another router), long-tail pairs where the intermediary is genuinely contested, and the join between token centrality in the liquidity graph (Yan & Tessone 2503.07834) and router intermediary selection. Nothing anywhere connects DEX routing to the vehicle-currency literature; searches for "vehicle currency" + DeFi routing return zero.

**Survivable reframing (adopt this):** *given* that routers differ (cite Xi & Moallemi as established fact, do not re-establish it), does the divergence appear in **vehicle-asset selection on pairs where the intermediary is contested**, and does the pattern match each router's integrated venue set as the vehicle-currency mechanism predicts? Our `data/unified/` layer — `route_class`, `tin_role`, `tout_role`, multi-leg routes reconstructed across eight venues — is precisely the asset their stated limitation lacks. This is a promotion of the multi-hop margin from incidental to headline.

**Residual risk:** SSRN was unsearchable in the prior-art pass (403), so finance-side working papers are unchecked; and an untraced MetaMask multi-aggregator study (554k swaps, "Vaish") is the structurally cleanest natural experiment for this question in existence. Both need chasing before the framing locks.

## 2. What the inertia literature licenses, and the FX identification limitation we overcome

**Licensed:**
- Persistence is real, large, and measured: ρ̂ = 0.90–0.96 (Chinn & Frankel), 0.98 with a 29-year half-life (Chiţu-Eichengreen-Mehl), 0.968 and "not easily distinguished from unity" under a common ρ (Chinn-Frankel-Ito 2024).
- The literature declares its own limit: "we have hit the limits of what aggregate foreign reserves data can tell us" (CFI 2024); "we do not have the luxury of sufficient data to expect robust results" (Chinn & Frankel).
- Adding better fundamentals does **not** shrink measured inertia — CEM add financial depth, show it explains most of the level, and report ρ̂ "remains unaltered."
- Ilzetzki-Reinhart-Rogoff: dollar anchor share flat-to-rising over seven decades while US output share fell — persistence surviving a measured decline in the most-cited fundamental.

**Not licensed:**
- Do **not** say prior authors failed to control for costs. CEM ran the correct IV (Griliches-Liviatan, Hatanaka); CFI added the right controls and honestly reported failure; Flandreau & Jobst (2009) went structural and **reject strong lock-in** while confirming persistence. That last paper is the closest prior claim to resolution and must be engaged directly — it is currently abstract-verified only, and reading it through institutional access is the single highest-priority verification gap.
- Do **not** claim the literature says "persistence = inertia." Camp B contests the crossover *date* and the *number* of simultaneous incumbents, not the parameter.
- Do **not** claim to speak to invoicing / unit-of-account (Goldberg-Tille, Gopinath-Stein, whose footnote 5 explicitly sets aside the vehicle role). Claim the routing / medium-of-exchange sense (Krugman, Rey, Devereux-Shi) and decline the other explicitly — Devereux & Shi warn the two senses are "quite different."

**The precise limitation, in one intro-ready sentence:**

> In foreign exchange, an incumbent vehicle currency's cost advantage is itself a consequence of its incumbency, so the data never contain the state in which a currency retains the vehicle role while being strictly cost-dominated by a rival; on-chain routing does, because every candidate route's all-in execution cost is observed contemporaneously and the road not taken can be priced.

**The conditional that decides whether this is an advance or merely better measurement.** Direct cost measurement breaks residualisation; thousands of pools break the degrees-of-freedom limit; block frequency moves ρ away from unity. But the missing-counterfactual layer is only broken if **windows exist in which an incumbent route is strictly cost-dominated on an executable all-in basis while its incumbency is intact** — fee-tier changes, V2→V3→V4 migrations, gas-regime shifts, the USDC depeg. **Settle this empirically before writing the framing.** If such windows are numerous, the claim is strong. If not, say plainly that the paper improves measurement and does not overcome the identification limitation.

## 3. LVR: what is settled, what is open, and the centrality curse

**Settled.** For a handful of large CEX-listed pools, gross fees are the *same order* as adverse-selection losses, with the sign flipping across pool, version, fee tier and period. That is the entire consensus.
- Milionis-Moallemi-Roughgarden-Zhang is routinely mis-cited: v2 WETH-USDC raw P&L −6.20% annualised is **market risk**, while delta-hedged P&L was **+5.04% to +9.75%** — fees exceeded LVR.
- Fritsch & Canidio: fees fall short in most large v3 pools (WETH-USDC 5bp ≈ 80% coverage) but **over-cover by ~50% in altcoin-ETH pools**, and v2 covers ~3×.
- Heimbach et al. (AFT'22), position-level: "less than 30% of the liquidity positions in the four [volatile] pools are rewarded for the added risks they shoulder."

**Open, and it is our leverage: nobody has netted gas.** The string "gas" appears zero times in Heimbach et al., zero in Fritsch & Canidio ("we do not consider blockchain transaction costs"). Only Cartea/Drissi/Monga price it: $84.8 per reposition operation, break-even only above ~$1.8m deposited. Because gas is a flat per-operation cost, net profitability has **no scalar answer — it has a size threshold**. Any net-return claim must carry a position-size distribution, not a mean.

**LP returns by pool-asset role: no paper does this.** Zero papers group LP profitability or LVR by asset role or centrality across the arXiv/OpenAlex searches run (SSRN, RePEc/EconLit unsearched). Existing taxonomies sort on *pair volatility*, not role. Fritsch & Canidio's split is the closest thing in existence and points our way — losers are hub-vs-numéraire (WETH-USDC/USDT, WBTC-USDC), winners are spoke-vs-hub (LDO/LINK/MATIC/UNI-ETH) — but they never frame it as asset role and it is confounded four ways (size, volume, fee tier, Binance listing).

**Is the centrality curse open? Yes — never named, tested, or ruled out. But it is *not surprising*, and §4.1(5) is wrong to say so.** It is *predicted*: LVR is the scaled product of price variance and marginal depth, so it is largest exactly where σ²·depth is largest (hub pools), while fee income scales with volume; and Yuan (2005) — already in our corpus — supplies the informational version, since a benchmark asset draws in informed traders, and more informativeness *is* more adverse selection. Yuan generates a centrality curse for LPs while improving market quality; our notes currently classify Yuan only as the vehicle-currency precedent and do not draw this out. The gross-fee leg is documented at ~20× (ETH-USDC 5bp 2.12×10⁻³ vs USDT-USDC 5bp 1.02×10⁻⁴ daily per $1 liquidity).

**Two attacks to pre-empt.** (i) **The CEX-listing confound**: "is the hub asset" is nearly collinear with "has a deep CEX reference market," and the CEX market is what *creates* measurable arbitrage — a centrality curse and a CEX-arbitrage-exposure curse predict the same cross-section. Separation requires CEX-listed spoke tokens (LINK, UNI, MATIC), pools where the on-chain hub is not the CEX numéraire, or L2 latency variation. Worse, the standard reference-price filter deletes exactly the long-tail tokens that identify the hub effect, and for non-hub pools the Binance benchmark is *constructed by chaining two USDT pairs* — imposing vehicle routing on the benchmark. (ii) **Gas is a mediator, not a nuisance**: Caparros/Chaudhary/Klein already show gas causally drives repositioning intensity, and repositioning is highest in hub pools, so gas cannot be absorbed into a fixed effect.

**Highest-value follow-up in the whole review:** Chu, Dowling & Li, "Impermanent loss in cryptocurrency," *JIMF* 160 (2026), DOI 10.1016/j.jimonfin.2025.103476 — secondary sources describe Fama-MacBeth regressions pricing IL risk in LP returns with pool-level controls. This is the paper most likely to already contain a pool-characteristic cross-section of LP returns. Needs a first-hand read; do not cite from summary.

## 4. Mandatory measurement requirements

**Route cost — adopt the Xi & Moallemi (arXiv 2607.20762) three-benchmark ladder, by name.** Suboptimality as proportional shortfall of the realised route against benchmarks solved at fixed pool state: **SCO** (reoptimise splits only across pools the trade touched — isolates mis-splitting), **FVO** (reoptimise across all pools, no gas — adds venue omission), **G-FVO** (gas-aware, fixed per-pool activation cost, mixed-integer). Also adopt their **direction-asymmetric gas model** (token0→1 deducts from output; token1→0 shrinks the input budget) and their **state-staleness experiment**: one block of staleness costs +1.29 bps (FVO) / +1.78 bps (G-FVO). Report medians alongside means — 2–3% of trades drive the entire mean. Justify the exercise with Angeris-Chitra-Evans-Boyd (EC 2022): gas-aware optimal routing is mixed-integer convex, hence production routers are necessarily heuristic and a shortfall exists to measure.

**Cost level — adopt Barbon & Ranaldo (*Management Science*):** `TC_XY(Δx) = S_XY(Δx) + f + g/Δx`, on **hypothetical trades at a fixed notional grid ($1k / $10k / $100k / $1M), hourly**, gas as a fixed unit count × median gas price. Their headline is that validator gas, not classical price impact, dominates trader cost. Reusing their definition costs nothing and buys referee familiarity.

**Second benchmark family — CEX markout, per Yuminaga/Chen/Sui (arXiv 2503.00738):** counterfactual simulated at **top-of-block (N−1)** liquidity to avoid own-trade interference, gas from same-block competing priority fees, plus a Binance-mid markout. "Was this the best on-chain path?" and "was the fill good absolutely?" are different questions with different benchmarks and **can disagree in sign**. Report both; divergence is a finding.

**Gas per hop must be measured, not assumed.** No verified per-additional-hop figure exists in any source. Measure from receipts per route topology; Barbon-Ranaldo's 118,340 (v2) / 130,889 (v3) single-swap constants are a fallback only. A two-hop vehicle route is mechanically more gas-expensive than one hop, so omitting gas biases the panel **systematically toward the vehicle route** — the direction that would manufacture our result.

**Depth — there is no accepted academic standard.** Options: the industry ±2% convention (Liao & Robinson, Uniswap, not peer-reviewed) or Barbon-Ranaldo's sidestep via fixed-notional cost curves (published). Our own SoK (Xu, Paruch, Cousaert, Feng, *ACM CSUR*, DOI 10.1145/3570639) is the natural citation for design-specific slippage — and is trivially checkable locally since we are an author.

**Separate MEV from routing shortfall.** Realised on-chain amounts embed sandwich losses; simulated counterfactuals do not. Flag sandwiched trades (Xi-Moallemi's bracketing heuristic or ZeroMEV labels) and report cost with and without. Do **not** condition naively on submission channel: 37.2% of sandwich victims migrate to private RPC within 60 days (Mancino & Rezzoli), so channel is an endogenously selected treatment, not a control.

**Intent venues need separate treatment.** CoW/UniswapX/1inch Fusion settlements may be **internalised against solver inventory or filled via RFQ**, in which case no AMM counterfactual describes the user's alternative. Cite Canidio & Fritsch (AFT 2023) for why batch venues are a structurally different cost regime, and Chitra-Kulkarni-Pai-Diamandis (arXiv 2403.02525) to block the assumption that solver competition passes value through — more solver entry can *reduce* welfare.

## 5. Contradictions with `docs/research-workflow.md` §4.0–4.2

Seven, ordered by how much they change the plan.

**C1 — §4.0 final bullet and §4.1(1) are published prior art (fatal to the result as stated).** "The entry contract in each transaction identifies the aggregator, so routing decisions can be compared across aggregators for comparable pair, size, and block … the residual is integration scope and heuristics. That is … the sharpest available answer to the objection." This is Xi & Moallemi (2607.20762), including the architectural attribution. It is no longer a finding to establish; it is a fact to cite. **Fix:** rewrite §4.1(1) as the intermediary-asset / multi-hop margin on contested pairs, and cite the prior art as foundation.

**C2 — §4.0 "the entry contract … identifies the aggregator" is false, and contradicts our own sibling doc.** `docs/router-identification-feasibility.md` already establishes that `sender` identifies the **executor, not the author of the routing decision** (Universal Router executes off-chain-computed calldata; any wallet or meta-aggregator can call it), and that the executor population fragments to 397 distinct senders by Oct 2025 with a hand registry capturing 11.8%. The literature corroborates independently: Maury/ClearTrace (Zenodo 21513263) argues no standard on-chain mechanism announces frontend identity and offers four recovery heuristics (calldata-suffix trapper, proxy-router mismatch detector, multi-hop origin tracer, fee-recipient clustering); Xi & Moallemi's own labelling reaches only ~21% of transactions / 5.6% of volume on a single pair. **§4.0 is stale relative to §feasibility and must be brought into line before it propagates into the paper.**

**C3 — §4.2 makes the cross-aggregator design the answer to endogeneity. It cannot be.** "Does an asset become the vehicle because execution costs are low, or are costs low because vehicle liquidity accumulated? … the cross-aggregator and cross-venue-spillover designs are how." A cross-section of routers at one instant contains no variation in incumbency holding cost fixed; it addresses a different question entirely, and it is now taken. **Fix:** re-base the endogeneity answer on cost-dominance windows plus cross-venue spillover, and drop the cross-aggregator leg from that sentence.

**C4 — §4.2 treats structural breaks purely as nuisances; they are the identifying variation.** "Structural breaks handled explicitly: the Merge, L2 migration, the USDC depeg, EIP-4844. Pooling across these … corrupts panel estimators." True as stated, but the inertia literature's decisive gap is the absence of any window where an incumbent is strictly cost-dominated while incumbent — and gas-regime shifts, fee-tier changes, version migrations and the depeg are exactly those windows. **Promote them from regime controls to the identification spine.** This is the most consequential constructive contradiction in the set.

**C5 — §4.2's depth definition is not automatically comparable across designs.** "Dollars required to move the marginal price by 10 bps and 50 bps, computed per venue against its own invariant and then aggregated." Not summing reserves is correct. But **marginal-price displacement and realised average execution cost stand in a design-dependent relation**: in constant product the marginal price moves roughly twice as far as the average execution price for small trades; stableswap (flat then sharply convex) and concentrated liquidity (piecewise, tick-dependent) have different ratios entirely, and a v3 pool can show large marginal depth while a trade exiting the active range costs far more. "Then aggregated" is also under-specified — the economically correct aggregation across heterogeneous pools is the joint split optimisation (FVO), not addition of per-venue depth numbers. **Fix:** make realised all-in cost at fixed notionals (Barbon-Ranaldo) the primary metric; keep marginal-price 10/50 bps depth as a secondary structural descriptor with the divergence documented.

**C6 — §4.1(5) says a centrality curse "would be surprising." It would not.** It is predicted by the LVR formula (σ² × marginal depth) and by Yuan (2005), already in our corpus, and it is already visible in Fritsch & Canidio's hub-vs-spoke coverage split and Heimbach et al.'s <30% figure. Framing it as surprising invites a referee to supply the mechanism we should have supplied. **Also reconsider the demotion:** §4.1(5) is kept "supporting rather than headline," but with C1 removing the planned second headline, rent incidence is now the strongest *unoccupied* empirical slot, and it carries a real methodological advantage — nobody but Cartea/Drissi/Monga has netted gas, and only for one pool.

**C7 — §4.1(2)'s design is the FX literature's exhausted design.** "Does lagged vehicle-linked liquidity predict current liquidity after current relative returns to provision are controlled for? … a lagged-share coefficient of 0.363 … is the object of interest." That is a lagged dependent variable with fundamentals controls — the Chinn-Frankel specification whose coefficient CEM and CFI show cannot separate switching costs from a serially correlated unobserved fundamental. Reporting 0.363 as "incumbency" reproduces the exact interpretive error the paper's contribution is supposed to overcome. **Fix:** this result is licensed only when paired with direct contemporaneous cost measurement as a regressor *and* cost-dominance windows; on its own it is a better-measured version of a known non-identification.

Also note for §4.2's completeness: the split treatment must be symmetric (comparing an unsplit best-single-pool direct route against a realised aggregator-split vehicle route is not like-for-like; Xi-Moallemi price the split gap at 2.02 bps mean / $24m on one pair), daily state must be replaced by transaction-time state or the wedge reported as a first-order magnitude, and the Curve/Fluid exclusion must be **signed** (under FVO logic an omitted venue mechanically flatters whichever route depends on covered venues) rather than merely share-quantified.

---

# Lane reports


## prior-art-cross-aggregator

## Bottom line

The idea is **half-taken, and the taken half is the half you described.** One paper published three weeks before this brief does steps 1 and 2 of your design — identify the router from the entry contract, compare across routers, attribute the residual to architecture. What it explicitly does *not* do is the intermediary-asset margin, which is your actual topic. Reframe onto that and you survive; state the claim as written and a referee hands you the paper.

---

## (1) Has anyone published this comparison?

**Yes — [Quantifying Sub-Optimality in Routing for Automated Market Makers](https://arxiv.org/abs/2607.20762), Weiye Xi & Ciamac C. Moallemi, arXiv 2607.20762, submitted 22 July 2026.** This is the redundancy risk. Verified from the full HTML (arxiv.org/html/2607.20762v1):

- **Sample:** 2.98M WETH-USDC swaps, Ethereum mainnet, blocks 19,500,000–23,000,000 (Mar 2024–Jul 2025), $120.42bn input volume.
- **Router identification — your step 1, already done:** "we also label trades executed by five widely used routing contracts: Uniswap Universal Router, CoWSwap, 1inch v4, 1inch v5, and Odos v2. Labels are assigned by destination contract address." Labelled flow: Universal Router 456,046 txs / $3.37bn; 1inch v5 77,769 / $383m; 1inch v4 47,812 / $1.82bn; CoWSwap 41,901 / $985m; Odos v2 3,332 / $128m (~21% of txs, 5.6% of volume).
- **Cross-router comparison — your step 2, already done:** three reproducible optimal benchmarks (Support-Constrained Optimum; Full-Venue Optimum; Gas-Aware FVO), mean shortfall 2.02 bps / ~$24m aggregate. Per-router: CoWSwap has the lowest medians and tightest dispersion on all three benchmarks; Universal Router and Odos v2 the highest medians and widest IQRs; 1inch v4/v5 intermediate. Sandwich exposure by router: Universal Router 0.215% of txs / 6.12% of volume; 1inch v4 1.56% / 7.93%; Odos v2 3.54% / 6.34%; CoWSwap 0.00233% / 0.00458%.
- **Your conclusion, already stated:** "Differences across routers in our staleness experiments are consistent with institutional features, e.g., solver-mediated batch auctions and private order flow in CoW Protocol that can mitigate within-block state sensitivity." That is your "residual reflects each router's integrated venue set and heuristics," in print.

**What remains open in it — and this is your opening.** The paper's own limitations section: "We restrict attention to a single token pair on L1 and to same-pair pools, abstract from multi-hop routes and cross-domain execution, and model gas activation as a fixed per-call cost," and in the setup, "we restrict attention to a simplified same-token setting... we do not allow trading through other intermediate tokens when routing." Stated future work explicitly names extending to multi-hop routing. It also does **not** do same-block head-to-head matching between routers — each router is measured against a counterfactual optimum, never against another router on a matched trade.

So: **intermediary-asset choice is untouched, multi-hop is untouched, and matched-trade cross-router comparison is untouched.**

## (2) Has anyone documented that aggregators route differently for equivalent trades, or measured routing suboptimality?

Repeatedly. This is a crowded, mostly-industry-adjacent measurement space:

- **[Quantifying Price Improvement in Order Flow Auctions](https://arxiv.org/abs/2405.00537), Bachu, Wan & Moallemi, arXiv 2405.00537 (May 2024), also published by Uniswap Labs as [Measuring Price Improvement with Order Flow Auctions](https://blog.uniswap.org/measuring-price-improvement-with-order-flow-auctions).** Interface-level cross-router comparison: ~4.6 bps price improvement for Uniswap-interface users vs ~4.3 bps for 1inch-interface users; UniswapX and 1inch Fusion show significant improvement while 1inch Aggregator and Uniswap Classic do not; 1inch Aggregator carries 0.5–1 bps of gas-overhead degradation vs Uniswap Classic. Decomposes improvement into routing efficiency, gas optimisation, priority fees. This is the interface-level version of your test, published two years ago, by an author who is also on the 2026 router-level paper. Note the authorship overlap — Moallemi has now covered both the interface and the router-contract cut.
- **[Execution Welfare Across Solver-based DEXes](https://arxiv.org/abs/2503.00738), arXiv 2503.00738 (Mar 2025).** CoWSwap vs 1inch Fusion vs UniswapX, benchmarked against Uniswap V2/V3 routing, on USDC-WETH (short-tail) and PEPE-WETH (long-tail). Attributes execution-quality dispersion to "solver market structure, variations in liquidity profile and inventory depth among solvers" — again your residual-explanation, though on solver inventory rather than venue set. Does not examine route composition or intermediary tokens.
- **[Multi-Path Routing in Decentralized Exchange Networks: Convex Allocation and an Improving-Path Certificate](https://arxiv.org/abs/2607.22540), Ilia Zhavoronkov, arXiv 2607.22540 (Apr 2026).** Benchmarks an own router against four production DEX aggregators on WETH-USDT across six trade sizes: median shortfall <5 bps, top-3 quote rank >57% of epochs. Cross-aggregator quote comparison at matched instants — but engineering benchmark, single pair, aggregators unnamed in the abstract.
- **[Measuring DEX Efficiency and The Effect of an Enhanced Routing Method](https://arxiv.org/abs/2508.03217), Yu Zhang & Claudio Tessone (Aug 2025)** and the follow-on **[Extensions of a Line-Graph-Based Method for Token Routing in Decentralized Exchanges](https://arxiv.org/abs/2509.20851)** (Sept 2025, ID inferred from the arXiv listing — verify before citing). Documents "suboptimal trades where alternative routing paths could yield more target tokens," generalises to a multi-DEX aggregator setting, introduces a STAP efficiency metric. Algorithmic, not a cross-aggregator economic comparison.
- **[Advancing DeFi Analytics: Efficiency Analysis with Decentralized Exchanges Comparison Service](https://arxiv.org/abs/2411.01950), Onishchuk, Dubovitskii & Horch, arXiv 2411.01950 (Nov 2024).** Built by **1inch Analytics** — ~1.2M transactions, multi-chain, simulation-based cross-aggregator swap-rate comparison, concludes 1inch Classic and Fusion outperform competitors. Interested party; useful only as evidence that the horse-race framing is already commercial table stakes.
- **Industry, and the most under-appreciated threat to your methodology: [Cross-Frontend Attribution Methodologies in Decentralized Exchange Volume](https://doi.org/10.5281/zenodo.21513263), Andrew Maury (ClearTrace), Zenodo 21513263 (2026).** Explicitly argues that "the same underlying trade-execution infrastructure exposes no standard mechanism by which a frontend — a wallet-native swap widget, an aggregator, an institutional smart contract, a meta-router — announces its own identity on-chain," and offers four heuristics for recovering origin: calldata-suffix trapper, proxy-router mismatch detector, multi-hop origin tracer, fee-recipient clustering. Plus a VWAP-oracle execution-quality layer kept separate from an MEV-exposure score, across Ethereum/Base/Arbitrum/Optimism, and a documented case of order-size-dependent quote degradation at a major aggregator. **Read this before you write your identification section.** Your "identify the aggregator from the entry contract" step is the naive version of what this paper shows to be insufficient — meta-routers and proxy routing break entry-contract labelling, and a referee who knows this literature will ask.
- **[Incentives and Market Structure in Intent-Based Exchanges: Evidence from a Solver-Reward Reform](https://arxiv.org/abs/2607.21955), Ruiyang Zhang, arXiv 2607.21955 (July 2026).** CoW Protocol CIP-74 (8 Dec 2025) as a governance-dated natural experiment; solver HHI and share shifts by order size, with UniswapX as an unaffected control. This is the "aggregator market structure" slot, already occupied with a cleaner identification design than a cross-sectional routing comparison offers.
- **[Private MEV Protection RPCs: Benchmark Study](https://arxiv.org/abs/2505.19708), Janicot & Vinyas, CoW DAO Research (May 2025)** (arXiv ID inferred from listing metadata — verify). Finds ~80% private-RPC usage and that "not all RPCs OFAs produce the same outcomes." Covers your RFQ/private-orderflow branch.
- **Unverified:** an independent analyst ("Vaish") study of 554,137 MetaMask swaps over 99 days / $567.8m, reporting Uniswap API winning 52.4% of routing decisions with median slippage 0.21–0.88 bps vs 1–27 bps for OKX, Kyber, 1inch v6 and 0x, covered by [Blockonomi](https://blockonomi.com/uniswap-api-captures-over-half-of-metamask-swaps-on-ethereum-mainnet/). **I could not locate the primary report** and cannot confirm whether it compares quotes for identical trades simultaneously. Flagging it because MetaMask's multi-aggregator quote solicitation is structurally the cleanest natural experiment for your question that exists — if someone has already exploited it, that is a second redundancy risk you should chase down directly.

Nothing found in **Heimbach's** corpus touches aggregators or routing — I enumerated all 31 of her arXiv papers; the nearest are [An Empirical Study of Market Inefficiencies in Uniswap and SushiSwap](https://arxiv.org/abs/2203.07774) (30% of trades at unfavourable rates) and [Non-Atomic Arbitrage in Decentralized Finance](https://arxiv.org/abs/2401.01622). **Capponi & Jia** are on AMM liquidity provision ([RFS 38(10):3040](https://academic.oup.com/rfs/article-abstract/38/10/3040/8200845)), not routing. **Angeris/Diamandis/Chitra** is optimal-routing theory ([An Efficient Algorithm for Optimal Routing Through CFMMs](https://arxiv.org/abs/2302.04938)), no empirics. That branch of your prior-art worry is clear.

## (3) What is genuinely novel and remains

Four things, in descending order of defensibility:

1. **The intermediary-asset margin itself.** No paper found compares *which token a route hops through* across aggregators. Xi & Moallemi exclude it by assumption. Zhavoronkov and Execution Welfare are single-pair. The network papers that do study intermediary tokens — [Network Analysis of Uniswap: Centralization and Fragility in the Decentralized Exchange Market](https://arxiv.org/abs/2503.07834) (Yan & Tessone, Mar 2025), which identifies important tokens and pools by betweenness, and [A Social Network Approach to Analyzing Token Properties and Abnormal Events in Decentralized Exchanges](https://arxiv.org/abs/2309.02579) (Mohammadi et al., 2023) — measure token centrality in the liquidity graph and never connect it to router choice. **The join between "which tokens are graph hubs" and "which routers select them" is empty.**
2. **Long-tail and cross-pair scope.** Every empirical paper found runs on WETH-USDC, WETH-USDT, or PEPE-WETH. Vehicle choice is mechanically uncontested on WETH-USDC; it is contested precisely on the pairs nobody has studied. Your comparable-pair design has real value only if it spans pairs where the intermediary is genuinely ambiguous.
3. **Matched-trade, same-block head-to-head.** Xi & Moallemi measure each router against a counterfactual optimum; nobody matches router A's trade to router B's comparable trade in the same block. This is a methodological contribution — but a modest one, and it needs the ClearTrace attribution caveats handled or it is fragile.
4. **The economic framing, which is your real differentiator.** Nothing found connects DEX routing-intermediary choice to the vehicle-currency literature. Searches for "vehicle currency" / "vehicle asset" plus DeFi routing returned zero. Somogyi (2026)'s price-impact-minimisation mechanism for vehicle-currency selection in FX has never been tested on DEX routing, and Krugman (1980)'s cost-driven vehicle selection has an exact on-chain analogue that is unexploited. Your `01_source_fidelity.md` already establishes that Somogyi explicitly disclaims crypto/DeFi and that Krugman's endogenous-cost loop is a static multiple-equilibrium result — that is a stated gap you are positioned to fill and the CS measurement literature has no interest in.

## (4) The paper that would make your version redundant

**Xi & Moallemi (2026), arXiv 2607.20762.** Blunt version: if your contribution is "we identify the aggregator from the entry contract, show routers choose differently for comparable trades, and argue the residual reflects router architecture," that is published, on a bigger sample, with three reproducible optimality benchmarks you would have to match, and with the architectural attribution (solver auctions, private orderflow) already stated in the text. A referee finds it in one search.

Secondary redundancy: **Bachu, Wan & Moallemi (2024)** owns the interface-level version, and **Ruiyang Zhang (2026)** owns aggregator market structure with a cleaner governance-dated design than a cross-section can offer.

**The survivable framing** is not "aggregators route differently, therefore cost doesn't explain it" — that is now a documented fact you cite rather than a finding you establish. It is: *given* that routers differ (cite Xi & Moallemi), does the divergence show up in **vehicle-asset selection** on pairs where the intermediary is contested, and does the pattern of intermediary choice map to each router's integrated venue set in a way the vehicle-currency mechanism predicts? That question is open, it is the one your project is actually about, and it uses the prior art as a foundation instead of colliding with it.

## What I could not verify

- **SSRN was not searchable.** ssrn.com returned HTTP 403 to direct fetch, and the session's web-search budget was exhausted (200/200) before I could route around it. **Finance-side working papers on SSRN are unchecked** — this is the largest hole in this review, and given the target venues it is the one most likely to hide a competitor. Someone should search SSRN manually for "DEX aggregator", "smart order routing" + crypto, and "aggregator competition" + decentralized.
- Semantic Scholar's API was rate-limited (429) on both WebFetch and curl; OpenAlex was usable but its full-text search is too noisy for this topic (2,796 hits, mostly dextran chemistry).
- The MetaMask/Vaish study's primary source — untraced, only secondary press coverage.
- Uniswap Labs' 2026 "Uniroute" router-comparison claims and the ClearTrace leaderboard methodology beyond the Zenodo abstract; the Uniswap research index lists only two relevant posts, both from 2023–2024.
- ACM DL blocked fetching for **ORDER: Optimal Routing with Path Indexing in Exchange Graph** ([doi 10.1145/3802097](https://dl.acm.org/doi/10.1145/3802097), Proc. ACM Management of Data). From its title and venue it is a database/indexing systems paper, not an economic comparison, but I could not read the abstract to confirm.
- Two arXiv IDs above (Zhang & Tessone Sept 2025; Janicot & Vinyas May 2025) are inferred from listing metadata rather than read off the abstract pages — verify before they enter a reference list.

Relevant local files: `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/00_manifest.md`, `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/01_source_fidelity.md`. Neither contains any of the routing/aggregator literature above — this is a wholly new branch relative to the existing corpus, which is FX/microstructure/LP-side and has no aggregator coverage at all.

---

## inertia-hysteresis

## Literature review: inertia and hysteresis in international currency dominance

**Scope note.** The repo's `01_source_fidelity.md` already carries cross-checked reads of Krugman (1980), Dowd & Greenaway (1993), and Gopinath & Stein (2021). I do not re-derive those; I extend them only where the *identification* question is concerned. Everything else below is new to the corpus — I confirmed none of Eichengreen, Flandreau, Chinn/Frankel, Rey, Devereux/Shi, Goldberg/Tille, or Ilzetzki/Reinhart/Rogoff is present in `literature/papers/` or `00_manifest.md`. A verification ledger (what I read in full vs. abstract-only) is at the end; please read it before quoting anything.

---

## 1. The debate is not "persistence, yes or no" — it has two camps that talk past each other

The framing that would be easiest to write, and that would be wrong, is "the literature says persistence is inertia, and we test it." The actual state is a split, and the split is not where you'd expect.

**Camp A — strong lock-in.** Krugman (1980), Dowd & Greenaway (1993), [Chinn & Frankel](https://www.nber.org/papers/w11510), [Goldberg & Tille](https://www.sciencedirect.com/science/article/abs/pii/S0022199608000664), [Devereux & Shi](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-2354.2012.00727.x), Gopinath & Stein, [Ilzetzki-Reinhart-Rogoff](https://www.nber.org/papers/w23134).

**Camp B — inertia is weaker than advertised.** [Eichengreen & Flandreau (2009)](https://www.nber.org/papers/w14154), [Eichengreen & Flandreau (2012)](https://ideas.repec.org/a/kap/openec/v23y2012i1p57-87.html), [Chiţu, Eichengreen & Mehl (2014)](https://www.nber.org/papers/w18097), [Flandreau & Jobst (2009)](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-0297.2009.02219.x).

**The load-bearing observation for your paper: Camp B's rhetoric and Camp B's own parameter estimates point in opposite directions.** Chiţu-Eichengreen-Mehl's abstract says "the advantages of incumbency are not all they are cracked up to be." Their own estimated persistence coefficient on the lagged currency share is **0.98 — a stated half-life of about 29 years, the highest persistence estimate anywhere in this literature**, and they note it is "similar in magnitude" to Chinn & Frankel's 0.90–0.96. The same paper that debunks incumbency measures the strongest incumbency in the field.

That is not authorial carelessness. It is a symptom: **Camp B is not actually testing inertia against fundamentals.** It is contesting (i) the *date* of a crossover and (ii) the *number* of currencies that can share the role at once. Both are important historiographic corrections, and neither identifies the parameter your paper wants. This distinction is the most useful thing I can hand you, and it is also the thing most likely to be caricatured if stated loosely.

---

## 2. Paper by paper

### Eichengreen & Flandreau (2009), [The Rise and Fall of the Dollar](https://www.nber.org/papers/w14154) — *European Review of Economic History* 13(3)

**Claim.** New archival estimates of interwar FX reserve composition show the dollar overtook sterling **in the mid-1920s**, not 1928/1938/1948 as Triffin and successors held; sterling then *regained* the lead after the 1933 dollar devaluation. Their inference: "Evidently inertia is less than sometimes supposed. Indeed, the status of dominant currency, once lost, was not lost forever." They further reject the winner-take-all premise: "A reasonable reading of the evidence is that sterling and the dollar shared reserve-currency status in the interwar period."

**Evidence.** Central-bank archival holdings covering ~80% of global FX reserves, 1920–1937, disaggregated by country and continent.

**Identification limitation — precisely.** Three layers, in ascending severity:

1. *Coverage sensitivity is conceded in the paper's own figure note*: "We suspect that actual estimates would be very influenced by which countries would be added. Having complete data for Brazil would raise the share of sterling; Data for Argentina might increase the US dollar's share." The headline crossover date rests on which archives survived.
2. *The inertia inference is entirely indirect.* Their logic is: crossover happened earlier than the narrative said → therefore the lag between fundamentals and currency status was shorter → therefore inertia is weaker. This requires an independent date for when US fundamentals overtook UK fundamentals. No such date is estimated. It is asserted from general economic history.
3. *Their own explanation of the key reversal concedes the identification problem.* They attribute sterling's 1930s recovery to "the politics of the sterling area" — an institutional fundamental. So the episode they read as evidence *against* lock-in is explained by an omitted, persistent, non-market fundamental. That is precisely the confound, appearing inside the paper that claims to dispose of it.

### Eichengreen & Flandreau (2012), [The Federal Reserve, the Bank of England, and the Rise of the Dollar](https://ideas.repec.org/a/kap/openec/v23y2012i1p57-87.html) — *Open Economies Review* 23(1); BIS conference version [here](https://www.bis.org/events/conf100624/eichengreenflandreaupaper.pdf)

**Claim.** The dollar rivalled and surpassed sterling in **bankers'/trade acceptances** in the 1920s, from a standing start (dollar acceptances were "virtually unknown as recently as 1914"). "The popular image of strongly increasing returns and pervasive network externalities leaving room for only one monetary technology is misleading."

**Why this is the most methodologically interesting paper of the set.** They lay out three explicitly competing hypotheses for the 1920s — (a) network effects strong enough that London keeps first-mover advantage even if an alternative is more efficient for the world; (b) network effects strong but a large player (the Fed as "market maker of last resort") can push the system between equilibria, "a policy analogous to 'big push'"; (c) increasing returns never strong enough for natural monopoly, so monopoly gave way to duopoly. **This is the correct decomposition of your research question.** They conclude for a mix of (b) and (c).

**Identification limitation — precisely.** The three hypotheses are adjudicated **narratively, not statistically**. The empirical work estimates that the US acceptance market "grew significantly faster than it would have in the absence of this official support," but the identifying variation — the Federal Reserve Act of 1913 (removing legal prohibitions *and* creating a discount facility), plus WWI's disruption of London — is a **bundle of simultaneous shocks to both the cost of using dollars and the incumbency configuration**, in a single time series with one treated unit. There is no design that moves incumbency while holding cost fixed, or vice versa. Their hypotheses (a), (b), (c) are consistent with the same observed path under different unobserved parameter values.

### Chiţu, Eichengreen & Mehl (2014), [When Did the Dollar Overtake Sterling? Evidence from the Bond Markets](https://www.nber.org/papers/w18097) — *Journal of Development Economics* 111

**Claim.** In foreign public debt denomination across 33 countries, 1914–1946, the dollar overtook sterling **as early as 1929**. "Financial market development appears to have been the main factor helping the dollar to surmount sterling's head start."

**Evidence.** Random-effects tobit on currency shares of foreign public debt; 66 country-currency groups; regressors are lagged share (inertia), relative GDP share (size), CPI inflation (credibility), and — the novel one — **bank assets/GDP (financial depth)**. Financial deepening is "by far the most important contributor" to the dollar's rise; US relative size actually contributed *negatively* (US share of world output fell 30%→22%, 1918–32).

**This is the paper that comes closest to confronting your exact problem, and it must be reported accurately.** They write, unprompted:

> "One could also argue that the interpretation of the lagged dependent variable in terms of inertia is problematic, insofar as the latter is simply picking up persistent error terms."

They then attempt to fix it two ways: **Griliches-Liviatan IV** (instrument the lagged share with its second lag and first lags of the regressors) and **Hatanaka**. Result: estimates "strikingly close" to baseline (0.90 under Griliches-Liviatan vs. 0.98 baseline), concluding "we are picking up genuine inertia effects and not merely persistence in the error term."

**Identification limitation — precisely, and this is the crux of your paper's warrant.** Their fix addresses a *narrower* problem than the one you care about, and the gap between the two is exactly your contribution:

- What the IV addresses: correlation between the lagged dependent variable and the **contemporaneous error**, i.e. autocorrelation bias in $\hat\rho$. A statistical nuisance.
- What the IV cannot address: whether $\rho$, even estimated perfectly, is a **switching cost** or a **serially correlated unobserved fundamental**. Lagged instruments purge $\hat\rho$ of error correlation; they do not construct a counterfactual in which incumbency is held fixed while cost advantage is removed. A persistent omitted fundamental is not an "error term" — it is a rival structural explanation, and it is observationally equivalent.
- **The paper contains its own strongest evidence for this.** When financial depth is added — a regressor they then show explains most of the *level* movement — "The point estimates for the persistence and credibility effects **remain unaltered**." A variable that dominates the level does not move $\hat\rho$ at all. So $\hat\rho$ is not "what's left after fundamentals"; it is measuring something the fundamentals never compete with. Adding better fundamentals does not shrink measured inertia. That is the identification failure in one line, and it is *in the data of the paper that claims to have handled it*.
- Two further fragilities: the 1929 crossover date holds only "when excluding the Commonwealth countries" (a sterling-inclined subsample); and panel logit was attempted but "convergence of the likelihood function to a global maximum was not obtained."

### Chinn & Frankel (2007), [Will the Euro Eventually Surpass the Dollar?](https://www.nber.org/papers/w11510) — in *G7 Current Account Imbalances* (ed. Clarida, Univ. Chicago Press)

**Claim.** Three-part structure, stated cleanly: determinants (size, credibility, financial depth); **nonlinearity/tipping** ("if one currency were to draw even and surpass another, the derivative… would be higher in that range"); and **inertia** ("In the chronological sense, however, the switch happens slowly… Thus inertia is great"). Their headline conditional forecast — euro possibly surpassing the dollar by ~2022 — required UK EMU accession and sustained dollar depreciation; neither occurred.

**Evidence.** Panel of reserve currency shares, 1973–1998, logistic-transformed ($\log(s/(1-s))$, chosen precisely to admit a tipping point at $s=0.5$), with a lagged endogenous variable. Adjustment: 4–10%/yr linear (half-life ~17 years), ~12%/yr logistic.

**Identification limitation — and they say it themselves, with unusual candour.** "Inertia" *is* the lagged-dependent-variable coefficient, by construction and by their own definition ("estimate the extent of inertia, which we will represent by means of a lagged endogenous variable"). Their own caveats:

> "One cannot be confident that any given data set will contain enough information to answer the questions of interest."

> "A good deal of work is being done by the lagged endogenous variable."

> "We are not calling these robustness checks, because we do not have the luxury of sufficient data to expect robust results, or even to dispense with *a priori* judgments in our basic specification."

That last sentence is remarkable and worth quoting in your paper. It is an author-declared statement that the design cannot separate the hypotheses. Note also the structural constraint: shares must sum to one, so the cross-section of ~5 currencies is not independent (they acknowledge the cross-equation error correlation and report SUR gives similar results).

### Chinn, Frankel & Ito (2024), [The dollar versus the euro as international reserve currencies](https://www.sciencedirect.com/science/article/abs/pii/S0261560624001104) — *JIMF* 146:103123

**The single most useful citation you can make, because it is this literature's own verdict on its own data.** Extending the design to 1999–2022 (USD, EUR, JPY, GBP, CNY), they find:

- $\hat\rho = 0.968$, while **GDP share, inflation, exchange-rate volatility and turnover all take "unanticipated signs."** The fundamentals become perverse; the lag absorbs everything.
- "Estimating a panel while imposing the same value on the autoregressive coefficient across currencies results in an estimate that is **not easily distinguished from unity**."
- And the concession: *"it makes sense to conclude that we have hit the limits of what aggregate foreign reserves data can tell us."*

Their response is to disaggregate to individual central banks (Ito-McCauley data, 56 central banks, 903 obs), which buys real cross-sectional variation — bilateral trade share, bilateral peg, UN voting distance, sanctions. Persistence remains 0.89–0.92 (6–7 year half-lives). Financial-market size, the fundamental most likely to be the true continuing cost advantage, is the one they "find little evidence of," because their only proxy is FX turnover by location.

**Identification limitation — precisely.** At $\rho \to 1$ the model is observationally a random walk: the level is determined by history alone, and $\beta$ is identified off a vanishing amount of mean-reverting variation. "Inertia" and "a random walk in unobserved fundamentals" are the *same reduced form*. Disaggregating to central banks fixes the degrees-of-freedom problem (layer 3 below) but not the confound (layer 1), because the cost-of-use fundamental is still proxied rather than measured.

### Rey (2001), [International Trade and Currency Exchange](https://academic.oup.com/restud/article-abstract/68/2/443/1523216) — *RESTUD* 68(2):443–464

**Claim (from the verified abstract).** A three-country GE model linking real trade patterns to currency-exchange structure with FX transaction costs. **Strategic complementarities generate multiple equilibrium currency structures for a given trade pattern**; bilateral trade links are the key parameters determining which equilibria exist; the equilibrium selected affects world output. The mechanism is "thick market externalities" — the self-reinforcing effect on transaction costs of using a given unit.

**Evidence.** None — pure theory, no data.

**Identification limitation.** Not applicable in the usual sense; the limitation is that Rey supplies the *multiplicity* that makes hysteresis possible without supplying any selection or transition dynamics. As with Krugman, the persistence claim is a property of the equilibrium set, not a derived path. **Its contribution to the identification problem is negative**: by establishing that trade patterns pin down the *set* of equilibria but not the *selection*, Rey implies that observed currency shares are not a function of fundamentals alone — which is exactly why a fundamentals regression cannot be interpreted structurally.

⚠️ **I could not obtain Rey's full text** (paywalled at OUP; the open-access candidates I tried returned an Internet Archive banner page). The above rests on the RePEc-verified abstract plus three independent characterisations by authors who engage it directly: Goldberg & Tille ("confirming the importance of a currency's 'thick market externalities' arising from a large presence in global international trade and low transaction costs"), Devereux & Shi ("examines how increasing returns to scale technologies in financial markets may give rise to an international currency"), and Chiţu-Eichengreen-Mehl ("looked at the emergence of multiple equilibria determined by network externalities and international trade patterns"). **Do not attribute specific propositions, comparative statics, or transition results to Rey without reading the paper.**

### Devereux & Shi (2013), [Vehicle Currency](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-2354.2012.00727.x) — *International Economic Review* 54(1):97–133 (working version [here](https://www.economics.utoronto.ca/public/workingPapers/tecipa-315.pdf))

**Claim.** Dynamic GE model of a vehicle currency with $N \geq 3$ countries and explicit trading posts. A vehicle currency economises on trading posts by $(N/2-1)(N-1)$, yielding large aggregate welfare gains — but gains are **asymmetrically weighted to residents of the vehicle-currency country**, and peripheral countries may lose. Three determinants: number of currencies, size of the vehicle economy, and the vehicle issuer's monetary policy.

**Two things here matter specifically for your paper.**

1. **Their sustainability analysis is the closest existing theoretical object to your testable question.** "Because the model combines fixed costs and 'network externalities', there are many Nash equilibria… In order to explore the robustness of a vehicle currency equilibrium we investigate the incentives for deviation by **aggregate groups of agents**." They derive a three-way trade-off between vehicle-country inflation, size, and $N$ that determines how much abuse an incumbent vehicle can sustain before coalitional defection. **That is your paper's proposition, in a model.** They also show a peripheral currency union (the euro) tightens the constraint on the incumbent — by cutting $N$ *and* raising peripheral size simultaneously.
2. **They explicitly warn that "vehicle currency" means two different things**, and this discipline should carry into your paper: "Goldberg and Tille (2005) use the term 'vehicle currency' to refer to a situation where a firm may set a price for sale to a foreign customer in the currency of a third currency. **This is quite different from the sense in which we use the term.**" The Krugman/Rey/Devereux-Shi sense is the **FX medium of exchange / routing** sense — which currency you route *through*. The Goldberg-Tille/Gopinath-Stein sense is **invoicing / unit of account** — which currency a price is *quoted* in. A DEX router is the first. Your paper should claim the routing literature and explicitly decline to settle the invoicing debate.

**Identification limitation.** Pure theory, calibrated, no estimation. Welfare numbers are calibration outputs, highly sensitive to the assumed FX transaction cost $\varphi$ (they show results at $\varphi = 0.0005$ and $\varphi = 0.001$, citing Huang & Stoll 1998, with gains varying substantially). Not evidence about persistence; a supplier of the structure a test would need.

### Goldberg & Tille (2008), [Vehicle currency use in international trade](https://www.sciencedirect.com/science/article/abs/pii/S0022199608000664) — *JIE* 76(2):177–192 (FRBNY Staff Report 200 version read in full)

**Claim.** Invoicing-currency choice is driven by a **"coalescing" (herding)** motive — exporters minimise price movements relative to competitors — set against a **hedging** motive against macro volatility. Industry structure beats macro performance: "producers in industries with high demand elasticities are more likely… to display herding." Dollar dominance is "largely attributable to international trade in reference-priced goods and goods traded on organized exchanges."

**The key theoretical result for hysteresis** is sharper than the abstract suggests: "The degree of macroeconomic volatility needed to disturb an invoicing status quo for more homogeneous products would need to be **exceptionally large**. This result supports the inertia and thick market externalities argued by Krugman and by Rey." This is a *modelled* threshold for how large a shock must be to dislodge an incumbent — a genuine hysteresis-band result, and closer to a testable object than anything in Krugman.

**Evidence.** 24 countries' invoicing shares; panel regressions of invoicing on trade shares, walrasian-good shares, and demand volatility.

**Identification limitation — precisely.** Hysteresis is inferred as a **residual**. Their own description: they relate "the invoicing unexplained by trade with the U.S. or walrasian exports to the volatility of aggregate demand." The conclusion is drawn from an *absence* — that invoicing "does not primarily depend on the exchange rate between the dollar and other partner currencies" — and the unexplained portion is then labelled "industry herding and hysteresis." Any persistent unmeasured cost of non-dollar invoicing (correspondent-banking access, hedging-instrument availability, contract-law convention, clearing infrastructure) sits in that same residual and is indistinguishable from herding. The paper also concedes it cannot see firms: the data lack "identifiers on specific exporters or importers," so within-firm persistence — the level at which a switching cost actually operates — is unobservable. The 2016 successor, [Micro, macro, and strategic forces in international trade invoicing](https://www.newyorkfed.org/medialibrary/media/research/economists/goldberg/GoldbergTilleSeptember222014JIE.pdf) (*JIE* 102), goes to transaction-level Canadian customs data and finds transaction size and importer-size heterogeneity matter — but notes "an unfortunate limitation of the database is the absence of individual identifiers," so the firm-level switching-cost question remains open there too.

### Gopinath & Stein (2021), *QJE* — extension only

`01_source_fidelity.md` already establishes the mechanism, the multiplicity/stability result, and the citation boundaries (reserves → 2018b; invoicing facts → Gopinath 2015; vehicle/medium-of-exchange role explicitly set aside). Two points to add, both bearing only on identification:

1. The existing note that "the model is symmetric between US and Europe by construction, so it cannot pin down *which* currency wins on fundamentals; the paper's history/incumbency argument is a verbal/heuristic selection device, not a proven result" **is the identification limitation**, stated at the level of theory. A model that is symmetric in fundamentals and resolves selection by appeal to history has, by construction, no fundamentals-based prediction to test persistence against.
2. Because the paper explicitly sets aside the medium-of-exchange/vehicle role (footnote 5), **it is not a competitor to your paper's object** and should not be framed as one. It is the strongest available statement of *why* the confound in §3 layer (4) exists — invoicing dominance and safe-asset/banking dominance are mutually reinforcing, so the incumbent's cost advantage is an equilibrium output of its incumbency.

### Ilzetzki, Reinhart & Rogoff (2019), [Exchange Arrangements Entering the 21st Century: Which Anchor Will Hold?](https://www.nber.org/papers/w23134) — *QJE* 134(2)

**Claim — and it runs directly against Camp B.** A new de facto classification of **anchor/reference currencies** for 194 countries, 1946–2016. "The US dollar scores (by a wide margin) as the world's dominant anchor currency and, by some metrics, its use is far wider today than 70 years ago." The euro "appears to have stalled" and by some metrics has declined. They stress this is a **revealed-preference summary statistic**: "That so much of the world chooses the dollar as its anchor/reference currency underscores the broad importance of the dollar across global markets" — and they argue the corroborating evidence others use (dollar funding, Fed spillovers, dollar invoicing) is "all partial and indirect."

**Why this is the strongest raw pattern in your favour.** Dollar anchor share flat-to-rising across seven decades while the US share of world output fell substantially. That is persistence surviving a large, sustained, measured decline in the most-cited fundamental. Chiţu-Eichengreen-Mehl found the same sign for the interwar dollar (size contributed *negatively* to the dollar's rise). The companion, [Why is the euro punching below its weight?](https://www.nber.org/papers/w26760) (*Economic Policy*), attributes the euro's flat trajectory principally to "the comparatively scarce supply of (safe) euro-denominated assets" — i.e. a *fundamentals* explanation for what looks like dollar inertia.

**Identification limitation — precisely, and this one requires care to state fairly.** Two distinct issues:

1. **The series is descriptive; no horse race is run.** IRR estimate no model of anchor choice on fundamentals. The persistence is displayed, not decomposed. The inference "dominance persists beyond fundamentals" is the reader's, drawn by eyeballing dollar share against US GDP share — and IRR's own euro paper shows how a fundamentals story (safe-asset supply) can absorb the same pattern.
2. **Persistence is partly an input to the measurement, not purely an output — but mildly, and I want to be exact about the degree.** Their classification algorithm invokes inertia as a methodological aid: "It is also the case that there is considerable inertia and path dependence in the choice of anchor currency. Switches of anchor currencies are far more infrequent than changes and revisions to the degree of exchange rate flexibility." And for the residual ambiguous cases, the most recent anchor is used as a tie-breaker. **The honest characterisation is: this affects 11 unclassified episodes out of 194 countries × 70 years, plus general guidance to the process of elimination — a mild prior, not a fatal circularity.** Do not overstate this into "IRR assumed their own conclusion." The defensible version: a de facto anchor classification built partly on the premise that anchors rarely switch is not a fully independent measurement of how rarely anchors switch, and the measured persistence should be read as an upper bound.

### Flandreau & Jobst (2009), [The Empirics of International Currencies: Network Externalities, History and Persistence](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-0297.2009.02219.x) — *Economic Journal* 119(537):643–664

**This is the paper that has come closest to claiming a resolution, and it is the one you must engage most carefully.**

**Claim (verified abstract, twice, consistently).** Using a new late-nineteenth-century database from the era of sterling dominance, they "provide evidence in favour of the search-theoretic models to international currencies" and support strategic externalities via a microeconomic model of currency choice. They "find strong confirmation of the existence of persistence, **but reject the view that the international monetary system was subject to pure path dependency and lock-in effects**, suggesting that, even in the absence of WWI, the USD was bound to overtake sterling."

**Method, per Eichengreen & Flandreau's own detailed account** (Flandreau is a co-author of both, so this is close to first-party): "The authors construct a model of the pre-1914 international monetary system that allows for strategic externalities. Currencies are traded abroad as a function of their value for users. Value is greater when currencies are liquid. This encourages more users to hold liquid currencies and generates positive feedback. **Persistence emerges when the feedback loop is sufficiently powerful.** Flandreau and Jobst estimate this model using pre-1914 data and reject the presence of strong lock-in effects."

**Why this is a genuine methodological advance over the Chinn-Frankel design, and what it still cannot do.**

*The advance is real and is worth conceding fully in your paper.* Flandreau & Jobst do not read inertia off a lagged dependent variable in a 5-currency time series. They **structurally estimate the strength of the strategic externality** — the feedback-loop parameter — from a rich bilateral cross-section: which currencies were quoted in which financial centres, across dozens of centres and currencies (the network dataset underlying their [Ties that Divide](https://www.cambridge.org/core/journals/journal-of-economic-history/article/abs/ties-that-divide-a-network-analysis-of-the-international-monetary-system-18901910/FD74CCE2123EEE4B009E3D2D9D3478AD), *JEH* 2005). Because the feedback parameter is a *structural* object, they can ask a counterfactual question — is the loop strong enough for lock-in? — rather than an interpretive one. That is the right shape of answer.

*What it still cannot do,* and where your setting differs: their identification comes from cross-sectional variation in the *network configuration*, with liquidity/cost entering as a modelled function rather than a directly observed price. The counterfactual is evaluated **inside the estimated model** — "would lock-in hold at the estimated parameter?" — so the answer inherits the model's functional form for how liquidity maps to user value. It is a structural rejection of strong lock-in, not a design-based one. No window is observed in which an incumbent currency is strictly cost-dominated and its network position is nonetheless held fixed.

⚠️ **I could not read Flandreau & Jobst (2009) in full.** OUP and Wiley are paywalled; CEPR DP5529 is behind Cloudflare (I was blocked); Academia.edu returned 403; Semantic Scholar reports no open-access PDF. **The above rests on the twice-verified abstract plus Eichengreen & Flandreau's (2012) first-party description and Chiţu-Eichengreen-Mehl's characterisation** ("find empirical evidence in favour of persistence in foreign exchange trading data for the late 19th century, but not in favour of pure path dependency and lock-in effects"). **Before your paper positions itself against this one — and it must, because this is the closest prior claim to resolution — someone needs to read it through institutional access.** I flag this as the single most important verification gap in this review.

---

## 3. The identification limitation, stated precisely

This is the section your paper's contribution rests on, so here it is as four distinct layers. They are usually conflated, and collapsing them is how the argument gets caricatured.

The empirical object throughout is a share $s_{ijt}$ (of reserves, bond denomination, invoicing, anchor choice). The canonical specification is a dynamic panel

$$z_{it} = \alpha + \rho\, z_{i,t-1} + X_{it}'\beta + u_{it}, \qquad z = \operatorname{logit}(s)$$

and "inertia" is read off $\hat\rho$.

**Layer 1 — $\hat\rho$ is residual persistence, not a structural switching cost.** $\rho$ absorbs the serial correlation of everything omitted from $X$. The fundamentals that plausibly constitute a *continuing cost advantage* — depth and liquidity of the issuer's markets, safe-asset supply, density of the peg network, hedging-instrument availability, correspondent-banking reach, legal/colonial convention — are all themselves highly persistent and either unmeasured or crudely proxied (Chinn-Frankel-Ito's only financial-depth proxy is FX turnover by location). A serially correlated fundamental and a switching cost imply *identical* $z$-dynamics. **This is not a hypothetical: Chiţu-Eichengreen-Mehl add financial depth, show it explains most of the level movement, and report $\hat\rho$ "remains unaltered" at 0.98.** Better fundamentals do not shrink measured inertia.

**Layer 2 — $\hat\rho$ sits at the unit root, where the interpretation is not merely biased but undefined.** Estimates: 0.90–0.96 (Chinn-Frankel, linear), ~0.88 logistic; 0.98 with a stated 29-year half-life (CEM); 0.919 then 0.968 (Chinn-Frankel-Ito), who state that imposing a common $\rho$ across currencies gives an estimate "not easily distinguished from unity." At $\rho \to 1$ the process is observationally a random walk: the level is history-determined and $\beta$ is identified off vanishing mean-reverting variation. "Inertia" and "a random walk in unobserved fundamentals" are the *same reduced form*. In the 1999–2022 sample this is visible as symptom: $\hat\rho = 0.968$ while GDP share, inflation, volatility and turnover all take "unanticipated signs."

**Layer 3 — there is not enough independent variation, even in principle.** ~4–6 currencies whose shares must sum to one (so the cross-section is not independent), over ~30–70 years, containing **one** transition event (sterling→dollar) and **one** non-event (the euro's failure). The literature says this itself: Chinn & Frankel, "One cannot be confident that any given data set will contain enough information to answer the questions of interest," and "we do not have the luxury of sufficient data to expect robust results, or even to dispense with *a priori* judgments"; Chinn-Frankel-Ito, "we have hit the limits of what aggregate foreign reserves data can tell us." Disaggregating to individual central banks (CFI 2024) or bilateral quotation networks (Flandreau & Jobst) relieves layer 3, and only layer 3.

**Layer 4 — the deepest, and the one to lead with: the counterfactual may not exist in FX.** Inertia and continuing cost advantage are not two separable causes of persistence, because **incumbency causally produces cost advantage.** Krugman's own endogenous-cost loop is this (volume → tighter spread → more volume). [Coppola, Krishnamurthy & Xu (2023)](https://ideas.repec.org/p/nbr/nberwo/30984.html) make it a policy channel: "once established, the dominant currency's host government invests more in financial market liquidity, further entrenching dominance." Gopinath & Stein make it a general-equilibrium complementarity. If the incumbent's cost advantage is an equilibrium *consequence* of incumbency, then "incumbency persisting after the cost advantage is gone" **is a state the FX system never visits** — there is no observable regime in which a currency retains its vehicle role while its execution costs are strictly worse than a rival's. You cannot condition on a counterfactual the data-generating process never produces.

**Why layer 4 must be stated carefully.** The FX literature's problem is not carelessness. CEM ran the correct IV for the problem they posed. CFI added the correct controls and then reported honestly that it did not work. Flandreau & Jobst went structural. The obstacle is that in FX data the incumbency and the cost advantage are **the same object measured once**. Any version of your argument that reads as "prior authors failed to control for costs" is both wrong and easily rebutted; the defensible version is "no FX dataset contains the state in which the two come apart."

---

## 4. Has anyone claimed to resolve it?

Four claims to resolution, in descending strength. None does what your setting proposes.

1. **Flandreau & Jobst (2009)** — the strongest, and the one to engage directly. Structurally estimates the strategic-externality parameter on a bilateral pre-1914 quotation network and **rejects strong lock-in** while confirming persistence. Limitation: the counterfactual is evaluated inside the estimated model, so it inherits the assumed mapping from liquidity to user value; cost is modelled, not observed. ⚠️ Not read in full — see the verification gap above.
2. **Chiţu, Eichengreen & Mehl (2014)** — explicitly poses the "lag may just be picking up persistent errors" objection and answers it with Griliches-Liviatan IV and Hatanaka. As argued in §2, this resolves *autocorrelation bias in $\hat\rho$*, a strictly narrower problem than inertia-vs-continuing-cost-advantage. Their own "financial depth leaves $\hat\rho$ unaltered" result is the best available demonstration that the wider problem survives their fix.
3. **[Bahaj & Reis, Jumpstarting an International Currency](https://ideas.repec.org/p/boe/boeewp/0874.html)** (BoE SWP 874, 2020) — the closest thing to a design-based answer. Theory: financing-currency and invoicing-currency choice are complementary, so policy that lowers the cost of working-capital credit in a currency abroad can seed international use. Empirics: the **38 PBoC swap lines, 2009–2018**, with signing dates as the source of variation; signing "is significantly associated with increases in the use of the RMB in payments to and from that country in the following months." **What it identifies: the elasticity of currency use to a cost shifter — i.e. that an incumbent's position is contestable by lowering rivals' costs. What it does not identify: the decomposition of observed persistence into inertia versus continuing cost advantage.** Note their own framing is associational ("significantly associated"), swap-line timing is plausibly but not verifiably exogenous, and it runs on a challenger currency, not an incumbent losing its cost edge. ⚠️ Abstract-level only; I did not read the paper. Also verify current publication status — RePEc showed working-paper versions only, which may be stale.
4. **[Eichengreen, Mehl & Chiţu, Mars or Mercury?](https://www.nber.org/papers/w24145)** (*Economic Policy*) — a "Mercury (economics) vs. Mars (geopolitics)" horse race on pre-WWI reserve composition for 19 countries, finding military alliances raise a currency's share in a partner's reserves by ~30pp. This is **adding an omitted variable to the same panel-with-LDV design**, not changing the identification. Its real relevance to you is as evidence *for* layer 1: a large, previously omitted, highly persistent determinant was found sitting inside what earlier work called inertia. ⚠️ Abstract-level only.

**Nothing I found claims, or achieves, a design in which an incumbent vehicle's cost advantage reverses while its incumbency is held fixed.** That is the open gap, and it is the precise gap your setting should claim.

---

## 5. What this implies for the on-chain claim (so it survives a referee)

Mapping your contribution onto the four layers, with the honest conditional attached:

- **Layer 1 (residualisation)** → broken by *direct, contemporaneous, per-route cost measurement*: realised AMM spread, gas, price impact. The continuing cost advantage becomes a measured regressor rather than the thing $\hat\rho$ absorbs. This is a real advance and the easiest to defend.
- **Layer 3 (degrees of freedom)** → broken by hundreds-to-thousands of pools and pairs, versus 4–6 currencies. Also defensible, though note Chinn-Frankel-Ito (56 central banks) and Flandreau & Jobst (bilateral network) already partially achieved this — claim improvement, not novelty.
- **Layer 2 (unit root)** → broken by high frequency: at block/hourly horizons $\rho$ is estimated far from unity, so persistence is a measurable rate rather than a non-stationarity.
- **Layer 4 (missing counterfactual)** → **this is the one that decides whether the paper is a genuine advance or just better measurement.** It requires exhibiting windows in which an incumbent route is *strictly cost-dominated* by a rival while its incumbency is intact: fee-tier changes, V2→V3→V4 migrations, gas-regime shifts, a rival pool becoming unambiguously cheaper on an executable all-in basis. **If such windows exist and are numerous, you have the state FX never provides, and the claim is strong. If they do not, the paper improves the cost measurement (layers 1–3) but does not overcome the identification limitation, and should say so.** I'd advise settling this empirically before the framing is written, because the whole positioning turns on it.

One scope discipline, from Devereux & Shi's warning: your setting speaks to the **routing / medium-of-exchange** sense of vehicle currency (Krugman, Rey, Devereux-Shi). It does **not** speak to **invoicing / unit of account** (Goldberg-Tille, Gopinath-Stein, and Gopinath & Stein's explicit footnote-5 exclusion of the vehicle role cuts both ways). Claim the first cleanly; decline the second explicitly. That declining will read as rigour, not weakness.

---

## 6. Verification ledger

**Read in full text (PDF extracted, quotes above are verbatim from the source):** Eichengreen & Flandreau (2009, NBER w14154, 31pp) · Eichengreen & Flandreau (2010 BIS conference version of the 2012 *OER* paper, 31pp) · Chiţu, Eichengreen & Mehl (NBER w18097, 42pp) · Chinn & Frankel (NBER w11510, 41pp) · Chinn, Frankel & Ito (2024 *JIMF* published version, 18pp) · Devereux & Shi (Toronto WP tecipa-315) · Goldberg & Tille (FRBNY Staff Report 200, the 2008 *JIE* precursor) · Goldberg & Tille (2014 revision = 2016 *JIE*, 60pp) · Ilzetzki, Reinhart & Rogoff (NBER w23134, 86pp).

Extracted text cached at `/private/tmp/claude-502/-Users-dsf-pro16-m3-glotl/d8c24615-d661-4ac9-899f-20596ce63759/scratchpad/lit/` — session-scoped, so copy anything you want to keep into the project repo.

**Abstract-verified only, NOT read in full — do not quote specifics:** Rey (2001) · Flandreau & Jobst (2009) ← *highest-priority gap; the paper closest to claiming resolution* · Bahaj & Reis (2020) · Coppola, Krishnamurthy & Xu (2023) · Eichengreen, Mehl & Chiţu (2017/2019).

**Could not verify:** exact pagination for Ilzetzki-Reinhart-Rogoff's *Economic Policy* euro paper (year reported inconsistently as 2020 vs. 2021 across sources — cite the NBER w26760 URL until checked). The Chiţu-Eichengreen-Mehl interwar **oil-markets** paper on homogeneous goods and network effects is relevant (homogeneous goods → strongest predicted network effects, which is Goldberg-Tille's mechanism tested historically) but **both RePEc and Wiley URLs I tried 404'd or paywalled, so I could not confirm its journal, volume or year — treat the citation as unverified.**

**Constraint on this pass:** the WebSearch budget (200 calls) was exhausted partway through, so later work ran on WebFetch against known/guessed URLs. Coverage of Camp B's most recent work may therefore be incomplete — in particular I did not systematically sweep 2024–2026 publications, so there may be a newer resolution claim I have not seen. A follow-up pass with search available should check that before the framing is locked.

---

## lvr-rents

## Literature review: AMM liquidity-provider economics

Scope note: this extends `output/nbc_pipeline/01_source_fidelity.md`, which already cross-checks Lehar & Parlour (JoF 2025), Klein/Kozhan/Viswanath-Natraj/Wang (2026), Caparros/Chaudhary/Klein (2024), Somogyi (2026) and Yuan (2005). None of the LVR / impermanent-loss / JIT / realised-LP-return literature appears in those notes, so this is new ground rather than a re-derivation. Where I read the actual PDF I say so; where I could only reach an abstract or a search summary I flag it.

---

### 1. What is actually established about positive net LP returns after LVR and gas

**Established.** For the handful of large, CEX-listed Uniswap pools anyone has measured, gross fee income is of the *same order* as adverse-selection losses, with the sign of the difference flipping across pool, version, fee tier and period. That is the whole of the consensus. Nothing stronger is established.

The specific findings, read from source:

- [Automated Market Making and Loss-Versus-Rebalancing](https://arxiv.org/abs/2208.06046) (Milionis, Moallemi, Roughgarden, Zhang; arXiv v5, 27 May 2024) is routinely mis-cited as showing LPs lose. Its own empirics show the opposite for its pool. On Uniswap v2 WETH-USDC, 1 Aug 2021 – 31 Jul 2022 (avg pool value $209m), raw pool P&L was **−6.20% annualised, Sharpe −0.15**, but delta-hedged P&L was **+5.04% (daily rebalancing) to +9.75% (hourly)**, with fees−LVR predicting +8.16%. Fees exceeded LVR. The authors explicitly hedge this: "this finding is specific to the setting we study here." The −6.20% is market risk, not LVR.
- [Measuring Arbitrage Losses and Profitability of AMM Liquidity](https://arxiv.org/abs/2404.05803) (Fritsch & Canidio, 2024) is the broadest measurement (Jan 2022 – Dec 2023, most-traded v2 and v3 pools). Fees fall short of arbitrage losses in **most of the largest v3 pools** — in WETH-USDC 5bp, fees run at roughly **80% of arbitrage losses**; WETH-USDT 5bp and WBTC-USDC 30bp roughly break even. But **less-traded pairs (LDO-ETH, LINK-ETH, MATIC-ETH, UNI-ETH) tend to over-cover, sometimes by ~50%**, and **v2 pools cover ~3× their arbitrage losses** in the second year of the sample.
- [Risks and Returns of Uniswap V3 Liquidity Providers](https://dl.acm.org/doi/10.1145/3558535.3559772) (Heimbach, Schertenleib, Wattenhofer, AFT'22) measures 6 pools (USDC-WETH and WBTC-WETH at 5/30bp, DAI-USDC at 1/5bp; May 2021 – Mar 2022) at **position level**. Verbatim: "the mean of each of the data series in Figure 14a is negative, thus, on average, liquidity providers lose money in comparison to holding the assets and are hence not compensated for the additional risk." Stable pools earn 0–0.04%/day with positive 5% CVaR; in the four volatile pools, **"less than 30% of the liquidity positions … are rewarded for the added risks they shoulder"** relative to stable pools.
- [Decentralized Finance and Automated Market Making: Predictable Loss and Optimal Liquidity Provision](https://epubs.siam.org/doi/10.1137/23M1602103) (Cartea, Drissi & Monga, SIAM J. Fin. Math. 15(3):931–959, 2024) is the only paper that both measures realised LP P&L *and* prices gas. On matched provide-then-withdraw pairs (5,156 LPs, ETH/USDC v3, 331,858 operations): position value **−1.64% per operation**, fee income **+0.155%**, total **≈ −1.49% per operation**, "includes transaction fees and excludes gas fees." Per minute: market total **−0.00067%** vs holding **−0.00016%**.
- [Impermanent Loss in Uniswap v3](https://arxiv.org/abs/2111.09192) (Loesch, Hindman, Richardson, Welch, 2021): 17 pools ≈ 43% of TVL from inception to Nov 2021 — **$199.3m fees against $260.1m impermanent loss, i.e. LPs $60.8m worse off than holding**. I could not extract this PDF's body text after four attempts, so I verified only the abstract-level figures. **The widely-repeated "49.5% of LPs had negative returns / about half would have been better off holding" figure I could not verify in the paper itself** — it circulates via secondary coverage (Rekt et al.) and should not be cited to Loesch et al. without a direct check.

**Not established, and this is the load-bearing gap for your paper: nobody has netted out gas.** The strings "gas" appears zero times in Heimbach/Schertenleib/Wattenhofer, zero times in Fritsch & Canidio, zero times in [Concentrated Liquidity in Automated Market Makers](https://arxiv.org/abs/2110.01368). Fritsch & Canidio state outright: "we do not consider blockchain transaction costs when determining profitable arbitrage opportunities." Only Cartea/Drissi/Monga quantify it: **$30.7 to provide, $24.5 to withdraw, $29.6 to take → $84.8 per reposition operation, implying their optimal strategy breaks even on average only above ~$1.8m of deposited wealth.** Because gas is a flat per-operation cost, "are LPs profitable after gas" has no scalar answer — it has a **size threshold**, and the threshold interacts with repositioning frequency (which is what Caparros/Chaudhary/Klein, already in your notes, causally identify off chain gas levels). Any claim in your paper about *net* returns has to carry a position-size distribution, not a mean.

Second not-established item: whether gross fee income measured at pool level is what a passive LP actually receives. [Just-in-time Liquidity on the Uniswap Protocol](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4382303) (Wan & Adams) counts only ~8,000 JIT transactions May 2021–Jul 2022, a fraction of a percent of v3 liquidity, concentrated on very large swaps because of fixed costs, with price improvement bounded above by 2× the pool fee rate. [Strategic Analysis of Just-In-Time Liquidity Provision in Concentrated Liquidity Market Makers](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2025.8) (Trotti et al., AFT 2025) reports JIT eroding average passive-LP profit by up to 44% *per trade* — I have this from a search summary, not the paper text, so treat the 44% as unverified. [The Paradox Of Just-in-Time Liquidity in Decentralized Exchanges](https://arxiv.org/abs/2311.18164) (Capponi, Jia & Zhu) gives the mechanism, purely theoretically: the JIT LP reads the mempool, so it serves only uninformed flow and *avoids* adverse selection, crowding out passive LPs when order volume is inelastic to depth — potentially lowering total liquidity. Net: JIT is small in aggregate but bites exactly where trade size is largest, which is exactly the hub pools.

Publication-status flag, given your manifest's discipline on this: the LVR paper, the fees-and-block-times follow-on, Fritsch & Canidio, Loesch et al. and Capponi/Jia/Zhu all show **no journal-ref** on arXiv as of my check. Cartea/Drissi/Monga (SIAM JFM) and Heimbach et al. (ACM AFT, DOI 10.1145/3558535.3559772) are the published anchors in this strand.

---

### 2. How LVR is measured in practice, and the measurement pitfalls

**The construct.** LVR is the loss of the pool versus a *rebalancing* portfolio holding exactly the pool's risky-asset position at every instant but trading at the external market price. The identity is `delta-hedged LP P&L = FEE − LVR`. For constant product, `LVR_t = ∫ (σ²_s/8) · V(P_s) ds`. Milionis et al. derive it in a frictionless continuous-time Black–Scholes setting: GBM under a risk-neutral measure, an infinitely deep zero-fee CEX with exogenous price, **passive LPs who never mint or burn**, continuously monitoring arbitrageurs who **pay no fees**, and — stated explicitly — "we assume away any blockchain transaction fees such as 'gas' fees, and also ignore the discrete-time nature of block updates."

**Two incompatible empirical implementations exist.** (a) *Plug-in*: measure realised σ² and pool value and evaluate the integral — Milionis et al. use Binance minutely closes sampled at 60-minute intervals. (b) *Simulation*: replay every Ethereum block, compare pool price to the CEX price, and execute the optimal fee-aware arbitrage trade whenever the gap exceeds the fee — Fritsch & Canidio's method, which never estimates σ². These are different estimators of different objects. **LVR magnitudes are not comparable across papers using (a) and (b).**

Pitfalls, ordered by how much they threaten your specific design:

1. **The reference-price requirement is a selection filter that is collinear with your treatment.** Every LVR measurement needs an off-chain price. Fritsch & Canidio "consider only Uniswap pools whose tokens are traded on Binance." That deletes precisely the long tail of tokens which exist on-chain *only* against WETH — i.e. the observations that identify the hub-role effect. Worse: for LDO/LINK/MATIC/UNI-ETH they **construct the Binance reference by chaining two USDT pairs**, so the vehicle-routing structure is *imposed on the benchmark* for exactly the non-hub pools. And USDC was not traded on Binance Sept 2022–Mar 2023 (BUSD auto-conversion), so USDT was substituted. Any hub-vs-spoke LVR comparison inherits all three artefacts.
2. **LVR is not a P&L; it is the Doob–Meyer compensator.** `FEE − LVR` answers "would a *delta-hedged* LP have made money." Milionis et al. state the hedge leg's costs — CEX spreads, trading fees, financing and borrow on the short — are all excluded, and only two one-off gas costs (mint, burn) are missing on the LP leg. Most real LPs do not hedge. For them the relevant number is the unhedged one, which in the LVR paper's own pool was −6.20% annualised and is dominated by market risk, not adverse selection.
3. **Impermanent loss and LVR are not interchangeable.** Milionis et al. show `E[IL] = E[LVR]` under the risk-neutral measure, but IL ("loss versus holding") is path-*in*dependent, depends on the LP's entry price so two LPs in the same pool over the same interval realise different IL, and is strictly noisier. They name Lehar et al. and Augustin et al. as papers whose IL-subtraction yields "at best, a much noisier measure." Practical consequence: Loesch et al. and both Heimbach papers benchmark against HODL/constant-mix (IL); Fritsch & Canidio and Cartea et al. benchmark against rebalancing (LVR/PL). **Splicing their headline numbers into one narrative is a category error.**
4. **The fee-adjusted no-arbitrage band matters and the baseline formula ignores it.** Baseline LVR assumes arbitrageurs pay nothing and prices are equalised continuously. [Automated Market Making and Arbitrage Profits in the Presence of Fees](https://arxiv.org/abs/2305.14604) (Milionis, Moallemi, Roughgarden; also in FC 2024, [Springer](https://link.springer.com/chapter/10.1007/978-3-031-78676-1_9)) adds fees and Poisson block arrival and shows low fees simply scale arbitrage profits down by the fraction of blocks presenting a profitable opportunity. Applying the raw σ²/8 formula to a 30bp pool **overstates** LVR — which biases fee-tier comparisons and therefore any hub-vs-spoke comparison, since hub pools sit at 5bp and spoke pools at 30bp.
5. **Discreteness.** Theory predicts arbitrage profits ∝ √(block interval); Fritsch & Canidio measure a log-log slope of **≈1/3 above 1s**, flatter below, and find 100ms blocks cut losses **20–70% depending on the pair**. So the continuous-time number is an upper bound whose tightness is pair-specific — i.e. the bias is not constant across your cross-section.
6. **Volatility-estimator sensitivity.** LVR scales in σ², so microstructure noise, jumps and sampling interval move the level first-order. Milionis et al. note ex-ante analysis wants implied vol and ex-post wants realised vol; nobody I read reports robustness across σ² estimators.
7. **Rebalancing-frequency convergence.** `FEE − LVR` matches measured hedged P&L only as rebalancing frequency rises (their Figure 6). For WETH-USDC, 4-hourly ≈ 1-minute; they warn "this finding would vary depending on the volatility of the underlying asset's price."
8. **Simulated passive full-range positions vs actual positions.** Fritsch & Canidio simulate a *full-range passive* v3 position, valid only while in range, and concede this may understate real v3 fee income because v3 lets active LPs "move their liquidity around … thereby possibly diminishing the share of fees going to passive LPs." **Their headline v2-beats-v3 result is exposed to exactly this.** Their fee attribution also assumes constant liquidity across each swap's price move (they bound the error at 0.01% over 6 months for WETH-USDC 5bp).
9. **Unit of observation.** Heimbach et al. state their analysis is "on the level of individual liquidity positions, as opposed to wallets or entities." Position-level, wallet-level and entity-level "share of LPs losing money" statistics are not comparable — and JIT positions, with one-block lifetimes, contaminate position-level daily-return distributions.
10. **Compounding conventions differ by version** — v2 fees auto-compound, v3 fees do not — which biases level comparisons of v2 vs v3 returns.
11. **Token incentives.** Heimbach/Wang/Wattenhofer deliberately excluded WETH-USDT, WETH-USDC, WETH-DAI and WETH-WBTC from their case study "as the influence of the liquidity mining program clearly presents itself in the data." Liquidity mining was concentrated in hub pools; any 2020–21 LP-return measure ignoring emissions is measuring the wrong object, with a bias aligned to your treatment variable.
12. **Where the toxic flow actually is.** [Non-Atomic Arbitrage in Decentralized Finance](https://arxiv.org/abs/2401.01622) (Heimbach, Pahari, Schertenleib, IEEE S&P 2024) attributes **more than a quarter of volume on Ethereum's five biggest DEXes from the Merge to 31 Oct 2023** to CEX–DEX (non-atomic) arbitrage. That is a direct measure of the adverse-selection intensity your LVR term is trying to capture, and it is mechanically concentrated in CEX-listed — i.e. hub-adjacent — pairs.

---

### 3. Has anyone compared LP returns by the *role* of the pool's assets?

**No. I found no paper that does this, and that appears to be a genuine gap rather than my failure to find it — but the search was not exhaustive and I want to be precise about what I checked.**

What I checked: systematic arXiv API queries over (i) `liquidity provider` × `loss-versus-rebalancing` (18 hits, all read at title/abstract level), (ii) `liquidity pool` × `centrality` (18 hits), (iii) `decentralized exchange` × {`vehicle`, `numeraire`, `multi-hop`, `routing`} (9 relevant hits), (iv) `Uniswap`/`AMM` × {`core-periphery`, `hub`, `network structure`, `token network`}, (v) `just-in-time` × `liquidity`, (vi) `predictable loss` × `liquidity`. **Zero papers group LP profitability or LVR by the pool's asset role or by a centrality measure.** My WebSearch budget was exhausted mid-task and Semantic Scholar returned HTTP 429 twice, so **I did not systematically search SSRN, RePEc/EconLit or journal databases.** Read this as "none found in the venues I could search," not "none exists."

The four closest things, and why each falls short:

- **Volatility taxonomies, not role taxonomies.** Both Heimbach papers use Uniswap's own stable / normal / exotic classification, which sorts on *relative price volatility of the pair*, not on either asset's market role. In [Behavior of Liquidity Providers in Decentralized Exchanges](https://arxiv.org/abs/2105.13822) (Heimbach, Wang, Wattenhofer, CVCBT 2021) the nine-pool case study gives stable pairs ≈ +0.03%/day and near-riskless, normal pairs (all X-WETH) oscillating around zero (LINK-WETH +0.04%/day, DPI-WETH 0.00%/day), and exotic pairs with ~70% IL over four months that fees cannot cover (KIMCHI-SUSHI −0.76%/day) and dominated in mean-CVaR space by everything else. Every "normal" pair is a WETH pair, so the volatility classification is *partially* proxying the hub role — and they then exclude the four biggest WETH-hub pools for liquidity-mining reasons, which severs the link.
- **Fritsch & Canidio's split is the closest empirical result in existence, and it points somewhere interesting.** Their losers are WETH-USDC / WETH-USDT / WBTC-USDC — the *hub asset against the stablecoin numeraire*. Their winners are LDO-ETH, LINK-ETH, MATIC-ETH, UNI-ETH — *spoke tokens against the hub*. But this is confounded four ways at once (pool size, volume, 5bp vs 30bp fee tier, and Binance-listing selection) and they never frame it as an asset-role result. They call the v2-vs-v3 gap "arguably surprising" and offer LP-competition as the explanation, not asset role.
- **The hub structure is documented, but never joined to returns.** Heimbach/Wang/Wattenhofer report that of ~25,231 tokens on Uniswap v2, **24,011 share a pool with ETH** (next: USDT 1,321, USDC 627, DAI 542, UNI 270, WBTC 148), with >60% of liquidity in the top 24 pools. That is the vehicle-asset stylised fact, in a paper that also measures LP returns — and the two are simply never crossed.
- **[Network Analysis of Uniswap: Centralization and Fragility in the Decentralized Exchange Market](https://arxiv.org/abs/2503.07834)** (Yan & Tessone, 2025) establishes scale-free / core-periphery structure and betweenness-centrality-driven fragility, but contains no LP-return object at all.

One adjacent cross-sectional paper I could not verify: **Chu, Dowling & Li, "Impermanent loss in cryptocurrency," Journal of International Money and Finance 160 (2026), DOI 10.1016/j.jimonfin.2025.103476** ([RePEc record](https://ideas.repec.org/a/eee/jimfin/v160y2026ics0261560625002116.html)). Secondary sources describe Fama–MacBeth regressions finding IL risk positively priced in LP returns after pool-level controls. ScienceDirect returned 403 and I could not read the abstract page directly, let alone the text. **Do not cite this from my summary** — it is the single most likely paper to already contain a pool-characteristic cross-section of LP returns, and it needs a first-hand read. It is the highest-value follow-up in this whole review.

Note also that your own existing corpus already holds the two halves your question joins: Somogyi (2026) measures the vehicle-routing share in FX but says nothing about liquidity-provider returns, and Yuan (2005) predicts a benchmark asset raises liquidity and price informativeness *for every security* but says nothing about who pays for that informativeness. The empty cell is exactly yours.

---

### 4. Has a "centrality curse" been documented, or ruled out?

**Neither. It has not been named, tested, or excluded.** But the literature already contains both of its ingredients measured separately, plus a mechanism that predicts it — which is a strong position for a paper and a hazard for identification.

**The gross-fee leg is documented.** Fritsch (2021) Table 1 gives average daily LP fee returns per $1 of liquidity: ETH-USDC v3 5bp at **2.12×10⁻³** versus USDT-USDC v3 5bp at **1.02×10⁻⁴** — roughly a **20× gross-fee gap** in favour of the hub-asset pool. Hub pools unambiguously earn more gross.

**The no-higher-net leg is documented in pieces, never as a centrality claim.** Fritsch & Canidio's WETH-USDC 5bp running at ~80% fee coverage of arbitrage losses while altcoin-ETH pools clear ~150% is, as far as I can find, **the closest thing to a documented centrality curse anywhere in this literature** — higher gross fees, worse net outcome, in the more central pool. Heimbach et al.'s "less than 30% of the liquidity positions in the four [WETH- and WBTC-paired] pools are rewarded for the added risks they shoulder" is the same shape at position level. Neither author frames it as centrality; neither constructs a centrality measure; neither controls for the confounds.

**A mechanism predicting the curse is already on the record, from two directions.** First, mechanically: LVR is "the scaled product of the variance of prices and the marginal liquidity available in the pool" — so LVR is largest exactly where σ² × depth is largest, which is the hub pools, while fee income scales with volume, not with σ²·depth. Second, informationally: Heimbach/Pahari/Schertenleib's >25%-of-volume non-atomic arbitrage figure says toxic flow concentrates in CEX-referenced pairs. And Yuan (2005) — already in your corpus — supplies the theory: a benchmark security raises price informativeness market-wide by drawing in informed traders. More informativeness *is* more informed order flow *is* more adverse selection. **Yuan's own mechanism generates a centrality curse for liquidity providers even while improving market quality.** That is a framing asset your existing notes do not draw out, since they classify Yuan only as the conceptual precedent for "vehicle currency."

**The identification problem you must confront, stated plainly.** In every existing dataset, "is the hub asset" is nearly collinear with "has a deep liquid CEX reference market," and the CEX reference market is what *creates* the measurable arbitrage in the first place. Fritsch & Canidio's Binance-listing filter makes this structural, not incidental. A centrality curse and a "CEX-arbitrage-exposure curse" predict the same cross-section in the pools that have been studied. Separating them plausibly requires either variation in hub role holding CEX-listing fixed (spoke tokens that *are* CEX-listed, e.g. LINK, UNI, MATIC — which Fritsch & Canidio happen to have and never exploit that way), or pools where the on-chain hub is not the CEX numeraire, or L2/chain variation where the arbitrage latency differs while the network position does not. Also: any test must net gas, because gas is a per-operation fixed cost and hub pools are where repositioning frequency is highest — Caparros/Chaudhary/Klein (in your notes) already show gas causally drives repositioning intensity, so gas is a *mediator* of the effect you are estimating, not a nuisance to absorb into a fixed effect.

**Bottom line for the paper.** The claim "LPs in hub-asset pools earn higher gross fees but no higher net return" is currently *suggested* by Fritsch & Canidio and Heimbach et al., *predicted* by the LVR formula and by Yuan (2005), and *tested by nobody*. The contribution is available. The two things that will be attacked are the CEX-listing confound and the absence of gas in every prior net-return number — and on the second point you have a genuine advantage, because only Cartea/Drissi/Monga have priced gas at all, and only for a single pool.

**Files consulted locally:** `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/00_manifest.md`, `00_exemplars.md`, `01_source_fidelity.md`. Extracted paper texts cached at `/private/tmp/claude-502/-Users-dsf-pro16-m3-glotl/d8c24615-d661-4ac9-899f-20596ce63759/scratchpad/{lvr,fritsch_canidio,fritsch_cl,heimbach_risks,heimbach_behavior,cartea}.txt`.

---

## sor-microstructure

## Scope check

Your existing notes (`00_manifest.md`, `01_source_fidelity.md`) cover the vehicle-currency theory chain, AMM microstructure (Lehar–Parlour, Klein et al., Caparros et al.), and the venue comparators. They contain **nothing** on routers, aggregators, solvers, order-flow auctions, or MEV measurement — the only MEV item in `literature/vehicle-currencies.bib` is Daian et al. (2020). Everything below is new. Two notes flag MEV as *out of scope by construction* for Caparros et al. and Lehar–Parlour; that exclusion is exactly what a routing-cost paper cannot inherit.

---

## A. Router mechanics: what is actually documented vs. proprietary

**Uniswap (Universal Router / Auto Router).** The routing decision is **off-chain**; the Universal Router contract only executes an encoded command sequence. The algorithm lives in the open-source [smart-order-router](https://github.com/Uniswap/smart-order-router). The README is uninformative, but `best-swap-route.ts` implements: candidate routes quoted at fractional amounts (a `distributionPercent` grid), then a **queue-based BFS over split combinations summing to 100%**, with a fixed-size heap keeping the top-3 best swaps per split-count, `minSplits`/`maxSplits` bounds, an early exit once splits ≥ 3 with no improvement, and gas subtracted from the quote (`quote − gasCostL1QuoteToken` for exact-input, `+` for exact-output). Two heuristics matter enormously for measurement: **routes in a split may not reuse the same pool** (because sequential execution changes pool state), and rounding residual is dumped into the final leg. Caveat: I obtained this via a fetch-summariser over the source file, not a line-by-line read — treat as high-confidence-but-secondhand and verify before asserting in print.

Public claims: [Auto Router](https://blog.uniswap.org/auto-router) splits across up to seven paths and takes an extra hop only if the net rate improves; [Auto Router V2](https://blog.uniswap.org/auto-router-v2) claims improved pricing on 13.97% of all trades and 36.84% of trades among the top-10 tokens by TVL. These are vendor blog posts with no methodology — usable to describe intent, not as evidence.

**1inch Pathfinder.** I could **not verify** any algorithmic detail against primary documentation. Widely repeated figures (500+ liquidity sources, splitting across 60+ venues, 5–20 micro-steps) trace to vendor and secondary marketing pages only. 1inch has never published a Pathfinder spec. Do not cite these numbers.

**0x.** [0x Swap API docs](https://docs.0x.org/evm/0x-swap-api/introduction.md) confirm smart order routing that splits across 150+ sources, concurrent AMM quoting plus **RFQ signed quotes from professional market makers** (zero-slippage fills), gas returned as `totalNetworkFee`/`gasFee`, and `minBuyAmount` slippage bounds. The routing algorithm itself is undocumented. The RFQ leg is material for you: RFQ fills have no AMM price impact and no pool state, so they are invisible to any pool-simulation counterfactual.

**Paraswap.** I could not fetch or verify anything usable. Assert nothing.

**Bottom line for identification:** on-chain you observe the *executed* path only. The considered alternatives are never on-chain. Every "route not taken" claim is therefore a simulation, and its credibility rests entirely on the pool universe and state timestamp you choose.

---

## B. Routing theory (the normative benchmark)

- [Optimal Routing for Constant Function Market Makers](https://arxiv.org/abs/2204.05238) (Angeris, Chitra, Evans, Boyd; ACM EC 2022, [DOI](https://dl.acm.org/doi/10.1145/3490486.3538336)): routing an order across a CFMM network is a **convex** program when fixed costs are ignored, and becomes **mixed-integer convex** once fixed (gas) costs enter — i.e. gas-aware optimal routing is combinatorially hard and production routers are necessarily heuristic. This is the single most useful theoretical citation for justifying why realised routes are suboptimal.
- [An Efficient Algorithm for Optimal Routing Through Constant Function Market Makers](https://arxiv.org/abs/2302.04938) (Diamandis, Resnick, Chitra, Angeris; Financial Cryptography 2023): decomposition method handling "aggregate CFMMs" such as Uniswap v3, with large speedups over commercial solvers. Springer pagination is paywalled and unverified — cite the arXiv/FC version.
- [Concave Continuation: Linking Routing to Arbitrage](https://arxiv.org/pdf/2604.02909) (Jiang & Wen, Apr 2026): unifies routing and arbitrage by extending trade functions to negative inputs. Frontier, not yet load-bearing for an empirical paper.

---

## C. Batch auctions, intents, solver competition

- [Batching Trades on Automated Market Makers](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2023.24) (Canidio & Fritsch, AFT 2023, 24:1–24:17): an AMM that batches all trades and executes at the post-trade marginal price is a function-maximising AMM; arbitrageur competition then eliminates LVR **and** sandwich attacks, since all trades clear at one exogenous price. This is the theoretical warrant for treating CoW-type venues as a structurally different cost regime, not just a cheaper router.
- [Fair Combinatorial Auction for Blockchain Trade Intents](https://arxiv.org/html/2408.12225v2) (Canidio & Henneke, Dec 2024): with no numeraire, batching multiple intents creates surplus that cannot be fairly divided — some batch-auction equilibria leave a trader *worse off* than separate single-order auctions. Their mechanism admits a batched bid only if it beats the simultaneous-single-auction reference for **every** trader. Purely theoretical; contains no data on actual CoW batches.
- [Solver competition rules](https://docs.cow.fi/cow-protocol/reference/core/auctions/competition-rules): solutions scored on user surplus from executed amounts; **uniform directional clearing prices** within a solution (hooks excepted); winner selection via the fair combinatorial auction (CIP-67) filtering batched solutions against per-pair reference outcomes; second-price rewards; solver buffers absorb fees, network fees, liquidity-source slippage, and internalisations. **Internalisation matters for you**: a solver may fill against its own inventory, so the settlement transaction's on-chain hops are not the economically relevant price formation.
- [An Analysis of Intent-Based Markets](https://arxiv.org/abs/2403.02525) (Chitra, Kulkarni, Pai, Diamandis, Mar 2024): with costly entry and congestive search effort, more solver entry can *reduce* user welfare; a welfare-maximising planner may prefer restricted entry and limited oligopoly. Direct rebuttal to any "solver competition ⇒ best execution" assumption.
- [Augmenting Batch Exchanges with Constant Function Market Makers](https://arxiv.org/pdf/2210.04929): price coherence, joint price discovery, path independence, and local computability cannot all hold simultaneously when CFMMs settle batch orders. Authors unverified — cite by title/URL.

Solver concentration: [Execution Welfare Across Solver-based DEXes](https://arxiv.org/html/2503.00738v1) reports two market-makers (SCP, Wintermute) at >90% of UniswapX volume vs. a flatter CoW distribution (top solver ≈25%, next five ≈10% each). A July-2026 preprint on CoW's CIP-74 reward reform (HHI 0.176→0.241, no detectable execution-quality change within ~7 bps) surfaced only in a search snippet — **I could not locate the preprint itself; do not cite it.**

---

## D. MEV, private orderflow, order-flow auctions

- [Sandwiched and Silent: Behavioral Adaptation and Private Channel Exploitation in Ethereum MEV](https://arxiv.org/html/2512.17602v1) (Mancino & Rezzoli; data Nov 2024–Feb 2025, ~149M transactions): sandwich triplets identified from ZeroMEV-labelled frontruns plus same-sender backruns bracketing a victim; public/private classification via MempoolDumpster mempool records. Findings: **37.2% of victims migrate to private routing within 60 days** (≈54% for 7+ exposures); 2,932 *private* sandwiches in Nov–Dec 2024 hitting 3,126 private victim transactions, $409,236 user losses / $293,786 attacker profit; one bot address ≈65% of private frontruns. Losses are ZeroMEV valuations, explicitly lower bounds. Conclusion you can use: **private RPC is a treatment that changes exposure but does not eliminate it, and it is endogenously chosen by previously-sandwiched traders** — a selection problem for any cost regression that conditions on submission channel.
- [Quantifying Price Improvement in Order Flow Auctions](https://arxiv.org/abs/2405.00537) (Bachu, Wan, Moallemi, May 2024; also [Uniswap PDF](https://blog.uniswap.org/UniswapX_PI.pdf), [blog](https://blog.uniswap.org/measuring-price-improvement-with-order-flow-auctions)): attributes price improvement to **modifiable inputs — routing efficiency, gas optimisation, priority-fee settings** — against a counterfactual Uniswap-router execution at historical block state; finds statistically significant improvement averaging **4–5 bps** on 1inch and Uniswap interfaces, sourced mainly from added liquidity on large swaps. My attempt to extract the full decomposition formulas from the PDF returned a generic, low-fidelity summary — **read the PDF directly before reproducing the decomposition.**

A frequently quoted Flashbots figure (1.2% of Ethereum DEX trades sandwiched, average loss 0.41% of trade value) appeared only in a search snippet. **Unverified; do not cite.**

---

## E. Measurement practice: how published papers actually compute execution cost and counterfactuals

**Published, venue-accepted baseline — follow this for the cost *level*.**
[On the Quality of Cryptocurrency Markets: CEX vs. DEX](https://arxiv.org/html/2112.07386v7) (Barbon & Ranaldo, *Management Science*, [DOI](https://pubsonline.informs.org/doi/10.1287/mnsc.2024.07703)) — already in your comparator set, but its *measurement* is what you need:

`TC_XY(Δx) = S_XY(Δx) + f + g/Δx`

i.e. size-dependent price impact + protocol fee + gas amortised over notional. Crucially it is computed on **hypothetical trades of fixed notional ($1k / $10k / $100k / $1M), hourly**, not on realised swaps; gas is a fixed unit count (**118,340 for Uniswap v2, 130,889 for v3**) times the hourly median gas price; and v3 pool choice is resolved by picking the **cheapest single pool including gas** — i.e. a primitive one-pool router. The CEX counterpart is VWAP-of-book depth plus flat fees. Their headline: validator gas, not classical price impact, is the dominant trader cost.

**The counterfactual ladder — follow this for route cost.**
[Quantifying Sub-Optimality in Routing for Automated Market Makers](https://arxiv.org/html/2607.20762) (Weiye Xi & Ciamac C. Moallemi, Columbia, arXiv 2607.20762v1, 22 Jul 2026) is the paper whose methodology you should adopt. It defines suboptimality as proportional shortfall of the realised route against **three reproducible benchmarks solved at fixed pool state**:

1. **SCO** (support-constrained optimum) — reoptimise the split *only across pools the trade actually touched*, ignoring gas. Isolates bad splitting.
2. **FVO** (full-venue optimum) — reoptimise across *all* available pools, ignoring gas. Adds the cost of venues not activated.
3. **G-FVO** (gas-aware FVO) — same, with a fixed per-pool activation cost, solved as a mixed-integer program by exact enumeration over all `2^|J|` pool subsets with bisection on marginal-price equalisation inside each subset.

Sample: Ethereum blocks 19.5M–23.0M (Mar 2024–Jul 2025), **2.98M WETH–USDC swaps, $120.42B input**, four pools (v2 30bp; v3 1/5/30bp), trades <$100 and counterflow filtered. Labelled routers: Universal Router, CoWSwap, 1inch v4, 1inch v5, Odos v2 (~21% of transactions, 5.6% of volume). Gas is **direction-asymmetric** (token0→1 deducts from output; token1→0 shrinks the input budget) and modelled as quantity-independent per-activation cost to preserve concavity — explicitly abstracting from v3 tick-crossing variability.

Results: **mean shortfall 2.02 bps**; aggregate $6.58M vs. SCO, $21.39M vs. FVO, $24.20M vs. G-FVO. **One block of state staleness costs +1.29 bps (FVO) / +1.78 bps (G-FVO)**, ≈$15.5M/$21.4M. Loss distribution is heavy-tailed: median ≈0, 2–3% of trades drive the mean. Sandwiched trades (heuristically: bracketed by opposite-direction swaps from the same counterparty cluster) shift suboptimality up by tens of bps with fat right tails; public-mempool routers show ~6% sandwiching by dollar volume vs. CoWSwap ~0.0046%.

**Their stated limitations are your opportunity: single pair, same-pair pools only, no multi-hop routes through intermediate tokens, L1 only.** A vehicle-currency paper is precisely the multi-hop extension they name as future work.

**Solver-venue welfare — the comparator design.**
[Execution Welfare Across Solver-based DEXes](https://arxiv.org/html/2503.00738v1) (Yuminaga, Chen, Sui; Aug 2023–Feb 2024, blocks 18.0M–19.16M, USDC-WETH and PEPE-WETH):

`Execution Welfare = (solver output − AMM output after gas) / (AMM output after gas)`

Counterfactual simulated on Uniswap V2/V3 at **top-of-block (block N−1)** liquidity to avoid own-trade interference; gas via Tenderly using priority-fee-adjusted prices from same-block competing transactions; V3 fees via the official Uniswap SDK quoter; gas converted at pool spot. They also report a **Binance markout** — a CEX-midprice benchmark — and find solvers negative against it (5 to 1,000+ bps by size) even where they beat the AMM. Their own limitations list is the one to copy defensively: only two pairs, no multi-pool routing in the benchmark, filled-orders-only selection bias, batch-auction delay uncosted, and token-incentive subsidies (COW/1INCH) inflating apparent welfare.

**Two distinct questions, two benchmarks.** "Was the route the best available on-chain path?" → counterfactual-route simulation (Xi–Moallemi). "Was the fill good in absolute terms?" → CEX markout (Yuminaga et al.). They can disagree in sign. A credible paper reports both.

---

## F. Depth on heterogeneous AMMs — is there an accepted standard?

**No, there is no accepted academic standard.** I checked and could not find a paper proposing a unified cross-design depth metric. What exists:

- **Industry de-facto convention: ±2% market depth.** [The Dominance of Uniswap v3 Liquidity](https://blog.uniswap.org/uniswap-v3-dominance) (Liao & Robinson, 5 May 2022) defines depth as dollars tradeable within a ±2% price-impact band, computed for CEXs by summing book levels and for v3 by aggregating LP positions across tick ranges via `m(δ) = (1/s) Σ |λx(i) + p₀⁻¹λy(i)|`. Headline: v3 ≈2× Binance/Coinbase on ETH/USD, ≈3–4.5× on ETH/BTC, ≈5.5× on USDC/USDT. Widely cited, not peer-reviewed.
- **Published alternative: fixed-notional cost curves.** Barbon–Ranaldo sidestep depth entirely and report all-in cost at four fixed notionals. This is the version that cleared *Management Science*.
- **Cross-design formalisation:** [SoK: Decentralized Exchanges (DEX) with Automated Market Maker (AMM) Protocols](https://arxiv.org/abs/2103.12732) (Xu, Paruch, Cousaert, Feng; *ACM Computing Surveys*, [DOI](https://dl.acm.org/doi/10.1145/3570639)) builds a general AMM framework and compares conservation functions plus slippage and divergence-loss functions across top protocols, defining slippage as spot-vs-realised price difference conditional on trade size relative to pool size and the conservation function. I could not open the full text in this session, so I cannot confirm which closed-form slippage expressions are given per family (constant product / stableswap / weighted / concentrated liquidity) — but the first author is you, so this is trivially checkable locally and is the natural citation for the claim that depth is design-specific.

**A trap worth writing into the paper.** Your `docs/research-workflow.md` already defines depth as *dollars to move the **marginal** price by 10 bps and 50 bps*, computed per venue against its own invariant then aggregated. That is defensible and correct not to sum reserves. But marginal-price displacement and realised average execution cost stand in a **design-dependent** relation: in constant product the marginal price moves roughly twice as far as the average execution price for small trades, whereas stableswap (flat then sharply convex in the amplification region) and concentrated liquidity (piecewise, tick-dependent) have entirely different ratios, and a v3 pool can show large marginal-price depth while a trade that exits the active range costs far more. So a marginal-price-move metric is **not** automatically comparable across your five venue families even when computed against each invariant. Recommendation: make **realised all-in cost at fixed notionals** the primary metric (Barbon–Ranaldo-comparable, and it is what a trader pays), and keep marginal-price 10/50 bps depth as the secondary structural descriptor with the divergence explicitly documented.

---

## G. What your paper must do

Against `scripts/run_route_cost_panel.py` as it stands — daily state, best *single* direct route vs. best *two-hop* vehicle route, V2/Sushi reserves plus offline-reconstructed V3 tick quoting, no gas, no splitting:

1. **Add the gas leg.** The design doc (`docs/research-questions-and-empirical-design.md:51`) promises `C^{D,gas}` and `C^{I,gas}`; I found no `gas` reference anywhere in the route-cost script. A two-hop vehicle route is mechanically more gas-expensive than a one-hop direct route, so omitting gas biases the panel **systematically toward the vehicle route** — and Barbon–Ranaldo's headline is that gas dominates classical price impact. Measure gas units empirically from receipts per route topology rather than assuming; their 118,340 / 130,889 single-swap constants are a fallback only, and I found **no verified per-additional-hop gas figure** anywhere.
2. **Make the split treatment symmetric and state it.** Comparing an *unsplit* best-single-pool direct route against a *realised, aggregator-split* vehicle route is not a like-for-like comparison. Xi–Moallemi price the split gap at 2.02 bps mean / $24M on WETH–USDC alone. Either optimise splits on both sides (SCO-style) or restrict both sides to single-pool legs and say so in the caption.
3. **Adopt the three-benchmark ladder explicitly.** Report SCO / FVO / G-FVO analogues for direct and vehicle routes. This converts "we compared two routes" into "we decomposed shortfall into mis-splitting, venue omission, and gas" — the difference between a descriptive table and a methodology reviewers recognise.
4. **Fix state staleness or bound it.** One block of staleness costs 1.29–1.78 bps; your daily state is orders of magnitude staler and the bias is not sign-neutral. `scripts/run_transaction_time_quote_robustness.py` already exists — promote it from robustness to the primary specification, or report the daily-vs-transaction-time wedge as a first-order magnitude, not a footnote.
5. **Report the direction of bias from the truncated venue universe.** Curve and Fluid are excluded from exact quoting (`run_curve_fluid_exclusion_sensitivity.py` acknowledges they are "material but not exact-quoteable"). Under FVO logic, an omitted venue mechanically makes whichever route depends on covered venues look better. A share-based sensitivity is not the same as signing the cost bias — say which direction it runs.
6. **Separate MEV from routing shortfall.** Realised on-chain amounts embed sandwich losses; simulated counterfactual quotes do not. Flag sandwiched victims (Xi–Moallemi's bracketing heuristic, or ZeroMEV labels as in Mancino–Rezzoli) and report route cost with and without them. Also report medians alongside means: 2–3% of trades drive the entire mean.
7. **Label the router and treat intent venues separately.** Much of what you code as a trader's "route choice" is an off-chain aggregator's decision, and for CoW/UniswapX/1inch Fusion the on-chain settlement path is the *solver's* — possibly internalised against inventory or filled via RFQ, in which case no AMM counterfactual describes the user's alternative. Label settlement contracts (Xi–Moallemi's five cover ~21% of transactions / 5.6% of volume on one pair) and report router-mediated share; if a large fraction of vehicle routing is aggregator-generated, your economic object is aggregator behaviour, not trader preference — which is a *stronger* paper if stated deliberately rather than discovered by a referee.
8. **Condition on submission channel — carefully.** Private RPC adoption is endogenous to prior sandwiching (37.2% migrate within 60 days), so channel is a selected treatment, not a control.
9. **Go beyond two hops on both sides.** Restricting the direct-route alternative to single-hop while vehicle routes get two hops, when production routers split across many legs, understates both.
10. **Report both benchmark families.** Counterfactual-route shortfall (in bps of notional) *and* a CEX markout. Divergence between them is a finding, not a failure.

---

## Papers whose methodology to follow, ranked

1. **[Xi & Moallemi (2026), "Quantifying Sub-Optimality in Routing for Automated Market Makers"](https://arxiv.org/html/2607.20762)** — adopt the SCO/FVO/G-FVO counterfactual ladder, the direction-asymmetric fixed-activation gas model, and the staleness experiment. This is the closest existing methodology to what you need, and its explicit exclusion of multi-hop/intermediate-token routing is your contribution slot. Preprint, ~2 weeks old, not peer-reviewed.
2. **[Barbon & Ranaldo, *Management Science*](https://pubsonline.informs.org/doi/10.1287/mnsc.2024.07703)** — adopt `TC = S(Δx) + f + g/Δx` and the fixed-notional grid for the cost *level*. Already your DeFi-native venue proof point; reusing its cost definition costs you nothing and buys referee familiarity.
3. **[Bachu, Wan & Moallemi (2024)](https://arxiv.org/abs/2405.00537)** — adopt the attribution of improvement to routing / gas / priority fee as modifiable inputs.
4. **[Yuminaga, Chen & Sui (2025)](https://arxiv.org/html/2503.00738v1)** — adopt top-of-block (N−1) counterfactual construction, Tenderly-style gas estimation from same-block competing priority fees, and the dual AMM-plus-CEX-markout benchmark. Not peer-reviewed; industry-authored.
5. **[Angeris, Chitra, Evans & Boyd (EC 2022)](https://arxiv.org/abs/2204.05238)** + **[Diamandis et al. (FC 2023)](https://arxiv.org/abs/2302.04938)** — cite for why gas-aware optimal routing is mixed-integer hard, hence why realised routes are heuristic and a shortfall exists to measure.
6. **[Canidio & Fritsch (AFT 2023)](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2023.24)** + **[Chitra, Kulkarni, Pai & Diamandis (2024)](https://arxiv.org/abs/2403.02525)** — cite to justify treating batch/intent venues as a different cost regime *and* to block the assumption that solver competition passes value through.

## Stated plainly: what I could not verify

- **1inch Pathfinder** and **Paraswap** mechanics: no primary source obtained. All circulating figures are vendor/secondary marketing. Do not cite.
- **Uniswap SOR internals** (BFS over split grid, top-3 heap per split count, no-pool-reuse constraint): obtained via a summariser over `best-swap-route.ts`, not a direct read. Verify against source.
- **Flashbots "1.2% of DEX trades sandwiched / 0.41% average loss"**: search snippet only. Unverified.
- **CoW CIP-74 preprint (HHI 0.176 → 0.241)**: search snippet only; preprint not located. Unverified.
- **Xu et al. SoK**: could not open full text; cannot confirm which per-family closed-form slippage expressions it provides. Checkable locally — you are an author.
- **Per-additional-hop gas cost**: no verified figure found in any source. Must be measured from your own receipts.
- **Springer pagination** for Diamandis et al. (978-3-031-47751-5_8): paywalled, unverified. Cite arXiv/FC 2023.
- **`Augmenting Batch Exchanges with CFMMs` authorship**: unverified; cite by title/URL.
- My web-search budget was exhausted mid-task, so coverage of **MEV-Boost / PBS-side literature** (Öz et al., Bahrani–Garimidi–Roughgarden) and of **Heimbach et al. on fragmentation/routing** is absent rather than assessed. Those are the two most likely remaining gaps.

Sources:
- [Quantifying Sub-Optimality in Routing for Automated Market Makers](https://arxiv.org/html/2607.20762)
- [Execution Welfare Across Solver-based DEXes](https://arxiv.org/html/2503.00738v1)
- [Quantifying Price Improvement in Order Flow Auctions](https://arxiv.org/abs/2405.00537)
- [Measuring Price Improvement with Order Flow Auctions](https://blog.uniswap.org/measuring-price-improvement-with-order-flow-auctions)
- [Optimal Routing for Constant Function Market Makers](https://arxiv.org/abs/2204.05238)
- [An Efficient Algorithm for Optimal Routing Through Constant Function Market Makers](https://arxiv.org/abs/2302.04938)
- [Concave Continuation: Linking Routing to Arbitrage](https://arxiv.org/pdf/2604.02909)
- [Batching Trades on Automated Market Makers](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2023.24)
- [Fair Combinatorial Auction for Blockchain Trade Intents](https://arxiv.org/html/2408.12225v2)
- [CoW Protocol solver competition rules](https://docs.cow.fi/cow-protocol/reference/core/auctions/competition-rules)
- [An Analysis of Intent-Based Markets](https://arxiv.org/abs/2403.02525)
- [Augmenting Batch Exchanges with Constant Function Market Makers](https://arxiv.org/pdf/2210.04929)
- [Sandwiched and Silent](https://arxiv.org/html/2512.17602v1)
- [On The Quality Of Cryptocurrency Markets](https://arxiv.org/html/2112.07386v7) / [Management Science version](https://pubsonline.informs.org/doi/10.1287/mnsc.2024.07703)
- [SoK: Decentralized Exchanges (DEX) with AMM Protocols](https://arxiv.org/abs/2103.12732) / [ACM CSUR](https://dl.acm.org/doi/10.1145/3570639)
- [The Dominance of Uniswap v3 Liquidity](https://blog.uniswap.org/uniswap-v3-dominance)
- [Introducing the Auto Router](https://blog.uniswap.org/auto-router) / [Auto Router V2](https://blog.uniswap.org/auto-router-v2)
- [Uniswap smart-order-router](https://github.com/Uniswap/smart-order-router)
- [0x Swap API docs](https://docs.0x.org/evm/0x-swap-api/introduction.md)

---

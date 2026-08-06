# Research workflow: paper and talk on dominant vehicle currencies

Version 2, 2026-08-05. Replaces `docs/nbc-2026-deck-pipeline.md` (version 1), whose single-venue empirics and deck were both binned. This is a graph. The paper and the deck inform each other, and evidence can send work back to design.

Every claim in the "grounding" column below was measured or read in this project. Where something is an assumption, it says so.

---

## 0. Standing rules

**Portability.** This file and every node's output is a plain tracked file in this repo. No node's real state may live only inside one model's session. Whatever executes a node reads this file plus the previous node's committed output and continues.

**Sync.** Commit and push after every node. An unpushed completed node counts as unfinished.

**Supersede means delete.** When a new version of any artefact exists, delete the old one in the same commit. Git history is the archive. Two live copies of a deck already caused a full review cycle to be spent on the wrong file.

**Challenge the spec itself, beyond conformance to it.** Every review node must answer: *is any requirement here wrong, unnecessary, or harmful to the deliverable's purpose?* A pipeline that only checks conformance will propagate a bad requirement to the deliverable. That is exactly how a slide reconciling the talk against its own submitted abstract survived three review phases: the requirement was written into the spec, so reviewers verified its presence instead of questioning its existence.

**Cross-family review.** Reviews that matter run on a different model family (`glotl review <role> <artifact> --model codex`; `glotl/agents.py::independent_model` picks a non-Claude substrate automatically). Grounding: a 9-judge same-family LLM panel was measured to carry the independent information of about 2 votes, because shared training produces shared blind spots, and a judge inflates its score when it shares the mistake being judged. Same-family redundancy buys confidence without accuracy.

**No internal process in any deliverable.** No slide or paragraph reconciles the work against its own earlier plans, renumbers propositions, references pipeline phases, or opens with limitations. Reporting a null is mandatory and belongs in results, stated as a finding. Performed uncertainty at the reader is a different thing and has no place there.

---

## 1. What the venue actually requires (node A output, already complete)

Derived by reading all 14 published JFE papers in `../defi-dominant-currency/lit/jfe-exemplars/`, one independent reader each. Full detail in the agent output; the load-bearing conclusions:

**Invariants, to comply with:**
- No standalone literature-review section (14/14). The review sits inside the introduction, each strand closing with a differentiation sentence.
- Introduction 5.5–8 manuscript pages, 12–18% of the document, narrating the whole argument in prose before any notation, and previewing every finding.
- Six top-level sections, ±2. None of the 14 has five. Last section is the Conclusion (14/14).
- Abstract ~100 words (median 101, 11/14 within 96–106). Opens in first person with what the paper does. No gap-framing (0/14). No coefficients, t-statistics, sample periods or sizes (0/14). 10/14 contain no numbers at all.
- No H1/H2 hypothesis list (0/14). No testable-predictions exhibit (0/14).
- If there are numbered results: Propositions, not Theorems (1/7 uses Theorem). Every result followed by a prose intuition paragraph (7/7). **No proof anywhere in the body (7/7, absolute)**; proofs go to an appendix.
- One central mechanism, stated three times at rising formality: abstract, then introduction prose with zero notation, then propositions or tables.
- Objections named and dispatched in the body, in numbered subsections; an appendix does not discharge them.
- Magnitudes translated into economic units in prose.
- Roughly 8 tables and 7 figures if empirical. Theory papers substitute 5–7 figures and zero tables.

**Idiosyncratic, so choose deliberately and do not assume:**
- **Having a model at all: 8/14 yes, 6/14 no.** A prior claim in version 1 of this workflow that JFE requires model-first structure was wrong on both halves and is retracted here.
- **Model before empirics, among papers with both: 1 of 3.** Huang, Ranaldo, Schrimpf and Somogyi state theirs is "a static partial equilibrium model that rationalises the two main empirical findings from the previous section." Facts first, model as rationalisation, is at least as safe.
- **Causal identification of any kind: 3 of 9 empirical papers.** 6 of 9 make no causal claim, two saying so in the text. Only 2/14 use a natural experiment as the identification spine. What substitutes, in every one of the six: **a data moat plus an obsessive validation apparatus.** Graham et al. spend the whole second half of the paper defending the data source.
- Length 20–45 typeset pages, median 23; roughly 45–60 manuscript pages.

**The strategic reading.** The distribution is bimodal: 5 pure theory, 6 pure empirics with no formal theory, only 3 doing both. Attempting both is the minority strategy. **This paper takes the pure-empirics lane**, because a model added to reach for respectability would be the third-least-common configuration in the sample. Caveat recorded from the independent review: counting structural features across 14 papers describes what published papers look like and does not establish what caused acceptance, so this is a presentation-architecture decision and carries no claim about acceptance odds. A model is added later only if a specific empirical coefficient or threshold cannot be explained without one.

**Craft pattern to adopt deliberately: the named rival mechanism run as a horse race.** This is what no-model empirical JFE papers use in place of formal hypotheses. Bolton and Kacperczyk italicise three competing hypotheses in the introduction, use them as running labels structuring the results, and reject one of their own.

---

## 2. What the data actually supports (node C, partially measured)

The repo's real asset, and the thing version 1 failed to use: `data/unified/`, **2,277 daily parquet files, 2020-02-11 to 2026-06-30, roughly 215k swap legs per day, all eight venues** (uniswap v1–v4, sushiswap v2/v3, curve, balancer, fluid). It carries `tx_hash`, `component_id`, `n_components`, `route_class`, `tin_role`, `tout_role`, meaning **multi-leg routes are already reconstructed across venues inside a single transaction**.

Measured, on eight days sampled across the span (needs the full panel before it goes in the paper): the share of multi-leg routes spanning more than one venue rises monotonically from **11.7% in Jan 2021 to 49.8% in Sep 2025**. Studying one venue in isolation is therefore not merely incomplete, it becomes progressively wrong across the sample.

An independent review (2026-08-05) correctly demolished the version-1 reading of this as a "data moat". Graham et al.'s advantage was *unobservable* variables from a 1,348-executive survey; on-chain data is public to anyone with an RPC endpoint. What exists here is **reconstruction difficulty**: attributing multi-leg routes across eight venues at scale is hard engineering. That is a weaker claim and gets stated as the weaker claim, and it does not substitute for identification. The validation apparatus is still required at Graham-level intensity: provenance, reconstruction validity, drift audits, exact-contract identity of every candidate asset.

**The silo to avoid repeating:** `src/ddvc/analysis/lp_concentration.py` reads only `data/raw/thegraph/uniswap_v3/`. Every liquidity measure built on it was a Uniswap-V3-only quantity. All measures get rebuilt on the unified layer.

---

## 3. Definitions to settle first (node C, blocking)

**Vehicle status and dominance are separate axes.** Vehicle status is a role that is binary and trivially satisfied: one bridging swap qualifies. What matters and what we measure is the *extent* to which one asset captures that role. The literature uses "vehicle currency" as a categorical label for what is really a continuous share, and making that precise is part of the contribution. Working title, a one-word insertion into the original public title so the public record stays continuous: **"The Making of Dominant Vehicle Currencies: Evidence from DeFi"** (decided by Java, 2026-08-06).

**Asset types before tickers.** DeFi is the laboratory and the claim is about currency types, so tickers appear only as proxies:
- *Native platform asset*: thickest incumbent pairing network, high volatility. Proxy: WETH. TradFi analogue: the incumbent international currency whose role rests on thick-market externalities.
- *Stable numéraire*: low volatility, unit of account. Proxies: USDC, USDT, DAI. TradFi analogue: the managed or pegged stable unit.
- *Imported store of value*: non-native, wrapped. Proxy: WBTC. TradFi analogue: gold or a foreign reserve asset.

The general question is then venue- and coin-independent: does the vehicle role stay with the thick-network incumbent or migrate to the low-volatility numéraire, and what triggers migration? That is the FX dominance-transition question, and we can observe the road not taken where FX cannot.

**Definitions belong on a slide and in a numbered subsection**, stated explicitly.

**What the route-cost experiment measures, stated once so it stops drifting.** For one trade, meaning a specific token pair at a specific hour at a specific size, the panel computes the best ONE-HOP route, which is the direct pool joining the endpoints priced at its cheapest venue, and the best TWO-HOP route through each candidate vehicle, where each leg independently picks its own cheapest pool across every available venue. It then asks whether routing through the native asset costs less than routing through the stable numéraire or the imported asset. Legs genuinely do cross venues: 32.3% of two-hop routes in the current panel have their two legs on different DEXes.

**Why this object and not realised swaps.** Vehicle-currency theory says the incumbent retains the role because routing through it is cheaper, which is the thick-market externality. The test is therefore the cost of the road not taken. FX data cannot run it, because the quote for the route nobody took is never observed; on-chain the state can be reconstructed and the counterfactual priced exactly, which is this paper's actual edge over the FX literature. What the panel does NOT measure is router behaviour or revealed preference. It is the cost surface a router faced, not the choices it made, and those are different papers.

**Consequence for venue coverage, which follows from the definition rather than from tidiness.** "Best available route" is defined over all venues, so truncating the venue set understates the best route on every leg and the bias direction depends on which routes lose most. Curve carries roughly 85% of Uniswap v2's volume on sampled 2024 days and sits where stable-to-stable legs happen, so omitting it plausibly penalises stable-vehicle routes hardest and flatters the native asset in exactly the comparison the headline rests on. Venue completeness is therefore part of identification here, not a robustness appendix.

**Balancer's coverage bound, signed (2026-08-06).** Balancer is the sixth venue and its weighted pools now price exactly: `ddvc.pricing.weighted` reproduces realised swaps at 0.0000% median absolute error with 100% of quotes inside 1%, scored on trades no fit ever saw, across twelve days spanning 2021-04 to 2026-02. Two things had to be identified from data before that held. The daily `poolSnapshots.amounts` record is the balance after the day's LAST event, so netting the day's flow off it and replaying forward gives per-swap balances; the two rival readings of that field score 1.7% and 2.8% on the same trades. And the flow has to include joins and exits, because a swap-only walk charges every liquidity event to the invariant and drops coverage from 87 of 105 testable pool-days to 177 of 367. The bound that remains is real and it is large: 256 of 473 testable pool-days price, and the excluded pools carry a median 91.8% of tested swap volume. The exclusions are decided by achieved fit error and not by pool type, and reading the types afterwards says what they are, namely the boosted and linear families and composable-stable pools.

**Correction to the line above, checked against the live schema (2026-08-06).** An earlier version of this paragraph said those families run StableSwap and could therefore be routed through `ddvc.pricing.stableswap` with Balancer's own `Pool.amp`. That is wrong for the two largest of them and understates the work for the rest. AaveLinear and ERC4626Linear, which carry a median 58.8% and 63.7% of a day's swap volume in the exclusion ranking, are not StableSwap at all: they hold `lowerTarget`, `upperTarget`, `mainIndex` and `wrappedIndex` and price a wrapped position piecewise with different fee treatment inside and outside the target band, so they need their own module. Every ComposableStable and ERC4626Linear pool also holds its OWN BPT inside `tokensList`, checked at 29 of 29 and 3 of 3 on a sampled day, carrying the virtual-supply sentinel balance of about 2.596e15, so the BPT has to be removed from the invariant and handled separately for BPT-in and BPT-out swaps. The binding obstacle is rate providers: `priceRate` is not one, reading 1.2397 for wstETH and 7.76e-10 for a boosted-USDC token, balances must be scaled by it before the invariant, it is absent from the extended schema, and it drifts continuously so a head-block reading cannot serve a past day. Identifying it from trades costs one free scalar per token instead of one per pool, which is where the achieved-fit-error gate stops being able to tell a correct fit from a flexible one, and that is the same over-parameterisation trap the gate exists to catch. Balancer's `AMP_PRECISION` is also 1000 against Curve's 100, a convention the Curve path never had to pin because A is fitted there.

**The cheapest correct next step, so the gap is scoped and not just noted.** 23 of 29 composable-stable pools have exactly two real tokens once the BPT is removed, which is one rate provider and therefore one free scalar, so those are gate-able on the same rule the weighted family already passes and that is where the WETH-adjacent stable-family volume concentrates. The linear and boosted families stay out until a linear module exists. Meanwhile the panel's Balancer leg covers the weighted family, priced at end-of-hour balances on the same convention as the v2 family, and the coverage gap is documented in `output/exhibits/weighted_quoter_validation.jsonl` instead of being silent.

---

## 4. Candidate results, screened for non-mechanicalness (node E)

Version 1's findings were near-tautological ("availability predicts usage", "netting reduces transfers"). A candidate result is rejected at design time if its sign is guaranteed by construction.

### 4.0 What is taken, what is open, and where incumbency can legitimately live

Two independent cross-family reviews plus a four-lane prior-art sweep settled this section. Revised 2026-08-05. The earlier version was wrong in three ways, retracted here explicitly.

**Routing is not a site of habit.** Swap routing is executed by smart-order routers that are deterministic graph optimisers, so a preference for an incumbent intermediary when a cheaper direct route existed fails as evidence of trader inertia. Version 1's plan to read a wrong-signed cost coefficient as Krugman/Eichengreen inertia is retracted.

**Adjacent work exists, and we re-establish it ourselves (Java, 2026-08-05).** Xi and Moallemi (arXiv 2607.20762, 22 July 2026) run a cross-aggregator routing-suboptimality exercise on 2.98M WETH-USDC swaps, labelling routers by destination contract and attributing residual dispersion to institutional features. **Venue, checked on the arXiv listing: 21 pages, accepted at the 5th Workshop on Decentralized Finance (DeFi 2026), held in association with Financial Cryptography and Data Security 2026.** A workshop paper at a CS-security conference, which is the lowest publication tier at a venue type JFE papers already do not cite. An earlier draft of this workflow proposed citing it as established fact. **That is reversed.** Anything this paper needs gets established from our own data, for two reasons.

The first is convention, and it is measured rather than asserted. Across the 14 JFE exemplars, 619 references contain 129 finance-journal and 86 economics-journal mentions, 135 working-paper, NBER or SSRN mentions, and **8 CS-venue or arXiv mentions, all of them inside a single paper** (Hinzen, John and Saleh on Bitcoin, where the consensus-protocol literature is unavoidable). Thirteen of fourteen cite none. So the constraint is not about preprints, since working papers are cited more often than finance journals; it is specifically that CS-venue work sits outside the conversation JFE papers conduct. A result this paper depends on cannot rest on a citation the target venue does not make.

The second is that our version is a different and better object anyway. Their exercise is single-pair, L1-only, and same-token by construction: *"we restrict attention to a simplified same-token setting … we do not allow trading through other intermediate tokens when routing"*, with multi-hop named as future work. Ours is multi-hop across eight venues, which is the margin the vehicle-currency question actually lives on.

Handling, revised once the venue was confirmed: since our claims and theirs do not overlap (they exclude multi-hop and multi-token by construction, which is our entire object), no citation is owed on intellectual-honesty grounds either. Keep a one-line mention in the related-work prose if the multi-hop framing ends up close enough to invite the comparison, and drop it otherwise. Nothing in the paper may depend on it.

**The entry contract does not identify the aggregator.** The earlier text asserted it did, which contradicted `docs/router-identification-feasibility.md` in this same repo. Corrected: `sender` identifies the **executor**, because Universal Router executes calldata computed off-chain and any wallet or meta-aggregator can call it. The executor population fragments to 397 distinct senders by late 2025 with a hand registry capturing 11.8% of swaps. Maury (Zenodo 21513263) argues no standard on-chain mechanism announces frontend identity and supplies four recovery heuristics; Xi and Moallemi's own labelling reaches roughly 21% of transactions and 5.6% of volume on a single pair. Any executor attribution must be built by trace classification with an address-version registry, and stated as partial.

**What is genuinely open.** The intermediary-asset margin, multi-hop routing, and matched-trade head-to-head comparison are unoccupied. Separately, **nothing in the literature connects DEX routing to the vehicle-currency question at all**: searches for vehicle currency plus DeFi routing return zero. The framing is the contribution, and the multi-hop intermediary margin is promoted from incidental to central.

**Where incumbency legitimately lives.** Routing is instantaneous, so stickiness cannot live there. It can live in (i) **LP capital allocation**, since providers face switching costs, gas costs and attention limits, and (ii) **aggregator integration scope**, a business decision updated on a business cadence. codex-undp states the distinction exactly: a router choosing the native asset because its pools are deepest is mechanically optimal today, while the reason those pools are deepest may be historical incumbency. That is incumbency operating through a state variable, with no algorithmic inertia at quote time.

**Structural breaks are the identification spine.** This is the most consequential correction. The FX literature's decisive gap is that an incumbent's cost advantage is itself a consequence of its incumbency, so the data never contain the state in which a currency holds the vehicle role while being strictly cost-dominated by a rival. Gas-regime shifts, fee-tier introductions, protocol-version migrations and the March 2023 depeg are candidate windows in which exactly that state occurs on-chain. Earlier drafts listed these as regime controls to absorb. They are the variation to exploit.

**Condition tested 2026-08-05, and the answer is not yet.** See `docs/finding-cost-dominance-not-yet-established.md`. A cheap existence test on realised rates fails: intraday price movement swamps execution cost by a factor of 34 (median absolute gap 775 bps on volatile pairs against 23 bps on near-zero-drift stable pairs), so daily-median comparison cannot detect a cost difference on 97% of the sample. Establishing cost-dominance windows requires pricing the road not taken at transaction-time pool state, for which the reference repo already holds a validated quoter (1,550 of 1,655 swaps within 1%, median absolute error 0.00 bp) that needs porting from single-venue two-hop to cross-venue multi-hop, plus a receipt-measured gas model. **Until that lands the paper makes no claim to resolve the inertia identification problem**, and the intro sentence drafted from the inertia literature stays out. The two measured results stand without it.

**On mechanical results, per Java: keep them, demote them.** Architectural factors (pair availability, pool existence, netting) shape dominance and belong in the paper as the layer that sets the feasible set, with slower allocative choices selecting within it. They may not lead, because a result whose sign is guaranteed by construction fails as a contribution.

### 4.1 Candidate results, reordered

1. **The intermediation transition, measured.** Which asset type intermediates, and has the role migrated from the native platform asset to the stable numeraire? Measured on the full panel: the native share of intermediation episodes falls while the stable share rises, with the crossover arriving far earlier value-weighted than count-weighted. This is ours, the framing is unoccupied, and it shows the sterling-to-dollar transition over six years instead of decades. Leads the paper.
2. **Cost-dominance windows.** Do windows exist in which an incumbent route is strictly cost-dominated on an executable all-in basis while its incumbency holds, and how fast does routing migrate when they open? Identification comes from the structural breaks above. This is the leg that speaks to the inertia literature's stated limit, and its viability is conditional on the measurement in 4.0.
3. **Rent incidence, with gas netted.** Does intermediating pay? Fee yield against LVR against net return, by pool-asset role. Promoted from supporting to a headline candidate because item 1 of the old list vacated a slot and because this is the strongest genuinely unoccupied empirical position: no paper groups LP profitability by asset role, and **nobody has netted gas** except Cartea, Drissi and Monga for a single pool, where the flat per-operation cost implies net profitability has a size threshold, so no scalar answer exists. Framing correction: a centrality curse is **predicted**. LVR scales with return variance times marginal depth and is therefore largest exactly where depth is largest, and Yuan (2005) in our own corpus supplies the informational version, because a benchmark asset attracts informed traders and more informativeness is more adverse selection. Two attacks to pre-empt: the CEX-listing confound (hub status is nearly collinear with having a deep centralised reference market, and the standard reference-price filter deletes exactly the long-tail tokens that identify the effect), and gas as a mediator, because gas causally drives repositioning and repositioning is highest in hub pools. **Measured 2026-08-06, see `docs/finding-rent-incidence.md`.** Intermediation pays where both legs are major assets and loses where the native asset is paired with the long tail, which is 80% of the pool-days and the pairings the vehicle role rests on, so the thick-market externality is supplied at a loss. The predicted centrality curse is rejected on both venues, and the depth half of it fails on arithmetic before it reaches the data: in the constant-product closed form LVR as a share of capital is realised variance over eight and carries no depth term, so depth cancels in the rate and only survives in dollars. The size threshold does reproduce, with the gas rate on repositioning pool-days falling 63-fold from the smallest capital decile to the largest, though LVR and not gas is what makes the long-tail pools unprofitable.
4. **Cross-venue spillover from an architecture change.** Spillover to venues that did not change is non-mechanical and shares any macro episode with the treated venue, absorbing the confound that killed version 1's event study. Templates already read: Bessembinder, Hao and Zheng on off-venue spillovers; Klein and Song on cross-venue commonality after MTF entry.
5. **Fragmentation across venues with concentration in the asset.** Measured: the cross-venue share of intermediated routing rises from 1.2% to 61.1% count-weighted and 11.1% to 89.1% value-weighted across the sample. Motivating fact and a supporting result. Caution retained: split routing concentrating on deep pools is partly graph mechanics, so state what would falsify an economic reading.

**Retired.** The lagged-share persistence design lacks a licence on its own. A lagged dependent variable with fundamentals controls is the Chinn-Frankel specification whose coefficient the FX literature itself shows cannot separate switching costs from a serially correlated unobserved fundamental, so reporting a lagged coefficient as incumbency would reproduce the exact interpretive error this paper claims to overcome. It re-enters only paired with contemporaneous cost as a regressor and with the cost-dominance windows.

### 4.2 Measurement requirements

Non-negotiable, because getting these wrong invalidates everything above. Adopt named methodology, which also buys referee familiarity.

- **Route cost: build a three-benchmark ladder ourselves.** The construction is standard optimisation and nobody's proprietary contribution, and Angeris, Chitra, Evans and Boyd (published) supply the theoretical warrant that gas-aware optimal routing is mixed-integer convex, so production routers are necessarily heuristic and a measurable shortfall exists. Suboptimality as proportional shortfall of the realised route against benchmarks solved at fixed pool state: support-constrained (reoptimise splits only across pools the trade touched, isolating mis-splitting), full-venue (reoptimise across all pools without gas, adding venue omission), and gas-aware full-venue (fixed per-pool activation cost, mixed-integer). Use a direction-asymmetric gas model, since one swap direction deducts from output while the other shrinks the input budget. Report medians alongside means, because a few per cent of trades drive the entire mean.
- **Cost level: adopt Barbon and Ranaldo's definition** of total cost as slippage plus fee plus gas over notional, on hypothetical trades at a fixed notional grid, hourly, with gas as a unit count times median gas price. Their headline: validator gas dominates trader cost, ahead of classical price impact.
- **Depth: realised all-in cost at fixed notionals is primary; marginal-price displacement is a secondary structural descriptor.** The earlier plan to define depth as dollars to move the marginal price 10 and 50 bps then "aggregate" across venues was wrong twice over. Marginal-price displacement and realised average execution cost stand in a design-dependent relation (roughly a factor of two in constant product for small trades, different entirely for stableswap's flat-then-convex curve and for concentrated liquidity's tick-dependent piecewise shape, where large marginal depth can coexist with a costly range exit). And the economically correct aggregation across heterogeneous pools is the joint split optimisation, and a sum of per-venue depth numbers has no economic meaning. There is no accepted academic depth standard; our own SoK (Xu, Paruch, Cousaert and Feng, ACM CSUR) is the natural citation for design-specific slippage and is checkable locally since we are an author.
- **Gas per hop must be measured from receipts.** No verified per-additional-hop figure exists in any source consulted. This matters directionally: a two-hop vehicle route is mechanically more gas-expensive than one hop, so omitting gas biases the panel toward the vehicle route, which is the direction that would manufacture our result.
- **Separate MEV from routing shortfall.** Realised amounts embed sandwich losses while simulated counterfactuals do not, so flag sandwiched trades and report cost both ways. Do not condition naively on submission channel: a large share of sandwich victims migrate to private RPC within weeks, which makes channel an endogenously selected treatment and disqualifies it as a control.
- **Intent venues need separate treatment.** Batch-auction and RFQ settlements may be internalised against solver inventory, in which case no AMM counterfactual describes the user's alternative. Treat batch venues as a structurally different cost regime, and do not assume solver competition passes value through, since more solver entry can reduce welfare.
- **Symmetric split treatment.** Comparing an unsplit best-single-pool direct route against a realised split vehicle route is not like-for-like.
- **Transaction-time state.** Transactions earlier in a block move reserves and ticks; report the wedge if daily state is used anywhere.
- **Sign the venue exclusions.** Under full-venue logic an omitted venue mechanically flatters whichever route depends on covered venues, so state the direction of the bias as well as its share.
- **Endogeneity, answered where it can be.** Whether an asset becomes the vehicle because costs are low or costs are low because vehicle liquidity accumulated is answered by cost-dominance windows and cross-venue spillover. The cross-aggregator cross-section cannot answer it, since a snapshot of routers contains no variation in incumbency holding cost fixed.
- **Wash and arbitrage screens before any regression.** Round-trip exclusion is already implemented and mandatory: round trips ran 25.6% of multi-leg routes by count and 90.5% by value on the day inspected. The turnover-spike and volume-spike screens, arbitrage-cycle detection and organic-versus-MEV decomposition in the reference repo's `ddc.integrity` still need applying on top.

### 4.3 Verification gaps to close before the framing locks

Named because a plausible-sounding claim resting on an unread source is how this project has gone wrong before.

- **Flandreau and Jobst (2009)** went structural on currency networks and **reject strong lock-in** while confirming persistence. That is the closest prior claim to resolving the question this paper claims to open, and it is currently abstract-verified only. Highest-priority read.
- **Chu, Dowling and Li, "Impermanent loss in cryptocurrency," JIMF 160 (2026)** reportedly prices impermanent-loss risk in LP returns with pool-level controls, making it the paper most likely to already contain the cross-section item 3 needs. Read first-hand; a summary will not do.
- **SSRN was unsearchable during the prior-art sweep**, so finance-side working papers are unchecked. A referee's first move on a novelty claim is an SSRN search.
- **An untraced MetaMask multi-aggregator study** is structurally the cleanest natural experiment for router-choice questions and needs locating before any novelty claim near that margin.

## 5. Method discipline adopted from documented practice (node F)

Sourced from an R&D pass over reproducibility and specification-robustness practice; full sourcing in the agent output.

- **Delete-and-rebuild as the gate** (Gentzkow and Shapiro). A run is done when a fresh clone regenerates every number, table and figure with no manual steps. That is the definition of done.
- **Machine-readable decision registry.** Every analytical choice declared as a named parameter with alternatives enumerated. Mitton (RFS 2022) showed that with discretion over ten routine choices a researcher can report over 70% of *randomly generated* variables as significant determinants of leverage; the three choices that matter most are dependent variable, transformation, and outlier treatment, so those are mandatory-to-vary.
- **Specification curve per headline claim** (Simonsohn, Simmons and Nelson), with the dashboard showing which choices drive the result and a joint inference test. Curated to reasonable specifications; a padded combinatorial multiverse deflates visible dispersion.
- **Multi-agent replication as a bug detector only.** Demoted after the independent review, correctly: Menkveld et al.'s 164 human teams measured genuine researcher variation, whereas N LLM agents on one codebase measure code-generation noise. Presenting that to a journal as an econometric quantity would be process theatre. Retained internal use: run the estimate independently twice with separate contexts, and treat any disagreement as evidence that one run has a bug. Menkveld et al.'s finding that dispersion falls after peer feedback still justifies putting the critique round before estimates are fixed.
- **Specification lock plus deviation log**, replacing external pre-registration, and placed **after** an explicit exploratory phase. The review objected to the friction; the exploratory-first ordering answers that, since distributions, pool anomalies, and contract mechanics must be understood before specifications are fixed. Burlig (2018) shows PAPs carry no epistemic credit for archival data, so this claims none: it is an internal integrity device, needed because version 1 did silently reframe results after seeing them. Keep the audit trail, decline the binding commitment.
- **Report everything run** (Harvey, JF 2017). Every specification goes to an internal appendix; the drafting agent may not silently select.
- **Desk-reject filter, early.** JoF desk-rejects 43% before review. Before any polishing, one agent answers: what is the single novel contribution, and is it visibly large enough in the first two pages? A negative kills or reframes.
- **Rank-ordered internal referee** (Berk, Harvey and Hirshleifer): output must separate fatal from major from minor, every objection carrying a scientific argument. Undifferentiated flaw lists are penalised, since that is the failure mode LLM reviewers default to and the exact pathology the paper warns human referees against.

---

## 6. The graph

Nodes, with the paper/deck cycle explicit. Every node writes a committed file; every review node also answers the challenge-the-spec question.

```
A. Venue study .................... COMPLETE (section 1)
B. Domain literature .............. partially complete
     01_source_fidelity.md holds 14 papers, two independent reads each.
     Extend for: Eichengreen/Krugman inertia; LVR and rent incidence.
C. Definitions and measurement .... section 3. BLOCKING on everything below.
     RECURRING, not phase 0. Reopened by K, by I, and by any F result that
     the current definition cannot express. See the note below.
D. Cross-venue data layer ......... rebuild all measures on data/unified/.
     Full-panel cross-venue routing series. Validation apparatus (the moat).
E. Design + specification lock .... section 4 hypotheses, decision registry,
     enumerated alternatives, locked and hashed before F runs.
F. Empirics ....................... per E. Specification curves. Multi-agent
     NSE with the critique round before estimates fix.
G. Paper .......................... six sections, JFE invariants of section 1,
     pure-empirics lane, named rival mechanisms as the horse race.
     Output: docs/paper-spine.md (architecture, claim inventory with
     EXISTS/PENDING status, table shells, definitions text, horse race,
     plus the two convergence sections F and H read).
H. Deck ........................... derived from G.

        F <-> G <-> H IS ONE ITERATING CLUSTER, not a chain with a cycle on
        the end. G decides which results the narrative NEEDS; F decides which
        results the data can SUPPORT. Fix G first and it demands results the
        panel cannot identify; fix F first and it yields results with no
        narrative slot, which is how an empirical paper becomes a list of
        regressions. G <-> H has the same mutual pull: slides expose narrative
        gaps, paper detail exposes missing slides. All three may start in
        parallel and none is finished while another still moves.

        CONVERGENCE CONDITION, because a cycle without a stopping rule is a
        hang. Converged only when all four hold at once: every result F
        produces has a slot in G; every claim G makes rests on a result F has
        actually produced; every slide in H maps to a G section and adds no
        claim of its own; and one complete pass generates no new demand in
        either direction. Two consecutive passes changing nothing but wording
        means converged, and the work moves to I.

        CONVERGENCE IS NOT COMPROMISE (Java, 2026-08-06). The standard stays a
        JFE-level paper, so the cluster converges by MEETING that bar, never by
        lowering a claim until the three nodes agree. If a claim cannot be
        supported, it leaves the paper; it does not get softened until it fits.
        Escalation rule: if five full passes do not close the gap and the
        remaining distance is no longer shrinking, stop and hand it to Java
        rather than declaring convergence on a weaker claim.
I. Cross-family review ............ Codex/Gemini. Feeds back into C..H.
     Desk-reject filter first, then rank-ordered referee.
        C IS THE HIGHEST-LEVERAGE NODE AND IT WAS THE ONE THAT COULD NOT
        LEARN. Java's diagnosis, 2026-08-06, sharper than the missing-generator
        one it followed. The specification in this graph comes from C, which
        fixes definitions and measurement, and from E, which screens candidates.
        Both ran ONCE in an early pass. E screens the list in section 4.1, but
        that list was written in the same early pass, so E cannot regenerate
        what it screens. The result is a graph whose definitions are frozen at
        the moment of least knowledge.

        The evidence is that measuring the vehicle role as network betweenness
        was not a new candidate RESULT, it was a better DEFINITION. Vehicle
        extent had been operationalised as a volume share, which is a proxy for
        the concept, when the concept is that a vehicle lies on the paths
        between other assets. That correction belongs in C and could only
        arrive from outside the graph because C was closed.

        C IS THEREFORE THE MOST LITERATURE-DEPENDENT NODE, not merely one that
        cites. Betweenness is the right definition BECAUSE Flandreau and Jobst
        model currency use as a network with externalities, so the definition is
        what connects this paper to the conversation it wants to join. A
        definition chosen without that reading produces a measurement nobody in
        the field can engage with, however clean it is. So C reads the corpus
        for how the target literature FORMALISES the object, and not only for
        what it found.

        REOPENING RULES, so C recurs on a trigger and not on a whim. C reopens
        when K proposes a measure the current definition cannot express, when I
        rejects a claim on definitional grounds, and when an F result is true
        but uninteresting because the definition made it close to a tautology,
        which is exactly what happened to native intermediation is cheaper.

K. Ideation ....................... proposes what nobody asked for. ADDED
     2026-08-06 on Java's diagnosis that the graph had no generator.

        WHY K EXISTS. Every other node either builds what is specified or
        attacks what is built. A..D construct, E screens, F estimates, G and H
        write, I rejects, J gates. Nothing PROPOSES. The symptom was that the
        two best ideas of a long session, measuring the vehicle role as network
        betweenness and separating succession from fragmentation with a
        Herfindahl index over vehicle shares, both came from Java and neither
        came from the graph. A workflow whose only creative input is its owner
        is not an agentic workflow, it is a very elaborate executor.

        WHAT K DOES, and the constraints that stop it being a platitude
        generator. It reads the DATA's affordances, meaning what is measurable
        here that is not being measured, and it reads the literature for
        concepts that exist but have not been operationalised on this data. Each
        proposal must name an estimand, sketch its identification, state what
        would falsify it, and say which existing result it would displace or
        support. A proposal with no identification sketch is an idea and not a
        candidate, and is rejected by K itself before it reaches E.

        HOW K IS SCORED. By whether its proposals survive node I, not by how
        many it makes. K runs CONTINUOUSLY rather than once, because the
        affordances change as the data layer grows: centrality only became
        proposable once the unified layer covered every venue, and the
        succession-against-fragmentation question only became sharp once
        centrality existed.
J. Gates .......................... run on every G/H artefact (section 7).
```

Ordering: A and B complete before C. C blocks D. D blocks E. E locks before F. F feeds G. G and H iterate. I runs on C, on E before the lock, and on G/H. Nothing proceeds on a guess.

---

## 7. Gates on every deliverable

- **Language, and it stays a real gate.** `python3 ~/glotl/scripts/style_gate.py --corpus ../defi-dominant-currency/lit/jfe-exemplars --target <file> --ignore paper/domain_terms.txt --fail-on-outlier`. Three layers: pattern metrics calibrated leave-one-out against the 14 papers, n-grams absent from the whole corpus, and log-odds over style vocabulary. Catalogue encoded from Wikipedia:Signs_of_AI_writing. Measured baseline for my own prose: em-dashes ran 10x the corpus maximum against a corpus median of zero, and "X, not Y" ran 39x the maximum.

  The independent review called this cargo-culting on the grounds that referees reject for weak identification and never for punctuation. **Java overrules that, and the argument is availability bias.** Before generative models, em-dash density was not a signal about anything, so nobody rejected on it. In 2026 a manuscript that reads as machine-written raises a referee's eyebrow about everything else in it, including whether the analysis was done carefully. The prose is evidence about the author's care, so the gate stays binding. Two guards against the review's legitimate worry: the gate may never be satisfied by convoluted phrasing (a flagged sentence gets rewritten simpler), and it never outranks substance in review priority. It also supplements and does not replace the house-voice blocklist, since roughly half those rules are voice and not venue anomaly.
- **Deck craft.** Load `slide-deck-authoring` and `diagram-design` before authoring; failing to do so last time produced 17 tables against one image. Data-overview slide mandatory. Every result a plot or diagram first, table only in backup. Phrases and short clauses, never full sentences, on core and backup slides alike. Inline citations throughout, plus a references slide. p-values as bare parentheses, `(0.003)`, and `(0.000)` below 0.001. No TODO frames ship.
- **Reproducibility.** Delete outputs, rebuild from one script, byte-compare. Pinned manifest, RNG seeds, execution order, auto-generated README.
- **Cleanup.** Superseded artefacts deleted in the same commit.

---

## 8. Open decisions for Java

1. Title: **DECIDED by Java 2026-08-06** — "The Making of Dominant Vehicle Currencies: Evidence from DeFi".
2. Pure-empirics lane: **ALREADY DECIDED, do not reopen.** Java settled this when the graph was first proposed, after rejecting an earlier "model-first per JFE convention" claim of mine as presumptuous. Re-derived from the 14 exemplar PDFs rather than from a summary: 6 of 14 have no formal model, and of the 3 that pair a model with data only 1 leads with theory. The JFE author profile says "IF the paper has a model, make the model do work", which is a conditional that I had flattened into an imperative. So: purely empirical is the lane, a model is added only if it raises the acceptance odds and only if done properly, and this line exists to stop the question resurfacing a third time.
3. Which of the five candidate results lead. **The numbering in an earlier version of this item referred to a superseded list and contradicted section 4.1, which node H flagged as blocking its slide order.** Reconciled against 4.1's numbering, which is authoritative: (1) the intermediation transition, (2) cost-dominance windows, (3) rent incidence with gas netted, (4) cross-venue spillover from an architecture change, (5) fragmentation with concentration in the asset. The earlier item also ranked "cross-aggregator routing choice" second, which section 4.0 retires outright on the ground that the entry contract identifies the executor and not the aggregator, so it cannot be ranked at all. Standing recommendation for Java, who owns this decision: **(1) the intermediation transition leads**, because it is unoccupied, it is measured on the full panel, and it shows a sterling-to-dollar transition over six years instead of decades; **(4) cross-venue spillover is second**, because spillover to venues that did not change is non-mechanical and shares any macro episode with the treated venue, which absorbs the confound that killed version 1's event study; **(2) cost-dominance windows supply the mechanism**, and its viability is conditional on the measurement work in 4.0; (3) and (5) support. Architectural results stay as the feasible-set layer and never lead. Java may reorder any of this in one sentence.

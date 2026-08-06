# Research workflow: paper and talk on dominant vehicle currencies

Version 2, 2026-08-05. Replaces `docs/nbc-2026-deck-pipeline.md` (version 1), whose single-venue empirics and deck were both binned. This is a graph. The paper and the deck inform each other, and evidence can send work back to design.

Every claim in the "grounding" column below was measured or read in this project. Where something is an assumption, it says so.

---

## 0. Standing rules

**Portability.** This file and every node's output is a plain tracked file in this repo. No node's real state may live only inside one model's session. Whatever executes a node reads this file plus the previous node's committed output and continues.

**Sync.** Commit and push after every node. An unpushed completed node counts as unfinished.

**Supersede means delete.** When a new version of any artefact exists, delete the old one in the same commit. Git history is the archive. Two live copies of a deck already caused a full review cycle to be spent on the wrong file.

**Challenge the spec itself, beyond conformance to it.** Every review node must answer: *is any requirement here wrong, unnecessary, or harmful to the deliverable's purpose?* A pipeline that only checks conformance will propagate a bad requirement to the deliverable. That is exactly how a slide reconciling the talk against its own submitted abstract survived three review phases: the requirement was written into the spec, so reviewers verified its presence instead of questioning its existence.

**Conformance is a LOOP and never a step, and it closes every writing node.** `python scripts/check_deliverable_conformance.py` runs the whole surface behind one command and exits non-zero on any failure: venue optics measured against the 14 published exemplars, prose conventions measured against the same corpus, house voice, provenance of every number, structural resemblance, spine agreement, and a clean compile of both the paper and the deck. It MUST run after ANY content change to either deliverable, and a node that changed content is not complete until it exits zero. `--brief` prints an agent brief naming exactly what is short, so the correction is dispatchable without anyone diagnosing it first.

The reason it is a loop is that content and conformance interfere. Every rewrite for content can break register, structure and resemblance again, and the failure mode this replaces is real: the paper was written, optics were measured once, an agent was dispatched by hand to fix what the measurement found, and the next content change silently undid part of it. A check that depends on someone remembering to dispatch it is not a check.

**Order nodes by the cost of redoing them, and freeze a node's input before running an expensive one.**

**Expensive nodes have one executable owner.** A long build must acquire a non-blocking job lock before it reads or writes shared artifacts, record its process and command in that lock, and refuse an overlapping launch. Every final artifact is installed from a unique temporary sibling by atomic replacement; a fixed `.tmp` name is unsafe because two processes can truncate the same file before either replaces it. After an interruption, the workflow validates the artifact and its manifest before deciding whether to resume or recompute. The canonical implementation is `ddvc.runtime`, not a session note or an agent-specific convention. This rule was made executable after two V4 enrichment processes were found writing an overlapping date range on 2026-08-06.

Two classes of node, and the graph must not mix them up.

*Idempotent gates* cost nothing to re-run and carry no state: measurement, linting, conformance. They run continuously, after every change, and re-running them on unchanged input is free.

*Non-idempotent transforms* consume a settled input and produce an artefact that has to be regenerated in full when that input moves: the prose rewrite (node P), deck authoring (H), figure polish. Running one of these before its input freezes buys rework in direct proportion to how much the input still moves.

This was violated on 2026-08-06 and the cost was legible in advance. Node P was launched while the horse race still carried one account with *no completed test at all* and another whose *discriminating test is blocked by a measure*, and while section 5 of the paper itself ends "the ranking here moves when the six-venue panel returns its own". Section 5's prose was therefore scheduled to be rewritten twice before anyone had written it once. Three of the four verification gaps in section 4.3 were also still open, and two of them sit under results that lead the paper.

**FREEZE GATE on node P.** It does not start until all four hold:
1. Every claim that leads a section has a completed test, so no headline rests on "blocked" or "no completed test".
2. Every source the paper CITES AND CHARACTERISES has been read first-hand and its characterisation checked (section 4.3). This is accuracy, not novelty; novelty sweeps are off.
3. Every open decision in section 8 is decided.
4. Two consecutive F <-> G passes generate no new claim and retire none.

**Research-state reconciliation is executable.** After every F to G pass, update `docs/findings-freeze.md` and run `python scripts/audit_findings_freeze.py`. The audit checks the live artefacts, their input-aware provenance, panel coverage, retired estimands in the refresh graph, and the unchanged-pass counter. Commit order, document recency, and a green paper build are not evidence that findings are frozen. This gate was added after prose work began while the full panel manifest still described 18,120 rows, v4 was priced on 30 of its historical days, and the downstream refresher still ran estimands the definition audit had retired.

**Validation state must be causally timed.** Reproducing a realised outcome is a valid quoter or simulator check only when every state variable contains information available immediately before that observation. Calendar-day membership is not enough, and block membership is not enough either. Replay all state-changing events by block and log index, use a strict-before lookup, and include a regression test with a state change between two observations. Both concentrated-liquidity validators once paired the preceding swap's price with the validation day's final liquidity map; this leaked later liquidity into earlier quotes. One shared event-order owner now interleaves V3 mints, V3 burns, V4 signed liquidity changes and swaps. Strict replay covers 1,206 V3 swaps and 4,218 V4 swaps, all inside 1%; V4's p99 absolute error is 0.00000039% and its maximum is 0.000998%. The first “own-block” triangle instrument then repeated the same class of error at a finer level: ordering only by block and using `bisect_right` included the target swap's own post-state and could include later logs from the same block. Strict block-log ordering raised the under-one-minute verdict-flip rate from 15.56% to 22.49%. Reverse state reconstruction has an additional contract: a timeline of per-event pre-states must return the first event at or after the target's pre-state, or the preceding event's post-state. Returning the last pre-state at or before the target omits the preceding swap's effect, while timestamp-only ordering also confounds events in the same second. A coherent unwind is not proof that no mint, burn or direct transfer occurred: reserve continuity must be observed against the preceding stored state, and a missing predecessor is unverifiable support, not a clean period. A validator also has to sample the estimand's population: direct-pool swap times are opportunity snapshots, not realised multi-leg routes, and whole transactions are not reconstructed route components, however precisely their state is ordered.

**Canonical identifiers own aggregation; display labels never do.** Canonicalise machine keys before selecting endpoints, ranking pairs or grouping observations, enforce the expected key uniqueness on every generated shard and final panel, and attach human-readable labels only after aggregation. A display field is metadata and cannot be allowed to split an economic cell. This became an executable rule after native ETH and WETH were correctly unified at the address layer but the route-cost pair selector continued grouping on `ETH` and `WETH`. The result was 1,372,248 duplicated quote cells in the assembled panel, all with multiplicity two. The corrected selector aggregates only on canonical endpoint addresses, rejects components with non-unique canonical endpoints and chooses one deterministic label after the economic cell is fixed.

**Market maturation is a decomposition, not one trend.** A rise in cross-venue paths measures opportunity-set integration. A decline in realised-to-best cost gaps within a fixed reachable set measures search and pool selection. A decline relative to the best direct or alternative-vehicle path measures path and intermediary selection. A change in which currency intermediates routes measures vehicle succession. None stands in for another, and “the market became more efficient” is admissible only after the relevant margin is named. The routing-efficiency branch therefore reports integration, within-vehicle search, path selection and vehicle choice as separate estimands before it asks whether they move together. Quote-size interpolation also has an identity contract: the winning intermediary, venue sequence and exact pool sequence must be unchanged at the bracketing sizes. If any of them switches, interpolating the two winners constructs a path that was never quoted and the cell is quarantined. Even a stable-path interpolation remains provisional until exact-size transaction-state re-quoting validates its error distribution.

Until then, write to `memo/` freely. Discovery register is correct there, because a record is judged on whether it is complete and traceable and never on whether it reads like the venue.

**The transform must be a FUNCTION of its input, never an edit to it.** Node P writes `paper/` FROM `memo/` and leaves the memo untouched. That is what makes it re-runnable: when a finding changes, the affected section is regenerated rather than patched, and patching is the mode that was measured not to converge. Rewriting the memo in place would destroy the input and make the second run impossible.

**A gate that cannot pass yet must REPORT and not FAIL.** While `paper/` does not exist, the shape gate measures the memo and reports the distance the rewrite has to travel, which is useful. Wiring that distance into a red build would leave conformance permanently red, and a permanently red gate trains everyone to ignore it, which is how a real failure gets missed later.

**Conventions come from the corpus in BOTH directions, and one direction alone does not converge.**

*Subtractive half, already in place.* When a stylistic tell is suspected, it is added as a PROBE to `scripts/measure_prose_conventions.py`, and `scripts/find_prose_outliers.py` discovers tells nobody named first. Both report the draft's rate per thousand words beside the published corpus and flag only what no published paper reaches.

*Positive half, added 2026-08-06 because the subtractive half was measured to be insufficient.* `scripts/measure_venue_shape.py` measures what venue prose IS and reports target bands: sentence length and its long tail, commas, subordinate clauses, share of sentences carrying none, sentences per paragraph, heading grammar, heading STRUCTURE (subsections per section, and which sections carry none), and the share of sentences that open on information the previous sentence already carried.

The grounding is a measured failure. Forty-two clean deletions of a banned construction moved the discovered-tell count by a third and moved both gates by nothing, because deleting a tell never installs a convention. Three findings from that round:

- **The draft was lexically saturated.** Nearly every candidate replacement was already at or past its own corpus ceiling (`bound` -18 occurrences of headroom, `threshold` -19, `quote` -35, `reading` -28). A document with no vocabulary headroom has a sentence-architecture problem, and word substitution has nowhere to move.
- **Shape survives synonym substitution.** Rewriting "and not at economics" as "and never at economics" changed the word and kept the banned correction-by-negation shape exactly.
- **Over-correction is invisible to the subtractive gates.** A first pass on section 3 cut the median sentence from 26 words to 14 and the venue's long tail to zero. Every subtractive gate approved. Only the positive bands caught it.

*Both gates bind.* A section is done when it sits inside the shape bands AND clears the two discovery gates. Neither alone is sufficient, and the positive bands are aimed at the venue's interquartile range, never at zero.

*A target computed from a varying corpus is not a target.* `measure_venue_shape.py` treats an exemplar that fails to extract as FATAL. The first version swallowed timeouts, so bands were silently computed from twelve papers instead of fourteen and moved between runs on identical inputs, and a section measured against one run was judged against a different ruler on the next.

It remains true that the corpus uses em dashes, "rather than" and three-item lists freely, so those are venue conventions and any ban on them is an author preference that must be labelled as one and not confused with venue conformance.

**A reported comparison is not a result until it is estimated conditionally.** Raw rates, shares and differences identify nothing on their own, since composition, the number of candidates, calendar conditions and pair heterogeneity all move them. Every headline comparison carries a specification with fixed effects, controls and clustered standard errors, and `fixed_effects` and `std_errors` are measured features in the optics comparison for exactly this reason. The failure this prevents: a turnover hazard ratio of 1.17 was reported from unconditional pair-day rates before any absorption was applied.

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

Measured on all 2,277 days after enforcing clean reconstructed routes: the share of economic multi-leg routes spanning more than one venue rises from **1.4% in 2020 to 60.6% in 2026** by count and from **15.4% to 89.4%** by value. Economic multi-leg incidence itself stays between 14.3% and 20.4% of all clean routes, so integration changes the venue composition of paths much more than the frequency of indirect routing. Complexity changes too: routes with more than two swap legs rise from **10.3% to 39.4%**, mean legs from **2.12 to 3.23** and mean venues from **1.02 to 1.80**, with the acceleration after 2024. A balanced perimeter restricted to the same five venue families gives a smaller but still clear 2022-to-2026 count rise from **19.1% to 43.6%**, while value moves only **49.4% to 55.5%**, routes above two legs **15.1% to 20.0%**, mean legs **2.25 to 2.39** and mean venues **1.22 to 1.47**. Integration among incumbent venues is therefore real; later venue entry explains much of the full series' late value and complexity surge. Swap-leg count combines sequential hops with pool splitting, so it measures route complexity and not optimisation quality. Studying one venue in isolation becomes progressively wrong, but cross-venue and complexity growth alone do not identify better routing.

The routing-efficiency attack separates four margins. Integration is the cross-venue series above. Within-vehicle search compares an exact two-leg realised route with the frontier through the same intermediary, retaining a comparison only when every frontier venue lies inside the route's observed venue set. Path selection expands that frontier to direct and alternative-vehicle paths. Vehicle succession remains the realised intermediary-share result. The first margin is descriptive, the next two are conservative observed-venue-reach diagnostics, and none becomes a finding until the counterfactual frontier is repriced at exact realised size and transaction state. The preliminary grid matcher now carries the winning pool identities and refuses to blend quote-size endpoints when the intermediary, venue sequence or pool sequence changes. The market-maturation test first estimates validated search and path shortfalls within fixed endpoint, vehicle, reach and notional cells, then tests whether their time compression is larger on complex or cross-venue routes, and finally adds relative search performance to the succession specification. Aggregator attribution is conditional on executor and quote-authorship coverage; calendar improvement alone is named market routing maturation.

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

1. **The intermediation transition, measured.** Which asset type intermediates, and has the role migrated from the native platform asset to the stable numeraire? Measured on the full panel: stable excess use rises above native excess use, and the count transition from 2024 to 2026 occurs inside both single- and cross-venue routing regimes. Raw value composition is less uniform: in 2026 stable leads native on single-venue value but native remains larger on cross-venue value. The lead result is therefore excess use relative to endpoint demand, with count and value composition reported separately instead of being collapsed into one succession claim. This is ours, the framing is unoccupied, and it shows a transition over six years instead of decades. Leads the paper.
2. **Cost-dominance windows.** Do windows exist in which an incumbent route is strictly cost-dominated on an executable all-in basis while its incumbency holds, and how fast does routing migrate when they open? Identification comes from the structural breaks above. This is the leg that speaks to the inertia literature's stated limit, and its viability is conditional on the measurement in 4.0.
3. **Rent incidence, with gas netted.** Does intermediating pay? Fee yield against LVR against net return, by pool-asset role. Promoted from supporting to a headline candidate because item 1 of the old list vacated a slot and because this is the strongest genuinely unoccupied empirical position: no paper groups LP profitability by asset role, and **nobody has netted gas** except Cartea, Drissi and Monga for a single pool, where the flat per-operation cost implies net profitability has a size threshold, so no scalar answer exists. Framing correction: a centrality curse is **predicted**. LVR scales with return variance times marginal depth and is therefore largest exactly where depth is largest, and Yuan (2005) in our own corpus supplies the informational version, because a benchmark asset attracts informed traders and more informativeness is more adverse selection. Two attacks to pre-empt: the CEX-listing confound (hub status is nearly collinear with having a deep centralised reference market, and the standard reference-price filter deletes exactly the long-tail tokens that identify the effect), and gas as a mediator, because gas causally drives repositioning and repositioning is highest in hub pools. **Measured 2026-08-06, see `docs/finding-rent-incidence.md`.** Intermediation pays where both legs are major assets and loses where the native asset is paired with the long tail, which is 80% of the pool-days and the pairings the vehicle role rests on, so the thick-market externality is supplied at a loss. The predicted centrality curse is rejected on both venues, and the depth half of it fails on arithmetic before it reaches the data: in the constant-product closed form LVR as a share of capital is realised variance over eight and carries no depth term, so depth cancels in the rate and only survives in dollars. The size threshold does reproduce, with the gas rate on repositioning pool-days falling 63-fold from the smallest capital decile to the largest, though LVR and not gas is what makes the long-tail pools unprofitable.
4. **Cross-venue spillover from an architecture change.** Spillover to venues that did not change is non-mechanical and shares any macro episode with the treated venue, absorbing the confound that killed version 1's event study. Templates already read: Bessembinder, Hao and Zheng on off-venue spillovers; Klein and Song on cross-venue commonality after MTF entry. **Built and measured 2026-08-06, see `docs/finding-cross-venue-spillover.md`, and the second half of that claim did not survive contact with the data.** Restricting the outcome to untreated venues does exclude the mechanical migration of activity onto the new venue, which the selection table confirms. It does not difference out a macro episode, because the untreated venues are most of the market: at the V4 launch the untreated-venue estimate of -0.293 (0.000) recovers 85% of the all-venue estimate of -0.346 (0.000), so the restriction removes almost nothing. The Merge placebo fires on the new-pair outcome at (0.000) and on route share under the donut specification at (0.000), passing cleanly only on betweenness. What the exercise leaves standing is a bounded null on betweenness at the V3 launch and a descriptive contrast between the two launches, and the identified version needs a within-day control group that holds the calendar fixed.
5. **Fragmentation across venues with concentration in the asset.** Measured on clean routes: the cross-venue share of intermediated routing rises from 1.4% to 60.6% count-weighted and 15.4% to 89.4% value-weighted across the sample, while economic multi-leg incidence is broadly flat. Inside the balanced five-venue perimeter the count rise remains, 19.1% to 43.6% from 2022 to 2026, but the value share is nearly flat after 2024. The native-to-stable count transition from 2024 to 2026 occurs inside both single-venue and cross-venue strata, so movement into the integrated regime is not a complete composition explanation. Motivating fact and a supporting result. The series measures path composition, not order splitting or optimisation quality, so it cannot be called routing efficiency.

**Retired.** The lagged-share persistence design lacks a licence on its own. A lagged dependent variable with fundamentals controls is the Chinn-Frankel specification whose coefficient the FX literature itself shows cannot separate switching costs from a serially correlated unobserved fundamental, so reporting a lagged coefficient as incumbency would reproduce the exact interpretive error this paper claims to overcome. It re-enters only paired with contemporaneous cost as a regressor and with the cost-dominance windows.

### 4.2 Measurement requirements

Non-negotiable, because getting these wrong invalidates everything above. Adopt named methodology, which also buys referee familiarity.

- **Route cost: build a three-benchmark ladder ourselves.** The construction is standard optimisation and nobody's proprietary contribution, and Angeris, Chitra, Evans and Boyd (published) supply the theoretical warrant that gas-aware optimal routing is mixed-integer convex, so production routers are necessarily heuristic and a measurable shortfall exists. Suboptimality as proportional shortfall of the realised route against benchmarks solved at fixed pool state: support-constrained (reoptimise splits only across pools the trade touched, isolating mis-splitting), full-venue (reoptimise across all pools without gas, adding venue omission), and gas-aware full-venue (fixed per-pool activation cost, mixed-integer). Use a direction-asymmetric gas model, since one swap direction deducts from output while the other shrinks the input budget. Report medians alongside means, because a few per cent of trades drive the entire mean.
- **Cost level: adopt Barbon and Ranaldo's definition** of total cost as slippage plus fee plus gas over notional, on hypothetical trades at a fixed notional grid, hourly, with gas as a unit count times median gas price. Their headline: validator gas dominates trader cost, ahead of classical price impact.
- **Normalise counterfactual cost by input notional.** Dividing an output difference by the realised output makes the denominator endogenous to route performance and mechanically magnifies the measured gap on the worst routes. Convert both outputs to the same value unit at the same state, take their difference and divide by input notional. An output-shortfall ratio may remain a quoter diagnostic, but it is not the economic cost estimand.
- **Depth: realised all-in cost at fixed notionals is primary; marginal-price displacement is a secondary structural descriptor.** The earlier plan to define depth as dollars to move the marginal price 10 and 50 bps then "aggregate" across venues was wrong twice over. Marginal-price displacement and realised average execution cost stand in a design-dependent relation (roughly a factor of two in constant product for small trades, different entirely for stableswap's flat-then-convex curve and for concentrated liquidity's tick-dependent piecewise shape, where large marginal depth can coexist with a costly range exit). And the economically correct aggregation across heterogeneous pools is the joint split optimisation, and a sum of per-venue depth numbers has no economic meaning. There is no accepted academic depth standard; our own SoK (Xu, Paruch, Cousaert and Feng, ACM CSUR) is the natural citation for design-specific slippage and is checkable locally since we are an author.
- **Gas per hop must be measured from receipts.** A two-hop vehicle route is mechanically more gas-expensive than one hop, so omitting gas biases the comparison toward the vehicle route and makes direct-dominance incidence a lower bound. A single per-hop constant is still insufficient for final all-in estimates: gas must vary by route topology, venue and date, using receipts and historical gas prices.
- **Separate MEV from routing shortfall.** Realised amounts embed sandwich losses while simulated counterfactuals do not, so flag sandwiched trades and report cost both ways. Do not condition naively on submission channel: a large share of sandwich victims migrate to private RPC within weeks, which makes channel an endogenously selected treatment and disqualifies it as a control.
- **Intent venues need separate treatment.** Batch-auction and RFQ settlements may be internalised against solver inventory, in which case no AMM counterfactual describes the user's alternative. Treat batch venues as a structurally different cost regime, and do not assume solver competition passes value through, since more solver entry can reduce welfare.
- **Symmetric split treatment.** Comparing an unsplit best-single-pool direct route against a realised split vehicle route is not like-for-like.
- **Transaction-time state.** Transactions earlier in a block move reserves and ticks; report the wedge if daily state is used anywhere.
- **Sign the venue exclusions.** Under full-venue logic an omitted venue mechanically flatters whichever route depends on covered venues, so state the direction of the bias as well as its share.
- **Endogeneity, answered where it can be.** Whether an asset becomes the vehicle because costs are low or costs are low because vehicle liquidity accumulated is answered by cost-dominance windows and cross-venue spillover. The cross-aggregator cross-section cannot answer it, since a snapshot of routers contains no variation in incumbency holding cost fixed.
- **Wash and arbitrage screens before any regression.** Round-trip exclusion is already implemented and mandatory: round trips run 12.7% of multi-leg routes by count and 21.7% by value on the median of 79 sampled days, reaching 25.9% and 91.3% on 2025-12-06, the worst. The turnover-spike and volume-spike screens, arbitrage-cycle detection and organic-versus-MEV decomposition in the reference repo's `ddc.integrity` still need applying on top.

### 4.3 Verification gaps to close before the framing locks

Named because a plausible-sounding claim resting on an unread source is how this project has gone wrong before.

- **Flandreau and Jobst: CLOSED 2026-08-06, read first-hand.** Verified in `literature/text/2009-FlandreauJobst2009Empirics-*.txt`, and every claim the paper makes about them holds.
  - The number is right. Section IV.A: *"Table 3, column III, implies that γ1γ2=0.463, which is smaller than 1. The data thus suggests that there is persistence but no lock-in effects."*
  - The degree-statistic characterisation is right. Their currency-status variable is literally *"Number of Markets Where Given Countries' Currencies are Traded"* (Table 1 heading), so it counts quoting markets and is silent on how much trade routes through a currency, which is what our differentiation sentence asserts.
  - γ1γ2 is the feedback between international circulation and the interest rate, as the paper states.

  **Two things the read surfaced that were NOT known before.**

  *Citation version, needs a decision.* The bib entry `FlandreauJobst2006Empirics` is the CEPR Discussion Paper 5529 (2006), so the paper renders "Flandreau and Jobst (2006)". The deck's reference slide says "Flandreau and Jobst (2009), *The Economic Journal*". These disagree in a shipped deliverable. The published article is EJ 119(537), 2009. A referee who knows this literature knows the EJ version exists, and citing the discussion paper for a number that appears in a published article invites the question of why. Cite the 2009 EJ article and re-verify that Table 3 column III carries the same 0.463 there, since the provenance comment currently points at the discussion paper's table.

  *An interpretive bridge the paper does not currently make.* F&J's persistence regime is not just "slow"; they describe it as a state in which *"the country has higher interest rates and lower popularity than is warranted by the long-run equilibrium"*, with formerly minor powers experiencing *"a delayed rise to monetary leadership"*. That is the challenger's delayed rise. This paper measures the mirror image, the incumbent's delayed fall, and it can condition on the cost state where they cannot. The two are the same adjustment process observed from opposite ends, which is a sharper relation than "closest empirical precedent" and is worth one sentence in the introduction.

  *The number reconciles, and HOW it reconciles is a warning.* 0.463 = 0.89 x 0.52, matching the γ1 and γ2 that F&J state in their own prose for column III. The extracted Table 3 in `literature/text/` disagrees: its γ1 row reads (-1.09, -0.87, -0.91), which would give 0.473, and its stated γ1 list in prose (-0.89, -0.91, -1.12) is a third ordering. The table extraction is column-scrambled by the PDF reader, so **a number read out of an extracted table in `literature/text/` is not verified**, and only the surrounding prose is. The paper's provenance comment currently reads "Table 3 column III", which points at the one representation that cannot be trusted. Point it at section IV.A, where F&J state the product in words, and re-verify against the published EJ table before submission.

  **Do NOT map θ onto γ1γ2 numerically.** They are not on the same scale: γ1γ2 is a long-run structural product from a two-equation feedback system, θ is a one-day-horizon hazard ratio. The honest statement is that both address whether the system returns to cost-efficiency, that F&J answer "it converges, slowly" from quotation counts with no counterfactual, and that this paper answers the same question with the declined route priced. Any stronger equivalence would be the kind of unearned bridge this section exists to prevent.
**Novelty sweeps are OFF. Standing decision by Java, 2026-08-06, and it overrides the three gaps that used to sit here.**

Novelty is overrated and no result gets binned because someone else may have reached it. Corroborating an existing claim on better data is a contribution, and this paper's data prices the road not taken, which is the thing the FX literature cannot do whoever else has tried. A result stands or falls on whether it is measured correctly here.

Three former "gaps" are struck, and they were all novelty policing rather than accuracy:
- A working-paper sweep, SSRN or otherwise. Working papers are not a bar this paper has to clear, nothing here may depend on one, and reading a pile of them before forming a view is how a project inherits someone else's framing. Do NOT run one, and do not raise it again, unless Java explicitly asks.
- Chu, Dowling and Li on impermanent loss, previously flagged as the paper most likely to pre-empt the rent-incidence cross-section. If the rent result is right it is right, and if we do not cite them there is nothing to verify.
- The untraced MetaMask multi-aggregator study, flagged for the same reason.

**What survives, because it is a different obligation.** Any source this paper CITES and CHARACTERISES must be read first-hand and the characterisation checked. That is accuracy and not novelty, and it is where the real risk lives: a mis-stated precedent is a referee's first target, and it is the failure this project has actually had. Verify what we say about what we cite. Do not go looking for who else got there first.

**First check under the accuracy framing found a real error, 2026-08-06.** The load-bearing LVR closed form in equation `eq:lvr` was cited to `MilionisMoallemiRoughgarden2023Myersonian`, "A Myersonian Framework for Optimal Liquidity Provision in Automated Market Makers". That paper is 10,831 words and contains ZERO occurrences of "rebalanc", "loss-versus" or "impermanent"; it is about Bayesian updating, no-trade gaps and the bid-ask spread under asymmetric information. The result actually comes from Milionis, Moallemi, Roughgarden AND ZHANG, "Automated Market Making and Loss-Versus-Rebalancing" (arXiv 2208.06046), a different paper with the same three lead authors, which is exactly why it was confusable. Corrected in `05-liquidity.tex` and in the provenance comment in `05-rivals.tex`, with the correct entry added to the bib.

The formula itself is right: instantaneous LVR of one eighth of the variance rate times pool value is standard for the constant-product invariant. So the rent-incidence result stands unchanged and only the attribution was wrong. That is the good case, and it is worth noticing how much rested on it: `eq:lvr`, `eq:lvrrate`, the -5.96% median net yield, and the arithmetic rejection of the centrality curse, which turns on LVR as a share of capital carrying no depth term.

The lesson generalises. The exposure was never that somebody else had reached the result first; it was that the paper said something false about a source it leans on, in a paper whose whole substitute for identification is a validation apparatus. Check what we assert about what we cite, especially where several papers share authors.

Independence is the point. Form the reading from our own measurement, then check the sources we lean on.

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
P. Prose rewrite .................. GATED. Does not start until the freeze gate in
     section 0 passes. Writes paper/ FROM memo/, per
     section, against the shape bands and the two discovery gates, and never
     edits memo/. Re-runs by regenerating a section whenever G changes it.
     A second "clean" copy was tried on 2026-08-06 and deleted the same day
     (a92295d). The standing rule applies to the paper as much as to the deck:
     two live copies cost a review cycle spent on the wrong file, and the
     content of record is git history, not a parallel directory.
     What does NOT work is word-level correction; see the standing rule above.
     The rewrite is at sentence and paragraph shape, which is why it is a
     rewrite node and not a lint.

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
        cites. Betweenness was justified BY APPEAL TO Flandreau and Jobst
        modelling currency use as a network, a paper absent from the corpus, so
        that justification is currently uncited, so the definition is
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

Graph contract: A and B feed C; C and K reopen each other; C sends data-changing definitions through D and then E; F, G and H iterate in both directions; I can return a defect to C, E, F, G or H; J runs continuously; P remains closed until the findings freeze. The active edge, parent loop and next edge live in the machine-readable frontmatter of `docs/findings-freeze.md`, so a long-running D build never makes the project look as though it has left C <-> K or entered prose.

---

## 7. Gates on every deliverable

- **Language, and it stays a real gate.** `python3 ~/glotl/scripts/style_gate.py --corpus ../defi-dominant-currency/lit/jfe-exemplars --target <file> --ignore paper/domain_terms.txt --fail-on-outlier`. Three layers: pattern metrics calibrated leave-one-out against the 14 papers, n-grams absent from the whole corpus, and log-odds over style vocabulary. Catalogue encoded from Wikipedia:Signs_of_AI_writing. Measured baseline for my own prose: em-dashes ran 10x the corpus maximum against a corpus median of zero, and "X, not Y" ran 39x the maximum.

  The independent review called this cargo-culting on the grounds that referees reject for weak identification and never for punctuation. **Java overrules that, and the argument is availability bias.** Before generative models, em-dash density was not a signal about anything, so nobody rejected on it. In 2026 a manuscript that reads as machine-written raises a referee's eyebrow about everything else in it, including whether the analysis was done carefully. The prose is evidence about the author's care, so the gate stays binding. Two guards against the review's legitimate worry: the gate may never be satisfied by convoluted phrasing (a flagged sentence gets rewritten simpler), and it never outranks substance in review priority. It also supplements and does not replace the house-voice blocklist, since roughly half those rules are voice and not venue anomaly.
- **Prose shape, the positive gate.** `python scripts/measure_venue_shape.py [--section NN]`. Reports the venue's interquartile band for each shape target beside the draft. Binding alongside the two subtractive gates, never instead of them. Aim at the band, never at zero, and never satisfy it by convoluted phrasing.

- **Deck craft.** Load `slide-deck-authoring` and `diagram-design` before authoring; failing to do so last time produced 17 tables against one image. Data-overview slide mandatory. Every result a plot or diagram first, table only in backup. Phrases and short clauses, never full sentences, on core and backup slides alike. Inline citations throughout, plus a references slide. p-values as bare parentheses, `(0.003)`, and `(0.000)` below 0.001. No TODO frames ship.
- **Reproducibility.** Delete outputs, rebuild from one script, byte-compare. Pinned manifest, RNG seeds, execution order, auto-generated README.
- **Cleanup.** Superseded artefacts deleted in the same commit.

---

## 8. Open decisions for Java

1. Title: **DECIDED by Java 2026-08-06** — "The Making of Dominant Vehicle Currencies: Evidence from DeFi".
2. Pure-empirics lane: **ALREADY DECIDED, do not reopen.** Java settled this when the graph was first proposed, after rejecting an earlier "model-first per JFE convention" claim of mine as presumptuous. Re-derived from the 14 exemplar PDFs rather than from a summary: 6 of 14 have no formal model, and of the 3 that pair a model with data only 1 leads with theory. The JFE author profile says "IF the paper has a model, make the model do work", which is a conditional that I had flattened into an imperative. So: purely empirical is the lane, a model is added only if it raises the acceptance odds and only if done properly, and this line exists to stop the question resurfacing a third time.
3. Which of the five candidate results lead. **REVISED 2026-08-06 after all five were tested against their own strongest threat, which is what the graph is for.** Every ordering before this was written before any of them had been attacked.

   **LEAD: the intermediation transition.** It measures realised routing only, so it inherits none of the support, timing, coverage or arbitrage problems that constrain the counterfactual estimands, and it survived its sharpest threat. Node K proposed that the stable numéraire's rise might be a stableswap-venue artefact wearing a monetary-economics label; tested on constant-product venues alone, where no stableswap technology exists and a route is kept only if every leg qualifies, the stable share still moves plus 49.5 percentage points and native minus 68.0, reaching 59.5% against 51.1% across all venues. The transition is STRONGER where Curve is absent, so the rival is dead and the result is harder than before it was raised.

   **MECHANISM: rent incidence.** Pools pairing the native asset with the long tail pay on 21.6% of pool-days, lose 5.22 billion dollars over the sample, and are 80% of all pool-days, while stable-stable pairs pay on 89.6%. The pairing network that keeps the native asset on every path is supplied at a loss. Joint role effects chi2(6) = 101.59 (0.000). The predicted centrality curse is REJECTED in the opposite direction, and its depth half fails on arithmetic before reaching data, since constant-product LVR as a share of capital is realised variance over eight with no depth term.

   **FOUNDATION: cost-dominance windows** at 27.2% of realised multi-leg routing, population-weighted. This is the state FX data cannot contain. Its persistence extension is withdrawn pending block-level pricing.

   **DEMOTED: cross-venue spillover**, which section 8 previously ranked second. It cannot carry a result. The Merge placebo fails on new pairs at +0.055 (0.000), which is the outcome carrying the large V3 estimate; one of nine cells passes both pre-trend diagnostics; and the untreated venues are most of the market, so the V4 untreated estimate recovers 85% of the all-venue figure and the restriction differences out almost nothing. What survives is a bounded null at V3 and a descriptive contrast, and the identified version needs a within-day control group holding the calendar fixed.

   **COMPROMISED: the centrality framing of fragmentation.** The betweenness leader equals the degree leader on 15 of 15 days while native is DEFINED as the thickest pairing network, so the leader-never-changes half restates a definition, and eigenvector centrality reverses the ordering. The share-based transition carries this instead.

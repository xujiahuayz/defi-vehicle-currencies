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

An independent review (2026-08-05) correctly demolished the version-1 reading of this as a "data moat". Graham et al.'s advantage was *unobservable* variables from a 1,348-executive survey; on-chain data is public to anyone with an RPC endpoint. What exists here is **reconstruction difficulty**, not privileged access: attributing multi-leg routes across eight venues at scale is hard engineering. That is a weaker claim and gets stated as the weaker claim, and it does not substitute for identification. The validation apparatus is still required at Graham-level intensity: provenance, reconstruction validity, drift audits, exact-contract identity of every candidate asset.

**The silo to avoid repeating:** `src/ddvc/analysis/lp_concentration.py` reads only `data/raw/thegraph/uniswap_v3/`. Every liquidity measure built on it was a Uniswap-V3-only quantity. All measures get rebuilt on the unified layer.

---

## 3. Definitions to settle first (node C, blocking)

**Vehicle status and dominance are separate axes.** Vehicle status is a role that is binary and trivially satisfied: one bridging swap qualifies. What matters and what we measure is the *extent* to which one asset captures that role. The literature uses "vehicle currency" as a categorical label for what is really a continuous share, and making that precise is part of the contribution. Working title, a one-word insertion into the original public title so the public record stays continuous: **"The Making of Dominant Vehicle Currencies."**

**Asset types before tickers.** DeFi is the laboratory and the claim is about currency types, so tickers appear only as proxies:
- *Native platform asset*: thickest incumbent pairing network, high volatility. Proxy: WETH. TradFi analogue: the incumbent international currency whose role rests on thick-market externalities.
- *Stable numéraire*: low volatility, unit of account. Proxies: USDC, USDT, DAI. TradFi analogue: the managed or pegged stable unit.
- *Imported store of value*: non-native, wrapped. Proxy: WBTC. TradFi analogue: gold or a foreign reserve asset.

The general question is then venue- and coin-independent: does the vehicle role stay with the thick-network incumbent or migrate to the low-volatility numéraire, and what triggers migration? That is the FX dominance-transition question, and we can observe the road not taken where FX cannot.

**Definitions belong on a slide and in a numbered subsection**, stated explicitly.

---

## 4. Candidate results, screened for non-mechanicalness (node E)

Version 1's findings were near-tautological ("availability predicts usage", "netting reduces transfers"). A candidate result is rejected at design time if its sign is guaranteed by construction.

### 4.0 The routing-agency problem, and where incumbency can legitimately live

An independent cross-family review (Antigravity, 2026-08-05) raised the objection that determines this paper's architecture, and it is largely right. Swap routing is executed by smart-order routers (1inch, Uniswap Universal Router, CoW, 0x) that are deterministic graph optimisers. Code has no habits. A preference for an incumbent intermediary when a cheaper direct route existed therefore fails as evidence of trader inertia, and presenting it that way invites immediate rejection. Version 1's plan to read a wrong-signed cost coefficient as Krugman/Eichengreen inertia is retracted.

Java's counter, which the design adopts: routers optimise, but not over the true universe and not with absolute certainty. Real residual discretion sits in **which venues and pools an aggregator has integrated**, its search-depth limits and split heuristics, its gas-price assumptions, pool whitelisting, and private-orderflow and RFQ arrangements. That integration set is a slow-moving business decision instead of an instantaneous optimisation. Two consequences:

- **Incumbency is relocated off the routing layer and onto two slower layers.** (i) **LP capital allocation**: liquidity providers are humans and firms facing switching costs, gas costs, and attention limits, so supply moves slowly. (ii) **Aggregator integration scope**: which venues a router can even see, updated on a business cadence. Both are legitimate homes for stickiness in a setting where routing itself is instant.
- **A direct test separates cost-optimality from router-specific choice.** The entry contract in each transaction identifies the aggregator, so routing decisions can be compared **across aggregators for comparable pair, size, and block**. If different routers select different intermediaries for equivalent trades at the same instant, cost alone cannot explain the choice, and the residual is integration scope and heuristics. That is identifiable from public data and is the sharpest available answer to the objection.

**On mechanical results, per Java: keep them, demote them.** Architectural factors (pair availability, pool existence, netting) genuinely do shape dominance and belong in the paper. They may not be the headline, because a result whose sign is guaranteed by construction fails as a contribution. They enter as the necessary architectural layer that the allocative results sit on top of. This is a balanced position and defensible as such: architecture sets the feasible set, slower allocative choices select within it.

### 4.1 Candidate results

1. **Routing choice beyond cost, across aggregators.** Do different aggregators route comparable trades through different intermediaries at the same block, after realized execution cost is measured properly? The residual identifies integration scope and heuristics. Replaces version 1's inertia framing.
2. **Incumbency in liquidity supply.** Does lagged vehicle-linked liquidity predict current liquidity after current relative returns to provision are controlled for? The retired July deck carried a lagged-share coefficient of 0.363 buried as a control, which is the object of interest and was mistaken for a nuisance term.
3. **Fragmentation across venues with concentration in the asset.** The 11.7% to 49.8% cross-venue trend sets this up: as routing fragments across venues, does vehicle concentration rise or fall? Speaks to Chen and Duffie. Reviewer caution accepted: split-routing concentrating on deep pools is partly graph mechanics, so this needs an explicit statement of what would falsify an economic reading.
4. **Cross-venue spillover from an architecture change.** Within-venue effects are mechanical because the treated venue's pools did not previously exist. Spillover to venues that did not change is not, and it shares any macro episode with the treated venue, absorbing the confound that killed version 1's event study. The independent review rated this the strongest candidate. Templates already read: Bessembinder, Hao and Zheng on off-venue spillovers; Klein and Song on cross-venue commonality after MTF entry.
5. **Rent incidence.** Does intermediating pay? Fee yield against LVR against net return on vehicle-linked versus other pools. A centrality curse (higher gross fees, no higher net return) would be surprising. Reviewer caution accepted: this drifts toward LP adverse selection and away from currency dominance, so it stays supporting rather than headline.

### 4.2 Measurement requirements, from the independent review

Non-negotiable, because getting these wrong invalidates every result above:

- **Cross-venue depth cannot be summed.** Constant-product (Uniswap v2, Sushi v2), concentrated-liquidity (v3), stableswap (Curve), weighted (Balancer), and Fluid's custom design use different invariants, so adding reserves is economically meaningless. Depth is defined as **dollars required to move the marginal price by 10 bps and by 50 bps**, computed per venue against its own invariant and then aggregated.
- **Cost is realized execution cost.** It includes marginal pool fees, price impact at the actual trade size along the depth curve, multi-leg gas overhead relative to single-leg, priority tips, and an explicit treatment of MEV exposure. A counterfactual built on fee tiers alone is meaningless.
- **Endogeneity stated explicitly.** Does an asset become the vehicle because execution costs are low, or are costs low because vehicle liquidity accumulated? The paper must answer this, and the cross-aggregator and cross-venue-spillover designs are how.
- **Structural breaks handled explicitly**: the Merge (Sep 2022), L2 volume migration, the USDC depeg (Mar 2023), EIP-4844 (Mar 2024). Pooling across these without regime controls corrupts panel estimators.

**Known design constraint, inherited:** any event study on the May 2021 V3 launch sits on a market-wide volatility episode peaking in the launch month, which makes placebo dates produce effects as large as the true date. Cross-venue difference-in-differences absorbs it; a within-venue design does not.

---

## 5. Method discipline adopted from documented practice (node F)

Sourced from an R&D pass over reproducibility and specification-robustness practice; full sourcing in the agent output.

- **Delete-and-rebuild as the gate** (Gentzkow and Shapiro). A run is done when a fresh clone regenerates every number, table and figure with no manual steps. That is the definition of done.
- **Machine-readable decision registry.** Every analytical choice declared as a named parameter with alternatives enumerated. Mitton (RFS 2022) showed that with discretion over ten routine choices a researcher can report over 70% of *randomly generated* variables as significant determinants of leverage; the three choices that matter most are dependent variable, transformation, and outlier treatment, so those are mandatory-to-vary.
- **Specification curve per headline claim** (Simonsohn, Simmons and Nelson), with the dashboard showing which choices drive the result and a joint inference test. Curated to reasonable specifications; a padded combinatorial multiverse deflates visible dispersion.
- **Multi-agent replication as a bug detector only.** Demoted after the independent review, correctly: Menkveld et al.'s 164 human teams measured genuine researcher variation, whereas N LLM agents on one codebase measure code-generation noise. Presenting that to a journal as an econometric quantity would be process theatre. Retained internal use: run the estimate independently twice with separate contexts, and treat any disagreement as evidence that one run has a bug. Menkveld et al.'s finding that dispersion falls after peer feedback still justifies putting the critique round before estimates are fixed.
- **Specification lock plus deviation log**, in place of external pre-registration, and placed **after** an explicit exploratory phase. The review objected to the friction; the exploratory-first ordering answers that, since distributions, pool anomalies, and contract mechanics must be understood before specifications are fixed. Burlig (2018) shows PAPs carry no epistemic credit for archival data, so this claims none: it is an internal integrity device, needed because version 1 did silently reframe results after seeing them. Keep the audit trail, decline the binding commitment.
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
D. Cross-venue data layer ......... rebuild all measures on data/unified/.
     Full-panel cross-venue routing series. Validation apparatus (the moat).
E. Design + specification lock .... section 4 hypotheses, decision registry,
     enumerated alternatives, locked and hashed before F runs.
F. Empirics ....................... per E. Specification curves. Multi-agent
     NSE with the critique round before estimates fix.
G. Paper .......................... six sections, JFE invariants of section 1,
     pure-empirics lane, named rival mechanisms as the horse race.
H. Deck ........................... derived from G.
        G <-> H is a cycle: slides expose narrative gaps, paper detail exposes
        missing slides. Neither is finished before the other stops changing.
I. Cross-family review ............ Codex/Gemini. Feeds back into C..H.
     Desk-reject filter first, then rank-ordered referee.
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

1. Title: "The Making of Dominant Vehicle Currencies" (proposed, section 3).
2. Pure-empirics lane confirmed, with a model added only if a specific coefficient demands it (proposed, section 1).
3. Which of the five candidate results in section 4.1 lead. Revised inclination after the independent review: **cross-venue spillover (4) as the headline**, since it was rated the strongest and is the cleanest identification available; **cross-aggregator routing choice (1) as the second**, since it is the direct answer to the routing-agency objection and nobody has run it; **incumbency in liquidity supply (2)** as the mechanism; fragmentation-with-concentration (3) and rent incidence (5) as supporting. Architectural results stay in the paper as the feasible-set layer, never leading.

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

**No internal process in any deliverable.** No slide or paragraph reconciles the work against its own earlier plans, renumbers propositions, references pipeline phases, or opens with limitations. Reporting a null is mandatory and belongs in results, stated as a finding. Performed uncertainty at the reader is not the same virtue.

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

**The strategic reading.** The distribution is bimodal: 5 pure theory, 6 pure empirics with no formal theory, only 3 doing both. Attempting both is the minority strategy. **This paper takes the pure-empirics lane with a data moat**, because that is where our comparative advantage actually is (see node C) and because a model added to reach for respectability would be the third-least-common configuration in the sample. A model is added later only if a specific empirical coefficient or threshold cannot be explained without one.

**Craft pattern to adopt deliberately: the named rival mechanism run as a horse race.** This is what no-model empirical JFE papers use in place of formal hypotheses. Bolton and Kacperczyk italicise three competing hypotheses in the introduction, use them as running labels structuring the results, and reject one of their own.

---

## 2. What the data actually supports (node C, partially measured)

The repo's real asset, and the thing version 1 failed to use: `data/unified/`, **2,277 daily parquet files, 2020-02-11 to 2026-06-30, roughly 215k swap legs per day, all eight venues** (uniswap v1–v4, sushiswap v2/v3, curve, balancer, fluid). It carries `tx_hash`, `component_id`, `n_components`, `route_class`, `tin_role`, `tout_role`, meaning **multi-leg routes are already reconstructed across venues inside a single transaction**.

Measured, on eight days sampled across the span (needs the full panel before it goes in the paper): the share of multi-leg routes spanning more than one venue rises monotonically from **11.7% in Jan 2021 to 49.8% in Sep 2025**. Studying one venue in isolation is therefore not merely incomplete, it becomes progressively wrong across the sample.

This is the data moat the venue evidence says substitutes for causal identification, and it has to be defended as hard as Graham et al. defend theirs: provenance, reconstruction validity, drift audits, and the exact-contract identity of every candidate asset.

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

Version 1's findings were near-tautological ("availability predicts usage", "netting reduces transfers"). A candidate result is rejected at design time if its sign is guaranteed by construction. Four survive that screen:

1. **Incumbency and hysteresis.** Does routing follow contemporaneous relative cost, or does incumbency predict routing after current economics are controlled for? Version 1 produced a robustly wrong-signed cost coefficient and treated it as a defect; read as inertia it is the finding. The retired July deck separately carried a lagged-share coefficient of 0.363 buried as a control. FX cannot settle the Eichengreen inertia debate for lack of an observable counterfactual; on-chain data can, because the cost of the unchosen route is computable.
2. **Fragmentation across venues with concentration in the asset.** The 11.7% → 49.8% cross-venue trend sets this up: as routing fragments across venues, does vehicle concentration rise or fall? Speaks directly to Chen and Duffie.
3. **Cross-venue spillover from an architecture change.** Within-venue effects are mechanical because the treated venue's pools did not previously exist. Spillover to venues that did not change is not mechanical, and it shares any macro episode with the treated venue, which absorbs the confound that killed version 1's event study. Templates already read: Bessembinder, Hao and Zheng on off-venue spillovers; Klein and Song on cross-venue commonality after MTF entry.
4. **Rent incidence.** Does intermediating pay? Fee yield against LVR against net return, on vehicle-linked versus other pools. A centrality curse (higher gross fees, no higher net return) would be a genuinely surprising result.

**Known design constraint, inherited:** any event study on the May 2021 V3 launch sits on a market-wide volatility episode peaking in the launch month, which makes placebo dates produce effects as large as the true date. Cross-venue difference-in-differences absorbs it; a within-venue design does not.

---

## 5. Method discipline adopted from documented practice (node F)

Sourced from an R&D pass over reproducibility and specification-robustness practice; full sourcing in the agent output.

- **Delete-and-rebuild as the gate** (Gentzkow and Shapiro). A run is done when a fresh clone regenerates every number, table and figure with no manual steps. Not a checklist item, the actual definition of done.
- **Machine-readable decision registry.** Every analytical choice declared as a named parameter with alternatives enumerated. Mitton (RFS 2022) showed that with discretion over ten routine choices a researcher can report over 70% of *randomly generated* variables as significant determinants of leverage; the three choices that matter most are dependent variable, transformation, and outlier treatment, so those are mandatory-to-vary.
- **Specification curve per headline claim** (Simonsohn, Simmons and Nelson), with the dashboard showing which choices drive the result and a joint inference test. Curated to reasonable specifications; a padded combinatorial multiverse deflates visible dispersion.
- **Multi-agent nonstandard errors.** Menkveld et al. (JF 2024), 164 teams on one dataset, found dispersion across researchers "on par with standard errors", that participants *underestimate* it, and that **it falls after peer feedback**. Design consequence: N independent analyst agents with separate contexts on the same hypothesis, report cross-agent dispersion, and put the critique round *before* the estimate is fixed. A single agent's self-assessed confidence is worthless.
- **Specification lock plus deviation log**, in place of external pre-registration. Burlig (2018) shows PAPs are credible in observational work only with self-collected, prospective, or restricted-access data, none of which applies to archival on-chain data. Keep the audit trail, decline the binding commitment; call it a specification lock and do not claim the epistemic credit of pre-registration.
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

- **Language.** `python3 ~/glotl/scripts/style_gate.py --corpus ../defi-dominant-currency/lit/jfe-exemplars --target <file> --ignore paper/domain_terms.txt --fail-on-outlier`. Three layers: pattern metrics calibrated leave-one-out against the 14 papers, n-grams absent from the whole corpus, and log-odds over style vocabulary. Catalogue encoded from Wikipedia:Signs_of_AI_writing. Measured baseline for my own prose: em-dashes ran 10x the corpus maximum against a corpus median of zero, and "X, not Y" ran 39x the maximum. This gate supplements and does not replace the house-voice blocklist, since roughly half those rules are voice and not venue anomaly.
- **Deck craft.** Load `slide-deck-authoring` and `diagram-design` before authoring; failing to do so last time produced 17 tables against one image. Data-overview slide mandatory. Every result a plot or diagram first, table only in backup. Phrases and short clauses, never full sentences, on core and backup slides alike. Inline citations throughout, plus a references slide. p-values as bare parentheses, `(0.003)`, and `(0.000)` below 0.001. No TODO frames ship.
- **Reproducibility.** Delete outputs, rebuild from one script, byte-compare. Pinned manifest, RNG seeds, execution order, auto-generated README.
- **Cleanup.** Superseded artefacts deleted in the same commit.

---

## 8. Open decisions for Java

1. Title: "The Making of Dominant Vehicle Currencies" (proposed, section 3).
2. Pure-empirics lane confirmed, with a model added only if a specific coefficient demands it (proposed, section 1).
3. Which of the four candidate results in section 4 lead, and which become supporting. My inclination: incumbency/hysteresis as the headline, fragmentation-with-concentration as the second, cross-venue spillover as the architecture test, rent incidence as the mechanism deepening.

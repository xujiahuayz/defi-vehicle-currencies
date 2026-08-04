# Phase 3 — benchmark scoring

Three judges, distinct lenses, on the single framing that survived Phase 2. Identification-scrutiny is a necessary-condition gate; structural/scope-fit is a required input to Phase 4, not just a score. The first run hit a transient API failure on the structural judge; it was retried cleanly and a corrected synthesis was produced. Final verdict: **CONDITIONAL** — see synthesis at the bottom for the authoritative, complete verdict; the fixes it required have already been applied to .

---

## Identification-scrutiny judge

# Referee Report — Framing #1, "Liquidity Provision Makes (and Unmakes) the Vehicle"

**Note on sourcing before I start:** the manifest lists Eisfeldt, Herskovic, Rajan & Siriwardane (2023) ("OTC Intermediaries," RFS) as one of the two closest mechanism matches, but `01_source_fidelity.md` contains **no independent-read entry for it at all** — I grepped the full file (all 451 lines) and it never appears. Everything I say about EHRS below rests only on the manifest's one-line, unverified description ("core-periphery network model + counterfactual dealer-exit simulation"), not on a cross-checked safe-to-cite statement the way every other comparator has. I flag this explicitly rather than silently treating EHRS as equally well-grounded as He/Khorrami/Song (HKS), which *does* have a full Phase-1 entry.

---

## P1 — Formation / self-reinforcement

**(1) What actually varies, in my own words.** Nothing is engineered to vary. The design is a panel/time-series regression across the five-token candidate set (WETH/USDC/USDT/DAI/WBTC) relating three objects that are jointly, contemporaneously determined by the same underlying trading activity: candidate-linked pool depth $L_{k,t}$, the direct-vs-indirect quoted-price gap (DirectCostAdvantage), and indirect-route volume share. There is no instrument, no policy discontinuity, no shock — the framing itself says P1's status is "infrastructure built, headline result not yet run," described only as a panel/time-series exhibit. This is observational comparative-statics, not a natural experiment.

**(2) Most damaging alternative explanation, and does the evidence hierarchy rule it out?** Simultaneity/reverse causality via an omitted common demand shock: a token becoming more fundamentally traded for reasons that have nothing to do with LP self-reinforcement (a new stablecoin listing, an exchange integration, a TVL inflow chasing yield elsewhere) will *mechanically* raise $L_{k,t}$, lower price impact, and raise indirect-route volume share all at once, with none of the proposed causal arrows (concentration → depth → lower cost → more volume → more concentration) needing to be true. Nothing in the design distinguishes "liquidity begets volume begets liquidity" from "a shock to fundamental demand raises all three variables independently." The evidence hierarchy does not rule this out — it doesn't even engage it. The theory citations (Krugman's F(V) feedback loop, Lehár-Parlour's Prop. 3, Yuan's benchmark-liquidity analogy) are all explicitly logged in Section 2 as "borrowed theoretical analogy, not evidence," so they cannot be doing identification work; they only motivate what the *correlation* would mean if it appeared, they don't argue why the correlation, if found, must be causal rather than a shared-shock artifact. This is an assertion gap, not a ruled-out alternative.

**(3) Would HKS's/EHRS's referees have accepted this?** No. HKS's own headline "40%+ of residual commonality" result is *already* just a correlation between two constructed factors and spread-change residuals — and even for that, the authors (per the safe-to-cite statement) still felt compelled to build a fallen-angel forced-sale IV, pass a formal Montiel-Olea–Pflueger weak-IV test, and even then hedge that the instrument isn't "unambiguously exogenous." If RFS referees required that much machinery for a *single-factor* correlational claim, they would not accept a three-way, self-reinforcing panel correlation with zero exogenous variation for the *stronger* claim P1 makes (a live feedback loop, not just static commonality). EHRS's manifest description (structural model + counterfactual dealer-exit simulation) implies an even higher bar — a full structural identification via model-implied counterfactuals — though I can't verify EHRS's specifics past that one line, for the reason flagged above.

---

## P2 — Persistence / architecture-conditioned stress rotation

**(1) What actually varies, in my own words.** If implemented as specified, cross-chain differences in gas cost (Ethereum vs. Arbitrum vs. Polygon), using chain-launch timing as an instrument for LP repositioning intensity, corroborated by the March 2023 ARB airdrop as a within-chain shock — this is Caparros/Chaudhary/Klein's (CCK) actual identification strategy, imported wholesale. That part is a real quasi-experiment, not pure correlation: chain launch timing and an airdrop are at least argued to be orthogonal to organic LP-repositioning decisions. But the framing is explicit that this has never been run "on this paper's candidate set" — it's a template, not a result — and the actual dependent variable is different from CCK's: not "does cheap gas raise repositioning/concentration in general" but "does cheap gas make *vehicle status itself* more elastic under stress." That's a new outcome bolted onto an old instrument.

**(2) Most damaging alternative explanation, and does the evidence hierarchy rule it out?** Chains don't differ only in gas cost — they differ in trader composition, baseline liquidity depth, bridge/security risk, and (crucially) in whether a "vehicle" even exists in the same structural sense on an L2 with mechanically smaller TVL. CCK's own authors, per the Phase-1 safe-to-cite statement, admit they "cannot possibly rule out" the Hasbrouck-Rivera-Saleh alternative — that cross-chain differences reflect different equilibrium trade-size distributions, not the repositioning-cost channel. Importing that instrument to a *new* outcome (vehicle-status rotation) inherits this unresolved confound and adds a further one on top: composition differences that determine which token is even a "candidate vehicle" per chain, unrelated to repositioning cost. To the framing's credit, it doesn't hide the borrowed-not-yet-run status (Section 2 is explicit about this), and it doesn't misrepresent CCK as more than a template. But it also proposes to back this up with only "one stress episode (a documented volatility or depeg event)" — a single illustrative case, not a systematic design — so the evidence hierarchy neither rules out the trade-size-composition confound nor proposes a design element that would.

**(3) Would HKS's/EHRS's referees have accepted this?** Unlikely as specified. HKS demanded a formal weak-IV test and an admitted-imperfect instrument for a narrower claim; a single anecdotal stress episode layered on an instrument the source paper's own authors say has an unclosed confound is thinner than that. EHRS's counterfactual-simulation approach (per the manifest, unverified in detail) implies referees in this genre expect either a structural model with explicit counterfactuals or a systematic multi-episode event-study/DiD — not one case study as the stress-rotation evidence.

---

## Final verdict: **CONDITIONAL**

Two named additions are required before this clears referee-grade scrutiny, and they are not cosmetic — each is currently a hole a referee would stop the paper on:

1. **For P1 — an exogenous supply-side liquidity shock to break the $L_{k,t}$/cost/volume simultaneity.** The current design is pure contemporaneous correlation among three jointly-determined variables and has no mechanism to distinguish the self-reinforcing loop from a common demand shock. This needs something that plausibly shifts LP capital *supply* without directly shifting trading demand — e.g., liquidity-mining incentive-program launches/expirations, or a fee-tier/protocol-parameter change — used in a lead-lag, Granger-style, or IV structure. Without this, P1 is not "not yet run," it's not yet a causal design at all, and as currently specified it would not survive review at the level of the comparator papers it's citing as templates.

2. **For P2 — either multiple systematically-analyzed stress episodes (a real event-study/DiD panel across the chain cross-section, not one illustrative depeg), or an explicit test/argument that rules out the Hasbrouck-Rivera-Saleh trade-size-composition confound before extending CCK's instrument to a vehicle-rotation outcome variable CCK never tested.** The identification template is legitimate, but importing it to a new dependent variable while relying on a single case for the "stress rotation" half of the claim is exactly the kind of specificity-without-rigor a referee at this tier would flag, especially given that even the template paper's authors concede the confound is unresolved.

If both are added, the framing survives at the level of its stated comparators. As currently specified — reduced-form correlation for P1's headline claim, single-episode illustration for P2's rotation claim — it would not.

---

## Source-fidelity judge

I read both files in full (`framing_1.md`, 65 lines; `01_source_fidelity.md`, 451 lines, all 8+ paper entries). Here is the citation-by-citation check.

## Citations that overclaim beyond Phase 1's license

**1. Lehár & Parlour (2024) — Proposition 3 applied to what is actually a V3 mechanism (the clearest violation)**

Phase 1's safe-to-cite statement (`01_source_fidelity.md` line 140, echoed correctly in the framing's own evidence-hierarchy note at line 26) restricts Prop. 3 to "a constant-product AMM (Uniswap V1/V2 specifically, **not V3** or other bonding-curve designs)" — pool-size-as-the-only-margin, no concentrated ranges.

But the framing's headline mechanism uses Prop. 3 as load-bearing support for claims that are inherently about V3 concentrated-liquidity behavior:
- Line 9 (P1): "...that concentration deepens the pool, which... mechanically lowers price impact on vehicle-routed trades (Lehár & Parlour 2024, Proposition 3...)" — but the paper's own $L_{k,t}$ construction (line 21) is explicitly "an existing contract-address-level **V3** data construction." Prop. 3's pool-size comparative static is about undifferentiated V1/V2 depth, not V3 concentration around a price range — these aren't the same object.
- Line 11 (P2): "...lets LPs re-concentrate liquidity faster... by Lehár & Parlour's Prop. 3 comparative statics, that faster re-concentration should make vehicle-route depth... more elastic to shocks." Repositioning concentrated ranges is a V3-only LP action (it's literally what Caparros/Chaudhary/Klein 2024 study, correctly cited alongside it) — Prop. 3 was never tested on, and per Phase 1 explicitly does not cover, that setting.

The framing states the V1/V2-only boundary correctly in its own §2 citation note (line 26) but then crosses it in the headline propositions (§1, lines 9 and 11) without the caveat — an internal inconsistency, and a real overclaim of what L&P (2024) licenses.

**2. Somogyi (2026) — the motivational-opener slide misattributes the fixed-effects caveat to the wrong statistic**

Phase 1's safe-to-cite statement (`01_source_fidelity.md` line 176) is explicit that two *different* empirical exercises live inside this paper: the ~13%/25–38% vehicle-currency volume-share estimate (from the quasi-experimental holiday design) and the separate C1–C3 panel-regression test of the mechanism's conditions (non-causal, ~5.3%/2.5–3.1% coefficients dwarfed by an ~18–20% overall R² dominated by fixed effects). The caveat about non-causality/fixed-effects belongs to the *second* exercise, not the headline 13%/25–38% figure.

The framing's own §2 evidence-hierarchy entry (line 31) gets this right, keeping the two separate. But the narrative-arc / motivational-opener slide (line 42) collapses them: "Open with the FX vehicle-currency stylized fact (Somogyi 2026's ~13%/25–38% figures, **explicitly flagged live as non-causal/fixed-effects-dominated**)." This attaches the fixed-effects caveat directly to the 13%/25–38% number — the one figure Phase 1 does *not* flag that way — contradicting both Phase 1 and the framing's own more careful §2 text. Since this line is the actual content of the opening slide (not just an internal note), it's the version that ships to the talk.

## Softer / borderline case

**3. Krugman (1980) — "exactly... reproduced" language against the three-currency-only boundary**

Phase 1 (line 36) is explicit: Krugman's mechanism "must not be extended beyond three currencies (footnote 3 blocks generalization)." The framing's P1 (line 9) states the AMM cost-comparison "is **exactly** Krugman's (1980) transaction-cost vehicle-selection condition, reproduced here inside an AMM rather than assumed," and applies it to a five-token candidate set (WETH/USDC/USDT/DAI/WBTC) in a market with many more than three tradeable currencies. The framing does flag Krugman elsewhere as "purely a motivating theoretical analogy" (line 29), which mitigates this, but the word "exactly" plus "reproduced" (rather than "analogized") pushes toward treating the n>3 AMM setting as a literal instance of Krugman's 3-currency result rather than an inspired-by analogy. Lower severity than #1–2 since the surrounding text elsewhere correctly hedges it, but worth tightening.

## Citations checked and found within license (no issues)

- **Caparros, Chaudhary & Klein (2024)** — correctly caveated everywhere as "general on that paper, not yet run on vehicle-candidate pools" (lines 11, 22, 28), including the professional-not-retail-LP caveat Phase 1 flags as single-source-confirmed.
- **Klein, Kozhan, Viswanath-Natraj & Wang (2026)** — uses the Phase-1-preferred "return-predictive content" phrasing (line 27), avoiding the "price impact" overclaim Phase 1 warns against; correctly scoped to motivating an assumption, not asserted as this paper's evidence.
- **Yuan (2005)** — correctly labeled "theoretical analogy, not evidence" (line 9) and conditioned on the cross-market order-flow assumption in §2 (line 30).
- **Klein & Song (2021)** and **He, Khorrami & Song (2022)** — both correctly restricted to "brief TradFi structural analogies... never as evidence for this paper's claims" (line 32), matching both papers' explicit DeFi-extension disclaimers in Phase 1.

## Coverage check

Every citation the framing makes (Krugman 1980, Lehár & Parlour 2024, Caparros/Chaudhary/Klein 2024, Klein/Kozhan/Viswanath-Natraj/Wang 2026, Yuan 2005, Somogyi 2026, Klein & Song 2021, He/Khorrami/Song 2022) has a corresponding entry in `01_source_fidelity.md`. Goldstein-Ozdenoren-Yuan (2011) and Ozdenoren-Yuan-Zhang (2023) are mentioned only to say they were deliberately *not* used — no citation gap there. No citation in the framing is uncovered by Phase 1.

Files reviewed: `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/02_framings/framing_1.md`, `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/01_source_fidelity.md`.

---

## Structural/scope-fit judge (retry — first attempt failed on a transient connection error)

## Part A — What each comparator actually pairs with its headline result

*(Reconstructed from the manifest's own genre/archetype tags in `00_manifest.md` lines 33-44, cross-checked against the published empirical architecture each paper is known to use. Where I'm inferring an exact instrument/date rather than quoting the manifest verbatim, I've flagged it — Phase 1 should re-verify against the paper text before any caption locks.)**

### He, Khorrami & Song (2022), RFS — "clean IV identification," intermediary-capacity-driven commonality
Headline: commonality in corporate-bond credit-spread changes is explained by dealer inventory risk / intermediary distress, not just a common macro-credit factor — i.e., the *same* "is this self-reinforcing capacity/commonality channel real, or is it a common shock in disguise" question P1 has to answer.
- **Identification pairing:** isolates variation in dealer capacity/inventory constraint that is not spanned by the common macro-credit factor already in the regression (an IV/instrument on the intermediary side, not the bond side) — the direct genre-match for P1's now-required exogenous supply-side shock.
- **Falsification/placebo:** shows the capacity channel's explanatory power collapses in periods/bonds where dealer constraints aren't binding (non-crisis windows, bonds not held by constrained dealers) — a placebo that the channel is capacity-specific, not a spurious correlate of the common factor.
- **Subsample split:** crisis vs. non-crisis; investment-grade vs. high-yield.
- **Alternative-measure robustness:** commonality measured via PCA/first-principal-component loading *and* pairwise correlation *and* common-factor R², not one metric.
- **Sample-period split:** full sample vs. crisis-only vs. calm-only, to show the capacity channel is strongest exactly when balance sheets are constrained (a theory-consistent heterogeneity check, not a nuisance robustness table).

### Eisfeldt, Herskovic, Rajan & Siriwardane (2023), RFS — core-periphery network + counterfactual dealer-exit simulation
Headline: OTC (CDS) intermediation is explained by a structural core-periphery network with capacity-constrained dealers — the direct genre-match for P2's "architecture/capacity-shock effect."
- **Identification/validation pairing:** the discipline device is a counterfactual — drop a dealer from the fitted network, compute the model's predicted liquidity/cost effect, and validate against what actually happened when a real dealer exited the market. This is the structural analog of a chain-launch/fee-tier shock, and the "counterfactual vs. actual" comparison *is* their falsification test.
- **Falsification test:** the model has to match not just the magnitude but the direction and cross-sectional heterogeneity of the real exit's effect (which counterparties were hit hardest) — a magnitude+heterogeneity match, not just a point estimate.
- **Multi-episode/robustness:** checked against more than one exit episode where available, and against counterfactual removal of dealers *other* than the one that actually exited (to show the result isn't an artifact of picking one convenient case) — this is precisely the "multi-episode, not one illustrative case" bar P2 now has to clear.
- **Alternative-measure robustness:** alternative core/periphery-classification and network-centrality definitions feeding the same counterfactual, to show it isn't sensitive to how "capacity" is operationalized.
- **Sample-period split:** pre/post the capacity-relevant regulatory or exit shock; rolling network re-estimation to rule out a static-window artifact.

### Barbon & Ranaldo, Management Science — CEX vs. DEX, gas-fee causal effects, arbitrage-deviation persistence
This is the closest DeFi-native template to *both* propositions at once.
- **Identification pairing:** gas fees are argued to carry variation exogenous to the specific pool/pair under study — driven by network-wide congestion from unrelated on-chain activity (other dApps, NFT mints, unrelated token launches). That's functionally the instrument P1 needs (a cost shock not caused by the vehicle-candidate's own liquidity dynamics) *and* the architecture-cost channel P2 needs (same genre as CCK's gas-cost mechanism the framing already borrows).
- **Falsification/placebo:** the CEX side is mechanically insulated from Ethereum gas prices, so a null/attenuated gas-fee effect on CEX-side quality is the built-in placebo showing the channel is DEX-architecture-specific, not a spurious market-wide correlate.
- **Subsample split:** by pool liquidity tier, by fee tier, by high- vs. low-congestion regime.
- **Alternative-measure robustness:** multiple market-quality metrics (effective spread, price impact, quoted spread) *and* multiple arbitrage-deviation constructions — the persistence result has to survive both.
- **Sample-period split:** across distinct gas-fee regimes (e.g., pre/post a network-level fee-mechanism change), to show the causal channel isn't an artifact of one fee regime.

### Ranaldo, Viswanath-Natraj & Wang, JFQA — regression + SVAR + event-study toolkit
- **Identification pairing:** an SVAR decomposes DEX pool dynamics into supply-side liquidity shocks vs. demand-side order-flow shocks — this is the literal empirical template for the lead-lag/Granger-or-IV structure the framing's P1 revision now requires, since an SVAR is exactly a device for separating a self-reinforcing depth↔volume loop from a common shock hitting both sides at once.
- **Falsification/event-study:** multiple distinct, plausibly-exogenous episodes (stablecoin-specific news, depeg episodes), not one — the same "multi-episode" standard P2 now needs.
- **Subsample split:** CLS trading hours vs. off-hours — a natural within-day split exploiting when the TradFi benchmark is/isn't trading to isolate DEX-only price discovery.
- **Alternative-measure robustness:** alternative DEX liquidity/price-impact measures and alternative benchmark constructions.
- **Sample-period split:** windows around known EURC/USDC-relevant redemption/regulatory events.

---

## Part B — Phase 4 evidence-build checklist

### P1 battery (self-reinforcing capital-allocation ↔ liquidity-depth loop)

1. **[HARD REQUIREMENT, already flagged]** Exogenous supply-side liquidity shock in a lead-lag/Granger or IV structure — modeled on HKS's intermediary-side instrument and RVW's SVAR supply/demand decomposition. Concretely: pick a liquidity-mining launch/expiration or fee-tier/parameter change whose timing is plausibly independent of contemporaneous demand shocks to the candidate pool, and either (a) run it through a Granger/lead-lag panel on $L_{k,t}$ → route-volume-share → $L_{k,t+1}$, or (b) use it as an instrument for $L_{k,t}$ in the DirectCostAdvantage/route-volume regression.
2. **Falsification/placebo (from HKS + Barbon & Ranaldo template):** show the shock's effect is muted/absent in a setting mechanically insulated from it — e.g., a non-candidate token's pool that shouldn't respond to the same liquidity-mining program, or (Barbon & Ranaldo style) a CEX-side comparator that can't be moved by an on-chain-only shock. Without this, the "exogenous shock" result is a single significant coefficient, not evidence the channel is specific.
3. **Subsample split (HKS + Barbon & Ranaldo template):** high- vs. low-baseline-depth pools, and calm vs. high-volatility windows — the self-reinforcing loop should be strongest exactly where/when LP capital is most mobile, which is a theory-consistent heterogeneity check, not a nuisance table.
4. **Alternative-measure robustness (all four comparators do this):** re-run the headline exhibit with an alternative depth measure (e.g., depth-in-a-band rather than full-range TVL) and an alternative DirectCostAdvantage construction (mean vs. median relative gap, alternative common-support window) to show the loop isn't an artifact of one metric definition.
5. **Sample-period split (HKS + RVW template):** at minimum a pre/post split around the exogenous shock date, and ideally a second, independent shock episode — a single event is a case study, not the panel-level evidence these comparators require.

### P2 battery (architecture/capacity-shock effect on the equilibrium)

1. **[HARD REQUIREMENT, already flagged]** Either a systematic multi-episode event-study/DiD panel across the chain cross-section, or an explicit trade-size-composition confound-ruling-out argument. Modeled on EHRS (multiple dealer-exit episodes, not one) and RVW (multiple depeg/news episodes). Concretely: identify ≥3 architecture/gas-cost-shock episodes across ≥2 chains (chain launches, fee-tier changes, L2 migrations) and require the repositioning→concentration→vehicle-status-elasticity result to replicate across them, not rest on the one illustrative episode currently in the Section 3 narrative arc.
2. **Falsification/placebo (Barbon & Ranaldo template, directly reusable since it's the same gas-cost channel CCK/P2 already borrows):** show the architecture-shock effect is absent on a venue/instrument mechanically insulated from the specific chain's gas/fee change (e.g., a pool on a chain unaffected by the fee-tier change) — the built-in control CCK's own design doesn't fully supply.
3. **Confound-ruling-out content, if the multi-episode panel isn't run (EHRS + CCK's own admitted gap):** don't just assert the argument — show trade-size distributions are comparable across the high- vs. low-repositioning-cost venues being compared (matching or binning by trade size), the way CCK's critics would demand; a bare sentence asserting "trade size isn't the driver" won't clear this bar.
4. **Subsample split (HKS + CCK genre):** professional vs. retail LP behavior (CCK's own paper splits on this), and by candidate-vehicle identity, since which token counts as a candidate differs by chain (the framing's own second identification gap) — this split is also the mechanism for partially addressing item 3.
5. **Alternative-measure robustness (EHRS + Barbon & Ranaldo template):** re-run with an alternative repositioning-cost/architecture proxy (e.g., realized gas spend per rebalance vs. a chain-level gas-price index) to show the elasticity result isn't an artifact of one cost measure.
6. **Sample-period split (all four comparators):** pre/post each architecture shock, not just a single before/after snapshot around the one stress episode currently budgeted in Section 3.

---

## Part C — Structural/scope-fit assessment: does the framing's evidence hierarchy already plan for this, or is there a gap?

**There is a gap, and it is specific, not generic.** The framing's Section 1 referee notes and Section 2 evidence hierarchy already absorbed the two identification upgrades (exogenous supply-shock for P1; multi-episode/confound-argument for P2) — that much is current. But those two upgrades only buy the *headline causal design* layer. None of the comparators stop there: every one of them pairs its headline causal result with a falsification/placebo test, a subsample heterogeneity split, an alternative-measure robustness check, and a sample-period split — and the framing's evidence hierarchy (Section 2) does not budget for any of these four, for either proposition.

Three concrete symptoms of the gap:

1. **The framing's only "robustness" section is about citation discipline, not empirical robustness.** Section 2's "Supporting/robustness" heading is entirely about what borrowed papers (Lehár & Parlour, Krugman, Yuan, CCK, Klein/Song, HKS) can be cited for without overclaiming — a citation-scope robustness list, not a battery of placebo/subsample/alternative-measure checks on this paper's *own* two headline exhibits. That's a different meaning of "robustness" than every comparator in the manifest actually runs. As written, Phase 4 has no section of the evidence hierarchy to hang items B.1.2–B.1.5 or B.2.2–B.2.6 on.

2. **Section 3's narrative arc (item 5) still says "one stress episode," which now directly conflicts with the revised P2 referee note.** The framing text was revised at Section 1/2 to require a multi-episode panel *or* an explicit confound argument, but Section 3's talk-time allocation ("plus one stress episode... showing vehicle-candidate liquidity reallocating faster on cheap-repositioning venues") was not updated to match. That's an internal inconsistency introduced by the revision, not just a missing robustness line — it means the current draft's own narrative structure is still built around the single-episode design the identification gap explicitly disallowed.

3. **The confound-ruling-out argument for P2 is named but not specified.** Section 1/2 both name "an explicit argument ruling out the trade-size-composition confound" as an acceptable alternative to the multi-episode panel, but nowhere does the framing sketch what such an argument would consist of (e.g., trade-size matching/binning across venues). Without that specification, Phase 4 can't tell whether it's building a panel or an argument, and if it's the latter, has no spec for what would make the argument convincing rather than asserted.

**Net assessment:** the framing's stated evidence hierarchy plans for the *existence* of a causal design (correctly, per the Phase 3 referee gate) but not for the *robustness shell* the comparators actually require around that design. Phase 4 should treat Part B above as an addition to Section 2's evidence hierarchy — one falsification test, one subsample split, one alternative-measure check, and one sample-period split per proposition, at minimum — and Phase 4/6 should either update Section 3 item 5's "one stress episode" language or explicitly commit to the multi-episode panel before slide-building starts, since the two currently point in different directions.

---

**Files read:**
- `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/02_framings/framing_1.md`
- `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/00_manifest.md`

---

## Final synthesis (complete inputs)

# Phase-3 Synthesis (Complete Inputs) — Framing #1, "Liquidity Provision Makes (and Unmakes) the Vehicle"

## 1. Overall verdict: **CONDITIONAL — unchanged from the identification judge, now with an additional, independent gap surfaced by the structural report**

The framing correctly absorbed the identification judge's two hard requirements and the source-fidelity judge's three citation corrections (confirmed by direct read below). But the structural/scope-fit report — now available for the first time — shows those fixes only closed the *causal-design* layer. They did not close the *robustness-shell* layer every comparator in the manifest pairs with its headline result, and one piece of the framing (Section 3's narrative arc) was left internally inconsistent with the P2 requirement the framing's own Section 1/2 now states. So this is not yet cleared for Phase 4. Required before it clears:

- Add the Part B robustness battery (falsification/placebo, subsample split, alternative-measure check, sample-period split — one of each per proposition, minimum) into Section 2's evidence hierarchy.
- Resolve the Section 3 vs. Section 1/2 contradiction: either rewrite narrative-arc item 5 to commit to the multi-episode panel, or replace it with a specified confound-ruling-out argument (trade-size matching/binning across venues) — not both left pointing in different directions.
- Specify what the "explicit argument ruling out the trade-size-composition confound" would actually consist of, so Phase 4 knows whether it's building a panel or an argument.
- When EHRS enters Phase 4 material as the P2 counterfactual template, use the corrected "closed-form re-solve" characterization and the fidelity-checked safe-to-cite paragraph — not the disputed magnitudes.

The EHRS closure itself does not change the verdict's direction (it was never the load-bearing citation for either headline proposition), but it does add one more precision fix that must land before Phase 4 material is built on the comparator (see §4).

---

## 2. Structural report's evidence-hierarchy/robustness checklist — reproduced in full (required Phase-4 input)

### P1 battery (self-reinforcing capital-allocation ↔ liquidity-depth loop)

1. **[HARD REQUIREMENT, already flagged]** Exogenous supply-side liquidity shock in a lead-lag/Granger or IV structure — modeled on HKS's intermediary-side instrument and RVW's SVAR supply/demand decomposition. Concretely: pick a liquidity-mining launch/expiration or fee-tier/parameter change whose timing is plausibly independent of contemporaneous demand shocks to the candidate pool, and either (a) run it through a Granger/lead-lag panel on $L_{k,t}$ → route-volume-share → $L_{k,t+1}$, or (b) use it as an instrument for $L_{k,t}$ in the DirectCostAdvantage/route-volume regression.
2. **Falsification/placebo (from HKS + Barbon & Ranaldo template):** show the shock's effect is muted/absent in a setting mechanically insulated from it — e.g., a non-candidate token's pool that shouldn't respond to the same liquidity-mining program, or (Barbon & Ranaldo style) a CEX-side comparator that can't be moved by an on-chain-only shock. Without this, the "exogenous shock" result is a single significant coefficient, not evidence the channel is specific.
3. **Subsample split (HKS + Barbon & Ranaldo template):** high- vs. low-baseline-depth pools, and calm vs. high-volatility windows — the self-reinforcing loop should be strongest exactly where/when LP capital is most mobile, which is a theory-consistent heterogeneity check, not a nuisance table.
4. **Alternative-measure robustness (all four comparators do this):** re-run the headline exhibit with an alternative depth measure (e.g., depth-in-a-band rather than full-range TVL) and an alternative DirectCostAdvantage construction (mean vs. median relative gap, alternative common-support window) to show the loop isn't an artifact of one metric definition.
5. **Sample-period split (HKS + RVW template):** at minimum a pre/post split around the exogenous shock date, and ideally a second, independent shock episode — a single event is a case study, not the panel-level evidence these comparators require.

### P2 battery (architecture/capacity-shock effect on the equilibrium)

1. **[HARD REQUIREMENT, already flagged]** Either a systematic multi-episode event-study/DiD panel across the chain cross-section, or an explicit trade-size-composition confound-ruling-out argument. Modeled on EHRS (multiple dealer-exit episodes, not one) and RVW (multiple depeg/news episodes). Concretely: identify ≥3 architecture/gas-cost-shock episodes across ≥2 chains (chain launches, fee-tier changes, L2 migrations) and require the repositioning→concentration→vehicle-status-elasticity result to replicate across them, not rest on the one illustrative episode currently in the Section 3 narrative arc.
2. **Falsification/placebo (Barbon & Ranaldo template, directly reusable since it's the same gas-cost channel CCK/P2 already borrows):** show the architecture-shock effect is absent on a venue/instrument mechanically insulated from the specific chain's gas/fee change (e.g., a pool on a chain unaffected by the fee-tier change) — the built-in control CCK's own design doesn't fully supply.
3. **Confound-ruling-out content, if the multi-episode panel isn't run (EHRS + CCK's own admitted gap):** don't just assert the argument — show trade-size distributions are comparable across the high- vs. low-repositioning-cost venues being compared (matching or binning by trade size), the way CCK's critics would demand; a bare sentence asserting "trade size isn't the driver" won't clear this bar.
4. **Subsample split (HKS + CCK genre):** professional vs. retail LP behavior (CCK's own paper splits on this), and by candidate-vehicle identity, since which token counts as a candidate differs by chain (the framing's own second identification gap) — this split is also the mechanism for partially addressing item 3.
5. **Alternative-measure robustness (EHRS + Barbon & Ranaldo template):** re-run with an alternative repositioning-cost/architecture proxy (e.g., realized gas spend per rebalance vs. a chain-level gas-price index) to show the elasticity result isn't an artifact of one cost measure.
6. **Sample-period split (all four comparators):** pre/post each architecture shock, not just a single before/after snapshot around the one stress episode currently budgeted in Section 3.

**Net structural assessment:** the framing's stated evidence hierarchy plans for the *existence* of a causal design (correctly, per the Phase 3 referee gate) but not for the *robustness shell* the comparators actually require around that design. Phase 4 should treat the above as an addition to Section 2's evidence hierarchy — one falsification test, one subsample split, one alternative-measure check, and one sample-period split per proposition, at minimum.

---

## 3. Did the framing's self-revisions land correctly? — Confirmed by direct read of `framing_1.md`

**Identification hard requirements — correctly encoded, no new problems:**
- P1 (line 9, restated line 21): the omitted-common-demand-shock gap is stated precisely, and the exogenous supply-side shock (liquidity-mining launch/expiration or fee-tier change, lead-lag/Granger or IV) is stated as "now a hard requirement, not a nice-to-have." Matches the judge's verdict exactly.
- P2 (line 11, restated line 22): the Hasbrouck-Rivera-Saleh confound inheritance from CCK plus the second candidate-identity-by-chain gap are both named, and the multi-episode panel / confound-ruling-out-argument alternative is stated as a hard requirement. Matches the judge's verdict exactly.

**Three citation corrections — all confirmed landed cleanly:**
- **Lehár & Parlour Prop 3 scope** (lines 9, 26): explicitly scoped to constant-product V1/V2 pools, explicitly flagged as an analogy (not the same object under test) against the paper's own V3 $L_{k,t}$ construction, and the citation-list entry (line 26) restates the exact bounded conditions and the 43-pair Binance-comparison scope. No overclaim remains.
- **Somogyi caveat misattachment** (lines 31, 42): now correctly disentangled — the ~13%/25–38% headline estimate (from the quasi-experimental holiday design) is the one used to open the talk (line 42), while the caveat that the *separate* C1–C3 panel-regression mechanism test is non-causal/fixed-effects-dominated is explicitly kept off that slide and attached only to the mechanism claim (line 31). This is a correct fix — the two claims are no longer conflated.
- **Krugman overclaim** (lines 9, 29): explicitly bounded to the three-country case, explicitly disclaimed as not extending beyond three currencies, and explicitly barred from being read as proving persistence-after-dominance-fades (Krugman's own dynamic-analysis disclaimer is quoted). No overclaim remains.

**What the self-revision did *not* fix — confirmed present, not newly introduced by the revision, but now blocking Phase 4:**
1. **Section 2's "robustness" is citation-scope discipline, not empirical robustness** (lines 24–34 confirmed — every bullet is about what a borrowed paper may/may not be cited for; none budgets a placebo/subsample/alt-measure/sample-period check on this paper's own two headline exhibits).
2. **Section 3, item 5 (line 46) still reads "plus one stress episode... showing vehicle-candidate liquidity reallocating faster on cheap-repositioning venues"** — this is a live, unedited contradiction of the P2 hard requirement stated three lines away in spirit (Sections 1–2) that requires a *multi-episode* panel or an explicit confound argument. The self-revision touched Sections 1 and 2 but did not propagate the change to Section 3's talk-time allocation, so the draft's own narrative structure is still built around the single-episode design the identification gap disallows.
3. **The confound-ruling-out alternative is named twice (lines 11, 22) but never specified** — no sketch anywhere in the file of what "an explicit argument ruling out the trade-size-composition confound" would contain (e.g., trade-size matching/binning across venues, per Part B.2.3 above).

None of these three are regressions caused by the edit — they are pre-existing scope gaps the identification-only revision didn't reach — but they are the reason the overall verdict stays CONDITIONAL rather than clearing.

---

## 4. EHRS finding — does it change anything material?

**Short answer: no change to the verdict or to any claim currently in the framing, but it produces two concrete to-dos for Phase 4 and confirms one part of the structural report.**

- **Access is fine, not a gap.** Both reads used the same disclosed working-paper proxy, cross-checked qualitatively against the published abstract. This paper is usable as the P2 counterfactual-design template Part A/B rely on — nothing here weakens that template's validity.
- **One terminology correction inherited by the structural report itself:** Part A's header language, "core-periphery network + counterfactual dealer-exit *simulation*," and its body text ("the discipline device is a counterfactual — drop a dealer... compute the model's predicted... effect") should be read with the fidelity check's correction in mind: it is a **closed-form analytical re-solve** of the calibrated equilibrium, not a stochastic/Monte Carlo simulation. This doesn't change which comparator-genre lesson Part B draws (multi-episode counterfactual-vs-actual validation is still the right template for P2 item 1/3), but if EHRS's method is described on a slide or in Phase 4 documentation, "simulation" must not be used.
- **Confirms, rather than weakens, the multi-episode requirement's evidentiary basis for P2.** The fidelity check corroborates that EHRS checks against more than one dealer-exit episode *and* against counterfactual removal of non-exiting dealers specifically to rule out cherry-picking one convenient case — this is exactly the standard Part B.P2.1 and B.P2.3 lean on, so the structural report's citation of EHRS as the "multi-episode, not one illustrative case" bar is now cross-checked, not resting on a one-line manifest tag.
- **No live citation to correct in `framing_1.md` today.** EHRS is not currently named in the framing's Section 2 supporting-citation list (only Klein & Song and He, Khorrami & Song appear there as TradFi structural analogies) — so the "don't cite disputed magnitudes / attribute to all four authors jointly / no real dealer identities" constraints from the fidelity check have nothing to correct *yet*. They become load-bearing the moment Phase 4 or a later framing revision adds EHRS to that list or to Section 3 material (e.g., as the methodological grounding for the P2 counterfactual-removal design) — at that point, the safe-to-cite paragraph in the fidelity report should be used verbatim, with no specific magnitude (not "+23%/+40%," not "6.14/7.69 bps") stated without a direct table check, since the two independent reads disagree on both headline numbers and neither has been reconciled against the source PDF.

**Bottom line on EHRS:** it changes documentation precision (simulation → closed-form re-solve) and adds a citation-discipline guardrail for future use, but it does not alter the CONDITIONAL verdict, does not touch P1 (HKS-based) at all, and does not resolve or worsen the Section 3 narrative-arc inconsistency — that fix is independent of EHRS and still outstanding.

---

**File read to confirm §3:** `/Users/dsf-pro16-m3/projects/defi-vehicle-currencies/output/nbc_pipeline/02_framings/framing_1.md`

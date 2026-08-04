# Candidate Framing #1 — "Liquidity Provision Makes (and Unmakes) the Vehicle"

Scope respected throughout: liquidity provision and vehicle currencies in DeFi/AMM markets only. No revival of the CDOM/asset-pricing/speculative-attack leg — I deliberately did **not** reach for Goldstein-Ozdenoren-Yuan (2011) or Ozdenoren-Yuan-Zhang (2023) even though the manifest flags them as usable templates, because both sit on the attack/asset-pricing side of the retired boundary, not the LP side.

---

## 1. Headline mechanism — the one or two claims this talk makes

**P1 (formation, self-reinforcing).** Vehicle-currency status in an AMM market is a liquidity-provision equilibrium, not a fixed technological fact about a token: LP capital concentrates around a candidate vehicle's pools because doing so lets LPs internalize a common risk factor once (the Yuan 2005 benchmark-liquidity logic, borrowed as theoretical analogy, not evidence); that concentration deepens the pool, which — holding volatility and informed-trading intensity fixed — mechanically lowers price impact on vehicle-routed trades (Lehár & Parlour 2024, Proposition 3: equilibrium AMM pool size rises in noise volume, falls in volatility/informed-trading probability); lower price impact lowers the effective cost of *indirect* (triangulated) routing relative to *direct* routing, which is exactly Krugman's (1980) transaction-cost vehicle-selection condition, reproduced here inside an AMM rather than assumed; and more indirect volume routed through the candidate feeds back into more LP capital being drawn to its pools — a volume↔depth loop that is Krugman's endogenous-cost feedback (F(V), F′<0), instrumented empirically via pool-level liquidity depth rather than posited.

**P2 (persistence and stress rotation, architecture-conditioned).** How sticky that equilibrium is — and how fast it can rotate to a different vehicle under stress — is governed by how cheaply LPs can reposition. Cheaper repositioning (lower gas / different-chain architecture) lets LPs re-concentrate liquidity faster in response to a volatility or demand shock (extending Caparros, Chaudhary & Klein 2024's causal gas-cost → repositioning-intensity → concentration channel, general on that paper, not yet run on vehicle-candidate pools specifically); by Lehár & Parlour's Prop. 3 comparative statics, that faster re-concentration should make vehicle-route depth — and hence vehicle status itself — more elastic to shocks. The comparative static: **architecture that cheapens LP repositioning trades stickiness for responsiveness** — a candidate vehicle should be harder to dislodge on a high-repositioning-cost venue and easier to dislodge (rotate away from) on a low-cost one.

Both propositions are stated purely in liquidity-provision terms — capital allocation, pool depth, price impact, repositioning cost — with no invocation of invoicing, reserve-currency, or asset-pricing channels.

---

## 2. Evidence hierarchy — headline vs. supporting, built vs. to-be-built

**Headline evidence (this paper's own contribution — must still be built):**

- **P1's test.** A time-series/panel exhibit linking candidate-linked liquidity $L_{k,t}$ (already defined and, per the brain's locked notation, backed by an existing contract-address-level V3 data construction: one-candidate pools get full TVL, two-candidate pools split half/half) to $\mathrm{DirectCostAdvantage}_{k,t,q}$ (already defined and sign-locked: median relative gap between direct and indirect quoted output on common support) and to indirect-route volume share. **Status: infrastructure built, headline result not yet run.** The manifest's own next-actions list still has "keep building/validating the unconditional vehicle-route value exhibit" as an open item, and explicitly warns it's "one empirical input, not the starting point" — so this is close to ready but not in hand.
- **P2's test.** An architecture-shock design applied specifically to vehicle-candidate pools, borrowing Caparros, Chaudhary & Klein's (2024) identification strategy (chain-launch IV for repositioning intensity, corroborated by a within-chain shock analogous to their ARB-airdrop test) — but their result as published is about general LP repositioning/concentration/slippage on ETH/USDC plus four robustness pairs across Ethereum/Arbitrum/Polygon, **not** about vehicle-candidate routing specifically. **Status: identification template exists in the literature, empirical implementation on this paper's candidate set does not exist yet.**

**Supporting/robustness (borrowed mechanisms and analogies, cited only to the letter Phase 1 licenses, never as this paper's own finding):**

- Lehár & Parlour (2024) — cite *only* for the narrow claim that constant-product (V1/V2) AMM pool size rises in noise trading and falls in volatility/informed-trading probability, and that under bounded conditions AMM price impact can be lower and less volatile than a comparable LOB's, tested only in their own 43-pair Binance comparison — not a general "AMMs beat order books" claim, not V3.
- Klein, Kozhan, Viswanath-Natraj & Wang (2026) — cite *only* for: net LP minting/burning near price has statistically significant short-horizon return-predictive content in one ETH/USDC pair (May 2021–Jul 2022), concentrated in the low-fee pool, via a recursive SVAR (predictive, not causal) — used here only to motivate that LP capital allocation is strategic/information-responsive, not passive, which is a load-bearing assumption behind P1's feedback loop.
- Caparros, Chaudhary & Klein (2024) — cite *only* for their own result (gas costs causally raise LP repositioning intensity/precision and liquidity concentration, professional not retail LPs, small-trade slippage falls on cheap chains) as the identification template for P2, not as evidence already obtained for this paper's vehicle-candidate set.
- Krugman (1980) — cite *only* for the specific three-country transaction-cost vehicle-selection mechanism and the volume→lower-cost→more-volume feedback loop under an endogenized cost function, used purely as a motivating theoretical analogy for what P1's regression is testing. Must not be presented as extending beyond three currencies, must not be treated as proving persistence-after-dominance-fades (Krugman explicitly disclaims the dynamic analysis), must not be treated as empirical.
- Yuan (2005) — cite *only* for the theoretical analogy that a liquid benchmark/common-factor asset can raise liquidity and price informativeness economy-wide, conditional on the specific assumption that market makers observe order flow across markets — flag explicitly as pure theory, not DeFi, not empirical, and conditional (not an assumption-free law).
- Somogyi (2026) — cite *only* as the TradFi-FX motivating comparator: ~13% of interdealer USD-pair volume is vehicle-currency (price-impact-reducing, not spread-reducing) routing, rising to 25–38% in majors, from a quasi-experimental holiday design — but note the C1–C3 panel-regression evidence behind the mechanism is explicitly non-causal and modest relative to an ~18–20% overall R² dominated by fixed effects (a caveat only one of two independent reads caught, so treat as live, not settled) — used to open the talk, not as DeFi evidence.
- Klein & Song (2021) and He, Khorrami & Song (2022) — cite *only* as brief TradFi structural analogies (liquidity commonality across venues; intermediary-capacity/inventory constraints driving liquidity-commonality patterns) — both explicitly disclaim any DeFi/crypto extension in their own safe-to-cite statements, so use only as "this pattern has a TradFi precedent," never as evidence for this paper's claims.

**Explicitly not re-derivable trusted evidence:** the pre-redesign `output/tables/*.pdf`, `core_empirical_rq_results.md`, `rq_memo.md` (dated 2026-07-17, pre-dating the redesign) are valid *inputs* to rebuild from, per the manifest, but must be independently re-checked against underlying data/scripts before any number from them appears on a slide — none of their captions are pre-cleared.

---

## 3. Narrative arc for a ~20-minute talk

Calibrated against the Phase 0-prime exemplars: classical-Beamer skeleton (title → outline → content under persistent section headers → conclusions → references) given the JFE-style target and mixed audience, but keeping the crypto-talk's visual discipline (one exhibit per slide, no dense equations live).

1. **Motivation (≈2 min).** Open with the FX vehicle-currency stylized fact (Somogyi 2026's ~13%/25–38% figures, explicitly flagged live as non-causal/fixed-effects-dominated) and pivot: "In FX, vehicle status is presumed to trace to fundamental dollar demand. In DeFi, transaction-level LP data lets us ask directly whether it instead traces to liquidity provision itself."
2. **The question, stated as P1/P2 (≈2 min).** State the two headline propositions in one slide each, in comparative-statics language, before any data appears.
3. **Mechanism scaffold (≈3–4 min).** One slide sketching the Krugman feedback loop, one showing Lehár & Parlour's Prop. 3 comparative statics, one showing the Yuan benchmark-liquidity analogy — explicitly labeled as borrowed theory/motivation, not this paper's contribution, to pre-empt the "is this your model?" question.
4. **Headline exhibit — formation (≈5 min).** The $L_{k,t}$ / DirectCostAdvantage / route-volume exhibit for the five-token candidate set (WETH/USDC/USDT/DAI/WBTC): show the feedback loop empirically. This is the paper's own result and gets the most slide-time.
5. **Architecture and stress rotation (≈4–5 min).** The gas-cost/repositioning-cost test (P2), plus one stress episode (a documented volatility or depeg event) showing vehicle-candidate liquidity reallocating faster on cheap-repositioning venues than expensive ones.
6. **Recap and contribution (≈2 min).** Restate P1/P2; position the contribution as: the first paper to treat vehicle-currency formation, stickiness, and stress rotation as directly measurable LP capital-allocation phenomena at the pool level, conditioned on architecture.
7. **Backup budget:** roughly matched to core content (per the Phase 0-prime "appendix-as-defense" takeaway) — pre-redesign RQ1-7 tables (flagged live as unverified), full regression tables, the older Beamer deck's material if any of it survives independent re-check, references slide(s) at full density.

---

## 4. Named, locatable bridging slide (old NBC abstract → this talk)

Caveat stated up front: I have not been shown or given a path to the actual text of the already-sent NBC abstract — only its label, "three-role/flight-to-dominance framing," as supplied in this task, and the manifest's pointer to the stale `slides/nanyang_vehicle_currencies.tex` deck (26 frames, Propositions 1-4b) as the artifact built on the old framing. The spec below is therefore a structural/content spec for what the bridge slide must accomplish, not a transcription of exact old wording I haven't read.

**Slide name/location:** **Slide 2, "From the abstract to this talk"** — placed immediately after the title slide and immediately before the outline slide (per the Kent Daniel / classical-Beamer skeleton the calibration file recommends), so it is the very first content the audience sees and pre-empts any "this isn't what the abstract said" reaction before the outline even loads.

**Exact content the slide states:**
- Top line: "The NBC abstract described three roles — quoting/invoicing, vehicle/intermediation, and reserve/settlement — with a flight-to-dominance story under stress."
- Second line, in bold: "This talk keeps only the vehicle/intermediation role, and re-derives it from liquidity provision rather than from asset-pricing or flight dynamics."
- Third line: "What's dropped, explicitly: the quoting/invoicing and reserve/settlement roles, and any claim about flight-to-dominance as a pricing or attack phenomenon."
- Fourth line: "What 'flight-to-dominance' becomes here: stress rotation of LP capital toward the deepest vehicle-linked pool — an architecture-conditioned liquidity-provision effect (Proposition 2), not a coordination or asset-pricing effect."
- Footer, small: "Full three-role framing remains the long-run agenda; today's talk is the liquidity-provision leg only."

This slide does one job only: it tells the room the talk is a deliberate narrowing of what they were promised, names exactly what was kept (vehicle role) and dropped (the other two roles, flight-to-dominance-as-attack), and re-labels the one abstract term that survives ("flight-to-dominance") with its new, liquidity-provision-only meaning — so the audience is never left wondering whether the speaker forgot the abstract or is quietly revising it.
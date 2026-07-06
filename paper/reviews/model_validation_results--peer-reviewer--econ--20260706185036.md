---
role: peer-reviewer
model: independent-agent
venue: econ
artifact: /Users/java/projects/defi-vehicle-currencies/paper/model_validation_results.md
reviewed_at: 2026-07-06T18:50:36+01:00
---

## Verdict — major revisions

## Findings — a numbered list; each finding gives the location, the issue, and a concrete suggested fix. Order by severity, most serious first.

1. **Location: Proposition 2 / Frozen main-test registry.** P2 is now explicitly downgraded to predictive association, which is appropriate, but this means the paper no longer identifies “liquidity feedback.” The title “Liquidity Feedback and Stickiness” still implies a mechanism stronger than the evidence. **Fix:** retitle P2 as persistence/predictability, remove causal feedback language, and state that reverse causality and common shocks are not ruled out.

2. **Location: Curve and Fluid materiality.** Curve and Fluid are material exclusions from the executable-depth route-cost panel: together they are `16.2%` of leg volume and heavily stablecoin-oriented. This is not a minor robustness caveat because it affects exactly the stablecoin comparison central to the paper. **Fix:** describe P1 as exact executable-depth evidence for covered venues only, and add a bound or sensitivity exercise showing how large excluded Curve/Fluid effects would need to be to overturn the WETH availability/thin-market conclusion.

3. **Location: Measurement / BridgeShare denominator robustness.** The all-route bridge share is only `5.3%` for WETH in 2026, while the paper-facing `44.5%` figure is conditional on indirect routing. This distinction is now acknowledged, but it remains central enough that any abstract/introduction claim could easily mislead. **Fix:** present both denominators wherever the main WETH share is introduced, and phrase the object as “conditional intermediary choice,” not overall DEX vehicle-currency share.

4. **Location: Proposition 1 / Route-cost distribution and economic weighting.** The artifact correctly narrows P1 to availability and thin-direct-market protection, but the section title “Route-Cost Advantage” still overstates the result because medians are small or negative at larger trade sizes and the evidence is skewed. **Fix:** rename the proposition and main table around “availability and thin-direct protection,” with cost advantage treated as heterogeneous rather than general.

5. **Location: Stress event specification.** The main P3 design uses the top 20 of 52 WETH downside days after imposing an 8% threshold and dropping absolute returns above 50%. This is now explicit, but the choice of top 20 remains discretionary, and four selected events overlap within 14 days. **Fix:** report sensitivity to using all 52 candidate events, non-overlapping events only, and alternative thresholds around 8%.

6. **Location: Stress-rotation decomposition.** The decomposed stress effect is clearer and more credible than the original aggregate result, but it remains a same-day event association. Hourly, weekly, and multi-day windows are weak or insignificant elsewhere in the artifact. **Fix:** make the same-day decomposition the only headline stress result and explicitly state that the paper does not establish persistent rotation.

7. **Location: V3 event-time and pre-trends / Frozen main-test registry.** The V3 main test is now narrowed to the no-direct/WETH-available decline, the only outcome without a detectable pretrend. That is the right move, but it supports a limited architecture claim, not a broad V3 launch causal claim. **Fix:** keep P4a narrowly framed as evidence that no-direct/WETH-available cases decline around V3 launch; avoid claiming V3 generally caused direct-route availability to rise.

8. **Location: V4 manual no-transfer audit.** The audit of the 25 largest V4 no-transfer route units strengthens the parser validation, but it is still a sample of 25 out of 93 no-transfer receipts. **Fix:** either audit all 93 no-transfer cases or explain why the largest 25 are the relevant stress test and provide random-sample audit results as a guard against selection.

9. **Location: V4 Settlement Virtualization.** Matching V3 and V4 routes by week, endpoint pair, and intermediate token may not fully balance route size, router, pool type, user mix, or gas conditions. The artifact reports size heterogeneity but not balance diagnostics. **Fix:** add a balance table and re-estimate the V4 transfer-incidence gap within route-size bins and router/pool-type controls.

10. **Location: Frozen main-test registry.** The registry is a useful discipline device, but the artifact only lists test labels, not estimands, samples, standard errors, or fixed effects. **Fix:** include a compact registry table with outcome, unit, sample, treatment/regressor, fixed effects, clustering, main coefficient, and interpretation for each proposition.

11. **Location: Current Paper Claim.** The paper is now closer to a coherent empirical spine, but the contribution remains narrower than “all four dimensions” suggests. P1 is covered-venue availability evidence, P2 is predictive association, P3 is same-day event rotation, P4a is a narrow V3 opportunity-set result, and P4b is settlement-mechanics evidence. **Fix:** write the contribution as a set of bounded empirical facts rather than a unified causal model unless the manuscript supplies stronger identification.

## Top priorities — the 1–3 things that matter most before this goes further.

1. Recast the paper’s central claim around bounded empirical facts, not causal propositions.

2. Contain the Curve/Fluid executable-depth limitation with explicit scope language and sensitivity/bounding.

3. Lock the main tables to the frozen registry with full specifications, standard errors, samples, and economic magnitudes.

---
role: peer-reviewer
model: independent-agent
venue: econ
artifact: /Users/java/projects/defi-vehicle-currencies/paper/model_validation_results.md
reviewed_at: 2026-07-06T19:52:22+01:00
---

## Verdict — major revisions

## Findings — a numbered list; each finding gives the location, the issue, and a concrete suggested fix. Order by severity, most serious first.

1. **Location: whole artifact / “Latest independent review status.”** The artifact is now internally candid, but it remains a validation memo rather than a paper-ready evidentiary presentation. It repeatedly says the remaining issues are “framing and scope control,” yet those are central to whether the claims are true. **Fix:** revise the manuscript claims first, then align every proposition title, abstract claim, and table caption with the narrowed evidence.

2. **Location: Proposition 2 / Frozen main-test registry.** P2 is correctly downgraded to predictive association, but the proposition still sits alongside other mechanism-style propositions and risks being read as evidence of liquidity feedback. The artifact explicitly says reverse causality, common demand shocks, token popularity, volatility, and router behavior are not ruled out. **Fix:** present P2 as a descriptive persistence/predictability fact, not as a proposition in the causal model.

3. **Location: Curve/Fluid materiality and scope diagnostics.** The Curve/Fluid issue is better bounded, but not solved. Exact-quote covered venues are `78.9%` of unified leg volume, while excluded Curve+Fluid are `16.2%` and `75.3%` stablecoin-leg. This means P1 cannot claim full-market executable-depth evidence. **Fix:** state in the main text that P1 is a covered-quoteable-venue result and keep Curve/Fluid as realized-measure robustness only, not executable-depth validation.

4. **Location: Curve/Fluid exclusion sensitivity.** Dropping Curve and Fluid does not overturn realized BridgeShare rankings, but the sensitivity is about realized vehicle shares, not counterfactual route costs. It does not answer whether stablecoin-heavy excluded venues would change the route-cost advantage comparison. **Fix:** separate these two claims explicitly: realized ranking is robust to excluding Curve/Fluid; executable-depth route-cost inference remains scoped.

5. **Location: Measurement / BridgeShare denominator robustness.** The all-route WETH bridge share is only `5.3%` despite indirect BridgeShare of `44.5%`. The artifact says both should be reported, but the Measurement section still leads with only indirect BridgeShare. **Fix:** introduce BridgeShare with both denominators immediately: WETH is leading conditional on indirect routing, while indirect vehicle routing is a small share of all route volume.

6. **Location: Proposition 1.** The common-support P1 table still reports a large positive t-statistic at `$100k` while the median advantage is `-0.4 bp` and WETH beats direct only `49.9%` of the time. This table can still be misread as general cost superiority. **Fix:** make the no-direct availability count and thin-direct advantage decomposition the main P1 table; move common-support median/t-stat rows to supporting heterogeneity.

7. **Location: Proposition 3 / Stress event specification.** The stress-rotation design is now much stronger: threshold and overlap sensitivities preserve sign and significance. The remaining issue is claim discipline: hourly, weekly, and longer-window results remain weak. **Fix:** call the result “same-day WETH downside rotation within indirect routes” and avoid generic “stress rotation” unless qualified each time.

8. **Location: Proposition 3.** The artifact still presents an earlier `5.4 pp` headline and later a decomposed `2.96 pp` effect. Both may be valid for different specifications, but the difference is not reconciled. **Fix:** designate one main estimate, explain the sample/specification difference, and use the decomposed estimate as the primary paper-facing number.

9. **Location: Proposition 4a / V3 event-time and pre-trends.** The narrowed V3 result is credible only for the no-direct/WETH-available outcome; other route-availability outcomes have positive pretrends. **Fix:** make P4a explicitly suggestive or appendix-level unless the paper can add a control group or stronger counterfactual for the V3 launch.

10. **Location: V4 balance diagnostics.** The V4 sample is not balanced on route size: V4 route units are smaller within matched cells, with log route-size difference `-0.692`, `p<0.001`. Because the V4 transfer-incidence gap is strongest for small routes, this imbalance is potentially material. **Fix:** make size-bin estimates the main V4 evidence or reweight/match V3 to the V4 size distribution.

11. **Location: V4 manual no-transfer audit.** Auditing all 93 no-transfer route units validates that the parser is not missing receipts or endpoint transfers. It still does not by itself prove economic equivalence of V3 and V4 route units. **Fix:** include representative audited examples tying the no-transfer pattern to V4 flash accounting, and report whether endpoint amounts match the inferred route units.

12. **Location: Frozen main-test registry.** The registry still lists labels rather than full specifications. A referee needs the unit of observation, sample, outcome, regressor/treatment, fixed effects, standard-error clustering, baseline mean, and economic magnitude. **Fix:** expand the registry into a specification table and make it part of the paper or appendix.

## Top priorities — the 1–3 things that matter most before this goes further.

1. Rewrite the paper around the narrowed claims: covered-venue WETH availability/thin-direct protection, predictive persistence, same-day stress rotation, limited V3 opportunity-set evidence, and V4 settlement mechanics.

2. Replace potentially misleading headline tables with the paper-facing main tests: no-direct/thin-direct P1, decomposed same-day P3, no-direct/WETH-available P4a, and size-adjusted V4 P4b.

3. Expand the frozen registry into full specifications with standard errors, fixed effects, baseline means, and economic magnitudes.

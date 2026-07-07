---
role: peer-reviewer
model: independent-agent
venue: econ
artifact: /Users/java/projects/defi-vehicle-currencies/paper/model_validation_results.md
reviewed_at: 2026-07-07T05:35:19+01:00
---

## Verdict — major revisions

## Findings — a numbered list; each finding gives the location, the issue, and a concrete suggested fix. Order by severity, most serious first.

1. **Location: whole artifact / Current Paper Claim.** The empirical spine is now much stronger, but the artifact still mixes bounded findings with proposition language that can sound causal or general. The strongest defensible paper is narrower: covered-venue WETH availability/thin-direct protection, predictive liquidity concentration, same-day stress rotation, limited V3 opportunity-set evidence, and V4 settlement mechanics. **Fix:** rewrite the paper’s abstract, introduction, proposition labels, and table captions to match those bounded claims exactly.

2. **Location: Curve and Fluid materiality / Curve/Fluid scope bound.** Curve and Fluid remain a material limitation for P1: excluded Curve+Fluid are `16.2%` of unified leg volume and `75.3%` stablecoin-leg. The realized BridgeShare ranking survives excluding them, but executable-depth counterfactual costs do not cover the full DEX universe. **Fix:** state that P1 is an exact executable-depth result for covered quoteable venues only, and do not imply full-market route-cost coverage.

3. **Location: Measurement / BridgeShare denominator robustness.** The Measurement section still leads with indirect BridgeShare only, while later diagnostics show WETH’s all-route bridge share is just `5.3%` versus `44.5%` conditional on indirect routing. This is a major interpretation risk. **Fix:** introduce both denominators together at first mention and define the estimand as “vehicle choice conditional on indirect routing.”

4. **Location: Proposition 1.** The common-support WETH table is still easy to overread as a route-cost advantage table, especially with large t-statistics despite the `$100k` median being `-0.4 bp` and WETH beating direct only `49.9%` of the time. **Fix:** make the no-direct availability rows and thin-direct value decomposition the main P1 evidence; move common-support cost comparisons to heterogeneity/supporting evidence.

5. **Location: Proposition 2 / P2 dynamic alignment.** The dynamic reduced-form table improves P2 alignment and appropriately avoids causal claims. However, “LP concentration predicts future BridgeShare” remains vulnerable to omitted time-varying token shocks and router behavior even with token/date fixed effects and current BridgeShare. **Fix:** present P2 as predictability only, include baseline means and economic magnitudes for beta values, and avoid mechanism language such as “liquidity feedback.”

6. **Location: Proposition 3 / Stress event specification.** The stress result is now robust across thresholds and non-overlap checks, but the paper still contains multiple effect sizes: `5.4 pp`, `3.09 pp`, `2.96 pp`, and threshold sensitivities around `-3 pp`. **Fix:** designate the decomposed same-day estimate as the main number, explain differences across specifications, and use one headline estimate consistently.

7. **Location: Proposition 3.** Hourly, weekly, and longer-window tests remain weak or insignificant. The evidence supports immediate same-day rotation, not persistent stress-state behavior. **Fix:** retitle or qualify P3 as “Same-Day Stress Rotation” and make attenuation outside the same-day window part of the interpretation.

8. **Location: Proposition 4a / V3 event-time and pre-trends.** The V3 result remains limited because direct-route and WETH-route availability have significant positive pretrends. Only no-direct/WETH-available cases lack a detectable pretrend. **Fix:** use only no-direct/WETH-available decline as the main P4a result and treat broader V3 architecture claims as suggestive.

9. **Location: V4 balance diagnostics / Proposition 4b.** V4 matched route units are significantly smaller than V3 route units within matched cells (`log route-size difference -0.692`, `p<0.001`), and the V4 transfer-incidence gap is strongest for small routes. This is a material compositional concern. **Fix:** report size-bin estimates as main evidence or reweight/match V3 to the V4 size distribution before presenting the headline V4 gap.

10. **Location: V4 manual no-transfer audit.** Auditing all 93 no-transfer route units supports the parser claim, but the artifact does not show representative trace examples tying the absence of intermediary ERC-20 transfers to V4 flash accounting. **Fix:** include one or two audited transaction examples showing endpoint transfers, route inference, and absence of external intermediary transfer.

11. **Location: Frozen main-test registry.** The registry lists the intended main tests but still lacks full specification detail. A referee needs unit of observation, sample, outcome, treatment/regressor, fixed effects, clustering, baseline mean, coefficient, and economic magnitude. **Fix:** expand the registry into a formal specification table before submission.

## Top priorities — the 1–3 things that matter most before this goes further.

1. Rewrite the paper around bounded, non-causal claims where identification does not support causality, especially P1 and P2.

2. Make the main evidence tables match the frozen registry: no-direct/thin-direct P1, dynamic predictive P2, decomposed same-day P3, no-direct/WETH-available P4a, and size-adjusted P4b.

3. Put the denominator and coverage limits in the main text: indirect versus all-route BridgeShare, and covered quoteable venues versus excluded Curve/Fluid executable-depth costs.

---
role: peer-reviewer
model: independent-agent
venue: econ
artifact: /Users/java/projects/defi-vehicle-currencies/paper/model_validation_results.md
reviewed_at: 2026-07-07T05:49:18+01:00
---

## Verdict — major revisions

## Findings — a numbered list; each finding gives the location, the issue, and a concrete suggested fix. Order by severity, most serious first.

1. **Location: Measurement / table_m01_measurement_scope.** The artifact still opens with WETH’s `44.5%` indirect BridgeShare, while the later scope table is needed to show that WETH’s all-route bridge share is only `5.3%` and exact-quote coverage is limited. This sequencing risks overstating the economic object. **Fix:** make `table_m01_measurement_scope` the first empirical table and introduce WETH’s role jointly as conditional indirect share plus all-route share plus quote-coverage scope.

2. **Location: Proposition 1 / table_m02_p1_availability_thin_direct.** The paper-facing table now uses the right headline, but the artifact still retains the common-support cost table where the `$100k` median advantage is `-0.4 bp` and WETH beats direct only `49.9%`. **Fix:** move the common-support cost table out of the main P1 narrative or explicitly label it as heterogeneity showing that WETH is not generally cheaper.

3. **Location: Curve and Fluid materiality / table_m01_measurement_scope.** Curve and Fluid remain a substantive coverage limitation: excluded Curve+Fluid are `16.2%` of unified leg volume and `75.3%` stablecoin-leg. The realized-ranking sensitivity helps, but it does not validate executable-depth route costs for excluded stablecoin-heavy venues. **Fix:** state in the abstract/main claim that route-cost evidence is for covered quoteable venues only; keep realized BridgeShare robustness separate from counterfactual quote evidence.

4. **Location: Proposition 2 / table_m03_p2_dynamic_predictability.** P2 is now properly downgraded to predictive association, and the dynamic table adds baseline means and 10 pp effects. But the proposition still cannot support liquidity-feedback mechanism claims because token/date fixed effects and current BridgeShare do not rule out time-varying token shocks or router behavior. **Fix:** keep P2 descriptive throughout and avoid placing it as a structural mechanism in the model.

5. **Location: Proposition 3 / table_m04_p3_stress_rotation.** The same-day decomposed stress table is the right main evidence, but the artifact still contains multiple headline magnitudes: `5.4 pp`, `3.09 pp`, and `2.96 pp`. **Fix:** designate `table_m04_p3_stress_rotation` as the sole headline estimate and relegate other specifications to robustness with a clear reconciliation.

6. **Location: Proposition 3.** Hourly, weekly, three-day, and seven-day windows remain weak or insignificant. The bounded claim is immediate same-day rotation, not stress-regime persistence. **Fix:** title P3 as “Same-Day Stress Rotation” and state that longer-window effects attenuate.

7. **Location: Proposition 4a / table_m05_p4a_v3_opportunity.** The paper-facing table now correctly focuses on no-direct/WETH-available decline, but the earlier text still says V3 “primarily changes the route-opportunity set by making direct routes feasible,” despite pretrends in direct-route and WETH-route availability. **Fix:** narrow the V3 claim to the no-direct/WETH-available outcome and avoid broader causal launch language.

8. **Location: Proposition 4b / table_m06_p4b_v4_settlement.** The size-bin table is necessary because V4 route units are smaller within matched cells (`log route-size difference -0.692`, `p<0.001`) and the transfer gap is strongest for small routes. **Fix:** make size-bin or size-adjusted estimates the headline V4 result, not the pooled `-18.6 pp` gap alone.

9. **Location: V4 manual no-transfer audit.** The audit of all 93 no-transfer route units supports receipt parsing, but the artifact still does not show trace-level examples connecting absent intermediary ERC-20 transfers to V4 flash accounting. **Fix:** include representative audited transactions with endpoint transfers, route-unit inference, and absence of intermediary transfer.

10. **Location: table_m07_specification_registry.** The registry now appears to include the right fields, but the artifact does not report the actual entries. A reviewer still cannot inspect the units, samples, inference choices, baseline means, and interpretations from this memo alone. **Fix:** include the registry table contents in the paper or appendix, not only the filename.

## Top priorities — the 1–3 things that matter most before this goes further.

1. Make the new paper-facing tables, especially `m01` through `m07`, the actual manuscript spine and remove older headline numbers that conflict with them.

2. Put the two scope limits in the main claim: BridgeShare is conditional on indirect routing, and P1 route-cost evidence covers quoteable venues excluding material stablecoin-heavy Curve/Fluid.

3. Keep P2 and P4a non-causal unless stronger identification is added.

---
role: peer-reviewer
model: independent-agent
venue: econ
artifact: /Users/java/projects/defi-vehicle-currencies/paper/model_validation_results.md
reviewed_at: 2026-07-06T14:58:03+01:00
---

## Verdict — reject

## Findings — a numbered list; each finding gives the location, the issue, and a concrete suggested fix. Order by severity, most serious first.

1. **Location: whole artifact / “Current Paper Claim.”** The document is a validation memo, not a paper-ready evidentiary package. It reports many headline estimates without enough specification detail to judge identification, sampling, standard errors, clustering, fixed effects, event definitions, or construction of denominators. As a referee, I cannot verify whether the claims follow from the analysis. **Fix:** for each proposition, state the exact estimating equation, unit of observation, sample window, inclusion/exclusion rules, fixed effects, standard-error treatment, and identifying assumption.

2. **Location: Proposition 1.** The table reports statistically significant WETH “advantages” even when the median advantage is negative at `$100k` trade size. This creates an internal inconsistency: the reported `t=63.95` cannot be interpreted as evidence of economically positive cost advantage if the median effect is `-0.4 bp`. **Fix:** clarify what the t-statistic tests, report mean effects alongside medians, show the distribution, and rewrite the claim around availability/thin-direct protection rather than cost dominance.

3. **Location: Proposition 1 / Measurement.** `BridgeShare` is based only on “indirect routes,” but the paper’s economic claim concerns vehicle-currency use relative to the full routing opportunity set. Conditioning on indirect routes may mechanically inflate vehicle-token importance and obscure substitution into direct routes. **Fix:** report analogous shares using all route volume, direct-route availability, and endpoint-pair opportunity sets; justify why the indirect-route denominator is the right object.

4. **Location: Proposition 2.** The liquidity-feedback result is described as a “within-token association” and persistence result, but the text repeatedly gestures toward a causal feedback channel. This is not identified: LP concentration may respond to expected future bridge use, common shocks, token popularity, volatility, exchange listings, or routing-algorithm changes. **Fix:** either downgrade the claim to predictive association or provide a credible identification strategy, such as shocks to executable liquidity plausibly orthogonal to expected bridge use.

5. **Location: Proposition 2.** The artifact says the result “should still strengthen the specification” with date fixed effects, near-price executable liquidity, and LP repositioning, but then later says the slope “survives token and date fixed effects.” These statements are hard to reconcile. **Fix:** separate current main specification from robustness specifications and report the coefficient changes across them.

6. **Location: Proposition 2 / Current Paper Claim.** The V3 mint/burn repositioning evidence cuts against the proposed mechanism: near-price repositioning is negative at several horizons. The memo says this should be “referee-proofing diagnostic,” but a referee would view it as a threat to the liquidity-feedback interpretation. **Fix:** either explain why negative repositioning is consistent with the mechanism or remove repositioning as mechanism evidence and narrow P2 substantially.

7. **Location: Proposition 3.** The stress-rotation evidence is fragile across frequency and horizon. The daily estimate is significant, but hourly and weekly checks are insignificant, the two-day window is marginal, and longer windows fail. This supports at most a same-day event association, not a general stress-rotation mechanism. **Fix:** make the event timing, stress definition, and economic channel explicit; present the null hourly/weekly results prominently; avoid language suggesting persistence or broad stress-state substitution.

8. **Location: Proposition 3.** The event design uses “large WETH downside events,” but the artifact does not define the event threshold, event count for the main result, overlap handling, or whether events coincide with market-wide crypto shocks. **Fix:** provide an event table, define treatment and baseline windows, show placebo distributions, and control for broad market stress or stablecoin-specific shocks where possible.

9. **Location: Proposition 3.** The dependent variable `WETH-minus-stable bridge share` may mechanically move if stablecoin route availability changes during stress, not because users actively rotate away from WETH. **Fix:** decompose the effect into WETH-route loss, stablecoin-route gain, total indirect-route volume, and direct-route substitution within the same endpoint-pair sets.

10. **Location: Proposition 4a.** The V3 launch design is not credible as causal evidence without addressing contemporaneous DeFi market growth and changing token-pair composition around May 5, 2021. A before/after pair fixed-effect design may still confound V3 launch effects with broad market maturation. **Fix:** add a control group of pairs/protocols not exposed to V3 launch, event-time plots, pre-trends, and pair-specific liquidity controls.

11. **Location: Proposition 4a.** The common-support WETH advantage falls by `647 bp` but is statistically insignificant. This is economically large and imprecise, yet the interpretation leans toward “V3 primarily changes the route-opportunity set.” **Fix:** report confidence intervals and sample size; discuss whether the estimate is too noisy to distinguish price effects from feasibility effects.

12. **Location: Proposition 4b.** The V4 settlement result compares V3 and V4 receipt-level route units, but the artifact does not establish comparability. V4 routes may differ by router, user type, pool composition, size, gas conditions, or time period. **Fix:** specify the matching design, balance diagnostics, and whether route-unit composition is comparable across V3 and V4.

13. **Location: Proposition 4b.** The claim that V4 “partially virtualizes settlement” relies on ERC-20 transfer incidence, but transfer absence may reflect router accounting conventions or trace parsing rather than economic settlement virtualization. **Fix:** validate the receipt parser against known V4 flash-accounting examples and show that missing intermediary transfers correspond to economically equivalent routed swaps.

14. **Location: Current Paper Claim.** The exclusion of Curve and Fluid from exact executable-depth quotes is called “defensible,” but this is a major coverage limitation, not merely a caveat. These venues are central to stablecoin and DeFi routing. **Fix:** quantify the volume/opportunity share excluded by Curve and Fluid and show that the main conclusions are not driven by omitting venues where stablecoin vehicles are especially important.

15. **Location: Current Paper Claim.** The transaction-time quote robustness is limited to hourly V2/Sushi V2 reserves, while V3 quotes rely on reconstructed tick-net states. The memo itself warns not to call this exact V3 tick replay. **Fix:** state this limitation in the main identification section and avoid claiming transaction-time executable quote validation for the full route-cost panel.

16. **Location: Measurement / Proposition 1.** The artifact reports large row counts but not economic weighting. Equal-weighted route rows may overstate relevance if many rows are tiny or economically inactive. **Fix:** report volume-weighted estimates, endpoint-pair-weighted estimates, and sensitivity to excluding low-volume pairs.

17. **Location: all propositions.** Economic significance is inconsistently developed. Some effects are in basis points, some in percentage points, and some only in t-statistics. **Fix:** translate each main estimate into dollar cost savings, route-volume reallocation, or economically meaningful market share changes.

18. **Location: all propositions.** Multiple testing is a concern. The artifact reports many horizons, trade sizes, filters, event windows, and robustness slices, with selective emphasis on significant results. **Fix:** pre-specify the main tests, report the full family of estimates, and address false-discovery or selection concerns.

19. **Location: Literature/positioning absent from artifact.** The artifact gives no evidence that the contribution is novel relative to existing work on DEX routing, intermediary assets, Uniswap V3 concentrated liquidity, stablecoin liquidity, or settlement mechanics. **Fix:** add a literature-positioning section that identifies exactly what prior work has shown and what this paper newly identifies.

20. **Location: Current Paper Claim.** The final “JFE-safe claim” is still too broad for the evidence. The strongest supported claims are descriptive and associational, while the propositions imply mechanisms. **Fix:** recast the paper as descriptive evidence on vehicle-token routing unless stronger causal designs are added for liquidity feedback, stress rotation, and architecture effects.

## Top priorities — the 1–3 things that matter most before this goes further.

1. Narrow the claims: the current evidence supports descriptive route availability, thin-market protection, and short-window associations, not full causal propositions.

2. Provide complete specifications and identification arguments for each proposition, including units, samples, fixed effects, standard errors, event definitions, and weighting.

3. Resolve construct-validity gaps in route-cost measurement, especially excluded Curve/Fluid coverage, indirect-route denominators, and transaction-time quote limitations.

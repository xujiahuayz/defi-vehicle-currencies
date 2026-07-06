# JFE Pre-Write Independent Review

Independent review verdict: the empirical spine is promising, but the current
package is not yet JFE-standard for a full manuscript write-up. It is credible
enough for an internal empirical memo. It is not yet strong enough to write as a
JFE submission draft without narrowing claims and upgrading inference.

## Blockers before write-up

1. **Route-cost construct validity.** The main route-cost table supports WETH
   route availability and thin-direct-route protection, not a universal WETH
   cost advantage. Once direct-route quality filters are imposed, WETH's
   advantage shrinks or turns negative. The core P1 exhibit should be reframed
   around no-direct/thin-direct availability and tail execution protection.

2. **Liquidity feedback is predictive association.** Current P2 tests are strong
   correlations with forward BridgeShare, including token/date fixed effects.
   They do not identify LP supply as causal. Main-paper language should say
   "vehicle-linked liquidity predicts future bridge use" unless near-price
   executable liquidity, LP repositioning, or a cleaner shock design is added.

3. **Inference needs journal-grade dependence handling.** Several current tables
   use classical standard errors or one-sample t-tests over mechanically related
   rows. Before writing, redo central inference at the appropriate unit:
   endpoint pair/date for route costs, token/date for liquidity, event for
   stress, matched cell for V4.

4. **Stress evidence is daily, not yet the advertised high-frequency design.**
   The daily common-support event design is useful, but the paper should either
   port the high-frequency/common-support panel or explicitly write the claim as
   a daily event-level result. The top-10-stress-only slice is negative but not
   statistically significant.

5. **V3 architecture remains a screen.** The launch-window V3 result should stay
   appendix/suggestive until connected to pair-level direct-route feasibility or
   route-cost changes.

## Appendix / referee-proofing gaps

- Clustered, HAC, block-bootstrap, or randomization inference for central tests.
- Fee versus price-impact decomposition in route-cost results.
- Explicit caveat or extension for Curve/Balancer/Fluid executable-depth quote
  coverage.
- Transaction-time or pre-trade quote-state robustness, rather than only daily
  state cutoffs.
- V4 matched-cell balance diagnostics: route size, vehicle composition, sampling
  design, and receipt coverage.
- Stress placebo dates and, if useful, placebo non-vehicle tokens.
- More explicit defense of BridgeShare, especially because 2026 count-weighted
  bridge use makes stablecoins co-dominant with or ahead of WETH.

## JFE-safe claim language

- Strong: BridgeShare isolates route intermediation from endpoint demand.
- Strong: WETH remains the leading volume-weighted route intermediary, while
  stablecoins are co-dominant on count and coverage measures.
- Strong: vehicle routes are availability and tail-execution infrastructure in
  thin or missing direct markets.
- Softer: route-cost and availability advantages are consistent with vehicle
  usefulness.
- Softer: vehicle-linked liquidity is strongly associated with future bridge use
  and persistence.
- Softer: V3 evidence is suggestive; V4 evidence shows partial settlement
  virtualization conditional on matched route use.

## Recommended exhibit spine

1. Measurement: BridgeShare versus VShare, with WETH/stablecoin evolution.
2. Route-cost availability: direct availability, WETH availability, common-support
   advantage, no-direct rows, and quality-filter caveat in one exhibit.
3. Thin/no-direct value-of-role exhibit as the core P1 display.
4. Liquidity association table, explicitly predictive, with stronger inference.
5. Stress common-support event figure/table, preferably high-frequency if ported.
6. V4 settlement table with matched-cell design, transfer incidence, and size
   heterogeneity.

Move to appendix: all-vehicle route costs, V3 aggregate launch screen, broad
robustness variants, measurement variants, and V4 token heterogeneity.

## Fix-pass status

Implemented before write-up:

- Reframed the main route-cost exhibit around direct-route availability,
  WETH-route availability, no-direct rows, common-support medians, and
  high-quality-direct medians.
- Added date-clustered inference to the liquidity-feedback robustness table.
- Recomputed route-cost robustness at the endpoint-pair-day unit instead of
  relying only on mechanically related quote rows.
- Added V4 matched-cell balance diagnostics for route size and receipt-log
  balance.
- Softened the model-validation memo so P1/P2/P3/P4 are stated as first-pass
  evidence with limited causal interpretation.

Fixed in the pre-write blocker pass:

- High-frequency stress is ported as an hourly common-support event panel. It is
  directionally negative but weaker than the daily design: WETH-minus-stable
  BridgeShare falls by 1.71 pp, with \(t=-1.46\), \(p=0.161\). This means the
  main stress claim should still be written around the daily common-support
  event evidence, while the hourly panel is a robustness/discipline check rather
  than the headline.
- A weekly common-support version also weakens rather than strengthens the stress
  evidence: the event-week effect is -1.15 pp, with \(t=-0.98\), \(p=0.340\).
  Weekly aggregation reduces noise but also averages away the short stress
  rotation, so it should be used to show that the daily result is event-window
  specific rather than persistent over a full week.
- Curve/Balancer/Fluid executable-depth coverage is now documented. Balancer
  weighted-pool quotes are feasible from daily balances, weights, decimals, and
  swap fees. Curve and Fluid should be excluded from exact executable-depth
  quotes in the current paper unless new state data are fetched: Curve lacks the
  amplification/ramp state needed for audited StableSwap quotes, and Fluid's
  Dune data lacks reserve/depth state.
- Transaction-time quote-state robustness is now built for V2/Sushi V2 hourly
  reserves. Route-hour and daily-state WETH route-cost advantages have median
  differences of 0 bp across all three trade sizes, same-sign shares of 76.4%,
  80.4%, and 93.3%, and winsorized correlations of 0.726, 0.911, and 0.948.
- Stress event-window and placebo checks are built. They support a short-window
  interpretation: the one-day stress effect is negative and significant, the
  two-day effect is marginal, and three-/seven-day effects wash out. The shifted
  placebo does not reproduce the same same-day negative effect.
- P1 route-cost decomposition is built. It confirms that the defensible claim is
  availability and thin-direct-market protection, not universal WETH cheapness.
- Balancer weighted-pool quote extension is built. It does not add direct-route
  or WETH-route availability beyond the existing route-cost panel in the matched
  WETH counterfactual universe, so excluding Balancer from the main P1 panel is
  empirically harmless for the current claim.
- V3 LP repositioning is built as a mechanism diagnostic. It does not deliver a
  clean positive mechanism result and should not be elevated into the main P2
  claim without a better identification design.
- V3 architecture is upgraded from an aggregate screen to a pair-level
  route-feasibility design. Direct-route availability rises sharply after V3
  launch in the balanced endpoint-pair sample, and no-direct/WETH-available
  cases fall. This is a usable architecture result, but the interpretation is
  route-opportunity expansion rather than a pure WETH price-advantage effect.

Still deliberately not fixed before write-up:

- Exact V3 transaction-time replay remains an extension; the current quote-state
  robustness is hourly constant-product, not full event-level V3 tick replay.

## Second independent review after pre-write diagnostics

After adding the stress-window/placebo checks, P1 decomposition, LP
repositioning diagnostic, V3 pair-level architecture design, Balancer weighted
quote extension, hourly/weekly stress, transaction-time quote-state robustness,
and non-Uni quote-coverage/exclusion diagnostics, a second independent reviewer
still gave the empirical package a **reject** verdict for JFE if written as
full model validation.

The reviewer's bottom line is not that the project is unpublishable. It is that
the current analytics support a narrower descriptive/associational paper better
than a broad causal mechanism paper. The evidence is strongest for route
availability, thin-direct-market protection, BridgeShare measurement, and
short-window event associations. It is weaker for causal LP feedback, persistent
stress-state rotation, and architecture effects unless those designs are
tightened further.

Highest-priority fixes before a JFE-style write-up:

1. Write a complete empirical specification registry for every proposition:
   estimating equation, unit of observation, sample window, inclusion/exclusion
   rules, fixed effects, clustering/bootstrapping, weights, and identifying
   assumption.
2. Strengthen construct validity for vehicle use: report BridgeShare with the
   indirect-route denominator, all-route denominator, direct-route substitution,
   and endpoint-pair opportunity-set variants.
3. Rebuild the P1 route-cost table around distributions, mean and median
   effects, economic weights, no-direct availability, thin-direct protection,
   and dollar cost savings. Do not let significant t-statistics imply positive
   cost dominance when the median effect is negative.
4. Downgrade P2 unless a better identification design is added. LP
   concentration predicts future bridge use, but repositioning does not provide
   a clean positive mechanism result.
5. Decompose P3 into WETH loss, stablecoin gain, total indirect-route volume,
   and direct-route substitution. Add event definitions, placebo distributions,
   event tables, and broad-market-stress controls.
6. Tighten P4a with event-time/pre-trend evidence and a credible control group
   or keep it as architecture evidence rather than causal V3 evidence.
7. Tighten P4b with matched-cell details, balance diagnostics, and parser
   validation against known V4 flash-accounting examples.
8. Quantify Curve and Fluid exclusion as a material coverage limitation, and
   show whether the main conclusions survive without assuming executable-depth
   quotes for stablecoin-heavy venues.
9. Report volume-weighted, endpoint-pair-weighted, and low-volume-exclusion
   variants for the central estimates.
10. Pre-specify the main tests and report the full robustness family to reduce
    multiple-testing and selective-emphasis concerns.

Implication for project strategy: if the target remains JFE, the next empirical
round should be a specification/identification/construct-validity round, not a
new descriptive-exhibit round and not prose drafting.

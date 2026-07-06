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

Still deliberately not fixed before write-up:

- High-frequency stress is not ported. The write-up must use the narrower daily
  common-support event claim unless this panel is built later.
- V3 architecture remains appendix/suggestive.
- Curve/Balancer/Fluid executable-depth quotes and transaction-time quote-state
  robustness remain extension/referee-proofing items, not current main claims.

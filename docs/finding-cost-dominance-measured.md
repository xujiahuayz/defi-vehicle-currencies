# Direct-route cost domination exists, but the V2-family survivor panel cannot identify market maturation

Built by `scripts/build_counterfactual_dominance.py` from strict pre-transaction pool state and calibrated by `scripts/process/build_route_gas_units.py`. The canonical outputs are `data/processed/counterfactual_dominance.parquet`, `output/exhibits/counterfactual_dominance_summary.jsonl`, `output/exhibits/counterfactual_dominance_support.jsonl`, and `output/exhibits/route_gas_units_summary.jsonl`.

The mixed-venue construction audit is built by `scripts/build_transaction_state_frontier.py --audit-calendar`; its tracked summaries are `output/exhibits/transaction_state_frontier_audit_summary.jsonl` and `output/exhibits/transaction_state_frontier_audit_support.jsonl`, with the audit row panel at `data/processed/transaction_state_frontier_audit.parquet`. Only after that audit passes does `--daily-calendar` publish the distinct analysis input at `data/processed/transaction_state_frontier_daily.parquet`.

This document supersedes every earlier figure based on the retired 103,857-route enumerated panel, the four-day matched panel, pooled gas constants, or hour-end state. In particular, 17.9%, 30.0%, 27.2%, 41.3%, and 70.1% are not admissible paper findings.

## Estimand

For each realised two-leg route in the Uniswap V2 and SushiSwap V2 families, the estimator asks whether an available one-leg pool would have returned more output for the exact realised input. The two alternatives share the same endpoints, transaction order, reconstructed pre-transaction state, token prices, and historical gas price. Reserve state is advanced through intervening swaps, mints, and burns. The comparison therefore measures a direct path omitted by a realised legacy two-hop route. It does not enumerate every path a contemporary multi-venue router could have chosen.

The fixed calendar contains 74 one-day snapshots stratified by calendar month; 73 are nonempty, yielding 45,720 unique comparable routes from June 2020 through June 2026. There are no duplicate route identifiers and no missing all-in estimates.

## Main level result and economic magnitude

The direct pool returns more gross of gas on 5,361 routes, or 11.7% (date-clustered 95% interval 8.8% to 14.7%). Equal weighting across the 73 nonempty dates gives 13.2%, with a daily interquartile range of 8.1% to 15.6%. Within the prespecified 20% input/output valuation-coherence band, 4,291 of 40,773 routes are cost-dominated, or 10.5% (7.8% to 13.2%); equal-date weighting gives 11.0%. The median gross direct advantage among strict-support cost-dominated routes is 58.2 basis points of input notional.

Historically priced, receipt-calibrated gas changes the economic comparison materially. The direct route is cheaper all-in on 14,229 routes, or 31.1% (26.8% to 35.5%). Within strict value support, the cost-domination incidence is 30.9% (26.4% to 35.5%), and substituting the lower and upper quartiles of matched gas cells gives 24.3% and 35.8%. Equal-date weighting lowers the strict estimate to 22.1%, with a daily interquartile range of 11.8% to 31.7%. The distinction matters: routing activity is concentrated on dates with higher cost-domination incidence.

Incidence is not loss magnitude. Within strict value support, the median all-in advantage among cost-dominated routes is 128.4 basis points but the median dollar saving is only $8.43. The sum across the sampled dates is $836,745, of which the top 1% of cost-dominated routes supply 72.8%; 67.7% of cost-dominated routes have notional below $1,000. The unconstrained $108.2 million aggregate is inadmissible because 99.1% comes from its top 1% and the underlying tail fails value coherence. The evidence establishes a frequent, concentrated fixed-cost and search friction. It does not establish a large representative welfare loss.

| intermediary type | routes | gross cost domination | strict-value gross cost domination | median-gas all-in cost domination | gas-IQR range |
|---|---:|---:|---:|---:|---:|
| imported | 1,129 | 8.7% | 8.4% | 51.6% | 40.6–63.9% |
| native | 12,395 | 8.4% | 7.3% | 17.1% | 12.9–22.1% |
| other | 6,430 | 10.2% | 6.4% | 16.4% | 12.0–22.6% |
| stable | 25,766 | 13.8% | 13.2% | 40.7% | 33.1–44.4% |

The gross result says most legacy two-hop routes beat the available direct pool on quote output. The all-in result says the extra execution burden overturns that output advantage often, especially for stable and imported intermediaries. These are different economic objects and both belong in the paper.

## Gas is measured as route support, not a pooled constant

The receipt panel samples 31,128 successful transactions across 77 one-day snapshots stratified by calendar month and 2,655 year-by-topology-by-venue-by-vehicle cells. Median gas use is 162,413 units for one-leg routes, 325,007 for two-leg routes, and 422,210 for three-leg routes. On 162 same-year, same-executor, same-venue comparisons, a repeated-venue second leg adds a median 67,172 units, with an interquartile range of 44,342 to 98,984; 90.1% of cells have a positive increment.

Every cost-domination observation matches the direct leg at year-by-venue-by-vehicle support. The realised vehicle route matches that same level for 39,290 observations and year-by-venue-by-type for the remaining 6,430. Broader topology fallbacks exist in code but are unused here. Gas uncertainty is retained in the estimand through the matched-cell interquartile range.

The fixed-cost pattern is visible by realised notional:

| notional | strict routes | strict gross cost domination | strict median-gas cost domination | median saving if cost-dominated |
|---|---:|---:|---:|---:|
| $100–1,000 | 17,842 | 12.8% | 47.8% | $6.10 |
| $1,000–10,000 | 18,096 | 9.4% | 20.6% | $13.85 |
| $10,000–100,000 | 4,616 | 6.3% | 7.5% | $95.28 |
| above $100,000 | 219 | 5.0% | 5.0% | $3,559.90 |

Gas flips many small routes and almost none of the large strict-support routes. The full-sample gross 20.4% rate above $100,000 is a valuation-tail artefact: only 219 of the 534 routes remain on strict support and their gross incidence is 5.0%.

## State support and venue reach

The result does not depend on one reserve-reconstruction class.

| reserve support | routes | gross cost domination | strict-value gross cost domination | median-gas all-in cost domination | gas-IQR range |
|---|---:|---:|---:|---:|---:|
| adjacent, no liquidity event | 7,777 | 13.5% | 11.7% | 29.7% | 22.6–34.7% |
| bridged, no liquidity event | 4,384 | 9.7% | 7.8% | 21.1% | 14.7–28.0% |
| liquidity replayed | 33,559 | 11.6% | 10.6% | 32.8% | 26.7–37.0% |

Only 1,030 of the 5,361 gross-dominated routes, or 19.2%, use a best direct pool outside the realised route's venue set. Most detected misses are therefore within observed V2-family venue reach. This does not prove the executor knew the pool or authored the quote.

## Multi-family exact-state pilot

The first V2/V3/V4 frontier pilot prices 2025-06-15 at strict pre-transaction state. Of 14,650 exact two-leg routes, 13,975, or 95.39%, use only those three supported venue families: 6,247 are V2-only, 5,086 are V3/V4-only, and 2,642 mix families. Raw transaction-log identities map all 13,975. After the $100 input floor, 7,939 routes remain; 7,760 chosen paths can be re-quoted, 238 fail the 1% chosen-output validation, and 7,522 enter the diagnostic frontier. On the primary 20% valuation-coherence support, 7,567 chosen paths are quotable and 7,515 pass, a 99.31% reproduction rate. V2 alternatives are unavailable for 439 target routes whose V4-only source rows expose no block number; those routes retain a V3/V4 opportunity-set bound.

On the 7,515 coherent routes carrying $12.00 million of input, 42.48% have best-public-path regret above 0.01 basis points, 35.60% exceed 1 basis point, and 17.33% exceed 10 basis points. The median is effectively zero and the 90th percentile is 29.29 basis points. Mean within-observed-reach search regret is 1.36 basis points, mean public-reach expansion is 14.09 basis points, and mean vehicle/path-choice expansion is 0.42 basis points. The reach mean is tail-sensitive: its median is zero and one route reaches 54,157 basis points. Direct paths are available on 14.54% of scored routes and strictly improve 3.43%. The sampled aggregate public-path gain is $12,258, of which the top 1% supply 65.3%.

This is a support and arithmetic pass, not a maturation finding. The unqualified positive-regret rate is not economically interpretable because it counts floating-point improvements near $10^{-12}$ basis points. The single date cannot identify a time trend; the top tail still mixes routing mistakes with arbitrage, liquidation, private intent, and token-specific anomalies; and an executor address does not identify the quote author or an aggregator. F must run the 77-date audit calendar, one exact daily snapshot per calendar month, and report the 0.01, 1, and 10 basis-point thresholds before G can assign mechanism weight.

## Why this is a level bound, not a maturation trend

Comparable support is concentrated early: 16,075 routes in 2020 and 21,907 in 2021, then 3,155 in 2022, 2,028 in 2023, 1,817 in 2024, 629 in 2025, and 109 in 2026. The late observations are survivors inside a shrinking legacy-venue perimeter while routing migrates to concentrated liquidity, new venues, aggregators, and universal routers. Annual cost-domination rates therefore mix efficiency with endogenous support exit.

The correct market-maturation design must hold the public opportunity set, endpoint pair, size, vehicle, and observed reach fixed while expanding transaction-state coverage across venues. It should separately measure direct-path omission, same-vehicle search shortfall, best-public-path regret, route integration, and path complexity. Executor heterogeneity can be reported only after establishing that an executor identifies the quote-authoring system.

## Permitted interpretation

The admissible claim is narrow and economically useful: direct-route cost domination exists on legacy V2-family support, and historically measured fixed execution costs make it substantially more common than quote-output comparisons imply. The median dollar consequence is small and the aggregate is concentrated. This shows that a vehicle can retain realised flow when a direct path is cheaper all-in, which opens the state required for a persistence test but does not establish persistence itself.

It does not yet show that a particular vehicle retains the role because of inertia, that aggregators caused convergence, or that market-wide routing became more efficient. The V2-family incidence is a lower bound with respect to omitted direct venues, but not a population estimate because support selection can work in either direction.

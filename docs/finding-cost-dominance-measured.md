# Direct-route dominance exists, but the V2-family survivor panel cannot identify market maturation

Built by `scripts/build_counterfactual_dominance.py` from strict pre-transaction pool state and calibrated by `scripts/process/build_route_gas_units.py`. The canonical outputs are `data/processed/counterfactual_dominance.parquet`, `output/exhibits/counterfactual_dominance_summary.jsonl`, `output/exhibits/counterfactual_dominance_support.jsonl`, and `output/exhibits/route_gas_units_summary.jsonl`.

This document supersedes every earlier figure based on the retired 103,857-route enumerated panel, the four-day matched panel, pooled gas constants, or hour-end state. In particular, 17.9%, 30.0%, 27.2%, 41.3%, and 70.1% are not admissible paper findings.

## Estimand

For each realised two-leg route in the Uniswap V2 and SushiSwap V2 families, the estimator asks whether an available one-leg pool would have returned more output for the exact realised input. The two alternatives share the same endpoints, transaction order, reconstructed pre-transaction state, token prices, and historical gas price. Reserve state is advanced through intervening swaps, mints, and burns. The comparison therefore measures a direct path omitted by a realised legacy two-hop route. It does not enumerate every path a contemporary multi-venue router could have chosen.

The fixed calendar contains 74 monthly dates; 73 are nonempty, yielding 45,720 unique comparable routes from June 2020 through June 2026. There are no duplicate route identifiers and no missing all-in estimates.

## Main level result

The direct pool returns more gross of gas on 5,361 routes, or 11.7%. Within the prespecified 20% input/output valuation-coherence band, 4,291 of 40,773 routes are dominated, or 10.5%. The median gross direct advantage among dominated routes is 76.7 basis points of input notional.

Historically priced, receipt-calibrated gas changes the economic comparison materially. The direct route is cheaper all-in on 14,229 routes, or 31.1%. Substituting the lower and upper quartiles of the matched gas cells gives 24.8% and 35.8%. The median all-in advantage among dominated routes is 134.7 basis points.

| intermediary type | routes | gross direct dominance | strict-value gross dominance | median-gas all-in dominance | gas-IQR range |
|---|---:|---:|---:|---:|---:|
| imported | 1,129 | 8.7% | 8.4% | 51.6% | 40.6–63.9% |
| native | 12,395 | 8.4% | 7.3% | 17.1% | 12.9–22.1% |
| other | 6,430 | 10.2% | 6.4% | 16.4% | 12.0–22.6% |
| stable | 25,766 | 13.8% | 13.2% | 40.7% | 33.1–44.4% |

The gross result says most legacy two-hop routes beat the available direct pool on quote output. The all-in result says the extra execution burden overturns that output advantage often, especially for stable and imported intermediaries. These are different economic objects and both belong in the paper.

## Gas is measured as route support, not a pooled constant

The receipt panel samples 31,128 successful transactions across 77 monthly dates and 2,655 year-by-topology-by-venue-by-vehicle cells. Median gas use is 162,413 units for one-leg routes, 325,007 for two-leg routes, and 422,210 for three-leg routes. On 162 same-year, same-executor, same-venue comparisons, a repeated-venue second leg adds a median 67,172 units, with an interquartile range of 44,342 to 98,984; 90.1% of cells have a positive increment.

Every dominance observation matches the direct leg at year-by-venue-by-vehicle support. The realised vehicle route matches that same level for 39,290 observations and year-by-venue-by-type for the remaining 6,430. Broader topology fallbacks exist in code but are unused here. Gas uncertainty is retained in the estimand through the matched-cell interquartile range.

The fixed-cost pattern is visible by realised notional:

| notional | routes | gross direct dominance | strict-value gross dominance | median-gas all-in dominance | gas-IQR range |
|---|---:|---:|---:|---:|---:|
| $100–1,000 | 20,544 | 13.9% | 12.8% | 46.7% | 37.9–52.4% |
| $1,000–10,000 | 19,706 | 10.2% | 9.3% | 20.7% | 15.5–25.3% |
| $10,000–100,000 | 4,936 | 7.7% | 6.2% | 9.0% | 8.2–9.9% |
| above $100,000 | 534 | 20.4% | 4.8% | 20.4% | 20.4–20.4% |

Gas flips many small routes and almost none of the large routes. The gross 20.4% rate above $100,000 is not evidence that large routing is worse: only 4.8% remains inside strict valuation support, and the cell contains 534 routes. It is a tail diagnostic.

## State support and venue reach

The result does not depend on one reserve-reconstruction class.

| reserve support | routes | gross direct dominance | strict-value gross dominance | median-gas all-in dominance | gas-IQR range |
|---|---:|---:|---:|---:|---:|
| adjacent, no liquidity event | 7,777 | 13.5% | 11.7% | 29.7% | 22.6–34.7% |
| bridged, no liquidity event | 4,384 | 9.7% | 7.8% | 21.1% | 14.7–28.0% |
| liquidity replayed | 33,559 | 11.6% | 10.6% | 32.8% | 26.7–37.0% |

Only 1,030 of the 5,361 gross-dominated routes, or 19.2%, use a best direct pool outside the realised route's venue set. Most detected misses are therefore within observed V2-family venue reach. This does not prove the executor knew the pool or authored the quote.

## Why this is a level bound, not a maturation trend

Comparable support is concentrated early: 16,075 routes in 2020 and 21,907 in 2021, then 3,155 in 2022, 2,028 in 2023, 1,817 in 2024, 629 in 2025, and 109 in 2026. The late observations are survivors inside a shrinking legacy-venue perimeter while routing migrates to concentrated liquidity, new venues, aggregators, and universal routers. Annual dominance rates therefore mix efficiency with endogenous support exit.

The correct market-maturation design must hold the public opportunity set, endpoint pair, size, vehicle, and observed reach fixed while expanding transaction-state coverage across venues. It should separately measure direct-path omission, same-vehicle search shortfall, best-public-path regret, route integration, and path complexity. Executor heterogeneity can be reported only after establishing that an executor identifies the quote-authoring system.

## Permitted interpretation

The admissible claim is narrow and economically useful: direct-route dominance exists on legacy V2-family support, and historically measured fixed execution costs make it substantially more common than quote-output comparisons imply. This shows that a vehicle can retain realised flow when a direct path is cheaper all-in, which opens the state required for a persistence test.

It does not yet show that a particular vehicle retains the role because of inertia, that aggregators caused convergence, or that market-wide routing became more efficient. The V2-family incidence is a lower bound with respect to omitted direct venues, but not a population estimate because support selection can work in either direction.

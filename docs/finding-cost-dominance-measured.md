# Cost-dominance windows exist, and the native vehicle is rarely in them

Supersedes the negative result in `docs/finding-cost-dominance-not-yet-established.md`, which failed because it compared realised trades across a day and intraday price movement swamped execution cost by 34 to 1. This prices both routes at identical reconstructed state, so price movement cannot enter.

Built by `scripts/build_counterfactual_dominance.py` on `src/ddvc/cpquote.py`. **103,857 intermediated two-leg routes with an available direct alternative, across 186 days sampled from 2020-05-29 to 2026-06-27.**

## The question, and the answer

The FX inertia literature's stated limit is that an incumbent's cost advantage is a consequence of its incumbency, so the data never contain the state where a currency holds the vehicle role while strictly cost-dominated. On-chain, that state is observable and common: **17.9% of intermediated routes were dominated gross of gas, 30.0% all-in.** So the windows exist.

## The result that matters, and a correction to a first reading

**First, a data filter that changes the claim.** The unfiltered panel contains mispriced tokens: 994 routes show gaps above 10,000 bps (one reaches 11.5 billion bps) and 22 report notionals above $50m, one of them $208 billion. Every top offender is an unclassified token with a null symbol, the same repricing failure that produced the wash-trade contamination elsewhere in this project. Filtering to plausible economics (absolute gap at most 10,000 bps, notional between $100 and $50m) keeps 99.0% of routes and is applied throughout below.

Dominance by intermediary type, filtered, gross of gas:

| type | routes | dominated | median gap |
|---|---|---|---|
| native | 19,339 | **13.2%** | **-2,459 bps** |
| stable | 33,037 | 16.8% | -492 bps |
| other | 48,441 | 18.7% | -171 bps |
| imported | 2,028 | 23.1% | -123 bps |

Pooled across the sample, the native asset is dominated least often, and the median native-intermediated route returns 2,459 bps more than the best available direct pool would have. That gap is an order of magnitude larger than for any other type.

**The year-by-year claim does not survive the filter, and an earlier version of this document was wrong to make it.** On the unfiltered panel native appeared to be dominated less often in all seven years. Filtered, it holds in five of seven:

| year | native | other | |
|---|---|---|---|
| 2020 | 10.7% | 22.4% | native lower |
| 2021 | 12.7% | 22.0% | native lower |
| 2022 | 14.6% | 13.8% | **reversed** |
| 2023 | 15.8% | 16.0% | native lower, within noise |
| 2024 | 13.1% | 12.2% | **reversed** |
| 2025 | 7.7% | 9.3% | native lower |
| 2026 | 16.4% | 30.0% | native lower |

So the defensible statement is the pooled one, plus the observation that the ordering is not uniform through time and reverses in two years. The junk-token contamination was inflating measured dominance among non-native intermediaries, which flattered the original claim.

**What still supports the reading against naive inertia.** An asset carried by habit should be dominated more often than alternatives, since habit keeps routing flow through it after it stops being best. Pooled, the opposite holds, and the median-gap difference is large and one-directional. What the evidence supports is incumbency operating through a state variable: the native asset's pools are deepest, so routing through it is genuinely optimal in most instances, while the reason those pools are deepest may still be historical. The two reversal years mean this is a tendency and not a law, and the paper should say so.

## Gas behaves exactly as a fixed cost should

Adding the receipt-measured gas of the extra hop (74,096 units, from median gasUsed of 154,604 for one leg against 228,701 for two) raises overall dominance from 17.9% to 30.0%, and the change concentrates where a fixed cost must bite hardest:

| trade size | n | dominated gross | dominated all-in |
|---|---|---|---|
| $100-1k | 50,283 | 17.0% | 39.1% |
| $1k-10k | 42,051 | 18.9% | 22.2% |
| $10k-100k | 10,674 | 17.0% | 17.3% |
| >$100k | 847 | 33.5% | 33.5% |

Small trades flip in large numbers; trades above $100k do not move at all, because one extra hop is 0.5 bp of a $100,000 notional and 478 bp of a $100 notional.

The >$100k row is the anomaly worth chasing: those routes have the highest gross dominance at 33.5%, meaning large trades were intermediated when a direct pool would have paid more, and gas cannot explain it away at that size. Candidate explanations to test: split routing across venues our v2-only counterfactual cannot see, MEV protection, or a genuinely suboptimal router. It is a small cell at 847 routes.

## Limits, stated

**Flat gas and ETH price.** The all-in figures use 25.8 gwei and ETH at $2,500 across the whole 2020-2026 span, which is wrong in both directions at different times: gas ran far higher in 2021 and far lower after EIP-4844, and ETH ranged from a few hundred dollars to several thousand. Per-day gas price is recoverable from receipts and per-day ETH price from the pools themselves. This is the next refinement and it will move the all-in numbers, though not the ordering across intermediary types, which is measured gross of gas too.

**v2-family venues only.** Concentrated liquidity needs the tick map. Omitting venues understates the best alternative route, so dominance incidence is a lower bound. The v2 sample also thins badly late as volume migrated to v3 and v4, which is why native n falls to 118 in 2026; the 2025 and 2026 rows should be read with that in mind rather than as a trend.

**Contaminated pool-hours excluded.** Hours failing the reserve-continuity check are dropped, roughly 3.2%, and their exclusion is not random since liquidity events concentrate in actively managed pools.

**Two legs only.** Longer routes are excluded from this panel.

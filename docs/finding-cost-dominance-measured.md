# Cost-dominance windows exist. The native vehicle's apparent advantage is composition.

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

**Temporal variation is the phenomenon, not a robustness failure.** An earlier version of this document reported the year-by-year pattern as "holds in five of seven years" and treated the two reversals as weakening the result. That was a conceptual error, flagged by Java: this paper is about how vehicle dominance is *made*, so the time dimension is the object of study. Demanding that the pattern hold uniformly across years assumes stationarity in a paper about non-stationarity, and it discards exactly the variation the paper exists to explain.

The legitimate version of the robustness question is whether the pooled result depends on any single period. It does not. Leave-one-year-out never flips the sign, with the native advantage ranging from +2.2pp (excluding 2021) to +6.3pp (excluding 2022).

What the quarterly series shows instead, in percentage points by which non-native intermediaries are dominated more often than native:

| quarter | native advantage | native share of v2 intermediation |
|---|---|---|
| 2020 Q3 | +12.3 | 17.5% |
| 2020 Q4 | +12.7 | 14.8% |
| 2021 Q1 | +14.8 | 13.9% |
| **2021 Q2** | **+20.4** | 17.4% |
| 2021 Q3 | +0.4 | 22.0% |
| 2021 Q4 | +0.3 | 25.3% |
| 2022 Q1 | +0.2 | 24.2% |
| 2022 Q3 | -2.1 | 16.8% |
| 2023 Q1 | -5.8 | 25.5% |
| 2023 Q2 | +7.1 | 30.2% |
| 2025 Q4 | +8.3 | 7.1% |
| 2026 Q2 | +23.4 | 8.9% |

**The native asset's routing advantage collapses in 2021 Q3, from +20.4pp to +0.4pp in a single quarter, and stays near zero for roughly two years.** Uniswap V3 launched in May 2021, which is 2021 Q2. An architecture change followed within a quarter by a step change in which asset it pays to route through is the paper's subject matter arriving in the data.

A composition alternative has to be ruled out before that reading is claimed. This panel is v2-only, so what is observed is the native advantage *within v2* after V3 began pulling liquidity elsewhere. If the best native-intermediated routes migrated to V3 first, the residual v2 native routes would look worse without the native asset's role having changed at all. Distinguishing the two requires extending the counterfactual to V3, which needs the tick map. Until then this is a documented association with a named confound.

**The controlled comparison overturns the descriptive result.** Java's point: subsample splits are fine as robustness, but the claim needs a controlled experiment. Run in `scripts/run_dominance_regressions.py`, and it changes the conclusion.

| specification | native coefficient | p |
|---|---|---|
| (1) pooled | -0.049 | 0.008 |
| (2) + log notional | -0.051 | 0.008 |
| (3) + year effects | -0.049 | 0.008 |
| **(4) pair-by-day fixed effects** | **+0.094** | 0.269 |
| (5) pair-by-day FE, gap in bps | +186 | 0.078 |

Specifications (1) to (3) reproduce the descriptive finding: native-intermediated routes are about 5 percentage points less likely to be dominated, on 3,654 pair clusters. Specification (4) compares routes between the same two tokens on the same day that used different intermediaries, so pair liquidity, token characteristics, that day's volatility and the gas regime are all held fixed. The coefficient flips sign and loses significance.

**The pooled comparison is confounded by composition, and specification (4) is too weak to say what remains.** The descriptive gap does not survive holding the trade fixed, so the pooled 5 percentage points cannot be read as an asset-role effect. What specification (4) itself establishes is much less than an earlier version of this document claimed by calling the result a composition effect and stopping there.

The reason is power, and it should be stated as a number rather than as a caveat. Specification (4) identifies from 703 pair-day cells out of 22,991 and 3,865 routes out of 102,845, so **96.2% of the panel contributes nothing to that coefficient**, on 158 clusters. Its standard error of 0.085 puts the minimum detectable effect near 24 percentage points at conventional power. The estimate is +0.094. So the design can neither confirm a native advantage nor exclude a substantial native *dis*advantage, and describing it as a null asserts an absence the data cannot support.

Why identification is so thin here is itself informative: within a single venue, a pair-day rarely sees both a native and a non-native intermediary actually used, so the estimator waits on a coincidence. The multi-venue route-cost panel quotes every vehicle candidate for every pair-day by construction, which removes the coincidence and is the correct place to settle this. Until that panel is read, the honest statement is that the sign is unresolved and the point estimate leans toward the native asset being the worse intermediary conditional on the trade, which would contradict the incumbency-advantage story and be the more interesting result of the two.

Two things this does not touch. It says nothing against dominance windows existing at all, which is a marginal frequency needing no controls. And it does not license the reverse claim either, for exactly the reason above.

One incidental result survives strongly in the controlled design: larger trades are markedly less likely to be dominated within a pair-day (log notional coefficient -0.042, p<0.001), consistent with the fixed-cost mechanics of gas and with larger flow attracting better routing.

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

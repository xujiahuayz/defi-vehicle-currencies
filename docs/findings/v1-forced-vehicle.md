# Uniswap V1's ETH mandate, and what happened when V2 removed it

Uniswap V1 gave every ERC20 token exactly one exchange contract holding an ETH-token pair, so a token-to-token trade had no direct pool and the protocol routed it through ETH. ETH was a *mandated* vehicle currency. Traders never chose it. Uniswap V2, live 2020-05-05, allowed arbitrary ERC20/ERC20 pools and withdrew the mandate. That is a discontinuity in this paper's dependent variable, on a date we did not choose, and this document measures it.

The verdict, stated first because it is negative in the places that matter. One large, clean, robust fact comes out of this. **The mandate was withdrawn and native-asset pairing did not retreat at all.** Six years on, 95 to 98% of single-leg Uniswap V2 trades still execute on a pool containing WETH, and the WETH share of newly created pairs *rose* from 84% in 2020 to 98% by 2023. Everything sharper remains secondary. The obvious event study on V1's own flow is absorbed by a mechanical confound. A new static registry fetch now resolves every V1 exchange in the daily panel and makes the V1-token persistence comparison possible. Its raw gap is large, but it disappears once both endpoint-token effects are absorbed, so it does not establish vehicle stickiness. Section 8 runs the token-level version of the event study that section 2's aggregate arithmetic cannot generate, and it reaches the same negative destination by a route that the thinning confound cannot touch.

Built by `scripts/fetch/fetch_v1_exchange_registry.py`, `scripts/process/build_v1_exchange_token_crosswalk.py`, `scripts/process/build_v1_forced_vehicle.py`, `scripts/process/build_v2_token_panel.py`, and `scripts/analyze/run_v1_forced_vehicle_tests.py`, plus `scripts/process/build_v1_exchange_class_panel.py` and `scripts/analyze/run_v1_forced_vehicle_token_level.py` for section 8, and `scripts/process/build_v1_route_case.py` for section 1's registered case. The main machine-readable outputs are `output/exhibits/v1_forced_vehicle_report.md`, `output/exhibits/v1_pair_persistence_regressions.jsonl`, and, for section 8, `output/exhibits/v1_forced_vehicle_token_level_report.md`.

## 1. The institutional premise, verified, and one correction to how it appears in the data

The brief for this work stated that a V1 row carrying both `ethPurchaseEvents` and `tokenPurchaseEvents` is a token-to-token trade forced through ETH. **That is wrong, and it would have missed essentially every forced route while counting a different object instead.** The V1 subgraph keys its `transaction` entity on `txhash-exchangeAddress`. A token-to-token trade calls `tokenToEthSwap` on exchange A and then `ethToTokenSwap` on exchange B, so it materialises as *two* rows sharing one transaction hash, one carrying only `ethPurchaseEvents` and one carrying only `tokenPurchaseEvents`. Rows carrying both arrays do exist, at 14,641 of 2,816,199 entity rows (0.52%), and they are a different object, namely one exchange trading in both directions inside one transaction, which is a round trip through a single pool. The correct signature recovers 217,003 forced routes where the stated one recovers none of them.

The forced route is therefore identified by pairing rows across a transaction hash, and it can be verified. If ETH physically flowed out of exchange A and into exchange B, the two legs must report the same ETH amount. Across 217,003 candidate token-to-token transactions, **87.4% report the two legs as exactly equal and 93.1% agree within 1%**, with a volume-weighted median relative gap of 3.5e-03. The residual 6.9% are transactions in which the two amounts differ materially, which is what an arbitrage bot bundling two unrelated swaps looks like. A separate strict-definition column carries them throughout, and they are never quietly folded in.

### One registered case, externally verified

`scripts/process/build_v1_route_case.py` registers a single authentic forced route as the deck's appendix A6 trace, selected under a deterministic rule so it cannot be cherry-picked: largest routed ETH among mandate-era transactions with exactly two exchange rows, one single-event leg in each direction, positive ETH legs, and relative leg gap below 1e-9. Of 1,376,633 transactions scanned across the 550 pre-launch days, 144,442 survive the two-row shape filter and 129,810 also carry exactly matching ETH legs. The winner is [`0x4dca160d…a0ca16`](https://eth.blockscout.com/tx/0x4dca160d762184835f34925a8cc556d7283a7642c88d1bef3382a73596a0ca16?tab=token_transfers), block 9,674,728, 2020-03-15 07:38:26 UTC: one row sells 250 tokens into exchange `0x2c4bd064b998838076fa341a83d007fc2fa50957` for 439.129687312060203802 ETH, and the other spends the string-identical ETH amount at exchange `0x2a1530c4c41db0b0b2bb646cb5eb1a67b7158667` for 49,892.398432534066569119 tokens. The subgraph rows identify exchange contracts only, so the token identities come from the public transfer record (blockscout token transfers, retrieved 2026-08-15): 250 MKR (`0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2`) in and 49,892.40 DAI (`0x6b175474e89094c44da98b954eedeac495271d0f`) out, submitted through a DEX.AG proxy during the March 2020 crash weekend. That is the mandate in one transaction: an MKR-to-DAI trade with no direct pool available, forced to buy and immediately resell 439 ETH. The machine-readable manifest, including the filter-stage counts and the verification fields, is `output/exhibits/v1_route_case.json`.

A second correction to the denominator. 61,033 V1 transactions (2.19%) carry neither event array and a zero fee. Inspection confirms these are liquidity provision and withdrawal, which the V1 subgraph's `transaction` entity covers alongside swaps. Leaving them in would deflate every share below, so all shares are taken over swap transactions only.

### Composition of V1 flow, whole sample

2,522,120 swap transactions across 2,798 days, 2018-11-02 to 2026-06-30. Volume is denominated in ETH throughout, because every V1 event reports `ethAmount` natively and ETH sidesteps the repriced-junk-token problem that has misled this project repeatedly.

| trade class | transactions | share | ETH volume | share |
|---|---|---|---|---|
| ETH to token | 1,203,360 | 47.71% | 3,561,614 | 43.21% |
| token to ETH | 1,075,970 | 42.66% | 3,550,092 | 43.07% |
| **token to token, forced via ETH** | **217,003** | **8.60%** | **668,171** | **8.11%** |
| round trip within one exchange | 12,051 | 0.48% | 153,088 | 1.86% |
| three or more exchanges | 13,736 | 0.54% | 309,498 | 3.75% |

The original daily pull retained `exchangeAddress` and omitted `tokenAddress`. The dedicated static fetch now retains 3,086 one-to-one exchange and token identities from the V1 subgraph. It resolves all 1,744 exchanges observed in the daily panel, including 1,629 whose exchanges traded before V2 launched. Section 4 uses that exact map.

So the headline share of V1 activity that was forced through ETH is **8.60% of swaps and 8.11% of ETH volume over the whole sample, rising to about 10% in 2019 and 2020 when V1 was actually alive**. That is the size of the mandate's bite. Roughly one V1 trade in ten was a token-to-token trade that the architecture compelled to touch ETH.

## 2. V1 after V2, and the confound that absorbs the result

V1 died after V2 launched, which is mechanical migration and not a finding. The non-mechanical quantity is whether the *forced* part of V1 flow left faster than the *ETH-paired* part. V2 replaced two hops with one for token-to-token trades and left ETH-paired trades roughly as they were, so the mandate's removal predicts exactly that divergence, and a common shock to V1 as a venue cannot produce a divergence between two flow types inside the same venue.

The divergence is there and it is large.

| window around 2020-05-05 | swap tx | ETH-paired tx | forced t2t tx | t2t share of swaps | ETH-paired vs pre | t2t vs pre | differential |
|---|---|---|---|---|---|---|---|
| -365 to -183 days | 283,590 | 254,321 | 28,298 | 9.98% | 0.31 | 0.25 | 1.24 |
| -182 to -1 days | 943,067 | 817,859 | 113,022 | 11.98% | 1.00 | 1.00 | 1.00 |
| 0 to +181 days | 653,705 | 589,523 | 60,038 | 9.18% | 0.72 | 0.53 | 1.36 |
| +182 to +364 days | 151,773 | 147,010 | 4,434 | 2.92% | 0.18 | 0.04 | **4.58** |
| +365 to +729 days | 43,956 | 42,396 | 1,431 | 3.26% | 0.05 | 0.01 | **4.09** |

The token-to-token share of V1 swaps was stable at 9 to 15% for the 26 weeks before the launch, and fell monotonically to 2.4% by December 2020. In the second half-year after launch, forced flow had contracted 4.6 times more than ETH-paired flow. ETH-paired V1 activity actually *grew* for two months after V2 went live, so this is not the venue shrinking.

**The response spreads out over months.** There is no discontinuity at the launch date. Weekly, the t2t share runs 12.6% at week -2, 10.5% at week +2, 9.5% at week +6, 6.2% at week +10, 5.2% at week +14. Whatever is happening takes about six months, consistent with V2 needing non-ETH pools to be created and funded before they were usable.

### The confound, and it is fatal to this test

A token-to-token trade needs *both* of its tokens to have a live V1 exchange. An ETH-paired trade needs one. As the V1 exchange network thinned, the set of feasible token-to-token pairs shrank roughly with the square of the number of live exchanges while feasible ETH-paired trades shrank roughly linearly, so the *ratio* of the two should fall roughly in proportion to the exchange count **even if no trader changed behaviour and no mandate had been removed**.

Benchmarking against the count of exchanges with at least ten trades in the month, indexed to 2020-05:

| month | exchanges with 10+ trades | t2t per ETH-paired | ratio vs 2020-05 | exchange count vs 2020-05 | excess over thinning |
|---|---|---|---|---|---|
| 2020-03 | 304 | 0.1451 | 1.04 | 0.97 | 1.07 |
| 2020-05 | 313 | 0.1395 | 1.00 | 1.00 | 1.00 |
| 2020-06 | 242 | 0.1074 | 0.77 | 0.77 | **1.00** |
| 2020-07 | 190 | 0.0751 | 0.54 | 0.61 | **0.89** |
| 2020-08 | 155 | 0.0575 | 0.41 | 0.50 | **0.83** |
| 2020-09 | 135 | 0.0598 | 0.43 | 0.43 | **0.99** |
| 2020-10 | 142 | 0.0605 | 0.43 | 0.45 | **0.96** |
| 2020-11 | 133 | 0.0597 | 0.43 | 0.42 | **1.01** |
| 2020-12 | 127 | 0.0244 | 0.18 | 0.41 | 0.43 |
| 2021-06 | 71 | 0.0337 | 0.24 | 0.23 | 1.06 |

Through the entire period in which the differential emerges, excess sits between 0.83 and 1.07. **Network thinning alone accounts for essentially the whole of it, leaving nothing for the removal of the mandate to explain.** Only December 2020 breaks from the benchmark, and one month on a venue by then executing 1,500 swaps a day is not a result.

Two things this does not settle. The N-squared benchmark is a crude combinatorial heuristic that assumes uniform trade propensity across pairs, whereas real V1 activity concentrated in a handful of tokens, so the benchmark could be wrong by a constant factor in either direction. And thinning is endogenous, because V2 is *why* exchanges went quiet, so thinning is partly a channel through which the mandate's removal operated, which makes it a poor rival explanation. Neither observation rescues the test, because both leave the differential unable to distinguish the mandate from the arithmetic of a shrinking network.

## 3. The plain fact that survives, which is that nobody stopped pairing against the native asset

This needs no route reconstruction and no V1 token identity. On V1, the share of trades on a pool containing ETH was 100% by construction. On V2 it was free to fall.

| year | single-leg V2 trades | share on a WETH pool, count | share on a WETH pool, value |
|---|---|---|---|
| 2020 | 14,422,786 | 95.1% | 81.2% |
| 2021 | 29,430,033 | 95.2% | 90.2% |
| 2022 | 17,001,637 | 93.4% | 85.1% |
| 2023 | 44,342,924 | 97.9% | 94.1% |
| 2024 | 48,367,432 | 97.7% | 85.2% |
| 2025 | 36,249,166 | 95.4% | 94.1% |
| 2026 | 13,862,895 | 95.5% | 84.6% |

Of 477,633 pairs that ever traded on V2, 463,548 (**97.1%**) include WETH. And the pattern strengthens rather than decays in the *supply* of new pools:

| year first traded | new pairs | share including WETH |
|---|---|---|
| 2020 | 25,400 | 84.1% |
| 2021 | 30,948 | 92.9% |
| 2022 | 66,170 | 96.5% |
| 2023 | 153,967 | 99.0% |
| 2024 | 90,679 | 98.0% |
| 2025 | 75,769 | 98.1% |
| 2026 | 34,700 | 97.9% |

This is the cleanest number in the exercise, and it is a null on the architectural hypothesis, because removing the constraint did not move the outcome the constraint had been producing. It is also the weakest kind of evidence about *why*, and it says nothing about routing. It describes which pools get created and used, and the dominant reason a new token launches against WETH may simply be that WETH is the default in every launch template and every liquidity-bootstrapping guide. That is still a thick-market externality operating through a state variable, which is where `README.md` section 4.0 already says incumbency can legitimately live, but convention and tooling would produce it just as well as optimisation, and the data cannot separate the two.

One boundary that must be stated whenever this table is used. It is **Uniswap V2 only**, and V2 became a legacy venue after V3 arrived in May 2021. The migration of stable-numeraire pairing to V3, Curve and elsewhere is exactly what `docs/findings/vehicle-transition.md` measures on the unified layer, and a V2-only WETH share cannot speak to it. It says the venue that lost the mandate never used its freedom. It does not say the native asset never lost ground anywhere.

## 4. Exact V1 identities recover the comparison, but endpoint composition absorbs it

The original daily query omitted the exchange's token address. A price-series substitute was attempted and rejected: 34.8% of real series and 32.1% of date-shifted placebo series passed the same rule, and only 4.0% of exchanges chose the same nearest token on odd and even days. Those matches remain discarded.

The direct fix is now complete. `fetch_v1_exchange_registry.py` queries the V1 `exchanges` entity for `id`, `tokenAddress`, and `tokenSymbol`. The retained registry contains 3,086 one-to-one identities and resolves all 1,744 exchange addresses in the daily panel. Of those tokens, 1,629 traded on V1 before V2 launched.

The recovered comparison contains 228 pairs whose two tokens both traded on V1 before V2 and whose direct V2 pool traded within the trailing 28 days. Their descriptive ETH-route share is high: 70.3% in weeks 13--25 after the direct pool first traded and 50.2% in weeks 26--51. The broader active-direct sample is 26.5% and 17.3% in the same windows.

That difference is composition, not a new stickiness result. In pair-week regressions with calendar-week and direct-pool-cohort effects, the V1-pair difference is +14.88 pp (SE 3.98) when pair-weeks receive equal weight and +12.27 pp (SE 4.26) when weighted by route count. After absorbing fixed effects for both endpoint tokens, the estimates become -2.09 pp (SE 6.05) and -14.52 pp (SE 7.15). Endpoint composition therefore explains the positive comparison and even reverses the route-weighted estimate. The exact re-fetch closes the missing-data problem; it does not supply an identification result.

## 5. Voluntary vehicle persistence on all V2 pairs, which is real, large, and not identified

The unrestricted version does run. For each unordered token pair, take the first day it traded through a direct pool; ETH routing before that is mandatory and measures nothing, ETH routing after it is a choice. ETH-routed trade is a two-leg component A to WETH to B inside one transaction, read from `data/unified/` where routes are already reconstructed, restricted to `uniswap_v2`.

Sample construction, every filter reported:

| filter | pair-days | share kept |
|---|---|---|
| pair-days with any V2 trade | 12,713,685 | 1.000 |
| both tokens present in the V2 decimals map | 11,511,497 | 0.905 |
| median trade notional between $100 and $50m | 8,018,149 | 0.631 |
| pairs with a direct pool, 20+ trades, and any ETH-routed trade | **2,265 pairs** | |

The window logic checks out. Before their direct pool existed these pairs traded 444,651 times through ETH and **0** times directly, which is what construction requires.

**A filter that changes the answer completely.** Dating availability at the direct pool's first trade is not enough. A pool that traded once and went dormant is not a usable alternative, and a pair whose direct pool died shows a near-100% ETH-routed share that reflects nothing about choosing the vehicle. Requiring a direct trade inside the trailing 28 days keeps 70.2% of post-availability pair-days, and per pair the median share of days with a live direct pool is 0.88.

Median per-pair ETH-routed share of trade count, weeks since the direct pool first traded:

| weeks since availability | no liveness condition | direct pool live in trailing 28 days |
|---|---|---|
| week 0 | 0.456 | 0.456 |
| week 1 | 0.638 | 0.638 |
| weeks 2-3 | 0.746 | 0.746 |
| weeks 4-7 | 0.800 | **0.600** |
| weeks 8-12 | 0.909 | **0.333** |
| weeks 13-25 | 0.933 | **0.321** |
| weeks 26-51 | 0.978 | **0.200** |
| week 52+ | 0.992 | **0.078** |

Without the liveness condition the median pair looks like it routes 99% through ETH a year after its direct pool arrived, which is an artefact of dead pools and would have been a spectacular false positive. With it, ETH routing decays but stays substantial. **The median pair still sends 32% of its trades through ETH three to six months after a live direct pool exists, and 20% at six to twelve months.** Pooled across trades the same series runs 33% at week 0, 29% at weeks 8-12, 17% at weeks 26-51 and 5.6% beyond a year; pooled figures are dominated by a few very large pairs and the two weightings disagree, so both are reported.

### Why this is not identified, in two steps

**Calendar time does most of the work, and horizon little of it.** Splitting by the year a pair's direct pool arrived, and separately by the calendar year of observation, median per-pair ETH-routed share:

| direct pool arrived | week 0 | weeks 1-3 | weeks 4-12 | weeks 13-25 | weeks 26-51 | week 52+ |
|---|---|---|---|---|---|---|
| 2020 | 0.506 | 0.793 | 0.801 | 0.631 | 0.500 | 0.189 |
| 2021 | 0.476 | 0.643 | 0.520 | 0.226 | 0.092 | 0.056 |
| 2022 | 0.076 | 0.111 | 0.058 | 0.022 | 0.019 | 0.010 |
| 2023 | 0.083 | 0.125 | 0.138 | 0.000 | 0.000 | 0.028 |
| 2024 | 0.167 | 0.454 | 0.296 | 0.049 | 0.013 | 0.008 |
| 2025 | 0.067 | 0.204 | 0.170 | 0.004 | 0.066 | 0.000 |

| observed in calendar | week 0 | weeks 1-3 | weeks 4-12 | weeks 13-25 | weeks 26-51 | week 52+ |
|---|---|---|---|---|---|---|
| 2020 | 0.500 | 0.773 | 0.833 | 0.830 | 0.907 | |
| 2021 | 0.491 | 0.667 | 0.533 | 0.403 | 0.362 | 0.303 |
| 2022 | 0.071 | 0.090 | 0.028 | 0.005 | 0.029 | 0.073 |
| 2023 | 0.083 | 0.100 | 0.129 | 0.019 | 0.010 | 0.029 |
| 2024 | 0.183 | 0.404 | 0.167 | 0.016 | 0.000 | 0.025 |
| 2025 | 0.114 | 0.240 | 0.128 | 0.023 | 0.009 | 0.084 |

Within a cohort there is genuine decay in horizon, clearest for 2021 (0.48 down to 0.06). But the level difference across cohorts and calendar years dwarfs it, since pairs whose direct pool arrived in 2020 kept routing 50 to 80% through ETH for six to twelve months, while 2022-onward pairs sit at 2 to 17% within weeks. In calendar 2020 there is **no decay in horizon at all** (0.50, 0.77, 0.83, 0.83, 0.91) — having a live direct pool available for a year did not reduce ETH routing in the year the mandate was withdrawn. Because most pairs acquired direct pools in 2020 and 2021, cohort and calendar are close to collinear and the pooled horizon profile cannot be cleanly attributed to time-since-availability. The 2026 row of both tables inverts the pattern on a handful of pairs and should be read as noise on a venue that is now nearly abandoned.

**Even a clean horizon profile would not measure inertia.** Routing is executed by graph optimisers, so preferring ETH when a direct pool exists is not evidence of habit. A newly created direct pool can be thin, and routing through the deepest network path can remain cost-optimal. An inertia claim would require a separately registered transaction-state counterfactual showing that a cheaper feasible route was declined. That analysis is outside the current paper and live workflow; Section 5 therefore describes routing behaviour and identifies no inertia effect.

## 6. Confounds, in the order they would sink the paper

**Fatal to the V1 event study (section 2).** Network thinning reproduces the entire differential, with excess over the benchmark between 0.83 and 1.07 across the whole response period. There is no version of the V1-side event study that survives this, because the treatment (V2 exists) and the confound (V1 exchanges go quiet) are the same event.

**Fatal to a V1-restricted persistence interpretation (section 4).** Exact token identity is now available, but the positive descriptive gap disappears after endpoint-token effects are absorbed. The comparison says which old tokens compose the V1 sample, not that prior architectural exposure causes later ETH routing.

**Fatal to any causal reading of section 5.** Router choice is a cost optimisation, so ETH routing over a live direct pool is the correct action whenever the direct pool is thinner net of gas. This is not a nuisance to control for, it is a rival explanation that is a priori more likely than incumbency and is untested here.

**Major, and specific to what was measured.**

*V2's router defaulted to WETH paths.* Both section 3's pairing shares and section 5's routing shares are partly a statement about one team's routing software and pool-creation defaults rather than about traders. A single implementation choice inside the Uniswap frontend can produce both patterns with no economics at all.

*Gas sits on the causal path, so controlling for it is wrong.* The former pooled extra-hop calibration cannot measure this channel. Route comparisons require candidate-specific units and the realised transaction's exact receipt price; until that join passes, gas remains an unmeasured part of the outcome and cannot be netted out by including a daily proxy as a regressor.

*V1 survivor bias.* By late 2020 V1 was executing under 1,500 swaps a day across roughly 130 exchanges. The tokens still trading there were selected on not having migrated, which selects on the outcome. All of section 2's post-launch windows live inside this.

*V1 was small and illiquid throughout.* Even at its 2020 peak, V1's whole forced-routing channel is 217,003 transactions over eight years. Section 3's V2 table alone covers 203 million single-leg trades. Any inference resting on the V1 side rests on a thin, dying venue.

*Bot composition.* V1 token-to-token flow includes atomic arbitrage; 6.9% of candidate routes have mismatched legs and are bundled unrelated swaps. Sophisticated flow migrates first for reasons unrelated to the mandate, and the strict-definition columns bound but do not remove this.

*Availability is dated late.* Section 5 dates a direct pool's availability at its first trade instead of its creation, because using `hourly_reserves` for pool existence means reading 2.4 GB against 329 MB for swaps. First trade is weakly later than creation, which *shortens* measured persistence, so the bias runs against the persistence finding. It also means "available" never distinguishes a $500 pool from a $5m one, which is the more serious version of the same gap.

*Composition of the pair panel.* The 2,222 pairs are 1,308 other-plus-stable and 807 other-plus-other by endpoint asset type, so the panel is a long-tail-token panel and its results should not be read as being about major pairs.

*Single venue.* Section 5 counts only `uniswap_v2` legs, so a trade routed A to WETH on V2 and WETH to B on V3 is invisible. On the full clean-route series with canonical endpoint identity, cross-venue routing rises from 1.4% of economic multi-leg routes in 2020 to 58.7% in 2026 by count. Omitting other venues understates the availability of alternatives, which inflates measured ETH routing.

*Filters that are not random.* The notional band removes 36.9% of pair-days, and small trades are exactly where gas makes the vehicle route uneconomic, so the band is correlated with the outcome.

**What the data cannot identify, stated plainly.** Whether ETH held the vehicle role on V2 because traders and liquidity providers were slow to leave an incumbent, or because ETH pools were genuinely deepest at every instant, is not answerable from anything in this document. The V1-to-V2 discontinuity does not help, because the mandate's removal changed the feasible set and the cost surface at the same moment and on the same date for every token. The one thing that is established without a counterfactual is the null in section 3: the constraint was withdrawn and the behaviour it had been enforcing did not change.

## 7. Is this natural experiment usable

Not as an identification spine. As a motivating fact, section 3 is strong. A hard architectural constraint was removed, and six years later 97% of pools on that venue still hold the asset the constraint had mandated, with new-pool creation converging *toward* it. That is a good opening fact for a paper about how dominance is made, and it is cheap to defend.

The first missing input is now complete: the V1 exchange registry supplies exact token identities. Two larger extensions remain. Point the transaction-time quoter at the pair-availability panel from section 5, which converts a description of routing into a test of whether the cheaper route was declined. Extend section 5 beyond `uniswap_v2` on the unified layer, which removes the single-venue bias that currently inflates every measured ETH share. The first would address the economic alternative; the second would address venue coverage.

## 8. The token-level test, which the aggregate arithmetic cannot generate

Section 2's verdict stands as a statement about aggregates and nothing here supersedes it. What follows is a different test on the same event, and the reason to run it is that section 2's own two concessions leave the N-squared benchmark unable to speak to it. The benchmark is a claim about the COMPOSITION of aggregate flow as the live-exchange count falls, it assumes uniform trade propensity across pairs, and thinning is endogenous to the treatment. None of that has cross-sectional content. It does not say that a V1 exchange with a high forced-routing share loses its own ETH-paired flow faster than an exchange of the same size with a low one. So the question this section asks is the token-level one: conditional on a V1 exchange's OWN pre-V2 activity, does how heavily it was used as a forced-routing endpoint predict how fast it left V1? Once own pre-V2 size is held fixed the combinatorial argument cannot generate that coefficient in either direction, and thinning stops mattering as a rival explanation because thinning is not being used as a control. Built by `scripts/process/build_v1_exchange_class_panel.py` and `scripts/analyze/run_v1_forced_vehicle_token_level.py`; the machine-readable output is `output/exhibits/v1_forced_vehicle_token_level_report.md` and the ten `output/exhibits/v1_token_level_*.jsonl` exhibits.

Two design choices matter more than anything else in the section and both are departures from the obvious version of the test. First, the outcome is dated on the exchange's own ETH-PAIRED flow, not on its total flow. Date exit on total trade count and an exchange whose flow was 40% forced routing loses 40% of its count the instant forced routing disappears, so the treatment mechanically produces the outcome; the treatment here is what share of an exchange's flow was forced routing and the outcome is how fast the REST of its flow died. Second, exit is dated against an ABSOLUTE floor of three ETH-paired legs in a thirty-day month as well as against 10% of the exchange's own pre-V2 baseline, because a threshold proportional to the ETH-paired baseline is itself lower for high-forced-share exchanges at any given total activity, which lengthens their measured survival for arithmetic rather than economic reasons. The absolute-floor version has no arithmetic connection to the treatment at all and is the primary specification. The total-count version is reported anyway, labelled as mechanically contaminated, because it is the design a reader would otherwise ask for.

The unit is a V1 exchange, identified by `exchangeAddress`; the exact registry now also supplies its token identity. The token-level exit test itself needs only the stable exchange identifier because every variable is constructed from that exchange's own transaction flow. The treatment is measured over the 182 days before 2020-05-05, the same pre-window section 2 uses. Forced-route legs are identified by the corrected signature from section 1, two rows sharing one transaction hash with one carrying only `ethPurchaseEvents` and the other only `tokenPurchaseEvents`; rows carrying both arrays are single-pool round trips and are excluded. A new panel was built for this because `data/processed/v1_exchange_day.parquet` folds liquidity provision, single-pool round trips and three-or-more-exchange transactions into its ETH-paired bucket, which is harmless for section 2's shares and not harmless for a dependent variable that is supposed to be an ETH-paired swap count.

### Sample, and what was filtered

| filter | exchanges | share kept |
|---|---|---|
| V1 exchanges with any activity in the 182 days before launch | 1,496 | 1.000 |
| pre-window ETH-paired legs at least 50 | 261 | 0.174 |
| traded ETH-paired within 30 days of the launch | 247 | 0.165 |
| nonzero pre-window ETH-paired volume, i.e. not dust-only | 247 | 0.165 |
| pool size resolved and positive at the launch date | 247 | 0.165 |

**247 exchanges** is the identifying sample and it is the number to hold onto. The 50-leg minimum removes 83% of exchanges that touched V1 in that window and is the binding filter; it is there because a forced-route share computed on a handful of legs is mostly measurement error. Pool-size resolution at the launch date is 100% of the exchanges that reach that step, so nothing was imputed and nothing was silently dropped. Forced-route intensity has mean 0.189, median 0.142, standard deviation 0.167, interquartile range 0.074 to 0.258 and maximum 0.924, and 98.0% of these exchanges carry at least one forced-route leg, so there is real cross-sectional spread in the treatment rather than a rare-event indicator. On the primary outcome 216 of 247 exchanges exit inside 24 thirty-day months, with a median of 4 months, so censoring is 31 units and the duration is well measured.

### Covariate balance, and the threat that intensity just labels peripheral tokens

| covariate | high-intensity median | low-intensity median | normalised difference |
|---|---|---|---|
| pre-V2 ETH-paired legs | 267 | 323 | 0.138 |
| pre-V2 ETH-paired volume, ETH | 77.4 | 95.5 | 0.218 |
| pool size at launch, ETH | 35.2 | 14.3 | 0.153 |
| age in days at launch | 230 | 178 | 0.141 |
| active days in the pre-window | 104 | 68 | 0.369 |
| distinct forced-route counterparties | 25 | 7 | 0.555 |
| log pre-window activity trend | -0.254 | -0.268 | 0.003 |

The specific threat named in advance, that forced-route intensity is a proxy for being a small peripheral token, is not what the data show. Intensity correlates **-0.012** with log pre-V2 ETH-paired legs and **+0.161** with log pool size, so on size the two groups are close to balanced and on depth the imbalance runs the wrong way for that threat: heavily routed exchanges are slightly DEEPER, not thinner. The imbalances that are real are activity breadth, 104 against 68 active days, and forced-route counterparty count, a median of 25 against 7. Those say the heavily routed exchanges were more central, not more peripheral, and that turns out to be the whole story of the sign.

### The estimate

| outcome | controls | n | forced-route intensity | robust se | t | R-squared |
|---|---|---|---|---|---|---|
| ETH-paired, absolute floor | none | 247 | +1.034 | 0.325 | +3.19 | 0.028 |
| ETH-paired, absolute floor | size only | 247 | +0.827 | 0.280 | +2.95 | 0.351 |
| **ETH-paired, absolute floor** | **full** | **247** | **+0.276** | **0.307** | **+0.90** | **0.471** |
| ETH-paired, 10% of own baseline | full | 247 | +0.260 | 0.323 | +0.81 | 0.287 |
| all legs, 10% of own baseline (contaminated) | full | 247 | -0.305 | 0.339 | -0.90 | 0.245 |

A negative coefficient is the mandate hypothesis: more forced-route intensity, faster exit. Standard errors are heteroskedasticity-robust, which is exactly what a variance clustered on the exchange collapses to when each exchange contributes one spell, and it is labelled that way rather than dressed up as clustering. The primary estimate is **+0.276 log-months per unit of forced-route intensity with a robust standard error of 0.307, t = +0.90, on 247 exchanges**. That is the WRONG SIGN for the hypothesis and it is not significant. Scaled to one standard deviation of intensity the point estimate is +0.046 log-months with a 95% interval of [-0.055, +0.147], a survival-time ratio between 0.95 and 1.16; across the 0.52 spread from the 5th to the 95th percentile of intensity the interval on the survival-time ratio is [0.84, 1.59]. Randomisation inference agrees with the asymptotics and is the inference to prefer at this sample size: reshuffling intensity across exchanges gives a two-sided p of **0.355** over 5,000 draws, and reshuffling only within size quintiles gives 0.359.

The grouped-time proportional hazard on the exchange-month panel is the one specification where clustering has content, and it is where the standard errors are clustered on the exchange. On the primary outcome, 2,457 exchange-months in 247 clusters with 216 failures, forced-route intensity enters the complementary-log-log hazard at **+0.026 with a cluster-robust standard error of 0.431**, a hazard ratio of 1.004 per standard deviation of intensity. That is as close to a literal zero as this exercise produces. The contaminated total-legs outcome gives +0.739 (se 0.477), in the hypothesised direction and still insignificant, which is what one expects from the outcome in which the treatment removes part of the dependent variable by construction.

### One wrong-signed significant result, and what it actually is

Dichotomising intensity at its median produces a coefficient that clears significance with the wrong sign, **+0.222 log-months, robust standard error 0.103, t = +2.15** with the full controls, and it survives matching: within size-quintile by depth-tercile strata the stratum-fixed-effects estimate is +0.297 (se 0.116, t = +2.56) on the **235 of 247 exchanges** that sit in a stratum containing both a high- and a low-intensity exchange, and +0.268 (t = +2.54) with the continuous controls added on top of the strata. It has to be reported as a real wrong-signed result, and then read against two things that dissolve it as a dose-response.

| intensity quintile | exchanges | mean forced share | log survival vs quintile 1 | robust se |
|---|---|---|---|---|
| 1 | 50 | 0.029 | 0 | |
| 2 | 49 | 0.087 | +0.009 | 0.165 |
| 3 | 49 | 0.143 | +0.445 | 0.165 |
| 4 | 49 | 0.226 | +0.288 | 0.165 |
| 5 | 50 | 0.457 | +0.137 | 0.168 |

First, the profile is hump-shaped rather than monotone. The most heavily routed quintile sits closer to the reference than quintiles 3 and 4 do, the four dummies are jointly significant at a Wald statistic of 11.22 on 4 degrees of freedom (p = 0.024), and the continuous version of the same stratified comparison is +0.328 with a standard error of 0.315 (t = +1.04). A monotone effect of intensity cannot produce that pattern; the median dichotomy is significant because of where it happens to cut, not because survival rises with intensity.

Second, the sign belongs to routing BREADTH rather than routing intensity. Breadth is the number of distinct counterparty exchanges an exchange was routed to or from in the pre-window; it correlates +0.362 with intensity and is the most imbalanced covariate in the sample.

| specification | treatment | robust se | t | breadth coefficient | t on breadth |
|---|---|---|---|---|---|
| continuous intensity, pre-specified controls | +0.276 | 0.307 | +0.90 | | |
| continuous intensity, plus routing breadth | -0.531 | 0.328 | -1.62 | +0.357 | +3.50 |
| above-median intensity, pre-specified controls | +0.222 | 0.103 | +2.15 | | |
| above-median intensity, plus routing breadth | -0.000 | 0.121 | -0.00 | +0.289 | +2.67 |

Holding breadth fixed, intensity turns negative, which is the direction the mandate hypothesis predicts, and the significant dichotomy collapses to zero. Every quintile dummy turns negative as well (joint Wald 10.68 on 4 degrees of freedom, p = 0.030). This specification is not promoted to primary, for a reason that must be stated rather than glossed: breadth is itself a function of the treatment, since an exchange with no forced routes has no counterparties, so conditioning on it partials out part of the object being measured. It is a decomposition of forced routing into intensity and reach, not a cleaner identification of intensity. What it establishes is that the **sign of the token-level estimate is not identified** — positive under the pre-specified controls, negative under a defensible addition to them, significant under neither — while the magnitude stays small in both.

### Robustness, reported including the parts that move

| variant | n | exits | forced-route intensity | robust se | t |
|---|---|---|---|---|---|
| baseline | 247 | 216 | +0.276 | 0.307 | +0.90 |
| minimum pre-V2 legs 20 | 351 | 318 | -0.009 | 0.268 | -0.03 |
| minimum pre-V2 legs 200 | 141 | 113 | +0.875 | 0.468 | +1.87 |
| horizon 12 months | 247 | 181 | +0.214 | 0.277 | +0.77 |
| horizon 36 months | 247 | 224 | +0.259 | 0.319 | +0.81 |
| treatment: strict-leg forced share | 247 | 216 | +0.390 | 0.297 | +1.31 |
| treatment: ETH-volume forced share | 247 | 216 | +0.199 | 0.338 | +0.59 |
| treatment: forced-route SOURCE legs only | 247 | 216 | +0.369 | 0.551 | +0.67 |
| treatment: forced-route DESTINATION legs only | 247 | 216 | +0.500 | 0.535 | +0.93 |
| drop the bottom decile of pool size | 222 | 191 | +0.558 | 0.326 | +1.71 |
| drop the five largest exchanges by legs | 242 | 215 | +0.280 | 0.312 | +0.90 |

Nothing here reaches significance and the point estimate moves across the sample cut, from -0.009 at a 20-leg minimum to +0.875 at a 200-leg minimum. That instability is itself evidence against a real dose-response rather than around it: an effect of the size the hypothesis needs would not flip sign when the sample doubles. The two directional treatments, forced-route source legs and destination legs taken separately, are individually uninformative because splitting an already-noisy treatment roughly doubles its standard error.

### Falsification, both checks, pass and fail

**Falsification 1 FAILED on its pre-stated rule.** The rule, fixed before the placebo ran: shift the event to 2019-11-05, six months before V2, truncate follow-up at six months so the whole outcome window closes on 2020-05-04 and cannot be contaminated by the event being falsified, re-estimate the real event on the same six-month horizon, and PASS only if the placebo coefficient is insignificant at 5% AND smaller in absolute value than the real one. The placebo gives +0.0333 (t = +0.12) on 99 exchanges with 17 exits; the real six-month estimate gives +0.0311 (t = +0.15) on 247 exchanges with 124 exits. The placebo is insignificant but it is larger in absolute value, by 0.0021 log-months, so the rule fails. The failure is uninformative rather than damning and the reason is stated rather than used to rewrite the rule: V1 in late 2019 was less than half the venue it was in May 2020, so the placebo carries a seventh of the exits and a larger standard error, and both coefficients are within a quarter of a standard error of zero, which makes the ordering condition a coin flip. A rule that compares magnitudes cannot discriminate when both magnitudes are noise. It is reported as FAIL.

**Falsification 2 PASSED, and it is the one that makes the null mean something.** A placebo date answers whether the design finds an effect that is not there. It does not answer the question that matters when the estimate is zero, which is whether the design would have found an effect that was. So: fit the primary specification with the treatment excluded, rebuild the outcome as that fit plus a KNOWN coefficient on intensity plus residuals resampled with replacement, and count how often the design recovers it at 5% with the right sign. The pre-stated criterion, fixed before the simulation ran, was at least 80% power against a halving of survival time between the 5th and 95th percentile of intensity.

| true survival ratio, 95th against 5th percentile of intensity | implied coefficient | power at 5%, correct sign |
|---|---|---|
| 0.90 | -0.201 | 9.2% |
| 0.75 | -0.549 | 42.2% |
| **0.50** | **-1.322** | **98.4%** |
| 0.25 | -2.643 | 100.0% |

Power against a halving is **98.4%** against a threshold of 80%, so this is a PASS, and the consequence is that the estimate above is not small merely because 247 units cannot see anything. An effect that halved the lifetime of the most heavily routed exchanges would have been detected in 98 of 100 samples like this one and it was not detected. The honest boundary is also in the table: power against a 25% shortening is 42%, so effects in that range are out of reach and are not being claimed against, and the breadth-conditioned specification has a wider interval whose lower end reaches a survival ratio of about 0.54 across the same spread. This is a bound that excludes large token-level effects, not a knife-edge zero.

### Does this change the verdict on the V1 natural experiment

**No, and it changes what the negative verdict rests on.** Section 2 said the aggregate differential is fully accounted for by network thinning and therefore uninformative. The token-level test is not vulnerable to that argument and reaches the same destination by a different route: conditional on an exchange's own pre-V2 size, depth, age and activity pattern, how heavily it was used as a forced-routing endpoint carries no information about how fast its own ETH-paired flow died. The point estimate is of the wrong sign, insignificant on both asymptotic and randomisation inference, literally zero in the hazard formulation, and unstable in sign across a defensible control and across the sample cut. The one significant result in the section is a median dichotomy which is non-monotone in intensity and vanishes once routing breadth is held fixed, and what breadth is measuring is that heavily routed exchanges were popular exchanges, which is the reverse of the peripherality story the design was built to guard against.

That is a stronger negative than section 2's, because it does not depend on a combinatorial benchmark that section 2 itself conceded might be off by a constant factor. It is also a bounded negative rather than an unbounded one, since falsification 2 establishes that an effect of the magnitude the hypothesis needs would have been visible. What it is NOT is a precise zero: 247 units cannot resolve a 25% difference in exchange lifetime, and the breadth-conditioned specification leaves room for something around a 0.54 survival ratio at the bottom of its interval. So the position to hold is that the V1 mandate's removal has no detectable token-level footprint in exit speed at a resolution of roughly a 30% change in lifetime, that the aggregate differential in section 2 has no cross-sectional counterpart, and that section 7's verdict is unchanged: the V1-to-V2 discontinuity is a motivating fact and not an identification spine.

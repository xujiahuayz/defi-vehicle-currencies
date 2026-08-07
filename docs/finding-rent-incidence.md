# Rent incidence, with gas netted

Built 2026-08-07 by `scripts/build_rent_incidence_panel.py` and `scripts/run_rent_incidence.py`. Uniswap v2 covers 2,235 days from 2020-05-05 to 2026-06-30, with 3,358,539 screened pool-days across 113,895 pools. Uniswap v3 covers 1,884 days from 2021-05-04 to 2026-06-30, with 366,876 screened pool-days across the 392 pools that survive screening from the 400 most traded. Asset roles come from `src/ddvc/asset_types.py`. Gas prices come from `data/processed/daily_gas_price_graph.parquet`, and centrality comes from `data/processed/vehicle_centrality_dense.parquet` (94 sampled days, rebuilt at stride 24 for this node). Artefacts live in `output/empirical/rent_incidence/`.

This asks workflow item 4.1.3. Does intermediating pay, once the loss to arbitrageurs and the gas bill are both charged against fee revenue, and does the answer depend on the role the pool's assets play.

## What is measured

Fee revenue is the fee rate times USD volume, 30 basis points on v2 and the exact tier on v3, recovered from the CREATE2 pool address by `ddvc.pricing.v3pools` because the raw layer carries no pool statics. Loss-versus-rebalancing is the constant-product closed form of Milionis, Moallemi, Roughgarden and Zhang, realised variance over eight times pool value, with realised variance taken from the pool's own hourly marginal price. Gas is the observed count of mints and burns times a per-operation gas figure times the day's median gas price times the ETH price, charged at pool level against pool-level fee revenue, which is the right incidence because the pool's providers as a group paid it. Net is fee revenue less LVR less gas.

Active liquidity on v3 is reconstructed by replaying every mint and burn in the sample into a per-pool binary indexed tree over initialised ticks, so active liquidity at a tick is the running sum of net deltas at or below it. That part is exact. The return accounting on top of it is an approximation and is labelled as one throughout: an in-range position is treated as a constant-product pool with the same local liquidity, which holds while the price stays inside the range and fails at the moment it leaves, and the day's tick is one volume-weighted summary of a path. The reconstruction validates against pools whose depth is independently known, giving virtual reserves of 1.24 billion USDC against 664,500 WETH for the USDC-WETH 5 basis point pool on 2023-06-01, two sides agreeing on value to three figures and a concentration factor near ten, and 583 billion on each side of the USDC-USDT 1 basis point pool, a concentration factor near ten thousand, which is what a pool whose liquidity sits inside one or two ticks looks like.

Because v3 capital is measured as CPMM-equivalent virtual reserves, v3 yield magnitudes are not comparable to v2. What survives that is the sign and the ratios, since fee revenue, LVR and gas are all dollars and the concentration factor divides out of every comparison among them, so a v3 net yield of a given sign on virtual capital has the same sign on deposited capital and a larger magnitude.

## Screening, and what it removed

| screen | v2 pool-days | v2 pools | v3 pool-days | v3 pools |
|---|---|---|---|---|
| raw | 7,667,786 | 495,396 | 420,019 | 400 |
| both legs carry a symbol | 7,667,133 | 495,244 | 420,019 | 400 |
| at least one intraday return | 4,549,129 | 317,699 | 400,930 | 400 |
| at least one externally anchored leg | 4,321,736 | 312,578 | 396,089 | 394 |
| no hour moving the pool price by more than 100x | 4,227,098 | 237,570 | 395,677 | 392 |
| the anchored leg's price passes the sanity test | 4,222,818 | 237,526 | 395,056 | 392 |
| venue-specific state checks | 4,222,810 | 237,526 | 394,400 | 392 |
| capital base at least $10,000 | 3,358,539 | 113,895 | 366,876 | 392 |

Two of these are load-bearing and were added after an earlier cut of the same table inverted. Pools are valued off an anchored leg, meaning a native, staked-native, stable or imported asset, at twice that leg's value, using the constant-product identity that both legs hold equal value. The repository's token price panel is itself derived from pool prices, so a token whose only market is one thin pool inherits whatever that pool implies, and multiplying it by the same pool's reserves manufactures capital from nothing. The first cut of this table put 145 trillion dollars of capital-days and a net return of minus 30,000 percent into the unclassified-pair bucket, and a single wstETH price of 346 million dollars against a median of 1,891 put 959 billion into the staked-native bucket. A price is now accepted when it sits within a factor of four of the token's own centred 91-day rolling median, and a US-dollar stablecoin additionally has to price between fifty cents and two dollars.

The hourly-move screen removes pool-days in which the pool price moved by more than a hundredfold inside one hour, which is a rug or a decimals artefact. It removes 2.2% of pool-days and 24% of the v2 pool cross-section, and its direction matters: these are the largest LVR observations in the sample, so screening them out works against the unprofitability result below and not for it.

## Does intermediating pay, by asset role

Uniswap v2, annualised, equal-weighted across pool-days except where the column says otherwise.

| pool role | pools | pool-days | capital-days ($bn) | fee yield | LVR rate | gas rate (mean) | net yield | share paying | capital-weighted net |
|---|---|---|---|---|---|---|---|---|---|
| native / other | 111,154 | 2,978,376 | 2,382.4 | 0.90% | 11.85% | 3.80% | -6.87% | 21.2% | -89.23% |
| native / stable | 12 | 17,614 | 619.1 | 5.23% | 4.38% | 0.42% | +0.57% | 59.7% | +11.20% |
| other / stable | 2,538 | 322,543 | 348.8 | 1.91% | 8.75% | 1.81% | -4.82% | 21.0% | -34.82% |
| imported / native | 4 | 4,801 | 179.2 | 2.83% | 1.81% | 0.23% | +0.50% | 72.4% | +3.10% |
| stable / stable | 24 | 10,981 | 140.1 | 0.84% | 0.15% | 0.28% | +0.32% | 87.8% | +2.59% |
| imported / other | 135 | 15,663 | 17.4 | 0.63% | 3.00% | 2.20% | -1.75% | 24.3% | -24.39% |
| native / staked native | 3 | 2,113 | 7.2 | 4.78% | 0.40% | 0.44% | +3.40% | 86.5% | +6.41% |
| imported / stable | 11 | 5,476 | 7.0 | 1.83% | 1.84% | 0.99% | +0.04% | 51.8% | +3.22% |

Fee yield, LVR rate and net yield are pool-day medians; the gas rate is a mean because its median is zero, since only 13.1% of native-other pool-days carry any liquidity event at all. In v2 the pool is the pair, so the pools column is also the count of distinct token pairs identifying each row, and the profitable rows rest on very few of them.

The pattern is a partition and not a gradient. Where both legs are major assets the intermediation business usually pays: stable against stable pays on 87.8% of pool-days, native against staked native on 86.5%, imported against native on 72.4%, and native against stable on 59.7%. Where the native asset is paired with the long tail it does not: 21.2% of pool-days pay, fee revenue is 17.0% of LVR in aggregate dollars, and the bucket loses 5.82 billion dollars over the sample. That bucket contains 111,154 of the 113,895 screened pools and 88.7% of the pool-days.

Role differences are tested, with no difference read off the table. At the pool-month level, 98,966 observations over 14,307 pools with month fixed effects and standard errors clustered by pool, the hypothesis that every role effect on the risk-adjusted net return is zero is rejected at chi2(6) = 113.65 (0.000), and on the probability that a pool-month pays at chi2(6) = 463.33 (0.000). Other-stable is 2.1 percentage points below the native-other base in the paying-probability regression (0.020), while every major-to-major role is economically higher. Long-tail pools do not become privately profitable merely because the quote asset is stable.

Uniswap v3 gives the same ordering on scale-free objects. The median pool-day earns more in fees than it loses to LVR in every major role, with a median pool-day ratio of 10.92 for stable-stable, 4.93 for native-staked-native, 2.30 for imported-imported, 1.36 for native-other, 1.24 for native-stable and 1.02 for other-stable, and between 49.4% and 81.8% of pool-days pay. The zero-role-effect hypothesis is again rejected, chi2(7) = 17.50 (0.014) on the probability a pool-month pays over 12,160 pool-months and 380 pools, with other-stable at -0.135 (0.007) and stable-stable at +0.238 (0.008) against a native-other base. The aggregate dollar ratio for v3 is not the headline, because it is dominated by a small number of large-move pool-days and those are exactly where the in-range approximation overstates LVR worst. The two venues disagree on the native-other bucket, which pays on 60.9% of v3 pool-days against 21.6% on v2, and the disagreement is a sample-selection artefact and not a venue effect: the v3 universe is the 400 most traded pools, so its native-other row is the head of the distribution while v2's is the whole of it, including the hundred thousand pools in the tail. Any comparison of the two venues' levels has to carry that, and the role ORDERING is what survives it.

## The gas threshold

Gas is a fixed cost per operation, so its incidence falls with the size of the capital base it is spread over. Across v2 capital deciles the median gas rate on the pool-days that carry a liquidity event falls from 19.22% annualised in the smallest decile, median capital 13,126 dollars, to 0.47% in the largest, median capital 2.67 million dollars, a factor of 41. Cartea, Drissi and Monga's point that net profitability has a size threshold therefore reproduces here across a hundred thousand pools instead of one.

Gas is not what makes intermediation unprofitable. Quadrupling the per-operation gas assumption moves the median v2 net yield from -6.20% to -7.00% annualised and the paying share from 21.8% to 21.2%; halving it moves them to -5.94% and 22.1%. LVR is what dominates, and the size gradient in net yield runs through the fee-to-LVR ratio, not through gas.

## The centrality curse does not hold, and the arithmetic says it cannot

The prediction was that the most central asset's pools earn the worst risk-adjusted net return, because LVR scales with return variance times marginal depth and is largest where depth is largest, with Yuan (2005) supplying the informational version in which a benchmark asset attracts informed traders. The prediction fails on both venues, and the first half of it fails before the data arrive.

In the constant-product closed form, LVR as a share of capital is exactly realised variance over eight and carries no depth term at all. Depth enters LVR in dollars and cancels in the rate, so "largest where depth is largest" is a statement about dollar losses that says nothing about the return an LP earns per dollar supplied. A curse in rate terms needs central assets to carry higher return variance, and they carry lower.

Regressions run at the pool-month level with month fixed effects and clustering by pool. Centrality is the volume-weighted betweenness of the pool's more central leg, in logs.

| specification | v2 coefficient | v2 p | v2 MDE | v3 coefficient | v3 p | v3 MDE |
|---|---|---|---|---|---|---|
| risk-adjusted net return, month FE only | 0.0135 | 0.092 | 0.0224 | 0.0102 | 0.663 | 0.0658 |
| risk-adjusted net return, plus depth and volatility | 0.0375 | 0.000 | 0.0164 | 0.0923 | 0.000 | 0.0618 |
| probability the pool-month pays | 0.0149 | 0.000 | 0.0104 | 0.0709 | 0.000 | 0.0504 |
| log fee revenue over LVR | 0.2778 | 0.001 | 0.2263 | 0.2850 | 0.001 | 0.2346 |
| fee yield annualised | 0.0994 | 0.138 | 0.1879 | -0.0001 | 0.990 | 0.0237 |
| degree in place of betweenness | 0.0370 | 0.000 | 0.0177 | 0.0901 | 0.000 | 0.0541 |

v2 rests on 88,062 pool-months over 13,175 pools and 73 months; v3 on 11,905 pool-months over 385 pools and 62 months.

Unconditionally the coefficient is a bounded null on both venues, and the bound is tight enough to be worth stating: a curse would have to be smaller than 0.022 standard-deviation units of monthly Sharpe per log unit of centrality on v2 and 0.066 on v3 to hide inside these standard errors. Conditional on depth and volatility the sign is positive and significant, which is the opposite of the prediction. The informational version fails in the same direction: fee revenue per dollar of LVR rises with centrality, 0.278 (0.001) on v2 and 0.285 (0.001) on v3, so a more central pool collects more fee-generating flow for each dollar of adverse selection it absorbs.

The positive sign is not the mechanical channel in which a central token routes more volume and volume is the fee base, because the fee-yield regression is itself a bounded null, 0.099 (0.138) with a minimum detectable effect of 0.188 on v2 and -0.000 (0.990) with a minimum detectable effect of 0.024 on v3. What moves is the ratio, through the LVR side.

Within pools quoted against the native asset, where the quote leg is held fixed and the surviving variation is the hub status of the other leg, the v2 coefficient is 0.169 (0.000) over 66,062 pool-months and 10,859 pools. The role interactions on v2 are jointly insignificant at chi2(2) = 3.99 (0.136); on v3 they are jointly non-zero at chi2(3) = 11.62 (0.009), driven by staked-native and imported legs. The old claim that v2 role interactions identify a long-tail centrality premium is therefore withdrawn.

## Temporal bridge to vehicle succession

The annual bridge normalizes capital-days by observed days, so the partial 2026 sample cannot masquerade as capital withdrawal. On v2, native-other mean daily capital falls from 1.011 billion dollars in 2024 to 0.344 billion in 2026, but its share of all screened capital rises from 70.2% to 77.8%. Other-stable capital falls from 0.151 billion to 0.023 billion and from 10.5% to 5.1%; native-stable falls from 0.232 billion to 0.044 billion and from 16.1% to 10.0%. Over the same period, native-other profitability improves: median net APR rises from -11.1% to -0.5% and the paying share from 16.0% to 34.0%. This is the opposite temporal ordering from a migration of capital or deteriorating native-spoke returns causing the stable vehicle transition.

The v3 panel shows apparent growth in other-stable CPMM-equivalent virtual reserves, but virtual reserves change with concentration and are not deposited capital. The document already forbids comparing v3 capital levels across roles; it therefore cannot revive the mechanism through that series. Measuring deposited v3 capital would require a position-level reconstruction outside the current lock.

## What this says about the paper

The vehicle role is held by the native asset through its pairing network with the long tail, and it is exactly those pairings that lose money. Providers of native-other pools supplied 2.38 trillion dollars of capital-days, earned 0.90% annualised in fees at the median pool-day against an 11.85% LVR rate, and gave up 5.82 billion dollars in aggregate. This is a strong incidence result: trading revenue alone does not privately compensate the providers who make the long-tail network thick.

It is not the mechanism of the 2024 to 2026 vehicle succession in the evidence currently available. The admissible v2 temporal bridge moves against that interpretation, and v3 deposited capital is unmeasured. Rent incidence therefore enters the paper as a companion distributional finding, not as the explanation for why stable assets gained the intermediary role.

The centrality curse being absent sharpens this. Hub status is not what makes intermediation unprofitable; pairing with the long tail is. Conditional on depth and volatility, hub status helps.

## Threats

The largest threat is LVR measurement. Realised variance comes from the pool's own hourly marginal price, and in a constant-product pool that price only moves when someone trades, so a round trip through the fee band and price impact registers as variance that no arbitrageur harvested. The bias inflates LVR and is largest in thin pools, which is the native-other bucket carrying the headline loss. Sampling every four hours moves the median v2 net yield from -6.20% to -2.99% annualised and the paying share from 21.8% to 28.3%; using only the open-to-close move gives -1.92% and 32.7%. The sign survives the most aggressive de-biasing available here and the magnitude falls sharply, so the direction is safe and the level is not.

Second, liquidity mining is outside the accounting. A pool that loses money on fees may have paid its providers in tokens, so "does not pay" means "does not pay out of trading revenue", and the subsidy reading is exactly what an unmeasured token subsidy would also produce.

Third, the profitable role buckets rest on a thin cross-section. Native-stable is 12 token pairs on v2 and 5 on v3, imported-native is 4 and 2, native-staked-native is 3 and 4. The joint tests are significant because the pool-month panel is long, and the cross-sectional cover is what a referee will press on.

Fourth, the CEX-listing confound named in workflow 4.0 is untouched here. Hub status is close to collinear with having a deep centralised reference market, and the reference-price filter that would address it deletes exactly the long-tail tokens that identify the effect.

Fifth, per-operation LP gas is set from the repository's receipt-measured one-leg swap figure of 154,604 units, with no receipt measurement of its own, since receipts for those were not fetchable offline. Every net-return conclusion is reported across a band from half to four times that figure and none of them turns on it.

Sixth, gas is a mediator and not only a cost, as workflow 4.0 notes, because gas prices drive repositioning and repositioning is highest in hub pools. Nothing here separates the two.

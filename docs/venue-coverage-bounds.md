# Venue coverage, signed

Measured 2026-08-06 by `scripts/run_venue_coverage_bounds.py` against `data/raw/thegraph/*/`. Written because the panel's coverage statements were counts and names, and a count is not a bound. Three questions get numbers here: how much of the market each of the seven venues carries, how much of Curve's own volume the StableSwap calibration gate throws away and which side of the native-versus-stable comparison that flatters, and whether sushiswap_v3 is priceable with machinery that exists.

Exhibits: `output/exhibits/venue_volume_by_year.jsonl`, `curve_excluded_volume.jsonl`, `curve_excluded_composition.jsonl`, `curve_excluded_by_year_leg.jsonl`, `sushiswap_v3_schema_probe.jsonl`, `sushiswap_v3_pair_overlap.jsonl`, and a `_minswaps4` sensitivity pair.

## What a USD volume figure had to survive before it could be compared

This section exists because the first three passes at the table below were wrong, each time in a way that changed which venue looked biggest, and the corrections are the reason the final numbers can be read at all. No two of these seven subgraphs mean the same thing by volume. Uniswap v1's `daily` stream is `exchangeHistoricalDatas`, one record per event carrying lifetime cumulative totals, so summing `tradeVolumeEth` counts a pool's whole history once per event and put a venue that had been dead for years at 99.9% of the 2020 market; the day's flow is that field's within-day range. Balancer's `poolSnapshots.swapVolume` is lifetime cumulative on the same pattern and put Balancer at 94% of 2024. Curve's and sushiswap_v3's `dailyVolumeUSD` is a daily flow but counts both legs of every trade while the Uniswap family counts one, which doubles them: 3Crv on 2024-04-02 reports $515m against $168m summed from its own swaps, and the ratio sits near two on every pool and day checked.

Then there are the subgraph oracles, which fail on thin exotic pools and fail large. Curve's vETHETH reports a $683,750,272,316,120,064 day and reusdsfrx reports $6.9e22, which is more money than exists; Curve's GHO/USR reports a $456m day whose own swaps sum to $8; Uniswap v2 reports $1,360,770,229 for WETH/TRI against $255 of reserves, and four more meme pairs with four-figure reserves report nine-figure days. Summing any of that unscreened hands the comparison to whichever venue hosts the worst bug. So volume for the two Messari venues is rebuilt from swaps on the smaller-leg basis, which is conservative by construction and neutralises the one-sided oracle blowups, and every pool-day must clear three physical bounds: at most $5e9 of volume, at most $1e10 of value locked, and at most a thousand times its own liquidity traded in a day. The turnover rule applies only where liquidity is reported at all, because requiring value locked above zero is itself a bias: Curve reports zero for pools whose tokens its oracle cannot price, which in 2026 means the newer stablecoins, and Uniswap v4 reports NEGATIVE `tvlUSD` on its largest pools, so the tidy version of that screen was deleting $87m USDC/USDT days and the stable side of the very comparison this document bounds. The screen removes 0.10% to 0.24% of pool-days a year, and those counts are in the exhibit.

## The seven venues by volume share

Every 7th calendar day from 2018-11-02 to 2026-06-30, 400 sampled days, shares within the seven-venue panel.

| year | uniswap_v3 | uniswap_v2 | curve | uniswap_v4 | balancer | sushiswap_v2 | sushiswap_v3 |
|---|---|---|---|---|---|---|---|
| 2020 | 0.00 | 77.51 | 11.36 | 0.00 | 0.00 | 11.13 | 0.00 |
| 2021 | 37.97 | 31.28 | 12.25 | 0.00 | 1.18 | 17.32 | 0.00 |
| 2022 | 64.08 | 7.01 | 18.70 | 0.00 | 5.87 | 4.35 | 0.00 |
| 2023 | 66.81 | 9.26 | 13.88 | 0.00 | 8.80 | 1.22 | 0.03 |
| 2024 | 69.32 | 11.67 | 12.62 | 0.00 | 5.89 | 0.49 | 0.01 |
| 2025 | 60.14 | 4.77 | 10.96 | 22.12 | 1.69 | 0.31 | 0.01 |
| 2026 | 49.35 | 2.43 | 13.52 | 34.24 | 0.16 | 0.12 | 0.18 |
| pooled | 56.02 | 14.98 | 13.73 | 5.45 | 3.92 | 5.88 | 0.02 |

| venue | priced | how |
|---|---|---|
| uniswap_v2 | yes | `ddvc.pricing.v2quote`, constant product, hourly reserves |
| sushiswap_v2 | yes | same quoter, same schema |
| uniswap_v3 | yes | `ddvc.pricing.v3quote`, tick-crossing on `sqrtPriceX96` and reconstructed ticks |
| uniswap_v4 | yes | same quoter, same fields |
| curve | yes, with an exclusion gate | `ddvc.pricing.stableswap`, A calibrated per pool-day, 0.022% median error, gate measured below |
| balancer | quoter built, integration pending | `ddvc.pricing.weighted`, weighted geometric mean, 0.0000% median error on backward-rolled balances |
| sushiswap_v3 | no, and should stay that way | ruled on below |

Uniswap v1 sits outside the panel and is the laboratory of the forced-vehicle study rather than a route-cost venue. Its volume relative to the same base is 2.14% in 2020 and between 0.004% and 0.018% every year after, so nothing in the route-cost estimates turns on it.

Two readings matter for the bound. Curve holds between 11% and 19% of panel volume in every year it existed and is the second largest venue in four of those seven years and never below fourth, so its internal exclusion gate is the single largest coverage question the panel has. Balancer at 3.9% pooled and 8.8% at its 2023 peak is the largest venue with no route-cost quotes yet, which makes its integration the largest outstanding coverage gain, and its quoter already clears the validation bar.

## Curve's calibration gate, measured in volume rather than pools

A Curve pool enters the panel only when calibrating its amplification coefficient on the first half of a day's trades reproduces those trades to within `MAX_CALIBRATION_ERROR`, 1%. Pools that fail are overwhelmingly crypto-pools, which price the CryptoSwap invariant, and the honest outcome for one of those is exclusion rather than a best-fit A that minimises a 36% error. Measured on 28 pool-days spread from 2020-02-11 to 2026-04-28, using `calibrate_amp` exactly as `scripts/validate_curve_quoter.py` does, with each pool-day's volume summed from the same swaps the fit is scored on.

| year | days | pools passed | pools failed | excluded share of tested volume | untested share of all volume |
|---|---|---|---|---|---|
| 2020 | 4 | 9 | 1 | 0.00% | 0.02% |
| 2021 | 5 | 41 | 44 | 55.15% | 4.40% |
| 2022 | 4 | 45 | 76 | 46.78% | 1.61% |
| 2023 | 4 | 52 | 61 | 23.58% | 4.07% |
| 2024 | 5 | 127 | 125 | 13.58% | 2.71% |
| 2025 | 4 | 222 | 197 | 22.54% | 1.76% |
| 2026 | 2 | 125 | 84 | 16.28% | 0.27% |
| pooled | 28 | 621 | 588 | 34.22% | 2.75% |

**34.2% of the Curve volume the gate rules on is in pools it rejects**, $1.83bn of $5.36bn across the measured days. The count and the volume tell opposite stories about time: excluded pools rise from 1 across four measured 2020 days to 49 a day in 2025, while the excluded VOLUME share peaks at 55% in 2021 and falls to between 14% and 23% after 2023. Curve keeps launching small crypto-pools, and the large ones it launched in 2021 and 2022, tricrypto and the UST and MIM metapools, are the years where the omission actually costs something. A separate 2.75% of Curve volume sits in pool-days with too few trades to fit and score apart, which is neither admitted nor rejected and is reported here rather than folded into either side. Halving the fit-and-score threshold from 8 trades to 4 moves the yearly excluded shares by at most 1.3 percentage points, so none of this rests on that choice.

## Which side the Curve omission flatters

The direction comes from the excluded pools' token composition, since excluding a pool understates the best available route on exactly the legs that pool would have served. Classifying each pool's tokens by leg required going past `ddvc.asset_types`, which knows the currencies a route can be intermediated THROUGH and therefore does not know 3Crv, aDAI, yUSDC or sUSDS. Curve's stable business runs through metapools pairing a stablecoin against 3Crv, the LP claim on the DAI/USDC/USDT base pool, and through interest-bearing wrappers, so the registry lookup alone labelled MIM/3Crv, LUSD/3Crv and USDP/3Crv as volatile pairs and would have reversed the sign of this bound. The registry runs first and a symbol pass over stable derivatives runs second. The residual tokens the classifier still calls other are CVX, CRV, STG, LDO, YFI, T, tBTC and BBTC, which are volatile alt-coins and correctly not stable, and the pools holding them are labelled by their other side.

| leg the pool would have served | excluded pool-days | excluded volume | share of excluded | share of priced | excluded share of that leg |
|---|---|---|---|---|---|
| native leg (holds ETH or a staking derivative) | 374 | $1.038bn | 56.6% | 15.7% | **65.2%** |
| stable leg (all stable, including baskets and wrappers) | 119 | $0.752bn | 41.0% | 79.9% | **21.1%** |
| other volatile leg | 95 | $0.045bn | 2.4% | 4.4% | 22.2% |

The last column is the bound's sign, and it holds in every year of the sample.

| year | excluded share of native-leg volume | of stable-leg volume | of other-volatile volume |
|---|---|---|---|
| 2021 | 85.49% | 46.91% | 15.23% |
| 2022 | 68.82% | 30.21% | 50.77% |
| 2023 | 59.11% | 5.51% | 56.60% |
| 2024 | 48.24% | 0.94% | 14.38% |
| 2025 | 47.47% | 13.96% | 10.52% |
| 2026 | 60.92% | 9.04% | 20.08% |

The gate removes 65.2% of Curve's native-leg volume and 21.1% of its stable-leg volume, and the gap is at least 33 percentage points in every year and reaches 54 in 2023. The mechanism is not subtle: the WBTC/WETH/USDT tricrypto pools, crv3crypto and crvTricrypto, are $818m of the $1.83bn excluded on their own, 44.6%, and hold seven of the twelve largest excluded pool-days including the top two. They are crypto-pools by construction, they price CryptoSwap, and they are where Curve's ETH-leg depth lived. What survives the gate is Curve's stable business, 79.9% of priced Curve volume against 15.7% native. **So Curve enters the panel as a nearly pure stable-leg venue, and the omission flatters the STABLE side of the comparison.** A route through the native asset is priced without the Curve depth that was actually available to it, while a route through a stable vehicle is priced with almost all of its Curve depth intact.

## sushiswap_v3, the seventh venue

Determined from the re-fetched files, not from what the venue is called. The daily stream has 2,038 files of which 1,210 carry records, from 2023-04-05 to 2026-07-31, and every one of those 1,210 carries both `inputTokenBalances` and `inputTokenWeights`. The swaps stream carries `amountIn`, `amountOut`, `amountInUSD`, `amountOutUSD`, `tokenIn`, `tokenOut`, `blockNumber`, `logIndex` and `hash`, and carries neither `sqrtPriceX96` nor `tick`. So by field inventory it presents as a balance-and-weights venue.

It is not one, and the weights say so themselves: across every sampled day the vector takes exactly ONE distinct value, `50|50`. That is a two-token schema placeholder and not pool state, so a weighted-product quoter has nothing to read. Nor would correct weights help, because sushiswap_v3 is a concentrated-liquidity fork whose reserves are distributed across ticks: a weighted geometric mean over total balances prices a pool that does not exist, and the error is not a small one in a known direction. This is the Curve crypto-pool lesson restated, where fitting the wrong invariant returned a plausible-looking parameter and a 36% median error. And `ddvc.pricing.v3quote` cannot be pointed at it either, since it needs `sqrtPriceX96`, in-range liquidity and the tick spacing, and the Messari schema serves none of the three at any date. **The verdict is that sushiswap_v3 is not priceable with existing machinery and should be excluded rather than approximated.**

One path would work and is worth naming so the decision is a decision. `v3quote` already supports active-range snapshot quotes with an empty tick map, needing only the current price and the in-range liquidity, and both are identified from the realised trade sequence: every swap reports both amounts, the swaps are orderable by block and log index, and a concentrated-liquidity pool in range behaves as a constant-product pool with virtual reserves. That is the identification trick that recovered Curve's A and Balancer's weight ratio, applied a third time.

It is not worth building. sushiswap_v3 is **0.016% of the five priced venues' volume pooled**, peaking at 0.176% in 2026 and sitting at 0.007% to 0.036% in the years before, against route-cost effects measured in tens of basis points. Volume share alone would not settle it, because a best-of-all-venues route statistic is sensitive to a venue that is sole host of a pair however small it is, so the test was uniqueness rather than size: across 14 sampled days only **4.1% of sushiswap_v3 volume sits on token pairs no priced venue hosts that day**, and in absolute terms that unique-pair volume never exceeds $37,609 on any sampled day. A fork of Uniswap v3 hosting a handful of pools on pairs Uniswap v3 already hosts cannot move a best-route statistic.

## The signed coverage bound

Every remaining gap in the panel pushes the native-versus-stable comparison in the same direction, against the native asset, so the measured native intermediation advantage is a floor and not a point. The Curve calibration gate is the large one and it is signed hard: it removes 65.2% of Curve's native-leg volume against 21.1% of its stable-leg volume, in every year of the sample, which means routes through ETH are being costed without roughly half to five sixths of the Curve depth that was available to them while routes through a stable vehicle keep four fifths of theirs. Balancer, 3.9% of panel volume pooled and 8.8% at its peak, points the same way for the same structural reason, because it is where the 80/20 native-asset pairings sit alongside the multi-asset stable baskets and it is currently absent from both sides. sushiswap_v3 at 0.016% and 4.1% pair-unique is too small to have a sign worth arguing about, and Uniswap v1 outside the panel is smaller still. The pooled 2.75% of Curve volume in pool-days too thin to fit is the only genuinely unsigned residual, and it is an order of magnitude below the native-leg exclusion it would have to overturn. So the headline comparison, native intermediation at -0.383 against the direct route and -0.368 head-to-head against the stable numeraire, is understated by its coverage gaps rather than manufactured by them, and closing the Curve gate by pricing crypto-pools with the CryptoSwap invariant should widen the native advantage, not narrow it. That is a falsifiable prediction and the next thing to build.

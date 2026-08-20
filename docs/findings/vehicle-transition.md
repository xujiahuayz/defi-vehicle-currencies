# The intermediation transition, measured

Rebuilt 2026-08-07 by `scripts/process/build_intermediation_by_type.py` over all 2,277 days of `data/unified/`, covering 43,705,695 topology-valid intermediary routes and 47,606,817 intermediary episodes from 2020-02-11 to 2026-06-30. Asset types and dated backing regimes come from `src/ddvc/asset_types.py`. Canonical endpoint round trips are excluded. Directed token flow defines the route and intermediary role; dollar estimates only weight that object and report raw, within-2x and within-20% source-to-intermediary-to-sink support.

This asks the FX literature's dominance-transition question where the intermediary is directly observable. When exchange passes through another asset, which type carries the middle leg, how does that role differ from ordinary endpoint demand, and does the composition change when venue integration and route complexity are held fixed?

## Primary one-vehicle result

The locked vehicle-choice unit is an exact two-leg intermediary route. It gives each economic choice one vehicle and one vote, so the rise of longer paths cannot mechanically raise a type's weight. On month-days common to the endpoint years, the equal-weighted daily stable share within native plus stable rises from 16.9% in 2024 to 42.3% in 2026, a 25.4 percentage-point change with a calendar-HAC standard error of 1.05 points (Holm-adjusted p=3.36e-87). On strict within-20% value support it rises from 32.7% to 76.5%, a 43.9-point change with a 2.02-point standard error (Holm-adjusted p=4.48e-75). The corresponding log-odds changes are 1.30 and 1.98, and ratio-of-total weighting gives changes of 27.5 and 43.9 points. The broader all-episode measure below remains the network-extent extension.

## Network-extent result

Share of intermediary episodes, count-weighted:

| year | native | staked native | stable | imported | other |
|---|---:|---:|---:|---:|---:|
| 2020 | 70.5% | 0.0% | 26.1% | 0.1% | 3.2% |
| 2021 | 71.7% | 0.0% | 23.4% | 2.1% | 2.7% |
| 2022 | 59.7% | 0.2% | 33.2% | 1.4% | 5.7% |
| 2023 | 72.5% | 0.4% | 21.6% | 1.1% | 4.4% |
| 2024 | 75.3% | 0.9% | 17.2% | 1.5% | 5.1% |
| 2025 | 57.0% | 1.1% | 30.7% | 3.5% | 7.7% |
| 2026 | 42.0% | 0.9% | 41.9% | 4.9% | 10.4% |

Value share on the strict within-20% support band:

| year | native | staked native | stable | imported | other |
|---|---:|---:|---:|---:|---:|
| 2020 | 79.3% | 0.0% | 18.4% | 1.1% | 1.1% |
| 2021 | 56.8% | 0.0% | 37.7% | 2.4% | 3.0% |
| 2022 | 33.9% | 0.1% | 44.0% | 3.0% | 19.0% |
| 2023 | 40.4% | 1.2% | 36.3% | 1.1% | 21.0% |
| 2024 | 53.3% | 5.9% | 33.6% | 3.0% | 4.1% |
| 2025 | 22.8% | 2.5% | 62.6% | 9.3% | 2.8% |
| 2026 | 16.7% | 1.0% | 71.2% | 8.6% | 2.4% |

## What can and cannot be claimed

**The late rotation is large, but not monotone.** Native intermediation rebounds in 2023 and 2024 before the stable type rises sharply. Stable value exceeds native in 2022, loses that lead during 2023–24, and then leads in every quarter from 2025-Q1 through the end of the sample. Count-weighted network extent reaches parity only in 2026-H1; among native-plus-stable episodes, stable first exceeds one-half in 2026-Q2. The paper can describe a late native-to-stable rotation that survives the one-vehicle route definition, not a smooth secular transition or a long-established count dominance.

**Vehicle role and absolute scale are different objects.** On the prespecified currency perimeter in 2026, stable assets carry 46.7% of intermediary episodes against 33.2% of endpoint route demand, for a count excess-use ratio of 1.41. Their strict-support value shares are 72.9% as intermediaries and 61.1% at endpoints, for an excess-use ratio of 1.19. Native ratios are 0.77 by count and 0.68 by strict-support value. Stable assets were disproportionately likely to serve as intermediaries before they became the largest absolute category; the late result is a change in scale layered on an older vehicle role.

**Venue integration and route complexity do not absorb the rotation, and the rotation is stronger across venues.** On the 181 calendar days common to 2024 and 2026, stable share within native-plus-stable episodes rises 23.0 percentage points on single-venue routes and 30.4 points on cross-venue routes, both with p<0.001. The paired-date interaction is 7.45 points (calendar-HAC SE 1.33 points; Holm p=2.18e-7). The corresponding strict-support value changes are 35.0 and 43.2 points, with an 8.17-point interaction (SE 2.26 points; Holm p=0.00096). Count changes remain positive in every integration-by-complexity cell, ranging from 16.3 points on routes with more than two legs to 31.5 points on cross-venue two-leg routes. These strata reject opportunity-set expansion and observed leg-count composition as complete explanations.

**The value result is support-bounded.** In 2026 the within-20% band covers 71.6% of native raw intermediary value and 55.1% of stable raw intermediary value. On cross-venue routes the corresponding coverage is 66.3% and 50.6%. The lower stable coverage makes the strict-support share conservative relative to raw value, but the excluded tail remains economically material. Count-based share and excess use therefore measure frequency dominance on full topology support, while strict-value share and excess use measure economic dominance on the stated value-support perimeter. Report both dimensions, with raw and within-2x value estimates retained as visible support diagnostics.

## Backing regimes are not interchangeable

Fiat-reserve stables account for 96.1% of strict-support stable intermediary value in 2026 against 90.5% of stable endpoint value, an excess-use ratio of 1.06. On-chain-collateralized stables have a ratio of 0.06, synthetic stables 0.49, and the DAI-to-USDS transition regime 0.32. Non-USD stables have a ratio above one but less than 0.01% of stable value, so they are a diagnostic, not a mechanism result. The stable-numeraire finding is principally a fiat-reserve result; a generic “stablecoin backing” interpretation would be false.

At token level, USDT carries 36.8% and USDC 33.0% of strict-support intermediary value in 2026. Their excess-use ratios are 1.42 and 1.14, respectively. WETH carries 17.2% with a ratio of 0.69. DAI remains count-overrepresented but value-underrepresented, with ratios of 1.39 and 0.71. This is why backing must be dated and why “on-chain collateralized” replaces the older static “crypto-collateral” label.

The 2024-to-2026 change is not a single-token artifact. USDC and USDT account for 92.1% of the stable count-share increase and effectively all of the strict-support stable value-share increase. USDC's annual excess-use ratios are nearly unchanged, from 1.50 to 1.53 by count and 1.12 to 1.14 by strict-support value. USDT is the transition margin: its ratios rise from 1.06 to 1.23 and from 0.59 to 1.42. Aggregating raw numerators and denominators over rolling windows, USDT's 120-day count ratio last falls below one on 2025-02-13 and its strict-support value ratio on 2025-04-11; at the sample end they are 1.22 and 1.49. A 30-day count window briefly falls below one again in late 2025, while the 30-day value ratio stays above one after 2025-05-04. The defensible reading is a persistent transition in USDT's economic weight with noisier route-count leadership, not one common change shared by all stablecoins.

USDT also carries the stronger cross-venue transition. Within exact two-leg routes and among the native currency, USDC and USDT, its paired-date cross-venue share premium relative to single-venue routing increases by 7.59 percentage points from 2024 to 2026 by episode count (calendar-HAC SE 0.88 points; Holm p=2.70e-16). On strict-support value the differential increase is 12.00 points (SE 2.03 points; Holm p=1.23e-8). The result survives the paired daily design and log-odds transformation, so it is not generated by pooling high-volume days or by one endpoint-year level difference.

Endpoint demand does not account for USDT's vehicle transition. On the prespecified currency perimeter, USDT's intermediary share minus its endpoint-demand share rises by 2.39 percentage points from 2024 to 2026 by count (calendar-HAC SE 0.89 points; Holm p=0.0147). On strict-support value, the gap moves from -7.13 points to +8.14 points, a 15.27-point change (SE 1.50 points; Holm p=5.03e-22). The strict-value excess-use ratio rises by 0.884 log points, equivalent to a 2.42-fold multiplicative change (Holm p=2.98e-35). USDT therefore becomes more likely to occupy the middle leg even after its increasing ordinary source-or-sink use is netted out.

## Stable-bridge establishment and route reallocation

The matched-endpoint-pair decomposition pools endpoint pairs with and without a feasible stable bridge, so its small within-pair component is not an availability-conditioned substitution estimate. The bridge-establishment design instead follows 865 ordered endpoint-pair and route-scope events that previously routed through WETH, had no earlier observed stablecoin route, and first acquired persistent DAI, USDC, or USDT support on both route legs in Uniswap V2 or SushiSwap V2. Relative to the prior 30 days, stablecoin route-count share rises by 7.93 percentage points in the first month (two-way-clustered SE 1.88 points) and supported-value share rises by 3.11 points (SE 1.53 points). The corresponding route-count change over days 30--119 is 8.68 points (SE 2.57 points). Availability therefore opens a measurable stable route, but it does not reveal whether that route has enough liquidity to compete.

The continuous-depth comparison resolves that distinction. For each active ordered-endpoint-pair day, stable depth is the largest two-leg bottleneck across DAI, USDC, and USDT, and WETH depth is its own two-leg bottleneck; both use exact prior-calendar deposited capital. In the first month, 7,752 of 11,327 comparable pair-days have stable depth below one tenth of WETH depth, and stable routes carry only 2.4% of route counts in that range. Within the same bridge event, a 10 percentage point increase in the stable share of combined stable-plus-WETH depth predicts a 6.41 percentage point increase in stable route share (SE 0.70 points). When stable depth reaches at least WETH depth, stable routes carry 53.0% of first-month counts (SE 4.6 points); when it reaches twice WETH depth, they carry 69.9% (SE 2.3 points). The earlier 92.6% pooled WETH-retention statistic is therefore principally a shallow-challenger result. Competitive deposited-capital depth makes vehicle dominance contestable.

The timing comparison separates liquidity presence from subsequent use. Stable routing begins on the support date in 9.1% of the 865 events, within 30 days in 54.3%, and within 120 days in 63.4%; the median lag among eventual adopters is eight days. Of 853 events with positive event-day stable and WETH depth, 44.2% of bridges below one tenth of WETH depth are adopted within 30 days, compared with 85.1% at or above one tenth. The equal-event difference is 40.92 percentage points (two-way-clustered SE 4.83 points, p=3.49e-14); through 120 days it remains 36.15 points (SE 4.45 points, p=2.41e-13). Persistent bridge capital often predates stable routing, and relative depth predicts whether use follows. Because support and use are equilibrium outcomes, the timing does not identify provider-supply causality.

This evidence identifies liquidity formation as the proximate allocation margin, not provider reluctance or trader inertia. Deposited capital is a pool state rather than a provider decision, and it does not measure fees, gas, active concentrated depth, fragmentation, or the executable cost of a stated trade size. Existing provider-side results show gradual capital, range, and pool-footprint adjustment, which is consistent with an endogenous liquidity-coordination mechanism: expected route demand can attract capital, while deeper routes can attract demand. Identifying why liquidity providers fund a challenger slowly would additionally require provider-level capital changes conditioned on expected fees, risk, incentives, and the incumbent footprint. The 120-day persistence of entry vehicle identity remains a separate descriptive fact. Separate USDC and USDT interactions rank already-feasible stablecoin alternatives relative to DAI; they do not estimate the effect of bridge establishment.

## Corrections that changed the result

The prior exhibit treated every economic multi-leg component as intermediated, although some were direct pool splits with no intermediary token. It also allowed positive downstream dollar values to decide which topology entered the count and used inconsistent leg-level dollar fields to weight otherwise identical routes. The corrected build separates direct split-routing from sequential intermediation, retains topology-valid routes even when value is unsupported, and audits the source, every intermediary, and the sink under nested support bands. The intermediation, cross-venue and vehicle-excess families now reconcile exactly on all 2,277 dates, 43,705,695 routes, 47,606,817 episodes, and raw/2x/20% values. That correction overturns two earlier statements: count dominance has not yet become sustained, while cross-venue value migration is strong instead of null.

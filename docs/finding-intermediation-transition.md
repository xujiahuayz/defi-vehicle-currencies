# The intermediation transition, measured

Rebuilt 2026-08-07 by `scripts/build_intermediation_by_type.py` over all 2,277 days of `data/unified/`, covering 43,705,695 topology-valid intermediary routes and 47,606,817 intermediary episodes from 2020-02-11 to 2026-06-30. Asset types and dated backing regimes come from `src/ddvc/asset_types.py`. Canonical endpoint round trips are excluded. Directed token flow defines the route and intermediary role; dollar estimates only weight that object and report raw, within-2x and within-20% source-to-intermediary-to-sink support.

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

**Venue integration and route complexity do not absorb the rotation.** On the 181 calendar days common to 2024 and 2026, stable share within native-plus-stable episodes rises 23.0 percentage points on single-venue routes and 30.4 points on cross-venue routes, both with p<0.001. The corresponding strict-support value changes are 35.0 and 43.2 points. Count changes remain positive in every integration-by-complexity cell, ranging from 16.3 points on routes with more than two legs to 31.5 points on cross-venue two-leg routes. These strata reject opportunity-set expansion and observed leg-count composition as complete explanations; they do not identify aggregator causality or the economic reason a stable asset is selected.

**The value result is support-bounded.** In 2026 the within-20% band covers 71.6% of native raw intermediary value and 55.1% of stable raw intermediary value. On cross-venue routes the corresponding coverage is 66.3% and 50.6%. The lower stable coverage makes the strict-support share conservative relative to raw value, but the excluded tail remains economically material. Counts therefore stay primary, with raw, within-2x and within-20% value estimates shown together.

## Backing regimes are not interchangeable

Fiat-reserve stables account for 96.1% of strict-support stable intermediary value in 2026 against 90.5% of stable endpoint value, an excess-use ratio of 1.06. On-chain-collateralized stables have a ratio of 0.06, synthetic stables 0.49, and the DAI-to-USDS transition regime 0.32. Non-USD stables have a ratio above one but less than 0.01% of stable value, so they are a diagnostic, not a mechanism result. The stable-numeraire finding is principally a fiat-reserve result; a generic “stablecoin backing” interpretation would be false.

At token level, USDT carries 36.8% and USDC 33.0% of strict-support intermediary value in 2026. Their excess-use ratios are 1.42 and 1.14, respectively. WETH carries 17.2% with a ratio of 0.69. DAI remains count-overrepresented but value-underrepresented, with ratios of 1.39 and 0.71. This is why backing must be dated and why “on-chain collateralized” replaces the older static “crypto-collateral” label.

The 2024-to-2026 change is not a single-token artifact. USDC and USDT account for 92.1% of the stable count-share increase and effectively all of the strict-support stable value-share increase. USDC's annual excess-use ratios are nearly unchanged, from 1.50 to 1.53 by count and 1.12 to 1.14 by strict-support value. USDT is the transition margin: its ratios rise from 1.06 to 1.23 and from 0.59 to 1.42. Aggregating raw numerators and denominators over rolling windows, USDT's 120-day count ratio last falls below one on 2025-02-13 and its strict-support value ratio on 2025-04-11; at the sample end they are 1.22 and 1.49. A 30-day count window briefly falls below one again in late 2025, while the 30-day value ratio stays above one after 2025-05-04. The defensible reading is a persistent transition in USDT's economic weight with noisier route-count leadership, not one common change shared by all stablecoins.

## Corrections that changed the result

The prior exhibit treated every economic multi-leg component as intermediated, although some were direct pool splits with no intermediary token. It also allowed positive downstream dollar values to decide which topology entered the count and used inconsistent leg-level dollar fields to weight otherwise identical routes. The corrected build separates direct split-routing from sequential intermediation, retains topology-valid routes even when value is unsupported, and audits the source, every intermediary, and the sink under nested support bands. The intermediation, cross-venue and vehicle-excess families now reconcile exactly on all 2,277 dates, 43,705,695 routes, 47,606,817 episodes, and raw/2x/20% values. That correction overturns two earlier statements: count dominance has not yet become sustained, while cross-venue value migration is strong instead of null.

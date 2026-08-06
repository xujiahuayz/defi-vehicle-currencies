---
freeze_status: red
stable_passes: 0
updated: 2026-08-06
---

# Findings freeze

This is the live handoff between the research graph and prose node P. A recent paper commit does not make prose the active node. Node P stays closed until `scripts/audit_findings_freeze.py` passes and two consecutive F to G passes add no claim and retire none.

## Current claim registry

| claim | status | evidence now | blocking attack |
|---|---|---|---|
| The vehicle role moves from the native asset toward stable numéraires | provisional, primary candidate | `data/processed/vehicle_excess_use_daily.parquet`; primary scope is the four prespecified currency types, cycles excluded, direct routes included in endpoint demand. Dated backing regimes show fiat-reserve stablecoins carrying 95.82% and 96.84% of stable intermediary value in 2025 and 2026 against 89.50% and 90.29% of stable endpoint demand; RWA-mixed DAI/USDS falls from a 1.35 within-stable excess-use ratio in 2021 to 0.22 in 2026. The venue rival survives: on constant-product venues, stable excess use rises from 0.65 in 2020 to 1.31 in 2026 while native falls from 1.23 to 0.53. After canonical native-ETH/WETH identity removes 1.19 million false wrapping episodes, 42,974,290 episodes remain. From 2024 to 2026, stable rises 18.6% to 41.2% on single-venue routes and 18.9% to 46.7% on cross-venue routes; native falls 75.7% to 45.7% and 60.7% to 33.7%. Daily HAC estimates within native-plus-stable episodes put the stable-share changes at +26.9 and +33.3 percentage points. Value weighting is not uniform: the daily stable-value change is +22.1 points on single-venue routes (p<0.001) but +1.8 cross-venue (p=0.562), and the all-route change is +4.1 (p=0.128) | report forced-versus-chosen routes, conditional routing-search efficiency, and the 2023 to 2024 native rebound before fixing the shape of the transition; non-USD and small-regime cells remain diagnostics because their shares are below 1% |
| Realised routing persists while its vehicle is cost-dominated | withdrawn pending redesign | the old 27.2%, 41.3%, and 70.1% figures are route-level diagnostics; the old realised join omitted quote hour, while the definition audit requires pair-candidate-period cells | implement same-hour matching as a diagnostic, own-block timing as the validating design, continuous signed gaps, and triplet-period aggregation |
| Losing the cost advantage barely changes vehicle turnover | preliminary, cannot lead | the unconditional one-venue block sample reports a 1.17 hazard ratio | estimate conditionally on the full candidate/pair/day panel, with pair and time absorption and candidate-count controls; reject the claim if it does not survive |
| Native-long-tail vehicle liquidity is supplied at a loss | survives as a headline candidate | `docs/finding-rent-incidence.md`; two independent venue families agree and the LVR attribution is corrected | finish gas incidence by venue and candidate; separate backing regimes; state the CEX-price support bound |
| The transition is fragmentation without succession | retired | betweenness is nearly degree and HHI plus leader cannot distinguish split cells from separate monopolies | rebuild on per-cell regimes and switching order; direction is open |
| Cross-venue spillovers identify the mechanism | retired | the untreated restriction recovers most of the all-venue estimate and Merge placebos fire | no control group is identified; retain only bounded descriptive facts |

## Data and execution gates

| gate | live state |
|---|---|
| Route-cost panel | the 123,262,704-row build is pre-correction and cannot support a frozen finding; strict atomic all-shard assembly is implemented, but the panel must be repriced after the v4 contract passes |
| Uniswap v4 | canonical signed swaps are being enriched by exact record ID with fee, tick spacing, hooks and token decimals; dynamic-fee and hook-bearing pools are excluded from vanilla quote math and require a swap- and value-weighted coverage bound before rebuild |
| Vehicle extent | full-sample candidate-currency panel built over 2,277 days and 8,219,702 token-days; backing ratios are now normalized within stablecoins after the first rebuild incorrectly left non-stable candidates in the denominator. All-asset version is retained only as a diagnostic because residual contracts carry 19 to 22 percent of 2022 to 2023 intermediation |
| Routing efficiency / aggregator era | opportunity-set integration is measured on 358,027,668 clean route units: cross-venue economic multi-leg routing rises from 1.4% to 60.6% by count and 15.4% to 89.4% by value, while economic multi-leg incidence stays between 14.3% and 20.4% of all routes. Across 42,974,290 canonical intermediary episodes, the 2024 to 2026 native-to-stable count transition occurs inside both single- and cross-venue strata, with daily HAC changes of +26.9 and +33.3 percentage points, so migration into integrated routes cannot explain it alone. Value migration is concentrated in single-venue routes and is absent cross-venue. The same-hour forced/chosen matcher is implemented with exact transaction identity and nearest log notional; conditional realised-to-best efficiency, the full match and own-block validation are not yet executed |
| Panel-dependent refresher | restricted to validated support, screened-window, and arbitrage-bound diagnostics; all finding estimators remain withheld until their definitions lock |
| Prose | frozen; existing paper and deck are evidence maps, not final deliverables |

## Loop position

Current edge: `C <-> K`, with a new `C -> E -> I` routing-efficiency branch. The replacement vehicle-extent definition, dated backing attack, venue-technology rival and single-versus-cross-venue split are implemented; forced-versus-chosen and conditional search-efficiency attacks remain open. Historical v4 state and the triplet-period dominance design remain red. Any defect found here routes back to C/E; no defect is patched only in prose.

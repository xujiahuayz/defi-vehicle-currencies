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
| The vehicle role moves from the native asset toward stable numéraires | provisional, primary candidate | `data/processed/vehicle_excess_use_daily.parquet`; primary scope is the four prespecified currency types, cycles excluded, direct routes included in endpoint demand | report count weighting, venue splits, forced-versus-chosen routes, dated backing regimes, routing-search efficiency and aggregator-era heterogeneity, and the 2023 to 2024 native rebound before fixing the shape of the transition |
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
| Vehicle extent | full-sample candidate-currency panel built; all-asset version retained only as a diagnostic because residual contracts carry 19 to 22 percent of 2022 to 2023 intermediation |
| Routing efficiency / aggregator era | design now separates the cost opportunity set from realised search sophistication and treats sender labels as partial; monthly efficiency measures and within-regime transition tests are not yet executed |
| Panel-dependent refresher | restricted to validated support, screened-window, and arbitrage-bound diagnostics; all finding estimators remain withheld until their definitions lock |
| Prose | frozen; existing paper and deck are evidence maps, not final deliverables |

## Loop position

Current edge: `C <-> K`, with a new `C -> E -> I` routing-efficiency branch. The replacement vehicle-extent definition is implemented but its dated backing, forced-versus-chosen, venue, and search-efficiency attacks remain open. Historical v4 state and the triplet-period dominance design remain red. Any defect found here routes back to C/E; no defect is patched only in prose.

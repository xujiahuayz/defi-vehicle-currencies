# Router identification: what the data actually supports

Measured 2026-08-05 against `data/raw/thegraph/uniswap_v3/uniswap_v3_swaps_*.jsonl.gz`. Written because the cross-aggregator routing test depends entirely on whether router identity is recoverable, and because an early claim of mine about which field carries it required verification.

## The fields, verified against the data

The Uniswap v3 subgraph swap record carries `sender`, `origin`, and `recipient`. On 74,323 swaps from 2024-01-15:

| field | distinct values | top value's share | reading |
|---|---|---|---|
| `sender` | 241 | 42.0% | immediate caller of the pool, i.e. the router contract |
| `origin` | 36,365 | 3.9% | `tx.origin`, the signing EOA |
| `recipient` | 27,033 | | destination of the output |

`sender == origin` in **0 of 74,323 rows**. Cardinality alone settles it: 241 senders across 74k swaps cannot be end users, and the largest resolve to known router addresses. So router identity is recoverable, and the EOA lives in a separate field.

## Router concentration over time, and a caveat about coverage

Labelling `sender` against a hand-built registry of known routers:

| day | swaps | distinct senders | share captured by top-10 labelled |
|---|---|---|---|
| 2022-06-15 | 62,657 | 171 | 50.2% |
| 2024-01-15 | 74,323 | 241 | 67.7% |
| 2025-10-15 | 130,282 | 397 | 11.8% |

The 2024 snapshot is dominated by identifiable infrastructure (Universal Router 42.0%, 1inch v5 13.1%, 0x Exchange Proxy 6.4%). By late 2025 the executor population has fragmented to 397 distinct senders and a small hand registry captures almost none of it, so the label set requires systematic construction (contract-creation traces, proxy implementation resolution, function selectors, event signatures) instead of hand curation. That fragmentation is itself a descriptive fact worth reporting.

## The limitation that matters, which differs from the one I first assumed

An independent clean-room review and a direct field audit established that **`sender` identifies the executor. It does not identify the author of the routing decision.** Uniswap's Universal Router is principally an execution contract: its calldata already contains commands, split proportions, and the V2/V3 path, all computed off-chain by a separate Smart Order Router. Any wallet, frontend, or meta-aggregator can call it with a route of its own choosing. So a 42% Universal Router share is not a 42% share of routes chosen by Uniswap's algorithm.

The systems are also non-equivalent and must not be pooled: 1inch Pathfinder and 0x run off-chain routing services that emit executable calldata, while CoW is a batch auction in which competing solvers submit individual and batched solutions. Treating these as one deterministic shortest-path algorithm is wrong.

Consequences the design must respect:

- Executor attribution is available. Quote authorship is only partially recoverable, requiring trace-based classification plus an address-version registry across contract upgrades.
- Public data cannot reconstruct losing RFQ quotes, market-maker inventory, all submitted CoW solutions, or the ex-ante value of private inclusion. Aggregator opportunity sets are genuinely private in part.
- "Same pair, size, and block" fails to mean the same market state, because transactions earlier in the block move reserves and ticks. State must be reconstructed immediately before the transaction itself.
- Expected MEV exposure is not fully recoverable ex post. Realised sandwiches can be measured, though MEV protection must never become an unrestricted residual that explains away every apparent suboptimality.

## What this makes feasible

Sound, with the caveats above stated in the paper:

1. **Three-benchmark cost decomposition.** For each executed swap compute the chosen route's cost, the best route within the executor's integrated venue set, and the best route across the declared public pool universe. Then `chosen − support-optimum` measures search, split, and timing inefficiency, while `support-optimum − public-optimum` measures the cost of restricted integration. Two distinct economic quantities.
2. **Integration event study**, which identifies integration-driven routing more directly than any cross-sectional comparison: date when an aggregator adds a venue (0x publishes a changelog of liquidity-source additions), then compare affected against unaffected pairs and test whether direct routing jumps without a matching discontinuity in pool liquidity or price.
3. **Executor heterogeneity with fixed effects**, testing whether the probability of vehicle mediation stays executor-specific after conditioning on the reconstructed gas-aware cost gap, size, volatility, pool depth, pair, and block.

## Adjacent work found

"Multi-Path Routing in DEX Networks" (arXiv 2607.22540) runs repeated quote comparisons against four production aggregators and reports substantial rank variation across epochs, with limited candidate-path search modelled explicitly. A recent preprint, short of settled literature, and it works from live quotes instead of reconstructed on-chain counterfactuals. Node B's prior-art lane should confirm the boundary against it before any novelty claim is made.

The closer and binding overlap is Xi and Moallemi's ["Quantifying Sub-Optimality in Routing for Automated Market Makers"](https://arxiv.org/abs/2607.20762) (2026, forthcoming in the Financial Cryptography workshop proceedings). On 2.98 million WETH-USDC swaps, they compare realised execution with a support-constrained optimum, a full-venue optimum and a gas-aware full-venue optimum; report a 2.02-basis-point mean shortfall and $24 million aggregate; identify missed pool activation as the dominant loss margin even after gas; and show that state staleness materially enlarges measured shortfall. Their scope is parallel allocation across four Uniswap pools for one endpoint pair from March 2024 to July 2025, and they explicitly exclude intermediate tokens and multi-hop routing. Their design removes novelty from a realised-versus-optimal routing audit, the support-versus-public-opportunity decomposition, or the claim that transaction-state timing matters. This project's remaining boundary is vehicle-currency formation, rotation, and persistent replacement: whether intermediary choice and vehicle-linked liquidity change after routing maturation is held fixed across a long multi-endpoint, multi-venue panel. Routing efficiency is therefore a rival mechanism and conditioning layer, not a standalone contribution, and Xi and Moallemi must be cited wherever that conditioning framework is introduced.

---

# Cross-venue routing: integration, direct splitting, and true intermediation

Rebuilt 2026-08-07 by `scripts/build_cross_venue_routing_series.py` over all 2,277 days of `data/unified/`: 461,041,454 clean swap legs reduce to 358,027,668 economic route units. Directed token flow now separates three objects that the prior exhibit conflated: direct pool-splitting routes have multiple swap legs but no intermediary token; pure sequential routes have one linear intermediary path; mixed indirect routes combine an intermediary path with a split or join. True intermediation is the union of the latter two. Canonical endpoint round trips are excluded from economic exchange, and value is reported raw plus nested 2x and 20% route-flow support.

## Headline series

Among true intermediary routes, the count and strict-support value shares that span more than one venue are:

| year | cross-venue count | cross-venue value20 | indirect / all economic | direct split / all economic | >2 legs among multi-leg | mean legs | mean venues | round-trip share | venues |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 2.0% | 10.8% | 19.5% | 0.1% | 9.8% | 2.10 | 1.02 | 10.1% | 3 |
| 2021 | 7.3% | 26.3% | 18.6% | 1.9% | 7.3% | 2.09 | 1.09 | 11.5% | 5 |
| 2022 | 21.3% | 41.7% | 13.8% | 5.4% | 13.0% | 2.19 | 1.20 | 14.1% | 5 |
| 2023 | 21.0% | 31.4% | 8.6% | 5.0% | 9.1% | 2.15 | 1.18 | 8.3% | 6 |
| 2024 | 25.4% | 40.2% | 11.5% | 2.8% | 9.4% | 2.15 | 1.27 | 9.5% | 7 |
| 2025 | 42.7% | 70.3% | 12.1% | 2.0% | 18.6% | 2.32 | 1.49 | 18.7% | 8 |
| 2026 | 57.2% | 79.1% | 11.8% | 1.9% | 28.5% | 2.58 | 1.67 | 24.9% | 8 |

The opportunity set clearly integrates: cross-venue incidence rises nearly thirty-fold on counts, and larger strict-support routes are more likely to span venues. The extensive intermediation margin does not rise with it. True intermediary routes fall from 13.8% of economic routes in 2022 to 11.8% in 2026, while direct splitting falls from 5.4% to 1.9%. On common January-to-June support, the daily intermediation change is -2.03 percentage points (HAC SE 0.39, p<0.001). Integration therefore changes where remaining intermediary routes source liquidity without mechanically creating more vehicle use. This is consistent with improved direct-liquidity discovery; it is not an efficiency or aggregator-causality estimate.

Complexity rises after 2024 even though intermediation incidence does not. Routes above two legs reach 28.5% of economic multi-leg routes in 2026, mean legs reach 2.58, and mean venues 1.67. The old series overstated these levels by counting direct splits as intermediary paths and by letting later venue entry define much of the full-market change. Leg count remains a route-complexity measure, not a welfare measure.

## Balanced five-venue perimeter

A second series keeps complete routes whose every leg lies in the same five venue families observed throughout the V3 era. The table begins in 2022, the first full calendar year with all five active.

| year | cross-venue count | cross-venue value20 | indirect / all economic | direct split / all economic | >2 legs | mean legs | mean venues | intermediary routes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 21.3% | 41.7% | 13.8% | 5.4% | 13.0% | 2.19 | 1.20 | 4,598,794 |
| 2023 | 20.9% | 31.3% | 8.6% | 5.0% | 9.0% | 2.15 | 1.18 | 5,549,768 |
| 2024 | 25.3% | 39.5% | 11.5% | 2.8% | 9.3% | 2.15 | 1.27 | 8,656,935 |
| 2025 | 34.4% | 38.7% | 10.7% | 1.7% | 12.5% | 2.19 | 1.36 | 6,846,687 |
| 2026 | 44.0% | 34.5% | 8.4% | 1.4% | 14.6% | 2.23 | 1.45 | 2,079,434 |

Integration survives inside a fixed perimeter, with a 22.7-point count increase. The value margin moves the other way, from 41.7% to 34.5%, while intermediation incidence falls 5.35 daily percentage points on horizon-balanced support (HAC SE 0.38, p<0.001). Balanced-route coverage falls from 100.0% to 71.9%, and entrant-touching routes have 20.4% intermediation incidence in 2026. The fixed-perimeter decline is therefore a support-exit decomposition: incumbent venues become more direct while complex paths migrate toward entrants. The full-market -2.03-point result is the admissible market-wide descriptive change.

## Does the vehicle rotation occur only on integrated or complex routes?

No. Across 47,606,817 intermediary episodes, stable share within native-plus-stable episodes rises from 19.6% to 42.6% on single-venue routes and from 23.5% to 53.9% on cross-venue routes between 2024 and 2026. Horizon-balanced changes are +23.0 and +30.4 percentage points, both p<0.001. Strict-support stable value share rises from 36.3% to 71.3% single-venue and from 40.1% to 83.3% cross-venue, changes of +35.0 and +43.2 points. The cross-venue value result is broad across days: its median rises from 35.3% to 84.2%, with a 2026 interquartile range of 80.1% to 87.2%.

The count rotation also survives every integration-by-complexity cell. Stable share rises 20.7 points on single-venue two-leg routes, 31.5 cross-venue two-leg, 19.7 single-venue routes above two legs and 17.0 cross-venue routes above two legs, all p<0.001. Integration and observed complexity cannot be the complete composition explanation. They remain live conditioning variables because neither result shows whether the realised route was efficient or why one intermediary was chosen.

## Measurement corrections

The corrected build no longer uses downstream positive USD values to decide whether a route exists. Counts retain every topology-valid clean-leg component; unsupported dollar values contribute zero to value estimates and remain visible through support coverage. It also distinguishes direct pool splitting from sequential intermediation. The intermediation, routing and vehicle-excess panels reconcile exactly on all dates, route partitions, type counts and raw/2x/20% values. The upstream unified layer still excludes the tiny set of raw legs that cannot be anchored into a clean route: annual drop rates are 0.00% to 0.09%, and preserving affected partial transactions changes candidate intermediary episodes by at most nine native and three stable episodes on an audited roughly 25,000-route day. Claims therefore apply to the clean-leg route universe, not every raw log regardless of reconstructability.

## First conditional-search smoke test, and why it is not a finding

The implemented first stage is narrower than the full three-benchmark design: exact two-leg realised routes are compared with the notional-interpolated same-hour frontier through the same intermediary, and a comparison survives only when the frontier's two venue sources are contained in the route's observed venue set. It measures pool and venue search conditional on the realised vehicle. It does not measure inefficient vehicle choice, direct-path omission, split routing, gas or private liquidity.

On one day in each of 2020, 2022 and 2024, the stale panel produced 16 comparable routes out of 772 linear routes, 565/6,331 and 288/18,065. Median realised-to-same-vehicle-frontier shortfalls were -0.80%, +0.02% and -0.14%. The negative shares were 93.8%, 48.8% and 68.1%. The direct-or-alternative-vehicle frontier retains 16, 1,242 and 381 routes, with median shortfalls of -0.80%, -0.06% and -0.08%. On the 565 routes comparable under both 2022 diagnostics, the alternative-path frontier is weakly better in every case and its 90th-percentile gain over the same-vehicle frontier is 23.5 basis points, so the nesting invariant holds. A realised transaction beating a reconstructed frontier is possible when the frontier is an end-of-hour state and the transaction occurred earlier in that hour; it is also a warning about price and route reconstruction. Both diagnostics therefore remain outside the claim registry until exact pre-transaction replay bounds this error.

The block-timing instrument does not close this gate. It evaluates marginal triangle prices at V3 direct-pool swap times, not at the transaction order of the realised two-leg routes being matched above. Its first implementation also ordered only by block and included the target swap's own post-state. After strict block-log `before` ordering, 74 evenly spaced dates contain 3,636 triangle-days and 1,897,733 opportunity snapshots. The hour-boundary verdict flips 38.63% at zero fee wedge, 23.53% at 30 basis points, 13.36% at 60 and 7.42% at 100; the time placebo rises monotonically from 21.75% within one minute of the boundary to 45.22% with 30 to 60 minutes remaining. Recurrent economic triangles show 15.9% to 16.5% annual marginal-gap compression, but the horizon-balanced economic set contains 18 identities over 397 triangle-days and estimates 6.4% (p=0.126), or 5.5% (p=0.177) among the 15 identities observed at least ten dates. The significant exact-pool horizon row contains only three pool triangles and cannot carry a market-wide claim. This is a timing bound and a balanced-support null on marginal price integration. It is not route-level validation or aggregator evidence.

The route-level timing instrument now closes the narrower causal-order and amount-orientation check. It matches each leg of an actual two-leg V3 route to its raw pool and transaction log, reads both pools strictly before the transaction's first V3 swap, and compares the product of the two realised effective rates with the product of the pre-transaction marginal rates. Across 12,931 routes on 2022-06-15, 2024-06-15 and 2025-09-14, zero realised products exceed their own-state marginal products; the pooled median fee-and-impact shortfall is 55.7 basis points. The validator initially produced a 37.6% negative share because missing raw decimals were silently converted to zero, then left one negative route after the shared decimals resolver was restored because its second leg consumed 16.8 basis points more of the intermediate token than its first leg produced. Using the two legs' effective-rate product and reporting the conservation gap separately removes that definition leak. Hour-end contamination remains material: the median absolute own-to-hour movement is 140.3, 52.1 and 31.7 basis points across the three dates, and 62.8% of pooled routes move by more than 30 basis points. The apparent decline is a candidate market-maturation fact, not evidence of aggregator causality from three dates.

## Market-maturation test locked before the panel rebuild

Three public Uniswap routing releases do not support one undifferentiated "post-aggregator" break. In symmetric 60-day market-wide windows excluding each release date, the [Auto Router v1 launch on 2021-09-16](https://blog.uniswap.org/auto-router) moves the cross-venue share from 9.22% to 9.99% while indirect-route incidence falls from 23.08% to 19.91%; the cross-version release on 2021-12-16, dated in Uniswap Labs' [v2-versus-v3 LP study](https://blog.uniswap.org/SuperiorReturnsForLiquidityProviders.pdf), moves them from 9.89% to 14.74% and from 19.50% to 19.26%; and the [Universal Router release on 2022-11-17](https://blog.uniswap.org/permit2-and-universal-router) moves them from 21.40% to 18.96% and from 20.06% to 19.71%. The fixed five-venue perimeter gives the same figures in these windows because the later entrant venues do not contribute to the selected route cells. These are descriptive whole-market windows, not treated-app estimates: executor contracts do not identify route authorship, every release can coincide with market composition, and the mixed signs reject a single release-date dummy as the primary design. Dated releases remain secondary discontinuity and placebo checks after the fixed-reach realised-to-frontier estimator is valid.

The exact-state V2-family branch supplies a level bound and rejects itself as a maturation instrument. On the fixed 74-month calendar, 45,720 unique two-leg routes have a same-state direct alternative; direct returns more gross of gas on 11.7%, and on 10.5% within the 20% input/output valuation-coherence band. Receipt-calibrated historical gas raises all-in direct dominance to 31.1%, with a matched-cell IQR range of 24.8% to 35.8%. Every direct leg has year-by-venue-by-vehicle gas support; 39,290 realised vehicle routes have that same support and 6,430 use year-by-venue-by-type support. The gross sign survives reserve-support decomposition: 13.5% on 7,777 adjacent/no-liquidity states, 11.6% on 33,559 states requiring mint/burn replay and 9.7% on 4,384 bridged/no-liquidity states. Stable routes are dominated gross on 13.8% against 8.4% for native, and only 19.2% of dominated routes require a direct pool outside the realised venue set. Most measured misses are therefore within observed legacy-venue reach. The time dimension fails: comparable annual support falls from 21,907 routes in 2021 to 109 in 2026 as routing leaves the V2-family perimeter. A trend on that survivor sample cannot be called improving market efficiency.

The new hypothesis is not “aggregators made DEX efficient” as a single claim. It is a sequence of tests. First, document the expansion of the feasible routing set using venue count, cross-venue route share, hop count and route complexity, on both the full and balanced venue perimeters. Second, estimate realised-to-same-vehicle and realised-to-best-path shortfalls within fixed endpoint, vehicle, observed-reach and notional cells, so changing composition cannot manufacture convergence. Third, ask whether conditional shortfalls compress over calendar time and whether that compression is larger on complex or cross-venue paths. Fourth, add relative search performance to the pair-candidate-period vehicle-choice specification and test whether the stable-numéraire transition remains. Executor addresses can support heterogeneity, but the label “aggregator effect” is withheld unless sender/origin coverage and quote authorship are audited: the executor contract is not necessarily the system that chose the route.

The smoke run also caught a panel-key defect before a full estimator could conceal it. Native ETH and WETH had been unified to one canonical address, but endpoint display symbols remained inside the grouping key. The assembled panel consequently contained 1,372,248 duplicated quote cells among 123,262,704 rows, always multiplicity two. Canonical addresses now determine the cell, ambiguous canonical endpoints are excluded, labels are attached afterward, and the matcher refuses duplicate cells. The full corrected rebuild contains 123,384,168 unique quote cells from 2,277 shards, including 17,143,088 cells where both route forms are available and 8,437,609 involving Uniswap v4.

## The filter this required, and why the first attempt was wrong

The first run of this series produced a value-weighted number that *collapsed* in 2025-Q4 (34.1% against a count share of 59.6%) and was non-monotone in a way no economic story explained. Diagnosis: routes whose first input token equals their last output token (A to K to A) are outside the endpoint-conversion unit, yet they carried **90.5% of multi-leg dollar value** on 2025-12-06 while being only 25.6% of routes by count. This population can contain cyclic arbitrage, wash activity and other self-returning paths; the endpoint rule does not classify each route. That day is the worst of 79 sampled across the corpus, where the median day runs 12.7% by count and 21.7% by value and no other sampled day exceeds 81.8% by value, so it should be read as the extreme case that motivated the screen and not as a typical one. The daily series is in `output/exhibits/round_trip_share_by_day.jsonl`. One contributing case was six separate transactions, each running WETH into a junk token and back on a single venue, each repriced to exactly $9,113,892.

Excluding round trips removed every inversion: **0 of 18 quarters from 2022 onward now show value below count**, where that ordering was previously the contamination signature. Round trips run 0.0% to 31.7% of multi-leg routes day to day, so this is not a marginal correction.

The panel keeps `cross_venue_share_unfiltered`, `cross_venue_usd_share_unfiltered`, and `round_trip_share_of_multileg` as columns, so the contamination stays visible in the data instead of living only in this prose.

## Reporting rules that follow

- Count-weighted is primary; value-weighted is secondary and always accompanied by the round-trip share because the project's own diagnostics show that a few self-returning routes can dominate repriced value. Cong, Li, Tang and Yang 2023 supplies separate wash-trading evidence. Heimbach et al. 2024 classifies more than one quarter of gross swap volume on five named Ethereum DEXes from the Merge through 2023-10-31 as likely non-atomic arbitrage using a five-part heuristic; that conditional result does not establish value inflation in this panel.
- Do not describe the series as monotone. It trends up with real reversals in 2023.
- The wash screens in `ddc.integrity` (turnover-spike and volume-spike at K robust MADs, arbitrage-cycle detection, organic-versus-MEV decomposition) still need applying on top of the round-trip filter before any regression uses this panel.

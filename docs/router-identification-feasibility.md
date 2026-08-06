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

An independent review on a separate model family (codex-undp, 2026-08-05) established that **`sender` identifies the executor. It does not identify the author of the routing decision.** Uniswap's Universal Router is principally an execution contract: its calldata already contains commands, split proportions, and the V2/V3 path, all computed off-chain by a separate Smart Order Router. Any wallet, frontend, or meta-aggregator can call it with a route of its own choosing. So a 42% Universal Router share is not a 42% share of routes chosen by Uniswap's algorithm.

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

---

# Cross-venue routing: the full-panel series, and the filter it required

Rebuilt 2026-08-06 by `scripts/build_cross_venue_routing_series.py` over all 2,277 days of `data/unified/`: **461,041,454 clean swap legs reduced to 358,027,668 clean route units.** Only `single` and `coherent` reconstructed components enter; the earlier build admitted ambiguous components and relied on file row order for route endpoints. Enforcing the stated contract removes 10,575,177 legs and 6,297,089 route units without changing the integration pattern.

## Headline series

Of economically meaningful intermediated routes (multi-leg, first input token differing from last output token), the share spanning more than one venue:

| year | count-weighted | value-weighted | economic multi-leg / all routes | round-trip share of multi-leg (excluded) | venues active |
|---|---|---|---|---|---|
| 2020 | 1.4% | 15.4% | 18.5% | 14.1% | 3 |
| 2021 | 7.3% | 34.1% | 20.4% | 13.4% | 5 |
| 2022 | 19.1% | 49.4% | 18.8% | 15.1% | 5 |
| 2023 | 19.2% | 47.2% | 14.3% | 9.4% | 6 |
| 2024 | 28.5% | 56.3% | 15.0% | 10.9% | 7 |
| 2025 | 47.8% | 82.4% | 15.6% | 17.1% | 8 |
| 2026 | 60.6% | 89.4% | 16.6% | 20.7% | 8 |

Stated conservatively, since the series trends upward but is **not monotone**: the cross-venue share of intermediated routing rises by roughly an order of magnitude across the sample on counts, and reaches close to nine-tenths of intermediated trade value by 2026. The value-weighted series sits consistently above the count-weighted one, so larger trades span venues more than smaller ones, which is what a depth constraint implies.

The new column is the key bound on the aggregator mechanism. Economic multi-leg routes do not rise as a share of all routes: the annual ratio stays between 14.3% and 20.4%, ending at 16.6% against 18.5% in 2020. Venue and aggregator integration therefore changed where a multi-leg route sources liquidity much more than how often routes are multi-leg. This does not identify routing efficiency. The conditional test still has to hold the reachable venue/pool set fixed and ask whether realised-to-best cost gaps compress.

## Does the vehicle transition occur only on integrated routes?

No. The full split uses canonical currency identity, collapsing native ETH and WETH so wrapping is not counted as intermediation, and contains 42,974,290 episodes. From 2024 to 2026, the stable episode share rises from 18.6% to 41.2% on single-venue routes and from 18.9% to 46.7% on cross-venue routes; the native share falls from 75.7% to 45.7% and from 60.7% to 33.7%. On equal-weighted daily stable shares within native-plus-stable episodes, the corresponding changes are +26.9 percentage points (Newey-West SE 1.8) and +33.3 points (SE 1.8), both p<0.001. The parallel movement rejects the simple composition account in which stable intermediation rises only because more transactions enter the cross-venue routing regime.

The value-weighted split is less uniform and prevents a stronger claim. In 2026, stable intermediaries carry 52.1% of single-venue value against 31.0% for native, while cross-venue value remains native-led at 41.2% against 35.4%. On equal-weighted daily native-plus-stable value shares, the 2024 to 2026 stable change is +22.1 percentage points on single-venue routes (SE 1.8, p<0.001), +1.8 cross-venue (SE 3.1, p=0.562), and +4.1 overall (SE 2.7, p=0.128). Integration is therefore neither irrelevant nor a complete explanation: the count transition survives within either regime, while value migration is concentrated in single-venue routing. Conditional realised-to-best gaps are still required before calling the market more search-efficient.

## First conditional-search smoke test, and why it is not a finding

The implemented first stage is narrower than the full three-benchmark design: exact two-leg realised routes are compared with the notional-interpolated same-hour frontier through the same intermediary, and a comparison survives only when the frontier's two venue sources are contained in the route's observed venue set. It measures pool and venue search conditional on the realised vehicle. It does not measure inefficient vehicle choice, direct-path omission, split routing, gas or private liquidity.

On one day in each of 2020, 2022 and 2024, the stale panel produced 16 comparable routes out of 772 linear routes, 565/6,331 and 288/18,065. Median realised-to-same-vehicle-frontier shortfalls were -0.80%, +0.02% and -0.14%. The negative shares were 93.8%, 48.8% and 68.1%. The direct-or-alternative-vehicle frontier retains 16, 1,242 and 381 routes, with median shortfalls of -0.80%, -0.06% and -0.08%. On the 565 routes comparable under both 2022 diagnostics, the alternative-path frontier is weakly better in every case and its 90th-percentile gain over the same-vehicle frontier is 23.5 basis points, so the nesting invariant holds. A realised transaction beating a reconstructed frontier is possible when the frontier is an end-of-hour state and the transaction occurred earlier in that hour; it is also a warning about price and route reconstruction. Both diagnostics therefore remain outside the claim registry until exact pre-transaction replay bounds this error.

The repository's earlier block-timing instrument does not close this gate. It evaluates marginal triangle prices at V3 direct-pool swap times, not at the transaction order of the realised two-leg routes being matched above. Its first implementation also ordered only by block and included the target swap's own post-state. After strict block-log `before` ordering and an aligned eligibility denominator, 371 triangles contain 189,622 opportunity snapshots. The hour-boundary verdict flips 38.89% at zero fee wedge, 25.34% at 30 basis points, 16.15% at 60 and 9.43% at 100; within one minute of the boundary it flips 22.49%, not the previously reported 15.56%. This is a useful timing bound and evidence against treating hourly state as exact. It is not route-level validation.

The smoke run also caught a panel-key defect before a full estimator could conceal it. Native ETH and WETH had been unified to one canonical address, but endpoint display symbols remained inside the grouping key. The assembled panel consequently contained 1,372,248 duplicated quote cells among 123,262,704 rows, always multiplicity two. Canonical addresses now determine the cell, ambiguous canonical endpoints are excluded, labels are attached afterward, and the matcher refuses duplicate cells.

## The filter this required, and why the first attempt was wrong

The first run of this series produced a value-weighted number that *collapsed* in 2025-Q4 (34.1% against a count share of 59.6%) and was non-monotone in a way no economic story explained. Diagnosis: routes whose first input token equals their last output token (A to K to A) are atomic arbitrage or wash trading and move no value between counterparties, yet they carried **90.5% of multi-leg dollar value** on 2025-12-06 while being only 25.6% of routes by count. That day is the worst of 79 sampled across the corpus, where the median day runs 12.7% by count and 21.7% by value and no other sampled day exceeds 81.8% by value, so it should be read as the extreme case that motivated the screen and not as a typical one. The daily series is in `output/exhibits/round_trip_share_by_day.jsonl`. One contributing case was six separate transactions, each running WETH into a junk token and back on a single venue, each repriced to exactly $9,113,892.

Excluding round trips removed every inversion: **0 of 18 quarters from 2022 onward now show value below count**, where that ordering was previously the contamination signature. Round trips run 0.0% to 31.7% of multi-leg routes day to day, so this is not a marginal correction.

The panel keeps `cross_venue_share_unfiltered`, `cross_venue_usd_share_unfiltered`, and `round_trip_share_of_multileg` as columns, so the contamination stays visible in the data instead of living only in this prose.

## Reporting rules that follow

- Count-weighted is primary; value-weighted is secondary and always accompanied by the round-trip share, because volume-weighted measures are more exposed to inflation than count-based ones (a result the reference repo's `ddc.integrity` already established, with Cong, Li, Tang and Yang 2023 on wash trading and Heimbach et al. 2024 measuring over a quarter of Ethereum DEX volume as likely non-atomic arbitrage).
- Do not describe the series as monotone. It trends up with real reversals in 2023.
- The wash screens in `ddc.integrity` (turnover-spike and volume-spike at K robust MADs, arbitrage-cycle detection, organic-versus-MEV decomposition) still need applying on top of the round-trip filter before any regression uses this panel.

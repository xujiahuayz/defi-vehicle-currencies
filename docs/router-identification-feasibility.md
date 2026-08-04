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

Built 2026-08-05 by `scripts/build_cross_venue_routing_series.py` over all 2,277 days of `data/unified/`: **471,616,631 swap legs reduced to 364,324,757 routes.**

## Headline series

Of economically meaningful intermediated routes (multi-leg, first input token differing from last output token), the share spanning more than one venue:

| year | count-weighted | value-weighted | round-trip share of multi-leg (excluded) | venues active |
|---|---|---|---|---|
| 2020 | 1.2% | 11.1% | 11.8% | 3 |
| 2021 | 7.6% | 33.9% | 13.4% | 5 |
| 2022 | 19.0% | 47.0% | 15.4% | 5 |
| 2023 | 19.4% | 46.1% | 9.6% | 6 |
| 2024 | 28.8% | 59.1% | 11.0% | 7 |
| 2025 | 48.3% | 81.7% | 16.9% | 8 |
| 2026 | 61.1% | 89.1% | 20.5% | 8 |

Stated conservatively, since the quarterly series is upward-trending but **not monotone** (2023 flattens and reverses slightly, and 2026-Q2 dips against Q1): the cross-venue share of intermediated routing rises by roughly an order of magnitude across the sample on counts, and reaches close to nine-tenths of intermediated trade value by 2026. The value-weighted series sits consistently above the count-weighted one, so larger trades span venues more than smaller ones, which is what a depth constraint implies.

## The filter this required, and why the first attempt was wrong

The first run of this series produced a value-weighted number that *collapsed* in 2025-Q4 (34.1% against a count share of 59.6%) and was non-monotone in a way no economic story explained. Diagnosis: routes whose first input token equals their last output token (A to K to A) are atomic arbitrage or wash trading and move no value between counterparties, yet they carried **90.5% of multi-leg dollar value** on the worst day inspected while being only 25.6% of routes by count. One contributing case was six separate transactions, each running WETH into a junk token and back on a single venue, each repriced to exactly $9,113,892.

Excluding round trips removed every inversion: **0 of 18 quarters from 2022 onward now show value below count**, where that ordering was previously the contamination signature. Round trips run 0.0% to 31.7% of multi-leg routes day to day, so this is not a marginal correction.

The panel keeps `cross_venue_share_unfiltered`, `cross_venue_usd_share_unfiltered`, and `round_trip_share_of_multileg` as columns, so the contamination stays visible in the data instead of living only in this prose.

## Reporting rules that follow

- Count-weighted is primary; value-weighted is secondary and always accompanied by the round-trip share, because volume-weighted measures are more exposed to inflation than count-based ones (a result the reference repo's `ddc.integrity` already established, with Cong, Li, Tang and Yang 2023 on wash trading and Heimbach et al. 2024 measuring over a quarter of Ethereum DEX volume as likely non-atomic arbitrage).
- Do not describe the series as monotone. It trends up with real reversals in 2023.
- The wash screens in `ddc.integrity` (turnover-spike and volume-spike at K robust MADs, arbitrage-cycle detection, organic-versus-MEV decomposition) still need applying on top of the round-trip filter before any regression uses this panel.
